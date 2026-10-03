"""Contratos de caso y referencia (Fase 1).

**ESCRITAS, NO EJECUTADAS** (ver `tests/experimentation/__init__.py`).

Lo que estas pruebas protegen no es la forma del dataclass: es la
separación entre lo que ve el agente y lo que ve el evaluador. Si esa
separación se rompe, las métricas dejan de significar algo y el síntoma
aparece recién al interpretar resultados demasiado buenos.
"""

import pytest

from src.experimentation.contracts import GroundTruth, ReferenciaMitre, RegistroProcedencia, TestCase


def _caso(**extra) -> TestCase:
    base = dict(
        case_id="bgl_dev_0001",
        dataset="bgl",
        tipo_deteccion="operativa",
        particion="desarrollo",
        contenido="- 1117838570 2005.06.03 R02-M1-N0 ... instruction cache parity error",
        dimensiones_aplicables=("deteccion", "consumo"),
    )
    base.update(extra)
    return TestCase(**base)


# --- TestCase: vocabularios cerrados --------------------------------------

def test_dataset_desconocido_se_rechaza():
    with pytest.raises(ValueError, match="dataset"):
        _caso(dataset="elasticsearch")


def test_tipo_de_deteccion_desconocido_se_rechaza():
    """`operativa` y `seguridad` son las dos únicas preguntas del protocolo;
    un tercer valor dejaría al evaluador eligiendo campo por su cuenta."""
    with pytest.raises(ValueError, match="tipo_deteccion"):
        _caso(tipo_deteccion="hibrida")


def test_dimension_desconocida_se_rechaza():
    with pytest.raises(ValueError, match="dimensiones_aplicables"):
        _caso(dimensiones_aplicables=("deteccion", "explicabilidad"))


def test_case_id_vacio_se_rechaza():
    with pytest.raises(ValueError, match="case_id"):
        _caso(case_id="")


# --- TestCase: no puede llevar la etiqueta --------------------------------

def test_el_caso_no_expone_ningun_campo_de_etiqueta():
    """La separación es estructural, no una convención: `TestCase` no
    tiene dónde guardar una etiqueta aunque alguien quisiera."""
    campos = set(_caso().to_dict())
    assert "etiqueta_deteccion" not in campos
    assert "ground_truth" not in campos
    assert "core_event_uids" not in campos
    assert "referencias_mitre" not in campos


# --- procedencia ----------------------------------------------------------

def test_la_procedencia_conserva_archivo_linea_y_grupo():
    registro = RegistroProcedencia(
        indice_en_caso=0,
        archivo_origen="data/logs/HDFS_2k.log",
        linea_original=1,
        grupo="blk_-1608999687919862906",
        uid=None,
    )
    assert registro.to_dict()["grupo"].startswith("blk_")


def test_linea_original_cero_se_rechaza_por_ser_1_indexada():
    with pytest.raises(ValueError, match="linea_original"):
        RegistroProcedencia(indice_en_caso=0, archivo_origen="x.log", linea_original=0)


# --- GroundTruth ----------------------------------------------------------

def test_la_referencia_no_puede_provenir_de_nodex():
    """Construir el ground truth con la salida del sistema evaluado
    invalida la medición -- el contrato lo rechaza en vez de confiar en que
    nadie lo haga."""
    with pytest.raises(ValueError, match="no puede provenir de NODEX"):
        GroundTruth(
            case_id="uwf_eval_0001",
            etiqueta_deteccion="anomalo",
            anotacion={"fuente": "nodex", "aprobada": True},
        )


def test_estado_de_dimension_desconocido_se_rechaza():
    with pytest.raises(ValueError, match="estado_dimension"):
        GroundTruth(
            case_id="uwf_eval_0001",
            estado_dimension={"mitre": "casi_evaluable"},
        )


def test_etiqueta_de_deteccion_fuera_del_vocabulario_se_rechaza():
    with pytest.raises(ValueError, match="etiqueta_deteccion"):
        GroundTruth(case_id="hdfs_eval_0001", etiqueta_deteccion="MALICIOUS")


def test_una_dimension_sin_referencia_queda_pendiente_no_acertada():
    """`referencia_pendiente` debe sobrevivir en el artefacto: es lo que
    impide que el cierre de esa dimensión se declare completo."""
    gt = GroundTruth(
        case_id="uwf_eval_0002",
        estado_dimension={"deteccion": "evaluable", "reporte": "referencia_pendiente"},
        etiqueta_deteccion="anomalo",
    )
    assert gt.to_dict()["estado_dimension"]["reporte"] == "referencia_pendiente"


def test_mitre_conserva_el_nivel_sin_inferir_subtecnica():
    """Una táctica no se convierte en técnica, y una subtécnica ausente no
    se completa: el nivel es parte de la referencia."""
    gt = GroundTruth(
        case_id="uwf_eval_0003",
        estado_dimension={"mitre": "evaluable"},
        referencias_mitre=[
            ReferenciaMitre(nivel="tactica", id="TA0006", nombre="Credential Access"),
            ReferenciaMitre(nivel="tecnica", id="T1110", evidence_uids=("CxyzA1",)),
        ],
    )
    niveles = [r["nivel"] for r in gt.to_dict()["referencias_mitre"]]
    assert niveles == ["tactica", "tecnica"]
    assert "subtecnica" not in niveles


def test_nivel_mitre_desconocido_se_rechaza():
    with pytest.raises(ValueError, match="nivel"):
        ReferenciaMitre(nivel="procedimiento", id="T1110")


def test_el_ground_truth_no_tiene_campos_de_reporte_gold():
    """El plan prohíbe ampliar el ERR con `gold_claims`, `expected_facts` o
    reportes de referencia: la calidad del reporte se mide con rúbrica
    humana."""
    campos = set(GroundTruth(case_id="uwf_eval_0004").to_dict())
    assert "gold_claims" not in campos
    assert "expected_facts" not in campos
    assert "reporte_gold" not in campos
