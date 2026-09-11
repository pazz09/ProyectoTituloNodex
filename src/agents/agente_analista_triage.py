"""Nodo LLM: agente_analista_triage.

Migrado desde la celda 22 del notebook de Colab.

Analiza el resumen del lote de logs y decide si necesita contexto histórico
(RAG). Si ya cuenta con contexto RAG, genera el diagnóstico. Alimenta el
router `router_triage`.

**Primera pasada real (11-sep-2026, Plan-and-Execute).** Antes, la primera
vez que este nodo corría, `necesita_rag` se fijaba en `True` de forma
incondicional -- sin llamar al LLM -- así que RAG se consultaba SIEMPRE,
sin importar si el lote lo justificaba. Ahora la primera pasada es una
llamada real al LLM que decide, informado por si el plan (`agente_
planificador`) incluyó o no un paso "rag": si decide que no hace falta,
diagnostica directamente en la misma llamada; si decide que sí, pide RAG
sin diagnosticar todavía. El paso "rag" del plan (si existe) queda
"omitido" con el motivo real cuando esto ocurre (ver
`src/graph/plan_tracking.py`).
"""

import json

from src.llm import llm_json
from src.preprocessing.prompt_context import contexto_preprocesamiento
from src.state import LogGuardState
from src.tools.resumen_prompt import acotar_resumen_para_prompt


def _contexto_plan_rag(state: LogGuardState) -> str:
    """Qué dijo el plan sobre el paso 'rag', para informar (no dictar) la
    decisión del triage -- el plan es guía, la evidencia real manda."""
    plan = state.get("plan") or {}
    for paso in plan.get("pasos", []):
        if paso.get("accion") == "rag":
            return f"El plan de investigación contempla consultar memoria histórica: {paso.get('objetivo')}"
    return "El plan de investigación no contempla consultar memoria histórica para este caso."


def agente_analista_triage(state: LogGuardState) -> dict:
    print("\n🧠 [Agente Triage] Analizando el incidente...")

    # necesita_rag empieza en None (ver pipeline.py). La primera vez que
    # este nodo corre, `contexto_rag` está vacío Y `necesita_rag` es None
    # (falsy) -- cae a la rama de abajo, que ahora SÍ decide con el LLM. Al
    # volver desde RAG, `necesita_rag` ya quedó en True (lo puso esta misma
    # función), y esa es la señal de "el RAG ya corrió una vez", haya o no
    # encontrado algo -- sin este OR, una lista vacía nunca es "truthy" y el
    # nodo pediría RAG de nuevo en un loop infinito con el router.
    if state.get("contexto_rag") or state.get("necesita_rag"):
        print("   → Contexto RAG disponible. Generando diagnóstico...")
        sys_instruction = (
            "Eres un analista SOC experto. Basándote en el resumen del lote de logs, "
            "el contexto histórico recuperado y las técnicas MITRE ATT&CK relacionadas, "
            "genera un diagnóstico del ataque. Si alguna técnica listada en TÉCNICAS "
            "MITRE ATT&CK realmente aplica a lo que ves en el resumen, cita su ID "
            "(p. ej. \"T1110\") dentro del diagnóstico; si ninguna aplica, o la lista "
            "viene vacía, no inventes IDs de técnica. "
            'Responde SOLO en JSON: {"diagnostico": "...", "necesita_rag": false}'
        )
        contexto_rag = state.get("contexto_rag") or []
        contexto_txt = (
            json.dumps(contexto_rag, ensure_ascii=False)
            if contexto_rag
            else "Sin patrones históricos previos (memoria aún vacía)."
        )
        # Técnicas MITRE ATT&CK recuperadas por tool_consultar_rag desde la
        # colección `attack_techniques` (STIX 2.1, ver src/memory.py) con la
        # misma firma del lote -- puede venir vacía si esa colección aún no
        # se pobló (`src/tools/preparar_mitre_attack.py`) o si nada superó
        # SIMILARITY_FLOOR.
        tecnicas_mitre = state.get("tecnicas_mitre") or []
        tecnicas_txt = (
            json.dumps(tecnicas_mitre, ensure_ascii=False)
            if tecnicas_mitre
            else "Sin técnicas MITRE ATT&CK relacionadas (colección vacía o sin similitud suficiente)."
        )
        # Acotado por costo (ver src/tools/resumen_prompt.py): el desglose
        # completo por_ip/ips_distintas/reputacion_ips escala en tokens con
        # la cantidad de IPs distintas del lote, no con las líneas de log
        # (hallazgo real 25-ago-2026). Esto NO toca state["resumen_logs"] --
        # solo el texto que ve el LLM aquí.
        resumen_para_llm = acotar_resumen_para_prompt(state["resumen_logs"])
        # Cómo se interpretó el lote: formatos, cobertura y advertencias.
        # Sin esto, el agente no puede saber que está diagnosticando sobre un
        # resumen incompleto y responde con la misma seguridad que si todo
        # se hubiera decodificado (Fase 10 del plan). Va vacío con el motor
        # v1, donde estos metadatos no existen.
        contexto_pre = contexto_preprocesamiento(
            state.get("preprocessing_metadata"),
            state.get("parsing_warnings"),
            state.get("raw_samples"),
            incluir_muestras=True,
        )
        plan_objetivo = state.get("plan_objetivo")
        user_content = (
            (f"OBJETIVO DEL PLAN DE INVESTIGACIÓN: {plan_objetivo}\n\n" if plan_objetivo else "")
            + f"RESUMEN DEL LOTE:\n{json.dumps(resumen_para_llm, ensure_ascii=False)}\n\n"
            + (f"{contexto_pre}\n\n" if contexto_pre else "")
            + f"CONTEXTO HISTÓRICO (RAG):\n{contexto_txt}\n\n"
            + f"TÉCNICAS MITRE ATT&CK RELACIONADAS:\n{tecnicas_txt}"
        )
        respuesta = llm_json(user_content, system=sys_instruction)
        return {
            "diagnostico": respuesta.get("diagnostico", "Ataque indeterminado"),
            "necesita_rag": False,
        }

    print("   → Primera pasada: decidiendo si hace falta contexto histórico...")
    sys_instruction = (
        "Eres un analista SOC experto. A partir del resumen del lote, decide si "
        "puedes diagnosticar directamente o si conviene primero consultar el "
        "historial de casos similares y técnicas MITRE ATT&CK relacionadas "
        "(memoria de largo plazo) antes de diagnosticar. Si decides que SÍ hace "
        "falta ese contexto, no diagnostiques todavía: pide la consulta. Si "
        "decides que NO hace falta, diagnostica directamente basándote solo en "
        "el resumen. "
        'Responde SOLO en JSON: {"necesita_rag": true/false, '
        '"diagnostico": "..." (vacío si necesita_rag es true), "razon": "..."}'
    )
    resumen_para_llm = acotar_resumen_para_prompt(state["resumen_logs"])
    plan_objetivo = state.get("plan_objetivo")
    user_content = (
        (f"OBJETIVO DEL PLAN DE INVESTIGACIÓN: {plan_objetivo}\n\n" if plan_objetivo else "")
        + f"{_contexto_plan_rag(state)}\n\n"
        + f"RESUMEN DEL LOTE:\n{json.dumps(resumen_para_llm, ensure_ascii=False)}"
    )
    respuesta = llm_json(user_content, system=sys_instruction)
    necesita_rag = bool(respuesta.get("necesita_rag", True))
    if not necesita_rag:
        print(f"   → No hace falta RAG ({respuesta.get('razon', 'sin razón')}). Diagnosticando directo...")
        return {
            "diagnostico": respuesta.get("diagnostico") or "Ataque indeterminado",
            "necesita_rag": False,
        }
    print(f"   → Solicitando RAG ({respuesta.get('razon', 'sin razón')})...")
    return {"necesita_rag": True}
