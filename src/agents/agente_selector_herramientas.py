"""Nodo LLM: agente_selector_herramientas.

Migrado desde la celda 22 del notebook de Colab.

Decide si el análisis necesita buscar CVEs en NVD. Alimenta el router
`router_selector`.
"""

from src.llm import llm_json
from src.state import LogGuardState


def agente_selector_herramientas(state: LogGuardState) -> dict:
    print("\n🤖 [Agente Selector] Decidiendo qué herramientas usar...")

    sys_instruction = (
        "Eres un coordinador de análisis de seguridad. "
        "Tienes acceso a estas herramientas: [query_cve, validate_solution]. "
        "Analiza el diagnóstico y decide si se deben buscar CVEs asociados al ataque. "
        "query_cve es útil cuando el diagnóstico menciona un servicio o vulnerabilidad específica. "
        'Responde SOLO en JSON: {"usar_cve": true/false, "razon": "..."}'
    )
    user_content = (
        f"DIAGNÓSTICO ACTUAL: {state.get('diagnostico', 'Sin diagnóstico')}\n"
        f"RESUMEN DEL LOTE: servicios={state['resumen_logs'].get('servicios', {})}"
    )

    respuesta = llm_json(user_content, system=sys_instruction)
    usar_cve = respuesta.get("usar_cve", True)
    razon = respuesta.get("razon", "")

    print(f"   → usar_cve: {usar_cve} | Razón: {razon}")
    return {"usar_cve": usar_cve}
