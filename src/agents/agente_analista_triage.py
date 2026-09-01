"""Nodo LLM: agente_analista_triage.

Migrado desde la celda 22 del notebook de Colab.

Analiza el resumen del lote de logs y decide si necesita contexto histórico
(RAG). Si ya cuenta con contexto RAG, genera el diagnóstico. Alimenta el
router `router_triage`.
"""

import json

from src.llm import llm_json
from src.state import LogGuardState
from src.tools.resumen_prompt import acotar_resumen_para_prompt


def agente_analista_triage(state: LogGuardState) -> dict:
    print("\n🧠 [Agente Triage] Analizando el incidente...")

    # necesita_rag empieza en False (ver pipeline.py). La primera vez que
    # este nodo corre, si no hay contexto lo pide (necesita_rag=True) y el
    # router lo manda a tool_consultar_rag. Al volver, contexto_rag puede
    # seguir vacío (ChromaDB sin patrones aún) -- sin este OR, una lista
    # vacía nunca es "truthy" y el nodo vuelve a pedir RAG en un loop
    # infinito con el router. necesita_rag=True en la segunda pasada es
    # la señal de "el RAG ya corrió una vez", haya o no encontrado algo.
    # Bug real heredado del notebook (celda 22) -- no es de la migración;
    # el Algoritmo 8.3 del informe especifica "consultar RAG UNA vez, con
    # o sin resultados", no un loop.
    if state.get("contexto_rag") or state.get("necesita_rag"):
        print("   → Contexto RAG disponible. Generando diagnóstico...")
        sys_instruction = (
            "Eres un analista SOC experto. Basándote en el resumen del lote de logs "
            "y el contexto histórico recuperado, genera un diagnóstico del ataque. "
            'Responde SOLO en JSON: {"diagnostico": "...", "necesita_rag": false}'
        )
        contexto_rag = state.get("contexto_rag") or []
        contexto_txt = (
            json.dumps(contexto_rag, ensure_ascii=False)
            if contexto_rag
            else "Sin patrones históricos previos (memoria aún vacía)."
        )
        # Acotado por costo (ver src/tools/resumen_prompt.py): el desglose
        # completo por_ip/ips_distintas/reputacion_ips escala en tokens con
        # la cantidad de IPs distintas del lote, no con las líneas de log
        # (hallazgo real 25-ago-2026). Esto NO toca state["resumen_logs"] --
        # solo el texto que ve el LLM aquí.
        resumen_para_llm = acotar_resumen_para_prompt(state["resumen_logs"])
        user_content = (
            f"RESUMEN DEL LOTE:\n{json.dumps(resumen_para_llm, ensure_ascii=False)}\n\n"
            f"CONTEXTO HISTÓRICO (RAG):\n{contexto_txt}"
        )
        respuesta = llm_json(user_content, system=sys_instruction)
        return {
            "diagnostico": respuesta.get("diagnostico", "Ataque indeterminado"),
            "necesita_rag": False,
        }

    print("   → Sin contexto histórico. Solicitando RAG...")
    return {"necesita_rag": True}
