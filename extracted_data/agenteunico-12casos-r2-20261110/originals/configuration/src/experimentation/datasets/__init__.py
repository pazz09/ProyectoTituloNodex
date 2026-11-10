"""Preparación de datasets y casos (Fase 2 del plan).

Divide la responsabilidad en tres capas, para que el defecto que tuvo el
evaluador anterior no pueda repetirse:

1. `inventario`  — qué archivo se usó, con hash. Sin esto, un resultado no
   se puede reproducir ni auditar.
2. `agrupacion`  — cómo se agrupan las líneas en unidades indivisibles
   (bloque en HDFS, ventana en BGL, sesión en UWF). La unidad es lo que
   **no** puede quedar partido entre desarrollo y evaluación.
3. `generador`   — cómo se arman los casos a partir de los grupos, con
   prevalencia solicitada y **prevalencia efectiva registrada aparte**.

El generador anterior (`src/tools/eval_deteccion.py`) mezclaba las tres y
por eso arrastraba tres problemas que acá se corrigen explícitamente:

- Atribuía cada línea al **primer** `blk_` que encontraba (`re.search`),
  perdiendo la asociación en las líneas que mencionan varios. En
  `HDFS_2k.log` eso afecta a 266 de 2000 líneas (13,3%), dos de ellas con
  100 bloques.
- Reutilizaba bloques normales entre lotes, de modo que el mismo dato
  aparecía en varias mediciones.
- Forzaba `max(1, ...)` positivos por lote, así que una prevalencia
  solicitada de 3,1% se volvía 5% efectiva sin que quedara registrado.
"""

from src.experimentation.datasets.agrupacion import (
    GrupoDataset,
    LineaFuente,
    agrupar_bgl,
    agrupar_hdfs,
)
from src.experimentation.datasets.generador import (
    EspecificacionCasos,
    ResultadoGeneracion,
    generar_casos,
)
from src.experimentation.datasets.inventario import (
    FUENTES_DECLARADAS,
    ArchivoInventariado,
    inventariar,
)
from src.experimentation.datasets.particion import particionar_grupos

__all__ = [
    "ArchivoInventariado",
    "EspecificacionCasos",
    "FUENTES_DECLARADAS",
    "GrupoDataset",
    "LineaFuente",
    "ResultadoGeneracion",
    "agrupar_bgl",
    "agrupar_hdfs",
    "generar_casos",
    "inventariar",
    "particionar_grupos",
]
