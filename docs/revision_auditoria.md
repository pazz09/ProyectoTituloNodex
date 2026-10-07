# Revision auditoria

Fecha de revisión: 25 de septiembre de 2026
Rama revisada: `main`
Commit experimental: `1dc2dfe70a52c04659c6f2d94f1058217d99cfa0`
Referencia de la auditoría anterior: `c5bb1fe`

## 1. Resumen ejecutivo

El proyecto sí incorporó cambios sustanciales después de la auditoría anterior. Entre `c5bb1fe` y `b30aa0a` se integraron 32 commits que modificaron 51 archivos, con 6320 inserciones y 233 eliminaciones.

Las dos correcciones que motivaron esta revisión están implementadas y verificadas:

1. El doble preprocesamiento por lote fue eliminado tanto del pipeline productivo como del baseline.
2. El agente de triage recibe el contexto v2 del preprocesamiento desde su primera pasada y también después de consultar RAG.

La fase 7 también fue incorporada antes de la fase 6. Ese cambio de orden es técnicamente razonable: fijar dependencias y configurar CI antes de regenerar métricas mejora la reproducibilidad de la evaluación.

La fase 6 fue completada después de esta revisión: se agregó trazabilidad reproducible, un orquestador de cierre y se ejecutaron los tres baselines y las tres evaluaciones multiagente. Las corridas descubrieron y permitieron corregir dos defectos: el tratamiento de checkpoints parciales como predicciones normales y la aceptación de listas JSON donde los agentes requerían objetos.

Dictamen general actualizado: **las fases 1 a 7 están implementadas; la fase 6 dispone de seis artefactos finales reproducibles y de un manifiesto automático de cierre**.

## 2. Evidencia utilizada

La revisión consideró:

- Inspección del historial Git y comparación entre `c5bb1fe` y `b30aa0a`.
- Inspección del pipeline productivo, baseline, agente de triage, contexto v2 y evaluador.
- Revisión de los 33 JSON históricos y de los seis artefactos finales más el manifiesto de fase 6.
- Revisión de `requirements.txt`, `constraints.txt`, `frontend/package.json` y `.github/workflows/ci.yml`.
- Ejecución completa de la suite backend con credenciales Gemini vacías.

Resultado de la suite actual:

```text
544 passed, 1 warning in 51.43s
```

La única advertencia proviene de `starlette.testclient` por el alias deprecado `anyio.abc.BlockingPortal`. No bloquea la ejecución, pero conviene corregirla mediante una actualización compatible de dependencias cuando se planifique mantenimiento técnico.

## 3. Estado general por fase

| Fase | Objetivo | Estado actual | Evaluación |
|---|---|---|---|
| 1 | Ejecutar el preprocesamiento una sola vez por lote | Resuelta | Verificada en código y pruebas de conteo real de invocaciones |
| 2 | Incorporar contexto v2 en la primera pasada de triage | Resuelta | Verificada en ambas pasadas y con presupuesto de caracteres |
| 3 | Hacer efectivo `LOG_PRESERVE_RAW` | Resuelta con alcance limitado | Controla persistencia/exportación, pero no las muestras enviadas al LLM |
| 4 | Completar metadatos, trazabilidad y contratos | Resuelta en su alcance | Se agregaron metadatos, golden tests, política de tamaño y procedencia del baseline |
| 5 | Actualizar documentación y presentación | Resuelta con residuos menores | README y documentación principal actualizados; persisten algunas referencias históricas a v1 |
| 6 | Regenerar la evidencia experimental final | **Resuelta** | Seis corridas completas, cero lotes fallidos y manifiesto reproducible para `1dc2dfe` |
| 7 | Incorporar CI y fijar dependencias | Implementada | Archivos y scripts presentes; backend verificado localmente; ejecución remota no comprobada en esta revisión |

## 4. Cambios solucionados

### 4.1. Preprocesamiento único por lote

Estado: **solucionado**.

El flujo actual concentra el procesamiento en `preprocesar_lote()`:

1. `src/tools/aggregation.py:49` llama una sola vez a `preprocesar(raw)`.
2. `src/tools/aggregation.py:50` genera una sola vez el agregado v2 mediante `agregar_v2()`.
3. `src/tools/aggregation.py:95` deriva el resumen compatible v1 usando exactamente el mismo resultado y agregado v2.
4. `src/pipeline.py:102` consume las tres vistas retornadas por `preprocesar_lote()`.
5. `src/pipeline.py:111` construye los metadatos desde los objetos ya calculados, sin reprocesar el texto.
6. `src/tools/baseline_reglas.py:97` utiliza el mismo punto de entrada y tampoco vuelve a parsear el lote.

La solución está protegida por `tests/test_preprocesamiento_unico.py`. Las pruebas cuentan las invocaciones reales y verifican que tanto `preprocesar()` como `agregar_v2()` se ejecuten exactamente una vez en el pipeline y en el baseline.

Consecuencias positivas:

- Se elimina el costo duplicado de CPU y latencia.
- El resumen compatible v1 y los metadatos v2 provienen de la misma ejecución.
- Se elimina el riesgo de que dos pasadas independientes produzcan estados divergentes.
- Los errores de preprocesamiento dejan de degradarse silenciosamente a metadatos vacíos.

### 4.2. Contexto v2 en el agente de triage

Estado: **solucionado**.

`src/agents/agente_analista_triage.py` utiliza `_contexto_pre()` en los dos caminos del agente:

- Primera pasada: `src/agents/agente_analista_triage.py:137-143`.
- Segunda pasada, después de RAG: `src/agents/agente_analista_triage.py:98-110`.

El contexto contiene una selección acotada de:

- Cantidad de eventos y líneas físicas.
- Cobertura del parsing.
- Advertencias de parsing.
- Distribución de decoders.
- Productos y perfiles reconocidos.
- Severidades y categorías.
- Muestras limitadas de registros.

`src/preprocessing/prompt_context.py` protege los campos esenciales. Si se supera `CONTEXTO_PREPROCESAMIENTO_MAX_CHARS`, elimina primero muestras y distribuciones; mantiene los conteos globales, la cobertura y las advertencias mientras sea posible.

Las pruebas actuales verifican:

- Presencia del contexto v2 en la primera pasada.
- Presencia del contexto en la segunda pasada.
- Respeto del presupuesto de caracteres con HDFS real.
- Ausencia de fuga de ground truth con BGL real.
- Exclusión de campos v2 no autorizados para el prompt.

### 4.3. `LOG_PRESERVE_RAW`

Estado: **solucionado parcialmente por diseño**.

La variable ya tiene un efecto real sobre la persistencia y exportación:

- Con `false`, la cronología no utiliza directamente el texto crudo.
- Se enmascaran IP, usuario y host cuando fueron reconocidos por el preprocesamiento.
- Se conserva una procedencia basada en hash SHA-256, cantidad de líneas y bytes.

La variable no controla las muestras enviadas al LLM. `contexto_preprocesamiento()` sigue pudiendo incluir texto de muestra en el prompt de triage aunque `LOG_PRESERVE_RAW=false`. Esto está documentado en `README.md:224-226` y continúa siendo una brecha de privacidad conocida.

### 4.4. Metadatos, trazabilidad y lotes heterogéneos

Estado: **solucionado en el alcance definido**.

Se incorporaron:

- `profile_distribution`.
- `event_outcomes`.
- Entidades enriquecidas.
- Ventana temporal.
- Distribuciones de vendor, versión y protocolo.
- `decoder_distribution` por segmento.
- Decoder efectivo e información del intento inicial del segmento.
- Golden tests para BGL, HDFS y un lote mixto.
- Contrato explícito del esquema agregado v2.
- Política uniforme de rechazo de lotes sobredimensionados.
- Uso de versión y fabricante como apoyo para la consulta de CVE.

También se agregó procedencia al baseline: motor, versión de esquema, configuración y commit.

### 4.5. Documentación y frontend

Estado: **mayoritariamente solucionado**.

Cambios comprobados:

- Se creó `docs/pipeline_preprocesamiento.md`.
- Se actualizó el README con configuración y limitaciones.
- Se corrigieron docstrings que describían la integración v2 como futura.
- Se añadió una explicación visual sobre decoder frente a producto/perfil.
- Se documentaron variables que antes no aparecían, como `SCORE_MALICIOSO` y `SCORE_SOSPECHOSO`.

Residuo menor:

- Algunos comentarios y pruebas todavía usan expresiones como “motor v1” para describir estados sin metadatos. El motor v1 ya no es seleccionable, por lo que sería más preciso hablar de “estado legado o incompleto sin `preprocessing_metadata`”. No afecta la ejecución.

## 5. Evaluación específica de la fase 7

### 5.1. Elementos implementados

La fase 7 está presente en el repositorio:

- `requirements.txt` fija versiones directas con `==`.
- `constraints.txt` fija dependencias transitivas.
- `.github/workflows/ci.yml` define jobs separados de backend y frontend.
- El backend instala con `requirements.txt` más `constraints.txt` y ejecuta pytest sin credenciales Gemini.
- El frontend instala con lockfile congelado y ejecuta lint, typecheck, test y build.
- `frontend/package.json` contiene scripts `lint`, `typecheck` y `test`.
- Se agregó un smoke test para comprobar la sincronización del catálogo de nodos con el grafo.

### 5.2. Validación realizada en esta revisión

- Backend: **537/537 pruebas aprobadas**.
- Frontend: no fue posible repetir localmente lint, typecheck, test y build porque el entorno actual no contiene `pnpm` ni `frontend/node_modules`.
- GitHub Actions: el workflow ya está en `origin/main`, pero no fue posible consultar sus ejecuciones mediante la API pública porque el repositorio respondió como no accesible sin autenticación.

Por lo tanto, la formulación precisa es:

> La fase 7 está implementada y el backend está verificado localmente. La ejecución efectiva del job remoto y la repetición local del frontend no quedaron comprobadas en esta revisión.

### 5.3. ¿Fue correcto ejecutar la fase 7 antes que la fase 6?

Sí. El cambio de orden es correcto porque la fase 6 genera evidencia que debe ser reproducible. Fijar primero dependencias, comandos y CI reduce el riesgo de obtener métricas que después no puedan reconstruirse.

Adelantar la fase 7 permitió ejecutar después la fase 6 sobre dependencias fijadas y un commit identificable. La secuencia quedó finalmente completada.

## 6. Evaluación específica de la fase 6

Estado actualizado: **completa y certificada por manifiesto**.

Desde la revisión inicial se incorporaron `src/tools/provenance.py` y `src/tools/fase6.py`, se añadieron pruebas y se generaron seis artefactos finales con el motor `heterogeneo`. El cierre corresponde al commit `1dc2dfe70a52c04659c6f2d94f1058217d99cfa0`; todas las corridas declaran `evaluation_status="complete"`, árbol limpio y `n_fallidos=0`.

### 6.1. Evidencia histórica que motivó la corrección

Se revisaron los 33 JSON presentes en `results/`:

- El resultado más reciente fue generado el 9 de septiembre de 2026.
- No existe ningún commit posterior al 9 de septiembre que agregue resultados nuevos.
- Cero archivos registran el commit de ejecución.
- Cero archivos declaran `motor_preprocesamiento: "heterogeneo"`.
- Cero archivos incluyen las métricas actuales `n_evaluados` y `n_fallidos`.
- Los resultados más recientes todavía declaran `motor_preprocesamiento: "v2"`.
- Los archivos de evaluación usan el modelo anterior de `lotes_abortados` y `metricas_excluyendo_abortos`.

Esto no coincide con el código actual:

- `src/config.py:276` fija el motor como `heterogeneo`.
- `src/tools/eval_deteccion.py` ahora registra fallos por lote con `estado="error"`.
- `_metricas()` informa `n_evaluados` y `n_fallidos`.
- El contexto de triage cambió después de los resultados históricos.
- Los enriquecedores, metadatos y política de tamaño también cambiaron después de esas corridas.

`docs/informe_cierre_auditoria.md` confirma la misma situación:

- Se identifica como un “borrador vivo”.
- Indica explícitamente que la fase 7 se adelantó antes de la fase 6.
- Señala que el evaluador quedó preparado para la fase 6, pero que todavía faltaba correrlo con datos reales.

### 6.2. Resultados históricos que no deben presentarse como actuales

| Ejecución histórica | Precision | Recall | F1 | Observación |
|---|---:|---:|---:|---|
| Multiagente BGL | 0,7143 | 1,0000 | 0,8333 | Motor registrado como `v2` |
| Multiagente HDFS balanceado | 0,5000 | 0,9000 | 0,6429 | Incluye abortos según el esquema anterior |
| Multiagente HDFS prevalencia 3,1% | 0,0556 | 1,0000 | 0,1053 | Alta cantidad de falsos positivos |
| Baseline BGL | 1,0000 | 0,4000 | 0,5714 | Sin procedencia del commit |
| Baseline HDFS balanceado | No definida | 0,0000 | No definida | No detectó positivos |
| Baseline HDFS prevalencia 3,1% | No definida | 0,0000 | No definida | No detectó positivos |

Estas métricas pueden conservarse como línea base histórica, pero no demuestran el comportamiento del código en `b30aa0a`.

### 6.3. Defectos corregidos al ejecutar la fase 6

La procedencia ya fue centralizada para baseline y multiagente. Registra commit, rama, estado del árbol, motor, esquema, configuración, entorno, dependencias, modelos y hashes de datasets.

Durante BGL se encontró otro defecto: cuando la API colapsaba, `analizar_lote()` devolvía el checkpoint parcial con valores iniciales y el evaluador lo interpretaba como una predicción normal. Ahora el pipeline agrega `_error_api`; el evaluador exige diagnóstico, evaluación del auditor y veredicto booleano. Un estado incompleto queda como lote fallido y fuera de la matriz de confusión.

El artefacto BGL interrumpido fue marcado como inválido y no debe citarse como métrica.

También se corrigió el contrato JSON: `llm_json()` ya no entrega listas a agentes que esperan objetos. La suite final quedó en **544 pruebas aprobadas** y una advertencia externa de Starlette/AnyIO.

### 6.4. Resultados finales

| Sistema | Dataset | TP | FP | FN | TN | Precisión | Recall | F1 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Baseline | BGL | 10 | 4 | 0 | 2 | 0,7143 | 1,0000 | 0,8333 |
| Multiagente | BGL | 10 | 4 | 0 | 2 | 0,7143 | 1,0000 | 0,8333 |
| Baseline | HDFS balanceado | 0 | 0 | 10 | 10 | no definida | 0,0000 | no definido |
| Multiagente | HDFS balanceado | 1 | 3 | 9 | 7 | 0,2500 | 0,1000 | 0,1429 |
| Baseline | HDFS 3,1% | 0 | 0 | 1 | 19 | no definida | 0,0000 | no definido |
| Multiagente | HDFS 3,1% | 0 | 6 | 1 | 13 | 0,0000 | 0,0000 | no definido |

`results/fase6_manifest.json` referencia los seis JSON y sus SHA-256. La
conmutación automática desde `gemini-3.1-pro-preview`, que alcanzó su cuota
diaria durante BGL, hacia `gemini-3.6-flash` permitió completar HDFS sin
lotes fallidos. La baja sensibilidad en HDFS es una limitación medida del
sistema y queda como línea de mejora posterior.

## 7. Elementos aún ausentes o pendientes

### Prioridad alta

1. **Rendimiento HDFS insuficiente.** Recall 0,10 en el conjunto balanceado y 0,00 con prevalencia 3,1%; requiere investigación antes de uso operativo.
2. **Validación remota de CI no comprobada.** El workflow existe, pero esta revisión no confirmó una ejecución de GitHub Actions.

### Prioridad media

1. **Privacidad frente al LLM.** `LOG_PRESERVE_RAW=false` no evita que muestras de logs salgan hacia Gemini.
2. **Apache/NCSA Combined.** Sigue sin existir un decoder específico para este formato.
3. **Relación CVE-MITRE ATT&CK.** Ambos dominios continúan recuperándose por separado, sin enlace formal.
4. **CPE estructurado.** Vendor y versión mejoran el término de búsqueda, pero todavía no se normalizan contra el diccionario CPE.
5. **Frontend no reverificado localmente.** Faltan `pnpm` y dependencias instaladas en el entorno actual.
6. **Advertencia de Starlette/AnyIO.** No bloquea, pero representa deuda de compatibilidad.

### Prioridad baja

1. Sustituir referencias residuales al “motor v1” por formulaciones de estado legado o metadatos ausentes.
2. Separar resultados históricos y resultados finales en subdirectorios o mediante un manifiesto para impedir que se confundan.
3. Incorporar en el README una insignia o enlace al workflow cuando su ejecución remota esté confirmada.

## 8. Consecuencias sobre la arquitectura

Los cambios realizados no reemplazan la arquitectura general. La consolidan:

- El preprocesador continúa siendo determinístico y previo a los agentes.
- El grafo sigue consumiendo un resumen compatible v1 más metadatos v2.
- La salida v2 está más completa, pero su exposición al prompt sigue gobernada por una allowlist.
- Las correcciones no reintroducen adaptadores HDFS/BGL como motor principal.
- HDFS y BGL siguen funcionando como enriquecimientos de producto/perfil sobre decoders genéricos.

La arquitectura actual queda respaldada tanto por pruebas automatizadas como por una evaluación experimental trazable. Esa evidencia también revela que la calidad de detección no es uniforme: BGL conserva recall 1,00, mientras HDFS alcanza solo 0,10 en balanceado y 0,00 con prevalencia 3,1%.

## 9. Recomendación de cierre

Siguientes acciones recomendadas, fuera del cierre de fase 6:

1. Investigar por qué las etiquetas de bloque HDFS no quedan reflejadas con suficiente señal en ventanas de 120 líneas y evaluar agregación por ciclo completo de bloque.
2. Calibrar el veredicto para reducir falsos positivos ante advertencias operativas comunes de HDFS.
3. Registrar explícitamente por llamada el modelo efectivo cuando actúa el fallback, además de los modelos configurados.
4. Confirmar una ejecución verde del workflow de GitHub Actions sobre `main` después del próximo push.
5. Mantener como trabajo futuro las limitaciones de privacidad frente al LLM, Apache/NCSA y CVE-ATT&CK.

## 10. Dictamen final

El proyecto avanzó de forma efectiva y resolvió los dos problemas principales consultados: doble preprocesamiento y falta de contexto v2 en la primera pasada del triage.

La fase 7 fue implementada antes que la fase 6 por una razón válida de reproducibilidad. La fase 6 quedó posteriormente completada sobre el commit `1dc2dfe70a52c04659c6f2d94f1058217d99cfa0`, con seis artefactos completos y `results/fase6_manifest.json`. Los resultados históricos, preliminares y la corrida BGL inválida no forman parte de la evidencia final.

Por lo tanto, el cierre técnico puede resumirse así:

- Implementación del pipeline heterogéneo: **vigente y verificada**.
- Doble preprocesamiento: **resuelto**.
- Contexto v2 en triage: **resuelto**.
- Metadatos, documentación y CI: **considerablemente mejorados**.
- Fase 6 y métricas finales reproducibles: **completadas y certificadas**.
- Cierre completo de auditoría: **alcanzado**, con rendimiento HDFS pendiente de mejora.

## 11. Extensión D-11 del contrato experimental — 7 de octubre de 2026

El cierre anterior corresponde a detección y al pipeline de preprocesamiento.
La revisión D-11 detectó una brecha adicional: el diagnóstico narrativo y los
candidatos MITRE recuperados no constituían predicciones estructuradas de
reconstrucción ni atribución. Se extendió el contrato a `d11-v1`.

La implementación añade `eventos_reconstruidos`, `secuencia_temporal` y
`tecnicas_atribuidas` con evidencia trazable, validación posterior al LLM,
normalización tolerante a respuestas parciales y contador de UIDs inválidos.
El Auditor existente produce estos campos en la misma llamada. El estado
LangGraph los transporta hasta el reporte SSE/API, persistencia JSON, CLI y
adaptador experimental. La topología, routers, RAG y reglas D1 permanecen.

El comparador de agente único, que no existía en `src`, produce el mismo
contrato sin ejecutar el grafo. Se selecciona mediante `--arquitectura
agente_unico`. La telemetría registra solicitudes reales, modelo efectivo,
consumo informado por el proveedor, duración, replanificaciones, correcciones
acumuladas y UIDs inválidos. No estima tokens ausentes.

Ver diagnóstico, archivos modificados, contrato anterior/nuevo, flujo final y
limitaciones en [Contrato de salida D-11](contrato_salida_d11.md).

**Validación efectivamente ejecutada:**

- `pytest tests/ -q`: **569 passed**, en 57,57 s. Una advertencia de deprecación
  de Starlette/AnyIO, sin fallos. Incluye API, persistencia, PDF, preprocesamiento,
  agentes, routers y topología del grafo.
- Después de corregir el caso donde un evento inválido reservaba su ID y añadir
  su prueba, `pytest tests/test_output_contract_d11.py -q`: **26 passed**, en
  48,10 s. Esta verificación final también ejercita el cliente LLM con respuesta
  SDK simulada dentro de LangGraph y comprueba su consumo en el reporte.
- El fixture A/B/C recorre entrada → grafo compilado → D2/D3 → adaptador → JSON
  experimental, además de streaming y CLI. El agente único y la ausencia de
  etiquetas Zeek en su prompt se prueban explícitamente. No hubo consultas
  reales al proveedor LLM ni se usó ground truth como contexto de inferencia.
- `python -m compileall -q src tests/test_output_contract_d11.py` y
  `git diff --check`: sin errores.

El `.venv` local apunta a un Python 3.12.10 eliminado. Las pruebas se ejecutaron
con Python 3.12.14 del runtime disponible, utilizando las dependencias locales
del proyecto. Windows bloqueaba la DLL instalada de `uuid_utils`; se instaló
la misma versión fijada (`0.17.1`) en `tmp/d11-test-deps`, sin cambiar los locks.
Se desactivó la autocarga de plugins opcionales de pytest y se vaciaron las
credenciales de proveedores para la corrida completa. No se ejecutó build del
frontend, cuyos archivos no cambiaron, ni una campaña con LLM real.

**Dictamen D-11:** contrato implementado y verificado con pruebas deterministas
e integración. La cobertura de evidencia se limita al catálogo visible (40
registros por defecto; el recorte se declara). El comparador no consulta RAG
por defecto, por lo que el protocolo debe declarar el acceso a herramientas.
El scoring D2/D3 requiere ground truth específico y matching predefinido.
Los artefactos históricos de fase 6 no certifican el consumo D5 ni las
capacidades D2/D3 de esta extensión: la campaña final debe usar `d11-v1` sobre
un commit limpio.
