# Guía de anotación del ground truth

Documento de la Fase 3, acción 3. Define **cómo se construye una
referencia** y, sobre todo, qué no puede entrar en ella.

> **Regla que no admite excepciones.** La referencia nunca se construye con
> la salida de NODEX, ni total ni parcialmente, ni "para ahorrar tiempo", ni
> "porque esa salida era correcta". Usar la salida del sistema evaluado como
> ground truth hace que el sistema se mida contra sí mismo y el resultado no
> dice nada. El contrato lo impide por código: `GroundTruth` rechaza
> `anotacion["fuente"] == "nodex"`.

## 1. Las tres procedencias admitidas

| `anotacion["fuente"]` | Qué significa | Quién la aprueba |
|---|---|---|
| `dataset` | La etiqueta viene del dataset, con una regla de normalización documentada | Nadie: es verificable releyendo el dataset |
| `revision_humana` | Anotación semántica que el dataset no provee | La persona que anota, identificada |
| *(prohibida)* `nodex` | — | — |

Una dimensión sin referencia aprobada queda **`referencia_pendiente`**. No
se puntúa, no se cuenta como acierto y bloquea el cierre de esa dimensión.
No existe la opción de "asumirla correcta".

## 2. Normalización de las etiquetas de detección

Se conserva la etiqueta original **y** la normalizada, porque la
normalización es una decisión que hay que poder auditar.

### HDFS (detección operativa → `hay_anomalia`)

| Original (`hdfs_anomaly_label_2k.csv`) | Normalizada |
|---|---|
| `Anomaly` | `anomalo` |
| `Normal` | `normal` |

Un grupo es positivo si **alguno** de sus bloques es `Anomaly`.

### BGL (detección operativa → `hay_anomalia`)

| Original (primer token de la línea) | Normalizada |
|---|---|
| `-` | `normal` |
| cualquier código (`KERNDTLB`, `KERNSTOR`, `APPSEV`, …) | `anomalo` |

Una ventana es positiva si **alguna** de sus líneas trae un código. El
código original se conserva en `etiqueta_original`; hay 12 distintos.

### UWF (detección de **seguridad** → `hay_incidente`)

| Original (`label_binary`) | Normalizada |
|---|---|
| `False` | `normal` (= `BENIGN`) |
| `True` | `anomalo` (= `MALICIOUS`) |
| `Duplicate` | **excluido del conjunto** (decisión D-9) |

La distinción entre detección operativa y de seguridad no es cosmética:
comparar `hay_incidente` contra etiquetas de anomalía de sistema mide la
pregunta equivocada. Ya pasó en este proyecto y dio recall 0,0 en BGL por
una razón metodológica, no por una falla del modelo.

## 3. Eventos relevantes (dimensión D2, reconstrucción)

La referencia es `core_event_uids`: el conjunto de identificadores de los
eventos que **constituyen** el incidente.

### UWF — derivada del dataset, no anotada a mano

`core_event_uids` son los `uid` de las conexiones del incidente inyectado.
Se conocen con certeza porque el caso se compuso: el incidente se eligió y
se insertó, así que no hay nada que inferir.

El plan considera la revisión humana del ERR de UWF como **completada** y no
abre una nueva etapa de anotación semántica para esos casos.

Condiciones que hacen válido el matching exacto, y que ya se verificaron:

1. `uid` es único dentro de cada caso y entre casos (31 200 `uid`, ninguno
   repetido).
2. Las filas que comparten `uid` en el dataset son la misma conexión
   —coinciden en los 9 campos que identifican el flujo—, así que deduplicar
   por `uid` no pierde eventos.

Un evento reconstruido cuenta como acierto **solo** si su `uid` está en
`core_event_uids`. No se aplican tolerancias ni equivalencias: existe un
identificador estable y usarlo laxamente inventaría aciertos.

### HDFS y BGL — `no_aplica`

Ninguno de los dos trae un identificador estable de evento. Declarar la
dimensión y después puntuarla con equivalencias aproximadas sería inventar
la referencia, así que queda `no_aplica` **por diseño**, fuera de todo
denominador.

## 4. Atribución MITRE (dimensión D3)

La referencia se lleva **por nivel**, en `estado_mitre_por_nivel`. Una
táctica no se convierte automáticamente en una técnica, ni una técnica en
una subtécnica.

| Nivel | UWF | HDFS / BGL |
|---|---|---|
| Táctica | `evaluable` — de `label_tactic` | `no_aplica` |
| Técnica | `evaluable` — de `label_technique` | `no_aplica` |
| Subtécnica | **`no_aplica`** | `no_aplica` |

La subtécnica es `no_aplica` en UWF porque el dataset no la trae: sus 22
etiquetas de técnica son todas `T####` sin punto. **No se infiere una
subtécnica para completar el ground truth**, aunque la técnica padre tenga
subtécnicas obvias en el catálogo.

Dos verificaciones hechas sobre esta referencia:

- Las 22 técnicas de UWF **existen** en el catálogo ATT&CK embebido (697
  documentos: 222 técnicas padre y 475 subtécnicas, v19.2). Si alguna
  faltara, el RAG no podría recuperarla nunca y D3 castigaría al sistema
  por una ausencia del catálogo.
- El contrato rechaza por código una incoherencia: un nivel marcado
  `no_aplica` que a la vez tenga referencias de ese nivel.

Una conexión puede tener más de una táctica (33 `uid` las tienen tras
excluir los `Duplicate`). En esos casos la referencia es el **conjunto** de
tácticas, y la métrica es de conjuntos, no de etiqueta única.

### Costo conocido de la decisión D-9

Excluir las filas `Duplicate` deja a 2 899 `uid` con una sola táctica
cuando tenían dos, porque la fila `Duplicate` era la segunda atribución. La
referencia resultante es **conservadora**: puede subcontar un acierto,
nunca inventarlo. Hay que tenerlo presente al leer el recall de D3.

## 5. Calidad del reporte (dimensión D4)

**No hay reporte de referencia.** El plan prohíbe expresamente ampliar el
ERR con `gold_claims`, `expected_facts`, reportes gold, conclusiones o
recomendaciones esperadas. La razón es que un texto gold convertiría una
cuestión de juicio en una comparación de cadenas, y mediría parecido
redaccional en vez de calidad.

Se evalúa con **rúbrica humana** (decisión D-4): **0–3 por criterio**, dos
evaluadores, y la concordancia entre ellos reportada.

| Criterio | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| Completitud | No menciona el incidente ni los eventos núcleo | Menciona el incidente pero omite la mayoría de los eventos núcleo | Cubre el incidente y la mayoría de los eventos núcleo | Cubre el incidente y todos los eventos núcleo relevantes |
| Corrección factual | Afirmaciones centrales falsas respecto del log | Alguna afirmación central falsa | Afirmaciones correctas con imprecisiones menores | Todas las afirmaciones verificables contra el log son correctas |
| Coherencia con la evidencia | Las conclusiones no se siguen de lo citado | Cita evidencia pero las conclusiones la exceden | Conclusiones sostenidas, con algún salto | Cada conclusión se apoya en evidencia citada |
| Claridad | Ininteligible para un analista | Requiere releer para entender qué pasó | Comprensible en una lectura | Comprensible y ordenado, útil tal como está |
| Información no sustentada | Abundante contenido inventado | Varias afirmaciones sin respaldo en el log | Alguna afirmación sin respaldo | Nada que no esté respaldado por el log |

Notas de aplicación:

- El último criterio se puntúa **al revés de la intuición**: 3 es *ausencia*
  de información no sustentada. Está redactado así para que en los cinco
  criterios "más alto es mejor" y el promedio tenga sentido.
- Los evaluadores puntúan **sin saber qué arquitectura** produjo el
  reporte. Si saben cuál es NODEX, la expectativa sesga.
- Los evaluadores **sí** ven el caso y su ground truth: sin la referencia no
  se puede juzgar corrección factual.
- La submuestra está preseleccionada en
  `experiments/subconjuntos/rubrica.json`, con semilla, **antes** de que
  exista cualquier resultado.
- Si los dos evaluadores difieren en más de 1 punto en un criterio, se
  registra el desacuerdo y se informa; **no** se promedia silenciosamente ni
  se convoca a un tercero para "romper el empate" después de ver los
  números.

## 6. Relaciones de evidencia

Toda afirmación del sistema que se puntúe tiene que poder rastrearse a
eventos concretos del caso:

| Qué afirma el sistema | Con qué se rastrea |
|---|---|
| Un evento reconstruido | su `uid`, que debe existir en el caso |
| Una táctica o técnica MITRE | `evidence_uids`, no vacío |
| Una línea del reporte | la evidencia citada en el propio reporte |

Y en la otra dirección, cada línea de un caso es rastreable al dataset por
su `RegistroProcedencia`: archivo de origen, número de línea original,
grupo y `uid`. En los casos compuestos de UWF, el `ts` original se recupera
restando el `offset_rebase_segundos` que el caso declara.

Una atribución MITRE sin `evidence_uids` **no se puntúa como acierto**: una
técnica adivinada sin evidencia y una técnica fundamentada no son el mismo
resultado.

## 7. Qué está aprobado hoy y qué no

| Dataset | Detección | Reconstrucción | MITRE | Reporte |
|---|---|---|---|---|
| HDFS | `evaluable` (dataset) | `no_aplica` | `no_aplica` | `referencia_pendiente` |
| BGL | `evaluable` (dataset) | `no_aplica` | `no_aplica` | `referencia_pendiente` |
| UWF | `evaluable` (dataset) | `evaluable` (dataset) | `evaluable` táctica y técnica; `no_aplica` subtécnica | `referencia_pendiente` |

`reporte` está `referencia_pendiente` en los tres: la rúbrica está definida
y su submuestra elegida, pero **nadie puntuó nada todavía**. Esa dimensión
no se cierra hasta que los dos evaluadores hayan trabajado.
