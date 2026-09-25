"""Contrato de procedencia compartido por la Fase 6."""

from pathlib import Path

import src.tools.provenance as provenance


ROOT = Path(__file__).resolve().parents[1]


def test_procedencia_ejecucion_identifica_codigo_entorno_y_dependencias():
    salida = provenance.procedencia_ejecucion(ROOT)

    assert salida["result_schema_version"] == "2.0"
    assert salida["motor_preprocesamiento"] == "heterogeneo"
    assert salida["schema_version"]
    assert isinstance(salida["config_preprocesamiento"], dict)
    assert salida["commit"] is None or len(salida["commit"]) == 40
    assert salida["git_branch"] is None or (
        isinstance(salida["git_branch"], str) and salida["git_branch"]
    )
    assert isinstance(salida["working_tree_dirty"], (bool, type(None)))
    assert salida["requirements_sha256"]
    assert salida["constraints_sha256"]
    assert salida["generated_at_utc"].endswith("+00:00")


def test_procedencia_archivos_calcula_hash_y_ruta_relativa(tmp_path):
    archivo = tmp_path / "dataset.log"
    archivo.write_text("evento\n", encoding="utf-8")

    salida = provenance.procedencia_archivos([archivo], tmp_path)

    assert salida == [{
        "path": "dataset.log",
        "bytes": archivo.stat().st_size,
        "sha256": provenance.sha256_archivo(archivo),
    }]
