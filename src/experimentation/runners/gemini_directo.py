"""Gemini 3.8 Flash directo: comparación de NODEX con el modelo base (evaluación final).

Responde: ¿aporta el sistema NODEX respecto de usar el mismo modelo directamente? Reproduce el uso
de un asistente de chat: el **prompt estructurado v2.1** (el mismo de la comparación con ChatGPT,
Claude y Gemini en chat; `experiments/config/prompt_gemini_directo_v2_1.txt`, texto congelado y
verificado por SHA-256) seguido del **archivo crudo y completo del caso**, en un solo mensaje.

- Mismo modelo que NODEX (`gemini-3.8-flash`, `LLM_MODEL_PRIMARY`), temperatura 0.
- Una sola llamada: sin modelo de respaldo, sin reintentos, sin herramientas, sin búsqueda ni
  grounding, sin instrucción de sistema y sin modo JSON forzado (el prompt pide un bloque de código).
- Sin preprocesamiento, memoria, RAG ni arquitectura: el archivo `.log`/`.csv` tal cual, sin recortes.
- Cliente propio (no `src/llm.py`, que trae reintentos, respaldo e instrumentación de NODEX).

Salida: la respuesta cruda completa, el JSON extraído del bloque de código (sin corregirlo) y su
normalización al esquema de NODEX con el **mismo filtro de evidencia** que `normalizar_d11`:
identificadores que no existen en el archivo del caso se descartan y se cuentan aparte; un evento sin
evidencia válida o sin descripción se descarta; una técnica necesita un id `Tdddd[.ddd]`, evidencia
válida y justificación, y su evidencia se limita a la de los eventos de incidente. El contrato v2.1
solo admite eventos de incidente, así que todos sus eventos quedan con `categoria = "incidente"`.
En BGL, `log_record_NNNNNN` es la posición (desde 1) de la línea en el archivo, el mismo identificador
que usa el catálogo de NODEX.

Fallas: un JSON inválido (o sin bloque utilizable, o que no es un objeto, o sin los veredictos
booleanos) es **falla del sistema**: se registra y no se repite. Un error de la API por red, cuota
transitoria o servidor es **falla de infraestructura** (el ejecutor aparta la corrida y la repite);
el crédito agotado se informa aparte para detener la ejecución.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
PROMPT_PATH = RAIZ / "experiments/config/prompt_gemini_directo_v2_1.txt"
#: SHA-256 del prompt v2.1 (UTF-8, saltos de línea LF). Se verifica antes de cada llamada.
PROMPT_SHA256 = "2dd880789645f682d411094f2bfa224168bf416c68fa8f66c348e16e93dde660"
ETIQUETA = "gemini_directo"
#: Columnas que no pueden llegar al modelo (etiquetas del dataset UWF).
COLUMNAS_PROHIBIDAS = ("label", "mitre", "tactic", "technique")
_PATRON_TECNICA = re.compile(r"T\d{4}(?:\.\d{3})?")


class PromptAlterado(RuntimeError):
    """El prompt en disco no coincide con el congelado."""


def prompt_congelado() -> str:
    texto = PROMPT_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    huella = hashlib.sha256(texto.encode("utf-8")).hexdigest()
    if huella != PROMPT_SHA256:
        raise PromptAlterado(f"el prompt v2.1 cambió (sha256 {huella}, esperado {PROMPT_SHA256})")
    return texto


def construir_solicitud(contenido: str) -> str:
    """El prompt congelado y, a continuación, el archivo completo del caso."""
    return prompt_congelado() + "\n" + contenido


def sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def columnas_prohibidas(contenido: str, dataset: str) -> list[str]:
    if dataset != "uwf":
        return []
    cabecera = next(csv.reader(io.StringIO(contenido)), [])
    return [c for c in cabecera if any(p in c.lower() for p in COLUMNAS_PROHIBIDAS)]


def identificadores(contenido: str, dataset: str) -> set[str]:
    """Identificadores citables del archivo: `uid` en UWF; `log_record_NNNNNN` por línea en BGL."""
    if dataset == "uwf":
        return {f["uid"].strip() for f in csv.DictReader(io.StringIO(contenido)) if f.get("uid")}
    lineas = [l for l in contenido.splitlines() if l.strip()]
    return {f"log_record_{i:06d}" for i in range(1, len(lineas) + 1)}


def extraer_json(texto: str) -> tuple[dict | None, str]:
    """El objeto JSON del bloque de código, sin repararlo. Devuelve `(objeto o None, motivo)`."""
    if not texto or not texto.strip():
        return None, "respuesta_vacia"
    bloques = re.findall(r"```[ \t]*(?:json|JSON)?[ \t]*\r?\n(.*?)```", texto, re.DOTALL)
    candidato, forma = (bloques[0], "bloque_de_codigo") if bloques else (texto.strip(), "sin_bloque_de_codigo")
    try:
        objeto = json.loads(candidato)
    except json.JSONDecodeError as e:
        return None, f"json_invalido ({forma}): {e.msg} en línea {e.lineno}"
    if not isinstance(objeto, dict):
        return None, f"json_no_es_objeto ({forma})"
    return objeto, forma


def normalizar(respuesta: dict, validos: set[str]) -> dict:
    """Esquema de NODEX con el mismo filtro de evidencia (`normalizar_d11`)."""
    from src.output_contract import clasificacion_detallada
    problemas, invalidos = [], 0

    def filtrar(valores):
        nonlocal invalidos
        if not isinstance(valores, list):
            problemas.append("evidence_uids_no_es_lista")
            return []
        salida = []
        for uid in valores:
            uid = uid.strip() if isinstance(uid, str) else uid
            if not isinstance(uid, str) or uid not in validos:
                invalidos += 1
                problemas.append("evidence_uid_inexistente")
            elif uid not in salida:
                salida.append(uid)
        return salida

    def lista(campo):
        valor = respuesta.get(campo)
        if not isinstance(valor, list):
            problemas.append(f"{campo}_ausente_o_invalido")
            return []
        return valor

    eventos, ids = [], set()
    for item in lista("eventos_reconstruidos"):
        if not isinstance(item, dict):
            problemas.append("evento_no_es_objeto")
            continue
        refs = filtrar(item.get("evidence_uids"))
        if not refs:
            problemas.append("evento_sin_evidencia")
            continue
        event_id = item.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip() or event_id.strip() in validos:
            event_id = f"event_{len(eventos) + 1:03d}"
        event_id = event_id.strip()
        if event_id in ids:
            problemas.append("event_id_duplicado")
            continue
        descripcion = item.get("description")
        if not isinstance(descripcion, str) or not descripcion.strip():
            problemas.append("evento_sin_descripcion")
            continue
        tipo = item.get("event_type")
        tipo = re.sub(r"[^a-z0-9]+", "_", tipo.lower()).strip("_") if isinstance(tipo, str) else ""
        ids.add(event_id)
        eventos.append({"event_id": event_id, "evidence_uids": refs,
                        # Sin catálogo de preprocesamiento: la marca de tiempo queda tal como la dio el modelo.
                        "timestamp": item.get("timestamp") if isinstance(item.get("timestamp"), str) else None,
                        "event_type": tipo or "observed_event", "description": descripcion.strip(),
                        "confidence": None, "categoria": "incidente"})
    de_incidente = {u for e in eventos for u in e["evidence_uids"]}
    tecnicas = {}
    for item in lista("tecnicas_atribuidas"):
        if not isinstance(item, dict):
            problemas.append("tecnica_no_es_objeto")
            continue
        refs = filtrar(item.get("evidence_uids"))
        technique_id = item.get("technique_id")
        technique_id = technique_id.strip().upper() if isinstance(technique_id, str) else ""
        if not _PATRON_TECNICA.fullmatch(technique_id):
            problemas.append("technique_id_invalido")
            continue
        justificacion = item.get("justification")
        if not refs or not isinstance(justificacion, str) or not justificacion.strip():
            problemas.append("tecnica_sin_evidencia_o_justificacion")
            continue
        refs = [u for u in refs if u in de_incidente]
        if not refs:
            problemas.append("tecnica_sin_evidencia_de_incidente")
            continue
        if technique_id in tecnicas:
            previo = tecnicas[technique_id]
            previo["evidence_uids"] = list(dict.fromkeys(previo["evidence_uids"] + refs))
            if justificacion.strip() != previo["justification"]:
                previo["justification"] += " | " + justificacion.strip()
        else:
            nombre = item.get("technique_name")
            tecnicas[technique_id] = {"technique_id": technique_id,
                                      "technique_name": nombre.strip() if isinstance(nombre, str) else None,
                                      "evidence_uids": refs, "justification": justificacion.strip(),
                                      "confidence": None}

    def booleano(clave):
        valor = respuesta.get(clave)
        return valor if isinstance(valor, bool) else None

    confianza = respuesta.get("confianza")
    confianza = (float(confianza) if isinstance(confianza, (int, float)) and not isinstance(confianza, bool)
                 and 0 <= confianza <= 1 else None)
    comandos = [c for c in lista("comandos_mitigacion") if isinstance(c, str)]
    estado = {
        "diagnostico": respuesta.get("diagnostico") if isinstance(respuesta.get("diagnostico"), str) else "",
        "hay_anomalia": booleano("hay_anomalia"), "hay_incidente": booleano("hay_incidente"),
        "confianza": confianza,
        "evaluacion": respuesta.get("evaluacion") if isinstance(respuesta.get("evaluacion"), str) else "",
        "comandos_mitigacion": comandos,
        "eventos_reconstruidos": eventos,
        # El orden en que el modelo listó los eventos (el prompt los pide en orden); el texto de su
        # secuencia queda en la respuesta cruda.
        "secuencia_temporal": [e["event_id"] for e in eventos],
        "tecnicas_atribuidas": list(tecnicas.values()),
        "invalid_evidence_uid_count": invalidos,
        "d11_warnings": problemas,
    }
    estado["evaluacion_auditor"] = estado["evaluacion"]
    estado["classification_detallada"] = clasificacion_detallada(estado)
    return estado


def clasificar_error(excepcion: Exception) -> str:
    """`credito_agotado`, `infraestructura` (red, cuota transitoria, servidor) o `sistema`."""
    texto = f"{type(excepcion).__name__}: {excepcion}"
    if "prepayment" in texto.lower() or "credits are depleted" in texto.lower() or " 402" in texto:
        return "credito_agotado"
    codigo = getattr(excepcion, "code", None) or getattr(excepcion, "status_code", None)
    if codigo in (408, 429, 500, 502, 503, 504) or any(
            p in texto for p in ("UNAVAILABLE", "DEADLINE_EXCEEDED", "RESOURCE_EXHAUSTED", "Timeout", "timed out",
                                 "Connection", "ConnectError", "RemoteProtocolError", "ReadError")):
        return "infraestructura"
    return "sistema"


def _llamar(solicitud: str):
    """Una llamada a Gemini, sin reintentos ni respaldo. Devuelve la respuesta de la API."""
    from google import genai
    from google.genai import types

    from src.config import GEMINI_API_KEY, LLM_MODEL_PRIMARY, TEMPERATURE, TIMEOUT_SOLICITUD_SEG
    cliente = genai.Client(api_key=GEMINI_API_KEY,
                           http_options=types.HttpOptions(timeout=int(TIMEOUT_SOLICITUD_SEG * 1000)))
    return cliente.models.generate_content(model=LLM_MODEL_PRIMARY, contents=solicitud,
                                           config=types.GenerateContentConfig(temperature=TEMPERATURE))


def ejecutar(contenido: str, dataset: str, llamar=None) -> dict:
    """Corre un caso. `llamar` permite simular el modelo en las pruebas (recibe la solicitud).

    **Con `llamar=None` hace una llamada real al modelo.**
    """
    from src.config import LLM_MODEL_PRIMARY, TEMPERATURE
    registro = {"arquitectura": ETIQUETA, "modelo": LLM_MODEL_PRIMARY, "temperatura": TEMPERATURE,
                "prompt_sha256": PROMPT_SHA256, "llamadas_llm": 0, "falla": None, "detalle_falla": None,
                "respuesta_cruda": None, "json_extraido": None, "forma_respuesta": None, "normalizado": None,
                "telemetria": None}
    prohibidas = columnas_prohibidas(contenido, dataset)
    if prohibidas:
        registro.update(falla="entrada_invalida", detalle_falla=f"columnas de etiqueta en el archivo: {prohibidas}")
        return registro
    solicitud = construir_solicitud(contenido)
    registro["solicitud_sha256"] = sha256(solicitud)
    registro["solicitud_caracteres"] = len(solicitud)
    inicio = time.monotonic()
    try:
        bruta = (llamar or _llamar)(solicitud)
        registro["llamadas_llm"] = 1
    except Exception as e:  # noqa: BLE001 - se registra y se clasifica, no se oculta
        registro.update(llamadas_llm=1, falla=clasificar_error(e), detalle_falla=f"{type(e).__name__}: {e}",
                        segundos=time.monotonic() - inicio)
        return registro
    registro["segundos"] = time.monotonic() - inicio
    texto = getattr(bruta, "text", None) or ""
    uso = getattr(bruta, "usage_metadata", None)

    def entero(nombre):
        valor = getattr(uso, nombre, None)
        return valor if isinstance(valor, int) and not isinstance(valor, bool) else None

    version = getattr(bruta, "model_version", None)
    registro["telemetria"] = {"llm_calls": [{
        "model": LLM_MODEL_PRIMARY, "model_version": version if isinstance(version, str) else None,
        "input_tokens": entero("prompt_token_count"), "output_tokens": entero("candidates_token_count"),
        "reasoning_tokens": entero("thoughts_token_count"), "total_tokens": entero("total_token_count")}],
        "execution_time": registro["segundos"], "llm_call_count": 1}
    registro["respuesta_cruda"] = texto
    objeto, forma = extraer_json(texto)
    registro["forma_respuesta"] = forma
    if objeto is None:
        registro.update(falla="sistema", detalle_falla=forma)
        return registro
    registro["json_extraido"] = objeto
    registro["normalizado"] = normalizar(objeto, identificadores(contenido, dataset))
    if not (isinstance(registro["normalizado"]["hay_anomalia"], bool)
            and isinstance(registro["normalizado"]["hay_incidente"], bool)):
        registro.update(falla="sistema", detalle_falla="la respuesta no trae los veredictos booleanos")
    return registro
