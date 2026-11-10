# rag_enriquecido_30_v1

Corpus histórico de desarrollo y snapshot aislado para la futura condición RAG enriquecido. No se ejecutaron agentes LLM, la campaña oficial de 12 casos ni métricas D1–D4. Los resultados R1–R3 y las bases originales permanecen intactos.

| Dataset | Normales | Anómalos | Total |
|---|---:|---:|---:|
| BGL | 8 | 7 | 15 |
| UWF | 7 | 8 | 15 |
| Total | 15 | 15 | 30 |

Hay **30 documentos históricos y 30 embeddings nuevos**, uno por caso. El snapshot contiene además las **697 técnicas MITRE originales**, con sus embeddings: **727 documentos y 727 embeddings de dimensión 384**. `error_memory` y `host_history` están vacías.

## Evidencia y límites

- [Independencia](manifests/validacion_independencia.json): 2.435 registros distintos, 2.135 UIDs UWF, cero registros, UIDs, eventos o ventanas compartidos. Se excluyó toda la partición de evaluación de 142 casos, además de comprobar las selecciones idénticas de R1–R3 y sus 12 entradas oficiales.
- [Poblado](validation/validacion_poblado.json): contenidos, IDs, metadatos, embeddings, idempotencia, conservación de MITRE, código original y restauración del snapshot.
- [Recuperación](validation/pruebas_recuperacion.json): consultas reales a `LongTermMemory.retrieve_examples()` y `tool_consultar_rag`, sin sustituirlas por mocks. Incluye firmas originales y variantes calculadas al reservar un registro.
- [Calidad de las firmas](validation/validacion_firmas.json): **limitación del preprocesamiento existente**. Los 15 BGL tienen cobertura de parsing declarada cero; 11 comparten una firma genérica, incluso entre clases diferentes. Hay 15 firmas distintas para 30 casos. La recuperación contractual funciona, pero no garantiza distinguir normal/anómalo ni devolver el propio caso dentro del top 3. No se corrigió el decoder ni se modificaron firmas o umbrales para favorecer resultados.
- [Comparación después de restaurar](validation/comparacion_recuperacion_restaurada.json): 39 de 60 consultas cambiaron IDs dentro de empates de firma y similitud idénticas. El contenido y los vectores permanecieron iguales; el RAG existente no garantiza un desempate estable.
- [Resumen de validación](validation/resumen_validacion.md): cantidades reales y alcance de las pruebas.

Para UWF se reconstruyeron los 349 episodios originales y su partición de 103 episodios de desarrollo, con el algoritmo y semilla originales. Se excluyeron por completo las semanas fuente de incidentes de los 12 oficiales: 28-ago–4-sep, 11–18-sep y 18–25-sep de 2022. Quedaron 13 candidatos válidos; se seleccionaron 8 episodios completos de 3–6 conexiones. **No hay incidentes visibles de al menos 20 conexiones que superen esta exclusión adicional**. Los episodios elegidos proceden de 4–11-sep y 25-sep–2-oct de 2022; no se desplazaron timestamps ni se mezclaron con fondos sintéticos. Los 7 normales provienen de ventanas existentes de desarrollo.

UWF no aporta un `campaign_id`. La exclusión de semanas, episodios, UIDs y ventanas es verificable; **no prueba independencia entre campañas reales no anotadas**. Las limitaciones de diversidad UWF y discriminación BGL deben acompañar cualquier análisis posterior.

## Fuentes y representación

Los originales están en `data/logs/BGL_2k.log` y `data/logs/UWF-ZeekDataFall22-parquet/`. Los manifiestos originales están en `experiments/manifests/`. Las entradas y metadatos de evaluación se usan solo para excluir; no se interpretan ni incorporan sus ground truth o predicciones. Se calculan hashes de archivos protegidos para comprobar que permanecen intactos.

La conversión UWF reutiliza `datasets/uwf.py`: excluye `Duplicate`, conserva la unión de etiquetas por UID y reproduce exactamente los SHA-256 de eventos y etiquetas registrados en `uwf_conversion.json`. Los CSV intermedios se regeneran en `tmp/rag-source-csv/`; no son un requisito permanente del snapshot.

Cada archivo de `corpus/bgl/` o `corpus/uwf/` tiene un JSON contiguo con los registros originales, etiquetas, timestamps, hashes, firma y observaciones. La línea UWF corresponde al CSV deduplicado verificable por hash; **el UID identifica el evento en el Parquet original**, donde puede tener varias filas de etiqueta. BGL se identifica por SHA-256 del original y número de línea. El corpus unificado es [corpus_historico.jsonl](corpus/corpus_historico.jsonl).

La firma se calcula con `preprocesar_lote()` y `firma_lote(resumen, v2)`, usando los mismos campos que el estado inicial productivo. Las descripciones contienen mensajes BGL observados y conteos Zeek originales. Los normales conservan su clase legítima y referencias MITRE vacías. Los anómalos BGL son anomalías operativas; no se convierten en ataques. UWF conserva únicamente tácticas y técnicas presentes en las etiquetas originales, sin inferir subtécnicas.

La colección es `attack_patterns`, creada por `LongTermMemory` con su función real de embeddings. Admite ambas clases sin filtros adicionales. El poblado experimental usa `upsert` con IDs `rag_enriquecido_30_v1:<historical_case_id>` y metadatos escalares de procedencia. Es el equivalente del esquema de `seed_pattern()`: esa función original genera IDs aleatorios y no admite procedencia adicional. No se cambió su implementación. Repetir la incorporación verifica contenido y omite IDs ya presentes; rechaza un ID existente con otro contenido.

Los IDs vectoriales se conservan también en `meta.vector_id`, porque `_query()` devuelve texto, metadatos y similitud, pero no el ID nativo de Chroma. La herramienta y el agente reciben el mismo contrato JSON de siempre. Las técnicas devueltas desde el catálogo estático por similitud **no se incorporan como ground truth de los casos históricos**.

## Reconstrucción

Implementación: [rag_enriquecido.py](../../../src/experimentation/knowledge/rag_enriquecido.py). Lanzador: [prepare_rag_enriquecido.py](../../../tools/prepare_rag_enriquecido.py).

Se conservan `all-MiniLM-L6-v2`, revisión `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, ChromaDB 1.5.9, sentence-transformers 6.0.1, torch 2.14.0 y transformers 5.16.1. La preparación Parquet utiliza pyarrow 25.0.1 en un directorio temporal separado. Los hashes del modelo y las versiones efectivas constan en el reporte de poblado. El modo de embeddings es local/offline. Se conservan top-k 3, umbral de patrones 0,55, umbral ATT&CK 0,42 y truncamiento de consulta de 2.000 caracteres.

En un entorno Python con las dependencias fijadas del repositorio:

```powershell
python tools/prepare_rag_enriquecido.py construir --output experiments/knowledge/rag_enriquecido_30_v1_reconstruido
python tools/prepare_rag_enriquecido.py poblar --output experiments/knowledge/rag_enriquecido_30_v1_reconstruido
```

En este equipo se utilizó el intérprete registrado en R1, reutilizando los paquetes locales mediante el lanzador:

```powershell
$pythonRag = (Get-Content experiments/ejecucion/oficial-12casos-r1-20261028/environment.json -Raw | ConvertFrom-Json).executable
& $pythonRag tools/prepare_rag_enriquecido.py construir --output experiments/knowledge/rag_enriquecido_30_v1_reconstruido
& $pythonRag tools/prepare_rag_enriquecido.py poblar --output experiments/knowledge/rag_enriquecido_30_v1_reconstruido
```

`construir` rechaza destinos existentes y valida la independencia antes de exportar. La selección usa cobertura ponderada determinista y desempate por identificador, sin azar adicional; la partición conserva la semilla 20261003. `poblar` parte de una copia de archivos de `experiments/knowledge/chroma_v2`, exige que coincida con la semilla R1–R3, y solo congela después de validar y restaurar en otro proceso. No abre la base fuente con la API de Chroma.

Repetir `poblar` sobre esta versión congelada verifica sus hashes y termina sin insertar documentos ni recalcular embeddings. Una reconstrucción conserva corpus, IDs y contenido lógico; Chroma puede asignar nuevos UUID internos, por lo que los hashes físicos de una nueva reconstrucción pueden diferir. La restauración del snapshot existente sí reproduce sus bytes exactamente.

## Restauración para futuras repeticiones

El snapshot maestro es `chroma_snapshot/`; su inventario y SHA-256 están en [snapshot_congelado.json](manifests/snapshot_congelado.json). **No abrir directamente el maestro con Chroma ni apuntarle una ejecución**: una apertura puede realizar migraciones o escrituras.

Crear una carpeta nueva por caso y repetición:

```powershell
python tools/prepare_rag_enriquecido.py restaurar --destino experiments/ejecucion/rag_enriquecido_30_v1/r1/caso_01/chroma
$env:CHROMA_PATH = (Resolve-Path experiments/ejecucion/rag_enriquecido_30_v1/r1/caso_01/chroma).Path
```

El comando verifica el maestro, rechaza destinos existentes y compara todos los hashes de la copia. En este equipo puede sustituirse `python` por `& $pythonRag`. Se repite con carpetas nuevas para cada caso de R1, R2 y R3. Feedback, cachés e historial de ejecución deben quedar en copias de trabajo independientes; nunca se reutiliza la memoria acumulada de un caso en otro.

**La campaña existente `campana.correr_una()` sigue copiando la semilla estática `chroma_v2` y sobrescribe `CHROMA_PATH` para su proceso hijo.** Exportar la variable antes de llamar a ese lanzador no selecciona la condición enriquecida. La futura campaña deberá usar explícitamente una copia de este snapshot por caso como origen de su proceso. Ese lanzador futuro y las ejecuciones comparativas no forman parte de esta preparación.

MITRE ATT&CK® data reproduced and distributed with the permission of The MITRE Corporation. © The MITRE Corporation.
