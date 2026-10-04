# Hallazgos sobre los datasets (Fase 2)

Todo lo de este documento se obtuvo **midiendo los archivos**: hashes,
conteos y lectura de metadatos. No se ejecutó NODEX, ni el agente único, ni
el baseline, ni la suite de pruebas, ni se hizo ninguna llamada a un
modelo.

Hay un hallazgo que condiciona la campaña completa (§1) y uno que cambia lo
que la Fase 3 tenía que preparar (§4). Los dos están medidos y son
verificables con los comandos que se indican.

## 1. `HDFS_2k.log` no puede sustentar detección a nivel de bloque

**Medición.** Las 2 000 líneas del archivo mencionan 2 200 bloques
distintos, y la relación entre bloques y líneas es:

| Líneas que tiene el bloque | Bloques |
|---|---|
| 1 | 2 194 |
| 2 | 6 |

Promedio: **1,00 líneas por bloque**. De los 69 bloques etiquetados
`Anomaly`, **68 tienen exactamente una línea**.

**Por qué importa.** La etiqueta de anomalía de HDFS, tal como la definen
Loghub y la literatura que la usa (DeepLog y derivados), es una propiedad
de la **secuencia completa de eventos de un bloque**: un bloque es anómalo
porque su secuencia se desvía de la normal — por ejemplo recibe
`Receiving block` y nunca `Received block`, o su replicación sigue un orden
atípico. Con un solo evento por bloque, la secuencia que define la etiqueta
**no está en el archivo**.

Se puede ver directamente en las plantillas de mensaje. Las seis más
frecuentes entre los bloques anómalos y entre los normales son las mismas:

```
Receiving block <blk> src: /<ip> dest: /<ip>
BLOCK* NameSystem.addStoredBlock: blockMap updated: <ip> is added to <blk>
BLOCK* NameSystem.delete: <blk> is added to invalidSet of <ip>
Received block <blk> of size <n> from /<ip>
PacketResponder <n> for block <blk> terminating
<ip> Served block <blk> to /<ip>
```

Son todas operaciones normales de HDFS. Un bloque anómalo y uno normal son,
en este archivo, una línea indistinguible tomada de la misma población de
plantillas.

**Consecuencia.** La tarea, planteada sobre este archivo, **no es resoluble
por ningún sistema** — ni por NODEX, ni por el agente único, ni por el
baseline de reglas, ni por un humano experto. Esto explica los resultados
de la fase 6 anterior (recall 0,10 en balanceado; 0,00 a prevalencia 3,1%
con 6 falsos positivos) sin apelar a ninguna falla del modelo: es un
problema de **validez de la medición**, no de desempeño.

La indicación de la usuaria (3-oct-2026) de que el rendimiento en HDFS "no
debe ser un bloqueante" es compatible con esto, pero por una razón distinta
a la supuesta: no es una limitación que haya que tolerar, es una medición
que no mide lo que dice medir.

**Qué hacer con esto es una decisión académica, no técnica.** Queda
registrada como D-7 (§6). Las tres salidas posibles, sin recomendación
encubierta:

1. Usar una muestra de HDFS donde los bloques tengan su secuencia completa
   (`HDFS_100k`, o el log completo filtrado por bloque). Exige descargar un
   dataset nuevo, que requiere autorización.
2. Declarar HDFS `no_aplica` para la dimensión de detección y conservarlo
   solo como caso de heterogeneidad de formato y de consumo, que sí mide
   algo real.
3. Reportar la dimensión de detección de HDFS **acompañada de esta
   limitación**, explicitando que el resultado acota la dificultad de la
   tarea y no la capacidad del sistema.

Lo que **no** es defendible es reportar el recall de HDFS como medida del
desempeño de NODEX sin esta aclaración.

Reproducible con:

```bash
python -m src.experimentation.datasets.preparar   # escribe el manifiesto
# el conteo líneas/bloque está en experiments/manifests/hdfs.json
```

## 2. El 13,3% de las líneas de HDFS menciona más de un bloque

**Medición** sobre `HDFS_2k.log`:

| `blk_` por línea | Líneas |
|---|---|
| 1 | 1 734 |
| 2 | 263 |
| 9 | 1 |
| 100 | 2 |

266 líneas (13,3%) mencionan dos o más. Las dos líneas con 100 son
`BLOCK* ask <ip> to delete <blk> <blk> ...`.

El generador anterior usaba `re.search`, que devuelve solo la primera
coincidencia, así que atribuía esas líneas a un único bloque y perdía la
asociación con el resto.

**Corrección aplicada.** La unidad de agrupación de HDFS no es el bloque
sino el **componente conexo** del grafo bipartito bloque–línea: dos bloques
quedan unidos si comparten una línea. Así ninguna línea pertenece a dos
grupos y, por lo tanto, no puede duplicarse entre dos casos ni entre las
dos particiones.

Resultado sobre `HDFS_2k.log`: **1 994 componentes** — 1 991 de un bloque,
uno de 9 bloques y dos de 100. 69 componentes contienen al menos un bloque
anómalo (3,46% frente al 3,14% a nivel de bloque). Solo **un** componente
es mixto (anómalo y normal juntos), y es uno de los de 100 bloques.

## 3. La prevalencia "natural" de BGL depende de la unidad elegida

BGL trae la etiqueta embebida como primer token de cada línea: `-` si no
hay alerta, un código (`KERNDTLB`, `KERNSTOR`, `APPSEV`, …) si la hay.
Sobre 2 000 líneas hay **143 de alerta (7,15%)** de 12 tipos, agrupadas en
**45 ráfagas contiguas**, la mayor de 60 líneas.

Como la etiqueta es por línea y no hay identificador de transacción, la
unidad de agrupación es una ventana contigua y disjunta de líneas. Y la
prevalencia depende del tamaño de esa ventana:

| Ventana | Grupos | Con ≥1 alerta |
|---|---|---|
| 10 | 200 | 40 (20%) |
| 20 | 100 | 28 (28%) |
| 25 | 80 | 24 (30%) |
| 50 | 40 | 17 (42%) |
| 100 | 20 | 12 (60%) |

Se fijó **20 líneas**: es el mayor tamaño que todavía deja 100 grupos
disjuntos, y la cantidad de grupos es lo que acota cuántos casos se pueden
armar sin reutilizar ninguno.

**Consecuencia para el informe.** La prevalencia de BGL que hay que citar
es 28% **a nivel de ventana de 20 líneas**, no 7,15%. Son dos cosas
distintas y confundirlas haría incomparable cualquier métrica. El tamaño de
ventana queda escrito en `experiments/manifests/bgl.json`.

## 4. UWF-ZeekDataFall22 trae las etiquetas que la Fase 3 iba a pedir a mano

El dataset llegó al repositorio en el commit `b0fe5de` de Felipe Bravo
Romo, como **13 archivos Parquet comprimidos con snappy** (44 862 135
bytes), uno por semana, en
`data/logs/UWF-ZeekDataFall22-parquet/`. Son **700 340 registros** de
`conn.log` de Zeek, escritos por Spark 3.3.0.

Esquema leído del footer Parquet (25 columnas): `community_id`,
`conn_state`, `duration`, `history`, `src_ip_zeek`, `src_port_zeek`,
`dest_ip_zeek`, `dest_port_zeek`, `local_orig`, `local_resp`,
`missed_bytes`, `orig_bytes`, `orig_ip_bytes`, `orig_pkts`, `proto`,
`resp_bytes`, `resp_ip_bytes`, `resp_pkts`, `service`, `ts`, `uid`,
`datetime`, **`label_tactic`**, **`label_technique`**, **`label_binary`**.

Esto es mejor de lo que el plan asumía. Las tres referencias que la Fase 3
iba a tener que conseguir por anotación humana **vienen en el dataset**:

| Dimensión | Referencia | De dónde sale |
|---|---|---|
| D1 detección (seguridad) | `MALICIOUS` / `BENIGN` | `label_binary` |
| D2 reconstrucción | `core_event_uids` | `uid` de los registros maliciosos del caso |
| D3 MITRE | tácticas y técnicas | `label_tactic`, `label_technique` |

`uid` es el identificador de conexión de Zeek: es exactamente la clave de
matching exacto que el protocolo exige para D2, y existe. D2 y D3 pasan de
`referencia_pendiente` a derivables del dataset, sin anotación humana y sin
tocar la prohibición de usar la salida de NODEX como referencia.

Queda una sola dimensión que sigue necesitando una persona: **D4 (reporte)**,
que se evalúa con rúbrica humana porque el plan prohíbe reportes gold.

NODEX, además, **ya tiene el enricher de este dataset escrito**:
`src/preprocessing/enrichers/zeek.py` reconoce las columnas de Zeek, mueve
`conn_state` a `event_outcome`, y en la línea 27 declara y retira
`label_tactic`, `label_technique` y `label_binary` del evento para que no
lleguen al prompt. Espera el log en **CSV o JSON**, no en Parquet.

### 4.1 Lo benigno y lo malicioso están en semanas distintas

Esto condiciona cómo se pueden armar los casos. Leyendo las estadísticas
min/max de las columnas de etiqueta en el footer de cada shard:

| Semana | Registros | `label_binary` |
|---|---|---|
| 2021-12-12 → 12-19 | 20 745 | solo `False` |
| 2021-12-19 → 12-26 | 97 807 | solo `False` |
| 2021-12-26 → 01-02 | 98 290 | solo `False` |
| 2022-01-02 → 01-09 | 133 497 | solo `False` |
| 2022-08-28 → 09-04 | 47 227 | `Duplicate`…`True` |
| 2022-09-04 → 09-11 | 1 762 | solo `True` |
| 2022-09-11 → 09-18 | 16 871 | solo `True` |
| 2022-09-18 → 09-25 | 284 004 | solo `True` |
| 2022-09-25 → 10-02 | 66 | `Duplicate`…`True` |
| 2022-10-02 → 10-09 | 5 | `Duplicate`…`True` |
| 2022-10-09 → 10-16 | 39 | solo `True` |
| 2022-10-16 → 10-23 | 22 | `Duplicate`…`True` |
| 2022-10-23 → 10-30 | 5 | `Duplicate`…`True` |

Es decir: **350 339 registros puramente benignos en diciembre de 2021** y
**~302 676 puramente maliciosos entre agosto y octubre de 2022**, más
47 325 en shards mixtos. No hay ningún shard con tráfico benigno y malicioso
naturalmente entremezclado en cantidades comparables.

Consecuencia: un caso que sea "una ventana temporal de un shard" es 100%
benigno o 100% malicioso. Eso no plantea el problema que NODEX debe
resolver (encontrar lo relevante dentro de un volumen de ruido) y además
permitiría acertar leyendo la fecha.

Para construir casos realistas hay que **componer**: insertar registros
maliciosos de los shards de 2022 sobre un fondo benigno de los de 2021. Es
una práctica estándar para armar conjuntos de evaluación etiquetados, pero
es una construcción sintética y **debe declararse como tal en la tesis**,
no presentarse como tráfico capturado tal cual. Además rompe la coherencia
temporal (fondo de diciembre 2021 con ataque de septiembre 2022), así que
exige una decisión explícita sobre rebasar los timestamps — y si se
rebasan, la transformación tiene que quedar en la procedencia del caso.

Queda como **D-8** (§6).

### 4.2 `label_binary` tiene un tercer valor: `Duplicate`

Cinco shards tienen `Duplicate` como mínimo de `label_binary`, y
`label_technique` también lo trae. No es `True` ni `False`: es un defecto de
curaduría del dataset.

Esos registros **no son clasificables** ni como benignos ni como maliciosos.
El protocolo ya tiene el estado para eso (`no_evaluable` / exclusión), pero
hay que decidir si los registros `Duplicate` se excluyen de los casos o se
dejan en el fondo y se excluyen solo del ground truth. Queda como **D-9**.

Hay un detalle a no heredar: `_ETIQUETAS_BENIGNAS` en
[zeek.py:30](../../src/preprocessing/enrichers/zeek.py#L30) no incluye
`"duplicate"`, así que el canal de ground truth interno de NODEX trataría
un `Duplicate` como **malicioso**. El evaluador experimental no debe usar
esa derivación; usa la suya, construida en la Fase 3.

### 4.3 Falta un motor de Parquet

Ninguno de los 7 decoders de NODEX lee Parquet, y el entorno no tiene con
qué leerlo: `pyarrow`, `fastparquet`, `polars` y `duckdb` no están
instalados ni figuran entre los 141 paquetes de `constraints.txt`. `pandas`
sí está fijado (3.0.6) pero `read_parquet` necesita uno de esos motores.

Los conteos y el esquema de este documento se obtuvieron parseando el
footer Parquet con biblioteca estándar, que alcanza para los metadatos pero
**no para leer los datos de las columnas**. Convertir el dataset a CSV
—que es lo que el enricher Zeek espera— requiere instalar un motor, y una
instalación necesita autorización explícita. Queda pendiente como la única
acción bloqueada de esta fase.

## 5. Inventario con hashes

Hashes SHA-256 completos en
`experiments/manifests/inventario_fuentes.json`. Primeros 16 caracteres:

| Archivo | Bytes | Líneas | SHA-256 (16) |
|---|---|---|---|
| `data/logs/HDFS_2k.log` | 287 848 | 2 000 | `7c967000980c086e` |
| `data/logs/BGL_2k.log` | 317 150 | 2 000 | `2a819ea540909db6` |
| `data/labels/hdfs_anomaly_label_2k.csv` | 71 307 | 2 201 | `beea376284b45dcc` |
| UWF (13 Parquet) | 44 862 135 | — | ver manifiesto |

Las etiquetas de HDFS cuadran exactamente con el log: 2 200 bloques
etiquetados, 2 200 presentes, ninguno huérfano en ninguna dirección. 69
`Anomaly` y 2 131 `Normal` (3,14%).

## 6. Decisiones tomadas el 3 de octubre de 2026

Las cuatro que abrió esta fase quedaron resueltas, más dos pendientes desde
la Fase 1.

| # | Decisión tomada |
|---|---|
| D-4 | Rúbrica de reporte **0–3 por criterio**, con **2 evaluadores** y la concordancia entre ellos reportada. Cuatro niveles anclados sobre los 5 criterios ya definidos. |
| D-6 | **12 casos por dataset principal** reciben la rúbrica humana: 12 de BGL + 12 de UWF = 24 reportes. Submuestra estratificada por veredicto esperado y por condición, con la semilla registrada. |
| D-7 | HDFS **no** se usa como métrica principal de desempeño. Queda como dataset **auxiliar / de validación técnica**, porque el archivo no contiene la secuencia completa por bloque. BGL y UWF son los datasets principales de evaluación, salvo que más adelante se incorpore un HDFS completo que preserve las secuencias por `blk_id`. |
| D-8 | Los casos de UWF se **componen**: registros benignos y maliciosos mezclados, con trazabilidad a los registros originales y declarando en metadatos que son escenarios sintéticos controlados. Los timestamps del incidente se **rebasan** a la ventana del fondo conservando los deltas internos, con el offset registrado por caso para que el `ts` original sea recuperable. |
| D-9 | Los registros con `label_binary == "Duplicate"` se **excluyen** del conjunto experimental, y la cantidad descartada queda en el manifiesto. |
| D-10 | El techo de 2 000 líneas **se mantiene durante el piloto** y se reevalúa después de verificar el pipeline experimental. No bloquea la continuación. |

### 6.1 Costo medido de la decisión D-9

Excluir los `Duplicate` tiene una consecuencia que conviene tener presente
al interpretar D3. Las filas `Duplicate` son la **segunda atribución de
táctica** de una conexión que ya aparece con su táctica principal: el par
más frecuente es `Defense Evasion / T1548` junto con
`Duplicate / Privilege Escalation` (3 397 casos).

Medido sobre la conversión:

| | |
|---|---|
| Filas excluidas por `Duplicate` | 3 068 |
| `uid` que desaparecen del conjunto | **0** |
| `uid` que pierden una táctica secundaria | 2 899 |
| `uid` que conservan más de una táctica | 33 |

Ningún evento se pierde: la conexión permanece a través de su fila gemela.
Lo que se pierde es la táctica secundaria de 2 899 conexiones, así que la
referencia de D3 para esas queda con una sola táctica. Es una referencia
**conservadora**: puede subcontar un acierto, nunca inventarlo.

## 7. Conversión de UWF y casos compuestos

Ejecutado el 3-oct-2026 con `pyarrow==25.0.1` en `.venv-preparacion`, con la
autorización que exigía no tocar las dependencias de producción.
`requirements.txt` y `constraints.txt` quedaron sin modificar, y `pyarrow`
solo lo importa `src/experimentation/datasets/uwf.py`, de forma diferida.

### 7.1 Conversión Parquet → CSV

| | |
|---|---|
| Filas en los 13 Parquet | 700 340 |
| Excluidas (`Duplicate`) | 3 068 |
| Colapsadas al deduplicar por `uid` | 36 899 |
| **Eventos emitidos** | **660 373** |
| &nbsp;&nbsp;benignos | 350 339 |
| &nbsp;&nbsp;maliciosos | 310 034 |

La deduplicación por `uid` es correcta y no pierde eventos. Se verificó
comparando los 9 campos que identifican el flujo (`ts`, IPs, puertos,
`proto`, duración, bytes) en las 37 423 filas que comparten `uid`:
**cero colisiones reales**. Todas son la misma conexión etiquetada más de
una vez, así que se emite un evento y las etiquetas se **unen**.

Salida en dos árboles separados físicamente:

- `data/experimentacion/uwf_csv/eventos/` — 22 columnas de Zeek. Es lo único
  que puede llegar a una arquitectura o al RAG.
- `data/experimentacion/uwf_csv/etiquetas/` — `uid`, `label_binary`,
  `label_tactic`, `label_technique`. Solo para evaluadores.

La separación se verificó **sobre los artefactos**, no sobre el código: la
cabecera de los 13 CSV de eventos es exactamente la allowlist de 22
columnas, y ninguno contiene los valores de etiqueta.

Los CSV (138 MB) no están versionados; sí lo están sus SHA-256 en
`experiments/manifests/uwf_conversion.json` y las instrucciones de
regeneración en `regenerar_uwf.md`.

### 7.2 Casos compuestos

La unidad de agrupación es el **incidente**: una ráfaga de conexiones
maliciosas del mismo origen y la misma táctica, con huecos de a lo más 60 s.
Resultan **349 incidentes** (103 en desarrollo, 246 en evaluación), de 3 a
60 conexiones y de a lo más 600 s de duración.

Un caso tiene 300 registros: un tramo contiguo de tráfico benigno de
dic-2021, con un incidente de 2022 insertado en el 70% central de su
ventana temporal. Dos condiciones, ambas con prevalencia de casos 0,5 —
así que lo que varía no es el balance sino **cuán enterrado está el
incidente**:

| Partición | Condición | n | Incidente / caso |
|---|---|---|---|
| desarrollo | visible | 12 | 9,3% – 20,0% (media 18,2%) |
| desarrollo | sigiloso | 12 | 1,00% – 1,67% (media 1,33%) |
| evaluación | visible | 40 | 8,0% – 20,0% (media 18,3%) |
| evaluación | sigiloso | 40 | 1,00% – 1,67% (media 1,18%) |

104 casos, 31 200 registros, **ningún `uid` repetido ni entre casos ni
dentro de un caso** — condición necesaria para que `uid` sirva como clave
de matching exacto de la reconstrucción.

Tácticas cubiertas por las referencias de los 52 casos positivos:
`Reconnaissance` 28, `Resource Development` 12, `Discovery` 10,
`Execution` 2, `Initial Access` 1, `Defense Evasion` 1. Y 8 técnicas:
T1592, T1590, T1587, T1046, T1548, T1566, T1203, T1059.

Esa diversidad no salió sola. En una primera versión **51 de los 52 casos
positivos eran `Reconnaissance`**, porque la selección tomaba los
incidentes por orden de identificador y el pool está dominado por esa
táctica (227 de 246 en evaluación). D3 habría medido una sola táctica. Se
corrigió seleccionando por rondas, empezando por las tácticas más escasas.

### 7.3 Dos defectos propios encontrados y corregidos

Quedan anotados porque los dos habrían sesgado resultados en silencio:

1. **Semilla derivada de `hash()`.** El hash de un `str` en Python cambia
   entre procesos por `PYTHONHASHSEED`, así que la generación no habría
   sido reproducible: cada corrida habría dado casos distintos. Se cambió a
   `zlib.crc32`, en `preparar.py` y en `uwf_casos.py`.
2. **Incidente desbordado por el final.** Un incidente de 37 minutos no
   cabía en la ventana de fondo y terminaba siendo los últimos registros
   del caso: una pista posicional que permitiría acertar sin analizar nada.
   Lo detectó la verificación de artefactos, no una prueba. Se corrigió
   exigiendo que la ventana de fondo abarque el incidente con margen, y
   limitando la duración del incidente a 600 s, lo que descarta **1 de 350**
   (los demás duran 0,4 s en la mediana y 46 s en el percentil 90).

## 8. Lo que sigue pendiente

| # | Decisión | Fase que la necesita |
|---|---|---|
| D-2 | Número de repeticiones `N` por caso | 7 |
| D-3 | Umbrales de aceptación por dimensión | 5 |
| D-5 | Comparación externa: experimental o bibliográfica | 9 |

## 9. Lo que esta fase **no** verificó

1. Que los casos generados pasen por el preprocesamiento de NODEX. Pasar un
   caso por `preprocesar()` es ejecutar NODEX sobre un caso de prueba, que
   el protocolo prohíbe sin autorización. La segmentación de los casos se
   validó contra el archivo original, no contra el pipeline. Para UWF esto
   importa más que para los otros dos: el enricher Zeek existe y está
   escrito para este dataset, pero **no se comprobó corriéndolo**.
2. Que las pruebas de `tests/experimentation/` pasen. Son 7 archivos
   escritos y revisados estáticamente; no se ejecutaron.
3. Que las etiquetas de HDFS, BGL y UWF sean correctas. Se tomaron tal como
   vienen; verificar la curaduría de los datasets está fuera de alcance.
4. Que los casos sean "difíciles" o "realistas" en algún sentido medido. Se
   verificó que el incidente no esté en los extremos y que no haya rastro
   de etiquetas, pero si una proporción maliciosa del 1% es detectable o no
   es justamente lo que el experimento tiene que responder.
