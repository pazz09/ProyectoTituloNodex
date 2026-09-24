"""Fase 3 del cierre de auditoría (23-sep-2026, hallazgo A3):
`LOG_PRESERVE_RAW` pasa de estar declarada-pero-sin-efecto a controlar de
verdad la persistencia (`data/historial.db`) y la exportación (PDF) del
raw. **No controla lo que se envía al LLM** -- las muestras del prompt del
Triage no pasan por acá, con `true` o con `false` (ver el comentario junto
a la declaración en `src/config.py`); eso queda fuera del alcance de este
cierre, documentado a propósito, no descubierto por accidente.
"""

import hashlib

import pytest
from fastapi.testclient import TestClient

import src.agents.agente_analista_triage as triage_mod
import src.agents.agente_auditor_final as auditor_mod
import src.agents.agente_ingeniero_mitigacion as mitigacion_mod
import src.agents.agente_planificador as planificador_mod
import src.agents.agente_selector_herramientas as selector_mod
import src.api.main as api
import src.config as cfg
from src.api import historial
from src.api.informe_pdf import generar_informe_pdf
from src.preprocessing.aggregation import _redactar_mensaje
from src.preprocessing.models import NormalizedEvent
from src.tools.aggregation import aggregate_logs, preprocesar_lote

AUTH = ("Jan 10 13:55:36 srv sshd[1]: Failed password for invalid user admin "
       "from 203.0.113.10 port 22 ssh2")


# --- unidad: _cronologia_v2 / derivar_v1 -----------------------------------

def test_con_preserve_raw_true_la_cronologia_trae_texto_crudo(monkeypatch):
    monkeypatch.setattr(cfg, "LOG_PRESERVE_RAW", True)
    resumen = aggregate_logs(AUTH + "\n")
    entrada = resumen["cronologia"][0]
    assert "203.0.113.10" in entrada["mensaje"]
    assert entrada["ip"] == "203.0.113.10"


def test_con_preserve_raw_false_la_cronologia_redacta_ip_y_usuario(monkeypatch):
    monkeypatch.setattr(cfg, "LOG_PRESERVE_RAW", False)
    resumen = aggregate_logs(AUTH + "\n")
    entrada = resumen["cronologia"][0]
    assert "203.0.113.10" not in entrada["mensaje"]
    assert "admin" not in entrada["mensaje"]
    assert "[IP-REDACTADA]" in entrada["mensaje"]
    assert entrada["ip"] == "[IP-REDACTADA]"
    assert entrada["usuario"] == "[USUARIO-REDACTADO]"


def test_redactar_mensaje_enmascara_host():
    """El host se enmascara por sustitución del valor que el propio
    preprocesamiento ya extrajo -- probado directo, sin depender de que
    algún decoder real puebla `source_host` para AUTH."""
    evento = NormalizedEvent(
        raw="conexión desde malo.interno.local rechazada",
        message="conexión desde malo.interno.local rechazada",
        source_host="malo.interno.local",
    )
    texto = _redactar_mensaje(evento.message, evento)
    assert "malo.interno.local" not in texto
    assert "[HOST-REDACTADO]" in texto


def test_raw_procedencia_hash_lineas_bytes():
    raw = AUTH + "\n" + AUTH + "\n"
    resumen = aggregate_logs(raw)
    proc = resumen["raw_procedencia"]
    assert proc["sha256"] == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert proc["lineas"] == 2
    assert proc["bytes"] == len(raw.encode("utf-8"))


def test_raw_procedencia_tambien_en_preprocesar_lote():
    _resultado, _v2, resumen = preprocesar_lote(AUTH + "\n")
    assert "sha256" in resumen["raw_procedencia"]


# --- integración: persistencia, exportación y forma de la respuesta -------
#
# Corre el flujo real (subida -> stream -> historial), con el LLM simulado
# (mismo patrón que tests/test_pipeline_plan.py) para que el preprocesamiento
# -- lo que de verdad cambia con LOG_PRESERVE_RAW -- sea real, no mockeado.

def _fake_llm(user_content, system=None, retries=1):
    system = system or ""
    if "planificador" in system:
        return {
            "objetivo": "Determinar si hay un ataque de fuerza bruta SSH.",
            "pasos": [{"id": 1, "accion": "triage", "objetivo": "diagnosticar", "estado": "pendiente"}],
            "criterios_finalizacion": ["diagnóstico con evidencia suficiente"],
        }
    if "decide si puedes diagnosticar directamente" in system:
        return {"necesita_rag": False, "diagnostico": "fuerza bruta SSH contra el usuario admin",
                "razon": "evidencia suficiente en el resumen"}
    if "coordinador de análisis de seguridad" in system:
        return {"usar_cve": False, "razon": "no se identifica un producto buscable"}
    if "ingeniero de sistemas Linux" in system:
        return {"comandos": ["iptables -I INPUT -s 203.0.113.10 -j DROP"]}
    if "Evalúa la solución de seguridad" in system:
        return {"confianza": 0.9, "hay_anomalia": True, "hay_incidente": True,
                "evaluacion": "Fuerza bruta SSH confirmada.", "cobertura_auditor": True}
    raise AssertionError(f"system prompt inesperado: {system[:80]!r}")


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(historial, "RUTA_DB", tmp_path / "historial_test.db")
    for mod in (planificador_mod, triage_mod, selector_mod, mitigacion_mod, auditor_mod):
        monkeypatch.setattr(mod, "llm_json", _fake_llm)
    return TestClient(api.app)


def _correr(cliente, nombre="auth.log"):
    r = cliente.post("/api/analizar",
                     files={"archivo": (nombre, (AUTH + "\n").encode(), "text/plain")})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    stream = cliente.get(f"/api/stream/{job_id}")
    assert stream.status_code == 200
    stream.read()
    return job_id


def test_con_preserve_raw_false_el_historial_no_guarda_la_ip_cruda(cliente, monkeypatch):
    """Alcance: LOG_PRESERVE_RAW redacta la CRONOLOGÍA (texto/campos
    derivados del mensaje crudo). No toca `reputacion_ips`, `ips_distintas`
    ni `por_ip` -- son hallazgos agregados del sistema (qué IPs vio, cuál
    es su reputación), no una reproducción del log crudo, y seguir
    mostrándolos con `false` es el comportamiento correcto, no una fuga."""
    monkeypatch.setattr(cfg, "LOG_PRESERVE_RAW", False)
    job_id = _correr(cliente)

    c = historial.obtener_corrida(job_id)
    cronologia = c["resumen_json"]["cronologia"]
    assert cronologia  # el lote sí generó una entrada crítica
    crudo_cronologia = str(cronologia)
    assert "203.0.113.10" not in crudo_cronologia
    assert "admin" not in crudo_cronologia
    assert c["resumen_json"]["raw_procedencia"]["sha256"]

    # la reputación de IPs SÍ sigue mostrando la IP -- es agregado, no raw.
    assert "203.0.113.10" in c["resumen_json"]["reputacion_ips"]


def test_con_preserve_raw_true_el_historial_si_guarda_la_ip(cliente, monkeypatch):
    monkeypatch.setattr(cfg, "LOG_PRESERVE_RAW", True)
    job_id = _correr(cliente)

    c = historial.obtener_corrida(job_id)
    assert "203.0.113.10" in str(c["resumen_json"])


def test_el_pdf_se_arma_solo_desde_lo_ya_persistido(cliente, monkeypatch):
    """Exportación: `generar_informe_pdf()` no vuelve a tocar el raw ni el
    preprocesamiento -- solo lee `corrida["resumen_json"]`/`["reporte_json"]`
    (ver informe_pdf.py). Si esos ya llegaron redactados (probado arriba,
    en la persistencia), el PDF sale redactado sin lógica propia que
    también haya que auditar.

    No se busca el string de la IP en los bytes del PDF: fpdf2 comprime el
    contenido (FlateDecode) y no venía ninguna librería de lectura de PDF
    en el entorno -- se comprobó que ni siquiera "auth.log" (el nombre de
    archivo, sin duda renderizado) aparece como substring literal. Una
    búsqueda así daría un falso "no está" sin importar si de verdad se
    redactó o no."""
    monkeypatch.setattr(cfg, "LOG_PRESERVE_RAW", False)
    job_id = _correr(cliente)

    c = historial.obtener_corrida(job_id)
    assert "203.0.113.10" not in str(c["resumen_json"]["cronologia"])  # la fuente ya viene redactada
    pdf_bytes = generar_informe_pdf(c)  # no debe fallar ni tocar nada fuera de `c`
    assert pdf_bytes[:4] == b"%PDF"


def test_la_respuesta_del_historial_conserva_su_forma_sin_raw(cliente, monkeypatch):
    """La interfaz espera el mismo shape tenga o no raw: `mensaje` sigue
    siendo un string no vacío, y las claves de la corrida no cambian."""
    monkeypatch.setattr(cfg, "LOG_PRESERVE_RAW", False)
    job_id = _correr(cliente)

    r = cliente.get(f"/api/historial/{job_id}")
    assert r.status_code == 200
    cuerpo = r.json()
    for clave in ("job_id", "diagnostico", "confianza", "resumen_json", "reporte_json"):
        assert clave in cuerpo
    entrada = cuerpo["resumen_json"]["cronologia"][0]
    assert isinstance(entrada["mensaje"], str) and entrada["mensaje"]
