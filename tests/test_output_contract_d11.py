"""D-11: validación determinista y conexión real grafo -> exportación.

Los modelos se simulan; los UIDs A/B/C pertenecen al fixture, nunca a GT.
"""

import copy
import json
from types import SimpleNamespace

import pytest

from src.output_contract import (
    campos_d11, construir_evidencia, normalizar_d11, normalizar_salida_experimental,
)
from src.preprocessing.models import NormalizedEvent
from src.telemetry import iniciar_llamada, medir_ejecucion, registrar_consumo, resumen_telemetria

EVIDENCIA = [
    {"uid": "A", "timestamp": "2026-10-01T10:00:00Z"},
    {"uid": "B", "timestamp": "2026-10-01T10:01:00Z"},
    {"uid": "C", "timestamp": None},
]


def evento(uid="A", event_id="event_001", **extras):
    return {"event_id": event_id, "evidence_uids": [uid],
            "timestamp": EVIDENCIA[0]["timestamp"], "event_type": "Authentication Failure",
            "description": "Intento de autenticación fallido observado.", "confidence": None, **extras}


def tecnica(uid="A", technique_id="T1110", **extras):
    return {"technique_id": technique_id, "technique_name": "Brute Force",
            "evidence_uids": [uid], "justification": "Intentos fallidos observados.",
            "confidence": None, **extras}


def respuesta(events=None, timeline=None, techniques=None):
    return {"eventos_reconstruidos": events or [], "secuencia_temporal": timeline or [],
            "tecnicas_atribuidas": techniques or []}


def test_contrato_vacio_valido():
    result = normalizar_d11(respuesta(), [])
    # `invalid_evidence_group_count` es aditivo (M6, NODEX final): grupos citados que no existen.
    assert result == {**respuesta(), "invalid_evidence_uid_count": 0,
                      "invalid_evidence_group_count": 0, "d11_warnings": []}


def test_evento_con_evidencia_se_conserva_sin_mutar():
    entrada = respuesta([evento()], ["event_001"])
    antes = copy.deepcopy(entrada)
    result = normalizar_d11(entrada, EVIDENCIA)
    assert result["eventos_reconstruidos"][0]["evidence_uids"] == ["A"]
    assert result["eventos_reconstruidos"][0]["event_type"] == "authentication_failure"
    assert result["secuencia_temporal"] == ["event_001"]
    assert entrada == antes


def test_uid_inventado_filtrado_y_contabilizado(caplog):
    result = normalizar_d11(respuesta([evento("NO_EXISTE")], techniques=[tecnica("NO_EXISTE")]), EVIDENCIA)
    assert result["eventos_reconstruidos"] == result["tecnicas_atribuidas"] == []
    assert result["invalid_evidence_uid_count"] == 2
    assert "invalid_evidence_uid_count=2" in caplog.text


def test_evidencia_mixta_conserva_solo_uids_validos():
    result = normalizar_d11(respuesta([evento(evidence_uids=["A", "NO_EXISTE", "A"])]), EVIDENCIA)
    assert result["eventos_reconstruidos"][0]["evidence_uids"] == ["A"]
    assert result["invalid_evidence_uid_count"] == 1


def test_secuencia_invalida_y_duplicados_no_rompen():
    result = normalizar_d11(respuesta([evento(), evento()], ["fantasma", {}, "event_001"]), EVIDENCIA)
    assert len(result["eventos_reconstruidos"]) == 1
    assert result["secuencia_temporal"] == ["event_001"]
    assert "event_id_duplicado" in result["d11_warnings"]


def test_evento_descartado_no_reserva_identificador():
    result = normalizar_d11(respuesta([evento(description=None), evento()]), EVIDENCIA)
    assert len(result["eventos_reconstruidos"]) == 1
    assert result["eventos_reconstruidos"][0]["event_id"] == "event_001"


def test_tecnica_valida_y_subtecnica_preservadas():
    result = normalizar_d11(respuesta(techniques=[tecnica(), tecnica(technique_id=" t1110.001 ")]), EVIDENCIA)
    assert [t["technique_id"] for t in result["tecnicas_atribuidas"]] == ["T1110", "T1110.001"]


def test_tecnica_sin_evidencia_o_id_malformado_excluida():
    result = normalizar_d11(respuesta(techniques=[tecnica(evidence_uids=[]), tecnica(technique_id="X1110")]), EVIDENCIA)
    assert result["tecnicas_atribuidas"] == []


def test_candidatos_rag_no_son_atribuciones():
    result = normalizar_d11({**respuesta(), "tecnicas_mitre": [{"technique_id": "T1021"}]}, EVIDENCIA)
    assert result["tecnicas_atribuidas"] == []
    normalizado = normalizar_salida_experimental({**result, "tecnicas_mitre": ["T1021"]})
    assert normalizado["mitre"]["attributed_techniques"] == []
    assert normalizado["mitre"]["retrieved_candidates"] == ["T1021"]


def test_deduplicacion_mitre_fusiona_evidencia():
    result = normalizar_d11(respuesta(techniques=[tecnica(), tecnica("B", " t1110 ")]), EVIDENCIA)
    assert len(result["tecnicas_atribuidas"]) == 1
    assert result["tecnicas_atribuidas"][0]["evidence_uids"] == ["A", "B"]


@pytest.mark.parametrize("malformada", [None, [], {"eventos_reconstruidos": None},
    {"eventos_reconstruidos": [None, {"evidence_uids": "A"}]},
    {"tecnicas_atribuidas": [False, {"technique_id": []}]}, {"error": "json_invalido"}])
def test_json_parcial_y_formas_incorrectas_toleradas(malformada):
    result = normalizar_d11(malformada, EVIDENCIA)
    assert result["eventos_reconstruidos"] == result["tecnicas_atribuidas"] == []
    json.dumps(result, allow_nan=False)


def test_fechas_derivadas_y_orden_observable():
    result = normalizar_d11(respuesta([
        evento("B", "event_002", timestamp="inventado"),
        evento(), evento("C", "event_003", timestamp=None)], ["event_003", "event_002", "event_001"]), EVIDENCIA)
    assert result["secuencia_temporal"] == ["event_001", "event_002"]
    assert result["eventos_reconstruidos"][0]["timestamp"] == EVIDENCIA[1]["timestamp"]
    assert result["eventos_reconstruidos"][2]["timestamp"] is None


def test_marcas_multiples_no_inventan_fecha_y_confianza():
    result = normalizar_d11(respuesta([evento(evidence_uids=["A", "B"], timestamp="2030-01-01", confidence=.99)]), EVIDENCIA)
    assert result["eventos_reconstruidos"][0]["timestamp"] is None
    assert result["eventos_reconstruidos"][0]["confidence"] is None
    assert result["secuencia_temporal"] == []


def test_fuente_identificable_recorte_y_sin_raw():
    events = [NormalizedEvent(raw="secret label_technique=T9999", message="secret label_technique=T9999",
                attributes={"uid": "A", "label_binary": "malicious"}, record_number=1),
              NormalizedEvent(raw="second", message="second", record_number=2)]
    evidencia, omitidos = construir_evidencia(SimpleNamespace(events=events), limite=1)
    assert evidencia[0]["uid"] == "A"
    assert omitidos == 1
    texto = json.dumps(evidencia)
    assert "secret" not in texto and "malicious" not in texto and "T9999" not in texto
    assert construir_evidencia(SimpleNamespace(events=events))[0][1]["uid"] == "log_record_000002"


def test_serializacion_adaptador_preserva_d2_d3_y_no_muta_estado():
    state = {**normalizar_d11(respuesta([evento()], ["event_001"], [tecnica()]), EVIDENCIA),
             "evidencia_logs": EVIDENCIA, "ground_truth": "prohibido"}
    result = json.loads(json.dumps(normalizar_salida_experimental(state), allow_nan=False))
    assert result["reconstruction"]["events"][0]["evidence_uids"] == ["A"]
    assert result["mitre"]["attributed_techniques"][0]["technique_id"] == "T1110"
    assert "prohibido" not in json.dumps(result)
    result["reconstruction"]["events"].clear()
    assert len(state["eventos_reconstruidos"]) == 1
    assert campos_d11({})["eventos_reconstruidos"] == []


def test_telemetria_consumo_real_y_aislamiento():
    with medir_ejecucion():
        call = iniciar_llamada("modelo")
        registrar_consumo(call, SimpleNamespace(usage_metadata=SimpleNamespace(
            prompt_token_count=10, candidates_token_count=4, total_token_count=17)))
        state = {"invalid_evidence_uid_count": 2, "replan_count": 1, "intentos_correccion": 1,
                 "historial_planes": [{"resultados_asociados": {"intentos_correccion": 2}}]}
        result = resumen_telemetria(state)
        assert (result["llm_call_count"], result["input_tokens"], result["output_tokens"], result["total_tokens"]) == (1, 10, 4, 17)
        assert result["intentos_correccion"] == 3
        assert result["invalid_evidence_uid_count"] == 2
        iniciar_llamada("fallo_sin_consumo")
        assert resumen_telemetria({})["total_tokens"] is None
    with medir_ejecucion():
        assert resumen_telemetria({})["llm_call_count"] == 0
        assert resumen_telemetria({})["total_tokens"] is None


LOGS = "\n".join(json.dumps({"uid": uid, "timestamp": timestamp, "message": "Failed SSH authentication",
                             "service": "ssh", "outcome": "failure"})
                 for uid, timestamp in [("A", EVIDENCIA[0]["timestamp"]), ("B", EVIDENCIA[1]["timestamp"]), ("C", None)])


def salida_llm():
    return {"diagnostico": "Intentos reiterados de autenticación SSH.", "hay_incidente": True,
            "hay_anomalia": True, "confianza": .9, "evaluacion": "Intentos fallidos en A y B.",
            "cobertura_auditor": True, "comandos_mitigacion": [],
            **respuesta([evento(), evento("B", "event_002", timestamp=EVIDENCIA[1]["timestamp"])],
                        ["event_001", "event_002"], [tecnica(evidence_uids=["A", "B"])])}


def test_agente_unico_mismo_contrato(monkeypatch):
    import src.single_agent as single
    llamadas = []

    def fake(prompt, system=None):
        llamadas.append(prompt)
        assert "EVIDENCIA DISPONIBLE" in prompt
        assert "ground_truth" not in prompt and "label_binary" not in prompt
        assert "no inventes UIDs" in system
        return salida_llm()

    monkeypatch.setattr(single, "llm_json", fake)
    result = single.analizar_lote_agente_unico(LOGS)
    assert len(llamadas) == 1
    assert result["_error_api"] is None
    assert result["secuencia_temporal"] == ["event_001", "event_002"]
    assert result["tecnicas_atribuidas"][0]["technique_id"] == "T1110"
    assert result["telemetry"]["output_tokens"] is None


def test_integracion_grafo_a_json_experimental_y_cli(monkeypatch, tmp_path):
    import src.llm as llm
    import src.pipeline as pipeline
    import src.tools.eval_deteccion as evaluator
    import src.tools.log_runner as runner
    from src.graph.build_graph import build_graph
    import src.agents.agente_planificador as planificador
    import src.agents.agente_analista_triage as triage
    import src.agents.agente_selector_herramientas as selector
    import src.agents.agente_ingeniero_mitigacion as mitigacion
    import src.agents.agente_auditor_final as auditor

    monkeypatch.setattr(pipeline, "_app", build_graph())
    monkeypatch.setattr(planificador, "llm_json", lambda *a, **k: {
        "objetivo": "Analizar SSH", "pasos": [
            {"id": 1, "accion": "triage", "objetivo": "analizar"},
            {"id": 2, "accion": "mitigacion", "objetivo": "contener"}]})
    monkeypatch.setattr(triage, "llm_json", lambda *a, **k: {"necesita_rag": False, "diagnostico": "Intentos SSH"})
    monkeypatch.setattr(selector, "llm_json", lambda *a, **k: {"usar_cve": False})
    monkeypatch.setattr(mitigacion, "llm_json", lambda *a, **k: {"comandos": []})
    monkeypatch.setattr(llm, "_asegurar_credenciales", lambda: None)
    monkeypatch.setattr(llm.client.models, "generate_content", lambda **kwargs: SimpleNamespace(
        text=json.dumps(salida_llm()), usage_metadata=SimpleNamespace(
            prompt_token_count=50, candidates_token_count=10, total_token_count=60)))

    def fake_auditor(prompt, **kwargs):
        assert '"uid": "A"' in prompt and '"uid": "B"' in prompt and '"uid": "C"' in prompt
        assert "label_technique" not in prompt
        return llm.llm_json(prompt, **kwargs)

    monkeypatch.setattr(auditor, "llm_json", fake_auditor)
    state = pipeline.analizar_lote(LOGS, thread_id="d11_integration")
    assert state["_error_api"] is None
    assert state["hay_incidente"] is True and state["diagnostico"] == "Intentos SSH"
    assert state["telemetry"]["llm_call_count"] == 1
    assert state["telemetry"]["total_tokens"] == 60
    normalized = normalizar_salida_experimental(state)
    assert normalized["reconstruction"]["timeline"] == ["event_001", "event_002"]
    assert normalized["mitre"]["attributed_techniques"][0]["evidence_uids"] == ["A", "B"]
    stream = list(pipeline.analizar_lote_stream(LOGS, thread_id="d11_stream"))
    assert stream[-1]["tipo"] == "final"
    assert stream[-1]["reporte"]["tecnicas_atribuidas"] == state["tecnicas_atribuidas"]
    assert stream[-1]["reporte"]["telemetry"]["llm_call_count"] == 1
    monkeypatch.setattr(evaluator, "_construir_lotes_bgl", lambda *a: [
        {"id": "fixture", "texto": LOGS, "ground_truth": "anomalo"}])
    monkeypatch.setattr(evaluator, "_RESULTS_DIR", tmp_path)
    result = evaluator.correr_evaluacion("bgl", 1, 3)
    experimental = json.loads(next(tmp_path.glob("eval*.json")).read_text(encoding="utf-8"))
    assert experimental["resultados"][0]["output_normalizado"]["reconstruction"] == normalized["reconstruction"]
    assert result["metricas"]["n_fallidos"] == 0
    logfile = tmp_path / "fixture.log"
    logfile.write_text(LOGS, encoding="utf-8")
    cli = runner.run_from_file(str(logfile), thread_id="d11_cli", guardar=False)
    assert cli["tecnicas_atribuidas"] == state["tecnicas_atribuidas"]


def test_ground_truth_zeek_no_llega_a_prompt(monkeypatch):
    import src.single_agent as single
    logs = 'uid,ts,id.orig_h,id.resp_h,conn_state,label_tactic,label_technique,label_binary\nA,1664883645,10.0.0.1,10.0.0.2,SF,SECRET_TACTIC,SECRET_TECHNIQUE,SECRET_BINARY\n'

    def fake(prompt, **kwargs):
        assert "SECRET" not in prompt
        assert "label_" not in prompt
        return {**salida_llm(), **respuesta()}

    monkeypatch.setattr(single, "llm_json", fake)
    result = single.analizar_lote_agente_unico(logs)
    assert result["_error_api"] is None
    assert result["tecnicas_atribuidas"] == []


def test_cliente_llm_mide_solicitudes_y_reintentos_json(monkeypatch):
    import src.llm as llm
    respuestas = iter([
        SimpleNamespace(text="invalid json", usage_metadata=SimpleNamespace(
            prompt_token_count=10, candidates_token_count=2, total_token_count=12)),
        SimpleNamespace(text='{"ok": true}', usage_metadata=SimpleNamespace(
            prompt_token_count=13, candidates_token_count=4, total_token_count=17)),
    ])
    monkeypatch.setattr(llm, "_asegurar_credenciales", lambda: None)
    monkeypatch.setattr(llm.client.models, "generate_content", lambda **kwargs: next(respuestas))
    with medir_ejecucion():
        assert llm.llm_json("analizar") == {"ok": True}
        result = resumen_telemetria({})
    assert result["llm_call_count"] == 2
    assert result["input_tokens"] == 23
    assert result["output_tokens"] == 6
    assert result["total_tokens"] == 29


def test_replanificacion_borra_conclusiones_y_conserva_validacion():
    from src.agents.agente_planificador import preparar_replanificacion, _archivar_plan_anterior
    state = {**normalizar_d11(respuesta([evento()], ["event_001"], [tecnica()]), EVIDENCIA),
             "plan": {}, "invalid_evidence_uid_count": 3, "intentos_correccion": 2}
    archive = _archivar_plan_anterior(state, "evidencia insuficiente")
    new = {**state, **preparar_replanificacion(state)}
    assert new["eventos_reconstruidos"] == new["secuencia_temporal"] == new["tecnicas_atribuidas"] == []
    assert new["invalid_evidence_uid_count"] == 3
    assert archive["resultados_asociados"]["eventos_reconstruidos"] == state["eventos_reconstruidos"]
    assert archive["resultados_asociados"]["intentos_correccion"] == 2


import pytest  # noqa: E402

# NODEX final, Fase B: estas pruebas verifican el flujo de la Fase A (sigue disponible con los
# interruptores de la Fase B apagados). El flujo nuevo lo cubre tests/test_nodex_final_fase_b.py.
pytestmark = pytest.mark.usefixtures("modo_fase_a")
