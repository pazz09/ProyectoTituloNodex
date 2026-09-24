"""Tests de la detección heterogénea (Fase 5 del plan).

Criterios de aceptación de la fase:
1. Un lote combinado HDFS, JSON, Syslog y texto se procesa completamente.
2. Los cambios de formato aparecen en `segments`.
3. Los registros no reconocidos terminan en `TextDecoder`.
4. No se comparte estado CSV entre análisis concurrentes.
"""

import pytest

from src.preprocessing.pipeline import PreprocesamientoError, preprocesar

SYSLOG = "<38>Jan 10 13:55:36 srv sshd[1]: Failed password for root from 203.0.113.10 port 22 ssh2"
JSON_L = '{"@timestamp": "2024-01-02T10:00:00Z", "src_ip": "10.0.0.1", "msg": "conexion"}'
HDFS = "081109 203615 148 INFO dfs.DataNode$PacketResponder: PacketResponder 1 for block blk_38865049064139660 terminating"
TEXTO = "esto no se parece a ningun formato conocido"
CEF = "CEF:0|Fortinet|FortiGate|7.0|100|Trafico denegado|8|src=10.0.0.7 dst=10.0.0.8"
KV = "date=2024-01-02 srcip=192.168.1.5 dstip=192.168.1.9 action=deny"

CSV_CABECERA = "ts,src_ip,dest_ip,dest_port,service"
CSV_FILA_1 = "1667212800,10.0.0.1,10.0.0.2,443,https"
CSV_FILA_2 = "1667212801,10.0.0.3,10.0.0.4,22,ssh"


# --- criterio 1: lote combinado se procesa completo -----------------------

def test_lote_mixto_procesa_todos_los_registros():
    """Criterio 1: el lote combinado se procesa completo, sin perder nada."""
    lote = "\n".join([TEXTO, HDFS, JSON_L, SYSLOG, CEF, KV]) + "\n"
    res = preprocesar(lote, modo="line")
    assert res.total_eventos == 6
    assert res.total_lineas_fisicas == 6
    assert all(e.decoder for e in res.events)
    assert all(0.0 <= e.parsing_confidence <= 1.0 for e in res.events)
    # el contenido original de cada línea sigue presente
    for fragmento in (TEXTO, HDFS, JSON_L, SYSLOG, CEF, KV):
        assert any(fragmento in e.raw for e in res.events)


def test_texto_suelto_tras_un_registro_con_timestamp_se_toma_como_continuacion():
    """Ambigüedad conocida y aceptada del diseño.

    Una línea de texto plano después de un registro con timestamp es
    indistinguible de la segunda línea de un stack trace: en ambos casos es
    texto sin estructura detrás de un registro que sí puede extenderse. La
    regla 4 de la segmentación las une, que es lo correcto para el stack
    trace (criterio de la Fase 3) y discutible para un lote heterogéneo.

    Se resuelve a favor de NO perder la relación entre líneas: el contenido
    se conserva íntegro en `raw` y las líneas quedan contabilizadas. Quien
    procese texto suelto intercalado puede desactivar la unión con
    LOG_ENABLE_MULTILINE=false.
    """
    lote = "\n".join([SYSLOG, TEXTO]) + "\n"
    unido = preprocesar(lote, modo="line")
    assert unido.total_eventos == 1
    assert TEXTO in unido.events[0].raw          # no se pierde
    assert unido.events[0].is_multiline is True

    separado = preprocesar(lote, modo="line", enable_multiline=False)
    assert separado.total_eventos == 2
    assert separado.events[1].decoder == "text"


def test_un_formato_autodelimitado_nunca_se_traga_el_registro_siguiente():
    """CEF, LEEF y JSON ocupan exactamente un registro: la línea que sigue
    no puede ser su continuación, sea del formato que sea."""
    for autodelimitado in (CEF, JSON_L, "LEEF:2.0|A|B|1.0|1|^|src=10.0.0.1"):
        res = preprocesar("\n".join([autodelimitado, TEXTO, KV]) + "\n", modo="line")
        assert res.total_eventos == 3, autodelimitado


def test_lote_mixto_asigna_el_decoder_correcto_a_cada_registro():
    lote = "\n".join([JSON_L, SYSLOG, CEF, KV, TEXTO]) + "\n"
    res = preprocesar(lote, modo="line")
    decoders = [e.decoder for e in res.events]
    assert decoders == ["json", "syslog", "cef", "key_value", "text"]


def test_los_campos_se_extraen_de_cada_formato():
    lote = "\n".join([JSON_L, SYSLOG, CEF]) + "\n"
    res = preprocesar(lote, modo="line")
    por_decoder = {e.decoder: e for e in res.events}
    assert por_decoder["json"].source_ip == "10.0.0.1"
    assert por_decoder["syslog"].process_name == "sshd"
    assert por_decoder["cef"].vendor == "Fortinet"
    assert por_decoder["cef"].destination_ip == "10.0.0.8"


# --- criterio 2: los cambios de formato aparecen en segments --------------

def test_formatos_por_segmentos_generan_segmentos_distintos():
    """Dos exportaciones concatenadas: syslog primero, JSON después."""
    lote = "\n".join([SYSLOG] * 3 + [JSON_L] * 3) + "\n"
    res = preprocesar(lote, modo="chunked", chunk_size=3)
    assert [s.decoder for s in res.segments] == ["syslog", "json"]
    assert res.segments[0].line_start == 1 and res.segments[0].line_end == 3
    assert res.segments[1].line_start == 4 and res.segments[1].line_end == 6


def test_cada_segmento_informa_su_confianza_y_cantidad():
    lote = "\n".join([SYSLOG] * 4) + "\n"
    res = preprocesar(lote, modo="chunked", chunk_size=4)
    seg = res.segments[0]
    assert seg.n_records == 4
    assert seg.confidence > 0.5
    assert seg.index == 0


def test_los_eventos_referencian_su_segmento():
    lote = "\n".join([SYSLOG] * 2 + [JSON_L] * 2) + "\n"
    res = preprocesar(lote, modo="chunked", chunk_size=2)
    assert [e.segment_index for e in res.events] == [0, 0, 1, 1]


# --- criterio 3: lo no reconocido cae en TextDecoder ----------------------

def test_texto_desconocido_termina_en_el_decoder_de_texto():
    res = preprocesar(TEXTO + "\n", modo="line")
    assert res.events[0].decoder == "text"
    assert res.events[0].es_fallback is True


def test_auth_log_ya_no_es_el_fallback_universal():
    """En v1, este texto habría recibido servicio y evento de auth-log."""
    res = preprocesar("una linea cualquiera con la palabra sshd\n", modo="line")
    ev = res.events[0]
    assert ev.decoder == "text"
    assert ev.service_name is None


def test_la_cobertura_refleja_cuanto_se_entendio():
    lote = "\n".join([JSON_L, JSON_L, TEXTO, TEXTO]) + "\n"
    res = preprocesar(lote, modo="line")
    assert res.eventos_decodificados == 2
    assert res.eventos_fallback == 2
    assert res.cobertura == 0.5
    assert res.resumen_parsing() == {"parsed_events": 2, "fallback_events": 2,
                                     "coverage": 0.5}


# --- criterio 4: sin estado CSV compartido --------------------------------

def test_dos_csv_con_cabeceras_distintas_en_el_mismo_archivo():
    """La segunda cabecera reemplaza a la primera desde donde aparece."""
    lote = "\n".join([
        CSV_CABECERA, CSV_FILA_1,
        "timestamp,dest_ip,action", "1667212900,10.9.9.9,deny",
    ]) + "\n"
    res = preprocesar(lote, modo="line")
    # las dos cabeceras se reconocen como metadatos, no como eventos
    assert res.total_eventos == 2
    assert res.events[0].source_ip == "10.0.0.1"
    assert res.events[1].destination_ip == "10.9.9.9"
    assert res.events[1].event_action == "deny"
    codigos = [w.codigo for w in res.warnings]
    assert codigos.count("csv_cabecera_detectada") == 2


def test_la_cabecera_csv_no_se_emite_como_evento():
    lote = "\n".join([CSV_CABECERA, CSV_FILA_1, CSV_FILA_2]) + "\n"
    res = preprocesar(lote, modo="line")
    assert res.total_eventos == 2
    assert res.total_lineas_fisicas == 3   # la línea sigue contabilizada


def test_dos_preprocesamientos_simultaneos_no_comparten_cabecera():
    """El contexto vive en el segmento, así que analizar un lote no
    contamina el análisis de otro -- el problema que obligó a instanciar
    el adaptador CSV por lote en el esquema v1."""
    lote_a = "\n".join([CSV_CABECERA, CSV_FILA_1]) + "\n"
    lote_b = "\n".join(["timestamp,dest_ip,action", "1667212900,10.9.9.9,deny"]) + "\n"
    a1 = preprocesar(lote_a, modo="line")
    b1 = preprocesar(lote_b, modo="line")
    a2 = preprocesar(lote_a, modo="line")
    assert a1.events[0].source_ip == a2.events[0].source_ip == "10.0.0.1"
    assert b1.events[0].destination_ip == "10.9.9.9"
    assert a2.events[0].destination_ip == "10.0.0.2"   # no quedó la de b1


# --- modos de parsing -----------------------------------------------------

def test_modo_batch_usa_un_unico_decoder_para_todo_el_lote():
    """Comportamiento v1: sirve de control para comparar."""
    lote = "\n".join([SYSLOG] * 3 + [JSON_L]) + "\n"
    res = preprocesar(lote, modo="batch")
    assert len(res.segments) == 1
    assert res.segments[0].decoder == "syslog"


def test_modo_hybrid_reprocesa_el_registro_que_el_dominante_no_explica():
    """Un JSON intercalado en un bloque mayoritariamente syslog debe
    decodificarse como JSON, no forzarse al decoder dominante. Acá el
    dominante inicial y el efectivo coinciden (syslog sigue siendo
    mayoría incluso entre los eventos ya decodificados) -- el caso donde
    DIVERGEN está en el test siguiente (M3)."""
    lote = "\n".join([SYSLOG] * 4 + [JSON_L]) + "\n"
    res = preprocesar(lote, modo="hybrid", chunk_size=10)
    assert res.segments[0].decoder == "syslog"       # efectivo
    assert res.segments[0].decoder_inicial == "syslog"  # y también el inicial
    decoders = [e.decoder for e in res.events]
    assert decoders == ["syslog"] * 4 + ["json"]     # el intruso se reprocesó
    assert res.events[4].source_ip == "10.0.0.1"


def test_m3_la_etiqueta_del_segmento_refleja_el_resultado_efectivo_no_el_intento_inicial():
    """Hallazgo M3 de la auditoría técnica (23-sep-2026, Fase 4): antes de
    este cierre, `segments[i].decoder` quedaba en el intento INICIAL sobre
    el bloque completo -- acá "json" con confianza 0.5, el decoder que
    "ganó" promediando sobre el bloque entero antes del reproceso -- aunque
    el reproceso individual (hybrid) terminara decodificando la MAYORÍA
    de los eventos del segmento con syslog. Ahora `decoder`/`confidence`
    se recalculan desde los eventos ya decodificados; el intento inicial
    queda aparte, en `decoder_inicial`/`confidence_inicial`, para
    trazabilidad -- no se pierde el dato, solo deja de ser el principal."""
    lote = "\n".join([JSON_L, SYSLOG, TEXTO, JSON_L, SYSLOG]) + "\n"
    res = preprocesar(lote, modo="hybrid", chunk_size=10)

    segmento = res.segments[0]
    assert segmento.decoder_inicial == "json"
    assert segmento.decoder == "syslog"              # efectivo: syslog es mayoría real
    assert segmento.decoder != segmento.decoder_inicial  # el caso que M3 describe
    assert segmento.confidence != segmento.confidence_inicial


def test_modo_chunked_no_reprocesa_y_por_eso_pierde_el_intruso():
    """Contraste explícito con hybrid: mismo lote, distinto resultado."""
    lote = "\n".join([SYSLOG] * 4 + [JSON_L]) + "\n"
    res = preprocesar(lote, modo="chunked", chunk_size=10)
    assert [e.decoder for e in res.events] == ["syslog"] * 5


# --- límites de volumen ---------------------------------------------------

def test_limite_de_eventos_rechaza_el_lote():
    """M6 (Fase 4 del cierre de auditoría, 23-sep-2026): antes truncaba
    con una advertencia; ahora rechaza, la misma política que ya usaba la
    API (HTTP 413) para el límite de bytes -- nunca se analiza "una
    parte" del lote sin que quien lo pidió lo sepa de antemano."""
    lote = "".join(f"{JSON_L}\n" for _ in range(30))
    with pytest.raises(ValueError, match="LOG_MAX_EVENTS"):
        preprocesar(lote, modo="line", max_eventos=10)


def test_limite_de_bytes_rechaza_el_lote():
    lote = "".join(f"{JSON_L}\n" for _ in range(100))
    with pytest.raises(PreprocesamientoError, match="LOG_MAX_FILE_BYTES"):
        preprocesar(lote, modo="line", max_bytes=500)


# --- procedencia ----------------------------------------------------------

def test_el_resultado_registra_la_configuracion_efectiva():
    """Sin esto, dos corridas con salidas distintas no son comparables."""
    res = preprocesar(SYSLOG + "\n", modo="line", chunk_size=7)
    assert res.config["LOG_PARSING_MODE"] == "line"
    assert res.config["LOG_DETECTION_CHUNK_SIZE"] == 7
    assert res.schema_version == "2.0"


def test_la_serializacion_omite_el_ground_truth_por_defecto():
    res = preprocesar(SYSLOG + "\n", modo="line")
    assert "ground_truth" not in res.to_dict()


def test_lote_vacio_no_rompe():
    res = preprocesar("", modo="hybrid")
    assert res.total_eventos == 0
    assert res.segments == []
