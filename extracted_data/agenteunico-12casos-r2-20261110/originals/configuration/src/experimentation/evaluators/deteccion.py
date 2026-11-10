"""Evaluador de detección (D1). Fase 5, acción 2.

Consume salidas guardadas y ground truth reservado. **No importa ningún
agente ni el pipeline**: un evaluador que pudiera invocar al sistema podría,
por descuido, evaluar una corrida nueva en vez de la guardada.

## La fórmula de F1, y por qué se cambió

    F1 = 2·TP / (2·TP + FP + FN)

El evaluador anterior (`src/tools/eval_deteccion.py`) usaba
`2·P·R / (P + R)` con una guarda `if precision and recall`. Como `0.0` es
falso en Python, un conjunto con TP=0, FP=6, FN=1 devolvía F1 **indefinido**
cuando el valor correcto es **0**. Son cosas distintas: indefinido significa
"la métrica no está definida para este conjunto"; cero significa "el sistema
no acertó ni un positivo". El informe anterior los mostró iguales.

Con la forma directa el único indefinido real es `2TP+FP+FN == 0`, es decir
un conjunto sin positivos reales ni predichos. Ahí F1 es genuinamente
indefinido y se devuelve `None`.

## `None` nunca significa cero

Cada métrica devuelve `None` cuando su denominador es cero, y eso se informa
como "indefinida", no como 0,0. Un recall indefinido (no había positivos
reales) y un recall 0 (había y no detectó ninguno) describen situaciones
opuestas.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.experimentation.contracts.metricas import DetectionCounts

#: Etiqueta de referencia y clasificación de salida que cuentan como
#: positivo. En detección operativa el positivo es `anomalo`; en detección
#: de seguridad, `MALICIOUS`. Son el mismo eje leído distinto, y el
#: `tipo_deteccion` del caso define la lectura.
POSITIVO_REFERENCIA = "anomalo"
POSITIVO_PREDICCION = "MALICIOUS"


@dataclass(frozen=True)
class ParDeteccion:
    """Un caso evaluable: lo que dijo el sistema y lo que dice la referencia."""

    case_id: str
    #: `MALICIOUS` | `BENIGN`. Nunca `None`: un caso sin veredicto no es
    #: evaluable y no llega hasta acá.
    prediccion: str
    #: `anomalo` | `normal`.
    referencia: str


def contar(pares: list[ParDeteccion]) -> DetectionCounts:
    """Matriz de confusión. Solo recibe casos evaluables."""
    tp = fp = fn = tn = 0
    for par in pares:
        if par.prediccion not in ("MALICIOUS", "BENIGN"):
            raise ValueError(
                f"{par.case_id}: predicción {par.prediccion!r} no es del "
                "vocabulario. Un caso sin veredicto válido no es evaluable y "
                "no debe llegar al conteo"
            )
        if par.referencia not in ("anomalo", "normal"):
            raise ValueError(
                f"{par.case_id}: referencia {par.referencia!r} no es del "
                "vocabulario"
            )
        predice_positivo = par.prediccion == POSITIVO_PREDICCION
        es_positivo = par.referencia == POSITIVO_REFERENCIA
        if predice_positivo and es_positivo:
            tp += 1
        elif predice_positivo and not es_positivo:
            fp += 1
        elif not predice_positivo and es_positivo:
            fn += 1
        else:
            tn += 1
    return DetectionCounts(tp=tp, fp=fp, fn=fn, tn=tn)


def _division(numerador: int, denominador: int) -> float | None:
    """`None` cuando el denominador es cero: indefinida, no cero."""
    if denominador == 0:
        return None
    return numerador / denominador


def metricas(conteos: DetectionCounts) -> dict[str, float | None]:
    """Las ocho métricas de D1, con `None` donde la métrica es indefinida.

    Denominadores, para poder auditar cada `None`:

    | Métrica   | Denominador   | Indefinida cuando |
    |---|---|---|
    | accuracy  | TP+FP+FN+TN   | el conjunto está vacío |
    | precision | TP+FP         | no predijo ningún positivo |
    | recall    | TP+FN         | no había ningún positivo real |
    | f1        | 2TP+FP+FN     | no había positivos reales ni predichos |
    | fpr       | FP+TN         | no había ningún negativo real |
    | fnr       | FN+TP         | no había ningún positivo real |
    """
    tp, fp, fn, tn = conteos.tp, conteos.fp, conteos.fn, conteos.tn
    return {
        "accuracy": _division(tp + tn, tp + fp + fn + tn),
        "precision": _division(tp, tp + fp),
        "recall": _division(tp, tp + fn),
        # Forma directa: NO 2PR/(P+R). Ver el docstring del módulo.
        "f1": _division(2 * tp, 2 * tp + fp + fn),
        "fpr": _division(fp, fp + tn),
        "fnr": _division(fn, fn + tp),
    }


def evaluar(pares: list[ParDeteccion]) -> tuple[DetectionCounts, dict]:
    conteos = contar(pares)
    return conteos, metricas(conteos)
