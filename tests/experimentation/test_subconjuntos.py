"""Subconjuntos congelados: piloto, rúbrica y evaluación completa.

Verifican dos cosas que importan para que la campaña sea defendible:

1. Que un subconjunto, una vez escrito, no se reescriba en silencio.
2. Que `evaluacion` sea toda la partición de evaluación de los datasets
   principales, sin muestreo y sin HDFS (decisión D-7).
"""

import json
from pathlib import Path

import pytest

from src.experimentation.subconjuntos import (
    escribir_sin_sobrescribir,
    seleccionar_evaluacion,
)

RAIZ = Path(__file__).resolve().parents[2]
EXPERIMENTS = RAIZ / "experiments"


def test_escribir_sin_sobrescribir_crea_el_archivo(tmp_path):
    ruta = tmp_path / "s.json"
    assert escribir_sin_sobrescribir(ruta, {"a": 1}) == "creado"
    assert json.loads(ruta.read_text(encoding="utf-8")) == {"a": 1}


def test_escribir_sin_sobrescribir_reconoce_un_contenido_identico(tmp_path):
    ruta = tmp_path / "s.json"
    escribir_sin_sobrescribir(ruta, {"a": 1})
    assert escribir_sin_sobrescribir(ruta, {"a": 1}) == "identico"


def test_escribir_sin_sobrescribir_falla_si_el_contenido_cambia(tmp_path):
    """Un subconjunto se fija antes de que exista ningún resultado. Una
    regeneración que lo cambie en silencio invalidaría esa garantía."""
    ruta = tmp_path / "s.json"
    escribir_sin_sobrescribir(ruta, {"a": 1})
    with pytest.raises(FileExistsError, match="congelados"):
        escribir_sin_sobrescribir(ruta, {"a": 2})
    assert json.loads(ruta.read_text(encoding="utf-8")) == {"a": 1}


def _ids(sub: dict) -> list[str]:
    return [c for conds in sub["datasets"].values() for d in conds.values()
            for c in d["case_ids"]]


def test_evaluacion_excluye_hdfs_por_la_decision_d7():
    sub = seleccionar_evaluacion(EXPERIMENTS)
    assert set(sub["datasets"]) == {"bgl", "uwf"}


def test_evaluacion_son_todos_los_casos_de_la_particion_sin_muestreo():
    sub = seleccionar_evaluacion(EXPERIMENTS)
    for dataset in ("bgl", "uwf"):
        en_disco = {p.stem for p in
                    (EXPERIMENTS / "cases" / dataset / "evaluacion").glob("*.json")}
        en_subconjunto = {c for d in sub["datasets"][dataset].values()
                          for c in d["case_ids"]}
        assert en_subconjunto == en_disco


def test_evaluacion_solo_trae_casos_de_la_particion_de_evaluacion():
    assert all("_eva_" in c for c in _ids(seleccionar_evaluacion(EXPERIMENTS)))


def test_evaluacion_no_repite_casos():
    ids = _ids(seleccionar_evaluacion(EXPERIMENTS))
    assert len(ids) == len(set(ids))


def test_el_archivo_congelado_coincide_con_lo_que_se_regenera():
    """Determinismo: regenerar da exactamente el archivo versionado."""
    versionado = json.loads(
        (EXPERIMENTS / "subconjuntos" / "evaluacion.json").read_text(encoding="utf-8")
    )
    assert versionado == seleccionar_evaluacion(EXPERIMENTS)


def test_piloto_y_rubrica_no_se_solapan_con_evaluacion_completa_salvo_la_rubrica():
    """El piloto sale de desarrollo: no puede tocar la partición reservada. La
    rúbrica sale de evaluación, así que es un subconjunto de ella."""
    evaluacion = set(_ids(seleccionar_evaluacion(EXPERIMENTS)))
    piloto = set(_ids(json.loads(
        (EXPERIMENTS / "subconjuntos" / "piloto.json").read_text(encoding="utf-8"))))
    rubrica = set(_ids(json.loads(
        (EXPERIMENTS / "subconjuntos" / "rubrica.json").read_text(encoding="utf-8"))))
    assert not piloto & evaluacion
    assert rubrica <= evaluacion
