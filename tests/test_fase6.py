"""La fase 6 solo se cierra con seis artefactos comparables y trazables."""

import json
from pathlib import Path

from src.tools.fase6 import ESCENARIOS, verificar_cierre


COMMIT = "a" * 40


def _artefacto(tipo: str, dataset: str, prop, estado="complete", dirty=False):
    doc = {
        "dataset": dataset,
        "prop_positivos": prop,
        "evaluation_status": estado,
        "result_schema_version": "2.0",
        "motor_preprocesamiento": "heterogeneo",
        "commit": COMMIT,
        "working_tree_dirty": dirty,
        "dataset_provenance": [{"path": "data.log", "bytes": 1, "sha256": "b" * 64}],
        "metricas": {"tp": 1, "fp": 0, "fn": 0, "tn": 1, "n_evaluados": 2, "n_fallidos": 0},
        "generated_at_utc": "2026-09-24T12:00:00+00:00",
    }
    if tipo == "baseline":
        doc["baseline"] = "reglas_deterministicas"
        doc["llamadas_llm"] = 0
    else:
        doc["llm_config"] = {"primary_model": "gemini-test"}
    return doc


def _escribir(path: Path, contenido: dict):
    path.write_text(json.dumps(contenido), encoding="utf-8")


def test_verificador_cierra_solo_con_los_seis_artefactos(tmp_path):
    for nombre, (tipo, dataset, prop) in ESCENARIOS.items():
        _escribir(tmp_path / f"{nombre}.json", _artefacto(tipo, dataset, prop))

    informe = verificar_cierre(tmp_path)

    assert informe["estado"] == "complete"
    assert informe["commit"] == COMMIT
    assert set(informe["artefactos"]) == set(ESCENARIOS)


def test_verificador_rechaza_corridas_parciales_o_sucias(tmp_path):
    _escribir(
        tmp_path / "eval_deteccion_bgl_parcial.json",
        _artefacto("multiagente", "bgl", None, estado="partial"),
    )
    _escribir(
        tmp_path / "baseline_reglas_bgl_dirty.json",
        _artefacto("baseline", "bgl", None, dirty=True),
    )

    informe = verificar_cierre(tmp_path)

    assert informe["estado"] == "incomplete"
    assert informe["artefactos"] == {}
    assert "multiagente_bgl" in informe["diagnostico"]
    assert "baseline_bgl" in informe["diagnostico"]
