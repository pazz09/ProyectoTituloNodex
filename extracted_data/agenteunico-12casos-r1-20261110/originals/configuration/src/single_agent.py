"""Comparador de una llamada LLM, sin grafo ni agentes delegados.

Comparte entrada preprocesada, contrato y validación con NODEX. Puede recibir
candidatos MITRE recuperados de manera independiente, nunca etiquetas.
"""

import json

from src.config import CONFIDENCE_THRESHOLD
from src.llm import llm_json
from src.output_contract import PROMPT_D11, campos_d11, contexto_d11, normalizar_d11
from src.pipeline import _preparar_estado_inicial
from src.preprocessing.prompt_context import contexto_preprocesamiento
from src.telemetry import medir_ejecucion, resumen_telemetria
from src.tools.resumen_prompt import acotar_resumen_para_prompt
from src.tools.validation import validate_solution


def analizar_lote_agente_unico(raw_logs: str, thread_id: str | None = None,
                              tecnicas_mitre: list | None = None) -> dict:
    """Misma tarea y contrato, arquitectura de una sola llamada (más retries)."""
    with medir_ejecucion():
        state, _, firma = _preparar_estado_inicial(raw_logs, thread_id)
        state["tecnicas_mitre"] = list(tecnicas_mitre or [])
        system = (
            "Eres un analista de logs de seguridad. Analiza la evidencia observada "
            "y entrega diagnóstico, veredictos independientes y propuesta de mitigación. "
            "hay_anomalia incluye fallas operativas; hay_incidente indica específicamente "
            "una amenaza de seguridad. confianza mide certeza del diagnóstico, también "
            "cuando todo es normal. No afirmes que ejecutaste los comandos. "
            'Devuelve SOLO JSON: {"diagnostico":"...", "hay_anomalia":true/false, '
            '"hay_incidente":true/false, "confianza":0.0, "evaluacion":"...", '
            '"comandos_mitigacion":[]}. '
            + PROMPT_D11
        )
        prompt = "RESUMEN DEL LOTE:\n" + json.dumps(
            acotar_resumen_para_prompt(state["resumen_logs"]), ensure_ascii=False)
        prompt += "\n" + contexto_preprocesamiento(state["preprocessing_metadata"], state["parsing_warnings"])
        prompt += contexto_d11(state)
        try:
            respuesta = llm_json(prompt, system=system)
            state.update(normalizar_d11(respuesta, state["evidencia_logs"]))
            if not isinstance(respuesta, dict):
                respuesta = {}
            for campo in ("diagnostico", "hay_anomalia", "hay_incidente", "confianza"):
                state[campo] = respuesta.get(campo)
            state["evaluacion_auditor"] = respuesta.get("evaluacion")
            comandos = respuesta.get("comandos_mitigacion")
            comandos = [c for c in comandos if isinstance(c, str)] if isinstance(comandos, list) else []
            state["comandos_mitigacion"] = comandos
            validacion = validate_solution(comandos)
            state["comandos_validos"] = validacion["valido"]
            state["motivos_rechazo"] = validacion["motivos"]
            state["_error_api"] = None
            if (respuesta.get("error") or not isinstance(state["hay_incidente"], bool)
                    or not isinstance(state["hay_anomalia"], bool)
                    or not isinstance(state["diagnostico"], str) or not state["diagnostico"].strip()
                    or not isinstance(state["evaluacion_auditor"], str) or not state["evaluacion_auditor"].strip()):
                state["_error_api"] = "El agente único no produjo un resultado D1/D4 completo."
            try:
                confianza = float(state["confianza"])
                if not 0 <= confianza <= 1:
                    raise ValueError("confianza fuera de rango")
                state["confianza"] = confianza
            except (TypeError, ValueError):
                state["confianza"] = None
                state["_error_api"] = "El agente único no produjo una confianza válida."
        except Exception as exc:
            state["_error_api"] = f"{type(exc).__name__}: {exc}"
        state["_firma"] = firma
        state["requiere_revision_humana"] = bool(state["_error_api"]) or (state.get("confianza") or 0) < CONFIDENCE_THRESHOLD
        state["telemetry"] = resumen_telemetria(state)
        state.update(campos_d11(state))
        return state
