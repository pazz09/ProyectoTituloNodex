"""Presupuesto (src/experimentation/presupuesto.py): costo con tokens medidos y precios de la tabla."""

import json
from pathlib import Path

import pytest

from src.experimentation import presupuesto as pr

PRECIOS = {
    "moneda": "USD", "fecha_de_consulta": "2026-10-15", "fuente": "fuente-de-prueba",
    "modelos": {"m": {"vigencias": [
        {"desde": None, "hasta": "2026-12-31", "entrada_por_millon": 1.0, "salida_por_millon": 10.0},
        {"desde": "2027-01-01", "hasta": None, "entrada_por_millon": 2.0, "salida_por_millon": 20.0}]}}}
V = PRECIOS["modelos"]["m"]["vigencias"][0]


def _llamada(i, o, r):
    return {"model": "m", "input_tokens": i, "output_tokens": o, "reasoning_tokens": r}


def test_el_costo_de_una_corrida_suma_entrada_y_factura_el_razonamiento_como_salida():
    tel = {"llm_calls": [_llamada(1_000_000, 100_000, 400_000), _llamada(500_000, 0, 100_000)]}
    c = pr.costo_de_telemetria(tel, V)
    # entrada 1,5 M × 1 + (salida 100 k + razonamiento 500 k) × 10 = 1,5 + 6
    assert c["usd"] == pytest.approx(7.5) and c["parcial"] is False
    assert (c["llamadas"], c["tokens_entrada"], c["tokens_salida_y_razonamiento"]) == (2, 1_500_000, 600_000)


def test_una_llamada_sin_tokens_hace_el_costo_parcial_y_no_inventa_consumo():
    tel = {"llm_calls": [_llamada(1_000_000, 0, 0),
                         {"model": "m", "input_tokens": None, "output_tokens": None}]}
    c = pr.costo_de_telemetria(tel, V)
    assert c["parcial"] is True and c["llamadas_sin_tokens"] == 1
    assert c["usd"] == pytest.approx(1.0)                  # solo lo que se sabe: un piso


def test_el_razonamiento_ausente_cuenta_como_cero_y_no_invalida_la_llamada():
    c = pr.costo_de_telemetria({"llm_calls": [{"input_tokens": 1_000_000, "output_tokens": 100_000}]}, V)
    assert c["parcial"] is False and c["usd"] == pytest.approx(1.0 + 1.0)


def test_valores_invalidos_no_se_suman():
    c = pr.costo_de_telemetria({"llm_calls": [{"input_tokens": True, "output_tokens": -5}]}, V)
    assert c["parcial"] is True and c["usd"] == 0.0


def test_sin_llamadas_el_costo_es_cero_y_no_es_parcial():
    for tel in (None, {}, {"llm_calls": []}):
        c = pr.costo_de_telemetria(tel, V)
        assert c["usd"] == 0.0 and c["parcial"] is False and c["llamadas"] == 0


def _guardar(raiz, run_id, arq, ds, llamadas, config="cfg", archivo=None):
    ruta = raiz / "experiments" / "telemetry" / ds / (archivo or f"{run_id}.json")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({"config_version": config, "run_id": run_id, "arquitectura": arq,
                                "dataset": ds, "telemetria": {"llm_calls": llamadas}}), encoding="utf-8")


def test_el_gasto_acumulado_suma_todas_las_corridas_de_la_configuracion(tmp_path):
    _guardar(tmp_path, "a", "nodex_multiagente", "bgl", [_llamada(1_000_000, 0, 0)])
    _guardar(tmp_path, "b", "gemini_externo", "uwf", [_llamada(2_000_000, 100_000, 0)])
    _guardar(tmp_path, "c", "baseline_reglas", "bgl", [])
    _guardar(tmp_path, "otra", "nodex_multiagente", "bgl", [_llamada(9_000_000, 0, 0)], config="OTRA")
    g = pr.gasto_acumulado(tmp_path, "cfg", PRECIOS, "m", "2026-10-15")
    assert g["usd"] == pytest.approx(1.0 + 3.0) and g["corridas"] == 3
    assert g["por_corrida"]["c"] == 0.0                    # el baseline no cuesta
    assert "otra" not in g["por_corrida"]                  # nada de otra configuración


def test_los_archivos_de_consultas_y_json_no_se_cuentan_como_corridas(tmp_path):
    _guardar(tmp_path, "a", "nodex_multiagente", "bgl", [_llamada(1_000_000, 0, 0)])
    _guardar(tmp_path, "aux1", "nodex_multiagente", "bgl", [_llamada(1_000_000, 0, 0)],
             archivo="a.consultas_externas.json")
    _guardar(tmp_path, "aux2", "nodex_multiagente", "bgl", [_llamada(1_000_000, 0, 0)],
             archivo="a.llm_json.json")
    g = pr.gasto_acumulado(tmp_path, "cfg", PRECIOS, "m", "2026-10-15")
    assert g["corridas"] == 1 and g["usd"] == pytest.approx(1.0)


def test_el_tope_exacto_no_se_considera_superado(tmp_path):
    """Un costo igual al tope no lo supera: con 1 corrida de 1, 2 o 3 USD, P(> 3) = 0."""
    c = _celdas(tmp_path)
    r = pr.riesgo_de_superar(c, {("nodex_multiagente", "uwf"): 1}, (3.0, 2.0), n_simulaciones=3000)
    assert r["prob_de_superar"]["3.0"] == 0.0
    assert 0.2 < r["prob_de_superar"]["2.0"] < 0.45


def test_el_gasto_marca_las_corridas_con_costo_parcial(tmp_path):
    _guardar(tmp_path, "a", "nodex_multiagente", "bgl",
             [_llamada(1_000_000, 0, 0), {"input_tokens": None, "output_tokens": None}])
    g = pr.gasto_acumulado(tmp_path, "cfg", PRECIOS, "m", "2026-10-15")
    assert g["corridas_con_costo_parcial"] == ["a"]


def test_sin_precio_vigente_no_se_puede_medir_el_gasto_y_falla_en_vez_de_dar_cero(tmp_path):
    _guardar(tmp_path, "a", "nodex_multiagente", "bgl", [_llamada(1, 1, 1)])
    with pytest.raises(ValueError, match="no hay precio vigente"):
        pr.gasto_acumulado(tmp_path, "cfg", {"modelos": {}}, "m", "2026-10-15")


def test_el_gasto_usa_el_precio_de_la_fecha_y_se_duplica_en_2027(tmp_path):
    _guardar(tmp_path, "a", "nodex_multiagente", "bgl", [_llamada(1_000_000, 100_000, 0)])
    antes = pr.gasto_acumulado(tmp_path, "cfg", PRECIOS, "m", "2026-12-31")["usd"]
    despues = pr.gasto_acumulado(tmp_path, "cfg", PRECIOS, "m", "2027-01-01")["usd"]
    assert despues == pytest.approx(2 * antes)


def _celdas(tmp_path):
    for i, usd in enumerate((1.0, 2.0, 3.0)):
        _guardar(tmp_path, f"n{i}", "nodex_multiagente", "uwf", [_llamada(int(usd * 1e6), 0, 0)])
    for i, usd in enumerate((0.5, 0.5)):
        _guardar(tmp_path, f"g{i}", "gemini_externo", "uwf", [_llamada(int(usd * 1e6), 0, 0)])
    _guardar(tmp_path, "b", "baseline_reglas", "uwf", [])
    return pr.costos_por_celda(tmp_path, "cfg", PRECIOS, "m", "2026-10-15")


def test_los_costos_por_celda_dan_minimo_media_y_maximo_y_no_incluyen_al_baseline(tmp_path):
    c = _celdas(tmp_path)
    n = c["nodex_multiagente|uwf"]
    assert (n["n"], n["minimo"], n["media"], n["maximo"]) == (3, 1.0, 2.0, 3.0)
    assert n["valores"] == [1.0, 2.0, 3.0]
    assert "baseline_reglas|uwf" not in c


def test_el_costo_maximo_esperado_usa_el_de_la_celda_o_el_mas_conservador(tmp_path):
    c = _celdas(tmp_path)
    assert pr.costo_maximo_esperado(c, "nodex_multiagente", "uwf") == 3.0
    assert pr.costo_maximo_esperado(c, "nodex_multiagente", "bgl") == 3.0     # sin celda: el de la arquitectura
    assert pr.costo_maximo_esperado(c, "gemini_externo", "hdfs") == 0.5
    assert pr.costo_maximo_esperado(c, "baseline_reglas", "uwf") == 0.0
    assert pr.costo_maximo_esperado({}, "nodex_multiagente", "uwf") == 0.0


def test_el_rango_de_un_plan_suma_minimos_medias_y_maximos_por_celda(tmp_path):
    c = _celdas(tmp_path)
    r = pr.costo_esperado_de_un_plan(c, {("nodex_multiagente", "uwf"): 10, ("gemini_externo", "uwf"): 10,
                                          ("baseline_reglas", "uwf"): 10})
    assert r["minimo"] == pytest.approx(10 * 1.0 + 10 * 0.5)
    assert r["media"] == pytest.approx(10 * 2.0 + 10 * 0.5)
    assert r["maximo"] == pytest.approx(10 * 3.0 + 10 * 0.5)


def test_una_celda_sin_medicion_no_suma_y_se_declara(tmp_path):
    c = _celdas(tmp_path)
    r = pr.costo_esperado_de_un_plan(c, {("nodex_multiagente", "hdfs"): 4})
    assert r["maximo"] == 0.0 and r["celdas_sin_medicion"] == [
        {"arquitectura": "nodex_multiagente", "dataset": "hdfs", "corridas": 4}]


def test_el_riesgo_es_cero_o_uno_si_el_tope_esta_fuera_del_rango_posible(tmp_path):
    c = _celdas(tmp_path)
    plan = {("nodex_multiagente", "uwf"): 4}
    r = pr.riesgo_de_superar(c, plan, (3.0, 20.0), n_simulaciones=2000)
    assert r["prob_de_superar"]["20.0"] == 0.0                # 4 × 3,0 = 12 es el máximo posible
    assert r["prob_de_superar"]["3.0"] > 0.9                  # 4 corridas casi siempre suman más de 3
    assert r["maximo_simulado"] <= 12.0 + 1e-9 and r["p5"] <= r["mediana"] <= r["p95"] <= r["p99"]


def test_el_riesgo_es_reproducible_con_la_semilla_y_cambia_con_otra(tmp_path):
    c = _celdas(tmp_path)
    plan = {("nodex_multiagente", "uwf"): 5}
    a = pr.riesgo_de_superar(c, plan, (7.5, 9.5, 10.5, 11.5), semilla=1, n_simulaciones=1000)
    b = pr.riesgo_de_superar(c, plan, (7.5, 9.5, 10.5, 11.5), semilla=1, n_simulaciones=1000)
    otra = pr.riesgo_de_superar(c, plan, (7.5, 9.5, 10.5, 11.5), semilla=2, n_simulaciones=1000)
    assert a == b and a["semilla"] == 1
    assert a["prob_de_superar"] != otra["prob_de_superar"]


def test_mas_corridas_en_la_celda_mas_cara_aumentan_el_riesgo(tmp_path):
    c = _celdas(tmp_path)
    poco = pr.riesgo_de_superar(c, {("nodex_multiagente", "uwf"): 3}, (6.0,), n_simulaciones=2000)
    mucho = pr.riesgo_de_superar(c, {("nodex_multiagente", "uwf"): 6}, (6.0,), n_simulaciones=2000)
    assert mucho["prob_de_superar"]["6.0"] > poco["prob_de_superar"]["6.0"]
