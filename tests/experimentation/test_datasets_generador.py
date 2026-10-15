"""Generación de casos: prevalencia y no reutilización (Fase 2).

**ESCRITAS, NO EJECUTADAS** (ver `tests/experimentation/__init__.py`).
"""

import json

import pytest

from src.experimentation.datasets.agrupacion import GrupoDataset, LineaFuente
from src.experimentation.datasets.generador import (
    EspecificacionCasos,
    escribir_generacion,
    generar_campana,
    generar_casos,
)


def _grupos(n_positivos: int, n_negativos: int) -> list[GrupoDataset]:
    grupos = []
    for i in range(n_positivos):
        grupos.append(GrupoDataset(
            grupo=f"pos_{i:04d}", etiqueta_original="Anomaly", es_positivo=True,
            lineas=(LineaFuente(linea_original=i + 1, contenido=f"linea pos {i}"),),
            miembros=(f"blk_p{i}",)))
    for i in range(n_negativos):
        grupos.append(GrupoDataset(
            grupo=f"neg_{i:04d}", etiqueta_original="Normal", es_positivo=False,
            lineas=(LineaFuente(linea_original=1000 + i, contenido=f"linea neg {i}"),),
            miembros=(f"blk_n{i}",)))
    return grupos


def _espec(**extra) -> EspecificacionCasos:
    base = dict(dataset="hdfs", tipo_deteccion="operativa", particion="evaluacion",
                condicion="natural", n_casos=10, grupos_por_caso=2,
                prevalencia_solicitada=0.5, semilla=1)
    base.update(extra)
    return EspecificacionCasos(**base)


# --- no se fuerza un positivo por lote -----------------------------------

def test_una_prevalencia_que_redondea_a_cero_da_cero_positivos():
    """El generador anterior hacía `max(1, round(...))`: con 16 lotes y
    prevalencia 0,031 producía 1 positivo (0,0625 efectivo) y el informe
    citaba 0,031. Acá el redondeo a cero se respeta y se registra."""
    resultado = generar_casos(_grupos(5, 100),
                              _espec(n_casos=10, prevalencia_solicitada=0.031))
    assert resultado.prevalencia_efectiva["n_casos_positivos"] == 0
    assert resultado.prevalencia_efectiva["efectiva"] == 0.0


def test_la_prevalencia_efectiva_se_registra_junto_a_la_solicitada():
    resultado = generar_casos(_grupos(10, 200),
                              _espec(n_casos=30, prevalencia_solicitada=0.0346))
    prevalencia = resultado.prevalencia_efectiva
    assert prevalencia["solicitada"] == 0.0346
    assert prevalencia["n_casos_positivos"] == 1
    # El manifiesto redondea a 6 decimales (`round(..., 6)` en el generador),
    # así que la tolerancia relativa por omisión de `approx` (1e-6) es más
    # estricta que el propio dato y fallaba por 3,3e-7.
    assert prevalencia["efectiva"] == pytest.approx(1 / 30, abs=1e-6)
    # El delta es lo que el informe tiene que citar si no es cero.
    assert prevalencia["delta_por_redondeo"] != 0


def test_la_prevalencia_balanceada_sale_exacta():
    resultado = generar_casos(_grupos(30, 300), _espec(n_casos=40,
                                                       prevalencia_solicitada=0.5))
    assert resultado.prevalencia_efectiva["efectiva"] == 0.5
    assert resultado.prevalencia_efectiva["delta_por_redondeo"] == 0.0


# --- ningún grupo se reutiliza -------------------------------------------

def test_ningun_grupo_entra_en_dos_casos():
    resultado = generar_casos(_grupos(20, 200), _espec(n_casos=20,
                                                       grupos_por_caso=5))
    usados = [g for caso in resultado.casos for g in caso.grupos]
    assert len(usados) == len(set(usados)) == 20 * 5


def test_grupos_insuficientes_fallan_en_vez_de_reutilizar():
    with pytest.raises(ValueError, match="no reutilizar grupos"):
        generar_casos(_grupos(2, 10), _espec(n_casos=20, grupos_por_caso=5))


def test_positivos_insuficientes_fallan_con_mensaje_propio():
    with pytest.raises(ValueError, match="grupos positivos"):
        generar_casos(_grupos(1, 500), _espec(n_casos=20,
                                              prevalencia_solicitada=0.5))


def test_las_condiciones_tampoco_comparten_grupos():
    """Si la condición balanceada y la natural usaran los mismos grupos, no
    serían dos mediciones independientes."""
    resultados = generar_campana(_grupos(30, 400), [
        _espec(condicion="natural", n_casos=20, prevalencia_solicitada=0.05),
        _espec(condicion="balanceado", n_casos=20, prevalencia_solicitada=0.5),
    ])
    grupos_natural = {g for c in resultados["natural"].casos for g in c.grupos}
    grupos_balanceado = {g for c in resultados["balanceado"].casos for g in c.grupos}
    assert not grupos_natural & grupos_balanceado


def test_una_condicion_repetida_se_rechaza():
    with pytest.raises(ValueError, match="condición repetida"):
        generar_campana(_grupos(30, 400), [_espec(), _espec()])


# --- separación caso / referencia ----------------------------------------

def test_el_caso_no_contiene_la_etiqueta_por_construccion():
    resultado = generar_casos(_grupos(10, 100), _espec())
    for caso in resultado.casos:
        serializado = json.dumps(caso.to_dict())
        assert "Anomaly" not in serializado
        assert "etiqueta" not in serializado


def test_la_referencia_declara_su_procedencia_y_no_es_nodex():
    resultado = generar_casos(_grupos(10, 100), _espec())
    for referencia in resultado.referencias:
        assert referencia.anotacion["fuente"] == "dataset"


def test_el_case_id_lleva_la_condicion_para_no_colisionar():
    natural = generar_casos(_grupos(10, 100), _espec(condicion="natural"))
    balanceado = generar_casos(_grupos(10, 100), _espec(condicion="balanceado"))
    assert not ({c.case_id for c in natural.casos}
                & {c.case_id for c in balanceado.casos})


def test_hdfs_declara_mitre_y_reconstruccion_como_no_aplica():
    """HDFS no trae `uid` estable ni etiquetas ATT&CK: declarar esas
    dimensiones y después puntuarlas sería inventar la referencia."""
    resultado = generar_casos(_grupos(10, 100), _espec())
    caso = resultado.casos[0]
    referencia = resultado.referencias[0]
    assert "mitre" not in caso.dimensiones_aplicables
    assert "reconstruccion" not in caso.dimensiones_aplicables
    assert referencia.estado_dimension["mitre"] == "no_aplica"
    assert referencia.estado_dimension["reconstruccion"] == "no_aplica"


def test_la_procedencia_permite_volver_a_la_linea_original():
    resultado = generar_casos(_grupos(10, 100), _espec(grupos_por_caso=3))
    caso = resultado.casos[0]
    assert len(caso.procedencia) == sum(1 for _ in caso.contenido.splitlines())
    assert [r.indice_en_caso for r in caso.procedencia] == [0, 1, 2]
    assert all(r.linea_original >= 1 for r in caso.procedencia)


def test_las_lineas_del_caso_quedan_en_orden_del_log_original():
    resultado = generar_casos(_grupos(10, 100), _espec(grupos_por_caso=4))
    originales = [r.linea_original for r in resultado.casos[0].procedencia]
    assert originales == sorted(originales)


# --- escritura en disco ---------------------------------------------------

def test_los_casos_y_las_referencias_van_a_directorios_distintos(tmp_path):
    resultado = generar_casos(_grupos(10, 100), _espec(n_casos=4))
    escribir_generacion(resultado, tmp_path)
    assert (tmp_path / "cases" / "hdfs" / "evaluacion").is_dir()
    assert (tmp_path / "ground_truth" / "hdfs" / "evaluacion").is_dir()
    # Ningún archivo de `cases/` puede mencionar la etiqueta.
    for archivo in (tmp_path / "cases").rglob("*"):
        if archivo.is_file():
            assert "Anomaly" not in archivo.read_text(encoding="utf-8")


def test_el_json_del_caso_no_duplica_el_contenido(tmp_path):
    """El contenido vive en el archivo de log; duplicarlo en el JSON haría
    divergir las dos copias."""
    resultado = generar_casos(_grupos(10, 100), _espec(n_casos=2))
    escribir_generacion(resultado, tmp_path)
    meta = json.loads(
        (tmp_path / "cases" / "hdfs" / "evaluacion"
         / f"{resultado.casos[0].case_id}.json").read_text(encoding="utf-8")
    )
    assert "contenido" not in meta
    assert meta["archivo_contenido"].endswith(".log")


# --- validación de la especificación -------------------------------------

def test_condicion_vacia_se_rechaza():
    with pytest.raises(ValueError, match="condicion"):
        _espec(condicion="")


def test_prevalencia_fuera_de_rango_se_rechaza():
    with pytest.raises(ValueError, match="prevalencia_solicitada"):
        _espec(prevalencia_solicitada=1.5)


def test_n_casos_cero_se_rechaza():
    with pytest.raises(ValueError, match="n_casos"):
        _espec(n_casos=0)
