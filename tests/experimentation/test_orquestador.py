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
    assert resumen["llamadas_llm_referencia"] > 0
    assert "llamadas_llm_piso" not in resumen
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


def test_las_llamadas_por_corrida_son_una_referencia_y_no_un_piso():
    """Lo medido el 15-oct-2026 (comparación de modelos): NODEX hizo 5, 6, 12 y 13
    llamadas. El 6 es una referencia de partida; un «piso» de 6 es falso (hubo una
    corrida de 5)."""
    assert orquestador.LLAMADAS_POR_CORRIDA["nodex_multiagente"] == 6
    assert orquestador.LLAMADAS_MEDIDAS["nodex_multiagente"] == (5, 6, 12, 13)
    assert min(orquestador.LLAMADAS_MEDIDAS["nodex_multiagente"]) < (
        orquestador.LLAMADAS_POR_CORRIDA["nodex_multiagente"])
    # La pseudo-ablación es Gemini directo, de un solo prompt (decisión del
    # 7-oct-2026): reemplazó al agente único integrado en esta tabla.
    assert orquestador.LLAMADAS_POR_CORRIDA["gemini_externo"] == 1
    assert "agente_unico" not in orquestador.LLAMADAS_POR_CORRIDA
    plan = orquestador.ejecutar_campana(RAIZ, "piloto", "prueba-001")["plan"]
    assert "NO un piso" in plan["nota_llamadas"]
    assert plan["rango_medido_de_llamadas_por_corrida"]["nodex_multiagente"] == [5, 13]


def test_el_plan_impreso_no_llama_piso_a_las_llamadas(capsys):
    plan = orquestador.ejecutar_campana(RAIZ, "piloto", "prueba-001")
    orquestador.imprimir_plan(plan)
    salida = capsys.readouterr().out
    assert "(piso)" not in salida
    assert "NO un piso" in salida
    assert "referencia" in salida


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

def _arbol(modulo: str) -> ast.Module:
    fuente = (RAIZ / "src" / "experimentation" / modulo).read_text(encoding="utf-8")
    return ast.parse(fuente)


def _funciones_que_construyen_ruta(modulo: str, literal: str) -> set[str]:
    """Funciones de `modulo` con `literal` como **constante de ruta**.

    Se analiza el AST y se buscan constantes exactas, no subcadenas: los
    docstrings mencionan `ground_truth` para declarar que no lo abren, y una
    búsqueda de texto daría falsos positivos.
    """
    encontradas = set()
    for nodo in _arbol(modulo).body:
        if not isinstance(nodo, ast.FunctionDef):
            continue
        for interno in ast.walk(nodo):
            if isinstance(interno, ast.Constant) and interno.value == literal:
                encontradas.add(nodo.name)
    return encontradas


def _importados(arbol: ast.AST) -> set[str]:
    modulos = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ImportFrom) and nodo.module:
            modulos.add(nodo.module)
            modulos.update(f"{nodo.module}.{a.name}" for a in nodo.names)
        elif isinstance(nodo, ast.Import):
            modulos.update(a.name for a in nodo.names)
    return modulos


def test_el_orquestador_no_contiene_ninguna_ruta_al_ground_truth():
    """Mientras una corrida está en curso, la referencia no está cargada en
    ninguna variable del proceso. Antes la ruta vivía en una función del
    orquestador; ahora el archivo entero queda limpio."""
    assert _funciones_que_construyen_ruta("orquestador.py", "ground_truth") == set()


def test_solo_el_modulo_de_evaluacion_arma_la_ruta_a_la_referencia():
    assert _funciones_que_construyen_ruta("evaluacion.py", "ground_truth") == {
        "_cargar_referencia"
    }


def test_solo_evaluar_corridas_lee_la_referencia():
    llamadores = set()
    for nodo in _arbol("evaluacion.py").body:
        if not isinstance(nodo, ast.FunctionDef):
            continue
        for interno in ast.walk(nodo):
            if (isinstance(interno, ast.Call)
                    and isinstance(interno.func, ast.Name)
                    and interno.func.id == "_cargar_referencia"):
                llamadores.add(nodo.name)
    assert llamadores == {"evaluar_corridas"}


def test_la_evaluacion_no_importa_runners_ni_el_sistema():
    """Si una corrida no está guardada se cuenta como ausente, no se ejecuta:
    la evaluación no debe depender de cuándo se la invoque."""
    importados = _importados(_arbol("evaluacion.py"))
    for prohibido in ("src.experimentation.runners", "src.pipeline",
                      "src.agents", "src.graph", "src.llm"):
        assert not any(m == prohibido or m.startswith(prohibido + ".")
                       for m in importados), prohibido


def test_el_orquestador_no_importa_el_modulo_de_evaluacion():
    """El sentido de la separación es que quien corre no pueda ver la
    referencia; si el orquestador importara la evaluación, la tendría a mano."""
    assert not any(m.endswith("evaluacion") or ".evaluacion." in m
                   for m in _importados(_arbol("orquestador.py")))


def test_la_evaluacion_declara_las_corridas_ausentes():
    fuente = (RAIZ / "src" / "experimentation" / "evaluacion.py").read_text(
        encoding="utf-8"
    )
    assert "ausentes" in fuente
    assert "no se ejecuta" in fuente


# --- subconjuntos --------------------------------------------------------

def test_un_subconjunto_inexistente_falla_en_vez_de_quedar_vacio():
    with pytest.raises(FileNotFoundError, match="subconjunto"):
        orquestador.cargar_subconjunto(RAIZ, "no_existe")


def test_los_casos_del_subconjunto_no_se_repiten():
    subconjunto = orquestador.cargar_subconjunto(RAIZ, "piloto")
    casos = orquestador._casos_del_subconjunto(subconjunto)
    assert len(casos) == len(set(casos))
