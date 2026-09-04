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

# Instancia única de memoria de largo plazo para el proceso.
# NOTA: si necesitas inyectar una instancia distinta (tests, múltiples hosts),
# reemplaza este import por una fábrica/inyección de dependencias.
ltm = LongTermMemory()


def tool_consultar_rag(state: LogGuardState) -> dict:
    print("   🔍 [Tool RAG] Buscando en ChromaDB...")
    patrones = ltm.retrieve_examples(state["firma"])
    print(f"   → {len(patrones)} patrones similares encontrados.")

    tecnicas = ltm.retrieve_attack_techniques(state["firma"])
    if tecnicas:
        ids = ", ".join(t["meta"].get("technique_id", "?") for t in tecnicas)
        print(f"   → {len(tecnicas)} técnicas MITRE ATT&CK relacionadas: {ids}")
    else:
        print("   → 0 técnicas MITRE ATT&CK relacionadas (colección vacía o sin similitud suficiente).")

    return {"contexto_rag": patrones, "tecnicas_mitre": tecnicas}
