"""Extractores del estado final de NODEX al contrato común (Fase 4).

Cada función de acá contesta una pregunta: **¿de dónde sale esta dimensión,
y qué pasa si no está?** La respuesta por omisión nunca es un valor
plausible: es un estado no evaluable con su motivo.

Hay una separación que el plan exige y que es fácil de romper sin darse
cuenta: **la cronología que arma el preprocesamiento no es la
reconstrucción del sistema**. `resumen_logs["cronologia"]` la produce
`src/preprocessing/aggregation.py` de forma determinística, sin LLM. Si se
la entregara como `reconstructed_events`, la métrica D2 mediría al
preprocesador y el informe diría que mide al sistema multiagente. Acá viaja
en `_meta`, nunca como reconstrucción.
"""

from __future__ import annotations

import re

from src.experimentation.contracts.enums import CAMPO_VEREDICTO_POR_TIPO
from src.experimentation.contracts.salida import (
    MitreCandidate,
    MitreItem,
    ReconstructedEvent,
)

#: Un ID de técnica ATT&CK: `T1110`, o con subtécnica `T1110.001`.
_ID_TECNICA = re.compile(r"\bT\d{4}(?:\.\d{3})?\b")


def extraer_veredicto(estado: dict, tipo_deteccion: str) -> tuple[bool | None, str | None]:
    """Lee el veredicto booleano del campo que corresponde al tipo.

    Devuelve `(veredicto, motivo_si_falta)`.

    **No se deriva de `confianza` bajo ninguna circunstancia.** Ese atajo ya
    falseó conteos en este proyecto: un checkpoint parcial con
    `confianza=0.0` se contaba como predicción "normal" y escondía el
    agotamiento de cuota, que es un fallo de ejecución y no una predicción.
    """
    campo = CAMPO_VEREDICTO_POR_TIPO.get(tipo_deteccion)
    if campo is None:
        return None, f"tipo_deteccion desconocido: {tipo_deteccion!r}"
    if campo not in estado:
        return None, (
            f"el estado final no trae el campo {campo!r}, que es el que "
            f"responde la pregunta de detección {tipo_deteccion!r}"
        )
    valor = estado[campo]
    if not isinstance(valor, bool):
        # `None`, un string o un número no son un veredicto. Convertirlos
        # con `bool()` inventaría una predicción.
        return None, (
            f"{campo!r} no es un booleano: es {type(valor).__name__} "
            f"({valor!r}). No se deriva una predicción de un valor no booleano"
        )
    return valor, None


def clasificacion_desde_veredicto(veredicto: bool | None) -> str | None:
    """`MALICIOUS` / `BENIGN` del vocabulario del contrato común.

    Para los datasets operativos el mismo par se lee anómalo/normal: lo que
    define la lectura es el `tipo_deteccion` del caso, no la etiqueta.
    """
    if veredicto is None:
        return None
    return "MALICIOUS" if veredicto else "BENIGN"


def extraer_candidatas_mitre(estado: dict) -> list[MitreCandidate]:
    """Técnicas que el RAG **recuperó por similitud**.

    No son una afirmación del sistema: recuperar `T1021` porque su texto se
    parece al log no equivale a atribuirla. Por eso van a `_meta` y no a
    `mitre`.
    """
    candidatas: list[MitreCandidate] = []
    for item in estado.get("tecnicas_mitre") or []:
        if not isinstance(item, dict):
            continue
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        identificador = meta.get("technique_id") or item.get("technique_id")
        if not identificador:
            continue
        distancia = item.get("distancia", item.get("distance"))
        candidatas.append(MitreCandidate(
            id=str(identificador),
            name=meta.get("name") or item.get("name"),
            # Chroma devuelve distancia, no similitud. Se convierte solo si
            # el dato está; inventar una similitud desde una distancia
            # ausente daría un número sin respaldo.
            similitud=(1.0 - float(distancia)) if isinstance(
                distancia, (int, float)) else None,
        ))
    return candidatas


def extraer_atribuciones_mitre(
    estado: dict,
) -> tuple[list[MitreItem], list[MitreItem], dict]:
    """Técnicas y tácticas que el sistema **atribuye al caso**.

    Devuelve `(tacticas, tecnicas, diagnostico)`, donde `diagnostico` son
    metadatos sobre por qué la lista puede estar vacía.

    Hoy NODEX no produce atribuciones estructuradas. El agente de triage
    recibe la instrucción de *citar* IDs de técnica dentro del texto libre
    de `diagnostico` (`agente_analista_triage.py:71`), sin campo propio y
    sin evidencia asociada. Una atribución sin `evidence_uids` no es
    puntuable según el protocolo, así que los IDs citados en prosa **no** se
    devuelven como atribuciones: se registran aparte, como señal de que la
    capacidad existe en alguna forma.

    Si el estado trae el campo estructurado `tecnicas_atribuidas` —que es la
    extensión propuesta en `contrato_agentes.py`— se usa ese.
    """
    tacticas: list[MitreItem] = []
    tecnicas: list[MitreItem] = []
    diagnostico: dict = {}

    estructuradas = estado.get("tecnicas_atribuidas")
    if isinstance(estructuradas, list) and estructuradas:
        for item in estructuradas:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            evidencias = tuple(
                str(u) for u in (item.get("evidence_uids") or [])
            )
            if not evidencias:
                # Se conserva, pero fuera de las atribuciones puntuables.
                diagnostico.setdefault("atribuciones_sin_evidencia", []).append(
                    str(item["id"])
                )
                continue
            destino = tacticas if item.get("nivel") == "tactica" else tecnicas
            destino.append(MitreItem(
                id=str(item["id"]),
                name=item.get("name"),
                evidence_uids=evidencias,
                nivel=item.get("nivel") or "tecnica",
            ))
        diagnostico["fuente"] = "campo_estructurado"
        return tacticas, tecnicas, diagnostico

    # Camino de hoy: IDs citados en prosa, sin evidencia.
    texto = " ".join(
        str(estado.get(campo) or "")
        for campo in ("diagnostico", "evaluacion_auditor")
    )
    citados = sorted(set(_ID_TECNICA.findall(texto)))
    diagnostico["fuente"] = "prosa_sin_evidencia"
    diagnostico["ids_citados_en_prosa"] = citados
    diagnostico["motivo"] = (
        "NODEX no produce atribuciones MITRE estructuradas: el agente de "
        "triage cita IDs dentro del texto de `diagnostico` y no hay "
        "evidence_uids. Una atribución sin evidencia no es puntuable, así "
        "que la dimensión queda no evaluable"
    )
    return [], [], diagnostico


def extraer_reconstruccion(
    estado: dict,
) -> tuple[list[ReconstructedEvent], tuple[str, ...], dict]:
    """Eventos que el sistema **reconstruye** como núcleo del incidente.

    Devuelve `(eventos, secuencia_temporal, diagnostico)`.

    Hoy NODEX no produce ninguno. Lo único parecido es la cronología que
    arma el preprocesamiento, que es determinística y no es una afirmación
    del sistema: entregarla como reconstrucción mediría al preprocesador.
    Por eso se devuelve vacío con el motivo, y la cronología viaja en
    `_meta`.
    """
    estructurada = estado.get("eventos_reconstruidos")
    if isinstance(estructurada, list) and estructurada:
        eventos = []
        for item in estructurada:
            if not isinstance(item, dict):
                continue
            eventos.append(ReconstructedEvent(
                uid=(str(item["uid"]) if item.get("uid") else None),
                timestamp=item.get("timestamp"),
                entities=tuple(str(e) for e in (item.get("entities") or ())),
                event_type=item.get("event_type") or item.get("tipo"),
                evidence_uids=tuple(
                    str(u) for u in (item.get("evidence_uids") or ())
                ),
            ))
        # La secuencia solo puede citar uids que existan entre los eventos.
        uids = {e.uid for e in eventos if e.uid}
        secuencia = tuple(
            str(u) for u in (estado.get("secuencia_temporal") or ())
            if str(u) in uids
        )
        return eventos, secuencia, {"fuente": "campo_estructurado"}

    return [], (), {
        "fuente": "ausente",
        "motivo": (
            "NODEX no produce eventos reconstruidos. La cronología de "
            "`resumen_logs` la arma el preprocesamiento sin LLM, así que no "
            "es la reconstrucción del sistema y no se usa como tal"
        ),
    }


def extraer_reporte(estado: dict) -> str | None:
    """Arma el texto del reporte, tal cual, para la rúbrica humana.

    No se resume ni se reescribe: la rúbrica puntúa lo que el sistema
    produjo. Se concatenan las piezas que el informe PDF ya usa
    (`src/api/informe_pdf.py`): diagnóstico, evaluación del auditor y
    comandos de mitigación.
    """
    partes: list[str] = []
    diagnostico = estado.get("diagnostico")
    if diagnostico:
        partes.append(f"## Diagnóstico\n\n{diagnostico}")
    evaluacion = estado.get("evaluacion_auditor")
    if evaluacion:
        partes.append(f"## Evaluación del auditor\n\n{evaluacion}")
    comandos = estado.get("comandos_mitigacion")
    if comandos:
        listado = "\n".join(f"- {c}" for c in comandos)
        partes.append(f"## Comandos de mitigación propuestos\n\n{listado}")
    return "\n\n".join(partes) if partes else None


def extraer_cronologia_preprocesamiento(estado: dict) -> dict:
    """La cronología determinística, **etiquetada como lo que es**."""
    resumen = estado.get("resumen_logs")
    if not isinstance(resumen, dict):
        return {}
    return {
        "entradas": resumen.get("cronologia") or [],
        "omitidos": resumen.get("cronologia_omitidos") or 0,
        "producida_por": "src/preprocessing/aggregation.py (sin LLM)",
        "no_es": "la reconstrucción atribuida al sistema",
    }
