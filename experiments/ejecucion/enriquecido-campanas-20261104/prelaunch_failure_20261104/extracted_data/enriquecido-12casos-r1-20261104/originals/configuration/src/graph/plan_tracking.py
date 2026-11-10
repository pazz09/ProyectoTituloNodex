"""Trazabilidad determinística del plan (Plan-and-Execute, 11-sep-2026).

No depende del LLM ni de ChromaDB -- es lógica pura sobre `state["plan"]`
y el `delta` que cada nodo del grafo devuelve. La invoca `_con_traza()`
en `build_graph.py`, envolviendo a cada uno de los 7 nodos existentes sin
modificarlos.

Vocabulario cerrado de `accion` (4 miembros, no 7): `triage`, `rag`, `cve`
y `mitigacion` son los únicos pasos con contenido de decisión real --
incluir/excluir (rag, cve) o un objetivo que vale la pena orientar
(triage, mitigacion). `agente_selector_herramientas`, `tool_validar_comandos`
y `agente_auditor_final` son mecanismos internos del grafo: siempre se
ejecutan, quedan trazados en `historial_ejecucion`, pero el Planificador
nunca los genera como pasos -- planificar "si conviene usar el selector"
no tendría contenido, porque el selector siempre corre.

Dos de estos mecanismos internos SÍ resuelven un paso del plan, aunque no
tengan uno propio: la decisión del selector (`usar_cve`) resuelve --por
omisión-- el paso "cve" si estaba planificado, y el resultado de
`tool_validar_comandos` resuelve el paso "mitigacion" (ejecutado si validó,
fallido si se agotaron los reintentos sin validar).
"""

from src.config import MAX_INTENTOS_CORRECCION

ACCIONES_VALIDAS = ("triage", "rag", "cve", "mitigacion")

# Nodo del grafo -> acción del plan que representa, o None si es un
# mecanismo interno sin paso propio.
NODO_A_ACCION = {
    "agente_analista_triage": "triage",
    "tool_consultar_rag": "rag",
    "agente_selector_herramientas": None,
    "tool_consultar_cve": "cve",
    "agente_ingeniero_mitigacion": "mitigacion",
    "tool_validar_comandos": None,
    "agente_auditor_final": None,
    "agente_planificador": None,
}


def _paso_pendiente(plan: dict, accion: str) -> dict | None:
    for paso in plan.get("pasos", []):
        if paso.get("accion") == accion and paso.get("estado") == "pendiente":
            return paso
    return None


def _resumen(nodo: str, delta: dict) -> str | None:
    """Nota breve y determinística de lo que ese nodo devolvió -- no la
    genera el LLM, se arma con reglas simples a partir del delta real."""
    if nodo == "agente_planificador":
        plan = delta.get("plan") or {}
        return f"plan v{plan.get('plan_version')}, {len(plan.get('pasos') or [])} pasos"
    if nodo == "agente_analista_triage":
        if delta.get("diagnostico"):
            return "diagnóstico producido"
        return "solicitó contexto histórico (RAG)"
    if nodo == "tool_consultar_rag":
        return (f"{len(delta.get('contexto_rag') or [])} patrones, "
                f"{len(delta.get('tecnicas_mitre') or [])} técnicas MITRE")
    if nodo == "agente_selector_herramientas":
        return f"usar_cve={delta.get('usar_cve')}"
    if nodo == "tool_consultar_cve":
        return f"{len(delta.get('cves_encontrados') or [])} CVEs encontrados"
    if nodo == "agente_ingeniero_mitigacion":
        return f"{len(delta.get('comandos_mitigacion') or [])} comandos propuestos"
    if nodo == "tool_validar_comandos":
        return "comandos válidos" if delta.get("comandos_validos") else "comandos rechazados"
    if nodo == "agente_auditor_final":
        return (f"confianza={delta.get('confianza')} "
                f"cobertura_suficiente={delta.get('cobertura_suficiente')}")
    return None


def actualizar_plan(state: dict, nodo: str, delta: dict) -> dict:
    """Se llama DESPUÉS de que `nodo` corrió, con `state` tal como estaba
    ANTES de aplicar `delta` (así llega `_con_traza`, que envuelve al nodo
    real). Devuelve el delta de trazabilidad a fusionar además del propio
    del nodo: `plan` (con los "estado" de paso que correspondan mutados),
    `paso_actual`, y las entradas nuevas de `historial_ejecucion` /
    `desviaciones_plan`.
    """
    plan = state.get("plan") or {}
    plan_version = plan.get("plan_version")
    paso_actual = state.get("paso_actual")
    desviaciones: list[dict] = []
    step_id = None
    accion_evento = None
    estado_evento = "ejecutado"

    def _marcar(accion: str, estado: str, motivo: str | None = None) -> int | None:
        paso = _paso_pendiente(plan, accion)
        if paso is None:
            return None
        paso["estado"] = estado
        if motivo is not None:
            paso["motivo"] = motivo
        return paso["id"]

    if nodo == "agente_analista_triage":
        accion_evento = "triage"
        if delta.get("diagnostico"):
            marcado = _marcar("triage", "ejecutado")
            step_id = marcado if marcado is not None else step_id
            paso_actual = step_id if step_id is not None else paso_actual
            if delta.get("necesita_rag") is False:
                _marcar("rag", "omitido",
                        motivo="el triage determinó que no hacía falta contexto histórico")
        else:
            pendiente = _paso_pendiente(plan, "triage")
            step_id = pendiente["id"] if pendiente else None
            paso_actual = step_id if step_id is not None else paso_actual

    elif nodo == "tool_consultar_rag":
        accion_evento = "rag"
        pendiente = _paso_pendiente(plan, "rag")
        if pendiente is not None:
            step_id = _marcar("rag", "ejecutado")
        else:
            desviaciones.append({
                "plan_version": plan_version, "accion": "rag", "nodo": nodo,
                "evidencia": "el triage solicitó contexto histórico",
                "motivo": "el plan no incluía un paso de recuperación de memoria",
            })
        paso_actual = step_id if step_id is not None else paso_actual

    elif nodo == "agente_selector_herramientas":
        # Mecanismo interno: sin accion propia, pero su decisión resuelve
        # (por omisión) el paso "cve" si estaba planificado.
        if delta.get("usar_cve") is False:
            _marcar("cve", "omitido",
                    motivo=delta.get("razon_seleccion") or "el selector determinó que no correspondía")

    elif nodo == "tool_consultar_cve":
        accion_evento = "cve"
        pendiente = _paso_pendiente(plan, "cve")
        if pendiente is not None:
            step_id = _marcar("cve", "ejecutado")
        else:
            desviaciones.append({
                "plan_version": plan_version, "accion": "cve", "nodo": nodo,
                "evidencia": "el selector determinó usar_cve=True",
                "motivo": "el plan no incluía un paso de consulta de vulnerabilidades",
            })
        paso_actual = step_id if step_id is not None else paso_actual

    elif nodo == "agente_ingeniero_mitigacion":
        accion_evento = "mitigacion"
        pendiente = _paso_pendiente(plan, "mitigacion")
        step_id = pendiente["id"] if pendiente else None
        paso_actual = step_id if step_id is not None else paso_actual
        # No se resuelve acá: lo resuelve tool_validar_comandos, que es
        # quien sabe si el intento final validó o no.

    elif nodo == "tool_validar_comandos":
        # Mecanismo interno: su resultado resuelve el paso "mitigacion".
        # `state["intentos_correccion"]` ya refleja el incremento que hizo
        # agente_ingeniero_mitigacion en el paso anterior del grafo (su
        # delta ya se fusionó al estado antes de que este nodo corriera).
        intentos = state.get("intentos_correccion", 0)
        if delta.get("comandos_validos") is True:
            _marcar("mitigacion", "ejecutado")
        elif intentos >= MAX_INTENTOS_CORRECCION:
            _marcar("mitigacion", "fallido",
                    motivo="se agotaron los reintentos sin validar los comandos")
            estado_evento = "fallido"
        # si no validó y aún quedan reintentos, el paso sigue "pendiente"

    # agente_auditor_final y agente_planificador: mecanismos internos que
    # no marcan pasos propios -- igual quedan registrados en historial_ejecucion.

    entrada = {
        "plan_version": plan_version,
        "step_id": step_id,
        "nodo": nodo,
        "accion": accion_evento,
        "estado": estado_evento,
        "resumen": _resumen(nodo, delta),
    }
    return {
        "plan": plan,
        "paso_actual": paso_actual,
        "historial_ejecucion": [entrada],
        "desviaciones_plan": desviaciones,
    }
