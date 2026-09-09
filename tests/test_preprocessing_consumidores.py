"""Tests de la adaptación de consumidores (Fases 10, 11 y 12 del plan).

Criterios de aceptación de la Fase 10:
1. No se usa `ssh` como fallback artificial para CVE.
2. Un lote sin IP o servicio conocido puede diagnosticarse.
3. El prompt permanece dentro de límites medidos.
4. La incertidumbre del parsing aparece en el razonamiento del agente.

Fase 11: firma y resultados versionados.
Fase 12: la API valida tamaño, contenido binario y encoding.
"""

import pytest

from src.preprocessing.prompt_context import contexto_preprocesamiento
from src.tools.tool_consultar_cve import elegir_keyword


# --- Fase 10, criterio 1: sin fallback artificial a "ssh" -----------------

def test_un_lote_sin_servicios_no_consulta_la_nvd_por_ssh():
    """Antes se consultaba `"ssh"` sin razón y devolvía CVEs de OpenSSH
    para logs que no tenían nada que ver. Un resultado inventado es peor
    que ninguno."""
    assert elegir_keyword({"servicios": {}}, {}) is None
    assert elegir_keyword({"servicios": {"desconocido": 10}}, {}) is None


def test_los_nombres_internos_de_componentes_no_se_buscan():
    """`hdfs.datanode` y `bgl.kernel` no son software que la NVD indexe:
    consultarlos gasta una llamada para devolver cero resultados."""
    assert elegir_keyword({"servicios": {"hdfs.datanode": 5}}, {}) is None
    assert elegir_keyword({"servicios": {"bgl.kernel": 5}}, {}) is None


def test_se_prefiere_el_producto_sobre_el_servicio():
    """La NVD indexa por producto y proveedor."""
    keyword = elegir_keyword(
        {"servicios": {"hdfs.datanode": 5}},
        {"product_distribution": {"HDFS": 5}},
    )
    assert keyword == "HDFS"


def test_un_servicio_buscable_se_usa_si_no_hay_producto():
    assert elegir_keyword({"servicios": {"sshd": 3}}, {}) == "sshd"


def test_el_nodo_cve_no_llama_a_la_nvd_sin_termino(monkeypatch):
    import src.tools.tool_consultar_cve as mod
    llamadas = []
    monkeypatch.setattr(mod, "query_cve",
                        lambda k: llamadas.append(k) or {"cves": []})
    salida = mod.tool_consultar_cve({"resumen_logs": {"servicios": {}},
                                     "preprocessing_metadata": {}})
    assert llamadas == []
    assert salida == {"cves_encontrados": []}


# --- Fase 10, criterio 4: la incertidumbre llega al agente ----------------

def test_el_contexto_avisa_cuando_la_cobertura_es_baja():
    """Un agente que lee '0.28' puede no dimensionar lo que significa."""
    texto = contexto_preprocesamiento({
        "total_eventos": 100, "total_lineas_fisicas": 100,
        "decoder_distribution": {"text": 72, "json": 28},
        "parsing": {"coverage": 0.28, "parsed_events": 28, "fallback_events": 72},
    })
    assert "28%" in texto
    assert "ATENCIÓN" in texto
    assert "nivel de confianza" in texto


def test_una_cobertura_alta_no_dispara_la_advertencia():
    texto = contexto_preprocesamiento({
        "total_eventos": 100, "total_lineas_fisicas": 100,
        "decoder_distribution": {"json": 100},
        "parsing": {"coverage": 1.0, "parsed_events": 100, "fallback_events": 0},
    })
    assert "ATENCIÓN" not in texto
    assert "100%" in texto


def test_el_contexto_declara_un_lote_heterogeneo():
    texto = contexto_preprocesamiento({
        "total_eventos": 10, "total_lineas_fisicas": 10,
        "decoder_distribution": {"syslog": 6, "json": 4},
        "segments": [{"index": 0}, {"index": 1}],
        "parsing": {"coverage": 1.0, "parsed_events": 10, "fallback_events": 0},
    })
    assert "HETEROGÉNEO" in texto
    assert "2 segmentos" in texto


def test_sin_metadatos_el_contexto_es_vacio():
    """Con el motor v1 no hay nada que informar, y fabricarlo sería peor."""
    assert contexto_preprocesamiento({}) == ""
    assert contexto_preprocesamiento(None) == ""


def test_las_advertencias_graves_llegan_al_agente():
    texto = contexto_preprocesamiento(
        {"total_eventos": 1, "total_lineas_fisicas": 1,
         "decoder_distribution": {"json": 1},
         "parsing": {"coverage": 1.0, "parsed_events": 1, "fallback_events": 0}},
        [{"severidad": "error", "mensaje": "se alcanzó el límite de eventos"},
         {"severidad": "info", "mensaje": "cabecera CSV detectada"}],
    )
    assert "límite de eventos" in texto
    assert "cabecera CSV" not in texto      # las informativas no ensucian


# --- Fase 10, criterio 3: el prompt sigue acotado -------------------------

def test_el_contexto_de_preprocesamiento_es_corto():
    """No debe competir en tamaño con el resumen del lote."""
    texto = contexto_preprocesamiento({
        "total_eventos": 2000, "total_lineas_fisicas": 2000,
        "decoder_distribution": {"text": 1000, "json": 1000},
        "product_distribution": {"HDFS": 2000},
        "segments": [{"index": i} for i in range(40)],
        "parsing": {"coverage": 0.5, "parsed_events": 1000, "fallback_events": 1000},
    })
    assert len(texto) < 1200        # ~300 tokens como mucho


def test_las_muestras_se_recortan():
    texto = contexto_preprocesamiento(
        {"total_eventos": 1, "total_lineas_fisicas": 1,
         "decoder_distribution": {"text": 1},
         "parsing": {"coverage": 0.0, "parsed_events": 0, "fallback_events": 1}},
        muestras=[{"decoder": "text", "texto": "x" * 5000}],
        incluir_muestras=True,
    )
    assert len(texto) < 1500


# --- Fase 11: firma y resultados versionados ------------------------------

def test_las_firmas_de_distinta_version_no_se_confunden():
    from src.tools.aggregation import firma_lote
    resumen = {"total_lineas": 1, "n_ips_distintas": 1,
               "servicios": {"sshd": 1}, "eventos": {"acceso_fallido": 1}}
    v1 = firma_lote(resumen)
    v2 = firma_lote(resumen, {"total_eventos": 1,
                              "decoder_distribution": {"syslog": 1},
                              "parsing": {"coverage": 1.0}})
    assert v1.startswith("v1|") and v2.startswith("v2|")
    assert v1 != v2


# --- Fase 12: validaciones de ingesta de la API ---------------------------

def test_la_api_rechaza_un_archivo_binario():
    from fastapi.testclient import TestClient
    from src.api.main import app
    cliente = TestClient(app)
    r = cliente.post("/api/analizar",
                     files={"archivo": ("x.log", b"texto\x00binario", "text/plain")})
    assert r.status_code == 415
    assert "binario" in r.json()["detail"]


def test_la_api_rechaza_un_archivo_demasiado_grande(monkeypatch):
    from fastapi.testclient import TestClient
    import src.config as cfg
    monkeypatch.setattr(cfg, "LOG_MAX_FILE_BYTES", 100)
    from src.api.main import app
    cliente = TestClient(app)
    r = cliente.post("/api/analizar",
                     files={"archivo": ("x.log", b"a" * 500, "text/plain")})
    assert r.status_code == 413
    assert "límite" in r.json()["detail"]


def test_la_api_sigue_rechazando_un_archivo_vacio():
    from fastapi.testclient import TestClient
    from src.api.main import app
    cliente = TestClient(app)
    r = cliente.post("/api/analizar",
                     files={"archivo": ("x.log", b"   \n", "text/plain")})
    assert r.status_code == 400


def test_un_archivo_de_texto_normal_se_acepta():
    from fastapi.testclient import TestClient
    from src.api.main import app
    cliente = TestClient(app)
    contenido = b"Jan 10 13:55:36 srv sshd[1]: Failed password for root from 1.2.3.4 port 22 ssh2\n"
    r = cliente.post("/api/analizar",
                     files={"archivo": ("x.log", contenido, "text/plain")})
    assert r.status_code == 200
    assert "job_id" in r.json()
