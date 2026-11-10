"""Adaptadores de las arquitecturas al contrato común (Fase 4).

Un adaptador traduce la salida de una arquitectura al contrato común. No
ejecuta nada: recibe un estado ya producido. Así se puede escribir y
revisar sin correr el sistema, y la ejecución queda confinada al
orquestador de la Fase 7.

Ninguno recibe el ground truth. La referencia solo la ve el evaluador.
"""

from src.experimentation.adapters.contrato_agentes import (
    CAMPOS_NUEVOS_DE_ESTADO,
    SI_NO_SE_ACTIVA,
    VERSION_CONTRATO_AGENTES,
)
from src.experimentation.adapters.nodex import (
    ResultadoAdaptacion,
    adaptar,
    dimension_final,
    preservar_estado_crudo,
)

__all__ = [
    "CAMPOS_NUEVOS_DE_ESTADO",
    "ResultadoAdaptacion",
    "SI_NO_SE_ACTIVA",
    "VERSION_CONTRATO_AGENTES",
    "adaptar",
    "dimension_final",
    "preservar_estado_crudo",
]
