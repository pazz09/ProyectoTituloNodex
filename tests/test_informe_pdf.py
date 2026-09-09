"""Tests del informe en PDF (Fase B del plan de ampliación).

No se parsea el contenido del PDF: alcanza con que se genere sin excepción
y con tamaño razonable en todos los casos borde. Lo que sí se verifica en
detalle es el saneamiento de texto, porque ahí está el modo de falla real
-- los diagnósticos del LLM traen caracteres que las fuentes base de fpdf2
no pueden codificar.
"""

import pytest
from fastapi.testclient import TestClient

import src.api.main as api
from src.api import historial
from src.api.informe_pdf import generar_informe_pdf, sanear
from src.config import MITRE_ATTACK_ATTRIBUTION

CORRIDA = {
    "job_id": "abc123",
    "timestamp": "2026-09-09T05:07:50Z",
    "archivo_origen": "BGL_2k.log",
    "formato_detectado": "bgl",
    "total_lineas": 2000,
    "motor_preprocesamiento": "v1",
    "diagnostico": "Se detectaron 143 eventos críticos de kernel.",
    "confianza": 0.95,
    "hay_anomalia": True,
    "hay_incidente": False,
    "requiere_revision_humana": False,
    "n_comandos_mitigacion": 2,
    "evaluacion_auditor": "El diagnóstico es coherente con la evidencia.",
    "tecnicas_mitre": [{"technique_id": "T1110", "nombre": "Brute Force"}],
    "estado": "completo",
    "error_mensaje": None,
    "feedback_correcto": None,
    "feedback_comentario": None,
    "feedback_timestamp": None,
    "resumen_json": {
        "formato_detectado": "bgl", "total_lineas": 2000, "n_ips_distintas": 11,
        "servicios": {"bgl.kernel": 1820, "bgl.app": 107},
        "eventos": {"evento_critico": 143, "evento_normal": 1857},
        "ventana_temporal": {"inicio": "2005-06-03", "fin": "2006-01-03"},
        "reputacion_ips": {"10.0.0.1": {"categoria": "limpio"}},
    },
    "reporte_json": {
        "comandos_mitigacion": ["ipmitool sel list", "dmesg -T | grep -i error"],
        "cves_encontrados": [],
    },
}


def corrida(**cambios):
    d = dict(CORRIDA)
    d.update(cambios)
    return d


def es_pdf(b: bytes) -> bool:
    return b.startswith(b"%PDF-") and len(b) > 800


# --- saneamiento: el modo de falla real ------------------------------------

@pytest.mark.parametrize("entrada,esperado", [
    ("el diagnóstico — coherente", "el diagnóstico -- coherente"),
    ("continúa…", "continúa..."),
    ("triage → auditor", "triage -> auditor"),
    ('el “diagnóstico” es ‘correcto’', 'el "diagnóstico" es \'correcto\''),
    ("confianza ≥ 0.70", "confianza >= 0.70"),
])
def test_los_caracteres_tipograficos_se_mapean(entrada, esperado):
    """fpdf2 con fuentes base codifica en latin-1: raya, puntos suspensivos
    y comillas tipográficas lanzan FPDFUnicodeEncodingException."""
    assert sanear(entrada) == esperado


def test_los_acentos_del_espanol_se_conservan():
    """Están en latin-1: no hay razón para degradarlos."""
    texto = "anomalía operativa, configuración, año, ¿qué?, ñandú"
    assert sanear(texto) == texto


def test_un_caracter_fuera_de_todo_rango_no_rompe():
    resultado = sanear("emoji 🔥 y kanji 日本")
    resultado.encode("latin-1")     # debe ser codificable
    assert "emoji" in resultado


def test_sanear_tolera_none_y_no_cadenas():
    assert sanear(None) == ""
    assert sanear(42) == "42"


def test_un_diagnostico_con_raya_genera_el_pdf_sin_excepcion():
    """Regresión del caso real: sin saneamiento, esto reventaba."""
    pdf = generar_informe_pdf(corrida(
        diagnostico="El diagnóstico — preciso — descarta un ataque…",
        evaluacion_auditor="Correcto → sin incidente"))
    assert es_pdf(pdf)


# --- generación en los casos borde -----------------------------------------

def test_corrida_completa_genera_pdf():
    assert es_pdf(generar_informe_pdf(CORRIDA))


def test_sin_tecnicas_mitre():
    assert es_pdf(generar_informe_pdf(corrida(tecnicas_mitre=[])))


def test_sin_comandos_de_mitigacion():
    """La sección no queda vacía sin explicación: se declara que no se
    requiere mitigación."""
    c = corrida(n_comandos_mitigacion=0,
                reporte_json={"comandos_mitigacion": [], "cves_encontrados": []})
    assert es_pdf(generar_informe_pdf(c))


def test_con_feedback_humano():
    c = corrida(feedback_correcto=True, feedback_comentario="coincide con lo observado",
                feedback_timestamp="2026-09-09T06:00:00Z")
    assert es_pdf(generar_informe_pdf(c))


def test_sin_feedback_humano():
    assert es_pdf(generar_informe_pdf(corrida(feedback_correcto=None)))


def test_corrida_que_termino_en_error():
    c = corrida(estado="error", error_mensaje="503 UNAVAILABLE",
                diagnostico="", confianza=0.0, evaluacion_auditor="")
    assert es_pdf(generar_informe_pdf(c))


def test_corrida_sin_resumen_ni_reporte():
    """Una corrida vieja, anterior al registro de los blobs."""
    c = corrida(resumen_json={}, reporte_json={})
    assert es_pdf(generar_informe_pdf(c))


def test_dict_vacio_no_lanza():
    """Nunca debe fallar la descarga, por incompletos que estén los datos."""
    assert es_pdf(generar_informe_pdf({}))


def test_blobs_como_texto_json_tambien_funcionan():
    """Un archivo viejo puede devolverlos sin deserializar."""
    import json
    c = corrida(resumen_json=json.dumps(CORRIDA["resumen_json"]),
                reporte_json=json.dumps(CORRIDA["reporte_json"]))
    assert es_pdf(generar_informe_pdf(c))


def test_muchos_comandos_no_desbordan():
    c = corrida(reporte_json={"comandos_mitigacion": [f"comando-{i}" for i in range(200)]})
    assert es_pdf(generar_informe_pdf(c))


def test_un_diagnostico_muy_largo_pagina_correctamente():
    c = corrida(diagnostico="Frase de relleno. " * 400)
    pdf = generar_informe_pdf(c)
    assert es_pdf(pdf)
    assert len(pdf) > 3000      # ocupó más de una página


# --- atribución de MITRE ---------------------------------------------------

def _texto_escrito(monkeypatch, datos):
    """Captura todo el texto que el informe manda al PDF.

    No se busca dentro de los bytes del PDF porque fpdf2 comprime los
    streams de contenido: el texto no aparece literal, y una aserción del
    tipo `b"MITRE" in pdf` pasaría o fallaría por la compresión y no por lo
    que el informe realmente escribió.
    """
    from fpdf import FPDF
    capturado = []
    for metodo in ("multi_cell", "write", "cell"):
        original = getattr(FPDF, metodo)

        def espia(self, *a, _orig=original, **k):
            for arg in a:
                if isinstance(arg, str):
                    capturado.append(arg)
            if isinstance(k.get("text"), str):
                capturado.append(k["text"])
            return _orig(self, *a, **k)

        monkeypatch.setattr(FPDF, metodo, espia)
    generar_informe_pdf(datos)
    return "\n".join(capturado)


def test_la_atribucion_de_mitre_esta_si_hay_tecnicas(monkeypatch):
    """Requisito del propio MITRE cuando se reproducen sus datos."""
    texto = _texto_escrito(monkeypatch, CORRIDA)
    assert "MITRE Corporation" in texto
    assert "T1110" in texto


def test_sin_tecnicas_no_se_menciona_la_atribucion(monkeypatch):
    """Si no se muestran datos de ATT&CK, la nota no corresponde."""
    texto = _texto_escrito(monkeypatch,
                           corrida(tecnicas_mitre=[], reporte_json={}))
    assert "MITRE Corporation" not in texto


def test_las_siete_secciones_aparecen(monkeypatch):
    texto = _texto_escrito(monkeypatch, CORRIDA)
    for seccion in ("Informe de Análisis de Incidente", "Resumen ejecutivo",
                    "Evidencia observada", "Contexto y técnicas relacionadas",
                    "Evaluación del auditor", "Mitigación propuesta"):
        assert sanear(seccion) in texto, seccion


def test_sin_comandos_la_seccion_lo_explica(monkeypatch):
    """No se deja un hueco silencioso: se lee como un fallo del sistema."""
    texto = _texto_escrito(monkeypatch, corrida(
        n_comandos_mitigacion=0,
        reporte_json={"comandos_mitigacion": [], "cves_encontrados": []}))
    assert "No se requiere mitigación" in texto


def test_los_comandos_aparecen_en_el_informe(monkeypatch):
    texto = _texto_escrito(monkeypatch, CORRIDA)
    assert "ipmitool sel list" in texto
    assert "NODEX no los ejecuta" in texto


def test_la_atribucion_configurada_es_la_que_se_usa():
    assert "MITRE Corporation" in MITRE_ATTACK_ATTRIBUTION


# --- endpoint --------------------------------------------------------------

@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(historial, "RUTA_DB", tmp_path / "h.db")
    return TestClient(api.app)


def test_el_endpoint_devuelve_un_pdf_descargable(cliente):
    historial.registrar_corrida("abc123", CORRIDA)
    r = cliente.get("/api/historial/abc123/pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert "attachment" in r.headers["content-disposition"]
    assert "informe_abc123.pdf" in r.headers["content-disposition"]
    assert es_pdf(r.content)


def test_el_endpoint_devuelve_404_si_la_corrida_no_existe(cliente):
    r = cliente.get("/api/historial/no-existe/pdf")
    assert r.status_code == 404


def test_el_endpoint_no_vuelve_a_correr_el_grafo(cliente, monkeypatch):
    """Descargar el informe no debe costar cuota de LLM."""
    def no_llamar(*a, **k):
        raise AssertionError("el endpoint de PDF no debe correr el pipeline")
    monkeypatch.setattr(api, "analizar_lote_stream", no_llamar)
    historial.registrar_corrida("abc123", CORRIDA)
    assert cliente.get("/api/historial/abc123/pdf").status_code == 200


def test_las_secciones_se_numeran_sin_saltos(monkeypatch):
    """Las secciones opcionales se omiten según los datos; con números fijos
    el informe saltaba de "2." a "4." y se leía como una página faltante."""
    import re
    texto = _texto_escrito(monkeypatch, corrida(tecnicas_mitre=[], reporte_json={}))
    numeros = [int(m) for m in re.findall(r"^(\d+)\. ", texto, re.M)]
    assert numeros == list(range(1, len(numeros) + 1)), numeros


def test_el_feedback_humano_ocupa_la_ultima_seccion(monkeypatch):
    import re
    texto = _texto_escrito(monkeypatch, corrida(
        feedback_correcto=True, feedback_comentario="coincide"))
    numeros = [int(m) for m in re.findall(r"^(\d+)\. ", texto, re.M)]
    assert numeros == list(range(1, len(numeros) + 1)), numeros
    assert re.search(r"^%d\. Revisión humana" % numeros[-1], texto, re.M)
