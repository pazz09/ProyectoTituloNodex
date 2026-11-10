"""Evaluadores externos (Fase 5).

Separados de los agentes a propósito: **ningún módulo de acá importa
`src.pipeline`, `src.agents` ni `src.graph`**. Un evaluador que pudiera
invocar al sistema podría, por descuido, evaluar una corrida nueva en vez de
la guardada, y el resultado dependería de cuándo se corrió el evaluador.

Consumen dos cosas y nada más: salidas ya guardadas (contrato común) y
ground truth reservado.

**Ninguno de estos módulos fue ejecutado.** La acción 7 de la Fase 5 lo
prohíbe expresamente: "No ejecutar los evaluadores ni las pruebas". Por eso
las fixtures de `tests/experimentation/fixtures/` llevan el resultado
calculado a mano, con la aritmética escrita, para que la revisión no dependa
de correr nada.
"""

from src.experimentation.evaluators.agregacion import (
    construir_conjuntos,
    construir_consumo,
    construir_deteccion,
    construir_reporte,
    contabilidad,
    escribir_resultado,
)
from src.experimentation.evaluators.conjuntos import (
    ComparacionConjuntos,
    evaluar_conjuntos,
)
from src.experimentation.evaluators.deteccion import ParDeteccion, contar, metricas
from src.experimentation.evaluators.reporte import (
    CRITERIOS,
    PuntuacionRubrica,
    agregar as agregar_rubrica,
)

__all__ = [
    "CRITERIOS",
    "ComparacionConjuntos",
    "ParDeteccion",
    "PuntuacionRubrica",
    "agregar_rubrica",
    "construir_conjuntos",
    "construir_consumo",
    "construir_deteccion",
    "construir_reporte",
    "contabilidad",
    "contar",
    "escribir_resultado",
    "evaluar_conjuntos",
    "metricas",
]
