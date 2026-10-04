"""Conocimiento aislado del experimento (Fase 3 del plan).

Separa dos cosas que no pueden compartir almacenamiento:

- **Conocimiento**: el catálogo MITRE ATT&CK embebido, que el agente puede
  consultar. Es información pública del dominio.
- **Referencias**: el ground truth de los casos, que solo ve el evaluador.

Y una tercera que tampoco debe mezclarse: la **memoria de corridas previas**
(`host_history`, `error_memory`, correcciones de feedback). La base de
producción la acumula legítimamente, pero dentro de un experimento
contamina: un caso reservado cuyo host ya fue analizado antes le daría al
sistema información que no vino del caso.
"""

from src.experimentation.knowledge.aislamiento import (
    ConfiguracionAislada,
    VARIABLES_AISLAMIENTO,
    configuracion_experimental,
)
from src.experimentation.knowledge.inventario import (
    COLECCIONES_CONOCIMIENTO,
    COLECCIONES_MEMORIA,
    inventariar_conocimiento,
)

__all__ = [
    "COLECCIONES_CONOCIMIENTO",
    "COLECCIONES_MEMORIA",
    "ConfiguracionAislada",
    "VARIABLES_AISLAMIENTO",
    "configuracion_experimental",
    "inventariar_conocimiento",
]
