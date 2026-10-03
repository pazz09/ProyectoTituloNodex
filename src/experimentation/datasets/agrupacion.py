"""Agrupación de líneas en unidades indivisibles.

La unidad de agrupación es la pieza central de la Fase 2: es lo que **no**
puede quedar partido entre desarrollo y evaluación, ni repetido entre dos
casos. Si se parte, el mismo dato se mide dos veces y la comparación entre
particiones deja de ser válida.

Cada dataset define su unidad de forma distinta:

- **HDFS**: el bloque. Pero una línea puede mencionar varios bloques, así
  que el bloque solo no sirve como unidad: si dos bloques comparten una
  línea y caen en casos distintos, la línea se duplicaría. La unidad real
  es el **componente conexo** del grafo bipartito bloque–línea. Medido
  sobre `HDFS_2k.log`: 1994 componentes, de los cuales 1991 son un bloque
  suelto, uno agrupa 9 bloques y dos agrupan 100 (las líneas
  `BLOCK* ask <ip> to delete <blk> ...`).

- **BGL**: la etiqueta es por línea y no hay identificador de transacción,
  así que la unidad es una **ventana contigua y disjunta** de líneas. El
  tamaño es un parámetro declarado, no un número mágico: ver
  `TAMANO_VENTANA_BGL`.

- **UWF**: la unidad es la sesión/incidente. Vive en `uwf.py` porque
  requiere leer Parquet.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

#: Un `blk_` puede ser negativo (`blk_-1608999687919862906`).
_BLOQUE = re.compile(r"blk_-?\d+")

#: Tamaño de la ventana de BGL, en líneas.
#:
#: Elegido midiendo `BGL_2k.log` (2000 líneas, 143 de alerta en 45 ráfagas
#: contiguas, la mayor de 60 líneas):
#:
#:   ventana  grupos  con >=1 alerta
#:        10     200       40 (20%)
#:        20     100       28 (28%)
#:        25      80       24 (30%)
#:        50      40       17 (42%)
#:       100      20       12 (60%)
#:
#: 20 es el mayor tamaño que todavía deja 100 grupos disjuntos, que es lo
#: que acota cuántos casos se pueden armar sin reutilizar líneas. Es un
#: parámetro, no una constante del dominio: cambiarlo cambia la unidad de
#: análisis y por eso queda registrado en el manifiesto de cada corrida.
TAMANO_VENTANA_BGL = 20

#: Etiquetas de BGL que significan "sin alerta".
_BGL_SIN_ALERTA = ("-", "")


@dataclass(frozen=True)
class LineaFuente:
    """Una línea del log, con su procedencia y su contenido ya saneado."""

    linea_original: int
    #: Contenido que verá la arquitectura. En BGL ya **sin** el token de
    #: etiqueta; en HDFS es la línea íntegra porque no lleva etiqueta.
    contenido: str
    #: Identificador estable del evento, si el dataset lo provee (`uid` de
    #: Zeek). HDFS y BGL no tienen uno, por eso queda `None` y la dimensión
    #: de reconstrucción no es puntuable ahí.
    uid: str | None = None


@dataclass
class GrupoDataset:
    """Unidad indivisible de un dataset."""

    grupo: str
    #: Etiqueta cruda del dataset, tal como viene (`Anomaly`, `KERNDTLB`,
    #: `-`). Se conserva sin normalizar para poder auditar la normalización.
    etiqueta_original: str
    #: `True` si el grupo cuenta como positivo de la pregunta de detección
    #: del dataset. Derivado de `etiqueta_original` por una regla explícita
    #: y documentada por dataset, nunca por heurística.
    es_positivo: bool
    lineas: tuple[LineaFuente, ...]
    #: Claves internas del grupo: los `blk_` que lo componen en HDFS. Sirve
    #: para auditar los componentes que agruparon varios bloques.
    miembros: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.lineas:
            raise ValueError(f"el grupo {self.grupo!r} no tiene líneas")

    @property
    def n_lineas(self) -> int:
        return len(self.lineas)


# --- HDFS ------------------------------------------------------------------

def agrupar_hdfs(ruta_log: Path, ruta_etiquetas: Path) -> list[GrupoDataset]:
    """Agrupa HDFS por componente conexo del grafo bloque–línea.

    Regla de positividad: el grupo es positivo si **alguno** de sus bloques
    está etiquetado `Anomaly`. Es la única regla compatible con un veredicto
    binario por caso; los grupos mixtos (anómalo + normal en el mismo
    componente) se registran para poder contarlos: en `HDFS_2k.log` hay 1.
    """
    lineas = ruta_log.read_text(encoding="utf-8", errors="replace").splitlines()
    with ruta_etiquetas.open(newline="", encoding="utf-8") as f:
        etiquetas = {fila["BlockId"]: fila["Label"] for fila in csv.DictReader(f)}

    bloques_por_linea = [sorted(set(_BLOQUE.findall(linea))) for linea in lineas]

    # Union-find: dos bloques quedan unidos si comparten alguna línea.
    padre: dict[str, str] = {}

    def raiz(x: str) -> str:
        padre.setdefault(x, x)
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    for bloques in bloques_por_linea:
        for bloque in bloques:
            raiz(bloque)
        for bloque in bloques[1:]:
            ra, rb = raiz(bloques[0]), raiz(bloque)
            if ra != rb:
                padre[ra] = rb

    miembros: dict[str, list[str]] = {}
    for bloque in sorted(padre):
        miembros.setdefault(raiz(bloque), []).append(bloque)

    lineas_por_componente: dict[str, list[LineaFuente]] = {}
    for numero, (bloques, texto) in enumerate(zip(bloques_por_linea, lineas), start=1):
        if not bloques:
            # Una línea sin `blk_` no pertenece a ningún bloque y por lo
            # tanto no tiene etiqueta: no puede formar parte de un caso
            # etiquetado. En `HDFS_2k.log` no hay ninguna.
            continue
        clave = raiz(bloques[0])
        lineas_por_componente.setdefault(clave, []).append(
            LineaFuente(linea_original=numero, contenido=texto)
        )

    grupos: list[GrupoDataset] = []
    for clave in sorted(lineas_por_componente):
        bloques = tuple(miembros[clave])
        etiquetas_grupo = [etiquetas.get(b, "Desconocida") for b in bloques]
        anomalos = [b for b, e in zip(bloques, etiquetas_grupo) if e == "Anomaly"]
        # El nombre del grupo usa el bloque menor para ser estable frente al
        # orden de recorrido; si agrupa varios, lo declara en el sufijo.
        nombre = bloques[0] if len(bloques) == 1 else f"{bloques[0]}+{len(bloques) - 1}"
        grupos.append(
            GrupoDataset(
                grupo=nombre,
                etiqueta_original="Anomaly" if anomalos else "Normal",
                es_positivo=bool(anomalos),
                lineas=tuple(
                    sorted(lineas_por_componente[clave], key=lambda l: l.linea_original)
                ),
                miembros=bloques,
            )
        )
    return grupos


# --- BGL -------------------------------------------------------------------

def etiqueta_bgl(linea: str) -> str:
    """Primer token de la línea: `-` si no hay alerta, el código si la hay."""
    partido = linea.split(None, 1)
    return partido[0] if partido else ""


def _sin_etiqueta_bgl(linea: str) -> str:
    """Retira el token de etiqueta embebido.

    Obligatorio: dejarlo haría que la arquitectura leyera la respuesta. Es
    la fuga que el proyecto ya tuvo con BGL.
    """
    partido = linea.split(None, 1)
    if len(partido) == 2 and (partido[0] == "-" or partido[0].isupper()):
        return partido[1]
    return linea


def agrupar_bgl(ruta_log: Path, tamano_ventana: int = TAMANO_VENTANA_BGL) -> list[GrupoDataset]:
    """Agrupa BGL en ventanas contiguas y disjuntas de líneas.

    Regla de positividad: la ventana es positiva si **alguna** de sus líneas
    trae un código de alerta distinto de `-`.
    """
    if tamano_ventana < 1:
        raise ValueError(f"tamano_ventana debe ser >= 1; es {tamano_ventana}")
    lineas = ruta_log.read_text(encoding="utf-8", errors="replace").splitlines()

    grupos: list[GrupoDataset] = []
    for inicio in range(0, len(lineas), tamano_ventana):
        bloque = lineas[inicio:inicio + tamano_ventana]
        etiquetas = [etiqueta_bgl(l) for l in bloque]
        alertas = [e for e in etiquetas if e not in _BGL_SIN_ALERTA]
        grupos.append(
            GrupoDataset(
                # El nombre lleva el rango de líneas 1-indexado: hace el
                # grupo trazable al archivo original sin consultar nada más.
                grupo=f"bgl_l{inicio + 1:05d}-{inicio + len(bloque):05d}",
                # Si hay varias alertas se conserva la primera, y el conteo
                # queda en las notas del caso. Inventar una etiqueta
                # compuesta rompería el vocabulario del dataset.
                etiqueta_original=alertas[0] if alertas else "-",
                es_positivo=bool(alertas),
                lineas=tuple(
                    LineaFuente(
                        linea_original=inicio + desplazamiento + 1,
                        contenido=_sin_etiqueta_bgl(texto),
                    )
                    for desplazamiento, texto in enumerate(bloque)
                ),
            )
        )
    return grupos
