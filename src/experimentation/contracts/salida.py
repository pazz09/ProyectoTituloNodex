"""Contrato común de salida: lo que toda arquitectura debe producir.

La forma de `to_dict()` respeta **exactamente** el contrato fijado por el
plan de preparación (§5, Fase 1 acción 4): `case_id`, `classification`,
`reconstructed_events[].uid/timestamp/entities`, `temporal_sequence`,
`mitre.tactics[]`, `mitre.techniques[]` con `evidence_uids`, y
`report.summary`. Los nombres de esos campos van en inglés porque el
contrato los fija así; el resto del módulo sigue la convención del
repositorio.

Dos separaciones que el plan exige y que este contrato hace explícitas:

1. **Candidatas vs. atribuidas** (Fase 4 acción 4). Lo que el RAG recuperó
   por similitud no es una atribución al caso. `mitre` lleva solo lo
   atribuido; las candidatas viajan aparte, en `mitre_candidates`, y no se
   puntúan como si el sistema las hubiera afirmado.
2. **Cronología vs. reconstrucción** (Fase 4 acción 3). La `cronologia` que
   el preprocesamiento selecciona de forma determinística no es una
   reconstrucción del incidente hecha por el sistema.
   `reconstructed_events` es lo segundo; lo primero queda en el output
   original preservado.

Y una prohibición: si el veredicto booleano no está, `classification`
queda en `None` y el caso es `no_evaluable`. **No se deriva la
clasificación desde la confianza.** Esa derivación ya existió en el
evaluador de detección y falseaba los conteos (un checkpoint parcial con
`False`/`0.0` se contaba como "normal"); el evaluador actual la bloquea y
este contrato no la reintroduce.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.experimentation.contracts.enums import (
    ARQUITECTURAS,
    CLASIFICACIONES,
    NIVELES_MITRE,
)


def _validar_en(valor, admitidos: tuple, campo: str) -> None:
    if valor not in admitidos:
        raise ValueError(
            f"{campo} inválido: {valor!r}. Admitidos: {', '.join(admitidos)}"
        )


@dataclass
class ReconstructedEvent:
    """Un evento que el sistema afirma parte del incidente.

    `uid` es la clave de matching exacto contra `core_event_uids` de la
    referencia. En datasets sin identificador estable queda `None` y el
    matching de esa dimensión no es exacto: el protocolo lo marca
    `no_aplica` en vez de inventar una equivalencia.
    """

    uid: str | None
    timestamp: str | None = None
    entities: tuple[str, ...] = ()
    #: Tipo de evento según el sistema (p. ej. `authentication_failure`).
    event_type: str | None = None
    #: Referencias a la evidencia que sustenta el evento.
    evidence_uids: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "timestamp": self.timestamp,
            "entities": list(self.entities),
            "event_type": self.event_type,
            "evidence_uids": list(self.evidence_uids),
        }


@dataclass
class MitreItem:
    """Táctica o técnica **atribuida** al caso, con su evidencia."""

    id: str
    name: str | None = None
    evidence_uids: tuple[str, ...] = ()
    nivel: str = "tecnica"

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("MitreItem.id no puede estar vacío")
        _validar_en(self.nivel, NIVELES_MITRE, "nivel")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "evidence_uids": list(self.evidence_uids),
        }


@dataclass
class MitreCandidate:
    """Técnica RECUPERADA por similitud. No es una afirmación del sistema."""

    id: str
    name: str | None = None
    similitud: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExperimentalOutput:
    """Salida normalizada de una arquitectura para un caso.

    `classification` usa el vocabulario del plan (`BENIGN`/`MALICIOUS`).
    Para un caso de detección operativa se lee como normal/anómalo: la
    pregunta que responde la define `TestCase.tipo_deteccion`, no este
    campo.
    """

    case_id: str
    run_id: str
    arquitectura: str
    contrato_version: str
    #: `None` cuando no hubo veredicto booleano válido que traducir.
    classification: str | None = None
    reconstructed_events: list[ReconstructedEvent] = field(default_factory=list)
    #: Orden temporal de los eventos reconstruidos, por `uid`.
    temporal_sequence: tuple[str, ...] = ()
    #: Atribuciones MITRE del sistema (no las candidatas del RAG).
    mitre_tactics: list[MitreItem] = field(default_factory=list)
    mitre_techniques: list[MitreItem] = field(default_factory=list)
    #: Recuperadas por similitud, informativas. Nunca se puntúan como
    #: atribuciones.
    mitre_candidates: list[MitreCandidate] = field(default_factory=list)
    report_summary: str | None = None
    #: `True` solo si la arquitectura entregó un booleano real. Si es
    #: `False`, `classification` DEBE ser `None`.
    veredicto_booleano_presente: bool = True
    #: Por qué la salida no se puede puntuar, si corresponde.
    motivo_no_evaluable: str | None = None
    #: Ruta relativa del output original de la arquitectura, preservado sin
    #: transformar (plan, Fase 4 acción 1).
    raw_output_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("case_id no puede estar vacío")
        if not self.run_id:
            raise ValueError("run_id no puede estar vacío")
        _validar_en(self.arquitectura, ARQUITECTURAS, "arquitectura")
        if not self.contrato_version:
            raise ValueError("contrato_version no puede estar vacía")
        if self.classification is not None:
            _validar_en(self.classification, CLASIFICACIONES, "classification")
        if not self.veredicto_booleano_presente and self.classification is not None:
            raise ValueError(
                "No se puede fijar `classification` sin un veredicto booleano "
                "de la arquitectura. Derivarla de la confianza falsea los "
                "conteos: el caso debe quedar `no_evaluable`."
            )
        if self.classification is None and not self.motivo_no_evaluable:
            raise ValueError(
                "Una salida sin `classification` debe declarar "
                "`motivo_no_evaluable`: un hueco silencioso se contaría "
                "después como caso normal."
            )
        uids_eventos = {e.uid for e in self.reconstructed_events if e.uid}
        sobrantes = [uid for uid in self.temporal_sequence if uid not in uids_eventos]
        if sobrantes:
            raise ValueError(
                "`temporal_sequence` referencia uids que no están en "
                f"`reconstructed_events`: {sobrantes[:5]}"
            )

    @property
    def es_evaluable(self) -> bool:
        return self.classification is not None and self.motivo_no_evaluable is None

    def to_dict(self) -> dict:
        """Serializa en la forma EXACTA que fija el plan, más los campos de
        trazabilidad que el protocolo agrega (prefijados o anidados aparte
        para no alterar el contrato mandatado)."""
        return {
            "case_id": self.case_id,
            "classification": self.classification,
            "reconstructed_events": [e.to_dict() for e in self.reconstructed_events],
            "temporal_sequence": list(self.temporal_sequence),
            "mitre": {
                "tactics": [t.to_dict() for t in self.mitre_tactics],
                "techniques": [t.to_dict() for t in self.mitre_techniques],
            },
            "report": {"summary": self.report_summary},
            # --- trazabilidad del protocolo (fuera del contrato mandatado) ---
            "_meta": {
                "run_id": self.run_id,
                "arquitectura": self.arquitectura,
                "contrato_version": self.contrato_version,
                "veredicto_booleano_presente": self.veredicto_booleano_presente,
                "motivo_no_evaluable": self.motivo_no_evaluable,
                "mitre_candidates": [c.to_dict() for c in self.mitre_candidates],
                "raw_output_ref": self.raw_output_ref,
            },
        }
