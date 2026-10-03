# Protocolo experimental de NODEX

**Versión del protocolo:** 1.0 · **Versión de los contratos:** 1.0
**Estado:** `PREPARADA_SIN_EJECUTAR` (Fase 1). Ninguna regla de este
documento se ha ejecutado todavía.

Define **qué se mide, contra qué referencia, con qué unidad y qué pasa
cuando algo falla**, para que el código no tenga que resolver esas
preguntas inventando un criterio. Los ejemplos de este documento son
**exclusivamente ilustrativos** y están marcados como tales: no son
resultados.

---

## 1. Dos preguntas de detección que no se pueden mezclar

HDFS y BGL etiquetan **anomalías de sistema** (un bloque que falla, un
kernel que entra en pánico). UWF-ZeekDataFall22 etiqueta **tráfico
malicioso**. No son la misma pregunta y NODEX las responde con campos
distintos:

| Tipo | Pregunta | Campo del estado de NODEX | Datasets |
|---|---|---|---|
| `operativa` | ¿el sistema se comporta de forma anómala? | `hay_anomalia` | HDFS, BGL |
| `seguridad` | ¿hay actividad maliciosa? | `hay_incidente` | UWF |

**Regla.** Cada caso declara su `tipo_deteccion`. El evaluador lee el campo
que corresponde a ese tipo (`CAMPO_VEREDICTO_POR_TIPO` en
`src/experimentation/contracts/enums.py`) y **se niega** a puntuar si
recibe el otro. No es una preferencia de estilo: comparar `hay_incidente`
contra etiquetas de BGL ya produjo recall 0,0 en este proyecto por una
razón puramente metodológica —el auditor distinguía correctamente una falla
de hardware de un ataque— y se interpretó como una falla del modelo.

En el contrato común de salida, `classification` usa el par
`BENIGN`/`MALICIOUS` que fija el plan. Para un caso `operativa` se lee como
normal/anómalo. El par de palabras no cambia la pregunta: la pregunta la
fija el caso.

---

## 2. Dimensiones y aplicabilidad

Cinco dimensiones **por caso** (D1–D5). La comparación con el agente único
que pide el formulario **no es una dimensión de caso**: es una comparación
entre arquitecturas sobre las mismas cinco dimensiones, y se calcula al
agregar (§7). Modelarla como sexta dimensión por caso mediría dos veces lo
mismo.

| Dimensión | Entrada | Salida evaluada | Referencia |
|---|---|---|---|
| D1 detección | `TestCase.contenido` | `classification` | `GroundTruth.etiqueta_deteccion` |
| D2 reconstrucción | ídem | `reconstructed_events[].uid`, `temporal_sequence` | `GroundTruth.core_event_uids` (ERR) |
| D3 MITRE | ídem | `mitre.tactics[]`, `mitre.techniques[]` con `evidence_uids` | `GroundTruth.referencias_mitre` |
| D4 reporte | ídem | `report.summary` | Rúbrica humana (no hay reporte gold) |
| D5 consumo | ídem | `RunRecord.telemetria` | No tiene referencia: se describe, no se acierta |

### Aplicabilidad por dataset

| Dimensión | HDFS | BGL | UWF |
|---|---|---|---|
| D1 detección | sí (`operativa`) | sí (`operativa`) | sí (`seguridad`) |
| D2 reconstrucción | `no_aplica` | `no_aplica` | sí |
| D3 MITRE | `no_aplica` | `no_aplica` | sí (táctica y técnica) |
| D4 reporte | rúbrica sobre submuestra | ídem | sí |
| D5 consumo | sí | sí | sí |

**Por qué `no_aplica` y no "pendiente":** HDFS y BGL solo traen una
etiqueta binaria por bloque o por línea. No existe en esos datasets una
lista de eventos núcleo ni un mapeo ATT&CK. Marcar esas dimensiones como
pendientes sugeriría que una anotación futura las habilitaría; marcarlas
`no_aplica` dice la verdad: **no hay referencia que obtener sin
inventarla**, y el plan prohíbe inventarla.

**D5 no tiene aciertos.** El consumo se reporta (tiempo, llamadas, tokens,
modelo efectivo, reintentos), no se compara contra un valor esperado. Los
umbrales operativos, si se definen, son criterio de aceptación (§10), no
una referencia.

---

## 3. Estados no puntuables

Cuatro estados, nunca colapsados entre sí ni convertidos en acierto o en
caso normal:

| Estado | Significa | Efecto en denominadores | Bloquea cierre |
|---|---|---|---|
| `no_aplica` | La dimensión no corresponde al caso **por diseño** | Fuera de todo denominador | No |
| `referencia_pendiente` | Corresponde, pero la anotación humana no está aprobada | Fuera de todo denominador | Sí, para esa dimensión |
| `fallido` | La ejecución no terminó (error de API, caída, timeout) | Fuera de la matriz de confusión | No, pero se informa |
| `no_evaluable` | Terminó, pero la salida no cumple el contrato | Fuera de métricas de calidad | No, pero se informa |

`fallido` y `no_evaluable` se separan porque la causa es distinta: una es de
ejecución y la otra de contrato de salida. Un agotamiento de cuota y un JSON
con forma de lista exigen acciones opuestas, y agruparlos esconde cuál
ocurrió. Ambos casos ya se dieron en este proyecto.

**Invariante contable.** Para toda dimensión y arquitectura:

```
n_casos == n_evaluables + Σ n_por_estado[estado_no_puntuable]
```

`MetricsRecord.__post_init__` lo verifica y lanza si no cuadra. Un caso que
se pierde entre medio invalida la métrica, no se redondea.

---

## 4. Unidad de análisis y matching

**Unidad:** el caso (`TestCase`). Una ejecución = un caso × una arquitectura
× una repetición. Las métricas de detección se calculan desde la matriz de
confusión agregada, nunca promediando un F1 por caso (§7).

| Dataset | Qué es un caso | Clave de agrupación (`grupo`) | Etiqueta del caso |
|---|---|---|---|
| BGL | Ventana contigua de N líneas | La ventana temporal | Anómalo si alguna línea de la ventana está marcada como alerta |
| HDFS | Conjunto de bloques cuyas líneas se intercalan en orden original | `blk_...` | Derivada del contenido efectivo del caso (§4.1) |
| UWF | Caso definido por el ERR | Sesión / incidente | `BENIGN` / `MALICIOUS` del ERR |

### 4.1 HDFS: la etiqueta se deriva del contenido efectivo

Defecto a corregir en la Fase 2 (ya diagnosticado, no corregido todavía):
el agrupador usa `re.search`, que toma **solo el primer** `blk_` de cada
línea. Una línea que referencia dos bloques queda contabilizada únicamente
bajo el primero, así que una línea perteneciente a un bloque anómalo puede
entrar en un caso etiquetado como normal.

**Regla del protocolo:** la etiqueta de un caso HDFS se deriva de **todos**
los bloques referenciados por sus líneas. Si el contenido efectivo incluye
algún bloque `Anomaly`, el caso es anómalo, aunque se haya construido como
negativo. Si esa derivación contradice la intención de construcción, el
caso se descarta; no se fuerza la etiqueta.

### 4.2 Reconstrucción (D2): matching exacto por `uid`

Para UWF/ERR, comparación **exacta de conjuntos**:

```
referencia  = set(GroundTruth.core_event_uids)
prediccion  = {e.uid for e in reconstructed_events if e.uid}
```

Las tolerancias temporales y las equivalencias de entidad quedan
**reservadas para datasets sin identificador estable**. UWF tiene `uid` de
Zeek: aplicar tolerancias ahí sería aflojar la medición sin necesidad.

`temporal_sequence` se valida como orden de los `uid` ya reconstruidos: el
contrato rechaza una secuencia que mencione un `uid` ausente de
`reconstructed_events`.

### 4.3 MITRE (D3): por nivel declarado, sin inferir

- Se evalúa **táctica** y **técnica**, cada una como comparación de
  conjuntos de IDs al nivel que la referencia declara.
- **Subtécnica ausente en la referencia → `no_aplica`.** No se infiere una
  subtécnica a partir de la técnica para completar el ground truth.
- Solo se puntúa lo **atribuido** (`mitre.tactics` / `mitre.techniques`).
  Lo recuperado por similitud viaja en `_meta.mitre_candidates` y no se
  cuenta como afirmación del sistema.
- Una atribución sin `evidence_uids` se registra como atribución sin
  evidencia: cuenta para la comparación de conjuntos, y el hecho de que no
  tenga respaldo se informa aparte.

### 4.4 Reporte (D4): rúbrica humana, sin texto de referencia

El plan prohíbe ampliar el ERR con `gold_claims`, `expected_facts`,
reportes gold o conclusiones esperadas. En consecuencia **no hay métrica
automática de calidad de reporte**. Se evalúa con rúbrica humana sobre
cinco criterios: completitud, corrección factual, coherencia con la
evidencia, claridad e información no sustentada. La escala y los umbrales
son decisión académica (§10).

---

## 5. Particiones de desarrollo y evaluación

- La partición es **por grupo**, no por caso: ningún `grupo` puede aparecer
  en las dos particiones.
- Un caso cuyos grupos caen a ambos lados se **descarta**, no se asigna
  arbitrariamente.
- `desarrollo` se usa para depurar y para el piloto. **Las métricas que se
  reportan salen exclusivamente de `evaluacion`.**
- La proporción es decisión académica (§10).

El solapamiento de bloques entre casos del generador HDFS actual (los
bloques normales se reutilizan entre lotes) queda registrado como
limitación a resolver en la Fase 2.

---

## 6. Métricas y denominadores vacíos

Sobre casos `evaluable` únicamente. Positivo = `anomalo` / `MALICIOUS`.

| Métrica | Fórmula | Indefinida cuando |
|---|---|---|
| accuracy | (TP+TN) / (TP+FP+FN+TN) | el total es 0 |
| precision | TP / (TP+FP) | TP+FP = 0 (no predijo ningún positivo) |
| recall | TP / (TP+FN) | TP+FN = 0 (no había positivos reales) |
| **F1** | **2·TP / (2·TP + FP + FN)** | 2TP+FP+FN = 0 |
| FPR | FP / (FP+TN) | FP+TN = 0 |
| FNR | FN / (FN+TP) | FN+TP = 0 |

**`None` significa indefinida, no cero.** Un recall indefinido (no había
positivos) y un recall 0 (había y no detectó ninguno) describen situaciones
opuestas.

**Corrección respecto del cálculo actual.** `_metricas()` en
`src/tools/eval_deteccion.py` calcula F1 como `2·P·R/(P+R)` con la guarda
`if precision and recall`. Como `0.0` es falso en Python, un caso con TP=0,
FP=6, FN=1 devuelve `None` cuando el valor correcto es **0**. Eso ocurrió
en la evidencia de la fase 6 anterior, donde HDFS 3,1% multiagente aparece
con F1 "no definido" teniendo 6 falsos positivos. La forma directa
`2TP/(2TP+FP+FN)` lo resuelve. **La corrección se implementa en la Fase 5**;
los resultados históricos no se recalculan ni se sobrescriben: cualquier
corrección genera artefactos nuevos con su versión de protocolo.

Para D2 y D3, comparación de conjuntos con las mismas fórmulas (`set_*`),
más `exact_match` = fracción de casos en que los conjuntos coinciden por
completo.

---

## 7. Comparación entre arquitecturas

Tres arquitecturas, una sola variable experimental:

| Arquitectura | Qué es |
|---|---|
| `nodex_multiagente` | El grafo completo (5 agentes LLM + 3 herramientas) |
| `agente_unico` | **Un** agente LLM responsable de todo el análisis |
| `baseline_reglas` | Clasificador determinístico sin LLM, comparación adicional |

**El baseline de reglas no sustituye al agente único.** Son comparaciones
distintas: el primero responde "¿cuánto aporta el LLM sobre reglas
evidentes?", el segundo "¿cuánto aporta la arquitectura multiagente sobre
un único agente con los mismos recursos?". El formulario pide el segundo, y
no estaba implementado.

Para que la comparación mida la arquitectura y no el presupuesto: mismo
modelo configurado, misma temperatura, mismos casos, misma información
disponible y mismos recursos externos. **No** se fuerza al agente único a
recorrer la misma secuencia de pasos que NODEX: eso convertiría la variable
en otra cosa.

**Agregación.** Las métricas de detección por dataset y arquitectura se
calculan sumando las matrices de confusión de los casos, no promediando F1
por caso. Entre repeticiones se reporta media, mediana y desviación,
declarando siempre la unidad de agregación.

---

## 8. Contratos

Código: `src/experimentation/contracts/`. Dos versiones distintas:

- `CONTRATO_VERSION` — la **forma** de los artefactos.
- `PROTOCOLO_VERSION` — las **reglas** de interpretación. Dos campañas con
  protocolo distinto no son comparables.

| Contrato | Rol | Nunca contiene |
|---|---|---|
| `TestCase` | Entrada para una arquitectura | Etiquetas ni referencias |
| `GroundTruth` | Referencia para el evaluador | — (solo lo recibe el evaluador) |
| `ExperimentConfig` | Configuración congelada de la campaña | Secretos (solo presencia de credenciales) |
| `RunRecord` | Bitácora de una ejecución | — |
| `ExperimentalOutput` | Salida normalizada común | Clasificación derivada de confianza |
| `MetricsRecord` | Métricas de una dimensión | Casos no puntuables mezclados con evaluables |

`TestCase` y `GroundTruth` son clases separadas, en directorios separados
(`experiments/cases/` y `experiments/ground_truth/`), vinculadas solo por
`case_id`. `GroundTruth.__post_init__` rechaza `anotacion.fuente ==
"nodex"`: construir la referencia con la salida del sistema evaluado
invalida la medición.

La procedencia reutiliza `src/tools/provenance.py` sin reimplementarla.

---

## 9. Defectos conocidos que el protocolo nuevo no debe heredar

| Defecto | Dónde está hoy | Tratamiento en el protocolo nuevo |
|---|---|---|
| F1 indefinido donde corresponde 0 | `_metricas()` | Fórmula directa (§6), corregida en Fase 5 |
| Primer `blk_` por línea | `_agrupar_por_bloque()` | Etiqueta derivada de todos los bloques (§4.1), Fase 2 |
| Bloques reutilizados entre lotes | `_seleccionar_bloques_hasta()` | Partición por grupo (§5), Fase 2 |
| Prevalencia 0,031 que da 0,05 efectiva | `n_pos = max(1, round(...))` | Se registran solicitada y efectiva; no se llama 3,1% a una muestra de 1/20 |
| Veredicto derivado de confianza | `_prediccion_desde_estado()` | Prohibido: `no_evaluable` (§3). El evaluador de detección actual ya lo bloquea con `_error_evaluacion_desde_estado()`; la derivación sobrevive como código muerto y **no se reintroduce** |
| Cronología confundida con reconstrucción | Reporte actual | Campos separados (§2, D2) |
| Candidatas MITRE tratadas como atribuciones | `tecnicas_mitre` del estado | `mitre` vs. `_meta.mitre_candidates` (§4.3) |

---

## 10. Decisiones académicas pendientes

El plan ordena presentarlas, no resolverlas por cuenta propia. Hasta que se
decidan, el protocolo las trata como `DECISION_PENDIENTE` y **ningún
umbral se da por fijado**.

| # | Decisión | Por qué no la puede tomar el código |
|---|---|---|
| D-1 | Proporción desarrollo / evaluación | Define cuántos casos quedan para reportar; es un criterio de diseño experimental |
| D-2 | Número de repeticiones `N` por caso | Compromiso entre medir variabilidad y gastar cuota |
| D-3 | Umbrales de aceptación por dimensión (¿qué F1, qué `set_f1`, qué nota de rúbrica es "aprobar"?) | Es el criterio de éxito de la tesis, no un parámetro técnico |
| D-4 | Escala de la rúbrica de reporte y nº de evaluadores humanos | Metodología de evaluación cualitativa |
| D-5 | Si la comparación con sistemas externos será experimental o bibliográfica | Depende de qué sistema reproducible esté disponible (el plan lo vuelve a pedir en la Fase 9) |
| D-6 | Tamaño de la muestra de D4 (reporte) por dataset | Costo de anotación humana |

---

## 11. Qué no está verificado

Este protocolo fue revisado **estáticamente**. No se ejecutó ninguna
prueba, ningún evaluador y ninguna llamada a modelos. En particular:

- Las reglas de matching no se probaron contra datos reales.
- Los contratos no se instanciaron fuera de los archivos de prueba
  escritos en `tests/experimentation/`, que **no se ejecutaron**.
- UWF-ZeekDataFall22 no está disponible localmente: todo lo definido para
  ese dataset (D2, D3, matching por `uid`) está especificado pero no
  confrontado con el ERR real.
