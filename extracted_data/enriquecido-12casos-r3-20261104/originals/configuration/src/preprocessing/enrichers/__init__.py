"""Enriquecedores de producto del preprocesamiento v2 (Fase 6 del plan).

Son OPCIONALES: una fuente sin perfil completa el flujo igual, con menos
campos. El orden importa solo para desempatar cuando dos enriquecedores
dicen aplicar al mismo evento; en la práctica sus condiciones son
excluyentes.
"""

from src.preprocessing.enrichers.auth import AuthEnricher
from src.preprocessing.enrichers.base import Enricher
from src.preprocessing.enrichers.bgl import BglEnricher
from src.preprocessing.enrichers.hdfs import HdfsEnricher
from src.preprocessing.enrichers.zeek import ZeekEnricher

ENRICHERS: tuple[Enricher, ...] = (
    HdfsEnricher(),
    BglEnricher(),
    ZeekEnricher(),
    # Último: su condición es la más laxa (reconoce por texto del
    # mensaje), así que no debe ganarle a un perfil de formato conocido.
    AuthEnricher(),
)

ENRICHERS_POR_NOMBRE: dict[str, Enricher] = {e.nombre: e for e in ENRICHERS}

__all__ = [
    "ENRICHERS",
    "ENRICHERS_POR_NOMBRE",
    "AuthEnricher",
    "BglEnricher",
    "Enricher",
    "HdfsEnricher",
    "ZeekEnricher",
]
