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
  (`eval_deteccion.py`) tenía el mismo problema — resuelto por separado,
  ver la sección "Evaluador" más abajo.
- Suite: 499/499 tras el cierre de A1 (499 en el momento; la suite total
  creció con las fases y hallazgos siguientes -- ver el conteo de cada
  commit).

### A2 — Contexto v2 en la primera pasada del triage

**Estado: resuelto.**

- Commits: `fase2: contexto v2 en la primera pasada del triage` (`128bd86`)
  y `fase2: prioridad de recorte explícita en contexto_preprocesamiento`
  (`0619751`), ambos en `cierre-auditoria`.
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
- Prioridad de recorte confirmada por Antonia: si el texto supera el
  presupuesto, se arma un núcleo protegido (eventos/líneas totales,
  cobertura, advertencias) que nunca se recorta, y se van quitando los
  bloques recortables (muestras primero, después distribuciones) de menor
  a mayor prioridad hasta que quepa. Recorte ciego solo si el núcleo por
  sí solo ya excede el presupuesto (no se dio en ninguna medición real).
- Suite: 507/507 tras el commit `0619751`.

### A3 — `LOG_PRESERVE_RAW`

**Estado: resuelto (Opción A).**

- Antes de este cierre, `LOG_PRESERVE_RAW` estaba declarada, documentada y
  persistida en la configuración efectiva de cada corrida, pero ningún
  componente la leía — el raw se conservaba siempre.
- **Dónde se persistía/exportaba el raw** (relevado antes de implementar):
  - `data/historial.db`, columna `resumen_json` → `cronologia[].mensaje`
    (hasta 40 entradas por corrida, texto crudo truncado a 180
    caracteres) y los campos `ip`/`ip_destino`/`usuario` de cada entrada.
    Es el punto de persistencia real — el único encontrado.
  - El informe en PDF (`/api/historial/{job_id}/pdf`) renderiza esa misma
    cronología: es una exportación de lo ya persistido, no una fuente de
    raw aparte.
  - `results/*.json` (CLI `log_runner.py`, `eval_deteccion.py`,
    `baseline_reglas.py`): **no** incluían cronología ni raw en ningún
    campo — confirmado por revisión de código, no solo supuesto.
  - `raw_samples` (muestras de hasta 500 caracteres por decoder): se
    envían al navegador durante el streaming en vivo, pero **nunca se
    persisten a disco** — quedan fuera del alcance de "persistencia y
    exportación".
  - Logs de aplicación (stdout): no imprimen contenido crudo del lote.
- **Implementación**: default `LOG_PRESERVE_RAW=true` (compatibilidad con
  el historial existente). Con `false`, `_cronologia_v2()`
  (`src/preprocessing/aggregation.py`) arma el mensaje siempre desde el
  evento ya decodificado (nunca `raw`) y lo redacta (`_redactar_mensaje`):
  IPs por patrón, usuarios/hosts por sustitución de los valores que el
  propio preprocesamiento ya extrajo para ese evento. Los campos
  `ip`/`ip_destino`/`usuario` de cada entrada de cronología se enmascaran
  igual — redactar el texto y dejar el mismo valor en un campo estructurado
  al lado habría sido una redacción a medias. En su lugar se persiste
  `raw_procedencia` (hash SHA-256, líneas, tamaño), calculado siempre
  (`src/tools/aggregation.py::_procedencia_raw`), tenga o no efecto la
  variable.
- **Límite de la redacción, documentado a propósito**: no es un análisis
  de PII en texto libre — cubre lo que el propio sistema ya identificó
  como IP/usuario/host para ese evento. Un valor que el enriquecedor no
  reconoció como tal queda tal cual.
- **Lo que la variable NO controla, aclarado en `src/config.py`,
  `.env.example` y el README**: las muestras que `contexto_
  preprocesamiento()` arma para el prompt del Triage (Fase 2) llegan a la
  API de Gemini sin pasar por acá, con `true` o con `false`. Si se
  necesita que ningún log crudo salga hacia el LLM, es un cambio aparte,
  no cubierto por este cierre — dejado explícito, no descubierto por
  accidente.
- **Alcance de la redacción confirmado por diseño, no por accidente**:
  `reputacion_ips`, `ips_distintas`, `por_ip` y `usuarios` (agregados
  estructurados, no reproducción del log) NO se redactan y siguen
  mostrando las IPs -- es el comportamiento correcto: son hallazgos del
  sistema, no una copia del raw.
- Commit: `fase3: LOG_PRESERVE_RAW tiene efecto real (opción A)` (`c8bcc0b`).
- Pruebas: cronología con/sin raw (IP, usuario, host), `raw_procedencia`
  con hash/líneas/bytes verificados, persistencia real vía el flujo
  completo (subida → stream → historial) con LLM simulado, exportación en
  PDF (no revuelve a tocar el raw, solo lee lo ya persistido), y forma de
  la respuesta del historial sin cambios cuando no hay raw.

## Fase 4 — Enriquecer trazabilidad y metadatos

### M1 — Perfiles, outcomes, entidades, ventana, vendor/versión/protocolo

**Estado: resuelto.** Commit `fase4-m1` (`6f2ddca`).

`agregar_v2()` ya calculaba `profile_distribution`, `event_outcomes`,
`entities` (ricas) y `time_window`, pero `_metadatos_desde_v2()`
(`src/pipeline.py`) nunca los propagaba al estado del grafo -- se agregan
ahí. Nuevas `vendor_distribution`, `version_distribution` y
`protocol_distribution` en `agregar_v2()` (solo las pueblan hoy CEF/LEEF
y el mapeo genérico clave-valor de Zeek).

**Hallazgo real durante la verificación**: `profile_distribution` estaba
en la allowlist del prompt del Triage desde la Fase 2 (el código ya la
leía), pero como el estado nunca la poblaba, la línea "Perfiles de
enriquecimiento aplicados" NUNCA apareció en un prompt real -- un cable
suelto que los tests de la Fase 2 no detectaron porque pasaban metadatos
sintéticos directo a la función, sin pasar por el estado real. Este
commit lo conecta por primera vez.

**Impacto medido en el presupuesto del prompt** (contradice la
expectativa inicial de "M1 no toca el prompt" -- corregido apenas se
midió, ver más abajo):

| Dataset | `contexto_preprocesamiento()` (Fase 2 → post-M1) | 1ª pasada (Fase 2 → post-M1) |
|---|---|---|
| HDFS_2k | 484 → 538 car. | 7 935 → 8 121 car. |
| BGL_2k  | 541 → 594 car. | 4 275 → 4 460 car. |

El delta completo (~53-54 caracteres en ambos) es la línea "Perfiles de
enriquecimiento aplicados" apareciendo por primera vez -- no un campo
nuevo agregado al prompt a propósito en la Fase 4. `entities`,
`time_window`, `event_outcomes` y las tres distribuciones nuevas SÍ están
en el estado pero NO se agregaron a la allowlist del prompt (confirmado
por test: `tests/test_triage_contexto_v2.py::
test_los_campos_nuevos_de_m1_no_llegan_al_prompt`). Ambos casos siguen
muy por debajo del presupuesto de 2000 caracteres. Test de fuga de ground
truth con BGL_2k real, vuelto a correr después de los cambios: sigue en
verde.

### M2 — Versión conectada a la búsqueda de CVEs

**Estado: resuelto.** Commit `fase4-m2` (`b5fa272`).

`elegir_keyword()` (`src/tools/tool_consultar_cve.py`) ya leía
`vendor_distribution` desde antes del cierre (esperando un dato que nunca
existía); M1 lo generó, y este commit conecta la versión dominante al
término de búsqueda ("FortiGate 7.0" en vez de "FortiGate"), solo cuando
el término viene de producto/fabricante. No se arma un CPE estructurado
-- exigiría normalizar al vocabulario exacto del diccionario CPE de NIST,
que no se justifica mientras `version_distribution` solo la pueblen
CEF/LEEF.

### M3 — Segmentos híbridos

**Estado: resuelto.** Commit `fase4-m3` (`10070e7`).

Decisión de Antonia: no dividir segmentos (cambiaría la trazabilidad y
la salida esperada de los golden tests, sin una ganancia que lo
justifique) ni publicar una distribución efectiva aparte -- en vez de
eso, **recalcular** `RecordSegment.decoder`/`.confidence` desde los
eventos ya decodificados del segmento (después del reproceso individual
del modo `hybrid`), y conservar el intento inicial sobre el bloque
completo en `decoder_inicial`/`confidence_inicial`, para trazabilidad.
Antes, un segmento con eventos JSON/syslog/texto mezclados podía
reportarse como "text @ 0.33" aunque la mayoría de sus registros se
hubiera decodificado bien -- probado con un caso real donde diverge
(json @ 0.5 inicial vs. syslog @ 0.95 efectivo).

### M5 — Procedencia del baseline

**Estado: resuelto.** Commit `fase4-m5` (`d2b999c`).

`baseline_reglas.py` no registraba nada de procedencia; `eval_
deteccion.py` ya registraba motor/configuración desde la Fase 11 del plan
original. A los dos les faltaba el commit. Nuevas `_procedencia()` y
`_commit_git()` (`git rev-parse HEAD`, `None` si falla) en
`baseline_reglas.py`, agregadas al JSON que se guarda en `results/`.

### M6 — Política de tamaño unificada

**Estado: resuelto.** Commit `fase4-m6` (`2360092`).

Decisión de Antonia: rechazar en todos los caminos. Antes de este
cierre, el mismo archivo daba dos respuestas distintas según la puerta
de entrada: la API (`/api/analizar`) ya rechazaba con HTTP 413 un
archivo sobre `LOG_MAX_FILE_BYTES`, pero `preprocesar()` (el único
chequeo que tienen el CLI y el evaluador, que no validan nada por su
cuenta) truncaba el texto y seguía analizando, con una advertencia de
severidad "error" en vez de detenerse. `LOG_MAX_EVENTS` tenía el mismo
patrón un nivel más abajo, en `segmentar()`. Los dos ahora rechazan
(`PreprocesamientoError`/`ValueError`, envuelto igual por la
infraestructura de la Fase 1) -- el CLI y el evaluador ya sabían
manejar esa excepción, no hizo falta tocarlos.

### Golden tests heterogéneos y contratos de esquema v2

**Estado: resuelto.** Commit `fase4` (`f2d3e90`).

`tests/golden/*_esperado.json` (lote mixto sintético, HDFS_2k, BGL_2k
reales): subconjunto curado de `agregar_v2()` -- distribuciones y
agregados, no los eventos crudos ni las muestras (2000 eventos por
dataset harían un archivo enorme e ilegible en el diff, y esos campos no
son deterministas de forma útil de versionar). `test_contrato_de_
esquema_v2` fija la forma completa de `agregar_v2()` (18 claves con su
tipo) sobre tres entradas distintas.

### Corrección post-cierre de M3 (revisión de Antonia)

El commit original de M3 (`10070e7`) no incluía `decoder_distribution`
por segmento -- la propuesta original ("publicar la distribución
efectiva junto al dominante") quedó implícita en la decisión de
recalcular, pero nunca se agregó como campo. Además, el mensaje del
commit y el test describían el caso de prueba como "syslog es mayoría
real" cuando en realidad es un EMPATE (2 json, 2 syslog) que
`_decoder_efectivo()` desempata por orden alfabético del nombre del
decoder, no por frecuencia. Corregido en `dde2250`: se agregó
`decoder_distribution` al contrato de `RecordSegment`, y se corrigió el
lenguaje en código y tests para no describir un empate como mayoría.

## Fase 5 — Documentación

**Estado: resuelto.**

- `docs/pipeline_preprocesamiento.md` (nuevo, commit `36a2d9e`): flujo
  completo, actores y responsabilidades por etapa, contrato v2→v1, qué
  llega al prompt del Triage (la allowlist) y qué no, con el motivo, y
  la explicación de `decoder` vs. producto/perfil.
- **M4** (commit `9df108c`): 6 archivos con docstrings de módulo
  desactualizados (describían una migración v1→v2 en curso que terminó
  hace tiempo) y 7 referencias a `docs/*.md` eliminados, corregidas o
  redirigidas a rutas reales (`data/labels/hdfs_anomaly_label_2k.csv`
  en vez de un documento que explicaba cómo conseguirlo). No se tocaron
  las menciones históricas a "esquema v1"/"adaptador" que explican por
  qué una decisión de diseño vigente es como es -- esas siguen siendo
  ciertas.
- **M7** (commit `71f2c6e`): investigado antes de tocar código -- el
  frontend hoy NUNCA muestra el decoder crudo en ninguna vista;
  `formato_detectado` (lo único que se muestra) ya resuelve al
  producto/perfil cuando existe, así que HDFS/BGL ya se ven como tales,
  no como "TEXT". El caso literal que M7 describe no tiene hoy una
  ubicación en la UI. Se agregó igual un tooltip explicativo en las tres
  vistas que muestran `formato_detectado`, cubriendo el espíritu del
  hallazgo. Verificado con `npx tsc --noEmit` (limpio) y `npx next
  build` (build de producción completo sin errores).
- README (commits `36a2d9e`... `0696ae7`): nueva sección "Configuración"
  con el efecto real de 17 variables; "Alcance y limitaciones conocidas"
  con la tercera limitación de privacidad (exposición al LLM); mención
  de decoder vs. producto/perfil en "Preprocesamiento"; `docs/` agregado
  al árbol de "Estructura del proyecto".
- **Revisión cruzada README ↔ código ↔ .env.example**: verificado que
  las 33 variables de `.env.example` están documentadas (17 en la tabla
  nueva; el resto -- modelo LLM, reintentos/backoff, memoria, MITRE --
  ya cubiertas en otras secciones o de bajo impacto de comportamiento) y
  que no hay contradicciones de valores. Verificado contra el código:
  8 nodos del grafo (5 LLM + 3 Tool) y 4 aristas condicionales
  (`src/graph/build_graph.py`), 31 campos de `LogGuardState`
  (`src/state.py`), puerto 3010 del frontend (`frontend/package.json`).
  Se encontró y corrigió un hueco real: `SCORE_MALICIOSO`/
  `SCORE_SOSPECHOSO` no estaban documentados en ningún lado (commit
  `0696ae7`).

## Limitaciones conocidas y trabajo futuro

- **Exposición al LLM no cubierta por `LOG_PRESERVE_RAW`.** La variable
  controla la persistencia local (`data/historial.db`) y la exportación
  (PDF) del raw -- **no** lo que se envía a Gemini. Las muestras que
  `contexto_preprocesamiento()` arma para el prompt del Triage (Fase 2)
  llegan a la API de Gemini sin pasar por esta variable, con `true` o con
  `false`. Decisión explícita de Antonia (23-sep-2026): no se implementa
  como parte de este cierre -- queda documentada como trabajo futuro. Si
  se necesita que ningún log crudo salga hacia el LLM, es un cambio
  aparte y más invasivo (tocaría qué ve el modelo para diagnosticar, no
  solo qué se guarda), a decidir por separado.
- **Estimación de tokens.** Los números de tokens que aparecen en este
  informe (p. ej. la tabla de la Fase 2) usan la heurística
  ~4 caracteres/token, no un conteo del tokenizer real de Gemini -- no
  hay forma de medirlo sin gastar cuota de API. Son una aproximación para
  dimensionar el orden de magnitud, no una cifra exacta.

## Evaluador (`eval_deteccion.py`)

**Estado: resuelto.** Commit: `eval: un lote fallido no aborta la corrida
ni se salta en silencio` (`7cd0c06`).

Decisión (23-sep-2026): un fallo de preprocesamiento en un lote no debe
abortar la corrida completa ni saltarse en silencio. `correr_evaluacion()`
atrapa `PreprocesamientoError` por lote, sigue con el resto, y registra el
lote fallido con `estado="error"` y su mensaje. `_metricas()` excluye
explícitamente de la matriz de confusión los resultados sin `prediccion`
válida e informa `n_evaluados`/`n_fallidos`. Implementado ahora (no se
espera a la Fase 6 para el código, solo para correrla con datos reales).
Suite: 509/509 tras este commit.
