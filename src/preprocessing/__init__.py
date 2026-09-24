"""Preprocesamiento heterogéneo de logs (esquema v2) -- único motor del
sistema desde el 23-sep-2026 (el motor anterior de adaptadores por
formato se retiró; ver "Preprocesamiento" en el README).

Flujo: ingesta -> segmentación -> detección y decodificación ->
enriquecimiento -> agregación (ver `docs/pipeline_preprocesamiento.md`
para el detalle de cada etapa). `src/tools/aggregation.py` sigue siendo
la fachada que el resto del sistema usa (`aggregate_logs()`,
`preprocesar_lote()`), pero por debajo corre exclusivamente esta tubería.
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
