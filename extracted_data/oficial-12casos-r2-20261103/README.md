# NODEX — R2: oficial-12casos-r2-20261103

Doce casos en el orden de R1, una ejecución por caso. Abrir `revision_datos_crudos.ipynb`. Las proyecciones conservan el esquema R1: detección, reconstrucción, MITRE, reportes y rendimiento. Los archivos `_items` mantienen orden y duplicados; `present` distingue ausencia de null.

Las entradas y referencias reservadas son idénticas a R1. Los estados de todos los casos, incluidos fallos, están en `run_status.jsonl`. Los reportes almacenados están en `reports/generated/`. El estado inicial del RAG y la comprobación de cada copia temporal se conservan en los originales. También se incluye una copia byte a byte de la semilla MITRE.

Consulte `manifest.json`, `extraction.json`, `verification.json` y `repetition_integrity.json`. La carpeta `procedure/` conserva los scripts y el procedimiento. Rendimiento contiene las medidas registradas por NODEX; no se inventan CPU/RAM/GPU ni costo facturado. raw es el estado final preservado, no todas las respuestas HTTP del proveedor.

Para Google Colab, descomprima el ZIP en una carpeta con su mismo nombre y abra el notebook; si hace falta, ajuste BASE a esa carpeta. La carga conjunta usa case_id, repeticion y run_id. No se ejecuta NODEX desde el notebook ni se calculan métricas.

Para verificar únicamente esta extracción: `python procedure/verify_official_repetition.py . --execute-notebook`.
