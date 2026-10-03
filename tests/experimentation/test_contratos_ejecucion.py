"""Contratos de configuración y bitácora de ejecución (Fase 1).

**ESCRITAS, NO EJECUTADAS** (ver `tests/experimentation/__init__.py`).
"""

import pytest

from src.experimentation.contracts import ExperimentConfig, PROTOCOLO_VERSION, RunRecord


def _config(**extra) -> ExperimentConfig:
    base = dict(
        config_id="campania_piloto_001",
        protocolo_version=PROTOCOLO_VERSION,
        arquitecturas=("nodex_multiagente", "agente_unico"),
        datasets=("bgl",),
        particion="desarrollo",
        repeticiones=1,
    )
    base.update(extra)
    return ExperimentConfig(**base)


def _run(**extra) -> RunRecord:
    base = dict(
        run_id="bgl_dev_0001__nodex__r1__a1b2c3",
        case_id="bgl_dev_0001",
        arquitectura="nodex_multiagente",
        dataset="bgl",
        repeticion=1,
        config_id="campania_piloto_001",
        protocolo_version=PROTOCOLO_VERSION,
        iniciado_utc="2026-10-03T12:00:00+00:00",
    )
    base.update(extra)
    return RunRecord(**base)


# --- ExperimentConfig: la ejecución viene deshabilitada -------------------

def test_la_ejecucion_viene_deshabilitada_por_defecto():
    """El plan exige que el modo entregado sea exclusivamente de
    preparación: habilitar la ejecución debe ser un acto explícito."""
    assert _config().ejecucion_habilitada is False


def test_no_se_guardan_credenciales_solo_su_presencia():
    with pytest.raises(ValueError, match="solo se registra la PRESENCIA"):
        _config(credenciales_presentes={"GEMINI_API_KEY": "AIza-secreto"})


def test_presencia_de_credenciales_como_booleano_se_acepta():
    config = _config(credenciales_presentes={"GEMINI_API_KEY": False})
    assert config.to_dict()["credenciales_presentes"]["GEMINI_API_KEY"] is False


def test_repeticiones_cero_se_rechaza():
    with pytest.raises(ValueError, match="repeticiones"):
        _config(repeticiones=0)


def test_arquitectura_desconocida_se_rechaza():
    with pytest.raises(ValueError, match="arquitecturas"):
        _config(arquitecturas=("nodex_multiagente", "agente_doble"))


def test_el_baseline_de_reglas_es_una_arquitectura_valida_aparte():
    """Se conserva como comparación adicional; no reemplaza al agente
    único."""
    config = _config(arquitecturas=("nodex_multiagente", "agente_unico", "baseline_reglas"))
    assert "baseline_reglas" in config.arquitecturas
    assert "agente_unico" in config.arquitecturas


def test_protocolo_version_vacia_se_rechaza():
    with pytest.raises(ValueError, match="protocolo_version"):
        _config(protocolo_version="")


def test_temperatura_fuera_de_rango_se_rechaza():
    with pytest.raises(ValueError, match="temperatura"):
        _config(temperatura=3.5)


# --- RunRecord ------------------------------------------------------------

def test_una_ejecucion_fallida_exige_mensaje_de_error():
    """Una corrida que falla sin causa registrada no es auditable: después
    no se puede distinguir cuota agotada de JSON mal formado."""
    with pytest.raises(ValueError, match="exige un mensaje"):
        _run(estado="error_api")


def test_una_ejecucion_fallida_con_causa_se_acepta():
    run = _run(estado="error_api", error="402 RESOURCE_EXHAUSTED")
    assert run.fue_completa is False
    assert "RESOURCE_EXHAUSTED" in run.to_dict()["error"]


def test_estado_de_ejecucion_desconocido_se_rechaza():
    with pytest.raises(ValueError, match="estado"):
        _run(estado="raro", error="x")


def test_repeticion_cero_se_rechaza_por_ser_1_indexada():
    with pytest.raises(ValueError, match="repeticion"):
        _run(repeticion=0)


def test_el_run_id_no_depende_solo_de_segundos():
    """Dos corridas del mismo segundo colisionarían y una sobreescribiría a
    la otra: el id lleva caso, arquitectura, repetición y un sufijo."""
    run = _run()
    assert run.run_id.count("__") >= 3
    assert run.case_id in run.run_id


def test_la_telemetria_es_un_campo_del_contrato_aunque_este_vacio():
    """La instrumentación real es de la Fase 6; el contrato ya reserva
    dónde va, para que no se agregue improvisado después."""
    assert _run().to_dict()["telemetria"] == {}
