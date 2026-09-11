# NODEX

> Nombre provisorio de repo para el **Proyecto de Título** (PUCV, Ingeniería Civil Informática).
> El nombre final del agente/sistema aún no está definido — hasta ahora se lo conoce como **"LogGuard Agent"** (nombre del Seminario de Título, sujeto a cambio).

> **Fuente de verdad de la especificación:** el **Informe de Seminario de Título** (`Informe_Seminario_Avance_Final 6.pdf`, sección 8 "Propuesta de Solución") define la arquitectura, el modelo LLM, y los requerimientos oficiales del sistema. El notebook `LLM_Agente_INICIO.ipynb` es solo el **prototipo de validación** que corroboró la viabilidad técnica del flujo — no la especificación. Donde el prototipo difiere del informe (p. ej. el modelo LLM usado), este repo sigue al informe y lo deja documentado.

Sistema multi-agente basado en LLMs para análisis semántico y reconstrucción narrativa de incidentes de ciberseguridad a partir de logs heterogéneos (sshd, apache, kernel, IDS).

## Qué hace

1. **Recibe** un lote de logs de seguridad.
2. **Agrega** de forma determinística (sin LLM) para no pasar miles de líneas crudas al modelo.
3. **Corrobora** todas las IPs distintas contra APIs de reputación (con caché).
4. **Diagnostica** el tipo de ataque con nivel de confianza.
5. **Propone** mitigación validada (comandos Linux).
6. **Escala** a analista humano si la confianza es baja (< 0.70).

## Arquitectura

Patrón **Plan-and-Execute real** (11-sep-2026 — antes de esa fecha el nombre era aspiracional: el diagrama de abajo con un nodo "PLANIFICADOR" existía en este README desde el principio, pero el grafo nunca lo implementó. Ver "Plan-and-Execute real" más abajo para la migración completa): se separa planificar de ejecutar, con una capa de agregación determinística antes de involucrar al LLM.

```
Entrada (lote de logs crudos)
 └─> AGREGACIÓN (código, sin LLM)
      └─> CORROBORACIÓN DE IPs (código + caché, AbuseIPDB)
           └─> agente_planificador (LLM) — plan de investigación sobre el resumen, no el log crudo
                └─> agente_analista_triage (LLM, [PLAN: triage]) ⇄ tool_consultar_rag (Tool, [PLAN: rag])
                     └─> agente_selector_herramientas (LLM, [interno]) ⇄ tool_consultar_cve (Tool, [PLAN: cve])
                          └─> agente_ingeniero_mitigacion (LLM, [PLAN: mitigacion]) ⇄ tool_validar_comandos (Tool, [interno])
                               └─> agente_auditor_final (LLM, [interno])
                                    └─> ¿cobertura suficiente? NO → replanifica (máx. 1 vez) | SÍ → SALIDA
                                         └─> FEEDBACK → memoria (ChromaDB)
```

Implementado como un `StateGraph` de **LangGraph** con **8 nodos** (5 LLM + 3 Tool) y **4 aristas condicionales (routers)**. De los 5 agentes LLM, `agente_planificador` es el único que no corresponde a un "paso" fijo de la propuesta original: genera el plan de investigación, con un vocabulario cerrado de 4 acciones planificables (`triage`, `rag`, `cve`, `mitigacion` — ver "Plan-and-Execute real" más abajo para por qué exactamente estas 4 y no las 7 del grafo).

| Nodo | Tipo | Función |
|---|---|---|
| `agente_planificador` | LLM | Genera el plan de investigación (qué analizar y en qué orden) ANTES del análisis especializado; replanifica si el ciclo no alcanza cobertura suficiente |
| `agente_analista_triage` | LLM | Analiza el resumen del lote; decide si necesita contexto histórico (RAG) |
| `tool_consultar_rag` | Tool | Recupera contexto histórico y técnicas MITRE ATT&CK relacionadas desde ChromaDB (ver "Integración MITRE ATT&CK" más abajo) |
| `agente_selector_herramientas` | LLM | Decide qué herramienta usar a continuación (mecanismo interno del grafo, no un paso del plan) |
| `tool_consultar_cve` | Tool | Consulta NVD por CVEs relacionados a los servicios afectados |
| `agente_ingeniero_mitigacion` | LLM | Propone comandos de mitigación |
| `tool_validar_comandos` | Tool | Valida los comandos propuestos (ciclo de corrección, máx. 2 intentos; mecanismo interno del grafo) |
| `agente_auditor_final` | LLM | Diagnóstico global, confianza, hipótesis alternativa, justificación, y si la cobertura alcanza para cerrar el ciclo (mecanismo interno del grafo) |

Routers: `router_triage`, `router_selector`, `router_validacion` (este último gestiona el ciclo de corrección de comandos, con `intentos_correccion` para evitar loops infinitos) y `router_finalizacion` (nuevo, 11-sep-2026 — decide si el ciclo termina o replanifica, acotado por `MAX_REPLANS`).

Checkpointer: `MemorySaver`.

## Plan-and-Execute real (11-sep-2026)

Hasta esta fecha, el nombre "Plan-and-Execute" era aspiracional: `MAX_PLAN_STEPS`/`MAX_REPLANS` existían en `config.py` sin un solo uso en el resto del código, no había ningún nodo planificador, y el diagrama de este mismo README con un paso "PLANIFICADOR" nunca correspondió al grafo real (7 nodos reactivos, cada router decidiendo solo con el resultado del nodo anterior). Esta sección documenta la migración a una arquitectura donde el plan es un artefacto real del estado, se usa durante la ejecución, y queda trazable.

**Vocabulario cerrado, más chico que el grafo.** El plan no es un espejo de los 8 nodos: solo tiene 4 acciones planificables (`triage`, `rag`, `cve`, `mitigacion`). `agente_selector_herramientas`, `tool_validar_comandos` y `agente_auditor_final` son mecanismos internos del grafo — siempre se ejecutan, quedan trazados en `historial_ejecucion`, pero el planificador nunca los genera como pasos: planificar "si conviene usar el selector" no tendría contenido, porque el selector siempre corre. De las 4 acciones planificables, `triage` y `mitigacion` son obligatorias (el LLM decide su `objetivo`, no si ocurren); `rag` y `cve` son la única inclusión/exclusión real.

**El plan gobierna, no solo acompaña.** Cada paso tiene un `estado` (`pendiente`/`ejecutado`/`omitido`/`fallido`) que se muta en vivo según lo que realmente ocurre en el grafo (`src/graph/plan_tracking.py::actualizar_plan`, invocada por el wrapper `_con_traza()` en `build_graph.py` sobre cada uno de los 7 nodos preexistentes, sin modificarlos). Una acción que se ejecuta sin estar contemplada en el plan (evidencia real la justifica pese a que el plan no la previó) **no se inserta retroactivamente**: queda registrada aparte, en `desviaciones_plan`, como una excepción explícita con acción/evidencia/motivo.

**Bug real corregido de paso: RAG ya no se consulta siempre.** `agente_analista_triage` fijaba `necesita_rag=True` de forma incondicional en su primera pasada, sin llamar al LLM — así que la memoria histórica se consultaba en el 100% de las corridas, sin importar si el lote lo justificaba. Ahora esa primera pasada es una decisión real del LLM, informada por si el plan incluyó un paso `rag` (ver `agente_analista_triage.py`).

**`paso_actual`** apunta al paso lógico que se ejecutó más recientemente, no "el primer pendiente": durante Triage → RAG → Triage, apunta a `rag` mientras ese nodo corre, y vuelve a `triage` en la segunda pasada — importante porque una misma etapa del plan puede implicar varias visitas a nodos.

**Replanificación acotada por `MAX_REPLANS`** (default 1): la decide `router_finalizacion`, el nuevo router tras `agente_auditor_final`, y combina la señal semántica del auditor (`cobertura_auditor`, el juicio crudo del LLM) con una verificación determinística propia sobre `state["plan"]` (¿quedó algún paso `fallido` o `pendiente`?) — nunca depende únicamente del booleano del LLM. `cobertura_suficiente` es la señal ya combinada que produce el auditor; `router_finalizacion` la revisa igual con su propio chequeo, como defensa adicional. El segundo plan recibe el plan anterior, `historial_ejecucion`, diagnóstico, contexto RAG, CVEs y la evaluación del auditor — no repite la misma entrada esperando una respuesta distinta (`agente_planificador.py::_construir_prompt`, modo replan). Al replanificar, `preparar_replanificacion()` reinicia el estado de control de la ejecución (`comandos_validos`, `cobertura_auditor`, `cobertura_suficiente` quedan en `None` — "no evaluado", nunca en `True` por defecto) y conserva la evidencia ya obtenida; el ciclo que termina se archiva en `historial_planes` antes del reinicio.

Sin infraestructura nueva: mismo `StateGraph` de LangGraph, mismo `MemorySaver`, mismo cliente LLM (`src/llm.py`). `MAX_TOOL_ITERS` se eliminó de `config.py` (0 usos en el código, apuntaba a un `src/legacy_agent.py` que nunca existió). Cobertura de tests: `tests/test_agente_planificador.py`, `tests/test_plan_tracking.py`, `tests/test_agente_analista_triage.py`, `tests/test_router_finalizacion.py`, `tests/test_build_graph.py`, y `tests/test_pipeline_plan.py` (el primer test end-to-end del grafo compilado vía `app.stream()`, incluido un caso que fuerza el tope de `MAX_REPLANS` y verifica que no hay loop infinito).

## Stack técnico

- **LangGraph** (`StateGraph`) para orquestación
- **Gemini** (`google-genai`, SDK directo) como LLM backbone. **Modelo especificado en el informe: `gemini-2.5-pro`**, temperatura 0 (sección 8.3.2, Tabla 8.2). El notebook prototipo corrió con `gemini-2.5-flash-lite` por costo/cuota durante el desarrollo — no es la especificación final. Configurable vía `LLM_MODEL_PRIMARY`/`LLM_MODEL_FALLBACK` en `.env`. **Nota (23-ago-2026, reconfirmada 1-sep-2026 con facturación activada):** la API key de Antonia no tiene acceso a `gemini-2.5-pro` (restricción de Google por antigüedad de cuenta, no una deprecación ni un límite de facturación — ver sección "Modelo LLM en la práctica" más abajo); el default operativo del repo es principal `gemini-3.1-pro-preview` con respaldo automático `gemini-3.6-flash`, con cuenta pagada.
- **ChromaDB**: 4 colecciones (`attack_patterns`, `error_memory`, `host_history`, `attack_techniques` — esta última poblada desde MITRE ATT&CK, ver "Integración MITRE ATT&CK" más abajo), embeddings `all-MiniLM-L6-v2` (384 dims)
- Herramientas externas: **AbuseIPDB** (reputación de IPs), **NVD** (CVEs)
- Umbrales: confianza **0.70**, auto-promoción **0.90**
- Python: pandas, matplotlib, xlrd (para el notebook de experimentos/baselines, no parte del stack oficial del agente — ver Tabla 8.9 del informe)

## Estructura del proyecto

```
NODEX/
├── src/
│   ├── config.py            # Variables de entorno y constantes (umbrales, modelos, límites)
│   ├── state.py             # LogGuardState: el TypedDict del grafo
│   ├── llm.py               # Cliente del LLM, con reintentos y manejo de cuota
│   ├── memory.py            # ChromaDB: 4 colecciones y el ciclo de feedback
│   ├── pipeline.py          # Punto de entrada: analizar_lote, el stream SSE y commit_feedback
│   ├── agents/              # Los 5 nodos LLM (planificador, triage, selector, mitigación, auditor)
│   ├── tools/               # Los 3 nodos Tool (RAG, CVE, validación) + agregación y evaluación
│   ├── preprocessing/       # Esquema v2: segmentación, decoders y enrichers por formato
│   ├── graph/
│   │   ├── build_graph.py   # StateGraph, los 4 routers y la compilación
│   │   ├── routers.py
│   │   └── plan_tracking.py # Trazabilidad determinística del plan (sin LLM)
│   └── api/                 # Backend web (FastAPI)
│       ├── main.py          # Endpoints: analizar, stream SSE, historial, PDF, feedback
│       ├── historial.py     # Persistencia de corridas en SQLite
│       ├── informe_pdf.py   # Generador del informe en PDF
│       └── static/index.html  # Interfaz anterior, sin build step
├── frontend/                # Interfaz en Next.js (ver "Interfaz en Next.js")
│   ├── app/                 # page.tsx (enrutado de vistas) y globals.css (sistema visual)
│   ├── components/          # Las 4 vistas, el armazón y el hook del análisis
│   └── lib/                 # Cliente de la API y catálogo de nodos
├── docs/                    # Plan de preprocesamiento, baseline y contrato de la API
├── notebooks/               # Notebook original de Colab, como referencia
├── data/                    # Caché de reputación, ChromaDB, historial (no se versiona el contenido)
├── results/                 # JSON de las corridas de evaluación
├── tests/                   # Tests deterministas por nodo, tool y endpoint
├── requirements.txt
├── .env.example
└── .gitignore
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env        # y completar las API keys
```

### API keys necesarias

| Variable | Servicio | Dónde obtenerla |
|---|---|---|
| `GEMINI_API_KEY` | Gemini (LLM backbone, ver "Modelo LLM en la práctica" para qué modelos exactos) | https://aistudio.google.com/apikey — cuenta Google; este proyecto corre con facturación activada (ver esa misma sección) |
| `ABUSEIPDB_API_KEY` | Reputación de IPs | https://www.abuseipdb.com/register — plan gratuito, 1000 consultas/día |
| `NVD_API_KEY` | Consulta de CVEs | https://nvd.nist.gov/developers/request-an-api-key — opcional sin key (rate limit bajo), recomendado con key (rate limit alto) |

**Nunca subir el archivo `.env` real a git.**

## Cómo correrlo

```bash
python -m pytest tests/ -v                              # tests deterministas (no requieren API keys)
python -m src.pipeline                                    # corre el grafo completo con un lote de logs de ejemplo (requiere .env con GEMINI_API_KEY)
python -m src.tools.log_runner data/logs/HDFS_2k.log      # corre el grafo sobre un archivo de logs real
python -m src.tools.log_runner data/logs/BGL_2k.log --no-guardar   # idem, sin guardar el resultado en results/
uvicorn src.api.main:app --reload                         # interfaz web (panel de análisis) — ver sección "Interfaz web" abajo
```

`src/pipeline.py` es el punto de entrada: agrega el lote, corre el grafo de 7 nodos con streaming paso a paso, y expone `analizar_lote()` / `commit_feedback()` para integrarlo en otro script o notebook. `src/tools/log_runner.py` (24-ago-2026) es un wrapper de línea de comandos sobre `analizar_lote()` para correrlo directamente contra un archivo de logs (en vez del lote de ejemplo hardcodeado en `pipeline.py`) — guarda un resumen curado del resultado (diagnóstico, confianza, comandos, formato detectado, distribución de servicios/eventos) en `results/<nombre>_<timestamp>.json`, salvo que se pase `--no-guardar`. `data/logs/` trae `HDFS_2k.log` y `BGL_2k.log` (muestras de LogHub, Tabla 8.11 del informe) listas para probar.

## Interfaz en Next.js (`frontend/`)

Interfaz definitiva: Next.js 16 + React 19 + Tailwind 4 + shadcn. Partió de un skeleton de diseño generado en v0 y se rehízo dos veces sobre referencias que eligió Antonia; esta sección describe el estado del 11-sep-2026. **No reemplaza todavía** a `src/api/static/index.html` (ver sección siguiente) — conviven hasta que se decida retirar la vieja.

```bash
# terminal 1 -- backend
uvicorn src.api.main:app --reload

# terminal 2 -- frontend
cd frontend && pnpm install && pnpm dev      # http://localhost:3000
```

El backend expone CORS para `http://localhost:3000` y `http://127.0.0.1:3000`, con `Content-Disposition` en `expose_headers` (el frontend lo lee para nombrar el PDF). La URL de la API se cambia con `NEXT_PUBLIC_API_BASE`; por defecto apunta a `http://127.0.0.1:8000`.

### Cuatro vistas

En `frontend/components/`, todas dentro del armazón de `app-shell.tsx`:

| Vista | Archivo | Qué muestra |
|---|---|---|
| Multiagente | `conversacion-view.tsx` | La ejecución como conversación con los 7 agentes |
| Resumen | `overview-view.tsx` | KPIs y actividad por día, desde el historial |
| Ejecuciones | `historial-view.tsx` | Tabla paginada de corridas anteriores |
| Informe | `report-view.tsx` | El PDF incrustado, más la revisión del analista |

### El análisis es una conversación

La carga del archivo y el avance del grafo son un mismo hilo: se ingresa el lote en el compositor de abajo y cada agente publica su mensaje a medida que corre. **No es decoración**: cada mensaje se arma con lo que ese nodo devolvió de verdad al estado, que es lo que trae el `detalle` del evento SSE. El triage publica su diagnóstico, el RAG cuántos precedentes encontró y qué técnicas, el selector su justificación, mitigación los comandos, el validador si aprobó y por qué no, y el auditor su evaluación con la confianza.

Eso vuelve legible el **recorrido no lineal**, que la barra de progreso de la versión anterior escondía detrás de un `x2`: se ve el triage salir sin diagnosticar porque le falta contexto, el RAG traer los precedentes, y el triage volver a hablar con el diagnóstico revisado. Es el proceso iterativo que pide el §8.7.1.

Para que el selector pueda explicarse hizo falta un cambio en el backend: `agente_selector_herramientas` devuelve ahora `razon_seleccion` al estado en vez de imprimirla y descartarla. Sin eso ese agente diría "sí" o "no" sin motivo, y la alternativa era que la interfaz inventara el texto.

**El hilo sobrevive a la navegación.** El estado vive en `use-analisis.ts`, un hook que se monta en el componente que enruta las vistas y no dentro de la conversación: si viviera ahí, ir a Resumen o a Ejecuciones desmontaría la vista y el hilo se perdería. Con el estado arriba, además, el `EventSource` sigue recibiendo mientras se mira otra pantalla, así que un análisis largo no se pierde por irse a revisar el historial.

**La zona de carga no es un campo de texto.** Tenía borde sólido, texto en color de *placeholder* y botón de enviar: la forma de un input de chat en el que no se puede escribir. Ahora el borde punteado, el icono de subida y el texto con aspecto de acción dicen que lo que se espera es un archivo; con uno elegido pasa a ser una ficha con su botón de quitar adentro. No se volvió escribible a propósito: eso exigiría un endpoint conversacional que el sistema no tiene, y quedaría un campo que acepta texto y lo ignora.

### El informe es el PDF

La vista del informe **incrusta el documento** (`?inline=1` en el endpoint del PDF) en lugar de maquetar el mismo contenido en HTML. Lo que se ve en pantalla es exactamente lo que se descarga, y desaparece la segunda maquetación que podía divergir del documento. El precio es que dentro del visor no hay nada interactivo, así que lo que no puede vivir en un PDF queda afuera como controles de la aplicación: descargar, abrir en otra pestaña, volver a la conversación y la revisión del analista.

El botón de volver al hilo aparece **solo** si el informe que se está viendo es el de la conversación en curso: volver desde una ejecución vieja llevaría a un hilo que no tiene nada que ver.

### El Resumen sale del historial

`GET /api/historial` alimenta cinco KPIs —ejecuciones registradas, con incidente, confianza promedio, escaladas a un analista y revisadas por un humano— y un gráfico de área con las ejecuciones por día. El gráfico es SVG propio (`area-chart.tsx`), sin librería, con interpolación monótona (Fritsch-Carlson): una spline cúbica común sobreimpulsa y dibujaría valores negativos donde el dato es cero.

Dos decisiones del gráfico que conviene no deshacer: los días sin ejecuciones se rellenan con cero —si no, comprimiría el tiempo y haría parecer continua una actividad que no lo fue— y la clave de día se calcula en hora **local**, porque con `toISOString()` una corrida de las 23:31 caía en el día siguiente mientras el límite "hoy" se calculaba en local, y el gráfico mostraba un día que todavía no existía.

### Sistema visual

Réplica de la referencia que eligió Antonia (11-sep-2026), con las reglas documentadas en la cabecera de `app/globals.css`:

1. **Fondo casi negro y cero sombras.** La separación la dan el color de superficie y un borde de 1px casi invisible; una sombra sobre ese fondo se ve como suciedad.
2. **El color se reserva para el estado.** Los neutros son neutros, el azul es solo acción y foco, y rojo/ámbar/verde solo severidad (`--crit`/`--warn`/`--ok`).
3. **Monoespaciado para todo lo que se lee como dato:** IPs, identificadores, marcas de tiempo, comandos, IDs de ATT&CK.
4. **Pesos livianos y mucho aire.** Nada por encima de 600, títulos en 500.

**La aplicación es una superficie centrada sobre un degradado azul**, con el fondo alrededor. Eso no fue solo estilo: obligó a que la superficie tenga altura fija y su propio scroll adentro, porque con `min-height: 100vh` y scroll de página todo lo pegajoso —la barra lateral, el compositor— se ancla al navegador y no al contenedor, y se salía de la superficie al desplazarse. El ancho del contorno es responsivo (`--app-max`, `--marco-aire`): a 1920 px la superficie mide 1260 px con 330 px de fondo por lado, y a 1200 px se reduce a 56 px para no perder ancho útil en las tablas.

No lleva marco de ventana: sin semáforos ni barra de menú. NODEX es una interfaz web, y ese decorado afirmaría una aplicación nativa que no existe.

### Detalles que conviene saber

- El límite de archivo que muestra la interfaz es el real del backend (`LOG_MAX_FILE_BYTES`, 50 MiB), no el "500 MB" que traía el skeleton.
- **El evento `final` del SSE no trae `job_id`** ni los datos del archivo, así que al recibirlo el frontend pide `GET /api/historial/{job_id}`: el mismo shape que consume el detalle del historial, para que el informe tenga una sola forma de entrada. Ver [`docs/contrato_api_frontend.md`](docs/contrato_api_frontend.md), que documenta los campos medidos contra respuestas reales.
- El veredicto se deriva de `hay_incidente`/`hay_anomalia`. **No se inventa un puntaje de riesgo** que el sistema no calcula.
- Las corridas anteriores **no se pueden reproducir como conversación**: solo se persisten el resumen del lote y el reporte final, no los eventos por nodo. Por eso el historial abre el informe y no el hilo.
- "Ajustes" está en la barra lateral pero inerte: el prototipo se configura por variables de entorno.
- `frontend/AGENTS.md` y `frontend/CLAUDE.md` los genera Next 16 en cada `pnpm dev`; borrarlos no sirve, vuelven a aparecer.

## Interfaz web anterior (panel de análisis, 1-sep-2026)

> **Nota.** Esta sección describe la interfaz **anterior**, la de `src/api/static/index.html`, que sigue en el repositorio y funcionando. La definitiva es la de la sección de arriba (`frontend/`). Lo que se menciona acá como "el panel" o "el panel de reporte" es de esta interfaz, no de la nueva.

`src/api/` agrega una interfaz web local (FastAPI + HTML/JS sin frameworks de frontend) sobre `src/pipeline.py`, pensada para demostración: subir un lote de logs, ver el grafo de 7 nodos ejecutarse en vivo (qué nodo está corriendo, qué devolvió, si entra al ciclo de RAG, CVE o de corrección de comandos) y el reporte final con confianza, diagnóstico, comandos de mitigación y CVEs. No reemplaza `log_runner.py` ni las corridas usadas para el informe — es una capa puramente visual sobre el mismo `analizar_lote()`.

```bash
pip install -r requirements.txt      # agrega fastapi, uvicorn, python-multipart
uvicorn src.api.main:app --reload
```

Abre `http://127.0.0.1:8000` en el navegador, sube un archivo de `data/logs/` (o cualquier lote de logs propio) y presiona "Analizar".

**Diseño técnico**:
- `src/pipeline.py` gana una función nueva, `analizar_lote_stream()`, generador que emite un evento por cada transición del grafo (`{"tipo": "nodo", "nombre": ..., "detalle": ...}`) en vez de solo devolver el resultado final como `analizar_lote()`. Ambas funciones comparten la misma preparación de estado inicial (`_preparar_estado_inicial()`, agregación + corroboración de IPs) para no duplicar lógica ni arriesgar que diverjan.
- El backend (`src/api/main.py`) expone `POST /api/analizar` (sube el archivo, devuelve un `job_id`) y `GET /api/stream/{job_id}` (Server-Sent Events: corre `analizar_lote_stream()` y transmite cada evento al navegador según ocurre). Se eligió SSE sobre WebSocket porque el flujo es unidireccional (servidor → navegador) — menos piezas que puedan fallar el día de la demostración.
- El frontend (`src/api/static/index.html`, un solo archivo, sin build step) dibuja la topología real del grafo (Triage → Selector → Mitigación → Validador → Auditor, con RAG y CVE como ramas condicionales) y resalta el nodo activo a medida que llegan los eventos; un nodo revisitado (p. ej. el Triage antes y después del RAG, o Mitigación en el ciclo de corrección) se marca con un contador (`×2`, `×3`, ...) en vez de perder la visita anterior.
- Verificado sin gastar cuota real: `analizar_lote_stream()` se probó con `llm_json` mockeado (dos escenarios — flujo con RAG+CVE, y ciclo de corrección de comandos rechazados→corregidos) para confirmar el orden de eventos emitidos y que el reporte final sea correcto y serializable a JSON, antes de aplicarlo al repo real.
- Limitación conocida: el `job_id` se consume al conectarse (`_JOBS.pop(...)`) y vive en memoria de un solo proceso — si el navegador se recarga a mitad de un análisis, o si se corre `uvicorn` con más de un worker, hay que subir el archivo de nuevo. Suficiente para demostración de un solo usuario; no es la arquitectura para un despliegue multiusuario.

### Historial de corridas (9-sep-2026)

Cada análisis lanzado desde el panel queda registrado en `data/historial.db` (SQLite de la librería estándar, ignorado por git como `data/chroma/`), de modo que se puede volver a mirar un resultado sin volver a correr el grafo — es decir, sin volver a gastar cuota de LLM. La sección "4. Historial de corridas" de la interfaz lista las corridas de la más reciente a la más antigua y, al hacer clic en una, reusa el mismo panel de reporte para mostrar el detalle.

- `src/api/historial.py` **solo almacena**: no sabe nada del grafo ni del LLM. El enganche vive en `src/api/main.py`, dentro del `finally` del generador SSE, para que una desconexión del navegador a mitad del análisis no pierda el resultado — el grafo igual corrió y gastó cuota.
- Endpoints: `GET /api/historial` (lista paginada) y `GET /api/historial/{job_id}` (detalle).
- Además de las columnas escalares, se guarda una copia íntegra del resumen del lote y del reporte final (`resumen_json`, `reporte_json`). Es lo que necesita el informe en PDF, que sin eso tendría que volver a correr el grafo para recuperar la ventana temporal, los servicios o la lista de comandos.

### Informe en PDF (`src/api/informe_pdf.py`)

`GET /api/historial/{job_id}/pdf` arma el documento a partir de lo ya persistido. **No genera contenido nuevo ni vuelve a correr el grafo**: emitir el informe no cuesta cuota. Con `?inline=1` responde `Content-Disposition: inline`, que es lo que permite a la interfaz incrustarlo; sin ese parámetro sigue siendo una descarga.

**Plantilla (11-sep-2026).** Réplica de la plantilla editorial que eligió Antonia: portada con el título en cuerpo grande y un bloque de datos al pie en dos columnas; encabezado corrido de dos líneas en cada hoja; cada sección en su propia página, con el título en versales y una regla gruesa debajo; cuerpo justificado en monoespaciado; y los datos en filas etiqueta/valor separadas por reglas finas. Blanco y negro.

Secciones, en orden: resumen del análisis (con el veredicto y la serie temporal), evidencia observada, secuencia temporal de los registros relevantes, técnicas MITRE ATT&CK, evidencias externas y precedentes, evaluación del auditor, mitigación propuesta y revisión del analista. Las que dependen de datos ausentes se omiten; la plantilla **no numera** las secciones, así que omitirlas no deja ningún hueco. Con el lote de BGL el documento sale de 9 páginas.

La serie temporal se dibuja con primitivas de fpdf2 —ejes, guías y la curva— y agrupa los registros relevantes por **posición en la secuencia**, no por reloj: las marcas de tiempo vienen en el formato de cada origen (`Sep  9 03:12:01` en auth-log, `2005-06-04-00.24.32` en BGL) y normalizarlas ahí sería reimplementar el parseo que el preprocesamiento ya hizo. Lo que la curva muestra es la concentración de los registros relevantes a lo largo del lote, que es la forma del incidente.

Tres limitaciones documentadas:

- **Tipografías.** La referencia usa una grotesca para los títulos y una monoespaciada de palo seco para el cuerpo. Con las fuentes base de fpdf2 los equivalentes son Helvetica y Courier: reproducen la *estructura* tipográfica (contraste sans/mono, versales, jerarquía por peso) pero no el dibujo de las letras. Empotrar las reales serían ~750 KB de binario en el repositorio.
- **Texto latin-1.** `fpdf2` se eligió por ser Python puro (sin binarios de sistema, coherente con el modelo de distribución autohospedado), pero sus fuentes base codifican en latin-1 y los diagnósticos del LLM traen raya (—), puntos suspensivos (…) y comillas tipográficas, que no existen ahí. Verificado el 9-sep-2026: `multi_cell()` lanza `FPDFUnicodeEncodingException` con cualquiera de ellos. Se resuelve mapeándolos a su equivalente ASCII (`sanear()`); los acentos del español sí están en latin-1 y se conservan intactos.
- **Corridas anteriores al 9-sep-2026** no tienen `resumen_json`/`reporte_json`: su informe se genera igual, pero declara explícitamente qué no se conservó en lugar de dejar la sección vacía.

### Feedback humano conectado a la memoria (9-sep-2026)

El panel de reporte —y el detalle de cualquier corrida del historial— cierra con "✅ Diagnóstico correcto" / "❌ Diagnóstico incorrecto" y un comentario opcional. `POST /api/feedback/{job_id}` guarda el veredicto en la tabla `corridas` y lo propaga a la memoria de largo plazo con `commit_feedback()` (`src/pipeline.py`). **Es una escritura real a ChromaDB**: cambia lo que el RAG le muestra al Triage en corridas futuras, y por eso la interfaz pide confirmación explícita antes de enviar.

Hasta esta fase `commit_feedback()` **no tenía ningún llamador** en el repositorio: el ciclo de feedback estaba implementado pero nunca se había ejercitado.

**Semántica del veredicto negativo.** `commit_feedback()` no distingue "correcto" de "incorrecto": distingue si recibe o no un `correccion`. Y con `correccion` igual llama a `commit_validated()`, que promueve a `attack_patterns` cuando la confianza supera `AUTO_PROMOTE` (0,90). Verificado con un stub que persiste en memoria de proceso, sobre una corrida real de confianza 1,00: marcar el diagnóstico como **incorrecto** lo dejaba igual como ejemplar few-shot del Triage — `attack_patterns` pasaba de 1 a 2 documentos. Es decir, el sistema aprendería el diagnóstico equivocado.

La capa web resuelve esto sin tocar `commit_feedback()`: el `correccion` que manda incluye `"confianza": 0.0`, y como la función mergea `{**reporte, **correccion}` **antes** de commitear, la promoción nunca se dispara. La corrida sí queda en `host_history`, para no perder la trazabilidad. Decisión de Antonia (9-sep-2026) entre las tres opciones medidas; `tests/test_api_feedback.py` fija tanto el argumento que manda el endpoint como el orden del merge del que depende la garantía, para que un cambio en `pipeline.py` no la rompa en silencio.

| Veredicto | `host_history` | `attack_patterns` | `error_memory` |
|---|---|---|---|
| ✅ correcto | + 1 | + 1 *(si confianza ≥ 0,90)* | — |
| ❌ incorrecto | + 1 *(confianza 0,00)* | — | + 1 *(con el comentario humano)* |

**Corridas sin firma.** `commit_feedback()` lee la firma del lote de `_firma`, y el historial no tiene columna propia para ella: viaja dentro de `reporte_json`. Las corridas anteriores a la Fase B no la conservan, y sin firma el documento que iría a ChromaDB sería la cadena vacía. En ese caso el veredicto se guarda igual en la tabla y la respuesta declara que no se propagó — se prefirió esto a rechazar el feedback o a reconstruir una firma que podría no coincidir con la que realmente se usó.

**Verificado contra la colección real** el 9-sep-2026, partiendo de las tres colecciones en 0 documentos. Un feedback positivo y uno negativo sobre dos corridas de prueba (`auth_muestra.log`, ajenas a los datos de evaluación) dejaron `attack_patterns`=1, `host_history`=2 y `error_memory`=1, con el contenido esperado en cada una: el positivo promovido con confianza 1,00, el negativo commiteado con 0,00 y su comentario humano en `error_memory`. Consultando después con la misma firma, `retrieve_examples()` devuelve el patrón (similitud 1,000) y `retrieve_corrections()` la corrección — **es la primera vez que el ciclo de feedback se ejercita de punta a punta con datos reales.**

*Nota:* esos documentos siguen en `data/chroma/`. Son de un lote sintético de prueba, así que una corrida de evaluación posterior sobre un lote parecido podría recuperarlos como few-shot; borrar la colección (`data/chroma/`) y repoblar solo `attack_techniques` con `preparar_mitre_attack.py` deja el estado limpio.


## Cobertura del alcance del informe (§8.7.1, 10-sep-2026)

Las siete capacidades del §8.7.1 están implementadas. Los ocho elementos que ese apartado exige en el reporte estructurado también, pero tres se cerraron el 10-sep-2026 porque faltaban o estaban a medias:

| Elemento del reporte (§8.7.1) | Dónde vive |
|---|---|
| Descripción general del evento | `diagnostico` |
| **Secuencia temporal de los registros relevantes** | `cronologia` — **agregado el 10-sep** |
| **Entidades involucradas** | `entidades` + `usuarios` — **usuarios agregados el 10-sep** |
| Hipótesis del incidente | `diagnostico`, `hay_incidente`, `hay_anomalia` |
| **Evidencias utilizadas** | CVEs, reputación, ATT&CK, y `precedentes` — **agregado el 10-sep** |
| Técnicas MITRE ATT&CK asociadas | `tecnicas_mitre` |
| Nivel de confianza | `confianza` + umbral de escalamiento |
| Acciones recomendadas | `comandos_mitigacion` + `comandos_validos` |

**Secuencia temporal.** Antes el reporte tenía la *ventana* del lote (inicio y fin) pero no una cronología, que es justo lo que sostiene el argumento de "reconstrucción del incidente". `cronologia` selecciona los registros que se apartan del comportamiento base del lote, en orden de aparición, con un extracto del registro. La selección es **determinística**: no interviene el LLM. La regla se define por exclusión —todo lo que no es `evento_generico`/`evento_normal`, más cualquier 4xx/5xx— para que un adaptador nuevo con etiquetas propias quede incluido por omisión en vez de perderse en silencio.

El tope es `CRONOLOGIA_MAX_EVENTOS` (40 por defecto) y lo recortado queda **declarado** en `cronologia_omitidos`: en BGL_2k son 40 mostrados y 103 omitidos de 143 eventos críticos; en HDFS_2k, 40 de 80. Es un tope de presentación, no de análisis — los conteos y distribuciones se siguen calculando sobre el lote completo.

**Cuidado con la fuga de ground truth.** La cronología reproduce texto del registro, y en BGL la etiqueta de anomalía del dataset **es el primer token de la línea**: copiar el crudo reabriría la fuga que cerró la Fase 7 del preprocesamiento y volvería circulares las métricas de detección. Hay dos defensas, y un test para cada una:

1. Para los formatos con etiqueta embebida en la línea, el mensaje se toma ya separado del flag (`_BglAdapter` expone `mensaje` en v1, `NormalizedEvent.message` en v2). Si no hay un mensaje separable, se declara la omisión en vez de caer al crudo.
2. `cronologia` y `entidades` **no llegan al prompt** del LLM: `resumen_prompt.py` las excluye. Son de la capa de presentación — el informe, el PDF y la interfaz.

**Códigos de respuesta.** El §8.7.1 los nombra entre los elementos a extraer y v1 no los guardaba (solo usaba `401|403` para contar fallos). `parse_log()` gana la clave `codigo_respuesta`, sin alterar ninguna de las claves previas ni la particularidad heredada del notebook que este README documenta. Se exige el marcador `HTTP/x.y` antes del número: en auth-log, HDFS o BGL abundan los números de tres cifras que son puertos, PIDs o ids de bloque, y tomarlos por códigos de respuesta sería inventar evidencia.

**Precedentes.** Los CVEs, la reputación de IPs y las técnicas de ATT&CK ya quedaban en el reporte; los patrones históricos que el RAG recuperó de ChromaDB, no — así que no era auditable qué precedentes influyeron en el diagnóstico. `precedentes` guarda una versión compacta (clasificación, confianza registrada, similitud, host) en vez del documento completo.

**Los dos motores exponen las mismas claves.** El informe, el PDF y la interfaz no deben cambiar de forma según `LOG_PREPROCESSING_ENGINE`; hay un test que lo fija.

### Lo que sigue fuera del alcance, a propósito

El §8.7.2 excluye explícitamente el despliegue productivo, la integración con SIEM, la ingesta en tiempo real, la ejecución automática de acciones, el parser universal, el fine-tuning, el análisis forense profundo y la generación de reglas SIEM. Nada de eso se implementó. Dos consecuencias concretas que conviene tener a mano:

- **La validación de comandos es básica por diseño**, como dice el propio alcance: 8 patrones destructivos y una lista blanca de 12 binarios en `src/tools/validation.py`. No es un sandbox.
- **El ciclo de corrección de comandos nunca se disparó con un LLM real.** `intentos_correccion > 1` en 0 de las corridas registradas: el validador aprobó siempre en el primer intento. El nodo existe y está cubierto con mocks, pero no hay evidencia empírica de ese camino.

## Informe vs. prototipo — qué manda dónde

| Aspecto | Informe (spec oficial) | Notebook (prototipo) | En este repo |
|---|---|---|---|
| Modelo LLM | `gemini-2.5-pro`, temp. 0 (§8.3.2, Tabla 8.2) | `gemini-2.5-flash-lite` (costo/cuota en desarrollo) | Principal `gemini-3.1-pro-preview` + respaldo automático `gemini-3.6-flash` (`LLM_MODEL_PRIMARY`/`LLM_MODEL_FALLBACK` en `.env`), cuenta pagada — `gemini-2.5-pro` bloqueado para la key actual (confirmado incluso pagando), ver sección "Modelo LLM en la práctica" |
| Nodos del grafo | 7 (4 LLM + 3 Tool), 3 routers (§8.2.3) | Igual | Igual — migrado 1:1 |
| Umbrales confianza | 0.70 escalar / 0.90 auto-promover (§8.2.4) | Igual | Igual |
| Memoria (ChromaDB) | 3 colecciones, `all-MiniLM-L6-v2`, k=3, similitud≥0.55 (§8.2.2, §8.3.1) | Igual | 4 colecciones — se agregó `attack_techniques` (MITRE ATT&CK/STIX, ver fila de abajo); resto igual |
| MITRE ATT&CK / STIX 2.1 | Entregable del Proyecto de Título (§8.7.2, §9); informe cita v15 | No implementado | Implementado (3-sep-2026), extendiendo `tool_consultar_rag` en vez de agregar un 8º nodo — apunta a la versión ACTUAL de ATT&CK: la corrida del 4-sep-2026 cargó **v19.2**, no la v15 que cita el informe (hay que actualizar esa cita en el texto); ver "Integración MITRE ATT&CK" |
| Dependencias | Tabla 8.9 (google-genai, chromadb, sentence-transformers, langgraph, requests, typing-extensions) | Igual + `!pip install langgraph graphviz` suelto | `requirements.txt` sigue la Tabla 8.9 + extras marcados aparte |

Cuando el notebook y el informe coinciden (arquitectura, nodos, routers, umbrales, memoria), la migración es fiel a ambos. Donde difieren (el modelo LLM es el único caso encontrado hasta ahora), este repo sigue al informe por ser la especificación formal, y lo deja documentado en el código (`src/config.py`) para que quede trazable.

## Modelo LLM en la práctica

El informe especifica `gemini-2.5-pro` (§8.3.2, Tabla 8.2) y el prototipo corrió con `gemini-2.5-flash-lite`. **Ninguno de los dos es ejecutable con la API key actual del proyecto — ni siquiera con facturación activada.** Esta sección documenta por qué y qué se usa en su lugar, para que la desviación quede trazable en la defensa.

### El bloqueo

Toda la serie 2.5 (`-pro`, `-flash`, `-flash-lite`) responde `404 NOT_FOUND` a `generateContent`:

```
This model models/gemini-2.5-pro is no longer available to new users.
Please update your code to use models/gemini-3.1-pro-preview for the
latest features and improvements.
```

**No es una deprecación**: es una restricción de capacidad de Google, que reserva la serie 2.5 para keys que ya la habían usado antes (confirmado por Google en su foro oficial). Confirmado **dos veces**, con dos keys distintas: la primera vez en tier gratuito (23-ago-2026), y de nuevo el 1-sep-2026 con la key **ya con facturación activada** — pagar no destraba el acceso, así que la restricción es por antigüedad/capacidad de la cuenta, no por tipo de tier. No hay configuración de cuenta que lo destrabe. Detalle a tener en cuenta: `models.list()` **sí lista** `gemini-2.5-pro` aunque rechace las llamadas, así que listar modelos no sirve para saber qué se puede usar realmente — hay que invocarlos.

### Decisión final (1-sep-2026): modelo principal + modelo de respaldo

Con facturación activada (sin los límites de cuota del tier gratuito) se pudieron medir 6 corridas reales completas (7/7 nodos, HDFS y BGL) contra los candidatos disponibles. En vez de fijar un único `LLM_MODEL`, el sistema define dos y cambia entre ellos automáticamente (ver `_generate_con_fallback` en `src/llm.py` y "Manejo de cuota" abajo) — así una demanda alta o una falla del modelo principal no tumba el análisis completo.

| | Modelo | Rol | Corridas reales | Confianza | Costo por lote (2000 líneas) | Extrapolado al §9 (HDFS 11,2M + BGL 4,7M líneas) |
|---|---|---|---|---|---|---|
| **Principal** | `gemini-3.1-pro-preview` | Mejor calidad/estabilidad medida | 2/2 sin fallas | 0.95 en ambas | ≈ USD 0.051 | ≈ USD 406 |
| **Respaldo** | `gemini-3.6-flash` | Se activa si el principal no responde o se queda sin cuota | 4/4 sin fallas | 0.90–0.95 | ≈ USD 0.014 (≈ 3.4× más barato) | ≈ USD 120 |

`gemini-3.7-flash` (el default anterior a esta decisión, usado entre el 23-ago y el 1-sep) queda descartado como default: fue el **único** modelo que falló en esta ronda de pruebas reales — una solicitud tardó 86s en responder a un prompt trivial, inmediatamente después de un 503 de 64s, un patrón de inestabilidad que ninguno de los otros dos candidatos mostró. Sigue siendo una opción válida vía `.env` si se necesita reproducir corridas anteriores.

Ambos se fijan por versión explícita, no por alias tipo `gemini-flash-latest` — los alias se reapuntan solos, y métricas reportadas con un alias dejan de ser reproducibles en cuanto Google lo rote.

### Cómo se activa el respaldo

`llm_json()` (en `src/llm.py`) llama primero al modelo **principal**. Si este agota sus reintentos por un error **reconocido** — cuota diaria agotada, cuota por minuto agotada, o un error transitorio (503/SSL/timeout) tras el backoff completo — reintenta automáticamente, una vez completo, con el modelo de **respaldo**, antes de darse por vencido. Un error **no reconocido** (p. ej. un 400 por un prompt mal formado — un bug de código, no de disponibilidad del modelo) se relanza de inmediato sin probar el respaldo: cambiar de modelo no arregla un bug. Si el respaldo también falla, se propaga su propio error. Verificado con 5 tests dedicados en `tests/test_llm.py` (mock de `generate_content` que distingue el modelo llamado por el argumento `model=`) — ver "Manejo de cuota" abajo.

### Tier gratuito vs. pagado

Antonia activó facturación el 1-sep-2026, principalmente para eliminar los límites de cuota del tier gratuito y tener modelos consistentes entre corridas (en el tier gratuito, varios candidatos devolvían 429 antes de completar una corrida). Efecto secundario relevante para el informe: en el tier pagado, a diferencia del gratuito, Google **no** usa los prompts/respuestas para mejorar sus productos ni los revisa con anotadores humanos — dato relevante porque el sistema procesa logs de seguridad (IPs, usuarios, estructura de infraestructura). Esto se cruza con el modelo de distribución autohospedado (ver más abajo): el cliente trae su propia key, así que hereda esta misma decisión y conviene advertírselo.

### Cómo cambiarlo

Dos líneas en `.env`, sin tocar código — `src/config.py` lee `LLM_MODEL_PRIMARY`/`LLM_MODEL_FALLBACK`:

```
LLM_MODEL_PRIMARY=gemini-3.1-pro-preview
LLM_MODEL_FALLBACK=gemini-3.6-flash
```

Si en algún momento la key obtiene acceso a `gemini-2.5-pro`, basta con ponerlo como principal para igualar el informe exactamente.

### Riesgo de fondo

Esto va a volver a pasar: el ciclo de vida de los modelos de Gemini es más corto que el de un Proyecto de Título — la serie 2.5 quedó inaccesible **durante** el proyecto, y a la 3.x le pasará lo mismo (de hecho `gemini-3.7-flash` ya mostró señales de inestabilidad en menos de dos semanas de uso). El mecanismo de principal+respaldo mitiga el síntoma (un modelo caído no tumba el sistema), pero no reemplaza la recomendación metodológica: que el informe especifique el *tier* y las *propiedades* requeridas (temperatura 0, salida JSON estructurada, ventana de contexto suficiente) y reporte el ID exacto usado en cada corrida como dato experimental, en vez de clavar un ID de modelo en la Tabla 8.2.

## Manejo de cuota y errores transitorios de la API

`src/llm.py` (`_generate_con_backoff`) distingue estos tipos de fallo al llamar a Gemini, cada uno con una respuesta distinta:

- **429, cuota DIARIA** (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, límite 20/día en tier gratuito): se relanza de inmediato, sin reintentar — no se repone en segundos, y reintentar solo arriesga gastar más cuota. En `_generate_con_fallback` (ver abajo), este es uno de los errores que sí activa el modelo de respaldo.
- **429, cuota POR MINUTO** (`GenerateRequestsPerMinutePerProjectPerModel-FreeTier`): se reintenta hasta `MAX_REINTENTOS_CUOTA_MINUTO` veces (default 3), esperando el `retryDelay` que el propio error de Google sugiere — es recuperable en segundos, a diferencia de la diaria.
- **503 / `UNAVAILABLE`** (sobrecarga transitoria del lado de Google) y **errores de transporte a nivel de red/TLS** (p. ej. `[SSL: UNEXPECTED_EOF_WHILE_READING]`, un corte de conexión a mitad de la respuesta, o una solicitud que se cuelga más de `TIMEOUT_SOLICITUD_SEG`): reintenta con backoff exponencial (hasta `MAX_REINTENTOS_TRANSITORIO` veces, default 5, `BACKOFF_INICIAL` × 2 cada vez hasta un techo `BACKOFF_MAX`, con jitter proporcional `BACKOFF_JITTER` para no sincronizar reintentos concurrentes) — comparten el mismo camino, ver hallazgo abajo.

**Hallazgo real (25-ago-2026)**: hasta esta fecha, el código trataba CUALQUIER 429 como la cuota diaria — terminal, sin reintentar. La primera corrida real end-to-end sobre `HDFS_2k.log` murió por eso: pegó el límite de 5 solicitudes/minuto (no el de 20/día) y abortó de inmediato, aunque el propio error traía `retryDelay: '1s'` diciendo que era recuperable. El `quotaId` que trae cada error distingue ambos casos (`...PerDay...` vs `...PerMinute...`) — `_tipo_error_cuota()` lo lee y separa los dos caminos; `_es_error_de_cuota()` se mantiene solo por compatibilidad hacia atrás (ya no se usa en `_generate_con_backoff`).

**Segundo hallazgo real (26-ago-2026)**: durante las corridas reales de ese día (ver "Primera corrida completa de punta a punta" abajo), una de las seis fallidas murió con `[SSL: UNEXPECTED_EOF_WHILE_READING]` — un corte de la conexión TLS, sin código HTTP (`.code`/`.status_code` vienen `None`). `_es_error_transitorio()` solo reconocía 503 por código o texto, así que este error —de los vistos ese día, el más claramente recuperable, un corte de socket y no un problema del servicio— no se reintentaba nunca. **Fix**: se reconoce también por tipo de excepción (`ssl.SSLError`, `ConnectionError`, `TimeoutError`, y `httpx.TransportError` si `httpx` está disponible) y, como respaldo, por texto del mensaje.

**Endurecimiento del reintento (1-sep-2026)**, ya con cuenta pagada y sin las restricciones del tier gratuito: `MAX_REINTENTOS_TRANSITORIO` subió de 2 a 5, se agregó un techo `BACKOFF_MAX` (30s por default) para que una racha larga de 503 no produzca esperas de minutos, jitter proporcional `BACKOFF_JITTER` (±25% por default, vía `_espera_con_jitter()`) para que reintentos concurrentes de varios nodos del grafo no se sincronicen entre sí, y un `TIMEOUT_SOLICITUD_SEG` explícito (300s por default, antes no había ninguno) para el caso de una solicitud que se cuelga sin fallar ni responder — el mismo patrón que motivó descartar `gemini-3.7-flash` como default (ver "Modelo LLM en la práctica").

**Modelo principal + modelo de respaldo (1-sep-2026)**: `_generate_con_fallback()` envuelve a `_generate_con_backoff()` — llama primero contra `LLM_MODEL_PRIMARY`, y si este agota sus reintentos por cuota (diaria o por minuto) o por un error transitorio, reintenta una vez completo contra `LLM_MODEL_FALLBACK`. `llm_json()` llama a `_generate_con_fallback()`, no directamente a `_generate_con_backoff()`. Ver "Modelo LLM en la práctica" arriba para la decisión de qué modelo va en cada rol y los datos medidos.

Esto es independiente del reintento existente por JSON inválido (`retries` en `llm_json()`, migrado del notebook) — son mecanismos distintos que conviven en la misma función.

`tests/test_llm.py` (17 tests) verifica los cuatro caminos de reintento (429 diario, 429 por minuto, 503, error de transporte), el techo y el jitter del backoff, y el mecanismo de respaldo (5 tests: uso del principal por default, activación ante error transitorio agotado, activación ante cuota diaria, ausencia de activación ante un error no reconocido, y propagación del propio error del respaldo si también falla) — mockeando `client.models.generate_content` y `time.sleep` según el `model=` recibido, sin llamar a la API real ni esperar tiempo real.

### Instrumentación de costo real en tokens

`llm_json()` imprime `entrada`/`salida`/`razonamiento`/`total` de `resp.usage_metadata` en cada llamada (25-ago-2026, ya no es temporal — se decidió mantenerla permanente por lo que reveló). Con datos reales de la primera corrida parcial sobre HDFS/BGL (25-ago-2026, antes del fix de costo):

| Nodo | Entrada | Salida | Razonamiento | Total |
|---|---|---|---|---|
| HDFS triage | 58.289 | 147 | 301 | 58.737 |
| HDFS selector | 279 | 47 | 150 | 476 |
| BGL triage | 1.096 | 190 | 323 | 1.609 |
| BGL selector | 319 | 50 | 442 | 811 |

**Hallazgo importante**: 58.289 vs. 1.096 tokens de entrada en el triage, para lotes del mismo tamaño (2000 líneas cada uno). La diferencia no es el volumen de logs — es la cardinalidad de IPs: HDFS tiene 202 IPs distintas, BGL tiene 2, y `agente_analista_triage` serializaba `por_ip` completo (con todas las IPs) en el prompt. El costo del sistema escala con la cantidad de IPs distintas del lote, no con el número de líneas. Para la evaluación formal del §9 sobre HDFS completo (~11M líneas, con muchas más IPs distintas que la muestra de 2k), esto podía ser el costo dominante — a ese ritmo, cientos de dólares en vez de centavos.

**Fix aplicado (25-ago-2026)**: `src/tools/resumen_prompt.py`, función `acotar_resumen_para_prompt()`. Antes de armar el prompt de triage, el resumen se acota a las `TOP_N_IPS_PROMPT` (config, default 20) IPs más activas por `n_eventos`, más cualquier IP con reputación AbuseIPDB "sospechoso"/"malicioso" aunque tenga poca actividad (una IP maliciosa de bajo volumen es justo el caso que no se puede permitir esconder). El resto se agrega en un solo campo `ips_resumidas` (cantidad, total de eventos, total de intentos fallidos) — el LLM sigue sabiendo que existen, sin gastar un token por cada una. `n_ips_distintas` nunca se trunca: el LLM siempre ve la escala real del incidente, aunque el detalle esté acotado. Esto solo afecta el texto que arma `agente_analista_triage` — `state["resumen_logs"]` y el JSON final en `results/` conservan el desglose completo por IP. `tests/test_resumen_prompt.py` (6 tests) verifica el acotamiento, que `n_ips_distintas` no se trunca, la agregación del resto, y el caso de la IP maliciosa de baja actividad — determinista, sin llamar al LLM.

**Confirmado con una corrida real (26-ago-2026)**: el triage de HDFS bajó de 58.289 a 8.271 tokens de entrada (−86 %), mismo lote de 2000 líneas y 202 IPs. Medido también en frío contra el resumen completo sin correr el grafo: ~23.300 → ~3.100 tokens (−87 %) en HDFS, BGL sin cambio (0 % — con solo 2 IPs no hay nada que acotar). El fix ataca el problema en la proporción esperada.

## Primera corrida completa de punta a punta (26-ago-2026)

Después de dos intentos que murieron por 429 por-minuto/503 (25-ago-2026, sección anterior) y de seis intentos fallidos más durante el día siguiente por una racha severa de 503 intermitentes del lado de Google (la corrida más lejos que llegó con `gemini-3.7-flash` fue 6 de 7 nodos, murió en `agente_auditor_final`), **`HDFS_2k.log` y `BGL_2k.log` completaron el grafo entero por primera vez**, con LLM real, sobre los dos datasets del informe.

**Advertencia sobre el modelo**: `gemini-3.7-flash` (el modelo de registro en `.env`) agotó su tope diario de 20 requests durante los intentos previos del mismo día. Estas dos corridas completas se hicieron con `gemini-3.5-flash` por variable de entorno, sin tocar `.env` — que sigue en `gemini-3.7-flash`. El costo estimado más abajo aplica precios de `gemini-3.7-flash` a tokens medidos con `gemini-3.5-flash` (cuentan como proxy razonable, no como cifra oficial). Si el informe necesita las cifras con el modelo especificado, hay que repetir la corrida cuando la cuota de `gemini-3.7-flash` resetee.

Orden de nodos, idéntico en ambas corridas: `triage → tool_consultar_rag → triage → selector → mitigación → tool_validar_comandos → auditor → END`. `tool_consultar_cve` quedó fuera de las dos — el selector decidió `usar_cve: False` con justificación correcta (ningún software con versión identificable en estos logs).

| | HDFS_2k | BGL_2k |
|---|---|---|
| Confianza | 0.95 | 0.90 |
| `requiere_revision_humana` | false | false |
| Comandos de mitigación | 3, aprobados | 5, aprobados |
| Ciclo de corrección | no se disparó | no se disparó |

Ambas superan el umbral de auto-promoción (0.90) — se promoverían a `attack_patterns` si se llamara `commit_feedback()`.

**HDFS** — diagnóstico: "comportamiento operativo normal y distribuido […] Los identificadores reportados como 'usuarios_objetivo' corresponden en realidad a bloques de datos de HDFS (block IDs). […] No se observan patrones de intrusión, exfiltración ni fuerza bruta." El auditor detectó explícitamente el falso positivo que se corrigió el 24-ago-2026 al construir el adaptador HDFS, y lo dijo en su propia justificación: "El diagnóstico es sumamente preciso al identificar que los supuestos 'usuarios_objetivo' son en realidad identificadores de bloques de HDFS (block IDs), evitando un falso positivo común." — el adaptador y el auditor se refuerzan entre sí, y ahora quedó registrado en una corrida real, no solo en un test. Comandos: tres reglas iptables que restringen HDFS a los rangos internos esperados y bloquean el resto.

**BGL** — diagnóstico: "no se observan indicios de un ataque cibernético externo dirigido […] apunta a fallos operativos, de conexión o de hardware distribuidos en los nodos", concentrado en la IP interna `172.16.96.116`. Más calibrado que los intentos previos del día (que leían "posible escaneo interno horizontal / propagación lateral"), pero **la limitación de interpretabilidad documentada el 25-ago-2026 sigue presente**: el diagnóstico sigue tratando a `172.16.96.116` como origen de la anomalía, cuando en el log aparece como destino de sockets `ciod` — dato relevante para la sección de evaluación de precisión del §9, ahora con evidencia de una corrida real completa, no solo parcial.

`intentos_correccion: 1` en ambas NO significa que se ejercitó el ciclo de corrección — es el contador de la primera pasada de `agente_ingeniero_mitigacion`, y el validador aprobó los comandos a la primera en las dos. El camino mitigación↔validador (`router_validacion`) sigue sin dispararse en una corrida real — solo está probado con el LLM mockeado en `tests/test_ciclo_correccion.py`.

**Costo real medido (corrida completa, 7 llamadas por lote incluyendo el reintento de triage vía RAG)**:

| Nodo | HDFS entrada/salida/razonamiento | BGL entrada/salida/razonamiento |
|---|---|---|
| triage | 8.271 / 187 / 822 | 1.096 / 215 / 744 |
| selector | 313 / 81 / 201 | 338 / 71 / 435 |
| mitigación | 228 / 271 / 1.902 | 256 / 180 / 1.392 |
| auditor | 503 / 161 / 949 | 436 / 148 / 1.023 |
| **Total** | **9.315 entrada / 4.574 salida** | **2.126 entrada / 4.208 salida** |

A precio de `gemini-3.7-flash`: ≈ USD 0,024 por lote HDFS, ≈ USD 0,017 por lote BGL (2000 líneas cada uno). Extrapolado al HDFS completo del informe (~11,2M líneas, ~5.600 lotes de este tamaño): **≈ USD 135** — un número planificable para el §9, y muy por debajo de lo que habría salido sin el acotamiento de costo (el triage solo, sin acotar, ya costaba más que esto por lote).

El razonamiento domina el costo de salida en mitigación: 1.902 tokens razonando vs. 271 respondiendo — un estimado basado solo en `candidates_token_count` (sin sumar `thoughts_token_count`) subestimaría el gasto real de ese nodo en ~7×. Gemini 3.x factura los tokens de razonamiento a precio de salida, así que cualquier estimación de costo debe incluirlos.

## Parsing multi-formato de logs (HDFS, BGL, y el resto de la Tabla 8.11)

El prototipo del Seminario validó el flujo agéntico completo, pero solo sobre logs estilo auth-log (sshd/Apache/kernel/IDS) — el formato para el que `parse_log()` fue diseñado (§8.2.1 del informe). El informe también nombra explícitamente HDFS y BGL como datasets de evaluación (Tabla 8.11, §8.6 Escenario A), que son formatos completamente distintos (logs de sistema distribuido y de supercomputador, sin usuarios ni auth). Al recibir muestras reales de ambos (`HDFS_2k.log`, `BGL_2k.log`, 23-ago-2026) se confirmó que el parser original no los procesaba de forma útil:

- Ningún timestamp de ninguno de los dos formatos matcheaba `TS_RE` (que espera el formato syslog `Aug 23 20:36:15`) → `ventana_temporal` quedaba vacía.
- HDFS caía 100% en `servicio="desconocido"` (sus líneas no contienen "sshd"/"apache"/"kernel"/"ids").
- **Falso positivo real**: la regex de usuario captura la palabra después de `"for"` — en HDFS, la frase omnipresente `"PacketResponder ... for block blk_123..."` producía `usuario="block"` para prácticamente cada línea.
- En BGL, la señal de anomalía real (el vocabulario de fallo es totalmente distinto a "failed password"/"401"/"403") era invisible para el clasificador de eventos — un lote de BGL entero habría reportado ~0 eventos críticos sin importar cuántas alertas reales contuviera.

Esto no era un bug de migración — es que el Proyecto de Título (a diferencia del Seminario) requiere que el sistema lea "logs de distintos tipos" (título del proyecto: análisis semántico), y el preprocesamiento determinístico necesitaba generalizarse para eso.

**Diseño**: `src/tools/aggregation.py` ahora tiene una capa de **adaptadores por formato** (`_AuthLogAdapter`, `_HdfsAdapter`, `_BglAdapter`). `aggregate_logs()` detecta el formato **una vez por lote** (sobre una muestra de hasta 50 líneas, no línea por línea — un lote real es homogéneo en su origen) y usa el adaptador correspondiente para todas las líneas. Si ningún adaptador reconoce el formato con confianza ≥ 0.5, cae al adaptador auth-log — el mismo comportamiento que había antes de este cambio — para no regresionar sobre formatos aún no soportados. El resumen ahora incluye `formato_detectado` (`"auth_log"` | `"hdfs"` | `"bgl"`), útil para trazabilidad.

- **HDFS**: timestamp `081109 203615` → `2008-11-09 20:36:15`; servicio normalizado por clase Java (`hdfs.datanode`, `hdfs.fsnamesystem`, `hdfs.fsdataset`, `hdfs.datablockscanner`); el "usuario" pasa a ser el `blk_...` (block id) de la línea, no un nombre de persona; evento crítico si el nivel es WARN/ERROR/FATAL (heurística — HDFS no trae una etiqueta de anomalía ground-truth por línea en el archivo crudo).
- **BGL**: timestamp legible ya viene en la línea (`2005-06-03-15.42.50.675872`); servicio normalizado por subsistema RAS (`bgl.kernel`, `bgl.app`, `bgl.mmcs`, `bgl.discovery`, `bgl.hardware`); "usuario" pasa a ser el id de nodo del clúster (p. ej. `R02-M1-N0-C:J12-U11`). El evento crítico usa el **flag de alerta real del dataset** (primer campo de la línea: `"-"` = no-alerta, cualquier otro valor = alerta) — es la convención estándar de BGL/LogHub, así que no se infiere por texto libre, se lee directo.
- **Verificado contra los archivos reales** (23-ago-2026): sobre `HDFS_2k.log`, 0 falsos positivos de `usuario="block"`, 80 eventos críticos (coincide exacto con las 80 líneas WARN del archivo). Sobre `BGL_2k.log`, 143 eventos críticos — coincide exacto con las 143 líneas cuyo flag de alerta no es `"-"` en el archivo real.
- **Límite conocido, no resuelto todavía**: algunas líneas de BGL (~2% de la muestra) no traen el token literal `"RAS"` en la posición esperada (usan `"NULL DISCOVERY ..."` en su lugar, típicamente eventos de descubrimiento de hardware) y caen en `servicio="bgl.otro"` en vez de `"bgl.discovery"`/`"bgl.hardware"`. Solo afecta la etiqueta de servicio de esas líneas puntuales — **no** la señal de anomalía: el flag de alerta (primer campo de la línea) se lee directamente del texto crudo antes de intentar el match completo, así que una línea de este tipo con flag de alerta real igual se cuenta como `evento_critico` (corregido 24-ago-2026 tras una verificación que encontró que la versión anterior sí podía perder esas alertas — ver `tests/test_aggregation_multi_formato.py`; confirmado con 0 casos perdidos en `BGL_2k.log`, 38 líneas de este tipo, ninguna con flag de alerta).
- **Efecto secundario a tener en cuenta**: `tool_consultar_cve.py` usa el primer `servicio` del lote como palabra clave de búsqueda en NVD. Para auth-log eso da buenos resultados ("sshd", "apache"); para `"hdfs.datanode"` o `"bgl.kernel"` probablemente no — es un punto a refinar cuando se trabaje la búsqueda de CVEs sobre estos datasets, no bloqueante para el resto del flujo.
- **Tests**: `tests/test_aggregation_multi_formato.py` — cubre detección de HDFS, detección de BGL con el flag de alerta como ground truth, fallback a auth-log ante un formato no reconocido, y que el comportamiento auth-log original no cambió (regresión).
- **Limitación documentada, no un bug de parsing (25-ago-2026)**: en la primera corrida real sobre `BGL_2k.log`, el LLM de triage afirmó que "tráfico anómalo" se originaba **desde** la IP `172.16.96.116` — pero esa IP aparece en el log como el **destino** del socket en los mensajes `ciod: failed to read...` (`CioStream socket to 172.16.96.116:...`), no como origen. El parser extrae la IP presente en el mensaje sin registrar su rol (origen/destino) — no hay esa noción en el formato BGL crudo — y el LLM, al razonar sobre un resumen sin esa información, asumió un rol que no está respaldado por el dato. Es un caso concreto de sobre-interpretación semántica cuando el formato de origen no es auth-log (donde "from IP" sí es explícito en el texto). Vale como hallazgo para la discusión de limitaciones del informe (relacionado con lo que el SLR encontró sobre interpretabilidad/XAI, §7.6.3) — no se intentó corregir todavía; una mitigación posible y acotada sería que el prompt de triage advierta explícitamente que el rol de las IPs no está garantizado fuera de logs auth-log.

## Evaluación cuantitativa de detección — Precisión/Recall/F1 (§8.6.2, 3-sep-2026)

El §8.6.2 del informe define métricas estándar de clasificación binaria (Precisión, Exhaustividad/Recall, F1-Score) para evaluar la capacidad del agente de diferenciar tráfico normal de actividad anómala. Las corridas completas anteriores (ver "Primera corrida completa de punta a punta") dan evidencia cualitativa de que el pipeline funciona, pero son **una sola muestra por dataset** — no alcanzan para calcular una métrica que necesita varios casos positivos y negativos independientes. `src/tools/eval_deteccion.py` cierra esa brecha: arma varios **lotes de control** con verdad-terreno (ground truth) conocida, corre `analizar_lote()` real sobre cada uno, y compara el veredicto del agente contra esa verdad-terreno.

### Ronda 1 — bug real (3-sep-2026): `confianza` no es un puntaje de anomalía

La primera versión de este script clasificaba un lote como "anómalo" si `confianza >= CONFIDENCE_THRESHOLD` (0.70). Es un proxy incorrecto: `confianza` mide qué tan seguro está el **auditor de su propio análisis**, no si ese análisis concluye que hay un incidente — un diagnóstico de "todo normal" bien fundamentado da confianza alta igual que uno de "esto es un ataque" bien fundamentado. Confirmado en la primera corrida real (4 lotes de BGL): **precisión 0.25 / recall 1.00**, exactamente lo que da un clasificador que predice "anómalo" siempre — en `bgl_ventana_0005` el auditor escribió *"comportamiento normal del sistema sin anomalías […] es correcto y esperado que no se sugieran comandos"* con confianza 1.00, y la regla vieja lo contaba como incidente detectado.

**Fix 1**: `agente_auditor_final` ahora devuelve un campo nuevo, `hay_incidente: bool`, un veredicto explícito e independiente de `confianza`.

### Ronda 2 — bug real, mismo día: la etiqueta de BGL/HDFS no es "incidente de seguridad", es "anomalía de sistema"

Con `hay_incidente` ya en uso, la corrida real sobre BGL dio **recall 0.0** — y el auditor tenía razón: distinguió correctamente un problema real de hardware/kernel de un ataque (*"al tratarse de un problema de estabilidad y mantenimiento de hardware, no constituye un incidente de seguridad, aunque sí una anomalía operativa que requiere atención del equipo de infraestructura"*, con 7 comandos de diagnóstico propuestos — `mcelog`, `edac-util`, `ipmitool`, `smartctl`). El problema es de definiciones, no de razonamiento: BGL y HDFS son benchmarks de **anomalías de sistema** (fallos de hardware, errores de replicación), no de seguridad — con la pregunta "¿es un incidente de seguridad?", ambos datasets iban a dar recall ≈0 de forma sistemática sin importar qué tan bien razone el modelo. El único dataset de la Tabla 8.11 con ground truth de seguridad real es UWF-ZeekDataFall22 (trae tácticas MITRE), aún sin adaptador implementado.

**Fix 2**: se agregó un segundo campo, `hay_anomalia: bool` — "¿el sistema se comporta de forma anómala u operacionalmente irregular, sea o no un problema de seguridad?" — junto a `hay_incidente`, que sigue preguntando específicamente por seguridad. `eval_deteccion.py` ahora usa el campo que corresponde a lo que cada dataset realmente etiqueta (`CAMPO_VEREDICTO_POR_DATASET`): `hay_anomalia` para BGL y HDFS, `hay_incidente` por defecto para cualquier dataset no listado (p. ej. UWF cuando se implemente). Ambos fixes tocaron: `LogGuardState`, el prompt del auditor, el reporte final de `analizar_lote`/`analizar_lote_stream`/`log_runner.py`, y `eval_deteccion.py` (`_prediccion_desde_estado()` ahora toma un parámetro `campo`, con `confianza` — o `hay_incidente` para el respaldo de `hay_anomalia` — como respaldo solo si el campo viniera ausente). Verificado con tests nuevos en `tests/test_agente_auditor_final.py` (7 tests: que `confianza`/`hay_incidente`/`hay_anomalia` no se confunden entre sí, en todas las combinaciones, incluyendo el caso exacto de la anomalía de hardware) y en `tests/test_eval_deteccion.py` (que `correr_evaluacion("bgl", ...)` usa `hay_anomalia` automáticamente y corrige el recall 0.0 — confirmado también con un mock end-to-end que reproduce el escenario real).

### Ronda 3 — primeros números reales que tienen sentido (3-sep-2026), y dos mejoras para hacerlos defendibles

Con los dos fixes aplicados, la primera corrida real completa (4 lotes BGL + 4 lotes HDFS) dio resultados coherentes con los diagnósticos reales: **BGL** Precisión=1.0, Recall=1.0, F1=1.0 (TP=1, FP=0, FN=0, TN=3); **HDFS** Precisión=0.67, Recall=1.0, F1=0.80 (TP=2, FP=1, FN=0, TN=1). En los 8 lotes, `hay_incidente` fue `False` siempre y `hay_anomalia` varió correctamente — el auditor nunca confundió un fallo de infraestructura con un ataque. El único falso positivo (`hdfs_negativo_001`) tiene una explicación razonable, no es un bug: `_HdfsAdapter` marca `evento_critico` para cualquier línea WARN/ERROR/FATAL, y un lote etiquetado `Normal` a nivel de **bloque** puede perfectamente contener líneas WARN sueltas de otros bloques mezclados en el mismo lote — el desacuerdo es de granularidad (bloque vs. línea), no del razonamiento del LLM.

Dos límites reales de esos primeros números, y los dos fixes que los cierran:

1. **n=4 es ruido, no evidencia** — un F1 de 1.0 sobre un único caso positivo no prueba nada; hace falta escalar a `--n-lotes 20` (10 positivos) antes de citar el número en el informe.
2. **Los lotes de HDFS se arman balanceados 50/50, pero la prevalencia real es ~3.1%** (69/2200 block_id) — una precisión medida sobre 50% de positivos no se traduce a la tasa real de falsos positivos que se vería en producción. **Fix**: nuevo parámetro `prop_positivos` en `_construir_lotes_hdfs()` (y flag `--prop-positivos` en el CLI, default 0.5) para poder armar también una corrida con prevalencia realista (`--prop-positivos 0.031`) — no aplica a BGL, cuyos lotes ya son un muestreo al azar sin balancear artificialmente.

Un tercer hallazgo, sin relación con las métricas pero necesario para poder explicar los resultados en el informe: **el texto de justificación del auditor (`evaluacion`) se imprimía por consola pero nunca se guardaba en el estado** — así que la corrida de 8 lotes de hoy no dejó registro persistente de *por qué* el auditor clasificó cada lote como lo hizo (necesario, por ejemplo, para justificar el falso positivo de `hdfs_negativo_001` citado arriba). **Fix**: nuevo campo `evaluacion_auditor: str` en `LogGuardState`, propagado por `pipeline.py`/`log_runner.py`, y guardado ahora en cada resultado de `eval_deteccion.py`.

Los tres fixes están verificados con tests nuevos (`test_evaluacion_auditor_se_persiste` en `tests/test_agente_auditor_final.py`; 3 tests de `prop_positivos` en `tests/test_eval_deteccion.py`, incluyendo el piso de al menos 1 lote positivo) y un mock end-to-end adicional que confirma que `evaluacion_auditor` llega completo hasta el JSON final y que `prop_positivos` arma la proporción de lotes pedida sin afectar a BGL. Nota pendiente, sin relación con esta evaluación: ChromaDB sigue en 0 documentos — el harness llama solo a `analizar_lote()`, nunca a `commit_feedback()`, así que estas corridas de evaluación no alimentan la memoria de largo plazo (decisión de diseño para no contaminarla con lotes sintéticos, pero vale la pena confirmarlo con Antonia si el informe necesita mostrar el ciclo de feedback funcionando).

### Fuente del ground truth — distinta por dataset

- **BGL**: el flag de alerta (primer campo de cada línea — `"-"` = normal, cualquier otro valor = alerta real) **ya es** el ground truth oficial del dataset (convención estándar de BGL/LogHub, la misma que usa `_BglAdapter` para `evento_critico`, ver sección de arriba). No requiere ningún archivo externo. Los lotes son ventanas contiguas del archivo real (`BGL_2k.log`); el ground truth del lote es "anómalo" si alguna línea de la ventana trae flag de alerta.

  ⚠️ **Advertencia metodológica** (no un bug, pero hay que citarla así en el informe): `_BglAdapter` lee ese mismo flag de alerta para calcular `evento_critico` **antes** de que el LLM vea nada — la agregación determinística ya le entrega al modelo una señal derivada directamente del ground truth. La evaluación sobre BGL mide, en rigor, si el LLM **transmite correctamente** una señal que el parser ya calculó, no si el sistema detecta anomalías de forma independiente. Es información real igual (el LLM podría ignorar o contradecir esa señal y no lo hace), pero es una limitación real de lo que esta evaluación específica puede afirmar sobre BGL.

- **HDFS**: el ground truth es por **bloque** (`block_id` → Normal/Anomaly) y no está en las líneas del log, y a diferencia de BGL, `_HdfsAdapter` no lo deriva de ahí (usa WARN/ERROR/FATAL como heurística de evento crítico, algo distinto e independiente del label real) — por eso la evaluación sobre HDFS sí es independiente de lo que la agregación determinística ya sabe. Hace falta el dataset canónico de ground truth para HDFS usado en la literatura (el mismo tipo de fuente que citan varios papers de la Tabla 7.1 del SLR, p. ej. Loglizer/He et al.). `src/tools/preparar_labels_hdfs.py` lo descarga y lo filtra a los ~2200 `block_id` que aparecen en `HDFS_2k.log`, guardando el resultado en `data/labels/hdfs_anomaly_label_2k.csv` (se corre una sola vez, requiere red real — no funciona desde un sandbox sin internet).

### Cómo se arman los lotes de control

Para BGL, ventanas contiguas del archivo (tamaño configurable, default 120 líneas) — el ground truth surge solo de si la ventana contiene una línea con alerta real, sin construcción artificial.

Para HDFS, cada lote mezcla un bloque real (uno con label `Anomaly` para los lotes "positivos", solo bloques `Normal` para los "negativos") con bloques `Normal` de relleno hasta el tamaño de lote pedido, preservando el **orden original** de las líneas en el archivo — así el lote se parece a un batch real, donde las líneas de distintos bloques llegan intercaladas, no agrupadas por bloque. Con `n-lotes=20` se arman ~10 positivos + ~10 negativos (siempre al menos 1 positivo si existe algún bloque `Anomaly`, incluso con `n-lotes` chico).

### Cómo correrlo

```bash
# BGL no necesita nada más -- corre directo:
python -m src.tools.eval_deteccion --dataset bgl --n-lotes 20 --lineas-por-lote 120

# HDFS: data/labels/hdfs_anomaly_label_2k.csv ya está preparado (3-sep-2026,
# 2200 block_id, 69 Anomaly / 2131 Normal, verificados contra loglizer) --
# no hace falta volver a correr preparar_labels_hdfs.py. Balanceado 50/50:
python -m src.tools.eval_deteccion --dataset hdfs --n-lotes 20 --lineas-por-lote 150 \
    --labels data/labels/hdfs_anomaly_label_2k.csv

# HDFS con prevalencia REAL (69/2200 ≈ 0.031) -- para un segundo número más
# representativo de producción, además del balanceado de arriba:
python -m src.tools.eval_deteccion --dataset hdfs --n-lotes 20 --lineas-por-lote 150 \
    --labels data/labels/hdfs_anomaly_label_2k.csv --prop-positivos 0.031
```

Cada corrida hace tantas llamadas reales y completas al pipeline (7 nodos LLM) como lotes se pidan — gasta cuota/dinero real. **Costo real medido** (3-sep-2026, 8 lotes en total — 4 BGL + 4 HDFS — de ~120-150 líneas, modelo principal `gemini-3.1-pro-preview`): **≈USD 0.033/lote**, ≈USD 0.26 en total — el razonamiento es ~87% de los tokens de salida. 20 lotes por dataset costarían ≈USD 0.66 cada uno (≈USD 1.32 los dos). El resultado (matriz de confusión, precisión, recall, F1 dentro de `metricas`, `campo_veredicto` usado, `prop_positivos` de la corrida, y el detalle por lote — incluye `hay_anomalia`, `hay_incidente`, `evaluacion_auditor` (el texto de justificación completo, no solo el veredicto), `confianza` y `n_comandos_mitigacion` de cada uno) se guarda en `results/eval_deteccion_<dataset>_<timestamp>.json`.

### Verificación antes de aplicar

La construcción de lotes (ground truth de BGL, mezcla y preservación de orden en HDFS, la proporción de positivos vía `prop_positivos`, manejo de casos sin bloques anómalos), el cómputo de métricas (incluyendo los casos borde de precisión/recall indefinidos por división por cero), y qué campo del estado se usa como predicción por dataset están cubiertos por `tests/test_eval_deteccion.py` y `tests/test_agente_auditor_final.py` (25 tests en total entre ambos) — deterministas, no llaman al LLM. La única parte que gasta cuota real (`analizar_lote()` sobre cada lote) se verificó aparte con el LLM mockeado antes de aplicar el script al repo (incluyendo mocks end-to-end de los escenarios reales de las rondas 2 y 3), siguiendo el mismo patrón que el resto del proyecto.

**Ejecutado el 3-sep-2026** a `--n-lotes 20` en ambos datasets y con `--prop-positivos 0.031` en HDFS (prevalencia real); ver los resultados más abajo. Queda pendiente para tener un número representativo de producción además del balanceado, y volcar todos los números resultantes al informe, citando la advertencia metodológica de BGL, la distinción anomalía-de-sistema vs. incidente-de-seguridad, y la explicación del falso positivo real de HDFS (ver "Ronda 3" arriba) usando `evaluacion_auditor` de cada resultado.

## Integración MITRE ATT&CK (STIX 2.1, §6.7/§8.7.2/§9 del informe, 3-sep-2026)

La Tabla 7.4 del informe (Brecha 2: "Falta de integración con CTI estructurada") especifica como respuesta "ChromaDB poblado desde repositorio oficial MITRE ATT&CK CTI (STIX 2.1)", y el reporte final debe incluir "las posibles técnicas MITRE ATT&CK asociadas". Hasta esta ronda, el enlace evento↔técnica dependía por completo del razonamiento libre del LLM, sin ninguna base de conocimiento estructurada detrás — esta sección cierra esa brecha, dentro del límite que el propio §8.7.2 fija explícitamente: "sin pretender cubrir exhaustivamente la totalidad de la base ATT&CK ni garantizar una atribución completa de grupos de amenaza".

### Diseño

- **Fuente**: el repositorio oficial `mitre-attack/attack-stix-data` (el mismo que alimenta ATT&CK Navigator), bundle Enterprise en formato STIX 2.1 — no un dataset de terceros ni una re-elaboración.
- **Versión**: se apunta a la ruta "flotante" (`enterprise-attack.json` en `master`), que siempre sirve la última release, en vez de fijar la v15 que cita el informe actual. **La corrida del 4-sep-2026 cargó la v19.2**, registrada en `data/mitre_attack/provenance.json`. Se repobló el 9-sep-2026 al limpiar `data/chroma/` (ver «Limpieza de la memoria» abajo): misma versión y misma cantidad de técnicas, solo cambia `fecha_corrida_utc`. **Decisión explícita de Antonia (3-sep-2026): usar la versión ACTUAL de ATT&CK, no la citada en el texto del informe** — la sección correspondiente del informe debe actualizarse para reflejar la versión real usada (`src/tools/preparar_mitre_attack.py` registra la versión real encontrada, `x_mitre_version`, en `data/mitre_attack/provenance.json`, para que la corrida quede documentada y sea reproducible aunque el archivo cambie más adelante).
- **Arquitectura**: se extendió el nodo Tool existente `tool_consultar_rag` para consultar también la nueva colección, **en vez de agregar un nodo nuevo al grafo** — decisión explícita de Antonia (3-sep-2026) para preservar la tabla de "7 nodos (4 LLM + 3 Tool)" que documenta el informe (§8.3.1, Tabla 8.9). La consulta usaba al principio la misma `firma` del lote que `patterns`/`errors`; desde el 9-sep-2026 usa una descripción en prosa del lote (`describir_lote_en_prosa()`, también determinística y en `src/tools/aggregation.py`) — ver «Texto de consulta a ATT&CK» abajo. `firma_lote()` no cambió y sigue siendo la clave de las otras tres colecciones.
- **4ta colección ChromaDB**: `attack_techniques` (ver `src/config.py`/`src/memory.py`), poblada UNA vez de forma offline — a diferencia de `patterns`/`errors`/`history`, no crece con el feedback loop del sistema.
- **Alcance**: solo Enterprise ATT&CK (no ICS ni Mobile — el informe no menciona esas matrices), excluyendo técnicas `revoked`/`x_mitre_deprecated`. No incluye atribución de grupos de amenaza (`intrusion-set`) ni de software (`malware`/`tool`) — fuera del alcance que el §8.7.2 excluye explícitamente.
- **Atribución**: los datos de ATT&CK **no son Creative Commons** (una confusión común) — MITRE exige una nota de atribución textual exacta en cualquier redistribución (ver https://attack.mitre.org/resources/terms-of-use/, verificado 3-sep-2026): *"© The MITRE Corporation. This work is reproduced and distributed with the permission of The MITRE Corporation."* — ver `MITRE_ATTACK_ATTRIBUTION` en `src/config.py`, y citarla en el informe donde se muestren o describan datos de ATT&CK.

### Cómo funciona en el pipeline

`tool_consultar_rag` recupera (con el mismo mecanismo de similitud coseno + `SIMILARITY_FLOOR` que usa para `patterns`) hasta `TOP_K_ATTACK` técnicas relacionadas con la firma del lote, y las agrega al estado (`tecnicas_mitre`). `agente_analista_triage` las recibe junto con el contexto RAG histórico en el prompt de diagnóstico, con instrucciones explícitas de citar el ID de una técnica (p. ej. "T1110") solo si de verdad aplica al lote, y de no inventar IDs cuando la lista viene vacía o ninguna técnica es relevante. El campo `tecnicas_mitre` se propaga hasta el reporte final (`analizar_lote`/`analizar_lote_stream`/`log_runner.py`), igual que `contexto_rag`.

### Cómo poblar `attack_techniques`

`src/tools/preparar_mitre_attack.py` descarga el bundle STIX oficial, lo parsea (`_extraer_tecnicas`, función pura, cubierta por `tests/test_preparar_mitre_attack.py` — 11 tests deterministas, sin red ni ChromaDB) y llama a `LongTermMemory().cargar_tecnicas_attack(...)`, que usa `upsert` (no `add`): correrlo de nuevo — por ejemplo tras una nueva versión de ATT&CK — reemplaza los documentos existentes por `technique_id` en vez de duplicarlos.

**Requiere red real** — igual que `preparar_labels_hdfs.py`, no funciona desde un sandbox sin acceso a internet (este repo se edita también desde un puente de dispositivo sin red). Se corre una sola vez (o de nuevo, para actualizar de versión):

```bash
python -m src.tools.preparar_mitre_attack
```

Guarda la procedencia de la corrida (versión de ATT&CK encontrada, cantidad de técnicas, fecha, atribución) en `data/mitre_attack/provenance.json`.

### Verificación antes de aplicar

`_extraer_tecnicas` (filtrado STIX puro: técnicas válidas, `revoked`, `x_mitre_deprecated`, sub-técnicas, objetos sin referencia `mitre-attack`, objetos de otro tipo mezclados en el bundle real, tácticas múltiples, `kill_chain_phases` de otro framework) está cubierto por 11 tests en `tests/test_preparar_mitre_attack.py`, siguiendo la misma convención que el resto del proyecto: la capa que toca ChromaDB (`cargar_tecnicas_attack`/`retrieve_attack_techniques`, y el propio `main()` de `preparar_mitre_attack.py`, que necesita red real) no tiene tests pytest — se verificó aparte con un stub de ChromaDB que sí persiste datos en memoria de proceso, confirmando: (1) carga y recuperación de técnicas, (2) que `upsert` reemplaza por `technique_id` sin duplicar al recargar, (3) que `cargar_tecnicas_attack([])` es un no-op seguro, (4) que `tool_consultar_rag` devuelve `contexto_rag` y `tecnicas_mitre` correctamente mezclados, y (5) que con la colección vacía (antes de correr `preparar_mitre_attack.py` por primera vez) no rompe nada — devuelve lista vacía.

**Ejecutado el 4-sep-2026.** `preparar_mitre_attack.py` corrió contra la API real de GitHub: **ATT&CK v19.2, 697 técnicas** (222 principales + 475 sub-técnicas, excluidas `revoked` y `deprecated`), cargadas en `attack_techniques` y con la procedencia registrada en `data/mitre_attack/provenance.json` (versión, fecha UTC y atribución de MITRE para citar). Confirmado de punta a punta con `log_runner.py` sobre `HDFS_2k.log`: `tecnicas_mitre` llega **vacío**, que es lo correcto para un lote operativo benigno — el propio diagnóstico concluye que «no se detectan patrones de ataque ni aplican técnicas de MITRE ATT&CK». La recuperación funciona cuando se la consulta **en prosa**: una consulta escrita a mano de fuerza bruta SSH devuelve T1110, T1110.003 y T1021.004 (ver «Umbral propio de similitud» abajo). Lo que esa verificación NO cubrió — y se descubrió el 9-sep-2026 — es que el sistema no consultaba en prosa, sino con `firma_lote()`: ver «Texto de consulta a ATT&CK» más abajo. También queda pendiente el enlace formal CVE ↔ técnica ATT&CK que menciona el §9 del informe — no incluido en esta ronda.

### Umbral propio de similitud (`SIMILARITY_FLOOR_ATTACK`, 4-sep-2026)

Bug real encontrado al confirmar la integración de punta a punta: la colección
quedaba **cargada pero desconectada**. `retrieve_attack_techniques()` devolvía
`[]` para cualquier lote, incluido un ataque evidente.

La causa era reusar `SIMILARITY_FLOOR` (0,55), que se calibró para comparar
firmas de lote contra firmas de lote — texto del mismo género. Acá se compara
la firma de un lote contra **prosa descriptiva de MITRE**, y `all-MiniLM-L6-v2`
no da similitudes tan altas entre dominios distintos aunque el contenido esté
claramente relacionado. Medido sobre la consulta `"brute force ssh failed
password authentication"`:

| Técnica | Similitud | Con umbral 0,55 |
|---|---|---|
| T1110 · Brute Force | **0,523** | ❌ filtrada |
| T1110.003 · Password Spraying | 0,404 | ❌ filtrada |
| T1021.004 · SSH | 0,370 | ❌ filtrada |

El match de manual se quedaba a 0,027 del umbral. Se agregó
`SIMILARITY_FLOOR_ATTACK` (0,35 por defecto) solo para esa colección; el umbral
global no se tocó, porque para su caso está bien calibrado.

El corte separa limpio: ruido operativo no relacionado midió 0,16–0,18 de
similitud contra las mismas técnicas. Verificado tras el fix: la consulta de
fuerza bruta recupera las tres técnicas, y las consultas de HDFS y BGL siguen
devolviendo **0** — sin falsos positivos, que era el riesgo de bajar el umbral.

### Texto de consulta a ATT&CK (`describir_lote_en_prosa`, 9-sep-2026)

El umbral de arriba se calibró con consultas **escritas a mano** en prosa. El sistema, en cambio, consultaba la colección con `firma_lote()` — una cadena de conteos del estilo `v1|lineas=23 ips=3 servicios=[sshd:18,...] eventos=[acceso_fallido:13,...]`. Se estaba comparando una tabla de conteos contra prosa narrativa, y la consecuencia, medida sobre corridas reales, era que **`tecnicas_mitre` venía vacío siempre**, para cualquier lote:

| Texto de consulta | auth_log (fuerza bruta SSH real) | BGL_2k | HDFS_2k |
|---|---|---|---|
| `firma_lote()` | 0,324 | 0,300 | 0,302 |
| `describir_lote_en_prosa()` | **0,484** (T1021, T1110.003) | 0,342 | 0,349 |

`describir_lote_en_prosa(resumen)` arma una o dos oraciones con los campos que la agregación ya produjo — formato, evento y servicio dominantes con sus conteos, intentos fallidos, IPs distintas, y una cláusula de reputación solo si AbuseIPDB marcó algo:

> Lote de tipo auth_log. Predominan eventos de acceso_fallido sobre el servicio sshd (13 eventos). 13 intentos fallidos de autenticacion desde 3 IPs distintas. 1 IP con reputacion maliciosa reportada en AbuseIPDB.

Es determinística (no consulta el LLM) y vive junto a `firma_lote()`, que **no cambió**: las colecciones `patterns`/`errors`/`history` se siguen consultando con la firma, porque ahí ambos lados de la comparación son firmas.

La cláusula de fallos se deriva de la distribución de eventos y no del contador `intentos_fallidos`. Los adaptadores de HDFS y BGL usan ese contador como marca de criticidad (`"intentos_fallidos": 1 if critico else 0`), no como fallo de login: describirlo como autenticación afirmaría algo que el log no dice y arrastraba la búsqueda hacia técnicas de credenciales por un lote de fallas de hardware — medido, con la primera versión de la prosa BGL llegaba a 0,369 contra T1016.

**Consecuencia sobre el umbral: 0,35 → 0,42.** Con la prosa como consulta, el piso viejo quedó dentro de la banda de ruido. Medido sobre 32 ventanas reales de BGL y HDFS — las mismas que arma la evaluación — 19 disparaban técnicas irrelevantes, incluidas **8 de 8 ventanas benignas de HDFS** con T1564.004 (*NTFS File Attributes*) a ~0,36. El barrido separa limpio, porque la señal real y el ruido no se tocan (ruido máximo 0,365; señal 0,462–0,484):

| Piso | Ventanas BGL/HDFS que disparan | Técnicas del ataque real |
|---|---|---|
| 0,35 | 19 / 32 | 5 / 5 |
| 0,38 | 0 / 32 | 5 / 5 |
| **0,42** | **0 / 32** | **5 / 5** |
| 0,45 | 0 / 32 | 5 / 5 |
| 0,47 | 0 / 32 | 2 / 5 |

Se toma 0,42 por ser el punto medio de la banda libre. La medición es reproducible sin gastar cuota de LLM: agregación determinística más consulta a ChromaDB.

**Verificado de punta a punta** el 9-sep-2026 contra la API real, con un lote `auth_log` de fuerza bruta SSH: el nodo RAG recupera T1021 (*Remote Services*, 0,484), T1685.001 (0,471) y T1110.003 (*Password Spraying*, 0,471), y las tres llegan al reporte y al informe en PDF con la nota de atribución de MITRE. Dos de las tres son pertinentes; T1685.001 (*Disable or Modify Windows Event Log*) es un vecino plausible pero equivocado — una técnica de Windows para un log de Linux. Es una consecuencia de recuperar `TOP_K_ATTACK=3` una vez superado el piso, no del piso en sí, y queda como limitación conocida: el prompt del triage ya instruye citar un ID **solo si de verdad aplica** al lote.

### Limpieza de la memoria (9-sep-2026)

La verificación de la Fase C escribió documentos reales en `host_history`, `attack_patterns` y `error_memory` a partir de un lote sintético de prueba (`auth_muestra.log`). Como las tres colecciones estaban en 0 antes de esa verificación, se borró `data/chroma/` completo y se repobló solo `attack_techniques`:

```bash
rm -rf data/chroma
python -m src.tools.preparar_mitre_attack
```

Estado confirmado después: `attack_techniques` = **697** documentos (ATT&CK **v19.2**, 222 técnicas + 475 sub-técnicas), y `attack_patterns` = `error_memory` = `host_history` = **0**. `data/mitre_attack/provenance.json` quedó idéntico salvo `fecha_corrida_utc` (`2026-09-04T00:13:20Z` → `2026-09-09T17:04:41Z`): misma URL de origen, misma versión, mismos conteos, misma atribución. La recuperación sigue dando el mismo resultado que antes de borrar — la prosa del lote de fuerza bruta devuelve T1021 (0,484), T1685.001 (0,471) y T1110.003 (0,469), idénticas similitudes.

`data/chroma/` está en `.gitignore`, así que la limpieza no aparece en el diff: quien clone el repositorio tiene que correr `preparar_mitre_attack.py` de todos modos.

### Unicidad de los ids en ChromaDB (9-sep-2026)

Los documentos se identificaban con `f"hist-{int(time.time()*1000)}"` (y equivalentes para `pat-`, `err-`, `seed-`), heredado del prototipo. Dos escrituras dentro del mismo milisegundo generaban el mismo id y ChromaDB sobrescribía la primera **en silencio**. Nunca importó mientras `commit_feedback()` no tenía llamadores; desde la Fase C es un botón que un analista puede apretar dos veces seguidas para corregirse.

`LongTermMemory._nuevo_id(prefijo)` agrega un sufijo aleatorio (`uuid4().hex[:6]`) y conserva el timestamp al principio, para que los ids sigan ordenándose cronológicamente. Cubierto por `tests/test_memory_ids.py`, que congela `time.time()` para forzar la colisión en vez de depender de la velocidad de la máquina.

**Los ids de `attack_techniques` NO llevan azar**: son `attack-<technique_id>`, y el `upsert` depende de esa clave estable para reemplazar al actualizar de versión de ATT&CK. Con ids aleatorios, cada recarga duplicaría las 697 técnicas — hay un test que lo fija.

## Preprocesamiento heterogéneo (esquema v2)

Implementa el plan de [`docs/plan_accion_preprocesamiento_heterogeneo.md`](docs/plan_accion_preprocesamiento_heterogeneo.md), completado en sus 14 fases el 4-sep-2026. Reemplaza el enfoque «detectar dataset → elegir un parser → procesar todo el lote» por una tubería genérica:

```
ingesta → segmentación → detección → decodificación → enriquecimiento → agregación
```

**El motor v1 sigue siendo el predeterminado.** `LOG_PREPROCESSING_ENGINE=v1` corre el agregador original sin cambios; `=v2` corre la tubería nueva y deriva de ella los campos que los consumidores esperan. La bandera permite comparar ambos sobre las mismas entradas y volver atrás sin tocar código.

### Qué cambia

| Aspecto | v1 | v2 |
|---|---|---|
| Formatos por lote | uno solo | varios, por segmentos o intercalados |
| Formatos soportados | auth-log, HDFS, BGL, CSV | + JSON/JSONL, syslog RFC 3164/5424, CEF, LEEF, `clave=valor`, texto libre |
| Fallback | auth-log (le atribuía semántica de sshd/apache a texto desconocido) | texto libre, que no inventa servicio ni evento |
| Eventos multilínea | no | sí (stack traces, JSON multilínea) |
| Líneas físicas vs. eventos | mismo contador | contadores separados |
| Campo `usuario` | usuario, block id, nodo o id de flujo, según el adaptador | un campo por concepto; los identificadores van a `attributes` |
| Registros sin IP | subrepresentados | eventos válidos con sus propias entidades |
| Ground truth | el flag de BGL alimentaba `evento_critico` | canal separado, invisible para el detector |
| Observabilidad | ninguna | cobertura, advertencias, segmentos y confianza por evento |

### Estructura

```
src/preprocessing/
├── models.py         # NormalizedEvent, RecordSegment, ParsingWarning, GroundTruthRecord
├── result.py         # PreprocessingResult
├── segmentation.py   # líneas físicas → registros lógicos
├── detection.py      # decoder dominante por bloque, modos batch/chunked/line/hybrid
├── normalization.py  # mapeo de campos por sinónimo, con prioridad declarada
├── aggregation.py    # resumen v2 + derivación de los campos v1
├── ground_truth.py   # canal separado de etiquetas
├── prompt_context.py # cómo se interpretó el lote, para los prompts
├── decoders/         # json, csv, syslog, key_value, cef, leef, text
└── enrichers/        # hdfs, bgl, zeek, auth
```

### La fuga de ground truth que esto corrige

El adaptador BGL de v1 leía el primer campo de cada línea —el flag de alerta que los curadores del dataset agregaron— y lo convertía en `evento_critico`, o sea en la feature que el detector observa. El sistema no detectaba anomalías: leía la respuesta escrita en la propia línea.

Eso explica el **F1 = 1.00 medido sobre BGL** el 2-sep-2026, que parecía detección perfecta y era circularidad.

En v2 el flag viaja al canal de ground truth y `evento_critico` se deriva de la severidad que el log declara y del resultado de la operación. Sobre `BGL_2k.log` eso da 403 eventos críticos en vez de 143: la señal es **ruidosa** —recall 1.00 y precisión 0.35 respecto de la etiqueta— o sea que el detector vuelve a tener trabajo real. Las métricas de HDFS y BGL deben recalcularse con el motor v2 antes de citarlas en el informe.

Preservar el registro original y ocultar la etiqueta se contradicen cuando la etiqueta está escrita en la línea, como en BGL. Se resuelve conservando `raw` para auditoría y **prohibiendo que se muestree hacia el LLM** cuando el lote trae ground truth embebido; `verificar_aislamiento(..., revisar_raw=True)` lo comprueba.

### Métricas medidas (4-sep-2026)

| Dataset | Eventos | Cobertura | Fallback | Pérdida de líneas | s/1000 ev | Memoria | Fugas |
|---|---|---|---|---|---|---|---|
| HDFS_2k | 2000 | 1.00 | 0 % | 0 | 0,17 | 5,8 MB | 0 |
| BGL_2k | 2000 | 1.00 | 0 % | 0 | 0,17 | 6,0 MB | 0 |
| Lote mixto (8 formatos) | 176 | 0,86 | 14 % | 0 | 0,20 | 0,5 MB | 0 |

Tokens del prompt de triage, sobre HDFS_2k: resumen completo 9842 → **acotado 1167 + 102 de contexto de preprocesamiento = 1269**. El acotamiento por cardinalidad de IPs sigue vigente y el contexto nuevo agrega ~100 tokens.

**Cobertura cuenta el enriquecimiento, no solo el decoder.** HDFS y BGL no tienen estructura genérica —los reconoce un enriquecedor de producto, no un decoder—, así que medir solo por decoder les daba 0 % estando completamente interpretados, y el contexto llegaba a advertirle al agente que el lote «no pudo interpretarse» cuando sí se había interpretado.

### Paridad con v1, verificada sobre los datasets reales

**HDFS_2k coincide exactamente** en formato, líneas, servicios (mismos 4 con igual conteo), IPs (las mismas 202) y eventos críticos (80).

**BGL_2k difiere en tres puntos, y los tres son mejoras:**

- **11 IPs en vez de 2.** Las 9 nuevas son direcciones privadas reales que v1 perdía. Además, v2 descarta `1.0.0.102`, que v1 reportaba como IP y en realidad es un fragmento de la cadena de versión `hpcc-1.0.0.102905` dentro de una ruta: la regex de v1 no usa bordes de palabra y matchea un prefijo truncado.
- **5 subsistemas en vez de 4**: reconoce también `bgl.discovery` y `bgl.hardware`.
- **403 eventos críticos en vez de 143**: el efecto de quitar la fuga, descrito arriba.

### Configuración

Todas las variables `LOG_*` están documentadas en `.env.example`. Las de uso más frecuente:

- `LOG_PREPROCESSING_ENGINE` — `v1` (predeterminado) o `v2`.
- `LOG_PARSING_MODE` — `batch` | `chunked` | `line` | `hybrid` (recomendado).
- `LOG_ENABLE_MULTILINE` — desactiva la unión de registros multilínea.
- `LOG_MAX_FILE_BYTES` / `LOG_MAX_EVENTS` — cotas de volumen, aplicadas en la API y en la tubería.

### Ambigüedad conocida y aceptada

Una línea de texto plano **después** de un registro con timestamp es indistinguible de la segunda línea de un stack trace. La segmentación las une, que es lo correcto para el stack trace y discutible para un lote heterogéneo. Se resolvió a favor de no perder la relación entre líneas —el contenido queda íntegro en `raw` y las líneas contabilizadas—, con `LOG_ENABLE_MULTILINE=false` como escape. Los formatos autodelimitados (CEF, LEEF, JSON, filas CSV) nunca absorben la línea siguiente.

### Divergencia deliberada entre motores

El enriquecedor de autenticación de v2 extrae `admin` de `"for invalid user admin"`, mientras que `parse_log()` de v1 extrae `invalid` — la particularidad heredada del notebook que este README documenta más arriba como preservada a propósito. **El motor v1 la conserva intacta**; solo v2 hace la extracción correcta. Los tests que fijan comportamiento v1 invocan `aggregate_logs_v1` directamente, así que siguen verificando lo que deben aunque el entorno tenga v2 activo.

## Notas de fidelidad con el prototipo (`notebooks/LLM_Agente_INICIO.ipynb`)

Además de lo anterior, la migración preserva dos particularidades de comportamiento del notebook que no están cubiertas por el informe (son detalles de implementación, no de arquitectura), documentadas y cubiertas por tests en `tests/`:

- `parse_log()` extrae el "usuario" por la alternativa de regex que aparece primero **en el texto**, no la más específica — en `"... for invalid user admin ..."` captura `"invalid"`, no `"admin"`.
- `validate_solution()` solo marca `valido=False` ante un patrón explícitamente peligroso (`rm -rf /`, `mkfs`, etc.); un binario fuera de la lista blanca se reporta en `motivos` pero no invalida el comando.

Si en algún momento quieres corregir alguno de estos dos puntos, es un cambio acotado a `src/tools/aggregation.py` / `src/tools/validation.py` — pero no se tocó en la migración para no alterar resultados ya usados en el informe del Seminario.

## Bugs corregidos durante la migración

A diferencia de las particularidades de la sección anterior — que se **preservan a propósito** —, acá se listan bugs reales encontrados al correr el sistema fuera de Colab, que sí se corrigieron.

### Loop infinito `agente_analista_triage` ↔ `tool_consultar_rag` con ChromaDB fría

- **Síntoma:** en una instalación limpia (ChromaDB vacía), `python -m src.pipeline` nunca termina: alterna indefinidamente entre `agente_analista_triage` y `tool_consultar_rag` hasta agotar el `recursion_limit` de LangGraph (~5000 ciclos), y el reporte final sale vacío (`diagnostico: ""`, `confianza: 0.0`). No consume cuota de Gemini, porque el nodo retorna antes de llamar al LLM.
- **Causa raíz:** `agente_analista_triage` decidía si ya tenía contexto por la *truthiness* de `state["contexto_rag"]`. `tool_consultar_rag` devuelve `{"contexto_rag": patrones}`, y sin patrones similares eso es una **lista vacía**, que es falsy. El triage volvía entonces a la rama "sin contexto" → `necesita_rag=True` → `router_triage` lo mandaba de nuevo al RAG → ciclo infinito. El grafo solo terminaba si ChromaDB ya contenía al menos un patrón similar.
- **Fix aplicado:** en `src/agents/agente_analista_triage.py`, la condición pasó a `if state.get("contexto_rag") or state.get("necesita_rag"):`. Como `necesita_rag` arranca en `False` (ver `src/pipeline.py`), que valga `True` al entrar al nodo significa inequívocamente "el RAG ya corrió una vez", con o sin resultados — que es lo que especifica el Algoritmo 8.3 del informe ("consultar RAG UNA vez"), no un loop. Además, al armar el prompt, un `contexto_rag` vacío ahora se interpola como `"Sin patrones históricos previos (memoria aún vacía)."` en vez de un `[]` crudo. No se tocaron `tool_consultar_rag.py` ni los routers.
- **Presente también en el prototipo:** el bug está latente en la celda 22 del notebook `LLM_Agente_INICIO.ipynb` — la migración es fiel 1:1 en este punto. Nunca se manifestó en Colab porque la memoria ChromaDB ya tenía datos de corridas previas de la misma sesión (`commit_feedback()`), así que el RAG siempre devolvía al menos un patrón y el ciclo cortaba en la primera vuelta.

## Modelo de distribución (decisión — 23-ago-2026)

El sistema se distribuirá como **software autohospedado (self-hosted), descargable**, no como SaaS multi-tenant. Decisión tomada por Antonia y Felipe tras evaluar que el dato que procesa (logs de seguridad crudos: IPs, usuarios, estructura de infraestructura) es demasiado sensible para que el segmento objetivo (PyMEs y organizaciones sin equipo de seguridad) lo mande a un tercero en la nube — sigue el patrón de distribución habitual en herramientas SOC/SIEM comparables (Wazuh, etc.).

Forma prevista:
- **Empaquetado en contenedor Docker**: el agente + ChromaDB embebido corren en la infraestructura del cliente (o su nube privada), no en infraestructura de Antonia/Felipe.
- **El cliente trae sus propias API keys** (Gemini, AbuseIPDB, NVD) — evita que el equipo del proyecto absorba el costo de inferencia por cliente.
- **Interfaz web local**, no expuesta a internet, para ver los reportes generados — a implementar (ver "Pendiente" abajo).
- Un tier SaaS/cloud gestionado queda como posible oferta futura sobre la misma base de código, no como el modelo inicial.

Esta decisión es de producto/negocio, posterior al alcance académico del Proyecto de Título (el informe §8.7.2 excluye explícitamente una "solución SOC productiva" del alcance de la tesis) — se documenta acá para que el empaquetado (Dockerfile, estructura de la app) se diseñe pensando en este destino desde ahora, sin que bloquee el trabajo académico pendiente.

## Estado del proyecto

- ✅ Informe de Seminario de Título completo — define arquitectura, modelo, requerimientos y alcance oficiales (§8 "Propuesta de Solución").
- ✅ Prototipo funcional del Seminario de Título (grafo de 7 nodos, notebook de Colab) — preservado en `notebooks/`, confirma viabilidad técnica del flujo.
- ✅ Migrado a módulos Python independientes en `src/` (agentes, tools, grafo, memoria, pipeline), alineado al informe donde este y el prototipo difieren, con tests para la lógica determinística.
- ✅ API keys creadas (Gemini, AbuseIPDB, NVD).
- ✅ Modelo de distribución decidido: software descargable/autohospedado (Docker), no SaaS — ver sección arriba.
- ✅ Loop infinito triage↔RAG corregido y verificado.
- ✅ Bloqueo de `gemini-2.5-pro` diagnosticado y verificado independientemente **dos veces** (23-ago tier gratuito, 1-sep con facturación activada) — decisión final (1-sep-2026): modelo principal `gemini-3.1-pro-preview` + respaldo automático `gemini-3.6-flash` (`_generate_con_fallback` en `src/llm.py`), medidos con 6 corridas reales, ver "Modelo LLM en la práctica".
- ✅ **Pipeline corrido de punta a punta, sin errores** (23-ago-2026): diagnóstico correcto, confianza 0.85–0.95 según corrida, comandos de mitigación aprobados, sin escalamiento a humano.
- ✅ Corroboración de IPs (AbuseIPDB) conectada al pipeline y verificada — cambia el diagnóstico con evidencia real, como espera el informe.
- ✅ Manejo de cuota (429 diaria vs. por minuto), errores transitorios (503) y errores de transporte (SSL/conexión) en `src/llm.py`, con reintento endurecido (techo de backoff, jitter, timeout explícito) y modelo de respaldo automático, verificado con `tests/test_llm.py` (25/26-ago y 1-sep-2026, 17 tests) — ver "Manejo de cuota y errores transitorios de la API" arriba. Corrige dos bugs reales encontrados en corridas reales: un 429 por minuto que se trataba igual que uno diario (25-ago), y un corte de conexión TLS sin código HTTP que no se reintentaba nunca (26-ago).
- ✅ Ciclo de corrección de comandos (`agente_ingeniero_mitigacion` ↔ `tool_validar_comandos`, router `router_validacion`) verificado con `tests/test_ciclo_correccion.py` — mockea el LLM en vez de depender de que una corrida real proponga algo peligroso (no determinista y gastaría cuota). Cubre el camino de corrección exitosa en el segundo intento y el de agotar `MAX_INTENTOS_CORRECCION` y escalar igual con `comandos_validos=False`. Confirmado en `pytest` (26-ago-2026: 30/30; al cierre del desarrollo, 9-sep-2026: **317/317**). Sigue pendiente verlo ocurrir con el LLM real al menos una vez — en las dos corridas completas reales (ver abajo), el validador aprobó a la primera en ambas.
- ✅ Parsing multi-formato de logs: `src/tools/aggregation.py` generaliza el preprocesamiento determinístico con adaptadores por formato (auth-log, HDFS, BGL) y detección automática por lote, con fallback seguro para formatos no reconocidos — ver "Parsing multi-formato de logs" arriba. Verificado contra `HDFS_2k.log`/`BGL_2k.log` reales (incluyendo un conteo independiente de eventos críticos que coincidió exacto, 25-ago-2026) y con tests de regresión (`tests/test_aggregation_multi_formato.py`). Quedan otros formatos de la Tabla 8.11 (UWF-ZeekDataFall22, LogHub) sin adaptador dedicado — usan el fallback auth-log por ahora.
- ✅ Runner de archivos de log reales (`src/tools/log_runner.py`) — reemplaza el lote de ejemplo hardcodeado de `pipeline.py` para poder correr `analizar_lote()` directo contra un archivo (`data/logs/HDFS_2k.log`, `data/logs/BGL_2k.log`), guardando un resumen curado en `results/`.
- ✅ Acotamiento de costo por cardinalidad de IPs en el prompt de triage (`src/tools/resumen_prompt.py`, 25-ago-2026) — resuelve el hallazgo de la tabla de tokens arriba (58.289 vs. 1.096 tokens de entrada solo por la cantidad de IPs distintas). Confirmado con una corrida real (26-ago-2026): triage de HDFS bajó de 58.289 a 8.271 tokens de entrada (−86 %). Ver "Instrumentación de costo real en tokens" arriba y `tests/test_resumen_prompt.py` (6 tests).
- ✅ **Primera corrida real completa, de punta a punta, sobre los dos datasets del informe** (26-ago-2026) — `HDFS_2k.log` y `BGL_2k.log` corrieron los 7 nodos sin abortar, con diagnóstico, comandos de mitigación aprobados y confianza final (0.95 y 0.90). Ver "Primera corrida completa de punta a punta" arriba para el detalle, incluida una advertencia importante: se corrió con `gemini-3.5-flash` (no el `gemini-3.7-flash` de `.env`) porque este último agotó su cuota diaria durante los intentos previos del mismo día — pendiente repetir con el modelo de registro cuando resetee la cuota, si se necesitan las cifras oficiales para el informe.
- ✅ **Integración MITRE ATT&CK vía STIX 2.1** (§6.7/§8.7.2/§9 del informe, Tabla 7.4 Brecha 2, 3-sep-2026): código implementado y verificado — `tool_consultar_rag` (nodo Tool existente, sin agregar un 8º nodo al grafo) ahora consulta también una 4ª colección de ChromaDB (`attack_techniques`), poblada desde el bundle STIX oficial de MITRE (`src/tools/preparar_mitre_attack.py`, apunta a la versión ACTUAL de ATT&CK: la corrida real cargó **v19.2**, no la v15 que cita el informe — hay que actualizar esa cita). 11 tests nuevos (`tests/test_preparar_mitre_attack.py`) más verificación end-to-end con un stub de ChromaDB. **Completado el 4-sep-2026**: corrido con red real (**v19.2, 697 técnicas**), confirmado end-to-end sobre `HDFS_2k.log`, y corregido un bug que dejaba la colección cargada pero desconectada (`SIMILARITY_FLOOR_ATTACK`, ver arriba). **Sigue pendiente**: el enlace formal CVE ↔ técnica ATT&CK (§9). Ver "Integración MITRE ATT&CK" arriba.
- 🟡 **Evaluación cuantitativa de detección — Precisión/Recall/F1** (§8.6.2, 3-sep-2026): `src/tools/eval_deteccion.py` construye lotes de control con ground truth conocido (BGL: flag de alerta real del dataset; HDFS: `anomaly_label.csv` canónico filtrado por `src/tools/preparar_labels_hdfs.py`, ya preparado — 2200 block_id, 69 Anomaly/2131 Normal) y compara el veredicto del agente contra esa verdad-terreno. **Dos bugs reales de clasificación, encontrados y corregidos en las dos primeras corridas reales, el mismo día**: (1) 4 lotes de BGL dieron precisión 0.25/recall 1.00 porque el script usaba `confianza` como proxy de "hay incidente" — se agregó `hay_incidente`, veredicto explícito del auditor; (2) con ese fix, la misma corrida dio recall 0.0 porque BGL/HDFS etiquetan anomalías de *sistema*, no de seguridad — se agregó un segundo campo, `hay_anomalia`, y la evaluación ahora usa el campo que corresponde a cada dataset. **Con ambos fixes, la primera corrida completa (4+4 lotes) dio números coherentes**: BGL F1=1.0, HDFS F1=0.80 (con un falso positivo explicable por granularidad bloque-vs-línea, no un bug). Se agregaron dos mejoras más el mismo día para que esos números sean defendibles en el informe: `evaluacion_auditor` (el texto de justificación del auditor, antes solo se imprimía por consola, ahora se persiste por lote) y `--prop-positivos` (permite armar una corrida de HDFS con la prevalencia real del dataset, ~3.1%, en vez del 50/50 balanceado por defecto). En total, 4 rondas de trabajo el mismo día tocaron `LogGuardState`, el prompt del auditor y el script de evaluación, con 25 tests nuevos entre `tests/test_agente_auditor_final.py` y `tests/test_eval_deteccion.py`. Costo real medido: ≈USD 0.033/lote con el modelo principal. **Falta**: escalar a `--n-lotes 20` (BGL y HDFS balanceado + HDFS con prevalencia real) y volcar los números finales al informe. Ver "Evaluación cuantitativa de detección" arriba.
- ✅ **Baseline determinístico de reglas** (§8.6.4/§9, 9-sep-2026): `src/tools/baseline_reglas.py` clasifica sin LLM (severidad grave, proporción de fallidos, concentración por IP) para dar el término de comparación que el informe compromete. Medido: BGL F1 **0,57** con motor v1 y **0,83** con v2; HDFS **recall 0,00** en los cuatro escenarios, porque sus anomalías son por bloque y no se manifiestan como umbrales agregados. Corre en ~0,01 s por lote y con costo USD 0.
- ⏳ Pendiente (§9 del informe): extender la evaluación cuantitativa a UWF-ZeekDataFall22 — el enriquecedor Zeek de `src/preprocessing/enrichers/` ya cubre parte del trabajo (extrae `conn_state` y desvía `label_tactic` al canal de ground truth), así que la adaptación restante puede ser menor de lo previsto. Requiere decisión de alcance antes de iniciarse.
- ✅ **Interfaz web local** (1-sep-2026): panel de análisis (FastAPI + HTML/JS) sobre `src/pipeline.py` — sube un lote de logs, muestra el grafo de 7 nodos ejecutándose en vivo (SSE) y el reporte final. Ver "Interfaz web" arriba. Lógica de streaming (`analizar_lote_stream()`) verificada con el LLM mockeado, dos escenarios (flujo con RAG+CVE, ciclo de corrección de comandos) — pendiente correrla contra la API real y, si se usa para la defensa, contra un dataset más grande que el de ejemplo.
- ✅ **Preprocesamiento heterogéneo v2, las 14 fases del plan** (9-sep-2026): `src/preprocessing/` reemplaza «detectar dataset → un parser → todo el lote» por una tubería genérica (segmentación, detección, decodificación, enriquecimiento, agregación), con 7 decodificadores estructurales, 4 enriquecedores de producto, lotes heterogéneos, eventos multilínea y observabilidad de cobertura. **El motor v1 sigue siendo el predeterminado**; v2 se activa con `LOG_PREPROCESSING_ENGINE=v2` y la migración es reversible sin tocar código. Corrige además la fuga de ground truth de BGL que explicaba el F1 = 1.00 circular. Ver "Preprocesamiento heterogéneo (esquema v2)" arriba.
- ✅ **Suite de tests al cierre del desarrollo** (9-sep-2026): **317 pruebas deterministas**, en verde con ambos motores y en un clon limpio sin credenciales. Ver `docs/preprocessing_baseline.md`.
- ⏳ Pendiente (empaquetado/producto): Dockerfile para el sistema de distribución decidido arriba — la interfaz web ya no depende de eso para poder demostrarse localmente.
