"""Regenera casos con la misma semilla y los mismos registros en un directorio NUEVO.

NODEX final, M9. Los casos existentes en `experiments/cases/` son la evidencia
del piloto y no se tocan. Este módulo vuelve a correr los generadores
(`preparar_dataset` para BGL/HDFS y `generar_casos_uwf` para UWF) con sus
semillas registradas, recorriendo SIEMPRE las dos particiones en el mismo
orden (así los registros asignados son exactamente los mismos), y escribe solo
las particiones pedidas bajo `<destino>/cases/` y `<destino>/ground_truth/`.

La única diferencia esperada respecto del original está en las filas rebasadas
de UWF: `ts` y `datetime` usan ahora el formato del fondo
(`UWF_REBASE_FORMATO_FONDO`). `comparar_con_original` lo verifica caso por caso.

    python -m src.experimentation.datasets.regenerar --destino experiments/cases_final --particiones evaluacion
"""

from __future__ import annotations

import argparse
import csv
import io
import json
from datetime import datetime
from pathlib import Path

DATASETS = ("bgl", "uwf")


def _validar_destino(raiz_repo: Path, destino: Path) -> Path:
    destino = Path(destino).resolve()
    original = (Path(raiz_repo) / "experiments").resolve()
    if destino == original or destino in original.parents:
        raise ValueError("El destino no puede ser experiments/ ni un directorio que lo contenga: "
                         "los casos existentes son la evidencia del piloto")
    for sub in ("cases", "ground_truth"):
        if (destino / sub).exists() and any((destino / sub).rglob("*")):
            raise FileExistsError(f"{destino / sub} ya tiene archivos: la regeneración no sobrescribe")
    return destino


def regenerar(raiz_repo: Path, destino: Path, particiones: tuple[str, ...],
              datasets: tuple[str, ...] = DATASETS) -> dict:
    """Regenera `datasets` y escribe solo `particiones` bajo `destino`. Devuelve los manifiestos."""
    from src.config import UWF_REBASE_FORMATO_FONDO
    from src.experimentation.datasets.preparar import preparar_dataset
    from src.experimentation.datasets.uwf_casos import generar_casos_uwf

    raiz_repo = Path(raiz_repo).resolve()
    destino = _validar_destino(raiz_repo, destino)
    manifiestos = {}
    for dataset in datasets:
        if dataset == "uwf":
            manifiestos[dataset] = generar_casos_uwf(raiz_repo, destino, particiones_a_escribir=particiones)
        else:
            manifiestos[dataset] = preparar_dataset(dataset, raiz_repo, destino, particiones_a_escribir=particiones)
        ruta = destino / "manifests" / f"{dataset}.json"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(manifiestos[dataset], indent=2, ensure_ascii=False), encoding="utf-8")
    registro = {"particiones_escritas": list(particiones), "datasets": list(datasets),
                "uwf_rebase_formato_fondo": UWF_REBASE_FORMATO_FONDO,
                "formato_filas_rebasadas": ("ts = repr(round(ts, 6)); datetime = str(fromtimestamp(ts, UTC)) "
                                            "sin zona (igual que el fondo)") if UWF_REBASE_FORMATO_FONDO
                else "ts con 6 decimales fijos; datetime en milisegundos (versión anterior)",
                "nota": "Mismas semillas y mismos registros que experiments/cases; los casos originales no se tocan."}
    (destino / "regeneracion.json").write_text(json.dumps(registro, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifiestos


# --- verificación -------------------------------------------------------------

def _filas_csv(ruta: Path) -> list[dict]:
    return list(csv.DictReader(io.StringIO(ruta.read_text(encoding="utf-8"))))


def _dt(valor: str) -> datetime:
    return datetime.fromisoformat(valor)


def comparar_con_original(raiz_repo: Path, destino: Path, dataset: str, particion: str) -> dict:
    """Compara cada caso regenerado con el original. Solo admite diferencias de formato.

    Para cada caso: mismos archivos, metadatos (`.json`) y referencias idénticos;
    en `.log` el contenido idéntico; en `.csv` las mismas filas en el mismo orden,
    con todas las columnas idénticas salvo `ts`/`datetime` de las filas que
    cambian, donde se exige el mismo instante (|Δts| ≤ 1 µs; `datetime`
    anterior = nuevo truncado a milisegundos) y que el nuevo `datetime` derive
    exactamente del nuevo `ts`.
    """
    raiz_repo, destino = Path(raiz_repo), Path(destino)
    original = raiz_repo / "experiments" / "cases" / dataset / particion
    nuevo = destino / "cases" / dataset / particion
    gt_original = raiz_repo / "experiments" / "ground_truth" / dataset / particion
    gt_nuevo = destino / "ground_truth" / dataset / particion
    problemas, filas_cambiadas, casos = [], 0, 0
    nombres = sorted(p.name for p in original.glob("*"))
    if nombres != sorted(p.name for p in nuevo.glob("*")):
        problemas.append("los archivos de casos no coinciden")
    for nombre in nombres:
        a, b = original / nombre, nuevo / nombre
        if not b.exists():
            continue
        if nombre.endswith(".json") or nombre.endswith(".log"):
            if a.read_text(encoding="utf-8") != b.read_text(encoding="utf-8"):
                problemas.append(f"{nombre}: contenido distinto")
            continue
        casos += 1
        fa, fb = _filas_csv(a), _filas_csv(b)
        if len(fa) != len(fb):
            problemas.append(f"{nombre}: distinto número de filas")
            continue
        for x, y in zip(fa, fb):
            distintas = [k for k in x if x[k] != y.get(k)]
            if not distintas:
                continue
            if set(distintas) - {"ts", "datetime"}:
                problemas.append(f"{nombre}: cambian columnas {sorted(set(distintas) - {'ts', 'datetime'})}")
                continue
            filas_cambiadas += 1
            if abs(float(x["ts"]) - float(y["ts"])) > 1e-6:
                problemas.append(f"{nombre}: ts cambia de instante en {x['uid']}")
            if _dt(y["datetime"]).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] != x["datetime"]:
                problemas.append(f"{nombre}: datetime cambia de instante en {x['uid']}")
            from src.experimentation.datasets.uwf_casos import _formato_del_fondo
            if _formato_del_fondo(float(y["ts"])) != (y["ts"], y["datetime"]):
                problemas.append(f"{nombre}: el formato nuevo no sigue la regla del fondo en {x['uid']}")
    gt_nombres = sorted(p.name for p in gt_original.glob("*.json"))
    if gt_nombres != sorted(p.name for p in gt_nuevo.glob("*.json")):
        problemas.append("las referencias no coinciden")
    for nombre in gt_nombres:
        if (gt_nuevo / nombre).exists() and (gt_original / nombre).read_bytes() != (gt_nuevo / nombre).read_bytes():
            problemas.append(f"referencia {nombre} distinta")
    return {"dataset": dataset, "particion": particion, "archivos": len(nombres), "casos_csv": casos,
            "filas_con_ts_datetime_reformateados": filas_cambiadas, "referencias": len(gt_nombres),
            "problemas": problemas, "solo_cambia_el_formato": not problemas}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destino", type=Path, required=True)
    parser.add_argument("--particiones", nargs="+", choices=("desarrollo", "evaluacion"), required=True)
    parser.add_argument("--datasets", nargs="+", choices=DATASETS, default=list(DATASETS))
    args = parser.parse_args(argv)
    raiz = Path(__file__).resolve().parents[3]
    regenerar(raiz, args.destino, tuple(args.particiones), tuple(args.datasets))
    for dataset in args.datasets:
        for particion in args.particiones:
            print(json.dumps(comparar_con_original(raiz, args.destino, dataset, particion), ensure_ascii=False))


if __name__ == "__main__":
    main()
