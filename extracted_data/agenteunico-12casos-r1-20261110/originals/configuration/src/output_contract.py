"""Contrato D-11 compartido: evidencia observada, normalización y exportación.

No consulta etiquetas, memoria ni herramientas. Los candidatos RAG nunca se
transforman en atribuciones sin una conclusión explícita del modelo.
"""

import copy
import json
import logging
import re
from datetime import datetime, timezone

from typing_extensions import TypedDict

from src.config import CRONOLOGIA_MAX_EVENTOS

logger = logging.getLogger(__name__)
OUTPUT_CONTRACT_VERSION = "d11-v1"


class EventoReconstruido(TypedDict):
    event_id: str
    evidence_uids: list[str]
    timestamp: str | None
    event_type: str
    description: str
    confidence: float | None


class TecnicaAtribuida(TypedDict):
    technique_id: str
    technique_name: str | None
    evidence_uids: list[str]
    justification: str
    confidence: float | None


PROMPT_D11 = """
La salida formal incluye eventos_reconstruidos, secuencia_temporal y
tecnicas_atribuidas. Reconstruye SOLO eventos relevantes usando evidencia
observada del catálogo EVIDENCIA DISPONIBLE. Cita uno o más evidence_uids
existentes: no inventes UIDs ni timestamps. event_id es un identificador interno
distinto del UID del log (event_001, event_002, ...). timestamp debe ser una
marca de los logs citados o null. event_type es una etiqueta breve snake_case.
secuencia_temporal referencia event_id: usa únicamente el orden temporal
observable; orden temporal no implica causalidad. No ordenes eventos sin fecha.
Las técnicas recuperadas por RAG son CANDIDATOS, no conclusiones. Atribuye una
técnica solo si la evidencia observada la respalda; usa un ID MITRE Tdddd o
Tdddd.ddd y evidence_uids válidos. Nunca copies automáticamente candidatos.
Puedes devolver listas vacías. Ausencia de evidencia es preferible a especular.
Usa confidence=null en eventos y técnicas; no inventes probabilidades.
description y justification son breves y verificables; no expongas razonamiento
interno. Añade al objeto JSON estos campos:
"eventos_reconstruidos": [{"event_id":"event_001", "evidence_uids":["UID"],
"timestamp":null, "event_type":"authentication_failure", "description":"...",
"confidence":null}], "secuencia_temporal":["event_001"],
"tecnicas_atribuidas": [{"technique_id":"T1110", "technique_name":"Brute Force",
"evidence_uids":["UID"], "justification":"...", "confidence":null}].
"""


def _fecha(value):
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Una fecha sin hora no permite ordenar eventos dentro del día.
        if len(value) <= 10:
            return None
        return parsed
    except ValueError:
        # BGL conserva la precisión del timestamp original.
        try:
            return datetime.strptime(value, "%Y-%m-%d-%H.%M.%S.%f")
        except ValueError:
            return None


def construir_evidencia(resultado, limite=CRONOLOGIA_MAX_EVENTOS):
    """Vista acotada por registro, con procedencia; nunca raw/attributes/GT.

    Conserva uid/flow_id originales. Si no existen, asigna un UID de registro
    determinista basado en la posición del log. Solo estos registros visibles
    pueden citarse. El recorte se declara y no depende de etiquetas.
    """
    evidencia = []
    # Reserva IDs de origen para evitar colisiones con UIDs sintetizados.
    originales = {
        str(e.attributes.get("uid") or e.attributes.get("flow_id")).strip()
        for e in resultado.events
        if e.attributes.get("uid") or e.attributes.get("flow_id")
    }
    campos = ("source_ip", "destination_ip", "source_user", "source_host",
              "service_name", "process_name", "event_category", "event_action",
              "event_outcome", "severity", "event_code", "destination_port",
              "protocol")
    for index, e in enumerate(resultado.events[:max(0, limite)], 1):
        uid = e.attributes.get("uid") or e.attributes.get("flow_id")
        uid = str(uid).strip() if uid else f"log_record_{index:06d}"
        if not (e.attributes.get("uid") or e.attributes.get("flow_id")):
            while uid in originales:
                uid = "record_" + uid
        item = {"uid": uid, "record_number": e.record_number,
                "line_start": e.line_start, "line_end": e.line_end,
                "timestamp": e.timestamp if _fecha(e.timestamp) else None}
        item.update({k: getattr(e, k) for k in campos if getattr(e, k) is not None})
        # Decoders estructurados usan raw como fallback cuando falta message.
        # En ese caso podría contener columnas de etiqueta, incluso ya retiradas
        # de attributes por Zeek. Nunca enviamos ese fallback como descripción.
        mensaje = e.message or ""
        if mensaje != e.raw:
            if not re.search(r"label(?:_binary|_tactic|_technique)?|ground_truth", mensaje, re.I):
                item["message"] = mensaje[:500]
        evidencia.append(item)
    return evidencia, max(0, len(resultado.events) - len(evidencia))


def contexto_d11(state):
    return (
        "\nEVIDENCIA DISPONIBLE (catálogo de logs observados):\n"
        + json.dumps(state.get("evidencia_logs") or [], ensure_ascii=False)
        + f"\nRegistros omitidos del catálogo: {state.get('evidencia_logs_omitidos', 0)}"
        + "\nCANDIDATOS MITRE RECUPERADOS POR RAG (no atribuidos):\n"
        + json.dumps(state.get("tecnicas_mitre") or [], ensure_ascii=False)
    )


def normalizar_d11(respuesta, evidencia):
    """Filtra evidencia inventada y formas parciales sin mutar la respuesta."""
    problemas = []
    invalidos = 0
    por_uid = {}
    for log in evidencia or []:
        if isinstance(log, dict) and isinstance(log.get("uid"), str):
            por_uid.setdefault(log["uid"], []).append(log)
    if not isinstance(respuesta, dict):
        respuesta = {}
        problemas.append("respuesta_d11_no_es_objeto")

    def lista(campo):
        value = respuesta.get(campo)
        if not isinstance(value, list):
            problemas.append(f"{campo}_ausente_o_invalido")
            return []
        return value

    def uids(item):
        nonlocal invalidos
        values = item.get("evidence_uids")
        if not isinstance(values, list):
            problemas.append("evidence_uids_no_es_lista")
            return []
        validos = []
        for uid in values:
            if not isinstance(uid, str) or uid not in por_uid:
                invalidos += 1
                problemas.append("evidence_uid_inexistente")
            elif uid not in validos:
                validos.append(uid)
        return validos

    eventos = []
    ids = set()
    for item in lista("eventos_reconstruidos"):
        if not isinstance(item, dict):
            problemas.append("evento_no_es_objeto")
            continue
        refs = uids(item)
        if not refs:
            problemas.append("evento_sin_evidencia")
            continue
        event_id = item.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip() or event_id.strip() in por_uid:
            event_id = f"event_{len(eventos) + 1:03d}"
        event_id = event_id.strip()
        if event_id in ids:
            problemas.append("event_id_duplicado")
            continue
        marcas = {log.get("timestamp") for uid in refs for log in por_uid[uid]
                  if _fecha(log.get("timestamp"))}
        timestamp = item.get("timestamp")
        if not isinstance(timestamp, str) or timestamp not in marcas:
            if timestamp is not None:
                problemas.append("timestamp_no_respaldado")
            # Solo derivar una fecha si la evidencia determina una única marca.
            timestamp = next(iter(marcas)) if len(marcas) == 1 else None
        tipo = item.get("event_type")
        tipo = re.sub(r"[^a-z0-9]+", "_", tipo.lower()).strip("_") if isinstance(tipo, str) else ""
        descripcion = item.get("description")
        if not isinstance(descripcion, str) or not descripcion.strip():
            problemas.append("evento_sin_descripcion")
            continue
        ids.add(event_id)
        eventos.append({"event_id": event_id, "evidence_uids": refs,
                        "timestamp": timestamp, "event_type": tipo or "observed_event",
                        "description": descripcion.strip(), "confidence": None})

    secuencia = lista("secuencia_temporal")
    if any(not isinstance(x, str) or x not in {e['event_id'] for e in eventos}
           for x in secuencia):
        problemas.append("secuencia_referencia_inexistente")
    # Derivar solo el orden observable, sin confiar en causalidad del LLM.
    fechados = [e for e in eventos if _fecha(e["timestamp"])]
    # No mezclar fechas sin zona con fechas zonificadas: no inventar una zona.
    zonas = {bool(_fecha(e["timestamp"]).tzinfo) for e in fechados}
    if len(zonas) > 1:
        problemas.append("secuencia_zonas_no_comparables")
        timeline = []
    else:
        timeline = [e["event_id"] for e in sorted(
            fechados, key=lambda e: _fecha(e["timestamp"]).replace(tzinfo=timezone.utc)
            if not _fecha(e["timestamp"]).tzinfo else _fecha(e["timestamp"]))]

    tecnicas = {}
    for item in lista("tecnicas_atribuidas"):
        if not isinstance(item, dict):
            problemas.append("tecnica_no_es_objeto")
            continue
        refs = uids(item)
        technique_id = item.get("technique_id")
        technique_id = technique_id.strip().upper() if isinstance(technique_id, str) else ""
        if not re.fullmatch(r"T\d{4}(?:\.\d{3})?", technique_id):
            problemas.append("technique_id_invalido")
            continue
        justification = item.get("justification")
        if not refs or not isinstance(justification, str) or not justification.strip():
            problemas.append("tecnica_sin_evidencia_o_justificacion")
            continue
        if technique_id in tecnicas:
            previo = tecnicas[technique_id]
            previo["evidence_uids"] = list(dict.fromkeys(previo["evidence_uids"] + refs))
            if justification.strip() != previo["justification"]:
                previo["justification"] += " | " + justification.strip()
        else:
            nombre = item.get("technique_name")
            tecnicas[technique_id] = {"technique_id": technique_id,
                "technique_name": nombre.strip() if isinstance(nombre, str) else None,
                "evidence_uids": refs, "justification": justification.strip(), "confidence": None}
    if problemas:
        logger.warning("D-11: %s; invalid_evidence_uid_count=%d", ", ".join(problemas), invalidos)
    return {"eventos_reconstruidos": eventos, "secuencia_temporal": timeline,
            "tecnicas_atribuidas": list(tecnicas.values()),
            "invalid_evidence_uid_count": invalidos, "d11_warnings": problemas}


def campos_d11(state):
    """Exportación aditiva para API/CLI/evaluación; defaults de estados viejos."""
    return {"output_contract_version": OUTPUT_CONTRACT_VERSION,
            **{k: copy.deepcopy(state.get(k) or []) for k in
               ("eventos_reconstruidos", "secuencia_temporal", "tecnicas_atribuidas", "d11_warnings")},
            "invalid_evidence_uid_count": state.get("invalid_evidence_uid_count", 0),
            "evidencia_logs": copy.deepcopy(state.get("evidencia_logs") or []),
            "evidencia_logs_omitidos": state.get("evidencia_logs_omitidos", 0),
            "telemetry": copy.deepcopy(state.get("telemetry") or {})}


def normalizar_salida_experimental(state):
    """Adaptador sin acceso a etiquetas y sin atribuir candidatos RAG."""
    d11 = campos_d11(state)
    return {"output_contract_version": OUTPUT_CONTRACT_VERSION,
            "detection": {k: state.get(k) for k in ("hay_incidente", "hay_anomalia", "confianza")},
            "reconstruction": {"events": d11["eventos_reconstruidos"], "timeline": d11["secuencia_temporal"]},
            "mitre": {"attributed_techniques": d11["tecnicas_atribuidas"],
                      "retrieved_candidates": copy.deepcopy(state.get("tecnicas_mitre") or [])},
            "report": {k: copy.deepcopy(state.get(k)) for k in
                       ("diagnostico", "evaluacion_auditor", "comandos_mitigacion", "comandos_validos")},
            "telemetry": d11["telemetry"], "evidence": d11["evidencia_logs"],
            "evidence_omitted": d11["evidencia_logs_omitidos"],
            "validation": {"warnings": d11["d11_warnings"],
                           "invalid_evidence_uid_count": d11["invalid_evidence_uid_count"]}}
