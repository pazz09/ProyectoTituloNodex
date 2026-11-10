"""Runner de línea de comandos para correr el pipeline sobre un archivo de
logs real (en vez del lote de ejemplo hardcodeado en pipeline.py).

Uso:
    python -m src.tools.log_runner data/logs/HDFS_2k.log
    python -m src.tools.log_runner data/logs/BGL_2k.log --thread-id bgl_prueba_1
    python -m src.tools.log_runner data/logs/HDFS_2k.log --no-guardar

Guarda un resumen del resultado en results/<nombre_del_archivo>_<timestamp>.json
salvo que se pase --no-guardar. Se guarda un resumen curado (diagnóstico,
confianza, comandos, formato detectado, distribución de servicios/eventos),
no el estado crudo completo de LangGraph -- alcanza para revisar corridas
después sin arrastrar el detalle interno del grafo.
"""

import argparse
import json
import os
import sys
import time

from src.pipeline import analizar_lote
from src.output_contract import campos_d11
from src.preprocessing.pipeline import PreprocesamientoError

RESULTS_DIR = "results"


def run_from_file(path: str, thread_id: str | None = None, guardar: bool = True) -> dict:
    """Lee un archivo de logs, corre el pipeline completo sobre su contenido,
    y devuelve (y opcionalmente guarda) un resumen curado del resultado."""
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read()

    nombre_base = os.path.splitext(os.path.basename(path))[0]
    resultado = analizar_lote(raw, thread_id=thread_id or f"{nombre_base}_{int(time.time())}")

    resumen_logs = resultado.get("resumen_logs", {})
    # Versionado del resultado (Fase 11 del plan): sin esto, dos archivos
    # de `results/` producidos por motores distintos parecen comparables y
    # no lo son. Se guarda además la configuración efectiva del parsing,
    # porque una salida distinta puede deberse al código o a la config.
    from src.config import LOG_PREPROCESSING_ENGINE
    metadatos = resultado.get("preprocessing_metadata") or {}
    salida = {
        **campos_d11(resultado),
        "archivo_origen": path,
        "motor_preprocesamiento": LOG_PREPROCESSING_ENGINE,
        "schema_version": metadatos.get("schema_version", "1.0"),
        "config_preprocesamiento": metadatos.get("config"),
        "preprocesamiento": {k: v for k, v in metadatos.items()
                             if k not in ("config", "segments")},
        "formato_detectado": resumen_logs.get("formato_detectado"),
        "total_lineas": resumen_logs.get("total_lineas"),
        "n_ips_distintas": resumen_logs.get("n_ips_distintas"),
        "ventana_temporal": resumen_logs.get("ventana_temporal"),
        "servicios": resumen_logs.get("servicios"),
        "eventos": resumen_logs.get("eventos"),
        # Procedencia del raw (Fase 3 del cierre de auditoría, 23-sep-2026,
        # hallazgo A3): hash, líneas y tamaño -- no el contenido.
        "raw_procedencia": resumen_logs.get("raw_procedencia"),
        "diagnostico": resultado.get("diagnostico"),
        "confianza": resultado.get("confianza"),
        "hay_incidente": resultado.get("hay_incidente"),
        "hay_anomalia": resultado.get("hay_anomalia"),
        "evaluacion_auditor": resultado.get("evaluacion_auditor"),
        "tecnicas_mitre": resultado.get("tecnicas_mitre"),
        "comandos_mitigacion": resultado.get("comandos_mitigacion"),
        "comandos_validos": resultado.get("comandos_validos"),
        "requiere_revision_humana": resultado.get("requiere_revision_humana"),
        "intentos_correccion": resultado.get("intentos_correccion"),
    }

    if guardar:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        destino = os.path.join(RESULTS_DIR, f"{nombre_base}_{int(time.time())}.json")
        with open(destino, "w", encoding="utf-8") as f:
            json.dump(salida, f, ensure_ascii=False, indent=2)
        salida["_guardado_en"] = destino

    return salida


def _main():
    parser = argparse.ArgumentParser(
        description="Corre el pipeline multiagente NODEX sobre un archivo de logs real."
    )
    parser.add_argument("archivo", help="Ruta al archivo de logs (p. ej. data/logs/HDFS_2k.log)")
    parser.add_argument(
        "--thread-id", default=None,
        help="ID de hilo para el checkpointer (default: <nombre_del_archivo>_<timestamp>)",
    )
    parser.add_argument(
        "--no-guardar", action="store_true",
        help="No guardar el resultado en results/ (por defecto sí se guarda)",
    )
    args = parser.parse_args()

    # Antes de este cierre, un fallo de `preprocesar()` acá no tenía ningún
    # try/except propio: se propagaba como traceback crudo de Python hasta
    # la terminal (revisión del camino productivo, cierre de auditoría
    # 23-sep-2026). `run_from_file` no atrapa nada -- corresponde acá,
    # al borde de la interfaz de usuario del CLI.
    try:
        salida = run_from_file(args.archivo, thread_id=args.thread_id, guardar=not args.no_guardar)
    except PreprocesamientoError as e:
        print(f"\n❌ {e}", file=sys.stderr)
        raise SystemExit(1)

    print("\n📋 REPORTE FINAL")
    print(json.dumps(salida, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
