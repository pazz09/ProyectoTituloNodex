# NODEX — Repeticiones oficiales R2 y R3

Solicitud autorizada del 3 de noviembre de 2026. Se ejecutan dos repeticiones adicionales de los doce casos oficiales, secuencialmente: R2, extracción y validación de R2, nueva comprobación del RAG limpio, R3, extracción y validación de R3. No se ejecuta nuevamente R1 ni se calculan métricas de calidad.

## Referencia inmutable

R1 es `oficial-12casos-r1-20261028`. Sus entradas, orden, SHA-256 completos, parámetros, código y versiones de dependencias se recuperan de su paquete preservado. `experiments/ejecucion/repeticiones-oficiales-20261103/r1_preservation_before.json` registra los hashes actuales de R1, sus originales, configuración, fuentes, procedimiento, ZIP y huella. Las comprobaciones posteriores solo leen R1; no se invoca sobre R1 el verificador que modifica metadatos del notebook.

Antes de la preparación y durante la ejecución se rechazan diferencias en los archivos de código conservados, requisitos, Python, versiones instaladas, inputs, orden y modelo de embeddings respecto a R1. Los parámetros congelados, generación, política externa y hashes funcionales también deben coincidir. Se conservan Gemini `gemini-3.8-flash`, temperatura 0, respaldo desactivado, reputación externa desactivada, NVD bloqueado y partición `evaluacion`. Las credenciales no se exportan.

La configuración nueva y los identificadores reflejan `repeticion=2`/`__r2__` o `repeticion=3`/`__r3__`. La fecha del identificador se obtiene al preparar cada repetición en `America/Santiago`.

## RAG limpio e independencia

Se revisaron `src/memory.py`, `knowledge/aislamiento.py`, `knowledge/poblar.py` y `campana.correr_una()`. La base `experiments/knowledge/chroma_v2` contiene solo `attack_techniques`, 697 documentos de dimensión 384. No contiene colecciones dinámicas. Sus cinco archivos coinciden byte a byte con el snapshot de `poblado_chroma_v2.json`, cuyo hash está fijado por la configuración R1. Los registros de inventario y verificación de conocimiento también coinciden con R1. Los archivos de embeddings almacenados corresponden a la revisión `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` de `all-MiniLM-L6-v2` y se verifican mediante sus hashes originales.

No es necesario repoblar esta semilla ni recalcular embeddings: ya coincide exactamente con el estado inicial. El restablecimiento efectivo consiste en descartar las copias temporales al terminar cada caso y crear una copia nueva de esa semilla para el siguiente. No se borra ni modifica la base de producción, la semilla original o el catálogo MITRE.

Antes de cada repetición se escribe `rag_initial.json`, con los hashes de los archivos, colecciones, configuración, cantidades y confirmación de memoria dinámica vacía. Antes de lanzar **cada proceso hijo**, un observador comprueba el entorno generado por el lanzador R1: la copia es independiente, sus bytes coinciden con la semilla, las colecciones dinámicas están vacías y la ruta de caché de IP todavía no existe. Se registra en `<run_id>.isolation.json`. Al salir el hijo se registra el estado de su copia y se comprueba que el directorio temporal fue descartado y la semilla quedó intacta.

El observador no modifica el entorno, comando, estado, agentes o respuestas; llama al mismo `campana.correr_una()` y al mismo lanzador de proceso de R1. Sus comprobaciones añaden una pequeña sobrecarga al tiempo total del proceso observado. `execution_time` y los tiempos de llamadas de la telemetría original conservan su definición; no deben confundirse con el tiempo de pared del envoltorio.

R3 vuelve a verificar la semilla y crea sus propios procesos y copias. No lee las memorias temporales de R2. El historial del sistema y los recursos de producción no son utilizados por este flujo. La política externa y la caché propia del caso son las mismas que R1.

## Ejecución sin repeticiones ocultas

Cada caso recibe un marcador exclusivo `.started.json` antes de iniciar el lanzador. Un caso iniciado nunca se repite automáticamente, incluso si falló. El resultado se conserva en `.result.json`, con inicio y fin UTC, identidad, error y duración. Se mantienen los reintentos internos originales de NODEX, el límite de dos horas por corrida y la parada después de tres fallas consecutivas de infraestructura. Una incompatibilidad del entorno o un error del envoltorio detiene el procedimiento.

Los archivos existentes no se sobrescriben. No se ejecutan baselines ni otras arquitecturas. Las referencias de ground truth solo se interpretan como JSON al extraer los resultados, después de la inferencia de la repetición correspondiente. El registro de preservación también comprueba sus bytes mediante SHA-256; no recupera etiquetas ni las incorpora al proceso hijo de inferencia.

## Extracción y verificación

Se reutiliza sin modificación `tools/export_experimental_data.py` para mantener exactamente las proyecciones, estados ausentes, valores null, orden, duplicados y sufijos `_items` de R1. Un envoltorio adapta únicamente los identificadores, el texto del README y la ruta de carga del notebook a R2/R3. También añade los registros de aislamiento, la evidencia de preservación de R1 y una copia binaria de la semilla en `originals/knowledge/`.

El verificador R2/R3 deriva del de R1 y valida el número de repetición real; rechaza escribir en R1. Comprueba hashes de copias, punteros JSON, texto literal de reportes, identidad de casos y ejecución de celdas del notebook. Las entradas y las referencias de ground truth exportadas deben tener los mismos hashes que las copias R1.

Cada repetición tiene su propia carpeta `extracted_data/oficial-12casos-rN-YYYYMMDD/`, con los cinco escenarios, originales, procedimiento, manifiestos, notebook, `extraction.json`, `verification.json` y `repetition_integrity.json`. Su ZIP y `.zip.sha256` se generan únicamente después de la validación y se comprueba la integridad del archivo comprimido.

Las referencias BGL pueden indicar `no_aplica` en reconstrucción o MITRE. Los candidatos RAG se mantienen separados de las técnicas atribuidas. El raw es el estado final conservado y no un archivo completo de todas las respuestas HTTP del proveedor. No se inventan mediciones de CPU, RAM, GPU o costo facturado. No se aplican matching, Precision, Recall, F1 ni rúbricas de reporte.

## Comandos

Desde la raíz del repositorio, con el mismo Python 3.12.14 utilizado en R1:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) '.venv/Lib/site-packages')
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
$pythonNodex = 'C:/Users/felip/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'

# Preparación, sin inferencia:
& $pythonNodex -B -u tools/run_official_repetitions.py --repetition 2

# R2 y su extracción. Sustituir la fecha si la ejecución ocurre otro día.
& $pythonNodex -B -u tools/run_official_repetitions.py --repetition 2 --execute
& $pythonNodex -B -u tools/export_official_repetition.py --config-version oficial-12casos-r2-20261103

# Solo después de extraer y validar R2:
& $pythonNodex -B -u tools/run_official_repetitions.py --repetition 3 --execute
& $pythonNodex -B -u tools/export_official_repetition.py --config-version oficial-12casos-r3-20261103
```

Para Google Colab, descomprimir cada ZIP en una carpeta con el nombre de su identificador y abrir el notebook correspondiente. Las tablas conservan `case_id`, `repeticion`, `run_id` y `config_version`, permitiendo cargar conjuntamente las tres repeticiones sin fusionar sus identidades.
