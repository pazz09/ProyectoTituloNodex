"""Tests de la segmentación de registros (Fase 3 del plan).

Criterios de aceptación de la fase:
1. Ninguna línea desaparece sin contabilización.
2. Un stack trace se representa como un evento.
3. Se conservan posiciones y contenido original.
"""

import pytest

from src.preprocessing.segmentation import segmentar

AUTH_LOG = (
    "Jan 10 13:55:36 srv sshd[1]: Failed password for root from 203.0.113.10 port 22 ssh2\n"
    "Jan 10 13:55:39 srv sshd[2]: Failed password for admin from 45.146.0.9 port 22 ssh2\n"
)

STACK_TRACE = (
    "2024-01-02 10:00:00 ERROR Fallo al procesar el lote\n"
    "java.lang.NullPointerException: campo nulo\n"
    "\tat com.ejemplo.Servicio.procesar(Servicio.java:42)\n"
    "\tat com.ejemplo.Main.main(Main.java:11)\n"
    "Caused by: java.io.IOException: disco lleno\n"
    "\t... 3 more\n"
    "2024-01-02 10:00:05 INFO Reintentando\n"
)

JSON_MULTILINEA = (
    '{\n'
    '  "ts": "2024-01-02T10:00:00Z",\n'
    '  "src_ip": "10.0.0.1",\n'
    '  "msg": "algo"\n'
    '}\n'
    '{"ts": "2024-01-02T10:00:01Z", "src_ip": "10.0.0.2"}\n'
)


# --- criterio 1: nada se pierde -------------------------------------------

def test_toda_linea_queda_contabilizada():
    res = segmentar(STACK_TRACE)
    assert res.lineas_contabilizadas == res.total_lineas_fisicas


def test_las_lineas_en_blanco_se_cuentan_pero_no_generan_registros():
    res = segmentar("linea uno\n\n\nlinea dos\n")
    assert res.total_lineas_fisicas == 4
    assert res.lineas_en_blanco == 2
    assert len(res.records) == 2
    assert res.lineas_contabilizadas == 4


def test_lote_vacio_no_rompe():
    res = segmentar("")
    assert res.records == []
    assert res.total_lineas_fisicas == 0


# --- criterio 2: un stack trace es UN evento ------------------------------

def test_stack_trace_es_un_solo_registro():
    """En v1 estas 6 líneas contaban como 6 eventos e inflaban el lote."""
    res = segmentar(STACK_TRACE)
    assert len(res.records) == 2  # el error completo + la línea INFO final

    error = res.records[0]
    assert error.is_multiline is True
    assert error.n_lineas == 6
    assert "NullPointerException" in error.raw
    assert "... 3 more" in error.raw

    assert res.records[1].is_multiline is False
    assert "Reintentando" in res.records[1].raw


def test_marcadores_sin_indentacion_tambien_continuan():
    """`Caused by:` viene sin tabulador en muchos formatos."""
    res = segmentar("ERROR algo fallo\nCaused by: otra cosa\n")
    assert len(res.records) == 1
    assert res.records[0].n_lineas == 2


def test_sin_multilinea_cada_linea_es_un_registro():
    """Control para comparar contra el comportamiento v1."""
    res = segmentar(STACK_TRACE, enable_multiline=False)
    assert len(res.records) == 7
    assert all(r.is_multiline is False for r in res.records)


def test_auth_log_de_una_linea_por_evento_no_se_agrupa():
    res = segmentar(AUTH_LOG)
    assert len(res.records) == 2
    assert all(not r.is_multiline for r in res.records)


# --- criterio 3: posiciones y contenido -----------------------------------

def test_se_conservan_las_lineas_de_inicio_y_fin():
    res = segmentar(STACK_TRACE)
    error = res.records[0]
    assert error.line_start == 1
    assert error.line_end == 6
    assert res.records[1].line_start == 7
    assert res.records[1].line_end == 7


def test_los_registros_se_numeran_en_orden():
    res = segmentar(AUTH_LOG)
    assert [r.record_number for r in res.records] == [1, 2]


def test_el_contenido_original_se_conserva_con_sus_saltos():
    res = segmentar("primera\n\tsegunda\n")
    assert res.records[0].raw == "primera\n\tsegunda"


# --- JSON multilínea ------------------------------------------------------

def test_json_multilinea_es_un_registro_y_el_de_una_linea_otro():
    res = segmentar(JSON_MULTILINEA)
    assert len(res.records) == 2
    assert res.records[0].is_multiline is True
    assert res.records[0].n_lineas == 5
    assert res.records[1].is_multiline is False


def test_llaves_dentro_de_una_cadena_no_abren_un_objeto():
    """`msg="recibido { sin cerrar"` no debe tragarse el resto del archivo."""
    texto = '{"msg": "recibido { sin cerrar"}\nsiguiente linea\n'
    res = segmentar(texto)
    assert len(res.records) == 2
    assert res.records[0].is_multiline is False


def test_json_sin_cerrar_avisa_y_no_arrastra_el_archivo():
    texto = '{\n  "a": 1\n\nlinea posterior\n'
    res = segmentar(texto)
    codigos = [w.codigo for r in res.records for w in r.warnings]
    assert "json_sin_cerrar" in codigos
    # la línea posterior no quedó absorbida por el objeto abierto
    assert any("linea posterior" in r.raw for r in res.records)


def test_json_sin_cerrar_al_final_del_lote_tambien_avisa():
    res = segmentar('{\n  "a": 1\n')
    codigos = [w.codigo for r in res.records for w in r.warnings]
    assert "json_sin_cerrar" in codigos


# --- casos límite ---------------------------------------------------------

def test_continuacion_huerfana_se_emite_sola_y_avisa():
    """Una línea indentada al inicio no tiene a qué unirse: no se descarta."""
    res = segmentar("\tat com.ejemplo.Main(Main.java:1)\nERROR posterior\n")
    assert len(res.records) == 2
    codigos = [w.codigo for w in res.records[0].warnings]
    assert "continuacion_huerfana" in codigos
    assert res.lineas_contabilizadas == res.total_lineas_fisicas


def test_limite_de_eventos_rechaza_el_lote():
    """M6 (Fase 4 del cierre de auditoría, 23-sep-2026): un archivo
    desmedido no debe procesarse en silencio ni "a medias" -- se rechaza,
    no se trunca."""
    texto = "".join(f"linea {i}\n" for i in range(1, 51))
    with pytest.raises(ValueError, match="LOG_MAX_EVENTS"):
        segmentar(texto, max_eventos=10)


def test_sin_limite_no_se_trunca():
    texto = "".join(f"linea {i}\n" for i in range(1, 51))
    res = segmentar(texto)
    assert res.truncado is False
    assert len(res.records) == 50
