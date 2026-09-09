"""Tests del mapeo al esquema normalizado (Fase 4 del plan).

`normalization.py` es compartido por todos los decoders estructurales, así
que sus reglas se prueban una vez acá en vez de repetirlas por formato.
"""

from src.preprocessing.normalization import (
    es_vacio,
    ips_del_texto,
    mapear_campos,
    normalizar_timestamp,
)


# --- prioridad entre sinónimos --------------------------------------------

def test_gana_el_sinonimo_declarado_antes_no_el_que_viene_primero():
    """Caso real de UWF-ZeekDataFall22: la fila trae `ts` (epoch de Spark)
    en la columna 20 y `datetime` (ISO) en la 22. El orden de las columnas
    no debería decidir cuál se conserva."""
    datos = {"ts": "1.664883645900091E9", "datetime": "2022-10-04T11:40:45.900Z"}
    canonicos, atributos = mapear_campos(datos)
    assert canonicos["timestamp"] == "2022-10-04T11:40:45.900Z"
    # el perdedor no se pierde: queda con su nombre original
    assert atributos["ts"] == "1.664883645900091E9"


def test_el_orden_inverso_da_el_mismo_resultado():
    datos = {"datetime": "2022-10-04T11:40:45.900Z", "ts": "1.664883645900091E9"}
    canonicos, atributos = mapear_campos(datos)
    assert canonicos["timestamp"] == "2022-10-04T11:40:45.900Z"
    assert atributos["ts"] == "1.664883645900091E9"


def test_si_solo_esta_el_epoch_ese_se_usa():
    canonicos, _ = mapear_campos({"ts": "1667212800"})
    assert canonicos["timestamp"] == "2022-10-31 10:40:00"


# --- no pérdida -----------------------------------------------------------

def test_lo_no_reconocido_vuelve_en_attributes_con_su_nombre():
    canonicos, atributos = mapear_campos(
        {"src_ip": "10.0.0.1", "campo_propietario": "x", "otro_raro": 5})
    assert canonicos["source_ip"] == "10.0.0.1"
    assert atributos == {"campo_propietario": "x", "otro_raro": 5}


def test_un_puerto_no_numerico_se_conserva_crudo_en_vez_de_descartarse():
    canonicos, atributos = mapear_campos({"dest_port": "no-es-un-puerto"})
    assert "destination_port" not in canonicos
    assert atributos["dest_port"] == "no-es-un-puerto"


def test_limite_de_atributos_no_mapeados_deja_constancia():
    datos = {f"campo_{i:03d}": i for i in range(50)}
    _, atributos = mapear_campos(datos, max_no_mapeados=10)
    assert atributos["_atributos_omitidos"] == 40
    assert len(atributos) == 11  # 10 conservados + el contador


# --- valores vacíos -------------------------------------------------------

def test_el_guion_de_zeek_cuenta_como_ausente():
    """En Zeek y en los access logs, `-` significa 'sin dato'."""
    assert es_vacio("-") is True
    canonicos, atributos = mapear_campos({"src_ip": "-", "dest_ip": "10.0.0.2"})
    assert "source_ip" not in canonicos
    assert "src_ip" not in atributos
    assert canonicos["destination_ip"] == "10.0.0.2"


def test_otros_marcadores_de_ausencia():
    for v in ("", "   ", "null", "N/A", "none", "NaN"):
        assert es_vacio(v) is True, v
    assert es_vacio("0") is False   # cero es un dato, no una ausencia


# --- timestamps -----------------------------------------------------------

def test_epoch_en_notacion_cientifica_no_rompe():
    """`int()` fallaría con esto; es un artefacto de los exports de Spark."""
    assert normalizar_timestamp("1.664883645900091E9") == "2022-10-04 11:40:45"


def test_epoch_en_milisegundos_se_reconoce():
    assert normalizar_timestamp("1667212800000") == "2022-10-31 10:40:00"


def test_un_timestamp_legible_se_devuelve_intacto():
    """No se reformatea: perdería precisión y zona horaria del original."""
    assert normalizar_timestamp("2024-01-02T10:00:00.123456+03:00") == \
        "2024-01-02T10:00:00.123456+03:00"


def test_valor_no_interpretable_no_lanza():
    assert normalizar_timestamp("ayer por la tarde") == "ayer por la tarde"
    assert normalizar_timestamp(None) is None


# --- IPs en texto libre ---------------------------------------------------

def test_ips_en_orden_de_aparicion_y_sin_repetir():
    texto = "de 10.0.0.1 a 10.0.0.2, reintento desde 10.0.0.1"
    assert ips_del_texto(texto) == ["10.0.0.1", "10.0.0.2"]


def test_no_confunde_una_version_con_una_ip():
    assert ips_del_texto("version 1.2.3 del agente") == []
