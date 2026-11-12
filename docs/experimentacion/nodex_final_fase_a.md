# NODEX final — Fase A: contexto, perfil, evidencia por grupos, mitigación y salida

Rama `nodex-final`, creada desde el tag `piloto-12casos` (commit `4b555fa`). Cada mejora tiene un
interruptor en `src/config.py`, con el valor del sistema final por omisión. Los umbrales son genéricos,
no se ajustaron a casos concretos y su justificación está junto a cada variable.

## Mejoras e interruptores

| Mejora | Interruptor | Qué cambia |
|---|---|---|
| M1 contexto | `CONTEXTO_LOTE_COMPLETO`, `TRIAGE_MAX_LINEAS=200`, `TRIAGE_MAX_CHARS=20000` | El triage (y el agente único) recibe el contenido del lote: en texto, todas las líneas `[uid] línea` con tope y aviso de recorte; en red, las filas completas de los flujos minoritarios. |
| M1 catálogo | `EVIDENCIA_CONTEXTO_EXTENDIDO`, `EVIDENCIA_MAX_CHARS_MENSAJE=300` | El catálogo `evidencia_logs` lleva el mensaje en logs de texto y, en red, `duration`, `orig_bytes`, `resp_bytes` y `history`. |
| M2 perfil | `PERFIL_LOTE_ACTIVO` y `PERFIL_*` | `resumen_logs.perfil_lote`, sin LLM: por origen (conexiones, destinos y puertos distintos, ventana, estados) y señales (barrido ≥15 puertos a un destino, servicio/protocolo <5 %, pares con ≤2 filas, inversión de rol, bytes > p95 con ≥20 filas). En texto: severidad, componente, nodos y uids de severidad alta. |
| M2 UDP | `UDP_S0_NO_ES_FALLO` | S0 en UDP/ICMP ya no es intento fallido ni `evento_critico` (no hay handshake). |
| M2 BGL | `BGL_ALERTA_OPCIONAL` | El enriquecedor de BGL acepta líneas sin el campo de alerta (que el generador retira). Antes no se aplicaba nunca: cobertura 0 %. Sin el campo no se emite etiqueta. |
| M6 grupos | `EVIDENCIA_POR_GRUPOS` | Grupos determinísticos G01…: red (origen, destino, protocolo, servicio o puerto; un barrido es un grupo); texto (nodo, componente, severidad, plantilla). Tabla de grupos en `contexto_d11`, `group_id` por registro, `PROMPT_D11` pide citar TODA la evidencia por `evidence_groups`/`evidence_uids`; `normalizar_d11` expande y cuenta grupos inexistentes como inválidos. |
| M7 mitigación | `MITIGACION_CON_CONTEXTO`, `VALIDACION_COMANDOS_ESTRICTA`, `MITIGACION_DIR_SALIDA=/var/tmp/nodex` | La mitigación recibe veredicto preliminar y evidencia, con reglas por veredicto. El validador rechaza abrir el firewall, escribir fuera del directorio, comandos destructivos y binarios no reconocidos; registra cada rechazo (`comandos_rechazados`). |
| M8 veredicto | `VEREDICTO_PRELIMINAR` | El triage entrega `veredicto_preliminar` (`incidente_seguridad`/`anomalia_operativa`/`normal`) y su justificación; la salida agrega `classification_detallada` derivada del veredicto final. |
| M9 generador | `UWF_REBASE_FORMATO_FONDO` | Las filas rebasadas usan el formato del fondo; regeneración en un directorio nuevo. |

**Correspondencia de `classification_detallada`** (`output_contract.clasificacion_detallada`):
`hay_incidente=True` → `incidente_seguridad`; `hay_incidente=False` y `hay_anomalia=True` →
`anomalia_operativa`; ambos `False` → `normal`; un veredicto ausente → `None`. `classification`
(MALICIOUS/BENIGN) no cambia: en BGL, cuya pregunta es operativa, una falla de hardware sigue saliendo
MALICIOUS; `classification_detallada` la distingue de un incidente.

**Agente único.** Recibe el mismo contenido del lote (bloque compartido `contexto_contenido_lote`), el
mismo catálogo y tabla de grupos, el mismo `PROMPT_D11`, las mismas reglas de mitigación y el mismo
validador estricto. La campaña `agenteunico-12casos` queda como parte del piloto.

## Hallazgos de la inspección

- **H1.** BGL entraba entero por el decoder de texto: el triage veía una sola línea y el catálogo no
  tenía mensaje (la regla de la línea 112 descartaba `message` cuando es igual al crudo).
- **H2, BGL 0 %.** `_BGL_RE` exigía el campo de alerta inicial, que el generador retira.
- **H9, formato.** En los 4 shards benignos (350 339 filas) `ts` es `repr(float)` y `datetime` sale de
  `ts` en UTC con microsegundos. Los shards maliciosos traen `datetime` en milisegundos. El generador
  escribía las filas rebasadas con `ts` de 6 decimales fijos y `datetime` en milisegundos: las dos
  columnas distinguían las filas inyectadas. Ninguna otra columna tiene formatos exclusivos de las filas
  maliciosas.
- **Pruebas de `test_llm.py`.** Cuatro fallaban porque el `.env` de evaluación fija el mismo modelo
  como principal y respaldo; un fixture les da nombres distintos.

## Regeneración (M9)

`python -m src.experimentation.datasets.regenerar --destino <dir> --particiones <...>` vuelve a correr
los generadores con sus semillas, recorre siempre las dos particiones en el mismo orden (el fondo UWF
se asigna con un cursor compartido) y escribe solo las particiones pedidas en `<dir>/cases` y
`<dir>/ground_truth`. Se niega a escribir en `experiments/`. Prueba con desarrollo (12-nov-2026):
BGL 24 casos y 24 referencias idénticos; UWF 24 casos y 24 referencias, con diferencias solo en `ts` y
`datetime` de 352 filas rebasadas (mismo instante, formato del fondo); manifiestos de desarrollo,
uids usados y fondo consumido idénticos al original.

## Inventario de la partición de evaluación (sin abrir casos ni ground truth)

Fuente: manifiestos del generador (un caso es positivo si su índice es menor que `n_positivos`;
`incidentes_usados[índice]` da la táctica) y los incidentes reconstruidos desde los CSV convertidos.
Se excluyen los 12 casos del piloto (`enriquecido-12casos-r1-20261104/selection.json`).

| Dataset y condición | Casos | Positivos | Piloto (positivos) | Disponibles sin piloto |
|---|---|---|---|---|
| BGL natural | 50 | 14 | 3 (1) | 13 con alerta, 34 sin alerta |
| BGL balanceado | 12 | 6 | 3 (2) | 4 con alerta, 5 sin alerta |
| UWF visible | 40 | 20 | 3 (1) | 19 maliciosos, 18 benignos |
| UWF sigiloso | 40 | 20 | 3 (2) | 18 maliciosos, 19 benignos |

Tácticas maliciosas disponibles sin piloto. Visible: Reconnaissance 12, Discovery 4, Resource
Development 2, Defense Evasion 1. Sigiloso: Reconnaissance 8, Resource Development 5, Discovery 1,
Discovery|Reconnaissance 1, Execution 1, Execution|Resource Development 1, Initial Access 1. Además hay
206 incidentes de evaluación sin usar, todos Reconnaissance (26 de ≥20 conexiones).

**Meta de 60 casos: alcanzable.** BGL 15 con alerta (de 17) y 15 sin alerta (de 39); UWF 7 visibles
(de 19), 8 sigilosos (de 18) y 15 benignos (de 37). Con variedad máxima: los 7 visibles pueden cubrir
Defense Evasion, Discovery (hasta 4), Resource Development (2) y Reconnaissance; los 8 sigilosos,
Execution, Execution|Resource Development, Initial Access, Discovery|Reconnaissance, Discovery,
Resource Development y Reconnaissance. La selección y regeneración se hará después de congelar el código.

## Desarrollo de BGL y UWF

BGL desarrollo: 24 de 30 ventanas usadas; las 6 libres no tienen alerta. UWF desarrollo: 83 incidentes
libres, todos Reconnaissance (64 de una sola IP); 19 de ≥20 conexiones.

## Prueba real con desarrollo (12-nov-2026)

`tools/probar_desarrollo_fase_a.py`, 5 casos de desarrollo, configuración de evaluación del piloto
(`gemini-3.8-flash`, temperatura 0, sin respaldo, sin reputación externa, red bloqueada). **Base de
conocimiento: `experiments/knowledge/chroma_v2`** (697 técnicas MITRE, sin históricos), copia nueva por
caso; no se usó el RAG enriquecido porque sus históricos salen de ventanas de desarrollo y podrían
recuperarse a sí mismos. 30 llamadas, todas `gemini-3.8-flash`, sin errores; gasto USD 0,368 (tope 1).
Resultados en `experiments/desarrollo_fase_a/20261112/`. Son observaciones de desarrollo, no métricas.

| Caso | Etiqueta | Preliminar | Final | USD |
|---|---|---|---|---|
| bgl_des_balanceado_0000 | anómalo | anomalia_operativa | anomalia_operativa | 0,036 |
| bgl_des_natural_0010 | normal | anomalia_operativa | anomalia_operativa | 0,044 |
| uwf_des_visible_0000 | malicioso (Discovery) | incidente_seguridad | incidente_seguridad, T1046 con G11 (60 uids) | 0,093 |
| uwf_des_visible_0008 | benigno | anomalia_operativa | anomalia_operativa (`hay_incidente=false`) | 0,085 |
| uwf_des_sigiloso_0000 | malicioso (Resource Development) | anomalia_operativa | anomalia_operativa (`hay_incidente=false`) | 0,110 |

En el sigiloso, las 3 filas del incidente llegaron al triage en los flujos minoritarios (grupo G08) y el
auditor las citó, pero las interpretó como un intento menor de conexión a un puerto inactivo.
