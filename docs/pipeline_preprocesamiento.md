# Pipeline de preprocesamiento

Referencia técnica del preprocesamiento heterogéneo (esquema v2, único motor
del sistema desde el 23-sep-2026 — ver "Preprocesamiento" en el README para
la vista general). Este documento detalla el flujo completo, quién es
responsable de qué, el contrato entre el esquema v2 y el v1 que siguen
esperando los agentes, y qué parte de todo esto llega al prompt del LLM.

## Flujo completo

```
texto crudo
  │
  ▼
[1] ingesta            preprocesar()                    src/preprocessing/pipeline.py
  │  límite de tamaño (LOG_MAX_FILE_BYTES) -- rechaza, no trunca
  ▼
[2] segmentación       segmentar()                       src/preprocessing/segmentation.py
  │  línea física → registro lógico (RawRecord)
  │  límite de eventos (LOG_MAX_EVENTS) -- rechaza, no trunca
  ▼
[3] detección +        detectar_y_decodificar()          src/preprocessing/detection.py
    decodificación     (+ decoders/*.py)
  │  RawRecord → NormalizedEvent, agrupados en RecordSegment
  ▼
[4] enriquecimiento    ENRICHERS                          src/preprocessing/enrichers/*.py
  │  NormalizedEvent enriquecido in-place + GroundTruthRecord (canal aparte)
  ▼
  PreprocessingResult (events, segments, warnings, ground_truth, config)
  │
  ├──▶ [5a] agregar_v2()      src/preprocessing/aggregation.py   resumen v2
  │
  └──▶ [5b] derivar_v1(resultado, v2)                             resumen v1
         (usa el v2 ya calculado, no vuelve a recorrer los eventos)
              │
              ▼
       [6] acotamiento para el prompt (solo lo que ve el LLM)
           acotar_resumen_para_prompt()      src/tools/resumen_prompt.py
           contexto_preprocesamiento()       src/preprocessing/prompt_context.py
```

Punto de entrada único: `src/tools/aggregation.py::preprocesar_lote(raw)`
ejecuta `preprocesar()` **una sola vez** por lote y devuelve
`(resultado, v2, resumen_v1)` — los tres derivados de la misma pasada.
`aggregate_logs(raw)` es el mismo camino cuando solo hace falta el
resumen v1 (evaluación por lotes, `log_runner.py`, tests). Antes del cierre
de auditoría del 23-sep-2026, `preprocesar()` corría dos veces por lote
(hallazgo A1) — ver el historial de commits `fase1:*` en la rama
`cierre-auditoria` para el detalle de esa corrección.

## Actores y responsabilidades

| Etapa | Módulo | Responsabilidad | No hace |
|---|---|---|---|
| Ingesta | `preprocesar()` | Valida tamaño, arma la configuración efectiva de la corrida | No decide formato |
| Segmentación | `segmentar()` | Separa línea física de registro lógico (un stack trace de 30 líneas es un evento, no 30) | No decodifica contenido |
| Detección + decodificación | `detectar_y_decodificar()` + `decoders/*.py` | Elige el decoder por confianza (7 decoders: JSON, CSV, Syslog, CEF, LEEF, clave-valor, texto), en modo `batch`/`chunked`/`line`/`hybrid` (recomendado) | No interpreta semántica de producto (eso es el enriquecedor) |
| Enriquecimiento | `enrichers/*.py` (HDFS, BGL, Zeek, auth) | Añade contexto específico del producto (severidad, categoría, outcome) y **separa el ground truth hacia un canal aparte** | Nunca traduce una etiqueta del dataset en una feature observada |
| Agregación | `agregar_v2()` / `derivar_v1()` | Una sola pasada sobre los eventos ya decodificados/enriquecidos; produce el resumen genérico (v2) y el compatible (v1) | No vuelve a tocar el texto crudo |
| Acotamiento | `acotar_resumen_para_prompt()` / `contexto_preprocesamiento()` | Reduce lo que ve el LLM, con una allowlist explícita y un presupuesto de caracteres | No decide el diagnóstico -- solo qué contexto recibe quien lo hace |

Ningún agente LLM participa en ninguna de estas etapas: todo el
preprocesamiento es determinístico (mismo input, mismo output, sin
llamadas a la API de Gemini).

## Contrato v2 → v1

`agregar_v2()` calcula el resumen genérico **una sola vez** por lote, con
18 claves (ver `test_contrato_de_esquema_v2` en
`tests/test_golden_heterogeneos.py` para el contrato exacto, con tipos):

```
schema_version, total_lineas_fisicas, total_eventos,
decoder_distribution, product_distribution, vendor_distribution,
version_distribution, protocol_distribution, profile_distribution,
severity_distribution, event_categories, event_outcomes,
entities, time_window, parsing, segments, warnings, samples
```

`derivar_v1(resultado, resumen_v2)` traduce ese mismo agregado al esquema
que los agentes, el historial y el informe en PDF siguen esperando
(`formato_detectado`, `total_lineas`, `servicios`, `por_ip`, `eventos`,
`cronologia`, ...) — nunca vuelve a parsear el raw ni a recorrer los
eventos por su cuenta; todo sale de `v2`. Es la garantía de que el
resumen v1 y los metadatos v2 (ver más abajo) describen exactamente el
mismo lote, nunca dos parseos que podrían divergir.

`_metadatos_desde_v2()` (`src/pipeline.py`) arma el tercer derivado: los
metadatos de preprocesamiento que se guardan en el estado del grafo
(`preprocessing_metadata`). Trae, además de lo que ya traía v1, los
campos que M1 (Fase 4 del cierre de auditoría) propagó por primera vez:
`profile_distribution`, `event_outcomes`, `entities` (ricas, no solo el
conteo), `time_window`, y las tres distribuciones nuevas de M1
(`vendor_distribution`, `version_distribution`, `protocol_distribution`).

## Qué llega al prompt del Triage, y qué no

El LLM del Triage recibe dos textos separados, cada uno con su propio
mecanismo de acotamiento:

### 1. El resumen del lote (`acotar_resumen_para_prompt()`)

Acota el desglose por IP: incluye las `TOP_N_IPS_PROMPT` (default 20) IPs
más activas, más cualquier IP con reputación sospechosa/maliciosa aunque
tenga poca actividad, y agrega el resto en un solo campo `ips_resumidas`.
Existe porque el costo en tokens de este resumen escala con la cantidad de
IPs **distintas** del lote, no con las líneas de log (HDFS con 202 IPs
disparó 58 289 tokens antes de que existiera este acotamiento).

También excluye explícitamente (`_CLAVES_FUERA_DEL_PROMPT` en
`src/tools/resumen_prompt.py`): `cronologia`, `cronologia_omitidos`,
`entidades`. La cronología **no puede** ir al prompt: sus entradas
incluyen un extracto del registro crudo, y en BGL la etiqueta de
anomalía del dataset es el primer token de la línea -- mandarla reabriría
la fuga de ground truth que cerró un hallazgo anterior del proyecto.
`entidades` se excluye por costo, no por fuga: es una vista corta de
`por_ip`, que el prompt ya recibe acotado.

### 2. El contexto de preprocesamiento (`contexto_preprocesamiento()`)

Allowlist explícita y cerrada (Fase 2 del cierre de auditoría,
23-sep-2026) -- esta función **solo lee**:

- Esquema y totales (`total_eventos`, `total_lineas_fisicas`)
- Distribución de decoders, cuenta de segmentos
- Productos reconocidos, perfiles de enriquecimiento aplicados
- Severidad declarada por el log, categorías de evento
- Cobertura del parsing (con una advertencia explícita si es baja)
- Advertencias graves de parsing (máximo 3)
- Muestras normalizadas y truncadas (máximo 5, 300 caracteres cada una) --
  se omiten por completo si el lote trae ground truth embebido en la línea

**Nunca lee** `time_window`, `entities`, `event_outcomes` ni las
distribuciones de vendor/version/protocol que M1 agregó al estado --
existen en `preprocessing_metadata` para el reporte y la trazabilidad,
pero deliberadamente no pasan por la allowlist. La ventana temporal en
particular queda excluida por la misma razón que la cronología: comparte
la fuente que reabrió la fuga de ground truth en el pasado. Que un campo
esté en el estado no implica que esté en el prompt --
`tests/test_triage_contexto_v2.py::test_los_campos_nuevos_de_m1_no_llegan_al_prompt`
lo prueba explícitamente.

`CONTEXTO_PREPROCESAMIENTO_MAX_CHARS` (default 2000) es el presupuesto
de este segundo texto. Si se supera, se recorta por prioridad: primero
las muestras y las distribuciones (listas que pueden crecer), nunca los
conteos globales, la cobertura ni las advertencias -- ver
`contexto_preprocesamiento()` en `src/preprocessing/prompt_context.py`
para el algoritmo exacto.

**Límite real de este acotamiento**: controla qué llega al prompt del
Triage, pero **no** existe ningún mecanismo que impida que los otros
cuatro agentes (selector, mitigación, validador, auditor) reciban
contexto adicional si en el futuro se los conecta a `preprocessing_
metadata` -- hoy no lo hacen, pero la allowlist vive en una función,
no en una garantía estructural del estado.

## `decoder` vs. producto/perfil: por qué HDFS y BGL son `decoder=text` con 100% de cobertura

Son dos dimensiones distintas del mismo evento, y confundirlas es el error
más fácil de cometer leyendo un resumen v2:

- **`decoder`** responde "¿qué SINTAXIS genérica tiene esta línea?" -- JSON,
  CSV, Syslog, CEF, LEEF, clave-valor, o ninguna de las anteriores
  (`text`). Es estructural, no sabe nada de HDFS ni de BGL.
- **`product`/`attributes["perfil"]`** responde "¿qué PRODUCTO reconozco en
  esta línea?" -- lo decide un enriquecedor (`enrichers/hdfs.py`,
  `enrichers/bgl.py`, `enrichers/zeek.py`, `enrichers/auth.py`), con un
  patrón propio del producto, DESPUÉS de que el decoder ya corrió.

HDFS y BGL tienen un formato de columnas fijas separadas por espacios
(`081109 203615 148 INFO dfs.DataNode...` / `- 1117838570 2005.06.03
R02-M1-N0...`) que **ningún decoder genérico reconoce** -- no es JSON, no
es CSV, no tiene el `<PRI>` de syslog. El decoder que gana por descarte es
`text`. Pero el enriquecedor de HDFS/BGL sí tiene un patrón propio para
esas columnas, y de ahí extrae timestamp, nodo, servicio, severidad y
mensaje -- el evento queda tan interpretado como uno que sí matcheó un
decoder genérico, solo que por un camino distinto.

La cobertura (`NormalizedEvent.es_fallback`, en
`src/preprocessing/models.py`) lo refleja: un evento es "fallback" (no
contó para la cobertura) solo si **ni el decoder ni el enriquecedor**
lo entendieron -- `decoder == "text" and product is None`. HDFS y BGL
tienen `decoder="text"` pero `product` poblado (`"HDFS"`/`"BlueGene/L"`),
así que no son fallback: de ahí la cobertura del 100% que a primera
vista contradice ver `decoder_distribution: {"text": 2000}` en el mismo
resumen. Antes de esta distinción (medido el 4-sep-2026), medir cobertura
solo por decoder le daba 0% a un lote completamente interpretado, y el
contexto que recibía el Triage llegaba a advertir "el lote no pudo
interpretarse" sobre datos que sí se habían entendido.

**Consecuencia práctica al leer un resumen**: `decoder_distribution` solo
dice cómo la SINTAXIS de las líneas fue reconocida; para saber qué
PRODUCTOS trae el lote hay que mirar `product_distribution` o
`profile_distribution` -- son las claves que de verdad importan para
juzgar si el preprocesamiento entendió el contenido, no solo la forma.

## Configuración

Ver "Configuración" en el README para la tabla completa con el efecto
real de cada variable, incluida `LOG_PRESERVE_RAW` (persistencia y
exportación, no el LLM) y el resto de las variables `LOG_*`.
