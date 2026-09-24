"""Tests del enganche del historial con la API (Fase A del plan).

Verifican el flujo completo subida → stream → registro, con el LLM
simulado: no se llama a Gemini ni se gasta cuota. Sigue el mismo patrón
que la verificación original de la interfaz (1-sep-2026).

El historial real (`data/historial.db`) nunca se toca: cada test
monkeypatchea `historial.RUTA_DB` a un archivo temporal.
"""

import json

import pytest
from fastapi.testclient import TestClient

import src.api.main as api
from src.api import historial
from src.preprocessing.pipeline import PreprocesamientoError

AUTH = ("Jan 10 13:55:36 srv sshd[1]: Failed password for root "
        "from 203.0.113.10 port 22 ssh2\n")


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    """Cliente de la API con el historial apuntando a una base temporal."""
    monkeypatch.setattr(historial, "RUTA_DB", tmp_path / "historial_test.db")
    return TestClient(api.app)


def _mock_stream(monkeypatch, eventos):
    """Sustituye `analizar_lote_stream` por una secuencia fija de eventos."""
    def falso(raw_logs, thread_id=None):
        yield from eventos
    monkeypatch.setattr(api, "analizar_lote_stream", falso)


EVENTOS_OK = [
    {"tipo": "inicio", "resumen": {"formato_detectado": "auth_log",
                                   "total_lineas": 1, "n_ips_distintas": 1}},
    {"tipo": "nodo", "nombre": "agente_analista_triage", "detalle": {}},
    {"tipo": "nodo", "nombre": "agente_auditor_final", "detalle": {}},
    {"tipo": "final", "reporte": {
        "diagnostico": "Fuerza bruta SSH desde una IP externa.",
        "confianza": 0.92,
        "hay_anomalia": True,
        "hay_incidente": True,
        "requiere_revision_humana": False,
        "comandos_mitigacion": ["iptables -I INPUT -s 203.0.113.10 -j DROP"],
        "evaluacion_auditor": "El diagnóstico es coherente con la evidencia.",
        "tecnicas_mitre": [{"technique_id": "T1110", "nombre": "Brute Force"}],
    }},
]

EVENTOS_ERROR = [
    {"tipo": "inicio", "resumen": {"formato_detectado": "auth_log",
                                   "total_lineas": 1}},
    {"tipo": "nodo", "nombre": "agente_analista_triage", "detalle": {}},
    {"tipo": "error", "mensaje": "503 UNAVAILABLE. El modelo está saturado."},
    {"tipo": "final", "reporte": {"diagnostico": "", "confianza": 0.0,
                                  "hay_anomalia": False, "hay_incidente": False,
                                  "requiere_revision_humana": True,
                                  "comandos_mitigacion": []}},
]


def _correr(cliente, nombre="auth.log"):
    r = cliente.post("/api/analizar",
                     files={"archivo": (nombre, AUTH.encode(), "text/plain")})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    stream = cliente.get(f"/api/stream/{job_id}")
    assert stream.status_code == 200
    stream.read()          # consumir el generador para que corra el `finally`
    return job_id


# --- registro de una corrida completa -------------------------------------

def test_una_corrida_completa_queda_registrada(cliente, monkeypatch):
    _mock_stream(monkeypatch, EVENTOS_OK)
    job_id = _correr(cliente)

    c = historial.obtener_corrida(job_id)
    assert c is not None
    assert c["estado"] == "completo"
    assert c["archivo_origen"] == "auth.log"
    assert c["formato_detectado"] == "auth_log"
    assert c["total_lineas"] == 1
    assert c["confianza"] == 0.92
    assert c["hay_anomalia"] is True
    assert c["hay_incidente"] is True
    assert c["n_comandos_mitigacion"] == 1
    assert c["tecnicas_mitre"][0]["technique_id"] == "T1110"
    assert c["error_mensaje"] is None


def test_se_registra_el_motor_de_preprocesamiento(cliente, monkeypatch):
    """Dos corridas con motores distintos no son comparables; sin este
    campo el historial no permitiría distinguirlas."""
    _mock_stream(monkeypatch, EVENTOS_OK)
    job_id = _correr(cliente)
    assert historial.obtener_corrida(job_id)["motor_preprocesamiento"] == "heterogeneo"


# --- registro de una corrida que falla ------------------------------------

def test_una_corrida_con_error_queda_registrada_como_error(cliente, monkeypatch):
    _mock_stream(monkeypatch, EVENTOS_ERROR)
    job_id = _correr(cliente)

    c = historial.obtener_corrida(job_id)
    assert c["estado"] == "error"
    assert "503 UNAVAILABLE" in c["error_mensaje"]
    assert c["confianza"] == 0.0


def test_una_excepcion_inesperada_tambien_queda_registrada(cliente, monkeypatch):
    """Si el generador revienta antes de emitir el evento final, la corrida
    igual gastó cuota y debe quedar constancia."""
    def revienta(raw_logs, thread_id=None):
        yield {"tipo": "inicio", "resumen": {"formato_detectado": "auth_log"}}
        raise RuntimeError("fallo de la agregación")
    monkeypatch.setattr(api, "analizar_lote_stream", revienta)

    job_id = _correr(cliente)
    c = historial.obtener_corrida(job_id)
    assert c["estado"] == "error"
    assert "fallo de la agregación" in c["error_mensaje"]


def test_un_fallo_de_preprocesamiento_da_un_mensaje_claro_no_generico(cliente, monkeypatch):
    """Revisión del camino productivo (cierre de auditoría, 23-sep-2026):
    `preprocesar()` falla ANTES del evento "inicio" -- el generador de
    `analizar_lote_stream` revienta en la primerísima iteración, sin haber
    emitido nada todavía. El navegador debe recibir el mensaje propio de
    `PreprocesamientoError`, no el prefijo genérico "Error inesperado del
    servidor" que se antepone a cualquier otra excepción sin clasificar.

    SSE ya comprometió la respuesta a HTTP 200 en cuanto StreamingResponse
    empezó a transmitir (no hay forma de dar un código de error distinto a
    mitad de un stream ya iniciado -- ver la nota de diseño en main.py): la
    señal de error va en el evento, y este test lo confirma en vez de
    asumirlo.
    """
    def revienta(raw_logs, thread_id=None):
        raise PreprocesamientoError("No se pudo preprocesar el lote (ValueError: boom)")
        yield  # pragma: no cover -- hace de esto un generador
    monkeypatch.setattr(api, "analizar_lote_stream", revienta)

    r = cliente.post("/api/analizar",
                     files={"archivo": ("x.log", AUTH.encode(), "text/plain")})
    stream = cliente.get(f"/api/stream/{r.json()['job_id']}")
    cuerpo = stream.read().decode("utf-8")

    assert stream.status_code == 200
    assert '"tipo": "error"' in cuerpo
    assert "No se pudo preprocesar el lote" in cuerpo
    assert "Error inesperado del servidor" not in cuerpo

    c = historial.obtener_corrida(r.json()["job_id"])
    assert c["estado"] == "error"
    assert "No se pudo preprocesar el lote" in c["error_mensaje"]


def test_un_fallo_al_guardar_no_rompe_el_stream(cliente, monkeypatch, capsys):
    """El análisis ya se entregó al navegador: un problema de escritura no
    debe convertirse en un error de cara al usuario."""
    _mock_stream(monkeypatch, EVENTOS_OK)
    def falla(*a, **k):
        raise OSError("disco lleno")
    monkeypatch.setattr(historial, "registrar_corrida", falla)

    r = cliente.post("/api/analizar",
                     files={"archivo": ("x.log", AUTH.encode(), "text/plain")})
    stream = cliente.get(f"/api/stream/{r.json()['job_id']}")
    cuerpo = stream.read().decode("utf-8")
    assert stream.status_code == 200
    assert '"tipo": "final"' in cuerpo          # el reporte igual llegó


# --- endpoints de consulta -------------------------------------------------

def test_el_listado_devuelve_la_corrida_registrada(cliente, monkeypatch):
    _mock_stream(monkeypatch, EVENTOS_OK)
    job_id = _correr(cliente)

    r = cliente.get("/api/historial")
    assert r.status_code == 200
    datos = r.json()
    assert datos["total"] == 1
    assert datos["corridas"][0]["job_id"] == job_id


def test_el_listado_ordena_de_la_mas_reciente_a_la_mas_antigua(cliente, monkeypatch):
    _mock_stream(monkeypatch, EVENTOS_OK)
    primero = _correr(cliente, "primero.log")
    historial.registrar_corrida(primero, {"timestamp": "2026-01-01T00:00:00Z",
                                          "archivo_origen": "primero.log",
                                          "estado": "completo"})
    segundo = _correr(cliente, "segundo.log")
    historial.registrar_corrida(segundo, {"timestamp": "2026-12-31T00:00:00Z",
                                          "archivo_origen": "segundo.log",
                                          "estado": "completo"})
    ids = [c["job_id"] for c in cliente.get("/api/historial").json()["corridas"]]
    assert ids[0] == segundo


def test_el_listado_respeta_limit_y_offset(cliente, monkeypatch):
    _mock_stream(monkeypatch, EVENTOS_OK)
    for i in range(4):
        _correr(cliente, f"lote{i}.log")
    r = cliente.get("/api/historial?limit=2&offset=1").json()
    assert len(r["corridas"]) == 2
    assert r["total"] == 4
    assert r["limit"] == 2 and r["offset"] == 1


def test_el_detalle_devuelve_el_mismo_shape_que_el_reporte(cliente, monkeypatch):
    """La interfaz reusa su función de render, así que los campos deben
    llamarse igual que en el evento `final`."""
    _mock_stream(monkeypatch, EVENTOS_OK)
    job_id = _correr(cliente)

    d = cliente.get(f"/api/historial/{job_id}").json()
    for campo in ("diagnostico", "confianza", "hay_anomalia", "hay_incidente",
                  "requiere_revision_humana", "evaluacion_auditor",
                  "tecnicas_mitre"):
        assert campo in d, campo


def test_el_detalle_de_una_corrida_inexistente_devuelve_404(cliente):
    r = cliente.get("/api/historial/no-existe")
    assert r.status_code == 404
    assert "no-existe" in r.json()["detail"]


def test_el_historial_vacio_no_rompe(cliente):
    r = cliente.get("/api/historial")
    assert r.status_code == 200
    assert r.json() == {"total": 0, "limit": 50, "offset": 0, "corridas": []}


# --- el pipeline no cambia -------------------------------------------------

def test_el_streaming_sigue_emitiendo_los_mismos_eventos(cliente, monkeypatch):
    """El hook es aditivo: no debe alterar lo que ve el navegador."""
    _mock_stream(monkeypatch, EVENTOS_OK)
    r = cliente.post("/api/analizar",
                     files={"archivo": ("x.log", AUTH.encode(), "text/plain")})
    cuerpo = cliente.get(f"/api/stream/{r.json()['job_id']}").read().decode("utf-8")
    tipos = [json.loads(l[6:])["tipo"] for l in cuerpo.splitlines()
             if l.startswith("data: ")]
    assert tipos == ["inicio", "nodo", "nodo", "final"]


def test_el_resumen_persistido_incluye_la_reputacion_de_las_ips(monkeypatch):
    """El informe en PDF resume la reputación observada, y el evento "inicio"
    es lo único del resumen que la capa web persiste: si `reputacion_ips` no
    viaja ahí, el campo del informe nunca se llena."""
    from src import pipeline

    estado = {
        "resumen_logs": {
            "formato_detectado": "auth_log", "total_lineas": 3,
            "n_ips_distintas": 1, "servicios": {"sshd": 3},
            "eventos": {"acceso_fallido": 3},
            "ventana_temporal": {"inicio": "a", "fin": "b"},
            "reputacion_ips": {"203.0.113.99": {"categoria": "malicioso"}},
        },
        "preprocessing_metadata": {},
        "parsing_warnings": [],
    }
    monkeypatch.setattr(pipeline, "get_app", lambda: object())
    monkeypatch.setattr(pipeline, "_preparar_estado_inicial",
                        lambda *a, **k: (estado, {}, "firma"))

    # Solo se consume el primer evento: el grafo nunca llega a ejecutarse, así
    # que el test no toca el LLM.
    generador = pipeline.analizar_lote_stream("x", thread_id="t")
    evento = next(generador)
    generador.close()

    assert evento["tipo"] == "inicio"
    assert evento["resumen"]["reputacion_ips"] == {
        "203.0.113.99": {"categoria": "malicioso"}}


def test_cors_habilitado_para_el_frontend_de_desarrollo(cliente):
    """El frontend de Next.js corre en :3000, otro origen que esta API."""
    r = cliente.get("/api/historial", headers={"Origin": "http://localhost:3000"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_expone_content_disposition(cliente):
    """El frontend lee esa cabecera para nombrar el PDF que descarga; sin
    `expose_headers` el navegador no se la entrega a JavaScript."""
    # Va en la respuesta real, no en el preflight.
    r = cliente.get("/api/historial", headers={"Origin": "http://localhost:3000"})
    assert "content-disposition" in r.headers.get("access-control-expose-headers", "").lower()


def test_un_origen_ajeno_no_recibe_cors(cliente):
    r = cliente.get("/api/historial", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers
