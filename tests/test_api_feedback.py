"""Tests del endpoint de feedback humano (Fase C).

`commit_feedback` va siempre mockeado: lo que se verifica acá es el
contrato de la capa web -- con qué argumentos se llama, qué se guarda en la
tabla y qué se responde. El comportamiento de `commit_feedback` contra
ChromaDB se verificó aparte, con un stub que persiste en memoria de
proceso (ver README, "Feedback humano conectado a la memoria").
"""

import pytest
from fastapi.testclient import TestClient

import src.api.main as api
from src.api import historial

CORRIDA = {
    "job_id": "fb001",
    "timestamp": "2026-09-09T18:00:00Z",
    "archivo_origen": "auth_muestra.log",
    "formato_detectado": "auth_log",
    "total_lineas": 23,
    "motor_preprocesamiento": "v1",
    "diagnostico": "Fuerza bruta SSH desde 45.155.205.233.",
    "confianza": 0.95,
    "hay_anomalia": True,
    "hay_incidente": True,
    "requiere_revision_humana": False,
    "n_comandos_mitigacion": 3,
    "evaluacion_auditor": "Coherente.",
    "tecnicas_mitre": [],
    "estado": "completo",
    "reporte_json": {"firma": "v1|lineas=23 ips=3 servicios=[sshd:18]"},
}

RESPUESTA_MEMORIA = {
    "guardado_en": "host_history",
    "promovido_a_attack_patterns": True,
    "error_registrado": False,
}


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(historial, "RUTA_DB", tmp_path / "h.db")
    return TestClient(api.app)


@pytest.fixture
def llamadas(monkeypatch):
    """Captura las llamadas a `commit_feedback` sin tocar ChromaDB."""
    registro = []

    def falso(estado, host="desconocido", correccion=None):
        registro.append({"estado": estado, "host": host, "correccion": correccion})
        return dict(RESPUESTA_MEMORIA)

    monkeypatch.setattr(api, "commit_feedback", falso)
    return registro


def crear(**cambios):
    datos = dict(CORRIDA)
    datos.update(cambios)
    historial.registrar_corrida(datos["job_id"], datos)
    return datos["job_id"]


# --- persistencia en la tabla ----------------------------------------------

def test_el_veredicto_positivo_queda_en_la_tabla(cliente, llamadas):
    crear()
    r = cliente.post("/api/feedback/fb001",
                     json={"correcto": True, "comentario": "coincide con lo observado"})
    assert r.status_code == 200
    guardada = historial.obtener_corrida("fb001")
    assert guardada["feedback_correcto"] is True
    assert guardada["feedback_comentario"] == "coincide con lo observado"
    assert guardada["feedback_timestamp"]


def test_el_veredicto_negativo_queda_en_la_tabla(cliente, llamadas):
    crear()
    cliente.post("/api/feedback/fb001", json={"correcto": False, "comentario": None})
    guardada = historial.obtener_corrida("fb001")
    assert guardada["feedback_correcto"] is False
    assert guardada["feedback_comentario"] is None


def test_se_puede_corregir_un_veredicto_previo(cliente, llamadas):
    crear()
    cliente.post("/api/feedback/fb001", json={"correcto": True})
    cliente.post("/api/feedback/fb001", json={"correcto": False, "comentario": "me equivoqué"})
    guardada = historial.obtener_corrida("fb001")
    assert guardada["feedback_correcto"] is False
    assert guardada["feedback_comentario"] == "me equivoqué"
    assert len(llamadas) == 2


def test_el_comentario_es_opcional(cliente, llamadas):
    crear()
    assert cliente.post("/api/feedback/fb001", json={"correcto": True}).status_code == 200


# --- argumentos con los que se llama a commit_feedback ---------------------

def test_el_feedback_positivo_no_manda_correccion(cliente, llamadas):
    """Sin `correccion`, `commit_feedback` solo commitea el resultado
    validado -- y promueve si la confianza supera AUTO_PROMOTE."""
    crear()
    cliente.post("/api/feedback/fb001", json={"correcto": True})
    assert len(llamadas) == 1
    assert llamadas[0]["correccion"] is None
    assert llamadas[0]["host"] == "web"


def test_el_estado_lleva_la_firma_bajo_la_clave_que_espera_commit_feedback(cliente, llamadas):
    """`commit_feedback` lee la firma de `_firma` (con guion bajo), no de
    `firma`: el historial la guarda dentro del reporte."""
    crear()
    cliente.post("/api/feedback/fb001", json={"correcto": True})
    estado = llamadas[0]["estado"]
    assert estado["_firma"] == CORRIDA["reporte_json"]["firma"]
    assert estado["diagnostico"] == CORRIDA["diagnostico"]
    assert estado["confianza"] == CORRIDA["confianza"]


def test_el_feedback_negativo_fuerza_confianza_cero(cliente, llamadas):
    """Regresión del problema encontrado en C.1: `commit_feedback` mergea
    `correccion` sobre el reporte antes de commitear, y `commit_validated`
    promueve a `attack_patterns` por confianza. Sin este 0.0, marcar un
    diagnóstico como INCORRECTO lo dejaba igual como ejemplar few-shot del
    Triage (verificado con stub: attack_patterns pasaba de 1 a 2)."""
    crear()
    cliente.post("/api/feedback/fb001",
                 json={"correcto": False, "comentario": "era un pentest interno"})
    correccion = llamadas[0]["correccion"]
    assert correccion["confianza"] == 0.0
    assert correccion["veredicto_humano"] == "incorrecto"
    assert correccion["comentario"] == "era un pentest interno"


def test_el_merge_de_correccion_realmente_evita_la_promocion():
    """La defensa de arriba depende de que `commit_feedback` aplique
    `{**reporte, **correccion}` ANTES de `commit_validated`. Se fija acá
    para que un cambio en esa función no rompa la garantía en silencio."""
    from src import pipeline
    from src.config import AUTO_PROMOTE

    vistos = {}

    class LtmFalsa:
        def record_error(self, firma, erroneo, correccion):
            vistos["error"] = (firma, correccion)

        def commit_validated(self, firma, report, host="desconocido"):
            vistos["confianza_commiteada"] = report.get("confianza")
            return float(report.get("confianza") or 0) >= AUTO_PROMOTE

    original = pipeline.ltm
    pipeline.ltm = LtmFalsa()
    try:
        r = pipeline.commit_feedback(
            {"_firma": "f", "diagnostico": "d", "confianza": 1.0},
            host="web",
            correccion={"veredicto_humano": "incorrecto", "confianza": 0.0})
    finally:
        pipeline.ltm = original

    assert vistos["confianza_commiteada"] == 0.0
    assert r["promovido_a_attack_patterns"] is False
    assert r["error_registrado"] is True


# --- corridas sin firma ----------------------------------------------------

def test_una_corrida_sin_firma_guarda_pero_no_toca_la_memoria(cliente, llamadas):
    """Las corridas anteriores al registro del reporte completo no
    conservan la firma. Sin ella el documento que iría a ChromaDB sería la
    cadena vacía, así que no se escribe -- pero el veredicto no se pierde."""
    crear(job_id="viejo", reporte_json={})
    r = cliente.post("/api/feedback/viejo", json={"correcto": True})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["guardado"] is True
    assert cuerpo["memoria"] is None
    assert "firma" in cuerpo["detalle"]
    assert llamadas == []
    assert historial.obtener_corrida("viejo")["feedback_correcto"] is True


# --- errores ---------------------------------------------------------------

def test_una_corrida_inexistente_da_404(cliente, llamadas):
    assert cliente.post("/api/feedback/no-existe", json={"correcto": True}).status_code == 404
    assert llamadas == []


def test_un_cuerpo_invalido_da_422(cliente, llamadas):
    crear()
    assert cliente.post("/api/feedback/fb001", json={}).status_code == 422
    assert cliente.post("/api/feedback/fb001", json={"correcto": "quizás"}).status_code == 422


def test_si_falla_chromadb_el_veredicto_igual_queda_guardado(cliente, monkeypatch):
    """Un fallo de la memoria de largo plazo no debe hacer perder el
    veredicto humano ni devolver un 500 que sugiera que no se guardó."""
    def explota(*a, **k):
        raise RuntimeError("chroma caído")

    monkeypatch.setattr(api, "commit_feedback", explota)
    crear()
    r = cliente.post("/api/feedback/fb001", json={"correcto": True})
    assert r.status_code == 200
    assert r.json()["memoria"] is None
    assert "chroma caído" in r.json()["detalle"]
    assert historial.obtener_corrida("fb001")["feedback_correcto"] is True


def test_la_respuesta_informa_que_paso_con_la_memoria(cliente, llamadas):
    crear()
    cuerpo = cliente.post("/api/feedback/fb001", json={"correcto": True}).json()
    assert cuerpo["memoria"] == RESPUESTA_MEMORIA
