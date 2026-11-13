# Bitácora de la variante "NODEX B.1 sin cazador, auditor reforzado" (12-nov-2026)

Configuración: los 48 casos de desarrollo, 1 repetición, solo NODEX, `gemini-3.8-flash`, temperatura 0, memoria
`rag_enriquecido_v2` (contrastiva, 2 por clase) y `memoria_grupos_v1`, exclusión por incidente activa, tope USD 8.
Interruptores fijados en el arnés: `--entorno CAZADOR_ACTIVO=false --entorno AUDITOR_REFORZADO=true`; el resto
como en B.1. Cada caso guarda sus interruptores efectivos (`interruptores_efectivos`). Código evaluado: commit
`8d70d6d` más `20261112/src_sin_commit.patch` (el código de la variante, sin commit).

## Incidentes

Horas locales del equipo (America/Santiago). Fuente: registro de sistema de Windows.

| Hora | Caso | Motivo | Tratamiento |
|---|---|---|---|
| 13:09:50 | NODEX `uwf_des_sigiloso_0003` (iniciado justo después de que terminara `uwf_des_sigiloso_0002`, a las 13:08:59) | Apagado inesperado del equipo (Kernel-Power 41 y EventLog 6008; no fue una suspensión). El arnés y el caso en curso murieron sin escribir resultado ni registro. | No hay corrida parcial que apartar. Los 27 casos terminados antes del apagado se conservan (`consola_parte1.txt`). Se verificó que el código actual es idéntico al parche evaluado y el arnés se relanzó omitiendo los terminados; `uwf_des_sigiloso_0003` y los 20 restantes corren desde cero, cada uno con un proceso nuevo y una copia nueva de la memoria. |

Hubo otros dos apagados inesperados (14:46 y 16:29) con el arnés ya detenido: no afectaron ningún caso.

## Cierre

La reanudación (`consola_parte2.txt`, `20261112/registro_021823.json`) corrió los 21 casos restantes con
código 0 y sin errores del modelo. El registro de la primera parte se perdió con el apagado; sus 27 casos
guardan en su propio resultado los interruptores efectivos y el código evaluado coincide con el parche
guardado. Resultado: 48 de 48 casos, gasto USD 3,02 (tope 8). Todos los casos registran los mismos
interruptores efectivos (`CAZADOR_ACTIVO=false`, `AUDITOR_REFORZADO=true`, resto como en B.1).

## Decisión (12-nov-2026)

Esta variante se eligió como configuración final de NODEX, como desviación documentada de la regla de
selección por F1 promedio. Motivos y consecuencias en `docs/experimentacion/bitacora_desarrollo_nodex_final.md`.
