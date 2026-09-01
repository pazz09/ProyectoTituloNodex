"""Routers — las 3 aristas condicionales del grafo.

Migrado desde la celda 22 del notebook de Colab (sección "3. ROUTERS").
"""

from typing import Literal

from src.config import MAX_INTENTOS_CORRECCION
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
