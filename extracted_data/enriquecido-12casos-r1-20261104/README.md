# NODEX — enriquecido-12casos-r1-20261104

Doce casos oficiales en el mismo orden; repetición 1, condición RAG enriquecido. Predicciones y referencias conservan las proyecciones literales originales: detection, reconstruction, mitre, reports y performance. No se normalizaron nuevas técnicas ni se calcularon métricas D1–D4.

`originals/` conserva archivos byte a byte y el snapshot usado. Los manifiestos contienen SHA-256 y procedencia; `present` distingue ausencia de null y los archivos `_items` preservan orden y duplicados. El notebook solo inspecciona datos.

`rag_usage/queries.jsonl` registra solicitudes naturales; `retrieved_documents.jsonl`, candidatos nativos y documentos devueltos por memoria; `llm_delivery.jsonl`, presencia literal del documento en los argumentos reales del SDK y resultado de la solicitud; `retrieval_summary.jsonl`, referencias literales en la salida final y límites de observación. Recuperar o entregar contexto no demuestra influencia causal en el razonamiento. Los empates fuera del top-k no son observables.

Cada caso partió de una copia independiente del mismo snapshot: 30 patrones históricos, 697 técnicas MITRE y memorias de errores/historial vacías. La evidencia individual está en los archivos `.isolation.json`. Los históricos no se borraron al limpiar memoria dinámica.

Se mantienen las limitaciones del corpus: once BGL comparten firmas genéricas entre clases y hay empates sin desempate estable; los UWF históricos son episodios sigilosos y no tienen campaign_id verificable.

El código funcional, prompts, modelo, generación, routers y umbrales coinciden con R1. `compatibility.json` documenta cinco diferencias auxiliares del inventario del runtime actualizado: cuatro versiones quedan ocultas por las originales del venv; artifact_tool no pertenece a NODEX ni se importa. No se afirma identidad absoluta de los paquetes instalados. La instrumentación añade solo observación y metadatos/IDs de campaña, sin modificar decisiones ni argumentos enviados al modelo.

Consultar `verification.json`, `manifest.json`, `extraction.json` y `rag_usage/initial_state.json`. Los errores se conservan en `run_status.jsonl` y no se reintentan experimentalmente. Para verificar las copias/proyecciones: `python procedure/export_enriched_campaign.py --verify .`.
