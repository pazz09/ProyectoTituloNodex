"""Mediciones por ejecución aisladas con ContextVar, incluidos reintentos."""

from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter

_medicion = ContextVar("nodex_medicion", default=None)


@contextmanager
def medir_ejecucion():
    token = _medicion.set({"start": perf_counter(), "calls": []})
    try:
        yield
    finally:
        _medicion.reset(token)


def medir_pasos(generador):
    """Mide un generador activando la medición solo DURANTE cada paso (cada `next()`).

    `medir_ejecucion()` abre la medición con `ContextVar.set()` y la cierra con `reset(token)`. Eso sirve para
    una función normal, pero NO para un generador que se consume por pasos desde otro contexto: el servidor web
    (Starlette) avanza un generador síncrono con un hilo y una copia nueva del contexto en cada paso. Entonces
    (1) el `reset` falla con «Token ... was created in a different Context» al terminar y (2) los pasos siguientes
    ni siquiera ven la medición, así que los tokens y las llamadas quedarían sin registrar.

    Acá la medición es un objeto propio del generador; en cada paso se la pone en el contexto de ESE paso y se
    la saca en el mismo paso (set y reset siempre en el mismo contexto). El objeto es compartido, así que las
    llamadas se acumulan entre pasos.
    """
    medicion = {"start": perf_counter(), "calls": []}
    try:
        while True:
            token = _medicion.set(medicion)
            try:
                evento = next(generador)
            except StopIteration:
                return
            finally:
                _medicion.reset(token)
            yield evento
    finally:
        generador.close()


def iniciar_llamada(modelo):
    medicion = _medicion.get()
    if medicion is None:
        return None
    llamada = {"model": modelo, "input_tokens": None, "output_tokens": None,
               "total_tokens": None}
    medicion["calls"].append(llamada)
    return llamada


def registrar_consumo(llamada, respuesta):
    if llamada is None:
        return
    uso = getattr(respuesta, "usage_metadata", None)
    for campo, proveedor in (("input_tokens", "prompt_token_count"),
                             ("output_tokens", "candidates_token_count"),
                             ("total_tokens", "total_token_count")):
        valor = getattr(uso, proveedor, None)
        if isinstance(valor, int) and not isinstance(valor, bool) and valor >= 0:
            llamada[campo] = valor


def resumen_telemetria(state):
    medicion = _medicion.get()
    calls = medicion["calls"] if medicion else []
    # Si falta consumo de alguna solicitud, el total correspondiente es
    # desconocido. El total del proveedor puede incluir tokens de razonamiento.
    tokens = {k: sum(c[k] for c in calls) if calls and all(c[k] is not None for c in calls) else None
              for k in ("input_tokens", "output_tokens", "total_tokens")}
    correcciones = state.get("intentos_correccion", 0) or 0
    correcciones += sum((p.get("resultados_asociados") or {}).get("intentos_correccion", 0) or 0
                       for p in state.get("historial_planes") or [])
    return {"llm_call_count": len(calls) if medicion else None, **tokens,
            "execution_time": round(perf_counter() - medicion["start"], 6) if medicion else None,
            "replan_count": state.get("replan_count", 0),
            "intentos_correccion": correcciones,
            "invalid_evidence_uid_count": state.get("invalid_evidence_uid_count", 0),
            "d11_warning_count": len(state.get("d11_warnings") or []),
            "llm_calls": [dict(c) for c in calls]}
