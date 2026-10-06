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
| 5 — Implementar los evaluadores externos | PREPARADA_SIN_EJECUTAR | Sí (5-oct-2026) | `src/experimentation/evaluators/` (8 módulos); fixtures con la aritmética hecha a mano (`tests/experimentation/fixtures/`); 1 archivo de pruebas (escrito, sin ejecutar) | (se registra abajo) | D-12: qué coeficiente de concordancia informar |
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
