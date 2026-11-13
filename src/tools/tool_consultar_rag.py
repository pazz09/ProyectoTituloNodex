"""Nodo Tool: tool_consultar_rag.

Migrado desde la celda 22 del notebook de Colab.

Busca patrones similares en ChromaDB usando la firma del lote. Desde el
3-sep-2026 también consulta la colección `attack_techniques` (MITRE ATT&CK
en formato STIX 2.1 -- ver `src/memory.py` y README, "Integración MITRE
ATT&CK") con la misma firma, en vez de agregar un nodo nuevo al grafo: la
Tabla 8.9/§8.3.1 del informe documenta 7 nodos (4 LLM + 3 Tool), y esta
consulta encaja en la responsabilidad ya existente de este Tool ("traer
contexto externo antes del diagnóstico") sin ampliar esa cuenta.
"""

from src.memory import LongTermMemory
from src.state import LogGuardState
from src.tools.aggregation import describir_lote_en_prosa

# Instancia única de memoria de largo plazo para el proceso.
# NOTA: si necesitas inyectar una instancia distinta (tests, múltiples hosts),
# reemplaza este import por una fábrica/inyección de dependencias.
ltm = LongTermMemory()


def _rag_por_hipotesis(state: LogGuardState) -> dict:
    """B3 (NODEX final). Corre después del triage.

    - Técnicas MITRE: se consultan con el texto de la HIPÓTESIS (el diagnóstico, si
      el veredicto es un incidente de seguridad). Sin hipótesis de seguridad no se
      consultan.
    - Patrones históricos: ya están en el estado (`casos_historicos`, consulta
      siempre activa de B4, con la representación por grupos y la exclusión por
      solapamiento); aquí solo se exponen como `contexto_rag` por compatibilidad.
    - Fija el `veredicto_consolidado`, determinístico, antes de la mitigación.
    """
    from src.graph.veredicto import texto_hipotesis, veredicto_consolidado
    print("   🔍 [Tool RAG] Consulta por hipótesis...")
    hipotesis = texto_hipotesis(state)
    tecnicas = ltm.retrieve_attack_techniques(hipotesis) if hipotesis else []
    if hipotesis:
        print(f"   → {len(tecnicas)} técnicas MITRE para la hipótesis de seguridad.")
    else:
        print("   → Sin hipótesis de seguridad: no se consultan técnicas MITRE.")
    return {"contexto_rag": list(state.get("casos_historicos") or []), "tecnicas_mitre": tecnicas,
            "consulta_mitre": hipotesis or "", "veredicto_consolidado": veredicto_consolidado(state),
            "rag_omitido": None if hipotesis else "sin hipótesis de seguridad: no se consultan técnicas"}


def tool_consultar_rag(state: LogGuardState) -> dict:
    from src.config import RAG_POR_HIPOTESIS
    if RAG_POR_HIPOTESIS:
        return _rag_por_hipotesis(state)
    print("   🔍 [Tool RAG] Buscando en ChromaDB...")
    patrones = ltm.retrieve_examples(state["firma"])
    print(f"   → {len(patrones)} patrones similares encontrados.")

    # ATT&CK se consulta con una descripción en prosa del lote, no con la
    # firma: la colección guarda las técnicas como texto en prosa, y
    # comparar contra una cadena de conteos (`v1|lineas=23 ips=3
    # servicios=[sshd:18...]`) no recuperaba nada. Medido el 9-sep-2026
    # sobre corridas reales, la similitud máxima con la firma quedaba en
    # 0.324 (auth_log) y 0.300 (BGL), bajo el piso de 0.35 -- es decir,
    # `tecnicas_mitre` venía vacío siempre. Las otras tres colecciones
    # siguen consultándose con la firma, que ahí sí es el formato correcto:
    # lo indexado también son firmas.
    descripcion = describir_lote_en_prosa(state.get("resumen_logs") or {})
    tecnicas = ltm.retrieve_attack_techniques(descripcion)
    if tecnicas:
        ids = ", ".join(t["meta"].get("technique_id", "?") for t in tecnicas)
        print(f"   → {len(tecnicas)} técnicas MITRE ATT&CK relacionadas: {ids}")
    else:
        print("   → 0 técnicas MITRE ATT&CK relacionadas (colección vacía o sin similitud suficiente).")

    return {"contexto_rag": patrones, "tecnicas_mitre": tecnicas}
