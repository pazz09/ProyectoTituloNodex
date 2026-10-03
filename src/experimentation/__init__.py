"""Espacio experimental de NODEX (preparación, sin ejecución).

Capa separada del código productivo (`src/preprocessing/`, `src/agents/`,
`src/graph/`) que existe para **evaluar** el sistema, no para analizar logs
en producción. Nada de acá forma parte del camino que recorre un lote
cuando un analista sube un archivo en la interfaz.

Reutiliza lo que ya existe en vez de reimplementarlo:

- `src/preprocessing/` para interpretar logs (no hay un segundo
  preprocesamiento ni un grafo paralelo).
- `src/tools/provenance.py` para la procedencia de cada corrida.
- `src/tools/eval_deteccion.py` para la construcción de lotes y las
  métricas de detección que ya estaban probadas.

Estado: **preparación**. Los módulos de este paquete se escriben y revisan
estáticamente; su ejecución queda pendiente de una autorización posterior
de pruebas (ver `docs/experimentacion/estado_preparacion.md`).
"""
