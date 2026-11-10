"""Armado de `MetricsRecord` y escritura de resultados. Fase 5, acciones 6 y 8.

Dos responsabilidades, las dos sobre honestidad contable más que sobre
cálculo:

1. **Que la contabilidad cuadre.** `MetricsRecord` exige que
   `n_evaluables + Σ n_por_estado == n_casos`. Si un caso se pierde entre
   medio, la métrica describe menos casos de los que se corrieron y no es
   publicable. El invariante está en el contrato y acá se alimenta.

2. **No sobrescribir resultados históricos** (acción 8). Una corrección no
   edita un artefacto viejo: genera uno nuevo, con su versión de protocolo.
   Así el informe de la tesis puede citar un resultado y que ese resultado
   siga existiendo tal como se citó.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.experimentation.contracts import PROTOCOLO_VERSION
from src.experimentation.contracts.enums import ESTADOS_NO_PUNTUABLES
from src.experimentation.contracts.metricas import DetectionCounts, MetricsRecord


def contabilidad(estados: list[str]) -> tuple[int, int, dict]:
    """De una lista de estados por caso a `(n_casos, n_evaluables, n_por_estado)`.

    Es la función que garantiza que nada se pierda: todo caso cae en
    `evaluable` o en uno de los cuatro estados no puntuables, y la suma da
    el total por construcción.
    """
    n_por_estado: dict[str, int] = {}
    n_evaluables = 0
    for estado in estados:
        if estado == "evaluable":
            n_evaluables += 1
        elif estado in ESTADOS_NO_PUNTUABLES:
            n_por_estado[estado] = n_por_estado.get(estado, 0) + 1
        else:
            raise ValueError(
                f"estado de dimensión desconocido: {estado!r}. No se puede "
                "contabilizar un caso en un estado que no existe"
            )
    return len(estados), n_evaluables, n_por_estado


def construir_deteccion(
    arquitectura: str,
    dataset: str,
    estados: list[str],
    conteos: DetectionCounts,
    metricas: dict,
    unidad_agregacion: str = "dataset",
) -> MetricsRecord:
    """`MetricsRecord` de D1."""
    n_casos, n_evaluables, n_por_estado = contabilidad(estados)
    return MetricsRecord(
        dimension="deteccion",
        arquitectura=arquitectura,
        dataset=dataset,
        protocolo_version=PROTOCOLO_VERSION,
        unidad_agregacion=unidad_agregacion,
        conteos=conteos,
        accuracy=metricas.get("accuracy"),
        precision=metricas.get("precision"),
        recall=metricas.get("recall"),
        f1=metricas.get("f1"),
        fpr=metricas.get("fpr"),
        fnr=metricas.get("fnr"),
        n_casos=n_casos,
        n_evaluables=n_evaluables,
        n_por_estado=n_por_estado,
    )


def construir_conjuntos(
    dimension: str,
    arquitectura: str,
    dataset: str,
    estados: list[str],
    resultado,
    nivel: str | None = None,
) -> MetricsRecord:
    """`MetricsRecord` de D2 o D3, desde un `ResultadoConjuntos`.

    Se informa **micro** en los campos del contrato y macro queda en el
    artefacto completo: el contrato tiene un solo juego de campos y elegir
    micro para ellos es una decisión que hay que declarar, no esconder.
    """
    if dimension not in ("reconstruccion", "mitre"):
        raise ValueError(f"dimensión de conjuntos inválida: {dimension!r}")
    n_casos, n_evaluables, n_por_estado = contabilidad(estados)
    return MetricsRecord(
        dimension=dimension,
        arquitectura=arquitectura,
        dataset=dataset,
        protocolo_version=PROTOCOLO_VERSION,
        set_precision=resultado.micro.get("precision"),
        set_recall=resultado.micro.get("recall"),
        set_f1=resultado.micro.get("f1"),
        exact_match=resultado.exact_match,
        nivel=nivel,
        n_casos=n_casos,
        n_evaluables=n_evaluables,
        n_por_estado=n_por_estado,
    )


def construir_reporte(
    arquitectura: str, dataset: str, estados: list[str], resultado
) -> MetricsRecord:
    """`MetricsRecord` de D4."""
    n_casos, n_evaluables, n_por_estado = contabilidad(estados)
    return MetricsRecord(
        dimension="reporte",
        arquitectura=arquitectura,
        dataset=dataset,
        protocolo_version=PROTOCOLO_VERSION,
        rubrica_por_criterio=resultado.por_criterio,
        rubrica_n_evaluadores=resultado.n_evaluadores,
        n_casos=n_casos,
        n_evaluables=n_evaluables,
        n_por_estado=n_por_estado,
    )


def construir_consumo(
    arquitectura: str, dataset: str, estados: list[str], resultado
) -> MetricsRecord:
    """`MetricsRecord` de D5."""
    n_casos, n_evaluables, n_por_estado = contabilidad(estados)
    return MetricsRecord(
        dimension="consumo",
        arquitectura=arquitectura,
        dataset=dataset,
        protocolo_version=PROTOCOLO_VERSION,
        consumo=resultado.to_dict(),
        n_casos=n_casos,
        n_evaluables=n_evaluables,
        n_por_estado=n_por_estado,
    )


def escribir_resultado(
    registros: list[MetricsRecord],
    destino: Path,
    detalle: dict | None = None,
    etiqueta: str | None = None,
    marca: str | None = None,
) -> Path:
    """Escribe un artefacto de resultados **nuevo**, sin sobrescribir ninguno.

    El nombre lleva la versión de protocolo y una marca temporal UTC. Si el
    archivo ya existe, **falla**: la acción 8 del plan prohíbe recalcular o
    sobrescribir resultados históricos, porque un informe que cita un
    resultado tiene que poder seguir citándolo.

    `marca` existe para poder fijar el nombre. Sin eso, la marca al segundo
    hace que dos llamadas den nombres distintos o iguales según el reloj, y
    una prueba de "no sobrescribe" quedaría intermitente.
    """
    destino.mkdir(parents=True, exist_ok=True)
    marca = marca or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sufijo = f"_{etiqueta}" if etiqueta else ""
    archivo = destino / f"metricas_p{PROTOCOLO_VERSION}_{marca}{sufijo}.json"
    if archivo.exists():
        raise FileExistsError(
            f"{archivo} ya existe. Los resultados no se sobrescriben: una "
            "corrección genera un artefacto nuevo"
        )
    archivo.write_text(
        json.dumps(
            {
                "protocolo_version": PROTOCOLO_VERSION,
                "generado_utc": marca,
                "registros": [r.to_dict() for r in registros],
                "detalle": detalle or {},
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return archivo
