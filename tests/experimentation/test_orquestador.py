"""Orquestador de la campaña (Fase C).

**ESCRITAS, NO EJECUTADAS** en su mayoría. Las que corren el plan en seco no
ejecutan ninguna arquitectura ni llaman al modelo: `ejecutar_campana()` con
`ejecucion_habilitada=False` solo enumera.

La prueba central es
`test_la_mitad_que_ejecuta_nunca_construye_una_ruta_al_ground_truth`:
verifica el invariante por AST, buscando el **literal de ruta** y no la
palabra. La primera versión de este control buscaba la subcadena
"ground_truth" y daba tres falsos positivos, porque los docstrings la
mencionan justamente para decir que no la abren.
"""

import ast
from pathlib import Path

import pytest

from src.experimentation import orquestador

RAIZ = Path(__file__).resolve().parents[2]


# --- la ejecución viene deshabilitada ------------------------------------

def test_sin_habilitar_la_ejecucion_no_corre_nada():
    plan = orquestador.ejecutar_campana(RAIZ, "piloto", "prueba-001")
    assert plan["ejecutado"] is False
    assert plan["modo"] == "plan_en_seco"
    assert "ejecucion_habilitada=True" in plan["aviso"]


def test_el_plan_en_seco_enumera_las_corridas_sin_ejecutarlas():
    plan = orquestador.ejecutar_campana(RAIZ, "piloto", "prueba-001")
    resumen = plan["plan"]
    assert resumen["corridas_pendientes"] > 0
    assert resumen["llamadas_llm_piso"] > 0
    # El piloto es de desarrollo: D-2 fija N=1.
    assert resumen["repeticiones"] == 1


# --- repeticiones (D-2) --------------------------------------------------

def test_el_piloto_usa_una_repeticion_y_la_evaluacion_tres():
    assert orquestador.REPETICIONES["desarrollo"] == 1
    assert orquestador.REPETICIONES["evaluacion"] == 3


def test_el_baseline_no_se_repite_porque_es_determinista():
    """Repetirlo tres veces daría tres archivos idénticos y triplicaría el
    conteo de casos sin aportar nada."""
    assert orquestador.REPETICIONES_BASELINE == 1
    plan = orquestador.planificar(
        RAIZ,
        orquestador.cargar_subconjunto(RAIZ, "rubrica"),
        "prueba-001",
    )
    por_arquitectura = plan.resumen()["por_arquitectura"]
    # En evaluación, las arquitecturas LLM corren 3 veces por caso y el
    # baseline una sola.
    assert por_arquitectura["nodex_multiagente"] == (
        3 * por_arquitectura["baseline_reglas"]
    )


def test_el_baseline_no_suma_llamadas_al_modelo():
    assert orquestador.LLAMADAS_POR_CORRIDA["baseline_reglas"] == 0


def test_las_llamadas_por_corrida_son_un_piso_declarado():
    """NODEX tiene 6 puntos de llamada y sube con los bucles de
    replanificación y corrección, que no se pueden acotar sin medir."""
    assert orquestador.LLAMADAS_POR_CORRIDA["nodex_multiagente"] == 6
    assert orquestador.LLAMADAS_POR_CORRIDA["agente_unico"] == 1
    plan = orquestador.ejecutar_campana(RAIZ, "piloto", "prueba-001")
    assert "piso" in plan["plan"]["nota_llamadas"]


# --- identidad y reanudación --------------------------------------------

def test_cada_corrida_del_plan_tiene_un_run_id_distinto():
    plan = orquestador.ejecutar_campana(RAIZ, "piloto", "prueba-001")
    ids = [c["run_id"] for c in plan["corridas"]]
    assert len(ids) == len(set(ids))


def test_cambiar_la_config_version_cambia_todos_los_run_id():
    """Una campaña nueva no pisa los artefactos de la anterior."""
    a = orquestador.ejecutar_campana(RAIZ, "piloto", "config-a")
    b = orquestador.ejecutar_campana(RAIZ, "piloto", "config-b")
    assert not ({c["run_id"] for c in a["corridas"]}
                & {c["run_id"] for c in b["corridas"]})


def test_el_plan_separa_lo_pendiente_de_lo_ya_hecho():
    """Permite reanudar una campaña interrumpida sin repetir ni
    sobrescribir: el `run_id` es determinístico, así que la existencia del
    archivo es respuesta suficiente."""
    plan = orquestador.ejecutar_campana(RAIZ, "piloto", "prueba-001")
    assert "corridas_ya_hechas" in plan["plan"]
    assert isinstance(plan["ya_hechas"], list)


# --- separación del ground truth ----------------------------------------

def _funciones_que_construyen_ruta(literal: str) -> set[str]:
    """Funciones del orquestador con `literal` como **constante de ruta**.

    Se analiza el AST y se buscan constantes exactas, no subcadenas: los
    docstrings mencionan `ground_truth` para declarar que no lo abren, y una
    búsqueda de texto daría falsos positivos.
    """
    fuente = (RAIZ / "src" / "experimentation" / "orquestador.py").read_text(
        encoding="utf-8"
    )
    arbol = ast.parse(fuente)
    encontradas = set()
    for nodo in arbol.body:
        if not isinstance(nodo, ast.FunctionDef):
            continue
        for interno in ast.walk(nodo):
            if (isinstance(interno, ast.Constant)
                    and interno.value == literal):
                encontradas.add(nodo.name)
    return encontradas


def test_la_mitad_que_ejecuta_nunca_construye_una_ruta_al_ground_truth():
    """Mientras una corrida está en curso, la referencia no está cargada en
    ninguna variable del proceso, así que no puede filtrarse a un prompt."""
    assert _funciones_que_construyen_ruta("ground_truth") == {
        "_cargar_referencia"
    }


def test_solo_la_evaluacion_lee_la_referencia():
    fuente = (RAIZ / "src" / "experimentation" / "orquestador.py").read_text(
        encoding="utf-8"
    )
    arbol = ast.parse(fuente)
    llamadores = set()
    for nodo in arbol.body:
        if not isinstance(nodo, ast.FunctionDef):
            continue
        for interno in ast.walk(nodo):
            if (isinstance(interno, ast.Call)
                    and isinstance(interno.func, ast.Name)
                    and interno.func.id == "_cargar_referencia"):
                llamadores.add(nodo.name)
    assert llamadores == {"evaluar_campana"}


def test_la_evaluacion_no_ejecuta_ninguna_arquitectura():
    """Si una corrida no está guardada se cuenta como ausente, no se corre:
    la evaluación no debe depender de cuándo se la invoque."""
    fuente = (RAIZ / "src" / "experimentation" / "orquestador.py").read_text(
        encoding="utf-8"
    )
    arbol = ast.parse(fuente)
    evaluar = next(
        n for n in arbol.body
        if isinstance(n, ast.FunctionDef) and n.name == "evaluar_campana"
    )
    for interno in ast.walk(evaluar):
        if isinstance(interno, ast.ImportFrom) and interno.module:
            assert "runners" not in interno.module


def test_la_evaluacion_declara_las_corridas_ausentes():
    fuente = (RAIZ / "src" / "experimentation" / "orquestador.py").read_text(
        encoding="utf-8"
    )
    assert "corridas_ausentes" in fuente
    assert "no se ejecuta" in fuente


# --- subconjuntos --------------------------------------------------------

def test_un_subconjunto_inexistente_falla_en_vez_de_quedar_vacio():
    with pytest.raises(FileNotFoundError, match="subconjunto"):
        orquestador.cargar_subconjunto(RAIZ, "no_existe")


def test_los_casos_del_subconjunto_no_se_repiten():
    subconjunto = orquestador.cargar_subconjunto(RAIZ, "piloto")
    casos = orquestador._casos_del_subconjunto(subconjunto)
    assert len(casos) == len(set(casos))
