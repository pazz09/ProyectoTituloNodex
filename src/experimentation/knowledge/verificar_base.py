"""Verificación de que una base de ChromaDB le sirve a NODEX.

## Por qué existe (qué falló antes)

La base experimental original (`experiments/knowledge/chroma`) se verificó
contando sus 697 documentos con la API de Chroma **sin función de embeddings**.
Eso comprobaba que los datos estaban, pero **no que NODEX pudiera abrirla**: la
base se había creado sin función de embeddings (Chroma guardó «default») y
`src/memory.py` la abre con `SentenceTransformerEmbeddingFunction`; ChromaDB
1.5.9 rechaza ese choque. Todo NODEX habría fallado en su primera corrida real
(en la comparación de modelos falló antes de llamar al modelo).

Por eso esta verificación **abre la base con el mismo código que usa NODEX**
(`LongTermMemory` de `src/memory.py`) y hace una consulta real, además de
comparar contenido y resultados contra la base anterior.

## Qué comprueba

1. La base se abre con `LongTermMemory` y responde una consulta real (los
   embeddings de la consulta se calculan en local; no hay LLM ni red).
2. Un conjunto FIJO de consultas, escrito antes de ejecutar y ajeno a los
   casos del experimento, da los mismos resultados principales que la base
   anterior. Se **reportan las diferencias**, no solo si coinciden.
3. El contenido es el mismo catálogo: mismos ids, documentos y metadatos, y
   los vectores guardados corresponden a lo que calcula el modelo.
4. No hay casos reservados, etiquetas ni feedback: solo `attack_techniques`,
   con las claves de metadatos del catálogo MITRE.

Solo lee. Las bases se abren siempre como COPIAS temporales.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

#: Consultas de verificación. FIJAS y escritas antes de ejecutar la
#: verificación. Son descripciones genéricas de comportamientos de ATT&CK; no
#: están sacadas de ningún caso del experimento (ni de sus logs ni de sus
#: etiquetas) y una prueba comprueba que no contienen ningún `case_id`.
CONSULTAS_FIJAS = (
    "brute force of remote login passwords with many failed attempts",
    "dumping credentials from operating system memory",
    "persistence through a scheduled task that runs at startup",
    "scanning a network to discover open ports and running services",
    "phishing email with a malicious attachment that executes a macro",
    "encrypting files on disk and demanding payment to restore them",
    "using remote desktop to move laterally between hosts",
    "disabling security tools and clearing logs to avoid detection",
    "web shell installed on a public-facing server",
    "exfiltrating data to an external server over an encrypted channel",
    "injecting code into the address space of a running process",
    "running commands through a PowerShell script",
)

#: Resultados que se comparan por consulta.
TOP_N = 5
#: Tamaño de la muestra de documentos cuyo vector se recalcula.
MUESTRA_VECTORES = 40
#: Claves de metadatos del catálogo MITRE. Cualquier otra sería sospechosa.
CLAVES_METADATA_CATALOGO = frozenset(
    {"technique_id", "name", "tactics", "is_subtechnique", "url"})
COLECCION = "attack_techniques"

#: Se ejecuta en un proceso aparte, con `CHROMA_PATH` apuntando a una copia,
#: porque `src.config` lee esa variable al importarse. Usa el mismo código que
#: NODEX para abrir y consultar la base.
_SCRIPT_MEMORIA = r"""
import json, sys
from src.memory import LongTermMemory
from src.config import MAX_RAW_CHARS_EMBED

consultas = json.loads(sys.stdin.read())
memoria = LongTermMemory()
col = memoria.attack_techniques
salida = {
    "colecciones": sorted(c if isinstance(c, str) else c.name
                          for c in memoria._db.list_collections()),
    "n_attack_techniques": col.count(),
    "consultas": [],
}
for texto in consultas:
    filtrado = memoria.retrieve_attack_techniques(texto)
    crudo = col.query(query_texts=[texto[:MAX_RAW_CHARS_EMBED]], n_results=%(top)d,
                      include=["distances", "metadatas"])
    salida["consultas"].append({
        "consulta": texto,
        "nodex": [{"technique_id": r["meta"].get("technique_id"),
                   "similitud": r["similitud"]} for r in filtrado],
        "ids": list(crudo["ids"][0]),
        "distancias": [float(d) for d in crudo["distances"][0]],
    })
print("RESULTADO_JSON:" + json.dumps(salida))
""" % {"top": TOP_N}


# --- comparaciones puras (sin Chroma): se pueden probar sin cargar nada ----------

def comparar_resultados(viejo: dict, nuevo: dict) -> dict:
    """Compara, consulta por consulta, lo que devolvieron las dos bases.

    Devuelve las diferencias, no solo un veredicto: orden de los ids, ids que
    cambian, mayor diferencia de distancia y diferencias en lo que vería NODEX
    (lo que supera el umbral de similitud).
    """
    por_consulta = []
    for v, n in zip(viejo["consultas"], nuevo["consultas"]):
        if v["consulta"] != n["consulta"]:
            raise ValueError("las dos bases se consultaron con textos distintos")
        dif_dist = [abs(a - b) for a, b in zip(v["distancias"], n["distancias"])]
        v_nodex = [(r["technique_id"], r["similitud"]) for r in v["nodex"]]
        n_nodex = [(r["technique_id"], r["similitud"]) for r in n["nodex"]]
        por_consulta.append({
            "consulta": v["consulta"],
            "ids_viejo": v["ids"], "ids_nuevo": n["ids"],
            "mismos_ids_y_orden": v["ids"] == n["ids"],
            "mismo_conjunto_de_ids": set(v["ids"]) == set(n["ids"]),
            "diferencia_maxima_de_distancia": max(dif_dist, default=0.0),
            "nodex_viejo": v_nodex, "nodex_nuevo": n_nodex,
            "mismo_resultado_para_nodex": v_nodex == n_nodex,
        })
    return {
        "n_consultas": len(por_consulta),
        "con_mismos_ids_y_orden": sum(c["mismos_ids_y_orden"] for c in por_consulta),
        "con_mismo_resultado_para_nodex": sum(
            c["mismo_resultado_para_nodex"] for c in por_consulta),
        "diferencia_maxima_de_distancia": max(
            (c["diferencia_maxima_de_distancia"] for c in por_consulta), default=0.0),
        "consultas_con_diferencias": [
            c for c in por_consulta
            if not (c["mismos_ids_y_orden"] and c["mismo_resultado_para_nodex"])],
        "detalle": por_consulta,
    }


def revisar_contenido(viejo: dict, nuevo: dict, case_ids: set[str]) -> dict:
    """Mismo catálogo y sin nada ajeno. `viejo`/`nuevo`: ids, documents, metadatas."""
    mismos_ids = viejo["ids"] == nuevo["ids"]
    claves = {k for m in nuevo["metadatas"] for k in (m or {})}
    texto = "\n".join(nuevo["documents"]) + "\n" + json.dumps(
        nuevo["metadatas"], ensure_ascii=False)
    casos_encontrados = sorted(c for c in case_ids if c in texto)
    return {
        "n_viejo": len(viejo["ids"]), "n_nuevo": len(nuevo["ids"]),
        "mismos_ids_y_orden": mismos_ids,
        "mismos_documentos": viejo["documents"] == nuevo["documents"],
        "mismos_metadatos": viejo["metadatas"] == nuevo["metadatas"],
        "claves_de_metadatos": sorted(claves),
        "claves_de_metadatos_inesperadas": sorted(claves - CLAVES_METADATA_CATALOGO),
        "case_ids_encontrados_en_el_contenido": casos_encontrados,
    }


def contenido_limpio(r: dict) -> bool:
    return (r["mismos_ids_y_orden"] and r["mismos_documentos"] and r["mismos_metadatos"]
            and not r["claves_de_metadatos_inesperadas"]
            and not r["case_ids_encontrados_en_el_contenido"])


# --- operaciones con Chroma ---------------------------------------------------------

def _copiar(origen: Path, temporal: Path, nombre: str) -> Path:
    destino = temporal / nombre
    shutil.copytree(origen, destino)
    return destino


def abrir_con_memoria(raiz_repo: Path, chroma: Path) -> dict:
    """Abre una COPIA de `chroma` con `LongTermMemory` (el código de NODEX) y la consulta."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        copia = _copiar(chroma, Path(tmp), "chroma")
        entorno = {**os.environ, "CHROMA_PATH": str(copia), "HF_HUB_OFFLINE": "1",
                   "TRANSFORMERS_OFFLINE": "1", "PYTHONIOENCODING": "utf-8"}
        proceso = subprocess.run(
            [sys.executable, "-c", _SCRIPT_MEMORIA], input=json.dumps(list(CONSULTAS_FIJAS)),
            cwd=raiz_repo, env=entorno, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    for linea in proceso.stdout.splitlines():
        if linea.startswith("RESULTADO_JSON:"):
            return json.loads(linea[len("RESULTADO_JSON:"):])
    raise RuntimeError(
        "LongTermMemory no pudo abrir la base:\n"
        + (proceso.stderr or proceso.stdout)[-1500:])


def _funcion_de_embeddings():
    from chromadb.utils import embedding_functions
    from src.config import EMBEDDING_MODEL
    return embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)


def consultar_sin_funcion_persistida(chroma: Path, funcion) -> tuple[dict, dict]:
    """Consulta una base ANTERIOR (cuya función de embeddings persistida es
    «default») calculando los embeddings de la consulta con la misma función
    que usa NODEX. Devuelve `(resultados, contenido)`."""
    import chromadb
    from src.config import MAX_RAW_CHARS_EMBED, SIMILARITY_FLOOR_ATTACK, TOP_K_ATTACK

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        copia = _copiar(chroma, Path(tmp), "chroma")
        col = chromadb.PersistentClient(path=str(copia)).get_collection(COLECCION)
        datos = col.get(include=["documents", "metadatas", "embeddings"], limit=col.count())
        resultados = {"consultas": []}
        for texto in CONSULTAS_FIJAS:
            vector = funcion([texto[:MAX_RAW_CHARS_EMBED]])
            crudo = col.query(query_embeddings=vector, n_results=TOP_N,
                              include=["distances", "metadatas"])
            filtrado = col.query(query_embeddings=vector,
                                 n_results=min(TOP_K_ATTACK, col.count()),
                                 include=["distances", "metadatas"])
            nodex = [
                {"technique_id": (m or {}).get("technique_id"),
                 "similitud": round(1 - d, 3)}
                for m, d in zip(filtrado["metadatas"][0], filtrado["distances"][0])
                if 1 - d >= SIMILARITY_FLOOR_ATTACK]
            resultados["consultas"].append({
                "consulta": texto, "nodex": nodex, "ids": list(crudo["ids"][0]),
                "distancias": [float(d) for d in crudo["distances"][0]]})
        contenido = {
            "ids": list(datos["ids"]), "documents": list(datos["documents"]),
            "metadatas": [dict(m) for m in datos["metadatas"]],
            "embeddings": [list(map(float, e)) for e in datos["embeddings"]],
        }
    return resultados, contenido


def leer_contenido(chroma: Path) -> dict:
    """Contenido de una base (copia temporal), sin función de embeddings."""
    import chromadb
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        copia = _copiar(chroma, Path(tmp), "chroma")
        cliente = chromadb.PersistentClient(path=str(copia))
        nombres = sorted(c if isinstance(c, str) else c.name for c in cliente.list_collections())
        col = cliente.get_collection(COLECCION)
        datos = col.get(include=["documents", "metadatas", "embeddings"], limit=col.count())
        configuracion = str(getattr(col, "configuration", None))
        return {
            "colecciones": nombres, "configuracion": configuracion,
            "ids": list(datos["ids"]), "documents": list(datos["documents"]),
            "metadatas": [dict(m) for m in datos["metadatas"]],
            "embeddings": [list(map(float, e)) for e in datos["embeddings"]],
        }


def muestra_de_vectores(contenido: dict, funcion) -> dict:
    """Recalcula el vector de una muestra de documentos y lo compara con el guardado."""
    import math
    n = len(contenido["ids"])
    paso = max(1, n // MUESTRA_VECTORES)
    indices = list(range(0, n, paso))[:MUESTRA_VECTORES]
    cosenos = []
    for i in indices:
        nuevo = list(map(float, funcion([contenido["documents"][i]])[0]))
        guardado = contenido["embeddings"][i]
        num = sum(a * b for a, b in zip(nuevo, guardado))
        den = math.sqrt(sum(a * a for a in nuevo)) * math.sqrt(sum(b * b for b in guardado))
        cosenos.append(num / den)
    return {"n_muestra": len(cosenos), "coseno_minimo": min(cosenos),
            "coseno_medio": sum(cosenos) / len(cosenos)}


def verificar(raiz_repo: Path, chroma_vieja: Path, chroma_nueva: Path) -> dict:
    """Corre la verificación completa y devuelve el informe."""
    funcion = _funcion_de_embeddings()
    case_ids = {p.stem for p in (raiz_repo / "experiments" / "cases").rglob("*.json")}

    abierta = abrir_con_memoria(raiz_repo, chroma_nueva)                 # (1)
    viejo_res, viejo_cont = consultar_sin_funcion_persistida(chroma_vieja, funcion)
    nuevo_cont = leer_contenido(chroma_nueva)
    comparacion = comparar_resultados(viejo_res, abierta)                # (2)
    contenido = revisar_contenido(viejo_cont, nuevo_cont, case_ids)      # (3)
    max_dif_vectores = max(
        (abs(a - b) for u, v in zip(viejo_cont["embeddings"], nuevo_cont["embeddings"])
         for a, b in zip(u, v)), default=0.0)
    return {
        "se_abre_con_el_codigo_de_memory_py": True,
        "colecciones_vistas_por_memory_py": abierta["colecciones"],
        "n_attack_techniques": abierta["n_attack_techniques"],
        "colecciones_en_la_base_nueva": nuevo_cont["colecciones"],
        "configuracion_de_la_coleccion_nueva": nuevo_cont["configuracion"],
        "comparacion_de_consultas": comparacion,
        "contenido": contenido,
        "contenido_limpio": contenido_limpio(contenido),
        "diferencia_maxima_entre_vectores": max_dif_vectores,
        "vectores_vs_modelo": muestra_de_vectores(nuevo_cont, funcion),
        "consultas_fijas": list(CONSULTAS_FIJAS),
    }


def main(raiz_repo: Path | None = None) -> int:
    raiz_repo = raiz_repo or Path(__file__).resolve().parents[3]
    from src.experimentation.knowledge.aislamiento import configuracion_experimental
    conf = configuracion_experimental(raiz_repo)
    informe = verificar(raiz_repo, conf.chroma_v1, conf.chroma)
    destino = conf.raiz / "verificacion_chroma_v2.json"
    if destino.exists():
        raise FileExistsError(f"{destino} ya existe: no se sobrescribe")
    destino.write_text(json.dumps(informe, indent=2, ensure_ascii=False), encoding="utf-8")
    c = informe["comparacion_de_consultas"]
    print(f"abre con memory.py: {informe['se_abre_con_el_codigo_de_memory_py']} | "
          f"documentos: {informe['n_attack_techniques']} | "
          f"colecciones: {informe['colecciones_vistas_por_memory_py']}")
    print(f"consultas con mismos ids y orden: {c['con_mismos_ids_y_orden']}/{c['n_consultas']} | "
          f"mismo resultado para NODEX: {c['con_mismo_resultado_para_nodex']}/{c['n_consultas']} | "
          f"mayor diferencia de distancia: {c['diferencia_maxima_de_distancia']:.3e}")
    print(f"contenido limpio: {informe['contenido_limpio']} | "
          f"vectores vs modelo (coseno min): {informe['vectores_vs_modelo']['coseno_minimo']:.6f}")
    print(f"informe escrito en {destino}")
    return 0 if informe["contenido_limpio"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
