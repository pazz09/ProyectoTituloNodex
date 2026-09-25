# Revision auditoria

Fecha de revisión: 24 de septiembre de 2026  
Rama revisada: `main`  
Commit revisado: `b30aa0a`  
Referencia de la auditoría anterior: `c5bb1fe`

## 1. Resumen ejecutivo

El proyecto sí incorporó cambios sustanciales después de la auditoría anterior. Entre `c5bb1fe` y `b30aa0a` se integraron 32 commits que modificaron 51 archivos, con 6320 inserciones y 233 eliminaciones.

Las dos correcciones que motivaron esta revisión están implementadas y verificadas:

1. El doble preprocesamiento por lote fue eliminado tanto del pipeline productivo como del baseline.
2. El agente de triage recibe el contexto v2 del preprocesamiento desde su primera pasada y también después de consultar RAG.

La fase 7 también fue incorporada antes de la fase 6. Ese cambio de orden es técnicamente razonable: fijar dependencias y configurar CI antes de regenerar métricas mejora la reproducibilidad de la evaluación.

La fase 6 fue iniciada después de esta revisión: se agregó trazabilidad reproducible, un orquestador de cierre y se ejecutaron los tres baselines. La evaluación multiagente BGL se interrumpió al agotarse los créditos de Gemini y reveló un defecto adicional en el tratamiento de estados parciales, que ya fue corregido. Por tanto, la fase está desarrollada pero todavía no puede declararse cerrada.

Dictamen general actualizado: **las fases 1 a 5 están implementadas, la fase 7 está implementada y la fase 6 está en ejecución bloqueada por crédito externo; faltan las tres corridas multiagente válidas y el manifiesto final**.

## 2. Evidencia utilizada

La revisión consideró:

- Inspección del historial Git y comparación entre `c5bb1fe` y `b30aa0a`.
- Inspección del pipeline productivo, baseline, agente de triage, contexto v2 y evaluador.
- Revisión de los 33 archivos JSON existentes en `results/`.
- Revisión de `requirements.txt`, `constraints.txt`, `frontend/package.json` y `.github/workflows/ci.yml`.
- Ejecución completa de la suite backend con credenciales Gemini vacías.

Resultado de la suite actual:

```text
537 passed, 1 warning in 81.27s
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
| 6 | Regenerar la evidencia experimental final | **En curso / bloqueada** | Baselines y mecanismo de cierre listos; Gemini agotó créditos durante BGL |
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

El problema no fue adelantar la fase 7. El problema es que, una vez completada, no se continuó con la ejecución efectiva de la fase 6.

## 6. Evaluación específica de la fase 6

Estado actualizado: **desarrollada, parcialmente ejecutada y bloqueada por crédito de Gemini**.

Desde la revisión inicial se incorporaron `src/tools/provenance.py` y `src/tools/fase6.py`, se añadieron pruebas y se generaron baselines nuevos con el motor `heterogeneo`. La corrida multiagente BGL se interrumpió por `402 RESOURCE_EXHAUSTED`; HDFS no se inició para evitar artefactos artificiales.

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

### 6.4. Trabajo requerido para cerrar la fase 6

Para completar la fase 6 todavía se debe ejecutar y guardar, sobre un commit limpio y fijado:

1. Baseline determinístico sobre BGL.
2. Baseline determinístico sobre HDFS balanceado.
3. Baseline determinístico sobre HDFS con prevalencia real aproximada de 3,1%.
4. Evaluación multiagente sobre BGL.
5. Evaluación multiagente sobre HDFS balanceado.
6. Evaluación multiagente sobre HDFS con prevalencia real.
7. Registro separado y auditable de lotes fallidos.
8. Comparación con las métricas históricas, explicando que el contexto de triage cambió y que la comparación no es completamente 1:1.
9. Actualización de `docs/informe_cierre_auditoria.md`, reemplazando el estado de borrador por un cierre con métricas, commit y configuración.

## 7. Elementos aún ausentes o pendientes

### Prioridad alta

1. **Fase 6 bloqueada por crédito externo.** Los baselines están disponibles, pero faltan BGL y las dos evaluaciones HDFS multiagente válidas.
2. **Commit limpio pendiente.** Los baselines preliminares registran `working_tree_dirty=true` y deben repetirse después de confirmar los cambios.
3. **Validación remota de CI no comprobada.** El workflow existe, pero esta revisión no pudo confirmar una ejecución de GitHub Actions.

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

La principal consecuencia pendiente es metodológica: sin fase 6, la arquitectura actual está verificada por pruebas, pero no por una nueva evaluación experimental comparable y trazable.

## 9. Recomendación de cierre

Orden recomendado desde el estado actual:

1. Confirmar los cambios de procedencia, evaluación y orquestación en un commit limpio.
2. Restablecer crédito de Gemini y confirmar una ejecución verde del workflow de GitHub Actions sobre `main`.
3. Ejecutar `python -m src.tools.fase6 --modo todo` sobre el commit resultante.
4. Revisar lotes fallidos y evitar mezclar fallos de infraestructura con predicciones.
5. Comparar resultados actuales con los históricos, explicitando cambios de contexto y esquema.
6. Finalizar `docs/informe_cierre_auditoria.md` con métricas, commit, configuración y fecha.
7. Mantener como trabajo futuro las limitaciones de privacidad frente al LLM, Apache/NCSA y CVE-ATT&CK.

## 10. Dictamen final

El proyecto avanzó de forma efectiva y resolvió los dos problemas principales consultados: doble preprocesamiento y falta de contexto v2 en la primera pasada del triage.

La fase 7 fue implementada antes que la fase 6 por una razón válida de reproducibilidad. La fase 6 ya tiene implementación, baselines y controles de cierre, pero la evaluación multiagente no terminó porque Gemini agotó sus créditos. Los resultados históricos y la corrida BGL inválida no deben utilizarse como evidencia final del pipeline actual.

Por lo tanto, el cierre técnico puede resumirse así:

- Implementación del pipeline heterogéneo: **vigente y verificada**.
- Doble preprocesamiento: **resuelto**.
- Contexto v2 en triage: **resuelto**.
- Metadatos, documentación y CI: **considerablemente mejorados**.
- Fase 6 y métricas finales reproducibles: **en curso; bloqueadas por crédito y commit limpio**.
- Cierre completo de auditoría: **todavía no alcanzado**.
