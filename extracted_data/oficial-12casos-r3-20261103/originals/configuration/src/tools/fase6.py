"""Orquestación y verificación del cierre reproducible de la Fase 6.

Uso recomendado, sobre un commit limpio y con ``GEMINI_API_KEY`` activa::

    python -m src.tools.fase6 --modo todo

También permite ejecutar por separado ``baselines`` o ``multiagente`` y
verificar artefactos ya existentes con ``verificar``. El manifiesto final
solo se escribe si existen seis corridas completas, limpias, trazables y del
mismo commit.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.tools.provenance import estado_git, sha256_archivo


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
MANIFEST = RESULTS / "fase6_manifest.json"

ESCENARIOS = {
    "baseline_bgl": ("baseline", "bgl", None),
    "baseline_hdfs_balanceado": ("baseline", "hdfs", 0.5),
    "baseline_hdfs_real": ("baseline", "hdfs", 0.031),
    "multiagente_bgl": ("multiagente", "bgl", None),
    "multiagente_hdfs_balanceado": ("multiagente", "hdfs", 0.5),
    "multiagente_hdfs_real": ("multiagente", "hdfs", 0.031),
}


def _tipo(documento: dict) -> str:
    return "baseline" if documento.get("baseline") == "reglas_deterministicas" else "multiagente"


def _prop_equivalente(real, esperada) -> bool:
    if esperada is None:
        return real is None
    try:
        return abs(float(real) - esperada) < 1e-9
    except (TypeError, ValueError):
        return False


def _valido(documento: dict, tipo: str) -> list[str]:
    errores = []
    if documento.get("evaluation_status") != "complete":
        errores.append("evaluation_status no es complete")
    if documento.get("result_schema_version") != "2.0":
        errores.append("result_schema_version distinto de 2.0")
    if documento.get("motor_preprocesamiento") != "heterogeneo":
        errores.append("motor distinto de heterogeneo")
    if not documento.get("commit"):
        errores.append("commit ausente")
    if documento.get("working_tree_dirty") is not False:
        errores.append("árbol de trabajo no limpio")
    if not documento.get("dataset_provenance"):
        errores.append("hashes de dataset ausentes")
    metricas = documento.get("metricas") or {}
    if metricas.get("n_fallidos") != 0:
        errores.append("la corrida contiene lotes fallidos")
    if tipo == "multiagente" and not documento.get("llm_config"):
        errores.append("configuración LLM ausente")
    return errores


def verificar_cierre(results_dir: Path = RESULTS) -> dict:
    """Selecciona la corrida válida más reciente de cada escenario."""
    candidatos: list[tuple[Path, dict]] = []
    for path in results_dir.glob("*.json"):
        if path.name == MANIFEST.name:
            continue
        try:
            candidatos.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError):
            continue

    seleccionados = {}
    diagnostico = {}
    for nombre, (tipo, dataset, prop) in ESCENARIOS.items():
        coincidentes = [
            (path, doc) for path, doc in candidatos
            if _tipo(doc) == tipo
            and doc.get("dataset") == dataset
            and _prop_equivalente(doc.get("prop_positivos"), prop)
        ]
        coincidentes.sort(
            key=lambda item: item[1].get("generated_at_utc") or "",
            reverse=True,
        )
        validos = []
        rechazos = []
        for path, doc in coincidentes:
            errores = _valido(doc, tipo)
            if errores:
                rechazos.append({"archivo": path.name, "errores": errores})
            else:
                validos.append((path, doc))
        if validos:
            path, doc = validos[0]
            seleccionados[nombre] = {
                "archivo": path.name,
                "sha256": sha256_archivo(path),
                "commit": doc["commit"],
                "metricas": doc["metricas"],
            }
        else:
            diagnostico[nombre] = {
                "estado": "faltante",
                "rechazos": rechazos[:5],
            }

    commits = {item["commit"] for item in seleccionados.values()}
    completo = len(seleccionados) == len(ESCENARIOS) and len(commits) == 1
    if len(commits) > 1:
        diagnostico["commits"] = {
            "estado": "inconsistente",
            "valores": sorted(commits),
        }
    return {
        "fase": 6,
        "estado": "complete" if completo else "incomplete",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "commit": next(iter(commits)) if completo else None,
        "artefactos": seleccionados,
        "diagnostico": diagnostico,
    }


def _comando(modulo: str, *args: str) -> list[str]:
    return [sys.executable, "-m", modulo, *args]


BASELINES = [
    _comando("src.tools.baseline_reglas", "--dataset", "bgl", "--n-lotes", "16", "--lineas-por-lote", "120"),
    _comando("src.tools.baseline_reglas", "--dataset", "hdfs", "--n-lotes", "20", "--lineas-por-lote", "120", "--labels", "data/labels/hdfs_anomaly_label_2k.csv", "--prop-positivos", "0.5"),
    _comando("src.tools.baseline_reglas", "--dataset", "hdfs", "--n-lotes", "20", "--lineas-por-lote", "120", "--labels", "data/labels/hdfs_anomaly_label_2k.csv", "--prop-positivos", "0.031"),
]

MULTIAGENTE = [
    _comando("src.tools.eval_deteccion", "--dataset", "bgl", "--n-lotes", "16", "--lineas-por-lote", "120"),
    _comando("src.tools.eval_deteccion", "--dataset", "hdfs", "--n-lotes", "20", "--lineas-por-lote", "120", "--labels", "data/labels/hdfs_anomaly_label_2k.csv", "--prop-positivos", "0.5"),
    _comando("src.tools.eval_deteccion", "--dataset", "hdfs", "--n-lotes", "20", "--lineas-por-lote", "120", "--labels", "data/labels/hdfs_anomaly_label_2k.csv", "--prop-positivos", "0.031"),
]


def ejecutar(comandos: list[list[str]], exigir_completa: bool = False) -> None:
    estado = estado_git(ROOT)
    if estado["working_tree_dirty"] is not False:
        raise RuntimeError(
            "La Fase 6 final debe ejecutarse sobre un commit limpio. "
            "Confirma o descarta los cambios antes de continuar."
        )
    entorno = os.environ.copy()
    entorno["PYTHONUTF8"] = "1"
    for comando in comandos:
        anteriores = set(RESULTS.glob("*.json"))
        subprocess.run(comando, cwd=ROOT, env=entorno, check=True)
        if exigir_completa:
            nuevos = set(RESULTS.glob("*.json")) - anteriores
            if not nuevos:
                raise RuntimeError("La evaluación terminó sin producir un artefacto nuevo.")
            reciente = max(nuevos, key=lambda path: path.stat().st_mtime_ns)
            documento = json.loads(reciente.read_text(encoding="utf-8"))
            if documento.get("evaluation_status") != "complete":
                raise RuntimeError(
                    f"La corrida {reciente.name} quedó en estado "
                    f"{documento.get('evaluation_status')!r}; se detiene la Fase 6 "
                    "para no consumir cuota en artefactos posteriores."
                )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--modo", choices=("verificar", "baselines", "multiagente", "todo"),
        default="verificar",
    )
    args = parser.parse_args()

    if args.modo in ("baselines", "todo"):
        ejecutar(BASELINES)
    if args.modo in ("multiagente", "todo"):
        from src.config import validate_config
        validate_config()
        ejecutar(MULTIAGENTE, exigir_completa=True)

    informe = verificar_cierre()
    print(json.dumps(informe, ensure_ascii=False, indent=2))
    if informe["estado"] == "complete":
        MANIFEST.write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Manifiesto final guardado en {MANIFEST}")
        return 0
    print("Fase 6 incompleta: no se escribió manifiesto final.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
