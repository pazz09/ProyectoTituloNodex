"""Tests de los decodificadores estructurales (Fase 4 del plan).

Criterios de aceptación de la fase:
1. Ningún registro textual válido aborta un lote.
2. Cada evento informa decoder y confianza.
3. JSON, CSV, Syslog, CEF, LEEF y `clave=valor` tienen pruebas positivas
   y negativas.

Consecuencia que también se verifica acá: **auth-log deja de ser el
fallback universal**. Un texto desconocido cae en `TextDecoder`, que no le
atribuye servicio ni tipo de evento, en vez de pasar por un parser de
sshd/apache que le inventaría semántica.
"""

import pytest

from src.preprocessing.decoders import (
    DECODERS,
    DECODER_TEXTO,
    CefDecoder,
    CsvDecoder,
    JsonDecoder,
    KeyValueDecoder,
    LeefDecoder,
    SyslogDecoder,
    detectar_cabecera,
)
from src.preprocessing.segmentation import RawRecord, segmentar


def rec(texto: str) -> RawRecord:
    """Un RawRecord de una línea, como lo produciría la segmentación."""
    r = segmentar(texto).records
    return r[0] if r else RawRecord(raw=texto, line_start=1, line_end=1)


# --- JSON -----------------------------------------------------------------

def test_json_positivo_mapea_campos_conocidos():
    d = JsonDecoder()
    linea = ('{"@timestamp": "2024-01-02T10:00:00Z", "src_ip": "10.0.0.1", '
             '"dest_ip": "10.0.0.2", "dest_port": "443", "message": "conexion", '
             '"proto": "tcp"}')
    assert d.detectar(linea) == 1.0
    ev = d.decodificar(rec(linea))
    assert ev.decoder == "json"
    assert ev.parsing_confidence == 1.0
    assert ev.source_ip == "10.0.0.1"
    assert ev.destination_ip == "10.0.0.2"
    assert ev.destination_port == 443       # convertido a entero
    assert ev.protocol == "tcp"
    assert ev.message == "conexion"


def test_json_aplana_objetos_anidados():
    d = JsonDecoder()
    linea = '{"source": {"ip": "10.0.0.9"}, "user": {"name": "ana"}, "msg": "x"}'
    ev = d.decodificar(rec(linea))
    assert ev.source_ip == "10.0.0.9"       # source.ip
    assert ev.source_user == "ana"          # user.name


def test_json_conserva_lo_que_no_reconoce():
    d = JsonDecoder()
    ev = d.decodificar(rec('{"msg": "x", "campo_raro": 42, "otro": "z"}'))
    assert ev.attributes["campo_raro"] == 42
    assert ev.attributes["otro"] == "z"


def test_json_negativo_no_reclama_texto_plano():
    d = JsonDecoder()
    assert d.detectar("Jan 10 13:55:36 srv sshd[1]: algo") == 0.0


def test_json_malformado_no_aborta_y_avisa():
    """Criterio 1: ningún registro válido textualmente aborta el lote."""
    d = JsonDecoder()
    linea = '{"a": 1, "b":}'
    assert 0 < d.detectar(linea) < 0.5      # sospechoso, no aceptado
    ev = d.decodificar(rec(linea))
    assert [w.codigo for w in ev.warnings] == ["json_invalido"]
    assert ev.raw == linea                  # no se perdió nada


# --- CSV ------------------------------------------------------------------

CABECERA_CSV = "ts,src_ip,dest_ip,dest_port,service,conn_state"
FILA_CSV = "1667212800.1,192.168.1.50,203.0.113.10,22,ssh,REJ"


def test_csv_detecta_cabecera_por_nombres_conocidos():
    delim, columnas = detectar_cabecera(CABECERA_CSV)
    assert delim == ","
    assert columnas[1] == "src_ip"


def test_csv_no_confunde_una_frase_con_comas_con_una_cabecera():
    """Aceptar cualquier línea con comas desalinearía el segmento entero."""
    assert detectar_cabecera("hola, esto es una frase, con comas") is None


def test_csv_positivo_usa_la_cabecera_del_contexto():
    d = CsvDecoder()
    ctx = {"csv_cabecera": CABECERA_CSV.split(","), "csv_delimitador": ","}
    assert d.detectar(FILA_CSV, ctx) == 0.95
    ev = d.decodificar(rec(FILA_CSV), ctx)
    assert ev.decoder == "csv"
    assert ev.source_ip == "192.168.1.50"
    assert ev.destination_ip == "203.0.113.10"
    assert ev.destination_port == 22
    assert ev.service_name == "ssh"
    assert ev.timestamp is not None         # epoch normalizado


def test_csv_sin_cabecera_en_el_contexto_no_reclama_el_registro():
    """El decoder es sin estado: sin cabecera en el segmento, no interpreta."""
    d = CsvDecoder()
    assert d.detectar(FILA_CSV, {}) == 0.0


def test_csv_negativo_fila_desalineada_baja_la_confianza_y_avisa():
    d = CsvDecoder()
    ctx = {"csv_cabecera": CABECERA_CSV.split(","), "csv_delimitador": ","}
    corta = "1667212800.1,192.168.1.50"
    assert d.detectar(corta, ctx) == 0.2
    ev = d.decodificar(rec(corta), ctx)
    assert "csv_columnas_desalineadas" in [w.codigo for w in ev.warnings]
    assert ev.source_ip == "192.168.1.50"   # lo que sí se pudo, se conserva


def test_csv_dos_segmentos_con_cabeceras_distintas_no_se_pisan():
    """El estado vive en el contexto del segmento, así que dos cabeceras
    conviven sin interferencia -- ni siquiera con el mismo decoder."""
    d = CsvDecoder()
    ctx_a = {"csv_cabecera": ["ts", "src_ip"], "csv_delimitador": ","}
    ctx_b = {"csv_cabecera": ["timestamp", "dest_ip", "action"],
             "csv_delimitador": ","}
    a = d.decodificar(rec("1667212800,10.0.0.1"), ctx_a)
    b = d.decodificar(rec("1667212800,10.0.0.2,deny"), ctx_b)
    assert a.source_ip == "10.0.0.1" and a.destination_ip is None
    assert b.destination_ip == "10.0.0.2" and b.event_action == "deny"


def test_csv_soporta_tabulador_y_punto_y_coma():
    assert detectar_cabecera("ts\tsrc_ip\tdest_ip")[0] == "\t"
    assert detectar_cabecera("ts;src_ip;dest_ip")[0] == ";"


# --- Syslog ---------------------------------------------------------------

def test_syslog_rfc3164_positivo():
    d = SyslogDecoder()
    linea = ("<38>Jan 10 13:55:36 srv sshd[1234]: Failed password for root "
             "from 203.0.113.10 port 22 ssh2")
    assert d.detectar(linea) == 0.95
    ev = d.decodificar(rec(linea))
    assert ev.decoder == "syslog"
    assert ev.source_host == "srv"
    assert ev.process_name == "sshd"
    assert ev.process_id == "1234"
    assert ev.source_ip == "203.0.113.10"
    assert ev.severity == "info"            # 38 % 8 == 6
    assert ev.attributes["syslog_rfc"] == "3164"


def test_syslog_rfc3164_sin_pri_tambien_se_reconoce():
    """El formato de auth.log tal como llega en la mayoría de los archivos."""
    d = SyslogDecoder()
    linea = "Jan 10 13:55:36 srv sshd[1]: Failed password for root from 45.146.0.9 port 22 ssh2"
    assert d.detectar(linea) == 0.85
    ev = d.decodificar(rec(linea))
    assert ev.process_name == "sshd"
    assert ev.source_ip == "45.146.0.9"
    assert ev.severity is None              # sin PRI no hay severidad


def test_syslog_rfc5424_positivo():
    d = SyslogDecoder()
    linea = ("<165>1 2024-01-02T10:00:00.5Z srv nginx 4321 ID47 "
             "- Se recibio una peticion de 198.51.100.7")
    assert d.detectar(linea) == 1.0
    ev = d.decodificar(rec(linea))
    assert ev.timestamp == "2024-01-02T10:00:00.5Z"
    assert ev.process_name == "nginx"
    assert ev.process_id == "4321"
    assert ev.event_code == "ID47"
    assert ev.source_ip == "198.51.100.7"
    assert ev.attributes["syslog_rfc"] == "5424"


def test_syslog_negativo_no_reclama_json_ni_csv():
    d = SyslogDecoder()
    assert d.detectar('{"a": 1}') == 0.0
    assert d.detectar("1667212800.1,10.0.0.1,ssh") == 0.0


# --- clave=valor ----------------------------------------------------------

def test_key_value_positivo():
    d = KeyValueDecoder()
    linea = ('date=2024-01-02 srcip=10.0.0.1 dstip=10.0.0.2 action=deny '
             'msg="acceso denegado"')
    assert d.detectar(linea) > 0.6
    ev = d.decodificar(rec(linea))
    assert ev.decoder == "key_value"
    assert ev.source_ip == "10.0.0.1"
    assert ev.destination_ip == "10.0.0.2"
    assert ev.event_action == "deny"
    assert ev.message == "acceso denegado"   # respeta las comillas


def test_key_value_negativo_texto_con_un_igual_suelto():
    """Una frase con un `=` no es un registro clave=valor."""
    d = KeyValueDecoder()
    assert d.detectar("el resultado fue x=1 y no se pudo continuar con el proceso") < 0.5


def test_key_value_negativo_sin_pares():
    d = KeyValueDecoder()
    assert d.detectar("no hay ningun par aca") == 0.0


# --- CEF ------------------------------------------------------------------

def test_cef_positivo():
    d = CefDecoder()
    linea = ("CEF:0|Fortinet|FortiGate|7.0|100|Trafico denegado|8|"
             "src=10.0.0.1 dst=10.0.0.2 dpt=445 act=block")
    assert d.detectar(linea) == 1.0
    ev = d.decodificar(rec(linea))
    assert ev.decoder == "cef"
    assert ev.vendor == "Fortinet"
    assert ev.product == "FortiGate"
    assert ev.event_code == "100"
    assert ev.message == "Trafico denegado"
    assert ev.severity == "high"            # 8 -> high
    assert ev.source_ip == "10.0.0.1"
    assert ev.destination_ip == "10.0.0.2"


def test_cef_respeta_la_barra_escapada_en_un_campo():
    d = CefDecoder()
    linea = r"CEF:0|Acme|Sensor|1.0|7|Regla A\|B activada|3|src=10.0.0.1"
    ev = d.decodificar(rec(linea))
    assert ev.message == "Regla A|B activada"
    assert ev.severity == "low"


def test_cef_negativo_cabecera_incompleta_avisa_sin_abortar():
    d = CefDecoder()
    linea = "CEF:0|Acme|Sensor|1.0"
    assert d.detectar(linea) == 0.4
    ev = d.decodificar(rec(linea))
    assert "cef_cabecera_incompleta" in [w.codigo for w in ev.warnings]


def test_cef_negativo_no_reclama_otros_formatos():
    assert CefDecoder().detectar("LEEF:2.0|A|B|1|100|") == 0.0


# --- LEEF -----------------------------------------------------------------

def test_leef_positivo_con_delimitador_declarado():
    d = LeefDecoder()
    linea = "LEEF:2.0|IBM|QRadar|1.0|4004|^|src=10.0.0.1^dst=10.0.0.2^usrName=ana"
    assert d.detectar(linea) == 1.0
    ev = d.decodificar(rec(linea))
    assert ev.decoder == "leef"
    assert ev.vendor == "IBM"
    assert ev.event_code == "4004"
    assert ev.source_ip == "10.0.0.1"
    assert ev.destination_ip == "10.0.0.2"


def test_leef_10_usa_tabulador_por_defecto():
    d = LeefDecoder()
    linea = "LEEF:1.0|Acme|Sensor|1.0|7000|src=10.0.0.5\tdst=10.0.0.6"
    ev = d.decodificar(rec(linea))
    assert ev.source_ip == "10.0.0.5"
    assert ev.destination_ip == "10.0.0.6"


def test_leef_negativo_cabecera_incompleta_avisa():
    d = LeefDecoder()
    ev = d.decodificar(rec("LEEF:2.0|A|B"))
    assert "leef_cabecera_incompleta" in [w.codigo for w in ev.warnings]


# --- texto libre: el fallback obligatorio ---------------------------------

def test_texto_acepta_cualquier_cosa_y_nunca_falla():
    """Criterio 1 de la fase, en su forma más directa."""
    for entrada in ("", "???", "\x00binario", "algo totalmente desconocido",
                    "081109 203615 148 INFO dfs.DataNode: mensaje"):
        ev = DECODER_TEXTO.decodificar(rec(entrada) if entrada else
                                       RawRecord(raw="", line_start=1, line_end=1))
        assert ev.decoder == "text"
        assert ev.es_fallback is True


def test_texto_no_inventa_servicio_ni_evento():
    """Auth-log dejó de ser el fallback universal: un texto desconocido ya
    no recibe una clasificación de sshd/apache/kernel que no le consta."""
    ev = DECODER_TEXTO.decodificar(rec("algo con la palabra sshd adentro"))
    assert ev.service_name is None
    assert ev.event_category is None


def test_texto_extrae_ips_pero_no_les_asigna_direccion():
    ev = DECODER_TEXTO.decodificar(rec("conexion de 10.0.0.1 hacia 10.0.0.2"))
    assert ev.source_ip == "10.0.0.1"
    assert ev.destination_ip is None        # sin estructura no se puede afirmar
    assert ev.attributes["ips_detectadas"] == ["10.0.0.1", "10.0.0.2"]


def test_el_fallback_pierde_contra_cualquier_decoder_real():
    """Si el texto libre empatara, ganaría por orden y taparía a los demás."""
    linea = '{"src_ip": "10.0.0.1", "msg": "x"}'
    confianza_texto = DECODER_TEXTO.detectar(linea)
    assert max(d.detectar(linea) for d in DECODERS) > confianza_texto


# --- criterio 2: todos informan decoder y confianza -----------------------

@pytest.mark.parametrize("linea", [
    '{"src_ip": "10.0.0.1", "msg": "x"}',
    "<38>Jan 10 13:55:36 srv sshd[1]: algo",
    "CEF:0|A|B|1.0|1|N|5|src=10.0.0.1",
    "LEEF:2.0|A|B|1.0|1|^|src=10.0.0.1",
    "srcip=10.0.0.1 dstip=10.0.0.2 action=deny",
    "texto libre sin estructura",
])
def test_todo_evento_informa_decoder_y_confianza(linea):
    mejor = max(DECODERS, key=lambda d: d.detectar(linea))
    decoder = mejor if mejor.detectar(linea) > DECODER_TEXTO.detectar(linea) else DECODER_TEXTO
    ev = decoder.decodificar(rec(linea))
    assert ev.decoder
    assert 0.0 <= ev.parsing_confidence <= 1.0
    assert ev.raw == rec(linea).raw
