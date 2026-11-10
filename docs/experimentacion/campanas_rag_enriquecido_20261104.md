# NODEX ? tres campa?as con RAG enriquecido, 4 de noviembre de 2026

Las tres repeticiones se completaron secuencialmente: **36 an?lisis v?lidos, cero casos fallidos y 36 reportes**. Cada caso tuvo una copia nueva del mismo snapshot. Los originales de R1?R3, el corpus y el snapshot congelado conservaron sus hashes. No se calcularon m?tricas D1?D4 ni se ejecutaron evaluaciones de calidad.

| Elemento | R1 enriquecida | R2 enriquecida | R3 enriquecida |
|---|---|---|---|
| Identificador | enriquecido-12casos-r1-20261104 | enriquecido-12casos-r2-20261104 | enriquecido-12casos-r3-20261104 |
| Snapshot restaurado | S?: 12 copias independientes | S?: 12 copias independientes | S?: 12 copias independientes |
| Estado inicial verificado | S?: 30 hist?ricos + 697 MITRE; errores/historial vac?os | S?: 30 hist?ricos + 697 MITRE; errores/historial vac?os | S?: 30 hist?ricos + 697 MITRE; errores/historial vac?os |
| Casos procesados | 12 | 12 | 12 |
| Casos completados | 12 | 12 | 12 |
| Casos fallidos | 0 | 0 | 0 |
| Consultas RAG realizadas | 6 | 7 | 7 |
| Recuperaciones de patrones hist?ricos | 18 | 21 | 21 |
| Reportes generados | 12 | 12 | 12 |
| Extracci?n verificada | S?; sin archivos requeridos faltantes | S?; sin archivos requeridos faltantes | S?; sin archivos requeridos faltantes |
| Ruta de resultados | [extracted_data/enriquecido-12casos-r1-20261104](../../extracted_data/enriquecido-12casos-r1-20261104/README.md) | [extracted_data/enriquecido-12casos-r2-20261104](../../extracted_data/enriquecido-12casos-r2-20261104/README.md) | [extracted_data/enriquecido-12casos-r3-20261104](../../extracted_data/enriquecido-12casos-r3-20261104/README.md) |
| ZIP generado | [enriquecido-12casos-r1-20261104.zip](../../extracted_data/enriquecido-12casos-r1-20261104.zip) | [enriquecido-12casos-r2-20261104.zip](../../extracted_data/enriquecido-12casos-r2-20261104.zip) | [enriquecido-12casos-r3-20261104.zip](../../extracted_data/enriquecido-12casos-r3-20261104.zip) |

?Recuperaciones? cuenta documentos hist?ricos devueltos, incluidas repeticiones de un mismo ID; no significa casos hist?ricos distintos ni demuestra influencia en el razonamiento. Las carpetas mantienen el esquema original de extracci?n; `rag_usage/` es una extensi?n separada. Las predicciones originales se conservan byte a byte y sus proyecciones mantienen valores, orden, duplicados, listas vac?as, ausencia y null. No se aplic? una nueva normalizaci?n MITRE.

**Configuraci?n y aislamiento.** El c?digo funcional, agentes, plantillas de prompts, routers, herramientas, clasificaci?n, l?mites y generaci?n coinciden con los hashes y par?metros congelados de la condici?n original. El modelo solicitado y el efectivo devuelto en las 200 llamadas observadas fue `gemini-3.8-flash`, temperatura 0.0, sin modelo de respaldo. Se conservaron el modo sin reputaci?n externa y el bloqueo NVD con respaldo local registrado.

Se mantuvieron `all-MiniLM-L6-v2`, revisi?n `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, dimensi?n 384, top-k 3, piso de patrones 0,55 y piso ATT&CK 0,42. El snapshot contiene 30 documentos hist?ricos y 697 MITRE: 727 documentos y embeddings. Los cambios de implementaci?n est?n limitados a nuevos scripts de orquestaci?n, identificaci?n y observaci?n; los archivos funcionales originales no se editaron. Los tiempos medidos incluyen el costo de esa observaci?n; no se descont? ni corrigi?.

Las 36 copias iniciales coincidieron con todos los archivos del maestro. `attack_patterns` comenz? con los 30 hist?ricos congelados, `attack_techniques` con 697 y `error_memory`/`host_history` con cero. Las copias de trabajo se descartaron al terminar cada caso; no se reutilizaron memorias entre casos o repeticiones. El maestro nunca se abri? con la API de Chroma durante la campa?a.

Snapshot inicial, SHA-256 del inventario can?nico:

`f8f1ce20d47021aef6e4fa0f621e7a2aff1337c46f7e6e225f6e1ec072b9a63c`

La evidencia individual est? en `experiments/ejecucion/<identificador>/<run_id>.isolation.json` y en la copia correspondiente de `originals/execution/` de cada extracci?n. `rag_usage/initial_state.json` enlaza los 12 casos con esas comprobaciones.

**Uso observado del RAG.** No se forz? ninguna consulta. Se observaron 20 solicitudes naturales y 60 devoluciones de documentos hist?ricos. La observaci?n de env?o comprueba el documento JSON completo dentro de los argumentos originales de `generate_content`, conservando los mismos argumentos y el mismo objeto de respuesta. Las referencias finales se detectan como coincidencias literales de identificadores fuera de los metadatos de candidatos; no son un an?lisis sem?ntico ni una atribuci?n causal.

| Observaci?n | R1 | R2 | R3 |
|---|---:|---:|---:|
| Llamadas al SDK Gemini | 66 | 67 | 67 |
| Llamadas al SDK con error | 0 | 0 | 0 |
| Casos con recuperaci?n hist?rica | 6 | 7 | 7 |
| Casos con documentos hist?ricos presentes en el payload al LLM | 6 | 7 | 7 |
| Documentos hist?ricos en payload, sumados por caso | 18 | 21 | 21 |
| Casos con IDs hist?ricos literales en la salida final | 2 | 2 | 4 |
| Empates observados dentro del top-k nativo | 0 | 0 | 0 |

`rag_usage/queries.jsonl` registra cada solicitud; `retrieved_documents.jsonl` conserva ID nativo, tipo de conocimiento, procedencia, puntuaciones y selecci?n por memoria; `llm_delivery.jsonl` registra presencia del documento en el payload y respuesta del proveedor; `retrieval_summary.jsonl` separa recuperaci?n, entrega y referencias literales finales. Estas observaciones no permiten certificar que el modelo atendi? o us? un documento en su razonamiento.

**Integridad y auditor?a de las seis campa?as.** Se contrastaron los mismos 12 `case_id` y su orden en las seis carpetas; las entradas y ground truth fueron id?nticos por SHA-256. Hay 72 `run_id` distintos entre ambas condiciones. Las tres enriquecidas usan un ?nico estado inicial. Se preservaron 1.685 archivos protegidos, sin cambios. La verificaci?n estricta rechazaba constantes no v?lidas de JSON como NaN/Infinity; todos los JSONL la superaron. Cada archivo dentro de cada ZIP coincide byte a byte con la carpeta entregada.

| Verificaci?n | R1 | R2 | R3 |
|---|---:|---:|---:|
| Originales copiados y verificados | 398 | 398 | 398 |
| Proyecciones contrastadas con su puntero JSON original | 4561 | 4568 | 4570 |
| Archivos JSONL con sintaxis estricta v?lida | 47 | 47 | 47 |
| Filas JSONL v?lidas, incluidos originales | 4891 | 4912 | 4914 |
| Archivos del ZIP contrastados byte a byte | 456 | 456 | 456 |
| Tama?o del ZIP en bytes | 5934067 | 5948553 | 5951348 |

SHA-256 de los ZIP:

- `enriquecido-12casos-r1-20261104.zip`: `42545bb374aadd008ef35a642a7f25453caa867ccdb873f9217bb66f2f8fa069`
- `enriquecido-12casos-r2-20261104.zip`: `89f921bf57bcbedceeeda27f9ea63e7efb09a974e49037aef84019282baf39a9`
- `enriquecido-12casos-r3-20261104.zip`: `ed44cc33a56123425f826da173278661eb36b38953b994f71972c4fe1b91bd9c`

**Diferencia auxiliar del entorno.** No se afirma identidad absoluta de todo el inventario instalado. El runtime de la aplicaci?n actualiz? cinco copias auxiliares respecto del registro original:

| Copia de paquete del runtime | Registro original | Actual |
|---|---|---|
| artifact_tool_v2 | 2.8.106 | 2.8.119 |
| pillow | 12.3.0 | 13.0.0 |
| pycparser | 3.11 | 3.12 |
| python-dateutil | 2.9.0.post0 | 3.0.0 |
| setuptools | 84.1.0 | 84.2.1 |

Las cuatro ?ltimas copias actualizadas no se resuelven en la ruta efectiva: los m?dulos se importan desde las versiones originales del `.venv` del proyecto. `artifact_tool` no forma parte de NODEX ni se importa en estos procesos. Python coincide exactamente con R1 y los dem?s paquetes del inventario coinciden; en particular se mantuvieron las versiones del SDK, Chroma, embeddings y LangGraph. La diferencia queda registrada en `compatibility.json`, `environment.json` y la auditor?a; no se presenta como un entorno f?sicamente id?ntico.

**Incidente preliminar conservado.** Mi primera adaptaci?n esperaba seis argumentos donde el lanzador original entrega siete, incluida la partici?n. Doce procesos terminaron en el parser CLI antes de iniciar el worker, NODEX o el SDK: **cero inferencias y cero llamadas al LLM**. Se conservaron ?ntegramente sus registros, fallos y extracci?n parcial en `experiments/ejecucion/enriquecido-campanas-20261104/prelaunch_failure_20261104/`; su `incident.json` tambi?n est? copiado en los tres paquetes.

Se corrigi? el contrato a siete argumentos, se a?adi? una prueba espec?fica y un bloqueo ante futuros fallos previos al arranque. Los an?lisis v?lidos usan IDs distintos bajo el espacio determinista `rag30-validated-launch-v1`. Ninguna respuesta del modelo se sustituy? ni ning?n an?lisis de NODEX se ejecut? dos veces. Los doce errores preliminares se identifican como fallos de lanzamiento, fuera de las 36 inferencias experimentales; no se ocultaron ni se mezclaron con ellas.

**Limitaciones conservadas.** Once casos hist?ricos BGL comparten firmas gen?ricas entre clases; los 15 BGL tienen cobertura de parsing declarada cero con el c?digo de referencia. Los hist?ricos UWF son episodios sigilosos de 3?6 conexiones, sin `campaign_id` que certifique independencia entre campa?as reales. No se cambi? el corpus para resolver esas limitaciones. No se observaron empates nativos dentro de los top-k de estas campa?as, pero no se consultaron resultados fuera del top-k y permanece la limitaci?n previa de desempate inestable. Los metadatos ausentes y la influencia causal en el razonamiento no se inventan.

**Evidencia y procedimiento.**

- [Auditor?a conjunta de las seis campa?as](../../experiments/ejecucion/enriquecido-campanas-20261104/joint_audit.json).
- [Verificaci?n final de modelos, archivos, proyecciones, JSONL y ZIP](../../experiments/ejecucion/enriquecido-campanas-20261104/final_verification.json).
- [Incidente previo a la inferencia y ubicaci?n de la evidencia preservada](../../experiments/ejecucion/enriquecido-campanas-20261104/prelaunch_failure_20261104/incident.json).
- [Lanzador secuencial](../../tools/run_enriched_campaign.py), [observaci?n transparente](../../tools/enriched_observation.py) y [extracci?n y auditor?a](../../tools/export_enriched_campaign.py).
- [Siete pruebas de contrato, identidad, integridad y observaci?n aprobadas](../../tests/experimentation/test_enriched_campaign.py). La prueba de transparencia con SDK simulado no hizo llamadas al proveedor.

Para comprobar una extracci?n sin inferencia: `python tools/export_enriched_campaign.py --verify extracted_data/enriquecido-12casos-r1-20261104` (adaptar R2/R3). Cada ZIP incluye los scripts en `procedure/`, el notebook de inspecci?n y las fuentes/casos/referencias necesarios para cargar las mismas proyecciones en Google Colab. El c?lculo y la normalizaci?n de D1?D4 quedan para esa etapa posterior.
