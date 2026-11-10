"""Runners de las arquitecturas comparadas (Fase C / Fase D).

Un runner corre **una** arquitectura sobre **un** caso y devuelve su estado
final. No calcula métricas, no ve el ground truth y no decide qué casos se
corren: eso es del orquestador.

| Runner | Rol | LLM | Repeticiones |
|---|---|---|---|
| `nodex` | sistema completo, foco de la campaña | sí | N=3 |
| `baseline` | comparación determinística | no | N=1 |
| `gemini_externo` | pseudo-ablación, procedimiento aparte | sí | N=3 |

**Importar este paquete no ejecuta nada.** Los imports de `src.pipeline`,
`src.llm` y el preprocesamiento están diferidos dentro de cada función.

## Qué pasó con el agente único

Había un `agente_unico.py` que replicaba el contexto de NODEX y le daba el
mismo acceso al RAG, para aislar la arquitectura como única variable. Se
retiró el 7-oct-2026 por dos decisiones:

- La comparación del proyecto es una **pseudo-ablación** declarada, no una
  ablación de una variable: NODEX completo (arquitectura + RAG +
  herramientas + coordinación) frente a Gemini usado directamente con un
  solo prompt. Darle RAG al agente único contradecía ese diseño.
- La pseudo-ablación se hace con una **instancia separada de Gemini**
  (`gemini_externo.py`), no con el `src/single_agent.py` integrado.

`src/single_agent.py` sigue existiendo en el sistema y no se toca; esta capa
simplemente no lo usa como implementación experimental principal.
"""

from src.experimentation.runners import baseline, gemini_externo, nodex

__all__ = ["baseline", "gemini_externo", "nodex"]
