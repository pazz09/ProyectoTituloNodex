# Extracción oficial NODEX — 12 casos, repetición 1

Abrir `revision_datos_crudos.ipynb`. No ejecuta NODEX ni calcula métricas.

Los archivos originales están en `originals/`; `manifest.json` y `manifest.csv` documentan sus hashes. Los JSONL son proyecciones literales con procedencia. Los sufijos `_items` contienen una fila por elemento, sin eliminar duplicados. La tabla padre conserva listas vacías y campos ausentes.

Escenarios: `detection/`, `reconstruction/`, `mitre/`, `reports/`, `performance/`. Las referencias están separadas de las predicciones. `run_status.jsonl` conserva el estado de los 12 casos, incluidos fallos. Consulte `extraction.json` para archivos faltantes y límites.

## Verificaci?n y procedimiento

Los controles pasaron sobre los datos reales: 276 originales, 4625 proyecciones, 12 reportes y las 10 celdas de c?digo del notebook. No faltan archivos requeridos.

Consulte `verification.json` y `procedure/prueba_oficial_12casos_20261028.md`. Para repetir ?nicamente la comprobaci?n desde esta carpeta:

```text
python procedure/verify_experimental_export.py . --execute-notebook
```

El entorno de inferencia utiliz? Python 3.12.14 con las dependencias existentes de .venv; la configuraci?n registra el ?rbol de Git sin commit de los archivos nuevos y los hashes del c?digo conservado. Esto queda documentado para la revisi?n metodol?gica.
