"""Preprocesamiento heterogéneo de logs (esquema v2).

Implementa el plan de `docs/plan_accion_preprocesamiento_heterogeneo.md`.
Durante la migración este paquete convive con `src/tools/aggregation.py`
(esquema v1): los modelos y la tubería nuevos se construyen aparte y no
alteran ningún contrato existente hasta la Fase 8.
"""

from src.preprocessing.models import (
    GroundTruthRecord,
    NormalizedEvent,
    ParsingWarning,
    RecordSegment,
)
from src.preprocessing.result import PreprocessingResult

__all__ = [
    "GroundTruthRecord",
    "NormalizedEvent",
    "ParsingWarning",
    "PreprocessingResult",
    "RecordSegment",
]
