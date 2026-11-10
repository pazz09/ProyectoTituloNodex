"""Métricas de conjuntos, compartidas por reconstrucción (D2) y MITRE (D3).

Las dos dimensiones hacen la misma pregunta: el sistema propuso un conjunto
de elementos y hay un conjunto de referencia, ¿cuánto coinciden? En D2 los
elementos son `uid` de eventos; en D3, identificadores de táctica o de
técnica.

## Micro y macro no son lo mismo, y hay que declarar cuál se informa

- **Micro**: se juntan los elementos de todos los casos y se calcula una
  sola matriz. Un caso con 50 eventos pesa 50 veces más que uno con 1.
- **Macro**: se calcula la métrica por caso y se promedian. Cada caso pesa
  igual, pero un caso con un solo elemento mueve el promedio tanto como uno
  grande.

Se informan **las dos**, porque eligen distinto y la diferencia entre ellas
es informativa: si micro es mucho mayor que macro, el sistema acierta en los
casos grandes y falla en los chicos.

## Exact match

Fracción de casos en que los dos conjuntos coinciden **por completo**. Es la
métrica más exigente y la que mejor refleja si la reconstrucción sirve: un
analista que recibe 8 de 10 eventos correctos y 3 inventados tiene que
revisar todo igual.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ComparacionConjuntos:
    """Comparación de un caso: lo propuesto contra la referencia."""

    case_id: str
    propuesto: frozenset[str]
    referencia: frozenset[str]

    @property
    def tp(self) -> int:
        return len(self.propuesto & self.referencia)

    @property
    def fp(self) -> int:
        return len(self.propuesto - self.referencia)

    @property
    def fn(self) -> int:
        return len(self.referencia - self.propuesto)

    @property
    def coincide_exacto(self) -> bool:
        return self.propuesto == self.referencia

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "n_propuesto": len(self.propuesto),
            "n_referencia": len(self.referencia),
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "coincide_exacto": self.coincide_exacto,
            # Los elementos sobrantes y faltantes se listan para poder
            # auditar un resultado: sin esto, un F1 bajo no dice si el
            # sistema inventó eventos o se perdió los reales.
            "sobrantes": sorted(self.propuesto - self.referencia),
            "faltantes": sorted(self.referencia - self.propuesto),
        }


def _division(numerador: int | float, denominador: int | float) -> float | None:
    if denominador == 0:
        return None
    return numerador / denominador


def _metricas_de_conteos(tp: int, fp: int, fn: int) -> dict[str, float | None]:
    return {
        "precision": _division(tp, tp + fp),
        "recall": _division(tp, tp + fn),
        # Misma forma directa que en detección, por la misma razón: con
        # `2PR/(P+R)` y una guarda de verdad, un F1 de 0 se informaría como
        # indefinido.
        "f1": _division(2 * tp, 2 * tp + fp + fn),
    }


@dataclass
class ResultadoConjuntos:
    micro: dict = field(default_factory=dict)
    macro: dict = field(default_factory=dict)
    exact_match: float | None = None
    n_casos: int = 0
    conteos_totales: dict = field(default_factory=dict)
    por_caso: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "micro": self.micro,
            "macro": self.macro,
            "exact_match": self.exact_match,
            "n_casos": self.n_casos,
            "conteos_totales": self.conteos_totales,
            "por_caso": self.por_caso,
        }


def _promedio(valores: list[float | None]) -> float | None:
    """Promedia ignorando los `None`, que son indefinidos y no ceros.

    Si todos son `None` el promedio también lo es: no hay nada que
    promediar. Tratar un indefinido como 0 bajaría el promedio con casos
    que no aportan información.
    """
    definidos = [v for v in valores if v is not None]
    if not definidos:
        return None
    return sum(definidos) / len(definidos)


def evaluar_conjuntos(
    comparaciones: list[ComparacionConjuntos],
) -> ResultadoConjuntos:
    """Micro, macro y exact match sobre una lista de comparaciones."""
    if not comparaciones:
        return ResultadoConjuntos(
            micro={"precision": None, "recall": None, "f1": None},
            macro={"precision": None, "recall": None, "f1": None},
            exact_match=None,
            n_casos=0,
            conteos_totales={"tp": 0, "fp": 0, "fn": 0},
        )

    tp = sum(c.tp for c in comparaciones)
    fp = sum(c.fp for c in comparaciones)
    fn = sum(c.fn for c in comparaciones)

    por_caso = [_metricas_de_conteos(c.tp, c.fp, c.fn) for c in comparaciones]
    return ResultadoConjuntos(
        micro=_metricas_de_conteos(tp, fp, fn),
        macro={
            clave: _promedio([m[clave] for m in por_caso])
            for clave in ("precision", "recall", "f1")
        },
        exact_match=sum(c.coincide_exacto for c in comparaciones) / len(comparaciones),
        n_casos=len(comparaciones),
        conteos_totales={"tp": tp, "fp": fp, "fn": fn},
        por_caso=[c.to_dict() for c in comparaciones],
    )
