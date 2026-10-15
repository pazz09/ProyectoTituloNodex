"""Presupuesto: costo de lo ya ejecutado, costo por celda y riesgo de superar un tope.

Todo se calcula con los TOKENS MEDIDOS (la telemetría de cada corrida) y la tabla de precios de
`estimacion.py`; no se supone ningún precio ni ningún consumo. El razonamiento se factura como salida.

## Qué es un costo «parcial»

`src/telemetry.py` deja los totales de una corrida en `None` si una llamada falló. Acá se suman las
llamadas que SÍ informaron tokens: es un piso (el gasto real de una llamada fallida no se conoce) y se
marca `parcial`.

Solo LEE lo guardado.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from src.experimentation import estimacion

ARQUITECTURAS_CON_MODELO = ("nodex_multiagente", "gemini_externo")


def _entero(valor) -> int | None:
    return valor if isinstance(valor, int) and not isinstance(valor, bool) and valor >= 0 else None


def costo_de_telemetria(telemetria: dict | None, vigencia: dict) -> dict:
    """USD de una corrida a partir de sus llamadas. `parcial` si alguna no informó tokens."""
    llamadas = [c for c in ((telemetria or {}).get("llm_calls") or []) if isinstance(c, dict)]
    entrada = salida = 0
    sin_tokens = 0
    for c in llamadas:
        i, o = _entero(c.get("input_tokens")), _entero(c.get("output_tokens"))
        if i is None or o is None:
            sin_tokens += 1
            continue
        entrada += i
        salida += o + (_entero(c.get("reasoning_tokens")) or 0)     # el razonamiento es salida
    return {"usd": estimacion.costo_de_tokens(entrada, salida, vigencia) if llamadas else 0.0,
            "parcial": sin_tokens > 0, "llamadas": len(llamadas), "llamadas_sin_tokens": sin_tokens,
            "tokens_entrada": entrada, "tokens_salida_y_razonamiento": salida}


def _telemetrias(raiz_repo: Path, config_version: str):
    for ruta in sorted((raiz_repo / "experiments" / "telemetry").glob("*/*.json")):
        if ruta.name.endswith((".consultas_externas.json", ".llm_json.json")):
            continue
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        if datos.get("config_version") == config_version:
            yield datos


def gasto_acumulado(raiz_repo: Path, config_version: str, precios: dict, modelo: str,
                    fecha: str) -> dict:
    """Gasto de TODAS las corridas guardadas de una configuración (se recalcula desde la
    telemetría; no se confía en ningún contador aparte, así que reanudar no puede perder gasto)."""
    vigencia = estimacion.precio_vigente(precios, modelo, fecha)
    if vigencia is None:
        raise ValueError(f"no hay precio vigente de {modelo} el {fecha}: no se puede medir el gasto")
    por_corrida, parciales = {}, []
    for d in _telemetrias(raiz_repo, config_version):
        c = costo_de_telemetria(d.get("telemetria"), vigencia)
        por_corrida[d["run_id"]] = round(c["usd"], 6)
        if c["parcial"]:
            parciales.append(d["run_id"])
    return {"usd": round(sum(por_corrida.values()), 6), "corridas": len(por_corrida),
            "corridas_con_costo_parcial": parciales, "por_corrida": por_corrida,
            "fecha_de_precios": fecha, "vigencia": {"desde": vigencia.get("desde"),
                                                   "hasta": vigencia.get("hasta")}}


def costos_por_celda(raiz_repo: Path, config_version: str, precios: dict, modelo: str,
                     fecha: str) -> dict[str, dict]:
    """Costo por corrida de cada (arquitectura, dataset): mínimo, media, máximo y todos los valores.

    La clave es `"<arquitectura>|<dataset>"` (JSON no admite tuplas). El baseline no usa el modelo y no
    figura.
    """
    vigencia = estimacion.precio_vigente(precios, modelo, fecha)
    if vigencia is None:
        raise ValueError(f"no hay precio vigente de {modelo} el {fecha}")
    celdas: dict[str, list[float]] = {}
    for d in _telemetrias(raiz_repo, config_version):
        if d["arquitectura"] not in ARQUITECTURAS_CON_MODELO:
            continue
        usd = costo_de_telemetria(d.get("telemetria"), vigencia)["usd"]
        celdas.setdefault(f"{d['arquitectura']}|{d['dataset']}", []).append(round(usd, 6))
    return {k: {"n": len(v), "minimo": min(v), "media": sum(v) / len(v), "maximo": max(v),
                "valores": sorted(v)} for k, v in sorted(celdas.items())}


def costo_maximo_esperado(costos: dict, arquitectura: str, dataset: str) -> float:
    """Costo máximo observado de una celda. Si la celda no se midió, el máximo de su arquitectura;
    si tampoco, el de todo lo medido (siempre el lado conservador)."""
    if arquitectura not in ARQUITECTURAS_CON_MODELO:
        return 0.0
    celda = costos.get(f"{arquitectura}|{dataset}")
    if celda:
        return celda["maximo"]
    de_la_arquitectura = [c["maximo"] for k, c in costos.items() if k.startswith(f"{arquitectura}|")]
    todos = [c["maximo"] for c in costos.values()]
    return max(de_la_arquitectura or todos or [0.0])


def costo_esperado_de_un_plan(costos: dict, corridas_por_celda: dict[tuple[str, str], int]) -> dict:
    """Mínimo, media y máximo del costo de un plan, sumando por celda lo observado en el piloto.

    `corridas_por_celda`: `{(arquitectura, dataset): n_corridas}`. Es un RANGO observado: el mínimo
    supone que toda corrida cuesta lo que la más barata del piloto; el máximo, lo que la más cara.
    """
    minimo = media = maximo = 0.0
    sin_medicion = []
    for (arq, ds), n in sorted(corridas_por_celda.items()):
        if arq not in ARQUITECTURAS_CON_MODELO:
            continue
        c = costos.get(f"{arq}|{ds}")
        if c is None:
            sin_medicion.append({"arquitectura": arq, "dataset": ds, "corridas": n})
            continue
        minimo += c["minimo"] * n
        media += c["media"] * n
        maximo += c["maximo"] * n
    return {"minimo": round(minimo, 4), "media": round(media, 4), "maximo": round(maximo, 4),
            "celdas_sin_medicion": sin_medicion}


def riesgo_de_superar(costos: dict, corridas_por_celda: dict[tuple[str, str], int],
                      topes: tuple[float, ...], semilla: int = 20261015,
                      n_simulaciones: int = 20000) -> dict:
    """Probabilidad de que el costo total supere cada tope, remuestreando los costos del piloto.

    Para cada simulación se saca, por cada corrida del plan, un costo al azar (con reposición) de los
    observados en su celda. Es una estimación con pocos datos por celda (los del piloto): sirve para
    comparar planes, no como garantía. La semilla queda registrada.
    """
    rng = random.Random(semilla)
    celdas = [(costos[f"{a}|{d}"]["valores"], n) for (a, d), n in sorted(corridas_por_celda.items())
              if a in ARQUITECTURAS_CON_MODELO and f"{a}|{d}" in costos]
    totales = sorted(sum(sum(rng.choice(valores) for _ in range(n)) for valores, n in celdas)
                     for _ in range(n_simulaciones))
    return {
        "semilla": semilla, "simulaciones": n_simulaciones,
        "p5": round(totales[int(0.05 * n_simulaciones)], 4),
        "mediana": round(totales[n_simulaciones // 2], 4),
        "p95": round(totales[int(0.95 * n_simulaciones)], 4),
        "p99": round(totales[int(0.99 * n_simulaciones) - 1], 4),
        "maximo_simulado": round(totales[-1], 4),
        "prob_de_superar": {str(t): sum(1 for x in totales if x > t) / n_simulaciones for t in topes},
    }
