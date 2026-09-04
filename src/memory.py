"""Memoria a corto plazo (sesión) y largo plazo (ChromaDB).

Migrado desde la celda 11 del notebook de Colab.

Colección `attack_techniques` (agregada 3-sep-2026, §6.7/§8.7.2/§9 del
informe -- "Falta de integración con CTI estructurada", Tabla 7.4): base de
conocimiento vectorial poblada desde el repositorio oficial de MITRE
ATT&CK en formato STIX 2.1, para que `tool_consultar_rag` pueda recuperar
técnicas conocidas relacionadas con cada lote de logs, en vez de que el
enlace evento↔técnica dependa solo del razonamiento libre del LLM. Ver
`src/tools/preparar_mitre_attack.py` (población, requiere red real) y el
README, sección "Integración MITRE ATT&CK".
"""

import json
import time

import chromadb
from chromadb.utils import embedding_functions

from src.config import (
    ATTACK_MAX_CHARS_EMBED,
    AUTO_PROMOTE,
    CHROMA_PATH,
    COL_ATTACK,
    COL_ERRORS,
    COL_HISTORY,
    COL_PATTERNS,
    EMBEDDING_MODEL,
    MAX_RAW_CHARS_EMBED,
    SIMILARITY_FLOOR,
    SIMILARITY_FLOOR_ATTACK,
    TOP_K_ATTACK,
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
    """Memoria persistente sobre ChromaDB (4 colecciones -- `attack_techniques`
    agregada 3-sep-2026, ver "Integración MITRE ATT&CK" en el README)."""

    def __init__(self):
        self._ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL)
        self._db = chromadb.PersistentClient(path=CHROMA_PATH)
        self.patterns = self._col(COL_PATTERNS)
        self.errors = self._col(COL_ERRORS)
        self.history = self._col(COL_HISTORY)
        self.attack_techniques = self._col(COL_ATTACK)

    def _col(self, name):
        return self._db.get_or_create_collection(
            name, embedding_function=self._ef, metadata={"hnsw:space": "cosine"})

    def _query(self, col, text, k, floor=SIMILARITY_FLOOR):
        """`floor` es el umbral de similitud mínimo para incluir un
        resultado -- por defecto `SIMILARITY_FLOOR` (calibrado para
        comparar texto del mismo género, p. ej. firma de lote contra firma
        de lote en `patterns`/`errors`). `retrieve_attack_techniques`
        pasa un umbral propio (`SIMILARITY_FLOOR_ATTACK`, más bajo) porque
        ahí se compara firma de lote contra prosa descriptiva de MITRE --
        géneros de texto distintos, con similitudes de embedding
        estructuralmente más bajas aunque el contenido esté relacionado.
        Bug real corregido 4-sep-2026: reusar `SIMILARITY_FLOOR` acá
        filtraba SIEMPRE los resultados de `attack_techniques`, incluso
        matches reales -- ver comentario en `src/config.py`."""
        if col.count() == 0:
            return []
        res = col.query(query_texts=[text[:MAX_RAW_CHARS_EMBED]], n_results=min(k, col.count()))
        out = []
        for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
            sim = 1 - dist
            if sim >= floor:
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

    # --- MITRE ATT&CK (STIX 2.1), agregado 3-sep-2026 ---
    #
    # `attack_techniques` se puebla UNA VEZ, de forma offline, desde el
    # repositorio oficial de MITRE (`src/tools/preparar_mitre_attack.py`,
    # requiere red real) -- no crece con el feedback loop del sistema como
    # `patterns`/`errors`/`history`. `tool_consultar_rag` la consulta en
    # cada análisis igual que las demás, con el mismo mecanismo de
    # similitud coseno + `SIMILARITY_FLOOR`.

    def retrieve_attack_techniques(self, query_text, k=TOP_K_ATTACK):
        return self._query(self.attack_techniques, query_text, k,
                           floor=SIMILARITY_FLOOR_ATTACK)

    def cargar_tecnicas_attack(self, tecnicas: list) -> int:
        """Puebla (o repuebla) `attack_techniques` desde una lista de dicts
        ya extraídos del bundle STIX oficial -- ver
        `src/tools/preparar_mitre_attack.py::_extraer_tecnicas`. Cada dict
        trae al menos `technique_id`, `name`, `description`; `tactics`,
        `is_subtechnique`, `url` son opcionales.

        Usa `upsert` (no `add`): correr este método de nuevo -- p. ej. tras
        actualizar a una versión más nueva de ATT&CK -- reemplaza los
        documentos existentes por `technique_id` en vez de duplicarlos."""
        if not tecnicas:
            return 0
        ids = [f"attack-{t['technique_id']}" for t in tecnicas]
        documents = [
            f"{t.get('name', '')}. {t.get('description', '')}".strip()[:ATTACK_MAX_CHARS_EMBED]
            for t in tecnicas
        ]
        metadatas = [
            {
                "technique_id": t["technique_id"],
                "name": t.get("name", ""),
                "tactics": ",".join(t.get("tactics") or []),
                "is_subtechnique": bool(t.get("is_subtechnique", False)),
                "url": t.get("url") or "",
            }
            for t in tecnicas
        ]
        self.attack_techniques.upsert(documents=documents, metadatas=metadatas, ids=ids)
        return len(tecnicas)
