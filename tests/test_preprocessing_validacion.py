"""Validación integral del preprocesamiento v2 (Fase 13 del plan).

Cubre las categorías de la batería del §13 que no tenían prueba propia:
líneas corruptas, timestamps incompatibles, y el pipeline/SSE con el LLM
simulado. El resto de las categorías ya está cubierto por los archivos de
cada fase (formatos, multilínea, segmentos, ground truth, compatibilidad v1).
"""

import json

import pytest

import src.pipeline as pipeline_mod
from src.preprocessing.pipeline import preprocesar


# --- líneas corruptas -----------------------------------------------------

def test_una_linea_truncada_a_la_mitad_no_aborta_el_lote():
    lote = ('{"src_ip": "10.0.0.1", "msg": "completa"}\n'
            '{"src_ip": "10.0.0.2", "ms\n'
            '{"src_ip": "10.0.0.3", "msg": "completa"}\n')
    res = preprocesar(lote, modo="line")
    assert res.total_eventos == 3
    assert all(e.raw for e in res.events)      # nada se perdió


def test_bytes_de_control_no_rompen_el_parseo():
    lote = "linea con \x01 control y \x1b escape\notra linea normal\n"
    res = preprocesar(lote, modo="line")
    assert res.total_eventos == 2


def test_una_fila_csv_con_comillas_sin_cerrar_se_reporta():
    lote = ('ts,src_ip,msg\n'
            '1667212800,10.0.0.1,"mensaje sin cerrar\n'
            '1667212801,10.0.0.2,normal\n')
    res = preprocesar(lote, modo="line")
    assert res.total_eventos >= 1
    assert any(e.raw for e in res.events)


def test_un_registro_con_solo_delimitadores_no_lanza():
    res = preprocesar(",,,,\n;;;;\n||||\n", modo="line")
    assert res.total_eventos == 3


def test_caracteres_no_utf8_ya_vienen_reemplazados_y_no_rompen():
    """El runner y la API decodifican con errors='replace', así que acá
    llegan como U+FFFD."""
    res = preprocesar("linea con � byte invalido\n", modo="line")
    assert res.total_eventos == 1


# --- timestamps incompatibles ---------------------------------------------

@pytest.mark.parametrize("valor,esperado_no_none", [
    ("2024-01-02T10:00:00Z", True),
    ("2024-01-02 10:00:00", True),
    ("1667212800", True),                  # epoch en segundos
    ("1.664883645900091E9", True),         # epoch científico (Spark)
    ("1667212800000", True),               # epoch en milisegundos
    ("02/Jan/2024:10:00:00 +0000", True),  # Apache CLF: se conserva como texto
    ("ayer por la tarde", True),           # no interpretable: se conserva
])
def test_formatos_de_timestamp_dispares_no_rompen(valor, esperado_no_none):
    from src.preprocessing.normalization import normalizar_timestamp
    resultado = normalizar_timestamp(valor)
    assert (resultado is not None) is esperado_no_none


def test_un_lote_con_timestamps_de_formatos_distintos_se_procesa():
    lote = ('{"timestamp": "2024-01-02T10:00:00Z", "msg": "a"}\n'
            '{"timestamp": "1667212800", "msg": "b"}\n'
            '{"timestamp": "ayer", "msg": "c"}\n')
    res = preprocesar(lote, modo="line")
    assert res.total_eventos == 3
    assert all(e.timestamp for e in res.events)


def test_un_timestamp_ausente_no_impide_procesar_el_evento():
    res = preprocesar('{"src_ip": "10.0.0.1", "msg": "sin fecha"}\n', modo="line")
    assert res.events[0].timestamp is None
    assert res.events[0].source_ip == "10.0.0.1"


# --- pipeline y SSE con LLM simulado --------------------------------------

class _GrafoFalso:
    """Sustituye al grafo compilado para no llamar al LLM."""

    def __init__(self, actualizaciones):
        self._actualizaciones = actualizaciones
        self._estado = {}

    def stream(self, entrada, config=None, stream_mode=None):
        self._estado = dict(entrada)
        for update in self._actualizaciones:
            for _, salida in update.items():
                self._estado.update(salida)
            yield update

    def get_state(self, config):
        return type("E", (), {"values": self._estado})()


@pytest.fixture
def grafo_simulado(monkeypatch):
    actualizaciones = [
        {"agente_analista_triage": {"necesita_rag": True}},
        {"tool_consultar_rag": {"contexto_rag": [], "tecnicas_mitre": []}},
        {"agente_analista_triage": {"diagnostico": "fuerza bruta SSH",
                                    "necesita_rag": False}},
        {"agente_selector_herramientas": {"usar_cve": False}},
        {"agente_ingeniero_mitigacion": {"comandos_mitigacion": ["iptables -L"],
                                         "intentos_correccion": 1}},
        {"tool_validar_comandos": {"comandos_validos": True}},
        {"agente_auditor_final": {"confianza": 0.9, "hay_anomalia": True,
                                  "hay_incidente": True,
                                  "evaluacion_auditor": "coherente"}},
    ]
    monkeypatch.setattr(pipeline_mod, "get_app",
                        lambda: _GrafoFalso(actualizaciones))
    return actualizaciones


AUTH = ("Jan 10 13:55:36 srv sshd[1]: Failed password for root "
        "from 203.0.113.10 port 22 ssh2\n")


def test_el_streaming_emite_inicio_nodos_y_final(grafo_simulado):
    eventos = list(pipeline_mod.analizar_lote_stream(AUTH, thread_id="t"))
    tipos = [e["tipo"] for e in eventos]
    assert tipos[0] == "inicio"
    assert tipos[-1] == "final"
    assert tipos.count("nodo") == 7


def test_el_evento_inicial_informa_el_preprocesamiento(grafo_simulado):
    """Criterio de la Fase 12: la interfaz debe poder distinguir un parsing
    completo de uno parcial."""
    eventos = list(pipeline_mod.analizar_lote_stream(AUTH, thread_id="t2"))
    inicio = eventos[0]
    assert "preprocesamiento" in inicio
    assert inicio["preprocesamiento"]["parsing"]["coverage"] == 1.0
    assert inicio["preprocesamiento"]["decoder_distribution"] == {"syslog": 1}


def test_el_reporte_final_del_streaming_es_serializable(grafo_simulado):
    eventos = list(pipeline_mod.analizar_lote_stream(AUTH, thread_id="t4"))
    final = eventos[-1]
    json.dumps(final, ensure_ascii=False)      # no lanza
    assert final["reporte"]["confianza"] == 0.9


def test_analizar_lote_devuelve_el_estado_final(grafo_simulado):
    estado = pipeline_mod.analizar_lote(AUTH, thread_id="t5")
    assert estado["diagnostico"] == "fuerza bruta SSH"
    assert estado["requiere_revision_humana"] is False
    assert estado["_firma"].startswith("v2|")


# --- pérdida de información ----------------------------------------------

def test_ninguna_linea_desaparece_en_un_lote_mixto():
    """Métrica de 'pérdida de información' del §13: toda línea física debe
    terminar contabilizada en algún evento."""
    lote = "\n".join([
        "Jan 10 13:55:36 srv sshd[1]: Failed password for root from 1.2.3.4 port 22 ssh2",
        '{"src_ip": "10.0.0.1", "msg": "json"}',
        "CEF:0|A|B|1.0|1|Evento|5|src=10.0.0.2",
        "081109 203615 148 INFO dfs.DataNode: algo blk_1",
        "texto suelto sin estructura",
    ]) + "\n"
    res = preprocesar(lote, modo="line")
    lineas_en_eventos = sum(
        (e.line_end or 0) - (e.line_start or 0) + 1 for e in res.events)
    assert lineas_en_eventos == res.total_lineas_fisicas


def test_el_contenido_original_se_puede_reconstruir():
    lote = "primera linea\nsegunda linea\ntercera linea\n"
    res = preprocesar(lote, modo="line", aplicar_enriquecedores=False)
    reconstruido = "\n".join(e.raw for e in res.events) + "\n"
    assert reconstruido == lote
