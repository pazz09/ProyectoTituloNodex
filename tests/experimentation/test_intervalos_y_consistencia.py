"""Intervalos de Wilson y consistencia entre repeticiones (paso 4 de la preparación de la campaña)."""

from types import SimpleNamespace

import pytest

from src.experimentation import consolidacion, estadistica
from src.experimentation.evaluators import deteccion as eval_deteccion


# --- Wilson ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("k, n, inf, sup", [
    (0, 10, 0.0, 0.2775),         # valores de referencia de la tabla de Wilson al 95 %
    (5, 10, 0.2366, 0.7634),
    (8, 10, 0.4902, 0.9433),
    (10, 10, 0.7225, 1.0),
    (1, 2, 0.0945, 0.9055),
])
def test_wilson_coincide_con_valores_de_referencia(k, n, inf, sup):
    lo, hi = estadistica.wilson(k, n)
    assert lo == pytest.approx(inf, abs=5e-4) and hi == pytest.approx(sup, abs=5e-4)


def test_wilson_nunca_se_sale_de_cero_a_uno_y_contiene_la_proporcion():
    for n in range(1, 40):
        for k in range(n + 1):
            lo, hi = estadistica.wilson(k, n)
            assert 0.0 <= lo <= k / n <= hi <= 1.0


def test_con_mas_casos_el_intervalo_es_mas_angosto():
    ancho = lambda n: (lambda i: i[1] - i[0])(estadistica.wilson(n // 2, n))      # noqa: E731
    assert ancho(10) > ancho(40) > ancho(160)


def test_sin_denominador_es_sin_dato_y_no_un_intervalo_de_ceros():
    assert estadistica.wilson(0, 0) is None and estadistica.texto_intervalo(None) is None


def test_aciertos_fuera_de_rango_es_un_error():
    with pytest.raises(ValueError, match="debe estar entre"):
        estadistica.wilson(5, 3)
    with pytest.raises(ValueError, match="debe estar entre"):
        estadistica.wilson(-1, 3)


def test_el_texto_usa_coma_decimal():
    assert estadistica.texto_intervalo((0.4902, 0.9433)) == "0,49 – 0,94"


# --- intervalos en la tabla de detección --------------------------------------------------------

def _conteos(tp, fp, fn, tn):
    return SimpleNamespace(tp=tp, fp=fp, fn=fn, tn=tn, total=tp + fp + fn + tn)


def test_los_intervalos_usan_el_denominador_propio_de_cada_metrica():
    campos = consolidacion._intervalos_d1(_conteos(tp=6, fp=2, fn=1, tn=3))
    assert (campos["accuracy_ic_n"], campos["precision_ic_n"], campos["recall_ic_n"]) == (12, 8, 7)
    esperado = estadistica.wilson(9, 12)
    assert campos["accuracy_ic_inf"] == pytest.approx(esperado[0], abs=1e-6)
    esperado = estadistica.wilson(6, 8)
    assert campos["precision_ic_sup"] == pytest.approx(esperado[1], abs=1e-6)
    esperado = estadistica.wilson(6, 7)
    assert campos["recall_ic_inf"] == pytest.approx(esperado[0], abs=1e-6)


def test_una_metrica_sin_denominador_queda_sin_intervalo():
    campos = consolidacion._intervalos_d1(_conteos(tp=0, fp=0, fn=0, tn=4))
    assert campos["precision_ic"] is None and campos["recall_ic"] is None
    assert campos["accuracy_ic"] is not None


def _reg(case, rep, pred, run=None):
    return SimpleNamespace(case_id=case, repeticion=rep, prediccion=pred, dataset="bgl",
                           arquitectura="nodex_multiagente", run_id=run or f"{case}__{rep}",
                           condicion="x", resultado_d1="TP")


def _grupo_d1(n_celdas=4):
    pares = []
    for i in range(n_celdas):
        pares.append(SimpleNamespace(case_id=f"c{i}", dataset="bgl", arquitectura="nodex_multiagente",
                                     repeticion=1, run_id=f"c{i}", condicion="x", resultado_d1="TP",
                                     prediccion="MALICIOUS", referencia="anomalo", estados={}))
    return pares


def test_la_tabla_de_deteccion_lleva_los_intervalos_y_el_aviso_de_muestras_chicas(monkeypatch):
    registros = _grupo_d1(4)
    monkeypatch.setattr(consolidacion, "construir_deteccion", lambda *a, **k: object())
    tabla, _, _ = consolidacion.tabla_d1(registros)
    claves = [c["clave"] for c in tabla["columnas"]]
    assert {"accuracy_ic", "precision_ic", "recall_ic"} <= set(claves)
    fila = tabla["filas"][0]
    assert fila["accuracy_ic"] and fila["accuracy_ic_inf"] < 1.0       # 4 de 4 NO da [1; 1]
    assert "Muestras chicas" in tabla["aviso"] and "4 corridas" in tabla["aviso"]
    assert "independientes" in tabla["aviso"]


def test_el_aviso_dice_el_rango_real_de_tamanos():
    aviso = consolidacion._aviso_muestras_chicas([{"n_evaluables": 12}, {"n_evaluables": 30}])
    assert "12 a 30 corridas" in aviso
    assert consolidacion._aviso_muestras_chicas([]) is None


# --- consistencia entre repeticiones -----------------------------------------------------------

def _tel(tokens, tiempo):
    return {"total_tokens": tokens, "execution_time": tiempo}


def test_la_concordancia_cuenta_los_casos_con_el_mismo_veredicto_en_todas_las_repeticiones():
    regs = [_reg("a", 1, "MALICIOUS"), _reg("a", 2, "MALICIOUS"),
            _reg("b", 1, "MALICIOUS"), _reg("b", 2, "BENIGN"),
            _reg("c", 1, "BENIGN"), _reg("c", 2, "BENIGN")]
    tel = {r.run_id: _tel(1000, 10.0) for r in regs}
    fila = consolidacion.tabla_consistencia(regs, tel)["filas"][0]
    assert (fila["n_casos"], fila["n_comparables"], fila["n_mismo_veredicto"]) == (3, 3, 2)
    assert fila["concordancia"] == pytest.approx(2 / 3)
    assert fila["concordancia_ic"] == estadistica.texto_intervalo(estadistica.wilson(2, 3))


def test_una_repeticion_sin_veredicto_no_se_compara_ni_cuenta_como_discrepancia():
    regs = [_reg("a", 1, "MALICIOUS"), _reg("a", 2, None),
            _reg("b", 1, "BENIGN"), _reg("b", 2, "BENIGN")]
    fila = consolidacion.tabla_consistencia(regs, {})["filas"][0]
    assert (fila["n_comparables"], fila["n_sin_comparar"], fila["n_mismo_veredicto"]) == (1, 1, 1)
    assert fila["concordancia"] == 1.0


def test_la_variacion_de_tokens_y_tiempo_es_maximo_menos_minimo_sobre_la_media():
    regs = [_reg("a", 1, "MALICIOUS"), _reg("a", 2, "MALICIOUS"),
            _reg("b", 1, "MALICIOUS"), _reg("b", 2, "MALICIOUS")]
    tel = {"a__1": _tel(1000, 10.0), "a__2": _tel(1200, 14.0),     # tokens 200/1100; tiempo 4/12
           "b__1": _tel(2000, 20.0), "b__2": _tel(2000, 20.0)}     # sin variación
    fila = consolidacion.tabla_consistencia(regs, tel)["filas"][0]
    assert fila["tokens_variacion_media_pct"] == pytest.approx((100 * 200 / 1100 + 0) / 2)
    assert fila["tokens_variacion_max_pct"] == pytest.approx(100 * 200 / 1100)
    assert fila["tiempo_variacion_media_pct"] == pytest.approx((100 * 4 / 12 + 0) / 2)
    assert fila["tiempo_variacion_max_pct"] == pytest.approx(100 * 4 / 12)
    assert (fila["n_casos_tokens"], fila["n_casos_tiempo"]) == (2, 2)


def test_tokens_ausentes_no_se_inventan_ni_se_cuentan_como_cero():
    regs = [_reg("a", 1, "MALICIOUS"), _reg("a", 2, "MALICIOUS")]
    fila = consolidacion.tabla_consistencia(regs, {"a__1": _tel(None, 5.0), "a__2": _tel(1000, 5.0)})["filas"][0]
    assert fila["n_casos_tokens"] == 0 and fila["tokens_variacion_media_pct"] is None
    assert fila["tiempo_variacion_media_pct"] == 0.0


def test_sin_repeticiones_no_hay_filas_el_baseline_y_el_piloto_no_aparecen():
    regs = [_reg("a", 1, "MALICIOUS"), _reg("b", 1, "BENIGN")]
    assert consolidacion.tabla_consistencia(regs, {})["filas"] == []


def test_la_tabla_de_consistencia_va_en_la_consolidacion_y_su_aviso_nombra_la_temperatura():
    tabla = consolidacion.tabla_consistencia([_reg("a", 1, "BENIGN"), _reg("a", 2, "BENIGN")], {})
    assert "Temperatura 0" in tabla["descripcion"] and tabla["aviso"] and tabla["seccion"] == "11.1"
