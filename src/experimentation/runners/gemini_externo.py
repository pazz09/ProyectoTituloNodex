"""Gemini usado directamente: la pseudo-ablación. §4 de los ajustes de Fase D.

Representa el comportamiento del **modelo usado directamente** frente al
sistema multiagente completo. Es deliberadamente una pseudo-ablación, no una
ablación controlada de una sola variable:

    NODEX                          VERSUS   Gemini directo
      + arquitectura                          + un único prompt
      + RAG                                   + sin arquitectura NODEX
      + herramientas                          + sin herramientas internas
      + coordinación

La pregunta que responde es *"¿qué diferencia hay entre usar NODEX como
sistema especializado completo y usar el modelo directamente?"*, **no**
*"¿qué aporta exclusivamente la división en agentes manteniendo todo lo
demás constante?"*.

## Lo que deliberadamente NO tiene

Nada de esto es un defecto: es el diseño.

- **Sin RAG.** No consulta ChromaDB ni recibe candidatas MITRE.
- **Sin herramientas.** Ni CVE, ni reputación de IP, ni validación de
  comandos.
- **Sin estado LangGraph**, sin plan, sin routers, sin bucles de corrección.
- **Sin contexto privado** generado por los agentes de NODEX.

## Lo único que comparte con NODEX

El **caso**, idéntico: el mismo archivo de `experiments/cases/`. Si recibiera
otro texto, la comparación mediría la entrada.

El preprocesamiento **no** se comparte: NODEX lo usa como parte de su
arquitectura, así que dárselo a Gemini directo sería regalarle una pieza del
sistema que se está comparando. Gemini recibe el **log crudo del caso**, que
es lo que recibiría alguien que simplemente le pega un log al modelo.

Por eso también usa su **propio cliente**, no `src/llm.py`: ese módulo
arrastra la instrumentación, el fallback y los reintentos de NODEX. Acá se
quiere el modelo desnudo, con el mismo nombre de modelo y la misma
temperatura para que la comparación sea del sistema y no del proveedor.

## Límite de tamaño

Un caso de UWF son 300 registros de ~190 bytes: ~57 KB, que entran sin
problema. Si un caso excediera `MAX_CARACTERES_PROMPT`, **no se recorta**:
se devuelve un error y la corrida queda no evaluable. Recortar en silencio
haría que Gemini viera menos caso que NODEX sin que nadie lo note.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

#: Tope de caracteres del log que se le pega al modelo. Un caso de UWF son
#: ~57 KB; el tope deja margen y falla fuerte si algo lo excede.
MAX_CARACTERES_PROMPT = 400_000

#: Instrucción del sistema. Pide los mismos campos de veredicto y reporte
#: que produce NODEX, **más** los tres campos de D-11, para que el mismo
#: evaluador pueda comparar las dos arquitecturas en las cinco dimensiones.
#:
#: Los nombres de campo son los del contrato `d11-v1`
#: (`event_id`, `technique_id`, `evidence_uids`), no los míos: el evaluador
#: compara contra lo que produce NODEX, y dos vocabularios distintos
#: obligarían a traducir uno de los dos lados, con el riesgo de traducir mal.
INSTRUCCION_SISTEMA = """\
Eres un analista de seguridad. Vas a recibir un log crudo completo y tienes
que analizarlo por tu cuenta, en una sola respuesta. No hay herramientas, no
hay búsquedas y no hay otros analistas: solo el log que te doy.

Tu trabajo:
1. Diagnosticar qué ocurrió.
2. Decidir, por separado, si hay una ANOMALÍA DE SISTEMA (comportamiento
   operativo anormal: fallos, errores, degradación) y si hay un INCIDENTE DE
   SEGURIDAD (actividad maliciosa). Son preguntas distintas: un disco que
   falla es una anomalía sin ser un incidente, y un escaneo exitoso es un
   incidente sin producir fallos.
3. Reconstruir los eventos que constituyen el incidente, si lo hay.
4. Atribuir técnicas MITRE ATT&CK, solo si el log las sustenta.
5. Proponer comandos de mitigación si corresponde.
6. Evaluar críticamente tu propio diagnóstico.

Para los eventos y las técnicas, cita los identificadores que APARECEN EN EL
LOG. Si el log trae una columna de identificador por registro (por ejemplo
`uid`), usa esos valores. No inventes identificadores: una técnica o un
evento sin evidencia citable no se cuenta.

Si ninguna técnica MITRE aplica, devuelve la lista vacía. No completes los
campos solo para satisfacer el formato.

Responde SOLO en JSON:
{"diagnostico": "...",
 "hay_anomalia": true/false,
 "hay_incidente": true/false,
 "confianza": 0.0,
 "evaluacion": "...",
 "comandos_mitigacion": ["..."],
 "eventos_reconstruidos": [{"event_id": "...", "evidence_uids": ["..."],
                            "timestamp": "...", "event_type": "...",
                            "description": "..."}],
 "secuencia_temporal": ["..."],
 "tecnicas_atribuidas": [{"technique_id": "T....", "technique_name": "...",
                          "evidence_uids": ["..."], "justification": "..."}]}
"""

#: Nombre del modelo y temperatura se toman de la misma configuración que
#: usa NODEX, para que la comparación no mida un modelo distinto.
_ETIQUETA = "gemini_externo"


def _cliente(api_key: str, timeout_ms: int):
    """Cliente propio, separado del de `src/llm.py`."""
    from google import genai
    from google.genai import types

    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=timeout_ms),
    ), types


def _parsear_json(texto: str):
    """Mismo criterio de tolerancia que `src/llm.py`, sin sus reintentos.

    Se repite acá a propósito en vez de importar `_safe_json_parse`: este
    runner no debe depender del módulo LLM de NODEX, que arrastra la
    instrumentación y el fallback.
    """
    if not texto:
        return None
    t = texto.strip()
    t = re.sub(r"^```(json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        encontrado = re.search(r"[\{\[].*[\}\]]", t, re.DOTALL)
        if encontrado:
            try:
                return json.loads(encontrado.group(0))
            except Exception:
                return None
        return None


def ejecutar(contenido: str, run_id: str) -> tuple[dict, dict]:
    """Una sola llamada a Gemini con el log crudo. Devuelve `(estado, diag)`.

    El `estado` usa las mismas claves que el estado final de NODEX más los
    tres campos de `d11-v1`, así que el adaptador experimental lo consume sin
    ramas especiales.

    **Hace una llamada al modelo.** Solo debe invocarse durante una corrida
    autorizada.
    """
    from src.config import (
        GEMINI_API_KEY,
        LLM_MODEL_PRIMARY,
        TEMPERATURE,
        TIMEOUT_SOLICITUD_SEG,
    )

    if len(contenido) > MAX_CARACTERES_PROMPT:
        # No se recorta: recortar en silencio haría que Gemini viera menos
        # caso que NODEX sin que nadie lo note.
        return {}, {
            "arquitectura": _ETIQUETA,
            "error": (
                f"el caso tiene {len(contenido)} caracteres y el tope es "
                f"{MAX_CARACTERES_PROMPT}; no se recorta"
            ),
            "modelo": LLM_MODEL_PRIMARY,
            "llamadas_llm": 0,
        }
    if not GEMINI_API_KEY:
        return {}, {
            "arquitectura": _ETIQUETA,
            "error": "falta GEMINI_API_KEY",
            "llamadas_llm": 0,
        }

    cliente, types = _cliente(
        GEMINI_API_KEY, int(TIMEOUT_SOLICITUD_SEG * 1000)
    )
    configuracion = types.GenerateContentConfig(
        temperature=TEMPERATURE,
        response_mime_type="application/json",
        system_instruction=INSTRUCCION_SISTEMA,
    )

    comenzado = time.monotonic()
    error: str | None = None
    respuesta = None
    uso = None
    # Sin reintentos y sin fallback de modelo: el punto de la pseudo-ablación
    # es el modelo desnudo. Un fallo se registra como fallo.
    try:
        bruta = cliente.models.generate_content(
            model=LLM_MODEL_PRIMARY,
            contents=f"LOG A ANALIZAR:\n{contenido}",
            config=configuracion,
        )
        respuesta = _parsear_json(getattr(bruta, "text", "") or "")
        uso = getattr(bruta, "usage_metadata", None)
    except Exception as excepcion:  # noqa: BLE001 - se registra, no se oculta
        error = f"{type(excepcion).__name__}: {excepcion}"
    transcurrido = time.monotonic() - comenzado

    if not isinstance(respuesta, dict):
        if error is None:
            error = "la respuesta no es un objeto JSON"
        respuesta = {}

    def _booleano(clave: str):
        """Solo un booleano real. `None` si no vino uno.

        Convertirlo con `bool()` inventaría una predicción, que es el defecto
        que ya falseó conteos en este proyecto.
        """
        valor = respuesta.get(clave)
        return valor if isinstance(valor, bool) else None

    def _lista(clave: str) -> list:
        valor = respuesta.get(clave)
        return valor if isinstance(valor, list) else []

    confianza = respuesta.get("confianza")
    estado = {
        "diagnostico": respuesta.get("diagnostico") or "",
        "hay_anomalia": _booleano("hay_anomalia"),
        "hay_incidente": _booleano("hay_incidente"),
        "confianza": (
            confianza
            if isinstance(confianza, (int, float)) and not isinstance(confianza, bool)
            else None
        ),
        "evaluacion_auditor": respuesta.get("evaluacion") or "",
        "comandos_mitigacion": _lista("comandos_mitigacion"),
        # Los tres campos de `d11-v1`, con los nombres del contrato.
        "eventos_reconstruidos": _lista("eventos_reconstruidos"),
        "secuencia_temporal": [
            str(u) for u in _lista("secuencia_temporal")
        ],
        "tecnicas_atribuidas": _lista("tecnicas_atribuidas"),
        # Sin RAG: la lista de candidatas va vacía, y eso es parte del
        # diseño, no un dato faltante.
        "tecnicas_mitre": [],
        "output_contract_version": "d11-v1",
    }

    def _entero(valor):
        if isinstance(valor, bool) or not isinstance(valor, int):
            return None
        return valor

    diagnostico = {
        "arquitectura": _ETIQUETA,
        "modelo": LLM_MODEL_PRIMARY,
        "temperatura": TEMPERATURE,
        "llamadas_llm": 0 if error and respuesta == {} else 1,
        "execution_time": transcurrido,
        "error": error,
        "sin_rag": True,
        "sin_herramientas": True,
        "sin_estado_langgraph": True,
        "reintentos": 0,
        "fallback_de_modelo": False,
        "telemetry": {
            "llm_call_count": 0 if error and respuesta == {} else 1,
            "input_tokens": _entero(getattr(uso, "prompt_token_count", None)),
            "output_tokens": _entero(
                getattr(uso, "candidates_token_count", None)
            ),
            "total_tokens": _entero(getattr(uso, "total_token_count", None)),
            "execution_time": transcurrido,
            # No aplican: no hay grafo que replanifique ni comandos que
            # corregir. `None` y no 0, porque 0 afirmaría que hubo cero
            # replanificaciones en un sistema que no replanifica.
            "replan_count": None,
            "intentos_correccion": None,
            "modelo_efectivo": LLM_MODEL_PRIMARY,
        },
        "campos_ausentes_en_la_respuesta": sorted(
            clave for clave in ("diagnostico", "hay_anomalia", "hay_incidente",
                                "confianza", "evaluacion",
                                "comandos_mitigacion",
                                "eventos_reconstruidos", "tecnicas_atribuidas")
            if clave not in respuesta
        ),
    }
    return estado, diagnostico


def cargar_caso(raiz_repo: Path, dataset: str, particion: str, case_id: str) -> str:
    """Lee el contenido de un caso. **No lee su ground truth.**

    Es la misma lectura que usan los otros runners, sobre el mismo archivo.
    """
    directorio = raiz_repo / "experiments" / "cases" / dataset / particion
    for extension in ("log", "csv"):
        archivo = directorio / f"{case_id}.{extension}"
        if archivo.is_file():
            return archivo.read_text(encoding="utf-8")
    raise FileNotFoundError(
        f"no se encontró el contenido del caso {case_id} en {directorio}"
    )
