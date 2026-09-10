"""Elementos del reporte estructurado que exige el §8.7.1 del informe.

Cubre lo que se agregó el 10-sep-2026 para cerrar el alcance: códigos de
respuesta, usuarios/entidades involucradas, la secuencia temporal de los
registros relevantes y los precedentes del RAG como evidencia utilizada.

El test que importa más es el de no-fuga: la cronología reproduce texto del
registro, y en BGL la etiqueta de anomalía del dataset es el primer token de
la línea. Si eso entra al resumen, se reabre la fuga que cerró la Fase 7 del
plan de preprocesamiento y las métricas de detección vuelven a ser
circulares.
"""

from pathlib import Path

import pytest

from src.config import CRONOLOGIA_MAX_EVENTOS
from src.tools.aggregation import aggregate_logs, aggregate_logs_v1, parse_log
from src.tools.resumen_prompt import acotar_resumen_para_prompt

AUTH = "\n".join([
    "Sep  9 03:12:01 srv sshd[1]: Failed password for invalid user admin from 45.155.205.233 port 1 ssh2",
    "Sep  9 03:12:03 srv sshd[2]: Failed password for root from 45.155.205.233 port 2 ssh2",
    "Sep  9 03:12:05 srv sshd[3]: Accepted password for deploy from 10.0.4.7 port 3 ssh2",
])

WEB = "\n".join([
    '10.0.0.5 - - [09/Sep/2026:03:12:01] "GET /admin HTTP/1.1" 401 512',
    '10.0.0.5 - - [09/Sep/2026:03:12:02] "GET /.env HTTP/1.1" 404 120',
    '10.0.0.6 - - [09/Sep/2026:03:12:03] "POST /login HTTP/1.1" 200 88',
])


# --- códigos de respuesta --------------------------------------------------

@pytest.mark.parametrize("linea,esperado", [
    ('1.2.3.4 - - [x] "GET /a HTTP/1.1" 401 512', "401"),
    ('1.2.3.4 - - [x] "POST /b HTTP/1.0" 200 88', "200"),
    ('1.2.3.4 - - [x] "GET /c HTTP/2" 503 0', "503"),
])
def test_extrae_el_codigo_de_respuesta(linea, esperado):
    assert parse_log(linea)["codigo_respuesta"] == esperado


@pytest.mark.parametrize("linea", [
    "Sep  9 03:12:01 srv sshd[2841]: Failed password for root from 1.2.3.4 port 51422 ssh2",
    "081109 203615 148 INFO dfs.DataNode$PacketResponder: Received block blk_123 of size 67108864",
    "- 1117838570 2005.06.03 R02-M1-N0-C:J12-U11 RAS KERNEL INFO instruction cache parity error",
])
def test_no_inventa_codigos_donde_no_hay_http(linea):
    """Un puerto, un PID o un tamaño de bloque son números de tres cifras que
    no son códigos de respuesta. Se exige el marcador `HTTP/x.y`."""
    assert parse_log(linea)["codigo_respuesta"] is None


def test_los_codigos_se_agregan_por_frecuencia():
    r = aggregate_logs_v1(WEB)
    assert r["codigos_respuesta"] == {"401": 1, "404": 1, "200": 1}


def test_sin_trafico_web_el_conteo_queda_vacio():
    assert aggregate_logs_v1(AUTH)["codigos_respuesta"] == {}


# --- usuarios y entidades involucradas -------------------------------------

def test_agrega_los_usuarios_observados():
    r = aggregate_logs_v1(AUTH)
    assert r["n_usuarios_distintos"] >= 2
    assert sum(r["usuarios"].values()) >= 3


def test_los_usuarios_van_acotados_pero_el_conteo_es_real():
    """En HDFS el "usuario" es un block id: hay miles por lote. Se acota la
    lista, nunca el conteo."""
    lineas = [
        f"081109 203615 148 WARN dfs.DataNode: Received block blk_{i} of size 1"
        for i in range(50)
    ]
    r = aggregate_logs_v1("\n".join(lineas))
    assert len(r["usuarios"]) == 10
    assert r["n_usuarios_distintos"] == 50


def test_las_entidades_traen_usuarios_y_servicios_por_ip():
    """El §8.7.1 pide "las entidades involucradas". Antes se calculaban en
    `por_ip` pero no llegaban al reporte."""
    entidades = aggregate_logs_v1(AUTH)["entidades"]
    atacante = next(e for e in entidades if e["ip"] == "45.155.205.233")
    assert atacante["n_eventos"] == 2
    assert atacante["intentos_fallidos"] == 2
    assert "sshd" in atacante["servicios"]
    assert atacante["usuarios_objetivo"]


def test_las_entidades_estan_acotadas():
    lineas = [f"Sep  9 03:12:0{i % 10} srv sshd[{i}]: Failed password for root from 10.0.0.{i} port 1 ssh2"
              for i in range(30)]
    assert len(aggregate_logs_v1("\n".join(lineas))["entidades"]) == 8


# --- secuencia temporal ----------------------------------------------------

def test_la_cronologia_selecciona_lo_relevante_y_conserva_el_orden():
    r = aggregate_logs_v1(AUTH)
    crono = r["cronologia"]
    # Las dos primeras líneas son accesos fallidos; la tercera es un acceso
    # aceptado, que es el comportamiento base del formato.
    assert [e["n"] for e in crono] == [1, 2]
    assert all(e["evento"] == "acceso_fallido" for e in crono)
    assert crono[0]["timestamp"] == "Sep  9 03:12:01"
    assert "45.155.205.233" in crono[0]["mensaje"]


def test_un_4xx_entra_aunque_el_evento_sea_generico():
    crono = aggregate_logs_v1(WEB)["cronologia"]
    codigos = [e.get("codigo_respuesta") for e in crono]
    assert "404" in codigos       # el adaptador lo clasifica como genérico
    assert "200" not in codigos   # un 2xx no es relevante


def test_la_cronologia_tiene_tope_y_declara_lo_omitido():
    lineas = [
        f"Sep  9 03:12:{i:02d} srv sshd[{i}]: Failed password for root from 1.2.3.4 port {i} ssh2"
        for i in range(CRONOLOGIA_MAX_EVENTOS + 12)
    ]
    r = aggregate_logs_v1("\n".join(lineas))
    assert len(r["cronologia"]) == CRONOLOGIA_MAX_EVENTOS
    assert r["cronologia_omitidos"] == 12
    # El recorte es de presentación: los conteos siguen siendo del lote entero.
    assert r["total_lineas"] == CRONOLOGIA_MAX_EVENTOS + 12


def test_el_mensaje_se_recorta():
    linea = "Sep  9 03:12:01 srv sshd[1]: Failed password for root from 1.2.3.4 " + "x" * 400
    entrada = aggregate_logs_v1(linea)["cronologia"][0]
    assert len(entrada["mensaje"]) <= 181
    assert entrada["mensaje"].endswith("…")


def test_no_agrega_claves_vacias():
    """Una cronología con `"usuario": null` en cada entrada infla el JSON y
    el PDF sin decir nada."""
    entrada = aggregate_logs_v1(
        "081109 203615 148 WARN dfs.DataNode: bloque sin ip ni usuario")["cronologia"][0]
    assert "ip" not in entrada
    assert "codigo_respuesta" not in entrada


# --- no-fuga de ground truth (Fase 7) --------------------------------------

BGL_ALERTA = (
    "APPREAD 1117869872 2005.06.04 R04-M1-N4-I:J18-U11 "
    "2005-06-04-00.24.32.432192 R04-M1-N4-I:J18-U11 RAS APP FATAL "
    "ciod: failed to read message prefix on control stream"
)


def test_la_cronologia_no_filtra_la_etiqueta_de_bgl():
    """En BGL la etiqueta del dataset es el primer token de la línea.
    Reproducir el crudo la metería en el resumen: es la fuga que cerró la
    Fase 7 y la que hacía circulares las métricas de detección."""
    r = aggregate_logs_v1(BGL_ALERTA + "\n")
    assert "APPREAD" not in str(r)
    entrada = r["cronologia"][0]
    assert "ciod: failed to read message prefix" in entrada["mensaje"]


def test_bgl_sin_mensaje_separable_declara_la_omision():
    """Una línea de un lote BGL que no matchea el patrón completo no tiene
    mensaje separado del flag (variantes como "NULL DISCOVERY ..."). En ese
    caso se declara la omisión en vez de caer al crudo, que llevaría la
    etiqueta.

    El lote necesita suficientes líneas válidas para que el detector elija el
    adaptador de BGL: con una sola línea rara caería al de auth-log.
    """
    lote = "\n".join([BGL_ALERTA] * 4 + [
        "KERNSTOR 1117869872 2005.06.04 variante rara sin el patron completo",
    ])
    r = aggregate_logs_v1(lote)
    assert r["formato_detectado"] == "bgl"
    assert "KERNSTOR" not in str(r)
    omitidas = [e for e in r["cronologia"] if "omitido" in e["mensaje"]]
    assert len(omitidas) == 1


def test_el_prompt_no_recibe_la_cronologia_ni_las_entidades():
    """Doble defensa: además de sanear el mensaje, estas claves no salen
    hacia el LLM. Es el único camino del resumen al prompt del triage."""
    r = aggregate_logs_v1(AUTH)
    acotado = acotar_resumen_para_prompt(r)
    assert "cronologia" not in acotado
    assert "cronologia_omitidos" not in acotado
    assert "entidades" not in acotado
    # Lo que sí es señal para el LLM se conserva.
    assert "usuarios" in acotado
    assert "codigos_respuesta" in acotado


def test_acotar_no_muta_el_resumen_original():
    r = aggregate_logs_v1(AUTH)
    acotar_resumen_para_prompt(r)
    assert "cronologia" in r


# --- paridad entre motores -------------------------------------------------

def test_los_dos_motores_exponen_las_mismas_claves():
    """El informe, el PDF y la interfaz consumen estas claves: no deben
    depender del motor de preprocesamiento activo."""
    from src.preprocessing.aggregation import derivar_v1
    from src.preprocessing.pipeline import preprocesar

    v1 = aggregate_logs_v1(AUTH)
    v2 = derivar_v1(preprocesar(AUTH))
    nuevas = {"usuarios", "n_usuarios_distintos", "codigos_respuesta",
              "entidades", "cronologia", "cronologia_omitidos"}
    assert nuevas <= set(v1)
    assert nuevas <= set(v2)


def test_v2_tampoco_filtra_la_etiqueta_de_bgl():
    from src.preprocessing.aggregation import derivar_v1
    from src.preprocessing.pipeline import preprocesar

    v2 = derivar_v1(preprocesar(BGL_ALERTA + "\n", modo="line"))
    assert "APPREAD" not in str(v2)


# --- precedentes como evidencia utilizada ----------------------------------

def test_los_precedentes_del_rag_quedan_en_el_reporte():
    """El §8.7.1 pide "las evidencias utilizadas": los CVEs, la reputación y
    ATT&CK ya quedaban, los precedentes de la memoria no."""
    from src.pipeline import _precedentes

    contexto = [
        {"texto": "v1|lineas=23 ...", "similitud": 0.91,
         "meta": {"clasificacion": "fuerza bruta SSH", "confianza": 0.95, "host": "web"}},
        {"texto": "v1|otra", "similitud": 0.62, "meta": {}},
    ]
    salida = _precedentes(contexto)
    assert salida[0] == {"clasificacion": "fuerza bruta SSH", "confianza": 0.95,
                         "host": "web", "similitud": 0.91}
    # No se copia el documento completo: es la firma del lote precedente y
    # no aporta nada leída.
    assert "texto" not in salida[0]
    assert salida[1]["clasificacion"] is None


@pytest.mark.parametrize("entrada", [None, [], ["basura"], [None]])
def test_los_precedentes_toleran_entrada_invalida(entrada):
    from src.pipeline import _precedentes

    assert isinstance(_precedentes(entrada), list)


# --- el informe en PDF los muestra -----------------------------------------

def test_el_pdf_incluye_la_cronologia_y_las_entidades(monkeypatch):
    from tests.test_informe_pdf import CORRIDA, _texto_escrito

    corrida = dict(CORRIDA)
    corrida["resumen_json"] = {
        **CORRIDA["resumen_json"],
        "usuarios": {"root": 4, "admin": 2},
        "n_usuarios_distintos": 2,
        "codigos_respuesta": {"401": 3},
        "entidades": [{"ip": "45.155.205.233", "n_eventos": 15,
                       "intentos_fallidos": 16, "servicios": ["sshd"],
                       "usuarios_objetivo": ["root", "admin"]}],
        "cronologia": [{"n": 1, "timestamp": "Sep  9 03:12:01", "servicio": "sshd",
                        "evento": "acceso_fallido", "ip": "45.155.205.233",
                        "mensaje": "Failed password for root"}],
        "cronologia_omitidos": 7,
    }
    corrida["reporte_json"] = {
        **CORRIDA["reporte_json"],
        "precedentes": [{"clasificacion": "fuerza bruta previa", "confianza": 0.9,
                         "host": "web", "similitud": 0.88}],
    }
    texto = _texto_escrito(monkeypatch, corrida)
    assert "Secuencia temporal" in texto
    assert "Failed password for root" in texto
    assert "7 registro(s)" in texto          # el recorte queda declarado
    assert "Entidades involucradas" in texto
    assert "root, admin" in texto            # usuarios objetivo de la entidad
    assert "401" in texto                    # códigos de respuesta
    assert "fuerza bruta previa" in texto    # precedentes


def test_el_pdf_omite_las_secciones_sin_datos(monkeypatch):
    from tests.test_informe_pdf import CORRIDA, _texto_escrito

    texto = _texto_escrito(monkeypatch, CORRIDA)
    assert "Secuencia temporal" not in texto
