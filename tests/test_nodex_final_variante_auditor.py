"""Variante de desarrollo "NODEX B.1 sin cazador, auditor reforzado" (interruptor AUDITOR_REFORZADO).

La única diferencia con B.1 debe ser QUIÉN evalúa los grupos con señal (un agente separado o el propio
auditor), no la información disponible: el auditor reforzado recibe exactamente lo que recibe el cazador.
"""

import json

import pytest

import src.config as config
from tests.test_nodex_final_fase_a import estado_de, lote_red


def _estado_red():
    estado = estado_de(lote_red())
    estado.update(diagnostico="d", veredicto_consolidado="normal", plan={"pasos": []},
                  cazador_ejecutado=False, hallazgos_cazador=[])
    return estado


def _respuesta(evaluacion):
    return {"evaluacion_grupos": evaluacion, "confianza": 0.9, "hay_anomalia": True, "hay_incidente": True,
            "evaluacion": "e", "cobertura_auditor": True, "eventos_reconstruidos": [], "secuencia_temporal": [],
            "tecnicas_atribuidas": []}


def test_el_auditor_reforzado_recibe_lo_mismo_que_el_cazador_y_evalua_antes_del_veredicto(monkeypatch):
    import src.agents.agente_auditor_final as auditor
    from src.agents.agente_cazador import grupos_para_cazador, resumen_dominante
    monkeypatch.setattr(config, "AUDITOR_REFORZADO", True)
    monkeypatch.setattr(config, "CAZADOR_ACTIVO", False)
    estado = _estado_red()
    grupos = grupos_para_cazador(estado)
    assert grupos and all(g["filas"] for g in grupos)
    gid = grupos[0]["group_id"]
    visto = {}

    def falso(prompt, system=None, **_):
        visto.update(prompt=prompt, system=system)
        return _respuesta([
            {"group_id": gid, "explicacion_benigna": "b", "explicacion_maliciosa": "m",
             "patron_lista": "Barrido_Descubrimiento_Servicios"},
            {"group_id": gid, "explicacion_benigna": "duplicado", "patron_lista": "ninguno"},
            {"group_id": "G99", "explicacion_benigna": "inventado", "patron_lista": "ninguno"}])

    monkeypatch.setattr(auditor, "llm_json", falso)
    salida = auditor.agente_auditor_final(estado)
    # Mismo contenido que el cazador: filas completas, motivo factual, memoria y resumen dominante.
    assert json.dumps(grupos, ensure_ascii=False) in visto["prompt"]
    assert json.dumps(resumen_dominante(estado), ensure_ascii=False) in visto["prompt"]
    assert "GRUPOS CON SEÑAL: EVALÚALOS UNO POR UNO ANTES DEL VEREDICTO" in visto["prompt"]
    assert "HALLAZGOS DEL CAZADOR" not in visto["prompt"]
    # Misma lista de verificación; la evaluación es el primer campo del JSON.
    assert "LISTA DE VERIFICACIÓN" in visto["system"] and "barrido_descubrimiento_servicios" in visto["system"]
    assert visto["system"].index('"evaluacion_grupos"') < visto["system"].index('"confianza"')
    assert "explicacion_benigna" in visto["system"] and "explicacion_maliciosa" in visto["system"]
    assert salida["evaluacion_grupos"] == [{"group_id": gid, "explicacion_benigna": "b",
                                            "explicacion_maliciosa": "m",
                                            "patron_lista": "barrido_descubrimiento_servicios"}]
    for otro in [g["group_id"] for g in grupos[1:]]:
        assert f"grupo_con_senal_sin_evaluacion:{otro}" in salida["d11_warnings"]


def test_con_el_interruptor_apagado_el_auditor_es_el_de_b1(monkeypatch):
    import src.agents.agente_auditor_final as auditor
    monkeypatch.setattr(config, "AUDITOR_REFORZADO", False)
    visto = {}

    def falso(prompt, system=None, **_):
        visto.update(prompt=prompt, system=system)
        return _respuesta([{"group_id": "G01", "patron_lista": "ninguno"}])

    monkeypatch.setattr(auditor, "llm_json", falso)
    salida = auditor.agente_auditor_final(_estado_red())
    assert salida["evaluacion_grupos"] == []
    assert "evaluacion_grupos" not in visto["system"] and "GRUPOS CON SEÑAL" not in visto["prompt"]
    assert "HALLAZGOS DEL CAZADOR" in visto["prompt"]
    assert not any(w.startswith("grupo_con_senal_sin_evaluacion") for w in salida["d11_warnings"])


def test_el_patron_de_la_evaluacion_se_valida_contra_la_lista():
    from src.agents.agente_auditor_final import normalizar_evaluacion_grupos
    salida = normalizar_evaluacion_grupos([{"group_id": "G01", "patron_lista": "enumeracion_reconocimiento_dns"},
                                           {"group_id": "G02", "patron_lista": "otro"},
                                           {"group_id": "G03"}, "basura"], {"G01", "G02", "G03"})
    assert [e["patron_lista"] for e in salida] == ["enumeracion_reconocimiento_dns", "fuera_de_lista",
                                                   "no_indicado"]
    assert normalizar_evaluacion_grupos(None, {"G01"}) == []


def test_sin_cazador_el_router_lo_omite_aunque_haya_grupos(monkeypatch):
    from src.graph.routers import router_caza
    estado = _estado_red()
    assert router_caza(estado) == "agente_cazador"
    monkeypatch.setattr(config, "CAZADOR_ACTIVO", False)
    assert router_caza(estado) == "tool_consultar_rag"


def test_la_evaluacion_de_grupos_llega_a_la_salida():
    from src.output_contract import campos_d11
    estado = _estado_red()
    estado["evaluacion_grupos"] = [{"group_id": "G01", "patron_lista": "ninguno"}]
    assert campos_d11(estado)["evaluacion_grupos"] == [{"group_id": "G01", "patron_lista": "ninguno"}]


def test_el_arnes_acepta_solo_interruptores_conocidos_y_los_registra():
    from tools import evaluar_desarrollo_fase_b as arnes
    assert "AUDITOR_REFORZADO" in arnes.INTERRUPTORES
    assert arnes.parsear_entorno(["CAZADOR_ACTIVO=false", "AUDITOR_REFORZADO=true"]) == {
        "CAZADOR_ACTIVO": "false", "AUDITOR_REFORZADO": "true"}
    with pytest.raises(SystemExit):
        arnes.parsear_entorno(["GEMINI_API_KEY=x"])
    with pytest.raises(SystemExit):
        arnes.parsear_entorno(["CAZADOR_ACTIVO"])
    assert set(arnes.interruptores_efectivos()) == set(arnes.INTERRUPTORES)
