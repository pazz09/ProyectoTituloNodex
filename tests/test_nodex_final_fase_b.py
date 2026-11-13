"""NODEX final, Fase B: grupos con señal (antes, entrada del cazador B1; hoy, del auditor reforzado),
B2 (corrección tras el auditor), B3 (RAG por hipótesis), B4 (memoria histórica de la organización) y
B5 (eventos por categoría).

Sin API: el modelo se simula. Lotes sintéticos construidos en las pruebas; ninguna prueba abre
casos de la partición de evaluación ni su ground truth.
"""

import json

import pytest

import src.config as config
from src.output_contract import PROMPT_D11, normalizar_d11
from tests.test_nodex_final_fase_a import _COLUMNAS, estado_de, fila, lote_bgl, lote_red


# --- utilidades ------------------------------------------------------------------

class ColeccionFalsa:
    """Colección de patrones con la interfaz de Chroma que usa `consultar_historicos`."""

    def __init__(self, patrones):
        self.patrones = patrones          # [(id, distancia, metadatos)]

    def count(self):
        return len(self.patrones)

    def query(self, query_texts, n_results):
        orden = sorted(self.patrones, key=lambda p: p[1])[:n_results]
        return {"ids": [[p[0] for p in orden]], "distances": [[p[1] for p in orden]],
                "metadatas": [[p[2] for p in orden]]}


def lote_red_sin_senales():
    t = 1639746000.0
    return _COLUMNAS + "\n" + "\n".join(fila(f"Cq{i:03d}", t + i, "10.0.0.5", "10.0.0.1", 53, "udp", "dns", "SF")
                                        for i in range(5)) + "\n"


# --- grupos con señal ----------------------------------------------------------------

def test_los_grupos_con_senal_traen_todas_sus_filas():
    from src.tools.grupos_con_senal import grupos_con_senal
    grupos = grupos_con_senal(estado_de(lote_red()))
    motivos = {m for g in grupos for m in g["motivos"]}
    assert "barrido_de_puertos" in motivos and "inversion_de_rol" in motivos
    barrido = next(g for g in grupos if "barrido_de_puertos" in g["motivos"])
    assert len(barrido["filas"]) == barrido["conteo"] == 20 and barrido["filas_omitidas"] == 0


def test_en_texto_los_grupos_con_senal_incluyen_severidad_alta():
    from src.tools.grupos_con_senal import grupos_con_senal
    grupos = grupos_con_senal(estado_de(lote_bgl()))
    assert [g["clave"]["severidad"] for g in grupos if "severidad_alta" in g["motivos"]] == ["FATAL"]


@pytest.mark.parametrize("preliminar", ["incidente_seguridad", "anomalia_operativa", "normal", None])
def test_veredicto_consolidado_es_el_del_triage(preliminar):
    from src.graph.veredicto import veredicto_consolidado
    assert veredicto_consolidado({"veredicto_preliminar": preliminar}) == preliminar


def test_sin_grupos_con_senal_la_lista_esta_vacia():
    from src.tools.grupos_con_senal import grupos_con_senal
    assert grupos_con_senal(estado_de(lote_red_sin_senales())) == []


# --- B3: RAG por hipótesis ---------------------------------------------------------------

def test_sin_hipotesis_de_seguridad_no_se_consultan_tecnicas(monkeypatch):
    import src.tools.tool_consultar_rag as rag
    llamadas = []
    monkeypatch.setattr(rag.ltm, "retrieve_attack_techniques", lambda texto, **_: llamadas.append(texto) or [])
    salida = rag.tool_consultar_rag({"veredicto_preliminar": "anomalia_operativa", "diagnostico": "falla"})
    assert llamadas == [] and salida["tecnicas_mitre"] == [] and salida["rag_omitido"]
    assert salida["veredicto_consolidado"] == "anomalia_operativa"


def test_la_consulta_mitre_usa_el_texto_de_la_hipotesis(monkeypatch):
    import src.tools.tool_consultar_rag as rag
    llamadas = []
    monkeypatch.setattr(rag.ltm, "retrieve_attack_techniques", lambda texto, **_: llamadas.append(texto) or [])
    estado = {"veredicto_preliminar": "incidente_seguridad",
              "diagnostico": "Sondeo de servicios: 20 puertos S0 hacia el 445",
              "casos_historicos": [{"id": "h1"}]}
    salida = rag.tool_consultar_rag(estado)
    assert llamadas == [salida["consulta_mitre"]] == ["Sondeo de servicios: 20 puertos S0 hacia el 445"]
    assert salida["contexto_rag"] == [{"id": "h1"}] and salida["rag_omitido"] is None


def test_la_representacion_usa_grupos_con_senal_y_no_lleva_ip():
    from src.tools.memoria_historica import representacion_lote
    estado = estado_de(lote_red())
    texto = representacion_lote(estado["resumen_logs"]["perfil_lote"], estado["grupos_evidencia"],
                                estado["contenido_lote"])
    assert texto.startswith("Grupos con señal:") and "barrido_de_puertos" in texto
    assert "10.0.0." not in texto


def test_exclusion_por_solapamiento_y_k():
    from src.tools.memoria_historica import consultar_historicos
    coleccion = ColeccionFalsa([
        ("mismo", 0.0, {"historical_case_id": "mismo", "etiqueta": "normal", "descripcion": "d",
                        "huellas": json.dumps(["uid:A", "uid:B"])}),
        ("otro1", 0.1, {"historical_case_id": "otro1", "etiqueta": "malicioso", "descripcion": "d1",
                        "huellas": json.dumps(["uid:X"])}),
        ("otro2", 0.2, {"historical_case_id": "otro2", "etiqueta": "normal", "descripcion": "d2",
                        "huellas": json.dumps(["uid:Y"])}),
        ("otro3", 0.3, {"historical_case_id": "otro3", "etiqueta": "normal", "descripcion": "d3"}),
    ])
    r = consultar_historicos(coleccion, "texto", ["uid:B", "uid:Q"], k=2)
    assert r["excluidos_por_solapamiento"] == ["mismo"]
    assert [c["id"] for c in r["casos"]] == ["otro1", "otro2"] and r["casos"][0]["similitud"] == 0.9


def test_huella_de_texto_ignora_el_campo_de_alerta():
    from src.preprocessing.pipeline import preprocesar
    from src.tools.memoria_historica import huellas_registros
    assert huellas_registros(preprocesar(lote_bgl(con_flag=True)).events) == \
        huellas_registros(preprocesar(lote_bgl()).events)


# --- B4: memoria histórica y criterio de la organización ---------------------------------

HISTORICOS = [{"id": "h1", "etiqueta": "normal", "similitud": 0.91,
               "descripcion": "Normal según la organización; contiene eventos FATAL que no se consideraron alerta."}]


def test_el_triage_recibe_historicos_y_definiciones_en_una_sola_pasada(monkeypatch):
    import src.agents.agente_analista_triage as triage
    estado = estado_de(lote_bgl())
    estado["casos_historicos"] = HISTORICOS
    visto = {}

    def falso(prompt, system=None, **_):
        visto["prompt"], visto["system"] = prompt, system
        return {"diagnostico": "d", "veredicto_preliminar": "normal", "justificacion_veredicto": "j"}

    monkeypatch.setattr(triage, "llm_json", falso)
    salida = triage.agente_analista_triage(estado)
    assert "CASOS HISTÓRICOS DE LA ORGANIZACIÓN" in visto["prompt"] and "no se consideraron alerta" in visto["prompt"]
    assert "la severidad declarada por el log no basta por sí sola" in visto["system"]
    assert "referencia de criterio, no como prueba" in visto["system"]
    assert "necesita_rag" not in visto["system"]
    assert salida["necesita_rag"] is False and salida["veredicto_preliminar"] == "normal"


def test_el_agente_unico_recibe_los_mismos_historicos_y_definiciones(monkeypatch):
    import src.pipeline as pipeline
    import src.single_agent as single
    original = pipeline._consultar_memoria_historica
    monkeypatch.setattr(pipeline, "_consultar_memoria_historica",
                        lambda r, a: dict(original(r, a), casos=HISTORICOS))
    visto = {}

    def falso(prompt, system=None, **_):
        visto["prompt"], visto["system"] = prompt, system
        return {"diagnostico": "x", "hay_anomalia": False, "hay_incidente": False, "confianza": 0.9,
                "evaluacion": "x", "comandos_mitigacion": [], "eventos_reconstruidos": [],
                "secuencia_temporal": [], "tecnicas_atribuidas": []}

    monkeypatch.setattr(single, "llm_json", falso)
    single.analizar_lote_agente_unico(lote_bgl())
    assert "CASOS HISTÓRICOS DE LA ORGANIZACIÓN" in visto["prompt"]
    assert "la severidad declarada por el log no basta por sí sola" in visto["system"]
    assert "categoria" in visto["system"]                      # contrato B5


def test_el_auditor_usa_las_definiciones_de_la_organizacion(monkeypatch):
    import src.agents.agente_auditor_final as auditor
    estado = estado_de(lote_bgl())
    estado.update(diagnostico="d", veredicto_consolidado="anomalia_operativa", casos_historicos=HISTORICOS,
                  plan={"pasos": []})
    visto = {}

    def falso(prompt, system=None, **_):
        visto["prompt"], visto["system"] = prompt, system
        return {"confianza": 0.9, "hay_anomalia": False, "hay_incidente": False, "evaluacion": "e",
                "cobertura_auditor": True, "eventos_reconstruidos": [], "secuencia_temporal": [],
                "tecnicas_atribuidas": []}

    monkeypatch.setattr(auditor, "llm_json", falso)
    salida = auditor.agente_auditor_final(estado)
    assert "también cuentan como anomalía" not in visto["system"]
    assert "según las definiciones de abajo" in visto["system"] and "revision_hallazgos" not in visto["system"]
    assert "VEREDICTO CONSOLIDADO: anomalia_operativa" in visto["prompt"] and "CASOS HISTÓRICOS" in visto["prompt"]
    assert "revision_hallazgos" not in salida


def test_descripciones_del_corpus_vienen_de_la_etiqueta_y_los_eventos():
    from src.experimentation.knowledge.memoria_historica_v2 import descripcion_red, descripcion_texto
    from src.preprocessing.pipeline import preprocesar
    eventos = preprocesar(lote_bgl()).events
    etiqueta, texto = descripcion_texto(eventos, [i == 2 for i in range(6)])
    assert etiqueta == "anomalo" and "[FATAL bgl.kernel]" in texto
    etiqueta, texto = descripcion_texto(eventos, [False] * 6)
    assert etiqueta == "normal" and "no se consideraron alerta" in texto
    red = preprocesar(lote_red()).events
    etiqueta, texto = descripcion_red(red, {f"Cscan{p:03d}" for p in range(20)}, ["Discovery"], ["T1046"])
    assert etiqueta == "malicioso" and "20 conexiones" in texto and "Discovery; T1046" in texto
    assert "10.0.0." not in texto


# --- B5: eventos por categoría ------------------------------------------------------------

def test_prompt_d11_pide_categoria():
    assert "categoria" in PROMPT_D11 and '"categoria":"incidente"' in PROMPT_D11


def test_normalizar_valida_categoria_y_limita_tecnicas_a_eventos_incidente():
    evidencia = [{"uid": u, "timestamp": None} for u in ("A", "B", "C")]
    respuesta = {"eventos_reconstruidos": [
        {"event_id": "event_001", "evidence_uids": ["A"], "categoria": "incidente", "event_type": "x", "description": "d"},
        {"event_id": "event_002", "evidence_uids": ["B"], "categoria": "contexto", "event_type": "y", "description": "d"},
        {"event_id": "event_003", "evidence_uids": ["C"], "categoria": "ruido", "event_type": "z", "description": "d"}],
        "secuencia_temporal": [], "tecnicas_atribuidas": [
        {"technique_id": "T1046", "evidence_uids": ["A", "B"], "justification": "j"},
        {"technique_id": "T1110", "evidence_uids": ["B"], "justification": "j"}]}
    r = normalizar_d11(respuesta, evidencia)
    assert [e["categoria"] for e in r["eventos_reconstruidos"]] == ["incidente", "contexto", None]
    assert "categoria_invalida_o_ausente" in r["d11_warnings"]
    assert [(t["technique_id"], t["evidence_uids"]) for t in r["tecnicas_atribuidas"]] == [("T1046", ["A"])]
    assert "tecnica_sin_evidencia_de_incidente" in r["d11_warnings"]


# --- B2: ciclo de corrección ---------------------------------------------------------------

@pytest.mark.parametrize("final, consolidado, correcciones, esperado", [
    ({"hay_incidente": False, "hay_anomalia": False}, "anomalia_operativa", 0, "tool_corregir_diagnostico"),
    ({"hay_incidente": False, "hay_anomalia": True}, "anomalia_operativa", 0, "__end__"),
    ({"hay_incidente": True, "hay_anomalia": True}, "normal", 1, "__end__"),
])
def test_router_de_coherencia(final, consolidado, correcciones, esperado):
    from src.graph.routers import router_coherencia
    estado = dict(final, veredicto_consolidado=consolidado, correcciones_auditor=correcciones,
                  replan_count=0, plan={"pasos": []}, cobertura_suficiente=True)
    assert router_coherencia(estado) == esperado


def test_la_correccion_guarda_el_diagnostico_inicial_y_adopta_la_clase_del_auditor():
    from src.tools.tool_corregir_diagnostico import tool_corregir_diagnostico
    delta = tool_corregir_diagnostico({"diagnostico": "triage: falla de hardware", "evaluacion_auditor": "Lote normal",
                                       "hay_incidente": False, "hay_anomalia": False,
                                       "veredicto_consolidado": "anomalia_operativa", "intentos_correccion": 2})
    assert delta["diagnostico_inicial"] == "triage: falla de hardware"
    assert delta["diagnostico"] == delta["diagnostico_corregido"] == "Lote normal"
    assert delta["veredicto_consolidado"] == "normal" and delta["correcciones_auditor"] == 1
    assert delta["historial_correcciones"] == [{"correccion": 1, "clase_anterior": "anomalia_operativa",
                                                "clase_nueva": "normal"}]
    assert delta["intentos_correccion"] == 0


def _grafo_simulado(monkeypatch, veredictos_auditor):
    """Corre el grafo completo con el modelo simulado. El auditor responde en orden `veredictos_auditor`."""
    import src.agents.agente_analista_triage as triage
    import src.agents.agente_auditor_final as auditor
    import src.agents.agente_ingeniero_mitigacion as mitigacion
    import src.agents.agente_planificador as planificador
    import src.agents.agente_selector_herramientas as selector
    import src.pipeline as pipeline
    import src.tools.tool_consultar_rag as rag
    monkeypatch.setattr(pipeline, "_app", None)
    monkeypatch.setattr(rag.ltm, "retrieve_attack_techniques", lambda *a, **k: [])
    pedidos = {"mitigacion": [], "auditor": 0}
    monkeypatch.setattr(planificador, "llm_json", lambda *a, **k: {
        "objetivo": "o", "pasos": [{"id": 1, "accion": "triage", "objetivo": "d", "estado": "pendiente"},
                                   {"id": 2, "accion": "mitigacion", "objetivo": "c", "estado": "pendiente"}],
        "criterios_finalizacion": ["x"]})
    monkeypatch.setattr(triage, "llm_json", lambda *a, **k: {
        "diagnostico": "Falla de hardware del kernel", "veredicto_preliminar": "anomalia_operativa",
        "justificacion_veredicto": "línea FATAL"})
    monkeypatch.setattr(selector, "llm_json", lambda *a, **k: {"usar_cve": False, "razon": "no aplica"})

    def mitigar(prompt, system=None, **_):
        pedidos["mitigacion"].append(prompt)
        return {"comandos": ["dmesg"]}

    def auditar(prompt, system=None, **_):
        incidente, anomalia = veredictos_auditor[min(pedidos["auditor"], len(veredictos_auditor) - 1)]
        pedidos["auditor"] += 1
        pedidos.setdefault("auditor_prompts", []).append(prompt)
        return {"confianza": 0.9, "hay_anomalia": anomalia, "hay_incidente": incidente,
                "evaluacion": f"Evaluación del auditor {pedidos['auditor']}", "cobertura_auditor": True,
                "eventos_reconstruidos": [], "secuencia_temporal": [], "tecnicas_atribuidas": []}

    monkeypatch.setattr(mitigacion, "llm_json", mitigar)
    monkeypatch.setattr(auditor, "llm_json", auditar)
    estado = pipeline.analizar_lote(lote_bgl(), thread_id=f"fase_b_{len(veredictos_auditor)}")
    return estado, pedidos


def test_el_auditor_contradice_al_triage_y_se_rediseña_la_mitigacion(monkeypatch):
    estado, pedidos = _grafo_simulado(monkeypatch, [(False, False)])       # el auditor dice "normal"
    assert estado["_error_api"] is None
    assert "agente_cazador" not in [e["nodo"] for e in estado["historial_ejecucion"]]
    assert "GRUPOS CON SEÑAL" in pedidos["auditor_prompts"][0]           # auditor reforzado (por defecto)
    assert estado["correcciones_auditor"] == 1 and pedidos["auditor"] == 2 and len(pedidos["mitigacion"]) == 2
    assert "VEREDICTO CONSOLIDADO: normal" in pedidos["mitigacion"][1]
    assert estado["diagnostico_inicial"] == "Falla de hardware del kernel"
    assert estado["diagnostico"] == "Evaluación del auditor 1"
    assert estado["classification_detallada"] == "normal" == estado["veredicto_consolidado"]
    assert estado["historial_correcciones"] == [{"correccion": 1, "clase_anterior": "anomalia_operativa",
                                                 "clase_nueva": "normal"}]
    nodos = [e["nodo"] for e in estado["historial_ejecucion"]]
    assert nodos.count("tool_corregir_diagnostico") == 1 and nodos.count("agente_ingeniero_mitigacion") == 2


def test_el_ciclo_de_correccion_respeta_el_maximo(monkeypatch):
    # El auditor dice "normal" y, tras corregir, "incidente": no hay segunda corrección.
    estado, pedidos = _grafo_simulado(monkeypatch, [(False, False), (True, True)])
    assert estado["correcciones_auditor"] == config.MAX_CORRECCIONES_AUDITOR == 1
    assert pedidos["auditor"] == 2 and len(pedidos["mitigacion"]) == 2
    assert estado["classification_detallada"] == "incidente_seguridad"


def test_sin_contradiccion_no_hay_correccion(monkeypatch):
    estado, pedidos = _grafo_simulado(monkeypatch, [(False, True)])        # coincide: anomalía operativa
    assert estado["correcciones_auditor"] == 0 and pedidos["auditor"] == 1
    assert estado["diagnostico_inicial"] == ""


# --- grafo y trazabilidad -----------------------------------------------------------------

def test_el_grafo_final_tiene_el_nuevo_orden_y_no_tiene_cazador():
    from src.graph.build_graph import build_graph
    g = build_graph().get_graph()
    aristas = {(e.source, e.target) for e in g.edges}
    assert "agente_cazador" not in g.nodes
    assert {("agente_analista_triage", "tool_consultar_rag"), ("tool_consultar_rag", "agente_selector_herramientas"),
            ("agente_auditor_final", "tool_corregir_diagnostico"),
            ("tool_corregir_diagnostico", "agente_ingeniero_mitigacion")} <= aristas
    assert ("tool_consultar_rag", "agente_analista_triage") not in aristas


def test_la_traza_registra_el_rag_sin_hipotesis():
    from src.graph.plan_tracking import actualizar_plan
    estado = {"plan": {"plan_version": 1, "pasos": [{"id": 1, "accion": "rag", "estado": "pendiente"}]},
              "historial_ejecucion": [{"nodo": "agente_analista_triage"}]}
    traza = actualizar_plan(estado, "tool_consultar_rag", {"rag_omitido": "sin hipótesis de seguridad"})
    assert [e["nodo"] for e in traza["historial_ejecucion"]] == ["tool_consultar_rag"]
    assert traza["historial_ejecucion"][0]["estado"] == "omitido"
    assert traza["plan"]["pasos"][0]["estado"] == "omitido"
