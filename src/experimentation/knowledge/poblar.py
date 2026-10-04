"""Poblado de la base vectorial del experimento (Fase 3, acción 6).

Copia **solo el conocimiento** —la colección `attack_techniques`, con el
catálogo ATT&CK embebido— desde una base de origen a la base del
experimento. Las colecciones de memoria de corridas previas se dejan
afuera: `host_history` y `error_memory` acumulan información de análisis
anteriores, y dentro de un experimento le darían al sistema datos sobre un
caso que no vinieron del caso.

Dos decisiones de implementación que importan:

1. **Se copian los vectores ya calculados**, no se recalculan. Así no se
   carga el modelo de embeddings (lo que sería el primer paso de una
   consulta de ensayo, prohibida) y no se necesita el JSON STIX. Si se
   recalcularan, dos campañas con versiones distintas de
   `sentence-transformers` darían similitudes distintas y los resultados no
   serían comparables.

   La copia **no** es bit a bit idéntica, y conviene decirlo con el número
   medido en vez de afirmar lo contrario: Chroma almacena en `float32` y
   devuelve `float64`, así que el viaje de ida y vuelta mueve el último bit
   de 18 076 de 267 648 componentes (6,8%). La diferencia absoluta máxima
   es **1,49e-08** sobre vectores de norma 1, y la similitud coseno fila a
   fila da **1,0 con 12 decimales**. A efectos de recuperación es el mismo
   catálogo; el ranking solo podría cambiar en un empate exacto.

2. **El origen debe ser una copia**, nunca la base de producción. Abrir una
   base con la API de Chroma puede ejecutarle migraciones de esquema; el
   driver copia el directorio antes de abrirlo y después verifica que el
   original no cambió de hash.

Requiere `chromadb`, que **no** está en `requirements-experimentacion.txt`:
este módulo se corre con el intérprete que ya tiene la dependencia fijada
(`chromadb==1.5.9`), sin instalar nada nuevo en ningún entorno.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.experimentation.knowledge.inventario import (
    COLECCIONES_CONOCIMIENTO,
    COLECCIONES_MEMORIA,
    inventariar_chroma,
)

#: Tamaño del lote al insertar. Chroma acepta inserciones grandes, pero
#: lotes acotados hacen que un fallo a mitad de camino sea diagnosticable.
LOTE = 200


def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def copiar_conocimiento(origen: Path, destino: Path) -> dict:
    """Copia las colecciones de conocimiento de `origen` a `destino`.

    `origen` tiene que ser una copia de trabajo, no la base de producción.
    """
    import chromadb

    if destino.exists() and any(destino.iterdir()):
        raise ValueError(
            f"el destino {destino} no está vacío: poblar sobre una base "
            "existente mezclaría dos conocimientos y el resultado no sería "
            "reproducible. Borrarlo explícitamente si se quiere repoblar"
        )
    destino.mkdir(parents=True, exist_ok=True)

    cliente_origen = chromadb.PersistentClient(path=str(origen))
    cliente_destino = chromadb.PersistentClient(path=str(destino))

    disponibles = {c.name for c in cliente_origen.list_collections()}
    faltantes = set(COLECCIONES_CONOCIMIENTO) - disponibles
    if faltantes:
        raise ValueError(
            f"la base de origen no tiene {sorted(faltantes)}; tiene "
            f"{sorted(disponibles)}"
        )

    resumen = {
        "origen": str(origen),
        "destino": str(destino),
        "colecciones_copiadas": {},
        "colecciones_omitidas": sorted(disponibles & set(COLECCIONES_MEMORIA)),
        "metodo": "copia de vectores ya calculados; no se recalcula ninguno",
    }

    for nombre in COLECCIONES_CONOCIMIENTO:
        original = cliente_origen.get_collection(nombre)
        total = original.count()
        # `include` explícito: sin los embeddings, Chroma los recalcularía
        # al insertar, que es justo lo que hay que evitar.
        datos = original.get(
            include=["embeddings", "documents", "metadatas"], limit=total
        )
        nueva = cliente_destino.create_collection(
            name=nombre, metadata=original.metadata or None
        )
        for inicio in range(0, total, LOTE):
            fin = inicio + LOTE
            nueva.add(
                ids=datos["ids"][inicio:fin],
                embeddings=datos["embeddings"][inicio:fin],
                documents=datos["documents"][inicio:fin],
                metadatas=datos["metadatas"][inicio:fin],
            )
        resumen["colecciones_copiadas"][nombre] = {
            "documentos_origen": total,
            "documentos_destino": nueva.count(),
            "dimension": (
                len(datos["embeddings"][0]) if total and datos["embeddings"]
                is not None and len(datos["embeddings"]) else None
            ),
        }
    return resumen


def main(raiz_repo: Path, origen_copia: Path, original: Path) -> None:
    from src.experimentation.knowledge.aislamiento import (
        configuracion_experimental,
    )

    hash_antes = _sha256(original / "chroma.sqlite3")
    configuracion = configuracion_experimental(raiz_repo)
    resumen = copiar_conocimiento(origen_copia, configuracion.chroma)

    hash_despues = _sha256(original / "chroma.sqlite3")
    resumen["original_sin_modificar"] = hash_antes == hash_despues
    resumen["sha256_original_antes"] = hash_antes
    resumen["sha256_original_despues"] = hash_despues
    # Inventario de la base resultante, leído del SQLite en modo `ro`: no se
    # vuelve a abrir con la API.
    resumen["inventario_resultante"] = inventariar_chroma(configuracion.chroma)

    destino_json = configuracion.raiz / "poblado_chroma.json"
    destino_json.write_text(
        json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    for nombre, detalle in resumen["colecciones_copiadas"].items():
        print(f"{nombre}: {detalle['documentos_origen']} -> "
              f"{detalle['documentos_destino']} docs, dim={detalle['dimension']}")
    print(f"omitidas (memoria): {resumen['colecciones_omitidas']}")
    print(f"original sin modificar: {resumen['original_sin_modificar']}")
    for coleccion in resumen["inventario_resultante"]["colecciones"]:
        print(f"  base experimental: {coleccion['nombre']} "
              f"rol={coleccion['rol']} embeddings={coleccion['n_embeddings']}")
    print(f"resumen escrito en {destino_json}")
