"""Estimación de tokens (y costo, si hay precios) de un plan. ORDEN DE MAGNITUD.

Lo que hay acá es lo **medido** en la comparación mínima de modelos (15-oct-2026,
`docs/experimentacion/estado_preparacion.md` §20.12), con `gemini-3.8-flash`. Es
**una corrida por celda** (arquitectura × dataset, N=1) y un solo caso por dataset:
sirve para saber si un plan cuesta decenas, miles o millones de tokens, no para
presupuestar con precisión. Los tokens de una corrida dependen mucho del caso (el
de UWF medido pesa 56 KB; otros pesan más o menos) y, en NODEX, de cuántos bucles de
replanificación y corrección haga el grafo.

Lo que NO hay:
- HDFS no se midió: sus corridas figuran como «sin medición» y NO suman.
- El baseline no usa el modelo: 0 tokens.
- **Precios.** No se supone ninguno. `experiments/config/precios_modelo.json` es una
  tabla configurable (con fecha y fuente) que viene vacía; mientras esté vacía el costo
  es `None`, no 0.
"""

from __future__ import annotations

import json
from pathlib import Path

#: Modelo con el que se hicieron las mediciones.
MODELO_MEDIDO = "gemini-3.8-flash"
FUENTE_MEDICIONES = (
    "comparación mínima de modelos del 15-oct-2026 (estado_preparacion.md §20.12): "
    "1 corrida por celda, 1 caso por dataset"
)

#: Tokens POR CORRIDA, medidos. `llamadas` es el número de llamadas de esa corrida.
MEDICIONES: dict[tuple[str, str], dict] = {
    ("nodex_multiagente", "bgl"): {"entrada": 4299, "salida": 1069, "razonamiento": 2226,
                                   "llamadas": 5, "n": 1},
    ("nodex_multiagente", "uwf"): {"entrada": 61667, "salida": 1826, "razonamiento": 5820,
                                   "llamadas": 6, "n": 1},
    ("gemini_externo", "bgl"): {"entrada": 2731, "salida": 2260, "razonamiento": 1263,
                                "llamadas": 1, "n": 1},
    ("gemini_externo", "uwf"): {"entrada": 50720, "salida": 1428, "razonamiento": 7038,
                                "llamadas": 1, "n": 1},
}

#: Arquitecturas que no consumen tokens.
SIN_TOKENS = ("baseline_reglas",)

RUTA_PRECIOS = Path("experiments") / "config" / "precios_modelo.json"


def _total(m: dict) -> int:
    return m["entrada"] + m["salida"] + m["razonamiento"]


def estimar(corridas: list[dict], modelo_activo: str | None = None) -> dict:
    """Estimación por (arquitectura, dataset) para una lista de corridas del plan.

    `corridas`: entradas con `arquitectura` y `dataset`. Devuelve filas con los tokens
    por corrida medidos y el total estimado, más lo que quedó sin medición.
    """
    conteo: dict[tuple[str, str], int] = {}
    for c in corridas:
        clave = (c["arquitectura"], c["dataset"])
        conteo[clave] = conteo.get(clave, 0) + 1

    filas, total, sin_medicion = [], 0, []
    for (arquitectura, dataset), n in sorted(conteo.items()):
        if arquitectura in SIN_TOKENS:
            filas.append({"arquitectura": arquitectura, "dataset": dataset, "corridas": n,
                          "por_corrida": {"entrada": 0, "salida": 0, "razonamiento": 0, "total": 0},
                          "total_estimado": 0, "medicion": "no usa el modelo"})
            continue
        m = MEDICIONES.get((arquitectura, dataset))
        if m is None:
            filas.append({"arquitectura": arquitectura, "dataset": dataset, "corridas": n,
                          "por_corrida": None, "total_estimado": None, "medicion": "sin medición"})
            sin_medicion.append({"arquitectura": arquitectura, "dataset": dataset, "corridas": n})
            continue
        por = {**{k: m[k] for k in ("entrada", "salida", "razonamiento")}, "total": _total(m)}
        filas.append({"arquitectura": arquitectura, "dataset": dataset, "corridas": n,
                      "por_corrida": por, "llamadas_por_corrida": m["llamadas"],
                      "total_estimado": por["total"] * n,
                      "medicion": f"N={m['n']} corrida medida"})
        total += por["total"] * n
    aviso_modelo = (
        None if modelo_activo in (None, MODELO_MEDIDO) else
        f"las mediciones son de {MODELO_MEDIDO}; el modelo activo es {modelo_activo}")
    return {
        "es": "orden de magnitud basado en N=1 corrida por celda; no es un presupuesto",
        "modelo_medido": MODELO_MEDIDO,
        "fuente": FUENTE_MEDICIONES,
        "filas": filas,
        "total_estimado_tokens": total,
        "corridas_sin_medicion": sin_medicion,
        "aviso_modelo": aviso_modelo,
    }


def leer_precios(raiz_repo: Path) -> dict:
    ruta = raiz_repo / RUTA_PRECIOS
    if not ruta.is_file():
        return {"modelos": {}}
    return json.loads(ruta.read_text(encoding="utf-8"))


def costo(estimacion: dict, precios: dict, modelo: str) -> dict:
    """Costo estimado con la tabla de precios, o `None` si no hay precio configurado.

    Los tokens de razonamiento se facturan como salida (documentación oficial de
    Gemini). No se usa ningún precio que no esté en la tabla.
    """
    fila = (precios.get("modelos") or {}).get(modelo) or {}
    p_entrada, p_salida = fila.get("entrada_por_millon"), fila.get("salida_por_millon")
    if p_entrada is None or p_salida is None:
        return {"costo": None, "motivo": f"sin precios configurados para {modelo}"}
    if not precios.get("fecha") or not precios.get("fuente"):
        return {"costo": None, "motivo": "la tabla de precios no declara fecha y fuente"}
    entrada = salida = 0
    for f in estimacion["filas"]:
        if f["por_corrida"] is None:
            continue
        entrada += f["por_corrida"]["entrada"] * f["corridas"]
        salida += (f["por_corrida"]["salida"] + f["por_corrida"]["razonamiento"]) * f["corridas"]
    valor = entrada / 1e6 * p_entrada + salida / 1e6 * p_salida
    return {"costo": round(valor, 4), "moneda": precios.get("moneda"),
            "fecha_de_precios": precios["fecha"], "fuente_de_precios": precios["fuente"],
            "nota": "solo incluye las corridas con medición"}
