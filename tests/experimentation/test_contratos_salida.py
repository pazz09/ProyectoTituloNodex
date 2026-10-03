"""Contrato común de salida (Fase 1).

**ESCRITAS, NO EJECUTADAS** (ver `tests/experimentation/__init__.py`).

La prueba central es la que bloquea derivar `classification` desde la
confianza. Ese atajo ya falseó conteos en este proyecto: un checkpoint
parcial con `False`/`0.0` se contaba como predicción "normal" y escondía el
agotamiento de cuota.
"""

import pytest

from src.experimentation.contracts import (
    CONTRATO_VERSION,
    ExperimentalOutput,
    MitreCandidate,
    MitreItem,
    ReconstructedEvent,
)


def _salida(**extra) -> ExperimentalOutput:
    base = dict(
        case_id="uwf_eval_0001",
        run_id="uwf_eval_0001__nodex__r1__a1b2c3",
        arquitectura="nodex_multiagente",
        contrato_version=CONTRATO_VERSION,
        classification="MALICIOUS",
        report_summary="Resumen ilustrativo, no es un resultado.",
    )
    base.update(extra)
    return ExperimentalOutput(**base)


# --- prohibición de derivar la clasificación ------------------------------

def test_sin_veredicto_booleano_no_se_puede_fijar_classification():
    with pytest.raises(ValueError, match="veredicto booleano"):
        _salida(veredicto_booleano_presente=False, classification="BENIGN")


def test_sin_classification_hay_que_declarar_el_motivo():
    """Un hueco silencioso se contaría después como caso normal."""
    with pytest.raises(ValueError, match="motivo_no_evaluable"):
        _salida(classification=None)


def test_salida_no_evaluable_bien_formada_se_acepta_y_se_marca():
    salida = _salida(
        classification=None,
        veredicto_booleano_presente=False,
        motivo_no_evaluable="El auditor no devolvió un veredicto booleano.",
    )
    assert salida.es_evaluable is False
    assert salida.to_dict()["classification"] is None
    assert salida.to_dict()["_meta"]["motivo_no_evaluable"]


def test_classification_fuera_del_vocabulario_se_rechaza():
    with pytest.raises(ValueError, match="classification"):
        _salida(classification="SOSPECHOSO")


# --- forma exacta del contrato mandatado por el plan ----------------------

def test_la_serializacion_respeta_el_contrato_del_plan():
    salida = _salida(
        reconstructed_events=[
            ReconstructedEvent(uid="CxyzA1", timestamp="2026-10-01T10:00:00Z",
                               entities=("10.0.0.1", "10.0.0.2")),
        ],
        temporal_sequence=("CxyzA1",),
        mitre_tactics=[MitreItem(id="TA0006", name="Credential Access",
                                 evidence_uids=("CxyzA1",), nivel="tactica")],
        mitre_techniques=[MitreItem(id="T1110", name="Brute Force",
                                    evidence_uids=("CxyzA1",))],
    )
    d = salida.to_dict()
    assert set(d) >= {"case_id", "classification", "reconstructed_events",
                      "temporal_sequence", "mitre", "report"}
    assert set(d["mitre"]) == {"tactics", "techniques"}
    assert set(d["report"]) == {"summary"}
    evento = d["reconstructed_events"][0]
    assert {"uid", "timestamp", "entities"} <= set(evento)
    assert d["mitre"]["techniques"][0]["evidence_uids"] == ["CxyzA1"]


# --- separaciones que el protocolo exige ----------------------------------

def test_las_candidatas_mitre_no_entran_en_las_atribuciones():
    """Lo que el RAG recuperó por similitud no es una afirmación del
    sistema: viaja en `_meta`, no en `mitre`."""
    salida = _salida(
        mitre_techniques=[MitreItem(id="T1110")],
        mitre_candidates=[MitreCandidate(id="T1021", name="Remote Services",
                                         similitud=0.43)],
    )
    d = salida.to_dict()
    ids_atribuidos = [t["id"] for t in d["mitre"]["techniques"]]
    assert ids_atribuidos == ["T1110"]
    assert "T1021" not in ids_atribuidos
    assert d["_meta"]["mitre_candidates"][0]["id"] == "T1021"


def test_el_output_original_queda_referenciado_no_descartado():
    salida = _salida(raw_output_ref="outputs/nodex/uwf_eval_0001__r1.json")
    assert salida.to_dict()["_meta"]["raw_output_ref"].endswith(".json")


# --- coherencia interna --------------------------------------------------

def test_la_secuencia_temporal_no_puede_citar_uids_inexistentes():
    with pytest.raises(ValueError, match="temporal_sequence"):
        _salida(
            reconstructed_events=[ReconstructedEvent(uid="CxyzA1")],
            temporal_sequence=("CxyzA1", "NoExiste9"),
        )


def test_un_evento_sin_uid_no_rompe_la_secuencia_vacia():
    """En datasets sin identificador estable el `uid` queda `None`; el
    protocolo marca esa dimensión `no_aplica` en vez de inventar claves."""
    salida = _salida(
        reconstructed_events=[ReconstructedEvent(uid=None, timestamp="2026-10-01T10:00:00Z")],
        temporal_sequence=(),
    )
    assert salida.to_dict()["reconstructed_events"][0]["uid"] is None


def test_arquitectura_desconocida_se_rechaza():
    with pytest.raises(ValueError, match="arquitectura"):
        _salida(arquitectura="nodex_v2_experimental")
