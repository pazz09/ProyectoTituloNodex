"""Decoder de texto libre: el fallback obligatorio (Fase 4 del plan).

Acepta cualquier registro y nunca falla. Es lo que garantiza el nivel de
servicio 1 del plan ("todo registro textual debe poder recibirse y
conservarse"): un formato desconocido no aborta el lote ni se descarta,
queda acá con confianza baja y su contenido íntegro.

Extrae solamente lo que se puede afirmar de cualquier texto: las IPv4 que
aparezcan. **No** clasifica servicios ni eventos por palabras clave, a
diferencia del adaptador auth-log del esquema v1, que era el fallback
universal y le atribuía semántica de sshd/apache/kernel a texto que podía
no serlo (riesgo 5 de la línea base).
"""

from src.preprocessing.decoders.base import Decoder
from src.preprocessing.models import NormalizedEvent
from src.preprocessing.normalization import ips_del_texto
from src.preprocessing.segmentation import RawRecord

# Confianza fija y baja: el texto libre siempre "puede" interpretar, pero
# no entendió la estructura. Debe perder contra cualquier decoder real.
CONFIANZA_TEXTO = 0.10


class TextDecoder(Decoder):
    nombre = "text"

    def detectar(self, texto: str, contexto: dict | None = None) -> float:
        return CONFIANZA_TEXTO

    def decodificar(self, registro: RawRecord,
                    contexto: dict | None = None) -> NormalizedEvent:
        ev = self._evento_base(registro, registro.raw, CONFIANZA_TEXTO)
        ips = ips_del_texto(registro.raw)
        if ips:
            ev.source_ip = ips[0]
            if len(ips) > 1:
                # Sin estructura no se puede afirmar cuál es el destino: se
                # conservan todas sin inventar una dirección al flujo.
                ev.attributes["ips_detectadas"] = ips
        return ev
