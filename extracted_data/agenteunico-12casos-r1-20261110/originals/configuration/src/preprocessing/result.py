"""Resultado del preprocesamiento v2 (Fase 1 del plan).

`PreprocessingResult` es lo que la tubería nueva devolverá cuando exista
(Fase 5). Acá se define el contenedor y sus invariantes; todavía nadie lo
produce ni lo consume.

Dos propiedades que este contenedor garantiza por construcción, y que la
línea base no tenía:

- **Líneas físicas y eventos lógicos son contadores distintos.** En v1,
  `total_lineas` mezclaba ambos, así que un stack trace de 30 líneas
  inflaba el conteo de eventos por 30.
- **El ground truth no sale por la puerta principal.** `to_dict()` lo
  omite salvo que se pida explícitamente, de modo que pasar el resultado
  al detector no puede filtrar etiquetas por descuido.
"""

from dataclasses import dataclass, field

from src.preprocessing.models import (
    GroundTruthRecord,
    NormalizedEvent,
    ParsingWarning,
    RecordSegment,
)


@dataclass
class PreprocessingResult:
    """Salida completa de una corrida de preprocesamiento."""

    schema_version: str
    total_lineas_fisicas: int = 0
    events: list[NormalizedEvent] = field(default_factory=list)
    segments: list[RecordSegment] = field(default_factory=list)
    warnings: list[ParsingWarning] = field(default_factory=list)
    # Canal separado: NO forma parte de las features observadas.
    ground_truth: list[GroundTruthRecord] = field(default_factory=list)
    # Configuración efectiva de la corrida, para poder reproducirla.
    config: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.schema_version:
            raise ValueError("PreprocessingResult.schema_version no puede estar vacía")
        if self.total_lineas_fisicas < 0:
            raise ValueError(
                f"total_lineas_fisicas no puede ser negativo: {self.total_lineas_fisicas}"
            )

    # --- contadores derivados ---
    @property
    def total_eventos(self) -> int:
        """Eventos lógicos. Distinto de `total_lineas_fisicas` a propósito."""
        return len(self.events)

    @property
    def eventos_fallback(self) -> int:
        return sum(1 for e in self.events if e.es_fallback)

    @property
    def eventos_decodificados(self) -> int:
        return self.total_eventos - self.eventos_fallback

    @property
    def cobertura(self) -> float:
        """Fracción de eventos con estructura reconocida, en [0, 1].

        Un lote vacío tiene cobertura 0.0 (no 1.0): no se decodificó nada,
        y reportar cobertura perfecta sobre cero eventos sería engañoso.
        """
        if not self.events:
            return 0.0
        return round(self.eventos_decodificados / self.total_eventos, 4)

    def distribucion_decoders(self) -> dict[str, int]:
        dist: dict[str, int] = {}
        for e in self.events:
            dist[e.decoder] = dist.get(e.decoder, 0) + 1
        return {k: dist[k] for k in sorted(dist)}

    def resumen_parsing(self) -> dict:
        return {
            "parsed_events": self.eventos_decodificados,
            "fallback_events": self.eventos_fallback,
            "coverage": self.cobertura,
        }

    # --- serialización ---
    def to_dict(self, incluir_eventos: bool = True,
                incluir_ground_truth: bool = False) -> dict:
        """Serializa de forma determinística.

        `incluir_ground_truth` es False por defecto **a propósito**: el
        camino natural del dato -- pasar este resultado al resumen que ve
        el detector -- no debe poder filtrar etiquetas. Quien calcula
        métricas lo pide de forma explícita.

        `incluir_eventos=False` da la vista compacta para el estado de
        LangGraph, que no debe crecer con el contenido completo del
        archivo (§14 del plan, riesgo de uso de memoria).
        """
        d: dict = {
            "schema_version": self.schema_version,
            "total_lineas_fisicas": self.total_lineas_fisicas,
            "total_eventos": self.total_eventos,
            "decoder_distribution": self.distribucion_decoders(),
            "parsing": self.resumen_parsing(),
            "segments": [s.to_dict() for s in self.segments],
            "warnings": [w.to_dict() for w in self.warnings],
            "config": {k: self.config[k] for k in sorted(self.config, key=str)},
        }
        if incluir_eventos:
            d["events"] = [e.to_dict() for e in self.events]
        if incluir_ground_truth:
            d["ground_truth"] = [g.to_dict() for g in self.ground_truth]
        return d

    def ground_truth_por_clave(self) -> dict[str, str]:
        """Mapa clave -> etiqueta, para la evaluación posterior al análisis."""
        return {g.key: g.label for g in self.ground_truth}
