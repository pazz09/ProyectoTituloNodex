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
    """Técnicas que el sistema **atribuye al caso**, del contrato `d11-v1`.

    Devuelve `(tacticas, tecnicas, diagnostico)`.

    Lee `tecnicas_atribuidas`, con los nombres del contrato:
    `technique_id`, `technique_name`, `evidence_uids`, `justification`.
    **No** `id` ni `nivel`: esos eran los nombres de una propuesta anterior
    que quedó superada, y leerlos daría una lista vacía en silencio.

    ## Solo nivel técnica

    `TecnicaAtribuida` no tiene nivel, y la decisión del 7-oct-2026 fija el
    scoring principal de D3 en `label_technique` y los identificadores
    `Txxxx` / `Txxxx.xxx`. `label_tactic` queda como información
    complementaria del dataset y **no** entra al scoring, así que la lista de
    tácticas va siempre vacía y el nivel de táctica se informa como no
    aplicable, no como fallo del sistema.

    ## Una atribución sin evidencia no cuenta

    `normalizar_d11` ya descarta las que no citan evidencia válida, pero acá
    se vuelve a verificar: el evaluador no debe confiar en que la capa
    anterior filtró bien.
    """
    tacticas: list[MitreItem] = []
    tecnicas: list[MitreItem] = []
    diagnostico: dict = {
        "fuente": "contrato_d11",
        "nivel_tactica": "no_aplica",
        "motivo_nivel_tactica": (
            "el contrato d11-v1 no lleva nivel y la decisión del 7-oct-2026 "
            "fija el scoring de D3 en label_technique; label_tactic queda "
            "como información complementaria"
        ),
    }

    atribuidas = estado.get("tecnicas_atribuidas")
    if not isinstance(atribuidas, list):
        diagnostico["motivo"] = (
            "el estado no trae `tecnicas_atribuidas` como lista"
        )
        return [], [], diagnostico

    sin_evidencia: list[str] = []
    for item in atribuidas:
        if not isinstance(item, dict):
            continue
        identificador = item.get("technique_id")
        if not isinstance(identificador, str) or not identificador.strip():
            continue
        identificador = identificador.strip()
        evidencias = tuple(
            str(u) for u in (item.get("evidence_uids") or []) if u
        )
        if not evidencias:
            sin_evidencia.append(identificador)
            continue
        tecnicas.append(MitreItem(
            id=identificador,
            name=item.get("technique_name"),
            evidence_uids=evidencias,
            nivel="tecnica",
        ))

    diagnostico["atribuciones_sin_evidencia"] = sorted(sin_evidencia)
    diagnostico["n_atribuidas"] = len(tecnicas)
    # Conteo que produce `normalizar_d11` al descartar uids inventados. Es
    # una señal de calidad de la atribución, no un error de ejecución.
    diagnostico["invalid_evidence_uid_count"] = estado.get(
        "invalid_evidence_uid_count"
    )
    diagnostico["d11_warnings"] = list(estado.get("d11_warnings") or [])
    return tacticas, tecnicas, diagnostico


def extraer_reconstruccion(
    estado: dict,
) -> tuple[list[ReconstructedEvent], tuple[str, ...], dict]:
    """Eventos que el sistema reconstruye, del contrato `d11-v1`.

    Devuelve `(eventos, secuencia_temporal, diagnostico)`.

    ## Cuál es la clave de matching

    **`evidence_uids`, no `event_id`.** Es la diferencia que decide si D2
    mide algo:

    - `evidence_uids` se valida contra el catálogo de evidencia, que está
      indexado por el `uid` real del registro —el `uid` de Zeek en UWF—.
      Los inventados se descartan y se cuentan en
      `invalid_evidence_uid_count`.
    - `event_id` es la etiqueta que el propio sistema le pone al evento
      reconstruido, y `normalizar_d11` la reemplaza por una sintética
      (`event_001`) si falta **o si colisiona con un uid de evidencia**.

    Así que comparar `event_id` contra `core_event_uids` no coincidiría con
    nada. El conjunto que se compara es la **unión de los `evidence_uids`**
    de todos los eventos reconstruidos.

    ## La cronología del preprocesamiento sigue sin ser la reconstrucción

    `resumen_logs["cronologia"]` la arma `src/preprocessing/aggregation.py`
    sin LLM. Entregarla como `reconstructed_events` haría que D2 midiera al
    preprocesador mientras el informe dice que mide al sistema multiagente.
    Viaja en `_meta`, etiquetada.
    """
    reconstruidos = estado.get("eventos_reconstruidos")
    if not isinstance(reconstruidos, list) or not reconstruidos:
        return [], (), {
            "fuente": "ausente",
            "motivo": (
                "el estado no trae `eventos_reconstruidos`. Con el contrato "
                "d11-v1 integrado, una lista vacía significa que el sistema "
                "no reconstruyó nada, no que falte el campo"
            ),
            "campo_presente": isinstance(reconstruidos, list),
        }

    eventos: list[ReconstructedEvent] = []
    uids_de_evidencia: list[str] = []
    for item in reconstruidos:
        if not isinstance(item, dict):
            continue
        evidencias = tuple(
            str(u) for u in (item.get("evidence_uids") or []) if u
        )
        for uid in evidencias:
            if uid not in uids_de_evidencia:
                uids_de_evidencia.append(uid)
        eventos.append(ReconstructedEvent(
            # `uid` del contrato común guarda el `event_id` del sistema, que
            # es su etiqueta; la clave de matching son las evidencias.
            uid=(str(item["event_id"]) if item.get("event_id") else None),
            timestamp=item.get("timestamp"),
            entities=(),
            event_type=item.get("event_type"),
            evidence_uids=evidencias,
        ))

    # La secuencia solo puede citar `event_id` que existan entre los eventos.
    etiquetas = {e.uid for e in eventos if e.uid}
    secuencia = tuple(
        str(u) for u in (estado.get("secuencia_temporal") or [])
        if str(u) in etiquetas
    )
    descartados = [
        str(u) for u in (estado.get("secuencia_temporal") or [])
        if str(u) not in etiquetas
    ]
    return eventos, secuencia, {
        "fuente": "contrato_d11",
        "n_eventos": len(eventos),
        # Lo que el evaluador tiene que comparar contra `core_event_uids`.
        "uids_de_evidencia": uids_de_evidencia,
        "n_uids_de_evidencia": len(uids_de_evidencia),
        "secuencia_descartada": descartados,
        "invalid_evidence_uid_count": estado.get("invalid_evidence_uid_count"),
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
