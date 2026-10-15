# Cálculos esperados, hechos a mano

Requerido por la acción 7 de la Fase 5: *"Preparar fixtures y archivos de
prueba con cálculos esperados manualmente documentados. No ejecutar los
evaluadores ni las pruebas."*

Como los evaluadores **no se ejecutaron**, la aritmética de acá es la
verificación. Está escrita paso a paso para que se pueda revisar sin correr
nada. Los mismos números están en `metricas_esperadas.json`, que es lo que
leen las pruebas.

Fórmulas usadas, todas con la convención de que un denominador cero da
**indefinida** (`None`), no cero:

```
accuracy  = (TP+TN) / (TP+FP+FN+TN)
precision = TP / (TP+FP)
recall    = TP / (TP+FN)
F1        = 2·TP / (2·TP+FP+FN)
FPR       = FP / (FP+TN)
FNR       = FN / (FN+TP)
```

## D1 — caso `f1_cero_no_indefinido`

Es el escenario exacto que rompía el evaluador anterior. Conteos:
**TP=0, FP=6, FN=1, TN=13** (20 casos).

```
accuracy  = (0+13) / 20      = 13/20  = 0,65
precision = 0 / (0+6)        = 0/6    = 0,0
recall    = 0 / (0+1)        = 0/1    = 0,0
F1        = 2·0 / (2·0+6+1)  = 0/7    = 0,0      <-- antes daba None
FPR       = 6 / (6+13)       = 6/19   = 0,3157894736842105
FNR       = 1 / (1+0)        = 1/1    = 1,0
```

El evaluador anterior calculaba `F1 = 2PR/(P+R)` con la guarda
`if precision and recall`. Con `precision = 0.0` y `recall = 0.0`, la guarda
es falsa y devolvía `None`. Pero 0 y "indefinido" no son lo mismo: acá hubo
un positivo real y seis predicciones positivas, así que la métrica **está**
definida y vale 0.

## D1 — caso `genuinamente_indefinido`

Conteos: **TP=0, FP=0, FN=0, TN=5** (5 casos, ninguno positivo ni predicho
positivo).

```
accuracy  = (0+5) / 5        = 1,0
precision = 0 / 0            -> None   (no predijo ningún positivo)
recall    = 0 / 0            -> None   (no había ningún positivo real)
F1        = 0 / (0+0+0)      -> None   (único indefinido real de F1)
FPR       = 0 / (0+5)        = 0,0
FNR       = 0 / (0+0)        -> None
```

Contraste con el caso anterior: acá `recall` es `None` porque **no había
positivos**; allá era `0,0` porque **había uno y no lo detectó**. Son
situaciones opuestas y el informe no puede mostrarlas igual.

## D1 — caso `normal`

Conteos: **TP=14, FP=3, FN=6, TN=27** (50 casos).

```
accuracy  = (14+27) / 50       = 41/50 = 0,82
precision = 14 / (14+3)        = 14/17 = 0,8235294117647058
recall    = 14 / (14+6)        = 14/20 = 0,7
F1        = 2·14 / (2·14+3+6)  = 28/37 = 0,7567567567567568
FPR       = 3 / (3+27)         = 3/30  = 0,1
FNR       = 6 / (6+14)         = 6/20  = 0,3
```

Comprobación de que la forma directa coincide con la media armónica cuando
las dos están definidas:

```
2PR/(P+R) = 2 · 0,8235294 · 0,7 / (0,8235294 + 0,7)
          = 1,1529412 / 1,5235294
          = 0,7567568            = 28/37  ✓
```

## D2 y D3 — conjuntos, caso `tres_casos`

Tres comparaciones:

| Caso | Propuesto | Referencia | TP | FP | FN | Exacto |
|---|---|---|---|---|---|---|
| A | {u1, u2, u3} | {u1, u2, u4} | 2 | 1 | 1 | no |
| B | {u5} | {u5} | 1 | 0 | 0 | **sí** |
| C | {} | {u6, u7} | 0 | 0 | 2 | no |

Por caso:

```
A: precision = 2/3 = 0,6666666666666666
   recall    = 2/3 = 0,6666666666666666
   F1        = 4/(4+1+1) = 4/6 = 0,6666666666666666
B: precision = 1/1 = 1,0
   recall    = 1/1 = 1,0
   F1        = 2/(2+0+0) = 1,0
C: precision = 0/0 -> None   (no propuso nada)
   recall    = 0/2 = 0,0     (había dos y no propuso ninguno)
   F1        = 0/(0+0+2) = 0,0
```

**Micro** (se juntan los elementos: TP=3, FP=1, FN=3):

```
precision = 3/(3+1)       = 3/4  = 0,75
recall    = 3/(3+3)       = 3/6  = 0,5
F1        = 2·3/(2·3+1+3) = 6/10 = 0,6
```

**Macro** (promedio por caso, ignorando los indefinidos):

```
precision: definidos = [0,6666667, 1,0]           -> 1,6666667/2 = 0,8333333333333333
recall:    definidos = [0,6666667, 1,0, 0,0]      -> 1,6666667/3 = 0,5555555555555555
F1:        definidos = [0,6666667, 1,0, 0,0]      -> 1,6666667/3 = 0,5555555555555555
```

Nótese que `precision` macro promedia **dos** valores y no tres: el caso C
tiene precisión indefinida y promediarlo como 0 castigaría al sistema por un
caso en el que no afirmó nada.

```
exact_match = 1/3 = 0,3333333333333333
```

Micro (0,6) y macro (0,5556) difieren porque el caso B, que es perfecto,
aporta un solo elemento al micro y un tercio entero al macro.

## D4 — rúbrica, caso `un_reporte_dos_evaluadores`

Un reporte, dos evaluadores, escala 0–3:

| Criterio | E1 | E2 | &#124;dif&#124; |
|---|---|---|---|
| completitud | 3 | 2 | 1 |
| correccion_factual | 2 | 2 | 0 |
| coherencia_con_evidencia | 2 | 0 | **2** |
| claridad | 3 | 3 | 0 |
| informacion_no_sustentada | 3 | 3 | 0 |

Promedio por criterio (sobre las dos puntuaciones):

```
completitud               = (3+2)/2 = 2,5
correccion_factual        = (2+2)/2 = 2,0
coherencia_con_evidencia  = (2+0)/2 = 1,0
claridad                  = (3+3)/2 = 3,0
informacion_no_sustentada = (3+3)/2 = 3,0

promedio_global = (2,5+2,0+1,0+3,0+3,0)/5 = 11,5/5 = 2,3
```

Concordancia, sobre las 5 comparaciones:

```
acuerdo_exacto             = 3/5 = 0,6     (correccion, claridad, informacion)
acuerdo_hasta_un_nivel     = 4/5 = 0,8     (las anteriores + completitud)
diferencia_absoluta_media  = (1+0+2+0+0)/5 = 3/5 = 0,6
desacuerdos_relevantes     = 1             (coherencia, diferencia 2)
```

El desacuerdo de 2 niveles en `coherencia_con_evidencia` se informa
individualmente y **no** se promedia en silencio: en una escala de 4
niveles, una diferencia de 2 indica que el descriptor no está claro o que
los evaluadores entendieron cosas distintas.

## D5 — consumo, caso `dos_completas_una_fallida`

Tres corridas, una con `estado = "error_api"`:

| Corrida | estado | input_tokens | execution_time |
|---|---|---|---|
| r1 | completa | 1000 | 10,0 |
| r2 | completa | 2000 | 30,0 |
| r3 | error_api | 150 | 2,0 |

Solo entran las completas:

```
input_tokens:  media = (1000+2000)/2 = 1500,0
                 mediana = 1500,0   min = 1000   max = 2000   total = 3000   n = 2
execution_time: media = (10+30)/2 = 20,0
                 mediana = 20,0     min = 10,0   max = 30,0   total = 40,0   n = 2

n_corridas_completas     = 2
n_por_estado_ejecucion   = {"error_api": 1}
```

Si la corrida fallida entrara, `input_tokens` medio daría
`(1000+2000+150)/3 = 1050`, un 30% menos. La arquitectura que falla más
parecería la más eficiente.

## Contabilidad — caso `veinte_casos`

Estados de dimensión de 20 casos: 14 `evaluable`, 2 `no_aplica`,
1 `referencia_pendiente`, 2 `fallido`, 1 `no_evaluable`.

```
n_casos      = 20
n_evaluables = 14
n_por_estado = {no_aplica: 2, referencia_pendiente: 1, fallido: 2, no_evaluable: 1}

verificación: 14 + (2+1+2+1) = 14 + 6 = 20  ✓
```

Y la matriz de confusión de ese conjunto tiene que sumar **14**, no 20: solo
los evaluables entran. `MetricsRecord` lo rechaza si no cuadra.
