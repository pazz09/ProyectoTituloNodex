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
    # El selector decidía mirando solo `servicios`, que con el esquema v2
    # puede traer nombres internos (`hdfs.datanode`) inútiles para buscar
    # CVEs. Se le agregan producto, categoría y protocolo, que son las
    # señales con las que la NVD indexa (Fase 10 del plan).
    metadatos = state.get("preprocessing_metadata") or {}
    resumen = state.get("resumen_logs") or {}
    senales = [f"servicios={resumen.get('servicios', {})}"]
    for etiqueta, clave in (("productos", "product_distribution"),
                            ("categorias", "event_categories"),
                            ("severidades", "severity_distribution")):
        valor = metadatos.get(clave)
        if valor:
            senales.append(f"{etiqueta}={valor}")

    user_content = (
        f"DIAGNÓSTICO ACTUAL: {state.get('diagnostico', 'Sin diagnóstico')}\n"
        f"RESUMEN DEL LOTE: {' '.join(senales)}"
    )

    respuesta = llm_json(user_content, system=sys_instruction)
    usar_cve = respuesta.get("usar_cve", True)
    razon = respuesta.get("razon", "")

    print(f"   → usar_cve: {usar_cve} | Razón: {razon}")
    # La razón se devuelve al estado, no solo a la consola: el §8.7.1 del
    # informe nombra "la decisión sobre la necesidad de consultar memoria o
    # conocimiento externo" como una tarea del flujo, y sin su justificación
    # esa decisión no es auditable. La interfaz conversacional la muestra
    # como el mensaje de este agente.
    return {"usar_cve": usar_cve, "razon_seleccion": razon}
