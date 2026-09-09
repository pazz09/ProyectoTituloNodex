"""Tests del adaptador CSV/TSV genérico de aggregate_logs().

A diferencia de los adaptadores de HDFS y BGL —atados al formato de un
dataset concreto—, este se guía por los NOMBRES DE COLUMNA de la cabecera,
así que un mismo código cubre exportaciones de Zeek, Suricata, firewalls y
SIEMs. Los tests reflejan eso: además de la muestra real de
UWF-ZeekDataFall22 (Tabla 8.11 del Informe), se cubren variantes de
delimitador, esquemas de columnas distintos y el fallback cuando el CSV no
trae columnas de IP reconocibles.

La primera muestra es una fila real del dataset (archivo
`part-00000-...csv`, export Parquet→CSV vía Spark).
"""

# Estos tests describen el comportamiento del AGREGADOR v1, así que
# invocan `aggregate_logs_v1` directamente en vez de pasar por la
# fachada `aggregate_logs`, que despacha según
# LOG_PREPROCESSING_ENGINE. De ese modo siguen verificando lo que
# deben verificar aunque el entorno tenga el motor v2 activo -- la
# fidelidad con el prototipo del Seminario se conserva en v1, no en
# el esquema nuevo (ver docs/plan_accion_preprocesamiento_heterogeneo.md).
from src.tools.aggregation import aggregate_logs_v1 as aggregate_logs

_UWF_CABECERA = (
    "community_id,conn_state,duration,history,src_ip_zeek,src_port_zeek,dest_ip_zeek,"
    "dest_port_zeek,local_orig,local_resp,missed_bytes,orig_bytes,orig_ip_bytes,orig_pkts,"
    "proto,resp_bytes,resp_ip_bytes,resp_pkts,service,ts,uid,datetime,label_tactic,"
    "label_technique,label_binary\n"
)

UWF_MUESTRA = _UWF_CABECERA + (
    "1:VhB7MbbJ52hjItNqXYgI9n8660Q=,SF,0.013730049133300781,Dd,143.88.20.12,68,143.88.20.1,"
    "67,false,false,0,600,656,2,udp,600,656,2,dhcp,1.664883645900091E9,CMcgot3HfOuCDV3s11,"
    "2022-10-04T11:40:45.900Z,Credential Access,Duplicate,Duplicate\n"
    "1:AaB7MbbJ52hjItNqXYgI9n8660Q=,SF,0.02,Dd,143.88.20.13,68,143.88.20.1,"
    "67,false,false,0,600,656,2,udp,600,656,2,dhcp,1.664883646900091E9,CNcgot3HfOuCDV3s12,"
    "2022-10-04T11:40:46.900Z,none,-,0\n"
)

# Esquema distinto (estilo Zeek nativo / Suricata: id.orig_h / id.resp_h),
# sin columna de etiqueta -- la anomalía sale de conn_state.
ZEEK_CONN_MUESTRA = (
    "ts,uid,id.orig_h,id.resp_h,id.resp_p,proto,service,conn_state\n"
    "1667212800.1,C1,192.168.1.50,203.0.113.10,22,tcp,ssh,REJ\n"
    "1667212801.4,C2,192.168.1.50,203.0.113.10,22,tcp,ssh,S0\n"
    "1667212805.9,C3,10.0.0.7,10.0.0.9,443,tcp,ssl,SF\n"
)

CSV_PUNTO_Y_COMA = (
    "fecha;source_ip;destination_ip;dest_port;service;label\n"
    "2024-01-02 10:00:00;198.51.100.7;10.0.0.5;3389;rdp;attack\n"
    "2024-01-02 10:00:05;198.51.100.7;10.0.0.5;3389;rdp;benign\n"
)

TSV_MUESTRA = (
    "timestamp\tsrc_ip\tdst_ip\tdst_port\tservice\n"
    "2024-01-02T10:00:00Z\t198.51.100.7\t10.0.0.5\t445\tsmb\n"
    "2024-01-02T10:00:05Z\t198.51.100.8\t10.0.0.5\t445\tsmb\n"
)

# CSV sin ninguna columna de IP reconocible: debe caer al adaptador auth-log
# en vez de reclamar el formato y producir un resumen vacío.
CSV_SIN_IPS = (
    "fecha,modulo,mensaje\n"
    "2024-01-02,facturacion,se genero el comprobante 1234\n"
    "2024-01-02,facturacion,se genero el comprobante 1235\n"
)

AUTH_LOG_MUESTRA = (
    "Jan 10 13:55:36 srv sshd[1]: Failed password for invalid user admin from 203.0.113.10 port 22 ssh2\n"
)


def test_detecta_csv_y_no_cuenta_la_cabecera_como_evento():
    resumen = aggregate_logs(UWF_MUESTRA)
    assert resumen["formato_detectado"] == "csv"
    # 3 líneas en el archivo, pero solo 2 son registros: la cabecera no lo es.
    assert resumen["total_lineas"] == 2


def test_captura_las_dos_puntas_del_flujo_con_su_rol():
    """Un log de flujos nombra dos IPs por línea. Ambas entran al agregado
    (para que la corroboración de reputación las cubra), pero se distingue
    quién inició la conexión de quién la recibió."""
    resumen = aggregate_logs(UWF_MUESTRA)
    assert set(resumen["ips_distintas"]) == {"143.88.20.12", "143.88.20.13", "143.88.20.1"}

    origen = resumen["por_ip"]["143.88.20.12"]
    assert origen["n_como_origen"] == 1 and origen["n_como_destino"] == 0

    destino = resumen["por_ip"]["143.88.20.1"]
    assert destino["n_como_destino"] == 2 and destino["n_como_origen"] == 0
    # los intentos fallidos se acreditan al que inicia, no al que recibe
    assert destino["intentos_fallidos"] == 0
    assert origen["intentos_fallidos"] == 1


def test_usa_label_tactic_como_ground_truth_y_lo_expone():
    """UWF-ZeekDataFall22 trae la táctica MITRE ATT&CK etiquetada por fila.
    'Credential Access' es alerta; 'none' es tráfico benigno."""
    resumen = aggregate_logs(UWF_MUESTRA)
    assert resumen["eventos"]["evento_critico"] == 1
    assert resumen["eventos"]["evento_normal"] == 1
    assert resumen["etiquetas"] == {"Credential Access": 1, "none": 1}


def test_prefiere_el_timestamp_legible_al_epoch_en_notacion_cientifica():
    """La columna `ts` viene como '1.664883645900091E9' (artefacto de
    Spark/Parquet): float() la parsea pero int() no. Habiendo una columna
    `datetime` legible, se usa esa."""
    resumen = aggregate_logs(UWF_MUESTRA)
    assert resumen["ventana_temporal"]["inicio"] == "2022-10-04T11:40:45.900Z"


def test_sin_columna_de_etiqueta_la_anomalia_sale_de_conn_state():
    """REJ y S0 son conexiones rechazadas o nunca establecidas; SF es normal."""
    resumen = aggregate_logs(ZEEK_CONN_MUESTRA)
    assert resumen["formato_detectado"] == "csv"
    assert resumen["eventos"]["evento_critico"] == 2
    assert resumen["eventos"]["evento_normal"] == 1
    assert "etiquetas" not in resumen  # este esquema no trae ground truth
    # timestamp epoch normal (sin notación científica) sí se convierte
    assert resumen["ventana_temporal"]["inicio"].startswith("2022-10-31")


def test_soporta_punto_y_coma_y_columna_label_generica():
    resumen = aggregate_logs(CSV_PUNTO_Y_COMA)
    assert resumen["formato_detectado"] == "csv"
    assert resumen["eventos"]["evento_critico"] == 1
    assert resumen["eventos"]["evento_normal"] == 1
    assert resumen["servicios"]["rdp:3389"] == 2


def test_soporta_tabulador():
    resumen = aggregate_logs(TSV_MUESTRA)
    assert resumen["formato_detectado"] == "csv"
    assert resumen["total_lineas"] == 2
    assert resumen["por_ip"]["10.0.0.5"]["n_como_destino"] == 2


def test_csv_sin_columnas_de_ip_cae_a_auth_log():
    """Mejor el fallback —que al menos saca IPs por regex del texto libre—
    que reclamar el formato y devolver un resumen sin IPs."""
    resumen = aggregate_logs(CSV_SIN_IPS)
    assert resumen["formato_detectado"] == "auth_log"


def test_formatos_de_una_sola_ip_no_cambian_de_comportamiento():
    """Regresión: auth-log (y por construcción HDFS/BGL) no tienen IP de
    destino, así que toda su actividad debe seguir contándose como origen."""
    resumen = aggregate_logs(AUTH_LOG_MUESTRA)
    assert resumen["formato_detectado"] == "auth_log"
    entrada = resumen["por_ip"]["203.0.113.10"]
    assert entrada["n_como_origen"] == entrada["n_eventos"] == 1
    assert entrada["n_como_destino"] == 0
