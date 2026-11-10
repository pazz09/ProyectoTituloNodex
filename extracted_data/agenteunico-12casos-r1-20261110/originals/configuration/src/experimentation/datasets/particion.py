"""Partición desarrollo / evaluación **por grupo**, no por línea ni por caso.

Decisión D-1 (3-oct-2026): 30% desarrollo, 70% evaluación.

Particionar por grupo es el requisito que el plan pone para que no haya
fuga: si el mismo bloque de HDFS (o la misma ventana de BGL) aparece en las
dos particiones, lo que se depuró en desarrollo ya se vio en evaluación y
la métrica de evaluación deja de ser una medición sobre datos reservados.

La partición se estratifica por positividad. Sin estratificar, con 69
grupos positivos sobre 1994 la asignación aleatoria puede dejar una
partición con una prevalencia muy distinta de la otra por puro azar, y
después no se sabe si una diferencia de resultados vino del sistema o del
reparto.
"""

from __future__ import annotations

import random
from collections import Counter

from src.experimentation.contracts.enums import PARTICIONES
from src.experimentation.datasets.agrupacion import GrupoDataset

#: Semilla por omisión. Está declarada acá y se copia al manifiesto de cada
#: generación: sin la semilla registrada, la partición no es reproducible.
SEMILLA_PARTICION = 20261003


def particionar_grupos(
    grupos: list[GrupoDataset],
    proporcion_desarrollo: float = 0.30,
    semilla: int = SEMILLA_PARTICION,
) -> dict[str, list[GrupoDataset]]:
    """Reparte los grupos entre `desarrollo` y `evaluacion`.

    El reparto es determinístico dada la semilla y el orden de entrada se
    normaliza por nombre de grupo, así que no depende de cómo los produjo
    el agrupador.
    """
    if not 0.0 < proporcion_desarrollo < 1.0:
        raise ValueError(
            "proporcion_desarrollo debe estar en (0,1); es "
            f"{proporcion_desarrollo}"
        )
    nombres = [g.grupo for g in grupos]
    repetidos = [n for n, veces in Counter(nombres).items() if veces > 1]
    if repetidos:
        raise ValueError(
            f"hay {len(repetidos)} nombres de grupo repetidos (p. ej. "
            f"{repetidos[:3]}): un grupo repetido se mediría dos veces"
        )

    reparto: dict[str, list[GrupoDataset]] = {p: [] for p in PARTICIONES}
    for positivo in (True, False):
        estrato = sorted(
            (g for g in grupos if g.es_positivo is positivo), key=lambda g: g.grupo
        )
        # Una instancia propia de Random por estrato, sembrada de forma
        # distinta pero determinística: así agregar grupos a un estrato no
        # reordena el otro.
        random.Random(semilla + int(positivo)).shuffle(estrato)
        corte = round(len(estrato) * proporcion_desarrollo)
        reparto["desarrollo"].extend(estrato[:corte])
        reparto["evaluacion"].extend(estrato[corte:])

    for particion in PARTICIONES:
        reparto[particion].sort(key=lambda g: g.grupo)
    verificar_sin_fuga(reparto)
    return reparto


def verificar_sin_fuga(reparto: dict[str, list[GrupoDataset]]) -> None:
    """Falla si un grupo quedó en más de una partición."""
    vistos: dict[str, str] = {}
    for particion, grupos in reparto.items():
        for grupo in grupos:
            if grupo.grupo in vistos:
                raise ValueError(
                    f"fuga entre particiones: el grupo {grupo.grupo!r} está en "
                    f"{vistos[grupo.grupo]!r} y en {particion!r}"
                )
            vistos[grupo.grupo] = particion


def resumen_particion(reparto: dict[str, list[GrupoDataset]]) -> dict:
    """Conteos por partición, para el manifiesto."""
    resumen = {}
    for particion, grupos in reparto.items():
        positivos = sum(1 for g in grupos if g.es_positivo)
        resumen[particion] = {
            "n_grupos": len(grupos),
            "n_grupos_positivos": positivos,
            "n_lineas": sum(g.n_lineas for g in grupos),
            "prevalencia_de_grupos": (
                round(positivos / len(grupos), 6) if grupos else None
            ),
        }
    return resumen
