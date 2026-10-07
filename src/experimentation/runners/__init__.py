"""Runners de las tres arquitecturas (Fase C del plan de continuación).

Un runner corre **una** arquitectura sobre **un** caso y devuelve su estado
final. No calcula métricas, no ve el ground truth y no decide qué casos se
corren: eso es del orquestador.

Las tres leen el caso con la misma función y sobre el mismo archivo. Si
recibieran entradas distintas, la comparación entre arquitecturas mediría la
entrada y no la arquitectura.

| Runner | Consume LLM | Repeticiones | D2/D3 |
|---|---|---|---|
| `nodex` | sí, 5 nodos + bucles | N=3 en la campaña | pendientes de D-11 |
| `agente_unico` | sí, 1 llamada | N=3 en la campaña | pendientes de D-11 |
| `baseline` | no | N=1: es determinístico | no aplica nunca |

**Importar este paquete no ejecuta nada.** Los imports de `src.pipeline`,
`src.llm` y el preprocesamiento están diferidos dentro de cada función, para
que el código se pueda revisar sin arrastrar el sistema.
"""

from src.experimentation.runners import agente_unico, baseline, nodex

__all__ = ["agente_unico", "baseline", "nodex"]
