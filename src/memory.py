"""Memoria a corto plazo (sesión) y largo plazo (ChromaDB).

Migrado desde la celda 11 del notebook de Colab.
"""

import json
import time

import chromadb
from chromadb.utils import embedding_functions

from src.config import (
    AUTO_PROMOTE,
    CHROMA_PATH,
    COL_ERRORS,
    COL_HISTORY,
    COL_PATTERNS,
    EMBEDDING_MODEL,
    MAX_RAW_CHARS_EMBED,
    SIMILARITY_FLOOR,
    TOP_K_ERRORS,
    TOP_K_FEWSHOT,
)


class ShortTermMemory:
    """Traza efímera de un único análisis (resumen + plan + observaciones)."""

    def __init__(self):
        self.summary = None
        self.plan = None
        self.observations = []

    def set_summary(self, s):
        self.summary = s

    def set_plan(self, plan):
        self.plan = plan

    def add_observation(self, obs):
        self.observations.append(obs)

    def reset(self):
        self.__init__()


class LongTermMemory:
    """Memoria persistente sobre ChromaDB (3 colecciones)."""

    def __init__(self):
        self._ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL)
        self._db = chromadb.PersistentClient(path=CHROMA_PATH)
        self.patterns = self._col(COL_PATTERNS)
        self.errors = self._col(COL_ERRORS)
        self.history = self._col(COL_HISTORY)

    def _col(self, name):
        return self._db.get_or_create_collection(
            name, embedding_function=self._ef, metadata={"hnsw:space": "cosine"})

    def _query(self, col, text, k):
        if col.count() == 0:
            return []
        res = col.query(query_texts=[text[:MAX_RAW_CHARS_EMBED]], n_results=min(k, col.count()))
        out = []
        for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
            sim = 1 - dist
            if sim >= SIMILARITY_FLOOR:
                out.append({"texto": doc, "meta": meta or {}, "similitud": round(sim, 3)})
        return out

    # --- few-shot dinámico ---
    def retrieve_examples(self, firma, k=TOP_K_FEWSHOT):
        return self._query(self.patterns, firma, k)

    # --- reflexión con memoria de errores ---
    def retrieve_corrections(self, firma, k=TOP_K_ERRORS):
        return self._query(self.errors, firma, k)

    def record_error(self, firma, diagnostico_erroneo, correccion):
        self.errors.add(
            documents=[firma[:MAX_RAW_CHARS_EMBED]],
            metadatas=[{"erroneo": json.dumps(diagnostico_erroneo, ensure_ascii=False)[:1500],
                        "correccion": json.dumps(correccion, ensure_ascii=False)}],
            ids=[f"err-{int(time.time()*1000)}"])

    # --- feedback loop ---
    def commit_validated(self, firma, report, host="desconocido"):
        meta = {"clasificacion": str(report.get("clasificacion_global")),
                 "confianza": float(report.get("confianza", 0) or 0), "host": host}
        self.history.add(documents=[firma[:MAX_RAW_CHARS_EMBED]], metadatas=[meta],
                          ids=[f"hist-{int(time.time()*1000)}"])
        if meta["confianza"] >= AUTO_PROMOTE:
            self.patterns.add(documents=[firma[:MAX_RAW_CHARS_EMBED]], metadatas=[meta],
                               ids=[f"pat-{int(time.time()*1000)}"])
            return True  # promovido
        return False

    def seed_pattern(self, firma, clasificacion, mitigacion):
        self.patterns.add(
            documents=[firma],
            metadatas=[{"clasificacion": clasificacion, "mitigacion": mitigacion}],
            ids=[f"seed-{int(time.time()*1000000)}"])
