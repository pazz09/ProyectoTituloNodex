# Plan de acción para preprocesamiento heterogéneo de logs en NODEX

## 1. Propósito del documento

Este documento define el plan de implementación para transformar el
preprocesamiento actual de NODEX en una arquitectura capaz de recibir lotes de
logs homogéneos, heterogéneos y de origen desconocido.

El plan está diseñado para ejecutarse gradualmente. Cada fase tiene objetivos,
actividades, archivos afectados, entregables, riesgos y criterios de aceptación.
No se debe iniciar una fase sin presentar los resultados de la anterior y
obtener aprobación explícita para continuar.

## 2. Objetivo general

Reemplazar el enfoque actual:

```text
Detectar dataset → seleccionar un parser → procesar todo el lote
```

por una tubería genérica y extensible:

```text
Recibir
  → segmentar registros
  → detectar estructuras
  → decodificar
  → normalizar
  → enriquecer opcionalmente
  → agregar
  → entregar un resumen al sistema multiagente
```

La solución deberá garantizar tres niveles de servicio:

1. Todo registro textual debe poder recibirse y conservarse.
2. Las estructuras conocidas deben decodificarse automáticamente.
3. Las fuentes conocidas pueden enriquecerse mediante perfiles específicos,
   pero un perfil no debe ser requisito para continuar.

Aceptar cualquier log no significa comprender perfectamente la semántica de
cualquier producto desconocido. Significa evitar el rechazo o la pérdida de
datos, extraer campos comunes cuando sea posible, conservar el contenido no
interpretado y declarar la cobertura y confianza del preprocesamiento.

## 3. Alcance

### 3.1 Incluido

- Archivos con un único formato.
- Archivos que contienen varios formatos por segmentos.
- Registros de diferentes formatos intercalados.
- JSON y JSON Lines.
- CSV, TSV y otros delimitadores configurados.
- Syslog RFC 3164 y RFC 5424.
- Registros `clave=valor`.
- CEF y LEEF.
- Texto libre como fallback.
- Eventos multilínea, como stack traces.
- Normalización a un esquema común.
- Preservación del registro original.
- Métricas de cobertura y confianza.
- Enriquecimiento opcional para HDFS, BGL y Zeek.
- Separación entre datos analizados y ground truth.
- Compatibilidad temporal con el contrato actual de `resumen_logs`.
- Adaptación de pipeline, agentes, RAG, CVE, memoria, API, interfaz y pruebas.

### 3.2 Fuera de alcance inicial

- Comprensión semántica perfecta de productos desconocidos.
- Uso de un LLM para parsear todos los registros.
- Ingesta continua desde Kafka, agentes de endpoint o SIEM externos.
- Procesamiento distribuido de millones de eventos en tiempo real.
- Reemplazo del grafo multiagente de siete nodos.
- Cambios en el propósito del diagnóstico, mitigación o auditoría final.

Estos puntos pueden abordarse posteriormente sobre la arquitectura propuesta.

## 4. Situación actual

El preprocesamiento se concentra en
[`src/tools/aggregation.py`](../src/tools/aggregation.py). Actualmente:

1. Divide el texto mediante `splitlines()`.
2. Elimina las líneas vacías.
3. Examina las primeras 50 líneas.
4. Selecciona un único adaptador para todo el lote.
5. Prueba adaptadores HDFS, BGL y CSV.
6. Usa auth-log como fallback.
7. Extrae principalmente IP, usuario u objeto, servicio, evento, intentos
   fallidos y timestamp.
8. Agrega el resultado en `resumen_logs`.

Las principales limitaciones son:

- Suposición de homogeneidad del lote.
- Asociación entre dataset y estrategia de parsing.
- Fallback auth-log aplicado a texto que puede no ser auth-log.
- Campo `usuario` reutilizado para usuarios, bloques HDFS, nodos BGL e IDs de
  flujo.
- Representación insuficiente de registros sin IP.
- Ausencia de soporte multilínea.
- Posible influencia de etiquetas del dataset en la señal entregada al
  detector.
- Falta de cobertura, confianza y advertencias de parsing.
- Firma RAG limitada a líneas, IP, servicios y eventos.

La línea base detallada está documentada en
[`docs/preprocessing_baseline.md`](preprocessing_baseline.md).

## 5. Principios de diseño

1. **Determinismo:** el preprocesamiento no utilizará LLM.
2. **No pérdida:** el registro original se conservará según límites definidos.
3. **Degradación controlada:** un registro desconocido utilizará el decoder de
   texto y no abortará el lote.
4. **Separación de responsabilidades:** segmentar, decodificar, normalizar,
   enriquecer y agregar serán operaciones distintas.
5. **Esquema explícito:** cada salida indicará su versión.
6. **Compatibilidad gradual:** el resumen v1 se mantendrá mientras existan
   consumidores que dependan de él.
7. **Ground truth aislado:** las etiquetas de evaluación no serán visibles al
   detector.
8. **Observabilidad:** se informará cobertura, confianza, fallbacks, descartes y
   advertencias.
9. **Control de volumen:** se limitarán eventos, muestras, campos no mapeados y
   contenido enviado al LLM.
10. **Extensibilidad:** nuevos formatos y productos se agregarán como módulos,
    sin modificar el núcleo de agregación.

## 6. Arquitectura objetivo

```text
Archivo / lote
      │
      ▼
Ingesta y validación
      │
      ▼
Segmentación de registros
      │
      ▼
Detección híbrida
      │
      ├── JSON / JSONL
      ├── CSV / TSV
      ├── Syslog
      ├── CEF / LEEF
      ├── clave=valor
      └── texto libre
      │
      ▼
Eventos normalizados
      │
      ├── Enriquecedor HDFS
      ├── Enriquecedor BGL
      ├── Enriquecedor Zeek
      └── Sin enriquecedor
      │
      ▼
Agregación v2 + resumen compatible v1
      │
      ▼
Reputación de entidades IP
      │
      ▼
Firma v2 y estado inicial
      │
      ▼
Primer agente: Analista de Triage
```

No participa ningún agente durante las etapas anteriores al Analista de
Triage.

## 7. Estructura de código propuesta

```text
src/
├── preprocessing/
│   ├── __init__.py
│   ├── models.py
│   ├── result.py
│   ├── pipeline.py
│   ├── segmentation.py
│   ├── detection.py
│   ├── normalization.py
│   ├── aggregation.py
│   ├── ground_truth.py
│   │
│   ├── decoders/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── json_decoder.py
│   │   ├── csv_decoder.py
│   │   ├── syslog_decoder.py
│   │   ├── key_value_decoder.py
│   │   ├── cef_decoder.py
│   │   ├── leef_decoder.py
│   │   └── text_decoder.py
│   │
│   └── enrichers/
│       ├── __init__.py
│       ├── base.py
│       ├── hdfs.py
│       ├── bgl.py
│       └── zeek.py
│
└── tools/
    └── aggregation.py  # fachada de compatibilidad temporal
```

## 8. Modelo normalizado propuesto

El modelo interno deberá representar eventos diversos sin reutilizar campos con
significados incompatibles.

```python
@dataclass
class NormalizedEvent:
    raw: str
    message: str
    timestamp: str | None = None

    source_ip: str | None = None
    source_port: int | None = None
    source_host: str | None = None
    source_user: str | None = None

    destination_ip: str | None = None
    destination_port: int | None = None
    destination_host: str | None = None
    destination_user: str | None = None

    service_name: str | None = None
    process_name: str | None = None
    process_id: str | None = None
    protocol: str | None = None

    event_category: str | None = None
    event_action: str | None = None
    event_outcome: str | None = None
    severity: str | None = None
    event_code: str | None = None

    product: str | None = None
    vendor: str | None = None
    version: str | None = None

    decoder: str = "text"
    parsing_confidence: float = 0.0
    attributes: dict = field(default_factory=dict)
```

Cada evento deberá incluir metadatos de procedencia:

- Número de registro.
- Línea física inicial y final.
- Segmento de origen.
- Decoder utilizado.
- Confianza.
- Advertencias.
- Indicación de evento multilínea.

## 9. Configuración propuesta

Se agregarán a `src/config.py` y `.env.example`:

```env
LOG_PARSING_MODE=hybrid
LOG_DETECTION_CHUNK_SIZE=50
LOG_FORMAT_CONFIDENCE_THRESHOLD=0.50
LOG_LINE_FALLBACK_THRESHOLD=0.70

LOG_ENABLE_MULTILINE=true
LOG_PRESERVE_RAW=true
LOG_MAX_RAW_SAMPLES=20
LOG_MAX_UNMAPPED_FIELDS=100

LOG_NORMALIZATION_SCHEMA_VERSION=2.0
LOG_MAX_FILE_BYTES=52428800
LOG_MAX_EVENTS=100000
```

Los modos previstos serán:

- `batch`: un decoder dominante por lote, para compatibilidad o rendimiento.
- `chunked`: un decoder por bloque.
- `line`: detección independiente por registro.
- `hybrid`: bloques con reprocesamiento individual de rechazos; será el modo
  recomendado.

## 10. Plan de ejecución por fases

### Fase 0 — Establecer la línea base

#### Objetivo

Congelar y verificar el comportamiento actual antes de alterar contratos.

#### Actividades

- Instalar Python y dependencias en `.venv`.
- Ejecutar las pruebas actuales.
- Registrar fallos preexistentes.
- Verificar HDFS, BGL, CSV y auth-log.
- Documentar el esquema v1 y sus consumidores.
- Conservar muestras de regresión.

#### Archivos

- `requirements.txt`
- `tests/`
- `results/`
- `docs/preprocessing_baseline.md`

#### Entregables

- Informe de línea base.
- Resultado de pruebas reproducible.
- Inventario de consumidores del contrato v1.

#### Criterio de aceptación

- Suite ejecutada y resultado documentado.
- Fallos preexistentes identificados.
- Contrato v1 explícito.

#### Puerta de aprobación

Presentar la línea base y solicitar autorización antes de definir los modelos
v2.

### Fase 1 — Definir contratos y modelos v2

#### Objetivo

Crear las estructuras normalizadas sin conectarlas todavía al pipeline.

#### Actividades

- Crear `NormalizedEvent`.
- Crear `RecordSegment`.
- Crear `ParsingWarning`.
- Crear `GroundTruthRecord`.
- Crear `PreprocessingResult`.
- Implementar serialización controlada.
- Validar invariantes y valores predeterminados.

#### Archivos nuevos

- `src/preprocessing/__init__.py`
- `src/preprocessing/models.py`
- `src/preprocessing/result.py`
- `tests/test_preprocessing_models.py`

#### Consecuencias

- Se introduce un contrato tipado adicional.
- El contrato v1 permanece sin cambios.
- No cambia todavía ninguna salida del sistema.

#### Criterio de aceptación

- Eventos sin IP, usuario o timestamp son válidos.
- `raw` y `message` se preservan.
- La serialización es determinística.
- Las nuevas pruebas pasan junto con las anteriores.

#### Puerta de aprobación

Presentar el contrato v2 y ejemplos serializados antes de crear decoders.

### Fase 2 — Configuración y versionado

#### Objetivo

Externalizar las decisiones del preprocesamiento.

#### Actividades

- Agregar variables `LOG_*`.
- Validar tipos, límites y combinaciones.
- Incorporar `schema_version`.
- Registrar la configuración efectiva en resultados.

#### Archivos

- `src/config.py`
- `.env.example`
- `tests/test_preprocessing_config.py`

#### Criterio de aceptación

- Configuración inválida produce mensajes claros.
- Los defaults permiten reproducir una corrida.
- La configuración no cambia el parser v1 todavía.

#### Puerta de aprobación

Presentar defaults y validaciones antes de implementar segmentación.

### Fase 3 — Segmentación de registros

#### Objetivo

Separar líneas físicas de eventos lógicos y soportar eventos multilínea.

#### Actividades

- Segmentar por línea en el caso base.
- Agrupar stack traces y continuaciones indentadas.
- Reconocer objetos JSON completos.
- Conservar líneas iniciales y finales.
- Registrar líneas huérfanas.
- Aplicar límites de tamaño.

#### Archivos

- `src/preprocessing/segmentation.py`
- `tests/test_preprocessing_segmentation.py`

#### Consecuencias

- `total_lineas` deja de ser equivalente a `total_eventos`.
- Se deberán exponer ambos contadores.
- Los errores multilínea ya no inflarán artificialmente el número de eventos.

#### Criterio de aceptación

- Ninguna línea desaparece sin contabilización.
- Un stack trace se representa como un evento.
- Se conservan posiciones y contenido original.

#### Puerta de aprobación

Presentar ejemplos simples y multilínea antes de implementar decoders.

### Fase 4 — Decodificadores estructurales

#### Objetivo

Interpretar estructuras generales sin depender del producto de origen.

#### Actividades

- Definir interfaz `Decoder`.
- Implementar JSON/JSONL.
- Implementar CSV/TSV y delimitadores configurados.
- Implementar Syslog RFC 3164/5424.
- Implementar `clave=valor`.
- Implementar CEF y LEEF.
- Implementar texto libre como fallback obligatorio.
- Conservar campos no mapeados.

#### Archivos

- `src/preprocessing/decoders/*`
- `src/preprocessing/normalization.py`
- Pruebas unitarias por decoder.

#### Consecuencias

- Auth-log deja de ser el fallback universal.
- Los decoders no clasifican ataques.
- Las estructuras desconocidas continúan mediante texto libre.

#### Criterio de aceptación

- Ningún registro textual válido aborta un lote.
- Cada evento informa decoder y confianza.
- JSON, CSV, Syslog, CEF, LEEF y `clave=valor` tienen pruebas positivas y
  negativas.

#### Puerta de aprobación

Presentar matriz de cobertura de formatos antes de activar lotes mixtos.

### Fase 5 — Detección heterogénea

#### Objetivo

Procesar diferentes estructuras dentro del mismo archivo.

#### Actividades

- Implementar modos `batch`, `chunked`, `line` y `hybrid`.
- Detectar decoder dominante por bloque.
- Reprocesar individualmente rechazos del bloque.
- Mantener contexto por segmento CSV.
- Detectar nuevas cabeceras.
- Registrar segmentos y cambios de estructura.
- Calcular cobertura y fallbacks.

#### Archivos

- `src/preprocessing/detection.py`
- `src/preprocessing/pipeline.py`
- `tests/test_preprocessing_heterogeneous.py`

#### Criterio de aceptación

- Un lote combinado HDFS, JSON, Syslog y texto se procesa completamente.
- Los cambios de formato aparecen en `segments`.
- Los registros no reconocidos terminan en `TextDecoder`.
- No se comparte estado CSV entre análisis concurrentes.

#### Puerta de aprobación

Presentar resultados sobre lotes mixtos antes de migrar HDFS/BGL.

### Fase 6 — Enriquecedores de producto

#### Objetivo

Convertir HDFS, BGL y Zeek en enriquecimientos opcionales.

#### Actividades

- Mover extracción de `block_id` y componentes HDFS.
- Mover nodo, subsistema y código RAS de BGL.
- Incorporar campos de flujo de Zeek.
- Definir interfaz `Enricher`.
- Permitir ejecución sin enriquecedor.

#### Archivos

- `src/preprocessing/enrichers/*`
- `tests/test_preprocessing_enrichers.py`

#### Consecuencias

- HDFS/BGL dejan de determinar la arquitectura del parser.
- Se mantiene información específica conocida.
- Agregar un producto nuevo no obliga a cambiar el núcleo.

#### Criterio de aceptación

- HDFS y BGL conservan al menos la información actualmente extraída.
- Una fuente desconocida completa el flujo sin perfil.
- Ningún enriquecedor decide por sí mismo que existe un ataque.

#### Puerta de aprobación

Comparar salidas actuales y enriquecidas antes de separar ground truth.

### Fase 7 — Separación de ground truth

#### Objetivo

Evitar fuga de etiquetas hacia las features observadas por el detector.

#### Actividades

- Crear canal separado de ground truth.
- Asociar etiquetas por ID de evento, bloque o ventana.
- Ocultar etiquetas del resumen utilizado por agentes.
- Adaptar evaluación HDFS/BGL/CSV.
- Marcar resultados históricos como esquema/metodología anterior.

#### Archivos

- `src/preprocessing/ground_truth.py`
- `src/tools/eval_deteccion.py`
- Decoders/enrichers afectados.
- Pruebas de evaluación.

#### Consecuencias

- Deben recalcularse las métricas BGL.
- El F1 puede disminuir al eliminar información filtrada desde las etiquetas.
- Las nuevas métricas tendrán mayor validez metodológica.

#### Criterio de aceptación

- Eliminar las etiquetas no modifica las features de entrada.
- El detector no recibe ground truth.
- Las métricas continúan pudiendo calcularse después del análisis.

#### Puerta de aprobación

Presentar evidencia de aislamiento antes de construir la agregación v2.

### Fase 8 — Agregación v2 y compatibilidad v1

#### Objetivo

Generar un resumen genérico sin romper consumidores actuales.

#### Actividades

- Implementar agregación de eventos normalizados.
- Agregar distribución de decoders, productos y severidad.
- Agregar entidades: IP, host, usuario, proceso, dominio, URL y hash.
- Calcular cobertura y advertencias.
- Seleccionar muestras representativas.
- Derivar campos compatibles v1.
- Convertir `src/tools/aggregation.py` en fachada temporal.

#### Salida v2 mínima

```json
{
  "schema_version": "2.0",
  "total_lineas_fisicas": 0,
  "total_eventos": 0,
  "decoder_distribution": {},
  "product_distribution": {},
  "severity_distribution": {},
  "event_categories": {},
  "entities": {},
  "time_window": {},
  "parsing": {
    "parsed_events": 0,
    "fallback_events": 0,
    "coverage": 0.0
  },
  "segments": [],
  "warnings": [],
  "samples": {}
}
```

#### Compatibilidad v1 temporal

- `formato_detectado`
- `total_lineas`
- `servicios`
- `eventos`
- `ventana_temporal`
- `n_ips_distintas`
- `ips_distintas`
- `por_ip`

#### Criterio de aceptación

- Las pruebas v1 continúan pasando.
- Las pruebas v2 validan cobertura y entidades.
- Los campos compatibles se derivan desde la misma fuente, sin doble parsing.

#### Puerta de aprobación

Presentar comparación v1/v2 antes de conectar el nuevo resumen al grafo.

### Fase 9 — Integración con el pipeline y el estado

#### Objetivo

Conectar el preprocesamiento v2 manteniendo el grafo de siete nodos.

#### Actividades

- Modificar `_preparar_estado_inicial()`.
- Consultar reputación solo para entidades IP.
- Incorporar metadatos y advertencias al estado.
- Mantener muestras acotadas.
- Evitar almacenar todos los eventos en LangGraph.
- Adaptar eventos SSE iniciales.

#### Archivos

- `src/pipeline.py`
- `src/state.py`
- Pruebas de pipeline y streaming.

#### Estado propuesto

```python
class LogGuardState(TypedDict):
    resumen_logs: dict
    preprocessing_metadata: dict
    parsing_warnings: list
    raw_samples: list
    firma: str
    # campos actuales del grafo
```

#### Criterio de aceptación

- El grafo conserva siete nodos.
- Los lotes sin IP pueden analizarse.
- El estado no crece proporcionalmente al contenido completo del archivo.
- El streaming informa correctamente el preprocesamiento.

#### Puerta de aprobación

Presentar pruebas de pipeline con LLM simulado antes de adaptar consumidores.

### Fase 10 — Adaptación de agentes y herramientas

#### Objetivo

Hacer que los consumidores comprendan el resumen generalizado.

#### Cambios por componente

| Componente | Cambio requerido |
|---|---|
| Triage | Analizar múltiples fuentes, cobertura, confianza y muestras |
| Resumen de prompt | Acotar todas las clases de entidad y contenido crudo |
| Selector | Usar productos, categorías, protocolos y procesos |
| CVE | Priorizar producto, fabricante, versión y CPE |
| RAG | Consultar mediante firma v2 |
| Auditor | Considerar incertidumbre y cobertura del parser |

#### Archivos

- `src/agents/agente_analista_triage.py`
- `src/agents/agente_selector_herramientas.py`
- `src/agents/agente_auditor_final.py`
- `src/tools/resumen_prompt.py`
- `src/tools/tool_consultar_cve.py`
- `src/tools/tool_consultar_rag.py`

#### Criterio de aceptación

- No se usa `ssh` como fallback artificial para CVE.
- Un lote sin IP o servicio conocido puede diagnosticarse.
- El prompt permanece dentro de límites medidos.
- La incertidumbre del parsing aparece en el razonamiento entregado al agente.

#### Puerta de aprobación

Presentar prompts y respuestas simuladas antes de versionar memoria.

### Fase 11 — Firma, memoria y persistencia

#### Objetivo

Evitar mezclar representaciones incompatibles.

#### Actividades

- Crear firmas prefijadas por versión.
- Incorporar decoders, productos, categorías y severidades.
- Crear colecciones ChromaDB v2 o reconstruir las existentes.
- Mantener acceso controlado a datos v1 durante la transición.
- Versionar resultados de `log_runner`.
- Guardar configuración efectiva de parsing.

#### Archivos

- `src/memory.py`
- `src/tools/aggregation.py` o módulo de firma nuevo.
- `src/tools/log_runner.py`
- `src/pipeline.py`

#### Riesgo principal

Los embeddings v1 y v2 no deben almacenarse como si representaran el mismo tipo
de firma.

#### Criterio de aceptación

- Cada resultado identifica esquema y configuración.
- Cada firma identifica su versión.
- Las búsquedas no mezclan firmas incompatibles.

#### Puerta de aprobación

Presentar estrategia de migración de ChromaDB antes de cambiar la interfaz.

### Fase 12 — API e interfaz web

#### Objetivo

Mostrar de forma transparente cómo se interpretó el archivo.

#### Actividades

- Mostrar formato único o mixto.
- Mostrar distribución de decoders y productos.
- Diferenciar líneas físicas y eventos.
- Mostrar cobertura, fallback y advertencias.
- Mostrar segmentos detectados.
- Validar tamaño, encoding, contenido binario y número de eventos.

#### Archivos

- `src/api/main.py`
- `src/api/static/index.html`

#### Criterio de aceptación

- El usuario puede distinguir parsing completo, parcial y fallback.
- Un error de preprocesamiento se muestra claramente.
- La API aplica límites antes de ocupar memoria excesiva.

#### Puerta de aprobación

Presentar evidencia visual y pruebas SSE antes de reevaluar datasets.

### Fase 13 — Validación integral y cierre

#### Objetivo

Demostrar compatibilidad, robustez, rendimiento y validez experimental.

#### Pruebas requeridas

- JSON y JSONL.
- CSV, TSV y múltiples delimitadores.
- Syslog RFC 3164 y RFC 5424.
- CEF y LEEF.
- `clave=valor`.
- Texto desconocido.
- Stack traces y eventos multilínea.
- Formatos por segmentos.
- Formatos intercalados.
- Dos CSV con cabeceras diferentes.
- Líneas corruptas.
- Logs sin IP.
- Timestamps incompatibles.
- Preservación de campos desconocidos.
- Separación de ground truth.
- Compatibilidad v1.
- Pipeline y SSE con LLM simulado.

#### Evaluaciones cuantitativas

- HDFS balanceado.
- HDFS con prevalencia real.
- BGL sin fuga de etiquetas.
- Zeek/CSV.
- Lotes mixtos.
- Baseline determinístico de reglas.

#### Métricas

- Cobertura de parsing.
- Exactitud de extracción de campos.
- Porcentaje de fallback.
- Pérdida de información.
- Tiempo por mil eventos.
- Uso máximo de memoria.
- Tokens del prompt.
- Precision, Recall y F1 del detector.

#### Criterio de aceptación

- Todas las pruebas pasan.
- No existe fuga conocida de ground truth.
- El costo de prompts se mantiene acotado.
- Las métricas se regeneran y documentan.
- README e informe reflejan la arquitectura efectiva.

#### Aprobación final

Presentar resultados completos y solicitar aceptación de la migración.

## 11. Matriz de impacto

| Área | Impacto | Motivo |
|---|---|---|
| Parsing | Alto | Se reemplaza el núcleo actual |
| Estado LangGraph | Medio | Se agregan metadatos, no eventos completos |
| Triage | Medio | Cambia la estructura del resumen |
| Selector de herramientas | Medio | Debe usar más señales que servicios |
| CVE | Medio | Cambia selección de keywords |
| RAG y firma | Alto | Cambia el significado del embedding |
| Memoria ChromaDB | Alto | Requiere versionado o reconstrucción |
| Interfaz web | Medio | Debe presentar heterogeneidad y cobertura |
| Resultados JSON | Medio | Nuevo esquema versionado |
| Evaluación | Alto | Deben recalcularse métricas sin fuga |
| Grafo de agentes | Bajo | Se conservan los siete nodos |

## 12. Estrategia de compatibilidad y migración

1. Introducir modelos v2 sin cambiar `aggregate_logs()`.
2. Implementar la nueva tubería detrás de una API separada.
3. Comparar salidas v1 y v2.
4. Generar campos v1 desde la agregación v2.
5. Conectar el pipeline mediante una configuración controlada.
6. Migrar consumidores uno por uno.
7. Versionar firma y resultados.
8. Mantener rollback al parser v1 durante la validación.
9. Retirar v1 solo cuando ningún consumidor dependa de él.

Una posible bandera temporal será:

```env
LOG_PREPROCESSING_ENGINE=v1
```

Durante el despliegue controlado podrá cambiarse a:

```env
LOG_PREPROCESSING_ENGINE=v2
```

El modo `v1` no debe eliminarse hasta completar la Fase 13.

## 13. Estrategia de rollback

Si una fase integrada introduce regresiones:

1. Mantener intacto el parser v1.
2. Desactivar v2 por configuración.
3. Conservar resultados v2 para diagnóstico.
4. No migrar ni borrar colecciones ChromaDB v1 durante la transición.
5. Corregir la fase sin continuar con la siguiente.
6. Repetir suite y comparación antes de solicitar otra aprobación.

No se deberán sobrescribir resultados históricos ni eliminar memoria como parte
automática de la migración.

## 14. Gestión de riesgos

| Riesgo | Mitigación |
|---|---|
| Ruptura de consumidores | Fachada v1 y migración gradual |
| Explosión de tokens | Resúmenes y muestras acotadas |
| Uso excesivo de memoria | No almacenar todos los eventos en LangGraph |
| Falsos significados | Decoders estructurales sin decisiones de ataque |
| Fuga de etiquetas | Canal de ground truth separado |
| Ambigüedad de formato | Confianza, segmentos y fallback |
| Corrupción de memoria RAG | Firmas y colecciones versionadas |
| Resultados no comparables | Registrar esquema y configuración |
| Archivos enormes | Límites de bytes y eventos |
| Parsing parcial silencioso | Cobertura y advertencias visibles |
| Estado CSV compartido | Instancia de decoder por segmento/análisis |

## 15. Protocolo de avance y aprobación

Para cada fase se seguirá este procedimiento:

1. Anunciar el inicio de la fase.
2. Confirmar alcance y archivos que se modificarán.
3. Implementar solamente esa fase.
4. Ejecutar pruebas pertinentes y suite de regresión.
5. Presentar:
   - Cambios realizados.
   - Archivos creados o modificados.
   - Pruebas ejecutadas.
   - Resultados.
   - Problemas o desviaciones.
   - Riesgos pendientes.
6. Detener la implementación.
7. Solicitar aprobación explícita.
8. Iniciar la siguiente fase únicamente después de recibirla.

Si una fase no cumple sus criterios, no se solicitará aprobación para avanzar;
se presentará el bloqueo y una propuesta de resolución.

## 16. Entregas recomendadas

Aunque el control se realiza por fase, los hitos técnicos pueden agruparse así:

1. **Fundaciones:** fases 0–2.
2. **Parsing universal:** fases 3–5.
3. **Semántica y evaluación:** fases 6–8.
4. **Integración del sistema:** fases 9–12.
5. **Validación y cierre:** fase 13.

Cada entrega debe dejar la suite estable y permitir volver al comportamiento
anterior.

## 17. Definición de terminado

La migración estará completa cuando:

- Todo registro textual se preserve aunque no sea reconocido.
- Un archivo pueda contener múltiples formatos.
- HDFS y BGL funcionen como enriquecedores opcionales.
- Los logs sin IP se procesen correctamente.
- Exista un esquema normalizado versionado.
- Las etiquetas no sean visibles para el detector.
- Se informe cobertura, confianza y fallback.
- Los prompts permanezcan acotados.
- La firma y memoria estén versionadas.
- La API y la interfaz muestren heterogeneidad y advertencias.
- Las pruebas actuales y nuevas pasen.
- Las métricas HDFS/BGL se hayan recalculado.
- El README y el informe académico describan la implementación real.

## 18. Estado de ejecución al emitir este documento

- Fase 0 iniciada.
- Python 3.12.10 instalado.
- `.venv` creado e ignorado por Git.
- Dependencias de `requirements.txt` instaladas.
- Primera ejecución de pruebas interrumpida durante la colección por ausencia de
  `GEMINI_API_KEY`.
- Se preparó una segunda ejecución con una clave ficticia temporal para los
  tests simulados, pero la ejecución fue interrumpida antes de obtener el
  resultado final.
- No se ha iniciado la Fase 1.
- No se ha modificado todavía el comportamiento productivo del parser.

El siguiente paso operativo será completar la suite de línea base y presentar
sus resultados para aprobación antes de iniciar la Fase 1.
