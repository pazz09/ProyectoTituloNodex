"""Comparador de una llamada LLM, sin grafo ni agentes delegados.

Comparte entrada preprocesada, contrato y validación con NODEX. Puede recibir
candidatos MITRE recuperados de manera independiente, nunca etiquetas.
"""

import json

from src.config import CONFIDENCE_THRESHOLD
from src.llm import llm_json
from src.output_contract import PROMPT_D11, campos_d11, contexto_d11, normalizar_d11
from src.pipeline import _preparar_estado_inicial
from src.preprocessing.prompt_context import contexto_contenido_lote, contexto_preprocesamiento
from src.telemetry import medir_ejecucion, resumen_telemetria
from src.tools.resumen_prompt import acotar_resumen_para_prompt
from src.tools.validation import validate_solution


def _reglas_mitigacion() -> str:
    """Las mismas reglas de mitigación que recibe NODEX (M7), para una comparación justa."""
    from src.config import MITIGACION_CON_CONTEXTO, MITIGACION_DIR_SALIDA
    if not MITIGACION_CON_CONTEXTO:
        return ""
    return (
        "Para comandos_mitigacion: si no hay anomalía, lista vacía; si es una anomalía operativa "
        "sin indicios de ataque, solo comandos de diagnóstico de solo lectura y ninguna regla de "
        "firewall; si es un incidente de seguridad, contención proporcional y verificable sobre "
        "las entidades de la evidencia. Nunca abras el firewall (-j ACCEPT, ufw allow), nunca "
        "desbanees (fail2ban-client unban), no uses comandos destructivos y no escribas ni "
        f"redirijas salida fuera de {MITIGACION_DIR_SALIDA}. "
    )


def _criterio_organizacion() -> str:
    """Las mismas definiciones del veredicto que reciben el triage y el auditor de NODEX (B4)."""
    from src.config import HISTORICO_ACTIVO
    if not HISTORICO_ACTIVO:
        return ""
    from src.tools.memoria_historica import CRITERIO_ORGANIZACION
    return ("hay_anomalia es true si hay una anomalía operativa o un incidente según estas definiciones; "
            "hay_incidente, si es un incidente de seguridad. " + CRITERIO_ORGANIZACION)


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
            + _reglas_mitigacion()
            + _criterio_organizacion()
            + PROMPT_D11
        )
        prompt = "RESUMEN DEL LOTE:\n" + json.dumps(
            acotar_resumen_para_prompt(state["resumen_logs"]), ensure_ascii=False)
        prompt += "\n" + contexto_preprocesamiento(state["preprocessing_metadata"], state["parsing_warnings"])
        # M1 (NODEX final): el mismo contenido del lote que recibe el triage de NODEX.
        contenido = contexto_contenido_lote(state.get("contenido_lote"))
        if contenido:
            prompt += "\n" + contenido
        # B4 (Fase B): los mismos casos históricos que NODEX (misma consulta y exclusión,
        # calculados en `_preparar_estado_inicial`). La memoria de la organización es
        # conocimiento, no arquitectura.
        from src.tools.memoria_historica import contexto_historico
        historicos = contexto_historico(state.get("casos_historicos"))
        if historicos:
            prompt += "\n" + historicos
        # B.1-2: la misma memoria de grupos que recibe el cazador de NODEX (misma consulta,
        # calculada en `_preparar_estado_inicial`), para una comparación justa.
        from src.tools.memoria_grupos import contexto_memoria_grupos
        grupos_memoria = contexto_memoria_grupos(state.get("memoria_grupos"))
        if grupos_memoria:
            prompt += "\n" + grupos_memoria
        prompt += contexto_d11(state)
        try:
            respuesta = llm_json(prompt, system=system)
            state.update(normalizar_d11(respuesta, state["evidencia_logs"], state.get("grupos_evidencia")))
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
            state["comandos_rechazados"] = [dict(r, intento=1) for r in validacion.get("rechazados", [])]
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
