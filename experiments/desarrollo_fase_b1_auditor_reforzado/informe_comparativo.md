# Comparación de configuraciones en los 48 casos de desarrollo (12-nov-2026)

Casos: 24 BGL (4 balanceados y 20 naturales) y 24 UWF (12 visibles y 12 sigilosos). Una repetición por
configuración, `gemini-3.8-flash`, temperatura 0, exclusión por incidente activa, sin usar la partición de
evaluación. BGL se puntúa con `hay_anomalia` y UWF con `hay_incidente`. F1 = 2·VP / (2·VP + FP + FN).

| Configuración | Carpeta | Código |
|---|---|---|
| NODEX A.1 | `desarrollo_fase_a1` | `76a03ef` (memoria `chroma_v2`, sin memoria histórica de la organización) |
| NODEX B | `desarrollo_fase_b` | `8e58465` |
| NODEX B.1 con cazador | `desarrollo_fase_b1` | `8d70d6d` (equivalente) |
| NODEX B.1 sin cazador, auditor reforzado | `desarrollo_fase_b1_auditor_reforzado` | `8d70d6d` + `src_sin_commit.patch` |
| Agente único B (referencia) | `desarrollo_fase_b` | `8e58465` |
| Agente único B.1 | `desarrollo_fase_b1` | `8d70d6d` (equivalente) |

## 1. Criterio de selección: F1 promedio BGL/UWF de NODEX

| Configuración | F1 BGL | F1 UWF | **F1 promedio** | Precisión / sensibilidad BGL | Precisión / sensibilidad UWF |
|---|---:|---:|---:|---|---|
| NODEX A.1 | 0,615 | 0,667 | **0,641** | 0,444 / 1,000 | 1,000 / 0,500 |
| NODEX B | 0,778 | 0,471 | **0,625** | 0,700 / 0,875 | 0,800 / 0,333 |
| NODEX B.1 con cazador | 0,778 | 0,471 | **0,625** | 0,700 / 0,875 | 0,800 / 0,333 |
| NODEX B.1 sin cazador, auditor reforzado | 0,778 | 0,500 | **0,639** | 0,700 / 0,875 | 1,000 / 0,333 |
| Agente único B | 0,778 | 0,500 | 0,639 | 0,700 / 0,875 | 1,000 / 0,333 |
| Agente único B.1 | 0,706 | 0,500 | 0,603 | 0,667 / 0,750 | 1,000 / 0,333 |

Orden según el criterio: A.1 (0,641) > B.1 con auditor reforzado (0,639) > B = B.1 con cazador (0,625).

**Cuánto pesa una diferencia de un caso.** El triage recibe exactamente la misma entrada en B.1 con cazador y
en la variante, porque el cazador y el auditor actúan después. Aun así, su veredicto preliminar cambió en 2 de
48 casos (`uwf_des_sigiloso_0007` y `uwf_des_visible_0010`). Esa es la variación propia del modelo entre
corridas idénticas. Las configuraciones se separan por 0 a 3 casos, así que con una sola repetición las
diferencias no son concluyentes:
- La diferencia entre A.1 y la variante (0,002) equivale a menos de un caso. Además, viene de errores
  distintos: A.1 detecta 2 incidentes UWF más, pero tiene 7 falsos positivos BGL más.
- La variante supera a B.1 con cazador por un solo caso: no tuvo el falso positivo UWF.

## 2. Matrices de confusión

| Configuración | BGL total | BGL balanceado | BGL natural | UWF total | UWF visible | UWF sigiloso |
|---|---|---|---|---|---|---|
| A.1 | VP 8, FP 10, VN 6, FN 0 | VP 2, FP 1, VN 1 | VP 6, FP 9, VN 5 | VP 6, FP 0, VN 12, FN 6 | VP 6, VN 6 | FN 6, VN 6 |
| B | VP 7, FP 3, VN 13, FN 1 | VP 2, FP 1, VN 1 | VP 5, FP 2, VN 12, FN 1 | VP 4, FP 1, VN 11, FN 8 | VP 4, FP 1, VN 5, FN 2 | FN 6, VN 6 |
| B.1 con cazador | VP 7, FP 3, VN 13, FN 1 | VP 2, FP 1, VN 1 | VP 5, FP 2, VN 12, FN 1 | VP 4, FP 1, VN 11, FN 8 | VP 4, FP 1, VN 5, FN 2 | FN 6, VN 6 |
| B.1 auditor reforzado | VP 7, FP 3, VN 13, FN 1 | VP 2, FP 1, VN 1 | VP 5, FP 2, VN 12, FN 1 | VP 4, FP 0, VN 12, FN 8 | VP 4, VN 6, FN 2 | FN 6, VN 6 |
| Agente único B | VP 7, FP 3, VN 13, FN 1 | VP 2, FP 1, VN 1 | VP 5, FP 2, VN 12, FN 1 | VP 4, FP 0, VN 12, FN 8 | VP 4, VN 6, FN 2 | FN 6, VN 6 |
| Agente único B.1 | VP 6, FP 3, VN 13, FN 2 | VP 2, FP 1, VN 1 | VP 4, FP 2, VN 12, FN 2 | VP 4, FP 0, VN 12, FN 8 | VP 4, VN 6, FN 2 | FN 6, VN 6 |

Detección UWF por táctica (las cuatro configuraciones B, B.1 y la variante, y ambos agentes únicos):
Discovery 3/3, Reconnaissance 0/6, Resource Development 1/3. A.1: Discovery 3/3, Reconnaissance 2/6,
Resource Development 1/3.

### Casos en que las configuraciones no coinciden

| Caso | Real | A.1 | B | B.1 cazador | B.1 auditor ref. | Único B | Único B.1 |
|---|---|---|---|---|---|---|---|
| bgl_des_natural_0003 | anómalo | sí | sí | sí | sí | sí | **no** |
| bgl_des_natural_0004 | anómalo | sí | no | no | no | no | no |
| bgl_des_natural_0006, 0007, 0010, 0011, 0015, 0017, 0019 | normal | **sí** | no | no | no | no | no |
| uwf_des_visible_0002 | malicioso | sí | no | no | no | no | no |
| uwf_des_visible_0004 | malicioso | sí | no | no | no | no | no |
| uwf_des_visible_0006 | benigno | no | no | **sí** | no | no | no |
| uwf_des_visible_0010 | benigno | no | **sí** | no | no | no | no |

Los demás 35 casos tienen el mismo veredicto en las seis configuraciones. Errores comunes a todas desde B:
FP BGL en `bgl_des_balanceado_0002`, `bgl_des_natural_0012` y `bgl_des_natural_0014` (fallas de hardware
o kernel calificadas como anomalía operativa); FN en los 6 sigilosos maliciosos y en `uwf_des_visible_0002` y
`0004` (reconocimiento DNS).

## 3. Grupos del incidente: patrón de la lista asignado

En B.1 con cazador, el patrón lo asigna el cazador y el auditor confirma o descarta el hallazgo si es alto o
medio. En la variante, el patrón lo asigna el propio auditor en `evaluacion_grupos`. Columna "eventos":
categoría con que se citaron las filas del incidente en el resultado final.

| Caso | Táctica | Grupo (filas del incidente) | B.1 cazador: nivel / patrón / auditor | B.1 auditor reforzado: patrón | Veredicto B.1 / variante |
|---|---|---|---|---|---|
| uwf_des_sigiloso_0000 | Resource Development | G08 (3) | medio / puerto_no_estandar / descartado | ninguno | FN / FN |
| uwf_des_sigiloso_0001 | Reconnaissance | G09 (5) | bajo / ninguno / — | ninguno | FN / FN |
| uwf_des_sigiloso_0002 | Resource Development | G08 (5) | bajo / ninguno / — | ninguno | FN / FN |
| uwf_des_sigiloso_0003 | Reconnaissance | G10 (5) | bajo / ninguno / — | ninguno | FN / FN |
| uwf_des_sigiloso_0004 | Reconnaissance | G09 (3) | bajo / ninguno / — | ninguno | FN / FN |
| uwf_des_sigiloso_0005 | Reconnaissance | G08 (3) | bajo / ninguno / — | ninguno | FN / FN |
| uwf_des_visible_0000 | Discovery | G11 (60) | alto / barrido_descubrimiento_servicios / confirmado | barrido_descubrimiento_servicios | VP / VP |
| uwf_des_visible_0001 | Discovery | G10 (60) | alto / barrido_descubrimiento_servicios / confirmado | barrido_descubrimiento_servicios | VP / VP |
| uwf_des_visible_0002 | Reconnaissance | G10 (60) | medio / enumeracion_reconocimiento_dns / descartado | enumeracion_reconocimiento_dns | FN / FN |
| uwf_des_visible_0003 | Discovery | G09 (60) | alto / barrido_descubrimiento_servicios / confirmado | barrido_descubrimiento_servicios | VP / VP |
| uwf_des_visible_0004 | Reconnaissance | G08 (28) | bajo / ninguno / — | ninguno | FN / FN |
| uwf_des_visible_0005 | Resource Development | G04 (60) | alto / barrido_descubrimiento_servicios / confirmado | barrido_descubrimiento_servicios | VP / VP |

- Los dos evaluadores asignaron el mismo patrón a los 12 grupos del incidente. La única diferencia fue
  `uwf_des_sigiloso_0000`: el cazador marcó `puerto_no_estandar` con nivel medio y el auditor lo descartó.
- En `uwf_des_visible_0002`, los dos reconocieron la enumeración DNS en el grupo del incidente, pero el
  veredicto quedó en normal: el auditor de B.1 descartó el hallazgo medio y el auditor reforzado no lo
  consideró suficiente.
- Ningún grupo de casos benignos UWF recibió un patrón distinto de `ninguno`, ni en B.1 ni en la variante.
  En la variante, el auditor evaluó 161 grupos en 38 casos y no omitió ninguno: 156 `ninguno`, 4
  `barrido_descubrimiento_servicios` (los 4 detectados) y 1 `enumeracion_reconocimiento_dns` (visible_0002).

## 4. Evidencia de los incidentes UWF (solo eventos con categoría "incidente")

| Configuración | Cobertura media (12 maliciosos) | Cobertura media (detectados) | Precisión media (detectados) |
|---|---:|---:|---:|
| A.1 | 0,000 (no tenía categorías de eventos) | 0,000 | 0,000 |
| B, B.1 con cazador, B.1 auditor reforzado, ambos agentes únicos | 0,333 | 1,000 | 1,000 |

En los 4 detectados, las configuraciones B y B.1 citan como incidente las 60 filas del incidente y ninguna otra.

## 5. Comportamiento de cazador y auditor

| | B | B.1 con cazador | B.1 auditor reforzado |
|---|---|---|---|
| Casos con grupos examinados | 38 | 38 | 38 (por el auditor) |
| Hallazgos alto / medio / bajo | 4 / 1 / 156 | 4 / 2 / 155 | — |
| Revisiones del auditor | 4 confirmados | 4 confirmados, 2 descartados | — |
| Correcciones tras el auditor | 1 (visible_0007, acertada) | 1 (visible_0010, acertada) | 2 (sigiloso_0007 y visible_0006, acertadas) |
| Replanificaciones | 0 | 0 | 0 |
| UWF benignos como "anomalía operativa" | 0 | 0 | 0 |

- **Falso positivo de B.1 con cazador (`uwf_des_visible_0006`).** El triage lo marcó como incidente en las dos
  corridas de B.1, la interrumpida y la repetida: la memoria contrastiva le mostró un reconocimiento DNS
  histórico (`uwf_des_visible_0004`). El cazador dejó los 4 grupos en "bajo", pero el auditor mantuvo el
  incidente. En la variante, el triage volvió a marcarlo y el auditor reforzado lo corrigió a normal tras
  evaluar los grupos. Lo mismo ocurrió con `uwf_des_sigiloso_0007`.
- La variante corrigió los 2 falsos positivos de su triage. B.1 con cazador corrigió 1 de 2.
- A.1 calificó los 12 UWF benignos como "anomalía operativa"; desde B, ninguno.

## 6. Tokens, tiempo y costo promedio por caso

| Configuración | Dataset | Llamadas | Entrada | Salida | Razonamiento | Segundos | USD / caso | USD total |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| A.1 | BGL | 5,00 | 11 800 | 1 570 | 3 386 | 47,5 | 0,0274 | 0,66 |
| A.1 | UWF | 5,75 | 88 080 | 1 619 | 4 703 | 61,9 | 0,0898 | 2,15 |
| B | BGL | 5,62 | 14 581 | 1 871 | 3 422 | 52,0 | 0,0308 | 0,74 |
| B | UWF | 6,17 | 91 871 | 2 119 | 4 673 | 65,4 | 0,0944 | 2,26 |
| B.1 con cazador | BGL | 5,62 | 15 574 | 1 754 | 3 344 | 54,3 | 0,0308 | 0,74 |
| B.1 con cazador | UWF | 6,17 | 94 628 | 2 157 | 5 540 | 72,2 | 0,0998 | 2,40 |
| B.1 auditor reforzado | BGL | 5,00 | 15 048 | 1 502 | 2 801 | 45,4 | 0,0274 | 0,66 |
| B.1 auditor reforzado | UWF | 5,21 | 96 656 | 1 717 | 5 207 | 64,5 | 0,0985 | 2,36 |
| Agente único B | BGL | 1,00 | 8 859 | 807 | 1 551 | 18,5 | 0,0155 | 0,37 |
| Agente único B | UWF | 1,00 | 75 630 | 640 | 2 255 | 23,6 | 0,0676 | 1,62 |
| Agente único B.1 | BGL | 1,00 | 9 055 | 854 | 1 946 | 20,5 | 0,0173 | 0,41 |
| Agente único B.1 | UWF | 1,00 | 77 790 | 737 | 2 711 | 27,7 | 0,0713 | 1,71 |

Tokens de entrada promedio por nodo (UWF):

| Nodo | A.1 | B | B.1 cazador | B.1 auditor ref. |
|---|---:|---:|---:|---:|
| Planificador | 5 887 | 6 145 | 5 887 | 5 887 |
| Triage | 14 661 | 10 179 | 10 332 | 10 331 |
| Cazador | — | 4 284 | 6 739 | — |
| Selector | 355 | 299 | 298 | 288 |
| Mitigación | 1 257 | 1 380 | 1 578 | 1 539 |
| Auditor | 65 919 | 69 584 | 69 794 | 78 611 |

Tokens de entrada promedio por nodo (BGL):

| Nodo | A.1 | B | B.1 cazador | B.1 auditor ref. |
|---|---:|---:|---:|---:|
| Planificador | 1 127 | 1 127 | 1 127 | 1 127 |
| Triage | 3 968 | 4 221 | 4 416 | 4 416 |
| Cazador | — | 1 192 | 1 577 | — |
| Selector | 289 | 270 | 265 | 270 |
| Mitigación | 1 075 | 1 452 | 1 671 | 1 585 |
| Auditor | 5 341 | 6 319 | 6 519 | 7 651 |

El cazador se activa en 38 de 48 casos: en UWF, en todos; en BGL, en 0,6 de cada caso en promedio. La
variante elimina esa llamada y suma unos 8 800 tokens de entrada al auditor en UWF (unos 1 100 en BGL):
cuesta casi lo mismo que B.1 con cazador y tarda menos.

## 7. Casos históricos recuperados

- **Sigilosos maliciosos.** En B, 3 de los 6 recuperaban algún caso malicioso entre sus 3 vecinos. Desde
  B.1, la consulta contrastiva entrega siempre 2 normales y 2 maliciosos. Aun así, los 6 siguen siendo FN en
  todas las configuraciones, y el auditor de la variante asignó `ninguno` a todos sus grupos del incidente.
- **Falsos positivos BGL** (los mismos 3 desde B): `bgl_des_balanceado_0002` y `bgl_des_natural_0012`
  recuperan como más parecidos 2 casos anómalos; en `bgl_des_natural_0014`, el más parecido es normal, seguido de 2 anómalos.
- **Efecto secundario de la memoria contrastiva:** al traer siempre casos maliciosos, empujó al triage a
  marcar como incidente lotes benignos UWF con DNS (`uwf_des_visible_0006` en B.1 y, en la variante, también
  `uwf_des_sigiloso_0007`). El auditor de la variante corrigió los dos; en B.1 con cazador, el primero
  quedó como falso positivo.
- **Agente único B.1:** pierde `bgl_des_natural_0003` frente a la Fase B. Es la única diferencia del agente
  único entre B y B.1.

## 8. Incidentes de ejecución y gasto

- B.1: 2 corridas interrumpidas por suspensión del equipo y 6 fallidas por falta de crédito. Todas
  quedaron apartadas, sin usarse en las métricas, y se repitieron desde cero (`desarrollo_fase_b1/bitacora.md`).
- Variante: apagado inesperado del equipo a las 13:09:50, entre dos casos. No hubo corrida parcial; se
  reanudó con el mismo código (`desarrollo_fase_b1_auditor_reforzado/bitacora.md`).
- Ninguna llamada fallida ni error de API en las corridas válidas; todas con `gemini-3.8-flash`.
- Gasto de las corridas válidas: B.1 NODEX USD 3,14; agente único B.1 USD 2,13; variante USD 3,02 (tope 8).
  Corridas descartadas de B.1: USD 0,14.
