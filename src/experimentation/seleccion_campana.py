"""Selección de los casos de la campaña final, fijada ANTES de correr y con semilla registrada.

El presupuesto (USD 6 en total) no alcanza para los 142 casos de la partición de evaluación. Se
elige una submuestra estratificada por CONDICIÓN (BGL: balanceado / natural; UWF: visible /
sigiloso) y por ETIQUETA de referencia (positivo / negativo), con los casos de la rúbrica humana
incluidos.

## Qué lee: este es código de PREPARACIÓN, no de las arquitecturas

Para estratificar por etiqueta lee, igual que `subconjuntos.py` (que generó `rubrica.json` y
`evaluacion.json`), la **etiqueta de referencia** (`etiqueta_deteccion`: anómalo/normal) de cada caso
de la partición de evaluación. **Solo la etiqueta**: ni el contenido del caso ni el resto de la
referencia. La usa únicamente para repartir cupos y no la escribe en el archivo de salida (que lleva
ids y conteos por estrato, como `evaluacion.json`).

Ningún código que ejecute una arquitectura (`campana.py`, `orquestador.py`, `runners/`, `agents/`,
`tools/`) importa este módulo ni `subconjuntos.py` (hay una prueba que lo verifica).

## Cómo elige

1. Reparte los cupos por (dataset, condición, etiqueta) (ver `CUPOS`).
2. En cada estrato entran primero TODOS los casos de la rúbrica que caben en el cupo.
3. El resto del cupo se completa al azar (semilla registrada; la mezcla de cada estrato depende de la
   semilla y del nombre del estrato, no del orden de ejecución).
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

POSITIVO, NEGATIVO = "anomalo", "normal"

#: Cupos por (dataset, condición): {etiqueta: casos}. 30 de BGL y 10 de UWF.
#:
#: - BGL balanceado: la condición solo tiene 12 casos (6 y 6): entran todos.
#: - BGL natural: 8 positivos y 10 negativos. La condición natural tiene 14 positivos de 50 (28 %); aquí se
#:   sobremuestrean los positivos (8 de 18 = 44 %) para que la exhaustividad tenga base. Consecuencia: la
#:   precisión dentro de «natural» NO representa la prevalencia natural y así debe informarse. Los 8 son
#:   más que los 4 que saldrían con 28 % de 18 y menos que los 9 de una división en mitades; con los 6 de
#:   balanceado, BGL queda con 14 positivos y 16 negativos.
#: - UWF: 5 positivos y 5 negativos en total y 5 casos por condición hasta donde permiten los casos de la
#:   rúbrica (visible: 1+ y 2+; sigiloso: 2+ y 1+): visible 2 positivos y 3 negativos, sigiloso 3 y 2.
CUPOS = {
    ("bgl", "balanceado"): {POSITIVO: 6, NEGATIVO: 6},
    ("bgl", "natural"): {POSITIVO: 8, NEGATIVO: 10},
    ("uwf", "visible"): {POSITIVO: 2, NEGATIVO: 3},
    ("uwf", "sigiloso"): {POSITIVO: 3, NEGATIVO: 2},
}


def _ids(subconjunto: dict) -> dict[tuple[str, str], list[str]]:
    return {(d, c): sorted(det["case_ids"])
            for d, conds in subconjunto["datasets"].items() for c, det in conds.items()}


def seleccionar(etiquetas: dict[tuple[str, str], dict[str, str]], rubrica: dict,
                semilla: int = SEMILLA_SELECCION,
                cupos: dict[tuple[str, str], dict[str, int]] | None = None) -> dict:
    """Subconjunto de la campaña (mismo formato que los demás, más lo que lo justifica).

    `etiquetas`: `{(dataset, condición): {case_id: "anomalo" | "normal"}}` de la partición de evaluación.
    """
    cupos = cupos or CUPOS
    de_rubrica = _ids(rubrica)
    datasets: dict = {}
    incluidos_rubrica, rubrica_fuera = [], []
    for (dataset, condicion), por_etiqueta in sorted(cupos.items()):
        universo = etiquetas.get((dataset, condicion))
        if universo is None:
            raise KeyError(f"la partición de evaluación no tiene {dataset}/{condicion}")
        rub_condicion = [c for c in de_rubrica.get((dataset, condicion), []) if c in universo]
        elegidos, composicion = [], {}
        for etiqueta, cupo in sorted(por_etiqueta.items()):
            del_estrato = sorted(c for c, e in universo.items() if e == etiqueta)
            if cupo > len(del_estrato):
                raise ValueError(f"{dataset}/{condicion}/{etiqueta}: cupo {cupo} mayor que los "
                                 f"{len(del_estrato)} casos")
            rub = [c for c in rub_condicion if universo[c] == etiqueta]
            entran_rub = rub[:cupo]
            rubrica_fuera += rub[cupo:]
            resto = [c for c in del_estrato if c not in entran_rub]
            azar = random.Random(
                semilla + zlib.crc32(f"campana|{dataset}|{condicion}|{etiqueta}".encode()) % 10_000)
            azar.shuffle(resto)
            elegidos += entran_rub + resto[:cupo - len(entran_rub)]
            incluidos_rubrica += entran_rub
            composicion[etiqueta] = {"disponibles": len(del_estrato), "entregados": cupo,
                                     "de_la_rubrica": len(entran_rub)}
        datasets.setdefault(dataset, {})[condicion] = {
            "composicion": {"entregados": len(elegidos),
                            "positivos": composicion.get(POSITIVO, {}).get("entregados", 0),
                            "negativos": composicion.get(NEGATIVO, {}).get("entregados", 0),
                            "por_etiqueta": composicion},
            "case_ids": sorted(elegidos),
        }
    n_rubrica = sum(len(v) for v in de_rubrica.values())
    return {
        "proposito": "campaña final con presupuesto de USD 6: submuestra de la partición de evaluación",
        "particion": "evaluacion",
        "decision": ("cambio de alcance del 15-oct-2026: USD 6 en total, N=2 (pedido del profesor guía) "
                     "y casos reducidos; HDFS es auxiliar (D-7) y no entra"),
        "muestreo": ("estratificado por condición y por etiqueta de referencia, con los casos de la rúbrica "
                     "incluidos; la etiqueta se usa solo en el código de preparación"),
        "semilla": semilla,
        "cupos": {f"{d}/{c}": dict(sorted(e.items())) for (d, c), e in sorted(cupos.items())},
        "casos_de_la_rubrica": {"incluidos": sorted(incluidos_rubrica),
                                "n_incluidos": len(incluidos_rubrica), "n_en_la_rubrica": n_rubrica,
                                "fuera_por_cupo": sorted(rubrica_fuera)},
        "preseleccionada_antes_de_resultados": True,
        "protocolo_version": PROTOCOLO_VERSION,
        "datasets": datasets,
        "n_casos": sum(d["composicion"]["entregados"] for c in datasets.values() for d in c.values()),
    }


def leer_etiquetas(raiz_repo: Path, datasets=("bgl", "uwf")) -> dict[tuple[str, str], dict[str, str]]:
    """Etiqueta de referencia de cada caso de evaluación, por estrato. CÓDIGO DE PREPARACIÓN."""
    from src.experimentation.subconjuntos import _cargar

    etiquetas: dict = {}
    for dataset in datasets:
        for caso in _cargar(raiz_repo / "experiments", dataset, "evaluacion"):
            etiquetas.setdefault((dataset, caso.condicion), {})[caso.case_id] = caso.etiqueta_deteccion
    return etiquetas


def generar(raiz_repo: Path, semilla: int = SEMILLA_SELECCION, etiquetas=None) -> dict:
    rubrica = json.loads((raiz_repo / "experiments" / "subconjuntos" / "rubrica.json")
                         .read_text(encoding="utf-8"))
    return seleccionar(etiquetas if etiquetas is not None else leer_etiquetas(raiz_repo), rubrica, semilla)


def main(raiz_repo: Path | None = None, nombre: str = "campana_final") -> int:
    from src.experimentation.subconjuntos import escribir_sin_sobrescribir

    raiz_repo = raiz_repo or Path(__file__).resolve().parents[2]
    datos = generar(raiz_repo)
    estado = escribir_sin_sobrescribir(
        raiz_repo / "experiments" / "subconjuntos" / f"{nombre}.json", datos)
    rub = datos["casos_de_la_rubrica"]
    print(f"{nombre}.json: {estado} — {datos['n_casos']} casos, semilla {datos['semilla']}, "
          f"{rub['n_incluidos']} de {rub['n_en_la_rubrica']} casos de la rúbrica incluidos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
