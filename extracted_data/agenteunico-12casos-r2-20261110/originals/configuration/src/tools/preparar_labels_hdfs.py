"""Descarga y filtra el ground truth oficial de HDFS (`anomaly_label.csv`,
el dataset canónico de ground truth block-level usado en la literatura de
detección de anomalías en logs -- el mismo tipo de fuente que citan varios
papers del SLR de la Tabla 7.1 del informe, p. ej. el trabajo original de
Loglizer/He et al.) a los `block_id` presentes en `data/logs/HDFS_2k.log`,
para poder usarlo con `src/tools/eval_deteccion.py --dataset hdfs`.

Por qué hace falta un archivo externo: el ground truth de HDFS es por
BLOQUE (`block_id` -> Normal/Anomaly), y esa etiqueta no está en las
líneas del log en sí -- a diferencia de BGL, donde el flag de alerta viene
incluido en cada línea (ver `eval_deteccion.py`, que para BGL no necesita
nada de esto).

Requiere red real -- no funciona desde un sandbox sin acceso a internet
(este repo se edita también desde un puente de dispositivo sin red; correr
este script directamente en tu máquina). Se corre UNA sola vez: el archivo
filtrado queda en `data/labels/hdfs_anomaly_label_2k.csv` (~2200 filas, sin
nada sensible, sí se versiona en git).

Uso:
    python -m src.tools.preparar_labels_hdfs
"""

import csv
import re
from pathlib import Path

import requests

_URL_LABELS = "https://raw.githubusercontent.com/logpai/loglizer/master/data/HDFS/anomaly_label.csv"
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LOG_PATH = _REPO_ROOT / "data" / "logs" / "HDFS_2k.log"
_DEST_DIR = _REPO_ROOT / "data" / "labels"
_DEST_PATH = _DEST_DIR / "hdfs_anomaly_label_2k.csv"


def _bloques_del_log(log_path: Path) -> set[str]:
    texto = log_path.read_text(encoding="utf-8", errors="replace")
    return set(re.findall(r"blk_-?\d+", texto))


def _filtrar_labels(texto_csv: str, bloques: set[str]) -> list[dict]:
    lector = csv.DictReader(texto_csv.splitlines())
    return [row for row in lector if row["BlockId"] in bloques]


def main() -> None:
    print(f"Extrayendo block_id de {_LOG_PATH} ...")
    bloques = _bloques_del_log(_LOG_PATH)
    print(f"  {len(bloques)} block_id distintos encontrados.")

    print(f"Descargando labels oficiales desde {_URL_LABELS} ...")
    resp = requests.get(_URL_LABELS, timeout=60)
    resp.raise_for_status()

    filas = _filtrar_labels(resp.text, bloques)
    encontrados = {row["BlockId"] for row in filas}
    faltantes = bloques - encontrados
    n_anomaly = sum(1 for row in filas if row["Label"] == "Anomaly")
    n_normal = sum(1 for row in filas if row["Label"] == "Normal")

    print(f"  {len(filas)}/{len(bloques)} block_id encontrados en el dataset oficial "
          f"({n_anomaly} Anomaly, {n_normal} Normal).")
    if faltantes:
        print(f"  ADVERTENCIA: {len(faltantes)} block_id de HDFS_2k.log no aparecen "
              "en el dataset oficial de labels -- no debería pasar si HDFS_2k.log es "
              "una muestra real de HDFS_v1; revisa antes de confiar en el resultado.")
    if n_anomaly == 0:
        raise SystemExit(
            "Ningún block_id de HDFS_2k.log tiene label 'Anomaly' -- algo está mal "
            "(la muestra 2k del informe sí debería incluir bloques anómalos reales, "
            "revisa la URL de origen y que el HDFS_2k.log no haya cambiado)."
        )

    _DEST_DIR.mkdir(exist_ok=True)
    with open(_DEST_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["BlockId", "Label"])
        w.writeheader()
        w.writerows(filas)
    print(f"Guardado en {_DEST_PATH}")


if __name__ == "__main__":
    main()
