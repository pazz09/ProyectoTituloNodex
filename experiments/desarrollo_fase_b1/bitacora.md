# Bitácora de la evaluación de desarrollo de la Fase B.1 (12-nov-2026)

Configuración: 48 casos de desarrollo con NODEX B.1 y 48 con el agente único B.1, `gemini-3.8-flash`,
temperatura 0, memoria `rag_enriquecido_v2` (contrastiva, 2 por clase) y `memoria_grupos_v1`, exclusión por
incidente activa, tope USD 15. Código evaluado: commit `0ac0a4c` más el parche de `src`
(`20261112/src_sin_commit.patch`) y los archivos nuevos de `src` (`20261112/src_sin_seguimiento/`).

## Incidentes

Horas locales del equipo (America/Santiago). Fuente de las suspensiones: registro de sistema de Windows
(Kernel-Power, eventos 42 y 1).

| Hora | Caso | Motivo | Tratamiento |
|---|---|---|---|
| 05:29:34 – 08:31:10 | NODEX `uwf_des_visible_0006` (en curso desde 05:29:21) | El equipo entró en suspensión durante la corrida. El arnés agotó su tope de 7 200 s por caso (el reloj siguió corriendo durante la suspensión) y se detuvo con `TimeoutExpired`; el proceso del caso terminó y escribió su resultado a las 08:32:40 (tiempo de análisis 96 s; tiempo de pared 10 999 s). | Corrida interrumpida apartada en `20261112/interrumpidas/nodex/` (no se usa en las métricas). El caso se repite desde cero con un proceso nuevo y una copia nueva de la memoria. La consola de la primera parte quedó en `consola_parte1.txt`; el arnés se reanudó a las 08:33 omitiendo los casos ya terminados. |
| 08:46:30 – 10:32:25 | Agente único `bgl_des_natural_0003` (en curso desde 08:46:10) | El equipo entró en suspensión durante la corrida. Al reanudarse, la llamada al modelo se reintentó (2 llamadas) y el caso terminó a las 10:38:08. Su tiempo no es válido porque incluye la suspensión. | Corrida interrumpida apartada en `20261112/interrumpidas/agente_unico/` (no se usa en las métricas). El caso se repite desde cero con un proceso nuevo y una copia nueva de la memoria. |

| 11:00:14 – 11:01:59 (último caso bueno a las 11:00:14) | Agente único `uwf_des_visible_0006` a `uwf_des_visible_0011` (6 casos) | La API respondió `402 RESOURCE_EXHAUSTED` (crédito prepagado de Google AI Studio agotado) en la única llamada de cada caso: sin diagnóstico ni tokens facturados. | Corridas fallidas apartadas en `20261112/fallidas_sin_credito/agente_unico/` (no se usan en las métricas). Los 6 casos se repiten desde cero cuando haya crédito. |

Ningún otro caso estaba en curso durante una suspensión (comparación de las horas de término de cada
resultado con las suspensiones del registro de sistema). Para reducir el riesgo, desde las 08:33 corre un
proceso temporal que pide a Windows no suspender por inactividad; no impide una suspensión pedida por el
usuario o por el cierre de la tapa.

## Repetición de los casos apartados (12-nov-2026, 12:26–12:34 hora local)

Tras recargar el crédito, el arnés se relanzó con el código del commit `8d70d6d` sin cambios
(`registro_153353.json`: `src_sin_cambios: true`), omitiendo los casos ya terminados. Se repitieron desde
cero, cada uno con un proceso nuevo y una copia nueva de la memoria, los 8 casos apartados: NODEX
`uwf_des_visible_0006` y agente único `bgl_des_natural_0003` y `uwf_des_visible_0006` a `0011`. Los 8
terminaron con código 0 y sin errores del modelo (USD 0,569 en total). Consola en `consola_parte3.txt`.
Con esto la evaluación B.1 queda completa: 48 casos de NODEX y 48 del agente único. Las corridas apartadas
no se usan en las métricas.

Nota: los casos ya terminados antes del commit corrieron con el parche `src_sin_commit.patch` más
`src_sin_seguimiento/`, verificados idénticos al contenido de `src` en `8d70d6d`.
