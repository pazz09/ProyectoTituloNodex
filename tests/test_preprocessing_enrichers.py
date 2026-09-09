"""Tests de los enriquecedores de producto (Fase 6 del plan).

Criterios de aceptación de la fase:
1. HDFS y BGL conservan al menos la información que se extraía en v1.
2. Una fuente desconocida completa el flujo sin perfil.
3. Ningún enriquecedor decide por sí mismo que existe un ataque.
"""

from src.preprocessing.enrichers import BglEnricher, HdfsEnricher, ZeekEnricher
from src.preprocessing.pipeline import preprocesar

HDFS_INFO = ("081109 203615 148 INFO dfs.DataNode$PacketResponder: "
             "PacketResponder 1 for block blk_38865049064139660 terminating")
HDFS_WARN = ("081109 214043 2561 WARN dfs.DataNode$DataXceiver: "
             "10.251.30.85:50010:Got exception while serving "
             "blk_-2918118818249673980 to /10.251.90.64:")

BGL_NORMAL = ("- 1117838570 2005.06.03 R02-M1-N0-C:J12-U11 "
              "2005-06-03-15.42.50.675872 R02-M1-N0-C:J12-U11 RAS KERNEL INFO "
              "instruction cache parity error corrected")
BGL_ALERTA = ("APPREAD 1117869872 2005.06.04 R04-M1-N4-I:J18-U11 "
              "2005-06-04-00.24.32.432192 R04-M1-N4-I:J18-U11 RAS APP FATAL "
              "ciod: failed to read message prefix on control stream")

DESCONOCIDO = "formato completamente desconocido sin estructura alguna"


# --- criterio 1: no se pierde lo que v1 extraía ---------------------------

def test_hdfs_conserva_timestamp_servicio_y_block_id():
    res = preprocesar(HDFS_INFO + "\n", modo="line")
    ev = res.events[0]
    assert ev.product == "HDFS"
    assert ev.timestamp == "2008-11-09 20:36:15"          # igual que v1
    assert ev.service_name == "hdfs.datanode"             # igual que v1
    assert ev.attributes["block_id"] == "blk_38865049064139660"


def test_el_block_id_ya_no_ocupa_el_campo_de_usuario():
    """En v1, `blk_...` se guardaba en `usuario`. Un bloque no es una persona."""
    res = preprocesar(HDFS_INFO + "\n", modo="line")
    ev = res.events[0]
    assert ev.source_user is None
    assert ev.attributes["block_id"].startswith("blk_")


def test_hdfs_extrae_las_direcciones_del_mensaje():
    res = preprocesar(HDFS_WARN + "\n", modo="line")
    ev = res.events[0]
    assert ev.source_ip == "10.251.30.85"
    assert ev.source_port == 50010


def test_bgl_conserva_nodo_subsistema_y_severidad():
    res = preprocesar(BGL_NORMAL + "\n", modo="line")
    ev = res.events[0]
    assert ev.product == "BlueGene/L"
    assert ev.source_host == "R02-M1-N0-C:J12-U11"
    assert ev.service_name == "bgl.kernel"                # igual que v1
    assert ev.severity == "INFO"
    assert ev.timestamp == "2005-06-03-15.42.50.675872"


def test_bgl_reconoce_todos_los_subsistemas_conocidos():
    e = BglEnricher()
    for subsistema, servicio in (("KERNEL", "bgl.kernel"), ("APP", "bgl.app"),
                                 ("MMCS", "bgl.mmcs"), ("DISCOVERY", "bgl.discovery"),
                                 ("HARDWARE", "bgl.hardware")):
        linea = BGL_NORMAL.replace("RAS KERNEL INFO", f"RAS {subsistema} INFO")
        res = preprocesar(linea + "\n", modo="line")
        assert res.events[0].service_name == servicio


# --- criterio 2: una fuente sin perfil completa el flujo ------------------

def test_una_fuente_desconocida_no_necesita_enriquecedor():
    res = preprocesar(DESCONOCIDO + "\n", modo="line")
    ev = res.events[0]
    assert ev.product is None          # ningún perfil aplicó
    assert ev.decoder == "text"
    assert ev.raw == DESCONOCIDO       # y el contenido está intacto


def test_los_enriquecedores_se_pueden_desactivar_por_completo():
    """Control para comparar: el flujo debe funcionar igual sin perfiles."""
    res = preprocesar(HDFS_INFO + "\n", modo="line", aplicar_enriquecedores=False)
    assert res.total_eventos == 1
    assert res.events[0].product is None
    assert res.events[0].raw == HDFS_INFO


def test_ningun_enriquecedor_aplica_a_un_formato_ajeno():
    from src.preprocessing.models import NormalizedEvent
    ev = NormalizedEvent(raw=DESCONOCIDO, message=DESCONOCIDO)
    assert HdfsEnricher().aplica(ev) is False
    assert BglEnricher().aplica(ev) is False
    assert ZeekEnricher().aplica(ev) is False


# --- criterio 3: ningún enriquecedor decide que hay un ataque -------------

def test_hdfs_guarda_el_nivel_como_severidad_no_como_evento_critico():
    """En v1, WARN se traducía a `evento_critico`: una decisión de
    detección tomada dentro del preprocesamiento. Ahora es solo lo que el
    log declara."""
    res = preprocesar(HDFS_WARN + "\n", modo="line")
    ev = res.events[0]
    assert ev.severity == "WARN"
    assert ev.event_category is None
    assert ev.event_outcome is None


def test_el_flag_de_alerta_de_bgl_no_queda_en_ninguna_feature():
    """La fuga que explicaba el F1 = 1.00 sobre BGL: el flag alimentaba
    `evento_critico`, que es lo que el detector observa."""
    res = preprocesar(BGL_ALERTA + "\n", modo="line")
    ev = res.events[0]
    features = {k: v for k, v in ev.to_dict().items() if k != "raw"}
    assert "APPREAD" not in str(features)
    assert ev.event_category is None
    assert ev.event_outcome is None


def test_el_texto_crudo_si_contiene_la_etiqueta_y_por_eso_no_va_al_detector():
    """Preservar el registro original y ocultar la etiqueta se contradicen
    cuando la etiqueta ESTÁ escrita en la línea, como en BGL.

    Se resuelve conservando `raw` —hace falta para auditar y para el
    reporte— y prohibiendo que llegue al detector. Este test deja la vía
    documentada para que la agregación de la Fase 8 no la abra por
    descuido al elegir muestras de texto crudo.
    """
    from src.preprocessing.ground_truth import verificar_aislamiento
    res = preprocesar(BGL_ALERTA + "\n", modo="line")
    assert "APPREAD" in res.events[0].raw          # sí, está en el crudo
    assert verificar_aislamiento(res.events, res.ground_truth) == []
    problemas = verificar_aislamiento(res.events, res.ground_truth, revisar_raw=True)
    assert problemas and "no debe enviarse como muestra" in problemas[0]


def test_dos_eventos_bgl_solo_se_distinguen_por_lo_que_el_log_declara():
    """Con alerta y sin alerta deben producir features del mismo tipo: la
    diferencia vive en el canal de ground truth, no en lo que ve el
    detector."""
    con = preprocesar(BGL_ALERTA + "\n", modo="line").events[0]
    sin = preprocesar(BGL_NORMAL + "\n", modo="line").events[0]
    assert sorted(con.attributes) == sorted(sin.attributes)
    # la severidad sí difiere, pero porque el propio log la declara
    assert con.severity == "FATAL" and sin.severity == "INFO"


def test_zeek_conserva_conn_state_pero_no_las_etiquetas():
    """`conn_state` lo calcula el sensor observando la conexión: es dato
    real. `label_tactic` lo agregaron los curadores: es la respuesta."""
    cabecera = "ts,uid,src_ip,dest_ip,conn_state,label_tactic"
    fila = "1667212800,C123,10.0.0.1,10.0.0.2,REJ,Credential Access"
    res = preprocesar(f"{cabecera}\n{fila}\n", modo="line")
    ev = res.events[0]
    assert ev.event_outcome == "REJ"
    assert ev.attributes["zeek_conexion_establecida"] is False
    assert not [k for k in ev.attributes if "label" in k.lower()]


def test_zeek_no_marca_el_evento_como_ataque_por_su_estado():
    """Una conexión rechazada no es un ataque: es una conexión rechazada."""
    cabecera = "ts,uid,src_ip,dest_ip,conn_state"
    res = preprocesar(f"{cabecera}\n1667212800,C1,10.0.0.1,10.0.0.2,REJ\n", modo="line")
    ev = res.events[0]
    assert ev.event_category == "network"     # categoría, no veredicto
    assert ev.severity is None


# --- orden obligatorio ----------------------------------------------------

def test_el_ground_truth_se_extrae_antes_del_enriquecimiento():
    """`ZeekEnricher.enriquecer()` retira las columnas `label_*`, así que
    invertir el orden dejaría el canal vacío sin que nada falle a la vista.
    Este test fija la secuencia."""
    cabecera = "ts,uid,src_ip,label_tactic"
    res = preprocesar(f"{cabecera}\n1667212800,C9,10.0.0.1,Discovery\n", modo="line")
    assert len(res.ground_truth) == 1
    assert res.ground_truth[0].label == "Discovery"
    assert res.ground_truth[0].key == "C9"     # la clave sale del uid original
    assert not [k for k in res.events[0].attributes if "label" in k.lower()]
