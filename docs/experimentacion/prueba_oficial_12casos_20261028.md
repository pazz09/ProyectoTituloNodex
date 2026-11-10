# Prueba oficial de NODEX: 12 casos, una repetición

Solicitud del 28 de octubre de 2026. Esta solicitud autoriza ejecutar NODEX una vez por cada uno de los doce casos indicados y extraer sus datos para revisión posterior. Sustituye las restricciones de no ejecución/no implementación del inventario del 21 de octubre para este alcance. La evaluación y la interpretación de resultados siguen siendo posteriores a la extracción.

## Diseño y trazabilidad

- Configuración nueva: `oficial-12casos-r1-20261028`. No mezcla resultados de campañas anteriores.
- Solo arquitectura `nodex_multiagente`, repetición `1`, partición `evaluacion`.
- Orden: el de la lista solicitada, conservado en `selection.json`.
- Los doce tamaños y prefijos SHA-256 deben coincidir antes de ejecutar. El espacio tipográfico en `206525757 33d` se elimina para verificar `20652575733d`; el archivo no se modifica.
- Gemini `gemini-3.8-flash`, temperatura `0`, sin modelo de respaldo, sin enriquecimiento de reputación externa y con consultas NVD bloqueadas y respaldo local registrado. Es la política experimental ya usada en el repositorio y el modelo configurado en el entorno actual.
- Se reutilizan los agentes, el pipeline, el adaptador y la instrumentación existentes. No se modificó `src/`.
- Un proceso nuevo por caso, copia aislada de ChromaDB y caché de IP propia. No se carga ground truth durante la inferencia.
- Una corrida puede incluir múltiples llamadas al LLM, correcciones, replanificaciones y reintentos internos ya presentes en NODEX. No se agregan repeticiones del caso ni reintentos de corridas fallidas.
- El marcador exclusivo `<run_id>.started.json` se crea antes de lanzar el caso. Una reanudación omite todos los casos iniciados. Un intento interrumpido sin resultado requiere inspección manual: nunca se repite automáticamente.
- Se mantiene el límite existente de dos horas por corrida y la parada tras tres fallas consecutivas de infraestructura.

`experiments/config/config_oficial-12casos-r1-20261028.json` congela parámetros, commit y hashes de los agentes. `experiments/ejecucion/oficial-12casos-r1-20261028/environment.json` registra la configuración efectiva, versiones instaladas y hashes de los archivos Python de `src/` y `tools/`. Como los scripts y artefactos nuevos aún no están confirmados en Git, el árbol completo no es limpio; se conserva este hecho y el código exacto se copia al paquete de extracción. No se presenta el commit por sí solo como descripción suficiente del experimento.

## Entorno

El ejecutable original referenciado por `.venv/pyvenv.cfg` (`Python312/python.exe`, 3.12.10) ya no existe. Para esta campaña se usa el Python 3.12.14 disponible con las dependencias instaladas en `.venv/Lib/site-packages` mediante `PYTHONPATH`. No se alteraron `.venv`, `requirements.txt` ni `constraints.txt`. Las versiones realmente usadas quedan registradas; no debe asumirse que coinciden con el lock histórico.

Desde PowerShell, en la raíz del repositorio:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) '.venv/Lib/site-packages')
$env:PYTHONIOENCODING = 'utf-8'
$pythonNodex = 'C:/Users/felip/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'

# Preparación y comprobación de configuración, sin inferencia:
& $pythonNodex -u tools/run_official_experiment.py

# Campaña autorizada; no repite casos ya iniciados:
& $pythonNodex -u tools/run_official_experiment.py --execute

# Extracción, después de finalizar o detenerse la campaña:
& $pythonNodex tools/export_experimental_data.py

# Verificar las copias y proyecciones, y ejecutar las celdas de revisión sin inferencia:
& $pythonNodex tools/verify_experimental_export.py extracted_data/oficial-12casos-r1-20261028 --execute-notebook
```

Si ya existe la carpeta de extracción, el extractor falla sin sobrescribirla. Se puede indicar otra carpeta con `--output`; esto no ejecuta NODEX.

## Datos para los cinco escenarios

| Escenario | Archivos proyectados | Datos conservados |
|---|---|---|
| E1 Detección | `detection/` | Clasificación, veredictos, confianza, estado de ejecución y referencia separada |
| E2 Reconstrucción | `reconstruction/` | Eventos, secuencia temporal, evidencia, resumen del preprocesamiento, historial de planes y referencia separada |
| E3 Técnicas | `mitre/` | Atribuciones, justificaciones, evidencia, salida normalizada, candidatos RAG separados y referencia MITRE |
| E4 Reporte | `reports/` | Texto literal en Markdown y JSONL; secciones originales del estado |
| E5 Rendimiento | `performance/` | Telemetría completa, llamadas, tokens, modelos efectivos, duración por llamada cuando exista, consultas externas y contadores JSON; inicio y fin UTC observados por el lanzador y duración de pared |

El tiempo de pared del lanzador incluye la preparación aislada del caso y la finalización del proceso; no se confunde con `execution_time` del sistema. No se infiere tiempo por agente, consumo de CPU/RAM/GPU ni costo facturado.

## Entrega y revisión

La carpeta `extracted_data/oficial-12casos-r1-20261028/` contiene:

- `originals/`: copias verificadas byte a byte de entradas, metadatos, referencias, resultados normalizados, estados finales crudos, telemetría, consola, configuración y código.
- `manifest.json` y `manifest.csv`: rutas, tamaños, hashes de originales y copias, disponibilidad e identidad de cada corrida.
- `extraction.json`: reglas de conversión, versión del extractor, faltantes y límites.
- `run_status.jsonl`: una fila por caso solicitado, incluso cuando falta el resultado.
- `revision_datos_crudos.ipynb`: revisión de integridad y carga de los cinco escenarios, sin matching ni cálculo de métricas. Funciona sin pandas; si está instalado, muestra tablas.
- `verification.json`: comprobación de hashes, punteros JSON, reportes literales y ejecución de celdas del notebook. El verificador completa identificadores de celda requeridos por nbformat 4.5 y permite cargar el notebook también desde Python sin IPython.

Los JSONL preservan campos ausentes (`present=false` y sin `value`), `null`, listas vacías y cadenas vacías. Las tablas con sufijo `_items` conservan orden y duplicados y agregan el índice del elemento. Los punteros JSON y las rutas permiten volver al original. No se calculan TP/FP/FN/TN, Precision, Recall, F1 ni calificaciones de reportes.

Las referencias BGL para reconstrucción y MITRE pueden ser `no_aplica`; se conserva ese estado y cualquier predicción producida. No existe un reporte gold. El estado crudo final no equivale al archivo de todas las respuestas del proveedor. Los Parquet completos quedan fuera de esta extracción limitada a los doce casos; las rutas de procedencia hacia CSV intermedios ausentes permanecen literales.

## Validación del procedimiento

Cinco pruebas offline comprueban: distinción entre ausente/null/vacío; copias byte a byte y orden/duplicados; rechazo de entradas con huella distinta; omisión de un caso ya iniciado incluso si falló; exportación explícita de salidas faltantes y rechazo de sobrescrituras. No invocan modelos ni evaluadores experimentales.

```powershell
& $pythonNodex -m unittest tests.experimentation.test_official_extraction -v
```

El resultado efectivo de la campaña debe consultarse en sus archivos `.result.json` y en `run_status.jsonl`, no deducirse de esta descripción del procedimiento.

## Resultado de la ejecución y entrega

La campaña se ejecutó el 28 de octubre de 2026, aproximadamente entre las 01:52 y las 02:16 de America/Santiago. Los doce casos tienen un único marcador de inicio y estado final `completa`. La telemetría registra cero llamadas fallidas y versión efectiva `gemini-3.8-flash` en todas las llamadas. Estos son controles operacionales, no resultados de evaluación de calidad.

La extracción quedó en `extracted_data/oficial-12casos-r1-20261028/`. Se verificaron 276 copias originales mediante SHA-256, 4625 proyecciones contra sus punteros JSON y 12 reportes contra el texto almacenado. Se ejecutaron correctamente las 10 celdas de código del notebook sobre los datos reales. No faltan archivos requeridos. El detalle está en `verification.json` y `extraction.json`.

El archivo `extracted_data/oficial-12casos-r1-20261028.zip` reúne el paquete para revisión y transferencia; su huella está en el archivo contiguo `.zip.sha256`. La carpeta `procedure/` incluida en el paquete conserva este procedimiento y los scripts de extracción y verificación. No se calcularon métricas de evaluación ni se aplicó una rúbrica de reporte.
