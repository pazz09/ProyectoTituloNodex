"""Selección de los casos de la campaña final, fijada ANTES de correr y con semilla registrada.

El presupuesto (USD 6 en total) no alcanza para los 142 casos de la partición de evaluación. Se
elige una submuestra estratificada por CONDICIÓN (BGL: balanceado / natural; UWF: visible /
sigiloso) y que incluye los casos de la rúbrica humana.

## Qué lee y qué NO lee

Solo lee dos archivos de `experiments/subconjuntos/`: la lista de ids de la partición de evaluación
(`evaluacion.json`) y la de la rúbrica (`rubrica.json`). **No abre `ground_truth/` ni `cases/`**: no
conoce la etiqueta de ningún caso. Por eso NO estratifica por veredicto (positivo/negativo): la
proporción de positivos queda la que los manifiestos declaran por condición (BGL balanceado 50 %,
BGL natural 28 %, UWF 50 %) y la composición real de la muestra elegida no se mira antes de correr.

## Cómo elige

1. Reparte los cupos por condición (ver `CUPOS`).
2. Dentro de cada condición, primero entran TODOS los casos de la rúbrica que caben en el cupo.
3. El resto del cupo se completa al azar (semilla registrada; la mezcla de cada condición depende
   de la semilla y del nombre de la condición, no del orden de ejecución).
4. Cada condición queda ordenada por id: la misma semilla da siempre el mismo archivo.
"""

from __future__ import annotations

import json
import random
import zlib
from pathlib import Path

from src.experimentation.contracts import PROTOCOLO_VERSION

#: Semilla de la selección (fecha de la decisión, 15-oct-2026).
SEMILLA_SELECCION = 20261015

#: Cupos por (dataset, condición). BGL balanceado solo tiene 12 casos en la partición de evaluación:
#: entran todos. 30 de BGL y 10 de UWF.
CUPOS = {
    ("bgl", "balanceado"): 12,
    ("bgl", "natural"): 18,
    ("uwf", "visible"): 5,
    ("uwf", "sigiloso"): 5,
}


def _ids(subconjunto: dict) -> dict[tuple[str, str], list[str]]:
    return {(d, c): sorted(det["case_ids"])
            for d, conds in subconjunto["datasets"].items() for c, det in conds.items()}


def seleccionar(evaluacion: dict, rubrica: dict, semilla: int = SEMILLA_SELECCION,
                cupos: dict[tuple[str, str], int] | None = None) -> dict:
    """Devuelve el subconjunto de la campaña (mismo formato que los demás, más lo que lo justifica)."""
    cupos = cupos or CUPOS
    del_universo = _ids(evaluacion)
    de_rubrica = _ids(rubrica)
    datasets: dict = {}
    incluidos_rubrica, rubrica_fuera = [], []
    for (dataset, condicion), cupo in sorted(cupos.items()):
        universo = del_universo.get((dataset, condicion))
        if universo is None:
            raise KeyError(f"la partición de evaluación no tiene {dataset}/{condicion}")
        if cupo > len(universo):
            raise ValueError(f"{dataset}/{condicion}: cupo {cupo} mayor que los {len(universo)} casos")
        rub = [c for c in de_rubrica.get((dataset, condicion), []) if c in universo]
        entran_rub = rub[:cupo]
        rubrica_fuera += rub[cupo:]
        resto = [c for c in universo if c not in entran_rub]
        azar = random.Random(semilla + zlib.crc32(f"campana|{dataset}|{condicion}".encode()) % 10_000)
        azar.shuffle(resto)
        elegidos = sorted(entran_rub + resto[:cupo - len(entran_rub)])
        incluidos_rubrica += entran_rub
        datasets.setdefault(dataset, {})[condicion] = {
            "composicion": {"disponibles": len(universo), "entregados": len(elegidos),
                            "de_la_rubrica": len(entran_rub),
                            "completados_al_azar": len(elegidos) - len(entran_rub)},
            "case_ids": elegidos,
        }
    n_rubrica = sum(len(v) for v in de_rubrica.values())
    return {
        "proposito": "campaña final con presupuesto de USD 6: submuestra de la partición de evaluación",
        "particion": "evaluacion",
        "decision": ("cambio de alcance del 15-oct-2026: USD 6 en total, N=2 (pedido del profesor guía) "
                     "y casos reducidos; HDFS es auxiliar (D-7) y no entra"),
        "muestreo": ("estratificado por condición, con los casos de la rúbrica incluidos; sin mirar "
                     "etiquetas (no abre ground_truth)"),
        "semilla": semilla,
        "cupos": {f"{d}/{c}": n for (d, c), n in sorted(cupos.items())},
        "casos_de_la_rubrica": {"incluidos": sorted(incluidos_rubrica),
                                "n_incluidos": len(incluidos_rubrica), "n_en_la_rubrica": n_rubrica,
                                "fuera_por_cupo": sorted(rubrica_fuera)},
        "preseleccionada_antes_de_resultados": True,
        "protocolo_version": PROTOCOLO_VERSION,
        "datasets": datasets,
        "n_casos": sum(d["composicion"]["entregados"] for c in datasets.values() for d in c.values()),
    }


def generar(raiz_repo: Path, semilla: int = SEMILLA_SELECCION) -> dict:
    carpeta = raiz_repo / "experiments" / "subconjuntos"

    def leer(nombre: str) -> dict:
        return json.loads((carpeta / nombre).read_text(encoding="utf-8"))

    return seleccionar(leer("evaluacion.json"), leer("rubrica.json"), semilla)


def main(raiz_repo: Path | None = None) -> int:
    from src.experimentation.subconjuntos import escribir_sin_sobrescribir

    raiz_repo = raiz_repo or Path(__file__).resolve().parents[2]
    datos = generar(raiz_repo)
    estado = escribir_sin_sobrescribir(
        raiz_repo / "experiments" / "subconjuntos" / "campana_final.json", datos)
    rub = datos["casos_de_la_rubrica"]
    print(f"campana_final.json: {estado} — {datos['n_casos']} casos, semilla {datos['semilla']}, "
          f"{rub['n_incluidos']} de {rub['n_en_la_rubrica']} casos de la rúbrica incluidos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
