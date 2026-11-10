"""Decoder de registros `clave=valor` (Fase 4 del plan).

Formato habitual en firewalls (Fortinet, pfSense), en logs de aplicación
estructurados con logfmt y en la parte de extensiones de CEF. Admite
valores entre comillas con espacios y un prefijo de texto antes del primer
par, que es lo que producen los equipos que anteponen un encabezado.

    date=2024-01-02 time=10:00:00 srcip=10.0.0.1 action=deny msg="acceso denegado"
"""

import re

from src.preprocessing.decoders.base import Decoder
from src.preprocessing.models import NormalizedEvent
from src.preprocessing.normalization import mapear_campos
from src.preprocessing.segmentation import RawRecord

# clave=valor, con valor entre comillas o hasta el próximo espacio.
_PAR_RE = re.compile(r'([A-Za-z_][\w.\-]*)=("([^"]*)"|\'([^\']*)\'|[^\s]*)')

# Mínimo de pares para considerar que el registro ES clave=valor y no un
# texto que casualmente contiene un `=`.
_MIN_PARES = 2


def extraer_pares(texto: str) -> dict:
    pares: dict = {}
    for m in _PAR_RE.finditer(texto):
        clave = m.group(1)
        valor = m.group(3) if m.group(3) is not None else (
            m.group(4) if m.group(4) is not None else m.group(2))
        if clave not in pares:
            pares[clave] = valor
    return pares


class KeyValueDecoder(Decoder):
    nombre = "key_value"

    def detectar(self, texto: str, contexto: dict | None = None) -> float:
        linea = texto.split("\n", 1)[0]
        pares = extraer_pares(linea)
        if len(pares) < _MIN_PARES:
            return 0.0
        # Cuánto del registro está efectivamente cubierto por pares: un
        # texto largo con dos pares sueltos no es un registro clave=valor.
        cubierto = sum(len(k) + len(str(v)) + 1 for k, v in pares.items())
        proporcion = min(cubierto / max(len(linea), 1), 1.0)
        if proporcion >= 0.6:
            return min(0.9, 0.5 + proporcion / 2)
        return 0.35

    def decodificar(self, registro: RawRecord,
                    contexto: dict | None = None) -> NormalizedEvent:
        linea = registro.raw.split("\n", 1)[0]
        pares = extraer_pares(linea)
        confianza = self.detectar(registro.raw, contexto)
        canonicos, atributos = mapear_campos(
            pares, max_no_mapeados=(contexto or {}).get("max_no_mapeados"))
        mensaje = canonicos.pop("message", None) or linea
        ev = self._evento_base(registro, mensaje, confianza)
        for campo, valor in canonicos.items():
            setattr(ev, campo, valor)
        ev.attributes.update(atributos)
        return ev
