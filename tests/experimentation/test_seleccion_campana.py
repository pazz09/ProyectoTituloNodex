"""Selección de casos de la campaña (seleccion_campana.py): fija, reproducible y estratificada por etiqueta.

La etiqueta solo se usa en el código de preparación: ningún módulo que ejecute una arquitectura importa
este módulo ni `subconjuntos.py`.
"""

import ast
import json
from pathlib import Path

import pytest

from src.experimentation import seleccion_campana as sc

RAIZ = Path(__file__).resolve().parents[2]
P, N = sc.POSITIVO, sc.NEGATIVO


def _etiquetas():
    """Universo ficticio con la forma de la partición de evaluación: BGL balanceado 12 (6+/6-), natural
    50 (14+), UWF visible 40 (20+) y sigiloso 40 (20+)."""
    def estrato(ds, cond, n, positivos):
        return {f"{ds}_eva_{cond}_{i:04d}": (P if i < positivos else N) for i in range(n)}
    return {("bgl", "balanceado"): estrato("bgl", "balanceado", 12, 6),
            ("bgl", "natural"): estrato("bgl", "natural", 50, 14),
            ("uwf", "visible"): estrato("uwf", "visible", 40, 20),
            ("uwf", "sigiloso"): estrato("uwf", "sigiloso", 40, 20)}


def _rubrica():
    def sub(**por_estrato):
        datos: dict = {}
        for clave, ids in por_estrato.items():
            d, c = clave.split("__")
            datos.setdefault(d, {})[c] = {"case_ids": list(ids)}
        return {"datasets": datos}
    # Positivos: ids con índice < n_positivos de su estrato (ver _etiquetas).
    return sub(bgl__balanceado=["bgl_eva_balanceado_0001", "bgl_eva_balanceado_0005",
                                "bgl_eva_balanceado_0006"],                    # 2 pos (1, 5) y 1 neg (6)
               bgl__natural=["bgl_eva_natural_0002", "bgl_eva_natural_0016", "bgl_eva_natural_0031"],
               uwf__visible=["uwf_eva_visible_0004", "uwf_eva_visible_0027", "uwf_eva_visible_0028"],
               uwf__sigiloso=["uwf_eva_sigiloso_0013", "uwf_eva_sigiloso_0018", "uwf_eva_sigiloso_0024"])


def _ids(r):
    return [c for d in r["datasets"].values() for e in d.values() for c in e["case_ids"]]


def _cuenta(r, etiquetas, dataset, condicion=None):
    ids = [c for cond, e in r["datasets"][dataset].items() if condicion in (None, cond)
           for c in e["case_ids"]]
    por = {P: 0, N: 0}
    for c in ids:
        por[etiquetas[(dataset, c.split("_")[2])][c]] += 1
    return por


def test_los_cupos_son_30_de_bgl_y_10_de_uwf():
    total = lambda ds: sum(n for (d, _), e in sc.CUPOS.items() if d == ds for n in e.values())     # noqa: E731
    assert total("bgl") == 30 and total("uwf") == 10


def test_uwf_queda_con_5_positivos_y_5_negativos_y_5_casos_por_condicion():
    et = _etiquetas()
    r = sc.seleccionar(et, _rubrica())
    assert _cuenta(r, et, "uwf") == {P: 5, N: 5}
    assert {c: len(v["case_ids"]) for c, v in r["datasets"]["uwf"].items()} == {"visible": 5, "sigiloso": 5}


def test_bgl_natural_tiene_8_positivos_y_bgl_balanceado_entra_completo_con_6_y_6():
    et = _etiquetas()
    r = sc.seleccionar(et, _rubrica())
    assert _cuenta(r, et, "bgl", "natural") == {P: 8, N: 10}
    assert _cuenta(r, et, "bgl", "balanceado") == {P: 6, N: 6}
    assert _cuenta(r, et, "bgl") == {P: 14, N: 16} and r["n_casos"] == 40
    assert sorted(r["datasets"]["bgl"]["balanceado"]["case_ids"]) == sorted(et[("bgl", "balanceado")])


def test_el_archivo_lleva_conteos_por_estrato_pero_no_la_etiqueta_de_cada_caso():
    r = sc.seleccionar(_etiquetas(), _rubrica())
    comp = r["datasets"]["uwf"]["visible"]["composicion"]
    assert (comp["positivos"], comp["negativos"]) == (2, 3)
    texto = json.dumps(r)
    assert "etiqueta_deteccion" not in texto and '"uwf_eva_visible_0004": "' not in texto


def test_entran_los_12_casos_de_la_rubrica_y_se_dice_cuales():
    r = sc.seleccionar(_etiquetas(), _rubrica())
    esperados = sorted(c for d in _rubrica()["datasets"].values() for e in d.values() for c in e["case_ids"])
    assert r["casos_de_la_rubrica"]["incluidos"] == esperados and len(esperados) == 12
    assert set(esperados) <= set(_ids(r)) and r["casos_de_la_rubrica"]["fuera_por_cupo"] == []


def test_si_los_casos_de_la_rubrica_de_una_etiqueta_no_caben_se_informan_fuera_y_no_se_ocultan():
    cupos = dict(sc.CUPOS)
    cupos[("uwf", "visible")] = {P: 0, N: 3}               # la rúbrica trae 1 positivo de uwf/visible
    r = sc.seleccionar(_etiquetas(), _rubrica(), cupos=cupos)
    assert r["casos_de_la_rubrica"]["fuera_por_cupo"] and r["casos_de_la_rubrica"]["n_incluidos"] < 12


def test_misma_semilla_mismo_resultado_y_otra_semilla_otro_resultado():
    a = sc.seleccionar(_etiquetas(), _rubrica(), semilla=1)
    assert a == sc.seleccionar(_etiquetas(), _rubrica(), semilla=1)
    assert a["datasets"]["bgl"]["natural"]["case_ids"] != \
        sc.seleccionar(_etiquetas(), _rubrica(), semilla=2)["datasets"]["bgl"]["natural"]["case_ids"]
    assert sc.seleccionar(_etiquetas(), _rubrica(), semilla=77)["semilla"] == 77
    assert sc.SEMILLA_SELECCION == 20261015


def test_no_hay_repetidos_todo_sale_del_universo_y_cada_condicion_va_ordenada():
    r = sc.seleccionar(_etiquetas(), _rubrica())
    ids = _ids(r)
    universo = {c for e in _etiquetas().values() for c in e}
    assert len(ids) == len(set(ids)) and set(ids) <= universo
    assert all(e["case_ids"] == sorted(e["case_ids"]) for d in r["datasets"].values() for e in d.values())


def test_un_cupo_mayor_que_los_casos_de_la_etiqueta_es_un_error_y_no_se_completa_con_la_otra():
    with pytest.raises(ValueError, match="mayor que"):
        sc.seleccionar(_etiquetas(), _rubrica(), cupos={("bgl", "balanceado"): {P: 7, N: 6}})
    with pytest.raises(KeyError):
        sc.seleccionar(_etiquetas(), _rubrica(), cupos={("hdfs", "natural"): {P: 1, N: 1}})


def test_la_seleccion_no_depende_del_orden_del_universo():
    invertido = {k: dict(reversed(list(v.items()))) for k, v in _etiquetas().items()}
    assert sc.seleccionar(invertido, _rubrica()) == sc.seleccionar(_etiquetas(), _rubrica())


def test_cada_estrato_tiene_su_propia_mezcla():
    r = sc.seleccionar(_etiquetas(), _rubrica())
    pos = lambda cond: [int(c[-4:]) for c in r["datasets"]["uwf"][cond]["case_ids"]]       # noqa: E731
    assert pos("visible") != pos("sigiloso")


def test_generar_y_main_usan_la_rubrica_y_no_sobrescriben(tmp_path):
    carpeta = tmp_path / "experiments" / "subconjuntos"
    carpeta.mkdir(parents=True)
    (carpeta / "rubrica.json").write_text(json.dumps(_rubrica()), encoding="utf-8")
    assert sc.generar(tmp_path, etiquetas=_etiquetas())["n_casos"] == 40
    sc.leer_etiquetas = lambda raiz, datasets=("bgl", "uwf"): _etiquetas()
    try:
        assert sc.main(tmp_path, nombre="prueba") == 0 and (carpeta / "prueba.json").is_file()
        assert sc.main(tmp_path, nombre="prueba") == 0          # idéntico: ni falla ni sobrescribe
    finally:
        import importlib
        importlib.reload(sc)


def test_el_subconjunto_generado_sirve_al_planificador_con_dos_repeticiones(tmp_path):
    from src.experimentation import orquestador

    r = sc.seleccionar(_etiquetas(), _rubrica())
    plan = orquestador.planificar(
        tmp_path, r, "cfg-x", ("nodex_multiagente", "baseline_reglas", "gemini_externo"))
    assert plan.resumen()["por_arquitectura"] == {
        "nodex_multiagente": 80, "gemini_externo": 80, "baseline_reglas": 40}


# --- la etiqueta no entra al código que ejecuta las arquitecturas --------------------------------------------

MODULOS_DE_EJECUCION = (
    ["src/experimentation/campana.py", "src/experimentation/orquestador.py",
     "src/experimentation/presupuesto.py", "src/experimentation/comparacion_modelos.py"]
    + [str(p.relative_to(RAIZ)).replace("\\", "/") for p in
       list((RAIZ / "src/experimentation/runners").glob("*.py")) + list((RAIZ / "src/agents").glob("*.py"))
       + list((RAIZ / "src/tools").glob("*.py")) + list((RAIZ / "src/experimentation/runtime").glob("*.py"))
       # `configuracion.py` (el congelado) importa constantes de semillas de los módulos de preparación:
       # corre al congelar, no al ejecutar una arquitectura. Es la única excepción.
       if p.name != "configuracion.py"])


def _importa(ruta: str) -> set[str]:
    arbol = ast.parse((RAIZ / ruta).read_text(encoding="utf-8"))
    nombres = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            nombres |= {a.name for a in nodo.names}
        elif isinstance(nodo, ast.ImportFrom):
            base = nodo.module or ""
            nombres.add(base)
            nombres |= {f"{base}.{a.name}" for a in nodo.names}
    return nombres


def test_ningun_modulo_de_ejecucion_importa_la_preparacion_que_lee_etiquetas():
    prohibidos = {"src.experimentation.seleccion_campana", "src.experimentation.subconjuntos"}
    for ruta in MODULOS_DE_EJECUCION:
        assert not (_importa(ruta) & prohibidos), ruta


def test_ningun_modulo_de_ejecucion_arma_rutas_a_ground_truth():
    """Solo se miran los literales de código (no los docstrings): un `"ground_truth"` en una ruta sería leerlo."""
    for ruta in MODULOS_DE_EJECUCION:
        arbol = ast.parse((RAIZ / ruta).read_text(encoding="utf-8"))
        docstrings = {id(n.body[0].value) for n in ast.walk(arbol)
                      if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
                      and n.body and isinstance(n.body[0], ast.Expr)
                      and isinstance(n.body[0].value, ast.Constant)}
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str) and id(nodo) not in docstrings:
                if ruta in ("src/tools/baseline_reglas.py", "src/tools/eval_deteccion.py") and "ground_truth" in nodo.value:
                    # Sus CLI propias (herramientas de desarrollo sobre data/logs) usan «ground_truth» como CLAVE de un dict de lotes que arma ella misma
                    # desde data/logs (no abre experiments/ground_truth).
                    assert "experiments" not in (RAIZ / ruta).read_text(encoding="utf-8")
                    continue
                if ruta == "src/experimentation/runtime/persistencia.py" and "ground_truth" in nodo.value:
                    # Solo el NOMBRE del subdirectorio en `SUBDIRECTORIOS`, que `preparar_estructura`
                    # crea con mkdir (no abre ni lista su contenido).
                    assert nodo.value == "ground_truth"
                    assert (RAIZ / ruta).read_text(encoding="utf-8").count("ground_truth") <= 2
                    continue
                assert "ground_truth" not in nodo.value, f"{ruta}: {nodo.value[:80]!r}"
