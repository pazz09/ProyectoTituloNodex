"""Tests de los modelos normalizados v2 (Fase 1 del plan de preprocesamiento).

Cubren los cuatro criterios de aceptación de la fase:
1. Eventos sin IP, usuario o timestamp son válidos.
2. `raw` y `message` se preservan.
3. La serialización es determinística.
4. Las nuevas pruebas pasan junto con las anteriores (suite completa).

Estos modelos todavía no los consume nadie: el contrato v1 sigue intacto.
"""

import json

import pytest

from src.preprocessing import (
    GroundTruthRecord,
    NormalizedEvent,
    ParsingWarning,
    PreprocessingResult,
    RecordSegment,
)


# --- criterio 1: campos semánticos opcionales -----------------------------

def test_evento_sin_ip_usuario_ni_timestamp_es_valido():
    """El esquema v1 subrepresentaba los registros sin IP. Acá son válidos."""
    ev = NormalizedEvent(raw="algo ocurrio", message="algo ocurrio")
    assert ev.source_ip is None
    assert ev.source_user is None
    assert ev.timestamp is None
    assert ev.decoder == "text"
    assert ev.es_fallback is True


def test_evento_admite_las_dos_puntas_de_un_flujo():
    ev = NormalizedEvent(
        raw="-", message="conexion",
        source_ip="10.0.0.1", source_port=54321,
        destination_ip="10.0.0.2", destination_port=22,
        protocol="tcp", decoder="csv", parsing_confidence=0.9,
    )
    assert ev.source_ip != ev.destination_ip
    assert ev.es_fallback is False


def test_identificador_de_objeto_no_ocupa_el_campo_de_usuario():
    """En v1, un `blk_...` de HDFS se guardaba en `usuario`. Ahora va a
    `attributes`, y `source_user` queda reservado a personas."""
    ev = NormalizedEvent(
        raw="PacketResponder 1 for block blk_123 terminating",
        message="PacketResponder 1 for block blk_123 terminating",
        decoder="text",
        attributes={"block_id": "blk_123"},
    )
    assert ev.source_user is None
    assert ev.attributes["block_id"] == "blk_123"


# --- criterio 2: preservación ---------------------------------------------

def test_raw_y_message_se_preservan_intactos():
    crudo = "  081109 203615 148 INFO dfs.DataNode: algo  "
    ev = NormalizedEvent(raw=crudo, message="algo")
    assert ev.raw == crudo          # sin recortes ni normalización
    assert ev.message == "algo"


def test_campos_no_mapeados_se_conservan_en_attributes():
    ev = NormalizedEvent(
        raw="a=1 b=2 zzz=3", message="a=1 b=2 zzz=3",
        decoder="key_value", parsing_confidence=0.8,
        attributes={"zzz": "3", "a": "1", "b": "2"},
    )
    assert ev.attributes == {"zzz": "3", "a": "1", "b": "2"}


def test_raw_vacio_es_valido_pero_none_no():
    NormalizedEvent(raw="", message="")  # no lanza
    with pytest.raises(ValueError, match="raw no puede ser None"):
        NormalizedEvent(raw=None, message="x")


# --- criterio 3: serialización determinística -----------------------------

def test_serializacion_ordena_attributes_y_es_estable():
    a = NormalizedEvent(raw="x", message="x", attributes={"z": 1, "a": 2, "m": 3})
    b = NormalizedEvent(raw="x", message="x", attributes={"a": 2, "m": 3, "z": 1})
    assert list(a.to_dict()["attributes"]) == ["a", "m", "z"]
    # mismo contenido, distinto orden de inserción -> mismo JSON
    assert json.dumps(a.to_dict()) == json.dumps(b.to_dict())


def test_serializacion_del_resultado_es_estable_entre_llamadas():
    res = PreprocessingResult(
        schema_version="2.0",
        total_lineas_fisicas=3,
        events=[NormalizedEvent(raw="x", message="x", decoder="json",
                                parsing_confidence=1.0)],
        config={"modo": "hybrid", "chunk": 50},
    )
    assert json.dumps(res.to_dict()) == json.dumps(res.to_dict())


def test_advertencias_se_serializan_dentro_del_evento():
    w = ParsingWarning(codigo="campo_desconocido", mensaje="columna sin mapeo",
                       record_number=7, line_start=7)
    ev = NormalizedEvent(raw="x", message="x", warnings=[w])
    d = ev.to_dict()
    assert d["warnings"][0]["codigo"] == "campo_desconocido"
    assert d["warnings"][0]["severidad"] == "warning"


# --- invariantes ----------------------------------------------------------

def test_confianza_fuera_de_rango_es_error_de_programacion():
    with pytest.raises(ValueError, match="entre 0.0 y 1.0"):
        NormalizedEvent(raw="x", message="x", parsing_confidence=1.5)
    with pytest.raises(ValueError, match="entre 0.0 y 1.0"):
        NormalizedEvent(raw="x", message="x", parsing_confidence=-0.1)


def test_severidad_de_advertencia_se_valida():
    with pytest.raises(ValueError, match="severidad inválida"):
        ParsingWarning(codigo="x", mensaje="y", severidad="catastrofico")


def test_segmento_con_rango_de_lineas_invertido_es_error():
    with pytest.raises(ValueError, match="anterior a line_start"):
        RecordSegment(index=0, decoder="json", line_start=10, line_end=4)


def test_segmento_guarda_su_propio_contexto():
    """La cabecera de un CSV vive en el segmento, no en el decoder: eso es
    lo que evita el estado compartido entre análisis concurrentes."""
    seg = RecordSegment(index=0, decoder="csv", line_start=1, line_end=99,
                        context={"cabecera": ["ts", "src_ip"]})
    assert seg.to_dict()["context"]["cabecera"] == ["ts", "src_ip"]


# --- líneas físicas vs. eventos lógicos -----------------------------------

def test_lineas_fisicas_y_eventos_son_contadores_distintos():
    """Un stack trace de 5 líneas es UN evento. En v1 contaba como 5."""
    ev = NormalizedEvent(raw="Traceback...\n  linea\n  linea", message="Traceback...",
                         line_start=10, line_end=14, is_multiline=True)
    res = PreprocessingResult(schema_version="2.0", total_lineas_fisicas=5, events=[ev])
    assert res.total_lineas_fisicas == 5
    assert res.total_eventos == 1


# --- cobertura ------------------------------------------------------------

def test_cobertura_distingue_decodificado_de_fallback():
    eventos = [
        NormalizedEvent(raw="a", message="a", decoder="json", parsing_confidence=1.0),
        NormalizedEvent(raw="b", message="b", decoder="syslog", parsing_confidence=0.9),
        NormalizedEvent(raw="c", message="c"),  # text -> fallback
    ]
    res = PreprocessingResult(schema_version="2.0", total_lineas_fisicas=3, events=eventos)
    assert res.eventos_decodificados == 2
    assert res.eventos_fallback == 1
    assert res.cobertura == round(2 / 3, 4)
    assert res.distribucion_decoders() == {"json": 1, "syslog": 1, "text": 1}


def test_lote_vacio_reporta_cobertura_cero_no_perfecta():
    res = PreprocessingResult(schema_version="2.0")
    assert res.total_eventos == 0
    assert res.cobertura == 0.0


# --- criterio transversal: aislamiento del ground truth --------------------

def test_ground_truth_no_sale_en_la_serializacion_por_defecto():
    """Contramedida a la fuga de etiquetas: pasar el resultado al detector
    no puede exponer el ground truth por descuido."""
    res = PreprocessingResult(
        schema_version="2.0",
        events=[NormalizedEvent(raw="x", message="x")],
        ground_truth=[GroundTruthRecord(key="blk_1", label="Anomaly", scope="bloque")],
    )
    assert "ground_truth" not in res.to_dict()
    assert "ground_truth" in res.to_dict(incluir_ground_truth=True)


def test_ground_truth_sigue_disponible_para_calcular_metricas():
    res = PreprocessingResult(
        schema_version="2.0",
        ground_truth=[
            GroundTruthRecord(key="blk_1", label="Anomaly", scope="bloque"),
            GroundTruthRecord(key="blk_2", label="Normal", scope="bloque"),
        ],
    )
    assert res.ground_truth_por_clave() == {"blk_1": "Anomaly", "blk_2": "Normal"}


def test_ground_truth_exige_clave_y_etiqueta():
    with pytest.raises(ValueError, match="key no puede estar vacía"):
        GroundTruthRecord(key="", label="Anomaly")
    with pytest.raises(ValueError, match="label no puede estar vacía"):
        GroundTruthRecord(key="blk_1", label="")


# --- vista compacta para el estado del grafo ------------------------------

def test_vista_sin_eventos_para_no_inflar_el_estado_de_langgraph():
    res = PreprocessingResult(
        schema_version="2.0", total_lineas_fisicas=2000,
        events=[NormalizedEvent(raw="x", message="x") for _ in range(2000)],
    )
    compacta = res.to_dict(incluir_eventos=False)
    assert "events" not in compacta
    assert compacta["total_eventos"] == 2000  # el contador sí se conserva
