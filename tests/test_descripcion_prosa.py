"""Tests de `describir_lote_en_prosa()` (9-sep-2026).

La función arma el texto con el que se consulta la colección
`attack_techniques`. Se prueba determinísticamente -- sin LLM y sin
ChromaDB -- porque lo que puede romperse es el contenido de la oración:
qué afirma sobre el lote y qué se calla cuando no hay dato.

La verificación de que esa prosa efectivamente recupera técnicas
relevantes (y no ruido) se hizo aparte, midiendo contra las 697 técnicas
cargadas y 32 ventanas reales de BGL/HDFS; los números están en
`src/config.py`, junto a `SIMILARITY_FLOOR_ATTACK`.
"""

import pytest

from src.tools.aggregation import aggregate_logs, describir_lote_en_prosa, firma_lote

AUTH = {
    "formato_detectado": "auth_log",
    "total_lineas": 23,
    "servicios": {"sshd": 18, "apache": 2, "kernel": 1},
    "eventos": {"evento_critico": 13, "evento_normal": 10},
    "n_ips_distintas": 3,
    "por_ip": {
        "45.155.205.233": {"intentos_fallidos": 12},
        "10.0.4.7": {"intentos_fallidos": 0},
        "185.220.101.44": {"intentos_fallidos": 1},
    },
}

BGL = {
    "formato_detectado": "bgl",
    "total_lineas": 2000,
    "servicios": {"bgl.kernel": 1820, "bgl.app": 107},
    "eventos": {"evento_normal": 1857, "evento_critico": 143},
    "n_ips_distintas": 2,
    "por_ip": {"172.16.96.116": {"intentos_fallidos": 26}},
}


def resumen(base, **cambios):
    d = dict(base)
    d.update(cambios)
    return d


# --- contenido de la oración -----------------------------------------------

def test_describe_formato_evento_y_servicio_dominantes():
    p = describir_lote_en_prosa(AUTH)
    assert p.startswith("Lote de tipo auth_log.")
    assert "evento_critico" in p
    assert "sshd" in p


def test_el_dominante_es_el_de_mayor_conteo_no_el_primero():
    p = describir_lote_en_prosa(resumen(
        AUTH, servicios={"apache": 2, "sshd": 18}))
    assert "sshd" in p
    assert "servicio apache" not in p


def test_los_intentos_fallidos_se_suman_por_ip():
    """`por_ip` acredita los fallos solo al origen, así que sumarlo no
    cuenta dos veces las líneas de flujo que nombran dos IPs."""
    assert "13 intentos fallidos" in describir_lote_en_prosa(AUTH)


def test_sin_por_ip_cae_al_conteo_de_eventos():
    """El resumen que persiste la capa web no lleva `por_ip`."""
    p = describir_lote_en_prosa(resumen(AUTH, por_ip={}))
    assert "13 intentos fallidos" in p


def test_no_afirma_autenticacion_en_formatos_que_no_la_tienen():
    """Los adaptadores de HDFS y BGL usan `intentos_fallidos` como marca de
    criticidad, no como fallo de login: describirlo como autenticación
    afirmaría algo que el log no dice, y arrastraría la búsqueda de ATT&CK
    hacia técnicas de credenciales por un lote de fallas de hardware."""
    p = describir_lote_en_prosa(BGL)
    assert "autenticacion" not in p
    assert "143 eventos criticos" in p


def test_la_reputacion_solo_aparece_si_hay_algo_marcado():
    limpio = describir_lote_en_prosa(resumen(AUTH, reputacion_ips={
        "10.0.4.7": {"categoria": "limpio"},
        "10.0.4.8": {"categoria": "desconocido"}}))
    assert "AbuseIPDB" not in limpio

    sucio = describir_lote_en_prosa(resumen(AUTH, reputacion_ips={
        "10.0.4.7": {"categoria": "limpio"},
        "45.155.205.233": {"categoria": "malicioso"}}))
    assert "1 IP con reputacion maliciosa" in sucio


def test_la_reputacion_cuenta_tambien_las_sospechosas():
    p = describir_lote_en_prosa(resumen(AUTH, reputacion_ips={
        "1.1.1.1": {"categoria": "malicioso"},
        "2.2.2.2": {"categoria": "sospechoso"}}))
    assert "2 IPs con reputacion maliciosa" in p


# --- robustez ---------------------------------------------------------------

@pytest.mark.parametrize("entrada", [{}, None, {"formato_detectado": "x"}])
def test_un_resumen_incompleto_no_lanza(entrada):
    assert describir_lote_en_prosa(entrada).startswith("Lote de tipo")


def test_es_ascii_puro():
    """El texto va a un embedding y a los logs de consola; no se gana nada
    con acentos y sí se arriesga un problema de codificación."""
    describir_lote_en_prosa(AUTH).encode("ascii")


def test_es_deterministica():
    assert describir_lote_en_prosa(AUTH) == describir_lote_en_prosa(AUTH)


def test_sobre_un_lote_real_describe_lo_mismo_que_agrego():
    raw = "\n".join([
        "Sep  9 03:12:01 srv sshd[1]: Failed password for invalid user admin from 45.155.205.233 port 1 ssh2",
        "Sep  9 03:12:03 srv sshd[2]: Failed password for root from 45.155.205.233 port 2 ssh2",
        "Sep  9 03:12:05 srv sshd[3]: Accepted password for deploy from 10.0.4.7 port 3 ssh2",
    ])
    r = aggregate_logs(raw)
    p = describir_lote_en_prosa(r)
    assert f"Lote de tipo {r['formato_detectado']}." in p
    assert "2 intentos fallidos de autenticacion desde 2 IPs distintas." in p


# --- separación de responsabilidades ---------------------------------------

def test_la_firma_no_cambia():
    """`firma_lote()` sigue siendo la clave de patterns/errors/history: ahí
    ambos lados de la comparación son firmas y el formato compacto es el
    correcto. La prosa es solo para ATT&CK."""
    assert firma_lote(AUTH).startswith("v1|lineas=23 ips=3 servicios=[")
    assert "Lote de tipo" not in firma_lote(AUTH)


def test_el_nodo_rag_consulta_attack_con_la_prosa(monkeypatch):
    """Regresión del bug de fondo: consultar ATT&CK con la firma devolvía []
    para cualquier lote, incluido un ataque real."""
    from src.tools import tool_consultar_rag as modulo

    vistos = {}
    monkeypatch.setattr(modulo.ltm, "retrieve_examples",
                        lambda f: vistos.setdefault("patterns", f) and [])
    monkeypatch.setattr(modulo.ltm, "retrieve_attack_techniques",
                        lambda t: vistos.setdefault("attack", t) and [])

    modulo.tool_consultar_rag({"firma": firma_lote(AUTH), "resumen_logs": AUTH})

    assert vistos["patterns"] == firma_lote(AUTH)
    assert vistos["attack"] == describir_lote_en_prosa(AUTH)
