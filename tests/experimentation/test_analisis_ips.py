"""Análisis de las IPs consultadas a AbuseIPDB (src/experimentation/analisis_ips.py)."""

import json
from pathlib import Path

import pytest

from src.experimentation import analisis_ips as ai

RAIZ = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("ip, clase", [
    ("10.0.0.1", "rfc1918"), ("192.168.1.5", "rfc1918"), ("172.16.96.116", "rfc1918"),
    ("172.28.128.3", "rfc1918"), ("172.31.255.255", "rfc1918"), ("172.32.0.1", "publica"),
    ("127.0.0.1", "loopback"), ("169.254.1.1", "link_local"), ("100.64.0.1", "cgnat"),
    ("224.0.0.251", "multicast"), ("240.0.0.1", "reservada"), ("0.0.0.0", "reservada"),
    ("8.8.8.8", "publica"), ("143.88.1.1", "publica"),
    ("fe80::1", "ipv6_no_global"), ("fd00::1", "ipv6_no_global"), ("2001:4860:4860::8888", "ipv6_global"),
    ("no-es-ip", "no_es_ip"), ("", "no_es_ip"),
])
def test_clasificacion_de_direcciones(ip, clase):
    assert ai.clasificar_ip(ip) == clase


def test_el_rango_privado_172_16_12_llega_hasta_172_31():
    """El respaldo local solo cubre 172.16.x.x; el rango real llega a 172.31.255.255."""
    for segundo in (16, 17, 24, 31):
        assert ai.clasificar_ip(f"172.{segundo}.0.1") == "rfc1918"
    assert ai.clasificar_ip("172.15.0.1") == "publica" and ai.clasificar_ip("172.32.0.1") == "publica"


def test_el_respaldo_local_real_trata_como_privadas_justo_las_que_decimos(monkeypatch):
    """Guarda contra el desfase: el comportamiento REAL de `check_ip_reputation` sin AbuseIPDB
    coincide con lo que este módulo dice que hace."""
    import src.tools.reputation as rep
    monkeypatch.setattr(rep, "ABUSEIPDB_API_KEY", None)
    for ip in ("10.1.1.1", "192.168.0.9", "172.16.5.5", "127.0.0.1", "172.28.1.1", "8.8.8.8",
               "fe80::1", "224.0.0.251", "169.254.3.3", "2001:db8::1"):
        real = rep.check_ip_reputation(ip)
        dice_privada = ai.respaldo_la_trata_como_privada(ip)
        assert (real["score"] == 0) == dice_privada, ip
        assert real["score"] in (0, 50)
        assert real["fuente"] == "fallback"


def test_el_respaldo_puntua_50_a_toda_direccion_que_no_empieza_con_sus_prefijos(monkeypatch):
    import src.tools.reputation as rep
    monkeypatch.setattr(rep, "ABUSEIPDB_API_KEY", None)
    assert rep.check_ip_reputation("172.28.128.3")["score"] == 50     # RFC 1918, pero lo puntúa «público»
    assert rep.check_ip_reputation("224.0.0.251")["score"] == 50
    assert rep.categorizar_reputacion(50) == "sospechoso"             # y 50 es «sospechoso»


def _escribir(raiz, dataset, run, ips, config="cfg"):
    ruta = raiz / "experiments" / "telemetry" / dataset / f"{run}.consultas_externas.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({
        "config_version": config, "dataset": dataset, "arquitectura": "nodex_multiagente",
        "run_id": run,
        "consultas": [{"herramienta": "abuseipdb", "parametros": {"ip": ip}, "intento_externo": True}
                      for ip in ips] + [{"herramienta": "nvd", "parametros": {"keyword": "x"}}]}),
        encoding="utf-8")


def test_el_analisis_cuenta_consultas_ips_unicas_y_fraccion_no_publica_por_dataset(tmp_path):
    _escribir(tmp_path, "hdfs", "a", ["10.0.0.1", "10.0.0.1", "10.0.0.2"])
    _escribir(tmp_path, "uwf", "b", ["8.8.8.8", "172.28.0.1", "fe80::1", "2001:4860:4860::8888"])
    r = ai.analizar(tmp_path, "cfg")
    hdfs, uwf = r["por_dataset"]["hdfs"], r["por_dataset"]["uwf"]
    assert (hdfs["consultas"], hdfs["ips_unicas"], hdfs["pct_consultas_no_publicas"]) == (3, 2, 100.0)
    assert (uwf["consultas"], uwf["consultas_no_publicas"], uwf["pct_consultas_no_publicas"]) == (4, 2, 50.0)
    assert uwf["por_clase_consultas"] == {"publica": 1, "rfc1918": 1, "ipv6_no_global": 1, "ipv6_global": 1}
    assert (r["total_consultas"], r["total_no_publicas"], r["pct_total_no_publicas"]) == (7, 5, 71.4)


def test_una_ipv6_global_cuenta_como_publica_y_una_no_global_no(tmp_path):
    _escribir(tmp_path, "uwf", "b", ["2001:4860:4860::8888", "fe80::1"])
    assert ai.analizar(tmp_path, "cfg")["por_dataset"]["uwf"]["consultas_no_publicas"] == 1


def test_se_cuentan_las_no_publicas_que_el_respaldo_puntua_como_publicas(tmp_path):
    _escribir(tmp_path, "uwf", "b", ["172.28.128.3", "172.16.0.9", "fe80::1", "224.0.0.251", "8.8.8.8"])
    d = ai.analizar(tmp_path, "cfg")["por_dataset"]["uwf"]
    assert d["ips_unicas_no_publicas"] == 4
    # 172.16.0.9 sí lo reconoce; las otras tres (172.28.x, fe80::, 224.x) las puntúa como públicas
    assert d["ips_no_publicas_que_el_respaldo_puntua_como_publicas"] == 3


def test_solo_cuenta_la_configuracion_pedida_y_solo_abuseipdb(tmp_path):
    _escribir(tmp_path, "uwf", "b", ["8.8.8.8"], config="otra")
    assert ai.analizar(tmp_path, "cfg")["por_dataset"] == {}
    _escribir(tmp_path, "uwf", "c", ["8.8.8.8"], config="cfg")
    assert ai.analizar(tmp_path, "cfg")["por_dataset"]["uwf"]["consultas"] == 1     # sin la de NVD


def test_sin_registros_el_analisis_esta_vacio_y_no_inventa_porcentajes(tmp_path):
    r = ai.analizar(tmp_path, "cfg")
    assert r["por_dataset"] == {} and r["total_consultas"] == 0 and r["pct_total_no_publicas"] is None


def test_la_descripcion_del_respaldo_sale_del_codigo_y_declara_que_no_tiene_fuente_ni_fecha():
    d = ai.descripcion_del_respaldo()
    assert d["abuseipdb"]["fuente"].startswith("ninguna") and d["abuseipdb"]["fecha"].startswith("ninguna")
    assert list(ai.PREFIJOS_PRIVADOS_DEL_RESPALDO) == ["10.", "192.168.", "172.16.", "127."]
    assert "score 50" in d["abuseipdb"]["cobertura"]
    from src.tools import cve
    assert d["nvd"]["cobertura"] == {k: list(v) for k, v in cve._CVE_LOCAL.items()}
    assert set(d["nvd"]["cobertura"]) == {"openssh", "apache", "sql"}
    assert any("172.31" in x for x in d["abuseipdb"]["limites_conocidos"])
