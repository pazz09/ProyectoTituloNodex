"""Gemini 3.8 Flash directo (comparación con el modelo base). Sin API: el modelo se simula."""

import hashlib
import json
from types import SimpleNamespace

import pytest

import src.experimentation.runners.gemini_directo as gd
from tests.test_nodex_final_fase_a import lote_bgl, lote_red


def _respuesta(texto, entrada=1000, salida=200, razonamiento=300):
    return SimpleNamespace(text=texto, model_version="gemini-3.8-flash", usage_metadata=SimpleNamespace(
        prompt_token_count=entrada, candidates_token_count=salida, thoughts_token_count=razonamiento,
        total_token_count=entrada + salida + razonamiento))


def _bloque(objeto):
    return "```json\n" + json.dumps(objeto, ensure_ascii=False, indent=2) + "\n```"


def _uids(raw):
    return [linea.split(",")[0] for linea in raw.splitlines()[1:] if linea]


def test_el_prompt_es_el_congelado_y_el_archivo_va_completo_a_continuacion():
    texto = gd.PROMPT_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert hashlib.sha256(texto.encode("utf-8")).hexdigest() == gd.PROMPT_SHA256
    assert texto.startswith("Eres un analista de seguridad. Vas a recibir un archivo de log crudo y completo.")
    raw = lote_red() * 40                                   # archivo grande: no se recorta
    vistas = []
    registro = gd.ejecutar(raw, "uwf", llamar=lambda s: vistas.append(s) or _respuesta(_bloque({})))
    (solicitud,) = vistas
    assert solicitud == texto + "\n" + raw and solicitud.endswith(raw)
    assert registro["solicitud_sha256"] == hashlib.sha256(solicitud.encode("utf-8")).hexdigest()
    assert registro["prompt_sha256"] == gd.PROMPT_SHA256 and registro["llamadas_llm"] == 1


def test_si_el_prompt_cambia_no_se_llama_al_modelo(tmp_path, monkeypatch):
    alterado = tmp_path / "prompt.txt"
    alterado.write_text(gd.PROMPT_PATH.read_text(encoding="utf-8") + " ", encoding="utf-8")
    monkeypatch.setattr(gd, "PROMPT_PATH", alterado)
    with pytest.raises(gd.PromptAlterado):
        gd.ejecutar(lote_red(), "uwf", llamar=lambda s: pytest.fail("no debía llamar al modelo"))


def test_extraccion_del_json_sin_reparar():
    objeto = {"hay_anomalia": True, "hay_incidente": False}
    assert gd.extraer_json(_bloque(objeto)) == (objeto, "bloque_de_codigo")
    assert gd.extraer_json("```\n" + json.dumps(objeto) + "\n```")[0] == objeto
    assert gd.extraer_json(json.dumps(objeto)) == (objeto, "sin_bloque_de_codigo")
    assert gd.extraer_json('```json\n{"hay_anomalia": true,}\n```')[0] is None          # coma final: no se repara
    assert gd.extraer_json("```json\n[1, 2]\n```") == (None, "json_no_es_objeto (bloque_de_codigo)")
    assert gd.extraer_json("") == (None, "respuesta_vacia")


def test_json_invalido_es_falla_del_sistema_y_se_guarda_la_respuesta_cruda():
    cruda = 'Aquí va mi análisis:\n```json\n{"diagnostico": "sin cerrar"\n```'
    registro = gd.ejecutar(lote_red(), "uwf", llamar=lambda s: _respuesta(cruda))
    assert registro["falla"] == "sistema" and registro["detalle_falla"].startswith("json_invalido")
    assert registro["respuesta_cruda"] == cruda and registro["normalizado"] is None
    assert registro["telemetria"]["llm_calls"][0]["reasoning_tokens"] == 300


def test_sin_veredictos_booleanos_es_falla_del_sistema():
    registro = gd.ejecutar(lote_red(), "uwf", llamar=lambda s: _respuesta(_bloque({"hay_anomalia": "sí"})))
    assert registro["falla"] == "sistema" and registro["normalizado"]["hay_anomalia"] is None


@pytest.mark.parametrize("mensaje, clase", [
    ("402 RESOURCE_EXHAUSTED. Your prepayment credits are depleted.", "credito_agotado"),
    ("503 UNAVAILABLE. The model is overloaded.", "infraestructura"),
    ("ConnectError: [Errno 11001] getaddrinfo failed", "infraestructura"),
    ("400 INVALID_ARGUMENT. Request contains an invalid argument.", "sistema"),
])
def test_clasificacion_de_errores_de_la_api(mensaje, clase):
    def falla(_):
        raise RuntimeError(mensaje)
    registro = gd.ejecutar(lote_red(), "uwf", llamar=falla)
    assert registro["falla"] == clase and registro["respuesta_cruda"] is None


def test_filtro_de_uids_igual_que_nodex_en_uwf():
    raw = lote_red()
    a, b, c = _uids(raw)[:3]
    respuesta = {
        "diagnostico": "d", "hay_anomalia": True, "hay_incidente": True, "confianza": 0.8, "evaluacion": "e",
        "comandos_mitigacion": ["iptables -A INPUT -s 10.0.0.9 -j DROP"],
        "eventos_reconstruidos": [
            {"event_id": "scan", "evidence_uids": [a, b, "INVENTADO1", a], "timestamp": "x", "event_type": "Port Scan",
             "description": "barrido"},
            {"event_id": "fantasma", "evidence_uids": ["INVENTADO2"], "description": "sin evidencia"}],
        "secuencia_temporal": ["paso 1"],
        "tecnicas_atribuidas": [
            {"technique_id": "t1046", "technique_name": "Network Service Discovery", "evidence_uids": [a, c],
             "justification": "barrido"},
            {"technique_id": "T1046", "evidence_uids": [b], "justification": "otra"},
            {"technique_id": "T1595.001", "evidence_uids": [c], "justification": "fuera de los eventos"},
            {"technique_id": "Recon", "evidence_uids": [a], "justification": "id inválido"}]}
    n = gd.ejecutar(raw, "uwf", llamar=lambda s: _respuesta(_bloque(respuesta)))["normalizado"]
    assert [e["event_id"] for e in n["eventos_reconstruidos"]] == ["scan"]
    assert n["eventos_reconstruidos"][0] | {} == {"event_id": "scan", "evidence_uids": [a, b], "timestamp": "x",
                                                 "event_type": "port_scan", "description": "barrido",
                                                 "confidence": None, "categoria": "incidente"}
    assert n["invalid_evidence_uid_count"] == 2
    assert n["tecnicas_atribuidas"] == [{"technique_id": "T1046", "technique_name": "Network Service Discovery",
                                         "evidence_uids": [a, b], "justification": "barrido | otra",
                                         "confidence": None}]
    assert n["classification_detallada"] == "incidente_seguridad" and n["secuencia_temporal"] == ["scan"]


def test_en_bgl_log_record_es_la_posicion_de_la_linea():
    raw = lote_bgl()
    n_lineas = len([l for l in raw.splitlines() if l.strip()])
    validos = gd.identificadores(raw, "bgl")
    assert validos == {f"log_record_{i:06d}" for i in range(1, n_lineas + 1)}
    respuesta = {"diagnostico": "d", "hay_anomalia": True, "hay_incidente": False, "confianza": 0.7,
                 "evaluacion": "e", "comandos_mitigacion": [],
                 "eventos_reconstruidos": [{"event_id": "e1", "evidence_uids": ["log_record_000003",
                                                                              f"log_record_{n_lineas + 1:06d}"],
                                            "description": "falla"}],
                 "secuencia_temporal": [], "tecnicas_atribuidas": []}
    n = gd.ejecutar(raw, "bgl", llamar=lambda s: _respuesta(_bloque(respuesta)))["normalizado"]
    assert n["eventos_reconstruidos"][0]["evidence_uids"] == ["log_record_000003"]
    assert n["invalid_evidence_uid_count"] == 1 and n["classification_detallada"] == "anomalia_operativa"


def test_un_archivo_con_columnas_de_etiqueta_no_se_envia():
    raw = lote_red().replace("community_id", "label_tactic", 1)
    registro = gd.ejecutar(raw, "uwf", llamar=lambda s: pytest.fail("no debía llamar al modelo"))
    assert registro["falla"] == "entrada_invalida" and registro["llamadas_llm"] == 0
