# Informe de cierre de la auditoría técnica (23-sep-2026)

> Borrador vivo, actualizado fase por fase. La versión final (con la tabla
> completa de hallazgos, resultados de la suite y métricas) se cierra en la
> Fase 7. Hasta entonces, este documento registra hechos confirmados para no
> depender de la memoria de la conversación entre fases.

## Hallazgos

### A1 — Preprocesamiento único por lote

**Estado: resuelto.**

- Commits: `fase1: preprocesamiento único por lote en pipeline y baseline`
  (`a757fb3`), `fase1: propagar fallas de preprocesamiento con mensaje
  claro (web/CLI)` (`1bf988b`), ambos en `cierre-auditoria`.
- `preprocesar()` corre una sola vez por lote (`preprocesar_lote()`, en
  `src/tools/aggregation.py`); `derivar_v1(resultado, v2)` se llama con
  ambos explícitos en todas las rutas (pipeline y baseline).
- **Corrección sobre el impacto en las muestras (LOG_MAX_RAW_SAMPLES).**
  Se midió mal en un primer momento: el cálculo de `agregar_v2()` que se
  eliminó (el que corría dentro de `derivar_v1()` sin `v2` explícito)
  calculaba `samples`, pero ese campo nunca llegaba a ningún consumidor
  (`derivar_v1()` no lo lee). El único `agregar_v2()` cuyo `samples` sí
  llegaba al prompt (vía `_metadatos_preprocesamiento()`, hoy
  `_metadatos_desde_v2()`) ya usaba `LOG_MAX_RAW_SAMPLES` explícito desde
  antes de la Fase 1. **Conclusión: el número de muestras que ven los
  agentes es el mismo antes y después de la Fase 1 (20 en ambos casos,
  valor por defecto sin sobreescribir en `.env`). La Fase 1 no cambia el
  contexto del triage — las métricas de la Fase 6 SÍ son comparables 1:1
  con las históricas en este punto.**
- Camino productivo revisado (web, API, CLI): la web ya emitía un evento
  de error genérico ante un fallo de `preprocesar()`, ahora con mensaje
  propio (`PreprocesamientoError`) en vez del prefijo genérico. El CLI
  (`log_runner.py`) no tenía ningún try/except — corregido, termina con
  mensaje claro por stderr y código de salida 1. El evaluador
  (`eval_deteccion.py`) tiene el mismo problema, pendiente — se corrige
  como parte de la Fase 6 (ver más abajo).
- Suite: 499/499 tras el cierre de A1.

### A2 — Contexto v2 en la primera pasada del triage

**Estado: resuelto.**

- Commit: `fase2: contexto v2 en la primera pasada del triage` (`128bd86`),
  en `cierre-auditoria`. Ajustes de prioridad de recorte y numeros
  concretos: commit pendiente de confirmar hash (ver más abajo).
- `contexto_preprocesamiento()` (`src/preprocessing/prompt_context.py`) se
  adjunta ahora en AMBAS pasadas del triage, no solo en la segunda. De
  paso se le agregaron los campos que la allowlist mínima pedía y que
  faltaban: severidad, categorías de evento y perfiles de enriquecimiento
  (`agregar_v2` ya los calculaba, no se leían).
- Nueva `CONTEXTO_PREPROCESAMIENTO_MAX_CHARS` (default 2000, configurable
  por variable de entorno). Prioridad de recorte confirmada: se quitan
  primero las muestras y las distribuciones (listas); los conteos
  globales, la cobertura del parsing y las advertencias de parsing NUNCA
  se recortan.
- Incluye muestras normalizadas y truncadas (hasta 5, 300 caracteres cada
  una) en ambas pasadas, tal como pedía la allowlist mínima del documento
  de cierre.
- **Esta fase SÍ cambia el contexto que ve el triage** (a diferencia de
  A1): la primera pasada ahora recibe información que antes no tenía.
  Las métricas de la Fase 6 se presentan como "antes vs. después del
  cierre de auditoría", no como comparables 1:1 con las históricas.
- Números medidos con datos reales (`data/logs/HDFS_2k.log`,
  `data/logs/BGL_2k.log`), vía el pipeline real
  (`pipeline._preparar_estado_inicial`), tokens estimados con la
  heurística ~4 caracteres/token (no es un conteo del tokenizer real de
  Gemini, que no está disponible sin cuota de API):

  | Dataset  | `contexto_preprocesamiento()` | 1ª pasada (antes → después) | 2ª pasada (sin cambios) |
  |---|---|---|---|
  | HDFS_2k (202 IPs) | 484 car. (~121 tok.) | 7 449 → 7 935 car. (~1 862 → ~1 984 tok.), +6.5% | 8 137 car. (~2 034 tok.) |
  | BGL_2k (11 IPs)   | 541 car. (~135 tok.) | 3 732 → 4 275 car. (~933 → ~1 069 tok.), +14.5% | 4 477 car. (~1 119 tok.) |

  `contexto_preprocesamiento()` usa ~24-27% del presupuesto de 2000
  caracteres en ambos datasets — margen amplio incluso en el caso más
  pesado medido (HDFS, 202 IPs).
- Pruebas: contexto en primera pasada, ausencia de contexto sin
  metadatos, presupuesto no superado con HDFS real, ausencia de ground
  truth en ambos prompts con BGL real (etiquetas reales del archivo, no
  sintéticas), allowlist (campos sospechosos no leídos), recorte por
  prioridad (núcleo protegido) y recorte ciego solo como último recurso.
- Suite: 506/506 tras el commit `128bd86`; pendiente de re-confirmar tras
  el ajuste de prioridad de recorte.

### A3 — `LOG_PRESERVE_RAW`

**Estado: en curso (Opción A, aprobada).**

(se completa al cerrar la Fase 3)

## Evaluador (`eval_deteccion.py`)

Decisión (23-sep-2026): un fallo de preprocesamiento en un lote no debe
abortar la corrida completa ni saltarse en silencio. Se registra como
error en los resultados (con su mensaje), se excluye explícitamente de la
matriz de confusión, y se informa cuántos lotes fallaron. Se implementa
como parte del cierre (no se espera a la Fase 6 para el código, solo para
correrla con datos reales).
