"""Registro de intentos de consulta externa (runtime/consultas_externas.py).

Se prueba con las herramientas REALES de NODEX (`check_ip_reputation`, `query_cve`) y
con la red bloqueada: no sale ninguna petición. Lo que se fija es qué queda anotado.
"""

import json

import pytest
import requests

from src.experimentation.runtime import consultas_externas as ce
from src.experimentation.runtime import persistencia
from src.experimentation.runtime.identidad import IdentidadCorrida
import src.tools.cve as cve
import src.tools.reputation as reputacion


@pytest.fixture
def instalado(monkeypatch):
    """Instala el registro y restaura todo al terminar."""
    monkeypatch.setattr(reputacion, "check_ip_reputation", reputacion.check_ip_reputation)
    monkeypatch.setattr(cve, "query_cve", cve.query_cve)
    monkeypatch.setattr(requests.sessions.Session, "request",
                        requests.sessions.Session.request)
    registro = ce.RegistroConsultas()
    ce.instalar(registro)
    return registro


def test_abuseipdb_con_llave_intenta_salir_se_bloquea_y_responde_el_respaldo(
        instalado, monkeypatch):
    monkeypatch.setattr(reputacion, "ABUSEIPDB_API_KEY", "llave-ficticia")
    resultado = reputacion.check_ip_reputation("8.8.8.8")
    assert resultado["fuente"] == "fallback"                 # el respaldo local contestó
    (c,) = instalado.consultas
    assert c["herramienta"] == "abuseipdb"
    assert c["parametros"] == {"ip": "8.8.8.8"}
    assert c["intento_externo"] is True and c["bloqueado"] is True
    assert c["respaldo_respondio"] is True and c["fuente_respuesta"] == "fallback"
    assert c["hosts"] == ["api.abuseipdb.com"]
    assert "llave-ficticia" not in json.dumps(c)             # nunca la credencial


def test_abuseipdb_sin_llave_no_intenta_salir_pero_la_consulta_queda_registrada(
        instalado, monkeypatch):
    monkeypatch.setattr(reputacion, "ABUSEIPDB_API_KEY", None)
    reputacion.check_ip_reputation("10.0.0.5")
    (c,) = instalado.consultas
    assert c["intento_externo"] is False and c["bloqueado"] is False
    assert c["n_intentos_bloqueados"] == 0
    assert c["respaldo_respondio"] is True


def test_nvd_siempre_intenta_salir_y_el_respaldo_local_responde(instalado):
    resultado = cve.query_cve("apache")
    assert resultado["fuente"] == "fallback"
    (c,) = instalado.consultas
    assert c["herramienta"] == "nvd"
    assert c["parametros"] == {"keyword": "apache"}
    assert c["intento_externo"] is True and c["bloqueado"] is True
    assert c["hosts"] == ["services.nvd.nist.gov"]
    assert c["respaldo_respondio"] is True


def test_el_orden_y_el_conteo_de_consultas_se_conservan(instalado, monkeypatch):
    monkeypatch.setattr(reputacion, "ABUSEIPDB_API_KEY", "x")
    reputacion.check_ip_reputation("1.1.1.1")
    cve.query_cve("openssl")
    reputacion.check_ip_reputation("2.2.2.2")
    assert [(c["orden"], c["herramienta"]) for c in instalado.consultas] == [
        (1, "abuseipdb"), (2, "nvd"), (3, "abuseipdb")]
    assert len(instalado.bloqueados) == 3


def test_ninguna_peticion_sale_a_la_red(instalado, monkeypatch):
    """`requests.get` sigue su camino normal hasta `Session.request`, que está bloqueada."""
    with pytest.raises(ConnectionError, match="bloqueada"):
        requests.get("https://example.com/")
    assert instalado.bloqueados == ["example.com"]


def test_sin_consultas_el_registro_queda_vacio_y_eso_es_un_dato(instalado):
    assert instalado.a_lista() == []


def test_una_respuesta_del_servicio_externo_no_cuenta_como_respaldo():
    """Si el servicio externo contestara, `fuente` sería la externa y NO el respaldo."""
    import types
    registro = ce.RegistroConsultas()
    modulo = types.SimpleNamespace(
        check_ip_reputation=lambda ip: {"fuente": "abuseipdb", "ip": ip, "score": 3})
    ce.envolver(registro, "abuseipdb", modulo)
    assert modulo.check_ip_reputation("9.9.9.9")["score"] == 3      # la respuesta pasa intacta
    (c,) = registro.consultas
    assert c["respaldo_respondio"] is False and c["intento_externo"] is False
    assert c["fuente_respuesta"] == "abuseipdb"


# --- persistencia ------------------------------------------------------------------------

IDENT = IdentidadCorrida("bgl_des_a_0000", "bgl", "nodex_multiagente", 1, "prueba")


def test_se_guarda_y_se_lee_y_no_se_sobrescribe(tmp_path):
    consultas = [{"orden": 1, "herramienta": "nvd", "parametros": {"keyword": "x"}}]
    persistencia.guardar_consultas_externas(IDENT, tmp_path, consultas)
    assert persistencia.leer_consultas_externas(IDENT, tmp_path) == consultas
    with pytest.raises(FileExistsError):
        persistencia.guardar_consultas_externas(IDENT, tmp_path, consultas)


def test_una_lista_vacia_es_un_dato_y_la_ausencia_del_archivo_es_none(tmp_path):
    assert persistencia.leer_consultas_externas(IDENT, tmp_path) is None   # no se registró
    persistencia.guardar_consultas_externas(IDENT, tmp_path, [])
    assert persistencia.leer_consultas_externas(IDENT, tmp_path) == []     # no consultó nada
