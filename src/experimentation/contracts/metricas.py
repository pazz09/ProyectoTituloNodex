"""Contrato de métricas. **Define la forma, no calcula nada.**

El cálculo es de la Fase 5 (`src/experimentation/evaluators/`). Acá se fija
qué campos existe obligación de reportar y qué invariantes deben cumplirse,
para que ningún evaluador pueda publicar una matriz de confusión
inconsistente con los conteos de casos no puntuables.

Las fórmulas quedan especificadas en `docs/experimentacion/protocolo.md`
(§6). La que importa recordar acá, porque corrige un defecto medido:

    F1 = 2·TP / (2·TP + FP + FN)

El cálculo anterior usaba `2·P·R/(P+R)` con una guarda `if precision and
recall`, y como `0.0` es falso en Python, un caso con TP=0, FP=6, FN=1
devolvía F1 indefinido cuando el valor correcto es 0. Con la forma directa,
el único indefinido real es `2TP+FP+FN == 0`, es decir un conjunto sin
positivos reales ni predichos.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.experimentation.contracts.enums import (
    ARQUITECTURAS,
    DIMENSIONES,
    ESTADOS_NO_PUNTUABLES,
)


def _validar_en(valor, admitidos: tuple, campo: str) -> None:
    if valor not in admitidos:
        raise ValueError(
            f"{campo} inválido: {valor!r}. Admitidos: {', '.join(admitidos)}"
        )


@dataclass
class DetectionCounts:
    """Matriz de confusión de una dimensión binaria.

    Positivo = `anomalo` en detección operativa, `MALICIOUS` en detección de
    seguridad. Solo entran casos `evaluable`: los cuatro estados no
    puntuables se cuentan aparte, en `MetricsRecord`.
    """

    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    def __post_init__(self) -> None:
        for campo in ("tp", "fp", "fn", "tn"):
            valor = getattr(self, campo)
            # `bool` es subclase de `int`: sin descartarlo, un `True` pasaría
            # como el conteo 1 y la matriz describiría un flag en vez de un
            # caso.
            if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
                raise ValueError(f"{campo} debe ser un entero >= 0; es {valor!r}")

    @property
    def total(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MetricsRecord:
    """Métricas de una dimensión, para una arquitectura y un dataset.

    `None` en una métrica significa **indefinida por denominador cero**, no
    cero. La distinción es obligatoria: un recall indefinido (no había
    positivos reales) y un recall 0 (había y no detectó ninguno) describen
    situaciones opuestas, y el informe anterior los mostró ambos como "no
    definido" por el defecto de F1 descrito arriba.
    """

    dimension: str
    arquitectura: str
    dataset: str
    protocolo_version: str
    #: Unidad sobre la que se agregó: `caso`, `repeticion`, `dataset`.
    unidad_agregacion: str = "dataset"

    # --- D1 detección ---
    conteos: DetectionCounts | None = None
    accuracy: float | None = None
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    fpr: float | None = None
    fnr: float | None = None

    # --- D2 reconstrucción / D3 MITRE (comparación de conjuntos) ---
    #: Para reconstrucción: conjuntos de `uid`. Para MITRE: conjuntos de IDs
    #: al nivel declarado. `exact_match` es la fracción de casos en que los
    #: conjuntos coinciden por completo.
    set_precision: float | None = None
    set_recall: float | None = None
    set_f1: float | None = None
    exact_match: float | None = None
    #: Nivel evaluado cuando la dimensión es MITRE (`tactica`/`tecnica`).
    nivel: str | None = None

    # --- D4 reporte (rúbrica humana) ---
    #: Promedio por criterio de la rúbrica. No se calcula contra un texto de
    #: referencia: el plan prohíbe reportes gold.
    rubrica_por_criterio: dict = field(default_factory=dict)
    rubrica_n_evaluadores: int | None = None

    # --- D5 consumo ---
    consumo: dict = field(default_factory=dict)

    # --- contabilidad de casos ---
    n_casos: int = 0
    n_evaluables: int = 0
    #: Conteo por cada estado no puntuable. La suma de estos más
    #: `n_evaluables` debe dar `n_casos`: si no cuadra, se perdió un caso en
    #: el camino y la métrica no es publicable.
    n_por_estado: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validar_en(self.dimension, DIMENSIONES, "dimension")
        _validar_en(self.arquitectura, ARQUITECTURAS, "arquitectura")
        if not self.protocolo_version:
            raise ValueError("protocolo_version no puede estar vacía")
        for estado in self.n_por_estado:
            _validar_en(estado, ESTADOS_NO_PUNTUABLES, "n_por_estado (clave)")
        if self.n_casos < 0 or self.n_evaluables < 0:
            raise ValueError("n_casos y n_evaluables no pueden ser negativos")
        if self.n_evaluables > self.n_casos:
            raise ValueError(
                f"n_evaluables ({self.n_evaluables}) no puede superar n_casos "
                f"({self.n_casos})"
            )
        suma = self.n_evaluables + sum(self.n_por_estado.values())
        if self.n_casos and suma != self.n_casos:
            raise ValueError(
                f"La contabilidad no cuadra: n_evaluables + no puntuables = "
                f"{suma}, pero n_casos = {self.n_casos}. Un caso perdido entre "
                "medio invalida la métrica."
            )
        if self.conteos is not None and self.conteos.total != self.n_evaluables:
            raise ValueError(
                f"La matriz de confusión suma {self.conteos.total} casos, pero "
                f"n_evaluables = {self.n_evaluables}."
            )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["conteos"] = self.conteos.to_dict() if self.conteos else None
        return d
