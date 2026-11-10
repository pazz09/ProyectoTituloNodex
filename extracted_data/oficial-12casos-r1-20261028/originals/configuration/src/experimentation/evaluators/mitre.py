"""Evaluador de atribución MITRE (D3). Fase 5, acción 4.

Se evalúa **un nivel a la vez**: táctica y técnica dan métricas separadas,
porque una táctica no equivale a una técnica y promediarlas daría un número
que no se puede interpretar.

Tres reglas que vienen del plan y de lo medido en los datasets:

1. **Un nivel sin referencia explícita no se evalúa.** La subtécnica queda
   `no_aplica` en UWF porque el dataset no la trae, y **no se infiere** una
   subtécnica desde la técnica padre para completar el ground truth.
2. **Una atribución sin `evidence_uids` no cuenta como acierto.** Una
   técnica adivinada y una fundamentada no son el mismo resultado. El
   adaptador ya las separa; acá se vuelve a verificar, porque el evaluador
   no debe confiar en que el adaptador filtró bien.
3. **Las candidatas del RAG no entran.** Lo que el RAG recuperó por
   similitud no es una afirmación del sistema. Viajan en `_meta` y este
   módulo no las mira.

## Coincidencia parcial entre niveles

Si el sistema atribuye la subtécnica `T1110.001` y la referencia tiene la
técnica `T1110`, hay una coincidencia parcial real. Se informa aparte, con
`coincidencias_por_padre`, y **no** se suma como acierto en el nivel de
técnica: convertir una subtécnica en su padre para que coincida sería la
inferencia que el plan prohíbe, en la dirección contraria.
"""

from __future__ import annotations

from src.experimentation.contracts.enums import NIVELES_MITRE
from src.experimentation.evaluators.conjuntos import (
    ComparacionConjuntos,
    ResultadoConjuntos,
    evaluar_conjuntos,
)


def _padre(identificador: str) -> str:
    """`T1110.001` -> `T1110`. Un ID sin punto es su propio padre."""
    return identificador.split(".", 1)[0]


def comparar_caso(
    case_id: str,
    atribuciones: list[dict],
    referencias: list[dict],
    nivel: str,
) -> tuple[ComparacionConjuntos, dict]:
    """Compara las atribuciones del sistema con la referencia, en un nivel.

    `atribuciones` son dicts `{id, nivel, evidence_uids}` tomados de
    `ExperimentalOutput.mitre_*`. `referencias` son dicts
    `{nivel, id, ...}` de `GroundTruth.referencias_mitre`.
    """
    if nivel not in NIVELES_MITRE:
        raise ValueError(f"nivel inválido: {nivel!r}")

    propuestas: set[str] = set()
    sin_evidencia: set[str] = set()
    for item in atribuciones:
        if item.get("nivel") != nivel:
            continue
        identificador = item.get("id")
        if not identificador:
            continue
        if not item.get("evidence_uids"):
            # Se registra, pero no entra: el protocolo no puntúa una
            # atribución sin evidencia.
            sin_evidencia.add(str(identificador))
            continue
        propuestas.add(str(identificador))

    esperadas = {
        str(r["id"]) for r in referencias if r.get("nivel") == nivel and r.get("id")
    }

    comparacion = ComparacionConjuntos(
        case_id=case_id,
        propuesto=frozenset(propuestas),
        referencia=frozenset(esperadas),
    )

    # Coincidencias por técnica padre: informativas, nunca sumadas.
    padres_esperados = {_padre(i) for i in esperadas}
    parciales = sorted(
        i for i in (propuestas - esperadas) if _padre(i) in padres_esperados
    )
    diagnostico = {
        "nivel": nivel,
        "atribuciones_sin_evidencia_descartadas": sorted(sin_evidencia),
        "coincidencias_por_padre": parciales,
        "nota_parciales": (
            "se informan pero no suman como acierto: convertir una "
            "subtécnica en su técnica padre para que coincida sería inferir "
            "la referencia"
        ),
    }
    return comparacion, diagnostico


def evaluar_nivel(
    comparaciones: list[ComparacionConjuntos], nivel: str
) -> tuple[ResultadoConjuntos, dict]:
    """Métricas de conjuntos para un nivel."""
    if nivel not in NIVELES_MITRE:
        raise ValueError(f"nivel inválido: {nivel!r}")
    return evaluar_conjuntos(comparaciones), {"nivel": nivel}


def niveles_evaluables(estado_mitre_por_nivel: dict) -> tuple[str, ...]:
    """Qué niveles tienen referencia y por lo tanto se pueden evaluar.

    Hoy, para los 336 casos, devuelve `("tactica", "tecnica")` en UWF y `()`
    en HDFS y BGL. `subtecnica` nunca aparece.
    """
    return tuple(
        nivel for nivel in NIVELES_MITRE
        if estado_mitre_por_nivel.get(nivel) == "evaluable"
    )
