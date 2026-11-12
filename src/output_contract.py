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


PROMPT_D11_ORIGINAL = """
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

# NODEX final, Fase A (M6). Se retira el sesgo a citar poco ("SOLO eventos
# relevantes", "uno o más evidence_uids"): se pide citar TODA la evidencia que
# respalda cada evento, por grupos o por uids, manteniendo la prohibición de
# inventar. `normalizar_d11` expande los grupos de forma determinística.
PROMPT_D11_GRUPOS = """
La salida formal incluye eventos_reconstruidos, secuencia_temporal y
tecnicas_atribuidas. Reconstruye los eventos que la evidencia observada
respalda, usando el catálogo EVIDENCIA DISPONIBLE y la tabla GRUPOS DE
EVIDENCIA. Para cada evento cita TODA la evidencia que lo respalda: en
evidence_groups, los grupos cuyos registros pertenecen todos a ese evento; en
evidence_uids, los registros sueltos. Si un grupo mezcla registros del evento
con otros que no lo son, cita solo los uids que corresponden; no inventes UIDs,
grupos ni timestamps. event_id es un identificador interno distinto del UID del
log (event_001, event_002, ...). timestamp debe ser una marca de los logs
citados o null. event_type es una etiqueta breve snake_case.
secuencia_temporal referencia event_id: usa únicamente el orden temporal
observable; orden temporal no implica causalidad. No ordenes eventos sin fecha.
Las técnicas recuperadas por RAG son CANDIDATOS, no conclusiones. Atribuye una
técnica solo si la evidencia observada la respalda; usa un ID MITRE Tdddd o
Tdddd.ddd y cita su evidencia con evidence_groups y/o evidence_uids válidos.
Nunca copies automáticamente candidatos. Puedes devolver listas vacías si la
evidencia no respalda eventos o técnicas: no especules.
Usa confidence=null en eventos y técnicas; no inventes probabilidades.
description y justification son breves y verificables; no expongas razonamiento
interno. Añade al objeto JSON estos campos:
"eventos_reconstruidos": [{"event_id":"event_001", "evidence_groups":["G01"],
"evidence_uids":["UID"], "timestamp":null, "event_type":"authentication_failure",
"description":"...", "confidence":null}], "secuencia_temporal":["event_001"],
"tecnicas_atribuidas": [{"technique_id":"T1110", "technique_name":"Brute Force",
"evidence_groups":["G01"], "evidence_uids":["UID"], "justification":"...",
"confidence":null}].
"""


def _prompt_d11():
    from src.config import EVIDENCIA_POR_GRUPOS
    return PROMPT_D11_GRUPOS if EVIDENCIA_POR_GRUPOS else PROMPT_D11_ORIGINAL


#: Texto vigente según la configuración (se fija al importar, como el resto
#: de los parámetros de `src/config.py`).
PROMPT_D11 = _prompt_d11()


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


_ETIQUETA_EN_TEXTO = re.compile(r"label(?:_binary|_tactic|_technique)?|ground_truth", re.I)
#: Campos de red que el catálogo agrega con `EVIDENCIA_CONTEXTO_EXTENDIDO`.
_CAMPOS_RED_EXTENDIDOS = ("duration", "orig_bytes", "resp_bytes", "history")


def construir_evidencia(resultado, limite=CRONOLOGIA_MAX_EVENTOS, grupo_de=None):
    """Vista acotada por registro, con procedencia; nunca raw/attributes/GT.

    Conserva uid/flow_id originales. Si no existen, asigna un UID de registro
    determinista basado en la posición del log (`perfil_lote.uid_de_evento`,
    el mismo que usan los grupos de evidencia). Solo estos registros visibles
    pueden citarse. El recorte se declara y no depende de etiquetas.

    Con `EVIDENCIA_CONTEXTO_EXTENDIDO` (NODEX final, M1): los logs de texto sin
    estructura llevan su línea (sin el campo de alerta de BGL), los logs de red
    llevan bytes, duración e historia de conexión, y cada registro lleva su
    `group_id` si se entregan los grupos (`grupo_de`).
    """
    from src.config import EVIDENCIA_CONTEXTO_EXTENDIDO, EVIDENCIA_MAX_CHARS_MENSAJE
    from src.preprocessing.perfil_lote import linea_sin_etiqueta, uid_de_evento, uids_originales

    evidencia = []
    # Reserva IDs de origen para evitar colisiones con UIDs sintetizados.
    originales = uids_originales(resultado.events)
    campos = ("source_ip", "destination_ip", "source_user", "source_host",
              "service_name", "process_name", "event_category", "event_action",
              "event_outcome", "severity", "event_code", "destination_port",
              "protocol")
    tope_mensaje = EVIDENCIA_MAX_CHARS_MENSAJE if EVIDENCIA_CONTEXTO_EXTENDIDO else 500
    for index, e in enumerate(resultado.events[:max(0, limite)], 1):
        uid = uid_de_evento(e, index, originales)
        item = {"uid": uid, "record_number": e.record_number,
                "line_start": e.line_start, "line_end": e.line_end,
                "timestamp": e.timestamp if _fecha(e.timestamp) else None}
        if grupo_de is not None and index - 1 < len(grupo_de):
            item["group_id"] = grupo_de[index - 1]
        item.update({k: getattr(e, k) for k in campos if getattr(e, k) is not None})
        # Decoders estructurados usan raw como fallback cuando falta message.
        # En ese caso podría contener columnas de etiqueta, incluso ya retiradas
        # de attributes por Zeek. Nunca enviamos ese fallback como descripción.
        mensaje = e.message or ""
        if mensaje != e.raw:
            if not _ETIQUETA_EN_TEXTO.search(mensaje):
                item["message"] = mensaje[:tope_mensaje]
        elif EVIDENCIA_CONTEXTO_EXTENDIDO and e.decoder == "text":
            # Texto libre: el mensaje ES la línea. Solo para el decoder de
            # texto, nunca para un CSV/JSON cuyo crudo podría traer columnas
            # de etiqueta.
            linea = linea_sin_etiqueta(e)
            if linea and not _ETIQUETA_EN_TEXTO.search(linea):
                item["message"] = linea[:tope_mensaje]
        if EVIDENCIA_CONTEXTO_EXTENDIDO:
            for campo in _CAMPOS_RED_EXTENDIDOS:
                valor = e.attributes.get(campo)
                if valor not in (None, "", "-"):
                    item[campo] = valor
        evidencia.append(item)
    return evidencia, max(0, len(resultado.events) - len(evidencia))


def tabla_grupos(grupos) -> list[dict]:
    """Tabla de grupos para el prompt: id, clave y conteo.

    Los uids de cada grupo no se repiten aquí: son los registros del catálogo
    que llevan ese `group_id`. Repetirlos costaba ~28 000 caracteres por
    llamada en un lote UWF de 300 filas."""
    return [{"group_id": g["group_id"], "clave": g["clave"], "conteo": g["conteo"]}
            for g in grupos or [] if isinstance(g, dict) and g.get("group_id")]


def contexto_d11(state):
    from src.config import EVIDENCIA_POR_GRUPOS
    grupos = ""
    if EVIDENCIA_POR_GRUPOS and state.get("grupos_evidencia"):
        grupos = ("\nGRUPOS DE EVIDENCIA (registros que describen lo mismo; sus uids son los "
                  "registros del catálogo con ese group_id; citar un grupo equivale a citar "
                  "todos sus uids):\n"
                  + json.dumps(tabla_grupos(state.get("grupos_evidencia")), ensure_ascii=False))
    return (
        "\nEVIDENCIA DISPONIBLE (catálogo de logs observados):\n"
        + json.dumps(state.get("evidencia_logs") or [], ensure_ascii=False)
        + f"\nRegistros omitidos del catálogo: {state.get('evidencia_logs_omitidos', 0)}"
        + grupos
        + "\nCANDIDATOS MITRE RECUPERADOS POR RAG (no atribuidos):\n"
        + json.dumps(state.get("tecnicas_mitre") or [], ensure_ascii=False)
    )


def normalizar_d11(respuesta, evidencia, grupos=None):
    """Filtra evidencia inventada y formas parciales sin mutar la respuesta.

    `grupos` (M6, NODEX final): grupos de evidencia del lote. Un evento o una
    técnica pueden citar `evidence_groups`; cada grupo válido se expande a sus
    uids que estén en el catálogo, en orden y sin duplicados. Un grupo
    inexistente se descarta y cuenta como inválido, igual que un uid
    inexistente (`invalid_evidence_uid_count`), y además se informa aparte
    (`invalid_evidence_group_count`).
    """
    problemas = []
    invalidos = 0
    grupos_invalidos = 0
    por_uid = {}
    for log in evidencia or []:
        if isinstance(log, dict) and isinstance(log.get("uid"), str):
            por_uid.setdefault(log["uid"], []).append(log)
    por_grupo = {g["group_id"]: list(g.get("uids") or []) for g in grupos or []
                 if isinstance(g, dict) and isinstance(g.get("group_id"), str)}
    if not isinstance(respuesta, dict):
        respuesta = {}
        problemas.append("respuesta_d11_no_es_objeto")

    def lista(campo):
        value = respuesta.get(campo)
        if not isinstance(value, list):
            problemas.append(f"{campo}_ausente_o_invalido")
            return []
        return value

    def grupos_citados(item):
        nonlocal invalidos, grupos_invalidos
        values = item.get("evidence_groups")
        if values is None:
            return [], []
        if not isinstance(values, list):
            problemas.append("evidence_groups_no_es_lista")
            return [], []
        validos, expandidos = [], []
        for gid in values:
            if not isinstance(gid, str) or gid.strip() not in por_grupo:
                invalidos += 1
                grupos_invalidos += 1
                problemas.append("evidence_group_inexistente")
                continue
            gid = gid.strip()
            if gid not in validos:
                validos.append(gid)
                expandidos.extend(u for u in por_grupo[gid] if u in por_uid)
        return validos, expandidos

    def uids(item):
        """(uids válidos, incluidos los expandidos de los grupos; grupos válidos)."""
        nonlocal invalidos
        values = item.get("evidence_uids")
        validos_grupos, expandidos = grupos_citados(item)
        if values is None and validos_grupos:
            values = []
        if not isinstance(values, list):
            problemas.append("evidence_uids_no_es_lista")
            return list(dict.fromkeys(expandidos)), validos_grupos
        validos = []
        for uid in values:
            if not isinstance(uid, str) or uid not in por_uid:
                invalidos += 1
                problemas.append("evidence_uid_inexistente")
            elif uid not in validos:
                validos.append(uid)
        return list(dict.fromkeys(expandidos + validos)), validos_grupos

    eventos = []
    ids = set()
    for item in lista("eventos_reconstruidos"):
        if not isinstance(item, dict):
            problemas.append("evento_no_es_objeto")
            continue
        refs, grupos_evento = uids(item)
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
        evento_normalizado = {"event_id": event_id, "evidence_uids": refs,
                              "timestamp": timestamp, "event_type": tipo or "observed_event",
                              "description": descripcion.strip(), "confidence": None}
        if grupos_evento:
            # Aditivo: qué grupos citó el modelo (sus uids ya están expandidos arriba).
            evento_normalizado["evidence_groups"] = grupos_evento
        eventos.append(evento_normalizado)

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
        refs, grupos_tecnica = uids(item)
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
            if grupos_tecnica:
                previo["evidence_groups"] = list(dict.fromkeys(previo.get("evidence_groups", []) + grupos_tecnica))
            if justification.strip() != previo["justification"]:
                previo["justification"] += " | " + justification.strip()
        else:
            nombre = item.get("technique_name")
            tecnicas[technique_id] = {"technique_id": technique_id,
                "technique_name": nombre.strip() if isinstance(nombre, str) else None,
                "evidence_uids": refs, "justification": justification.strip(), "confidence": None}
            if grupos_tecnica:
                tecnicas[technique_id]["evidence_groups"] = grupos_tecnica
    if problemas:
        logger.warning("D-11: %s; invalid_evidence_uid_count=%d", ", ".join(problemas), invalidos)
    return {"eventos_reconstruidos": eventos, "secuencia_temporal": timeline,
            "tecnicas_atribuidas": list(tecnicas.values()),
            "invalid_evidence_uid_count": invalidos,
            "invalid_evidence_group_count": grupos_invalidos, "d11_warnings": problemas}


def clasificacion_detallada(state) -> str | None:
    """`incidente_seguridad` / `anomalia_operativa` / `normal`, desde el veredicto FINAL.

    Correspondencia (M8, NODEX final), con los booleanos que se mantienen por
    compatibilidad:

    - `hay_incidente=True`                      -> `incidente_seguridad`
    - `hay_incidente=False`, `hay_anomalia=True` -> `anomalia_operativa`
    - `hay_incidente=False`, `hay_anomalia=False` -> `normal`
    - cualquier veredicto ausente o no booleano -> `None` (no se inventa)

    `classification` del contrato experimental sigue siendo MALICIOUS/BENIGN
    leído del campo que corresponde al tipo de detección del caso; por eso en
    BGL (pregunta operativa) una falla de hardware sale MALICIOUS. Este campo
    distingue esa falla operativa de un incidente de seguridad.
    """
    incidente, anomalia = state.get("hay_incidente"), state.get("hay_anomalia")
    if incidente is True:
        return "incidente_seguridad"
    if incidente is False and anomalia is True:
        return "anomalia_operativa"
    if incidente is False and anomalia is False:
        return "normal"
    return None


def campos_d11(state):
    """Exportación aditiva para API/CLI/evaluación; defaults de estados viejos."""
    return {"output_contract_version": OUTPUT_CONTRACT_VERSION,
            **{k: copy.deepcopy(state.get(k) or []) for k in
               ("eventos_reconstruidos", "secuencia_temporal", "tecnicas_atribuidas", "d11_warnings")},
            "invalid_evidence_uid_count": state.get("invalid_evidence_uid_count", 0),
            "evidencia_logs": copy.deepcopy(state.get("evidencia_logs") or []),
            "evidencia_logs_omitidos": state.get("evidencia_logs_omitidos", 0),
            "telemetry": copy.deepcopy(state.get("telemetry") or {}),
            # NODEX final, Fase A (aditivos): clasificación de tres valores
            # derivada del veredicto final (M8), veredicto preliminar del
            # triage, grupos de evidencia citables (M6) y comandos rechazados
            # por el validador (M7).
            "classification_detallada": clasificacion_detallada(state),
            "veredicto_preliminar": state.get("veredicto_preliminar"),
            "justificacion_veredicto_preliminar": state.get("justificacion_veredicto_preliminar"),
            "invalid_evidence_group_count": state.get("invalid_evidence_group_count", 0),
            "grupos_evidencia": copy.deepcopy(state.get("grupos_evidencia") or []),
            "comandos_rechazados": copy.deepcopy(state.get("comandos_rechazados") or [])}


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
