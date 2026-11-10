"""Inventario del conocimiento, con hashes. **Solo lectura.**

La Fase 3 pide un snapshot versionado del catálogo MITRE y del modelo de
embeddings, con inventario y hashes. Sin eso, una atribución MITRE no es
reproducible: si el catálogo cambia de versión, cambian las técnicas
recuperadas y la métrica de D3 cambia sin que nadie lo note.

Este módulo **no abre ChromaDB con su API ni ejecuta consultas**: lee el
SQLite subyacente en modo `ro`. El plan prohíbe las consultas de ensayo, y
una consulta de similitud cargaría además el modelo de embeddings.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path

#: Colecciones que son CONOCIMIENTO: información pública del dominio que el
#: agente puede consultar legítimamente.
COLECCIONES_CONOCIMIENTO = ("attack_techniques",)

#: Colecciones que son MEMORIA de corridas previas. Dentro de un
#: experimento contaminan: un caso reservado cuyo host ya fue analizado
#: antes recibiría información que no vino del caso. No se copian a la base
#: experimental.
COLECCIONES_MEMORIA = ("host_history", "error_memory", "attack_patterns")


@dataclass
class ColeccionInventariada:
    nombre: str
    dimension: int | None
    n_embeddings: int
    #: `conocimiento` o `memoria`, según las constantes de arriba.
    rol: str
    #: Claves de metadata presentes, con su conteo. Describe qué hay dentro
    #: sin volcar el contenido.
    claves_metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ArchivoModelo:
    nombre: str
    bytes: int
    sha256: str

    def to_dict(self) -> dict:
        return asdict(self)


def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _consulta(con: sqlite3.Connection, sql: str, args: tuple = ()) -> list:
    # Un cursor nuevo por consulta: reusar el cursor de un bucle externo
    # lo reinicia y la iteración devuelve una sola fila. Pasó mientras se
    # escribía este inventario y dio un conteo de colecciones equivocado.
    cursor = con.cursor()
    cursor.execute(sql, args)
    return cursor.fetchall()


def inventariar_chroma(ruta_chroma: Path) -> dict:
    """Inventaría las colecciones de una base ChromaDB, en solo lectura."""
    sqlite_path = ruta_chroma / "chroma.sqlite3"
    if not sqlite_path.is_file():
        return {"existe": False, "ruta": str(ruta_chroma), "colecciones": []}

    con = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    try:
        colecciones = []
        filas = _consulta(
            con, "SELECT id, name, dimension FROM collections ORDER BY name"
        )
        for cid, nombre, dimension in filas:
            n = _consulta(
                con,
                "SELECT COUNT(*) FROM embeddings WHERE segment_id IN "
                "(SELECT id FROM segments WHERE collection=?)",
                (cid,),
            )[0][0]
            claves = dict(_consulta(
                con,
                "SELECT key, COUNT(*) FROM embedding_metadata WHERE id IN "
                "(SELECT id FROM embeddings WHERE segment_id IN "
                "(SELECT id FROM segments WHERE collection=?)) "
                "GROUP BY key ORDER BY 2 DESC",
                (cid,),
            ))
            colecciones.append(ColeccionInventariada(
                nombre=nombre,
                dimension=dimension,
                n_embeddings=n,
                rol=("conocimiento" if nombre in COLECCIONES_CONOCIMIENTO
                     else "memoria"),
                claves_metadata=claves,
            ).to_dict())

        # Desglose del catálogo: una subtécnica tiene un punto en su ID
        # (`T1001.001`). Se cuenta así y no por el campo `is_subtechnique`,
        # que en esta base está vacío en las 697 filas.
        con_punto = _consulta(
            con,
            "SELECT COUNT(*) FROM embedding_metadata WHERE key='technique_id' "
            "AND string_value LIKE '%.%'",
        )[0][0]
        sin_punto = _consulta(
            con,
            "SELECT COUNT(*) FROM embedding_metadata WHERE key='technique_id' "
            "AND string_value NOT LIKE '%.%'",
        )[0][0]
    finally:
        con.close()

    return {
        "existe": True,
        "ruta": str(ruta_chroma),
        "bytes_sqlite": sqlite_path.stat().st_size,
        "sha256_sqlite": _sha256(sqlite_path),
        "colecciones": colecciones,
        "catalogo_mitre": {
            "tecnicas_padre": sin_punto,
            "subtecnicas": con_punto,
            "total": sin_punto + con_punto,
            "nota": (
                "el campo is_subtechnique está vacío en las 697 filas; el "
                "desglose se deriva del punto en technique_id"
            ),
        },
    }


def inventariar_modelo_embeddings(nombre_modelo: str) -> dict:
    """Inventaría el modelo de embeddings en la caché de HuggingFace.

    El modelo no se carga: solo se hashean sus archivos. Cargarlo sería el
    primer paso de una consulta de ensayo, que el plan prohíbe.
    """
    cache = Path(
        os.environ.get("HF_HOME")
        or Path.home() / ".cache" / "huggingface"
    )
    if cache.name != "hub":
        cache = cache / "hub"
    carpeta = cache / f"models--sentence-transformers--{nombre_modelo}"
    if not carpeta.is_dir():
        return {
            "modelo": nombre_modelo,
            "en_cache": False,
            "nota": (
                "no está en la caché local: usarlo implicaría una descarga, "
                "que requiere autorización explícita"
            ),
        }

    snapshots = sorted(p for p in (carpeta / "snapshots").iterdir()
                       if p.is_dir()) if (carpeta / "snapshots").is_dir() else []
    archivos = []
    for snapshot in snapshots:
        for archivo in sorted(snapshot.iterdir()):
            real = archivo.resolve()
            if real.is_file():
                archivos.append(ArchivoModelo(
                    nombre=archivo.name,
                    bytes=real.stat().st_size,
                    sha256=_sha256(real),
                ).to_dict())
    return {
        "modelo": nombre_modelo,
        "en_cache": True,
        "revision": snapshots[-1].name if snapshots else None,
        "bytes_totales": sum(a["bytes"] for a in archivos),
        "archivos": archivos,
    }


def inventariar_catalogo_mitre(raiz_repo: Path) -> dict:
    """Inventaría el catálogo STIX y su procedencia."""
    directorio = raiz_repo / "data/mitre_attack"
    procedencia = directorio / "provenance.json"
    stix = sorted(p for p in directorio.glob("*.json")
                  if p.name != "provenance.json") if directorio.is_dir() else []
    resultado: dict = {
        "directorio": "data/mitre_attack",
        "procedencia_presente": procedencia.is_file(),
        "stix_presente": bool(stix),
        "archivos_stix": [
            {"nombre": p.name, "bytes": p.stat().st_size,
             "sha256": _sha256(p)} for p in stix
        ],
    }
    if procedencia.is_file():
        resultado["procedencia"] = json.loads(
            procedencia.read_text(encoding="utf-8")
        )
        resultado["sha256_procedencia"] = _sha256(procedencia)
    if not stix:
        resultado["nota"] = (
            "el JSON STIX no está versionado en el repositorio. No hace falta "
            "para el experimento: el catálogo ya está embebido en ChromaDB y "
            "la base experimental se puebla copiando esos vectores, sin "
            "recalcularlos ni volver a descargar el catálogo. Haría falta solo "
            "para reconstruir la base desde cero."
        )
    return resultado


def inventariar_conocimiento(
    raiz_repo: Path,
    ruta_chroma: Path,
    nombre_modelo: str = "all-MiniLM-L6-v2",
) -> dict:
    """Inventario completo. No abre ChromaDB ni carga el modelo."""
    return {
        "chroma_origen": inventariar_chroma(ruta_chroma),
        "modelo_embeddings": inventariar_modelo_embeddings(nombre_modelo),
        "catalogo_mitre": inventariar_catalogo_mitre(raiz_repo),
        "colecciones_de_conocimiento": list(COLECCIONES_CONOCIMIENTO),
        "colecciones_de_memoria_excluidas": list(COLECCIONES_MEMORIA),
    }
