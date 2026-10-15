"""Selección de casos de la campaña (seleccion_campana.py): fija, reproducible y sin etiquetas."""

import json
from pathlib import Path

import pytest

from src.experimentation import seleccion_campana as sc

RAIZ = Path(__file__).resolve().parents[2]


def _sub(**por_estrato):
    datos: dict = {}
    for clave, ids in por_estrato.items():
        d, c = clave.split("__")
        datos.setdefault(d, {})[c] = {"case_ids": list(ids)}
    return {"datasets": datos}


def _universo():
    return _sub(bgl__balanceado=[f"bgl_eva_balanceado_{i:04d}" for i in range(12)],
                bgl__natural=[f"bgl_eva_natural_{i:04d}" for i in range(50)],
                uwf__visible=[f"uwf_eva_visible_{i:04d}" for i in range(40)],
                uwf__sigiloso=[f"uwf_eva_sigiloso_{i:04d}" for i in range(40)])


def _rubrica():
    return _sub(bgl__balanceado=["bgl_eva_balanceado_0001", "bgl_eva_balanceado_0005"],
                bgl__natural=["bgl_eva_natural_0002", "bgl_eva_natural_0016"],
                uwf__visible=["uwf_eva_visible_0004", "uwf_eva_visible_0027"],
                uwf__sigiloso=["uwf_eva_sigiloso_0013"])


def test_los_cupos_son_30_de_bgl_y_10_de_uwf():
    assert sum(n for (d, _), n in sc.CUPOS.items() if d == "bgl") == 30
    assert sum(n for (d, _), n in sc.CUPOS.items() if d == "uwf") == 10


def test_cada_condicion_recibe_su_cupo_y_bgl_balanceado_entra_completo():
    r = sc.seleccionar(_universo(), _rubrica())
    d = r["datasets"]
    assert {c: len(v["case_ids"]) for c, v in d["bgl"].items()} == {"balanceado": 12, "natural": 18}
    assert {c: len(v["case_ids"]) for c, v in d["uwf"].items()} == {"visible": 5, "sigiloso": 5}
    assert r["n_casos"] == 40


def test_entran_todos_los_casos_de_la_rubrica_que_caben_y_se_dice_cuales():
    r = sc.seleccionar(_universo(), _rubrica())
    todos = {c for d in r["datasets"].values() for e in d.values() for c in e["case_ids"]}
    esperados = {c for d in _rubrica()["datasets"].values() for e in d.values() for c in e["case_ids"]}
    assert esperados <= todos
    assert r["casos_de_la_rubrica"]["n_incluidos"] == 7
    assert r["casos_de_la_rubrica"]["fuera_por_cupo"] == []
    assert r["casos_de_la_rubrica"]["incluidos"] == sorted(esperados)


def test_si_los_casos_de_la_rubrica_no_caben_en_el_cupo_se_informan_fuera_y_no_se_ocultan():
    rubrica = _sub(uwf__visible=[f"uwf_eva_visible_{i:04d}" for i in range(7)])
    r = sc.seleccionar(_universo(), rubrica)
    assert len(r["casos_de_la_rubrica"]["fuera_por_cupo"]) == 2
    assert r["casos_de_la_rubrica"]["n_incluidos"] == 5
    assert len(r["datasets"]["uwf"]["visible"]["case_ids"]) == 5


def test_misma_semilla_mismo_resultado_y_otra_semilla_otro_resultado():
    a = sc.seleccionar(_universo(), _rubrica(), semilla=1)
    assert a == sc.seleccionar(_universo(), _rubrica(), semilla=1)
    otra = sc.seleccionar(_universo(), _rubrica(), semilla=2)
    assert a["datasets"]["bgl"]["natural"]["case_ids"] != otra["datasets"]["bgl"]["natural"]["case_ids"]


def test_la_semilla_queda_registrada():
    assert sc.seleccionar(_universo(), _rubrica(), semilla=77)["semilla"] == 77
    assert sc.SEMILLA_SELECCION == 20261015


def test_no_hay_repetidos_y_todo_sale_del_universo():
    r = sc.seleccionar(_universo(), _rubrica())
    ids = [c for d in r["datasets"].values() for e in d.values() for c in e["case_ids"]]
    assert len(ids) == len(set(ids))
    universo = {c for d in _universo()["datasets"].values() for e in d.values() for c in e["case_ids"]}
    assert set(ids) <= universo
    assert all(e["case_ids"] == sorted(e["case_ids"]) for d in r["datasets"].values() for e in d.values())


def test_un_cupo_mayor_que_el_universo_es_un_error_y_no_se_completa_en_silencio():
    with pytest.raises(ValueError, match="mayor que"):
        sc.seleccionar(_universo(), _rubrica(), cupos={("bgl", "balanceado"): 13})
    with pytest.raises(KeyError):
        sc.seleccionar(_universo(), _rubrica(), cupos={("hdfs", "natural"): 1})


def test_la_seleccion_no_depende_del_orden_en_que_vengan_los_ids():
    invertido = _universo()
    for d in invertido["datasets"].values():
        for e in d.values():
            e["case_ids"].reverse()
    assert sc.seleccionar(invertido, _rubrica()) == sc.seleccionar(_universo(), _rubrica())


def test_funciona_sin_ground_truth_ni_cases_porque_no_los_abre(tmp_path):
    carpeta = tmp_path / "experiments" / "subconjuntos"
    carpeta.mkdir(parents=True)
    (carpeta / "evaluacion.json").write_text(json.dumps(_universo()), encoding="utf-8")
    (carpeta / "rubrica.json").write_text(json.dumps(_rubrica()), encoding="utf-8")
    assert sc.generar(tmp_path)["n_casos"] == 40          # no hay experiments/ground_truth ni cases
    assert sc.main(tmp_path) == 0 and (carpeta / "campana_final.json").is_file()
    assert sc.main(tmp_path) == 0                          # idéntico: ni falla ni sobrescribe


def test_el_modulo_no_menciona_ground_truth_en_su_codigo():
    codigo = (RAIZ / "src" / "experimentation" / "seleccion_campana.py").read_text(encoding="utf-8")
    sin_docstring = codigo.split('"""', 2)[2]
    assert "ground_truth" not in sin_docstring.replace("no abre ground_truth", "")
    assert "etiqueta_deteccion" not in sin_docstring


def test_el_subconjunto_generado_sirve_al_planificador_con_dos_repeticiones(tmp_path):
    from src.experimentation import orquestador

    r = sc.seleccionar(_universo(), _rubrica())
    plan = orquestador.planificar(
        tmp_path, r, "cfg-x", ("nodex_multiagente", "baseline_reglas", "gemini_externo"))
    assert plan.resumen()["por_arquitectura"] == {
        "nodex_multiagente": 80, "gemini_externo": 80, "baseline_reglas": 40}


def test_cada_condicion_tiene_su_propia_mezcla_y_no_repite_el_mismo_patron():
    """Dos condiciones del mismo tamaño no deben elegir las mismas posiciones."""
    r = sc.seleccionar(_universo(), _sub())
    posiciones = lambda cond: [int(c[-4:]) for c in r["datasets"]["uwf"][cond]["case_ids"]]      # noqa: E731
    assert posiciones("visible") != posiciones("sigiloso")
