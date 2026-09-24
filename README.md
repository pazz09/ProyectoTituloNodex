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
├── results/                        # JSON de corridas de evaluación
├── tests/                           # Suite de pruebas deterministas
├── requirements.txt
├── .env.example
└── .gitignore
```

## Setup

### Backend

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Unix: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # completar con tus API keys
```

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
pytest tests/ -q
```

## Preprocesamiento

Un único motor, determinístico y sin LLM, que reemplaza «detectar dataset → un parser → todo el lote» por una tubería genérica:

```
ingesta → segmentación → detección y decodificación → enriquecimiento → agregación
```

- **Segmentación**: separa línea física de registro lógico (un *stack trace* de 30 líneas es un evento, no 30).
- **Detección y decodificación**: 7 decodificadores estructurales (JSON, CSV, Syslog, CEF, LEEF, clave-valor, texto libre), con detección de formato por confianza y reproceso individual de los registros que el decodificador dominante de un bloque no explica bien (modo `hybrid`, el recomendado) — permite que un mismo lote mezcle formatos.
- **Enriquecimiento**: 4 enriquecedores de producto (HDFS, BGL, Zeek, autenticación) añaden contexto específico y separan cualquier etiqueta de verdad de referencia del dataset hacia un canal aparte — el detector nunca ve la respuesta que se usa para evaluarlo.
- **Agregación**: produce el resumen estructurado que llega a los agentes (nunca los eventos crudos completos).

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

El reporte final se persiste en SQLite (`data/historial.db`) y se sirve en dos formas, ambas derivadas del mismo estado final del grafo:

- **Estructurado** (JSON): expuesto por la API y por el modo de línea de comandos.
- **PDF**: documento único con plantilla propia (portada, una sección por página, serie temporal de eventos relevantes); la interfaz lo incrusta directamente, no lo vuelve a maquetar.

`LOG_PRESERVE_RAW` (default `true`) controla si la secuencia temporal persistida y exportada conserva el texto crudo o una versión redactada (IPs/usuarios/hosts enmascarados), con un hash SHA-256 del lote en su lugar. **No controla lo que se envía al LLM**: las muestras del prompt del Triage llegan a la API de Gemini sin pasar por esta variable, con `true` o con `false` — ver el comentario junto a su declaración en `src/config.py`.

## Pruebas

Suite determinista (`pytest tests/ -q`), sin costo de cuota de LLM ni credenciales reales — cubre agentes (con el LLM simulado), routers, el grafo compilado, preprocesamiento, memoria, y los endpoints de la API.

## Alcance y limitaciones conocidas

Por diseño (ver Capítulo 8 del informe, §8.7.2): no incluye despliegue productivo, integración con SIEM, ingesta en tiempo real, ejecución automática de comandos, ni fine-tuning del modelo de lenguaje. La validación final y la toma de decisiones operacionales quedan bajo responsabilidad humana — el sistema propone, no ejecuta.

Limitaciones técnicas conocidas, ya documentadas en el código: sin decodificador para logs de acceso web (ver "Preprocesamiento" arriba); variabilidad menor entre corridas idénticas pese a operar con temperatura 0; el enlace formal entre CVEs y técnicas MITRE ATT&CK no está implementado.
