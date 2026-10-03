"""Contrato de métricas (Fase 1).

**ESCRITAS, NO EJECUTADAS** (ver `tests/experimentation/__init__.py`).

Estas pruebas no calculan métricas -- el cálculo es de la Fase 5. Verifican
el invariante contable: que la suma de casos evaluables y no puntuables dé
el total. Sin ese invariante, un caso que se pierde entre medio pasa
desapercibido y la matriz de confusión queda describiendo menos casos de
los que se corrieron.
"""

import pytest

from src.experimentation.contracts import DetectionCounts, MetricsRecord, PROTOCOLO_VERSION


def _metricas(**extra) -> MetricsRecord:
    base = dict(
        dimension="deteccion",
        arquitectura="nodex_multiagente",
        dataset="bgl",
        protocolo_version=PROTOCOLO_VERSION,
    )
    base.update(extra)
    return MetricsRecord(**base)


# --- invariante contable --------------------------------------------------

def test_la_contabilidad_tiene_que_cuadrar():
    with pytest.raises(ValueError, match="no cuadra"):
        _metricas(n_casos=20, n_evaluables=15, n_por_estado={"fallido": 2})


def test_contabilidad_correcta_con_los_cuatro_estados():
    metricas = _metricas(
        n_casos=20,
        n_evaluables=14,
        n_por_estado={
            "no_aplica": 2,
            "referencia_pendiente": 1,
            "fallido": 2,
            "no_evaluable": 1,
        },
        conteos=DetectionCounts(tp=5, fp=3, fn=2, tn=4),
    )
    assert metricas.n_evaluables == metricas.conteos.total


def test_la_matriz_no_puede_describir_mas_casos_que_los_evaluables():
    with pytest.raises(ValueError, match="matriz de confusión"):
        _metricas(n_casos=10, n_evaluables=10, conteos=DetectionCounts(tp=9, fp=9, fn=9, tn=9))


def test_n_evaluables_no_puede_superar_n_casos():
    with pytest.raises(ValueError, match="no puede superar"):
        _metricas(n_casos=5, n_evaluables=6)


def test_estado_no_puntuable_desconocido_se_rechaza():
    with pytest.raises(ValueError, match="n_por_estado"):
        _metricas(n_casos=1, n_evaluables=0, n_por_estado={"casi": 1})


def test_evaluable_no_es_un_estado_no_puntuable():
    """`evaluable` se cuenta en `n_evaluables`, no en `n_por_estado`:
    ponerlo en los dos lados rompería el invariante."""
    with pytest.raises(ValueError, match="n_por_estado"):
        _metricas(n_casos=1, n_evaluables=0, n_por_estado={"evaluable": 1})


# --- conteos --------------------------------------------------------------

def test_conteos_negativos_se_rechazan():
    with pytest.raises(ValueError, match="tp"):
        DetectionCounts(tp=-1)


def test_conteos_booleanos_se_rechazan_aunque_python_los_acepte_como_int():
    """`True` es `int` en Python; dejarlo pasar daría una matriz con 1 que
    en realidad era un flag."""
    with pytest.raises(ValueError):
        DetectionCounts(tp=True)


# --- None significa indefinida, no cero -----------------------------------

def test_none_y_cero_son_distintos_en_las_metricas():
    """Un recall indefinido (no había positivos reales) y un recall 0
    (había y no detectó ninguno) describen situaciones opuestas. El
    contrato permite ambos y no los confunde."""
    indefinida = _metricas(n_casos=2, n_evaluables=2,
                           conteos=DetectionCounts(tn=2), recall=None, f1=None)
    cero = _metricas(n_casos=2, n_evaluables=2,
                     conteos=DetectionCounts(fn=1, fp=1), recall=0.0, f1=0.0)
    assert indefinida.recall is None
    assert cero.recall == 0.0
    assert cero.f1 == 0.0


def test_la_dimension_reporte_usa_rubrica_y_no_matriz():
    """D4 no tiene matriz de confusión: se evalúa con rúbrica humana porque
    el plan prohíbe reportes de referencia."""
    metricas = _metricas(
        dimension="reporte",
        n_casos=4,
        n_evaluables=4,
        rubrica_por_criterio={
            "completitud": 0.0,
            "correccion_factual": 0.0,
            "coherencia_con_evidencia": 0.0,
            "claridad": 0.0,
            "informacion_no_sustentada": 0.0,
        },
        rubrica_n_evaluadores=1,
    )
    assert metricas.conteos is None
    assert len(metricas.rubrica_por_criterio) == 5


def test_la_dimension_mitre_declara_el_nivel_evaluado():
    """Táctica y técnica se miden por separado: una métrica sin nivel no se
    puede interpretar."""
    metricas = _metricas(dimension="mitre", dataset="uwf", nivel="tecnica",
                         n_casos=3, n_evaluables=3, set_f1=0.0)
    assert metricas.to_dict()["nivel"] == "tecnica"


def test_dimension_desconocida_se_rechaza():
    with pytest.raises(ValueError, match="dimension"):
        _metricas(dimension="explicabilidad")
