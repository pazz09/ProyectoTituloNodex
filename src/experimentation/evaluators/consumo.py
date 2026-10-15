"""Evaluador de consumo (D5). Fase 5, acción 6.

Agrega la telemetría de las corridas. **La instrumentación es de la Fase 6**;
acá solo se define cómo se resume lo que esa fase registre.

Dos decisiones que cambian lo que el número significa:

1. **Las corridas fallidas no entran en los promedios, y se cuentan
   aparte.** Una corrida que se cortó por cuota agotada consumió menos
   tokens que una completa: promediarla bajaría el consumo medio y haría
   parecer más eficiente a la arquitectura que falló más. El plan lo pide
   explícitamente: separar calidad del resultado de éxito operacional.

2. **Se informa la mediana además de la media.** Una sola corrida con
   reintentos puede duplicar la media de latencia; la mediana muestra el
   caso típico. Las dos juntas dicen más que cualquiera sola.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Métricas de consumo, con los nombres que produce `src/telemetry.py`
#: (`resumen_telemetria`, contrato `d11-v1`).
#:
#: Este evaluador esperaba antes `tokens_entrada`, `latencia_total_s`,
#: `llamadas_llm`, etc. —nombres que escribí yo antes de que existiera la
#: telemetría real— y con la telemetría de `d11-v1` habría dado toda la
#: columna como ausente, sin error. Las pruebas pasaban porque sus fixtures
#: usaban los mismos nombres equivocados. Se detectó al conectar el
#: consolidador con las salidas guardadas.
CAMPOS_TELEMETRIA = (
    "llm_call_count",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "reasoning_tokens",
    "execution_time",
    "replan_count",
    "intentos_correccion",
    "invalid_evidence_uid_count",
)


@dataclass
class ResultadoConsumo:
    #: `{campo: {media, mediana, min, max, total}}`, solo de corridas completas.
    por_campo: dict = field(default_factory=dict)
    n_corridas_completas: int = 0
    #: `{estado: n}` para los estados de ejecución que no son `completa`.
    n_por_estado_ejecucion: dict = field(default_factory=dict)
    #: Campos que la telemetría no trajo en alguna corrida completa.
    campos_ausentes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "por_campo": self.por_campo,
            "n_corridas_completas": self.n_corridas_completas,
            "n_por_estado_ejecucion": self.n_por_estado_ejecucion,
            "campos_ausentes": self.campos_ausentes,
            "nota": (
                "las corridas no completas se cuentan pero no entran en los "
                "promedios: una corrida cortada consumió menos y bajaría el "
                "consumo medio de la arquitectura que falló más"
            ),
        }


def _mediana(valores: list[float]) -> float | None:
    if not valores:
        return None
    ordenados = sorted(valores)
    n = len(ordenados)
    mitad = n // 2
    if n % 2:
        return float(ordenados[mitad])
    return (ordenados[mitad - 1] + ordenados[mitad]) / 2


def _resumen(valores: list[float]) -> dict:
    if not valores:
        return {"media": None, "mediana": None, "min": None, "max": None,
                "total": None, "n": 0}
    return {
        "media": sum(valores) / len(valores),
        "mediana": _mediana(valores),
        "min": min(valores),
        "max": max(valores),
        "total": sum(valores),
        "n": len(valores),
    }


def agregar(corridas: list[dict]) -> ResultadoConsumo:
    """Agrega la telemetría de una lista de corridas.

    Cada corrida es un dict con al menos `estado` y `telemetria`.
    """
    completas = [c for c in corridas if c.get("estado") == "completa"]
    no_completas: dict[str, int] = {}
    for corrida in corridas:
        estado = corrida.get("estado")
        if estado != "completa":
            no_completas[str(estado)] = no_completas.get(str(estado), 0) + 1

    por_campo: dict = {}
    ausentes: dict = {}
    for campo in CAMPOS_TELEMETRIA:
        valores: list[float] = []
        faltan = 0
        for corrida in completas:
            valor = (corrida.get("telemetria") or {}).get(campo)
            if isinstance(valor, bool) or not isinstance(valor, (int, float)):
                faltan += 1
                continue
            valores.append(float(valor))
        por_campo[campo] = _resumen(valores)
        if faltan:
            # Un campo ausente no se rellena con 0: se declara, porque un 0
            # inventado bajaría la media y nadie podría notarlo.
            ausentes[campo] = faltan

    return ResultadoConsumo(
        por_campo=por_campo,
        n_corridas_completas=len(completas),
        n_por_estado_ejecucion=no_completas,
        campos_ausentes=ausentes,
    )
