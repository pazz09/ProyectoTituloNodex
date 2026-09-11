"""Tests estructurales de `build_graph()` -- inspecciona el grafo compilado
vía `app.get_graph()` (API pública de LangGraph), sin invocar a ningún
nodo. No hay LLM de por medio: esto solo verifica la TOPOLOGÍA.
"""

from langgraph.graph import END

from src.graph.build_graph import build_graph


def _grafo():
    return build_graph().get_graph()


def test_hay_ocho_nodos_cinco_llm_tres_tool():
    grafo = _grafo()
    nodos = {n for n in grafo.nodes if n not in ("__start__", "__end__")}
    assert nodos == {
        "agente_planificador", "agente_analista_triage", "tool_consultar_rag",
        "agente_selector_herramientas", "tool_consultar_cve",
        "agente_ingeniero_mitigacion", "tool_validar_comandos", "agente_auditor_final",
    }


# --- C: el grafo comienza por el Planificador -----------------------------

def test_start_apunta_a_agente_planificador():
    grafo = _grafo()
    destinos_start = {e.target for e in grafo.edges if e.source == "__start__"}
    assert destinos_start == {"agente_planificador"}


def test_planificador_apunta_al_triage():
    grafo = _grafo()
    destinos = {e.target for e in grafo.edges if e.source == "agente_planificador"}
    assert destinos == {"agente_analista_triage"}


def test_auditor_puede_volver_al_planificador_o_terminar():
    """La arista condicional de router_finalizacion: agente_auditor_final
    debe poder ir tanto a agente_planificador (replan) como a __end__."""
    grafo = _grafo()
    destinos = {e.target for e in grafo.edges if e.source == "agente_auditor_final"}
    assert "agente_planificador" in destinos
    assert "__end__" in destinos


def test_los_tres_routers_preexistentes_siguen_intactos():
    grafo = _grafo()
    aristas = {(e.source, e.target) for e in grafo.edges}
    # router_triage
    assert ("agente_analista_triage", "tool_consultar_rag") in aristas
    assert ("agente_analista_triage", "agente_selector_herramientas") in aristas
    assert ("tool_consultar_rag", "agente_analista_triage") in aristas  # arista directa de vuelta
    # router_selector
    assert ("agente_selector_herramientas", "tool_consultar_cve") in aristas
    assert ("agente_selector_herramientas", "agente_ingeniero_mitigacion") in aristas
    # router_validacion
    assert ("tool_validar_comandos", "agente_ingeniero_mitigacion") in aristas
    assert ("tool_validar_comandos", "agente_auditor_final") in aristas
