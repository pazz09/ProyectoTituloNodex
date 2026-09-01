"""Cliente Gemini y wrapper de llamadas con salida JSON.

Migrado desde las celdas 4 y 9 del notebook de Colab.
"""

import json
import random
import re
import ssl
import time

from google import genai
from google.genai import types

try:
    import httpx
    _TIPOS_ERROR_TRANSPORTE = (ssl.SSLError, ConnectionError, TimeoutError, httpx.TransportError)
except ImportError:  # httpx no es una dependencia directa; si no está, igual cubrimos lo esencial
    _TIPOS_ERROR_TRANSPORTE = (ssl.SSLError, ConnectionError, TimeoutError)

from src.config import (
    BACKOFF_INICIAL,
    BACKOFF_JITTER,
    BACKOFF_MAX,
    GEMINI_API_KEY,
    LLM_MODEL_FALLBACK,
    LLM_MODEL_PRIMARY,
    MAX_REINTENTOS_CUOTA_MINUTO,
    MAX_REINTENTOS_TRANSITORIO,
    TEMPERATURE,
    TIMEOUT_SOLICITUD_SEG,
    validate_config,
)

validate_config()
client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options=types.HttpOptions(timeout=int(TIMEOUT_SOLICITUD_SEG * 1000)),
)


def _safe_json_parse(text: str):
    """Intenta parsear JSON; tolera ```json ...``` y texto alrededor."""
    if text is None:
        return None
    t = text.strip()
    t = re.sub(r"^```(json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"[\{\[].*[\}\]]", t, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
        return None


def _tipo_error_cuota(e: Exception) -> str | None:
    """Distingue el TIPO de 429 -- no todos los errores de cuota son iguales.

    Hallazgo real (25-ago-2026, primera corrida real sobre HDFS_2k.log): el
    código anterior trataba cualquier 429 como terminal ("no reintentar,
    nunca se repone en segundos"). Eso es correcto para la cuota DIARIA
    (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`), pero esa corrida
    murió por la cuota POR MINUTO (`GenerateRequestsPerMinutePerProjectPerModel
    -FreeTier`, límite 5/min), que Google indicó como recuperable con
    `retryDelay: 1s` en el mismo error -- y el código la abortaba igual que
    si fuera la diaria, sin motivo.

    El `quotaId` en el cuerpo del error distingue ambos casos. Devuelve
    "dia", "minuto", o None si no es un 429 de cuota reconocible. Un 429
    real cuyo quotaId no se puede identificar se trata como "dia" (la
    opción conservadora: no asumir que es seguro reintentar).
    """
    codigo = getattr(e, "code", None) or getattr(e, "status_code", None)
    msg = str(e)
    es_cuota = codigo == 429 or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower()
    if not es_cuota:
        return None
    if "PerMinute" in msg:
        return "minuto"
    if "PerDay" in msg:
        return "dia"
    return "dia"


def _es_error_de_cuota(e: Exception) -> bool:
    """Compatibilidad hacia atrás: True ante CUALQUIER 429 (diario o por
    minuto). Preferir `_tipo_error_cuota` para decidir si vale la pena
    reintentar -- este helper ya no se usa en `_generate_con_backoff`."""
    return _tipo_error_cuota(e) is not None


def _retry_delay_sugerido(e: Exception, default: float = 15.0) -> float:
    """Extrae el `retryDelay` que Google sugiere en el propio error (p. ej.
    "retryDelay: '1s'") para un 429 por minuto. Si no está presente, usa
    `default` -- con el límite de 5 solicitudes/minuto del tier gratuito,
    ~12-15s de espera alcanza para no volver a pegarle al mismo límite."""
    m = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s", str(e))
    if m:
        return float(m.group(1))
    return default


def _es_error_transitorio(e: Exception) -> bool:
    """503 UNAVAILABLE / sobrecarga momentánea del lado de Google, Y fallos de
    transporte a nivel de red/TLS -- estos sí vale la pena reintentar con
    backoff corto, a diferencia de un 429 de cuota.

    Hallazgo real (26-ago-2026, corridas reales sobre HDFS/BGL): una corrida
    murió con `[SSL: UNEXPECTED_EOF_WHILE_READING]` -- un corte de la
    conexión TLS a mitad de la respuesta. Este tipo de error NO trae código
    HTTP (`.code`/`.status_code` vienen None), así que la versión anterior
    de esta función no lo reconocía como transitorio y no lo reintentaba --
    siendo, de los errores vistos ese día, el más claramente recuperable
    (un corte de socket, no un problema del lado del servicio). Se cubre
    por tipo de excepción (`ssl.SSLError`, `ConnectionError`, `TimeoutError`,
    y `httpx.TransportError` si `httpx` está disponible) y, como respaldo,
    por texto del mensaje -- algunos SDKs envuelven el error de transporte
    en su propia clase de excepción sin preservar el tipo original.
    """
    codigo = getattr(e, "code", None) or getattr(e, "status_code", None)
    msg = str(e)
    if codigo == 503 or "UNAVAILABLE" in msg or "high demand" in msg.lower():
        return True
    if isinstance(e, _TIPOS_ERROR_TRANSPORTE):
        return True
    msg_lower = msg.lower()
    return (
        "ssl" in msg_lower
        or "unexpected_eof" in msg_lower
        or "connection reset" in msg_lower
        or "connection aborted" in msg_lower
    )


def _espera_con_jitter(espera: float, jitter: float) -> float:
    """Aplica jitter proporcional (±`jitter`) a una espera de backoff, para
    que reintentos que arrancan al mismo tiempo (p. ej. varios nodos del
    grafo pegándole a la API tras el mismo 503 masivo) no se sincronicen y
    vuelvan a chocar juntos contra el límite. `jitter=0` desactiva el
    efecto y devuelve `espera` sin cambios (usado en tests deterministas)."""
    if jitter <= 0:
        return espera
    return espera * random.uniform(1 - jitter, 1 + jitter)


def _generate_con_backoff(
    msg: str,
    cfg,
    modelo: str = LLM_MODEL_PRIMARY,
    max_reintentos: int = MAX_REINTENTOS_TRANSITORIO,
    espera_inicial: float = BACKOFF_INICIAL,
    max_reintentos_cuota_minuto: int = MAX_REINTENTOS_CUOTA_MINUTO,
    backoff_max: float = BACKOFF_MAX,
    jitter: float = BACKOFF_JITTER,
):
    """`generate_content` con dos mecanismos de reintento independientes,
    contra un único `modelo` (ver `_generate_con_fallback` para el cambio
    automático de modelo cuando este agota sus reintentos):

    - 503 / error de transporte (SSL, conexión): backoff exponencial
      (hasta `max_reintentos` veces, `espera_inicial` -> ×2 cada vez, con
      un techo `backoff_max` y jitter proporcional `jitter` para no
      sincronizar reintentos concurrentes -- ver `_espera_con_jitter`)
      -- comparten el mismo contador y camino, ver `_es_error_transitorio`.
    - 429 por minuto: reintenta hasta `max_reintentos_cuota_minuto` veces,
      esperando el `retryDelay` que sugiere el propio error de Google (no
      backoff exponencial -- la cuota por minuto se repone en un tiempo fijo,
      no cada vez más lento).

    Ante un 429 DIARIO, relanza de inmediato sin reintentar -- no se repone
    en segundos y cada intento arriesga gastar más cuota (ver
    `_tipo_error_cuota`). Motivado por una corrida real (23-ago-2026) donde
    un bucle de reintentos sin esta distinción quemó la cuota diaria del
    tier gratuito ante una racha de 503 intermitentes.
    """
    espera = espera_inicial
    intentos_503 = 0
    intentos_cuota_minuto = 0
    while True:
        try:
            return client.models.generate_content(model=modelo, contents=msg, config=cfg)
        except Exception as e:
            tipo_cuota = _tipo_error_cuota(e)
            if tipo_cuota == "dia":
                raise
            if tipo_cuota == "minuto":
                if intentos_cuota_minuto >= max_reintentos_cuota_minuto:
                    raise
                intentos_cuota_minuto += 1
                time.sleep(_retry_delay_sugerido(e))
                continue
            if not _es_error_transitorio(e) or intentos_503 >= max_reintentos:
                raise
            intentos_503 += 1
            time.sleep(_espera_con_jitter(espera, jitter))
            espera = min(espera * 2, backoff_max)


def _generate_con_fallback(msg: str, cfg, **kwargs):
    """Llama primero a `LLM_MODEL_PRIMARY`; si agota sus reintentos por un
    error RECONOCIDO (cuota diaria o por minuto agotada, o error transitorio
    agotado -- ver `_tipo_error_cuota`/`_es_error_transitorio`), reintenta
    una vez completo con `LLM_MODEL_FALLBACK` antes de darse por vencido.

    Un error NO reconocido (p. ej. un 400 por un prompt mal formado -- un
    bug de código, no de disponibilidad del modelo) se relanza de inmediato
    sin probar el modelo de respaldo: cambiar de modelo no arregla un bug,
    solo lo repite dos veces.

    Decisión (1-sep-2026): principal `gemini-3.1-pro-preview` (mejor calidad
    medida, más caro), respaldo `gemini-3.6-flash` (~3.4x más barato, 0
    fallas en las corridas reales de prueba) -- ver `src/config.py` para el
    detalle de la decisión y los datos medidos.
    """
    try:
        return _generate_con_backoff(msg, cfg, modelo=LLM_MODEL_PRIMARY, **kwargs)
    except Exception as e:
        if _tipo_error_cuota(e) is None and not _es_error_transitorio(e):
            raise
        print(
            f"\n⚠️  Modelo principal ({LLM_MODEL_PRIMARY}) no disponible "
            f"({type(e).__name__}: {e}). Reintentando con el de respaldo "
            f"({LLM_MODEL_FALLBACK})..."
        )
        return _generate_con_backoff(msg, cfg, modelo=LLM_MODEL_FALLBACK, **kwargs)


def llm_json(prompt: str, system: str = None, retries: int = 1) -> dict:
    """Llama a Gemini y devuelve un dict.

    Mecanismos de reintento/resiliencia, de más al menos granular:
    - `retries`: si el JSON de la respuesta viene inválido, se le pide de nuevo
      al LLM (comportamiento original, migrado del notebook).
    - Backoff/espera ante errores transitorios de la API contra el modelo
      principal (ver `_generate_con_backoff`): reintenta 503 y
      429-por-minuto; nunca reintenta un 429 diario.
    - Cambio automático a un modelo de respaldo si el principal agota sus
      reintentos por un error reconocido (ver `_generate_con_fallback`).
    """
    cfg = types.GenerateContentConfig(
        temperature=TEMPERATURE,
        response_mime_type="application/json",
        system_instruction=system,
    )
    last_text = ""
    for attempt in range(retries + 1):
        msg = prompt if attempt == 0 else (
            prompt + f"\n\nTu respuesta anterior no fue JSON válido:\n{last_text}\n"
            "Devuelve ÚNICAMENTE JSON válido, sin texto adicional."
        )
        resp = _generate_con_fallback(msg, cfg)
        if resp.usage_metadata:
            um = resp.usage_metadata
            print(f"   [tokens] entrada={um.prompt_token_count} "
                  f"salida={um.candidates_token_count} "
                  f"razonamiento={getattr(um, 'thoughts_token_count', 0)} "
                  f"total={getattr(um, 'total_token_count', '?')}")
        last_text = resp.text or ""
        parsed = _safe_json_parse(last_text)
        if isinstance(parsed, (dict, list)):
            return parsed
    return {"error": "json_invalido", "raw": last_text}
