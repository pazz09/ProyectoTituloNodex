# NODEX

Sistema multiagente basado en LLM para el análisis semántico de logs de seguridad. Recibe un lote de logs, los interpreta de forma determinística, y un grafo de agentes LLM (orquestado con LangGraph, patrón **Plan-and-Execute**) diagnostica si hay una anomalía o un incidente de seguridad, recupera contexto histórico y conocimiento externo (MITRE ATT&CK, CVEs, reputación de IPs), propone y valida comandos de mitigación, y entrega un reporte estructurado —con su versión en PDF— explicando el porqué del diagnóstico.

Desarrollado por Antonia Paz Navarrete Silva como Proyecto de Título (PUCV).

## Qué hace

1. **Preprocesa** logs heterogéneos de forma determinística (sin LLM): extrae IPs, usuarios, servicios, eventos críticos, códigos de respuesta y ventanas temporales.
2. **Planifica** un plan de investigación antes de analizar (qué revisar y en qué orden).
3. **Diagnostica** el tipo de evento, consultando memoria histórica y MITRE ATT&CK cuando corresponde.
4. **Consulta fuentes externas**: vulnerabilidades conocidas (NVD) y reputación de IPs (AbuseIPDB).
5. **Propone y valida** comandos de mitigación.
6. **Evalúa** la calidad del análisis; si la cobertura de evidencia no alcanza, replanifica (acotado).
7. **Reporta**: diagnóstico, nivel de confianza, técnicas MITRE ATT&CK asociadas, comandos de mitigación, y un informe en PDF.
8. **Aprende**: un analista humano puede confirmar o corregir el diagnóstico desde la interfaz, lo que alimenta la memoria de largo plazo para casos futuros.

## Arquitectura

Patrón **Plan-and-Execute**: un agente planifica qué investigar antes de que el análisis especializado comience, y el ciclo puede replanificarse (acotado) si la evidencia reunida no alcanza para una conclusión sólida.

```
Logs crudos
  → Preprocesamiento determinístico (segmentación, decodificación, enriquecimiento)
  → Corroboración de reputación de IPs
  → agente_planificador (LLM) — plan de investigación sobre el resumen
       → agente_analista_triage (LLM) ⇄ tool_consultar_rag (Tool)
            → agente_selector_herramientas (LLM) ⇄ tool_consultar_cve (Tool)
                 → agente_ingeniero_mitigacion (LLM) ⇄ tool_validar_comandos (Tool)
                      → agente_auditor_final (LLM)
                           → ¿cobertura suficiente? NO → replanifica (máx. 1 vez) | SÍ → SALIDA
  → Persistencia (historial) + reporte (JSON y PDF)
  → Retroalimentación humana → memoria de largo plazo
```

Implementado como un `StateGraph` de **LangGraph**: **8 nodos** (5 agentes LLM + 3 herramientas determinísticas) y **4 aristas condicionales**.

| Nodo | Tipo | Rol |
|---|---|---|
| `agente_planificador` | LLM | Genera el plan de investigación antes del análisis especializado; replanifica si la cobertura de evidencia no alcanza |
| `agente_analista_triage` | LLM | Analiza el resumen del lote; decide si necesita contexto histórico |
| `tool_consultar_rag` | Tool | Recupera contexto histórico y técnicas MITRE ATT&CK desde ChromaDB |
| `agente_selector_herramientas` | LLM | Decide si corresponde consultar vulnerabilidades conocidas |
| `tool_consultar_cve` | Tool | Consulta NVD por CVEs relacionados |
| `agente_ingeniero_mitigacion` | LLM | Propone comandos de mitigación |
| `tool_validar_comandos` | Tool | Valida los comandos contra una lista blanca y patrones peligrosos |
| `agente_auditor_final` | LLM | Diagnóstico global, confianza, veredictos de anomalía/incidente, cobertura de evidencia |

Las herramientas (`tool_*`) no invocan al modelo de lenguaje — son deterministas y reproducibles. Los 4 *routers* (`router_triage`, `router_selector`, `router_validacion`, `router_finalizacion`) resuelven decisiones locales con evidencia real; el plan generado por el planificador es una guía global y queda trazado paso a paso (qué se planificó, qué se ejecutó, qué se omitió y por qué), pero nunca sobreescribe una decisión de router.

Checkpointer de LangGraph: `MemorySaver` (memoria de corto plazo, no persiste entre ejecuciones).

## Stack técnico

- **LangGraph** (`StateGraph`) para la orquestación del grafo.
- **Gemini** (`google-genai`, SDK directo) como modelo de lenguaje — dos modelos configurados, uno principal y uno de respaldo automático ante fallas o cuota agotada (ver `src/llm.py`).
- **ChromaDB**: 4 colecciones (`attack_patterns`, `error_memory`, `host_history`, `attack_techniques`), embeddings `all-MiniLM-L6-v2` (384 dimensiones).
- Herramientas externas: **AbuseIPDB** (reputación de IPs), **NVD** (CVEs), **MITRE ATT&CK** (STIX 2.1).
- **FastAPI** + *Server-Sent Events* para la API y el streaming en vivo del análisis.
- **Next.js** (React, Tailwind CSS, shadcn/ui) para la interfaz principal.
- **fpdf2** para el informe en PDF (Python puro, sin dependencias nativas).
- Python 3.10+; testing con `pytest`.

## Estructura del proyecto

```
NODEX/
├── src/
│   ├── config.py            # Variables de entorno y constantes (umbrales, modelos, límites)
│   ├── state.py              # LogGuardState: el TypedDict del grafo (31 campos)
│   ├── llm.py                 # Cliente del LLM, con reintentos y manejo de cuota
│   ├── memory.py               # ChromaDB: 4 colecciones y el ciclo de feedback
│   ├── pipeline.py              # Punto de entrada: analizar_lote, el stream SSE y commit_feedback
│   ├── agents/                   # Los 5 nodos LLM (planificador, triage, selector, mitigación, auditor)
│   ├── tools/                     # Los 3 nodos Tool (RAG, CVE, validación) + agregación y evaluación
│   ├── preprocessing/               # Preprocesamiento heterogéneo: segmentación, decoders, enriquecedores
│   ├── graph/
│   │   ├── build_graph.py             # StateGraph, los 4 routers y la compilación
│   │   ├── routers.py
│   │   └── plan_tracking.py            # Trazabilidad determinística del plan (sin LLM)
│   └── api/                              # Backend web (FastAPI)
│       ├── main.py                        # Endpoints: analizar, stream SSE, historial, PDF, feedback
│       ├── historial.py                    # Persistencia de corridas en SQLite
│       ├── informe_pdf.py                   # Generador del informe en PDF
│       └── static/index.html                 # Interfaz de respaldo, sin build step
├── frontend/                     # Interfaz en Next.js
│   ├── app/                        # page.tsx (enrutado de vistas) y globals.css (sistema visual)
│   ├── components/                   # Resumen, Multiagente, Informe, Ejecuciones
│   └── lib/                            # Cliente de la API y catálogo de nodos
├── data/                          # Caché de reputación, ChromaDB, historial (no se versiona el contenido real)
├── docs/                           # Referencia técnica (pipeline de preprocesamiento, cierre de auditoría)
├── results/                        # JSON de corridas de evaluación
├── tests/                           # Suite de pruebas deterministas
├── .github/workflows/ci.yml           # Backend (pytest) + frontend (lint/typecheck/test/build)
├── requirements.txt
├── constraints.txt                      # Lock completo (directas + transitivas) para reproducibilidad
├── .env.example
└── .gitignore
```

## Setup

### Backend

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Unix: source .venv/bin/activate
pip install -r requirements.txt -c constraints.txt
cp .env.example .env   # completar con tus API keys
```

`requirements.txt` fija cada dependencia directa a la versión exacta con la que corre la suite hoy; `constraints.txt` es el `pip freeze` completo (directas + transitivas), para que el entorno se pueda reproducir igual en cualquier máquina — importante para que las métricas de evaluación (`results/`) sean comparables entre corridas. Sin `-c constraints.txt` igual instala (`requirements.txt` solo no falla), pero sin la garantía de reproducibilidad total.

### API keys necesarias

- `GEMINI_API_KEY` — obligatoria.
- `ABUSEIPDB_API_KEY` — opcional (fallback heurístico local si falta).
- `NVD_API_KEY` — opcional (límite de tasa muy bajo sin ella).

### Frontend

```bash
cd frontend
pnpm install
```

## Cómo correrlo

**Interfaz completa** (recomendado): backend + frontend.

```bash
# Terminal 1
uvicorn src.api.main:app --reload

# Terminal 2
cd frontend && pnpm dev
```

**Línea de comandos** (para corridas de evaluación, sin interfaz):

```bash
python -m src.tools.log_runner data/logs/HDFS_2k.log
```

**Pruebas**:

```bash
pytest tests/ -q                # backend
cd frontend && pnpm lint && pnpm typecheck && pnpm test && pnpm build   # frontend
```

CI (`.github/workflows/ci.yml`) corre ambos en cada push/PR.

### Evaluación reproducible (Fase 6)

La evaluación final se orquesta desde un único comando y debe ejecutarse
sobre un commit limpio, con `GEMINI_API_KEY` activa y crédito disponible:

```bash
python -m src.tools.fase6 --modo todo
```

Modos disponibles: `baselines`, `multiagente`, `verificar` y `todo`. El modo
`todo` genera los baselines y las evaluaciones multiagente de BGL, HDFS
balanceado y HDFS con prevalencia 3,1%. Cada JSON registra commit, rama,
estado del árbol, versiones, configuración, modelos y hashes SHA-256 de los
datasets. `results/fase6_manifest.json` solo se crea si existen las seis
corridas completas, sin lotes fallidos y correspondientes al mismo commit.

Un error de API o un estado sin diagnóstico/veredicto se registra como lote
fallido y se excluye de precisión, recall y F1; nunca se convierte por defecto
en una predicción `normal`.

## Preprocesamiento

Un único motor, determinístico y sin LLM, que reemplaza «detectar dataset → un parser → todo el lote» por una tubería genérica:

```
ingesta → segmentación → detección y decodificación → enriquecimiento → agregación
```

- **Segmentación**: separa línea física de registro lógico (un *stack trace* de 30 líneas es un evento, no 30).
- **Detección y decodificación**: 7 decodificadores estructurales (JSON, CSV, Syslog, CEF, LEEF, clave-valor, texto libre), con detección de formato por confianza y reproceso individual de los registros que el decodificador dominante de un bloque no explica bien (modo `hybrid`, el recomendado) — permite que un mismo lote mezcle formatos.
- **Enriquecimiento**: 4 enriquecedores de producto (HDFS, BGL, Zeek, autenticación) añaden contexto específico y separan cualquier etiqueta de verdad de referencia del dataset hacia un canal aparte — el detector nunca ve la respuesta que se usa para evaluarlo.
- **Agregación**: produce el resumen estructurado que llega a los agentes (nunca los eventos crudos completos).

`decoder` (la sintaxis reconocida) y `product`/`perfil` (qué producto reconoció un enriquecedor) son dos cosas distintas: HDFS y BGL aparecen con `decoder=text` —ningún decodificador genérico reconoce sus columnas fijas— pero igual llegan a 100% de cobertura, porque el enriquecedor de producto sí las entiende. Ver "`decoder` vs. producto/perfil" en [`docs/pipeline_preprocesamiento.md`](docs/pipeline_preprocesamiento.md) para el detalle completo del flujo, el contrato v2↔v1 y qué campos llegan al prompt del Triage.

**Limitación conocida**: no hay todavía un decodificador para logs de acceso web estilo Apache/NCSA combined, así que el campo `codigo_respuesta` queda vacío para ese estilo de log.

## Memoria de largo plazo

Base de datos vectorial (ChromaDB), 4 colecciones:

| Colección | Se puebla cuando... | Umbral de similitud |
|---|---|---|
| `attack_patterns` | Un analista confirma un diagnóstico con confianza ≥ 0.90 | 0.55 |
| `error_memory` | Un analista corrige un diagnóstico | 0.55 |
| `host_history` | Cualquier retroalimentación humana, correcta o no | 0.55 |
| `attack_techniques` | Una sola vez, desde el catálogo oficial de MITRE ATT&CK (697 técnicas, STIX 2.1) | 0.42 |

Las primeras tres se pueblan **exclusivamente** mediante retroalimentación humana explícita desde la interfaz — nunca automáticamente durante un análisis ni durante una corrida de evaluación por lotes.

## Herramientas externas

- **NVD**: la palabra clave de búsqueda se elige por especificidad (producto/fabricante antes que servicio); no se consulta si no hay un término razonable.
- **AbuseIPDB**: cada IP única del lote se corrobora antes de que el grafo se ejecute, con caché persistente.
- **MITRE ATT&CK**: integrado como extensión de la herramienta de recuperación aumentada (no agrega un nodo al grafo). Versión del catálogo: la vigente al momento de poblar la base de conocimiento (ver `data/mitre_attack/provenance.json`).

## Generación de reportes

Desde el contrato `d11-v1`, el reporte JSON añade eventos reconstruidos,
secuencia temporal y técnicas MITRE explícitamente atribuidas con UIDs de
evidencia validados. Los candidatos RAG permanecen separados. API, CLI y
evaluador conservan estos campos y telemetría D5. El evaluador permite el
comparador de una llamada con `--arquitectura agente_unico`. Alcance, límites
del catálogo de evidencia y contrato: [D-11](docs/contrato_salida_d11.md).

El reporte final se persiste en SQLite (`data/historial.db`) y se sirve en dos formas, ambas derivadas del mismo estado final del grafo:

- **Estructurado** (JSON): expuesto por la API y por el modo de línea de comandos.
- **PDF**: documento único con plantilla propia (portada, una sección por página, serie temporal de eventos relevantes); la interfaz lo incrusta directamente, no lo vuelve a maquetar.

`LOG_PRESERVE_RAW` (default `true`) controla si la secuencia temporal persistida y exportada conserva el texto crudo o una versión redactada (IPs/usuarios/hosts enmascarados), con un hash SHA-256 del lote en su lugar. **No controla lo que se envía al LLM**: las muestras del prompt del Triage llegan a la API de Gemini sin pasar por esta variable, con `true` o con `false` — ver el comentario junto a su declaración en `src/config.py`.

## Configuración

Todas las variables viven en `.env.example`, con sus defaults. Esta tabla documenta el **efecto real** de las que más cambian el comportamiento del sistema — el resto son ajustes finos con nombre autoexplicativo.

| Variable | Default | Efecto real |
|---|---|---|
| `LOG_PARSING_MODE` | `hybrid` | Cómo se agrupan los registros para detectar formato: `batch` (un decoder para todo el lote, comportamiento de control), `chunked` (un decoder por bloque, sin reproceso), `line` (detección por registro, el más lento), `hybrid` (bloques + reproceso individual de los registros que el dominante no explica bien — el recomendado). |
| `LOG_DETECTION_CHUNK_SIZE` | `50` | Tamaño del bloque en modo `chunked`/`hybrid`. |
| `LOG_FORMAT_CONFIDENCE_THRESHOLD` | `0.50` | Confianza mínima para aceptar un decoder como dominante de un bloque; por debajo, el bloque cae a texto libre. |
| `LOG_LINE_FALLBACK_THRESHOLD` | `0.70` | En modo `hybrid`, por debajo de esta confianza un registro se reprocesa individualmente en vez de aceptarse con el decoder dominante del bloque. Debe ser mayor que `LOG_FORMAT_CONFIDENCE_THRESHOLD`, si no el modo `hybrid` se comporta como `chunked` y la validación lo rechaza. |
| `LOG_ENABLE_MULTILINE` | `true` | Si `false`, cada línea física es un registro (comportamiento de control, sin agrupar *stack traces*). |
| `LOG_PRESERVE_RAW` | `true` | Controla la **persistencia** (`data/historial.db`) y la **exportación** (PDF) del texto crudo en la cronología del reporte. Con `false`: se redactan IPs/usuarios/hosts en el mensaje y se guarda un hash SHA-256 + líneas + tamaño en su lugar (`raw_procedencia`). **No controla lo que se envía al LLM** — ver más abajo. |
| `LOG_MAX_RAW_SAMPLES` | `20` | Cuántas muestras de texto crudo (una por decoder distinto, hasta 500 caracteres cada una) se calculan durante el preprocesamiento. Estas muestras SÍ llegan al prompt del Triage (`contexto_preprocesamiento()`, ver `docs/pipeline_preprocesamiento.md`), sin pasar por `LOG_PRESERVE_RAW` — es la vía real por la que hoy sale texto crudo hacia Gemini. |
| `LOG_MAX_UNMAPPED_FIELDS` | `100` | Tope de campos sin mapear que se conservan en `attributes` por evento, antes de descartar el resto silenciosamente. |
| `LOG_MAX_FILE_BYTES` | `52428800` (50 MiB) | Tamaño máximo de un lote. Si se supera, el lote se **rechaza** (`PreprocesamientoError`) — no se trunca. Mismo límite que ya aplicaba la API al subir un archivo (HTTP 413); desde el cierre de auditoría del 23-sep-2026 (M6), CLI y evaluador también rechazan en vez de analizar una parte. |
| `LOG_MAX_EVENTS` | `100000` | Igual que `LOG_MAX_FILE_BYTES`, pero por cantidad de eventos lógicos en vez de bytes. |
| `CRONOLOGIA_MAX_EVENTOS` | `40` | Tope de entradas en la secuencia temporal del reporte (`cronologia`). Es un recorte de presentación: los conteos y distribuciones siguen calculándose sobre el lote completo. |
| `TOP_N_IPS_PROMPT` | `20` | Cuántas IPs se detallan individualmente en el resumen que ve el Triage; el resto se agrega en `ips_resumidas`. Existe porque el costo en tokens del prompt escala con la cantidad de IPs distintas, no con las líneas del lote. |
| `CONTEXTO_PREPROCESAMIENTO_MAX_CHARS` | `2000` | Presupuesto de caracteres para el segundo texto que ve el Triage (`contexto_preprocesamiento()`: esquema, cobertura, decoders, severidad, muestras). Si se supera, se recortan primero las muestras y las distribuciones; los conteos globales, la cobertura y las advertencias nunca se recortan. |
| `CONFIDENCE_THRESHOLD` | `0.70` | Por debajo de esta confianza, el auditor marca `requiere_revision_humana=true`. |
| `AUTO_PROMOTE` | `0.90` | Confianza a partir de la cual un diagnóstico confirmado por un analista se promueve a `attack_patterns` (few-shot para casos futuros). |
| `SCORE_MALICIOSO` / `SCORE_SOSPECHOSO` | `75` / `25` | Score de AbuseIPDB (0-100) a partir del cual una IP se categoriza como "malicioso"/"sospechoso" — esa categoría es la que decide qué IPs de cola larga igual entran en detalle al prompt acotado (ver `TOP_N_IPS_PROMPT`). |
| `MAX_PLAN_STEPS` / `MAX_REPLANS` | `6` / `1` | Cotas del ciclo Plan-and-Execute: pasos máximos del plan y replanificaciones máximas si la cobertura de evidencia no alcanza. |
| `MAX_INTENTOS_CORRECCION` | `2` | Reintentos del ingeniero de mitigación si el validador rechaza los comandos propuestos. |

### Lo que `LOG_PRESERVE_RAW` no cubre

`LOG_PRESERVE_RAW=false` controla la persistencia local y la exportación en PDF — no lo que se envía a la API de Gemini. Las muestras de texto crudo que arma `contexto_preprocesamiento()` para el prompt del Triage (acotadas por `LOG_MAX_RAW_SAMPLES`) llegan al modelo sin pasar por esta variable, con `true` o con `false`. Es una limitación conocida y documentada a propósito (ver "Alcance y limitaciones conocidas" más abajo), no un descuido: cerrarla exigiría decidir si el Triage puede seguir diagnosticando con muestras redactadas, y es un cambio aparte del alcance de este README.

## Pruebas

Suite determinista (`pytest tests/ -q`), sin costo de cuota de LLM ni credenciales reales — cubre agentes (con el LLM simulado), routers, el grafo compilado, preprocesamiento, memoria, y los endpoints de la API.

## Alcance y limitaciones conocidas

Por diseño (ver Capítulo 8 del informe, §8.7.2): no incluye despliegue productivo, integración con SIEM, ingesta en tiempo real, ejecución automática de comandos, ni fine-tuning del modelo de lenguaje. La validación final y la toma de decisiones operacionales quedan bajo responsabilidad humana — el sistema propone, no ejecuta.

Limitaciones técnicas conocidas, ya documentadas en el código:

- Sin decodificador para logs de acceso web estilo Apache/NCSA combined (ver "Preprocesamiento" arriba) — el campo `codigo_respuesta` queda vacío para ese estilo de log.
- El enlace formal entre CVEs y técnicas MITRE ATT&CK no está implementado — ambos se recuperan por separado, sin relacionarse entre sí en el reporte.
- **Exposición de muestras al LLM**: `LOG_PRESERVE_RAW=false` evita persistir/exportar texto crudo, pero no evita que las muestras acotadas (`LOG_MAX_RAW_SAMPLES`) lleguen al prompt del Triage y salgan hacia la API de Gemini — ver "Configuración" arriba. Es la brecha de privacidad más relevante hoy entre las tres (persistencia, exportación, LLM): las dos primeras tienen control real, la tercera todavía no.
- Variabilidad menor entre corridas idénticas pese a operar con temperatura 0.
