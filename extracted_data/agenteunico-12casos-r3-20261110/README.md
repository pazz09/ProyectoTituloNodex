# NODEX agente único — R3: agenteunico-12casos-r3-20261110

Doce casos en el orden de `oficial-12casos-r1-20261028`, una ejecución por caso, arquitectura `agente_unico` (`src/single_agent.py`, una llamada al modelo). Mismo modelo, temperatura y política externa que las campañas oficiales de NODEX multiagente. Abrir `revision_datos_crudos.ipynb`.

Las proyecciones conservan el esquema de R1: `detection/`, `reconstruction/`, `mitre/`, `reports/`, `performance/`. Los archivos `_items` mantienen orden y duplicados; `present` distingue ausencia de null. Las referencias (ground truth) se copiaron solo al extraer, después de la inferencia, y están separadas de las predicciones.

Propio del agente único: `mitre/retrieval_observation.jsonl` (candidatos MITRE recuperados SIEMPRE, con similitud, texto de la consulta y comprobación de que llegaron al prompt; no son atribuciones) y `performance/single_agent_observation.jsonl` (JSON válido y tamaño del prompt). El texto exacto enviado al modelo está en `originals/execution/.../<run_id>.llm_input.json`.

`run_status.jsonl` conserva los 12 casos e indica `resultado_incompleto` cuando el agente no entregó el contrato completo (la corrida se cuenta como completa con la regla de NODEX si trae un veredicto booleano).

Consulte `manifest.json`, `extraction.json`, `verification.json` y `repetition_integrity.json`. La carpeta `procedure/` conserva los scripts y la bitácora. No se ejecuta el sistema desde el notebook ni se calculan métricas.
