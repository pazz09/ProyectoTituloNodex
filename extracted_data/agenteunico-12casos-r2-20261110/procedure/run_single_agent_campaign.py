"""Campaña NODEX agente único: los 12 casos oficiales, una inferencia por caso y repetición.

Preparación, sin inferencia:        python tools/run_single_agent_campaign.py --repetition 1
Preflight, sin LLM y sin credencial: python tools/run_single_agent_campaign.py --repetition 1 --preflight
Ejecución autorizada:               python tools/run_single_agent_campaign.py --repetition 1 --execute

Mismas condiciones que `oficial-12casos-r1-20261028`; solo cambian la arquitectura
(`agente_unico`), `config_version` y `repeticion`. Reutiliza `campana.correr_una` (proceso
nuevo, copia desechable de `chroma_v2`, caché de IP propia, tope de 2 h, red bloqueada) y
`campana.trabajar`; el despacho a `agente_unico` se instala con `unittest.mock.patch` solo
dentro del proceso hijo. No modifica `src/`, no lee ground truth y no calcula métricas.
Un caso iniciado nunca se repite.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_official_experiment import sha, utc, write_new, validate_inputs  # noqa: E402
from tools import run_official_repetitions as oficial  # noqa: E402

ARQUITECTURA = "agente_unico"
PREFIJO = "agenteunico-12casos"
R1 = oficial.R1
R1_EXPORT = oficial.R1_EXPORT
R1_CODIGO = R1_EXPORT / "originals" / "configuration"
R1_COMMIT = "46f6a5cbcac7fe0cb291e2a8dd20bd81f052dc67"
SEED = oficial.SEED
EJECUCION = ROOT / "experiments" / "ejecucion"
COORD = EJECUCION / f"{PREFIJO}-coordinacion"
TOPE_GASTO_USD = 2.50
SALIDA_TOPE_DE_GASTO, SALIDA_DETENIDA = 5, 4
#: Archivos de orquestación propios; su hash se congela al preparar.
ORQUESTACION = ("tools/run_single_agent_campaign.py", "tools/single_agent_runner.py")
#: Paquetes que se comparan explícitamente con R1 en el informe del entorno.
PAQUETES_CLAVE = ("google-genai", "chromadb", "sentence-transformers", "transformers", "torch",
                  "tokenizers", "onnxruntime", "numpy", "langgraph", "langchain-core", "pydantic",
                  "requests", "python-dotenv")
#: Lo único que puede diferir en la configuración frente a R1.
CLAVES_FUNCIONALES = ("parametros", "parametros_ausentes", "prompts_sha256", "capa_experimental_sha256",
                      "datasets", "conocimiento", "semillas", "d11_integrado", "recursos_externos")
#: Cambios de `src/` desde el commit de R1 que se aceptan (solo agregados de Felipe, no usados aquí).
SRC_AGREGADOS_ACEPTADOS = ("src/experimentation/knowledge/rag_enriquecido.py",)
OBS_ENV = "AGENTE_UNICO_OBSERVATION_DIR"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def require(ok, message):
    if not ok:
        raise ValueError(message)


def hoy_santiago():
    return datetime.now(ZoneInfo("America/Santiago")).strftime("%Y%m%d")


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def _h(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*args):
    """Solo comandos de lectura."""
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


# --- compatibilidad con R1 -----------------------------------------------------------------------

def misma_fuente(actual: bytes, registrado: str, copia_r1: bytes | None) -> str | None:
    """Cómo coincide un archivo con R1, o `None` si su contenido difiere.

    `core.autocrlf=true` en este equipo convierte los finales de línea al hacer checkout. Se acepta
    el hash registrado en R1 sobre los bytes, con LF o con CRLF; si R1 tenía finales mezclados, se
    compara el contenido sin CR contra la copia del código guardada en el paquete de R1.
    """
    if _h(actual) == registrado:
        return "bytes"
    if _h(_lf(actual)) == registrado:
        return "contenido_lf"
    if _h(_lf(actual).replace(b"\n", b"\r\n")) == registrado:
        return "contenido_crlf"
    if copia_r1 is not None and _h(_lf(actual)) == _h(_lf(copia_r1)):
        return "contenido_igual_a_copia_r1"
    return None


def fuentes_compatibles(root=ROOT):
    registrado = oficial.r1_environment()["source_sha256"]
    modos, distintos = {}, []
    for nombre, valor in sorted(registrado.items()):
        copia = R1_CODIGO / nombre
        modo = misma_fuente((root / nombre).read_bytes(), valor,
                            copia.read_bytes() if copia.is_file() else None)
        if modo is None:
            distintos.append(nombre)
        modos[nombre] = modo
    require(not distintos, f"Código distinto de R1 (no solo saltos de línea): {distintos}")
    cambios_src = [l.split("\t")[-1] for l in git("diff", "--name-status", R1_COMMIT, "HEAD", "--", "src").splitlines() if l]
    require(all(c in SRC_AGREGADOS_ACEPTADOS for c in cambios_src),
            f"src/ cambió en Git desde el commit de R1: {cambios_src}")
    sucio_src = git("status", "--porcelain", "--", "src").splitlines()
    require(not sucio_src, f"src/ tiene cambios sin commit: {sucio_src}")
    from collections import Counter
    return dict(archivos_comparados=len(modos), por_modo=dict(Counter(modos.values())),
                solo_saltos_de_linea=sorted(n for n, m in modos.items() if m != "bytes"),
                git_head=git("rev-parse", "HEAD").strip(), git_rama=git("rev-parse", "--abbrev-ref", "HEAD").strip(),
                commit_r1=R1_COMMIT, cambios_src_desde_r1=cambios_src, src_sin_cambios_locales=True,
                core_autocrlf=git("config", "--get", "core.autocrlf").strip())


def paquetes_actuales():
    return sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions()
                  if d.metadata.get("Name"))


def comparar_entorno():
    ref = oficial.r1_environment()
    r1 = {n.lower(): v for n, v in ref["packages"]}
    actual = {n.lower(): v for n, v in paquetes_actuales()}
    nombres = sorted(set(r1) | set(actual))
    return dict(
        python_r1=ref["python"], python_actual=sys.version, python_igual=ref["python"] == sys.version,
        ejecutable_actual=sys.executable, plataforma_r1=ref["platform"], plataforma_actual=platform.platform(),
        paquetes_clave=[dict(paquete=p, r1=r1.get(p), actual=actual.get(p), igual=r1.get(p) == actual.get(p))
                        for p in PAQUETES_CLAVE],
        solo_en_r1=[(n, r1[n]) for n in nombres if n not in actual],
        solo_actual=[(n, actual[n]) for n in nombres if n not in r1],
        version_distinta=[(n, r1[n], actual[n]) for n in nombres if n in r1 and n in actual and r1[n] != actual[n]],
        decision="Se usa el .venv local (Python 3.13.5) por decisión de la responsable del 10-nov-2026; "
                 "las diferencias se registran y no se presenta el entorno como idéntico al de R1.")


def entradas_compatibles():
    filas = validate_inputs()
    referencia = oficial.r1_selection()["casos"]
    require(len(filas) == len(referencia) == 12, "El corpus debe tener doce casos")
    for fila, original in zip(filas, referencia):
        for clave in ("orden", "case_id", "dataset", "particion", "input_path", "size_bytes", "sha256"):
            require(fila[clave] == original[clave], f"Entrada u orden distintos de R1: {clave} en {original['case_id']}")
    return dict(casos=12, tamanos_y_sha256_iguales_a_r1=True, orden_igual_a_r1=True)


def embeddings_compatibles():
    inventario = read(ROOT / "experiments/knowledge/inventario_conocimiento_v2.json")
    modelo = inventario["conocimiento"]["modelo_embeddings"]
    cache = Path(os.environ.get("HF_HOME", Path.home() / ".cache/huggingface"))
    cache = cache if cache.name == "hub" else cache / "hub"
    revision = cache / ("models--sentence-transformers--" + modelo["modelo"]) / "snapshots" / modelo["revision"]
    for item in modelo["archivos"]:
        archivo = revision / item["nombre"]
        require(archivo.is_file() and archivo.stat().st_size == item["bytes"] and sha(archivo) == item["sha256"],
                f"Archivo del modelo de embeddings distinto de R1: {item['nombre']}")
    return dict(modelo=modelo["modelo"], revision=modelo["revision"], archivos_iguales_al_inventario=len(modelo["archivos"]))


def nota_archivos_borrados():
    """Archivos del commit de Felipe que no se materializan por rutas largas de Windows. No se tocan."""
    filas = [l for l in git("-c", "core.longpaths=true", "status", "--porcelain").splitlines() if l.startswith(" D ")]
    return dict(n=len(filas), archivos=[l[3:] for l in filas],
                nota="Marcados como borrados en el árbol de trabajo porque Windows no pudo crear rutas tan largas "
                     "al actualizar main2.0. No se restauran ni se tocan; no participan en esta campaña.")


def compatibilidad():
    return dict(comprobado_utc=utc(), fuentes=fuentes_compatibles(), entorno=comparar_entorno(),
                entradas=entradas_compatibles(), embeddings=embeddings_compatibles(),
                archivos_borrados_por_rutas_largas=nota_archivos_borrados())


# --- preparación ---------------------------------------------------------------------------------

def carpeta_de(repeticion):
    existentes = sorted(EJECUCION.glob(f"{PREFIJO}-r{repeticion}-*/selection.json"))
    require(len(existentes) <= 1, f"Hay varias campañas de agente único para la repetición {repeticion}")
    version = existentes[0].parent.name if existentes else f"{PREFIJO}-r{repeticion}-{hoy_santiago()}"
    return version, EJECUCION / version


def versiones_existentes():
    return sorted(p.parent.name for p in EJECUCION.glob(f"{PREFIJO}-r[123]-*/selection.json"))


def filas_de(version, repeticion):
    from src.experimentation.runtime.identidad import IdentidadCorrida
    filas = copy.deepcopy(oficial.r1_selection()["casos"])
    for fila in filas:
        fila.update(IdentidadCorrida(fila["case_id"], fila["dataset"], ARQUITECTURA, repeticion, version).to_dict())
    return filas


def configuracion_de(version, repeticion):
    import google.genai
    congelada = copy.deepcopy(oficial.r1_configuration())
    congelada.update(
        config_version=version, congelada_utc=utc(), arquitectura=ARQUITECTURA, repeticion=repeticion,
        referencia_r1=R1,
        git=dict(commit=git("rev-parse", "HEAD").strip(), rama=git("rev-parse", "--abbrev-ref", "HEAD").strip(),
                 arbol_limpio=not git("-c", "core.longpaths=true", "status", "--porcelain").strip(),
                 src_sin_cambios_locales=not git("status", "--porcelain", "--", "src").strip()),
        entorno=dict(python=platform.python_version(), plataforma=platform.platform()),
        entorno_r1=oficial.r1_configuration().get("entorno"),
        agente_unico=dict(
            implementacion="src/single_agent.py::analizar_lote_agente_unico (sin modificar)",
            recuperacion_mitre="siempre, una vez por caso: ltm.retrieve_attack_techniques("
                               "describir_lote_en_prosa(resumen_logs)) sobre la copia de chroma_v2 del caso",
            patrones_historicos=False, reputacion_ip=False, tope_gasto_usd=TOPE_GASTO_USD,
            orquestacion_sha256={n: sha(ROOT / n) for n in ORQUESTACION}))
    congelada["generacion"] = dict(congelada["generacion"], sdk_google_genai=google.genai.__version__)
    congelada["generacion_r1_sdk_google_genai"] = oficial.r1_configuration()["generacion"].get("sdk_google_genai")
    congelada.pop("huella", None)
    congelada["huella"] = hashlib.sha256(json.dumps({k: v for k, v in congelada.items() if k != "congelada_utc"},
                                                    sort_keys=True, default=str).encode()).hexdigest()
    return congelada


def preparar(repeticion):
    from dotenv import dotenv_values
    from src.experimentation import campana

    version, carpeta = carpeta_de(repeticion)
    compatible = compatibilidad()
    if repeticion > 1:
        # Mismo entorno, entradas y semilla que la R1 del agente único.
        previas = [v for v in versiones_existentes() if v.startswith(f"{PREFIJO}-r1-")]
        require(len(previas) == 1, "Falta la R1 del agente único")
        ambiente_r1 = read(EJECUCION / previas[0] / "environment.json")
        require(ambiente_r1["packages"] == [list(p) for p in paquetes_actuales()] and ambiente_r1["python"] == sys.version,
                "Python o paquetes distintos de la R1 del agente único")
        require(read(EJECUCION / previas[0] / "selection.json")["casos"][0]["sha256"]
                == oficial.r1_selection()["casos"][0]["sha256"], "Selección distinta")
    filas = filas_de(version, repeticion)
    seleccion = dict(copy.deepcopy(oficial.r1_selection()), config_version=version, repeticiones=1,
                     repeticion=repeticion, arquitectura=ARQUITECTURA, casos=filas, referencia_r1=R1)
    destino = carpeta / "selection.json"
    if destino.exists():
        require(read(destino) == seleccion, "La selección congelada no coincide")
    else:
        write_new(destino, seleccion)
    ruta_config = campana.ruta_configuracion(ROOT, version)
    if not ruta_config.exists():
        write_new(ruta_config, configuracion_de(version, repeticion))
    congelada = read(ruta_config)
    for clave in CLAVES_FUNCIONALES:
        require(congelada[clave] == oficial.r1_configuration()[clave], f"Configuración funcional distinta de R1: {clave}")
    for nombre, valor in congelada["agente_unico"]["orquestacion_sha256"].items():
        require(sha(ROOT / nombre) == valor, f"Orquestación cambió desde la preparación: {nombre}")
    efectiva = campana.verificar_configuracion(ROOT, ROOT / ".env", congelada)
    require(efectiva["coincide"], f"Configuración efectiva distinta de la congelada: {efectiva['distintos']}")
    base = {**os.environ, **{k: v for k, v in dotenv_values(ROOT / ".env").items() if v is not None}}
    require(base.get("GEMINI_API_KEY") or base.get("GOOGLE_API_KEY"), "Falta credencial Gemini")
    if not (carpeta / "compatibility.json").exists():
        write_new(carpeta / "compatibility.json", compatible)
    ambiente = carpeta / "environment.json"
    if not ambiente.exists():
        archivos = sorted(p for d in ("src", "tools") for p in (ROOT / d).rglob("*.py"))
        archivos += [ROOT / "requirements.txt", ROOT / "constraints.txt"]
        write_new(ambiente, dict(
            created_utc=utc(), python=sys.version, executable=sys.executable, platform=platform.platform(),
            packages=paquetes_actuales(),
            source_sha256={p.relative_to(ROOT).as_posix(): sha(p) for p in archivos},
            source_sha256_lf={p.relative_to(ROOT).as_posix(): _h(_lf(p.read_bytes())) for p in archivos},
            orchestration_sha256={n: sha(ROOT / n) for n in ORQUESTACION},
            effective_configuration=efectiva, referencia_r1=R1, compatibility=compatible,
            policy=dict(attempts_per_case=1, repeated_failed_runs=False, external=campana.RECURSOS_EXTERNOS,
                        timeout_seconds=campana.TOPE_CORRIDA_S, fallback=False,
                        isolation="campana.correr_una sin modificación; despacho a agente_unico solo en el hijo"),
            nota="Python 3.13.5 del .venv local; R1 usó 3.12.14. Diferencias de paquetes en compatibility.json."))
    else:
        registrado = read(ambiente)
        for nombre, valor in registrado["source_sha256"].items():
            require(sha(ROOT / nombre) == valor, f"El código cambió desde la preparación: {nombre}")
    return version, carpeta, filas, base, congelada


# --- preflight sin LLM ---------------------------------------------------------------------------

def candidatos_nodex_r1():
    """Candidatos que recuperó NODEX en R1 (lo que llegó a su estado), por caso."""
    filas = {}
    for linea in (R1_EXPORT / "mitre" / "retrieved_candidates.jsonl").read_text(encoding="utf-8").splitlines():
        fila = json.loads(linea)
        # Cada caso trae dos proyecciones: el estado crudo (lo que recibió NODEX, con similitud) y la
        # salida adaptada (`/salida/_meta/mitre_candidates`, sin similitud). Se usa solo la primera.
        if fila.get("source_json_pointer") != "/estado_crudo/tecnicas_mitre":
            continue
        require(fila["case_id"] not in filas, f"Candidatos NODEX duplicados para {fila['case_id']}")
        filas[fila["case_id"]] =[dict(technique_id=(c.get("meta") or {}).get("technique_id"),
                                       similitud=c.get("similitud")) for c in (fila.get("value") or [])]
    return filas


def comparar_con_nodex(propios, nodex):
    """IDs en orden y diferencia máxima de similitud (las similitudes vienen redondeadas a 3 decimales)."""
    ids_p, ids_n = [c["technique_id"] for c in propios], [c["technique_id"] for c in nodex]
    diferencias = [abs(a["similitud"] - b["similitud"]) for a, b in zip(propios, nodex)] if ids_p == ids_n else []
    return dict(ids_iguales=ids_p == ids_n, diferencia_maxima_similitud=max(diferencias) if diferencias else (0.0 if ids_p == ids_n else None))


def preflight_caso(dataset, case_id, ltm=None):
    """En el proceso hijo: preprocesamiento, recuperación y prompt, con `llm_json` reemplazado por un stub.

    El proceso se lanza SIN credencial: aunque el stub fallara, una llamada real no podría salir.
    """
    import tools.single_agent_runner as runner
    import src.single_agent as single

    contenido = runner.cargar_caso(ROOT, dataset, "evaluacion", case_id)
    recuperacion = runner.recuperar_candidatos(contenido, ltm)
    original = single.llm_json

    def stub(prompt, system=None, *args, **kwargs):
        return {"error": "preflight_sin_llm"}

    single.llm_json = stub
    observacion = runner.Observacion().instalar()
    try:
        runner.ejecutar(contenido, f"preflight__{case_id}", recuperacion["candidatos"])
    finally:
        observacion.desinstalar()
        single.llm_json = original
    p = observacion.prompts[0]
    return dict(case_id=case_id, dataset=dataset, candidatos=runner.resumen_candidatos(recuperacion["candidatos"]),
                consulta=recuperacion["consulta"], consulta_sha256=recuperacion["consulta_sha256"],
                consulta_interna_igual=all(c == recuperacion["consulta"] for c in observacion.consultas_internas),
                llegada_al_prompt=runner.candidatos_en_prompt(p["prompt"], recuperacion["candidatos"]),
                prompt_chars=len(p["prompt"]), system_chars=len(p["system"] or ""),
                candidatos_chars=len(json.dumps(recuperacion["candidatos"], ensure_ascii=False)),
                segundos_recuperacion_mitre=recuperacion["segundos_recuperacion_mitre"],
                llamadas_reales_al_modelo=0)


def preflight(repeticion):
    from src.experimentation import campana
    version, carpeta, filas, base, congelada = preparar(repeticion)
    estado_semilla = oficial.clean_rag()
    # Vacías, no ausentes: `src/config.py` llama a `load_dotenv()` al importarse y, si la variable no
    # existe, la vuelve a cargar desde `.env`. `load_dotenv` no sobrescribe una variable ya definida.
    sin_credencial = dict(base, GEMINI_API_KEY="", GOOGLE_API_KEY="")
    nodex = candidatos_nodex_r1()
    resultados = []
    for fila in filas:
        with tempfile.TemporaryDirectory(prefix="agenteunico-preflight-", ignore_cleanup_errors=True) as tmp:
            copia = Path(tmp) / "chroma"
            shutil.copytree(SEED, copia)
            require(oficial.inspect_chroma(copia)["files"] == estado_semilla["files"], "Copia distinta de la semilla")
            entorno = campana.entorno_de_la_corrida(sin_credencial, congelada, copia, Path(tmp) / "ip.json")
            r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--preflight-case",
                                fila["dataset"], fila["case_id"]], cwd=ROOT, env=entorno, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=900)
            linea = next((l for l in r.stdout.splitlines() if l.startswith("PREFLIGHT_JSON:")), None)
            require(r.returncode == 0 and linea, f"Preflight falló en {fila['case_id']}: {(r.stderr or r.stdout)[-1500:]}")
            dato = json.loads(linea[len("PREFLIGHT_JSON:"):])
        dato.update(orden=fila["orden"], nodex_r1=nodex.get(fila["case_id"]),
                    comparacion_nodex_r1=comparar_con_nodex(dato["candidatos"], nodex.get(fila["case_id"]) or [])
                    if nodex.get(fila["case_id"]) else None)
        resultados.append(dato)
        print(f"[preflight {fila['orden']}/12] {fila['case_id']}: "
              f"{[c['technique_id'] for c in dato['candidatos']]}", flush=True)
    require(tree_igual(estado_semilla), "La semilla cambió durante el preflight")
    registro = dict(creado_utc=utc(), config_version=version, llamadas_reales_al_modelo=0,
                    credencial_en_el_proceso_hijo=False, casos=resultados,
                    semilla_intacta=True)
    return registro


def tree_igual(estado_semilla):
    return oficial.tree_hashes(SEED) == estado_semilla["files"]


# --- gasto --------------------------------------------------------------------------------------

def gasto_campana(raiz=ROOT, fecha=None):
    """Gasto real de TODAS las repeticiones del agente único, recalculado desde la telemetría."""
    from src.experimentation import estimacion, presupuesto
    fecha = fecha or datetime.now(ZoneInfo("America/Santiago")).strftime("%Y-%m-%d")
    precios = estimacion.leer_precios(raiz)
    total, por_dataset = 0.0, {}
    vigencia = estimacion.precio_vigente(precios, "gemini-3.8-flash", fecha)
    require(vigencia is not None, f"Sin precio vigente para {fecha}")
    for version in sorted(p.parent.name for p in (raiz / "experiments/ejecucion").glob(f"{PREFIJO}-r[123]-*/selection.json")):
        for datos in presupuesto._telemetrias(raiz, version):
            costo = presupuesto.costo_de_telemetria(datos.get("telemetria"), vigencia)["usd"]
            total += costo
            por_dataset.setdefault(datos["dataset"], []).append(costo)
    return dict(usd=round(total, 6), por_dataset=por_dataset, fecha_de_precios=fecha)


def costo_maximo_siguiente(dataset, gasto, previo):
    """Máximo observado del dataset en la campaña; si aún no hay, la cota previa del preflight."""
    observados = gasto["por_dataset"].get(dataset) or []
    cota_previa = (previo or {}).get(dataset)
    require(observados or cota_previa is not None, f"Sin costo máximo para {dataset}: falta presupuesto.json")
    return max(observados + ([cota_previa] if cota_previa is not None else []))


def permitido_por_gasto(dataset, tope, gasto, previo):
    maximo = costo_maximo_siguiente(dataset, gasto, previo)
    return gasto["usd"] + maximo <= tope, maximo


# --- ejecución ----------------------------------------------------------------------------------

def comando_del_worker(comando):
    """Cambia `-m src.experimentation.campana --trabajar <7 args>` por el worker propio (7 args)."""
    argumentos = comando[comando.index("--trabajar") + 1:]
    require(len(argumentos) == 7, f"El lanzador original entregó {len(argumentos)} argumentos, no 7")
    return [sys.executable, str(Path(__file__).resolve()), "--worker", *argumentos]


def caso_aislado(fila, carpeta, base, congelada, estado_semilla):
    from src.experimentation import campana
    original = campana.ejecutar_hijo
    registro = {k: fila[k] for k in ("case_id", "dataset", "run_id", "arquitectura", "repeticion", "config_version")}

    def observar(comando, cwd, entorno, tope):
        copia = Path(entorno["CHROMA_PATH"])
        antes = oficial.inspect_chroma(copia)
        require(antes["files"] == estado_semilla["files"] and antes["dynamic_empty"], "La copia no coincide con la semilla")
        require(copia.resolve() != SEED.resolve() and not Path(entorno["IP_CACHE_PATH"]).exists(), "Caso no aislado")
        entorno = dict(entorno, **{OBS_ENV: str(carpeta)})
        nuevo = comando_del_worker(comando)
        registro.update(checked_utc=utc(), chroma_path=str(copia), cache_path=entorno["IP_CACHE_PATH"],
                        cache_absent_before_inference=True, initial_chroma=antes, independent_working_copy=True,
                        subprocess_command=nuevo, expected_model=congelada["parametros"]["LLM_MODEL_PRIMARY"])
        resultado = original(nuevo, cwd, entorno, tope)
        registro["final_chroma"] = oficial.inspect_chroma(copia)
        if not (carpeta / f"{fila['run_id']}.worker.json").exists():
            (carpeta / f"{fila['run_id']}.prelaunch.stdout.txt").write_text(resultado[1], encoding="utf-8")
            (carpeta / f"{fila['run_id']}.prelaunch.stderr.txt").write_text(resultado[2], encoding="utf-8")
            raise RuntimeError("El proceso hijo no llegó a iniciar el worker; se detiene sin lanzar más casos")
        return resultado

    try:
        with patch.object(campana, "ejecutar_hijo", observar):
            resultado = campana.correr_una(ROOT, base, congelada, fila, "evaluacion", fila["config_version"], carpeta)
    finally:
        registro["seed_unchanged_after_case"] = tree_igual(estado_semilla)
        registro["working_copy_discarded"] = bool(registro.get("chroma_path")) and not Path(registro["chroma_path"]).exists()
        write_new(carpeta / f"{fila['run_id']}.isolation.json", registro)
    require(registro["seed_unchanged_after_case"], "La semilla se modificó durante el caso")
    return resultado


def verificar_modelo(fila, congelada, raiz=ROOT):
    """Cada llamada sin error debe pedir y recibir gemini-3.8-flash. Devuelve un problema o None."""
    ruta = raiz / "experiments" / "telemetry" / fila["dataset"] / f"{fila['run_id']}.json"
    if not ruta.exists():
        return None
    for llamada in read(ruta)["telemetria"].get("llm_calls") or []:
        if llamada.get("model") != congelada["parametros"]["LLM_MODEL_PRIMARY"]:
            return f"Modelo pedido distinto: {llamada.get('model')}"
        if not llamada.get("error") and llamada.get("model_version") != "gemini-3.8-flash":
            return f"Versión efectiva distinta: {llamada.get('model_version')}"
    return None


def correr_casos(filas, carpeta, lanzar, tope, previo, congelada, gasto=gasto_campana, log=print):
    """Bucle de la repetición. `lanzar(fila)` corre un caso. Nunca repite un caso iniciado."""
    infra = 0
    for fila in filas:
        iniciado = carpeta / f"{fila['run_id']}.started.json"
        resultado = carpeta / f"{fila['run_id']}.result.json"
        if iniciado.exists():
            log(f"Omitido sin repetir (ya iniciado): {fila['case_id']}"
                + ("" if resultado.exists() else " — intento previo SIN resultado: requiere inspección manual"))
            continue
        require(not resultado.exists(), f"Existe resultado sin marcador de inicio: {resultado}")
        actual = gasto()
        ok, maximo = permitido_por_gasto(fila["dataset"], tope, actual, previo)
        if not ok:
            write_new(carpeta / f"detenido_por_gasto_{fila['orden']:02d}.json",
                      dict(utc=utc(), caso=fila["case_id"], gasto_usd=actual["usd"], costo_maximo_siguiente=maximo, tope_usd=tope))
            log(f"Detenido antes de {fila['case_id']}: gasto {actual['usd']:.4f} + máximo {maximo:.4f} > tope {tope:.2f}")
            return SALIDA_TOPE_DE_GASTO
        comienzo, reloj = utc(), time.perf_counter()
        write_new(iniciado, dict(fila, process_started_utc=comienzo, gasto_previo_usd=actual["usd"]))
        log(f"[{fila['orden']}/12] Iniciando {fila['case_id']}")
        try:
            salida = lanzar(fila)
        except Exception as error:  # noqa: BLE001
            write_new(resultado, dict(fila, estado="error_lanzador", error=f"{type(error).__name__}: {error}",
                                      infraestructura=True, process_started_utc=comienzo, process_finished_utc=utc(),
                                      wall_seconds=time.perf_counter() - reloj))
            log(f"Detenido: error del lanzador en {fila['case_id']}. No se reintenta.")
            return SALIDA_DETENIDA
        salida.update(config_version=fila["config_version"], process_started_utc=comienzo,
                      process_finished_utc=utc(), wall_seconds=time.perf_counter() - reloj)
        write_new(resultado, salida)
        log(f"[{fila['orden']}/12] {fila['case_id']}: {salida.get('estado')} ({salida['wall_seconds']:.1f} s)")
        problema = verificar_modelo(fila, congelada)
        if problema:
            log(f"Detenido: {problema}")
            return SALIDA_DETENIDA
        infra = infra + 1 if salida.get("infraestructura") else 0
        if infra >= 3:
            log("Detenido: tres fallas de infraestructura seguidas. No se reintenta ningún caso.")
            return SALIDA_DETENIDA
    return 0


def ejecutar(repeticion, tope):
    version, carpeta, filas, base, congelada = preparar(repeticion)
    previo_path = COORD / "presupuesto.json"
    require(previo_path.exists(), "Falta presupuesto.json (Fase 2): no se ejecuta sin cota de costo previa")
    previo = read(previo_path)["costo_maximo_previo_por_dataset"]
    if repeticion > 1:
        anterior = [v for v in versiones_existentes() if v.startswith(f"{PREFIJO}-r{repeticion - 1}-")]
        require(len(anterior) == 1 and len(list((EJECUCION / anterior[0]).glob("*.result.json"))) == 12,
                "La repetición anterior no terminó sus 12 casos")
    estado_semilla = oficial.clean_rag()
    inicial = carpeta / "rag_initial.json"
    if not inicial.exists():
        write_new(inicial, estado_semilla)
    require(read(inicial)["files"] == estado_semilla["files"], "La semilla cambió respecto del inicio de la repetición")
    log = lambda m: print(m, flush=True)  # noqa: E731

    def lanzar(fila):
        entradas_compatibles()
        return caso_aislado(fila, carpeta, base, congelada, estado_semilla)

    codigo = correr_casos(filas, carpeta, lanzar, tope, previo, congelada, log=log)
    return codigo


# --- proceso hijo -------------------------------------------------------------------------------

def worker(argumentos):
    from functools import partial
    from src.experimentation import campana, orquestador
    import tools.single_agent_runner as runner

    dataset, case_id, arquitectura, repeticion, version, particion, destino = argumentos
    require(arquitectura == ARQUITECTURA and particion == "evaluacion", "Worker solo para agente_unico en evaluación")
    carpeta = Path(os.environ[OBS_ENV])
    from src.experimentation.runtime.identidad import IdentidadCorrida
    identidad = IdentidadCorrida(case_id, dataset, arquitectura, int(repeticion), version)
    write_new(carpeta / f"{identidad.run_id}.worker.json",
              dict(identidad.to_dict(), worker_started_utc=utc(), pid=os.getpid(), python=sys.version,
                   chroma_path=os.environ.get("CHROMA_PATH"), ip_cache_path=os.environ.get("IP_CACHE_PATH")))
    despacho = partial(runner.correr_una_agente_unico, carpeta_observacion=carpeta)
    with patch.object(orquestador, "_correr_una", despacho):
        return campana.trabajar(ROOT, dataset, case_id, arquitectura, int(repeticion), version, particion, Path(destino))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetition", type=int, choices=(1, 2, 3))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--tope-gasto", type=float, default=TOPE_GASTO_USD)
    parser.add_argument("--worker", nargs=7)
    parser.add_argument("--preflight-case", nargs=2, metavar=("DATASET", "CASE_ID"))
    args = parser.parse_args(argv)
    if args.worker:
        return worker(args.worker)
    if args.preflight_case:
        sin_clave = lambda: not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))  # noqa: E731
        require(sin_clave(), "El preflight se ejecuta sin credencial")
        import src.config as configuracion
        from src.config import CHROMA_PATH
        require(sin_clave() and not configuracion.GEMINI_API_KEY,
                "src.config cargó una credencial: el preflight debe correr sin ella")
        require(Path(CHROMA_PATH).resolve() != SEED.resolve(), "El preflight debe usar una copia de la semilla")
        print("PREFLIGHT_JSON:" + json.dumps(preflight_caso(*args.preflight_case), ensure_ascii=False), flush=True)
        return 0
    if not args.repetition:
        parser.error("--repetition es obligatorio")
    if args.preflight:
        registro = preflight(args.repetition)
        COORD.mkdir(parents=True, exist_ok=True)
        destino = COORD / f"preflight_r{args.repetition}_{hoy_santiago()}.json"
        write_new(destino, registro)
        print(f"Preflight sin LLM guardado en {destino.relative_to(ROOT).as_posix()}", flush=True)
        return 0
    if args.execute:
        return ejecutar(args.repetition, args.tope_gasto)
    version, carpeta, filas, _base, _congelada = preparar(args.repetition)
    print(f"Preparados 12 casos, agente único, repetición {args.repetition}: {version}. Sin inferencia.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
