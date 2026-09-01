"""Nodo Tool: tool_consultar_rag.

Migrado desde la celda 22 del notebook de Colab.

Busca patrones similares en ChromaDB usando la firma del lote.
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
    return {"contexto_rag": patrones}
