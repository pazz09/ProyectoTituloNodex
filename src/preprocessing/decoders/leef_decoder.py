"""Decoder LEEF — Log Event Extended Format, de IBM QRadar (Fase 4 del plan).

El otro estándar de intercambio con SIEM, junto a CEF.

    LEEF:2.0|Vendor|Product|1.0|EventID|^|src=10.0.0.1^dst=10.0.0.2

Diferencias con CEF que importan al parsear: la cabecera tiene 5 campos
(no 6), los atributos van separados por TABULADOR en LEEF 1.0, y LEEF 2.0
admite un delimitador propio declarado como sexto campo de la cabecera
(`^` en el ejemplo), que puede venir literal o como `x09`/`\\t`.
"""

import re

from src.preprocessing.decoders.base import Decoder
from src.preprocessing.models import NormalizedEvent, ParsingWarning
from src.preprocessing.normalization import mapear_campos
from src.preprocessing.segmentation import RawRecord

_LEEF_PREFIJO_RE = re.compile(r"^LEEF:\s*(\d+(?:\.\d+)?)\s*\|", re.IGNORECASE)


def _resolver_delimitador(declarado: str) -> str:
    """LEEF 2.0 puede declarar el delimitador de atributos en la cabecera."""
    d = (declarado or "").strip()
    if not d:
        return "\t"
    if d.lower() in ("x09", "\\t", "0x09"):
        return "\t"
    return d[0]


class LeefDecoder(Decoder):
    nombre = "leef"

    def detectar(self, texto: str, contexto: dict | None = None) -> float:
        linea = texto.split("\n", 1)[0].strip()
        if not _LEEF_PREFIJO_RE.match(linea):
            return 0.0
        return 1.0 if len(linea.split("|")) >= 6 else 0.4

    def decodificar(self, registro: RawRecord,
                    contexto: dict | None = None) -> NormalizedEvent:
        linea = registro.raw.split("\n", 1)[0].strip()
        partes = linea.split("|")

        if len(partes) < 6:
            ev = self._evento_base(registro, linea, 0.4)
            ev.warnings.append(ParsingWarning(
                codigo="leef_cabecera_incompleta",
                mensaje=f"Se esperaban al menos 6 campos LEEF y hay {len(partes)}.",
                line_start=registro.line_start,
            ))
            return ev

        version_leef = partes[0].split(":", 1)[-1].strip()
        vendor, product, version, event_code = (p.strip() for p in partes[1:5])

        # LEEF 2.0: el sexto campo puede ser el delimitador declarado. Se
        # distingue por su longitud: un delimitador es un carácter o una
        # secuencia corta como "x09", nunca una lista de atributos.
        resto = partes[5:]
        delim = "\t"
        if version_leef.startswith("2") and resto and len(resto[0].strip()) <= 3 \
                and "=" not in resto[0]:
            delim = _resolver_delimitador(resto[0])
            resto = resto[1:]
        atributos_crudos = "|".join(resto)

        ev = self._evento_base(registro, event_code or linea, 1.0)
        ev.vendor = vendor or None
        ev.product = product or None
        ev.version = version or None
        ev.event_code = event_code or None
        ev.attributes["leef_version"] = version_leef

        pares: dict = {}
        for trozo in atributos_crudos.split(delim):
            if "=" in trozo:
                clave, _, valor = trozo.partition("=")
                clave = clave.strip()
                if clave and clave not in pares:
                    pares[clave] = valor.strip()

        if pares:
            canonicos, extra = mapear_campos(
                pares, max_no_mapeados=(contexto or {}).get("max_no_mapeados"))
            mensaje = canonicos.pop("message", None)
            if mensaje:
                ev.message = mensaje
            for campo, valor in canonicos.items():
                if getattr(ev, campo, None) is None:
                    setattr(ev, campo, valor)
            ev.attributes.update(extra)
        return ev
