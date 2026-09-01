"""Nodo LLM: agente_auditor_final.

Migrado desde la celda 22 del notebook de Colab.

Evalúa la calidad global del análisis y asigna el nivel de confianza final.
Si `confianza < CONFIDENCE_THRESHOLD`, el resultado debe tratarse como
"requiere escalamiento a analista humano" (lo resuelve quien consuma el
estado final del grafo, ver `src/pipeline.py`).
"""

from src.llm import llm_json
from src.state import LogGuardState


def agente_auditor_final(state: LogGuardState) -> dict:
    print("\n🕵️ [Agente Auditor] Evaluando calidad de la solución...")

    sys_instruction = (
        "Evalúa la solución de seguridad propuesta. Considera: "
        "precisión del diagnóstico, relevancia de los comandos y evidencia disponible. "
        'Responde SOLO en JSON: {"confianza": 0.0-1.0, "evaluacion": "..."}'
    )
    user_content = (
        f"DIAGNÓSTICO: {state.get('diagnostico')}\n"
        f"COMANDOS VALIDADOS: {state.get('comandos_mitigacion')}\n"
        f"CVEs ENCONTRADOS: {len(state.get('cves_encontrados', []))} CVEs\n"
        f"CONTEXTO RAG: {'Sí' if state.get('contexto_rag') else 'No'}"
    )

    respuesta = llm_json(user_content, system=sys_instruction)
    try:
        confianza = float(respuesta.get("confianza", 0.5))
    except Exception:
        confianza = 0.5

    evaluacion = respuesta.get("evaluacion", "")
    print(f"   → Confianza final: {confianza:.2f} | {evaluacion}")
    return {"confianza": confianza}
