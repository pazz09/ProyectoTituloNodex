"""Estimación de tokens del plan (src/experimentation/estimacion.py).

Es un orden de magnitud basado en UNA corrida medida por celda; no se supone ningún
precio. Estas pruebas fijan lo que la estimación puede y no puede afirmar.
"""

import json
from pathlib import Path

import pytest

from src.experimentation import estimacion as est

RAIZ = Path(__file__).resolve().parents[2]


def _corridas(**cuentas):
    out = []
    for clave, n in cuentas.items():
        arquitectura, dataset = clave.split("__")
        out += [{"arquitectura": arquitectura, "dataset": dataset}] * n
    return out


def test_la_estimacion_multiplica_lo_medido_por_el_numero_de_corridas():
    e = est.estimar(_corridas(nodex_multiagente__bgl=3))
    fila = e["filas"][0]
    assert fila["por_corrida"] == {"entrada": 4299, "salida": 1069, "razonamiento": 2226,
                                   "total": 7594}
    assert fila["total_estimado"] == 3 * 7594
    assert e["total_estimado_tokens"] == 3 * 7594


def test_lo_medido_coincide_con_la_tabla_de_resultados_de_la_comparacion():
    """El total de cada celda es entrada + salida + razonamiento, como lo informa la API."""
    for (arq, ds), m in est.MEDICIONES.items():
        assert est._total(m) == {
            ("nodex_multiagente", "bgl"): 7594, ("nodex_multiagente", "uwf"): 69313,
            ("gemini_externo", "bgl"): 6254, ("gemini_externo", "uwf"): 59186}[(arq, ds)]


def test_un_dataset_sin_medicion_queda_sin_medicion_y_no_suma_ni_cero():
    e = est.estimar(_corridas(nodex_multiagente__hdfs=4, nodex_multiagente__bgl=1))
    hdfs = next(f for f in e["filas"] if f["dataset"] == "hdfs")
    assert hdfs["por_corrida"] is None and hdfs["total_estimado"] is None
    assert hdfs["medicion"] == "sin medición"
    assert e["total_estimado_tokens"] == 7594           # solo lo medido
    assert e["corridas_sin_medicion"] == [
        {"arquitectura": "nodex_multiagente", "dataset": "hdfs", "corridas": 4}]


def test_el_baseline_no_usa_el_modelo_y_cuesta_cero_tokens():
    e = est.estimar(_corridas(baseline_reglas__hdfs=4))
    assert e["filas"][0]["total_estimado"] == 0
    assert e["corridas_sin_medicion"] == []


def test_se_declara_que_es_un_orden_de_magnitud_de_una_corrida_por_celda():
    e = est.estimar(_corridas(nodex_multiagente__uwf=1))
    assert "orden de magnitud" in e["es"] and "N=1" in e["es"]
    assert e["filas"][0]["medicion"] == "N=1 corrida medida"


def test_avisa_si_el_modelo_activo_no_es_el_medido():
    assert est.estimar([], "gemini-3.8-flash")["aviso_modelo"] is None
    assert "gemini-3.8-flash" in est.estimar([], "gemini-3.1-pro-preview")["aviso_modelo"]


# --- precios: tabla configurable, sin supuestos ---------------------------------------

def test_la_tabla_de_precios_del_repositorio_viene_vacia_y_no_inventa_un_costo():
    precios = est.leer_precios(RAIZ)
    e = est.estimar(_corridas(nodex_multiagente__bgl=1))
    c = est.costo(e, precios, "gemini-3.8-flash")
    assert c["costo"] is None
    assert "sin precios" in c["motivo"]
    assert precios["fecha"] is None and precios["fuente"] is None


def test_con_precios_pero_sin_fecha_y_fuente_tampoco_hay_costo():
    precios = {"modelos": {"m": {"entrada_por_millon": 1.0, "salida_por_millon": 2.0}}}
    c = est.costo(est.estimar([]), precios, "m")
    assert c["costo"] is None and "fecha y fuente" in c["motivo"]


def test_con_la_tabla_completa_el_costo_factura_el_razonamiento_como_salida():
    precios = {"fecha": "2026-10-15", "fuente": "fuente-de-prueba", "moneda": "USD",
               "modelos": {"gemini-3.8-flash": {"entrada_por_millon": 1.0,
                                                "salida_por_millon": 10.0}}}
    e = est.estimar(_corridas(gemini_externo__bgl=1000))
    c = est.costo(e, precios, "gemini-3.8-flash")
    entrada = 2731 * 1000 / 1e6 * 1.0
    salida = (2260 + 1263) * 1000 / 1e6 * 10.0
    assert c["costo"] == pytest.approx(round(entrada + salida, 4))
    assert c["fecha_de_precios"] == "2026-10-15" and c["fuente_de_precios"] == "fuente-de-prueba"


def test_el_costo_no_incluye_las_corridas_sin_medicion_y_lo_dice():
    precios = {"fecha": "d", "fuente": "f", "moneda": "USD",
               "modelos": {"m": {"entrada_por_millon": 1.0, "salida_por_millon": 1.0}}}
    c = est.costo(est.estimar(_corridas(nodex_multiagente__hdfs=10)), precios, "m")
    assert c["costo"] == 0.0 and "solo incluye" in c["nota"]


def test_el_archivo_de_precios_es_json_valido_con_la_forma_esperada():
    d = json.loads((RAIZ / "experiments" / "config" / "precios_modelo.json")
                   .read_text(encoding="utf-8"))
    assert {"fecha", "fuente", "moneda", "modelos"} <= set(d)
