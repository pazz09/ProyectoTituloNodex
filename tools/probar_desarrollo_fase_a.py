"""Prueba real de la Fase A de NODEX final sobre casos de DESARROLLO (nunca de evaluación).

    python tools/probar_desarrollo_fase_a.py --ejecutar

Cada caso corre en un proceso propio con la configuración de evaluación del piloto
(`gemini-3.8-flash`, temperatura 0, sin respaldo, sin reputación externa), una copia desechable de
`experiments/knowledge/chroma_v2` (697 técnicas MITRE, sin históricos: los del RAG enriquecido salen
de ventanas de desarrollo y podrían recuperarse a sí mismos), caché de IP vacía y red bloqueada con
registro de intentos. Tope de gasto acumulado configurable (USD 1 por omisión), verificado antes de
cada caso con la cota máxima por dataset.

Para medir tokens por nodo, el `llm_json` de cada agente se envuelve SOLO para observar: anota qué
llamadas de la telemetría hizo el nodo y el texto enviado; llama a la función original con los mismos
argumentos y devuelve el mismo objeto. Los resultados van a `experiments/desarrollo_fase_a/<fecha>/`.
"""
from __future__ import annotations

import argparse
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

CASOS = [("bgl", "bgl_des_balanceado_0000"), ("bgl", "bgl_des_natural_0010"),
         ("uwf", "uwf_des_visible_0000"), ("uwf", "uwf_des_visible_0008"),
         ("uwf", "uwf_des_sigiloso_0000")]
#: Cota máxima por caso usada antes de lanzar (peor caso estimado con replanificación, con margen).
COTA_POR_DATASET = {"bgl": 0.06, "uwf": 0.30}
NODOS = {"agente_planificador": "planificador", "agente_analista_triage": "triage",
         "agente_selector_herramientas": "selector", "agente_ingeniero_mitigacion": "mitigacion",
         "agente_auditor_final": "auditor"}
SEMILLA = ROOT / "experiments" / "knowledge" / "chroma_v2"
CONFIG_REFERENCIA = ROOT / "experiments" / "config" / "config_oficial-12casos-r1-20261028.json"
PRECIO = {"entrada": 0.75, "salida": 3.75}       # USD por millón, vigente hasta 2026-12-31


def utc():
    return datetime.now(timezone.utc).isoformat()


def costo(llamadas):
    entrada = sum(c.get("input_tokens") or 0 for c in llamadas)
    salida = sum((c.get("output_tokens") or 0) + (c.get("reasoning_tokens") or 0) for c in llamadas)
    return (entrada * PRECIO["entrada"] + salida * PRECIO["salida"]) / 1e6


# --- proceso hijo ----------------------------------------------------------------

def hijo(dataset, case_id, salida):
    """Corre NODEX sobre un caso. **Llama al modelo.**"""
    from src.experimentation.runtime.consultas_externas import RegistroConsultas, instalar
    registro = RegistroConsultas()
    instalar(registro)
    import src.telemetry as telemetria
    from src import pipeline
    import importlib

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
                                      "prompt_chars": len(prompt or ""), "system_chars": len(system or ""),
                                      "prompt": prompt, "system": system})
        modulo.llm_json = observado

    for nombre, nodo in NODOS.items():
        envolver(importlib.import_module(f"src.agents.{nombre}"), nodo)

    contenido = (ROOT / "experiments" / "cases" / dataset / "desarrollo"
                 / f"{case_id}.{'log' if dataset == 'bgl' else 'csv'}").read_text(encoding="utf-8")
    inicio = time.perf_counter()
    estado = pipeline.analizar_lote(contenido, thread_id=f"desarrollo_fase_a__{case_id}")
    segundos = time.perf_counter() - inicio
    llamadas = (estado.get("telemetry") or {}).get("llm_calls") or []
    for o in observaciones:
        o["tokens"] = [{k: llamadas[i].get(k) for k in ("input_tokens", "output_tokens", "reasoning_tokens",
                                                       "model", "model_version", "error")}
                       for i in o["llamadas"] if i < len(llamadas)]
    estado.pop("raw_samples", None)
    Path(salida).write_text(json.dumps({"case_id": case_id, "dataset": dataset, "segundos_pared_hijo": segundos,
                                        "estado": estado, "observaciones": observaciones,
                                        "consultas_externas": registro.a_lista()},
                                       ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0


# --- lanzador -----------------------------------------------------------------------

def ejecutar(tope):
    from dotenv import dotenv_values
    from src.experimentation import campana

    congelada = json.loads(CONFIG_REFERENCIA.read_text(encoding="utf-8"))
    base = {**os.environ, **{k: v for k, v in dotenv_values(ROOT / ".env").items() if v is not None}}
    if not (base.get("GEMINI_API_KEY") or base.get("GOOGLE_API_KEY")):
        raise SystemExit("Falta credencial Gemini")
    carpeta = ROOT / "experiments" / "desarrollo_fase_a" / datetime.now(ZoneInfo("America/Santiago")).strftime("%Y%m%d")
    carpeta.mkdir(parents=True, exist_ok=True)
    registro = {"inicio_utc": utc(), "tope_usd": tope, "base_conocimiento": "experiments/knowledge/chroma_v2 (copia por caso)",
                "parametros": congelada["parametros"], "casos": []}
    gastado = 0.0
    for dataset, case_id in CASOS:
        destino = carpeta / f"{case_id}.json"
        if destino.exists():
            print(f"Omitido (ya existe): {case_id}", flush=True)
            datos = json.loads(destino.read_text(encoding="utf-8"))
            gastado += costo((datos["estado"].get("telemetry") or {}).get("llm_calls") or [])
            continue
        if gastado + COTA_POR_DATASET[dataset] > tope:
            print(f"Detenido antes de {case_id}: gasto {gastado:.4f} + cota {COTA_POR_DATASET[dataset]} > {tope}", flush=True)
            registro["detenido_por_tope"] = case_id
            break
        with tempfile.TemporaryDirectory(prefix="fase_a_", ignore_cleanup_errors=True) as tmp:
            tmp = Path(tmp)
            shutil.copytree(SEMILLA, tmp / "chroma")
            entorno = campana.entorno_de_la_corrida(base, congelada, tmp / "chroma", tmp / "ip.json")
            print(f"Iniciando {case_id}", flush=True)
            reloj = time.perf_counter()
            r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--hijo", dataset, case_id, str(destino)],
                               cwd=ROOT, env=entorno, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=7200)
            (carpeta / f"{case_id}.stdout.txt").write_text(r.stdout, encoding="utf-8")
            (carpeta / f"{case_id}.stderr.txt").write_text(r.stderr, encoding="utf-8")
        fila = {"case_id": case_id, "codigo": r.returncode, "segundos_pared": round(time.perf_counter() - reloj, 1)}
        if destino.exists():
            llamadas = (json.loads(destino.read_text(encoding="utf-8"))["estado"].get("telemetry") or {}).get("llm_calls") or []
            fila.update(usd=round(costo(llamadas), 5), llamadas=len(llamadas),
                        versiones=sorted({c.get("model_version") for c in llamadas if c.get("model_version")}))
            gastado += fila["usd"]
        registro["casos"].append(fila)
        print(f"Terminó {case_id}: {fila}", flush=True)
    registro.update(fin_utc=utc(), gasto_usd=round(gastado, 5))
    (carpeta / f"registro_{datetime.now(timezone.utc).strftime('%H%M%S')}.json").write_text(
        json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Gasto total: USD {gastado:.4f}", flush=True)
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ejecutar", action="store_true")
    p.add_argument("--tope", type=float, default=1.0)
    p.add_argument("--hijo", nargs=3)
    a = p.parse_args()
    if a.hijo:
        raise SystemExit(hijo(*a.hijo))
    if a.ejecutar:
        raise SystemExit(ejecutar(a.tope))
    print("Sin --ejecutar no se llama al modelo. Casos:", [c for _, c in CASOS])
