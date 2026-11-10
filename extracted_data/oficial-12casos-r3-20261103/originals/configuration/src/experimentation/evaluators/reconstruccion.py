"""Evaluador de reconstrucción (D2). Fase 5, acción 3.

El matching es **exacto por `uid`**: se compara
`GroundTruth.core_event_uids` con los `uid` de
`ExperimentalOutput.reconstructed_events`. Nada de tolerancias ni
equivalencias.

El plan admite tolerancias solo en datasets **sin** identificador estable
equivalente. UWF tiene uno —el `uid` de Zeek— y se verificó que es apto:
único dentro de cada caso y entre casos, y sin colisiones reales en el
dataset. Con un identificador así, aplicar equivalencias aproximadas
inventaría aciertos.

HDFS y BGL no tienen identificador estable, así que esta dimensión queda
`no_aplica` por diseño. Para ellos no se define ninguna tolerancia: la
salida correcta es no medir, no medir mal.
"""

from __future__ import annotations

from src.experimentation.evaluators.conjuntos import (
    ComparacionConjuntos,
    ResultadoConjuntos,
    evaluar_conjuntos,
)

#: Datasets con identificador de evento estable, donde D2 es medible.
DATASETS_CON_UID_ESTABLE = ("uwf",)


def comparar_caso(
    case_id: str,
    uids_propuestos: list[str | None],
    core_event_uids: tuple[str, ...],
    uids_del_caso: frozenset[str] | None = None,
) -> tuple[ComparacionConjuntos, dict]:
    """Compara los eventos reconstruidos con los del incidente.

    `uids_del_caso` son los `uid` que realmente están en el archivo del
    caso. Si se pasa, los `uid` propuestos que no estén ahí se cuentan
    aparte como **afirmaciones no sustentadas**: no son un falso positivo
    sobre un evento real, son un evento inventado. Siguen sumando a `fp`
    —proponer algo que no está en la referencia es un falso positivo— pero
    el informe tiene que poder distinguir las dos cosas.
    """
    propuestos = {u for u in uids_propuestos if u}
    inventados: set[str] = set()
    if uids_del_caso is not None:
        inventados = propuestos - uids_del_caso

    comparacion = ComparacionConjuntos(
        case_id=case_id,
        propuesto=frozenset(propuestos),
        referencia=frozenset(core_event_uids),
    )
    diagnostico = {
        "n_propuestos": len(propuestos),
        "n_propuestos_sin_uid": sum(1 for u in uids_propuestos if not u),
        "uids_inventados": sorted(inventados),
        "n_uids_inventados": len(inventados),
    }
    return comparacion, diagnostico


def evaluar(
    comparaciones: list[ComparacionConjuntos],
    diagnosticos: list[dict] | None = None,
) -> tuple[ResultadoConjuntos, dict]:
    """Agrega las comparaciones de todos los casos evaluables."""
    resultado = evaluar_conjuntos(comparaciones)
    resumen = {}
    if diagnosticos:
        resumen = {
            "casos_con_uid_inventado": sum(
                1 for d in diagnosticos if d["n_uids_inventados"]
            ),
            "total_uids_inventados": sum(
                d["n_uids_inventados"] for d in diagnosticos
            ),
            "eventos_propuestos_sin_uid": sum(
                d["n_propuestos_sin_uid"] for d in diagnosticos
            ),
            "nota": (
                "un uid inventado suma a fp, pero se cuenta aparte porque no "
                "es un evento real mal elegido sino un evento que no existe"
            ),
        }
    return resultado, resumen
