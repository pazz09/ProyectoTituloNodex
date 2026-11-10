"""Evaluador del reporte (D4). Fase 5, acción 5.

**No compara contra ningún texto de referencia.** El plan prohíbe reportes
gold, `gold_claims`, `expected_facts` y conclusiones esperadas. Este módulo
solo **agrega** lo que dos personas puntuaron: no juzga nada por sí mismo.

Escala y evaluadores: decisión D-4 — **0 a 3 por criterio, dos evaluadores,
con la concordancia informada**. Los descriptores de cada nivel están en
`docs/experimentacion/anotacion_ground_truth.md` §5.

## Sobre la concordancia

Se informan tres medidas simples y verificables a mano:

- **acuerdo exacto**: fracción de puntuaciones idénticas entre los dos.
- **acuerdo ±1**: fracción que difiere en a lo más un nivel. En una escala
  de 4 niveles, una diferencia de 1 es ruido normal entre anotadores; una
  de 2 o 3 indica que el descriptor no está claro.
- **diferencia absoluta media**.

**No se calcula ningún coeficiente kappa.** Elegir cuál (Cohen simple,
ponderado lineal, ponderado cuadrático) es una decisión metodológica, no una
de implementación, y queda registrada como pendiente. Publicar un kappa
calculado con una fórmula que nunca se ejecutó sería peor que no publicarlo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Los cinco criterios, en el orden en que los lista el plan.
CRITERIOS = (
    "completitud",
    "correccion_factual",
    "coherencia_con_evidencia",
    "claridad",
    "informacion_no_sustentada",
)

#: Escala de la decisión D-4.
PUNTAJE_MINIMO, PUNTAJE_MAXIMO = 0, 3

#: Número de evaluadores de la decisión D-4.
EVALUADORES_ESPERADOS = 2

#: Diferencia a partir de la cual un desacuerdo se informa individualmente,
#: en vez de promediarse. Un desacuerdo de 2 niveles en una escala de 4 no
#: es ruido: o el descriptor no está claro o los evaluadores entendieron
#: cosas distintas.
DESACUERDO_RELEVANTE = 2


@dataclass(frozen=True)
class PuntuacionRubrica:
    """Lo que un evaluador puntuó para un reporte."""

    case_id: str
    arquitectura: str
    evaluador: str
    #: `{criterio: 0..3}`, los cinco criterios.
    puntajes: dict

    def __post_init__(self) -> None:
        faltantes = set(CRITERIOS) - set(self.puntajes)
        if faltantes:
            raise ValueError(
                f"{self.case_id}/{self.evaluador}: faltan criterios "
                f"{sorted(faltantes)}. Una rúbrica incompleta no se promedia"
            )
        sobrantes = set(self.puntajes) - set(CRITERIOS)
        if sobrantes:
            raise ValueError(
                f"{self.case_id}/{self.evaluador}: criterios desconocidos "
                f"{sorted(sobrantes)}"
            )
        for criterio, valor in self.puntajes.items():
            if isinstance(valor, bool) or not isinstance(valor, int):
                raise ValueError(
                    f"{self.case_id}/{self.evaluador}/{criterio}: el puntaje "
                    f"debe ser un entero; es {valor!r}"
                )
            if not PUNTAJE_MINIMO <= valor <= PUNTAJE_MAXIMO:
                raise ValueError(
                    f"{self.case_id}/{self.evaluador}/{criterio}: {valor} "
                    f"está fuera de la escala {PUNTAJE_MINIMO}-{PUNTAJE_MAXIMO}"
                )


@dataclass
class ResultadoRubrica:
    #: Promedio por criterio, sobre todos los reportes y evaluadores.
    por_criterio: dict = field(default_factory=dict)
    #: Promedio de los cinco criterios. Tiene sentido porque los cinco están
    #: orientados igual: en los cinco, más alto es mejor. El criterio
    #: `informacion_no_sustentada` está redactado al revés de la intuición
    #: justamente para eso (3 = no hay información sin sustento).
    promedio_global: float | None = None
    n_reportes: int = 0
    n_evaluadores: int = 0
    concordancia: dict = field(default_factory=dict)
    #: Desacuerdos de 2 niveles o más, listados uno por uno.
    desacuerdos_relevantes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "por_criterio": self.por_criterio,
            "promedio_global": self.promedio_global,
            "n_reportes": self.n_reportes,
            "n_evaluadores": self.n_evaluadores,
            "concordancia": self.concordancia,
            "desacuerdos_relevantes": self.desacuerdos_relevantes,
            "escala": f"{PUNTAJE_MINIMO}-{PUNTAJE_MAXIMO}",
            "kappa": None,
            "nota_kappa": (
                "no se calcula: elegir el coeficiente es una decisión "
                "metodológica pendiente, no de implementación"
            ),
        }


def _promedio(valores: list[float]) -> float | None:
    return (sum(valores) / len(valores)) if valores else None


def agregar(puntuaciones: list[PuntuacionRubrica]) -> ResultadoRubrica:
    """Agrega las puntuaciones y calcula la concordancia entre evaluadores."""
    if not puntuaciones:
        return ResultadoRubrica()

    evaluadores = sorted({p.evaluador for p in puntuaciones})
    reportes = sorted({(p.case_id, p.arquitectura) for p in puntuaciones})

    por_criterio = {
        criterio: _promedio([p.puntajes[criterio] for p in puntuaciones])
        for criterio in CRITERIOS
    }
    definidos = [v for v in por_criterio.values() if v is not None]

    resultado = ResultadoRubrica(
        por_criterio=por_criterio,
        promedio_global=_promedio(definidos),
        n_reportes=len(reportes),
        n_evaluadores=len(evaluadores),
    )

    # Concordancia: solo entre reportes que los DOS evaluadores puntuaron.
    # Un reporte puntuado por uno solo no aporta concordancia y se cuenta
    # aparte, en vez de inflar el acuerdo.
    indice: dict = {}
    for puntuacion in puntuaciones:
        clave = (puntuacion.case_id, puntuacion.arquitectura)
        indice.setdefault(clave, {})[puntuacion.evaluador] = puntuacion.puntajes

    comparables = [v for v in indice.values() if len(v) == EVALUADORES_ESPERADOS]
    diferencias: list[int] = []
    for clave, por_evaluador in sorted(indice.items()):
        if len(por_evaluador) != EVALUADORES_ESPERADOS:
            continue
        primero, segundo = (por_evaluador[e] for e in sorted(por_evaluador))
        for criterio in CRITERIOS:
            diferencia = abs(primero[criterio] - segundo[criterio])
            diferencias.append(diferencia)
            if diferencia >= DESACUERDO_RELEVANTE:
                resultado.desacuerdos_relevantes.append({
                    "case_id": clave[0],
                    "arquitectura": clave[1],
                    "criterio": criterio,
                    "puntajes": sorted(
                        (e, p[criterio]) for e, p in por_evaluador.items()
                    ),
                    "diferencia": diferencia,
                })

    resultado.concordancia = {
        "reportes_con_dos_evaluadores": len(comparables),
        "reportes_con_un_evaluador": len(indice) - len(comparables),
        "n_comparaciones": len(diferencias),
        "acuerdo_exacto": (
            sum(1 for d in diferencias if d == 0) / len(diferencias)
            if diferencias else None
        ),
        "acuerdo_hasta_un_nivel": (
            sum(1 for d in diferencias if d <= 1) / len(diferencias)
            if diferencias else None
        ),
        "diferencia_absoluta_media": _promedio([float(d) for d in diferencias]),
        "n_desacuerdos_relevantes": len(resultado.desacuerdos_relevantes),
    }
    return resultado
