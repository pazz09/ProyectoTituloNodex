"""Modo opt-in «sin reputación externa» (src/tools/reputation.py, REPUTACION_SIN_ENRIQUECIMIENTO).

Con el modo activo ninguna IP recibe puntaje y todas quedan «desconocido», sin consultar nada. Con el
modo apagado (el valor por omisión de producción) el comportamiento es el de siempre.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import requests

import src.tools.reputation as rep

RAIZ = Path(__file__).resolve().parents[1]
IPS = ["8.8.8.8", "10.1.2.3", "172.28.1.1", "fe80::1", "224.0.0.251", "127.0.0.1", "143.88.1.1"]


@pytest.fixture
def sin_red(monkeypatch):
    """Cualquier petición HTTP hace fallar la prueba."""
    llamadas = []

    def prohibida(*a, **k):
        llamadas.append((a, k))
        raise AssertionError("se intentó una petición HTTP")

    monkeypatch.setattr(requests, "get", prohibida)
    monkeypatch.setattr(rep.requests, "get", prohibida)
    return llamadas


def test_con_el_modo_activo_ninguna_ip_recibe_puntaje_y_todas_quedan_desconocido(monkeypatch, sin_red):
    monkeypatch.setattr(rep, "REPUTACION_SIN_ENRIQUECIMIENTO", True)
    monkeypatch.setattr(rep, "ABUSEIPDB_API_KEY", "llave-ficticia")      # aun con llave, no consulta
    for ip in IPS:
        r = rep.check_ip_reputation(ip)
        assert r["score"] is None and r["fuente"] == "sin_reputacion", ip
        assert rep.categorizar_reputacion(r["score"]) == "desconocido", ip
    assert sin_red == []


def test_el_resultado_es_igual_para_toda_ip_publica_privada_ipv6_o_multicast(monkeypatch, sin_red):
    monkeypatch.setattr(rep, "REPUTACION_SIN_ENRIQUECIMIENTO", True)
    sin_ip = [{k: v for k, v in rep.check_ip_reputation(ip).items() if k != "ip"} for ip in IPS]
    assert all(r == sin_ip[0] for r in sin_ip)           # la forma de la dirección no cambia nada


def test_corroborar_ips_deja_todas_desconocido_y_no_consulta_nada(monkeypatch, sin_red):
    monkeypatch.setattr(rep, "REPUTACION_SIN_ENRIQUECIMIENTO", True)
    r = rep.corroborar_ips(IPS)
    assert set(r) == set(IPS)
    assert {v["categoria"] for v in r.values()} == {"desconocido"}
    assert {v["score"] for v in r.values()} == {None}
    assert sin_red == []


def test_el_modo_no_lee_ni_escribe_la_cache(monkeypatch, tmp_path, sin_red):
    """Una caché con puntajes reales de antes no puede anular el modo, y el modo no la ensucia."""
    monkeypatch.setattr(rep, "REPUTACION_SIN_ENRIQUECIMIENTO", True)
    cache = rep.ReputationCache(path=str(tmp_path / "c.json"))
    cache.set("8.8.8.8", {"fuente": "abuseipdb", "score": 99, "categoria": "malicioso"})
    antes = (tmp_path / "c.json").read_text(encoding="utf-8")
    r = rep.corroborar_ips(["8.8.8.8", "1.1.1.1"], cache)
    assert r["8.8.8.8"]["score"] is None and r["8.8.8.8"]["categoria"] == "desconocido"
    assert (tmp_path / "c.json").read_text(encoding="utf-8") == antes
    assert cache.get("1.1.1.1") is None


def test_con_el_modo_apagado_el_comportamiento_es_el_de_siempre(monkeypatch):
    monkeypatch.setattr(rep, "REPUTACION_SIN_ENRIQUECIMIENTO", False)
    monkeypatch.setattr(rep, "ABUSEIPDB_API_KEY", None)
    assert rep.check_ip_reputation("10.1.2.3")["score"] == 0
    assert rep.check_ip_reputation("8.8.8.8")["score"] == 50
    assert rep.check_ip_reputation("8.8.8.8")["fuente"] == "fallback"
    assert rep.categorizar_reputacion(50) == "sospechoso"


def test_con_el_modo_apagado_y_llave_sigue_consultando_abuseipdb(monkeypatch):
    monkeypatch.setattr(rep, "REPUTACION_SIN_ENRIQUECIMIENTO", False)
    monkeypatch.setattr(rep, "ABUSEIPDB_API_KEY", "llave-ficticia")
    visto = {}

    class Respuesta:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": {"abuseConfidenceScore": 77, "totalReports": 3, "countryCode": "XX"}}

    def falsa(url, **k):
        visto["url"] = url
        return Respuesta()

    monkeypatch.setattr(rep.requests, "get", falsa)
    r = rep.check_ip_reputation("8.8.8.8")
    assert r["fuente"] == "abuseipdb" and r["score"] == 77 and "abuseipdb" in visto["url"]


def _valor_de_la_bandera(**entorno_extra):
    entorno = {k: v for k, v in os.environ.items() if k != "REPUTACION_SIN_ENRIQUECIMIENTO"}
    entorno.update(entorno_extra)
    salida = subprocess.run(
        [sys.executable, "-c", "import src.config as c; print(c.REPUTACION_SIN_ENRIQUECIMIENTO)"],
        cwd=RAIZ, env=entorno, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120)
    return salida.stdout.strip().splitlines()[-1], salida.stderr


def test_por_omision_el_modo_esta_apagado():
    valor, error = _valor_de_la_bandera()
    assert valor == "False", error


def test_la_variable_de_entorno_enciende_el_modo():
    valor, error = _valor_de_la_bandera(REPUTACION_SIN_ENRIQUECIMIENTO="true")
    assert valor == "True", error


def test_el_modo_entra_en_la_configuracion_congelada():
    from src.experimentation.runtime.configuracion import PARAMETROS_CONGELADOS
    assert "REPUTACION_SIN_ENRIQUECIMIENTO" in PARAMETROS_CONGELADOS


def test_el_modo_en_el_pipeline_real_no_cambia_el_formato_del_resumen(monkeypatch, sin_red):
    """El resto del sistema consume `categoria` y `score`; ambos existen con el modo activo."""
    monkeypatch.setattr(rep, "REPUTACION_SIN_ENRIQUECIMIENTO", True)
    info = rep.corroborar_ips(["8.8.8.8"])["8.8.8.8"]
    assert {"fuente", "ip", "score", "categoria"} <= set(info)
