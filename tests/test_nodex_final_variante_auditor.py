"""Auditor reforzado (interruptor AUDITOR_REFORZADO): configuración final de NODEX.

Origen: la variante de desarrollo "B.1 sin cazador, auditor reforzado". El auditor recibe exactamente lo
que recibía el agente cazador (eliminado del sistema final) y evalúa cada grupo con señal antes del veredicto.
"""

import importlib
import json

import pytest

import src.config as config
from tests.test_nodex_final_fase_a import estado_de, lote_red

#: La configuración elegida (docs/experimentacion/bitacora_desarrollo_nodex_final.md).
CONFIGURACION_ELEGIDA = {
    "RAG_POR_HIPOTESIS": True, "CORRECCION_AUDITOR": True, "MAX_CORRECCIONES_AUDITOR": 1,
    "HISTORICO_ACTIVO": True, "HISTORICO_K": 3, "EVENTOS_POR_CATEGORIA": True,
    "HISTORICO_CONTRASTIVO": True, "HISTORICO_K_POR_CLASE": 2, "MEMORIA_GRUPOS_ACTIVA": True,
    "MEMORIA_GRUPOS_PATH": "./experiments/knowledge/memoria_grupos_v1/memoria_grupos.json",
    "AUDITOR_REFORZADO": True, "GRUPOS_MOTIVO_FACTUAL": True, "LISTA_PATRONES_MITRE": True,
    "GRUPOS_SENAL_MAX_GRUPOS": 15, "GRUPOS_SENAL_MAX_FILAS": 200,
}


def _estado_red():
    estado = estado_de(lote_red())
    estado.update(diagnostico="d", veredicto_consolidado="normal", plan={"pasos": []})
    return estado


def _respuesta(evaluacion):
    return {"evaluacion_grupos": evaluacion, "confianza": 0.9, "hay_anomalia": True, "hay_incidente": True,
            "evaluacion": "e", "cobertura_auditor": True, "eventos_reconstruidos": [], "secuencia_temporal": [],
            "tecnicas_atribuidas": []}


def test_los_valores_por_defecto_son_la_configuracion_elegida(monkeypatch):
    for nombre in CONFIGURACION_ELEGIDA:
        monkeypatch.delenv(nombre, raising=False)
    try:
        recargado = importlib.reload(config)
        assert {k: getattr(recargado, k) for k in CONFIGURACION_ELEGIDA} == CONFIGURACION_ELEGIDA
        for retirado in ("CAZADOR_ACTIVO", "CAZADOR_MOTIVO_FACTUAL", "CAZADOR_LISTA_PATRONES",
                         "CAZADOR_MAX_GRUPOS", "CAZADOR_MAX_FILAS", "AUDITOR_REVISA_MEDIOS", "NIVELES_SOSPECHA"):
            assert not hasattr(recargado, retirado)
    finally:
        importlib.reload(config)


def test_el_auditor_reforzado_recibe_los_grupos_con_senal_y_evalua_antes_del_veredicto(monkeypatch):
    import src.agents.agente_auditor_final as auditor
    from src.tools.grupos_con_senal import grupos_con_senal, resumen_dominante
    estado = _estado_red()
    grupos = grupos_con_senal(estado)
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
    # Filas completas, motivo factual, memoria y comportamiento dominante, en un bloque destacado.
    assert json.dumps(grupos, ensure_ascii=False) in visto["prompt"]
    assert json.dumps(resumen_dominante(estado), ensure_ascii=False) in visto["prompt"]
    assert "GRUPOS CON SEÑAL: EVALÚALOS UNO POR UNO ANTES DEL VEREDICTO" in visto["prompt"]
    assert "cazador" not in visto["prompt"].lower() and "cazador" not in visto["system"].lower()
    # Lista de verificación MITRE; la evaluación es el primer campo del JSON.
    assert "LISTA DE VERIFICACIÓN" in visto["system"] and "barrido_descubrimiento_servicios" in visto["system"]
    assert visto["system"].index('"evaluacion_grupos"') < visto["system"].index('"confianza"')
    assert "explicacion_benigna" in visto["system"] and "explicacion_maliciosa" in visto["system"]
    assert "(los grupos con señal los evalúas tú)" in visto["system"]
    assert salida["evaluacion_grupos"] == [{"group_id": gid, "explicacion_benigna": "b",
                                            "explicacion_maliciosa": "m",
                                            "patron_lista": "barrido_descubrimiento_servicios"}]
    for otro in [g["group_id"] for g in grupos[1:]]:
        assert f"grupo_con_senal_sin_evaluacion:{otro}" in salida["d11_warnings"]


def test_con_el_interruptor_apagado_no_hay_evaluacion_de_grupos(monkeypatch):
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
    assert "VEREDICTO CONSOLIDADO: normal" in visto["prompt"]
    assert not any(w.startswith("grupo_con_senal_sin_evaluacion") for w in salida["d11_warnings"])


def test_el_patron_de_la_evaluacion_se_valida_contra_la_lista():
    from src.agents.agente_auditor_final import normalizar_evaluacion_grupos
    salida = normalizar_evaluacion_grupos([{"group_id": "G01", "patron_lista": "enumeracion_reconocimiento_dns"},
                                           {"group_id": "G02", "patron_lista": "otro"},
                                           {"group_id": "G03"}, "basura"], {"G01", "G02", "G03"})
    assert [e["patron_lista"] for e in salida] == ["enumeracion_reconocimiento_dns", "fuera_de_lista",
                                                   "no_indicado"]
    assert normalizar_evaluacion_grupos(None, {"G01"}) == []


def test_la_evaluacion_de_grupos_llega_a_la_salida_y_el_cazador_no():
    from src.output_contract import campos_d11
    estado = _estado_red()
    estado["evaluacion_grupos"] = [{"group_id": "G01", "patron_lista": "ninguno"}]
    salida = campos_d11(estado)
    assert salida["evaluacion_grupos"] == [{"group_id": "G01", "patron_lista": "ninguno"}]
    assert not {"hallazgos_cazador", "cazador_ejecutado", "revision_hallazgos"} & set(salida)


def test_el_arnes_acepta_solo_interruptores_conocidos_y_los_registra():
    from tools import evaluar_desarrollo_fase_b as arnes
    assert "AUDITOR_REFORZADO" in arnes.INTERRUPTORES and "CAZADOR_ACTIVO" not in arnes.INTERRUPTORES
    assert arnes.parsear_entorno(["AUDITOR_REFORZADO=false", "HISTORICO_K=3"]) == {
        "AUDITOR_REFORZADO": "false", "HISTORICO_K": "3"}
    with pytest.raises(SystemExit):
        arnes.parsear_entorno(["GEMINI_API_KEY=x"])
    with pytest.raises(SystemExit):
        arnes.parsear_entorno(["CAZADOR_ACTIVO=false"])
    with pytest.raises(SystemExit):
        arnes.parsear_entorno(["AUDITOR_REFORZADO"])
    assert set(arnes.interruptores_efectivos()) == set(arnes.INTERRUPTORES)
