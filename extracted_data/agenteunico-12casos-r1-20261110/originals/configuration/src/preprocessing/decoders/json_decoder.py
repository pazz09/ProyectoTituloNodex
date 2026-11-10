"""Decoder JSON / JSON Lines (Fase 4 del plan).

Cubre el formato más común de las aplicaciones modernas, contenedores y
servicios cloud. Acepta tanto un objeto por línea (JSON Lines) como un
objeto repartido en varias líneas, que la segmentación ya reunió en un
único registro.

Aplana los objetos anidados con notación de punto (`user.name`), porque los
sinónimos del esquema normalizado están definidos en esos términos y
porque un diccionario anidado dentro de `attributes` es mucho menos útil
para el prompt del LLM.
"""

import json

from src.preprocessing.decoders.base import Decoder
from src.preprocessing.models import NormalizedEvent, ParsingWarning
from src.preprocessing.normalization import mapear_campos
from src.preprocessing.segmentation import RawRecord

_PROFUNDIDAD_MAX = 6


def _aplanar(objeto: dict, prefijo: str = "", profundidad: int = 0) -> dict:
    plano: dict = {}
    for clave, valor in objeto.items():
        nombre = f"{prefijo}{clave}"
        if isinstance(valor, dict) and profundidad < _PROFUNDIDAD_MAX:
            plano.update(_aplanar(valor, f"{nombre}.", profundidad + 1))
        elif isinstance(valor, (list, tuple)):
            # Las listas se conservan tal cual: aplanarlas por índice
            # generaría claves sin significado (`tags.0`, `tags.1`).
            plano[nombre] = list(valor)
        else:
            plano[nombre] = valor
    return plano


class JsonDecoder(Decoder):
    nombre = "json"

    def detectar(self, texto: str, contexto: dict | None = None) -> float:
        t = texto.strip()
        if not (t.startswith("{") and t.endswith("}")):
            return 0.0
        try:
            objeto = json.loads(t)
        except ValueError:
            # Parece JSON pero no lo es: confianza baja, no cero, para que
            # el modo híbrido lo reprocese en vez de darlo por bueno.
            return 0.15
        return 1.0 if isinstance(objeto, dict) else 0.3

    def decodificar(self, registro: RawRecord,
                    contexto: dict | None = None) -> NormalizedEvent:
        texto = registro.raw.strip()
        try:
            objeto = json.loads(texto)
        except ValueError as e:
            ev = self._evento_base(registro, texto, 0.15)
            ev.warnings.append(ParsingWarning(
                codigo="json_invalido",
                mensaje=f"No se pudo parsear como JSON: {e}",
                line_start=registro.line_start,
            ))
            return ev

        if not isinstance(objeto, dict):
            ev = self._evento_base(registro, texto, 0.3)
            ev.attributes["json_raiz"] = objeto
            ev.warnings.append(ParsingWarning(
                codigo="json_no_es_objeto",
                mensaje="El JSON no es un objeto; se conserva sin mapear.",
                severidad="info",
                line_start=registro.line_start,
            ))
            return ev

        plano = _aplanar(objeto)
        canonicos, atributos = mapear_campos(plano)
        mensaje = canonicos.pop("message", None) or texto
        ev = self._evento_base(registro, mensaje, 1.0)
        for campo, valor in canonicos.items():
            setattr(ev, campo, valor)
        ev.attributes.update(atributos)
        return ev
