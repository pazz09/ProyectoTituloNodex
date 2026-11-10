"""Decodificadores estructurales del preprocesamiento v2 (Fase 4 del plan).

El orden de `DECODERS` importa solo para desempatar confianzas idénticas:
van primero los formatos con marcador inequívoco (CEF y LEEF empiezan por
su propio nombre), después los estructurales generales, y `TextDecoder`
queda fuera de la lista porque es el fallback obligatorio, no un candidato
que compita por confianza.
"""

from src.preprocessing.decoders.base import Decoder
from src.preprocessing.decoders.cef_decoder import CefDecoder
from src.preprocessing.decoders.csv_decoder import CsvDecoder, detectar_cabecera
from src.preprocessing.decoders.json_decoder import JsonDecoder
from src.preprocessing.decoders.key_value_decoder import KeyValueDecoder
from src.preprocessing.decoders.leef_decoder import LeefDecoder
from src.preprocessing.decoders.syslog_decoder import SyslogDecoder
from src.preprocessing.decoders.text_decoder import TextDecoder

# Candidatos que compiten por confianza, en orden de desempate.
DECODERS: tuple[Decoder, ...] = (
    CefDecoder(),
    LeefDecoder(),
    JsonDecoder(),
    CsvDecoder(),
    SyslogDecoder(),
    KeyValueDecoder(),
)

# Fallback obligatorio: acepta cualquier registro y nunca falla.
DECODER_TEXTO = TextDecoder()

DECODERS_POR_NOMBRE: dict[str, Decoder] = {
    d.nombre: d for d in (*DECODERS, DECODER_TEXTO)
}

__all__ = [
    "DECODERS",
    "DECODERS_POR_NOMBRE",
    "DECODER_TEXTO",
    "CefDecoder",
    "CsvDecoder",
    "Decoder",
    "JsonDecoder",
    "KeyValueDecoder",
    "LeefDecoder",
    "SyslogDecoder",
    "TextDecoder",
    "detectar_cabecera",
]
