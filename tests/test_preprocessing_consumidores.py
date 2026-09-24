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


# --- M2 (Fase 4 del cierre de auditoría, 23-sep-2026): versión conectada
# a la búsqueda -----------------------------------------------------------

def test_la_version_dominante_se_agrega_al_termino_de_busqueda():
    keyword = elegir_keyword(
        {"servicios": {}},
        {"product_distribution": {"FortiGate": 5}, "version_distribution": {"7.0": 5}},
    )
    assert keyword == "FortiGate 7.0"


def test_sin_version_distribution_el_termino_no_cambia():
    """La mayoría de los lotes no declaran versión (solo CEF/LEEF la
    pueblan hoy) -- no debe romperse ni inventar nada."""
    keyword = elegir_keyword(
        {"servicios": {}},
        {"product_distribution": {"HDFS": 5}},
    )
    assert keyword == "HDFS"


def test_la_version_no_se_agrega_al_termino_por_servicio():
    """Un servicio ("sshd") no tiene una versión de producto asociada de
    forma confiable -- solo se conecta la versión cuando el término viene
    de producto/fabricante."""
    keyword = elegir_keyword(
        {"servicios": {"sshd": 3}},
        {"version_distribution": {"9.2": 3}},
    )
    assert keyword == "sshd"


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


def test_el_contexto_informa_severidad_categorias_y_perfiles():
    """Fase 2 del cierre de auditoría (23-sep-2026): antes solo se
    informaban decoders y productos -- severidad, categorías y perfiles de
    enriquecimiento quedaban fuera aunque `agregar_v2` ya los calculaba."""
    texto = contexto_preprocesamiento({
        "total_eventos": 10, "total_lineas_fisicas": 10,
        "decoder_distribution": {"text": 10},
        "profile_distribution": {"bgl": 10},
        "severity_distribution": {"FATAL": 2, "INFO": 8},
        "event_categories": {"hardware": 10},
        "parsing": {"coverage": 1.0, "parsed_events": 10, "fallback_events": 0},
    })
    assert "bgl (10)" in texto
    assert "FATAL=2" in texto
    assert "hardware=10" in texto


def test_el_contexto_solo_lee_la_allowlist_ignora_lo_demas():
    """Aunque `metadatos` traiga colgando un campo fuera de la allowlist
    (cronología, entidades, o directamente una etiqueta de verdad-terreno),
    `contexto_preprocesamiento` no lo referencia -- no hay forma de que
    aparezca en el texto porque ninguna línea de la función lo lee."""
    texto = contexto_preprocesamiento({
        "total_eventos": 1, "total_lineas_fisicas": 1,
        "decoder_distribution": {"text": 1},
        "parsing": {"coverage": 1.0, "parsed_events": 1, "fallback_events": 0},
        # campos fuera de la allowlist, deliberadamente sospechosos:
        "cronologia": [{"mensaje": "SECRETO_DE_CRONOLOGIA"}],
        "etiqueta_real_del_dataset": "ANOMALIA_CRITICA_XYZ",
        "entities": {"ip": {"198.51.100.7": 1}},
    })
    assert "SECRETO_DE_CRONOLOGIA" not in texto
    assert "ANOMALIA_CRITICA_XYZ" not in texto
    assert "198.51.100.7" not in texto


def test_el_recorte_quita_primero_las_muestras_y_las_listas(monkeypatch):
    """Prioridad de recorte (confirmada por Antonia, cierre de auditoría):
    con presupuesto insuficiente para todo, lo primero que se quita son las
    muestras y las distribuciones -- los conteos globales, la cobertura y
    las advertencias NUNCA se recortan."""
    import src.config as cfg
    # El núcleo (eventos + cobertura + advertencia) de este escenario mide
    # ~410 caracteres: el presupuesto queda por encima para que el núcleo
    # entre siempre entero, y por debajo del total con todos los bloques
    # (~1120) para forzar que se descarte al menos alguno.
    monkeypatch.setattr(cfg, "CONTEXTO_PREPROCESAMIENTO_MAX_CHARS", 500)
    metadatos = {
        "total_eventos": 500, "total_lineas_fisicas": 500,
        "decoder_distribution": {"text": 300, "json": 150, "syslog": 50},
        "product_distribution": {"HDFS": 300, "OpenSSH": 200},
        "profile_distribution": {"hdfs": 300, "auth": 200},
        "severity_distribution": {"FATAL": 3, "ERROR": 47, "WARN": 100, "INFO": 350},
        "event_categories": {"hardware": 300, "authentication": 200},
        "segments": [{"index": i} for i in range(30)],
        "parsing": {"coverage": 0.30, "parsed_events": 150, "fallback_events": 350},
    }
    advertencias = [{"severidad": "error", "mensaje": "se alcanzó el límite de eventos"}]
    muestras = [{"decoder": "text", "texto": "x" * 2000}]

    texto = contexto_preprocesamiento(metadatos, advertencias, muestras, incluir_muestras=True)

    # núcleo protegido: siempre presente, pase lo que pase con el presupuesto
    assert "500 eventos lógicos" in texto
    assert "Cobertura del parsing: 30%" in texto
    assert "ATENCIÓN" in texto          # cobertura baja (< COBERTURA_BAJA)
    assert "límite de eventos" in texto  # advertencia grave

    # lo primero que se sacrifica: las muestras (2000 caracteres) no caben
    # en un presupuesto de 250 junto con el núcleo, y no aparecen
    assert "x" * 50 not in texto
    assert "[…se omitieron algunos detalles" in texto


def test_el_recorte_ciego_solo_ocurre_si_el_nucleo_por_si_solo_ya_excede(monkeypatch):
    """Caso extremo: ni sacando todos los bloques recortables alcanza. Ahí
    sí se recorta el núcleo, como último recurso -- no antes."""
    import src.config as cfg
    monkeypatch.setattr(cfg, "CONTEXTO_PREPROCESAMIENTO_MAX_CHARS", 40)
    texto = contexto_preprocesamiento({
        "total_eventos": 1, "total_lineas_fisicas": 1,
        "decoder_distribution": {"text": 1},
        "parsing": {"coverage": 1.0, "parsed_events": 1, "fallback_events": 0},
    })
    assert texto.endswith("[…contexto recortado por presupuesto de caracteres]")


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
