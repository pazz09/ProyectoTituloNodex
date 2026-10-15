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


# --- precios: tabla con vigencias, procedencia y sin supuestos -------------------------------

TABLA = {
    "moneda": "USD", "fecha_de_consulta": "2026-10-15", "fuente": "fuente-de-prueba",
    "modelos": {"m": {"vigencias": [
        {"desde": None, "hasta": "2026-12-31", "entrada_por_millon": 1.0, "salida_por_millon": 10.0},
        {"desde": "2027-01-01", "hasta": None, "entrada_por_millon": 2.0, "salida_por_millon": 20.0},
    ]}},
}


def test_los_precios_del_repositorio_tienen_procedencia_y_las_dos_vigencias():
    precios = est.leer_precios(RAIZ)
    assert precios["fecha_de_consulta"] == "2026-10-15"
    assert precios["fuente"] == "https://ai.google.dev/gemini-api/docs/pricing"
    assert precios["moneda"] == "USD"
    antes = est.precio_vigente(precios, "gemini-3.8-flash", "2026-12-31")
    despues = est.precio_vigente(precios, "gemini-3.8-flash", "2027-01-01")
    assert (antes["entrada_por_millon"], antes["salida_por_millon"]) == (0.75, 3.75)
    assert (despues["entrada_por_millon"], despues["salida_por_millon"]) == (1.5, 7.5)


def test_la_vigencia_se_elige_por_fecha_con_limites_inclusivos():
    assert est.precio_vigente(TABLA, "m", "2026-10-15")["entrada_por_millon"] == 1.0
    assert est.precio_vigente(TABLA, "m", "2026-12-31")["entrada_por_millon"] == 1.0
    assert est.precio_vigente(TABLA, "m", "2027-01-01")["entrada_por_millon"] == 2.0
    assert est.precio_vigente(TABLA, "m", "2030-01-01")["entrada_por_millon"] == 2.0


def test_sin_precio_para_el_modelo_o_la_fecha_no_hay_precio():
    assert est.precio_vigente(TABLA, "otro", "2026-10-15") is None
    sin_inicio = {**TABLA, "modelos": {"m": {"vigencias": [
        {"desde": "2027-01-01", "hasta": None, "entrada_por_millon": 2.0, "salida_por_millon": 20.0}]}}}
    assert est.precio_vigente(sin_inicio, "m", "2026-10-15") is None       # no hay vigencia ese día


def test_una_tabla_sin_fecha_de_consulta_o_fuente_no_da_precios():
    assert est.precio_vigente({**TABLA, "fuente": None}, "m", "2026-10-15") is None
    assert est.precio_vigente({**TABLA, "fecha_de_consulta": None}, "m", "2026-10-15") is None
    assert est.precio_vigente({"modelos": {}}, "m", "2026-10-15") is None


def test_un_precio_incompleto_no_se_completa_con_cero():
    incompleta = {**TABLA, "modelos": {"m": {"vigencias": [
        {"desde": None, "hasta": None, "entrada_por_millon": 1.0, "salida_por_millon": None}]}}}
    assert est.precio_vigente(incompleta, "m", "2026-10-15") is None


def test_el_costo_factura_el_razonamiento_como_salida_con_la_vigencia_de_la_fecha():
    e = est.estimar(_corridas(gemini_externo__bgl=1000))
    c = est.costo(e, TABLA, "gemini-3.8-flash", "2026-10-15")
    assert c["costo"] is None and "sin precio vigente" in c["motivo"]    # el modelo no está en TABLA
    tabla = {**TABLA, "modelos": {"gemini-3.8-flash": TABLA["modelos"]["m"]}}
    antes = est.costo(e, tabla, "gemini-3.8-flash", "2026-10-15")
    despues = est.costo(e, tabla, "gemini-3.8-flash", "2027-02-01")
    entrada, salida = 2731 * 1000 / 1e6, (2260 + 1263) * 1000 / 1e6
    assert antes["costo"] == pytest.approx(round(entrada * 1 + salida * 10, 4))
    assert despues["costo"] == pytest.approx(round(entrada * 2 + salida * 20, 4))
    assert despues["costo"] == pytest.approx(2 * antes["costo"])
    assert antes["fecha_de_precios"] == "2026-10-15" and antes["fuente_de_precios"] == "fuente-de-prueba"


def test_el_costo_no_incluye_las_corridas_sin_medicion_y_lo_dice():
    tabla = {**TABLA, "modelos": {"m": TABLA["modelos"]["m"]}}
    c = est.costo(est.estimar(_corridas(nodex_multiagente__hdfs=10)), tabla, "m", "2026-10-15")
    assert c["costo"] == 0.0 and "solo incluye" in c["nota"]


def _resumen_consumo(filas):
    return {"tablas": {"consumo": {"filas": filas}}}


def _fila(arq, ds, n, entrada, salida, razon, llamadas=1.0):
    return {"arquitectura": arq, "dataset": ds, "n_completas": n, "tokens_entrada_medios": entrada,
            "tokens_salida_medios": salida, "tokens_razonamiento_medios": razon,
            "llamadas_medias": llamadas}


def test_el_costo_real_suma_las_corridas_ejecutadas_y_excluye_al_baseline():
    resumen = _resumen_consumo([
        _fila("nodex_multiagente", "bgl", 8, 1_000_000, 100_000, 200_000, 5.0),
        _fila("gemini_externo", "bgl", 2, 500_000, 50_000, 50_000),
        {"arquitectura": "baseline_reglas", "dataset": "bgl", "n_completas": 8,
         "tokens_entrada_medios": None, "tokens_salida_medios": None,
         "tokens_razonamiento_medios": None, "llamadas_medias": 0.0}])
    r = est.costo_real(resumen, TABLA, "m", "2026-10-15")
    assert r["corridas_con_llm"] == 10 and r["llamadas"] == 42
    assert r["tokens_entrada"] == 9_000_000 and r["tokens_razonamiento"] == 1_700_000
    # entrada 9 M × 1 + (salida 900 k + razonamiento 1,7 M) × 10 = 9 + 26
    assert r["costo"] == pytest.approx(35.0)


def test_el_costo_real_sin_precio_es_none_y_no_cero():
    resumen = _resumen_consumo([_fila("gemini_externo", "bgl", 2, 1, 1, 1)])
    r = est.costo_real(resumen, {"modelos": {}}, "m", "2026-10-15")
    assert r["costo"] is None and r["corridas_con_llm"] == 2


def test_las_mediciones_de_un_resumen_son_medias_por_corrida_y_no_incluyen_al_baseline():
    resumen = _resumen_consumo([_fila("gemini_externo", "bgl", 8, 2759, 1243, 1133),
                                {"arquitectura": "baseline_reglas", "dataset": "bgl",
                                 "n_completas": 8, "tokens_entrada_medios": None}])
    m = est.mediciones_de_un_resumen(resumen)
    assert list(m) == [("gemini_externo", "bgl")] and m[("gemini_externo", "bgl")]["n"] == 8


def test_la_estimacion_de_la_campana_multiplica_casos_por_repeticiones_y_muestra_ambas_vigencias():
    m = {("gemini_externo", "bgl"): {"entrada": 1000, "salida": 100, "razonamiento": 400,
                                     "llamadas": 1.0, "n": 8}}
    c = est.estimar_campana({"bgl": 10}, 3, m, TABLA, "m",
                            {"hasta_2026": "2026-12-01", "desde_2027": "2027-01-15"},
                            ("gemini_externo",))
    (fila,) = c["filas"]
    assert fila["corridas"] == 30 and fila["tokens"] == 30 * 1500
    assert fila["costo"]["hasta_2026"] == pytest.approx(30 * (1000 / 1e6 * 1 + 500 / 1e6 * 10), abs=0.01)
    assert fila["costo"]["desde_2027"] == pytest.approx(2 * fila["costo"]["hasta_2026"], abs=0.02)
    assert "no se presupuesta" in c["baseline"] and "orden de magnitud" in c["es"]


def test_una_celda_sin_medicion_no_suma_y_se_declara_en_la_campana():
    c = est.estimar_campana({"hdfs": 5}, 1, {}, TABLA, "m", {"a": "2026-10-15"},
                            ("nodex_multiagente",))
    assert c["filas"] == [] and c["costo_total"] == {"a": 0.0}
    assert c["celdas_sin_medicion"] == [
        {"arquitectura": "nodex_multiagente", "dataset": "hdfs", "corridas": 5}]


def test_el_archivo_de_precios_es_json_valido_con_la_forma_esperada():
    d = json.loads((RAIZ / "experiments" / "config" / "precios_modelo.json")
                   .read_text(encoding="utf-8"))
    assert {"fecha_de_consulta", "fuente", "moneda", "modelos", "nota_fecha_de_la_fuente"} <= set(d)
