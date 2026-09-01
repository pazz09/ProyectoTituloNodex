"""Tests de la corroboración de reputación de IPs (no requieren API keys).

Fuerzan el camino de fallback local (sin ABUSEIPDB_API_KEY) para que sean
deterministas y no dependan de red -- igual que test_aggregation.py y
test_validation.py.
"""

import src.tools.reputation as reputation


def test_categorizar_reputacion_umbrales():
    assert reputation.categorizar_reputacion(None) == "desconocido"
    assert reputation.categorizar_reputacion(10) == "limpio"
    assert reputation.categorizar_reputacion(30) == "sospechoso"
    assert reputation.categorizar_reputacion(80) == "malicioso"


def test_check_ip_reputation_fallback_ip_privada(monkeypatch):
    monkeypatch.setattr(reputation, "ABUSEIPDB_API_KEY", None)
    info = reputation.check_ip_reputation("192.168.1.10")
    assert info["fuente"] == "fallback"
    assert info["score"] == 0


def test_check_ip_reputation_fallback_ip_publica(monkeypatch):
    monkeypatch.setattr(reputation, "ABUSEIPDB_API_KEY", None)
    info = reputation.check_ip_reputation("203.0.113.10")
    assert info["fuente"] == "fallback"
    assert info["score"] == 50


def test_corroborar_ips_agrega_categoria_y_usa_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(reputation, "ABUSEIPDB_API_KEY", None)
    cache = reputation.ReputationCache(path=str(tmp_path / "cache.json"))

    resultado = reputation.corroborar_ips(["203.0.113.10", "45.146.0.9"], cache)

    assert set(resultado) == {"203.0.113.10", "45.146.0.9"}
    assert resultado["203.0.113.10"]["categoria"] == "sospechoso"  # score 50 >= SCORE_SOSPECHOSO (25)
    assert len(cache) == 2

    # Segunda pasada: no debe volver a llamar check_ip_reputation (ya está en caché).
    llamadas = []
    original = reputation.check_ip_reputation
    monkeypatch.setattr(reputation, "check_ip_reputation", lambda ip: (llamadas.append(ip), original(ip))[1])
    reputation.corroborar_ips(["203.0.113.10"], cache)
    assert llamadas == []
