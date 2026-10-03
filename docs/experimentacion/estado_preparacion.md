# Estado de preparación del espacio de pruebas de NODEX

**Plan de referencia:** `plan_preparación de pruebas_revisado.md` (2 de octubre de 2026).
**Alcance autorizado:** preparar la infraestructura experimental. **No ejecutar pruebas, experimentos ni llamadas a modelos.**
**Rama de preparación:** `preparacion-entorno-pruebas`.
**Worktree de preparación:** `C:\Users\antop\Desktop\ProyectoTituloNodex-pruebas`.
**Checkout original (intacto):** `C:\Users\antop\Desktop\NODEX`, rama `main`.

> `PREPARADA_SIN_EJECUTAR` significa que los artefactos existen y fueron
> revisados estáticamente. **No** significa que el sistema haya superado
> ninguna prueba.

## 1. Punto de partida

| Elemento | Valor |
|---|---|
| Repositorio (origin) | `https://github.com/pazz09/ProyectoTituloNodex.git` |
| Commit de origen | `6adc3436cdb9de38f5bf310fa06beb0f37247aac` |
| Rama de origen | `main`, sincronizada con `origin/main` |
| Commit de origen (fecha / autor / asunto) | 2026-09-25 02:26:42 -0300 / Felipe Bravo Romo / `docs: cerrar fase 6 con evidencia reproducible` |
| Tipo de checkout | Completo, no *shallow* (68 commits de historial) |
| Estado del árbol al ramificar | Limpio (sin cambios locales ni archivos sin seguimiento) |
| Worktrees previos | Ninguno (solo el checkout original) |

### Decisión sobre el ZIP (Fase 0, acción 2 del plan)

El plan pide comparar la versión del repositorio con un ZIP y documentar
cuál será el punto de partida. **No se encontró ningún ZIP** en el
directorio del proyecto ni en el escritorio, y la consulta al respecto no
recibió indicación de un archivo alternativo.

**Decisión registrada:** se adopta el repositorio real (`origin/main` @
`6adc343`) como punto de partida y fuente de verdad. Si más adelante
aparece un ZIP que represente otra versión, la diferencia debe
reconciliarse explícitamente **antes** de la Fase 2, porque afectaría la
procedencia de los casos.

### Actualización del punto de partida (3-oct-2026, al abrir la Fase 2)

`origin/main` avanzó a **`b0fe5de` "Dataset UWF"** (Felipe Bravo Romo), que
agrega los 13 archivos Parquet de UWF-ZeekDataFall22 en
`data/logs/UWF-ZeekDataFall22-parquet/` (44 862 135 bytes). Se trajo con
`git merge --ff-only` al `main` local y se integró a esta rama con un merge
(`bbec894`), de modo que el dataset está disponible tanto en el checkout
original como en el worktree de preparación.

El punto de partida de la Fase 2 en adelante es por lo tanto `b0fe5de`, no
`6adc343`. La Fase 0 y la Fase 1 se cerraron sobre `6adc343` y no se
rehacen: no dependen del dataset.

## 2. Registro de fases

| Fase | Estado | Autorización recibida | Entregables | Commit | Pendientes |
|---|---|---|---|---|---|
| 0 — Aislar el trabajo y fijar el punto de partida | PREPARADA_SIN_EJECUTAR | Sí (3-oct-2026) | Rama `preparacion-entorno-pruebas`, worktree aislado, commit de origen documentado, este registro | `26832c2` | Verificaciones de entorno que exigen ejecución (§6) |
| 1 — Definir el protocolo y los contratos experimentales | PREPARADA_SIN_EJECUTAR | Sí (3-oct-2026) | `docs/experimentacion/protocolo.md`; contratos en `src/experimentation/contracts/`; 4 archivos de prueba en `tests/experimentation/` (escritos, sin ejecutar) | `d3a3234` | 6 decisiones académicas pendientes (§8) |
| 2 — Preparar datasets y casos con segmentación válida | PREPARADA_SIN_EJECUTAR (HDFS y BGL); UWF BLOQUEADA | Sí (3-oct-2026) | `docs/experimentacion/hallazgos_datasets.md`; `src/experimentation/datasets/` (6 módulos); 232 casos + 232 referencias + 3 manifiestos en `experiments/`; 2 archivos de prueba (escritos, sin ejecutar) | (se registra abajo) | UWF requiere un motor Parquet (autorización de instalación); D-7 a D-10 |
| 3 — Preparar ground truth y conocimiento aislado | PENDIENTE_AUTORIZACION | No | — | — | Catálogo MITRE no versionado; ChromaDB sin documentos. **Menos trabajo del previsto:** UWF trae `label_binary`, `label_tactic`, `label_technique` y `uid`, así que D1, D2 y D3 son derivables del dataset (ver hallazgos §4) |
| 4 — Hacer evaluables las salidas de NODEX | PENDIENTE_AUTORIZACION | No | — | — | — |
| 5 — Implementar los evaluadores externos | PENDIENTE_AUTORIZACION | No | — | — | Rúbrica humana del reporte por definir |
| 6 — Preparar telemetría y configuración congelable | PENDIENTE_AUTORIZACION | No | — | — | — |
| 7 — Preparar almacenamiento y orquestación sin ejecución | PENDIENTE_AUTORIZACION | No | — | — | — |
| 8 — Implementar el agente único de comparación | PENDIENTE_AUTORIZACION | No | — | — | — |
| 9 — Preparar consolidación y protocolo comparativo | PENDIENTE_AUTORIZACION | No | — | — | Decisión: comparación externa experimental o bibliográfica |
| 10 — Entregar el kit del piloto, sin ejecutarlo | PENDIENTE_AUTORIZACION | No | — | — | — |

## 3. Runtime y dependencias declaradas

Obtenidas **leyendo archivos del repositorio**, no ejecutando intérpretes.

| Componente | Versión declarada | Fuente del dato |
|---|---|---|
| Python | 3.13 | `.github/workflows/ci.yml` |
| Node.js | 22 | `.github/workflows/ci.yml` |
| pnpm | 10.33.0 | `frontend/package.json` (`packageManager`) |
| Dependencias backend directas | 16 pines exactos (`==`) | `requirements.txt` |
| Cierre transitivo backend | 141 paquetes | `constraints.txt` |
| Next.js / React / TypeScript | 16.3.3 / ^19 / 5.7.3 | `frontend/package.json` |

No existen `.python-version`, `pyproject.toml`, `runtime.txt`, `.nvmrc` ni
`.tool-versions`: la única declaración de versiones de runtime vive en el
workflow de CI.

## 4. Instrucciones de instalación preparadas — **NO EJECUTADAS**

Backend, dentro del worktree de preparación y con un entorno virtual
**propio** (no reutilizar el `.venv` del checkout original):

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Unix: source .venv/bin/activate
pip install -r requirements.txt -c constraints.txt
```

Frontend:

```bash
cd frontend
pnpm install --frozen-lockfile
```

Configuración: copiar `.env.example` a `.env`. Las credenciales reales solo
hacen falta para una futura ejecución autorizada; **la preparación no las
necesita** y no deben quedar en este worktree hasta entonces.

Ninguno de estos comandos se ejecutó en la Fase 0. Cualquier instalación o
descarga debe presentarse en la solicitud de permiso de la fase que la
necesite.

## 5. Aislamiento verificado por inspección

| Comprobación | Resultado |
|---|---|
| `.venv` heredado | No existe en el worktree |
| `.env` / credenciales heredadas | No existen en el worktree |
| `frontend/node_modules` | No existe en el worktree |
| `data/chroma/`, `data/historial.db`, `data/ip_reputation_cache.json` | No viajan al worktree (ignorados por git) |
| Checkout original | Sigue en `main` @ `6adc343`, árbol limpio |

Datos versionados **sí** disponibles en el worktree:

- `data/logs/BGL_2k.log`
- `data/logs/HDFS_2k.log`
- `data/labels/hdfs_anomaly_label_2k.csv`
- `data/mitre_attack/provenance.json` — solo la procedencia (ATT&CK v19.2,
  697 técnicas, 475 subtécnicas, corrida 2026-09-11). **El catálogo STIX en
  sí no está versionado en el repositorio.**

## 6. Información del entorno **no comprobada mediante ejecución**

Requerido por la acción 6 de la Fase 0. Nada de lo siguiente fue verificado
y no debe presentarse como verificado:

1. Versiones de Python, Node y pnpm realmente instaladas en la máquina
   (solo se leyeron las declaradas en archivos).
2. Que `pip install -r requirements.txt -c constraints.txt` resuelva dentro
   de este worktree.
3. Que la suite del backend pase en este worktree. (En el checkout original
   el último conteo conocido es 544 aprobadas, pero no se reverificó acá y
   no corresponde a esta rama.)
4. Que el frontend instale, compile o pase lint / typecheck / test en este
   worktree.
5. Disponibilidad, cuota o credenciales válidas de Gemini, AbuseIPDB y NVD.
6. Estado real de ChromaDB. El diagnóstico del plan indica cuatro
   colecciones con cero documentos; en esta fase no se abrió ninguna base.
7. Que el catálogo MITRE ATT&CK sea obtenible: exigiría una descarga, que
   requiere autorización en la fase correspondiente.
8. Ejecución remota del workflow de CI sobre esta rama.

Agregado al cerrar la Fase 2:

9. Que los 232 casos generados pasen por el preprocesamiento de NODEX.
   Llamar a `preprocesar()` sobre un caso es ejecutar NODEX sobre un caso de
   prueba, que el protocolo prohíbe sin autorización. La segmentación se
   validó contra el archivo original, no contra el pipeline.
10. Que las pruebas de `tests/experimentation/` pasen. Son 4 + 2 archivos
    escritos y revisados estáticamente, nunca ejecutados.
11. Nada de los **datos** de UWF: solo se leyeron los metadatos del footer
    Parquet. No se leyó una sola fila.
12. Que las etiquetas de HDFS, BGL y UWF sean correctas. Se toman tal como
    vienen; auditar la curaduría de los datasets está fuera de alcance.

## 7. Pendientes y riesgos registrados al cierre de la Fase 0

- **UWF-ZeekDataFall22 no está incorporado localmente.** *Resuelto el
  3-oct-2026:* llegó en `b0fe5de`. Lo que queda es poder leerlo (viene en
  Parquet y falta un motor).
- **Catálogo MITRE no versionado y ChromaDB sin documentos.** La Fase 3
  necesitará una decisión explícita: descargar el catálogo (con
  autorización) o declarar la dimensión MITRE como no preparable. *Matizado
  el 3-oct-2026:* la **referencia** MITRE de UWF ya no depende del catálogo
  —viene en `label_tactic` / `label_technique`—; el catálogo sigue haciendo
  falta para el RAG que usa NODEX, no para evaluar.
- **Rendimiento HDFS del detector.** *Reinterpretado el 3-oct-2026, con
  medición:* no es un problema de rendimiento. `HDFS_2k.log` tiene 1,00
  líneas por bloque, así que la secuencia de eventos que define la etiqueta
  de anomalía no está en el archivo y la tarea no es resoluble por ningún
  sistema. Es una amenaza a la **validez** de esa medición, no una
  limitación del detector. Detalle y las tres salidas posibles en
  `hallazgos_datasets.md` §1 (decisión D-7). Sigue sin ser bloqueante de la
  preparación, por indicación de la usuaria.
- **Referencias humanas pendientes.** Las anotaciones semánticas que el
  dataset no provee requieren revisión humana. El plan considera el ERR de
  UWF ya revisado; el resto queda como `referencia_pendiente` hasta su
  aprobación.

## 8. Decisiones académicas pendientes

Registradas en la Fase 1. El protocolo las trata como
`DECISION_PENDIENTE`: **ningún umbral está fijado** y el código no debe
suplirlas con un valor por defecto. Detalle y justificación en
`docs/experimentacion/protocolo.md` §10.

| # | Decisión | Fase que la necesita |
|---|---|---|
| D-1 | Proporción desarrollo / evaluación | 2 |
| D-2 | Número de repeticiones `N` por caso | 7 |
| D-3 | Umbrales de aceptación por dimensión | 5 (y la interpretación final) |
| D-4 | Escala de la rúbrica de reporte y nº de evaluadores humanos | 3 y 5 |
| D-5 | Comparación externa: experimental o bibliográfica | 9 |
| D-6 | Tamaño de la submuestra de D4 (reporte) por dataset | 3 |
| D-7 | Qué hacer con la detección en HDFS: muestra nueva, `no_aplica`, o reportar con la limitación | Interpretación de D1 en HDFS |
| D-8 | Si los casos de UWF se componen (malicioso de 2022 sobre fondo benigno de 2021) y si se rebasan los timestamps | Generación de casos de UWF |
| D-9 | Si los registros `Duplicate` de UWF se excluyen del caso o solo del ground truth | Ground truth de UWF (Fase 3) |
| D-10 | Si se amplía a muestras mayores de HDFS/BGL o se acepta el techo de 2 000 líneas | Tamaño de la campaña |

D-1 quedó resuelta (30/70) y la Fase 2 ya particionó con ella. D-6 sigue
bloqueando la Fase 3. D-7 a D-10 abrieron en la Fase 2 y están
fundamentadas con medición en `hallazgos_datasets.md`; D-8 y D-9 bloquean
la generación de casos de UWF, y D-7 y D-10 afectan la interpretación, no
el avance.
