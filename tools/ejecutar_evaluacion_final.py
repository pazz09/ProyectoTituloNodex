"""Ejecución de la evaluación final de NODEX (preregistro: docs/experimentacion/preregistro_evaluacion_final.md).

    python tools/ejecutar_evaluacion_final.py --plan                     # orden de las corridas, sin API
    python tools/ejecutar_evaluacion_final.py --verificar-api            # una llamada mínima al modelo
    python tools/ejecutar_evaluacion_final.py --preflight-gemini         # Gemini directo sin modelo: tamaños y columnas
    python tools/ejecutar_evaluacion_final.py --ejecutar --tope 40       # todo, reanudable
    python tools/ejecutar_evaluacion_final.py --simulado --salida <dir> --casos A B --repeticiones 1   # prueba sin API

Orden (preregistro, sección 4): por repetición, NODEX (60), agente único (60) y Gemini directo (60); primero
R1 completa, luego R2 y luego R3. Al final, NODEX sobre los 12 casos del piloto (1 repetición, carpeta
`piloto_no_confirmatorio/`, sobre los mismos archivos que usó el piloto).

Configuración congelada: `experiments/config/config_oficial-12casos-r1-20261028.json` (gemini-3.8-flash,
temperatura 0, sin modelo de respaldo, sin reputación externa) aplicada a cada proceso hijo; red bloqueada salvo
la API del modelo; un proceso nuevo por caso con una copia desechable de `rag_enriquecido_v2` (exclusión por
solapamiento del propio sistema). **Sin** exclusión por incidente (fue un control de desarrollo).

Registro por corrida: commit, configuración efectiva e interruptores (leídos dentro del proceso hijo), SHA-256 del
`system` y del prompt de cada llamada al modelo, tokens, tiempo y costo.

Fallas:
- del sistema (excepción, salida inválida, tope de tiempo, `_error_api` no atribuible a infraestructura): se
  registran y NO se repiten;
- de infraestructura (suspensión o apagado del equipo según el registro de Windows, red, servidor o cuota
  transitoria de la API): la corrida se aparta sin borrarla en `apartadas/`, se repite desde cero y se registra;
- crédito agotado: se detiene todo y se informa.

Autónomo y reanudable: al relanzarlo omite las corridas terminadas; una corrida interrumpida (estado `en_curso`
en `estado.json`, o un resultado sin cierre) se aparta y se repite desde cero. Se detiene solo ante crédito
agotado o el tope de gasto. Archivos en la carpeta de salida: `ejecucion.log` (log), `estado.json` (avance),
`bitacora_ejecucion.md` (incidentes), `registro_*.json` (procedencia por lanzamiento) e
`informe_operativo_<etapa>.json`. Mantiene el equipo despierto mientras corre y restaura la configuración al
terminar (también si se interrumpe).
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CASOS_FINAL = ROOT / "experiments" / "cases_final"
SALIDA = ROOT / "experiments" / "evaluacion_final"
PILOTO = ROOT / "experiments/ejecucion/enriquecido-12casos-r1-20261104/selection.json"
MEMORIA = ROOT / "experiments/knowledge/rag_enriquecido_v2"
MEMORIA_GRUPOS = ROOT / "experiments/knowledge/memoria_grupos_v1/memoria_grupos.json"
CONFIG_CONGELADA = ROOT / "experiments/config/config_oficial-12casos-r1-20261028.json"
PREREGISTRO = ROOT / "docs/experimentacion/preregistro_evaluacion_final.md"
SISTEMAS = ("nodex", "agente_unico", "gemini_directo")
REPETICIONES = 3
PRECIO = {"entrada": 0.75, "salida": 3.75}          # USD por millón de tokens; razonamiento = salida
#: Cota de gasto por caso para el control del tope (por encima del máximo observado en desarrollo).
COTA = {("nodex", "bgl"): 0.08, ("nodex", "uwf"): 0.35, ("agente_unico", "bgl"): 0.08,
        ("agente_unico", "uwf"): 0.25, ("gemini_directo", "bgl"): 0.08, ("gemini_directo", "uwf"): 0.30}
TOPE_SEGUNDOS_CASO = 1800
NODOS = {"agente_planificador": "planificador", "agente_analista_triage": "triage",
         "agente_selector_herramientas": "selector", "agente_ingeniero_mitigacion": "mitigacion",
         "agente_auditor_final": "auditor"}
_SECRETOS = ("KEY", "TOKEN", "SECRET", "PASSWORD")
_INFRA = ("503", "UNAVAILABLE", "500 INTERNAL", "502", "504", "DEADLINE_EXCEEDED", "429", "Timeout", "timed out",
          "ConnectError", "Connection", "RemoteProtocolError", "ReadError", "ServerError")


def utc():
    return datetime.now(timezone.utc).isoformat()


def _leer(ruta):
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def _escribir(ruta, datos):
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")


def sha_archivo(ruta) -> str:
    return hashlib.sha256(Path(ruta).read_bytes()).hexdigest()


def sha_texto(texto: str) -> str:
    return hashlib.sha256((texto or "").encode("utf-8")).hexdigest()


def costo(llamadas) -> float:
    entrada = sum(c.get("input_tokens") or 0 for c in llamadas)
    salida = sum((c.get("output_tokens") or 0) + (c.get("reasoning_tokens") or 0) for c in llamadas)
    return (entrada * PRECIO["entrada"] + salida * PRECIO["salida"]) / 1e6


def git(*args) -> str:
    return subprocess.run(["git", "-c", "core.longpaths=true", "-C", str(ROOT), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout.strip()


# --- plan ----------------------------------------------------------------------------------------

def plan(casos: list[str] | None = None, repeticiones: int = REPETICIONES, piloto: bool = True) -> list[dict]:
    seleccion = _leer(CASOS_FINAL / "seleccion.json")["casos"]
    finales = [c for c in seleccion if not casos or c["case_id"] in casos]
    corridas = []
    for r in range(1, repeticiones + 1):
        for sistema in SISTEMAS:
            for c in finales:
                ext = "log" if c["dataset"] == "bgl" else "csv"
                corridas.append({"etapa": f"r{r}", "repeticion": r, "sistema": sistema, "dataset": c["dataset"],
                                 "case_id": c["case_id"], "confirmatorio": True,
                                 "entrada": f"experiments/cases_final/cases/{c['dataset']}/evaluacion/{c['case_id']}.{ext}"})
    if piloto:
        for c in _leer(PILOTO)["casos"]:
            if casos and c["case_id"] not in casos:
                continue
            corridas.append({"etapa": "piloto_no_confirmatorio", "repeticion": 1, "sistema": "nodex",
                             "dataset": c["dataset"], "case_id": c["case_id"], "confirmatorio": False,
                             "entrada": c["input_path"], "entrada_sha256_piloto": c["sha256"]})
    return corridas


def destino(salida: Path, corrida: dict) -> Path:
    return salida / corrida["etapa"] / corrida["sistema"] / f"{corrida['case_id']}.json"


# --- proceso hijo -------------------------------------------------------------------------------------

def _respuestas_simuladas(dataset: str):
    """Modelo simulado para la prueba del ejecutor (sin API)."""
    comunes = {"confianza": 0.9, "hay_anomalia": False, "hay_incidente": False, "evaluacion": "simulado",
               "cobertura_auditor": True, "eventos_reconstruidos": [], "secuencia_temporal": [],
               "tecnicas_atribuidas": [], "evaluacion_grupos": []}
    return {
        "planificador": {"objetivo": "o", "pasos": [{"id": 1, "accion": "triage", "objetivo": "d",
                                                     "estado": "pendiente"}], "criterios_finalizacion": ["x"]},
        "triage": {"diagnostico": "simulado", "veredicto_preliminar": "normal", "justificacion_veredicto": "s"},
        "selector": {"usar_cve": False, "razon": "simulado"},
        "mitigacion": {"comandos": []},
        "auditor": comunes,
        "agente_unico": dict(comunes, diagnostico="simulado", comandos_mitigacion=[]),
    }


def hijo(sistema: str, dataset: str, case_id: str, entrada: str, salida: str) -> int:
    import importlib

    from src.experimentation.runtime.consultas_externas import RegistroConsultas, instalar
    registro = RegistroConsultas()
    instalar(registro)
    import src.config as config
    import src.telemetry as telemetria
    simulado = os.environ.get("NODEX_EVALUACION_SIMULADA") == "1"
    respuestas = _respuestas_simuladas(dataset)
    prompts, observaciones = [], []

    def envolver(modulo, nodo):
        original = modulo.llm_json

        def observado(prompt, system=None, *args, **kwargs):
            prompts.append({"nodo": nodo, "system_sha256": sha_texto(system), "prompt_sha256": sha_texto(prompt),
                            "system_chars": len(system or ""), "prompt_chars": len(prompt or "")})
            medicion = telemetria._medicion.get()
            antes = len(medicion["calls"]) if medicion else 0
            try:
                if simulado:
                    return json.loads(json.dumps(respuestas[nodo]))
                return original(prompt, system, *args, **kwargs)
            finally:
                medicion = telemetria._medicion.get()
                despues = len(medicion["calls"]) if medicion else 0
                observaciones.append({"nodo": nodo, "llamadas": list(range(antes, despues))})
        modulo.llm_json = observado

    contenido = (ROOT / entrada).read_text(encoding="utf-8")
    documento = {"case_id": case_id, "dataset": dataset, "sistema": sistema, "entrada": entrada,
                 "entrada_sha256": sha_texto(contenido), "simulado": simulado, "inicio_utc": utc()}
    inicio = time.perf_counter()
    if sistema == "gemini_directo":
        from src.experimentation.runners import gemini_directo as gd
        resultado = gd.ejecutar(contenido, dataset, llamar=(
            (lambda s: _gemini_simulado(s, dataset)) if simulado else None))
        prompts.append({"nodo": "gemini_directo", "system_sha256": None, "prompt_sha256": resultado.get("solicitud_sha256"),
                        "prompt_v2_1_sha256": gd.PROMPT_SHA256, "prompt_chars": resultado.get("solicitud_caracteres")})
        documento["resultado"] = resultado
        llamadas = (resultado.get("telemetria") or {}).get("llm_calls") or []
    elif sistema == "nodex":
        for nombre, nodo in NODOS.items():
            envolver(importlib.import_module(f"src.agents.{nombre}"), nodo)
        from src import pipeline
        estado = pipeline.analizar_lote(contenido, thread_id=f"final__{case_id}")
        estado.pop("raw_samples", None)
        documento["estado"] = estado
        llamadas = (estado.get("telemetry") or {}).get("llm_calls") or []
    else:
        import src.single_agent as single
        from tools.single_agent_runner import recuperar_candidatos
        envolver(single, "agente_unico")
        candidatos = recuperar_candidatos(contenido)["candidatos"]
        estado = single.analizar_lote_agente_unico(contenido, thread_id=f"final_unico__{case_id}",
                                                   tecnicas_mitre=candidatos)
        estado.pop("raw_samples", None)
        documento["estado"] = estado
        llamadas = (estado.get("telemetry") or {}).get("llm_calls") or []
    for o in observaciones:
        o["tokens"] = [{k: llamadas[i].get(k) for k in ("input_tokens", "output_tokens", "reasoning_tokens",
                                                       "model_version", "error")}
                       for i in o["llamadas"] if i < len(llamadas)]
    documento.update(
        segundos_pared_hijo=time.perf_counter() - inicio, fin_utc=utc(), prompts=prompts, observaciones=observaciones,
        usd=round(costo(llamadas), 6), llamadas_llm=len(llamadas),
        configuracion_efectiva={k: getattr(config, k) for k in sorted(dir(config))
                                if k.isupper() and not any(s in k for s in _SECRETOS)
                                and isinstance(getattr(config, k), (bool, int, float, str, type(None)))},
        consultas_externas=registro.a_lista())
    _escribir(salida, documento)
    return 0


def _gemini_simulado(solicitud: str, dataset: str):
    from types import SimpleNamespace
    cuerpo = {"diagnostico": "simulado", "hay_anomalia": False, "hay_incidente": False, "confianza": 0.5,
              "evaluacion": "simulado", "comandos_mitigacion": [], "eventos_reconstruidos": [],
              "secuencia_temporal": [], "tecnicas_atribuidas": []}
    texto = "```json\n" + json.dumps(cuerpo) + "\n```"
    return SimpleNamespace(text=texto, model_version="simulado", usage_metadata=SimpleNamespace(
        prompt_token_count=len(solicitud) // 2, candidates_token_count=100, thoughts_token_count=50,
        total_token_count=len(solicitud) // 2 + 150))


# --- clasificación de fallas ----------------------------------------------------------------------------

def eventos_de_energia(desde: datetime, hasta: datetime) -> list[dict]:
    """Suspensiones, reanudaciones y apagados de Windows entre dos instantes (vacío si no hay o no es Windows)."""
    if os.name != "nt":
        return []
    filtro = ("@{LogName='System'; Id=42,107,1,41,6008; StartTime=[datetime]'%s'; EndTime=[datetime]'%s'}"
              % (desde.astimezone().strftime("%Y-%m-%dT%H:%M:%S"), hasta.astimezone().strftime("%Y-%m-%dT%H:%M:%S")))
    comando = (f"Get-WinEvent -FilterHashtable {filtro} -ErrorAction SilentlyContinue | "
               "Where-Object { $_.ProviderName -match 'Kernel-Power|Power-Troubleshooter|EventLog' } | "
               "ForEach-Object { '{0}|{1}|{2}' -f $_.TimeCreated.ToString('s'), $_.Id, $_.ProviderName }")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", comando], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return [dict(zip(("hora", "id", "fuente"), l.split("|"))) for l in r.stdout.splitlines() if l.count("|") == 2]


def clasificar(documento: dict | None, codigo: int | None, tope_tiempo: bool, energia: list) -> tuple[str, str]:
    """`completa`, `falla_sistema`, `falla_infraestructura` o `credito_agotado`, con el motivo."""
    if energia:
        return "falla_infraestructura", f"suspensión o apagado del equipo durante la corrida: {energia}"
    if documento is None:
        return ("falla_sistema", "tope de tiempo del caso") if tope_tiempo else \
            ("falla_sistema", f"el proceso terminó con código {codigo} sin resultado")
    if documento["sistema"] == "gemini_directo":
        falla = documento["resultado"].get("falla")
        detalle = documento["resultado"].get("detalle_falla") or ""
        if falla == "credito_agotado":
            return "credito_agotado", detalle
        if falla == "infraestructura":
            return "falla_infraestructura", detalle
        if falla:
            return "falla_sistema", f"{falla}: {detalle}"
        return "completa", ""
    error = documento["estado"].get("_error_api")
    if not error:
        return "completa", ""
    texto = str(error)
    if "prepayment" in texto.lower() or "credits are depleted" in texto.lower():
        return "credito_agotado", texto
    if any(m in texto for m in _INFRA):
        return "falla_infraestructura", texto
    return "falla_sistema", texto


# --- lanzador ----------------------------------------------------------------------------------------------

class Despierto:
    """Pide a Windows no suspender por inactividad mientras corre; restaura al salir."""
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001

    def __enter__(self):
        if os.name == "nt":
            ctypes.windll.kernel32.SetThreadExecutionState(self.ES_CONTINUOUS | self.ES_SYSTEM_REQUIRED)
        return self

    def __exit__(self, *exc):
        if os.name == "nt":
            ctypes.windll.kernel32.SetThreadExecutionState(self.ES_CONTINUOUS)
        return False


def _matar_arbol(pid: int):
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)


def _entorno_base(simulado: bool) -> dict:
    from dotenv import dotenv_values
    base = {**os.environ, **{k: v for k, v in dotenv_values(ROOT / ".env").items() if v is not None}}
    if simulado:
        base = {k: v for k, v in base.items() if not any(s in k.upper() for s in _SECRETOS)}
        base["GEMINI_API_KEY"] = "simulado-sin-api"
        base["NODEX_EVALUACION_SIMULADA"] = "1"
    elif not (base.get("GEMINI_API_KEY") or base.get("GOOGLE_API_KEY")):
        raise SystemExit("Falta credencial Gemini")
    return base


def correr_caso(corrida: dict, salida: Path, base: dict) -> dict:
    from src.experimentation import campana
    congelada = _leer(CONFIG_CONGELADA)
    archivo = destino(salida, corrida)
    archivo.parent.mkdir(parents=True, exist_ok=True)
    if corrida.get("entrada_sha256_piloto") and sha_archivo(ROOT / corrida["entrada"]) != corrida["entrada_sha256_piloto"]:
        raise SystemExit(f"{corrida['case_id']}: la entrada del piloto cambió")
    with tempfile.TemporaryDirectory(prefix="eval_final_", ignore_cleanup_errors=True) as tmp:
        tmp = Path(tmp)
        shutil.copytree(MEMORIA / "chroma_snapshot", tmp / "chroma")
        entorno = campana.entorno_de_la_corrida(base, congelada, tmp / "chroma", tmp / "ip.json")
        entorno["MEMORIA_GRUPOS_PATH"] = str(MEMORIA_GRUPOS)
        inicio_utc, reloj, tope_tiempo, codigo = datetime.now(timezone.utc), time.perf_counter(), False, None
        proceso = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--hijo", corrida["sistema"],
                                    corrida["dataset"], corrida["case_id"], corrida["entrada"], str(archivo)],
                                   cwd=ROOT, env=entorno, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace")
        try:
            stdout, stderr = proceso.communicate(timeout=TOPE_SEGUNDOS_CASO)
            codigo = proceso.returncode
        except subprocess.TimeoutExpired:
            tope_tiempo = True
            _matar_arbol(proceso.pid)
            stdout, stderr = proceso.communicate()
        fin_utc = datetime.now(timezone.utc)
        archivo.with_suffix(".stderr.txt").write_text(stderr or "", encoding="utf-8")
    documento = _leer(archivo) if archivo.exists() else None
    energia = eventos_de_energia(inicio_utc, fin_utc)
    estado, motivo = clasificar(documento, codigo, tope_tiempo, energia)
    fila = {**{k: corrida[k] for k in ("etapa", "repeticion", "sistema", "dataset", "case_id", "confirmatorio")},
            "estado": estado, "motivo": motivo[:2000], "codigo": codigo, "inicio_utc": inicio_utc.isoformat(),
            "fin_utc": fin_utc.isoformat(), "segundos_pared": round(time.perf_counter() - reloj, 1),
            "usd": documento.get("usd") if documento else 0.0, "llamadas_llm": documento.get("llamadas_llm") if documento else None}
    if documento is not None:
        documento["ejecucion"] = fila
        _escribir(archivo, documento)
    return fila


def apartar(salida: Path, corrida: dict, intento) -> None:
    """Mueve (sin borrar) la corrida a `apartadas/`, para repetirla desde cero."""
    archivo = destino(salida, corrida)
    carpeta = salida / "apartadas" / corrida["etapa"] / corrida["sistema"]
    carpeta.mkdir(parents=True, exist_ok=True)
    for origen in (archivo, archivo.with_suffix(".stderr.txt")):
        if origen.exists():
            origen.replace(carpeta / f"{corrida['case_id']}__intento{intento}{''.join(origen.suffixes)}")


def gasto_registrado(salida: Path) -> float:
    total = 0.0
    for archivo in salida.rglob("*.json"):
        if archivo.name.startswith(("registro_", "informe_", "plan", "estado")):
            continue
        try:
            total += float(_leer(archivo).get("usd") or 0.0)
        except Exception:  # noqa: BLE001 - un archivo parcial no se cuenta
            pass
    return total


def informe_operativo(salida: Path, etapa: str) -> dict:
    """Casos completados, fallas, costo y tiempo de una etapa (desde los archivos). Sin métricas de calidad."""
    informe = {"etapa": etapa, "generado_utc": utc(), "sistemas": {}}
    for sistema in SISTEMAS:
        carpeta = salida / etapa / sistema
        if not carpeta.is_dir():
            continue
        filas = [d["ejecucion"] for d in (_leer(a) for a in sorted(carpeta.glob("*.json"))) if d.get("ejecucion")]
        apartadas = sorted((salida / "apartadas" / etapa / sistema).glob("*__intento*.json")) \
            if (salida / "apartadas" / etapa / sistema).is_dir() else []
        informe["sistemas"][sistema] = {
            "completas": sum(1 for f in filas if f["estado"] == "completa"),
            "fallas_del_sistema": sorted(f["case_id"] for f in filas if f["estado"] == "falla_sistema"),
            "corridas_apartadas_y_repetidas": [a.stem for a in apartadas],
            "usd": round(sum(f.get("usd") or 0 for f in filas), 4),
            "horas_de_pared": round(sum(f["segundos_pared"] for f in filas) / 3600, 2)}
    _escribir(salida / f"informe_operativo_{etapa}.json", informe)
    return informe


class Bitacora:
    """Log de consola, bitácora de incidentes y estado de la ejecución, en archivos de la carpeta de salida."""

    def __init__(self, salida: Path):
        self.salida = salida
        self.log_path = salida / "ejecucion.log"
        self.bitacora_path = salida / "bitacora_ejecucion.md"
        self.estado_path = salida / "estado.json"
        if not self.bitacora_path.exists():
            self.bitacora_path.write_text(
                "# Bitácora de la ejecución de la evaluación final\n\nHora local (America/Santiago). Incidentes "
                "registrados automáticamente por `tools/ejecutar_evaluacion_final.py`.\n\n"
                "| Hora | Etapa / sistema / caso | Incidente | Tratamiento |\n|---|---|---|---|\n", encoding="utf-8")

    @staticmethod
    def ahora():
        return datetime.now(ZoneInfo("America/Santiago")).strftime("%Y-%m-%d %H:%M:%S")

    def log(self, mensaje: str):
        linea = f"[{self.ahora()}] {mensaje}"
        print(linea, flush=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(linea + "\n")

    def incidente(self, donde: str, que: str, tratamiento: str):
        limpio = lambda s: str(s).replace("|", "/").replace("\n", " ")[:400]  # noqa: E731
        with self.bitacora_path.open("a", encoding="utf-8") as f:
            f.write(f"| {self.ahora()} | {limpio(donde)} | {limpio(que)} | {limpio(tratamiento)} |\n")
        self.log(f"INCIDENTE {donde}: {que} -> {tratamiento}")

    def estado(self) -> dict:
        return _leer(self.estado_path) if self.estado_path.exists() else {}

    def guardar(self, **cambios):
        estado = dict(self.estado(), **cambios, actualizado=self.ahora())
        _escribir(self.estado_path, estado)


def _clave(corrida: dict) -> str:
    return f"{corrida['etapa']}/{corrida['sistema']}/{corrida['case_id']}"


def ejecutar(tope: float, salida: Path, simulado: bool, casos: list[str] | None, repeticiones: int,
             piloto: bool) -> int:
    """Reanudable: omite las corridas terminadas; una corrida interrumpida se aparta y se repite desde cero.

    Se detiene solo ante crédito agotado o el tope de gasto. Las fallas de infraestructura se apartan y se
    repiten (con espera creciente) sin límite de intentos.
    """
    base = _entorno_base(simulado)
    salida.mkdir(parents=True, exist_ok=True)
    b = Bitacora(salida)
    corridas = plan(casos, repeticiones, piloto)
    previo = b.estado()
    b.log(f"Inicio: {len(corridas)} corridas planificadas, tope USD {tope}, salida {salida}")
    if previo.get("en_curso"):
        b.incidente(previo["en_curso"], f"corrida interrumpida (en curso desde {previo.get('en_curso_desde')}; "
                    "el proceso se detuvo antes de terminarla: corte, suspensión o cierre)",
                    "se aparta lo que haya dejado y se repite desde cero")
    if not simulado:
        try:
            verificar_api()
        except Exception as e:  # noqa: BLE001
            from src.experimentation.runners.gemini_directo import clasificar_error
            clase = clasificar_error(e)
            b.incidente("verificación de la API", f"{type(e).__name__}: {e}", "ejecución detenida antes de empezar")
            b.guardar(detenido=f"la API no respondió al iniciar ({clase})", en_curso=None)
            return 3 if clase == "credito_agotado" else 5
    registro = {"inicio_utc": utc(), "commit": git("rev-parse", "HEAD"),
                "tag": git("describe", "--tags", "--exact-match", "HEAD") or None,
                "rama": git("rev-parse", "--abbrev-ref", "HEAD"), "src_sin_cambios": not git("status", "--porcelain", "--", "src"),
                "simulado": simulado, "tope_usd": tope, "preregistro_sha256": sha_archivo(PREREGISTRO),
                "config_congelada": CONFIG_CONGELADA.relative_to(ROOT).as_posix(),
                "config_congelada_sha256": sha_archivo(CONFIG_CONGELADA),
                "memoria": MEMORIA.relative_to(ROOT).as_posix(),
                "memoria_manifiesto_sha256": sha_archivo(MEMORIA / "manifiesto.json"),
                "memoria_grupos_sha256": sha_archivo(MEMORIA_GRUPOS),
                "casos_final_verificacion_sha256": sha_archivo(CASOS_FINAL / "verificacion_regeneracion.json"),
                "exclusion_por_incidente": False, "corridas_planificadas": len(corridas), "filas": []}
    nombre_registro = salida / f"registro_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    gastado = gasto_registrado(salida)
    codigo_salida, etapa_actual, terminadas = 0, None, 0
    with Despierto():
        for corrida in corridas:
            if corrida["etapa"] != etapa_actual:
                if etapa_actual is not None:
                    b.log("Informe operativo " + json.dumps(informe_operativo(salida, etapa_actual), ensure_ascii=False))
                etapa_actual = corrida["etapa"]
            archivo = destino(salida, corrida)
            if archivo.exists():
                previo_doc = _leer(archivo)
                if (previo_doc.get("ejecucion") or {}).get("estado") in ("completa", "falla_sistema"):
                    terminadas += 1
                    continue
                # Resultado sin cierre del lanzador: la corrida se interrumpió.
                apartar(salida, corrida, f"interrumpida_{datetime.now().strftime('%Y%m%dT%H%M%S')}")
                b.incidente(_clave(corrida), "resultado sin cierre del lanzador (corrida interrumpida)",
                            "apartada en apartadas/ y repetida desde cero")
            elif archivo.with_suffix(".stderr.txt").exists():
                apartar(salida, corrida, f"interrumpida_{datetime.now().strftime('%Y%m%dT%H%M%S')}")
            intento = 0
            while True:
                intento += 1
                cota = COTA[(corrida["sistema"], corrida["dataset"])]
                if gastado + cota > tope:
                    registro["detenido"] = f"tope de gasto USD {tope} antes de {_clave(corrida)}"
                    b.incidente(_clave(corrida), f"gasto USD {gastado:.2f} + cota {cota} supera el tope", "ejecución detenida")
                    codigo_salida = 2
                    break
                b.guardar(en_curso=_clave(corrida), en_curso_desde=b.ahora(), gasto_usd=round(gastado, 4),
                          terminadas=terminadas, total=len(corridas), detenido=None)
                fila = correr_caso(corrida, salida, base)
                fila["intento"] = intento
                gastado += fila["usd"] or 0.0
                registro["filas"].append(fila)
                b.log(f"{_clave(corrida)}: {fila['estado']} (intento {intento}, USD {fila['usd']}, "
                      f"{fila['segundos_pared']} s, gasto acumulado USD {gastado:.2f}) {fila['motivo'][:200]}")
                if fila["estado"] in ("falla_infraestructura", "credito_agotado"):
                    apartar(salida, corrida, intento)
                if fila["estado"] == "credito_agotado":
                    registro["detenido"] = f"crédito agotado en {_clave(corrida)}"
                    b.incidente(_clave(corrida), "crédito agotado (402)", "corrida apartada; ejecución detenida: recargar y relanzar")
                    codigo_salida = 3
                    break
                if fila["estado"] == "falla_infraestructura":
                    espera = 0 if simulado else min(600, 30 * 2 ** (intento - 1))
                    b.incidente(_clave(corrida), f"falla de infraestructura: {fila['motivo']}",
                                f"apartada; se repite desde cero en {espera} s")
                    time.sleep(espera)
                    continue
                if fila["estado"] == "falla_sistema":
                    b.incidente(_clave(corrida), f"falla del sistema: {fila['motivo']}", "registrada; no se repite")
                terminadas += 1
                break
            b.guardar(en_curso=None, gasto_usd=round(gastado, 4), terminadas=terminadas, total=len(corridas))
            _escribir(nombre_registro, dict(registro, gasto_usd=round(gastado, 4)))
            if codigo_salida:
                break
        if etapa_actual is not None:
            b.log("Informe operativo " + json.dumps(informe_operativo(salida, etapa_actual), ensure_ascii=False))
    registro.update(fin_utc=utc(), gasto_usd=round(gastado, 4))
    _escribir(nombre_registro, registro)
    if any(c["etapa"] == "piloto_no_confirmatorio" for c in corridas):
        (salida / "piloto_no_confirmatorio").mkdir(parents=True, exist_ok=True)
        (salida / "piloto_no_confirmatorio" / "NO_CONFIRMATORIO.md").write_text(
            "NODEX final sobre los 12 casos del piloto (1 repetición). **No confirmatorio**: estos casos se usaron "
            "en el diagnóstico. Solo para mostrar la evolución piloto → final (preregistro, secciones 4 y 7).\n",
            encoding="utf-8")
    b.guardar(en_curso=None, gasto_usd=round(gastado, 4), terminadas=terminadas, total=len(corridas),
              detenido=registro.get("detenido"), terminado=not registro.get("detenido") and terminadas == len(corridas))
    b.log(f"Fin: {terminadas}/{len(corridas)} corridas terminadas, gasto USD {gastado:.4f}"
          + (f" — DETENIDO: {registro['detenido']}" if registro.get("detenido") else " — TODO TERMINADO"))
    return codigo_salida


def preflight_gemini() -> dict:
    """Gemini directo sin modelo, sobre los 60 casos: solicitud exacta, columnas de etiqueta e identificadores."""
    from src.experimentation.runners import gemini_directo as gd
    casos = []
    for c in plan(repeticiones=1, piloto=False):
        if c["sistema"] != "gemini_directo":
            continue
        contenido = (ROOT / c["entrada"]).read_text(encoding="utf-8")
        solicitud = gd.construir_solicitud(contenido)
        lineas = contenido.splitlines()
        casos.append({"case_id": c["case_id"], "dataset": c["dataset"], "archivo_caracteres": len(contenido),
                      "solicitud_caracteres": len(solicitud), "solicitud_sha256": gd.sha256(solicitud),
                      "archivo_completo_en_la_solicitud": solicitud.endswith(contenido),
                      "columnas_de_etiqueta": gd.columnas_prohibidas(contenido, c["dataset"]),
                      "identificadores_citables": len(gd.identificadores(contenido, c["dataset"])),
                      "lineas": len(lineas), "lineas_vacias_intermedias": sum(1 for l in lineas[:-1] if not l.strip())})
    resultado = {"prompt_sha256": gd.PROMPT_SHA256, "prompt_caracteres": len(gd.prompt_congelado()), "casos": casos}
    _escribir(CASOS_FINAL / "preflight_gemini_directo.json", resultado)
    return resultado


def verificar_api() -> int:
    """Una llamada mínima al modelo congelado para confirmar que la API responde."""
    from dotenv import dotenv_values
    from google import genai
    from google.genai import types
    congelada = _leer(CONFIG_CONGELADA)["parametros"]
    clave = dotenv_values(ROOT / ".env").get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    cliente = genai.Client(api_key=clave)
    r = cliente.models.generate_content(model=congelada["LLM_MODEL_PRIMARY"], contents="Responde solo: OK",
                                        config=types.GenerateContentConfig(temperature=0))
    uso = r.usage_metadata
    print(json.dumps({"modelo": congelada["LLM_MODEL_PRIMARY"], "version": getattr(r, "model_version", None),
                      "respuesta": (r.text or "").strip()[:40], "tokens_entrada": uso.prompt_token_count,
                      "tokens_salida": uso.candidates_token_count,
                      "tokens_razonamiento": getattr(uso, "thoughts_token_count", None)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--plan", action="store_true")
    p.add_argument("--verificar-api", action="store_true")
    p.add_argument("--preflight-gemini", action="store_true")
    p.add_argument("--ejecutar", action="store_true")
    p.add_argument("--simulado", action="store_true")
    p.add_argument("--tope", type=float, default=40.0)
    p.add_argument("--salida", type=Path, default=SALIDA)
    p.add_argument("--casos", nargs="*")
    p.add_argument("--repeticiones", type=int, default=REPETICIONES)
    p.add_argument("--sin-piloto", action="store_true")
    p.add_argument("--hijo", nargs=5)
    a = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    if a.hijo:
        raise SystemExit(hijo(*a.hijo))
    if a.plan:
        corridas = plan(a.casos, a.repeticiones, not a.sin_piloto)
        print(len(corridas), "corridas;", sorted({(c["etapa"], c["sistema"]) for c in corridas}))
    elif a.preflight_gemini:
        r = preflight_gemini()
        print(json.dumps({"casos": len(r["casos"]), "prompt_sha256": r["prompt_sha256"]}, ensure_ascii=False))
    elif a.verificar_api:
        raise SystemExit(verificar_api())
    elif a.ejecutar or a.simulado:
        if a.simulado and a.salida.resolve() == SALIDA.resolve():
            raise SystemExit("--simulado necesita una --salida distinta de la carpeta de la evaluación")
        raise SystemExit(ejecutar(a.tope, a.salida, a.simulado, a.casos, a.repeticiones, not a.sin_piloto))
    else:
        p.print_help()
