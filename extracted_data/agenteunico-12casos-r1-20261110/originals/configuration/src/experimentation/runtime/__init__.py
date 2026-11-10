"""Capa de ejecución del experimento (Fase C del plan de continuación).

Identidad, configuración congelada, persistencia, telemetría y exportación.
**Ninguno de estos módulos ejecuta NODEX ni llama a un modelo**: definen
dónde va cada cosa y con qué garantías. Los runners viven aparte.
"""

from src.experimentation.runtime.configuracion import (
    ConfiguracionCongelada,
    congelar,
    detectar_d11,
)
from src.experimentation.runtime.exportacion import COLUMNAS, fila
from src.experimentation.runtime.identidad import IdentidadCorrida
from src.experimentation.runtime.persistencia import (
    guardar,
    preparar_estructura,
    rutas,
    ya_existe,
)
from src.experimentation.runtime.telemetria import LlamadaLlm, Telemetria

__all__ = [
    "COLUMNAS",
    "ConfiguracionCongelada",
    "IdentidadCorrida",
    "LlamadaLlm",
    "Telemetria",
    "congelar",
    "detectar_d11",
    "fila",
    "guardar",
    "preparar_estructura",
    "rutas",
    "ya_existe",
]
