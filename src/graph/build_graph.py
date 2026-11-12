"""Construcción del StateGraph (LangGraph): 8 nodos + 4 routers condicionales.

Migrado desde la celda 22 del notebook de Colab (sección "4. CONSTRUCCIÓN DEL GRAFO").

Arquitectura Plan-and-Execute real (11-sep-2026). El diagrama de esta
versión distingue los 4 pasos que el Planificador realmente decide
(triage, rag, cve, mitigacion -- el único vocabulario que produce
`agente_planificador`, ver `src/agents/agente_planificador.py`) de los 3
mecanismos internos del grafo (selector, validacion, auditoria) que
siempre se ejecutan y nunca son un paso planificado:

    Entrada (lote de logs crudos)
     -> AGREGACIÓN (código, sin LLM)                         [src/tools/aggregation.py]
      -> CORROBORACIÓN DE IPs (código + caché, AbuseIPDB)     [src/tools/reputation.py]
       -> agente_planificador (LLM)                            [PLANIFICACIÓN]
        -> agente_analista_triage (LLM, [PLAN: triage]) --router_triage--> tool_consultar_rag (Tool, [PLAN: rag])
         -> agente_selector_herramientas (LLM, [interno]) --router_selector--> tool_consultar_cve (Tool, [PLAN: cve])
          -> agente_ingeniero_mitigacion (LLM, [PLAN: mitigacion])
           -> tool_validar_comandos (Tool, [interno]) --router_validacion--> (retry o continúa)
            -> agente_auditor_final (LLM, [interno]) --router_finalizacion--> agente_planificador (replan) | FIN
             -> SALIDA: confianza, diagnóstico, comandos_mitigacion, plan, historial_ejecucion
              -> FEEDBACK -> memoria (ChromaDB, ver src/pipeline.py)

`router_finalizacion` reemplaza la arista directa que antes iba de
`agente_auditor_final` a END: decide si el ciclo terminó o si hace falta
replanificar (acotado por `MAX_REPLANS`, ver `src/graph/routers.py`). Los
3 routers preexistentes (triage/selector/validacion) no cambian: siguen
resolviendo decisiones LOCALES con evidencia real, el plan no las
sobreescribe -- ver `src/graph/plan_tracking.py` para cómo el plan y la
ejecución real se mantienen trazables sin que uno gobierne rígidamente al
otro.
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from src.agents.agente_analista_triage import agente_analista_triage
from src.agents.agente_auditor_final import agente_auditor_final
from src.agents.agente_ingeniero_mitigacion import agente_ingeniero_mitigacion
from src.agents.agente_planificador import agente_planificador
from src.agents.agente_selector_herramientas import agente_selector_herramientas
from src.graph.plan_tracking import actualizar_plan
from src.graph.routers import router_finalizacion, router_selector, router_triage, router_validacion
from src.state import LogGuardState
from src.tools.tool_consultar_cve import tool_consultar_cve
from src.tools.tool_consultar_rag import tool_consultar_rag
from src.tools.tool_validar_comandos import tool_validar_comandos


def _con_traza(nombre: str, fn):
    """Envuelve un nodo para registrar su ejecución en `historial_ejecucion`/
    `desviaciones_plan` y actualizar el "estado" del paso del plan que
    corresponda (ver `src/graph/plan_tracking.py`), SIN modificar el nodo
    real -- `fn` corre exactamente igual que antes, esto solo agrega la
    traza a partir de lo que `fn` ya devolvió.

    No envuelve a `agente_planificador`: ese nodo arma su propia entrada de
    trazabilidad (ver su docstring) porque `actualizar_plan` necesita el
    plan VIEJO para resolver pasos, mientras que el planificador es quien
    produce el plan NUEVO -- envolverlo pisaría el plan recién generado con
    el que había antes.
    """
    def envoltura(state: LogGuardState) -> dict:
        delta = fn(state)
        traza = actualizar_plan(state, nombre, delta)
        return {**delta, **traza}
    return envoltura


def build_graph():
    """Grafo de NODEX. Con `RAG_POR_HIPOTESIS` (NODEX final, Fase B) el orden es:

        planificador -> triage -> router_caza -> [agente_cazador] -> tool_consultar_rag
          -> selector -> [cve] -> mitigación -> validación (ciclo) -> auditor
          -> router_coherencia -> [tool_corregir_diagnostico -> mitigación ...] | router_finalizacion

    Apagado, el grafo es el de la Fase A (triage <-> RAG). Los interruptores se
    leen al construir el grafo (`src/config.py`).
    """
    import src.config as config
    if config.RAG_POR_HIPOTESIS:
        return _grafo_fase_b(config)
    return _grafo_fase_a()


def _grafo_fase_b(config):
    from src.agents.agente_cazador import agente_cazador
    from src.graph.routers import router_caza, router_coherencia
    from src.tools.tool_corregir_diagnostico import tool_corregir_diagnostico

    workflow = StateGraph(LogGuardState)
    workflow.add_node("agente_planificador", agente_planificador)
    for nombre, fn in (("agente_analista_triage", agente_analista_triage),
                       ("agente_cazador", agente_cazador),
                       ("tool_consultar_rag", tool_consultar_rag),
                       ("agente_selector_herramientas", agente_selector_herramientas),
                       ("tool_consultar_cve", tool_consultar_cve),
                       ("agente_ingeniero_mitigacion", agente_ingeniero_mitigacion),
                       ("tool_validar_comandos", tool_validar_comandos),
                       ("agente_auditor_final", agente_auditor_final),
                       ("tool_corregir_diagnostico", tool_corregir_diagnostico)):
        workflow.add_node(nombre, _con_traza(nombre, fn))

    workflow.add_edge(START, "agente_planificador")
    workflow.add_edge("agente_planificador", "agente_analista_triage")
    workflow.add_conditional_edges("agente_analista_triage", router_caza,
                                   {"agente_cazador": "agente_cazador",
                                    "tool_consultar_rag": "tool_consultar_rag"})
    workflow.add_edge("agente_cazador", "tool_consultar_rag")
    workflow.add_edge("tool_consultar_rag", "agente_selector_herramientas")
    workflow.add_conditional_edges("agente_selector_herramientas", router_selector,
                                   {"tool_consultar_cve": "tool_consultar_cve",
                                    "agente_ingeniero_mitigacion": "agente_ingeniero_mitigacion"})
    workflow.add_edge("tool_consultar_cve", "agente_ingeniero_mitigacion")
    workflow.add_edge("agente_ingeniero_mitigacion", "tool_validar_comandos")
    workflow.add_conditional_edges("tool_validar_comandos", router_validacion,
                                   {"agente_ingeniero_mitigacion": "agente_ingeniero_mitigacion",
                                    "agente_auditor_final": "agente_auditor_final"})
    workflow.add_conditional_edges("agente_auditor_final", router_coherencia,
                                   {"tool_corregir_diagnostico": "tool_corregir_diagnostico",
                                    "agente_planificador": "agente_planificador",
                                    END: END})
    workflow.add_edge("tool_corregir_diagnostico", "agente_ingeniero_mitigacion")
    return workflow.compile(checkpointer=MemorySaver())


def _grafo_fase_a():
    workflow = StateGraph(LogGuardState)

    # Registrar los 8 nodos (5 LLM + 3 Tool). agente_planificador sin
    # envoltura (ver docstring de _con_traza); los 7 restantes, envueltos.
    workflow.add_node("agente_planificador", agente_planificador)                                         # LLM
    workflow.add_node("agente_analista_triage", _con_traza("agente_analista_triage", agente_analista_triage))              # LLM
    workflow.add_node("tool_consultar_rag", _con_traza("tool_consultar_rag", tool_consultar_rag))                          # Tool
    workflow.add_node("agente_selector_herramientas", _con_traza("agente_selector_herramientas", agente_selector_herramientas))  # LLM
    workflow.add_node("tool_consultar_cve", _con_traza("tool_consultar_cve", tool_consultar_cve))                          # Tool
    workflow.add_node("agente_ingeniero_mitigacion", _con_traza("agente_ingeniero_mitigacion", agente_ingeniero_mitigacion))  # LLM
    workflow.add_node("tool_validar_comandos", _con_traza("tool_validar_comandos", tool_validar_comandos))                 # Tool
    workflow.add_node("agente_auditor_final", _con_traza("agente_auditor_final", agente_auditor_final))                    # LLM

    # Aristas directas
    workflow.add_edge(START, "agente_planificador")
    workflow.add_edge("agente_planificador", "agente_analista_triage")  # primera vez o tras replan
    workflow.add_edge("tool_consultar_rag", "agente_analista_triage")   # RAG → vuelve al triage con contexto
    workflow.add_edge("tool_consultar_cve", "agente_ingeniero_mitigacion")
    workflow.add_edge("agente_ingeniero_mitigacion", "tool_validar_comandos")

    # Aristas condicionales (los 4 routers)
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

    workflow.add_conditional_edges(
        "agente_auditor_final",
        router_finalizacion,
        {
            "agente_planificador": "agente_planificador",
            END: END,
        },
    )

    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)
