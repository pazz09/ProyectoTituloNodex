"""Adaptador experimental de NODEX (Fase 4, acción 1).

Convierte el estado final de una corrida de NODEX en el contrato común, y
**preserva el output original** en un archivo aparte: si después hace falta
auditar una métrica, se vuelve al estado crudo y no a una versión ya
interpretada.

Lo que el adaptador **no** hace, a propósito:

- No llama a NODEX. Recibe un estado ya producido. Así se puede escribir y
  revisar sin ejecutar nada, y la ejecución queda confinada al orquestador
  de la Fase 7, con su propia autorización.
- No recibe ni toca el ground truth. El adaptador trabaja del lado del
  sistema evaluado; la referencia solo la ve el evaluador (Fase 5).
- No rellena una dimensión ausente con un valor plausible. Marca el estado
  no evaluable y escribe el motivo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from src.experimentation.adapters.extraccion import (
    clasificacion_desde_veredicto,
    extraer_atribuciones_mitre,
    extraer_candidatas_mitre,
    extraer_cronologia_preprocesamiento,
    extraer_reconstruccion,
    extraer_reporte,
    extraer_veredicto,
)
from src.experimentation.contracts import CONTRATO_VERSION
from src.experimentation.contracts.salida import ExperimentalOutput

#: Campos del estado que **nunca** se copian al artefacto crudo. No son
#: secretos, pero son voluminosos y ya están en el caso: duplicarlos haría
#: que los artefactos de una campaña pesaran de más sin agregar nada.
_CAMPOS_VOLUMINOSOS = ("raw_samples",)


@dataclass
class ResultadoAdaptacion:
    salida: ExperimentalOutput
    #: Estado por dimensión **desde el lado de la salida**: si el sistema no
    #: produjo nada que puntuar, la dimensión es `no_evaluable` sin importar
    #: que exista la referencia. El evaluador cruza esto con el estado del
    #: ground truth y se queda con el más restrictivo.
    estado_por_dimension: dict = field(default_factory=dict)
    #: Por qué cada dimensión quedó como quedó.
    diagnostico: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "salida": self.salida.to_dict(),
            "estado_por_dimension": self.estado_por_dimension,
            "diagnostico": self.diagnostico,
        }


def adaptar(
    estado: dict,
    case_id: str,
    run_id: str,
    tipo_deteccion: str,
    dimensiones_aplicables: tuple[str, ...],
    arquitectura: str = "nodex_multiagente",
    raw_output_ref: str | None = None,
) -> ResultadoAdaptacion:
    """Adapta un estado final al contrato común."""
    veredicto, motivo_veredicto = extraer_veredicto(estado, tipo_deteccion)
    candidatas = extraer_candidatas_mitre(estado)
    tacticas, tecnicas, diag_mitre = extraer_atribuciones_mitre(estado)
    eventos, secuencia, diag_reconstruccion = extraer_reconstruccion(estado)
    reporte = extraer_reporte(estado)

    salida = ExperimentalOutput(
        case_id=case_id,
        run_id=run_id,
        arquitectura=arquitectura,
        contrato_version=CONTRATO_VERSION,
        classification=clasificacion_desde_veredicto(veredicto),
        reconstructed_events=eventos,
        temporal_sequence=secuencia,
        mitre_tactics=tacticas,
        mitre_techniques=tecnicas,
        mitre_candidates=candidatas,
        report_summary=reporte,
        veredicto_booleano_presente=veredicto is not None,
        motivo_no_evaluable=motivo_veredicto,
        raw_output_ref=raw_output_ref,
    )

    estados: dict[str, str] = {}
    diagnostico: dict = {
        "mitre": diag_mitre,
        "reconstruccion": diag_reconstruccion,
        "cronologia_preprocesamiento": extraer_cronologia_preprocesamiento(estado),
    }

    for dimension in ("deteccion", "reconstruccion", "mitre", "reporte", "consumo"):
        if dimension not in dimensiones_aplicables:
            estados[dimension] = "no_aplica"
            continue
        if dimension == "deteccion":
            estados[dimension] = (
                "evaluable" if veredicto is not None else "no_evaluable")
        elif dimension == "reconstruccion":
            estados[dimension] = "evaluable" if eventos else "no_evaluable"
        elif dimension == "mitre":
            estados[dimension] = (
                "evaluable" if (tacticas or tecnicas) else "no_evaluable")
        elif dimension == "reporte":
            # Hay texto que puntuar; que la rúbrica se haya aplicado o no es
            # asunto del ground truth, no de la salida.
            estados[dimension] = "evaluable" if reporte else "no_evaluable"
        else:
            # El consumo lo aporta la telemetría (Fase 6), no el estado.
            estados[dimension] = "evaluable"

    if motivo_veredicto:
        diagnostico["deteccion"] = {"motivo": motivo_veredicto}
    if not reporte:
        diagnostico["reporte"] = {
            "motivo": "el estado no trae diagnóstico ni evaluación del auditor"
        }
    return ResultadoAdaptacion(
        salida=salida, estado_por_dimension=estados, diagnostico=diagnostico
    )


def preservar_estado_crudo(estado: dict, destino: Path) -> str:
    """Guarda el estado final tal cual, para poder auditar cualquier métrica.

    Devuelve la ruta relativa que se anota en `raw_output_ref`. Los campos
    voluminosos se omiten y la omisión queda declarada en el archivo, para
    que nadie lea una ausencia como un dato faltante.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    recortado = {k: v for k, v in estado.items() if k not in _CAMPOS_VOLUMINOSOS}
    recortado["_campos_omitidos_al_preservar"] = list(_CAMPOS_VOLUMINOSOS)
    destino.write_text(
        json.dumps(recortado, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return destino.as_posix()


def dimension_final(estado_salida: str, estado_referencia: str) -> str:
    """Combina el estado de la salida con el del ground truth.

    Se queda con el **más restrictivo**, en este orden de prioridad:
    `no_aplica` gana sobre todo (la dimensión no corresponde al caso), luego
    `referencia_pendiente`, luego `fallido`, luego `no_evaluable`, y solo si
    las dos partes dicen `evaluable` la dimensión se puntúa.

    Es deliberado que `evaluable` sea lo último: si hay cualquier duda sobre
    si se puede medir, no se mide.
    """
    prioridad = ("no_aplica", "referencia_pendiente", "fallido", "no_evaluable")
    for estado in prioridad:
        if estado_salida == estado or estado_referencia == estado:
            return estado
    if estado_salida == "evaluable" and estado_referencia == "evaluable":
        return "evaluable"
    return "no_evaluable"
