"""Inventario de los archivos fuente, con hash.

Un número experimental sin el hash del archivo que lo produjo no es
reproducible: basta que alguien reemplace el log por otra muestra para que
la métrica cambie sin que nadie lo note. Este módulo reutiliza
`src/tools/provenance.py` (ya existente, de la Fase 6 anterior) en vez de
reimplementar el hashing.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

#: Archivos fuente declarados, con el rol que cumple cada uno. `etiquetas`
#: indica si el archivo contiene la referencia: esos **no** pueden entrar
#: nunca al contenido de un caso.
FUENTES_DECLARADAS: dict[str, dict] = {
    "hdfs_log": {
        "ruta": "data/logs/HDFS_2k.log",
        "dataset": "hdfs",
        "rol": "log",
        "etiquetas": False,
    },
    "hdfs_labels": {
        "ruta": "data/labels/hdfs_anomaly_label_2k.csv",
        "dataset": "hdfs",
        "rol": "etiquetas",
        "etiquetas": True,
    },
    "bgl_log": {
        "ruta": "data/logs/BGL_2k.log",
        "dataset": "bgl",
        "rol": "log",
        # BGL trae la etiqueta EMBEBIDA como primer token de cada línea.
        # El archivo es a la vez log y referencia: por eso el generador
        # tiene que retirar ese token al materializar el caso.
        "etiquetas": True,
    },
    "uwf_parquet": {
        "ruta": "data/logs/UWF-ZeekDataFall22-parquet",
        "dataset": "uwf",
        "rol": "log+etiquetas",
        # Las columnas label_tactic / label_technique / label_binary son
        # referencia y viajan al canal de ground truth.
        "etiquetas": True,
    },
}


@dataclass(frozen=True)
class ArchivoInventariado:
    ruta_relativa: str
    bytes: int
    sha256: str
    #: `None` para archivos binarios (Parquet): contar líneas no aplica.
    lineas: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _es_texto(ruta: Path) -> bool:
    return ruta.suffix.lower() in {".log", ".csv", ".txt", ".json", ".tsv"}


def inventariar(ruta: Path, raiz: Path) -> list[ArchivoInventariado]:
    """Inventaría un archivo, o todos los de un directorio, recursivamente.

    Las rutas se guardan relativas a `raiz` para que el manifiesto no
    dependa de dónde está clonado el repositorio.
    """
    if not ruta.exists():
        raise FileNotFoundError(f"fuente declarada ausente: {ruta}")
    archivos = sorted(p for p in ruta.rglob("*") if p.is_file()) if ruta.is_dir() else [ruta]
    inventario: list[ArchivoInventariado] = []
    for archivo in archivos:
        datos = archivo.read_bytes()
        lineas = None
        if _es_texto(archivo):
            lineas = datos.count(b"\n") + (0 if datos.endswith(b"\n") or not datos else 1)
        inventario.append(
            ArchivoInventariado(
                ruta_relativa=archivo.relative_to(raiz).as_posix(),
                bytes=len(datos),
                sha256=_sha256(archivo),
                lineas=lineas,
            )
        )
    return inventario


def inventariar_fuentes(raiz: Path) -> dict[str, list[dict]]:
    """Inventaría todas las fuentes declaradas presentes bajo `raiz`."""
    resultado: dict[str, list[dict]] = {}
    for clave, meta in FUENTES_DECLARADAS.items():
        ruta = raiz / meta["ruta"]
        if not ruta.exists():
            resultado[clave] = []
            continue
        resultado[clave] = [a.to_dict() for a in inventariar(ruta, raiz)]
    return resultado
