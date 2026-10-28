# NODEX — Inventario y procedimiento de extracción de datos experimentales

**Fecha de exportación:** 21 de octubre de 2026.  
**Estado:** inventario y procedimiento propuesto; scripts y exportaciones de datos aún no implementados.  
**Origen:** revisión del repositorio y conversación con la persona responsable del proyecto. Las disponibilidades indicadas corresponden a esa revisión previa; exportar este documento no implica una nueva auditoría de los datos.

## Contexto para continuar en otro chat

Estoy desarrollando la evaluación experimental de NODEX, un sistema multiagente basado en LLM para analizar logs e incidentes de ciberseguridad, como parte de mi Proyecto de Título.

Necesito identificar, localizar y posteriormente extraer los datos originales de forma organizada, trazable y reproducible para realizar personalmente la evaluación.

Los cuatro escenarios de interés son:

- **E1:** detección de anomalías.
- **E2:** reconstrucción de incidentes.
- **E3:** identificación MITRE ATT&CK.
- **E4:** generación de reportes.

BGL balanceado/natural y UWF visible/sigiloso son **condiciones de los datasets**, no los cuatro escenarios E1–E4. Esta distinción corrige una interpretación inicial de la conversación.

### Restricciones que deben mantenerse

- No ejecutar NODEX, el agente, el modelo ni las pruebas.
- No ejecutar evaluadores ni consolidaciones.
- No calcular Precision, Recall, F1, TP, FP, FN, TN ni otras métricas experimentales.
- No comparar predicciones con ground truth ni clasificar respuestas como correctas o incorrectas.
- No interpretar incidentes, hacer evaluaciones semánticas, gráficos ni conclusiones sobre desempeño.
- No modificar las fuentes ni alterar etiquetas, contenido, valores faltantes, orden o duplicados.
- Mantener separados ground truth, entradas y resultados. Nunca incorporar referencias reservadas al proceso de inferencia.
- **No implementar todavía los scripts.** Primero revisar este inventario y comprender el procedimiento. La solicitud actual solo autoriza exportar este documento a Markdown.

La definición de criterios de evaluación, el matching, el cálculo de métricas y la interpretación de resultados estarán a mi cargo.

### Trabajo realizado hasta este punto

Se revisaron carpetas, configuración, código de persistencia y estructura de artefactos existentes. No se ejecutaron NODEX, pruebas, evaluadores ni consolidaciones. No se calcularon métricas ni se compararon predicciones con referencias. No se implementaron scripts de extracción ni se generaron exportaciones de datos.

La información necesaria está principalmente en **experiments/**. Es necesario conservar tanto las salidas normalizadas como los archivos **raw**, porque estos últimos contienen detalles que no pasan al JSON resumido.

## A. Inventario de información

Todas las rutas siguientes parten de esta carpeta:

~~~text
C:\Users\felip\OneDrive\Documentos\GitHub\ProyectoTituloNodex\
~~~

Los marcadores significan:

- **&lt;dataset&gt;:** bgl, uwf o hdfs.
- **&lt;particion&gt;:** desarrollo o evaluacion.
- **&lt;case_id&gt;:** identificador del caso.
- **&lt;run_id&gt;:** identificador de la ejecución.
- **&lt;variante&gt;:** carpeta nodex, gemini_externo o baseline.
- **&lt;config_version&gt;:** configuración registrada en el archivo de ejecución.

| Escenario | Información | Ruta exacta relativa | Formato | Disponible |
|---|---|---|---|---|
| E1–E4 | Entrada exacta preparada para BGL | `experiments\cases\bgl\<particion>\<case_id>.log` | LOG | Sí |
| E1–E4 | Entrada exacta preparada para UWF | `experiments\cases\uwf\<particion>\<case_id>.csv` | CSV | Sí |
| E1–E4 | Entrada auxiliar HDFS | `experiments\cases\hdfs\<particion>\<case_id>.log` | LOG | Sí |
| E1–E4 | Metadatos, procedencia y grupos del caso | `experiments\cases\<dataset>\<particion>\<case_id>.json` | JSON | Sí |
| E1 | Etiqueta preparada y etiqueta original conservada | `experiments\ground_truth\<dataset>\<particion>\<case_id>.json` | JSON | Sí |
| E1 | Clasificación del sistema e identidad de ejecución | `experiments\<variante>\<dataset>\<run_id>.json` | JSON | Sí |
| E1 | Veredictos booleanos conservados por NODEX | `experiments\nodex\<dataset>\raw\<run_id>.raw.json` | JSON | Sí |
| E1 | BGL original, con etiqueta por línea | `data\logs\BGL_2k.log` | LOG | Sí |
| E1 | HDFS original y etiquetas por bloque | `data\logs\HDFS_2k.log y data\labels\hdfs_anomaly_label_2k.csv` | LOG / CSV | Sí |
| E1 / E3 | UWF original, anterior a la preparación | `data\logs\UWF-ZeekDataFall22-parquet\<semana>\<archivo>.snappy.parquet` | Parquet | Sí, 13 archivos; lectura directa de sus columnas pendiente |
| E1 / E3 | CSV intermedios de eventos y etiquetas UWF | `data\experimentacion\uwf_csv\eventos\*.csv y data\experimentacion\uwf_csv\etiquetas\*.csv` | CSV | No están en esta copia |
| E2 | Referencia de eventos núcleo | `experiments\ground_truth\uwf\<particion>\<case_id>.json` | JSON | Sí, campo core_event_uids |
| E2 | Reconstrucción normalizada y orden temporal | `experiments\<variante>\<dataset>\<run_id>.json` | JSON | Sí, según variante y contenido |
| E2 | Descripciones, evidencia, entidades observadas y reconstrucción detallada | `experiments\nodex\<dataset>\raw\<run_id>.raw.json` | JSON | Sí; algunos campos pueden estar vacíos |
| E3 | Referencias MITRE del caso | `experiments\ground_truth\uwf\<particion>\<case_id>.json` | JSON | Sí, según el caso |
| E3 | Técnicas atribuidas y evidencia | `experiments\<variante>\<dataset>\<run_id>.json` | JSON | Sí, según variante y contenido |
| E3 | Justificaciones y candidatos recuperados por RAG | `experiments\nodex\<dataset>\raw\<run_id>.raw.json` | JSON | Sí, según el contenido |
| E4 | Texto del reporte experimental | `experiments\<variante>\<dataset>\<run_id>.json` | JSON con texto Markdown | Sí para NODEX y Gemini directo |
| E4 | Secciones, contexto, evidencias y referencias conservadas | `experiments\<variante>\<dataset>\raw\<run_id>.raw.json` | JSON | Sí, con distinto detalle por variante |
| Transversal | Consumo, duración y llamadas | `experiments\telemetry\<dataset>\<run_id>.json` | JSON | Sí |
| Transversal | Registro de consultas externas | `experiments\telemetry\<dataset>\<run_id>.consultas_externas.json` | JSON | Sí en ejecuciones del lanzador |
| Transversal | Conteo de respuestas JSON de NODEX | `experiments\telemetry\<dataset>\<run_id>.llm_json.json` | JSON | Sí en las ejecuciones instrumentadas |
| Transversal | Consola y errores | `experiments\ejecucion\<config_version>\<run_id>.stdout.txt y <run_id>.stderr.txt` | TXT | Sí en el lanzador |
| Transversal | Gasto registrado e informes | `experiments\ejecucion\<config_version>\gasto.json e informe_etapa*.json` | JSON | Sí, según configuración |
| Trazabilidad | Configuración, commit, parámetros y hashes registrados | `experiments\config\config_<config_version>.json` | JSON | Sí para las tres configuraciones existentes |
| Trazabilidad | Inventarios y preparación de datasets | `experiments\manifests\*.json` | JSON | Sí |
| Trazabilidad | Selección de casos | `experiments\subconjuntos\*.json` | JSON | Sí |

En BGL y HDFS, las referencias de reconstrucción y MITRE están marcadas como **no_aplica**. Esto no debe utilizarse para eliminar contenido que el sistema haya guardado: la extracción debe conservarlo junto con ese estado.

Como inventario de archivos —sin evaluar su contenido— se encontraron:

| Configuración | NODEX | Gemini directo | Baseline |
|---|---:|---:|---:|
| campana-flash38-sinrep-20261015 | 40 | 40 | 40 |
| piloto-flash38-20261015 | 24 | 24 | 24 |
| verificacion-sinrep-20261015 | 2 | — | — |

También existen:

- **experiments\piloto_no_reportable\piloto-flash38-20261015\:** copia archivada del piloto, con manifiesto. Debe identificarse como copia, sin deduplicar ni contar sus archivos como nuevas ejecuciones.
- **experiments\metrics\piloto-flash38-20261015\:** resultados derivados ya calculados. No se proponen como fuente de la extracción original.
- **results\:** salidas históricas con esquemas diferentes. Conviene mantenerlas en un conjunto separado.

## B. Relación entre archivos y variantes

La clave de una ejecución es:

~~~text
case_id + dataset + arquitectura + repeticion + config_version
~~~

Esos campos aparecen en las cabeceras de las salidas, los estados crudos y la telemetría. El nombre del archivo contiene un **run_id**, pero la configuración debe recuperarse del contenido, no deducirse del sufijo.

### Ejemplo concreto revisado

~~~text
Caso:
bgl_eva_balanceado_0009

Ejecución:
bgl_eva_balanceado_0009__nodex__r1__45002a05

Configuración:
campana-flash38-sinrep-20261015
~~~

| Pieza | Archivo |
|---|---|
| Entrada | `experiments\cases\bgl\evaluacion\bgl_eva_balanceado_0009.log` |
| Metadatos del caso | `experiments\cases\bgl\evaluacion\bgl_eva_balanceado_0009.json` |
| Referencia reservada | `experiments\ground_truth\bgl\evaluacion\bgl_eva_balanceado_0009.json` |
| Salida | `experiments\nodex\bgl\bgl_eva_balanceado_0009__nodex__r1__45002a05.json` |
| Estado crudo | `experiments\nodex\bgl\raw\bgl_eva_balanceado_0009__nodex__r1__45002a05.raw.json` |
| Telemetría | `experiments\telemetry\bgl\bgl_eva_balanceado_0009__nodex__r1__45002a05.json` |
| Configuración | `experiments\config\config_campana-flash38-sinrep-20261015.json` |

### Procedencia por registro

Está en los metadatos del caso:

~~~text
procedencia[].indice_en_caso
procedencia[].archivo_origen
procedencia[].linea_original
procedencia[].grupo
procedencia[].uid
~~~

Hay dos distinciones esenciales:

1. **event_id** identifica un evento reconstruido por el sistema. En la salida normalizada aparece como **reconstructed_events[].uid**.
2. **evidence_uids** contiene identificadores de los logs citados. En UWF corresponden a los UID de Zeek. No son intercambiables con event_id.

El código documenta esta diferencia en **src\experimentation\adapters\extraccion.py**, alrededor de las líneas 184–238.

En BGL y HDFS, procedencia[].uid puede ser null: deben conservarse el archivo, la línea original y el grupo. Los identificadores sintéticos del catálogo de evidencia no deben presentarse como identificadores originales del dataset.

### Variantes

| Variante | Campo arquitectura | Carpeta |
|---|---|---|
| NODEX completo | nodex_multiagente | `experiments\nodex\` |
| LLM independiente, pseudo-ablación | gemini_externo | `experiments\gemini_externo\` |
| Baseline de reglas | baseline_reglas | `experiments\baseline\` |
| Otra implementación de agente único | agente_unico | `experiments\single_agent\, sin salidas encontradas` |

**gemini_externo y agente_unico son identificadores distintos; no deben fusionarse durante la exportación.**

Las salidas de distintas campañas comparten carpetas. Deben distinguirse mediante config_version, arquitectura y repeticion, además de case_id.

## C. Procedimiento de extracción propuesto

La primera operación sería **copiar los archivos originales sin modificar sus bytes** y generar su manifiesto. Las tablas serían productos adicionales; nunca sustituirían a los originales.

### E1. Detección

| Origen | Campos que recuperar | Salida recomendada |
|---|---|---|
| Metadatos del caso | case_id, dataset, tipo_deteccion, particion, archivo_contenido, procedencia, grupos, notas | cases.jsonl y provenance.csv |
| Archivo de entrada | Contenido completo, sin retirar columnas ni normalizar saltos de línea | Copia original |
| Ground truth | etiqueta_deteccion, etiqueta_original, estado_dimension, anotacion | detection/ground_truth.jsonl |
| Salida | Identidad completa, salida.classification, ejecucion | detection/predictions.csv y JSONL |
| Estado crudo | hay_anomalia, hay_incidente, confianza | Campos separados en la exportación de predicciones |

Se conservarían tanto tipo_deteccion como los veredictos originales. No se traduciría MALICIOUS a otra etiqueta ni se construirían columnas de acierto.

Para etiquetas originales por registro:

- **BGL:** copiar BGL_2k.log; recuperar el primer token de cada línea conservando su número original.
- **HDFS:** copiar el CSV y conservar literalmente BlockId y Label.
- **UWF:** copiar los Parquet. Una lectura adicional podría exportar uid, label_binary, label_tactic y label_technique, conservando archivo e índice de fila.

Las columnas UWF anteriores están declaradas en **src\experimentation\datasets\uwf.py**, alrededor de la línea 51. No se leyeron directamente sus valores desde Parquet en esta revisión.

**No debe reutilizarse el conversor de preparación para una extracción literal:** ese conversor excluye registros Duplicate, agrupa UID y combina etiquetas. El extractor propuesto conservaría todas las filas originales.

### E2. Reconstrucción

Se mantendrían separados referencia y predicción:

| Origen | Campos | Salida |
|---|---|---|
| Ground truth UWF | case_id, core_event_uids, estado_dimension, anotacion | reconstruction/reference.jsonl |
| Estado crudo | eventos_reconstruidos[]: event_id, evidence_uids, timestamp, event_type, description, confidence, cuando existan | reconstruction/predictions.jsonl |
| Salida normalizada | reconstructed_events, temporal_sequence | Copia y proyección separada |
| Estado crudo NODEX | evidencia_logs, resumen_logs.entidades, resumen_logs.cronologia | reconstruction/evidence.jsonl |
| Estado crudo NODEX | secuencia_temporal, historial_planes | JSON, preservando orden y versiones |

El catálogo evidencia_logs puede contener UID, número de registro, líneas inicial/final, timestamp, IP de origen/destino, servicio, proceso, categoría, mensaje y otros campos.

**La cronología del preprocesamiento y la reconstrucción del sistema deben mantenerse diferenciadas.** También se conservarían los resultados archivados dentro de historial_planes[].resultados_asociados, identificando su versión.

No se generarían intersecciones, listas de omisiones ni etiquetas de eventos correctos o inventados.

### E3. MITRE ATT&CK

| Origen | Campos | Salida |
|---|---|---|
| Ground truth | referencias_mitre[]: nivel, id, nombre, evidence_uids; además estado_mitre_por_nivel | mitre/ground_truth.jsonl |
| Estado crudo | tecnicas_atribuidas[]: technique_id, technique_name, evidence_uids, justification, confidence, cuando exista | mitre/attributions.jsonl |
| Salida normalizada | salida.mitre.tactics, salida.mitre.techniques | Proyección JSONL separada |
| Estado crudo / salida | tecnicas_mitre, salida._meta.mitre_candidates | mitre/retrieved_candidates.jsonl |

Las justificaciones se conservan en el raw, aunque no aparezcan en la lista normalizada.

Los candidatos del RAG deben exportarse como **candidatos recuperados**, separados de las técnicas atribuidas. Se mantendrían literalmente los identificadores y nombres existentes, sin completar códigos TA..., técnicas ni subtécnicas mediante consultas externas.

### E4. Reportes

Se recuperaría literalmente:

~~~text
salida.report.summary
~~~

Ese campo contiene el reporte experimental ya ensamblado. Puede exportarse a:

~~~text
reports/generated/<run_id>.md
~~~

Además, se conservarían las secciones del estado crudo en JSON:

~~~text
diagnostico
evaluacion_auditor
comandos_mitigacion
cves_encontrados
contexto_rag
tecnicas_mitre
tecnicas_atribuidas
evidencia_logs
~~~

Así se preservan las evidencias, URLs, referencias y estructura que realmente existan. No se reescribiría el reporte ni se añadirían citas.

El PDF de la interfaz se genera bajo demanda. **No se encontraron PDF persistidos ni data\historial.db en esta copia.** Generar ahora un PDF produciría un documento nuevo; no sería recuperar un archivo original existente.

### Información transversal de ejecución

| Información solicitada | Fuente/campo recuperable | Disponibilidad real |
|---|---|---|
| Inicio registrado | Salida: ejecucion.iniciado_utc | Sí en las ejecuciones actuales |
| Finalización exacta | terminado_utc | No aparece en las salidas revisadas |
| Duración de ejecución | Telemetría: execution_time | Sí |
| Duración del runner | tiempo_total_runner_s | Según variante |
| Duración del proceso lanzado | Informes de etapa: informes[].segundos | Sí |
| Duración por llamada NODEX | llm_calls[].duration_s | Sí |
| Duración por agente o herramienta | Sin campo completo asociado | No disponible como medición por agente |
| Llamadas al LLM | llm_call_count | Sí |
| Tokens | input_tokens, output_tokens, reasoning_tokens, total_tokens y detalle llm_calls[] | Sí, conservando valores null |
| Modelo utilizado | llm_calls[].model, model_version, modelos_efectivos | Sí |
| Iteraciones/correcciones | replan_count, intentos_correccion, historial_planes | Sí en NODEX |
| Uso de nodos y herramientas | historial_ejecucion[] | Sí en NODEX |
| RAG | Entradas del historial, contexto_rag, tecnicas_mitre | Hay trazas; no un contador completo dedicado |
| Consultas externas | consultas_externas.json: herramienta, parámetros, orden, fuente y bloqueo | Sí en el lanzador |
| Gasto ya registrado | gasto.json y sección gasto de los informes | Acumulado/por etapa |
| Costo individual facturado por ejecución | Sin campo directo encontrado | No disponible |
| RAM, CPU, GPU | Sin telemetría encontrada | No disponible |

Estos tiempos corresponden a mediciones distintas y se exportarían con sus nombres originales. No se calcularía finalización sumando inicio y duración, ni costo individual restando acumulados.

## D. Información faltante y límites de recuperación

- **CSV intermedios UWF ausentes.** procedencia[].archivo_origen puede apuntar a ellos. Esa ruta se conservaría literalmente y se marcaría como fuente no encontrada. linea_original corresponde al CSV intermedio; no debe aplicarse directamente como número de fila del Parquet.
- **Timestamps UWF transformados previamente.** Los casos conservan offset_rebase_segundos y otros metadatos de composición. La extracción mantendría los timestamps del caso y los del Parquet por separado, sin deshacer el desplazamiento.
- **Respuesta literal del proveedor por cada llamada.** Los archivos raw contienen el estado final preservado, que ya puede haber pasado por validaciones. No constituyen un archivo completo de todas las respuestas originales del LLM, incluidas las descartadas.
- **Entidades por evento reconstruido.** El adaptador actual deja vacío reconstructed_events[].entities. Hay entidades en entradas y catálogos de evidencia, pero no debe rellenarse retrospectivamente esa lista.
- **Relaciones causales.** Hay secuencias temporales y referencias de evidencia; no se encontró un grafo causal explícito.
- **Tácticas y subtécnicas.** UWF conserva referencias de táctica y técnica; las subtécnicas de referencia están marcadas como no_aplica. La salida D11 no produce una lista independiente de tácticas. Se exportaría lo almacenado, sin completar niveles.
- **Reporte de referencia.** No existe un reporte gold. Tampoco se encontraron resultados de rúbrica en experiments\rubrica\.
- **Finalización y recursos.** No pueden recuperarse mediciones exactas de finalización, CPU, RAM, GPU o duración por agente si no fueron registradas.
- **Flujo manual.** No se encontraron artefactos manual-*. Además, su código escribe iniciado_utc al registrar el resultado después del análisis: ese campo no debe asumirse como inicio real en futuras exportaciones manuales.
- **Resultados manuales de la interfaz.** Su consolidación se calcula temporalmente; no deja automáticamente un conjunto permanente de CSV.

## E. Propuesta mínima de implementación — pendiente de revisión

Se propone **un único script independiente**, por ejemplo tools/export_experimental_data.py, con secciones seleccionables. No importaría agentes, adaptadores, validadores, evaluadores ni consolidadores: leería JSON, CSV y archivos binarios directamente.

La organización podría ser:

~~~text
extracted_data/<export_id>/
├── manifest.csv
├── manifest.json
├── extraction.json
├── originals/
│   ├── inputs/
│   ├── ground_truth/
│   ├── predictions/
│   ├── telemetry/
│   └── configuration/
├── detection/
├── reconstruction/
├── mitre/
├── reports/generated/
└── performance/
~~~

Solo se crearían productos con datos recuperados. Los errores se registrarían cuando existan.

Cada archivo original tendría en el manifiesto:

~~~text
source_path
source_filename
export_path
sha256_source
sha256_copy
size_bytes
case_id
dataset
particion
run_id
arquitectura
repeticion
config_version
~~~

Cada registro proyectado añadiría source_json_pointer o número de fila, e índice del elemento dentro del array. extraction.json conservaría versión y SHA-256 del extractor, argumentos, fecha de extracción y reglas de conversión.

Para CSV:

- Las estructuras anidadas se conservarían como JSON en celdas o en JSONL complementario.
- Se distinguirían campo ausente, null, lista vacía y cadena vacía.
- Se mantendrían duplicados, orden y etiquetas.
- Los originales permanecerían como respaldo exacto.

Los siguientes serían **comandos propuestos, todavía no implementados ni ejecutados**:

~~~powershell
python tools/export_experimental_data.py --config-version campana-flash38-sinrep-20261015 --section all --output extracted_data/campana_r1

python tools/export_experimental_data.py --config-version piloto-flash38-20261015 --section reports --output extracted_data/piloto_reportes
~~~

La copia y extracción de JSON/CSV puede hacerse con la biblioteca estándar de Python. La lectura opcional de Parquet requeriría pyarrow, ya declarado en requirements-experimentacion.txt; no sería necesario instalarlo para copiar y preservar los Parquet originales.

## Estado de continuidad

Este documento reúne el inventario y el procedimiento para su revisión. **La implementación y la extracción de datos siguen pendientes.** Exportar este Markdown no autoriza a ejecutar NODEX, las pruebas, los evaluadores ni la propuesta de scripts.
