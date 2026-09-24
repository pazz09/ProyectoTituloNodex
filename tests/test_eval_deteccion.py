"""Tests de la lógica determinística de `src/tools/eval_deteccion.py`:
construcción de lotes de control (BGL, HDFS), cómputo de Precisión/
Recall/F1, y qué campo del estado se usa como predicción. No llama al LLM
ni a `analizar_lote` -- esa parte (la única que gasta cuota real) se corre
manualmente contra la API real, no en CI.
"""

import csv

import src.tools.eval_deteccion as ev
from src.preprocessing.pipeline import PreprocesamientoError


# --- _metricas() ---

def test_metricas_caso_perfecto():
    resultados = [
        {"ground_truth": "anomalo", "prediccion": "anomalo"},
        {"ground_truth": "normal", "prediccion": "normal"},
    ]
    m = ev._metricas(resultados)
    assert m == {"tp": 1, "fp": 0, "fn": 0, "tn": 1, "precision": 1.0, "recall": 1.0, "f1": 1.0,
                "n_evaluados": 2, "n_fallidos": 0}


def test_metricas_con_falsos_positivos_y_negativos():
    # 2 TP, 1 FP, 1 FN, 1 TN
    resultados = (
        [{"ground_truth": "anomalo", "prediccion": "anomalo"}] * 2
        + [{"ground_truth": "normal", "prediccion": "anomalo"}]
        + [{"ground_truth": "anomalo", "prediccion": "normal"}]
        + [{"ground_truth": "normal", "prediccion": "normal"}]
    )
    m = ev._metricas(resultados)
    assert m["tp"] == 2 and m["fp"] == 1 and m["fn"] == 1 and m["tn"] == 1
    assert m["precision"] == 2 / 3
    assert m["recall"] == 2 / 3
    assert abs(m["f1"] - 2 / 3) < 1e-9


def test_metricas_sin_positivos_predichos_precision_none():
    """Si el agente nunca predice 'anomalo', precisión no está definida
    (0/0) -- debe devolver None, no explotar por división por cero."""
    resultados = [
        {"ground_truth": "anomalo", "prediccion": "normal"},
        {"ground_truth": "normal", "prediccion": "normal"},
    ]
    m = ev._metricas(resultados)
    assert m["precision"] is None
    assert m["recall"] == 0.0
    assert m["f1"] is None


def test_metricas_sin_anomalos_reales_recall_none():
    resultados = [
        {"ground_truth": "normal", "prediccion": "normal"},
        {"ground_truth": "normal", "prediccion": "anomalo"},
    ]
    m = ev._metricas(resultados)
    assert m["recall"] is None
    assert m["precision"] == 0.0


def test_metricas_excluye_los_lotes_fallidos_de_la_matriz(monkeypatch):
    """Revisión del camino productivo (cierre de auditoría, 23-sep-2026):
    un lote que falló al preprocesarse no trae 'prediccion' -- no debe
    contar como TN/FN por descarte silencioso, y `n_fallidos` debe dejarlo
    visible en el resultado."""
    resultados = [
        {"ground_truth": "anomalo", "prediccion": "anomalo"},
        {"ground_truth": "normal", "prediccion": "normal"},
        {"ground_truth": "anomalo", "estado": "error", "error_mensaje": "boom"},
    ]
    m = ev._metricas(resultados)
    assert m["tp"] == 1 and m["fp"] == 0 and m["fn"] == 0 and m["tn"] == 1
    assert m["n_evaluados"] == 2
    assert m["n_fallidos"] == 1


# --- _construir_lotes_bgl() ---

def test_construir_lotes_bgl_ground_truth_correcto(tmp_path):
    # 3 ventanas de 2 líneas: la primera sin alerta, la segunda con alerta,
    # la tercera sin alerta.
    contenido = "\n".join([
        "- 100 ts nodo1 ts2 nodo1 RAS KERNEL INFO evento normal 1",
        "- 101 ts nodo1 ts2 nodo1 RAS KERNEL INFO evento normal 2",
        "ALERTA123 200 ts nodo2 ts2 nodo2 RAS KERNEL FATAL evento anomalo",
        "- 201 ts nodo2 ts2 nodo2 RAS KERNEL INFO evento normal 3",
        "- 300 ts nodo3 ts2 nodo3 RAS KERNEL INFO evento normal 4",
        "- 301 ts nodo3 ts2 nodo3 RAS KERNEL INFO evento normal 5",
    ])
    p = tmp_path / "BGL_fake.log"
    p.write_text(contenido, encoding="utf-8")

    lotes = ev._construir_lotes_bgl(p, n_lotes=3, lineas_por_lote=2)
    assert len(lotes) == 3
    por_id = {l["id"]: l for l in lotes}
    assert por_id["bgl_ventana_0000"]["ground_truth"] == "normal"
    assert por_id["bgl_ventana_0001"]["ground_truth"] == "anomalo"
    assert por_id["bgl_ventana_0002"]["ground_truth"] == "normal"


def test_construir_lotes_bgl_respeta_n_lotes_pedido(tmp_path):
    lineas = [f"- {i} ts nodo ts2 nodo RAS KERNEL INFO evento {i}" for i in range(20)]
    p = tmp_path / "BGL_fake.log"
    p.write_text("\n".join(lineas), encoding="utf-8")

    lotes = ev._construir_lotes_bgl(p, n_lotes=3, lineas_por_lote=5)
    assert len(lotes) == 3  # 20/5 = 4 ventanas posibles, pedimos solo 3


# --- _construir_lotes_hdfs() ---

def _fake_hdfs_log(tmp_path):
    """3 bloques: blk_1 (normal, 2 líneas), blk_2 (anomalo, 2 líneas),
    blk_3 (normal, 2 líneas), intercalados como en un archivo real."""
    lineas = [
        "081109 1 1 INFO dfs.DataNode: blk_1 primera linea",
        "081109 2 1 INFO dfs.DataNode: blk_2 primera linea",
        "081109 3 1 INFO dfs.DataNode: blk_3 primera linea",
        "081109 4 1 INFO dfs.DataNode: blk_1 segunda linea",
        "081109 5 1 INFO dfs.DataNode: blk_2 segunda linea",
        "081109 6 1 INFO dfs.DataNode: blk_3 segunda linea",
    ]
    p = tmp_path / "HDFS_fake.log"
    p.write_text("\n".join(lineas), encoding="utf-8")
    return p


def _fake_labels_csv(tmp_path):
    p = tmp_path / "labels.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["BlockId", "Label"])
        w.writerow(["blk_1", "Normal"])
        w.writerow(["blk_2", "Anomaly"])
        w.writerow(["blk_3", "Normal"])
    return p


def test_construir_lotes_hdfs_ground_truth_y_mezcla(tmp_path):
    log = _fake_hdfs_log(tmp_path)
    labels = _fake_labels_csv(tmp_path)

    lotes = ev._construir_lotes_hdfs(log, labels, n_lotes=2, lineas_por_lote=10)
    assert len(lotes) == 2
    positivos = [l for l in lotes if l["ground_truth"] == "anomalo"]
    negativos = [l for l in lotes if l["ground_truth"] == "normal"]
    assert len(positivos) == 1 and len(negativos) == 1
    # el lote positivo debe incluir las líneas de blk_2 (el único anómalo)
    assert "blk_2" in positivos[0]["texto"]
    # el lote negativo NO debe incluir ninguna línea de blk_2
    assert "blk_2" not in negativos[0]["texto"]


def test_construir_lotes_hdfs_preserva_orden_original(tmp_path):
    """Las líneas de un lote deben venir en el orden en que aparecen en el
    archivo original, no agrupadas por bloque -- así el lote se parece a
    un batch real donde los bloques llegan intercalados."""
    log = _fake_hdfs_log(tmp_path)
    labels = _fake_labels_csv(tmp_path)

    # Un solo lote positivo que incluya los 3 bloques (lineas_por_lote alto).
    lotes = ev._construir_lotes_hdfs(log, labels, n_lotes=1, lineas_por_lote=100)
    texto = lotes[0]["texto"]
    lineas = texto.splitlines()
    # Si preserva el orden original, "blk_2 primera linea" debe aparecer
    # ANTES que "blk_1 segunda linea" (tal como en el archivo fuente).
    idx_blk2_primera = next(i for i, l in enumerate(lineas) if "blk_2 primera" in l)
    idx_blk1_segunda = next(i for i, l in enumerate(lineas) if "blk_1 segunda" in l)
    assert idx_blk2_primera < idx_blk1_segunda


def test_construir_lotes_hdfs_sin_anomalos_lanza_error(tmp_path):
    log = _fake_hdfs_log(tmp_path)
    p = tmp_path / "labels_todo_normal.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["BlockId", "Label"])
        w.writerow(["blk_1", "Normal"])
        w.writerow(["blk_2", "Normal"])
        w.writerow(["blk_3", "Normal"])

    try:
        ev._construir_lotes_hdfs(log, p, n_lotes=2, lineas_por_lote=10)
        assert False, "debía lanzar ValueError -- no hay ningún bloque Anomaly"
    except ValueError as e:
        assert "Anomaly" in str(e)


# --- _prediccion_desde_estado() ---
#
# Este es el test que hubiera atrapado el bug real del 3-sep-2026 (ronda
# 1): la primera versión de correr_evaluacion() usaba `confianza` como
# proxy de "hay incidente", lo que confundía "seguro de que todo está
# normal" con "seguro de que hay un ataque". Los casos de abajo son
# exactamente esa confusión, verificada explícitamente.

def test_prediccion_usa_hay_incidente_no_confianza_alta_sin_incidente():
    """El caso real que rompió la primera versión: confianza=1.0 (el
    auditor está seguro de su propio diagnóstico) pero hay_incidente=False
    (el diagnóstico ES que no hay nada anómalo) -- debe predecir 'normal',
    no 'anomalo'."""
    estado = {"hay_incidente": False}
    assert ev._prediccion_desde_estado(estado, confianza=1.0) == "normal"


def test_prediccion_usa_hay_incidente_no_confianza_baja_con_incidente():
    """El caso inverso: confianza baja pero hay_incidente=True -- debe
    predecir 'anomalo', no 'normal'."""
    estado = {"hay_incidente": True}
    assert ev._prediccion_desde_estado(estado, confianza=0.1) == "anomalo"


def test_prediccion_respalda_en_confianza_si_hay_incidente_ausente():
    estado_alta = {}
    estado_baja = {"hay_incidente": None}
    assert ev._prediccion_desde_estado(estado_alta, confianza=0.9) == "anomalo"
    assert ev._prediccion_desde_estado(estado_baja, confianza=0.5) == "normal"


# --- _prediccion_desde_estado() con `campo` (bug real del 3-sep-2026, ronda 2) ---
#
# BGL dio recall 0.0 en la primera corrida real con hay_incidente: el
# auditor distinguía bien una anomalía de hardware de un incidente de
# seguridad, pero BGL/HDFS etiquetan cualquier anomalía de sistema, no solo
# las de seguridad. Los casos de abajo son ese escenario exacto.

def test_prediccion_usa_campo_hay_anomalia_cuando_se_pide():
    """El caso real que rompió la segunda versión: hay_incidente=False
    (correcto -- no es un ataque) pero hay_anomalia=True (también correcto
    -- sí es una anomalía real de hardware). Con campo='hay_anomalia' debe
    predecir 'anomalo'; con el campo por defecto ('hay_incidente') debe
    seguir prediciendo 'normal' -- ambos son "correctos" según lo que cada
    uno mide, y por eso el campo usado debe ser explícito."""
    estado = {"hay_incidente": False, "hay_anomalia": True}
    assert ev._prediccion_desde_estado(estado, confianza=0.9, campo="hay_anomalia") == "anomalo"
    assert ev._prediccion_desde_estado(estado, confianza=0.9, campo="hay_incidente") == "normal"
    assert ev._prediccion_desde_estado(estado, confianza=0.9) == "normal"  # default sigue siendo hay_incidente


def test_campo_veredicto_por_dataset_bgl_y_hdfs_usan_hay_anomalia():
    """BGL y HDFS etiquetan anomalías de sistema, no incidentes de
    seguridad -- deben mapear a 'hay_anomalia', no al default."""
    assert ev.CAMPO_VEREDICTO_POR_DATASET["bgl"] == "hay_anomalia"
    assert ev.CAMPO_VEREDICTO_POR_DATASET["hdfs"] == "hay_anomalia"


# --- `prop_positivos` en _construir_lotes_hdfs() (3-sep-2026, tercera ronda) ---
#
# Recomendación real de la corrida de 8 lotes: los lotes balanceados 50/50
# no representan la prevalencia real de HDFS (~3.1%) -- se agregó
# `prop_positivos` para poder armar también una corrida con prevalencia
# realista, sin tocar el comportamiento por defecto (0.5, igual que antes).

def _fake_hdfs_log_grande(tmp_path):
    """10 bloques: blk_101..blk_104 (4 anómalos, 1 línea c/u), blk_201..blk_206
    (6 normales, 1 línea c/u). Los IDs deben matchear `_BLOQUE_RE`
    (`blk_-?\\d+`) -- por eso son numéricos, no `blk_a1` (que no matchea)."""
    bloques = [f"blk_{100 + i}" for i in range(1, 5)] + [f"blk_{200 + i}" for i in range(1, 7)]
    lineas = [f"081109 {i} 1 INFO dfs.DataNode: {b} unica linea" for i, b in enumerate(bloques)]
    p = tmp_path / "HDFS_grande.log"
    p.write_text("\n".join(lineas), encoding="utf-8")
    return p


def _fake_labels_csv_grande(tmp_path):
    p = tmp_path / "labels_grande.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["BlockId", "Label"])
        for i in range(1, 5):
            w.writerow([f"blk_{100 + i}", "Anomaly"])
        for i in range(1, 7):
            w.writerow([f"blk_{200 + i}", "Normal"])
    return p


def test_construir_lotes_hdfs_prop_positivos_default_es_balanceado(tmp_path):
    """Sin pasar prop_positivos, el comportamiento debe ser idéntico al de
    antes de que existiera el parámetro: balanceado ~50/50."""
    log = _fake_hdfs_log_grande(tmp_path)
    labels = _fake_labels_csv_grande(tmp_path)

    lotes = ev._construir_lotes_hdfs(log, labels, n_lotes=6, lineas_por_lote=5)
    positivos = [l for l in lotes if l["ground_truth"] == "anomalo"]
    assert len(positivos) == 3  # round(6 * 0.5) = 3


def test_construir_lotes_hdfs_prop_positivos_baja_da_menos_positivos(tmp_path):
    """Con prop_positivos baja, deben armarse proporcionalmente menos lotes
    positivos -- para simular la prevalencia real de un dataset (HDFS real:
    ~0.031), en vez del 50/50 por defecto."""
    log = _fake_hdfs_log_grande(tmp_path)
    labels = _fake_labels_csv_grande(tmp_path)

    lotes = ev._construir_lotes_hdfs(log, labels, n_lotes=10, lineas_por_lote=5, prop_positivos=0.2)
    positivos = [l for l in lotes if l["ground_truth"] == "anomalo"]
    assert len(positivos) == 2  # round(10 * 0.2) = 2, hay 4 anómalos disponibles -- no hace falta el piso


def test_construir_lotes_hdfs_prop_positivos_muy_baja_respeta_piso_de_1(tmp_path):
    """Incluso con prop_positivos casi 0, sigue garantizado al menos 1 lote
    positivo si existe algún bloque Anomaly -- mismo piso que ya existía
    para n_lotes chico."""
    log = _fake_hdfs_log_grande(tmp_path)
    labels = _fake_labels_csv_grande(tmp_path)

    lotes = ev._construir_lotes_hdfs(log, labels, n_lotes=10, lineas_por_lote=5, prop_positivos=0.01)
    positivos = [l for l in lotes if l["ground_truth"] == "anomalo"]
    assert len(positivos) == 1  # round(10 * 0.01) = 0, pero el piso lo sube a 1


# --- correr_evaluacion(): un lote que falla no aborta la corrida ----------
#
# Revisión del camino productivo (cierre de auditoría, 23-sep-2026): antes,
# un `PreprocesamientoError` en CUALQUIER lote tumbaba `correr_evaluacion()`
# entero -- se perdían los resultados de los lotes ya evaluados y no
# quedaba ningún registro de cuál había fallado ni por qué.

def test_correr_evaluacion_sigue_tras_un_lote_fallido(tmp_path, monkeypatch):
    lotes_falsos = [
        {"id": "bgl_0", "texto": "log 0", "ground_truth": "normal"},
        {"id": "bgl_1", "texto": "log 1", "ground_truth": "anomalo"},
        {"id": "bgl_2", "texto": "log 2", "ground_truth": "normal"},
    ]
    monkeypatch.setattr(ev, "_construir_lotes_bgl", lambda *a, **k: lotes_falsos)
    monkeypatch.setattr(ev, "_RESULTS_DIR", tmp_path)

    def falso_analizar_lote(texto, thread_id=None):
        if texto == "log 1":
            raise PreprocesamientoError("No se pudo preprocesar el lote (ValueError: boom)")
        return {"confianza": 0.9, "hay_incidente": False, "hay_anomalia": False,
                "diagnostico": "todo normal", "evaluacion_auditor": "ok",
                "comandos_mitigacion": []}
    monkeypatch.setattr(ev, "analizar_lote", falso_analizar_lote)

    salida = ev.correr_evaluacion(dataset="bgl", n_lotes=3, lineas_por_lote=10)

    # Los otros dos lotes se evaluaron igual -- no abortó la corrida.
    assert len(salida["resultados"]) == 3
    fallido = next(r for r in salida["resultados"] if r["id"] == "bgl_1")
    assert fallido["estado"] == "error"
    assert "No se pudo preprocesar el lote" in fallido["error_mensaje"]
    assert "prediccion" not in fallido

    exitosos = [r for r in salida["resultados"] if r["id"] != "bgl_1"]
    assert all(r["estado"] == "completo" for r in exitosos)

    # Excluido explícitamente de la matriz de confusión, y contado.
    assert salida["metricas"]["n_evaluados"] == 2
    assert salida["metricas"]["n_fallidos"] == 1
