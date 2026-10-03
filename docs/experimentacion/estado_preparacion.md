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

## 2. Registro de fases

| Fase | Estado | Autorización recibida | Entregables | Commit | Pendientes |
|---|---|---|---|---|---|
| 0 — Aislar el trabajo y fijar el punto de partida | PREPARADA_SIN_EJECUTAR | Sí (3-oct-2026) | Rama `preparacion-entorno-pruebas`, worktree aislado, commit de origen documentado, este registro | `26832c2` | Verificaciones de entorno que exigen ejecución (§6) |
| 1 — Definir el protocolo y los contratos experimentales | PREPARADA_SIN_EJECUTAR | Sí (3-oct-2026) | `docs/experimentacion/protocolo.md`; contratos en `src/experimentation/contracts/`; 4 archivos de prueba en `tests/experimentation/` (escritos, sin ejecutar) | `d3a3234` | 6 decisiones académicas pendientes (§8) |
| 2 — Preparar datasets y casos con segmentación válida | PENDIENTE_AUTORIZACION | No | — | — | UWF-ZeekDataFall22 no incorporado localmente |
| 3 — Preparar ground truth y conocimiento aislado | PENDIENTE_AUTORIZACION | No | — | — | Catálogo MITRE no versionado; ChromaDB sin documentos |
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

## 7. Pendientes y riesgos registrados al cierre de la Fase 0

- **UWF-ZeekDataFall22 no está incorporado localmente.** Queda como
  dependencia bloqueante para su dimensión hasta que se disponga del
  dataset y sus etiquetas (Fase 2).
- **Catálogo MITRE no versionado y ChromaDB sin documentos.** La Fase 3
  necesitará una decisión explícita: descargar el catálogo (con
  autorización) o declarar la dimensión MITRE como no preparable.
- **Rendimiento HDFS del detector.** Limitación conocida y medida en la
  evidencia de la fase 6 anterior (recall 0,10 en balanceado; 0,00 a
  prevalencia 3,1%). Por indicación de la usuaria (3-oct-2026) **no es
  bloqueante** de esta preparación; se registra como riesgo a considerar al
  interpretar la campaña futura, no como defecto a corregir acá.
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

D-1 y D-6 son las únicas que bloquean el avance inmediato: la Fase 2 no
puede particionar sin D-1, y la Fase 3 no puede dimensionar la anotación
humana sin D-6.
