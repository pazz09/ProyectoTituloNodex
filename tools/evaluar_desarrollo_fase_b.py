"""Evaluación de DESARROLLO de NODEX final (Fase B) y del agente único. Nunca usa la partición de evaluación.

    python tools/evaluar_desarrollo_fase_b.py --ejecutar                 # NODEX y agente único, 48 + 48
    python tools/evaluar_desarrollo_fase_b.py --ejecutar --arquitectura nodex

Configuración de evaluación del piloto (`gemini-3.8-flash`, temperatura 0, sin respaldo, sin
reputación externa, red bloqueada con registro de intentos), un proceso por caso y una copia
desechable de la memoria `experiments/knowledge/rag_enriquecido_v2` (56 patrones + 697 técnicas
MITRE) por caso. El sistema excluye por sí mismo los patrones que comparten registros fuente con el
caso (validación cruzada dejando uno fuera).

**Exclusión por incidente (`--excluir-mismo-incidente`, activada por defecto).** Control del ARNÉS
experimental, no del sistema: en desarrollo, un caso UWF malicioso podría recuperar otro incidente del
mismo atacante (UWF tiene solo 10 IP atacantes). Para cada caso UWF malicioso se excluyen además los
patrones cuyo incidente comparte IP de origen atacante y táctica con el incidente del caso (datos del
ground truth de DESARROLLO). Se aplica igual a NODEX y al agente único y queda registrada por caso.

Tokens por nodo: el `llm_json` de cada agente se envuelve solo para observar. Tope de gasto conjunto
(USD 15 por omisión), verificado antes de cada caso con la cota máxima de su celda. Los resultados
registran el commit evaluado.
"""
from __future__ import annotations

import argparse
import csv
import io
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

MEMORIA = ROOT / "experiments/knowledge/rag_enriquecido_v2"
CONFIG_REFERENCIA = ROOT / "experiments/config/config_oficial-12casos-r1-20261028.json"
PRECIO = {"entrada": 0.75, "salida": 3.75}
COTA = {("nodex", "bgl"): 0.08, ("nodex", "uwf"): 0.35, ("agente_unico", "bgl"): 0.04,
        ("agente_unico", "uwf"): 0.20}
NODOS = {"agente_planificador": "planificador", "agente_analista_triage": "triage",
         "agente_cazador": "cazador", "agente_selector_herramientas": "selector",
         "agente_ingeniero_mitigacion": "mitigacion", "agente_auditor_final": "auditor"}


def utc():
    return datetime.now(timezone.utc).isoformat()


def costo(llamadas):
    entrada = sum(c.get("input_tokens") or 0 for c in llamadas)
    salida = sum((c.get("output_tokens") or 0) + (c.get("reasoning_tokens") or 0) for c in llamadas)
    return (entrada * PRECIO["entrada"] + salida * PRECIO["salida"]) / 1e6


def casos_de_desarrollo():
    return [(ds, f.stem) for ds in ("bgl", "uwf")
            for f in sorted((ROOT / "experiments/cases" / ds / "desarrollo").glob("*.json"))]


# --- exclusión por incidente (arnés) -------------------------------------------------

def incidente_de_caso_uwf(case_id: str) -> dict | None:
    """IP(s) de origen y tácticas del incidente de un caso UWF de desarrollo (None si es benigno)."""
    gt = json.loads((ROOT / "experiments/ground_truth/uwf/desarrollo" / f"{case_id}.json").read_text(encoding="utf-8"))
    nucleo = set(gt.get("core_event_uids") or [])
    if not nucleo:
        return None
    texto = (ROOT / "experiments/cases/uwf/desarrollo" / f"{case_id}.csv").read_text(encoding="utf-8")
    ips = {f["src_ip_zeek"] for f in csv.DictReader(io.StringIO(texto)) if f["uid"] in nucleo}
    tacticas = {t for r in gt.get("referencias_mitre") or [] if r.get("nivel") == "tactica"
                for t in str(r["id"]).split("|")}
    return {"ips": sorted(ips), "tacticas": sorted(tacticas)}


def incidentes_de_patrones() -> dict:
    """Incidente (IP y tácticas) de cada patrón malicioso de la memoria."""
    manifiesto = json.loads((MEMORIA / "manifiesto.json").read_text(encoding="utf-8"))
    salida = {}
    for p in manifiesto["casos"]:
        if p["dataset"] != "uwf" or p["etiqueta"] != "malicioso":
            continue
        if p["origen"] == "caso_desarrollo":
            salida[p["historical_case_id"]] = incidente_de_caso_uwf(p["historical_case_id"])
        else:
            incidente = p["origen"].split(":", 1)[1]          # shard__Tactica__IP__nnnn
            _, tactica, ip, _ = incidente.split("__")
            salida[p["historical_case_id"]] = {"ips": [ip], "tacticas": tactica.split("|")}
    return salida


def excluir_por_incidente(case_id: str, dataset: str, patrones: dict) -> list[str]:
    if dataset != "uwf":
        return []
    propio = incidente_de_caso_uwf(case_id)
    if not propio:
        return []
    return sorted(pid for pid, inc in patrones.items() if pid != case_id and inc
                  and set(inc["ips"]) & set(propio["ips"]) and set(inc["tacticas"]) & set(propio["tacticas"]))


# --- proceso hijo -------------------------------------------------------------------------

def _instalar_exclusion(ruta: str):
    """Envuelve la consulta histórica para excluir también los patrones del mismo incidente (arnés)."""
    import src.tools.memoria_historica as mh
    excluir = set(json.loads(Path(ruta).read_text(encoding="utf-8")))
    original = mh.consultar_historicos

    def con_exclusion(coleccion, representacion, huellas, k):
        total = coleccion.count() if coleccion is not None else 0
        r = original(coleccion, representacion, huellas, total)
        r["excluidos_mismo_incidente"] = [c["id"] for c in r["casos"] if c["id"] in excluir]
        r["casos"] = [c for c in r["casos"] if c["id"] not in excluir][:k]
        r["exclusion_por_incidente_activa"] = True
        return r
    mh.consultar_historicos = con_exclusion


def hijo(arquitectura, dataset, case_id, salida, exclusion):
    from src.experimentation.runtime.consultas_externas import RegistroConsultas, instalar
    registro = RegistroConsultas()
    instalar(registro)
    if exclusion != "-":
        _instalar_exclusion(exclusion)
    import importlib
    import src.telemetry as telemetria
    observaciones = []

    def envolver(modulo, nodo):
        original = modulo.llm_json

        def observado(prompt, system=None, *args, **kwargs):
            medicion = telemetria._medicion.get()
            antes = len(medicion["calls"]) if medicion else 0
            try:
                return original(prompt, system, *args, **kwargs)
            finally:
                medicion = telemetria._medicion.get()
                despues = len(medicion["calls"]) if medicion else 0
                observaciones.append({"nodo": nodo, "llamadas": list(range(antes, despues)),
                                      "prompt_chars": len(prompt or ""), "system_chars": len(system or "")})
        modulo.llm_json = observado

    contenido = (ROOT / "experiments/cases" / dataset / "desarrollo"
                 / f"{case_id}.{'log' if dataset == 'bgl' else 'csv'}").read_text(encoding="utf-8")
    inicio = time.perf_counter()
    if arquitectura == "nodex":
        for nombre, nodo in NODOS.items():
            envolver(importlib.import_module(f"src.agents.{nombre}"), nodo)
        from src import pipeline
        estado = pipeline.analizar_lote(contenido, thread_id=f"fase_b__{case_id}")
    else:
        import src.single_agent as single
        from tools.single_agent_runner import recuperar_candidatos
        envolver(single, "agente_unico")
        candidatos = recuperar_candidatos(contenido)["candidatos"]      # su consulta actual sobre el resumen
        estado = single.analizar_lote_agente_unico(contenido, thread_id=f"fase_b_unico__{case_id}",
                                                   tecnicas_mitre=candidatos)
    segundos = time.perf_counter() - inicio
    llamadas = (estado.get("telemetry") or {}).get("llm_calls") or []
    for o in observaciones:
        o["tokens"] = [{k: llamadas[i].get(k) for k in ("input_tokens", "output_tokens", "reasoning_tokens",
                                                       "model_version", "error")}
                       for i in o["llamadas"] if i < len(llamadas)]
    estado.pop("raw_samples", None)
    Path(salida).write_text(json.dumps({"case_id": case_id, "dataset": dataset, "arquitectura": arquitectura,
                                        "segundos_pared_hijo": segundos, "estado": estado,
                                        "observaciones": observaciones, "consultas_externas": registro.a_lista()},
                                       ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0


# --- lanzador ---------------------------------------------------------------------------------

def git(*args):
    return subprocess.run(["git", "-c", "core.longpaths=true", "-C", str(ROOT), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout.strip()


def ejecutar(arquitecturas, tope, excluir_incidente, nombre_carpeta):
    from dotenv import dotenv_values
    from src.experimentation import campana
    congelada = json.loads(CONFIG_REFERENCIA.read_text(encoding="utf-8"))
    base = {**os.environ, **{k: v for k, v in dotenv_values(ROOT / ".env").items() if v is not None}}
    if not (base.get("GEMINI_API_KEY") or base.get("GOOGLE_API_KEY")):
        raise SystemExit("Falta credencial Gemini")
    carpeta = ROOT / "experiments" / nombre_carpeta / datetime.now(ZoneInfo("America/Santiago")).strftime("%Y%m%d")
    carpeta.mkdir(parents=True, exist_ok=True)
    patrones = incidentes_de_patrones() if excluir_incidente else {}
    registro = {"inicio_utc": utc(), "commit": git("rev-parse", "HEAD"), "rama": git("rev-parse", "--abbrev-ref", "HEAD"),
                "src_sin_cambios": not git("status", "--porcelain", "--", "src"), "tope_usd": tope,
                "memoria": MEMORIA.relative_to(ROOT).as_posix(),
                "memoria_manifiesto_sha256": __import__("hashlib").sha256((MEMORIA / "manifiesto.json").read_bytes()).hexdigest(),
                "exclusion_por_solapamiento": "del sistema (siempre)",
                "exclusion_por_incidente": excluir_incidente,
                "criterio_exclusion_por_incidente": "mismo IP de origen atacante y al menos una táctica en común (GT de desarrollo)",
                "parametros": congelada["parametros"], "arquitecturas": arquitecturas, "casos": []}
    gastado = 0.0
    for arquitectura in arquitecturas:
        (carpeta / arquitectura).mkdir(exist_ok=True)
        for dataset, case_id in casos_de_desarrollo():
            destino = carpeta / arquitectura / f"{case_id}.json"
            if destino.exists():
                datos = json.loads(destino.read_text(encoding="utf-8"))
                gastado += costo((datos["estado"].get("telemetry") or {}).get("llm_calls") or [])
                print(f"Omitido (ya existe): {arquitectura} {case_id}", flush=True)
                continue
            if gastado + COTA[(arquitectura, dataset)] > tope:
                print(f"Detenido antes de {arquitectura} {case_id}: gasto {gastado:.4f}", flush=True)
                registro["detenido_por_tope"] = f"{arquitectura}:{case_id}"
                break
            excluidos = excluir_por_incidente(case_id, dataset, patrones) if excluir_incidente else []
            with tempfile.TemporaryDirectory(prefix="fase_b_", ignore_cleanup_errors=True) as tmp:
                tmp = Path(tmp)
                shutil.copytree(MEMORIA / "chroma_snapshot", tmp / "chroma")
                ruta_exclusion = "-"
                if excluir_incidente:
                    ruta_exclusion = str(tmp / "excluir.json")
                    Path(ruta_exclusion).write_text(json.dumps(excluidos), encoding="utf-8")
                entorno = campana.entorno_de_la_corrida(base, congelada, tmp / "chroma", tmp / "ip.json")
                reloj = time.perf_counter()
                r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--hijo", arquitectura, dataset,
                                    case_id, str(destino), ruta_exclusion], cwd=ROOT, env=entorno,
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=7200)
                (carpeta / arquitectura / f"{case_id}.stderr.txt").write_text(r.stderr, encoding="utf-8")
            fila = {"arquitectura": arquitectura, "case_id": case_id, "codigo": r.returncode,
                    "segundos_pared": round(time.perf_counter() - reloj, 1), "excluidos_mismo_incidente_previstos": excluidos}
            if destino.exists():
                llamadas = (json.loads(destino.read_text(encoding="utf-8"))["estado"].get("telemetry") or {}).get("llm_calls") or []
                fila.update(usd=round(costo(llamadas), 5), llamadas=len(llamadas),
                            versiones=sorted({c.get("model_version") for c in llamadas if c.get("model_version")}))
                gastado += fila["usd"]
            registro["casos"].append(fila)
            print(f"Terminó {arquitectura} {case_id}: código {r.returncode}, USD {fila.get('usd')}, "
                  f"llamadas {fila.get('llamadas')}", flush=True)
        if registro.get("detenido_por_tope"):
            break
    registro.update(fin_utc=utc(), gasto_usd=round(gastado, 5))
    (carpeta / f"registro_{datetime.now(timezone.utc).strftime('%H%M%S')}.json").write_text(
        json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Gasto total: USD {gastado:.4f}", flush=True)
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ejecutar", action="store_true")
    p.add_argument("--arquitectura", choices=("nodex", "agente_unico", "ambas"), default="ambas")
    p.add_argument("--tope", type=float, default=15.0)
    p.add_argument("--excluir-mismo-incidente", dest="excluir", action="store_true", default=True)
    p.add_argument("--sin-excluir-mismo-incidente", dest="excluir", action="store_false")
    p.add_argument("--carpeta", default="desarrollo_fase_b")
    p.add_argument("--hijo", nargs=5)
    a = p.parse_args()
    if a.hijo:
        raise SystemExit(hijo(*a.hijo))
    if a.ejecutar:
        arqs = ["nodex", "agente_unico"] if a.arquitectura == "ambas" else [a.arquitectura]
        raise SystemExit(ejecutar(arqs, a.tope, a.excluir, a.carpeta))
    print("Sin --ejecutar no se llama al modelo.", len(casos_de_desarrollo()), "casos de desarrollo.")
