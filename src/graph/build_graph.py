"""Construcción del StateGraph (LangGraph): 7 nodos + 3 routers condicionales.

Migrado desde la celda 22 del notebook de Colab (sección "4. CONSTRUCCIÓN DEL GRAFO").

Arquitectura Plan-and-Execute:

    Entrada (lote de logs crudos)
     -> AGREGACIÓN (código, sin LLM)                         [src/tools/aggregation.py]
      -> CORROBORACIÓN DE IPs (código + caché, AbuseIPDB)     [src/tools/reputation.py]
       -> agente_analista_triage (LLM) --router_triage--> tool_consultar_rag (Tool)
        -> agente_selector_herramientas (LLM) --router_selector--> tool_consultar_cve (Tool)
         -> agente_ingeniero_mitigacion (LLM)
          -> tool_validar_comandos (Tool) --router_validacion--> (retry o continúa)
           -> agente_auditor_final (LLM)
            -> SALIDA: confianza, diagnóstico, comandos_mitigacion
             -> FEEDBACK -> memoria (ChromaDB, ver src/pipeline.py)
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from src.agents.agente_analista_triage import agente_analista_triage
from src.agents.agente_auditor_final import agente_auditor_final
from src.agents.agente_ingeniero_mitigacion import agente_ingeniero_mitigacion
from src.agents.agente_selector_herramientas import agente_selector_herramientas
from src.graph.routers import router_selector, router_triage, router_validacion
from src.state import LogGuardState
from src.tools.tool_consultar_cve import tool_consultar_cve
from src.tools.tool_consultar_rag import tool_consultar_rag
from src.tools.tool_validar_comandos import tool_validar_comandos


def build_graph():
    workflow = StateGraph(LogGuardState)

    # Registrar los 7 nodos (4 LLM + 3 Tool)
    workflow.add_node("agente_analista_triage", agente_analista_triage)              # LLM
    workflow.add_node("tool_consultar_rag", tool_consultar_rag)                      # Tool
    workflow.add_node("agente_selector_herramientas", agente_selector_herramientas)  # LLM
    workflow.add_node("tool_consultar_cve", tool_consultar_cve)                      # Tool
    workflow.add_node("agente_ingeniero_mitigacion", agente_ingeniero_mitigacion)    # LLM
    workflow.add_node("tool_validar_comandos", tool_validar_comandos)                # Tool
    workflow.add_node("agente_auditor_final", agente_auditor_final)                  # LLM

    # Aristas directas
    workflow.add_edge(START, "agente_analista_triage")
    workflow.add_edge("tool_consultar_rag", "agente_analista_triage")  # RAG → vuelve al triage con contexto
    workflow.add_edge("tool_consultar_cve", "agente_ingeniero_mitigacion")
    workflow.add_edge("agente_ingeniero_mitigacion", "tool_validar_comandos")
    workflow.add_edge("agente_auditor_final", END)

    # Aristas condicionales (los 3 routers)
    workflow.add_conditional_edges(
        "agente_analista_triage",
        router_triage,
        {
            "tool_consultar_rag": "tool_consultar_rag",
            "agente_selector_herramientas": "agente_selector_herramientas",
        },
    )

    workflow.add_conditional_edges(
        "agente_selector_herramientas",
        router_selector,
        {
            "tool_consultar_cve": "tool_consultar_cve",
            "agente_ingeniero_mitigacion": "agente_ingeniero_mitigacion",
        },
    )

    workflow.add_conditional_edges(
        "tool_validar_comandos",
        router_validacion,
        {
            "agente_ingeniero_mitigacion": "agente_ingeniero_mitigacion",
            "agente_auditor_final": "agente_auditor_final",
        },
    )

    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)
