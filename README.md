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

Patrón **Plan-and-Execute** (no ReAct estándar): se separa pensar de hacer, y se antepone una capa de agregación determinística antes de involucrar al LLM.

```
Entrada (lote de logs crudos)
 └─> AGREGACIÓN (código, sin LLM)
      └─> CORROBORACIÓN DE IPs (código + caché, AbuseIPDB)
           └─> PLANIFICADOR (LLM) — arma plan sobre el resumen, no el log crudo
                └─> EJECUTOR (function calling manual: query_cve, validate_solution)
                     └─> SÍNTESIS (LLM) — diagnóstico + confianza + mitigación validada
                          └─> SALIDA: JSON | escalamiento si confianza < 0.70
                               └─> FEEDBACK → memoria (ChromaDB)
```

Implementado como un `StateGraph` de **LangGraph** con **7 nodos** (4 LLM + 3 Tool) y **3 aristas condicionales (routers)**:

| Nodo | Tipo | Función |
|---|---|---|
| `agente_analista_triage` | LLM | Analiza el resumen del lote; decide si necesita contexto histórico (RAG) |
| `tool_consultar_rag` | Tool | Recupera contexto histórico desde ChromaDB |
| `agente_selector_herramientas` | LLM | Decide qué herramienta usar a continuación |
| `tool_consultar_cve` | Tool | Consulta NVD por CVEs relacionados a los servicios afectados |
| `agente_ingeniero_mitigacion` | LLM | Propone comandos de mitigación |
| `tool_validar_comandos` | Tool | Valida los comandos propuestos (ciclo de corrección, máx. 2 intentos) |
| `agente_auditor_final` | LLM | Diagnóstico global, confianza, hipótesis alternativa, justificación |

Routers: `router_triage`, `router_selector`, `router_validacion` (este último gestiona el ciclo de corrección de comandos, con `intentos_correccion` para evitar loops infinitos).

Checkpointer: `MemorySaver`.

## Stack técnico

- **LangGraph** (`StateGraph`) para orquestación
- **Gemini** (`google-genai`, SDK directo) como LLM backbone. **Modelo especificado en el informe: `gemini-2.5-pro`**, temperatura 0 (sección 8.3.2, Tabla 8.2). El notebook prototipo corrió con `gemini-2.5-flash-lite` por costo/cuota durante el desarrollo — no es la especificación final. Configurable vía `LLM_MODEL_PRIMARY`/`LLM_MODEL_FALLBACK` en `.env`. **Nota (23-ago-2026, reconfirmada 1-sep-2026 con facturación activada):** la API key de Antonia no tiene acceso a `gemini-2.5-pro` (restricción de Google por antigüedad de cuenta, no una deprecación ni un límite de facturación — ver sección "Modelo LLM en la práctica" más abajo); el default operativo del repo es principal `gemini-3.1-pro-preview` con respaldo automático `gemini-3.6-flash`, con cuenta pagada.
- **ChromaDB**: 3 colecciones, embeddings `all-MiniLM-L6-v2` (384 dims)
- Herramientas externas: **AbuseIPDB** (reputación de IPs), **NVD** (CVEs)
- Umbrales: confianza **0.70**, auto-promoción **0.90**
- Python: pandas, matplotlib, xlrd (para el notebook de experimentos/baselines, no parte del stack oficial del agente — ver Tabla 8.9 del informe)

## Estructura del proyecto

```
NODEX/
├── src/
│   ├── config.py          # Carga de variables de entorno y constantes (umbrales, modelos)
│   ├── state.py           # Definición de LogGuardState (TypedDict del grafo)
│   ├── agents/             # Los 4 nodos LLM (triage, selector, mitigación, auditor)
│   ├── tools/               # Los 3 nodos Tool (RAG, CVE, validación de comandos)
│   ├── graph/
│   │   └── build_graph.py  # Construcción del StateGraph, routers y compilación
│   └── api/                 # Interfaz web (FastAPI) — panel de análisis con progreso en vivo
│       ├── main.py
│       └── static/index.html
├── notebooks/               # Notebook(s) original(es) de Colab, como referencia
├── data/                    # Caché de reputación de IPs, colecciones ChromaDB (no versionar contenido real)
├── tests/                   # Tests unitarios por nodo/tool
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

## Interfaz web (panel de análisis, 1-sep-2026)

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

## Informe vs. prototipo — qué manda dónde

| Aspecto | Informe (spec oficial) | Notebook (prototipo) | En este repo |
|---|---|---|---|
| Modelo LLM | `gemini-2.5-pro`, temp. 0 (§8.3.2, Tabla 8.2) | `gemini-2.5-flash-lite` (costo/cuota en desarrollo) | Principal `gemini-3.1-pro-preview` + respaldo automático `gemini-3.6-flash` (`LLM_MODEL_PRIMARY`/`LLM_MODEL_FALLBACK` en `.env`), cuenta pagada — `gemini-2.5-pro` bloqueado para la key actual (confirmado incluso pagando), ver sección "Modelo LLM en la práctica" |
| Nodos del grafo | 7 (4 LLM + 3 Tool), 3 routers (§8.2.3) | Igual | Igual — migrado 1:1 |
| Umbrales confianza | 0.70 escalar / 0.90 auto-promover (§8.2.4) | Igual | Igual |
| Memoria (ChromaDB) | 3 colecciones, `all-MiniLM-L6-v2`, k=3, similitud≥0.55 (§8.2.2, §8.3.1) | Igual | Igual |
| MITRE ATT&CK / STIX 2.1 | Entregable del Proyecto de Título (§8.7.2, §9) | No implementado | No implementado — próximo paso |
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
- ✅ Ciclo de corrección de comandos (`agente_ingeniero_mitigacion` ↔ `tool_validar_comandos`, router `router_validacion`) verificado con `tests/test_ciclo_correccion.py` — mockea el LLM en vez de depender de que una corrida real proponga algo peligroso (no determinista y gastaría cuota). Cubre el camino de corrección exitosa en el segundo intento y el de agotar `MAX_INTENTOS_CORRECCION` y escalar igual con `comandos_validos=False`. Confirmado 30/30 en `pytest` (26-ago-2026, suite completa). Sigue pendiente verlo ocurrir con el LLM real al menos una vez — en las dos corridas completas reales (ver abajo), el validador aprobó a la primera en ambas.
- ✅ Parsing multi-formato de logs: `src/tools/aggregation.py` generaliza el preprocesamiento determinístico con adaptadores por formato (auth-log, HDFS, BGL) y detección automática por lote, con fallback seguro para formatos no reconocidos — ver "Parsing multi-formato de logs" arriba. Verificado contra `HDFS_2k.log`/`BGL_2k.log` reales (incluyendo un conteo independiente de eventos críticos que coincidió exacto, 25-ago-2026) y con tests de regresión (`tests/test_aggregation_multi_formato.py`). Quedan otros formatos de la Tabla 8.11 (UWF-ZeekDataFall22, LogHub) sin adaptador dedicado — usan el fallback auth-log por ahora.
- ✅ Runner de archivos de log reales (`src/tools/log_runner.py`) — reemplaza el lote de ejemplo hardcodeado de `pipeline.py` para poder correr `analizar_lote()` directo contra un archivo (`data/logs/HDFS_2k.log`, `data/logs/BGL_2k.log`), guardando un resumen curado en `results/`.
- ✅ Acotamiento de costo por cardinalidad de IPs en el prompt de triage (`src/tools/resumen_prompt.py`, 25-ago-2026) — resuelve el hallazgo de la tabla de tokens arriba (58.289 vs. 1.096 tokens de entrada solo por la cantidad de IPs distintas). Confirmado con una corrida real (26-ago-2026): triage de HDFS bajó de 58.289 a 8.271 tokens de entrada (−86 %). Ver "Instrumentación de costo real en tokens" arriba y `tests/test_resumen_prompt.py` (6 tests).
- ✅ **Primera corrida real completa, de punta a punta, sobre los dos datasets del informe** (26-ago-2026) — `HDFS_2k.log` y `BGL_2k.log` corrieron los 7 nodos sin abortar, con diagnóstico, comandos de mitigación aprobados y confianza final (0.95 y 0.90). Ver "Primera corrida completa de punta a punta" arriba para el detalle, incluida una advertencia importante: se corrió con `gemini-3.5-flash` (no el `gemini-3.7-flash` de `.env`) porque este último agotó su cuota diaria durante los intentos previos del mismo día — pendiente repetir con el modelo de registro cuando resetee la cuota, si se necesitan las cifras oficiales para el informe.
- ⏳ Pendiente (entregable del Proyecto de Título, §8.7.2/§9 del informe): integración formal de **MITRE ATT&CK vía STIX 2.1** poblando ChromaDB desde el repositorio oficial, y enlace formal CVE ↔ técnica ATT&CK.
- ⏳ Pendiente (§9 del informe): evaluación experimental rigurosa sobre HDFS, BGL y UWF-ZeekDataFall22 con métricas de precisión/recall/F1 y comparación contra baseline de reglas — requerirá tier pagado de Gemini por el límite de cuota del tier gratuito (ver "Modelo LLM en la práctica").
- ✅ **Interfaz web local** (1-sep-2026): panel de análisis (FastAPI + HTML/JS) sobre `src/pipeline.py` — sube un lote de logs, muestra el grafo de 7 nodos ejecutándose en vivo (SSE) y el reporte final. Ver "Interfaz web" arriba. Lógica de streaming (`analizar_lote_stream()`) verificada con el LLM mockeado, dos escenarios (flujo con RAG+CVE, ciclo de corrección de comandos) — pendiente correrla contra la API real y, si se usa para la defensa, contra un dataset más grande que el de ejemplo.
- ⏳ Pendiente (empaquetado/producto): Dockerfile para el sistema de distribución decidido arriba — la interfaz web ya no depende de eso para poder demostrarse localmente.
