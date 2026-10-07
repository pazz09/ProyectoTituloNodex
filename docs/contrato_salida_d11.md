# Contrato de salida D-11

Fecha: 7 de octubre de 2026. Versión del contrato: `d11-v1`.

## Diagnóstico y alcance

Antes de la extensión, Triage producía `diagnostico`; el Auditor agregaba
veredictos D1, confianza, evaluación D4 y cobertura. `tecnicas_mitre` contenía
resultados de RAG, no conclusiones. `cronologia` era un recorte determinista de
presentación, no una reconstrucción del modelo. `eval_deteccion` exportaba D1 y
duración, sin D2/D3. No había un comparador LLM de agente único en `src`.

La extensión mantiene los ocho nodos, LangGraph, routers, herramientas, modelos,
RAG y reglas D1. El Auditor existente entrega las conclusiones D2/D3 en su misma
llamada; no se incorpora otro nodo al grafo. El agente único es un comparador
independiente, sin planificación, delegación ni ciclo multiagente.

## Contrato formal

Se conservan los campos anteriores y se añaden:

```json
{
  "output_contract_version": "d11-v1",
  "eventos_reconstruidos": [{
    "event_id": "event_001",
    "evidence_uids": ["A"],
    "timestamp": "2026-10-01T10:00:00Z",
    "event_type": "authentication_failure",
    "description": "Intento de autenticación fallido observado.",
    "confidence": null
  }],
  "secuencia_temporal": ["event_001"],
  "tecnicas_atribuidas": [{
    "technique_id": "T1110",
    "technique_name": "Brute Force",
    "evidence_uids": ["A"],
    "justification": "Intentos fallidos observados.",
    "confidence": null
  }],
  "invalid_evidence_uid_count": 0,
  "d11_warnings": [],
  "evidencia_logs": [],
  "evidencia_logs_omitidos": 0,
  "telemetry": {}
}
```

Las tres listas de conclusiones admiten `[]`. `tecnicas_mitre` sigue siendo el
canal de candidatos RAG y jamás se copia automáticamente a `tecnicas_atribuidas`.
La validación comprueba formato de Technique ID, incluidos IDs de subtécnicas;
no comprueba que el ID exista en una versión específica del catálogo ATT&CK.

## Evidencia y validación

El preprocesamiento se ejecuta una vez. Se construye un catálogo de registros
normalizados con una allowlist de hechos, timestamp y procedencia por líneas.
No se copian `raw`, `attributes`, etiquetas ni el canal `ground_truth` al
catálogo. Se omite `message` cuando es una copia del registro crudo o contiene
nombres de campos de etiquetado. Se conserva el UID/flow ID de origen cuando
existe; de lo contrario se asigna `log_record_000001`, estable por posición del
registro lógico. Este UID de evidencia es distinto del `event_id` reconstruido.

El catálogo está acotado a los primeros `CRONOLOGIA_MAX_EVENTOS` registros
(40 por defecto), sin selección por etiquetas. `evidencia_logs_omitidos` declara
el recorte. El conjunto válido contiene solo UIDs efectivamente visibles para
el Auditor/comparador; un registro omitido no puede citarse. Esto mantiene
acotados los prompts y checkpoints, pero limita la cobertura de D2/D3 en lotes
grandes. El ground truth de reconstrucción debe emparejarse por UID o procedencia
de registro, nunca por `event_id`, que pertenece a la ejecución del modelo.

Después del LLM se filtran UIDs inexistentes, se cuentan sus apariciones y se
registran advertencias. Se excluyen eventos sin evidencia/descripción y técnicas
sin evidencia/justificación. Se normaliza snake_case e IDs MITRE, se excluyen
event IDs duplicados y se fusiona evidencia de técnicas repetidas. La pertenencia
del UID es una garantía de trazabilidad; la validez semántica de la conclusión
sigue siendo una capacidad a evaluar, no una verdad impuesta por el validador.

Los timestamps se aceptan solo si son marcas válidas de los logs citados. Si
falta una fecha válida, solo se deriva cuando la evidencia contiene una única
marca; en otro caso queda `null`. Se reconstruye la secuencia ordenando eventos
con fecha observable, sin colocar eventos sin fecha ni inferir causalidad. No
se mezclan fechas con zona y sin zona para ordenar: queda advertencia y secuencia
vacía. No se inventa el año de timestamps Syslog BSD. Las confianzas D2/D3 se
mantienen en `null`, sin alterar la confianza global existente de D1/D4.

Las conclusiones se reemplazan en cada Auditor. Al replanificar se archivan y
se vacían las activas; los contadores de evidencia inválida y advertencias se
conservan para toda la ejecución. Los estados antiguos tienen defaults seguros.

## Flujo y consumidores

```text
logs -> preprocesamiento -> catálogo de evidencia sin etiquetas
     -> estado LangGraph -> Auditor (JSON explícito D2/D3)
     -> validación determinista -> estado final
     -> reporte SSE/API y SQLite.reporte_json / CLI
     -> normalizar_salida_experimental -> JSON de eval_deteccion
```

`normalizar_salida_experimental` expone `detection`, `reconstruction.events`,
`reconstruction.timeline`, `mitre.attributed_techniques`, `report`, `telemetry`,
`evidence` y `validation`. `mitre.retrieved_candidates` es un canal separado.
El evaluador conserva sus métricas D1 y guarda además `output_normalizado` con
los resultados reales D2/D3. No se fabrican métricas D2/D3: BGL/HDFS actualmente
aportan etiquetas de anomalía, no un ground truth completo de reconstrucción
y técnicas. El scoring D2/D3 requiere ese ground truth y una regla de matching
predefinida. D4 mantiene el reporte/PDF anterior; el nuevo contenido estructurado
vive en el reporte JSON, sin cambiar la plantilla PDF ni las vistas frontend.

El agente único usa el mismo preprocesamiento, catálogo, prompt D-11, validador
y exportación. Produce D1/D2/D3/D4 en una sola llamada lógica, con los mismos
reintentos/fallback del cliente. Su propuesta de comandos pasa por el validador
existente; no ejecuta comandos. Puede recibir candidatos MITRE explícitos
mediante `tecnicas_mitre`; por defecto no consulta RAG ni CVEs. Esta diferencia
de acceso a herramientas debe declararse en el protocolo comparativo.

```powershell
python -m src.tools.eval_deteccion --dataset bgl --n-lotes 2 --arquitectura agente_unico
```

Las etiquetas solo se agregan a los resultados del evaluador después del
análisis; no se pasan al comparador ni al adaptador.

## Telemetría D5

La medición usa `ContextVar` por ejecución; se reinicia al terminar, también
ante errores. `llm_call_count` cuenta intentos reales de `generate_content`,
incluidos JSON inválido, backoff y fallback. Cada solicitud registra el modelo
efectivo. `input_tokens`, `output_tokens` y `total_tokens` provienen de los campos
del proveedor. Si falta un campo en alguna solicitud, su total es `null`, no una
estimación. `total_tokens` puede incluir razonamiento informado por el proveedor
y no tiene que ser igual a entrada + salida.

Se registran `execution_time` en segundos (preprocesamiento y ejecución),
`replan_count`, `intentos_correccion` acumulados entre ciclos,
`invalid_evidence_uid_count` y `d11_warning_count`. En streaming, el tiempo
incluye el tiempo durante el cual el consumidor mantiene suspendido el
generador. Las ejecuciones parciales conservan telemetría; no se convierten en
predicciones normales válidas.

Las métricas históricas del contrato anterior no certifican D2/D3 ni consumo
de esta versión. La campaña final debe regenerarse sobre un commit limpio de
`d11-v1`, sin ajustar prompts con sus resultados.

## Archivos y razones

| Archivo | Cambio |
| --- | --- |
| `src/output_contract.py` | Tipos, prompt compartido, evidencia, validación y adaptador |
| `src/state.py` | Transporta evidencia y conclusiones D2/D3 |
| `src/agents/agente_auditor_final.py` | Emite y valida D2/D3 en la llamada existente |
| `src/agents/agente_planificador.py` | Archiva y reinicia conclusiones al replanificar |
| `src/pipeline.py` | Inicializa catálogo y exporta contrato/telemetría por CLI y SSE |
| `src/single_agent.py` | Comparador independiente con contrato equivalente |
| `src/telemetry.py`, `src/llm.py` | Medición aislada y consumo por solicitud real |
| `src/tools/eval_deteccion.py` | Guarda contrato normalizado y selecciona arquitectura |
| `src/tools/log_runner.py` | Preserva D2/D3 en JSON de CLI |
| `tests/test_output_contract_d11.py` | Casos requeridos y fixture integrado A/B/C |

## Verificación

El fixture integrado usa tres registros con UIDs A/B/C y respuestas simuladas,
sin pasar ground truth al modelo. Recorre el grafo compilado, estado final,
streaming, CLI, adaptador y archivo JSON experimental. Incluye pruebas de
ausencia de etiquetas Zeek, aislamiento de mediciones, reintentos JSON y
replanificación. Los resultados efectivos de ejecución se registran en
`docs/revision_auditoria.md`; no se considera cerrada la verificación pendiente.
