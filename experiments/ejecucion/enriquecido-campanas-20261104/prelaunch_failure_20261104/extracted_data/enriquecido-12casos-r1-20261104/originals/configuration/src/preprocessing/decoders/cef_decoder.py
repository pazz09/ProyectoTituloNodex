"""Decoder CEF — Common Event Format, de ArcSight (Fase 4 del plan).

Es uno de los dos formatos estándar de intercambio con SIEM, así que
aparece en cualquier integración con producto comercial.

    CEF:0|Vendor|Product|1.0|100|Nombre del evento|5|src=10.0.0.1 dst=10.0.0.2

Los siete campos de cabecera van separados por `|`, con `\\|` para escapar
una barra dentro de un campo. Las extensiones son pares `clave=valor` y se
delegan al decoder correspondiente, que ya sabe interpretarlas.
"""

import re

from src.preprocessing.decoders.base import Decoder
from src.preprocessing.decoders.key_value_decoder import extraer_pares
from src.preprocessing.models import NormalizedEvent, ParsingWarning
from src.preprocessing.normalization import mapear_campos
from src.preprocessing.segmentation import RawRecord

_CEF_PREFIJO_RE = re.compile(r"^CEF:\s*(\d+)\s*\|", re.IGNORECASE)

# Severidad CEF: 0-3 baja, 4-6 media, 7-8 alta, 9-10 muy alta.
_ESCALA_SEVERIDAD = ((3, "low"), (6, "medium"), (8, "high"), (10, "very-high"))


def _partir_cabecera(texto: str) -> list[str]:
    """Corta por `|` respetando `\\|` escapado."""
    partes: list[str] = []
    actual = ""
    escapado = False
    for ch in texto:
        if escapado:
            actual += ch
            escapado = False
            continue
        if ch == "\\":
            escapado = True
            continue
        if ch == "|":
            partes.append(actual)
            actual = ""
            continue
        actual += ch
    partes.append(actual)
    return partes


def _severidad_textual(valor: str) -> str | None:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        return valor or None
    for tope, etiqueta in _ESCALA_SEVERIDAD:
        if n <= tope:
            return etiqueta
    return None


class CefDecoder(Decoder):
    nombre = "cef"

    def detectar(self, texto: str, contexto: dict | None = None) -> float:
        linea = texto.split("\n", 1)[0].strip()
        if not _CEF_PREFIJO_RE.match(linea):
            return 0.0
        # La cabecera son 7 campos más las extensiones.
        return 1.0 if len(_partir_cabecera(linea)) >= 7 else 0.4

    def decodificar(self, registro: RawRecord,
                    contexto: dict | None = None) -> NormalizedEvent:
        linea = registro.raw.split("\n", 1)[0].strip()
        partes = _partir_cabecera(linea)

        if len(partes) < 7:
            ev = self._evento_base(registro, linea, 0.4)
            ev.warnings.append(ParsingWarning(
                codigo="cef_cabecera_incompleta",
                mensaje=f"Se esperaban 7 campos de cabecera CEF y hay {len(partes)}.",
                line_start=registro.line_start,
            ))
            return ev

        # partes[0] es "CEF:0"; el resto son los seis campos siguientes.
        _, vendor, product, version, event_code, nombre, severidad = partes[:7]
        extensiones = "|".join(partes[7:])

        ev = self._evento_base(registro, nombre.strip() or linea, 1.0)
        ev.vendor = vendor.strip() or None
        ev.product = product.strip() or None
        ev.version = version.strip() or None
        ev.event_code = event_code.strip() or None
        ev.severity = _severidad_textual(severidad.strip())
        ev.attributes["cef_version"] = partes[0].split(":", 1)[-1].strip()

        if extensiones.strip():
            canonicos, atributos = mapear_campos(
                extraer_pares(extensiones),
                max_no_mapeados=(contexto or {}).get("max_no_mapeados"))
            # La cabecera manda sobre las extensiones: es la parte
            # estructurada del estándar.
            canonicos.pop("message", None)
            for campo, valor in canonicos.items():
                if getattr(ev, campo, None) is None:
                    setattr(ev, campo, valor)
            ev.attributes.update(atributos)
        return ev
