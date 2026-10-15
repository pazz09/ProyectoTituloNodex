# Estado de preparación del espacio de pruebas de NODEX

**Plan de referencia:** `plan_preparación de pruebas_revisado.md` (2 de octubre de 2026).
**Alcance autorizado:** preparar la infraestructura experimental. **No ejecutar pruebas, experimentos ni llamadas a modelos.**
**Rama de preparación:** `preparacion-entorno-pruebas`.
**Worktree de preparación:** `C:\Users\antop\Desktop\ProyectoTituloNodex-pruebas`.
**Checkout original (intacto):** `C:\Users\antop\Desktop\NODEX`, rama `main`.

> `PREPARADA_SIN_EJECUTAR` significa que los artefactos existen y fueron
> revisados estáticamente. **No** significa que el sistema haya superado
> ninguna prueba.

## 1. Punto de partida

| Elemento | Valor |
|---|---|
| Repositorio (origin) | `https://github.com/pazz09/ProyectoTituloNodex.git` |
| Commit de origen | `6adc3436cdb9de38f5bf310fa06beb0f37247aac` |
| Rama de origen | `main`, sincronizada con `origin/main` |
| Commit de origen (fecha / autor / asunto) | 2026-09-25 02:26:42 -0300 / Felipe Bravo Romo / `docs: cerrar fase 6 con evidencia reproducible` |
| Tipo de checkout | Completo, no *shallow* (68 commits de historial) |
| Estado del árbol al ramificar | Limpio (sin cambios locales ni archivos sin seguimiento) |
| Worktrees previos | Ninguno (solo el checkout original) |

### Decisión sobre el ZIP (Fase 0, acción 2 del plan)

El plan pide comparar la versión del repositorio con un ZIP y documentar
cuál será el punto de partida. **No se encontró ningún ZIP** en el
directorio del proyecto ni en el escritorio, y la consulta al respecto no
recibió indicación de un archivo alternativo.

**Decisión registrada:** se adopta el repositorio real (`origin/main` @
`6adc343`) como punto de partida y fuente de verdad. Si más adelante
aparece un ZIP que represente otra versión, la diferencia debe
reconciliarse explícitamente **antes** de la Fase 2, porque afectaría la
procedencia de los casos.

### Actualización del punto de partida (3-oct-2026, al abrir la Fase 2)

`origin/main` avanzó a **`b0fe5de` "Dataset UWF"** (Felipe Bravo Romo), que
agrega los 13 archivos Parquet de UWF-ZeekDataFall22 en
`data/logs/UWF-ZeekDataFall22-parquet/` (44 862 135 bytes). Se trajo con
`git merge --ff-only` al `main` local y se integró a esta rama con un merge
(`bbec894`), de modo que el dataset está disponible tanto en el checkout
original como en el worktree de preparación.

El punto de partida de la Fase 2 en adelante es por lo tanto `b0fe5de`, no
`6adc343`. La Fase 0 y la Fase 1 se cerraron sobre `6adc343` y no se
rehacen: no dependen del dataset.

## 2. Registro de fases

| Fase | Estado | Autorización recibida | Entregables | Commit | Pendientes |
|---|---|---|---|---|---|
| 0 — Aislar el trabajo y fijar el punto de partida | PREPARADA_SIN_EJECUTAR | Sí (3-oct-2026) | Rama `preparacion-entorno-pruebas`, worktree aislado, commit de origen documentado, este registro | `26832c2` | Verificaciones de entorno que exigen ejecución (§6) |
| 1 — Definir el protocolo y los contratos experimentales | PREPARADA_SIN_EJECUTAR | Sí (3-oct-2026) | `docs/experimentacion/protocolo.md`; contratos en `src/experimentation/contracts/`; 4 archivos de prueba en `tests/experimentation/` (escritos, sin ejecutar) | `d3a3234` | 6 decisiones académicas pendientes (§8) |
| 2 — Preparar datasets y casos con segmentación válida | PREPARADA_SIN_EJECUTAR (HDFS, BGL y UWF) | Sí (3-oct-2026) | `hallazgos_datasets.md`, `regenerar_uwf.md`; `src/experimentation/datasets/` (8 módulos); **336 casos + 336 referencias** y 5 manifiestos en `experiments/`; `requirements-experimentacion.txt`; 3 archivos de prueba (escritos, sin ejecutar) | `fb77559`, UWF en `d467486` | UWF requiere un motor Parquet (autorización de instalación); D-7 a D-10 |
| 3 — Preparar ground truth y conocimiento aislado | PREPARADA_SIN_EJECUTAR, salvo el poblado de ChromaDB | Sí (4-oct-2026) | `anotacion_ground_truth.md`; `src/experimentation/knowledge/` (4 módulos) y `subconjuntos.py`; `estado_mitre_por_nivel` en las 336 referencias; `experiments/knowledge/inventario_conocimiento.json`; subconjuntos piloto (24) y rúbrica (24); 1 archivo de controles de aislamiento (escrito, sin ejecutar) | `114b32d` | Poblar la base vectorial del experimento requiere autorización (acción 6) |
| 4 — Hacer evaluables las salidas de NODEX | PREPARADA_SIN_EJECUTAR, con **D2 y D3 bloqueadas por una decisión** | Sí (4-oct-2026) | `src/experimentation/adapters/` (4 módulos); extensión de contrato de agentes propuesta y **sin conectar**; 1 archivo de pruebas (escrito, sin ejecutar) | `192d181` | NODEX no produce reconstrucción ni atribución MITRE: ver §11 |
| 5 — Implementar los evaluadores externos | PREPARADA_SIN_EJECUTAR | Sí (5-oct-2026) | `src/experimentation/evaluators/` (8 módulos); fixtures con la aritmética hecha a mano (`tests/experimentation/fixtures/`); 1 archivo de pruebas (escrito, sin ejecutar) | `eddd9b3` | D-12: qué coeficiente de concordancia informar |
| 6 — Preparar telemetría y configuración congelable | PENDIENTE_AUTORIZACION | No | — | — | — |
| 7 — Preparar almacenamiento y orquestación sin ejecución | PENDIENTE_AUTORIZACION | No | — | — | — |
| 8 — Implementar el agente único de comparación | PENDIENTE_AUTORIZACION | No | — | — | — |
| 9 — Preparar consolidación y protocolo comparativo | PENDIENTE_AUTORIZACION | No | — | — | Decisión: comparación externa experimental o bibliográfica |
| 10 — Entregar el kit del piloto, sin ejecutarlo | PENDIENTE_AUTORIZACION | No | — | — | — |

## 3. Runtime y dependencias declaradas

Obtenidas **leyendo archivos del repositorio**, no ejecutando intérpretes.

| Componente | Versión declarada | Fuente del dato |
|---|---|---|
| Python | 3.13 | `.github/workflows/ci.yml` |
| Node.js | 22 | `.github/workflows/ci.yml` |
| pnpm | 10.33.0 | `frontend/package.json` (`packageManager`) |
| Dependencias backend directas | 16 pines exactos (`==`) | `requirements.txt` |
| Cierre transitivo backend | 141 paquetes | `constraints.txt` |
| Next.js / React / TypeScript | 16.3.3 / ^19 / 5.7.3 | `frontend/package.json` |

No existen `.python-version`, `pyproject.toml`, `runtime.txt`, `.nvmrc` ni
`.tool-versions`: la única declaración de versiones de runtime vive en el
workflow de CI.

## 4. Instrucciones de instalación preparadas — **NO EJECUTADAS**

Backend, dentro del worktree de preparación y con un entorno virtual
**propio** (no reutilizar el `.venv` del checkout original):

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Unix: source .venv/bin/activate
pip install -r requirements.txt -c constraints.txt
```

Frontend:

```bash
cd frontend
pnpm install --frozen-lockfile
```

Configuración: copiar `.env.example` a `.env`. Las credenciales reales solo
hacen falta para una futura ejecución autorizada; **la preparación no las
necesita** y no deben quedar en este worktree hasta entonces.

Ninguno de estos comandos se ejecutó en la Fase 0. Cualquier instalación o
descarga debe presentarse en la solicitud de permiso de la fase que la
necesite.

## 5. Aislamiento verificado por inspección

| Comprobación | Resultado |
|---|---|
| `.venv` heredado | No existe en el worktree |
| `.env` / credenciales heredadas | No existen en el worktree |
| `frontend/node_modules` | No existe en el worktree |
| `data/chroma/`, `data/historial.db`, `data/ip_reputation_cache.json` | No viajan al worktree (ignorados por git) |
| Checkout original | Sigue en `main` @ `6adc343`, árbol limpio |

Datos versionados **sí** disponibles en el worktree:

- `data/logs/BGL_2k.log`
- `data/logs/HDFS_2k.log`
- `data/labels/hdfs_anomaly_label_2k.csv`
- `data/mitre_attack/provenance.json` — solo la procedencia (ATT&CK v19.2,
  697 técnicas, 475 subtécnicas, corrida 2026-09-11). **El catálogo STIX en
  sí no está versionado en el repositorio.**

## 6. Información del entorno **no comprobada mediante ejecución**

Requerido por la acción 6 de la Fase 0. Nada de lo siguiente fue verificado
y no debe presentarse como verificado:

1. Versiones de Python, Node y pnpm realmente instaladas en la máquina
   (solo se leyeron las declaradas en archivos).
2. Que `pip install -r requirements.txt -c constraints.txt` resuelva dentro
   de este worktree.
3. Que la suite del backend pase en este worktree. (En el checkout original
   el último conteo conocido es 544 aprobadas, pero no se reverificó acá y
   no corresponde a esta rama.)
4. Que el frontend instale, compile o pase lint / typecheck / test en este
   worktree.
5. Disponibilidad, cuota o credenciales válidas de Gemini, AbuseIPDB y NVD.
6. Estado real de ChromaDB. El diagnóstico del plan indica cuatro
   colecciones con cero documentos; en esta fase no se abrió ninguna base.
7. Que el catálogo MITRE ATT&CK sea obtenible: exigiría una descarga, que
   requiere autorización en la fase correspondiente.
8. Ejecución remota del workflow de CI sobre esta rama.

Agregado al cerrar la Fase 2:

9. Que los 232 casos generados pasen por el preprocesamiento de NODEX.
   Llamar a `preprocesar()` sobre un caso es ejecutar NODEX sobre un caso de
   prueba, que el protocolo prohíbe sin autorización. La segmentación se
   validó contra el archivo original, no contra el pipeline.
10. Que las pruebas de `tests/experimentation/` pasen. Son 4 + 2 archivos
    escritos y revisados estáticamente, nunca ejecutados.
11. Nada de los **datos** de UWF: solo se leyeron los metadatos del footer
    Parquet. No se leyó una sola fila.
12. Que las etiquetas de HDFS, BGL y UWF sean correctas. Se toman tal como
    vienen; auditar la curaduría de los datasets está fuera de alcance.

## 7. Pendientes y riesgos registrados al cierre de la Fase 0

- **UWF-ZeekDataFall22 no está incorporado localmente.** *Resuelto el
  3-oct-2026:* llegó en `b0fe5de`. Lo que queda es poder leerlo (viene en
  Parquet y falta un motor).
- **Catálogo MITRE no versionado y ChromaDB sin documentos.** *Resuelto el
  4-oct-2026, y el diagnóstico del plan era incorrecto.* Medido leyendo
  `data/chroma/chroma.sqlite3` en solo lectura: la base de producción tiene
  **4 colecciones y 697 documentos MITRE** cargados en `attack_techniques`
  (222 técnicas padre y 475 subtécnicas, ATT&CK v19.2), y el modelo
  `all-MiniLM-L6-v2` está en la caché local de HuggingFace (91,6 MB, 11
  archivos hasheados). **No hace falta descargar nada.** El JSON STIX sigue
  sin versionar, pero solo se necesitaría para reconstruir la base desde
  cero: la base experimental se puebla copiando los vectores ya calculados.
  Lo único pendiente es la autorización para ese poblado.
- **Rendimiento HDFS del detector.** *Reinterpretado el 3-oct-2026, con
  medición:* no es un problema de rendimiento. `HDFS_2k.log` tiene 1,00
  líneas por bloque, así que la secuencia de eventos que define la etiqueta
  de anomalía no está en el archivo y la tarea no es resoluble por ningún
  sistema. Es una amenaza a la **validez** de esa medición, no una
  limitación del detector. Detalle y las tres salidas posibles en
  `hallazgos_datasets.md` §1 (decisión D-7). Sigue sin ser bloqueante de la
  preparación, por indicación de la usuaria.
- **Referencias humanas pendientes.** Las anotaciones semánticas que el
  dataset no provee requieren revisión humana. El plan considera el ERR de
  UWF ya revisado; el resto queda como `referencia_pendiente` hasta su
  aprobación.

## 8. Decisiones académicas

El protocolo trata las pendientes como `DECISION_PENDIENTE`: **ningún
umbral está fijado** y el código no debe suplirlas con un valor por
defecto. Detalle en `protocolo.md` §10 y en `hallazgos_datasets.md` §6.

### Resueltas (3-oct-2026)

| # | Decisión | Dónde quedó implementada |
|---|---|---|
| D-1 | Partición **30% desarrollo / 70% evaluación**, por grupo y estratificada | `datasets/particion.py`; manifiestos |
| D-4 | Rúbrica **0–3 por criterio**, **2 evaluadores**, concordancia reportada | pendiente de implementar en la Fase 3 |
| D-6 | **12 casos por dataset principal** con rúbrica humana (12 BGL + 12 UWF = 24 reportes) | pendiente de implementar en la Fase 3 |
| D-7 | HDFS es **auxiliar / de validación técnica**, no métrica principal. BGL y UWF son los datasets principales | `hallazgos_datasets.md` §1 y §6 |
| D-8 | Casos de UWF **compuestos**, declarados sintéticos, con timestamps **rebasados** y offset registrado | `datasets/uwf_casos.py` |
| D-9 | `label_binary == "Duplicate"` **excluido**, con la cantidad en el manifiesto | `datasets/uwf.py`; `uwf_conversion.json` |
| D-10 | El techo de 2 000 líneas **se mantiene en el piloto** y se reevalúa después | — |

### Pendientes

| # | Decisión | Fase que la necesita |
|---|---|---|
| D-2 | Número de repeticiones `N` por caso | 7 |
| D-3 | Umbrales de aceptación por dimensión | 5 (y la interpretación final) |
| D-5 | Comparación externa: experimental o bibliográfica | 9 |

Ninguna de las tres bloquea la Fase 3. D-2 y D-3 se necesitan antes de
ejecutar; D-5 recién en la Fase 9.

## 9. Inventario de casos preparados

336 casos, con su referencia en un árbol separado. Ninguno fue ejecutado.

| Dataset | Rol | Partición | Condición | Casos | Prevalencia efectiva |
|---|---|---|---|---|---|
| HDFS | auxiliar (D-7) | desarrollo | natural | 30 | 0,0333 |
| HDFS | auxiliar | desarrollo | balanceado | 16 | 0,5000 |
| HDFS | auxiliar | evaluación | natural | 60 | 0,0333 |
| HDFS | auxiliar | evaluación | balanceado | 40 | 0,5000 |
| BGL | principal | desarrollo | natural | 20 | 0,3000 |
| BGL | principal | desarrollo | balanceado | 4 | 0,5000 |
| BGL | principal | evaluación | natural | 50 | 0,2800 |
| BGL | principal | evaluación | balanceado | 12 | 0,5000 |
| UWF | principal | desarrollo | visible | 12 | 0,5000 |
| UWF | principal | desarrollo | sigiloso | 12 | 0,5000 |
| UWF | principal | evaluación | visible | 40 | 0,5000 |
| UWF | principal | evaluación | sigiloso | 40 | 0,5000 |

En UWF las dos condiciones tienen prevalencia 0,5: lo que varía es el
tamaño del incidente dentro del caso (8–20% en `visible`, 1,0–1,67% en
`sigiloso`).

**Advertencia de costo.** 336 casos × 2 arquitecturas LLM × `N`
repeticiones es mucho más de lo que conviene correr de entrada. El pool
grande existe para que la campaña final tenga de dónde sacar.

## 10. Subconjuntos preseleccionados (Fase 3)

Fijados **antes** de que exista cualquier resultado, con semilla registrada
(`20261004`). Elegir después qué casos se miran, viendo ya cómo le fue al
sistema, sería cherry-picking.

| Subconjunto | Partición | Casos | Para qué |
|---|---|---|---|
| `experiments/subconjuntos/piloto.json` | desarrollo | 24 (4 por dataset × condición) | Verificar el pipeline de punta a punta. **No produce métricas reportables.** 48 corridas con 2 arquitecturas LLM |
| `experiments/subconjuntos/rubrica.json` | evaluación | 24 (12 BGL + 12 UWF) | Rúbrica humana de D4. **48 reportes a puntuar**, porque cada caso se evalúa en las dos arquitecturas |

El piloto sale solo de `desarrollo`: depurar contra los casos de evaluación
los deja de ser datos reservados. La rúbrica excluye HDFS por la decisión
D-7 (es auxiliar, no principal).

Una advertencia sobre el costo de D-6: son **48 reportes**, no 24. La
rúbrica se aplica por (caso, arquitectura), porque comparar arquitecturas es
el objetivo de esa dimensión. Con 2 evaluadores a ~10 min por reporte son
~16 horas-persona, el doble de lo estimado al decidir D-6. Si eso no es
viable, la salida es bajar a 6 casos por dataset (24 reportes), no reducir
los evaluadores a uno: sin el segundo no hay concordancia que informar.

## 11. Dos dimensiones que el sistema no produce (Fase 4)

Hallazgo de la Fase 4, y es el más importante hasta ahora para decidir qué
puede afirmar la tesis.

De las cinco dimensiones del protocolo, **dos no se pueden medir** porque
NODEX no genera la salida correspondiente. No es un problema de desempeño:
no hay nada que puntuar.

| Dimensión | Qué produce NODEX hoy | Medible |
|---|---|---|
| D1 detección | `hay_anomalia` / `hay_incidente`, booleanos del auditor final | **Sí** |
| D2 reconstrucción | Nada | **No** |
| D3 MITRE | Solo candidatas del RAG (`tecnicas_mitre`); el agente de triage cita IDs dentro del texto libre de `diagnostico`, sin evidencia | **No** |
| D4 reporte | `diagnostico` + `evaluacion_auditor` + comandos de mitigación | **Sí** |
| D5 consumo | Telemetría (Fase 6) | **Sí** |

Dos aclaraciones sobre por qué no se puede rellenar el hueco:

- **La cronología del preprocesamiento no es la reconstrucción.**
  `resumen_logs["cronologia"]` la arma `src/preprocessing/aggregation.py` de
  forma determinística, sin LLM. Entregarla como `reconstructed_events`
  haría que D2 midiera al preprocesador mientras el informe dice que mide
  al sistema multiagente. El adaptador la pasa en `_meta`, etiquetada.
- **Un ID citado en prosa no es una atribución puntuable.** El agente de
  triage recibe la instrucción de citar IDs en el texto
  (`agente_analista_triage.py:71`), pero sin `evidence_uids`. El protocolo
  no puntúa una atribución sin evidencia: una técnica adivinada y una
  fundamentada no son el mismo resultado. Los IDs en prosa se registran en
  `_meta` como señal de que la capacidad existe en alguna forma.

### La decisión que falta

Hay dos caminos y los dos son defendibles; lo que no se puede es dejarlo
sin declarar.

**(A) Extender el contrato de salida de los agentes.** Está escrito y sin
conectar en `src/experimentation/adapters/contrato_agentes.py`: tres campos
nuevos (`eventos_reconstruidos`, `secuencia_temporal`,
`tecnicas_atribuidas`) y el añadido de prompt que los pide. El adaptador ya
sabe leerlos. Habilita D2 y D3.

Lo que cuesta: **cambia el sistema evaluado**. Pedirle al agente que
enumere eventos y atribuya técnicas con evidencia modifica su tarea y puede
mejorar o empeorar el diagnóstico. La campaña mediría esa versión y la
tesis tiene que describirla. Además el agente único debe recibir el mismo
contrato de salida, o la comparación entre arquitecturas mediría el
contrato y no la arquitectura.

**(B) No extenderlo.** La campaña mide detección, calidad de reporte y
consumo. Reconstrucción y atribución MITRE quedan declaradas como
**capacidades no medidas**, con la razón, en los 336 casos.

Es la decisión **D-11** y bloquea el cierre completo de la Fase 4.

## 12. Evaluadores (Fase 5)

Ocho módulos en `src/experimentation/evaluators/`, **ninguno ejecutado**: la
acción 7 de la Fase 5 lo prohíbe expresamente. Por eso los valores esperados
viven en `tests/experimentation/fixtures/metricas_esperadas.md`, con la
aritmética escrita paso a paso, y en el `.json` que leen las pruebas.

Verifiqué esa aritmética recalculándola de forma independiente, con fórmulas
en línea y **sin importar los evaluadores**: 0 discrepancias sobre los 5
grupos de fixtures.

### El defecto de F1 que se corrige

Fórmula nueva: `F1 = 2·TP / (2·TP + FP + FN)`.

El evaluador anterior usaba `2·P·R/(P+R)` con la guarda
`if precision and recall`. Como `0.0` es falso en Python, un conjunto con
**TP=0, FP=6, FN=1** devolvía F1 indefinido cuando el valor correcto es
**0,0**. Con la forma directa el único indefinido real es `2TP+FP+FN == 0`.

Esto importa para leer la evidencia anterior: el informe de la fase 6 mostró
como "no definido" algunos valores que eran ceros reales.

### Separaciones que los evaluadores respetan

| Separación | Por qué |
|---|---|
| Ningún evaluador importa `src.pipeline`, `src.agents` ni `src.graph` (verificado por AST) | Un evaluador que pudiera invocar al sistema podría evaluar una corrida nueva en vez de la guardada |
| Micro y macro se informan los dos | Eligen distinto: si micro ≫ macro, el sistema acierta en los casos grandes y falla en los chicos |
| Las corridas fallidas no entran en los promedios de consumo | Una corrida cortada consumió menos; incluirla haría parecer más eficiente a la arquitectura que falló más (en la fixture, 1 050 en vez de 1 500 tokens) |
| Un `uid` inventado se cuenta aparte del falso positivo | Proponer un evento que no existe no es lo mismo que elegir mal un evento real |
| Una subtécnica no se convierte en su técnica padre para acertar | Sería inferir la referencia, que el plan prohíbe |
| Los resultados no se sobrescriben | Un informe que cita un resultado tiene que poder seguir citándolo |

### Decisión nueva: D-12

La concordancia entre evaluadores se informa con tres medidas simples y
verificables a mano: acuerdo exacto, acuerdo hasta un nivel y diferencia
absoluta media. **No se calcula ningún kappa.** Elegir el coeficiente
(Cohen simple, ponderado lineal, ponderado cuadrático) es una decisión
metodológica, y publicar uno calculado con una fórmula que nunca se ejecutó
sería peor que no publicarlo.

| # | Decisión | Fase que la necesita |
|---|---|---|
| D-11 | Si se extiende el contrato de salida de los agentes para habilitar D2 y D3 | 4 (bloquea su cierre completo) |
| D-12 | Qué coeficiente de concordancia informar en D4, si alguno | 5 (interpretación final) |

## 13. Plan de continuación (7-oct-2026)

Llegó `PROMPT_CLAUDE_CONTINUACION_PLAN_PRUEBAS_NODEX.md`, que cierra todas
las decisiones que estaban abiertas. Resoluciones y su efecto acá:

| Decisión | Resolución | Efecto en el código |
|---|---|---|
| D-11 | **Resuelta externamente. No implementar.** | `adapters/contrato_agentes.py` queda marcado SUPERADO; `runtime/configuracion.py::detectar_d11()` solo comprueba si llegó |
| D-2 | N=1 piloto, N=3 campaña final | A cablear en el orquestador |
| D-6 | **6 BGL + 6 UWF = 12 casos**, 24 reportes, 48 evaluaciones | `subconjuntos.py` corregido: antes eran 12 por dataset (48 reportes) |
| D-3 | Sin umbrales absolutos; comparación interna pareada + descriptivas | Ya cumplido: ningún evaluador tiene umbrales |
| D-12 | Sin kappa | Ya cumplido |
| D-5 | Comparación externa bibliográfica | Ya cumplido: nada instala sistemas externos |

### Estado de D-11: NO integrado

Verificado el 7-oct-2026 sobre `src/state.py` y `src/agents/`: **cero
ocurrencias** de `eventos_reconstruidos`, `secuencia_temporal`,
`tecnicas_atribuidas`, `evidence_uids` e `invalid_evidence_uid_count`.

Consecuencias mientras no esté:

- **D2 y D3 no son medibles.** D1, D4 y D5 sí.
- La telemetría del piloto **no es la definitiva**: §11 prohíbe mezclar
  mediciones previas a D-11 con posteriores. `Telemetria.previa_a_d11`
  arranca en `True` y la exportación lo propaga.
- La Fase D (validación de integración) no puede empezar.

Nada más depende de D-11: runners, persistencia, identidad y baseline se
pueden construir ahora.

### Hallazgo nuevo: el fallback de modelo rompe la comparabilidad

`src/config.py` define `LLM_MODEL_PRIMARY = gemini-3.1-pro-preview` y
`LLM_MODEL_FALLBACK = gemini-3.6-flash`: si el primario agota reintentos, el
sistema reintenta con el otro. Una corrida que cayó al fallback **usó otro
modelo** y no es comparable con el resto de la campaña.

No es hipotético: es el comportamiento por omisión. Por eso la telemetría
registra el **modelo efectivo por llamada**, `Telemetria.uso_fallback` lo
expone, y `exportacion.resumen_de_integridad()` cuenta esas corridas y
emite la advertencia junto a la tabla, no en un log aparte.

### Capa de ejecución preparada (Fase C, parcial)

`src/experimentation/runtime/`, 6 módulos, **ninguno ejecuta NODEX ni llama
a un modelo**:

| Módulo | Qué garantiza |
|---|---|
| `identidad.py` | `run_id` determinístico con las cinco coordenadas del §15. Cambiar la configuración cambia el id, así que no se pisan corridas de campañas distintas |
| `configuracion.py` | Congelado del §12, con hash de los 5 prompts, de la capa experimental y de los manifiestos. Los parámetros ausentes se listan aparte para que un nombre mal escrito no quede como un `None` invisible. Las credenciales solo como booleano: verificado que la clave no aparece en el artefacto |
| `persistencia.py` | Estructura del §15 y escritura única. Comprueba las tres piezas **antes** de escribir cualquiera, para no dejar una corrida a medio guardar |
| `telemetria.py` | Campos del §11. `total_tokens` es `None` y no 0 cuando el proveedor no informó nada; si solo algunas llamadas informaron, lo declara en `campos_parciales` |
| `exportacion.py` | Tabla del §14. `D1_precision/recall/f1` van `null` por fila, porque son métricas de conjunto y por caso darían el acierto disfrazado de métrica; el acierto va en `D1_outcome` |
| `__init__.py` | — |

### Lo que falta para el piloto

| Brecha | Bloqueante |
|---|---|
| **El agente único no existe en el repositorio** | Sí |
| Runners de NODEX, agente único y baseline | Sí |
| Orquestador que recorra el subconjunto piloto con N=1 | Sí |
| Integración externa de D-11 → Fase D | Sí, para D2 y D3 |

## 14. Runners de las tres arquitecturas (Fase C)

`src/experimentation/runners/`, 4 módulos. **Ninguno se ejecutó**: correr un
runner es ejecutar NODEX, el agente único o el preprocesamiento sobre un
caso, lo que requiere autorización.

| Runner | LLM | Repeticiones | D2/D3 |
|---|---|---|---|
| `nodex` | 5 nodos + bucles | N=3 en campaña | pendientes de D-11 |
| `agente_unico` | 1 llamada | N=3 en campaña | pendientes de D-11 |
| `baseline` | no usa | N=1: determinístico | no aplica nunca |

### El agente único existía solo como decisión; ahora existe como código

Lo que se mantiene **idéntico** a NODEX, para que la variable medida sea la
arquitectura y no la entrada:

| Elemento | Cómo |
|---|---|
| El caso | El mismo archivo, la misma función de lectura |
| Preprocesamiento | La misma `preprocesar_lote()` |
| Resumen que ve el modelo | El mismo `acotar_resumen_para_prompt()` |
| Contexto de interpretación | `contexto_preprocesamiento(metadatos, advertencias, muestras, incluir_muestras=True)` — el mismo camino que `_metadatos_desde_v2()` |
| Conocimiento externo | El mismo `tool_consultar_rag()`, con la `firma` calculada igual |
| Modelo y temperatura | El mismo `llm_json()` |
| Claves de salida | Las seis que produce el estado de NODEX, así el **mismo** adaptador sirve para las dos |

Que el adaptador sea el mismo no es comodidad: dos adaptadores podrían
diferir en cómo interpretan un veredicto ausente, y esa diferencia se
confundiría con una diferencia entre arquitecturas.

El contrato de salida de D-11 queda como `MARCADOR_CONTRATO_D11` **sin
rellenar**. El texto lo define la implementación externa; escribirlo acá
sería duplicarla. `contrato_d11_pendiente()` lo detecta y lo reporta en cada
corrida.

### El baseline responde otra pregunta que UWF, y hay que declararlo

Las reglas del baseline son operativas: severidad declarada, proporción de
eventos fallidos y concentración de intentos fallidos por IP. Eso responde
*"¿el sistema se comporta de forma anómala?"*.

UWF pregunta *"¿hay actividad maliciosa?"*. Un escaneo de puertos exitoso no
produce severidades graves ni conexiones fallidas, así que el baseline puede
no detectarlo **por diseño de sus reglas**, no por debilidad.

No se arregla inventándole una noción de malicia. Cada salida lleva
`pregunta_respondida` y, en casos de seguridad,
`desalineacion_de_pregunta = True`. Para **BGL** la comparación con el
baseline es pareada y válida; para **UWF** es contextual y el informe tiene
que decirlo.

### Tres errores propios encontrados en esta fase

Los dos primeros solo habrían fallado **en plena campaña**:

1. `CONTRATO_VERSION` se importaba de `contracts.salida`, donde no existe
   (vive en `contracts/__init__.py`).
2. `firma_lote` se importaba de `tools.resumen_prompt` en vez de
   `tools.aggregation`. El RAG exige `state["firma"]` y lanza `KeyError` si
   falta.
3. `construir_entrada()` del agente único usaba el valor equivocado de
   `preprocesar_lote()` —que devuelve `(resultado, v2, resumen_v1)`— y
   omitía las muestras crudas y `incluir_muestras=True`. El agente único
   habría visto **menos contexto que NODEX**, sesgando la comparación a
   favor del multiagente. Es el sesgo que el §10 prohíbe expresamente.

A raíz de los dos primeros quedó un control nuevo en
`tests/experimentation/test_runners.py`: verifica por AST que **cada**
`from src.X import Y` de la capa experimental apunte a un nombre que existe.
Corrido a mano: **170 imports verificados, 0 fallos**. También detecté y
corregí un falso positivo del propio control (no manejaba asignaciones en
tupla como `VALOR_BENIGNO, VALOR_MALICIOSO = "False", "True"`).

### Lo que falta para el piloto

| Brecha | Bloqueante |
|---|---|
| Orquestador que recorra el subconjunto piloto con N=1, persista y exporte | Sí |
| Integración externa de D-11 → Fase D | Solo para D2 y D3 |

## 15. Orquestador y plan en seco (Fase C, cerrada)

`src/experimentation/orquestador.py`. Es la última pieza antes del piloto.

### La ejecución viene deshabilitada

`ejecutar_campana()` **no corre nada** salvo que se le pase
`ejecucion_habilitada=True` de forma explícita. Con el valor por omisión
hace un **plan en seco**: enumera qué corridas haría, cuántas llamadas
implican y qué ya está hecho, sin tocar el modelo ni el preprocesamiento.

### Plan en seco del piloto (medido el 7-oct-2026)

| Arquitectura | Corridas | Llamadas LLM (piso) |
|---|---|---|
| `nodex_multiagente` | 24 | 144 |
| `agente_unico` | 24 | 24 |
| `baseline_reglas` | 24 | 0 |
| **Total** | **72** | **168** |

24 casos (8 por dataset), N=1, los tres datasets. El baseline corre una sola
vez por ser determinístico.

### Plan en seco de la campaña final (N=3, datasets principales)

| Dataset | Casos | Corridas | Llamadas (piso) |
|---|---|---|---|
| BGL | 62 | 434 | 1 302 |
| UWF | 80 | 560 | 1 680 |
| **Total** | **142** | **994** | **2 982** |

HDFS auxiliar, aparte del agregado principal: 100 casos, 2 100 llamadas más
si se corriera con N=3.

«Piso» es literal: NODEX tiene 6 puntos de llamada y sube con los bucles de
replanificación y de corrección de comandos, que no se pueden acotar sin
medir. No es una estimación de consumo.

### Las dos mitades no se tocan

    ejecutar_campana()   -> corre arquitecturas. NO abre ground_truth/.
    evaluar_campana()    -> lee las salidas guardadas + ground_truth/.

Verificado por AST: **una sola** función del módulo construye una ruta a
`ground_truth` (`_cargar_referencia`), y **una sola** la llama
(`evaluar_campana`). Mientras una corrida está en curso, la referencia no
está cargada en ninguna variable del proceso.

`evaluar_campana()` tampoco importa los runners: si una corrida no está
guardada se cuenta como **ausente**, no se ejecuta. Así la evaluación no
depende de cuándo se la invoque.

Para cada dimensión combina **dos** estados y se queda con el más
restrictivo: el de la salida (¿el sistema produjo algo que puntuar?) y el de
la referencia (¿hay una referencia aprobada?).

### Reanudación

El `run_id` es determinístico, así que una campaña interrumpida se reanuda
sola: las corridas guardadas se detectan por la existencia del archivo y se
omiten. Y como la `config_version` entra en el hash del `run_id`, una
campaña nueva no pisa los artefactos de la anterior — verificado.

### Dos defectos propios corregidos

1. Quedó una expresión sin sentido de una edición anterior
   (`crudo=preservar_estado_crudo.__name__ and crudo`). Funcionaba por
   accidente, porque el nombre de la función es una cadena verdadera.
2. La exportación buscaba el `dataset` y la `repeticion` recorriendo el plan
   por `run_id`: O(n²) y se rompe si el plan cambia entre la corrida y la
   exportación. Ahora la identidad viaja con el resultado.

Y un falso positivo de mi propio control: la auditoría de acceso al ground
truth buscaba la subcadena `ground_truth` y marcaba tres funciones, porque
sus docstrings la mencionan para declarar que **no** la abren. Corregido a
buscar la constante exacta de ruta.

### Estado: listo para el piloto, salvo D-11

Lo que falta ya no es código de la capa experimental:

| Pendiente | Quién |
|---|---|
| Integración externa de D-11 → Fase D | Proceso externo |
| Autorización para ejecutar el piloto (168 llamadas) | Decisión de la autora |
| Instrumentación de tokens y modelo efectivo (Fase 6) | Pendiente; hoy la telemetría no inventa tokens, los deja en `None` |

## 16. Telemetría del cliente LLM (Fase 6)

> **OBSOLETA desde la Fase D (7-oct-2026).** El módulo que describe esta
> sección (`src/telemetria_llm.py`) se retiró en favor de `src/telemetry.py` de
> D-11, y `src/llm.py` quedó igual al de `origin/main`. Se conserva solo como
> registro de las decisiones de diseño. Ver la sección 17 y la 18.

Instrumentación de `src/llm.py`, **sin cambiar ninguna decisión de NODEX**.
El diff contra producción son tres bloques y ningún valor de retorno ni
camino de excepción se modifica.

### Por qué `llm_json()` basta como único punto

Los cinco nodos LLM y el segundo punto de llamada del triage pasan todos por
`llm_json()`. Los bucles de replanificación y de corrección de comandos no
agregan puntos nuevos: vuelven a invocar a los mismos agentes, que vuelven a
llamar a `llm_json()`. Un solo embudo cubre todo.

### Dos contadores, porque una invocación puede ser varias llamadas

Una invocación de `llm_json()` puede producir varias llamadas HTTP:

1. el bucle de `retries` por JSON inválido vuelve a pedir;
2. `_generate_con_backoff` reintenta ante 503 y 429-por-minuto;
3. `_generate_con_fallback` repite la secuencia completa con el modelo de
   respaldo.

| Contador | Qué cuenta |
|---|---|
| `llm_call_count` | invocaciones de `llm_json()`, o sea **pasos de agente** |
| `api_call_count` | llamadas reales a `generate_content`, reintentos incluidos |
| `reintentos_api` | la diferencia |

**Los tokens se suman sobre las llamadas físicas**, porque un reintento
también consume. Si solo se registrara la respuesta final, el consumo
quedaría subestimado justo en las corridas problemáticas, que son las que
más interesa medir.

### Qué se registra

Por llamada: agente, invocación lógica a la que pertenece, reintento de
JSON, modelo solicitado, **modelo efectivo**, tokens de entrada, salida,
razonamiento y total, latencia y error.

Por corrida: los dos contadores, los tokens sumados, `uso_fallback`, los
modelos efectivos vistos, la latencia total de API, los errores, el consumo
agrupado por agente, y —agregados por el orquestador desde el estado del
grafo, no por el grabador— **`replan_count` e `intentos_correccion`**.

### `None` nunca es cero

Un contador que el proveedor no informa queda `None`. No se estima.

El `print` que ya tenía `llm_json` usa
`getattr(um, "thoughts_token_count", 0)`: está bien para un mensaje en
pantalla, pero no para una métrica, porque un 0 se promedia y baja el
consumo medio. El grabador lee el mismo atributo conservando el `None`.

`origen_total_tokens` declara de dónde salió el total: `proveedor`,
`suma_de_partes` o `no_informado`. La suma de partes puede no incluir tokens
que el proveedor contabilice aparte, así que la distinción importa.

### Atribución al agente sin tocar los agentes

Se deduce recorriendo la pila hasta el primer marco de `src/agents/`, con
`sys._getframe` y no `inspect.stack()` (que lee el código fuente de cada
marco). Se eligió así para **no editar los cinco agentes**: pasarles un
parámetro nuevo obligaría a tocar archivos que la implementación externa de
D-11 también está modificando.

### Verificación con cliente simulado

Se ejercitó con `generate_content` reemplazado por un objeto falso, **sin
credenciales y sin red**. Ocho escenarios: caso normal, reintento por JSON
inválido, razonamiento ausente, respuesta sin `usage_metadata`, 503
transitorio, fallback de modelo, grabador inactivo y agrupación por agente.
Siete pasaron tal cual. El octavo destapó un defecto de producción.

### Defecto de producción encontrado: la salida redirigida aborta la corrida

**No lo causa la instrumentación.** `src/llm.py:248` imprime el aviso del
fallback con `⚠️`, y **56 líneas de `src/`** tienen caracteres que cp1252 no
puede codificar (`→`, `⚠️`, `✓`). En Windows, cuando la salida se **redirige**
a un archivo, `sys.stdout.encoding` es cp1252 — medido, no supuesto.

Consecuencia: una corrida con la salida redirigida muere con
`UnicodeEncodeError` al imprimir, no por un problema del modelo. Y el camino
que crashea es justo el del fallback, que es el que más interesa observar.
Para una campaña de 2 982 llamadas, que se va a registrar en un archivo, es
un riesgo vivo.

Se mitiga **en la capa experimental y no en NODEX**:
`orquestador.asegurar_salida_utf8()` reconfigura stdout y stderr a UTF-8 con
`errors="replace"` antes de la primera corrida. Verificado: cp1252 → utf-8 y
el aviso imprime sin crashear. Reconfigurar el proceso que orquesta no
cambia ninguna lógica del sistema evaluado.

Queda como defecto abierto de producción, para arreglar aparte si se quiere
que la salida redirigida funcione fuera del experimento.

### Dos falsos positivos más de mi propio control de imports

El control que verifica que cada `from src.X import Y` apunte a un nombre
existente dio tres falsos positivos nuevos:
`runtime.exportacion`, `runtime.persistencia` y `evaluators.deteccion`. Son
**submódulos**, y `from paquete import submodulo` es válido aunque el
`__init__.py` no los reexporte. Confirmado importándolos. El control ahora
acepta ese caso: **194 imports verificados, 0 fallos**.

Es el tercer falso positivo del mismo control (antes: asignaciones en tupla
y búsqueda por subcadena). Vale anotarlo: un control estático que avisa de
más se deja de leer, y entonces no sirve.

### Lo que falta para el piloto

| Pendiente | Quién |
|---|---|
| Integración externa de D-11 → Fase D | Proceso externo |
| Ejecutar el piloto N=1 (168 llamadas), **después** de la Fase D | Decisión de la autora |
| HDFS con N=3 | Se decide después del piloto principal |

## 17. Fase D: integración de D-11 (7-oct-2026)

D-11 llegó en `9cac64f` (Felipe Bravo Romo), contrato `d11-v1`. Se integró a
esta rama resolviendo el conflicto **a favor del núcleo**, y la capa
experimental se adaptó a él.

### El bloqueante que se encontró y se resolvió

`CRONOLOGIA_MAX_EVENTOS` valía **40**: la evidencia citable eran los primeros
40 registros del lote. Medido sobre los 104 casos de UWF, que tienen 300
registros con el incidente insertado en el 70% central:

| | Antes (40) | Ahora (300) |
|---|---|---|
| Casos positivos con **algún** evento del incidente en la ventana | **0 de 52** | **52 de 52** |
| Posición del primer evento del incidente | mín. 49, mediana 139 | — |

Con 40, D2 y D3 eran **estructuralmente imposibles** en UWF y D1 quedaba
degradado: el agente solo veía tráfico benigno. El resultado se habría leído
como que NODEX no detecta nada, cuando la restricción era de posición.

Decisión del 7-oct-2026: subir a 300 y **no** tocar los casos. Prioriza
mantener la dificultad original del escenario, a costa de ~18 000 tokens de
entrada más por llamada en un caso de UWF (estimado por conteo de
caracteres, no medido).

### Qué se adaptó, y un error que habría pasado desapercibido

**El matching de D2 va por `evidence_uids`, no por `event_id`.** Es la
diferencia que decide si D2 mide algo:

- `evidence_uids` se valida contra el catálogo de evidencia, indexado por el
  `uid` real del registro —el de Zeek en UWF—. Los inventados se descartan y
  se cuentan en `invalid_evidence_uid_count`.
- `event_id` es la etiqueta que el sistema le pone al evento, y
  `normalizar_d11` la reemplaza por una sintética (`event_001`) si falta **o
  si colisiona con un uid**.

Mi versión inicial leía `event_id`. No habría fallado con error: habría
comparado etiquetas contra uids y dado recall 0 en todos los casos. Lo
detectó la lectura de `normalizar_d11`, no una prueba.

**Nombres del contrato**: `technique_id` / `technique_name`, no `id`.
Leer `id` habría dado una lista vacía en silencio.

**D3 solo a nivel técnica.** `TecnicaAtribuida` no lleva nivel, y la decisión
fija el scoring en `label_technique` y los identificadores `Txxxx` /
`Txxxx.xxx`. `label_tactic` queda como información complementaria del
dataset y no entra. El contrato D-11 **no** se extiende para tácticas.

### Pseudo-ablación: Gemini externo, no el agente único integrado

La comparación del proyecto es una pseudo-ablación **declarada**:

    NODEX completo                 VERSUS   Gemini directo
      + arquitectura                          + un único prompt
      + RAG                                   + sin arquitectura
      + herramientas                          + sin herramientas
      + coordinación                          + sin estado LangGraph

La pregunta es *"¿qué diferencia hay entre usar NODEX como sistema completo y
usar el modelo directamente?"*, **no** *"¿qué aporta la división en agentes
manteniendo todo lo demás constante?"*.

Consecuencia: se retiró `runners/agente_unico.py`, que replicaba el contexto
de NODEX y le daba el mismo RAG — eso contradecía el diseño. En su lugar,
`runners/gemini_externo.py`: cliente propio (no `src/llm.py`, que arrastra
instrumentación, fallback y reintentos), log **crudo** del caso, un solo
prompt, sin RAG ni herramientas, mismo modelo y temperatura. Si un caso
excede el tope de caracteres **falla** en vez de recortarse: recortar en
silencio haría que Gemini viera menos caso que NODEX.

`src/single_agent.py` sigue en el sistema y no se toca; la campaña
simplemente no lo usa como implementación experimental principal.

### Telemetría: se retiró la mía en favor de la de D-11

`src/telemetria_llm.py` se eliminó y `src/llm.py` quedó **byte a byte igual**
al de `origin/main`. La telemetría la produce ahora el propio sistema:
`analizar_lote()` envuelve el grafo en `medir_ejecucion()` y deja el resumen
en `estado["telemetry"]`.

Su versión tiene algo que la mía no tenía, y era un error mío:
`resumen_telemetria` **acumula `intentos_correccion` a través de
`historial_planes`**, no solo el del estado final. Tras un replan, mi versión
habría subcontado. Verificado: con 1 en el estado y 3 en el historial,
devuelve 4.

Dos huecos de su versión quedan **reportados y no parcheados**, porque
`src/telemetry.py` es del núcleo:

1. ~~No registra las llamadas fallidas ni el error.~~ **Corregido el
   15-oct-2026 (ver §20.3): era falso con el código actual.**
   `iniciar_llamada` agrega la llamada antes de intentarla; una fallida queda
   con tokens `None`. Lo que sí falta es el texto del error.
2. ~~No guarda el modelo solicitado.~~ **Corregido el 15-oct-2026 (ver
   §20.3): era falso.** Cada intento, del principal y del respaldo, queda
   registrado con el modelo con que se lo pidió, así que el fallback sí se
   detecta.

Y un criterio a revisar, no un bug: los totales son todo-o-nada
(`all(c[k] is not None)`). Un solo 503 transitorio deja los tokens de **toda**
la corrida en `None`, perdiendo el consumo medido de las llamadas exitosas.

### Campaña: NODEX + baseline

La pseudo-ablación es un procedimiento **separado**, así que la campaña
automatizada ya no exige el agente único en toda corrida. El piloto baja de
72 a **48 corridas** y de 168 a **144 llamadas** (piso).

### Las siete verificaciones del §7

Corridas el 7-oct-2026 sobre un estado sintético con la forma de `d11-v1`.
**0 fallos.** No se ejecutó NODEX ni se llamó al modelo.

| # | Verificación | Resultado |
|---|---|---|
| 1 | Los 300 registros son accesibles | `CRONOLOGIA_MAX_EVENTOS=300`; **52/52** casos positivos con el incidente completo dentro |
| 2 | D2 y D3 llegan al adaptador | evaluables; técnica leída; atribución sin evidencia descartada; candidata del RAG en `_meta` |
| 3 | `evidence_uids` comparables con el ground truth | matching exacto por uid: tp/fp/fn = 1/1/1 |
| 4 | `tecnicas_atribuidas` vs `label_technique` | coincide; 22 técnicas en el vocabulario del dataset, 0 subtécnicas |
| 5 | Sin acceso a ground truth en inferencia | solo `_cargar_referencia` arma la ruta; ningún runner la arma; el adaptador no la recibe |
| 6 | Telemetría con `d11-v1` | D-11 detectado; `intentos_correccion` acumulado = 4; tokens `None` sin llamadas |
| 7 | Persistencia y evaluación | `run_id` de `gemini_externo` válido; campaña = NODEX + baseline; plan en seco sin ejecutar |

### Lo que falta

| Pendiente | Quién |
|---|---|
| Ejecutar el piloto N=1: **48 corridas, 144 llamadas** | Autorización de la autora |
| Los dos huecos de `src/telemetry.py` | Decisión sobre si se parchean en el núcleo |
| HDFS con N=3 | Se decide después del piloto principal |

## 18. Etapa 1: verificación por ejecución (14-oct-2026)

Primera vez que se ejecuta algo de la capa experimental. **No se llamó al
modelo, ni a AbuseIPDB, ni a NVD; no se ejecutó NODEX, el baseline ni
`gemini_externo` sobre ningún caso; `ejecutar_campana` se invocó solo con su
valor por omisión (plan en seco).** El worktree no tiene `.env`.

### Entorno real

| Componente | Versión instalada |
|---|---|
| Python | 3.13.5 |
| Node | 22.17.0 |
| pnpm | 10.33.0 |
| chromadb / sentence-transformers / torch | 1.5.9 / 6.1.0 / 2.14.0 |
| fastapi / pytest / langgraph / google-genai | 0.141.1 / 9.1.1 / 1.2.12 / 2.25.0 |
| pyarrow (solo `requirements-experimentacion.txt`) | 25.0.1 |

Instalado con `pip install -r requirements.txt -c constraints.txt` y luego
`requirements-experimentacion.txt`, en un `.venv` propio del worktree.
`pip check`: sin conflictos. El resultado coincide con lo declarado en la
Fase 0, que se había leído de archivos y no comprobado.

### Pruebas

| Corrida | Resultado |
|---|---|
| `tests/experimentation`, primera ejecución | **249 pasan, 10 fallan** |
| `tests/experimentation`, tras corregir | **290 pasan, 0 fallan** (incluye 31 pruebas nuevas) |
| Suite completa del proyecto | **860 pasan, 0 fallan, 0 omitidas**, 1 advertencia (obsolescencia de `anyio` dentro de Starlette, ajena) |

Correr la suite no modificó el repositorio ni escribió en `experiments/`.

### Los 10 fallos, clasificados

Ninguno fue defecto del código; ninguno fue del entorno. **Los diez eran
defectos de las pruebas**, escritas sin poder ejecutarse:

| # | Prueba | Causa |
|---|---|---|
| 1-6 | `test_adaptador_nodex` (6) | Afirmaban el comportamiento de la propuesta anterior (campos `id`, `nivel`, `uid`; extracción de IDs desde la prosa). La Fase D reescribió el adaptador para `d11-v1` y no actualicé estas pruebas |
| 7 | `test_la_cronologia_viaja_etiquetada...` | Buscaba `"no es"` con espacio en las claves de un dict cuya clave es `no_es`. Nunca pudo pasar |
| 8 | `test_la_base_experimental_existe_pero_esta_vacia` | Dejó de ser cierta al poblar la base el 4-oct (por diseño). Ahora verifica qué contiene |
| 9 | `test_la_prevalencia_efectiva...` | `approx` por omisión (1e-6 relativo) era más estricto que el redondeo a 6 decimales del propio manifiesto |
| 10 | `test_las_llamadas_por_corrida...` | Leía `agente_unico`, que la Fase D reemplazó por `gemini_externo` |

Las pruebas no se tocaron para que pasaran: se reescribieron para verificar
el comportamiento correcto del contrato actual, y se agregaron dos que
cubren el error que casi se cuela: que la clave de matching de D2 son los
`evidence_uids` y no el `event_id`, y que las tácticas quedan fuera del
scoring de D3.

### Defectos del código encontrados por ejecución

| Defecto | Cómo se encontró | Corrección |
|---|---|---|
| `gemini_externo` no tenía carpeta de almacenamiento (`KeyError` al planificar) | El plan en seco con esa arquitectura. **Las 261 pruebas no lo veían** | `persistencia.py` + prueba parametrizada sobre cada arquitectura del vocabulario. Verificado que falla sin el arreglo y pasa con él |
| `subconjuntos.main()` reescribía `piloto.json` y `rubrica.json` en cada corrida | Lectura al agregar el subconjunto de evaluación | `escribir_sin_sobrescribir()`. Al regenerar, ambos dieron contenido **idéntico**: la selección es determinista |
| `TestCase` chocaba con la convención de pytest | Advertencia en cada corrida | `__test__ = False` |

### Plan en seco (medido, no estimado)

`ejecutar_campana` con el valor por omisión. «Piso» es literal: NODEX tiene
6 puntos de llamada y sube con los bucles de replanificación y corrección,
que no se pueden acotar sin medir. Archivos en `experiments/` antes y
después del plan en seco: 1 023 y 1 023.

| Subconjunto | Partición | Reps. LLM | NODEX | Baseline | Gemini directo | Corridas | Llamadas (piso) |
|---|---|---|---|---|---|---|---|
| piloto, por defecto | desarrollo | 1 | 24 | 24 | — | **48** | **144** |
| piloto, con `gemini_externo` | desarrollo | 1 | 24 | 24 | 24 | **72** | **168** |
| rubrica, por defecto | evaluación | 3 | 36 | 12 | — | 48 | 216 |
| evaluacion, por defecto | evaluación | 3 | 426 | 142 | — | **568** | **2 556** |
| evaluacion, con `gemini_externo` | evaluación | 3 | 426 | 142 | 426 | **994** | **2 982** |

El subconjunto `evaluacion` (142 casos: 62 de BGL y 80 de UWF, sin HDFS por la
decisión D-7) no existía; se generó de forma determinista y no sobrescribe.

### Verificado por ejecución

- **60 hashes** coinciden con los registrados: 16 archivos fuente, 13 Parquet,
  13 CSV de eventos y 13 de etiquetas de UWF, y los 5 archivos de la base
  vectorial. Con la comprobación posterior a abrir la base, **61**.
- Los **336 casos** listados en los manifiestos existen en disco con su JSON,
  su contenido y su referencia (solo se comprobó la existencia de esta
  última; no se leyó).
- Los **3 subconjuntos** (piloto 24, rúbrica 12, evaluación 142) referencian
  únicamente casos existentes.
- La base vectorial abre en **modo solo lectura** (la escritura es rechazada),
  tiene una única colección, `attack_techniques`, con **697 documentos: 222
  técnicas y 475 subtécnicas**, y ninguna colección de memoria. La API de
  chromadb se abrió sobre una **copia**, porque abrir una base con la API puede
  ejecutarle migraciones; el original quedó con el mismo hash.
  **Esta verificación fue insuficiente (15-oct-2026, ver §21):** comprobó que los
  datos estaban, pero abrió la base sin la función de embeddings de NODEX, y con
  ella `src/memory.py` no puede abrirla. Se corrigió con una base v2 y un control
  nuevo que abre la base con el código de NODEX.
- La suite de D-11 (`tests/test_output_contract_d11.py`, de Felipe) pasa dentro
  de las 860.

### Pendiente: NO verificado por ejecución

- Cualquier corrida de NODEX, del baseline o de `gemini_externo` sobre un caso.
- Que Gemini responda: credencial, cuota y disponibilidad de
  `gemini-3.1-pro-preview` (modelo *preview*, lanzado el 19-feb-2026 según la
  página oficial de deprecaciones de Google; sin fecha de cierre anunciada.
  Una versión anterior de este documento lo llamaba «deprecado»: era un
  error, ver §20.1).
- Consumo real: tokens, latencia y llamadas por corrida.
- El recorrido completo corrida → almacenamiento → evaluación → métricas. Las
  piezas se probaron por separado; el recorrido entero se prueba en la Etapa 2.
- Consultas al RAG. **Corrección:** el modelo de embeddings SÍ se cargó, de forma
  indirecta: importar `src.api.main` (que hacen las pruebas de la API de
  producción) construye la memoria y carga los 103 tensores de
  `all-MiniLM-L6-v2` desde la caché local, y además avisa de una consulta
  sin autenticar a HF Hub. Es comportamiento ya existente. No se ejecutó
  ninguna consulta.
- Detección de fallback de modelo sobre telemetría real.
- Build, lint y typecheck del frontend.

### Correcciones a lo dicho antes

Al leer `src/telemetry.py` de nuevo con el código delante, dos de las tres
observaciones que hice sobre ella (Fase D) eran **parcialmente erróneas**:

- «No registra las llamadas fallidas»: **sí las cuenta**.
  `iniciar_llamada(modelo)` agrega la llamada a la lista *antes* de pedirle
  nada al proveedor, así que un intento fallido figura con tokens `None`. Lo
  que no guarda es el texto del error.
- «No detecta el fallback de modelo»: **sí es detectable**. Cada llamada guarda
  el modelo que se usó, y se compara contra `LLM_MODEL_PRIMARY` de la
  configuración congelada. Lo que falta es el modelo *solicitado*, no el
  efectivo.

Lo que sigue siendo cierto: los totales de tokens son todo-o-nada, así que un
solo intento fallido deja en `None` los tokens de toda la corrida.

La sección 16 de este documento (instrumentación propia del cliente LLM) está
**obsoleta**: el módulo se retiró en la Fase D.

## 19. Etapa 2: vista «Resultados» (15-oct-2026)

Consolidación, API de solo lectura y vista en la interfaz, listas para recibir
datos reales. **No se necesitaron datos reales y no se ejecutó nada**: ni
NODEX, ni el baseline, ni `gemini_externo`, ni `ejecutar_campana` con
`ejecucion_habilitada=True`. El bucle de ejecución se ejerció con corredores
simulados a través de `ejecutar_plan`. `experiments/outputs` no existe y
`experiments/metrics` quedó vacía.

### Qué se construyó

| Pieza | Dónde | Qué hace |
|---|---|---|
| Evaluación por corrida | `src/experimentation/evaluacion.py` | **Único módulo que abre `ground_truth/`**. Devuelve un registro por corrida, no métricas agregadas |
| Consolidación | `src/experimentation/consolidacion.py` | Agrupa, declara y escribe en `experiments/metrics/<config>/<marca>/`. Reutiliza los evaluadores; no reimplementa ninguna métrica |
| Línea de comandos | `python -m src.experimentation.consolidacion --subconjunto X --config Y` | Solo lee. Se niega a crear una consolidación si no hay corridas |
| API | `src/api/resultados.py` | 3 rutas GET: lista, resumen, reporte por `run_id` |
| Vista | `frontend/components/resultados-view.tsx` | Secciones 11.1 a 11.7, CSV por tabla, SVG y PNG por gráfico |

Salida de cada consolidación: `resumen.json`, un CSV por tabla, `registros.json`
(una fila por corrida evaluada), `tabla_14.csv` (el esquema exacto del §14) y
`metricas_p1.0_<marca>_contrato.json`, armado con los `MetricsRecord` del
contrato, cuyo invariante contable valida que no se pierda ninguna corrida.

### Definiciones que hay que conocer para leer una cifra

- **D1 micro**: una matriz de confusión con todas las corridas evaluables de
  un dataset y una arquitectura, repeticiones incluidas.
- **D1 macro por condición**: promedio de las métricas dentro de cada
  condición (natural, balanceado, visible, sigiloso). Cada condición pesa
  igual aunque tenga distinto número de casos o distinta prevalencia.
- **Media y desviación entre repeticiones**: la métrica se calcula por
  repetición y se promedia. Con una sola repetición la desviación es `null`,
  no cero: una observación no tiene dispersión.
- **D2 y D3**: micro, macro y coincidencia exacta; D3 solo a nivel de técnica
  (`label_technique`), por decisión del 7-oct-2026.
- **Fallback de modelo**: una corrida lo usó si alguna de sus llamadas la
  respondió un modelo distinto de `LLM_MODEL_PRIMARY` de la configuración
  congelada. Sin configuración congelada **no se da por inexistente**: se
  declara `fallback_no_determinable`.
- **Celdas `null`**: «no aplica o sin dato». En CSV, celda vacía. Para el
  baseline, por ejemplo, los tokens y el fallback no aplican.

### Defectos reales encontrados al conectar las piezas

Ninguna prueba unitaria los veía; cada pieza, por separado, estaba bien.

| # | Defecto | Consecuencia si no se corregía |
|---|---|---|
| 1 | Las corridas guardaban su salida pero **no cómo habían terminado ni qué dimensiones eran puntuables**; la evaluación lo leía justo de ahí | Toda dimensión habría figurado como no evaluable: tablas vacías que se confunden con un sistema que falla |
| 2 | `gemini_externo` no tenía carpeta de almacenamiento (`KeyError`) | Fallaba **después** de gastar la llamada al modelo (Etapa 1) |
| 3 | El evaluador de consumo esperaba `tokens_entrada`, `latencia_total_s`… y la telemetría real produce `input_tokens`, `execution_time`… | Toda la columna de consumo habría salido ausente, sin error. Las pruebas pasaban porque sus fixtures usaban los mismos nombres equivocados |
| 4 | Un fallo solo vivía en el valor de retorno de `ejecutar_campana` | Se perdía al terminar el proceso; nada podía mostrarlo |
| 5 | La evaluación mezclaba BGL y UWF en una sola matriz de confusión por arquitectura | Dos preguntas distintas promediadas juntas |
| 6 | Al baseline le aparecían «sin tokens: 4» y «con fallback: 0» | No usa el modelo: esas celdas **no aplican** y un 0 dice lo contrario. Lo mostró la revisión visual de la página renderizada |
| 7 | `subconjuntos.main()` reescribía `piloto.json` y `rubrica.json` en cada corrida | Violaba la regla de no sobrescribir (Etapa 1) |

Además se separó la lectura del ground truth en `evaluacion.py`:
`orquestador.py` —el que corre arquitecturas— **ya no contiene ninguna ruta
a `ground_truth/`**, y las pruebas lo verifican por AST: el orquestador no
tiene la ruta, no importa la evaluación, y la evaluación no importa los
runners ni el sistema.

### Verificado por ejecución

- **Suite completa: 928 pasan, 0 fallan.** Capa experimental: 323. Interfaz
  (Vitest): 65.
- `pnpm lint`: **0 errores**, 2 advertencias que ya existían (el patrón de
  carga al montar de las otras vistas). La vista nueva no suma ninguna.
- `pnpm typecheck`: limpio. `pnpm build`: exitoso (Next.js 16.3.3).
- El recorrido **ejecutar → guardar → evaluar → consolidar** con corredores
  simulados produce las ocho tablas, la tabla del §14 y el contrato.
- **Mutaciones**: se reintrodujo cada defecto a propósito y cada uno hizo
  fallar su prueba (5 en el recorrido completo, 4 en la API, 6 en la
  interfaz). Hubo una que **no** se atrapaba —devolver el archivo entero de
  la corrida en la API— y por eso se agregó la prueba de campos exactos.
- La API: 3 rutas, todas GET; validación estricta de la URL; la ruta final se
  comprueba contra `experiments/`; un archivo centinela en `ground_truth/` no
  aparece en ninguna respuesta; el módulo no contiene la ruta ni importa el
  sistema.

### Pendiente: NO verificado

- **La vista en un navegador real contra la API real.** Se verificó con
  jsdom (65 pruebas) y con un build de producción, no a ojo. No hay tools de
  navegador en esta sesión.
- Todo lo de la Etapa 1 que sigue pendiente: corridas reales, disponibilidad
  de Gemini, consumo real, detección de fallback sobre telemetría real.
- **Formulario para los dos evaluadores humanos.** La consolidación lee
  `experiments/rubrica/<config>/puntajes.csv`, pero no hay plantilla ni
  herramienta para capturar los puntajes, y los informes **no se ocultan**
  respecto de qué arquitectura los produjo. Hacerlo ciego es un requisito de la
  rúbrica y falta construirlo antes de la parte humana.
- **Lanzador**: no hay un comando para ejecutar el piloto. Hoy `ejecutar_campana`
  se invoca desde código. Falta una línea de comandos que exija
  `--ejecutar` de forma explícita y muestre el plan antes.
- Los totales de tokens todo-o-nada de `src/telemetry.py` (un solo 503 deja
  los tokens de toda la corrida en `None`). Reportado a Felipe; no se tocó el
  núcleo. *(La versión original de esta línea decía también que el modelo
  solicitado no se guardaba: era falso, ver §20.3.)*

## 20. Cambio de modelo: instrumentación, «sin respaldo» y comparación mínima (15-oct-2026)

Preparación para decidir si la campaña corre con `gemini-3.8-flash` en vez de
`gemini-3.1-pro-preview`. **Esta sección se escribió antes de ejecutar la
comparación**: los casos, los criterios y la regla de decisión de abajo están
fijados de antemano, y el resultado se registra aparte, después.

### 20.1 Estado real del modelo principal (corrección)

Documentos anteriores decían que `gemini-3.1-pro-preview` estaba «deprecado
desde feb-2026». **Es incorrecto.** El 19-feb-2026 es su **fecha de lanzamiento**
según la página oficial de deprecaciones de Google. Es un modelo *preview*, sin
fecha de cierre anunciada y sin versión estable (GA). El riesgo que sí existe,
y que no cambia: un modelo *preview* puede cambiar o retirarse con poco aviso.
`src/config.py` no contenía la afirmación; se corrigieron los dos lugares de
este documento que la repetían.

### 20.2 Qué se construyó

| Pieza | Dónde | Qué hace |
|---|---|---|
| Versión devuelta y tokens de razonamiento | `src/llm.py` | Cada llamada registra `model_version` (lo que dice la respuesta de la API) y `reasoning_tokens` (`thoughts_token_count`). Lo que el proveedor no informa queda `None`, nunca 0. `src/telemetry.py` no se tocó: `iniciar_llamada` devuelve el mismo diccionario que luego se copia a `llm_calls` |
| Puente a la capa experimental | `runtime/telemetria.py::campos_de_modelo` | Alimenta `LlamadaLlm.modelo_efectivo` y `reasoning_tokens`; suma, lista versiones y declara las sumas parciales |
| Persistencia y exportación | `orquestador.py`, `runtime/exportacion.py` | La telemetría guardada lleva `reasoning_tokens` y `modelos_efectivos`; la tabla del §14 suma las columnas `reasoning_tokens` y `modelos_efectivos` |
| Consolidación y vista | `consolidacion.py`, vista «Resultados» | Tabla de consumo con «Tokens de razonamiento» y «Versión devuelta por la API»; la serie «Razonamiento» en el gráfico de tokens; dos avisos informativos (`razonamiento_no_informado`, `version_de_modelo_no_informada`) |
| Opción «sin respaldo» | `src/config.py`, `src/llm.py` | `LLM_SIN_RESPALDO` (opt-in; **por omisión apagada**, el comportamiento no cambia). Solo apaga el **cambio de modelo**: los reintentos con espera sobre el mismo modelo (503, 429 por minuto) siguen. Entra en la configuración congelada |
| Comparación mínima | `src/experimentation/comparacion_modelos.py` | Plan, seis criterios de validez y regla de decisión, regla de repetición y orden por etapas. Sin `--etapa` solo muestra el plan |

Dos reglas de diseño que conviene recordar al leer los datos:

- **El fallback NO se deduce comparando el nombre pedido con la versión
  devuelta.** La API puede devolver `modelo-001` cuando se pidió `modelo`, y
  eso no es un respaldo. El fallback se decide con el nombre pedido en cada
  llamada (`model`), que en el camino de respaldo ya es el modelo de respaldo.
- Una respuesta de **Gemini directo** que no era JSON figuraba con **0
  llamadas** aunque la llamada se hizo y gastó tokens (defecto previo, ahora
  corregido): el consumo quedaba subestimado.

### 20.3 Corrección de dos afirmaciones de la sección 17

La sección 17 decía que `src/telemetry.py` «no registra las llamadas fallidas»
y «no guarda el modelo solicitado». Con el código actual **ambas son falsas**:
`iniciar_llamada(modelo)` agrega la llamada **antes** de intentarla, así que una
llamada fallida queda con tokens `None`, y cada intento (principal y respaldo)
queda registrado con el modelo con que se lo pidió. Lo que sigue siendo cierto:
los totales de tokens son todo-o-nada (`all(c[k] is not None ...)`).

### 20.4 Limitación declarada: temperatura 0

La guía oficial de Gemini 3 indica: *«For all Gemini 3 models, we strongly
recommend keeping the temperature parameter at its default value of 1.0»*, y
advierte que bajarla puede causar *«looping or degraded performance,
particularly in complex mathematical or reasoning tasks»*.

NODEX y Gemini directo usan **temperatura 0** (decisión del proyecto: la
especificación del informe pide 0, y 0 minimiza la variación entre corridas).
Se mantiene en 0 en ambos modelos de la comparación. **Es una limitación de
validez, no un hallazgo:** si se observan bucles o respuestas degradadas, se
reportan; no se corrigen cambiando la temperatura.

Tampoco se envía `thinking_level`: rige el valor por omisión de cada modelo
(`medium` para `gemini-3.8-flash` y `gemini-3.6-flash`; `minimal` no está
soportado en 3.8-flash y da error, y NODEX nunca lo pide). El valor por omisión
del Pro no se verificó en la documentación oficial. Los tokens de razonamiento
se cobran aparte de la salida, así que el costo y el tiempo pueden diferir
entre modelos aunque el texto se parezca.

### 20.5 Comparación mínima (diseño fijado antes de ejecutar)

**Pregunta:** con cada modelo, ¿la corrida produce una salida válida y sin
accidentes? **No** se compara acierto, F1 ni calidad del reporte, y esta
comparación **no se guarda como resultado reportable** (se escribe fuera de
`experiments/`).

**Casos.** Criterio fijado antes: el primer `case_id`, por orden alfabético, de
cada dataset del subconjunto de desarrollo `piloto`.

| Dataset | Caso | Tamaño de la entrada |
|---|---|---|
| BGL | `bgl_des_balanceado_0000` | 3,5 KB |
| UWF | `uwf_des_sigiloso_0004` | 55,9 KB (CSV) |

HDFS queda fuera (D-7, solo auxiliar). El caso de UWF es de la condición
«sigiloso» solo porque ese es el primero alfabético; no se eligió por su
dificultad.

**Corridas.** 2 casos × 2 modelos (`gemini-3.1-pro-preview`,
`gemini-3.8-flash`) × 2 arquitecturas con LLM (NODEX y Gemini directo) = **8
corridas, 28 llamadas como mínimo** (NODEX 6 + Gemini directo 1, por cada
combinación). El 28 es un **piso**: un reintento o una corrección lo supera.
El baseline no entra porque no usa el modelo.

**Criterios de validez** (los seis, por corrida):

1. `json_objeto_valido`: la respuesta del modelo es JSON válido y es un objeto.
   En NODEX se cuenta cada respuesta final de `llm_json` (ninguna debe ser
   `json_invalido`); en Gemini directo, que la respuesta se haya podido leer
   como objeto.
2. `veredicto_presente`: hay un veredicto booleano.
3. `evidencia_valida`: `invalid_evidence_uid_count` es 0 **y** todo uid citado
   existe en el caso (recalculado aparte con el archivo del caso). En NODEX el
   contador debe valer 0 (si falta, no se da por 0); Gemini directo no tiene
   contador y se juzga solo por los uids. En BGL, que no tiene uids, citar
   alguno es inválido.
4. `tokens_registrados`: hay tokens de entrada y de salida registrados.
5. `sin_timeout_ni_error`: sin timeout ni error de API ni excepción.
6. `solo_el_modelo_pedido`: ninguna llamada usó otro modelo.

También se informan, sin criterio: tokens de razonamiento, tiempo, número de
llamadas, versión devuelta y tamaño de las salidas (para detectar bucles).

**Regla de decisión** (fijada antes): si `gemini-3.8-flash` cumple los seis
criterios en sus cuatro corridas (los dos casos, con NODEX y con Gemini
directo), será el modelo principal de la campaña. Si falla alguno, se mantiene
`gemini-3.1-pro-preview` y se documenta el motivo. Que falle el Pro no cambia
la regla: es la referencia, no el candidato. La herramienta solo aplica la
regla y la muestra; **no cambia ninguna configuración ni congela nada.**

**Condiciones de ejecución.**

- Respaldo **apagado** (`LLM_SIN_RESPALDO=true`), con el modelo de respaldo
  igualado al principal. Cada corrida es un proceso propio con su modelo en el
  entorno.
- Temperatura 0 en ambos modelos.
- Las llamadas HTTP de `requests` (el cliente de AbuseIPDB y NVD) **se
  bloquean**: no están autorizadas para esta comparación y la política del
  proyecto las deja congeladas fuera de la campaña. Las herramientas caen a su
  respaldo local, igual para los dos modelos. Los intentos bloqueados se
  cuentan y se informan. Gemini usa otro cliente y no se ve afectado.
- ChromaDB y la caché de IP son **copias temporales**: la base experimental no
  se modifica (NODEX puede escribir en su memoria al auditar).
- El modo sin conexión de Hugging Face se fuerza (`HF_HUB_OFFLINE=1`).

**Qué NO prueba:** no mide acierto; con un solo caso por dataset no prueba
estabilidad entre corridas; y cumplir los criterios no demuestra que
`gemini-3.8-flash` detecte igual de bien que el Pro, solo que el sistema no se
rompe con él.

### 20.6 Regla de repetición y orden de ejecución (fijadas antes de la primera llamada)

**Interpretación estricta de la regla de decisión** (confirmada): `gemini-3.8-flash`
pasa a modelo principal solo si cumple los 6 criterios en sus 4 corridas (los
dos casos, con NODEX y con Gemini directo).

**Regla de repetición:**

| Tipo de fallo | Qué es | Se repite |
|---|---|---|
| Contenido | JSON inválido, veredicto ausente, uids de evidencia inválidos, tokens no registrados (o llamadas con otro modelo) | **No.** Cuenta como fallo |
| Infraestructura | Timeout, 503 o 429 que persisten tras los reintentos con espera de `src/llm.py` | **Una vez.** Se conservan los dos intentos. Si el repetido también falla, cuenta como fallo |
| Otro | Un error que no es ninguno de los dos (p. ej. un 400 o un fallo del propio código) | **No.** Cuenta como fallo: repetirlo no lo arregla |

Si hay un error, el error manda: un timeout deja la corrida sin tokens y sin
veredicto, y eso es infraestructura, no contenido. Nunca hay un tercer intento.

**Orden de ejecución.** Etapa 1: caso de BGL (`bgl_des_balanceado_0000`) con el
candidato, primero Gemini directo y luego NODEX. Antes de seguir se revisa lo que
devolvió la API real: que `model_version` no sea `None` y corresponda al modelo
pedido, y que los tokens de razonamiento estén informados o sean `None` (si el
proveedor no los informa se dejan así; no se inventan). Si algo es inesperado la
herramienta termina con código 3 y **se detiene**. Si todo está limpio, la
etapa 2 corre las seis restantes sin otra confirmación: BGL con el Pro, y luego
UWF con el candidato y con el Pro (en cada caso, Gemini directo antes que
NODEX).

### 20.7 DECISIÓN PENDIENTE: NVD y AbuseIPDB en la campaña final

En esta comparación **se bloquean** las llamadas HTTP de `requests` (el cliente
que usan NVD y AbuseIPDB), con confirmación expresa. Las herramientas caen a su
respaldo local, **igual para los dos modelos**, y los intentos bloqueados se
cuentan y se informan.

Para la **campaña final** queda abierto, y debe decidirse antes de congelar la
configuración, si NODEX corre:

- **con consultas reales** a NVD y AbuseIPDB (como en producción; la caché de IP
  se llenaría una vez, en un paso autorizado aparte, y luego se usaría en solo
  lectura, según `POLITICA_RECURSOS_EXTERNOS`), o
- **con el respaldo local** (sin red, reproducible, pero distinto de producción).

**Cualquiera de las dos opciones hay que declararla en el informe**, porque
cambia lo que las herramientas le entregan al sistema y por lo tanto lo que se
está midiendo. Ninguna comparación hecha con una opción es directamente
comparable con otra hecha con la otra.

### 20.8 ENMIENDA del criterio 3 (15-oct-2026, DESPUÉS del primer resultado)

**Esta enmienda se hace después de ver un resultado y se registra como tal.**

*Primer resultado* (etapa 1, 15-oct-2026): `gemini-3.8-flash` con Gemini directo
sobre `bgl_des_balanceado_0000` cumplió 5 de los 6 criterios y **falló el 3**
(`evidencia_valida`). El modelo reconstruyó 8 eventos y citó 19 «uids», números
tipo `1129456912`. BGL no tiene columna `uid`, y el criterio original decía que
citar uids en un caso sin uids es inválido. Falla de contenido: no se repite.

*Motivo de la enmienda.* El criterio original no mide lo que se quería medir en
BGL: la dimensión de reconstrucción **no aplica** a BGL, así que no hay
referencia contra la cual juzgar los uids que cita el modelo, y el prompt de
Gemini directo se los pide igual (ver 20.9). Un criterio que cualquier modelo
incumple en BGL no discrimina entre modelos.

*Enmienda.* En datasets **sin columna `uid`** (BGL):
- **Gemini directo:** no se juzga la evidencia citada.
- **NODEX:** solo cuenta `invalid_evidence_uid_count` (debe ser 0; ausente no se
  da por 0).

En datasets **con** columna `uid` (UWF) el criterio **no cambia**. (Interpretación
de la enmienda: se aplica solo a los datasets sin `uid`; no se la extendió a UWF.)

*Cómo se conserva lo anterior.*
- El veredicto con el criterio **ORIGINAL** de la primera corrida queda guardado
  tal cual; no se recalcula.
- Cada corrida guarda **los dos veredictos** (original y enmendado), y la tabla
  final muestra ambos.
- Las corridas del Pro previstas sobre el mismo caso se ejecutan igual.

*Regla de decisión con la enmienda.* La decisión se toma con el criterio
**enmendado SOLO si el Pro también incumple el criterio 3 ORIGINAL en BGL con
Gemini directo** (eso demuestra que el criterio original no discrimina). Si el Pro
lo cumple y el candidato no, vale la regla original y el resultado es «se mantiene
el Pro». Si esa corrida del Pro no se hizo o no devolvió una respuesta que juzgar
(p. ej. una caída de infraestructura), también vale la original: una caída no
demuestra nada sobre el criterio.

### 20.9 Limitaciones declaradas de la comparación

1. **El prompt de Gemini directo pide reconstrucción de eventos en BGL**, donde esa
   dimensión no aplica. Gemini directo recibe la misma instrucción en todos los
   datasets, así que en BGL inventa referencias de evidencia que no se pueden
   juzgar. Es una limitación del diseño de la pseudo-ablación, no del modelo.
2. **DECISIÓN PENDIENTE sobre NVD y AbuseIPDB** para la campaña final (ver 20.7):
   consultas reales o respaldo local, y la elección debe declararse en el informe.
3. **Temperatura 0** frente a la recomendación oficial de 1.0 (ver 20.4).
4. Un caso por dataset: no prueba estabilidad entre corridas.

### 20.10 Primer intento de la etapa 1 (anulado por la base de conocimiento)

El primer intento de NODEX con `gemini-3.8-flash` sobre BGL terminó en error **antes
de llamar al modelo** (0 llamadas): la base de ChromaDB no se podía abrir con el
código de NODEX (ver sección 21). Ese intento no mide nada del modelo. Sus archivos
se conservan con la extensión `.anulada` y la corrida se repite con la base v2.
No cuenta como repetición «por infraestructura» de la regla 20.6: fue un defecto de
la base y no del proveedor.

### 20.11 Tope de tiempo de las corridas del Pro en UWF (fijado DESPUÉS de observar la corrida 4)

**Fecha:** 15-oct-2026. **Motivo:** la corrida 4 (NODEX con `gemini-3.1-pro-preview` en
BGL) tardó **97 minutos** (5.806 s), frente a 34 s de la corrida 2 (NODEX con el
candidato en el mismo caso). Se fijó entonces un tope de **2 horas** para las
corridas 7 y 8 (Pro, UWF), que son de comparación y **no entran en la regla de
decisión**. Si una lo superaba, se cortaba y se registraba como «no completó en el
tiempo previsto». Las corridas 5 y 6 (candidato, UWF) no tenían tope.

**Este tope NO es un criterio de decisión del modelo.** No se activó: las corridas
7 y 8 terminaron en 30 s y 185 s.

**Defecto encontrado en el tope anterior.** El código tenía un tope de 2400 s para
todas las corridas, pero **no se cumplía**: el `python.exe` del venv es un lanzador
que arranca al intérprete real; matar solo al lanzador deja vivo al hijo, y
`communicate()` esperaba a que el hijo cerrara las tuberías. La corrida 4 superó
los 2400 s sin cortarse y quedó registrada como una corrida normal. Se corrigió
(`ejecutar_hijo` mata el **árbol** de procesos) y una prueba reproduce el defecto
original (con el defecto, el tope tarda los 120 s del hijo en volver). Mientras se
corregía el código, la corrida 8 (que ya había arrancado con el código anterior) se
vigiló con un proceso externo con el mismo tope de 2 horas; no llegó a cortar nada.

### 20.12 Resultado de la comparación mínima (15-oct-2026)

Casos: `bgl_des_balanceado_0000` y `uwf_des_sigiloso_0004`. Respaldo apagado,
temperatura 0, ChromaDB v2 (copia). **Intentos de HTTP bloqueados: NO SE MIDIERON** (el
contador estaba roto, ver 20.16; el bloqueo sí funcionó). Todas las
versiones devueltas por la API coinciden con el modelo pedido.

Criterios en el orden 1 JSON · 2 veredicto · 3 evidencia · 4 tokens · 5 sin error ·
6 solo el modelo pedido. **S** = cumple, **N** = no.

| # | Modelo | Arq. | Caso | Original | Enmendado | Entrada | Salida | Razonam. | Tiempo | Llamadas |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 3.8-flash | Gemini directo | BGL | S S **N** S S S | S S S S S S | 2.731 | 2.260 | 1.263 | 22 s | 1 |
| 2 | 3.8-flash | NODEX | BGL | S S **N** S S S | S S S S S S | 4.299 | 1.069 | 2.226 | 34 s | 5 |
| 3 | 3.1-pro | Gemini directo | BGL | S S **N** S S S | S S S S S S | 2.731 | 1.541 | 3.196 | 36 s | 1 |
| 4 | 3.1-pro | NODEX | BGL | S S **N** **N** S S | S S S **N** S S | None (≥9.796 parcial) | None (≥2.201 parcial) | None (≥9.830 parcial) | 5.806 s | 12 (1 sin tokens) |
| 5 | 3.8-flash | Gemini directo | UWF | S S S S S S | S S S S S S | 50.720 | 1.428 | 7.038 | 62 s | 1 |
| 6 | 3.8-flash | NODEX | UWF | S S S S S S | S S S S S S | 61.667 | 1.826 | 5.820 | 70 s | 6 |
| 7 | 3.1-pro | Gemini directo | UWF | S S S S S S | S S S S S S | 50.720 | 863 | 3.695 | 30 s | 1 |
| 8 | 3.1-pro | NODEX | UWF | S S S S S S | S S S S S S | 128.643 | 3.791 | 13.935 | 185 s | 13 |

Ninguna corrida se repitió (ni por contenido ni por infraestructura). La corrida 2
original quedó **anulada** (la base de ChromaDB v1 no se podía abrir, 0 llamadas al
modelo) y sus archivos se conservan con la extensión `.anulada`.

**Aplicación de la regla, tal como quedó escrita (20.6 y 20.8).**
- Con el criterio **original**: `gemini-3.8-flash` falla el criterio 3 en las
  corridas 1 y 2 → resultado «se mantiene `gemini-3.1-pro-preview`».
- Con el criterio **enmendado**: cumple los 6 criterios en sus 4 corridas →
  `gemini-3.8-flash`.
- Qué veredicto vale: el enmendado **solo si el Pro también incumple el criterio 3
  original en BGL con Gemini directo**. Lo incumple (corrida 3: citó los mismos 19
  números como «uids»), así que el criterio original no discrimina y vale el
  enmendado. **Resultado de la regla: `gemini-3.8-flash` pasa a modelo principal.**

La herramienta no cambia ninguna configuración; no se congeló nada ni se lanzó el
piloto.

### 20.13 Observaciones (no son criterios)

1. **Contraste de tiempo entre las corridas 2 y 4.** Mismo caso, misma arquitectura,
   distinto modelo: 34 s con el candidato y 5.806 s con el Pro. Es **una sola
   corrida** de cada una y puede ser transitorio: la corrida 8 (Pro, NODEX, UWF)
   tardó 185 s y la 3 (Pro, Gemini directo, BGL) 36 s. No se puede atribuir a una
   propiedad del modelo con estos datos.
2. **Corrida 4, criterio 4 («tokens registrados»): falso, tal como salió.** Causa:
   una de sus 12 llamadas falló y se reintentó (queda registrada sin tokens ni
   versión), y `src/telemetry.py` calcula los totales de forma **todo-o-nada**
   (`all(c[k] is not None ...)`), así que los totales de la corrida quedan en
   `None`. Suma parcial de las 11 llamadas que sí registraron tokens, **parcial y
   por lo tanto un piso**: entrada ≥ 9.796, salida ≥ 2.201, razonamiento ≥ 9.830.
   El veredicto del criterio no se cambió. **Cuánto tardó cada llamada no se
   puede decir:** la telemetría no guarda duración por llamada y la salida estándar
   de esa corrida no se conservó (se corrigió: ahora se guarda). Solo se conoce el
   total (5.806 s), 1 reemplanificación y 2 intentos de corrección.
3. **NODEX no hizo siempre 6 llamadas.** La corrida 2 hizo 5. El «piso de 6» de
   `LLAMADAS_POR_CORRIDA` no es un piso: el número depende del camino del grafo
   (5, 6, 12 y 13 llamadas en estas cuatro corridas). La cifra «28 llamadas
   mínimas» fue una estimación de partida; se hicieron **40 llamadas** en total
   (13 con el candidato y 27 con el Pro, una de ellas fallida).
4. No se observaron bucles ni respuestas degradadas con temperatura 0: la mayor
   salida por llamada fue 2.260 tokens (Gemini directo, BGL).

### 20.14 PROPUESTA (implementada el 15-oct-2026, ver 22.4): cómo debe mostrar el consolidador las corridas con total `None`

Hoy una llamada fallida deja `input_tokens`, `output_tokens` y `total_tokens` de
toda la corrida en `None`, y la tabla de consumo la excluye de los promedios de
tokens y la cuenta en «Sin tokens informados». Propuesta para la campaña:

1. **Conteo explícito:** en la tabla de consumo, «Corridas con total None: k de n»
   y «Llamadas fallidas: m», separadas de «sin tokens porque el proveedor no los
   informa».
2. **Suma parcial rotulada, nunca mezclada con los totales:** columnas
   «Tokens (suma parcial, piso)» que solo se llenan cuando el total es `None`, con
   el rótulo «≥» y «(11 de 12 llamadas)».
3. **Los promedios de tokens siguen usando solo corridas con total completo.**
   Una media que mezclara totales y pisos subestimaría el consumo. Se muestra
   además cuántas corridas quedaron fuera de la media.
4. **Aviso de integridad** `tokens_parciales` (severidad media) con la lista de
   corridas, el n de llamadas fallidas y la causa probable (reintento tras
   503/429).
5. **Duración por llamada:** registrarla en `src/llm.py` (como ya se hace con
   `model_version`) para poder decir cuánto duró cada llamada, incluidas las
   fallidas.
6. En la vista, esas corridas se marcan con una advertencia visible junto a las
   cifras; el CSV deja el total vacío y la suma parcial en su propia columna.

### 20.15 Decisión: `gemini-3.8-flash` es el modelo principal (15-oct-2026)

Se acepta el resultado de la regla de decisión: **`gemini-3.8-flash` es el modelo
principal** del piloto y de la campaña. Conviene dejar claro en qué se basa:

- **La elección se basa en validez técnica, no en acierto.** La comparación no midió
  acierto, F1 ni calidad del reporte; solo comprobó que el sistema produce una salida
  válida y sin accidentes con cada modelo (JSON válido, veredicto, evidencia, tokens
  registrados, sin error, solo el modelo pedido). **No hay evidencia de que
  `gemini-3.8-flash` detecte igual o mejor que el Pro.** Esa pregunta es de la campaña,
  no de esta comparación.
- **El criterio 3 se enmendó DESPUÉS del primer resultado** (ver 20.8). La evidencia de
  que el criterio original no discriminaba es la corrida 3: el Pro con Gemini directo
  en BGL citó los mismos 19 números como «uids» y también lo incumplió. La enmienda y su
  motivo están registrados con fecha; el veredicto original de cada corrida se conserva.
- **La corrida 4 del Pro (97 min, una llamada fallida) es una observación aislada.** Es
  una sola corrida y puede ser transitoria (la corrida 8, del mismo modelo y la misma
  arquitectura, tardó 185 s). No se usa como argumento contra el Pro ni a favor del
  candidato.

### 20.16 CORRECCIÓN: el contador de intentos HTTP de la comparación estaba roto

> **El contador «0 intentos HTTP bloqueados» de la comparación de modelos NO es una
> medición válida y NO debe citarse** (ni en el informe ni en otros documentos). No se
> sabe cuántos intentos de consulta externa hubo en esa comparación. El primer dato
> válido saldrá del piloto (sección 22.5).

En 20.12 se informó «0 intentos de HTTP bloqueados en las 8 corridas (las herramientas de
NVD/AbuseIPDB no se invocaron en estos casos)». **Esa afirmación no estaba respaldada.**
El bloqueo de red recibía la URL como argumento posicional, pero `requests.get` llama a
`Session.request(method=..., url=...)` **por nombre**: la función de bloqueo fallaba con
`TypeError` antes de anotar el intento. El efecto práctico:

- **El bloqueo SÍ funcionó** (la petición no salió; las herramientas, que tragan toda
  excepción, cayeron a su respaldo local).
- **El contador marcó 0 siempre**, así que no se sabe cuántos intentos hubo en la
  comparación. «0» era un artefacto, no una medición.

Se corrigió (`consultas_externas.py` y `comparacion_modelos.py`) y una prueba reproduce
el defecto: llama a `requests.get(...)` de verdad con la red bloqueada y exige que el
intento quede anotado. Lo aprendido: un contador que dice 0 tiene que haberse probado
con un caso que dé más de 0.

## 21. Base de ChromaDB v2 (15-oct-2026)

### 21.1 Qué falló y por qué la verificación anterior no lo vio

La base experimental original (`experiments/knowledge/chroma`, **v1**) se creó con
`create_collection` **sin función de embeddings**, así que ChromaDB guardó la
función «default». `src/memory.py` abre las colecciones con
`SentenceTransformerEmbeddingFunction` y ChromaDB 1.5.9 rechaza el choque
(*«An embedding function already exists in the collection configuration... new:
sentence_transformer vs persisted: default»*). Toda corrida de NODEX con esa base
habría fallado al importar el sistema.

**La verificación de la Etapa 1 (sección 18) fue insuficiente.** Contó los 697
documentos abriendo la base con la API de Chroma **sin función de embeddings**:
comprobó que los datos estaban, no que NODEX pudiera abrirlos. Lo descubrió la
primera corrida real de NODEX.

### 21.2 Qué se cambió para que no se repita

- **Nuevo control** (`knowledge/verificar_base.py`): abre una copia de la base con
  `LongTermMemory`, **el mismo código que usa NODEX**, y hace consultas reales con
  embeddings locales. Está incorporado como sección 7 de `verificar_artefactos`.
- **Una prueba reproduce el defecto:** abrir la v1 con el código de NODEX falla, y
  la prueba lo exige. Sin ese control, la verificación anterior habría seguido
  «pasando».
- Regla de trabajo: **una base de conocimiento se verifica abriéndola con el código
  que la va a usar, no con una API equivalente.**

### 21.3 Qué se hizo

- **Base nueva en una ruta versionada:** `experiments/knowledge/chroma_v2`. La v1 **no
  se tocó** (sus hashes registrados siguen coincidiendo) y queda solo como
  referencia (`ConfiguracionAislada.chroma_v1`).
- Construida desde **una copia** de la v1 con los vectores ya calculados (no se
  recalculan), creando la colección con la función de embeddings de NODEX
  (`sentence_transformer`, `all-MiniLM-L6-v2`). Mismos 697 documentos, ids y
  metadatos. Solo `attack_techniques`: **sin casos reservados, etiquetas ni
  feedback** (las colecciones de memoria de producción no se copian).
- `src/memory.py` **no se adaptó.**
- Registros nuevos (los de la v1 no se reescribieron): `poblado_chroma_v2.json` (con
  el hash de cada archivo), `inventario_conocimiento_v2.json`,
  `verificacion_chroma_v2.json`. La configuración congelada registra sus hashes.

### 21.4 Verificación de la v2 (por ejecución)

Las 12 consultas se escribieron y commitearon **antes** de construir o consultar la
base (`CONSULTAS_FIJAS`), son descripciones genéricas de ATT&CK y una prueba
comprueba que no contienen ningún `case_id` ni líneas de un caso.

| Qué | Resultado |
|---|---|
| Se abre con `LongTermMemory` y responde consultas reales | Sí: 697 documentos, 12/12 consultas con resultados |
| Mismos ids y mismo orden que la v1 (top 5) | **12 de 12** |
| Mismo resultado que vería NODEX (tras el umbral de similitud) | **12 de 12** |
| Mayor diferencia de distancia entre v1 y v2 | **5,96e-08** (consultas «scanning a network...» y «disabling security tools...»), el redondeo de float32 ya medido |
| Diferencia máxima entre vectores guardados | 1,49e-08 |
| Ids, documentos y metadatos | Idénticos |
| Claves de metadatos | Solo las del catálogo (`technique_id`, `name`, `tactics`, `is_subtechnique`, `url`) |
| Vectores guardados vs recalculados con el modelo (40 documentos) | Coseno mínimo 0,99999999999992 |
| `case_id` encontrado dentro del contenido | Ninguno |
| Aislamiento (`test_aislamiento` y `verificar_artefactos`) | 67 hashes comprobados, 0 fallos |

No se observó ninguna diferencia de ids ni de orden; la única diferencia es la de
distancia ya citada. Una limitación: 12 consultas no prueban todos los casos de
empate posibles, solo que la v2 no cambia lo que recupera en ese conjunto.

## 22. Preparación del piloto (15-oct-2026)

Todo lo de esta sección se construyó y probó con procesos y clientes simulados; **no se
hizo ninguna llamada al modelo** para construirlo.

### 22.1 Configuración congelada

`campana --congelar` fija, en un proceso con el entorno ya puesto, la configuración que
verá el sistema: `gemini-3.8-flash`, `LLM_SIN_RESPALDO` activo, temperatura 0 y
`generateContent`. Gemini directo hereda el mismo modelo y temperatura. La
configuración congelada registra además, en campos nuevos, **cómo se llama al modelo**
(`generacion`: API, formato de respuesta, respaldo apagado, reintentos con espera, versión
del SDK) y la **política de recursos externos** (`recursos_externos`). Cada corrida corre
en un proceso propio cuyo entorno sale de lo congelado, no del `.env` (que solo aporta las
credenciales). Antes de ejecutar se exige que el código sea el congelado (mismo commit y
`src/` limpio) y que la configuración efectiva coincida con la congelada.

### 22.2 «Piso» de llamadas: corregido

`LLAMADAS_POR_CORRIDA` decía que 6 era un piso de llamadas de NODEX. Lo medido fue 5, 6, 12
y 13 (la corrida 2 hizo 5). Ahora el plan habla de **llamadas de referencia (NO un
piso)**, con el rango medido por arquitectura (`LLAMADAS_MEDIDAS`).

### 22.3 Estimación de tokens (orden de magnitud)

`estimacion.py` multiplica lo medido en la comparación (Flash, **una corrida por celda y un
caso por dataset**) por el número de corridas del plan. Es un orden de magnitud, no un
presupuesto: los tokens dependen del caso y, en NODEX, de los bucles del grafo. **HDFS no se
midió** y figura como «sin medición» (no suma). El baseline no usa el modelo. **No se supone
ningún precio:** `experiments/config/precios_modelo.json` es una tabla configurable con
fecha y fuente que viene vacía; mientras lo esté, el costo es `None`, no 0.

### 22.4 Duración por llamada y totales `None` (la propuesta de 20.14, implementada)

- `src/llm.py` registra por llamada `duration_s` (solo la llamada a la API, sin las esperas
  de reintento) y `error` (clase y código HTTP, sin el mensaje).
- El consolidador, para las corridas con el total de tokens en `None`: conteo de corridas
  con total `None` (fuera de las medias de tokens), llamadas fallidas, y la **suma parcial
  rotulada** con «≥» y «(k de n llamadas)», en columna aparte. Los promedios usan solo corridas
  con total completo. Aviso `tokens_parciales`, distinto de `tokens_no_informados` (ninguna
  llamada informó). La vista lista esas corridas.

### 22.5 Intentos de consulta externa (NVD, AbuseIPDB)

En el piloto se mantiene el **bloqueo con respaldo local**, y **cada consulta que hace una
herramienta queda registrada por corrida**: herramienta, parámetros, si intentó salir a la
red, si fue bloqueada y si el respaldo respondió. Al terminar el piloto, el consolidador
entrega la tabla de intentos por arquitectura, dataset y herramienta. Solo NODEX usa
herramientas: para Gemini directo y el baseline las celdas «no aplican» (no son 0), y «sin
registro» tampoco es 0.

**DECISIÓN PENDIENTE (campaña final):** si NODEX corre con consultas reales o con respaldo
local. Cualquiera de las dos debe declararse en el informe. La tabla del piloto es el
insumo para decidir con datos.

### 22.6 Lanzador y etiqueta de depuración

`python -m src.experimentation.campana`: sin `--ejecutar` solo muestra el plan; con
`--ejecutar --etapa 1` corre UN caso con las tres arquitecturas e informa credencial, modelo
efectivo, fallback, tokens, tiempo, llamadas y errores; con `--etapa 2` sigue con el resto.
Tope de 2 horas por corrida (se mata el árbol de procesos); **tres fallas de infraestructura
seguidas** (503, 429, timeout) detienen la campaña. Los resultados del piloto se consolidan
con la etiqueta **de depuración, no reportable** (también en la vista).

### 22.7 Defecto encontrado al congelar: `arbol_limpio` nunca podía ser True

La primera congelación del piloto (15-oct-2026) registró `arbol_limpio: False` con el árbol
realmente limpio. Causa: `_git()` convertía una salida vacía en `None` (`... or None`), y
`git status --porcelain` de un árbol limpio es justo una salida vacía; la comparación con `""`
fallaba siempre. Es un defecto previo de la congelación (ninguna configuración congelada
anterior pudo marcar el árbol como limpio). Se corrigió: una salida vacía es un resultado
válido y solo un fallo de git da `None`; cuatro pruebas lo cubren (árbol limpio, con cambios,
con archivo sin seguimiento y fuera de un repositorio). Esa primera congelación (huella
`20d936582d27...`) no se usó en ninguna corrida y se descartó; el piloto se congeló de nuevo,
con el mismo nombre, sobre el commit con la corrección.

## 23. Piloto de depuración (15-oct-2026)

**Resultados de DEPURACIÓN: no son reportables.** Desarrollo, N=1, 24 casos (8 de BGL, 8 de
HDFS, 8 de UWF) × 3 arquitecturas = 72 corridas. Configuración congelada
`piloto-flash38-20261015` (huella `8be17560bd44f7a59bf76ebf7bad0b7942b6b4fd3de3997600a764512bacce32`,
commit `fbeeba6`, árbol limpio): `gemini-3.8-flash`, `LLM_SIN_RESPALDO` activo, temperatura 0,
`generateContent`; Gemini directo hereda el mismo modelo.

### 23.1 Resultado operativo

- **72 de 72 corridas completas**; 0 ausentes, 0 fallidas, **0 con fallback**, 0 fallas de
  infraestructura (no se activó la parada de 3 seguidas ni el tope de 2 h).
- Todas las llamadas con `model_version` = `gemini-3.8-flash` (el pedido) y razonamiento
  informado. **Ninguna corrida con total de tokens `None`**: no hubo llamadas fallidas.
- Etapa 1 (`bgl_des_balanceado_0000`, 3 arquitecturas): limpia; se siguió con las 69 restantes.
- Consumo de las 48 corridas con LLM: **158 llamadas** y **≈1,265 M de tokens** (entrada
  1.055.970, salida 55.996, razonamiento 152.904).
- **Estimación del plan vs lo real (un solo dato):** el plan estimó ≈1,139 M de tokens solo con
  lo medido (sin HDFS). Las 32 corridas con LLM de BGL y UWF consumieron 1,166 M (+2,4 %).
  Es una coincidencia con N=1 por celda: no valida la estimación.
- NODEX hizo 5, 6 y 11 llamadas por corrida (BGL 5,1 de media, HDFS 5,0, UWF 6,6).

### 23.2 HDFS aparte: las 16 corridas con LLM (sin medición previa de tokens)

HDFS es **auxiliar (D-7)** y no tenía medición previa. Resultado: NODEX 8 corridas, 40
llamadas, 6.132 / 851 / 2.636 tokens (entrada / salida / razonamiento) y 32 s por corrida;
Gemini directo 8 corridas, 8 llamadas, 1.318 / 339 / 1.097 tokens y 10,5 s por corrida. Total
de las 16: 48 llamadas, **98.983 tokens**, 342 s. Con esto la estimación de HDFS deja de estar
«sin medición» (una sola vez, N=8 por arquitectura).

### 23.3 Intentos de consulta externa (primer dato válido)

NODEX, 24 corridas (el bloqueo y la tabla funcionaron: ver 20.16):

| Dataset | AbuseIPDB: consultas / corridas con intentos | NVD |
|---|---|---|
| BGL | 2 / 2 de 8 | 0 |
| HDFS | 43 / 8 de 8 | 0 |
| UWF | 158 / 8 de 8 | 0 |
| **Total** | **203, todos bloqueados, el respaldo local respondió en el 100 %** | **0** |

NVD **no se consultó nunca** en los 24 casos de NODEX. Gemini directo y el baseline no usan
herramientas (la celda no aplica). **La política para la campaña final sigue PENDIENTE.**

### 23.4 Revisión de la vista «Resultados» (Chrome real, API real)

Chrome sin ventana contra la API real (`/api/resultados`) y la interfaz de producción. Capturas
en `docs/experimentacion/capturas_piloto_20261015/`. Lo que se ve:

- **Banner de no reportable:** visible y en rojo («RESULTADOS DE DEPURACIÓN — NO REPORTABLES»).
- **Integridad:** 72 / 72 / 72 / 0 / 0 / 0, y dos advertencias: la de depuración (alta, roja) y
  «203 · intentos de consulta a NVD/AbuseIPDB bloqueados, con respaldo local» (informativa, azul).
- **Totales `None` y suma parcial:** las columnas existen («Corridas con total None», «Llamadas
  fallidas», «Tokens parciales») y muestran 0, 0 y «—»; **no hubo ninguna corrida real con
  total `None`, así que la suma parcial no se pudo ver con datos reales.** Está cubierta por las
  pruebas, no por este piloto.
- **Tabla de intentos de consulta externa:** visible por arquitectura, dataset y herramienta;
  «—» (no aplica) para Gemini directo y el baseline, 0 medidos para NVD en NODEX.

**Defectos de la vista encontrados al verla (no se corrigieron: el código está congelado):**

1. Las seis tarjetas de integridad no caben en la fila de cinco: «Con fallback de modelo» pasa
   a una segunda fila.
2. Las tablas de consumo y de consultas externas son más anchas que la pantalla (2.477 px contra
   1.026 visibles): las columnas nuevas («Corridas con total None», «Llamadas fallidas»,
   «Tokens parciales») quedan fuera de pantalla hasta desplazarse a la derecha.
3. En la tabla de consultas externas la columna «Nota» es un texto largo que parte las celdas y
   estira las filas de NODEX a ~180 px; la nota debería ir en la descripción de la tabla.
4. La captura del lado derecho de la tabla de consultas (columna «Respondió el respaldo local») no
   se logró por un detalle del script de captura; sus valores están en `consultas_externas.csv`.

### 23.5 Limitaciones y pendientes

- Gemini directo no registra la duración por llamada (su runner no pasa por `src/llm.py`);
  solo hay el tiempo total de su única llamada.
- Los resultados de este piloto no deben citarse como resultados experimentales.
- **PENDIENTES, abiertos:** (1) la política de NVD y AbuseIPDB para la campaña final (consultas
  reales o respaldo local; cualquiera debe declararse en el informe); (2) el presupuesto de la
  campaña con la tabla de precios vigente (`experiments/config/precios_modelo.json` sigue vacía:
  falta fecha, fuente y precios); (3) el formulario ciego de la rúbrica humana (hoy los informes
  no ocultan qué arquitectura los produjo).

## 24. Después del piloto (15-oct-2026)

El piloto se acepta como **validación del flujo, no de acierto**. Esta sección reúne lo que se hizo
a continuación, sin lanzar la campaña final y sin tocar prompts, umbrales ni el código del sistema
evaluado.

### 24.1 Salud estructural del piloto (solo casos de desarrollo)

Módulo `salud_piloto.py`: solo lee lo guardado (salidas, estado crudo, telemetría y
`registros.json` de la consolidación); **no abre `ground_truth/`** y se niega a correr sobre la
partición de evaluación. No mide acierto. Resultado por arquitectura y dataset (8 corridas por
celda). **D2 y D3 usan el estado FINAL** (la salida cruzada con la referencia), el mismo que usan
las métricas; el estado «del lado de la salida» se guarda aparte.

| Arq. | Dataset | JSON válido | Veredicto presente | D2 evaluable / no evaluable / no aplica (con contenido) | D3 evaluable / no evaluable / no aplica (con contenido) | `invalid_evidence_uid_count` > 0 | uids inventados (D2) > 0 | D1 TP / FP / FN / TN |
|---|---|---|---|---|---|---|---|---|
| Baseline | BGL | n/a | 8/8 | 0 / 0 / 8 (0) | 0 / 0 / 8 (0) | n/a | n/a | 0 / 0 / 4 / 4 |
| Baseline | HDFS | n/a | 8/8 | 0 / 0 / 8 (0) | 0 / 0 / 8 (0) | n/a | n/a | 0 / 0 / 3 / 5 |
| Baseline | UWF | n/a | 8/8 | 0 / 0 / 8 (0) | 0 / 0 / 8 (0) | n/a | n/a | 4 / 4 / 0 / 0 |
| Gemini directo | BGL | 8/8 (100 %) | 8/8 | 0 / 0 / 8 (6) | 0 / 0 / 8 (0) | n/a | 0 | 4 / 3 / 0 / 1 |
| Gemini directo | HDFS | 8/8 (100 %) | 8/8 | 0 / 0 / 8 (1) | 0 / 0 / 8 (0) | n/a | 0 | 0 / 1 / 3 / 4 |
| Gemini directo | UWF | 8/8 (100 %) | 8/8 | 4 / 0 / 4 (6) | 2 / 2 / 4 (4) | n/a | 0 | 2 / 2 / 2 / 2 |
| NODEX | BGL | **no medido** | 8/8 | 0 / 0 / 8 (3) | 0 / 0 / 8 (0) | 0 | 0 | 3 / 0 / 1 / 4 |
| NODEX | HDFS | **no medido** | 8/8 | 0 / 0 / 8 (2) | 0 / 0 / 8 (0) | 0 | 0 | 0 / 1 / 3 / 4 |
| NODEX | UWF | **no medido** | 8/8 | 4 / 0 / 4 (8) | 3 / 1 / 4 (6) | 0 | 0 | 3 / 3 / 1 / 1 |

La matriz de confusión de D1 es **solo diagnóstico**, no un resultado. «Con contenido» cuenta salidas
con eventos o técnicas aunque la dimensión no aplique (D2 y D3 no aplican a BGL ni a HDFS).

**Qué se puede y qué no se puede afirmar de «JSON válido».** Para Gemini directo se midió de verdad
(su runner parsea la respuesta). Para NODEX el JSON lo valida `llm_json()` en cada nodo y el lanzador del
piloto **no contaba las respuestas inválidas**: no hay medición directa. Se informa un *proxy* (corrida
completa y con veredicto: 100 %), que **no es lo mismo**. El baseline no usa el modelo.

**Hallazgos (se reportan, no se corrigen):**

1. **D3 «no evaluable» deja afuera los casos en que el sistema no atribuyó ninguna técnica.** En UWF,
   Gemini directo tiene 2 de 4 casos con incidente en D3 «no evaluable» y NODEX 1 de 4: son casos en que
   el sistema no dio ninguna técnica (coinciden con falsos negativos de D1). Hoy esas corridas **salen
   de la métrica en vez de contar como fallo**: una exhaustividad calculada solo sobre las corridas
   evaluables está inflada y premia al sistema que se calla. Es una decisión documentada del adaptador
   («si el sistema no produjo nada que puntuar, la dimensión es `no_evaluable`»), no un error de
   implementación, pero es una decisión que sesga. *Qué cambiaría:* en el evaluador (no en el sistema),
   puntuar la ausencia de atribución en un caso con referencia como fallo (exhaustividad 0 para ese
   caso), o como mínimo **publicar la cobertura** («3 de 4 evaluables») junto a cada cifra. *Qué obligaría
   a repetir:* nada de lo ya corrido; se reevalúan las salidas guardadas, sin llamar al modelo.
2. **Ninguna arquitectura detecta ninguno de los 3 casos anómalos de HDFS** (TP = 0 y FN = 3 en las tres).
   No es un defecto confirmado: HDFS es auxiliar (D-7) y el dato no basta para saber si es un límite de
   los sistemas o del armado de los casos. *Qué haría:* revisar a mano esos 3 casos antes de usar HDFS
   para algo. No obliga a repetir.
3. **El baseline predice «malicioso» en los 8 casos de UWF** (4 falsos positivos): responde otra
   pregunta (ya declarado en 11.6). En BGL y HDFS predice «benigno» en los 16.
4. **Gemini directo sobre-predice en BGL** (7 de 8 «maligno», 3 falsos positivos de 4 negativos) y
   devuelve eventos en BGL y HDFS aunque D2 no aplica (6/8 y 1/8): límite conocido del prompt (20.9).
5. **Cero evidencia inválida** en todas las celdas, tanto por el contador del sistema (NODEX) como por
   los uids inventados que detecta la evaluación en D2.
6. **Para la campaña final conviene medir el JSON de NODEX:** agregar al lanzador el contador de
   respuestas `json_invalido` de `llm_json` (ya existe en la comparación de modelos). Es herramienta,
   no sistema evaluado.

Nada de lo anterior obliga a repetir el piloto.

### 24.2 Política de consultas externas (NVD y AbuseIPDB): PROPUESTA, pendiente de confirmación

**Fracción de las IPs consultadas a AbuseIPDB que no son públicas** (RFC 1918, loopback, link-local,
multicast, IPv6 no global, etc.; un IPv6 global cuenta como público):

| Dataset | Consultas | IPs únicas | No públicas (consultas) | No públicas (IPs únicas) | IPs no públicas que el respaldo puntúa como públicas |
|---|---|---|---|---|---|
| BGL | 2 | 1 | **2 (100 %)** | 1 de 1 | 0 |
| HDFS | 43 | 41 | **43 (100 %)** | 41 de 41 | 0 |
| UWF | 158 | 50 | **61 (38,6 %)** | 15 de 50 (30 %) | **13** |
| **Total** | **203** | | **106 (52,2 %)** | | |

Todas las consultas de BGL y HDFS eran a direcciones privadas, que no tienen reputación pública. En UWF
hubo 23 consultas RFC 1918, 31 IPv6 no global, 6 multicast y 1 loopback.

**Qué contiene exactamente el respaldo local** (leído del código por `analisis_ips.descripcion_del_respaldo`):

- **AbuseIPDB** (`check_ip_reputation`, rama sin servicio): **no tiene fuente, fecha ni cobertura
  declaradas; es una heurística escrita en el código** (viene de la migración del prototipo, 1-sep-2026).
  Una sola regla: si la dirección empieza con `10.`, `192.168.`, `172.16.` o `127.` es privada (score 0,
  «limpio»); **cualquier otra cadena es pública con score 50**, y 50 ≥ `SCORE_SOSPECHOSO` (25) la clasifica como
  **«sospechoso»**. Límites: `172.16.` cubre solo 172.16.x.x (el rango real llega a 172.31); no reconoce IPv6,
  169.254, multicast ni 100.64/10; no distingue una IP pública de otra.
- **NVD** (`query_cve`, catálogo `_CVE_LOCAL`): **sin fuente ni fecha; tres entradas escritas a mano**
  (`openssh`, `apache`, `sql`). Una palabra clave que contenga alguna devuelve su entrada; cualquier otra,
  lista vacía. En el piloto NODEX no consultó NVD nunca.

**Propuesta (a confirmar):** la campaña final usa el **respaldo local**, y el informe declara que **NVD y
AbuseIPDB no forman parte de la medición**. Matices que conviene tener presentes antes de confirmar:

1. **No es «igual para todas las arquitecturas»:** solo NODEX usa herramientas. Gemini directo y el
   baseline no reciben reputación de IP. La declaración correcta es «NODEX recibe un respaldo local fijo;
   las otras no usan herramientas externas».
2. **El respaldo no es neutro:** toda IP pública recibe score 50 («sospechoso») y toda IP privada con
   prefijo conocido, «limpio». NODEX recibe, entonces, una señal de reputación que es una función de la
   forma de la dirección. En BGL y HDFS (100 % privadas) la señal es casi constante; en UWF distingue
   «interna» de «externa». No hay evidencia de que esto empuje las predicciones (en UWF NODEX tuvo 3 falsos
   positivos de 4 negativos), pero tampoco se descartó.
3. **13 IPs no públicas de UWF se puntúan como públicas** por los límites del respaldo (p. ej. 172.28.x.x,
   multicast, fe80::).
4. La alternativa (consultas reales congeladas en una caché, `POLITICA_RECURSOS_EXTERNOS`) daría datos
   reales, pero las IPs privadas seguirían sin reputación y hay que congelar la caché en un paso aparte.

### 24.3 Precios y costos

`experiments/config/precios_modelo.json` (esquema 2.0, con vigencias) para `gemini-3.8-flash`, en USD por
millón de tokens, **la salida incluye el razonamiento**:

| Vigencia | Entrada | Salida (con razonamiento) |
|---|---|---|
| hasta el 31-dic-2026 | 0,75 | 3,75 |
| desde el 1-ene-2027 | 1,50 | 7,50 |

Fuente: <https://ai.google.dev/gemini-api/docs/pricing>, **consultada el 15-oct-2026**. Los precios
coinciden con los indicados por el responsable. **Nota sobre la fecha de la fuente:** el responsable indica
que la página no muestra fecha de actualización; la lectura automática del 15-oct-2026 mostró «Last updated
2026-10-15 UTC». No coinciden: verificar a mano antes de presupuestar.

**Costo real del piloto** (48 corridas con LLM, precios vigentes el 15-oct-2026): **USD 1,5754**
(entrada 1.055.970 × 0,75/M + salida y razonamiento 208.900 × 3,75/M). Por dataset: BGL 0,225, HDFS 0,192, UWF
1,158. Por corrida: BGL 0,011 (Gemini) / 0,017 (NODEX); HDFS 0,006 / 0,018; UWF 0,065 / 0,079.

**Estimación de la campaña final** (BGL 62 + UWF 80 casos, N=3, NODEX y Gemini directo; el baseline no
se presupuesta). **Orden de magnitud, no un presupuesto.** Base: la media de las 8 corridas por celda del
piloto (mejor que una corrida por celda, pero siguen siendo 8 casos de desarrollo):

| Celda | Corridas | Tokens/corrida | Tokens | USD hasta 2026 | USD desde 2027 |
|---|---|---|---|---|---|
| BGL · NODEX | 186 | 7.771 | 1,45 M | 3,19 | 6,38 |
| BGL · Gemini directo | 186 | 5.135 | 0,96 M | 2,04 | 4,08 |
| UWF · NODEX | 240 | 75.119 | 18,03 M | 19,04 | 38,08 |
| UWF · Gemini directo | 240 | 57.711 | 13,85 M | 15,69 | 31,39 |
| **Total** | 852 | | **34,3 M** | **≈ 40** | **≈ 80** |

Con la medición previa de una corrida por celda el total sale 33,4 M de tokens (USD 40,5 / 80,9): coincide
en orden de magnitud. **HDFS aparte** (no está en el subconjunto de evaluación; 100 casos de evaluación en
el manifiesto, N=1, hipotético): ≈ 1,24 M de tokens, USD 2,41 (hasta 2026) o 4,81 (desde 2027). Lo que más
mueve el total es UWF con NODEX (la media de llamadas varió entre 5 y 13) y la fecha de la campaña: **el
precio se duplica el 1-ene-2027.**

### 24.4 Correcciones de la vista «Resultados» (los tres defectos)

Revisadas en Chrome real contra la API real, con mediciones (no solo capturas):

1. **Tarjeta de fallback** en una segunda fila: las seis tarjetas de integridad ahora caben en **una sola
   fila** (medido: 1 fila de 6).
2. **Tablas más anchas que la pantalla:** encabezados que bajan de línea, relleno más ajustado, columnas
   ancla (dataset y arquitectura quedan fijas al desplazarse) y sombras laterales que indican que hay más.
   La tabla de consultas externas **cabe entera** (885 px de 885). La de consumo (18 columnas) sigue siendo
   más ancha que el panel (1.372 px de 885 visibles) y se desplaza con las columnas ancla; no se partió en
   dos tablas para no cambiar su CSV.
3. **Columna «Nota»** de la tabla de consultas: reemplazada por «Estado» (`medido` / `no aplica` / `sin
   registro`); el texto largo pasó a la descripción de la tabla. Las filas de NODEX pasaron de ~185 px a
   ≤ 57 px.

**Error propio detectado al mirar la captura:** una primera versión del arreglo usó `overflow-wrap:
anywhere`, que dejó columnas de **un carácter de ancho** (encabezados y «gemini-3.8-flash» en vertical) aunque
«cabían». Las pruebas de estilo no lo vieron; la captura sí. Se corrigió (los encabezados bajan solo en los
espacios) y una prueba nueva prohíbe `anywhere` y `break-all` en las reglas de tablas. Lección: una prueba
de CSS no sustituye mirar el resultado.

### 24.5 Formulario ciego de la rúbrica humana (D-4)

`rubrica_ciega.py`. Escala 0–3 por criterio (los cinco de la rúbrica), dos evaluadores, 12 casos (6 BGL +
6 UWF, `experiments/subconjuntos/rubrica.json`) × 2 arquitecturas = 24 reportes = 48 evaluaciones.

- **Ciego:** los reportes salen de una plantilla común, se redactan los nombres de arquitecturas y modelos y
  se **audita** que no quede ninguno (si queda, no se arma el paquete). Cada reporte se identifica por su
  posición (R01…R24); la correspondencia con caso y arquitectura está en una clave secreta aparte.
- **Orden aleatorio con semilla registrada:** cada evaluador tiene su orden (`Random(semilla:evaluador)`).
  La semilla va en la clave; en el paquete solo va un compromiso (hash), porque conocerla permitiría
  reconstruir qué reporte es cuál.
- **Evaluadores independientes:** un HTML autocontenido por evaluador con solo sus reportes; exporta un JSON
  propio y no deja exportar con puntajes incompletos. La importación exige un archivo de cada evaluador y
  rechaza puntajes fuera de la escala, repetidos, incompletos o de otro paquete.
- **Concordancia sin kappa:** acuerdo exacto, acuerdo hasta un nivel y diferencia absoluta media (más los
  desacuerdos de 2 niveles o más, listados). Escribe `puntajes.csv` en el formato que ya lee el consolidador.
- **No incluye ninguna salida de la campaña:** recibe los reportes armados; las pruebas usan reportes
  ficticios. No lee `ground_truth/` (los evaluadores deben ver el caso y su referencia: quien arme el paquete
  decide el contexto, y habrá que hacerlo por un camino autorizado).
- **Verificado en Chrome real** con reportes ficticios: abre, rechaza exportar incompleto, se llena con clics,
  conserva las respuestas al recargar, exporta, y la importación desciega y calcula la concordancia. Encontré y
  corregí un defecto: la columna del nivel 3 quedaba fuera de pantalla (ahora los cuatro niveles caben a 1.100 y
  a 420 px).

### 24.6 Archivo del piloto: «piloto, no reportable»

Copia (no mueve) de lo que produjo `piloto-flash38-20261015` a
`experiments/piloto_no_reportable/piloto-flash38-20261015/`, con `MANIFIESTO.json` (config_version, huella
`8be17560…`, commit `fbeeba6`, árbol limpio al congelar, SHA-256 de cada archivo) y `LEEME.txt`: 463 archivos, 4,6 MB,
hashes verificados. Los originales siguen en `experiments/<carpeta>/`.

### 24.7 Para lanzar la campaña final falta

1. **Decisiones tuyas:** la política de NVD y AbuseIPDB (24.2) y si se archiva el piloto en git (24.6).
2. **Decidir qué se hace con D3/D2 «no evaluable»** (hallazgo 1 de 24.1) **antes** de ver resultados de la campaña.
3. **Medir el JSON de NODEX** (contador de `llm_json` en el lanzador).
4. **Congelar un `config_version` nuevo** (el del piloto no se reutiliza) sobre un árbol limpio, con los
   prompts y el código tal como quedarán, y `--verificar-config`.
5. **Confirmar que las particiones de evaluación no se han visto** (evidencia abajo) y que el subconjunto
   `evaluacion` (62 + 80 casos) es el que se corre.
6. **Presupuesto** con la tabla de precios verificada y la fecha prevista de la campaña (el precio se duplica
   el 1-ene-2027).
7. **Rúbrica humana:** dos evaluadores, y un camino autorizado para darles el caso y su referencia.
8. **Tu autorización explícita.**

**Evidencia sobre las particiones de evaluación** (no prueba que nadie las haya abierto a mano): el
subconjunto del piloto es 100 % de desarrollo (0 casos de evaluación); ninguno de los 288 archivos de corridas
menciona un caso de evaluación; no hay cambios sin commitear en `cases/`, `ground_truth/`, `manifests/` ni
`subconjuntos/`; y la referencia solo la lee `evaluacion.py`, que en el piloto abrió solo las de los 24 casos
del subconjunto. **Divulgación:** durante esta preparación se leyeron metadatos de evaluación, no su
contenido: los ids de `rubrica.json` y `evaluacion.json` y los conteos agregados de los manifiestos (para
estimar costos y armar el formulario). No se abrió ningún caso ni referencia de evaluación.


## 25. Preparación de la campaña final con presupuesto de USD 6 (15-oct-2026)

Esta sección fija, **antes de correr nada en la partición de evaluación**, el cambio de alcance y las reglas
que lo acompañan. Nada de lo que sigue usa resultados de la campaña: no existen.

### 25.1 Cambio de alcance (decisión de la usuaria)

| Antes | Ahora | Por qué |
|---|---|---|
| D-2: N = 3 repeticiones en evaluación | **N = 2** para NODEX y Gemini directo; baseline N = 1 (es determinístico) | lo pide el profesor guía |
| Los 142 casos de evaluación de BGL y UWF (subconjunto `evaluacion`) | **40 casos** (`campana_final`): 30 de BGL y 10 de UWF | presupuesto total de **USD 6** (verificaciones, reintentos y márgenes incluidos) |
| Modelo | sin cambio: `gemini-3.8-flash`, respaldo apagado, temperatura 0 | decisión cerrada; no se comparan otros modelos, ni Batch ni Flex |
| HDFS | sin cambio: auxiliar (D-7), **fuera** de la campaña principal, de sus agregados y de su costo | ver 25.5 |

`orquestador.REPETICIONES["evaluacion"]` pasó de 3 a 2 (con prueba). El subconjunto `evaluacion.json` (142 casos) se
conserva sin tocar; la campaña usa `experiments/subconjuntos/campana_final.json`.

### 25.2 Selección de casos (fijada antes de correr)

`src/experimentation/seleccion_campana.py`, semilla registrada **20261015**. Estratificada por **condición** y con
los casos de la rúbrica humana incluidos:

| Dataset / condición | Casos disponibles | Cupo | De la rúbrica | Completados al azar |
|---|---|---|---|---|
| BGL balanceado | 12 | 12 (entra completo) | 3 | 9 |
| BGL natural | 50 | 18 | 3 | 15 |
| UWF visible | 40 | 5 | 3 | 2 |
| UWF sigiloso | 40 | 5 | 3 | 2 |

**Entran los 12 casos de la rúbrica** (6 de BGL y 6 de UWF): `bgl_eva_balanceado_0001/0005/0006`,
`bgl_eva_natural_0002/0016/0031`, `uwf_eva_sigiloso_0013/0018/0024`, `uwf_eva_visible_0004/0027/0028`.

**No se estratifica por veredicto** (positivo/negativo): el módulo solo lee las listas de ids de `evaluacion.json` y
`rubrica.json` y **no abre `ground_truth/` ni `cases/`** (hay una prueba que lo verifica). La proporción de positivos
queda la que declaran los manifiestos por condición (BGL balanceado 50 %, BGL natural 28 %, UWF 50 %) y la
composición real de la muestra no se miró antes de correr. Consecuencia: el número de positivos por celda es una
variable aleatoria; con 10 casos de UWF y ~5 positivos esperados, las estimaciones de exhaustividad y precisión
serán muy anchas (por eso la vista muestra intervalos de Wilson y un aviso de muestras chicas, 25.4).

Plan resultante: NODEX 80 corridas (BGL 60 + UWF 20), Gemini directo 80, baseline 40 = **200 corridas**.

### 25.3 Costo esperado y riesgo frente al presupuesto

Con los costos **medidos en el piloto** (8 corridas por celda, `gemini-3.8-flash`, USD 0,75 por millón de entrada y
3,75 de salida con razonamiento incluido, vigentes hasta el 31-dic-2026):

| Celda | Costo por corrida: mínimo / media / máximo (USD) | Tiempo medio / máximo |
|---|---|---|
| NODEX · BGL | 0,0131 / 0,0172 / 0,0224 | 39 s / 49 s |
| Gemini directo · BGL | 0,0048 / 0,0110 / 0,0156 | 18 s / 26 s |
| NODEX · UWF | 0,0652 / 0,0793 / 0,1361 | 59 s / 101 s |
| Gemini directo · UWF | 0,0522 / 0,0654 / 0,0866 | 51 s / 78 s |

| Plan | Corridas con modelo | Costo mín. / media / máx. (USD) | Simulación p5 – p95 (máx.) | P(> 5,00) | P(> 6,00) | Horas (media – máx.) |
|---|---|---|---|---|---|---|
| **N = 2 · BGL 30 + UWF 10** | 160 | 3,42 / **4,58** / 6,73 | 4,39 – 4,78 (5,21) | 0,08 % | 0 % | 1,6 – 2,2 |
| N = 3 · BGL 20 + UWF 8 | 168 | 3,89 / 5,16 / 7,62 | 4,96 – 5,38 (5,75) | 90 % | 0 % | 1,7 – 2,4 |

Lectura: el «máximo» de 6,73 suma el peor caso observado de **todas** las corridas a la vez (no es esperable). El
costo esperado de N = 2 es **USD 4,58**, con un margen de **USD 1,42** frente a los 6 y de USD 0,42 frente al tope de
gasto de 5,00. **N = 3 con menos casos tiene más riesgo**: su costo esperado (5,16) ya supera el tope de 5,00, que
lo detendría antes de terminar con ~90 % de probabilidad. UWF explica el 63 % del costo del plan elegido (son corridas
de ~300 eventos). Límites de la estimación: 8 observaciones por celda; el remuestreo no puede superar lo ya observado y
subestima las colas; los casos de evaluación pueden ser más grandes que los de desarrollo; el modo «sin reputación
externa» cambia el comportamiento de NODEX respecto del piloto. Por eso el tope de gasto se evalúa **antes de cada
corrida** con el máximo observado de su celda (25.6) y se recalcula desde la telemetría guardada.

### 25.4 Enmiendas a la evaluación y a la vista (todas antes de la campaña)

- **D2/D3 — la omisión cuenta (regla `v2-omision-cuenta`, 15-oct-2026, commit `3c8c289`).** En el piloto, los casos con
  incidente en que el sistema no atribuyó ninguna técnica salían de la métrica como «no evaluables» y la
  exhaustividad quedaba calculada solo donde el sistema habló: inflada y favorable al que se calla. Ahora, con
  corrida válida y completa y referencia existente, no entregar eventos/técnicas es una omisión (exhaustividad 0,
  precisión indefinida) y cuenta. Reevaluando las salidas del piloto sin llamar al modelo: D1 y D2 no cambian; la
  exhaustividad micro de D3 baja de 0,500 a 0,167 en Gemini directo (2 omisiones) y de 0,250 a 0,167 en NODEX (1).
  Cada cifra D2/D3 lleva su cobertura («k de n evaluables»).
- **Consistencia entre repeticiones** (tabla nueva, sección 11.1): concordancia de veredicto por caso (mismo
  veredicto en todas las repeticiones, con intervalo de Wilson) y variación de tokens y de tiempo
  ((máx. − mín.) / media por caso). Temperatura 0 no garantiza respuestas idénticas.
- **Intervalos de Wilson al 95 %** para exactitud, precisión y exhaustividad de D1, con **aviso destacado de
  muestras chicas** en la vista. Wilson supone observaciones independientes y las repeticiones del mismo caso no lo
  son: los intervalos son además optimistas (el aviso lo dice).
- **JSON válido de NODEX:** el lanzador envuelve `llm_json` y guarda por corrida cuántas respuestas fueron inválidas
  (`<run_id>.llm_json.json`; son las inválidas **tras** el reintento interno de `llm_json`). La salud estructural
  informa el porcentaje real de NODEX donde antes decía «no medido».
- **Bug corregido en el lanzador:** `informe_de_corrida` leía siempre la repetición 1; con N = 2 habría mezclado la
  telemetría de la repetición 2 con la 1.

### 25.5 HDFS: auxiliar y amenaza a la validez

HDFS queda **fuera** de la campaña principal, de sus agregados y de su costo (D-7). Si se corre algo, se reporta aparte
y rotulado **«auxiliar / validación técnica»**. La razón de validez: `HDFS_2k.log` trae **una línea por bloque**, la
etiqueta de anomalía de HDFS depende de **secuencias completas por bloque** que no están en el archivo, y en el piloto
**ninguna arquitectura detectó los 3 casos anómalos**. Una cifra de detección sobre HDFS no mide la capacidad del
sistema sino la información disponible: **amenaza a la validez**, no un resultado. Si al final sobra presupuesto, se
**propondrá** una muestra pequeña de HDFS aparte; **no se ejecuta sin autorización**.

### 25.6 Tope de gasto acumulado de USD 5,00 (lanzador)

`campana.py` calcula el gasto desde los tokens **medidos** (telemetría guardada) y la tabla de precios vigente ese
día (el razonamiento se factura como salida). Antes de **cada** corrida: gasto acumulado + costo **máximo observado**
de la celda de la corrida siguiente (el mayor entre lo medido en la campaña y el piloto de referencia, `--config-referencia`)
no puede superar el tope; si lo superaría, se detiene (**código 5**), de forma **reanudable** (las corridas guardadas
no se repiten; el gasto se recalcula, no hay contador aparte que perder). Se revisa también después de cada corrida.
Una corrida fallida sin tokens deja un costo **parcial** (un piso) que se informa aparte. Sin precio vigente, no se
lanza nada. El gasto acumulado se imprime por corrida y queda por etapa en el informe y en `gasto.json`. Se
mantienen **3 fallas de infraestructura seguidas** (código 4) y **2 h por corrida**. Etapas por dataset
(`--dataset bgl` y luego `--dataset uwf`). Pruebas con 20 defectos reintroducidos a propósito, todos detectados.
Los USD 5,00 dejan USD 1,00 de margen para verificaciones y reintentos dentro de los USD 6.

### 25.7 Modo «sin reputación externa» (NODEX)

Modo opt-in `REPUTACION_SIN_ENRIQUECIMIENTO` (apagado por omisión; congelado como parámetro): `corroborar_ips` no
consulta nada ni usa la caché y devuelve `fuente: sin_reputacion` y `score: None`, de modo que ninguna IP recibe
puntaje. El registro de consultas lo distingue (`sin_reputacion`) de un respaldo local. **Declaración propuesta para
el informe:** *«NODEX se evaluó sin enriquecimiento de reputación externa.»* El diff está pendiente de aprobación.

### 25.8 Lecturas de metadatos de evaluación y declaración sobre inspección manual

- **Lo que leí yo (Claude)** durante esta preparación: solo **ids** (`evaluacion.json`, `rubrica.json`,
  `campana_final.json`) y **conteos agregados** de los manifiestos (casos, prevalencia efectiva, positivos por
  condición). No abrí ningún caso ni referencia de la partición de evaluación, y no lo hace ningún código de esta
  sección.
- **Declaración de la usuaria (15-oct-2026):** nadie del equipo abrió casos de la partición de evaluación a mano.
  Se registra como declaración de la usuaria; no es verificable desde el repositorio.
- **Precisión necesaria:** los archivos `rubrica.json` y `evaluacion.json` se generaron el 4–14-oct con
  `subconjuntos.py`, que **sí lee la etiqueta de referencia (no el contenido) de los casos de evaluación** para
  estratificar la rúbrica y contar positivos por condición. Es una lectura previa, de código y de las etiquetas, hecha antes
  de que existiera cualquier salida de las arquitecturas; no es una inspección manual. `seleccion_campana.py`
  (la selección de 25.2) no abre `ground_truth/`.
- **Declaración propuesta para el informe:** *«Las particiones de evaluación no fueron inspeccionadas manualmente
  antes de la campaña.»* (con la precisión anterior sobre la preselección por etiquetas).

### 25.9 Pendiente para lanzar (no se lanza nada sin tu autorización explícita)

1. Aprobar el diff del modo «sin reputación externa» (`src/tools/reputation.py`, `src/config.py`).
2. Verificación mínima NODEX (1 caso de BGL y 1 de UWF de **desarrollo**, no reportable) con la configuración nueva.
3. Congelar el `config_version` de la campaña sobre un árbol limpio y `--verificar-config`.
4. Plan en seco final y tu autorización explícita.
5. Rúbrica humana: dos evaluadores y un camino autorizado para darles el caso y su referencia.
