# Bitácora de desarrollo de NODEX final

Decisiones tomadas durante el desarrollo, con la partición de desarrollo solamente (48 casos: 24 BGL y 24
UWF). Las bitácoras de cada corrida (incidentes, repeticiones, gasto) están junto a sus resultados en
`experiments/desarrollo_*/`.

## 12-nov-2026 — Configuración final: "B.1 sin cazador, auditor reforzado"

**Decisión.** La configuración final de NODEX es la variante "B.1 sin cazador, auditor reforzado"
(`AUDITOR_REFORZADO=true`; el agente cazador se elimina del código final).

**Regla de selección y desviación documentada.** La regla acordada era elegir la configuración de NODEX
con mayor F1 promedio BGL/UWF en desarrollo. Resultados (1 repetición, 48 casos):

| Configuración | F1 BGL | F1 UWF | F1 promedio |
|---|---:|---:|---:|
| A.1 | 0,615 | 0,667 | 0,641 |
| B.1 sin cazador, auditor reforzado | 0,778 | 0,500 | 0,639 |
| B | 0,778 | 0,471 | 0,625 |
| B.1 con cazador | 0,778 | 0,471 | 0,625 |

Por la regla estricta correspondería A.1. Se elige la variante como **desviación documentada** de la regla,
por estos motivos:

1. Con una repetición, A.1 (0,641) y la variante (0,639) no se distinguen dentro de la variación del
   modelo: el triage, con exactamente la misma entrada en B.1 y en la variante, cambió su veredicto en 2
   de 48 casos. La diferencia de 0,002 equivale a menos de un caso.
2. A.1 conserva el defecto de que la corrección del auditor no se propaga al resto del análisis (diagnóstico
   y mitigación quedan con la clase anterior); la variante tiene el ciclo de corrección tras el auditor y
   en esta corrida corrigió los 2 falsos positivos de su triage.
3. La variante tiene mejor precisión en BGL (0,700 frente a 0,444 de A.1: 3 falsos positivos en lugar de 10).

Detalle completo: `experiments/desarrollo_fase_b1_auditor_reforzado/informe_comparativo.md`.

**Consecuencias en el código final.**
- Se elimina el agente cazador (módulo, router, campos de estado, interruptor, pruebas y referencias en el
  frontend y en `docs/arquitectura_nodex_final.md`). El historial de git y las carpetas de resultados de
  desarrollo no se tocan.
- Se conservan la memoria por grupo de eventos y la lista de verificación de patrones MITRE: ahora las usa
  el auditor reforzado.
- Los valores por defecto de `src/config.py` quedan exactamente en la configuración elegida.
- La configuración no se congela (sin tag) hasta la aprobación explícita.
