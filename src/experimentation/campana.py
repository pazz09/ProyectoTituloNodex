"""Lanzador de la campaña (piloto y, más adelante, campaña final).

    python -m src.experimentation.campana --config-version V                    # plan, no corre
    python -m src.experimentation.campana --config-version V --env .env --ejecutar --etapa 1

## Reglas del lanzador

- **Sin `--ejecutar` solo muestra el plan** (corridas, referencia de llamadas, estimación
  de tokens y qué configuración congelada se usaría). No hace ninguna llamada.
- **La configuración manda.** Cada corrida corre en un proceso propio cuyo entorno se
  arma a partir de la configuración CONGELADA (modelo, respaldo apagado, temperatura...),
  no de lo que tenga el `.env`. El `.env` solo aporta las credenciales; no se copia.
  Antes de ejecutar se comprueba que el código es el congelado (mismo commit, `src/`
  limpio).
- **Escalonado.** Etapa 1: UN solo caso con las tres arquitecturas, y un informe
  (credencial, modelo efectivo, fallback, tokens, tiempo, llamadas, errores). Etapa 2: el
  resto. Si la etapa 1 no sale limpia, termina con código 3 y NO sigue.
- **Tope de 2 horas por corrida** (se mata el ÁRBOL de procesos). **Tres fallas de
  infraestructura seguidas** (503, 429, timeout, tope) detienen la campaña: código 4.
- **Tope de gasto acumulado** (`--tope-gasto`, por omisión USD 5,00). El gasto se RECALCULA antes
  de cada corrida con los tokens medidos de todo lo guardado de la configuración y la tabla de
  precios vigente ese día: no hay contador aparte que pueda perderse al reanudar. Si el gasto más el
  costo MÁXIMO observado de la celda de la corrida siguiente superaría el tope, se detiene antes de
  lanzarla (código 5). La parada es reanudable: las corridas guardadas no se repiten. Una corrida
  fallida cuyas llamadas no informaron tokens deja un costo PARCIAL (un piso): se informa aparte.
  El gasto acumulado se informa por corrida y por etapa (`gasto.json`).
- **JSON válido de NODEX:** cada corrida de NODEX deja `<run_id>.llm_json.json` con las respuestas
  de `llm_json()` y cuántas fueron inválidas.
- **Aislamiento.** ChromaDB y la caché de IP son copias temporales por corrida; las
  llamadas HTTP de `requests` (NVD, AbuseIPDB) se bloquean con respaldo local y **cada
  intento de consulta queda registrado por corrida** (herramienta, parámetros, si el
  respaldo respondió). La política de esas consultas para la campaña final sigue
  PENDIENTE.
- **No lee `ground_truth/`.** La evaluación es otro paso (`evaluacion.py`).
- Los resultados del piloto son de **depuración**: no son reportables.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from src.experimentation import estimacion, orquestador
from src.experimentation.comparacion_modelos import ejecutar_hijo
from src.experimentation.knowledge.aislamiento import configuracion_experimental
from src.experimentation.runtime import persistencia
from src.experimentation.runtime.identidad import IdentidadCorrida

#: Lo que se congela para el piloto: modelo, respaldo apagado y temperatura 0.
CONFIGURACION_PILOTO = {
    "LLM_MODEL_PRIMARY": "gemini-3.8-flash",
    "LLM_MODEL_FALLBACK": "gemini-3.8-flash",     # sin efecto con el respaldo apagado
    "LLM_SIN_RESPALDO": "true",
    "TEMPERATURE": "0",
}
ARQUITECTURAS_PILOTO = ("nodex_multiagente", "baseline_reglas", "gemini_externo")

TOPE_CORRIDA_S = 7200
MAX_FALLAS_DE_INFRAESTRUCTURA_SEGUIDAS = 3
ESTADOS_DE_INFRAESTRUCTURA = ("error_api", "timeout")

#: Códigos de salida.
SALIDA_OK, SALIDA_ETAPA_NO_LIMPIA, SALIDA_FALLAS_SEGUIDAS = 0, 3, 4
SALIDA_TOPE_DE_GASTO = 5
SALIDA_ETAPA_B_NO_AUTORIZADA = 6

#: Etapas de la campaña final. A = repetición 1 de todos los casos (NODEX, Gemini directo y baseline,
#: BGL primero y UWF después). B = repetición 2 (NODEX y Gemini directo). B solo corre si
#: «gasto real de A × 2» no supera el tope de gasto; si lo supera, se detiene y se informa.
ETAPAS_DE_CAMPANA = {"A": 1, "B": 2}
FACTOR_PROYECCION_ETAPA_B = 2

#: Tope de gasto acumulado de la campaña (USD). El presupuesto total es 6,00; el resto es el margen.
TOPE_GASTO_USD = 5.00

GENERACION = {
    "api": "generateContent (google-genai, Models.generate_content)",
    "response_mime_type": "application/json",
    "thinking_level": "no se envía: rige el valor por omisión del modelo",
    "respaldo_de_modelo": "apagado (LLM_SIN_RESPALDO=true)",
    "reintentos_con_espera": "activos sobre el mismo modelo (503, 429 por minuto)",
    "gemini_directo": "hereda el mismo modelo y temperatura que NODEX",
}
RECURSOS_EXTERNOS = {
    "nvd": "bloqueado con respaldo local; cada intento de consulta se registra por corrida",
    "abuseipdb": "bloqueado con respaldo local; cada intento de consulta se registra por corrida",
    "politica_campana_final": (
        "DECISIÓN PENDIENTE: consultas reales o respaldo local. Cualquiera de las dos "
        "debe declararse en el informe."),
}


def raiz_del_repo() -> Path:
    return Path(__file__).resolve().parents[2]


# --- configuración congelada -------------------------------------------------------------------

def ruta_configuracion(raiz: Path, config_version: str) -> Path:
    return raiz / "experiments" / "config" / f"config_{config_version}.json"


def leer_configuracion(raiz: Path, config_version: str) -> dict:
    ruta = ruta_configuracion(raiz, config_version)
    if not ruta.is_file():
        raise FileNotFoundError(f"no existe la configuración congelada {ruta}")
    return json.loads(ruta.read_text(encoding="utf-8"))


def _como_variable(valor) -> str:
    if isinstance(valor, bool):
        return "true" if valor else "false"
    return str(valor)


def entorno_de_la_corrida(base: dict, congelada: dict, chroma: Path, cache_ip: Path) -> dict:
    """Entorno del proceso hijo: lo CONGELADO manda sobre lo que tenga el `.env`."""
    entorno = dict(base)
    for nombre, valor in (congelada.get("parametros") or {}).items():
        if valor is not None:
            entorno[nombre] = _como_variable(valor)
    entorno.update({
        "CHROMA_PATH": str(chroma),
        "IP_CACHE_PATH": str(cache_ip),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "PYTHONIOENCODING": "utf-8",
    })
    return entorno


def _leer_entorno(ruta: Path) -> dict:
    from dotenv import dotenv_values
    return {k: v for k, v in dotenv_values(ruta).items() if v is not None}


def _git(raiz: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(raiz), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout.strip()


def comprobar_codigo(raiz: Path, congelada: dict) -> list[str]:
    """Problemas entre el código actual y el congelado. Vacío = es el mismo código."""
    problemas = []
    commit = _git(raiz, "rev-parse", "HEAD")
    if commit != (congelada.get("git") or {}).get("commit"):
        problemas.append(f"el commit actual ({commit[:10]}) no es el congelado "
                         f"({str((congelada.get('git') or {}).get('commit'))[:10]})")
    sucio = _git(raiz, "status", "--porcelain", "--", "src")
    if sucio:
        problemas.append("hay cambios sin commitear en src/")
    return problemas


_SCRIPT_CONGELAR = r"""
import json, sys
from pathlib import Path
import google.genai
import src.config as c
from src.experimentation.runtime import configuracion as k
datos = json.loads(sys.stdin.read())
generacion = dict(datos["generacion"], sdk_google_genai=google.genai.__version__)
conf = k.congelar(datos["config_version"], Path(datos["raiz"]), modulo_config=c,
                  generacion=generacion, recursos_externos=datos["recursos_externos"])
ruta = k.escribir(conf, Path(datos["raiz"]))
print("CONGELADA_JSON:" + json.dumps({"archivo": str(ruta), "huella": conf.huella,
      "config_version": conf.config_version, "git": conf.git}))
"""

_SCRIPT_EFECTIVA = r"""
import json
import src.config as c
from src.experimentation.runtime.configuracion import PARAMETROS_CONGELADOS
print("EFECTIVA_JSON:" + json.dumps({n: getattr(c, n, None) for n in PARAMETROS_CONGELADOS}))
"""


def _ejecutar_script(raiz: Path, script: str, entorno: dict, entrada: str = "") -> str:
    r = subprocess.run([sys.executable, "-c", script], input=entrada, cwd=raiz, env=entorno,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=600)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[-1500:])
    return r.stdout


def congelar_piloto(raiz: Path, ruta_env: Path, config_version: str) -> dict:
    """Congela la configuración del piloto en un proceso con el entorno ya fijado.

    `src.config` lee las variables al importarse, así que el congelado se hace en un
    proceso hijo cuyo entorno tiene el modelo, el respaldo apagado y la temperatura
    del piloto: lo que queda escrito es lo que de verdad verá el sistema.
    """
    entorno = {**os.environ, **_leer_entorno(ruta_env), **CONFIGURACION_PILOTO,
               "PYTHONIOENCODING": "utf-8"}
    salida = _ejecutar_script(
        raiz, _SCRIPT_CONGELAR, entorno,
        json.dumps({"config_version": config_version, "raiz": str(raiz),
                    "generacion": GENERACION, "recursos_externos": RECURSOS_EXTERNOS}))
    for linea in salida.splitlines():
        if linea.startswith("CONGELADA_JSON:"):
            return json.loads(linea[len("CONGELADA_JSON:"):])
    raise RuntimeError("no se obtuvo la configuración congelada:\n" + salida[-800:])


def verificar_configuracion(raiz: Path, ruta_env: Path, congelada: dict) -> dict:
    """Qué configuración verá el sistema en una corrida real, frente a la congelada."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        entorno = entorno_de_la_corrida(
            {**os.environ, **_leer_entorno(ruta_env)}, congelada,
            Path(tmp) / "chroma", Path(tmp) / "ip.json")
        salida = _ejecutar_script(raiz, _SCRIPT_EFECTIVA, entorno)
    efectiva = next(json.loads(l[len("EFECTIVA_JSON:"):]) for l in salida.splitlines()
                    if l.startswith("EFECTIVA_JSON:"))
    congelados = congelada.get("parametros") or {}
    distintos = {n: {"congelado": congelados.get(n), "efectivo": efectiva.get(n)}
                 for n in congelados if congelados.get(n) != efectiva.get(n)}
    return {"efectiva": efectiva, "congelada": congelados, "distintos": distintos,
            "coincide": not distintos}


# --- el plan ----------------------------------------------------------------------------------------

def _primer_caso(subconjunto: dict) -> str:
    return orquestador._casos_del_subconjunto(subconjunto)[0][1]


def entradas_de_la_etapa(plan, subconjunto: dict, etapa: int | str) -> list[dict]:
    """Etapa 1: un solo caso con las tres arquitecturas. Etapa 2: todo lo demás.

    Etapas de campaña: «A» = repetición 1 de todos los casos; «B» = repetición 2. Dentro de cada una
    el orden es el del plan: BGL antes que UWF, y por caso.
    """
    if etapa in ETAPAS_DE_CAMPANA:
        return [e for e in plan.pendientes if e["repeticion"] == ETAPAS_DE_CAMPANA[etapa]]
    primero = _primer_caso(subconjunto)
    if etapa == 1:
        return [e for e in plan.pendientes if e["case_id"] == primero]
    return [e for e in plan.pendientes if e["case_id"] != primero]


def etiqueta_de_resultados(subconjunto: dict) -> str:
    """Los resultados de la partición de evaluación son de la campaña; los demás, de depuración."""
    return ("campana_evaluacion" if subconjunto.get("particion") == "evaluacion"
            else "depuracion_no_reportable")


def describir_plan(raiz: Path, subconjunto: dict, plan, congelada: dict | None) -> str:
    resumen = plan.resumen()
    modelo = ((congelada or {}).get("parametros") or {}).get("LLM_MODEL_PRIMARY")
    lineas = [
        f"config_version : {resumen['config_version']}"
        + ("" if congelada else "   (SIN configuración congelada)"),
        f"partición      : {resumen['particion']}   repeticiones: {resumen['repeticiones']}",
        f"modelo         : {modelo}   respaldo apagado: "
        f"{((congelada or {}).get('parametros') or {}).get('LLM_SIN_RESPALDO')}   "
        f"temperatura: {((congelada or {}).get('parametros') or {}).get('TEMPERATURE')}",
        f"corridas       : {resumen['corridas_pendientes']} pendientes, "
        f"{resumen['corridas_ya_hechas']} ya hechas",
    ]
    for a, n in sorted(resumen["por_arquitectura"].items()):
        rango = resumen["rango_medido_de_llamadas_por_corrida"].get(a)
        medido = f"  (medido {rango[0]}-{rango[1]} llamadas por corrida)" if rango else ""
        lineas.append(f"  {a:<20} {n:>4} corridas{medido}")
    lineas.append(f"llamadas de referencia (NO un piso): {resumen['llamadas_llm_referencia']}")
    est = estimacion.estimar(plan.pendientes, modelo)
    lineas.append(f"estimación de tokens ({est['es']}):")
    for f in est["filas"]:
        if f["por_corrida"] is None:
            lineas.append(f"  {f['arquitectura']:<20} {f['dataset']:<5} {f['corridas']:>3} corridas  "
                          f"sin medición (no suma)")
        else:
            if f["medicion"] == "no usa el modelo":
                lineas.append(f"  {f['arquitectura']:<20} {f['dataset']:<5} {f['corridas']:>3} corridas  "
                              f"no usa el modelo (0 tokens)")
                continue
            lineas.append(f"  {f['arquitectura']:<20} {f['dataset']:<5} {f['corridas']:>3} corridas  "
                          f"{f['por_corrida']['total']:>8,} tokens/corrida medido  "
                          f"≈ {f['total_estimado']:>9,}".replace(",", "."))
    lineas.append(f"  total estimado (solo lo medido): ≈ "
                  f"{est['total_estimado_tokens']:,} tokens".replace(",", "."))
    if est["aviso_modelo"]:
        lineas.append(f"  AVISO: {est['aviso_modelo']}")
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    costo = estimacion.costo(est, estimacion.leer_precios(raiz), modelo or "", hoy)
    lineas.append("  costo (solo lo medido): " + (
        f"{costo['costo']} {costo.get('moneda')} con los precios vigentes el {hoy} "
        f"(tabla consultada el {costo['fecha_de_precios']}, fuente: {costo['fuente_de_precios']})"
        if costo["costo"] is not None else f"sin calcular — {costo['motivo']}"))
    e1 = entradas_de_la_etapa(plan, subconjunto, 1)
    e2 = entradas_de_la_etapa(plan, subconjunto, 2)
    lineas.append(f"etapas: 1 = {len(e1)} corridas (caso {_primer_caso(subconjunto)}), "
                  f"2 = {len(e2)} corridas")
    ea = entradas_de_la_etapa(plan, subconjunto, "A")
    eb = entradas_de_la_etapa(plan, subconjunto, "B")
    lineas.append(f"etapas de campaña: A = {len(ea)} corridas (repetición 1, BGL y luego UWF), "
                  f"B = {len(eb)} corridas (repetición 2); B solo corre si el gasto real de A × "
                  f"{FACTOR_PROYECCION_ETAPA_B} no supera el tope")
    lineas.append(f"tope por corrida: {TOPE_CORRIDA_S // 3600} h | se detiene tras "
                  f"{MAX_FALLAS_DE_INFRAESTRUCTURA_SEGUIDAS} fallas de infraestructura seguidas")
    lineas.append(f"tope de gasto acumulado: USD {TOPE_GASTO_USD:.2f} (por omisión; --tope-gasto)")
    lineas.append("resultados: " + (
        "de la CAMPAÑA (partición de evaluación)"
        if etiqueta_de_resultados(subconjunto) == "campana_evaluacion"
        else "de DEPURACIÓN, no reportables"))
    return "\n".join(lineas)


# --- una corrida (proceso hijo) ---------------------------------------------------------------

def trabajar(raiz: Path, dataset: str, case_id: str, arquitectura: str, repeticion: int,
             config_version: str, particion: str, destino: Path) -> int:
    """Corre UNA corrida en este proceso y la persiste. **Hace llamadas al modelo.**

    Instala el bloqueo de red y el registro de consultas externas ANTES de importar el
    pipeline (los agentes se quedan con la función que haya al importarse).
    """
    from src.experimentation.runtime.consultas_externas import RegistroConsultas, instalar

    registro = RegistroConsultas()
    instalar(registro)
    cuenta_json = None
    if arquitectura == "nodex_multiagente":
        # Medición de JSON válido de NODEX: hay que envolver `llm_json` ANTES de que se importen
        # los agentes (se quedan con la función que haya en ese momento).
        import src.llm as modulo_llm
        from src.experimentation.comparacion_modelos import _instrumentar_llm_json
        cuenta_json = _instrumentar_llm_json(modulo_llm)
    orquestador.asegurar_salida_utf8()
    identidad = IdentidadCorrida(case_id=case_id, dataset=dataset, arquitectura=arquitectura,
                                 repeticion=repeticion, config_version=config_version)
    metadatos = orquestador._metadatos_del_caso(raiz, dataset, particion, case_id)
    error = None
    try:
        orquestador._correr_una(raiz, identidad, particion, metadatos)
    except Exception as e:  # noqa: BLE001 - se registra, no se oculta
        error = f"{type(e).__name__}: {e}"
    try:
        persistencia.guardar_consultas_externas(identidad, raiz, registro.a_lista())
    except FileExistsError:
        pass   # ya hay un registro de un intento anterior de esta misma corrida
    if cuenta_json is not None:
        try:
            persistencia.guardar_llm_json(identidad, raiz, cuenta_json["llamadas"],
                                          cuenta_json["invalidas"])
        except FileExistsError:
            pass
    destino.write_text(json.dumps({"error": error}), encoding="utf-8")
    return 0


def estado_guardado(identidad: IdentidadCorrida, raiz: Path) -> str | None:
    """`ejecucion.estado` de la salida guardada, o `None` si no hay salida."""
    ruta = persistencia.rutas(identidad, raiz).salida
    if not ruta.is_file():
        return None
    return (persistencia.leer_salida(ruta).get("ejecucion") or {}).get("estado")


def correr_una(raiz: Path, base_env: dict, congelada: dict, entrada: dict, particion: str,
               config_version: str, carpeta_logs: Path, tope_s: int | None = TOPE_CORRIDA_S) -> dict:
    """Lanza una corrida en un proceso aparte. Devuelve cómo terminó. Nunca la oculta."""
    from src.experimentation.runners import nodex

    identidad = IdentidadCorrida(
        case_id=entrada["case_id"], dataset=entrada["dataset"],
        arquitectura=entrada["arquitectura"], repeticion=entrada["repeticion"],
        config_version=config_version)
    carpeta_logs.mkdir(parents=True, exist_ok=True)
    inicio = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp = Path(tmp)
        copia = tmp / "chroma"
        shutil.copytree(configuracion_experimental(raiz).chroma, copia)
        resultado_hijo = tmp / "resultado.json"
        entorno = entorno_de_la_corrida(base_env, congelada, copia, tmp / "ip.json")
        codigo, stdout, stderr, vencio = ejecutar_hijo(
            [sys.executable, "-m", "src.experimentation.campana", "--trabajar",
             identidad.dataset, identidad.case_id, identidad.arquitectura,
             str(identidad.repeticion), config_version, particion, str(resultado_hijo)],
            raiz, entorno, tope_s)
        error_hijo = None
        if resultado_hijo.is_file():
            error_hijo = json.loads(resultado_hijo.read_text(encoding="utf-8")).get("error")
    (carpeta_logs / f"{identidad.run_id}.stdout.txt").write_text(stdout, encoding="utf-8")
    (carpeta_logs / f"{identidad.run_id}.stderr.txt").write_text(stderr, encoding="utf-8")
    segundos = round((datetime.now(timezone.utc) - inicio).total_seconds(), 1)

    estado = estado_guardado(identidad, raiz)
    error = None
    if vencio:
        error = f"NoCompletoEnElTiempoPrevisto: superó el tope de {tope_s} s"
        estado = "timeout"
    elif error_hijo:
        error = error_hijo
    elif estado is None:
        error = f"el proceso terminó con código {codigo} sin dejar salida"
    if error and (estado is None or vencio):
        estado = "timeout" if vencio else nodex.clasificar_error(error)
        persistencia.guardar_fallo(identidad, raiz, estado=estado, error=error)
    return {"run_id": identidad.run_id, "case_id": identidad.case_id,
            "dataset": identidad.dataset, "arquitectura": identidad.arquitectura,
            "repeticion": identidad.repeticion, "estado": estado, "error": error, "segundos": segundos,
            "infraestructura": estado in ESTADOS_DE_INFRAESTRUCTURA,
            "tope_alcanzado": bool(vencio)}


# --- informe de etapa ----------------------------------------------------------------------------------

def informe_de_corrida(raiz: Path, corrida: dict, congelada: dict) -> dict:
    """Credencial, modelo efectivo, fallback, tokens, tiempo, llamadas y errores de UNA corrida."""
    from src.experimentation import consolidacion

    identidad = IdentidadCorrida(corrida["case_id"], corrida["dataset"], corrida["arquitectura"],
                                 corrida.get("repeticion", 1), congelada["config_version"])
    tel = persistencia.leer_telemetria(identidad, raiz) or {}
    json_nodex = (persistencia.leer_llm_json(identidad, raiz)
                  if corrida["arquitectura"] == "nodex_multiagente" else None)
    principal = (congelada.get("parametros") or {}).get("LLM_MODEL_PRIMARY")
    usa_modelo = corrida["arquitectura"] != "baseline_reglas"
    llamadas = tel.get("llm_calls") or []
    tokens = consolidacion.tokens_de_la_corrida(tel)
    consultas = persistencia.leer_consultas_externas(identidad, raiz)
    versiones = sorted({c["model_version"] for c in llamadas if c.get("model_version")})
    return {
        "run_id": corrida["run_id"], "arquitectura": corrida["arquitectura"],
        "dataset": corrida["dataset"], "case_id": corrida["case_id"],
        "estado": corrida["estado"], "error": corrida["error"],
        "segundos": corrida["segundos"],
        "credencial_presente": (congelada.get("credenciales_presentes") or {}).get("GEMINI_API_KEY")
        if usa_modelo else None,
        "modelo_pedido": principal if usa_modelo else None,
        "versiones_devueltas": versiones if usa_modelo else None,
        "usa_fallback": consolidacion.uso_fallback(tel, principal) if usa_modelo else None,
        "llamadas": len(llamadas) if usa_modelo else 0,
        "llamadas_fallidas": tokens["n_fallidas"] if usa_modelo else 0,
        "tokens": {"entrada": tel.get("input_tokens"), "salida": tel.get("output_tokens"),
                   "razonamiento": tel.get("reasoning_tokens"), "total": tel.get("total_tokens"),
                   "parcial": consolidacion.es_parcial(tel)} if usa_modelo else None,
        "intentos_de_consulta_externa": (None if consultas is None else
                                         sum(1 for c in consultas if c.get("intento_externo"))),
        "json_llamadas": None if json_nodex is None else json_nodex["llamadas"],
        "json_invalidas": None if json_nodex is None else json_nodex["invalidas"],
    }


def etapa_limpia(informes: list[dict], congelada: dict) -> tuple[bool, list[str]]:
    """La etapa sale limpia si todo se completó, con el modelo pedido y sin fallback."""
    motivos = []
    principal = (congelada.get("parametros") or {}).get("LLM_MODEL_PRIMARY")
    for i in informes:
        if i["estado"] != "completa":
            motivos.append(f"{i['run_id']}: estado {i['estado']}" + (f" ({i['error']})" if i["error"] else ""))
        if i["usa_fallback"]:
            motivos.append(f"{i['run_id']}: usó el modelo de respaldo")
        if i["arquitectura"] != "baseline_reglas":
            if not i["versiones_devueltas"]:
                motivos.append(f"{i['run_id']}: la API no devolvió model_version")
            for v in i["versiones_devueltas"] or []:
                if not (v == principal or v.startswith(f"{principal}-")):
                    motivos.append(f"{i['run_id']}: versión devuelta {v!r} no corresponde a {principal!r}")
            if i["llamadas_fallidas"]:
                motivos.append(f"{i['run_id']}: {i['llamadas_fallidas']} llamada(s) fallida(s)")
    return not motivos, motivos


def imprimir_informe(informes: list[dict]) -> None:
    for i in informes:
        t = i["tokens"]
        tokens = ("sin modelo" if t is None else
                  f"entrada {t['entrada']} salida {t['salida']} razonamiento {t['razonamiento']}"
                  f"{' (PARCIAL: total None)' if t['parcial'] else ''}")
        print(f"- {i['arquitectura']:<18} {i['dataset']:<4} {i['case_id']}: estado={i['estado']} "
              f"tiempo={i['segundos']}s llamadas={i['llamadas']} (fallidas {i['llamadas_fallidas']}) "
              f"credencial={i['credencial_presente']} modelo={i['modelo_pedido']} "
              f"versiones={i['versiones_devueltas']} fallback={i['usa_fallback']} "
              f"tokens: {tokens} consultas_externas={i['intentos_de_consulta_externa']}"
              + (f" ERROR: {i['error']}" if i["error"] else ""))


# --- ejecución de una etapa --------------------------------------------------------------------------

def ruta_gasto(raiz: Path, config_version: str) -> Path:
    return raiz / "experiments" / "ejecucion" / config_version / "gasto.json"


def leer_registro_de_gasto(raiz: Path, config_version: str) -> list[dict]:
    ruta = ruta_gasto(raiz, config_version)
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else []


def _anotar_gasto(raiz: Path, config_version: str, entrada: dict) -> None:
    ruta = ruta_gasto(raiz, config_version)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(leer_registro_de_gasto(raiz, config_version) + [entrada],
                               indent=2, ensure_ascii=False), encoding="utf-8")


def revisar_tope_de_gasto(raiz: Path, congelada: dict, tope: float, hoy: str,
                          siguiente: dict | None = None,
                          config_referencia: str | None = None) -> dict:
    """Gasto acumulado de la configuración y si lanzar `siguiente` podría superar el tope.

    El gasto se recalcula desde la telemetría guardada (tokens medidos × precios vigentes `hoy`).
    El costo de la corrida siguiente se acota con el MÁXIMO observado de su celda
    (arquitectura, dataset), tomando lo mayor entre lo ya medido en esta configuración y lo del
    piloto de referencia. Sin ninguna medición el máximo es 0: no se inventa un costo.
    """
    from src.experimentation import presupuesto

    config_version = congelada["config_version"]
    modelo = (congelada.get("parametros") or {}).get("LLM_MODEL_PRIMARY") or ""
    precios = estimacion.leer_precios(raiz)
    gasto = presupuesto.gasto_acumulado(raiz, config_version, precios, modelo, hoy)
    maximo_siguiente = 0.0
    if siguiente is not None:
        celdas = [presupuesto.costos_por_celda(raiz, config_version, precios, modelo, hoy)]
        if config_referencia:
            celdas.append(presupuesto.costos_por_celda(raiz, config_referencia, precios, modelo, hoy))
        maximo_siguiente = max(presupuesto.costo_maximo_esperado(
            c, siguiente["arquitectura"], siguiente["dataset"]) for c in celdas)
    proyectado = round(gasto["usd"] + maximo_siguiente, 6)
    return {"gasto_acumulado_usd": gasto["usd"], "corridas_con_costo": gasto["corridas"],
            "corridas_con_costo_parcial": gasto["corridas_con_costo_parcial"],
            "maximo_de_la_siguiente_usd": round(maximo_siguiente, 6),
            "proyectado_usd": proyectado, "tope_usd": tope,
            "supera": proyectado > tope, "fecha_de_precios": hoy}


def _detener_por_gasto(raiz: Path, config_version: str, etapa: int, revision: dict,
                       corridas: list[dict], congelada: dict, subconjunto: dict,
                       gasto_inicial: float, motivo: str) -> tuple[int, list[dict]]:
    print(f"DETENIDO POR TOPE DE GASTO: {motivo}. Gasto acumulado USD "
          f"{revision['gasto_acumulado_usd']:.4f} de USD {revision['tope_usd']:.2f}. "
          f"Reanudable: las corridas guardadas no se repiten.", flush=True)
    informes = [informe_de_corrida(raiz, c, congelada) for c in corridas]
    _guardar_informe(raiz / "experiments" / "ejecucion" / config_version, etapa, informes,
                     detenido=True, motivo_de_parada=motivo, subconjunto=subconjunto,
                     gasto={"inicial_usd": gasto_inicial, **revision})
    return SALIDA_TOPE_DE_GASTO, informes


def decidir_etapa_b(raiz: Path, congelada: dict, tope_gasto: float, hoy: str,
                    pendientes_de_a: int) -> dict:
    """¿Se puede lanzar la Etapa B? Solo si A terminó y el gasto REAL de A × 2 no supera el tope.

    El gasto de A se recalcula desde la telemetría guardada (repetición 1), con los tokens medidos y los
    precios vigentes `hoy`. Un gasto de A × 2 exactamente igual al tope sí se permite.
    """
    from src.experimentation import presupuesto

    modelo = (congelada.get("parametros") or {}).get("LLM_MODEL_PRIMARY") or ""
    gasto = presupuesto.gasto_acumulado(raiz, congelada["config_version"], estimacion.leer_precios(raiz),
                                        modelo, hoy)
    gasto_a = round(gasto["por_repeticion"].get(ETAPAS_DE_CAMPANA["A"], 0.0), 6)
    proyectado = round(gasto_a * FACTOR_PROYECCION_ETAPA_B, 6)
    decision = {"gasto_real_etapa_a_usd": gasto_a, "factor": FACTOR_PROYECCION_ETAPA_B,
                "proyeccion_etapa_b_usd": proyectado, "tope_usd": tope_gasto,
                "etapa_a_pendientes": pendientes_de_a,
                "corridas_con_costo_parcial": gasto["corridas_con_costo_parcial"]}
    if pendientes_de_a:
        decision.update(autorizada=False, motivo=f"la Etapa A no terminó: faltan {pendientes_de_a} corridas")
    elif proyectado > tope_gasto:
        decision.update(autorizada=False, motivo=(
            f"el gasto real de la Etapa A (USD {gasto_a:.4f}) × {FACTOR_PROYECCION_ETAPA_B} = "
            f"USD {proyectado:.4f} supera el tope de USD {tope_gasto:.2f}"))
    else:
        decision.update(autorizada=True, motivo=(
            f"USD {gasto_a:.4f} × {FACTOR_PROYECCION_ETAPA_B} = USD {proyectado:.4f} no supera "
            f"USD {tope_gasto:.2f}"))
    return decision


def ejecutar_campana_por_etapas(raiz: Path, ruta_env: Path, config_version: str, subconjunto_nombre: str,
                                correr=correr_una, tope_gasto: float = TOPE_GASTO_USD,
                                hoy: str | None = None, config_referencia: str | None = None
                                ) -> tuple[int, dict]:
    """Etapa A y, solo si corresponde, Etapa B. Se detiene en la primera que no salga bien."""
    resultado: dict = {}
    codigo, informes = ejecutar_etapa(raiz, ruta_env, config_version, subconjunto_nombre, "A",
                                      correr=correr, tope_gasto=tope_gasto, hoy=hoy,
                                      config_referencia=config_referencia)
    resultado["A"] = {"codigo": codigo, "corridas": len(informes)}
    if codigo != SALIDA_OK:
        resultado["B"] = {"lanzada": False, "motivo": "la Etapa A no salió limpia"}
        return codigo, resultado
    codigo, informes = ejecutar_etapa(raiz, ruta_env, config_version, subconjunto_nombre, "B",
                                      correr=correr, tope_gasto=tope_gasto, hoy=hoy,
                                      config_referencia=config_referencia)
    resultado["B"] = {"lanzada": codigo != SALIDA_ETAPA_B_NO_AUTORIZADA, "codigo": codigo,
                      "corridas": len(informes)}
    return codigo, resultado


def ejecutar_etapa(raiz: Path, ruta_env: Path, config_version: str, subconjunto_nombre: str,
                   etapa: int | str, correr=correr_una, tope_gasto: float = TOPE_GASTO_USD,
                   hoy: str | None = None, dataset: str | None = None,
                   config_referencia: str | None = None,
                   arquitecturas: tuple[str, ...] = ARQUITECTURAS_PILOTO) -> tuple[int, list[dict]]:
    """Corre una etapa. Devuelve `(código de salida, informes)`.

    Se detiene (en este orden de importancia) por tres fallas de infraestructura seguidas o
    porque la corrida siguiente podría superar el tope de gasto acumulado. `dataset` limita la
    etapa a un dataset (la campaña se hace primero BGL y después UWF).
    """
    hoy = hoy or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    congelada = leer_configuracion(raiz, config_version)
    subconjunto = orquestador.cargar_subconjunto(raiz, subconjunto_nombre)
    plan = orquestador.planificar(raiz, subconjunto, config_version, arquitecturas)
    entradas = entradas_de_la_etapa(plan, subconjunto, etapa)
    if dataset:
        entradas = [e for e in entradas if e["dataset"] == dataset]
    base_env = {**os.environ, **_leer_entorno(ruta_env)}
    carpeta_logs = raiz / "experiments" / "ejecucion" / config_version
    try:
        revision = revisar_tope_de_gasto(raiz, congelada, tope_gasto, hoy,
                                         config_referencia=config_referencia)
    except ValueError as e:
        print(f"NO SE PUEDE MEDIR EL GASTO: {e}. No se lanza nada.", flush=True)
        return SALIDA_TOPE_DE_GASTO, []
    gasto_inicial = revision["gasto_acumulado_usd"]
    if etapa == "B":
        # La compuerta de la Etapa B vive AQUÍ, no en quien la llama: nadie puede saltársela.
        decision = decidir_etapa_b(
            raiz, congelada, tope_gasto, hoy,
            pendientes_de_a=len(entradas_de_la_etapa(plan, subconjunto, "A")))
        _anotar_gasto(raiz, config_version, {
            "momento": datetime.now(timezone.utc).isoformat(timespec="seconds"), "etapa": "B",
            "decision_etapa_b": decision})
        print(f"Compuerta de la Etapa B: {decision['motivo']}", flush=True)
        if not decision["autorizada"]:
            _guardar_informe(carpeta_logs, "B", [], detenido=True,
                             motivo_de_parada="compuerta de la Etapa B: " + decision["motivo"],
                             subconjunto=subconjunto, gasto={"inicial_usd": gasto_inicial, **revision},
                             decision_etapa_b=decision)
            return SALIDA_ETAPA_B_NO_AUTORIZADA, []
    if revision["supera"]:
        return _detener_por_gasto(raiz, config_version, etapa, revision, [], congelada, subconjunto,
                                  gasto_inicial, "el gasto acumulado ya supera el tope")
    corridas, seguidas = [], 0
    for entrada in entradas:
        revision = revisar_tope_de_gasto(raiz, congelada, tope_gasto, hoy, siguiente=entrada,
                                         config_referencia=config_referencia)
        if revision["supera"]:
            return _detener_por_gasto(
                raiz, config_version, etapa, revision, corridas, congelada, subconjunto,
                gasto_inicial,
                f"gasto USD {revision['gasto_acumulado_usd']:.4f} + máximo observado de la siguiente "
                f"({entrada['arquitectura']}, {entrada['dataset']}) USD "
                f"{revision['maximo_de_la_siguiente_usd']:.4f} superaría USD {tope_gasto:.2f}")
        corrida = correr(raiz, base_env, congelada, entrada, subconjunto["particion"],
                         config_version, carpeta_logs)
        corridas.append(corrida)
        seguidas = seguidas + 1 if corrida["infraestructura"] else 0
        despues = revisar_tope_de_gasto(raiz, congelada, tope_gasto, hoy,
                                        config_referencia=config_referencia)
        _anotar_gasto(raiz, config_version, {
            "momento": datetime.now(timezone.utc).isoformat(timespec="seconds"), "etapa": etapa,
            "run_id": corrida["run_id"], "estado": corrida["estado"],
            "gasto_acumulado_usd": despues["gasto_acumulado_usd"], "tope_usd": tope_gasto})
        print(f"[{len(corridas)}/{len(entradas)}] {corrida['arquitectura']} {corrida['case_id']}: "
              f"{corrida['estado']} en {corrida['segundos']} s | gasto acumulado USD "
              f"{despues['gasto_acumulado_usd']:.4f} de {tope_gasto:.2f}", flush=True)
        if seguidas >= MAX_FALLAS_DE_INFRAESTRUCTURA_SEGUIDAS:
            print(f"DETENIDO: {seguidas} fallas de infraestructura seguidas", flush=True)
            informes = [informe_de_corrida(raiz, c, congelada) for c in corridas]
            _guardar_informe(carpeta_logs, etapa, informes, detenido=True,
                             motivo_de_parada="fallas de infraestructura seguidas",
                             subconjunto=subconjunto,
                             gasto={"inicial_usd": gasto_inicial, **despues})
            return SALIDA_FALLAS_SEGUIDAS, informes
        if despues["gasto_acumulado_usd"] > tope_gasto:
            return _detener_por_gasto(raiz, config_version, etapa, despues, corridas, congelada,
                                      subconjunto, gasto_inicial,
                                      "la corrida que acaba de terminar dejó el gasto sobre el tope")
    informes = [informe_de_corrida(raiz, c, congelada) for c in corridas]
    limpia, motivos = etapa_limpia(informes, congelada)
    final = revisar_tope_de_gasto(raiz, congelada, tope_gasto, hoy,
                                  config_referencia=config_referencia)
    _guardar_informe(carpeta_logs, etapa, informes, detenido=False, limpia=limpia, motivos=motivos,
                     subconjunto=subconjunto, gasto={"inicial_usd": gasto_inicial, **final})
    return (SALIDA_OK if limpia else SALIDA_ETAPA_NO_LIMPIA), informes


def _guardar_informe(carpeta: Path, etapa: int, informes: list[dict], detenido: bool,
                     limpia: bool | None = None, motivos: list[str] | None = None,
                     motivo_de_parada: str | None = None, subconjunto: dict | None = None,
                     gasto: dict | None = None, decision_etapa_b: dict | None = None) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"informe_etapa{etapa}.json"
    if destino.exists():
        destino = carpeta / (f"informe_etapa{etapa}_"
                             f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
    gasto = gasto or {}
    destino.write_text(json.dumps({
        "etapa": etapa, "detenido": detenido, "detenido_por_fallas_seguidas":
            detenido and motivo_de_parada == "fallas de infraestructura seguidas",
        "motivo_de_parada": motivo_de_parada, "limpia": limpia,
        "decision_etapa_b": decision_etapa_b,
        "motivos": motivos or [], "etiqueta": etiqueta_de_resultados(subconjunto or {}),
        "gasto": {**gasto, "de_la_etapa_usd": round(
            gasto.get("gasto_acumulado_usd", 0.0) - gasto.get("inicial_usd", 0.0), 6)} if gasto else None,
        "informes": informes}, indent=2, ensure_ascii=False), encoding="utf-8")


def main(argv: list[str] | None = None, raiz: Path | None = None) -> int:
    raiz = raiz or raiz_del_repo()
    # El plan lleva símbolos (≈, ≥) que cp1252 no puede codificar si la salida se redirige.
    orquestador.asegurar_salida_utf8()
    p = argparse.ArgumentParser(prog="campana", description=__doc__.split("\n")[0])
    p.add_argument("--subconjunto", default="piloto")
    p.add_argument("--config-version", help="versión de la configuración congelada")
    p.add_argument("--env", help="ruta al .env con las credenciales (no se copia)")
    p.add_argument("--congelar", action="store_true",
                   help="congela la configuración del piloto (modelo, respaldo apagado, ...)")
    p.add_argument("--verificar-config", action="store_true",
                   help="muestra la configuración efectiva frente a la congelada; no usa la red")
    p.add_argument("--ejecutar", action="store_true",
                   help="HACE LLAMADAS AL MODELO. Sin esto solo se muestra el plan.")
    p.add_argument("--etapa", choices=("1", "2", "A", "B"),
                   help="1 = un caso con las tres arquitecturas; 2 = el resto; A = repetición 1 de todos "
                        "los casos; B = repetición 2 (solo si el gasto real de A × 2 no supera el tope)")
    p.add_argument("--arquitecturas",
                   help="lista separada por comas (p. ej. nodex_multiagente); por omisión las tres. "
                        "Para verificaciones; la campaña usa las tres")
    p.add_argument("--campana", action="store_true",
                   help="Etapa A y, si la compuerta lo permite, Etapa B. HACE LLAMADAS AL MODELO.")
    p.add_argument("--dataset", help="limita la etapa a un dataset (la campaña: primero bgl, luego uwf)")
    p.add_argument("--tope-gasto", type=float, default=TOPE_GASTO_USD,
                   help=f"tope de gasto acumulado en USD (por omisión {TOPE_GASTO_USD:.2f})")
    p.add_argument("--config-referencia",
                   help="config_version de un piloto con corridas medidas: acota el costo máximo de "
                        "las celdas que aún no tienen medición en esta campaña")
    p.add_argument("--trabajar", nargs=7, metavar=("DATASET", "CASO", "ARQ", "REP", "CONFIG",
                                                    "PARTICION", "DESTINO"),
                   help="uso interno: corre una corrida en este proceso")
    a = p.parse_args(argv)

    if a.trabajar:
        dataset, caso, arq, rep, config, particion, destino = a.trabajar
        return trabajar(raiz, dataset, caso, arq, int(rep), config, particion, Path(destino))
    if not a.config_version:
        p.error("falta --config-version")

    if a.congelar:
        if not a.env:
            p.error("--congelar necesita --env")
        r = congelar_piloto(raiz, Path(a.env), a.config_version)
        print(f"configuración congelada: {r['archivo']}\nhuella: {r['huella']}\n"
              f"commit: {r['git'].get('commit')} | árbol limpio: {r['git'].get('arbol_limpio')}")
        return SALIDA_OK

    congelada = None
    try:
        congelada = leer_configuracion(raiz, a.config_version)
    except FileNotFoundError:
        pass

    if a.verificar_config:
        if not (a.env and congelada):
            p.error("--verificar-config necesita --env y una configuración congelada")
        v = verificar_configuracion(raiz, Path(a.env), congelada)
        print(f"configuración efectiva: {json.dumps({k: v['efectiva'][k] for k in CONFIGURACION_PILOTO if k in v['efectiva']})}")
        print(f"coincide con la congelada: {v['coincide']}")
        for nombre, d in v["distintos"].items():
            print(f"  DISTINTO {nombre}: congelado {d['congelado']!r} efectivo {d['efectivo']!r}")
        return SALIDA_OK if v["coincide"] else SALIDA_ETAPA_NO_LIMPIA

    subconjunto = orquestador.cargar_subconjunto(raiz, a.subconjunto)
    arquitecturas = tuple(a.arquitecturas.split(",")) if a.arquitecturas else ARQUITECTURAS_PILOTO
    desconocidas = set(arquitecturas) - set(ARQUITECTURAS_PILOTO)
    if desconocidas:
        p.error(f"arquitecturas desconocidas: {sorted(desconocidas)}")
    plan = orquestador.planificar(raiz, subconjunto, a.config_version, arquitecturas)
    print(describir_plan(raiz, subconjunto, plan, congelada))

    if not a.ejecutar:
        print("\n(sin --ejecutar: no se hizo ninguna llamada)")
        return SALIDA_OK
    if not (a.env and (a.etapa or a.campana)):
        p.error("--ejecutar necesita --env y --etapa (o --campana)")
    if a.campana and a.arquitecturas:
        p.error("--campana corre siempre las tres arquitecturas; --arquitecturas es solo para verificaciones")
    if a.campana and a.etapa:
        p.error("--campana corre las etapas A y B; no se combina con --etapa")
    if congelada is None:
        p.error(f"no existe la configuración congelada de {a.config_version}: usar --congelar")
    problemas = comprobar_codigo(raiz, congelada)
    if problemas:
        print("EL CÓDIGO NO ES EL CONGELADO:\n  - " + "\n  - ".join(problemas))
        return SALIDA_ETAPA_NO_LIMPIA
    v = verificar_configuracion(raiz, Path(a.env), congelada)
    if not v["coincide"]:
        print(f"LA CONFIGURACIÓN EFECTIVA NO COINCIDE CON LA CONGELADA: {v['distintos']}")
        return SALIDA_ETAPA_NO_LIMPIA

    if a.campana:
        codigo, resultado = ejecutar_campana_por_etapas(
            raiz, Path(a.env), a.config_version, a.subconjunto, tope_gasto=a.tope_gasto,
            config_referencia=a.config_referencia)
        print(f"Campaña por etapas: {json.dumps(resultado, ensure_ascii=False)} -> código {codigo}")
        return codigo
    etapa = int(a.etapa) if a.etapa.isdigit() else a.etapa
    codigo, informes = ejecutar_etapa(raiz, Path(a.env), a.config_version, a.subconjunto, etapa,
                                      tope_gasto=a.tope_gasto, dataset=a.dataset,
                                      config_referencia=a.config_referencia,
                                      arquitecturas=arquitecturas)
    print(f"\nInforme de la etapa {a.etapa}:")
    imprimir_informe(informes)
    limpia, motivos = etapa_limpia(informes, congelada)
    print(f"\nLa etapa {'salió LIMPIA' if limpia else 'NO salió limpia'}")
    for m in motivos:
        print(f"  - {m}")
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
