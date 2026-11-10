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


def precio_vigente(precios: dict, modelo: str, fecha: str) -> dict | None:
    """Precios de `modelo` vigentes en `fecha` (`AAAA-MM-DD`), o `None` si no hay.

    Cada vigencia lleva `desde` y `hasta` (inclusivos; `null` = sin límite). Si la tabla no
    declara fecha de consulta y fuente, tampoco se usa: un precio sin procedencia no es un
    precio.
    """
    if not precios.get("fecha_de_consulta") or not precios.get("fuente"):
        return None
    for v in ((precios.get("modelos") or {}).get(modelo) or {}).get("vigencias") or []:
        if (v.get("desde") is None or v["desde"] <= fecha) and (
                v.get("hasta") is None or fecha <= v["hasta"]):
            if v.get("entrada_por_millon") is None or v.get("salida_por_millon") is None:
                return None
            return v
    return None


def costo_de_tokens(entrada: float, salida_con_razonamiento: float, vigencia: dict) -> float:
    """USD de una cantidad de tokens. El razonamiento se factura como salida."""
    return (entrada / 1e6 * vigencia["entrada_por_millon"]
            + salida_con_razonamiento / 1e6 * vigencia["salida_por_millon"])


def costo(estimacion: dict, precios: dict, modelo: str, fecha: str) -> dict:
    """Costo estimado de un plan con los precios vigentes en `fecha`, o `None` sin precio."""
    v = precio_vigente(precios, modelo, fecha)
    if v is None:
        return {"costo": None,
                "motivo": f"sin precio vigente de {modelo} el {fecha} (o la tabla no declara "
                          f"fecha de consulta y fuente)"}
    entrada = salida = 0
    for f in estimacion["filas"]:
        if f["por_corrida"] is None:
            continue
        entrada += f["por_corrida"]["entrada"] * f["corridas"]
        salida += (f["por_corrida"]["salida"] + f["por_corrida"]["razonamiento"]) * f["corridas"]
    return {"costo": round(costo_de_tokens(entrada, salida, v), 4),
            "moneda": precios.get("moneda"), "fecha": fecha,
            "fecha_de_precios": precios["fecha_de_consulta"], "fuente_de_precios": precios["fuente"],
            "vigencia": {"desde": v.get("desde"), "hasta": v.get("hasta")},
            "nota": "solo incluye las corridas con medición"}


def mediciones_de_un_resumen(resumen: dict) -> dict[tuple[str, str], dict]:
    """Tokens POR CORRIDA (media de las corridas completas) por (arquitectura, dataset), a
    partir de la tabla de consumo de una consolidación. Para el baseline no hay tokens."""
    salida = {}
    for f in resumen["tablas"]["consumo"]["filas"]:
        if f["arquitectura"] == "baseline_reglas" or f.get("tokens_entrada_medios") is None:
            continue
        salida[(f["arquitectura"], f["dataset"])] = {
            "entrada": f["tokens_entrada_medios"], "salida": f["tokens_salida_medios"],
            "razonamiento": f["tokens_razonamiento_medios"],
            "llamadas": f["llamadas_medias"], "n": f["n_completas"]}
    return salida


def costo_real(resumen: dict, precios: dict, modelo: str, fecha: str) -> dict:
    """Costo de lo que YA se ejecutó (suma de las corridas completas de una consolidación)."""
    v = precio_vigente(precios, modelo, fecha)
    entrada = salida = razon = corridas = llamadas = 0.0
    for f in resumen["tablas"]["consumo"]["filas"]:
        if f["arquitectura"] == "baseline_reglas" or f.get("tokens_entrada_medios") is None:
            continue
        n = f["n_completas"]
        entrada += f["tokens_entrada_medios"] * n
        salida += f["tokens_salida_medios"] * n
        razon += f["tokens_razonamiento_medios"] * n
        llamadas += f["llamadas_medias"] * n
        corridas += n
    base = {"corridas_con_llm": round(corridas), "llamadas": round(llamadas),
            "tokens_entrada": round(entrada), "tokens_salida": round(salida),
            "tokens_razonamiento": round(razon)}
    if v is None:
        return {**base, "costo": None, "motivo": f"sin precio vigente de {modelo} el {fecha}"}
    return {**base, "costo": round(costo_de_tokens(entrada, salida + razon, v), 4),
            "moneda": precios.get("moneda"), "fecha": fecha,
            "vigencia": {"desde": v.get("desde"), "hasta": v.get("hasta")}}


def estimar_campana(casos: dict[str, int], repeticiones: int,
                    mediciones: dict[tuple[str, str], dict], precios: dict, modelo: str,
                    fechas: dict[str, str], arquitecturas: tuple[str, ...]) -> dict:
    """Orden de magnitud de una campaña: casos por dataset × repeticiones × tokens por corrida.

    `mediciones`: tokens por corrida por celda. `fechas`: nombre de escenario -> fecha, para
    mostrar el costo bajo cada vigencia de precios. El baseline NO se presupuesta. Una celda
    sin medición no suma y se declara.
    """
    filas, sin_medicion = [], []
    totales = {nombre: 0.0 for nombre in fechas}
    tokens_total = 0.0
    for dataset, n_casos in casos.items():
        for arq in arquitecturas:
            m = mediciones.get((arq, dataset))
            corridas = n_casos * repeticiones
            if m is None:
                sin_medicion.append({"arquitectura": arq, "dataset": dataset, "corridas": corridas})
                continue
            por_corrida = {k: m[k] for k in ("entrada", "salida", "razonamiento")}
            costos = {}
            for nombre, fecha in fechas.items():
                v = precio_vigente(precios, modelo, fecha)
                costos[nombre] = (None if v is None else round(costo_de_tokens(
                    m["entrada"] * corridas, (m["salida"] + m["razonamiento"]) * corridas, v), 2))
                if costos[nombre] is not None:
                    totales[nombre] += costos[nombre]
            tokens = (m["entrada"] + m["salida"] + m["razonamiento"]) * corridas
            tokens_total += tokens
            filas.append({"arquitectura": arq, "dataset": dataset, "casos": n_casos,
                          "repeticiones": repeticiones, "corridas": corridas,
                          "tokens_por_corrida": round(sum(por_corrida.values())),
                          "tokens": round(tokens), "base": f"media de {m['n']} corridas medidas",
                          "costo": costos})
    return {
        "es": "orden de magnitud; no es un presupuesto",
        "baseline": "no se presupuesta (no usa el modelo)",
        "filas": filas, "tokens_total": round(tokens_total),
        "costo_total": {k: round(v, 2) for k, v in totales.items()},
        "celdas_sin_medicion": sin_medicion,
    }
