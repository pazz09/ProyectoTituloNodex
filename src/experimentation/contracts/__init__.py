"""Contratos versionados del protocolo experimental.

`CONTRATO_VERSION` identifica la forma de los artefactos;
`PROTOCOLO_VERSION` identifica las REGLAS con que se interpretan (qué es un
acierto, cómo se hace matching, qué denominador se usa). Son dos cosas
distintas: se puede agregar un campo opcional sin cambiar las reglas, y se
pueden cambiar las reglas sin cambiar la forma. Dos campañas con
`PROTOCOLO_VERSION` distinta no son comparables entre sí.
"""

from src.experimentation.contracts.casos import (
    GroundTruth,
    ReferenciaMitre,
    RegistroProcedencia,
    TestCase,
)
from src.experimentation.contracts.ejecucion import ExperimentConfig, RunRecord
from src.experimentation.contracts.metricas import DetectionCounts, MetricsRecord
from src.experimentation.contracts.salida import (
    ExperimentalOutput,
    MitreCandidate,
    MitreItem,
    ReconstructedEvent,
)

#: Forma de los artefactos serializados.
CONTRATO_VERSION = "1.0"

#: Reglas de evaluación (matching, denominadores, aplicabilidad). Sube
#: cuando cambia un criterio, aunque la forma no cambie.
PROTOCOLO_VERSION = "1.0"

__all__ = [
    "CONTRATO_VERSION",
    "PROTOCOLO_VERSION",
    "DetectionCounts",
    "ExperimentConfig",
    "ExperimentalOutput",
    "GroundTruth",
    "MetricsRecord",
    "MitreCandidate",
    "MitreItem",
    "ReconstructedEvent",
    "ReferenciaMitre",
    "RegistroProcedencia",
    "RunRecord",
    "TestCase",
]
