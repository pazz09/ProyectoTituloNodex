"""Adaptador experimental de NODEX (Fase 4).

**ESCRITAS, NO EJECUTADAS** (ver `tests/experimentation/__init__.py`).

Las tres pruebas que importan más son las que bloquean maneras de fabricar
una capacidad que el sistema no tiene:

1. Derivar el veredicto de `confianza` cuando falta el booleano.
2. Promover una candidata del RAG a atribución del sistema.
3. Entregar la cronología del preprocesamiento como si fuera la
   reconstrucción del sistema multiagente.
"""

import json

import pytest

from src.experimentation.adapters.extraccion import (
    extraer_atribuciones_mitre,
    extraer_candidatas_mitre,
    extraer_cronologia_preprocesamiento,
    extraer_reconstruccion,
    extraer_reporte,
    extraer_veredicto,
)
from src.experimentation.adapters.nodex import (
    adaptar,
    dimension_final,
    preservar_estado_crudo,
)

TODAS = ("deteccion", "reconstruccion", "mitre", "reporte", "consumo")


def _estado(**extra) -> dict:
    base = {
        "hay_incidente": True,
        "hay_anomalia": False,
        "confianza": 0.91,
        "diagnostico": "Escaneo de puertos desde 143.88.18.12 (T1046).",
        "evaluacion_auditor": "El diagnóstico se sostiene con la evidencia.",
        "comandos_mitigacion": ["iptables -A INPUT -s 143.88.18.12 -j DROP"],
        "tecnicas_mitre": [
            {"meta": {"technique_id": "T1046", "name": "Network Service Discovery"},
             "distancia": 0.21},
            {"meta": {"technique_id": "T1021", "name": "Remote Services"},
             "distancia": 0.57},
        ],
        "resumen_logs": {"cronologia": [{"ts": "10:00", "msg": "conn"}],
                         "cronologia_omitidos": 4},
    }
    base.update(extra)
    return base


def _adaptar(estado=None, tipo="seguridad", dimensiones=TODAS):
    return adaptar(
        estado if estado is not None else _estado(),
        case_id="uwf_eva_visible_0000",
        run_id="uwf_eva_visible_0000__nodex__r1__abc123",
        tipo_deteccion=tipo,
        dimensiones_aplicables=dimensiones,
    )


# --- el veredicto nunca se deriva de la confianza ------------------------

def test_sin_el_campo_del_veredicto_la_deteccion_es_no_evaluable():
    estado = _estado()
    del estado["hay_incidente"]
    resultado = _adaptar(estado)
    assert resultado.estado_por_dimension["deteccion"] == "no_evaluable"
    assert resultado.salida.classification is None
    assert "hay_incidente" in resultado.salida.motivo_no_evaluable


def test_un_veredicto_no_booleano_no_se_convierte_con_bool():
    """`confianza=0.0` con veredicto `None` se contaba como predicción
    'normal' y escondía el agotamiento de cuota, que es un fallo de
    ejecución y no una predicción."""
    veredicto, motivo = extraer_veredicto(
        {"hay_incidente": None, "confianza": 0.0}, "seguridad")
    assert veredicto is None
    assert "no es un booleano" in motivo


@pytest.mark.parametrize("valor", ["true", 1, 0.0, "", []])
def test_ningun_valor_no_booleano_pasa_como_veredicto(valor):
    veredicto, motivo = extraer_veredicto(
        {"hay_incidente": valor}, "seguridad")
    assert veredicto is None
    assert motivo


def test_la_confianza_alta_no_salva_un_veredicto_ausente():
    estado = _estado(confianza=0.99)
    del estado["hay_incidente"]
    resultado = _adaptar(estado)
    assert resultado.salida.classification is None


def test_cada_tipo_de_deteccion_lee_su_propio_campo():
    """Comparar `hay_incidente` contra etiquetas de anomalía de sistema mide
    la pregunta equivocada. Ya pasó en este proyecto."""
    estado = _estado(hay_incidente=True, hay_anomalia=False)
    assert _adaptar(estado, tipo="seguridad").salida.classification == "MALICIOUS"
    assert _adaptar(estado, tipo="operativa").salida.classification == "BENIGN"


def test_tipo_de_deteccion_desconocido_se_rechaza():
    veredicto, motivo = extraer_veredicto(_estado(), "semantica")
    assert veredicto is None
    assert "desconocido" in motivo


# --- candidatas del RAG != atribuciones del sistema ---------------------

def test_las_candidatas_del_rag_no_se_promueven_a_atribuciones():
    """Recuperar T1021 porque su texto se parece al log no equivale a
    atribuirla."""
    resultado = _adaptar()
    salida = resultado.salida.to_dict()
    assert salida["mitre"]["techniques"] == []
    assert salida["mitre"]["tactics"] == []
    ids_candidatos = [c["id"] for c in salida["_meta"]["mitre_candidates"]]
    assert ids_candidatos == ["T1046", "T1021"]


def test_la_similitud_se_deriva_de_la_distancia_solo_si_existe():
    candidatas = extraer_candidatas_mitre({"tecnicas_mitre": [
        {"meta": {"technique_id": "T1046"}, "distancia": 0.25},
        {"meta": {"technique_id": "T1110"}},
    ]})
    assert candidatas[0].similitud == pytest.approx(0.75)
    assert candidatas[1].similitud is None


def test_un_id_citado_en_prosa_no_cuenta_como_atribucion():
    """El agente de triage cita IDs dentro del texto de `diagnostico`, sin
    evidencia. Una atribución sin evidence_uids no es puntuable."""
    tacticas, tecnicas, diagnostico = extraer_atribuciones_mitre(_estado())
    assert tacticas == [] and tecnicas == []
    assert diagnostico["fuente"] == "prosa_sin_evidencia"
    assert diagnostico["ids_citados_en_prosa"] == ["T1046"]


def test_mitre_queda_no_evaluable_con_el_contrato_actual():
    resultado = _adaptar()
    assert resultado.estado_por_dimension["mitre"] == "no_evaluable"
    assert "no produce atribuciones" in resultado.diagnostico["mitre"]["motivo"]


def test_con_el_campo_estructurado_la_atribucion_si_cuenta():
    estado = _estado(tecnicas_atribuidas=[
        {"id": "T1046", "nivel": "tecnica", "evidence_uids": ["CxyzA1"]},
        {"id": "Discovery", "nivel": "tactica", "evidence_uids": ["CxyzA1"]},
    ])
    resultado = _adaptar(estado)
    assert resultado.estado_por_dimension["mitre"] == "evaluable"
    salida = resultado.salida.to_dict()
    assert [t["id"] for t in salida["mitre"]["techniques"]] == ["T1046"]
    assert [t["id"] for t in salida["mitre"]["tactics"]] == ["Discovery"]


def test_una_atribucion_estructurada_sin_evidencia_se_descarta():
    estado = _estado(tecnicas_atribuidas=[
        {"id": "T1046", "nivel": "tecnica", "evidence_uids": []},
    ])
    _, tecnicas, diagnostico = extraer_atribuciones_mitre(estado)
    assert tecnicas == []
    assert diagnostico["atribuciones_sin_evidencia"] == ["T1046"]


# --- la cronología del preprocesamiento no es la reconstrucción ---------

def test_la_cronologia_del_preprocesamiento_no_llega_como_reconstruccion():
    """Entregarla como `reconstructed_events` haría que D2 midiera al
    preprocesador y el informe dijera que mide al sistema multiagente."""
    resultado = _adaptar()
    assert resultado.salida.reconstructed_events == []
    assert resultado.salida.temporal_sequence == ()
    assert resultado.estado_por_dimension["reconstruccion"] == "no_evaluable"


def test_la_cronologia_viaja_etiquetada_como_lo_que_es():
    cronologia = extraer_cronologia_preprocesamiento(_estado())
    assert cronologia["omitidos"] == 4
    assert "sin LLM" in cronologia["producida_por"]
    assert "no es" in cronologia


def test_con_el_campo_estructurado_la_reconstruccion_si_cuenta():
    estado = _estado(
        eventos_reconstruidos=[
            {"uid": "CxyzA1", "timestamp": "2022-09-14T16:37:35Z",
             "event_type": "port_scan", "entities": ["143.88.18.12"]},
            {"uid": "CxyzA2", "timestamp": "2022-09-14T16:37:36Z"},
        ],
        secuencia_temporal=["CxyzA1", "CxyzA2"],
    )
    resultado = _adaptar(estado)
    assert resultado.estado_por_dimension["reconstruccion"] == "evaluable"
    assert resultado.salida.temporal_sequence == ("CxyzA1", "CxyzA2")


def test_la_secuencia_descarta_uids_que_no_estan_entre_los_eventos():
    """Un `uid` inventado no puede entrar en la secuencia: rompería el
    contrato y además sería una afirmación falsa."""
    eventos, secuencia, _ = extraer_reconstruccion({
        "eventos_reconstruidos": [{"uid": "CxyzA1"}],
        "secuencia_temporal": ["CxyzA1", "NoExiste9"],
    })
    assert len(eventos) == 1
    assert secuencia == ("CxyzA1",)


# --- reporte --------------------------------------------------------------

def test_el_reporte_se_preserva_tal_cual_para_la_rubrica():
    reporte = extraer_reporte(_estado())
    assert "Escaneo de puertos" in reporte
    assert "El diagnóstico se sostiene" in reporte
    assert "iptables" in reporte


def test_sin_texto_el_reporte_es_no_evaluable():
    estado = _estado(diagnostico="", evaluacion_auditor="",
                     comandos_mitigacion=[])
    resultado = _adaptar(estado)
    assert resultado.salida.report_summary is None
    assert resultado.estado_por_dimension["reporte"] == "no_evaluable"


# --- dimensiones no aplicables -------------------------------------------

def test_una_dimension_fuera_de_las_aplicables_es_no_aplica():
    """HDFS y BGL no declaran MITRE ni reconstrucción: no es un fallo del
    sistema, la dimensión no corresponde al caso."""
    resultado = _adaptar(tipo="operativa",
                         dimensiones=("deteccion", "reporte", "consumo"))
    assert resultado.estado_por_dimension["mitre"] == "no_aplica"
    assert resultado.estado_por_dimension["reconstruccion"] == "no_aplica"
    assert resultado.estado_por_dimension["deteccion"] == "evaluable"


# --- combinación con el estado de la referencia --------------------------

@pytest.mark.parametrize("salida,referencia,esperado", [
    ("evaluable", "evaluable", "evaluable"),
    ("evaluable", "referencia_pendiente", "referencia_pendiente"),
    ("no_evaluable", "evaluable", "no_evaluable"),
    ("evaluable", "no_aplica", "no_aplica"),
    ("no_aplica", "evaluable", "no_aplica"),
    ("fallido", "evaluable", "fallido"),
    ("no_evaluable", "referencia_pendiente", "referencia_pendiente"),
])
def test_se_toma_el_estado_mas_restrictivo(salida, referencia, esperado):
    """Si hay cualquier duda sobre si se puede medir, no se mide."""
    assert dimension_final(salida, referencia) == esperado


# --- preservación del estado crudo ---------------------------------------

def test_el_estado_crudo_se_preserva_y_declara_lo_que_omite(tmp_path):
    destino = tmp_path / "raw" / "uwf_eva_visible_0000__r1.json"
    estado = _estado(raw_samples=["linea cruda 1", "linea cruda 2"])
    ruta = preservar_estado_crudo(estado, destino)
    guardado = json.loads(destino.read_text(encoding="utf-8"))
    assert "raw_samples" not in guardado
    assert guardado["_campos_omitidos_al_preservar"] == ["raw_samples"]
    assert guardado["hay_incidente"] is True
    assert ruta.endswith(".json")


def test_la_salida_referencia_el_crudo_sin_reemplazarlo():
    resultado = adaptar(
        _estado(), case_id="c", run_id="r", tipo_deteccion="seguridad",
        dimensiones_aplicables=TODAS,
        raw_output_ref="outputs/nodex/c__r1.json",
    )
    assert resultado.salida.to_dict()["_meta"]["raw_output_ref"].endswith(".json")


# --- el adaptador no toca el ground truth --------------------------------

def test_el_adaptador_no_acepta_ni_devuelve_ground_truth():
    """Firma deliberadamente sin ground truth: el adaptador trabaja del
    lado del sistema evaluado."""
    import inspect

    parametros = set(inspect.signature(adaptar).parameters)
    assert not {"ground_truth", "referencia", "etiqueta", "etiqueta_deteccion"} & parametros
    serializado = json.dumps(_adaptar().to_dict(), default=str)
    for prohibido in ("etiqueta_deteccion", "core_event_uids", "anotacion"):
        assert prohibido not in serializado
