"""Tests de la agregación v2 y la compatibilidad v1 (Fase 8 del plan).

Criterios de aceptación de la fase:
1. Las pruebas v1 continúan pasando (suite completa).
2. Las pruebas v2 validan cobertura y entidades.
3. Los campos compatibles se derivan desde la misma fuente, sin doble
   parsing.
"""

from src.preprocessing.aggregation import agregar_v2, derivar_v1
from src.preprocessing.pipeline import preprocesar

SYSLOG = ("<38>Jan 10 13:55:36 srv sshd[1]: Failed password for root "
          "from 203.0.113.10 port 22 ssh2")
HDFS = ("081109 214043 2561 WARN dfs.DataNode$DataXceiver: "
        "10.251.30.85:50010:Got exception while serving blk_-2918 to /10.251.90.64:")
BGL_ALERTA = ("APPREAD 1117869872 2005.06.04 R04-M1-N4-I:J18-U11 "
              "2005-06-04-00.24.32.432192 R04-M1-N4-I:J18-U11 RAS APP FATAL "
              "ciod: failed to read message prefix")
CSV = ("ts,uid,src_ip,dest_ip,dest_port,service,conn_state\n"
       "1667212800,C1,192.168.1.50,203.0.113.10,22,ssh,REJ\n"
       "1667212801,C2,192.168.1.50,203.0.113.10,22,ssh,SF\n")


# --- criterio 2: cobertura y entidades ------------------------------------

def test_el_resumen_v2_informa_cobertura_y_fallback():
    # El texto va primero: detrás de un registro con timestamp quedaría
    # unido a él (ambigüedad documentada en la Fase 5).
    res = preprocesar(f"texto sin estructura\n{SYSLOG}\n", modo="line")
    v2 = agregar_v2(res)
    assert v2["parsing"] == {"parsed_events": 1, "fallback_events": 1,
                             "coverage": 0.5}


def test_las_entidades_van_mas_alla_de_las_ips():
    """`por_ip` de v1 dejaba fuera cualquier lote sin direcciones."""
    res = preprocesar(SYSLOG + "\n", modo="line")
    entidades = agregar_v2(res)["entities"]
    assert entidades["ip"] == {"203.0.113.10": 1}
    assert entidades["host"] == {"srv": 1}
    assert entidades["proceso"] == {"sshd": 1}


def test_un_lote_sin_ips_igual_produce_entidades():
    res = preprocesar('{"user": "ana", "process": "cron", "msg": "tarea"}\n',
                      modo="line")
    entidades = agregar_v2(res)["entities"]
    assert entidades["usuario"] == {"ana": 1}
    assert entidades["proceso"] == {"cron": 1}
    assert "ip" not in entidades


def test_las_distribuciones_se_ordenan_por_frecuencia():
    lote = "\n".join(["texto suelto"] + [SYSLOG] * 3) + "\n"
    v2 = agregar_v2(preprocesar(lote, modo="line"))
    assert list(v2["decoder_distribution"]) == ["syslog", "text"]


def test_el_resumen_v2_incluye_segmentos_y_advertencias():
    v2 = agregar_v2(preprocesar(CSV, modo="line"))
    assert isinstance(v2["segments"], list)
    assert any(w["codigo"] == "csv_cabecera_detectada" for w in v2["warnings"])


# --- muestras acotadas ----------------------------------------------------

def test_las_muestras_cubren_un_ejemplo_por_decoder():
    lote = "\n".join([SYSLOG, '{"msg": "x"}', "texto suelto"]) + "\n"
    v2 = agregar_v2(preprocesar(lote, modo="line"))
    assert set(v2["samples"]["por_decoder"]) == {"syslog", "json", "text"}


def test_las_muestras_se_omiten_si_el_lote_trae_ground_truth_embebido():
    """En BGL la etiqueta es el primer token de la línea: mandar el crudo
    al LLM reabriría la fuga que la Fase 7 cerró."""
    v2 = agregar_v2(preprocesar(BGL_ALERTA + "\n", modo="line"))
    assert "por_decoder" not in v2["samples"]
    assert "filtraría la etiqueta" in v2["samples"]["nota"]


def test_sin_ground_truth_las_muestras_si_se_incluyen():
    v2 = agregar_v2(preprocesar(SYSLOG + "\n", modo="line"))
    assert SYSLOG in v2["samples"]["por_decoder"]["syslog"]


# --- criterio 3: v1 se deriva de la misma fuente --------------------------

def test_el_resumen_v1_derivado_tiene_todos_los_campos_del_contrato():
    """El contrato está fijado en docs/preprocessing_baseline.md."""
    v1 = derivar_v1(preprocesar(CSV, modo="line"))
    assert set(v1) == {"formato_detectado", "total_lineas", "servicios",
                       "eventos", "ventana_temporal", "n_ips_distintas",
                       "ips_distintas", "por_ip",
                       # Agregados el 10-sep-2026 para cubrir los elementos
                       # que el §8.7.1 del informe exige en el reporte.
                       "usuarios", "n_usuarios_distintos", "codigos_respuesta",
                       "entidades", "cronologia", "cronologia_omitidos"}


def test_por_ip_conserva_la_forma_que_los_consumidores_esperan():
    v1 = derivar_v1(preprocesar(CSV, modo="line"))
    entrada = v1["por_ip"]["192.168.1.50"]
    assert set(entrada) == {"intentos_fallidos", "usuarios_objetivo",
                            "servicios", "n_eventos", "n_como_origen",
                            "n_como_destino"}
    assert entrada["n_como_origen"] == 2
    assert entrada["n_como_destino"] == 0


def test_las_dos_puntas_del_flujo_siguen_contandose_con_su_rol():
    v1 = derivar_v1(preprocesar(CSV, modo="line"))
    assert v1["por_ip"]["203.0.113.10"]["n_como_destino"] == 2
    assert v1["n_ips_distintas"] == 2


def test_no_hay_doble_parseo_v1_y_v2_salen_del_mismo_agregado():
    """Si divergieran, el sistema diagnosticaría sobre una cosa y
    reportaría otra."""
    res = preprocesar(CSV, modo="line")
    v2 = agregar_v2(res)
    v1 = derivar_v1(res, v2)
    assert v1["ventana_temporal"] == v2["time_window"]
    assert v1["total_lineas"] == v2["total_eventos"]


def test_un_lote_heterogeneo_se_declara_mixto_en_vez_de_elegir_uno():
    """Informar un único formato haría creer que el lote era homogéneo."""
    lote = "\n".join([HDFS, BGL_ALERTA]) + "\n"
    v1 = derivar_v1(preprocesar(lote, modo="line"))
    assert v1["formato_detectado"].startswith("mixto:")


def test_el_formato_usa_el_nombre_del_perfil_no_el_del_producto():
    """v1 nombraba al adaptador ('hdfs'), no al producto comercial."""
    assert derivar_v1(preprocesar(HDFS + "\n", modo="line"))["formato_detectado"] == "hdfs"
    assert derivar_v1(preprocesar(BGL_ALERTA + "\n", modo="line"))["formato_detectado"] == "bgl"


# --- el contador de eventos críticos --------------------------------------

def test_evento_critico_sale_de_la_severidad_declarada_por_el_log():
    """HDFS: un WARN es crítico porque el log lo dice, no porque nadie lo
    haya etiquetado."""
    v1 = derivar_v1(preprocesar(HDFS + "\n", modo="line"))
    assert v1["eventos"] == {"evento_critico": 1}


def test_evento_critico_tambien_sale_del_resultado_de_la_operacion():
    v1 = derivar_v1(preprocesar(CSV, modo="line"))
    assert v1["eventos"]["evento_critico"] == 1   # el REJ
    assert v1["eventos"]["evento_normal"] == 1    # el SF


def test_evento_critico_nunca_sale_de_la_etiqueta_del_dataset():
    """La fuga de BGL. La línea es crítica por declarar FATAL, no por
    traer el flag APPREAD."""
    res = preprocesar(BGL_ALERTA + "\n", modo="line")
    v1 = derivar_v1(res)
    assert v1["eventos"] == {"evento_critico": 1}
    # y el flag no aparece en ninguna parte del resumen
    assert "APPREAD" not in str(v1)


def test_una_linea_bgl_sin_alerta_pero_grave_tambien_cuenta_como_critica():
    """Contraprueba de que la señal ya no es la etiqueta: una línea SIN
    flag de alerta pero con severidad FATAL cuenta igual."""
    sin_flag = BGL_ALERTA.replace("APPREAD", "-", 1)
    res = preprocesar(sin_flag + "\n", modo="line")
    assert res.ground_truth[0].label == "Normal"       # no es alerta
    assert derivar_v1(res)["eventos"] == {"evento_critico": 1}   # pero sí grave


# --- casos límite ---------------------------------------------------------

def test_lote_vacio_produce_un_resumen_valido():
    res = preprocesar("", modo="line")
    v2 = agregar_v2(res)
    v1 = derivar_v1(res, v2)
    assert v1["formato_detectado"] == "desconocido"
    assert v1["total_lineas"] == 0
    assert v1["por_ip"] == {}
    assert v2["entities"] == {}


def test_un_lote_sin_servicios_no_deja_el_campo_vacio():
    """`servicios` alimenta al selector de herramientas: un dict vacío lo
    dejaría sin nada que decidir."""
    v1 = derivar_v1(preprocesar("texto suelto\n", modo="line"))
    assert v1["servicios"] == {"desconocido": 1}
