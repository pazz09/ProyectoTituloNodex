"""Tests del canal separado de ground truth (Fase 7 del plan).

Criterios de aceptación de la fase:
1. Eliminar las etiquetas no modifica las features de entrada.
2. El detector no recibe ground truth.
3. Las métricas continúan pudiendo calcularse después del análisis.
"""

from src.preprocessing.ground_truth import (
    cargar_labels_csv,
    claves_de_evento,
    etiquetar_eventos,
    verificar_aislamiento,
)
from src.preprocessing.models import GroundTruthRecord, NormalizedEvent
from src.preprocessing.pipeline import preprocesar

BGL_ALERTA = ("APPREAD 1117869872 2005.06.04 R04-M1-N4-I:J18-U11 "
              "2005-06-04-00.24.32.432192 R04-M1-N4-I:J18-U11 RAS APP FATAL "
              "ciod: failed to read message prefix on control stream")
BGL_NORMAL = ("- 1117838570 2005.06.03 R02-M1-N0-C:J12-U11 "
              "2005-06-03-15.42.50.675872 R02-M1-N0-C:J12-U11 RAS KERNEL INFO "
              "instruction cache parity error corrected")


# --- criterio 1: quitar las etiquetas no cambia las features --------------

def test_las_features_son_identicas_con_y_sin_ground_truth():
    """La comprobación literal del criterio: el evento que ve el detector
    no depende de que exista una etiqueta."""
    lote = "\n".join([BGL_ALERTA, BGL_NORMAL]) + "\n"
    res = preprocesar(lote, modo="line")

    con_etiquetas = [
        {k: v for k, v in e.to_dict().items() if k != "raw"} for e in res.events
    ]
    res.ground_truth.clear()          # se elimina el canal por completo
    sin_etiquetas = [
        {k: v for k, v in e.to_dict().items() if k != "raw"} for e in res.events
    ]
    assert con_etiquetas == sin_etiquetas


def test_bgl_no_deja_rastro_de_la_etiqueta_en_las_features():
    lote = "\n".join([BGL_ALERTA, BGL_NORMAL]) + "\n"
    res = preprocesar(lote, modo="line")
    assert verificar_aislamiento(res.events, res.ground_truth) == []


def test_la_deteccion_de_fuga_encuentra_una_etiqueta_plantada():
    """Contraprueba: si la fuga existiera, la verificación debe verla.
    Sin esto, un 'sin problemas' no probaría nada."""
    ev = NormalizedEvent(raw="x", message="x", event_category="Alert")
    etiquetas = [GroundTruthRecord(key="1", label="Alert", source="bgl")]
    problemas = verificar_aislamiento([ev], etiquetas)
    assert problemas and "event_category" in problemas[0]


def test_tambien_detecta_una_columna_de_etiqueta_olvidada_en_attributes():
    ev = NormalizedEvent(raw="x", message="x",
                         attributes={"label_tactic": "Discovery"})
    etiquetas = [GroundTruthRecord(key="1", label="Discovery", source="zeek")]
    problemas = verificar_aislamiento([ev], etiquetas)
    assert any("columna de ground truth" in p for p in problemas)


# --- criterio 2: el detector no recibe ground truth -----------------------

def test_el_resultado_serializado_omite_el_canal_por_defecto():
    res = preprocesar(BGL_ALERTA + "\n", modo="line")
    assert res.ground_truth                      # existe
    assert "ground_truth" not in res.to_dict()   # pero no sale


def test_se_puede_pedir_explicitamente_para_evaluar():
    res = preprocesar(BGL_ALERTA + "\n", modo="line")
    d = res.to_dict(incluir_ground_truth=True)
    assert d["ground_truth"][0]["label"] == "Alert"


# --- criterio 3: las métricas se siguen pudiendo calcular ----------------

def test_bgl_produce_una_etiqueta_por_evento():
    lote = "\n".join([BGL_ALERTA, BGL_NORMAL, BGL_ALERTA]) + "\n"
    res = preprocesar(lote, modo="line")
    etiquetas = [g.label for g in res.ground_truth]
    assert etiquetas == ["Alert", "Normal", "Alert"]


def test_el_mapa_clave_etiqueta_permite_evaluar_despues_del_analisis():
    res = preprocesar("\n".join([BGL_ALERTA, BGL_NORMAL]) + "\n", modo="line")
    mapa = etiquetar_eventos(res.events, res.ground_truth)
    assert mapa == {"1": "Alert", "2": "Normal"}


def test_etiquetar_eventos_no_escribe_nada_en_los_eventos():
    """Devolver el mapa aparte es lo que mantiene la separación."""
    res = preprocesar(BGL_ALERTA + "\n", modo="line")
    antes = res.events[0].to_dict()
    etiquetar_eventos(res.events, res.ground_truth)
    assert res.events[0].to_dict() == antes


# --- etiquetas en archivo aparte (HDFS) -----------------------------------

def test_carga_de_labels_externos_estilo_loglizer(tmp_path):
    csv = tmp_path / "labels.csv"
    csv.write_text("BlockId,Label\nblk_1,Anomaly\nblk_2,Normal\n", encoding="utf-8")
    registros = cargar_labels_csv(csv, scope="bloque")
    assert len(registros) == 2
    assert registros[0].key == "blk_1" and registros[0].label == "Anomaly"
    assert registros[0].scope == "bloque"


def test_carga_de_labels_tolera_otros_nombres_de_columna(tmp_path):
    csv = tmp_path / "labels.csv"
    csv.write_text("key,etiqueta\nabc,attack\n", encoding="utf-8")
    registros = cargar_labels_csv(csv)
    assert registros[0].key == "abc" and registros[0].label == "attack"


def test_las_filas_incompletas_se_saltan_sin_romper(tmp_path):
    csv = tmp_path / "labels.csv"
    csv.write_text("BlockId,Label\nblk_1,Anomaly\n,Normal\nblk_3,\n", encoding="utf-8")
    assert len(cargar_labels_csv(csv)) == 1


def test_hdfs_se_empareja_por_block_id_no_por_linea():
    """El ground truth oficial de HDFS etiqueta bloques, y un lote mezcla
    líneas de muchos bloques: el emparejamiento tiene que ser por la clave
    correcta."""
    linea = ("081109 203615 148 INFO dfs.DataNode$PacketResponder: "
             "PacketResponder 1 for block blk_777 terminating")
    res = preprocesar(linea + "\n", modo="line")
    assert "blk_777" in claves_de_evento(res.events[0])

    externas = [GroundTruthRecord(key="blk_777", label="Anomaly", scope="bloque")]
    assert etiquetar_eventos(res.events, externas) == {"blk_777": "Anomaly"}


def test_un_evento_sin_clave_conocida_no_se_empareja():
    res = preprocesar("texto suelto sin identificadores\n", modo="line")
    externas = [GroundTruthRecord(key="blk_999", label="Anomaly", scope="bloque")]
    assert etiquetar_eventos(res.events, externas) == {}


# --- Zeek / UWF -----------------------------------------------------------

def test_zeek_etiqueta_por_identificador_de_flujo():
    cabecera = "ts,uid,src_ip,label_tactic"
    res = preprocesar(f"{cabecera}\n1667212800,CabC123,10.0.0.1,Credential Access\n",
                      modo="line")
    assert len(res.ground_truth) == 1
    g = res.ground_truth[0]
    assert g.key == "CabC123"
    assert g.label == "Credential Access"
    assert g.source == "zeek"


def test_una_etiqueta_benigna_se_normaliza_a_normal():
    cabecera = "ts,uid,src_ip,label_tactic"
    res = preprocesar(f"{cabecera}\n1667212800,C1,10.0.0.1,none\n", modo="line")
    assert res.ground_truth[0].label == "Normal"


def test_un_csv_sin_columna_de_etiqueta_no_produce_ground_truth():
    """Lo normal en producción: los logs reales no vienen etiquetados."""
    cabecera = "ts,uid,src_ip,conn_state"
    res = preprocesar(f"{cabecera}\n1667212800,C1,10.0.0.1,SF\n", modo="line")
    assert res.ground_truth == []
