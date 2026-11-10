"""Interfaz común de los decodificadores estructurales (Fase 4 del plan).

Un decoder interpreta la ESTRUCTURA de un registro (JSON, CSV, syslog,
CEF...), no su significado de seguridad. La distinción es deliberada y es
uno de los criterios de aceptación de la fase: **ningún decoder decide que
existe un ataque**. Eso queda para los agentes, que es donde el informe lo
ubica.

Contrato:

- `detectar(texto, contexto)` devuelve una confianza en [0, 1] sin efectos
  secundarios. Se usa para elegir el decoder dominante de un bloque.
- `decodificar(registro, contexto)` devuelve un `NormalizedEvent`. Nunca
  lanza por contenido malformado: ante la duda, devuelve lo que pudo y
  agrega una advertencia. Lo que aborta un lote no es un log raro.
- `contexto` es el diccionario del segmento (`RecordSegment.context`), no
  estado del propio decoder. Así dos análisis concurrentes con cabeceras
  CSV distintas no se pisan, que fue un problema real del adaptador v1.
"""

from src.preprocessing.models import NormalizedEvent
from src.preprocessing.segmentation import RawRecord


class Decoder:
    """Clase base. Los decoders son sin estado; el estado vive en `contexto`."""

    nombre: str = "base"

    def detectar(self, texto: str, contexto: dict | None = None) -> float:
        raise NotImplementedError

    def decodificar(self, registro: RawRecord,
                    contexto: dict | None = None) -> NormalizedEvent:
        raise NotImplementedError

    # -- helper compartido --
    def _evento_base(self, registro: RawRecord, mensaje: str,
                     confianza: float) -> NormalizedEvent:
        return NormalizedEvent(
            raw=registro.raw,
            message=mensaje,
            decoder=self.nombre,
            parsing_confidence=confianza,
            record_number=registro.record_number or None,
            line_start=registro.line_start,
            line_end=registro.line_end,
            is_multiline=registro.is_multiline,
            warnings=list(registro.warnings),
        )
