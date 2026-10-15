"""Exportación de resultados. §14 del plan de continuación.

Produce la tabla plana que pide el plan, una fila por

    (case_id, dataset, architecture, run)

con las columnas exactas del §14. Cuando una dimensión no aplica a una
arquitectura o a un dataset, la celda va `None` (`null` en JSON, vacía en
CSV) y **nunca** 0: un 0 se promedia y una ausencia no.

## Por qué D1 no se puede llenar por fila

Precision, recall y F1 son métricas **de conjunto**: necesitan TP, FP, FN
sobre varios casos. Un caso solo aporta una celda de la matriz, así que
calcular `D1_precision` para una fila daría 1,0 o 0,0 según el cuadrante,
que no es precisión sino el acierto del caso disfrazado de métrica.

Las columnas `D1_*` existen en la fila para respetar el esquema, con valor
`None`, y el acierto del caso viaja en `D1_outcome` (`TP`, `FP`, `FN`, `TN`
o `NA`). Las métricas D1 reales se exportan agregadas, con
`exportar_agregado()`.

D2 y D3 **sí** tienen sentido por caso: comparan dos conjuntos dentro del
mismo caso, así que se llenan por fila.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

#: Columnas del §14, en ese orden. `D1_outcome` se agrega al final porque el
#: esquema del plan no tiene dónde poner el acierto por caso.
COLUMNAS = (
    "case_id",
    "dataset",
    "architecture",
    "run",
    "D1_precision",
    "D1_recall",
    "D1_f1",
    "D2_precision",
    "D2_recall",
    "D2_f1",
    "D2_exact_match",
    "D3_precision",
    "D3_recall",
    "D3_f1",
    "D3_exact_match",
    "D4_scores",
    "execution_time",
    "llm_call_count",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "replan_count",
    "intentos_correccion",
    "status",
    # --- añadidos, cada uno por una razón concreta ---
    #: Cuadrante de la matriz al que aportó este caso.
    "D1_outcome",
    #: `MALICIOUS` | `BENIGN` | `None`. Lo que el sistema afirmó.
    "D1_prediccion",
    #: Estado de cada dimensión: sin esto, un `null` no distingue "no
    #: aplica" de "falló la corrida" de "falta la referencia".
    "estado_deteccion",
    "estado_reconstruccion",
    "estado_mitre",
    "estado_reporte",
    "estado_consumo",
    #: Nivel MITRE que describen las columnas D3. Táctica y técnica se miden
    #: por separado, así que una fila por nivel.
    "D3_nivel",
    #: `True` si alguna llamada la respondió un modelo distinto del
    #: solicitado. Esa corrida no es comparable con las demás.
    "uso_fallback",
    #: Configuración congelada bajo la que corrió.
    "config_version",
    #: `True` si la telemetría se tomó antes de integrar D-11.
    "telemetria_previa_a_d11",
    #: Tokens de razonamiento (suma de las llamadas que los informaron).
    #: `None` si el proveedor no los informó: no es 0.
    "reasoning_tokens",
    #: Versión(es) que devolvió la API, separadas por "; ". `None` si no hubo.
    "modelos_efectivos",
)

#: Valor con que se representa una celda inaplicable en CSV. En JSON va
#: `null`; en CSV, vacío. Se documenta para que nadie lo lea como 0.
VACIO_CSV = ""


def _celda(valor) -> object:
    """Normaliza una celda. `None` se conserva; nunca se convierte a 0."""
    if isinstance(valor, bool):
        return valor
    if valor is None:
        return None
    return valor


def fila(
    identidad: dict,
    estados: dict,
    deteccion: dict | None = None,
    reconstruccion: dict | None = None,
    mitre: dict | None = None,
    reporte: dict | None = None,
    telemetria: dict | None = None,
    status: str = "completa",
) -> dict:
    """Arma una fila del §14 para una corrida.

    `deteccion` lleva `{prediccion, outcome}`; `reconstruccion` y `mitre`,
    las métricas de conjuntos de ese caso; `reporte`, los puntajes de la
    rúbrica si ya se aplicó.
    """
    telemetria = telemetria or {}
    reconstruccion = reconstruccion or {}
    mitre = mitre or {}
    deteccion = deteccion or {}

    return {
        "case_id": identidad.get("case_id"),
        "dataset": identidad.get("dataset"),
        "architecture": identidad.get("arquitectura"),
        "run": identidad.get("repeticion"),
        # Métricas de conjunto: no se calculan por fila. Ver el docstring.
        "D1_precision": None,
        "D1_recall": None,
        "D1_f1": None,
        "D2_precision": _celda(reconstruccion.get("precision")),
        "D2_recall": _celda(reconstruccion.get("recall")),
        "D2_f1": _celda(reconstruccion.get("f1")),
        "D2_exact_match": _celda(reconstruccion.get("coincide_exacto")),
        "D3_precision": _celda(mitre.get("precision")),
        "D3_recall": _celda(mitre.get("recall")),
        "D3_f1": _celda(mitre.get("f1")),
        "D3_exact_match": _celda(mitre.get("coincide_exacto")),
        # Los puntajes crudos de los dos evaluadores, no un promedio: el
        # promedio se calcula al agregar y la concordancia necesita los dos.
        "D4_scores": json.dumps(reporte, ensure_ascii=False) if reporte else None,
        "execution_time": _celda(telemetria.get("execution_time")),
        "llm_call_count": _celda(telemetria.get("llm_call_count")),
        "input_tokens": _celda(telemetria.get("input_tokens")),
        "output_tokens": _celda(telemetria.get("output_tokens")),
        "total_tokens": _celda(telemetria.get("total_tokens")),
        "replan_count": _celda(telemetria.get("replan_count")),
        "intentos_correccion": _celda(telemetria.get("intentos_correccion")),
        "status": status,
        "D1_outcome": deteccion.get("outcome", "NA"),
        "D1_prediccion": _celda(deteccion.get("prediccion")),
        "estado_deteccion": estados.get("deteccion"),
        "estado_reconstruccion": estados.get("reconstruccion"),
        "estado_mitre": estados.get("mitre"),
        "estado_reporte": estados.get("reporte"),
        "estado_consumo": estados.get("consumo"),
        "D3_nivel": mitre.get("nivel"),
        "uso_fallback": bool(telemetria.get("uso_fallback", False)),
        "config_version": identidad.get("config_version"),
        "telemetria_previa_a_d11": bool(
            telemetria.get("previa_a_d11", True)
        ),
        "reasoning_tokens": _celda(telemetria.get("reasoning_tokens")),
        "modelos_efectivos": "; ".join(telemetria.get("modelos_efectivos") or []) or None,
    }


def escribir_csv(filas: list[dict], destino: Path) -> Path:
    """Escribe la tabla del §14, sin sobrescribir."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        raise FileExistsError(
            f"{destino} ya existe. Los resultados no se sobrescriben"
        )
    with destino.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(
            f, fieldnames=list(COLUMNAS), restval=VACIO_CSV, extrasaction="raise"
        )
        escritor.writeheader()
        for registro in filas:
            escritor.writerow({
                clave: (VACIO_CSV if registro.get(clave) is None
                        else registro.get(clave))
                for clave in COLUMNAS
            })
    return destino


def escribir_json(filas: list[dict], destino: Path, meta: dict | None = None) -> Path:
    """La misma tabla en JSON, donde `None` sí se distingue de vacío."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        raise FileExistsError(
            f"{destino} ya existe. Los resultados no se sobrescriben"
        )
    destino.write_text(
        json.dumps(
            {
                "columnas": list(COLUMNAS),
                "nota_d1": (
                    "D1_precision/recall/f1 van null por fila: son métricas "
                    "de conjunto y por caso darían 1,0 o 0,0, que es el "
                    "acierto disfrazado de métrica. El acierto del caso está "
                    "en D1_outcome y las métricas agregadas en metrics/"
                ),
                "nota_nulos": (
                    "null significa inaplicable o ausente, nunca 0. En CSV se "
                    "escribe como celda vacía"
                ),
                "meta": meta or {},
                "filas": filas,
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )
    return destino


def resumen_de_integridad(filas: list[dict]) -> dict:
    """Conteos que tienen que acompañar cualquier tabla exportada.

    El plan prohíbe ocultar ejecuciones fallidas (§16). Este resumen hace
    que el recuento de fallos viaje junto a las métricas en vez de quedar
    en un log que nadie abre.
    """
    por_estado: dict[str, int] = {}
    for registro in filas:
        estado = str(registro.get("status"))
        por_estado[estado] = por_estado.get(estado, 0) + 1
    con_fallback = sum(1 for r in filas if r.get("uso_fallback"))
    previas = sum(1 for r in filas if r.get("telemetria_previa_a_d11"))
    return {
        "n_filas": len(filas),
        "por_status": por_estado,
        "corridas_con_fallback_de_modelo": con_fallback,
        "advertencia_fallback": (
            "esas corridas respondieron con un modelo distinto del "
            "solicitado y no son comparables con el resto"
            if con_fallback else None
        ),
        "corridas_con_telemetria_previa_a_d11": previas,
        "advertencia_d11": (
            "§11 prohíbe mezclar telemetría previa a D-11 con la posterior"
            if previas else None
        ),
    }
