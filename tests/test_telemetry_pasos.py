"""Regresión: «Token ... was created in a different Context» al analizar desde la interfaz web.

El servidor (Starlette) avanza un generador síncrono con un hilo y una COPIA NUEVA del contexto en cada paso.
`medir_ejecucion()` (set al abrir, reset al cerrar) revienta ahí y, antes de reventar, los pasos siguientes no
ven la medición: los tokens y las llamadas del análisis se perdían. `medir_pasos()` lo resuelve.
"""

import contextvars
import json

import pytest

from src import pipeline, telemetry


def _respuesta(entrada=10, salida=5):
    uso = type("U", (), {"prompt_token_count": entrada, "candidates_token_count": salida,
                         "total_token_count": entrada + salida})()
    return type("R", (), {"usage_metadata": uso})()


def _un_paso_por_contexto_nuevo(generador):
    """Lo que hace Starlette con un generador síncrono: cada `next()` en una copia nueva del contexto."""
    eventos = []
    while True:
        try:
            eventos.append(contextvars.copy_context().run(next, generador))
        except StopIteration:
            return eventos


def _interno(n=3):
    for i in range(n):
        llamada = telemetry.iniciar_llamada("m")
        telemetry.registrar_consumo(llamada, _respuesta())
        yield {"i": i, "hay_medicion": llamada is not None, "resumen": telemetry.resumen_telemetria({})}


def test_medir_ejecucion_sobre_un_generador_falla_en_contextos_distintos_este_es_el_defecto():
    def generador():
        with telemetry.medir_ejecucion():
            yield from _interno()

    with pytest.raises(ValueError, match="different Context"):
        _un_paso_por_contexto_nuevo(generador())


def test_medir_pasos_no_falla_con_un_contexto_distinto_en_cada_paso():
    eventos = _un_paso_por_contexto_nuevo(telemetry.medir_pasos(_interno()))
    assert len(eventos) == 3


def test_medir_pasos_acumula_las_llamadas_entre_pasos():
    eventos = _un_paso_por_contexto_nuevo(telemetry.medir_pasos(_interno()))
    assert all(e["hay_medicion"] for e in eventos)
    assert [e["resumen"]["llm_call_count"] for e in eventos] == [1, 2, 3]
    assert [e["resumen"]["total_tokens"] for e in eventos] == [15, 30, 45]


def test_medir_pasos_deja_la_medicion_libre_al_terminar_y_entre_pasos():
    gen = telemetry.medir_pasos(_interno())
    next(gen)
    assert telemetry._medicion.get() is None          # entre pasos no queda puesta
    list(gen)
    assert telemetry._medicion.get() is None


def test_dos_analisis_seguidos_no_comparten_medicion():
    a = _un_paso_por_contexto_nuevo(telemetry.medir_pasos(_interno(2)))
    b = _un_paso_por_contexto_nuevo(telemetry.medir_pasos(_interno(2)))
    assert a[-1]["resumen"]["llm_call_count"] == b[-1]["resumen"]["llm_call_count"] == 2


def test_una_excepcion_dentro_del_generador_se_propaga_y_no_deja_la_medicion_puesta():
    def malo():
        telemetry.iniciar_llamada("m")
        yield {"i": 0}
        raise RuntimeError("503 UNAVAILABLE")

    gen = telemetry.medir_pasos(malo())
    contextvars.copy_context().run(next, gen)
    with pytest.raises(RuntimeError, match="503"):
        contextvars.copy_context().run(next, gen)
    assert telemetry._medicion.get() is None


def test_cerrar_el_generador_antes_de_tiempo_cierra_tambien_el_interno():
    cerrado = []

    def interno():
        try:
            yield {"i": 0}
            yield {"i": 1}
        finally:
            cerrado.append(True)

    gen = telemetry.medir_pasos(interno())
    next(gen)
    gen.close()
    assert cerrado == [True]


def test_el_stream_del_pipeline_usa_medir_pasos(monkeypatch):
    monkeypatch.setattr(pipeline, "_analizar_lote_stream", lambda raw, tid=None: _interno())
    eventos = _un_paso_por_contexto_nuevo(pipeline.analizar_lote_stream("x"))
    assert [e["resumen"]["llm_call_count"] for e in eventos] == [1, 2, 3]


def test_la_interfaz_web_real_recibe_los_eventos_y_la_telemetria_completa(monkeypatch, tmp_path):
    """Por el camino real: TestClient avanza el generador en hilos con contextos distintos, como uvicorn."""
    from fastapi.testclient import TestClient

    from src.api import historial, main

    monkeypatch.setattr(historial, "RUTA_DB", tmp_path / "h.db")
    monkeypatch.setattr(main, "RAIZ_REPO", tmp_path)

    def interno(raw, tid=None):
        yield {"tipo": "inicio", "resumen": {"formato_detectado": "x", "total_lineas": 1}}
        llamada = telemetry.iniciar_llamada("m")
        telemetry.registrar_consumo(llamada, _respuesta(100, 20))
        yield {"tipo": "nodo", "nombre": "triage", "detalle": {}}
        llamada = telemetry.iniciar_llamada("m")
        telemetry.registrar_consumo(llamada, _respuesta(50, 10))
        yield {"tipo": "final", "reporte": {"hay_anomalia": True, "telemetry": telemetry.resumen_telemetria({})}}

    monkeypatch.setattr(pipeline, "_analizar_lote_stream", interno)
    cliente = TestClient(main.app)
    job = cliente.post("/api/analizar", files={"archivo": ("x.log", b"linea\n")}).json()["job_id"]
    cuerpo = cliente.get(f"/api/stream/{job}").text
    eventos = [json.loads(l[6:]) for l in cuerpo.splitlines() if l.startswith("data: ")]
    tipos = [e["tipo"] for e in eventos]
    assert "error" not in tipos and tipos[-1] == "final"          # antes: un evento de error al cerrar
    tel = eventos[-1]["reporte"]["telemetry"]
    assert tel["llm_call_count"] == 2 and tel["total_tokens"] == 180
