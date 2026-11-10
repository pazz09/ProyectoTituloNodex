# NODEX — agente único, 12 casos × 3 repeticiones, 10 de noviembre de 2026

Se ejecutó la arquitectura `agente_unico` (`src/single_agent.py`, `analizar_lote_agente_unico`) sobre los mismos
12 casos de evaluación de las campañas `oficial-12casos`, en las mismas condiciones y **cambiando solo la
arquitectura**. Resultado operacional: **36 análisis completos, cero fallidos, cero incompletos y 36 reportes**;
36 llamadas al modelo, todas con versión efectiva `gemini-3.8-flash`; gasto real **USD 0,927**. No se calcularon
métricas D1–D4, no se compararon salidas con el ground truth y no se aplicó ninguna rúbrica.

| Elemento | R1 | R2 | R3 |
|---|---|---|---|
| Identificador | `agenteunico-12casos-r1-20261110` | `agenteunico-12casos-r2-20261110` | `agenteunico-12casos-r3-20261110` |
| Casos completos / incompletos / fallidos | 12 / 0 / 0 | 12 / 0 / 0 | 12 / 0 / 0 |
| Llamadas al modelo | 12 | 12 | 12 |
| JSON válido a la primera | 12 de 12 | 12 de 12 | 12 de 12 |
| Tokens de entrada | 314.708 | 314.708 | 314.708 |
| Tokens de salida | 6.747 | 6.593 | 6.271 |
| Tokens de razonamiento | 13.018 | 14.378 | 11.377 |
| Costo real (USD) | 0,3101 | 0,3147 | 0,3022 |
| Candidatos MITRE recuperados | iguales en las tres repeticiones y en el preflight | | |

## 1. Diseño y condiciones

**Igual que `oficial-12casos-r1-20261028`:** los 12 casos y su orden (tomados de su `selection.json`, verificados
por tamaño y SHA-256 antes de cada repetición y de cada caso); `gemini-3.8-flash`, `TEMPERATURE=0.0`,
`LLM_SIN_RESPALDO=true`, `REPUTACION_SIN_ENRIQUECIMIENTO=true`, NVD bloqueado con respaldo local registrado,
`all-MiniLM-L6-v2` (revisión `1110a243…`), `TOP_K_ATTACK=3`, pisos 0,55 / 0,42; partición `evaluacion`.
La configuración congelada de cada repetición es una copia de la de R1 en la que cambian solo `config_version`,
`arquitectura` y `repeticion` (más el registro del entorno real; ver §5). Las claves funcionales (`parametros`,
`prompts_sha256`, `capa_experimental_sha256`, `datasets`, `conocimiento`, `semillas`, `recursos_externos`) se
comprobaron idénticas a R1.

**Aislamiento:** un proceso nuevo por caso con `campana.correr_una` sin modificar (copia temporal y desechable de
`experiments/knowledge/chroma_v2`, caché de IP inexistente al inicio, red bloqueada, tope de 2 horas por corrida,
parada tras 3 fallas de infraestructura seguidas). Antes de cada caso se verificó que la copia coincide byte a byte
con la semilla y que las colecciones dinámicas están vacías; al terminar, que la copia se descartó y la semilla
quedó intacta (`<run_id>.isolation.json`). Un caso iniciado nunca se repite (`<run_id>.started.json`). El ground
truth no se leyó durante la inferencia; se copió solo al extraer.

**Despacho sin editar `src/`:** el orquestador original solo conoce tres arquitecturas. El lanzador
(`tools/run_single_agent_campaign.py`) intercepta `campana.ejecutar_hijo` para lanzar su propio proceso hijo
(`--worker`, los mismos 7 argumentos) y, solo dentro del hijo, reemplaza `orquestador._correr_una` con
`unittest.mock.patch` por `tools/single_agent_runner.py::correr_una_agente_unico`, que replica la rama LLM del
orquestador: misma `adaptar(..., arquitectura="agente_unico")`, misma `persistencia.guardar` y misma forma de la
telemetría. Luego llama al `campana.trabajar` original. Las salidas están en `experiments/single_agent/`.
`identidad.py` ya define `agente_unico → unico`, por lo que no hizo falta parchear identificadores.

**Regla de «completa»:** la de NODEX (`nodex.estado_de_ejecucion`): una excepción se clasifica con
`nodex.clasificar_error`; sin excepción, la corrida es completa si trae un veredicto booleano. Si el agente no
entrega el contrato completo (diagnóstico, evaluación o confianza), se registra aparte en
`ejecucion.resultado_incompleto` y en `run_status.jsonl`. **No hubo ningún resultado incompleto** en las 36 corridas.

**Tope de gasto:** USD 2,50 para toda la campaña (`presupuesto.json`). R2 y R3 corrieron con
`--tope-gasto 1.20`, el umbral de detención fijado por la responsable. Antes de cada caso el lanzador recalcula el
gasto real desde la telemetría y no lanza el caso si el gasto más el costo máximo del dataset superaría el tope.
Nunca se acercó: el gasto final fue USD 0,927.

## 2. Qué recibe y qué no recibe el agente único frente a NODEX multiagente

| Aspecto | NODEX multiagente | Agente único |
|---|---|---|
| Entrada | Mismo archivo del caso; mismo preprocesamiento determinístico (`_preparar_estado_inicial`) | Igual |
| Prompt de sistema | Uno por agente: planificador, analista de triage, selector de herramientas, ingeniero de mitigación y auditor final (el auditor agrega `PROMPT_D11`) | Uno solo (texto completo en §3), que incluye `PROMPT_D11` |
| Contexto entregado al modelo | Repartido entre nodos: el triage recibe el resumen del lote y, si el RAG se consultó, patrones y candidatos; el auditor recibe diagnóstico, comandos validados, conteo de CVE, si hubo contexto RAG, contexto de preprocesamiento, catálogo de evidencia y candidatos | En una sola solicitud: resumen del lote acotado (`acotar_resumen_para_prompt`, incluye las IP con `sin_reputacion`), contexto de preprocesamiento, catálogo `EVIDENCIA DISPONIBLE` y `CANDIDATOS MITRE RECUPERADOS POR RAG` |
| Llamadas al modelo por corrida | 5 a 11 (R1–R3 oficiales: BGL 5, salvo 2 corridas con 11; UWF 6 u 11) | 1 (más 1 si el JSON es inválido: `llm_json(retries=1)`); medido: 1 en las 36 corridas |
| Candidatos MITRE ATT&CK | Solo si el selector decide consultar el RAG (`tool_consultar_rag`) | **Siempre**, una vez por caso, con la misma función y el mismo texto de consulta: `ltm.retrieve_attack_techniques(describir_lote_en_prosa(resumen_logs))` sobre la copia de `chroma_v2` del caso, fuera de la llamada al modelo |
| Patrones históricos (`attack_patterns`) | Se consultan con la firma (colección vacía en `chroma_v2`) | No se consultan |
| CVE / NVD | Herramienta `tool_consultar_cve` (NVD bloqueado, respaldo local) | No |
| Reputación de IP | Modo sin reputación (ninguna IP recibe puntaje) | Igual: el resumen trae las IP marcadas `sin_reputacion` |
| Validación de comandos | `tool_validar_comandos` con ciclo de corrección (hasta `MAX_INTENTOS_CORRECCION=2`) | `validate_solution` sobre los comandos propuestos, **sin** ciclo de corrección |
| Replanificación | Sí (planificador, hasta `MAX_REPLANS=1`) | No |
| Auditoría separada | Sí (agente auditor final) | No: el mismo modelo entrega veredictos, confianza y evaluación |
| Contrato de salida | D-11 (`normalizar_d11`, `campos_d11`) | Igual |

**MITRE en BGL (explícito, pedido de la responsable).** El agente único consulta el RAG MITRE en **todos** los
casos, también en BGL. En los 6 BGL, NODEX no recibió candidatos en ninguna de sus tres repeticiones oficiales
(R1, R2 y R3: lista vacía en `/estado_crudo/tecnicas_mitre`). El agente único sí consultó, pero en 5 de los 6 BGL
ninguna técnica superó el piso de similitud 0,42 y la lista llegó vacía; solo **`bgl_eva_balanceado_0001`**
recibió candidatos: T1685.001 (0,527), T1685.004 (0,49) y T1654 (0,458), en las tres repeticiones. Para BGL la
dimensión MITRE es `no_aplica` en los metadatos de los casos.

**MITRE en UWF.** Los candidatos del agente único son exactamente los mismos que recibió NODEX en
`oficial-12casos-r1-20261028`: mismos IDs, mismo orden y mismas similitudes (diferencia 0,0 con 3 decimales):

| Caso | Candidatos (agente único = NODEX R1) |
|---|---|
| uwf_eva_visible_0004 | T1584.002 (0,435), T1071.004 (0,435) |
| uwf_eva_visible_0027 | T1071.004 (0,45), T1584.002 (0,44), T1590.002 (0,424) |
| uwf_eva_sigiloso_0018 | T1584.002 (0,469), T1071.004 (0,463), T1583.002 (0,43) |
| uwf_eva_sigiloso_0024 | T1071.004 (0,434), T1568.002 (0,434), T1584.002 (0,429) |
| uwf_eva_visible_0028 | T1584.002 (0,451), T1071.004 (0,449), T1590.002 (0,435) |
| uwf_eva_sigiloso_0013 | T1071.004 (0,474), T1584.002 (0,452), T1590.002 (0,445) |

En las 36 corridas se comprobó que la lista completa de candidatos llegó al bloque `CANDIDATOS MITRE RECUPERADOS
POR RAG` del prompt y que el texto de consulta coincide con el que se obtiene del resumen interno del agente
(`<run_id>.mitre_retrieval.json`). La recuperación tardó 0,08–0,23 s por caso. Los candidatos son contexto, no
atribuciones: se conservan separados en `mitre/retrieved_candidates*.jsonl` y `mitre/retrieval_observation*.jsonl`.

## 3. Prompt de sistema del agente único (texto completo)

Idéntico en las 36 solicitudes (1.996 caracteres; copiado de `<run_id>.llm_input.json`):

```text
Eres un analista de logs de seguridad. Analiza la evidencia observada y entrega diagnóstico, veredictos independientes y propuesta de mitigación. hay_anomalia incluye fallas operativas; hay_incidente indica específicamente una amenaza de seguridad. confianza mide certeza del diagnóstico, también cuando todo es normal. No afirmes que ejecutaste los comandos. Devuelve SOLO JSON: {"diagnostico":"...", "hay_anomalia":true/false, "hay_incidente":true/false, "confianza":0.0, "evaluacion":"...", "comandos_mitigacion":[]}. 
La salida formal incluye eventos_reconstruidos, secuencia_temporal y
tecnicas_atribuidas. Reconstruye SOLO eventos relevantes usando evidencia
observada del catálogo EVIDENCIA DISPONIBLE. Cita uno o más evidence_uids
existentes: no inventes UIDs ni timestamps. event_id es un identificador interno
distinto del UID del log (event_001, event_002, ...). timestamp debe ser una
marca de los logs citados o null. event_type es una etiqueta breve snake_case.
secuencia_temporal referencia event_id: usa únicamente el orden temporal
observable; orden temporal no implica causalidad. No ordenes eventos sin fecha.
Las técnicas recuperadas por RAG son CANDIDATOS, no conclusiones. Atribuye una
técnica solo si la evidencia observada la respalda; usa un ID MITRE Tdddd o
Tdddd.ddd y evidence_uids válidos. Nunca copies automáticamente candidatos.
Puedes devolver listas vacías. Ausencia de evidencia es preferible a especular.
Usa confidence=null en eventos y técnicas; no inventes probabilidades.
description y justification son breves y verificables; no expongas razonamiento
interno. Añade al objeto JSON estos campos:
"eventos_reconstruidos": [{"event_id":"event_001", "evidence_uids":["UID"],
"timestamp":null, "event_type":"authentication_failure", "description":"...",
"confidence":null}], "secuencia_temporal":["event_001"],
"tecnicas_atribuidas": [{"technique_id":"T1110", "technique_name":"Brute Force",
"evidence_uids":["UID"], "justification":"...", "confidence":null}].
```

El mensaje de usuario se compone, en este orden, de `RESUMEN DEL LOTE:` (JSON acotado), `CÓMO SE INTERPRETÓ EL
LOTE` (contexto de preprocesamiento), `EVIDENCIA DISPONIBLE (catálogo de logs observados)`, el número de registros
omitidos del catálogo y `CANDIDATOS MITRE RECUPERADOS POR RAG (no atribuidos)`. Tamaño: 3.000–6.800 caracteres en
BGL y 100.300–103.300 en UWF. El texto exacto de cada solicitud está en `<run_id>.llm_input.json`.

## 4. Resultados operacionales por caso

Sin métricas de calidad. «Ejecución» es `execution_time` del agente (preprocesamiento + llamada); «pared» es el
tiempo del lanzador (incluye crear el proceso, copiar Chroma, cargar los embeddings y verificar el aislamiento).
Costo con `precios_modelo.json` (USD 0,75 / 3,75 por millón de tokens de entrada / salida; el razonamiento se
factura como salida). Cada caso tuvo 1 llamada y JSON válido a la primera.

**R1 — `agenteunico-12casos-r1-20261110`**

| # | Caso | Entrada | Salida | Razon. | USD | Ejecución | Pared | Cand. |
|---|---|---|---|---|---|---|---|---|
| 1 | bgl_eva_balanceado_0006 | 1.959 | 200 | 606 | 0,0045 | 8,9 s | 26,5 s | 0 |
| 2 | uwf_eva_visible_0004 | 49.572 | 1.011 | 1.653 | 0,0472 | 21,4 s | 39,4 s | 2 |
| 3 | bgl_eva_natural_0031 | 1.803 | 181 | 438 | 0,0037 | 8,5 s | 25,5 s | 0 |
| 4 | bgl_eva_balanceado_0005 | 1.995 | 303 | 532 | 0,0046 | 8,4 s | 25,3 s | 0 |
| 5 | bgl_eva_natural_0016 | 2.432 | 188 | 647 | 0,0050 | 10,3 s | 27,3 s | 0 |
| 6 | uwf_eva_visible_0027 | 49.999 | 867 | 1.916 | 0,0479 | 23,2 s | 40,3 s | 3 |
| 7 | uwf_eva_sigiloso_0018 | 50.679 | 884 | 1.784 | 0,0480 | 22,3 s | 39,3 s | 3 |
| 8 | bgl_eva_natural_0002 | 2.118 | 191 | 531 | 0,0043 | 8,0 s | 24,9 s | 0 |
| 9 | bgl_eva_balanceado_0001 | 2.861 | 370 | 814 | 0,0066 | 11,3 s | 28,4 s | 3 |
| 10 | uwf_eva_sigiloso_0024 | 50.530 | 651 | 1.370 | 0,0455 | 18,4 s | 35,5 s | 3 |
| 11 | uwf_eva_visible_0028 | 50.213 | 1.031 | 1.573 | 0,0474 | 21,9 s | 39,0 s | 3 |
| 12 | uwf_eva_sigiloso_0013 | 50.547 | 870 | 1.154 | 0,0455 | 17,0 s | 34,0 s | 3 |

**R2 — `agenteunico-12casos-r2-20261110`**

| # | Caso | Entrada | Salida | Razon. | USD | Ejecución | Pared | Cand. |
|---|---|---|---|---|---|---|---|---|
| 1 | bgl_eva_balanceado_0006 | 1.959 | 215 | 575 | 0,0044 | 8,7 s | 28,2 s | 0 |
| 2 | uwf_eva_visible_0004 | 49.572 | 1.019 | 1.442 | 0,0464 | 19,0 s | 37,1 s | 2 |
| 3 | bgl_eva_natural_0031 | 1.803 | 186 | 423 | 0,0036 | 7,1 s | 25,2 s | 0 |
| 4 | bgl_eva_balanceado_0005 | 1.995 | 207 | 435 | 0,0039 | 8,3 s | 27,9 s | 0 |
| 5 | bgl_eva_natural_0016 | 2.432 | 175 | 636 | 0,0049 | 9,5 s | 29,1 s | 0 |
| 6 | uwf_eva_visible_0027 | 49.999 | 741 | 2.616 | 0,0501 | 28,1 s | 47,9 s | 3 |
| 7 | uwf_eva_sigiloso_0018 | 50.679 | 897 | 1.555 | 0,0472 | 20,1 s | 37,6 s | 3 |
| 8 | bgl_eva_natural_0002 | 2.118 | 205 | 385 | 0,0038 | 7,2 s | 24,5 s | 0 |
| 9 | bgl_eva_balanceado_0001 | 2.861 | 482 | 765 | 0,0068 | 13,2 s | 30,3 s | 3 |
| 10 | uwf_eva_sigiloso_0024 | 50.530 | 886 | 1.750 | 0,0478 | 21,2 s | 38,5 s | 3 |
| 11 | uwf_eva_visible_0028 | 50.213 | 711 | 2.055 | 0,0480 | 24,3 s | 41,7 s | 3 |
| 12 | uwf_eva_sigiloso_0013 | 50.547 | 869 | 1.741 | 0,0477 | 22,5 s | 39,8 s | 3 |

**R3 — `agenteunico-12casos-r3-20261110`**

| # | Caso | Entrada | Salida | Razon. | USD | Ejecución | Pared | Cand. |
|---|---|---|---|---|---|---|---|---|
| 1 | bgl_eva_balanceado_0006 | 1.959 | 190 | 407 | 0,0037 | 7,5 s | 26,0 s | 0 |
| 2 | uwf_eva_visible_0004 | 49.572 | 978 | 925 | 0,0443 | 16,1 s | 33,4 s | 2 |
| 3 | bgl_eva_natural_0031 | 1.803 | 186 | 555 | 0,0041 | 8,9 s | 25,9 s | 0 |
| 4 | bgl_eva_balanceado_0005 | 1.995 | 183 | 567 | 0,0043 | 8,7 s | 25,6 s | 0 |
| 5 | bgl_eva_natural_0016 | 2.432 | 184 | 535 | 0,0045 | 9,3 s | 26,4 s | 0 |
| 6 | uwf_eva_visible_0027 | 49.999 | 711 | 1.250 | 0,0449 | 16,2 s | 33,2 s | 3 |
| 7 | uwf_eva_sigiloso_0018 | 50.679 | 970 | 1.498 | 0,0473 | 20,8 s | 37,8 s | 3 |
| 8 | bgl_eva_natural_0002 | 2.118 | 207 | 257 | 0,0033 | 6,4 s | 23,4 s | 0 |
| 9 | bgl_eva_balanceado_0001 | 2.861 | 400 | 700 | 0,0063 | 9,0 s | 26,0 s | 3 |
| 10 | uwf_eva_sigiloso_0024 | 50.530 | 775 | 1.306 | 0,0457 | 16,9 s | 34,0 s | 3 |
| 11 | uwf_eva_visible_0028 | 50.213 | 601 | 2.151 | 0,0480 | 22,2 s | 39,4 s | 3 |
| 12 | uwf_eva_sigiloso_0013 | 50.547 | 886 | 1.226 | 0,0458 | 16,9 s | 34,4 s | 3 |

Los tokens de entrada son idénticos entre repeticiones (misma entrada y mismos candidatos); varían la salida y el
razonamiento. Estimación previa (Fase 2): USD 0,29–0,61 por repetición; real: 0,30–0,31.

## 5. Entorno

Se usó el `.venv` del equipo de la responsable por su decisión del 10-nov-2026. **No se presenta el entorno como
idéntico al de las campañas oficiales**, que corrieron en el equipo de Felipe:

| Componente | Campañas oficiales (R1) | Esta campaña |
|---|---|---|
| Python | 3.12.14 | 3.13.5 |
| Plataforma | Windows-11-10.0.26200 | Windows-11-10.0.26300 |
| google-genai | 2.22.0 | 2.25.0 |
| sentence-transformers | 6.0.1 | 6.1.0 |
| transformers | 5.16.1 | 5.17.0 |
| numpy | 2.5.2 | 2.5.3 |
| onnxruntime | 1.29.0 | 1.30.0 |
| langgraph / langchain-core | 1.2.11 / 1.6.1 | 1.2.12 / 1.6.4 |
| pydantic | 2.14.1 | 2.13.5 |
| chromadb, torch, tokenizers, requests, python-dotenv | — | iguales |

63 de 158 paquetes difieren de versión o de presencia (16 paquetes de PDF/Office existen solo en el entorno de R1 y
NODEX no los usa); el detalle está en `compatibility.json` y `environment.json`. Los archivos del modelo de
embeddings coinciden con el inventario de R1 y **la recuperación MITRE resultó idéntica a la de NODEX R1** (§2), de
modo que la diferencia de versiones no alteró los candidatos. El efecto de la versión del SDK sobre la respuesta
del proveedor no es observable desde aquí.

**Código.** 129 archivos registrados en el entorno de R1: 94 iguales byte a byte y 35 distintos solo por los finales
de línea (este repositorio tiene `core.autocrlf=true`). Sin contar los finales de línea, todos son idénticos a la
copia del código de R1; en Git, `src/` no cambió desde el commit de R1 (`46f6a5c`) salvo el agregado
`src/experimentation/knowledge/rag_enriquecido.py`, no usado aquí. `src/` no tiene cambios locales. Los lanzadores de
Felipe comparan bytes y exigen Python 3.12.14, por lo que no podían usarse en este equipo sin cambios; el lanzador
nuevo hace las mismas comprobaciones ignorando solo los finales de línea. R2 y R3 verificaron Python, paquetes,
entradas y semilla idénticos a la R1 del agente único. El `environment.json` de R3 lista además
`tools/export_single_agent_campaign.py`, creado entre la preparación de R2 y la de R3; ningún archivo registrado en
R1 cambió de hash y la orquestación (lanzador y runner) es idéntica en las tres repeticiones. El exportador no se
importa durante la inferencia.

**Archivos de la campaña enriquecida «borrados».** Al actualizar `main2.0` con el commit `3699f5b` de Felipe,
`git status` muestra 8 archivos del snapshot de `prelaunch_failure_20261104` como borrados. **No faltan:** son rutas
más largas que el límite por omisión de Windows; con `git -c core.longpaths=true status` no aparece ninguna
diferencia. No se tocaron ni se ejecutó ningún comando Git que restaure o elimine archivos.

## 6. Incidentes y validación, todos sin llamadas al modelo

1. **Preflight abortado por la salvaguarda.** El preflight lanza un proceso hijo sin credencial y con el modelo
   reemplazado por un sustituto. El hijo se detuvo antes de preprocesar el primer caso porque `src/config.py` ejecuta
   `load_dotenv()` al importarse y volvía a cargar la credencial desde `.env`. Corrección: se pasan las variables
   vacías (`load_dotenv` no sobrescribe una variable definida) y el hijo comprueba la credencial antes y después de
   importar `src.config`; se agregó una prueba. Cero llamadas.
2. **Columna de NODEX vacía en el segundo preflight.** `mitre/retrieved_candidates.jsonl` de R1 tiene dos filas por
   caso (`/estado_crudo/tecnicas_mitre`, con similitud, y `/salida/_meta/mitre_candidates`, sin similitud); el lector
   tomaba la última. Se corrigió para usar solo el estado crudo y se agregó una prueba.
3. Como la configuración congela el hash del lanzador, tras cada corrección la preparación de R1 se rehízo. Las
   preparaciones anteriores no se borraron: están, con su `MOTIVO.md`, en
   `experiments/ejecucion/agenteunico-12casos-coordinacion/preparacion_descartada_r1_20261110/` y `..._b/`. Ninguna
   corrida se inició con ellas.
4. **Granularidad de la detención.** El lanzador se detiene solo ante un modelo efectivo distinto, una diferencia de
   entorno, entradas o semilla, un error del lanzador, tres fallas de infraestructura seguidas o el tope de gasto. Un
   caso fallido o incompleto aislado no detiene la repetición en curso (cortar en medio dejaría un caso iniciado que
   no puede repetirse); se revisó cada repetición completa antes de lanzar la siguiente. No hubo ninguno.

**Pruebas.** `tests/experimentation/test_single_agent_campaign.py`: 27 pruebas offline con modelo simulado (despacho,
candidatos en el prompt, mismo esquema que NODEX, identificadores, no repetición, tope de gasto, clasificación,
proceso hijo, finales de línea, preflight sin modelo y sin credencial, lectura de NODEX R1, exportador). Pasan
`test_runners.py`, `test_official_extraction.py` y `test_official_repetitions.py`. En `test_enriched_campaign.py`
**fallan 2 de 7 pruebas en este equipo**, por el entorno y no por esta campaña:

- `test_functional_sources_and_effective_dependency_paths_match`: «Python distinto de R1» (su lanzador exige
  3.12.14).
- `test_snapshot_inventory_is_verified_without_modifying_it`: «Corpus cambiado después de su validación». De los 61
  archivos del corpus enriquecido, 30 son idénticos y 31 difieren solo en los finales de línea (CRLF). Ese corpus
  (`rag_enriquecido_30_v1`) no participa en esta campaña.

**Presupuesto previo.** La proporción caracteres/token se calibró reconstruyendo sin modelo el prompt del auditor de
NODEX R1 desde su estado crudo y comparándolo con su `input_tokens` medido (BGL 2,98–3,11; UWF 2,07–2,09). Los
scripts y la calibración están en `agenteunico-12casos-coordinacion/procedimiento_presupuesto/`.

## 7. Limitaciones

- Comparación entre arquitecturas con entornos distintos (§5): la arquitectura no es la única diferencia física,
  aunque la configuración, el código funcional, las entradas y la recuperación MITRE sí coinciden.
- Las campañas no son simultáneas (NODEX: 28-oct y 3-nov; agente único: 10-nov). El proveedor devolvió la misma
  versión nominal, pero no puede certificarse que el modelo servido sea idéntico.
- El agente único recibe candidatos MITRE siempre; NODEX solo cuando su selector consulta el RAG. En UWF el contenido
  recuperado coincide; en BGL difiere en un caso (`bgl_eva_balanceado_0001`).
- El estado crudo es el estado final preservado, no el archivo de todas las respuestas HTTP del proveedor. No se
  miden CPU, RAM, GPU ni costo facturado; el costo es el calculado con la tabla de precios.
- La presencia de un candidato en el prompt no demuestra que el modelo lo haya usado en su razonamiento.

## 8. Extracción

Cada repetición tiene `extracted_data/agenteunico-12casos-rN-20261110/`, en el mismo formato que
`extracted_data/oficial-12casos-r1-20261028/`: `originals/` (entradas, ground truth copiado solo al extraer,
predicciones, crudos, telemetría, consola, configuración, código, semilla `chroma_v2`, registros de aislamiento,
de recuperación MITRE y del texto enviado al modelo), `detection/`, `reconstruction/`, `mitre/` (candidatos separados
de las atribuciones), `reports/`, `performance/`, `manifest.json`, `manifest.csv`, `extraction.json`,
`run_status.jsonl`, `verification.json`, `repetition_integrity.json`, `README.md`, `procedure/` y el notebook de
revisión. Se generó con `tools/export_single_agent_campaign.py`, que reutiliza sin modificar
`tools/export_experimental_data.py` y `tools/verify_official_repetition.py` (adaptados en tiempo de ejecución: las
predicciones se leen de `experiments/single_agent/` y el verificador acepta los nombres `agenteunico-…`). Las
entradas y las referencias exportadas tienen los mismos hashes que las copias de R1.

```powershell
.venv\Scripts\python.exe tools/export_single_agent_campaign.py --config-version agenteunico-12casos-r1-20261110
```

Los hashes de los ZIP se registran al final de este documento después de la extracción; la copia de este documento
dentro de `procedure/` de cada paquete es anterior a ese registro.
