"""Nodo LLM: agente_planificador (11-sep-2026).

Primer nodo del grafo (antes del Triage). Produce un plan de investigación
-- QUÉ debe analizarse y en qué orden -- antes de que el análisis
especializado comience. No ejecuta herramientas ni fabrica resultados.

Vocabulario cerrado de 4 acciones (ver `src/graph/plan_tracking.py` para el
porqué de exactamente estas 4, y no las 7 del grafo): `triage` y
`mitigacion` son obligatorias (el plan decide su "objetivo", no si ocurren);
`rag` y `cve` son la única inclusión/exclusión real. `selector`,
`validacion` y `auditoria` son mecanismos internos del grafo, nunca pasos
del plan.

Se reinvoca cuando `router_finalizacion` decide replanificar (evidencia
insuficiente, pasos fallidos o pendientes tras el ciclo, hasta
`MAX_REPLANS` veces). En modo replan, el prompt incluye el plan anterior,
el historial de ejecución y toda la evidencia obtenida -- el nuevo plan es
función de eso, no una repetición de la misma entrada esperando una
respuesta distinta. `preparar_replanificacion()` reinicia el estado de
control de la ejecución (nunca a defaults optimistas: `None`, no `True`)
y conserva la evidencia (contexto_rag, tecnicas_mitre, cves_encontrados,
historial_ejecucion) para que el nuevo plan la use.

Aislamiento de ground truth: el prompt solo usa `resumen_logs`,
`preprocessing_metadata` y `parsing_warnings` -- los mismos campos que ya
usa `agente_analista_triage`, que nunca contienen etiquetas de evaluación
desde la Fase 7 del plan de preprocesamiento (ver
`src/preprocessing/ground_truth.py`). Nunca se le pasan campos de
`resumen_logs` como `cronologia`/`entidades` (excluidos también del prompt
del Triage, ver `src/tools/resumen_prompt.py`).
"""

import json

from src.config import MAX_PLAN_STEPS
from src.graph.plan_tracking import ACCIONES_VALIDAS
from src.llm import llm_json
from src.preprocessing.prompt_context import contexto_preprocesamiento
from src.state import LogGuardState
from src.tools.resumen_prompt import acotar_resumen_para_prompt

_OBJETIVOS_DEFAULT = {
    "triage": "Diagnosticar el lote a partir del resumen agregado.",
    "mitigacion": "Proponer comandos de mitigación acordes al diagnóstico.",
}


class PlanInvalidoError(Exception):
    """El LLM no produjo un plan utilizable (JSON inválido o sin pasos
    ejecutables tras la validación). No se fabrica un plan de respaldo por
    reglas: se relanza y el manejo de errores genérico de `pipeline.py`
    (el mismo que ya cubre cualquier otro nodo) marca la corrida como
    "error", sin un reporte final que aparente ser válido."""


def _construir_prompt(state: LogGuardState) -> tuple[str, str]:
    """Devuelve (system, user_content). Función pura -- no llama al LLM --
    para poder testear en aislamiento que el prompt nunca contiene ground
    truth (ver tests/test_agente_planificador.py)."""
    modo_replan = bool(state.get("plan"))
    resumen = acotar_resumen_para_prompt(state.get("resumen_logs") or {})
    contexto_pre = contexto_preprocesamiento(
        state.get("preprocessing_metadata"), state.get("parsing_warnings"))

    partes = [f"RESUMEN DEL LOTE:\n{json.dumps(resumen, ensure_ascii=False)}"]
    if contexto_pre:
        partes.append(contexto_pre)

    vocabulario = (
        "El plan tiene como máximo estas acciones, cada una a lo sumo una vez: "
        "'triage' (diagnóstico inicial -- SIEMPRE se incluye), "
        "'rag' (consultar memoria histórica y técnicas MITRE ATT&CK -- inclúyela "
        "solo si el resumen sugiere que hace falta contexto de casos anteriores), "
        "'cve' (consultar vulnerabilidades conocidas -- inclúyela solo si el "
        "resumen identifica un servicio o producto concreto), "
        "'mitigacion' (proponer contención -- SIEMPRE se incluye). "
        "No inventes otras acciones: cualquiera fuera de esta lista se descarta."
    )
    formato = (
        'Responde SOLO en JSON: {"objetivo": "...", "pasos": '
        '[{"id": 1, "accion": "...", "objetivo": "...", "estado": "pendiente"}, ...], '
        '"criterios_finalizacion": ["..."]}'
    )

    if not modo_replan:
        sys_instruction = (
            "Eres el planificador de un sistema multiagente de análisis de "
            "seguridad. A partir del resumen del lote, produce un plan de "
            "investigación ANTES de que el análisis especializado comience. "
            f"{vocabulario} {formato}"
        )
        return sys_instruction, "\n\n".join(partes)

    # --- modo replanificación: el nuevo plan usa la ejecución anterior ---
    plan_anterior = state.get("plan") or {}
    sys_instruction = (
        "Eres el planificador de un sistema multiagente de análisis de "
        "seguridad. El plan anterior no alcanzó cobertura suficiente: genera "
        "un SEGUNDO plan que use lo ya investigado, no repitas la misma "
        f"estrategia esperando un resultado distinto. {vocabulario} {formato}"
    )
    partes.append(f"PLAN ANTERIOR (versión {plan_anterior.get('plan_version')}):\n"
                  f"{json.dumps(plan_anterior, ensure_ascii=False)}")
    partes.append("HISTORIAL DE EJECUCIÓN DEL PLAN ANTERIOR:\n"
                  f"{json.dumps(state.get('historial_ejecucion') or [], ensure_ascii=False)}")
    partes.append(f"DIAGNÓSTICO OBTENIDO: {state.get('diagnostico') or '(vacío)'}")
    partes.append("CONTEXTO RAG RECUPERADO:\n"
                  f"{json.dumps(state.get('contexto_rag') or [], ensure_ascii=False)}")
    partes.append("CVEs ENCONTRADOS:\n"
                  f"{json.dumps(state.get('cves_encontrados') or [], ensure_ascii=False)}")
    partes.append(f"VALIDACIÓN DE COMANDOS: comandos_validos={state.get('comandos_validos')}, "
                  f"motivos_rechazo={state.get('motivos_rechazo') or []}")
    partes.append(f"EVALUACIÓN DEL AUDITOR: {state.get('evaluacion_auditor') or '(vacía)'}")
    partes.append(f"MOTIVO DE LA REPLANIFICACIÓN: {state.get('motivo_replanificacion') or '(no especificado)'}")
    return sys_instruction, "\n\n".join(partes)


def _validar_y_normalizar(plan_bruto, plan_version: int) -> dict:
    """Valida el JSON crudo del LLM contra el vocabulario cerrado, inyecta
    las acciones obligatorias si el LLM las omitió, deduplica, recorta a
    MAX_PLAN_STEPS descartando primero las opcionales, y asigna id/orden de
    forma determinística (canónico: triage, rag, cve, mitigacion) -- el
    orden NO lo decide el LLM, así el plan nunca declara una secuencia que
    el grafo no puede ejecutar."""
    if not isinstance(plan_bruto, dict):
        raise PlanInvalidoError(f"el plan no es un objeto JSON: {plan_bruto!r}")

    pasos_bruto = plan_bruto.get("pasos")
    if not isinstance(pasos_bruto, list):
        raise PlanInvalidoError("el plan no trae una lista de 'pasos'")

    objetivos: dict[str, str] = {}
    for paso in pasos_bruto:
        if not isinstance(paso, dict):
            continue
        accion = paso.get("accion")
        if accion not in ACCIONES_VALIDAS:
            print(f"   ⚠️ [Planificador] acción fuera del vocabulario cerrado descartada: {accion!r}")
            continue
        if accion in objetivos:
            continue  # ya vista -- sin duplicados
        objetivo = paso.get("objetivo")
        objetivos[accion] = objetivo.strip() if isinstance(objetivo, str) and objetivo.strip() else None

    for accion, default in _OBJETIVOS_DEFAULT.items():
        if objetivos.get(accion) is None:
            objetivos[accion] = default

    opcionales = [a for a in ("rag", "cve") if a in objetivos]
    seleccionadas = [a for a in ACCIONES_VALIDAS if a in objetivos]
    while len(seleccionadas) > MAX_PLAN_STEPS and opcionales:
        descartada = opcionales.pop()  # cve antes que rag (orden inverso al canónico)
        seleccionadas.remove(descartada)
        print(f"   ⚠️ [Planificador] plan recortado a MAX_PLAN_STEPS={MAX_PLAN_STEPS}: "
              f"se descarta el paso opcional '{descartada}'")

    pasos = [
        {"id": i + 1, "accion": accion, "objetivo": objetivos[accion], "estado": "pendiente"}
        for i, accion in enumerate(seleccionadas)
    ]

    objetivo_global = plan_bruto.get("objetivo")
    if not isinstance(objetivo_global, str) or not objetivo_global.strip():
        objetivo_global = "Determinar si el lote representa una anomalía o un incidente de seguridad."

    criterios = plan_bruto.get("criterios_finalizacion")
    criterios = [c for c in criterios if isinstance(c, str)] if isinstance(criterios, list) else []

    return {
        "plan_version": plan_version,
        "objetivo": objetivo_global,
        "pasos": pasos,
        "criterios_finalizacion": criterios,
    }


def _archivar_plan_anterior(state: LogGuardState, motivo: str) -> dict:
    """Snapshot del ciclo que termina, para `historial_planes` -- se arma
    ANTES de que `preparar_replanificacion()` reinicie el estado activo."""
    plan = state.get("plan") or {}
    pasos = plan.get("pasos", [])
    return {
        "version": plan.get("plan_version"),
        "plan": plan,
        "motivo_reemplazo": motivo,
        "resultados_asociados": {
            "diagnostico": state.get("diagnostico"),
            "evaluacion_auditor": state.get("evaluacion_auditor"),
            "hay_anomalia": state.get("hay_anomalia"),
            "hay_incidente": state.get("hay_incidente"),
            "confianza": state.get("confianza"),
            "cobertura_auditor": state.get("cobertura_auditor"),
            "cobertura_suficiente": state.get("cobertura_suficiente"),
            "n_pasos_ejecutados": sum(1 for p in pasos if p.get("estado") == "ejecutado"),
            "n_pasos_fallidos": sum(1 for p in pasos if p.get("estado") == "fallido"),
        },
    }


def preparar_replanificacion(state: LogGuardState) -> dict:
    """Campos que se reinician al empezar un nuevo ciclo tras replanificar.
    Lo que NO aparece acá (contexto_rag, tecnicas_mitre, cves_encontrados,
    historial_ejecucion, historial_planes, desviaciones_plan) se conserva
    intacto: es la evidencia que el nuevo plan usa como insumo.

    Sin defaults optimistas: `comandos_validos`, `cobertura_auditor` y
    `cobertura_suficiente` quedan en `None` ("no evaluado todavía"), nunca
    en `True` -- nada los lee antes de que el nodo correspondiente los fije
    de verdad, así que no hay riesgo de que un `None` se malinterprete como
    "ya validado"."""
    return {
        "necesita_rag": False,
        "usar_cve": False,
        "comandos_mitigacion": [],
        "comandos_validos": None,
        "motivos_rechazo": [],
        "intentos_correccion": 0,
        "cobertura_auditor": None,
        "cobertura_suficiente": None,
        "requiere_replanificacion": False,
        "diagnostico": "",
        "evaluacion_auditor": "",
        "hay_anomalia": False,
        "hay_incidente": False,
        "confianza": 0.0,
    }


def agente_planificador(state: LogGuardState) -> dict:
    print("\n🗺️ [Agente Planificador] Generando plan de investigación...")
    modo_replan = bool(state.get("plan"))

    sys_instruction, user_content = _construir_prompt(state)
    respuesta = llm_json(user_content, system=sys_instruction)

    if not isinstance(respuesta, dict) or respuesta.get("error") == "json_invalido":
        raise PlanInvalidoError(f"el LLM no devolvió un plan JSON válido: {respuesta!r}")

    plan_version = (state.get("plan") or {}).get("plan_version", 0) + 1
    plan_nuevo = _validar_y_normalizar(respuesta, plan_version)
    if not plan_nuevo["pasos"]:
        raise PlanInvalidoError("el plan validado quedó sin pasos ejecutables")

    print(f"   → Plan v{plan_version}: {[p['accion'] for p in plan_nuevo['pasos']]}")

    resultado = {
        "plan": plan_nuevo,
        "plan_objetivo": plan_nuevo["objetivo"],
        "paso_actual": plan_nuevo["pasos"][0]["id"],
        # Entrada de traza propia -- este nodo no pasa por `_con_traza()`
        # (ver docstring en `build_graph.py`): `actualizar_plan()` necesita
        # el plan VIEJO para resolver pasos, y devolvería ese plan viejo en
        # su delta, pisando el plan recién generado acá.
        "historial_ejecucion": [{
            "plan_version": plan_version,
            "step_id": None,
            "nodo": "agente_planificador",
            "accion": None,
            "estado": "ejecutado",
            "resumen": f"plan v{plan_version}, {len(plan_nuevo['pasos'])} pasos: "
                       f"{[p['accion'] for p in plan_nuevo['pasos']]}",
        }],
    }

    if modo_replan:
        motivo = state.get("motivo_replanificacion") or "cobertura insuficiente"
        resultado.update(preparar_replanificacion(state))
        # preparar_replanificacion() no toca "plan"/"plan_objetivo"/"paso_actual"
        resultado["replan_count"] = state.get("replan_count", 0) + 1
        resultado["historial_planes"] = [_archivar_plan_anterior(state, motivo)]

    return resultado
