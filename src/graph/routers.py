"""Routers — las 4 aristas condicionales del grafo.

Las 3 primeras migradas desde la celda 22 del notebook de Colab (sección
"3. ROUTERS"). `router_finalizacion` es nueva (11-sep-2026, Plan-and-Execute).
"""

from typing import Literal

from langgraph.graph import END

from src.config import MAX_INTENTOS_CORRECCION, MAX_REPLANS
from src.state import LogGuardState


def router_triage(state: LogGuardState) -> Literal["tool_consultar_rag", "agente_selector_herramientas"]:
    """Router 1: ¿Necesita contexto histórico de ChromaDB?"""
    if state["necesita_rag"]:
        print("   🔀 Router Triage → tool_consultar_rag")
        return "tool_consultar_rag"
    print("   🔀 Router Triage → agente_selector_herramientas")
    return "agente_selector_herramientas"


def router_selector(state: LogGuardState) -> Literal["tool_consultar_cve", "agente_ingeniero_mitigacion"]:
    """Router 2: ¿El selector decidió usar CVEs de NVD?"""
    if state.get("usar_cve", False):
        print("   🔀 Router Selector → tool_consultar_cve")
        return "tool_consultar_cve"
    print("   🔀 Router Selector → agente_ingeniero_mitigacion")
    return "agente_ingeniero_mitigacion"


def router_validacion(state: LogGuardState) -> Literal["agente_ingeniero_mitigacion", "agente_auditor_final"]:
    """Router 3: ¿Los comandos son válidos? Si no, ciclo de corrección (máx MAX_INTENTOS_CORRECCION)."""
    intentos = state.get("intentos_correccion", 0)

    if not state["comandos_validos"] and intentos < MAX_INTENTOS_CORRECCION:
        print(f"   🔀 Router Validación → agente_ingeniero_mitigacion (intento {intentos}/{MAX_INTENTOS_CORRECCION})")
        return "agente_ingeniero_mitigacion"

    if not state["comandos_validos"]:
        print("   🔀 Router Validación → agente_auditor_final (máx intentos alcanzado)")
    else:
        print("   🔀 Router Validación → agente_auditor_final (comandos OK)")
    return "agente_auditor_final"


def router_caza(state: LogGuardState) -> Literal["agente_cazador", "tool_consultar_rag"]:
    """Router de caza (NODEX final, B1): ¿hay grupos minoritarios que examinar?

    Omite al cazador si no hay grupos con señal (o si `CAZADOR_ACTIVO` está
    apagado). La omisión queda en `historial_ejecucion` (la registra la traza del
    nodo siguiente, ver `plan_tracking.actualizar_plan`).
    """
    from src.agents.agente_cazador import grupos_para_cazador
    from src.config import CAZADOR_ACTIVO
    if CAZADOR_ACTIVO and grupos_para_cazador(state):
        print("   🔀 Router Caza → agente_cazador")
        return "agente_cazador"
    print("   🔀 Router Caza → tool_consultar_rag (sin grupos con señal: cazador omitido)")
    return "tool_consultar_rag"


def router_coherencia(state: LogGuardState):
    """Router de coherencia (NODEX final, B2), después del auditor.

    Si la clase del veredicto final del auditor difiere del veredicto consolidado
    y quedan correcciones (`MAX_CORRECCIONES_AUDITOR`), vuelve a diseñar la
    mitigación sobre el diagnóstico corregido. Si coinciden (o se alcanzó el
    máximo), sigue al router de finalización existente.
    """
    from src.config import CORRECCION_AUDITOR, MAX_CORRECCIONES_AUDITOR
    from src.graph.veredicto import clase_final
    final, consolidado = clase_final(state), state.get("veredicto_consolidado")
    if (CORRECCION_AUDITOR and final and consolidado and final != consolidado
            and (state.get("correcciones_auditor") or 0) < MAX_CORRECCIONES_AUDITOR):
        print(f"   🔀 Router Coherencia → tool_corregir_diagnostico ({consolidado} ≠ {final})")
        return "tool_corregir_diagnostico"
    return router_finalizacion(state)


def router_finalizacion(state: LogGuardState):
    """Router 4: ¿el ciclo termina, o replanifica?

    No depende únicamente de `cobertura_suficiente` (un booleano de origen
    LLM, aunque ya viene combinado con una verificación determinística
    dentro del propio auditor -- ver `agente_auditor_final.py`): este
    router hace su PROPIA verificación directa sobre `state["plan"]`, como
    defensa adicional ante un juicio del LLM equivocado. El tope
    `MAX_REPLANS` se evalúa primero y sin excepción -- garantiza que no hay
    loop infinito sin importar qué digan las demás condiciones.
    """
    if state.get("replan_count", 0) >= MAX_REPLANS:
        print(f"   🔀 Router Finalización → END (MAX_REPLANS={MAX_REPLANS} alcanzado)")
        return END

    pasos = (state.get("plan") or {}).get("pasos", [])
    hay_fallidos = any(p.get("estado") == "fallido" for p in pasos)
    hay_pendientes = any(p.get("estado") == "pendiente" for p in pasos)
    cobertura_suficiente = state.get("cobertura_suficiente")

    if hay_fallidos or hay_pendientes or not cobertura_suficiente:
        motivo = "pasos fallidos" if hay_fallidos else "pasos pendientes" if hay_pendientes else "cobertura insuficiente"
        print(f"   🔀 Router Finalización → agente_planificador (replanifica: {motivo})")
        return "agente_planificador"

    print("   🔀 Router Finalización → END (plan cumplido)")
    return END
