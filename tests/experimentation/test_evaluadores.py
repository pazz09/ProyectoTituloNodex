"""Evaluadores externos (Fase 5).

**ESCRITAS, NO EJECUTADAS.** La acción 7 de la Fase 5 lo prohíbe
expresamente: "No ejecutar los evaluadores ni las pruebas". Por eso los
valores esperados vienen de `fixtures/metricas_esperadas.json`, calculados a
mano, con la aritmética escrita paso a paso en
`fixtures/metricas_esperadas.md`.

La prueba más importante es `test_f1_cero_no_es_indefinido`: reproduce el
escenario exacto que rompía el evaluador anterior.
"""

import json
from pathlib import Path

import pytest

from src.experimentation.contracts.metricas import DetectionCounts, MetricsRecord
from src.experimentation.evaluators.agregacion import (
    construir_deteccion,
    contabilidad,
    escribir_resultado,
)
from src.experimentation.evaluators.conjuntos import (
    ComparacionConjuntos,
    evaluar_conjuntos,
)
from src.experimentation.evaluators.consumo import agregar as agregar_consumo
from src.experimentation.evaluators.deteccion import (
    ParDeteccion,
    contar,
    metricas,
)
from src.experimentation.evaluators.mitre import comparar_caso as comparar_mitre
from src.experimentation.evaluators.mitre import niveles_evaluables
from src.experimentation.evaluators.reconstruccion import (
    comparar_caso as comparar_reconstruccion,
)
from src.experimentation.evaluators.reporte import (
    CRITERIOS,
    PuntuacionRubrica,
    agregar as agregar_rubrica,
)

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "metricas_esperadas.json")
    .read_text(encoding="utf-8")
)


def _conteos(nombre: str) -> tuple[DetectionCounts, dict]:
    caso = FIXTURES["deteccion"][nombre]
    return DetectionCounts(**caso["conteos"]), caso["esperado"]


# --- D1: el defecto que se corrige ---------------------------------------

def test_f1_cero_no_es_indefinido():
    """TP=0, FP=6, FN=1: hubo un positivo real y seis predicciones
    positivas, así que F1 está definido y vale 0. El evaluador anterior
    devolvía None porque `if precision and recall` es falso con 0.0."""
    conteos, esperado = _conteos("f1_cero_no_indefinido")
    obtenido = metricas(conteos)
    assert obtenido["f1"] == 0.0
    assert obtenido["f1"] is not None
    assert obtenido["precision"] == 0.0
    assert obtenido["recall"] == 0.0


def test_f1_indefinido_solo_si_no_hay_positivos_reales_ni_predichos():
    conteos, esperado = _conteos("genuinamente_indefinido")
    obtenido = metricas(conteos)
    assert obtenido["f1"] is None
    assert obtenido["precision"] is None
    assert obtenido["recall"] is None
    # Y aun así accuracy está definida: cinco negativos bien clasificados.
    assert obtenido["accuracy"] == 1.0


def test_recall_cero_y_recall_indefinido_son_distintos():
    """Un recall 0 (había positivos y no detectó ninguno) y uno indefinido
    (no había positivos) describen situaciones opuestas."""
    cero, _ = _conteos("f1_cero_no_indefinido")
    indefinido, _ = _conteos("genuinamente_indefinido")
    assert metricas(cero)["recall"] == 0.0
    assert metricas(indefinido)["recall"] is None


@pytest.mark.parametrize("nombre", ["f1_cero_no_indefinido",
                                    "genuinamente_indefinido", "normal"])
def test_las_metricas_coinciden_con_el_calculo_a_mano(nombre):
    conteos, esperado = _conteos(nombre)
    obtenido = metricas(conteos)
    for clave, valor in esperado.items():
        if valor is None:
            assert obtenido[clave] is None, clave
        else:
            assert obtenido[clave] == pytest.approx(valor), clave


def test_la_forma_directa_coincide_con_la_media_armonica_cuando_ambas_valen():
    """Control de que el cambio de fórmula no cambió el resultado donde las
    dos están definidas: solo donde la vieja fallaba."""
    conteos, _ = _conteos("normal")
    obtenido = metricas(conteos)
    p, r = obtenido["precision"], obtenido["recall"]
    assert obtenido["f1"] == pytest.approx(2 * p * r / (p + r))


# --- D1: conteo ----------------------------------------------------------

def test_el_conteo_distingue_los_cuatro_cuadrantes():
    pares = [
        ParDeteccion("a", "MALICIOUS", "anomalo"),   # TP
        ParDeteccion("b", "MALICIOUS", "normal"),    # FP
        ParDeteccion("c", "BENIGN", "anomalo"),      # FN
        ParDeteccion("d", "BENIGN", "normal"),       # TN
    ]
    conteos = contar(pares)
    assert (conteos.tp, conteos.fp, conteos.fn, conteos.tn) == (1, 1, 1, 1)


def test_una_prediccion_fuera_del_vocabulario_se_rechaza():
    """Un caso sin veredicto válido no es evaluable y no debe llegar al
    conteo: si llega, es un error de contabilidad aguas arriba."""
    with pytest.raises(ValueError, match="no es del vocabulario"):
        contar([ParDeteccion("a", "SOSPECHOSO", "anomalo")])


def test_una_prediccion_nula_no_se_cuenta_como_negativa():
    with pytest.raises(ValueError, match="no es del vocabulario"):
        contar([ParDeteccion("a", None, "normal")])


# --- D2 y D3: conjuntos --------------------------------------------------

def test_las_metricas_de_conjuntos_coinciden_con_el_calculo_a_mano():
    fixture = FIXTURES["conjuntos"]["tres_casos"]
    comparaciones = [
        ComparacionConjuntos(
            case_id=c["case_id"],
            propuesto=frozenset(c["propuesto"]),
            referencia=frozenset(c["referencia"]),
        )
        for c in fixture["casos"]
    ]
    resultado = evaluar_conjuntos(comparaciones)
    esperado = fixture["esperado"]
    assert resultado.conteos_totales == esperado["conteos_totales"]
    for clave, valor in esperado["micro"].items():
        assert resultado.micro[clave] == pytest.approx(valor), f"micro.{clave}"
    for clave, valor in esperado["macro"].items():
        assert resultado.macro[clave] == pytest.approx(valor), f"macro.{clave}"
    assert resultado.exact_match == pytest.approx(esperado["exact_match"])


def test_el_macro_ignora_los_indefinidos_en_vez_de_contarlos_como_cero():
    """El caso C no propone nada, así que su precisión es indefinida.
    Contarla como 0 castigaría al sistema por no haber afirmado nada."""
    fixture = FIXTURES["conjuntos"]["tres_casos"]
    comparaciones = [
        ComparacionConjuntos(c["case_id"], frozenset(c["propuesto"]),
                             frozenset(c["referencia"]))
        for c in fixture["casos"]
    ]
    resultado = evaluar_conjuntos(comparaciones)
    # Promedio de 2 valores (0,667 y 1,0), no de 3.
    assert resultado.macro["precision"] == pytest.approx(0.8333333333333333)


def test_un_conjunto_vacio_de_comparaciones_da_todo_indefinido():
    resultado = evaluar_conjuntos([])
    assert resultado.micro["f1"] is None
    assert resultado.exact_match is None
    assert resultado.n_casos == 0


def test_el_detalle_por_caso_permite_auditar_un_f1_bajo():
    """Sin los sobrantes y faltantes, un F1 bajo no dice si el sistema
    inventó eventos o se perdió los reales."""
    resultado = evaluar_conjuntos([
        ComparacionConjuntos("A", frozenset({"u1", "u3"}), frozenset({"u1", "u2"}))
    ])
    detalle = resultado.por_caso[0]
    assert detalle["sobrantes"] == ["u3"]
    assert detalle["faltantes"] == ["u2"]


# --- D2: reconstrucción --------------------------------------------------

def test_el_matching_de_reconstruccion_es_exacto_por_uid():
    comparacion, _ = comparar_reconstruccion(
        "c1", ["CxyzA1", "CxyzA2"], ("CxyzA1", "CxyzA3"))
    assert comparacion.tp == 1
    assert comparacion.fp == 1
    assert comparacion.fn == 1
    assert comparacion.coincide_exacto is False


def test_un_uid_inventado_se_cuenta_aparte_de_un_falso_positivo_real():
    """Proponer un evento que no existe en el caso no es lo mismo que
    elegir mal un evento real."""
    comparacion, diagnostico = comparar_reconstruccion(
        "c1", ["CxyzA1", "NoExiste9"], ("CxyzA1",),
        uids_del_caso=frozenset({"CxyzA1", "CxyzA2"}))
    assert diagnostico["uids_inventados"] == ["NoExiste9"]
    # Sigue sumando a fp, porque propuso algo que no está en la referencia.
    assert comparacion.fp == 1


def test_un_evento_propuesto_sin_uid_se_cuenta_pero_no_entra_al_conjunto():
    comparacion, diagnostico = comparar_reconstruccion(
        "c1", ["CxyzA1", None], ("CxyzA1",))
    assert diagnostico["n_propuestos_sin_uid"] == 1
    assert comparacion.coincide_exacto is True


# --- D3: MITRE -----------------------------------------------------------

def test_una_atribucion_sin_evidencia_no_entra_en_la_comparacion():
    comparacion, diagnostico = comparar_mitre(
        "c1",
        atribuciones=[
            {"id": "T1046", "nivel": "tecnica", "evidence_uids": ["u1"]},
            {"id": "T1110", "nivel": "tecnica", "evidence_uids": []},
        ],
        referencias=[{"nivel": "tecnica", "id": "T1046"},
                     {"nivel": "tecnica", "id": "T1110"}],
        nivel="tecnica",
    )
    assert comparacion.tp == 1
    # T1110 estaba en la referencia pero la atribución no traía evidencia:
    # cuenta como no detectada, no como acierto.
    assert comparacion.fn == 1
    assert diagnostico["atribuciones_sin_evidencia_descartadas"] == ["T1110"]


def test_cada_nivel_se_evalua_por_separado():
    """Una táctica no equivale a una técnica: promediarlas daría un número
    que no se puede interpretar."""
    atribuciones = [
        {"id": "Discovery", "nivel": "tactica", "evidence_uids": ["u1"]},
        {"id": "T1046", "nivel": "tecnica", "evidence_uids": ["u1"]},
    ]
    referencias = [{"nivel": "tactica", "id": "Discovery"},
                   {"nivel": "tecnica", "id": "T1595"}]
    tacticas, _ = comparar_mitre("c1", atribuciones, referencias, "tactica")
    tecnicas, _ = comparar_mitre("c1", atribuciones, referencias, "tecnica")
    assert tacticas.coincide_exacto is True
    assert tecnicas.coincide_exacto is False


def test_una_subtecnica_no_se_convierte_en_su_tecnica_padre_para_acertar():
    """Se informa la coincidencia parcial, pero no suma: convertir
    `T1110.001` en `T1110` sería inferir la referencia."""
    comparacion, diagnostico = comparar_mitre(
        "c1",
        atribuciones=[{"id": "T1110.001", "nivel": "tecnica",
                       "evidence_uids": ["u1"]}],
        referencias=[{"nivel": "tecnica", "id": "T1110"}],
        nivel="tecnica",
    )
    assert comparacion.tp == 0
    assert comparacion.fp == 1
    assert comparacion.fn == 1
    assert diagnostico["coincidencias_por_padre"] == ["T1110.001"]


def test_la_subtecnica_nunca_es_un_nivel_evaluable_hoy():
    """UWF no trae subtécnicas y el plan prohíbe inferirlas."""
    estado = {"tactica": "evaluable", "tecnica": "evaluable",
              "subtecnica": "no_aplica"}
    assert niveles_evaluables(estado) == ("tactica", "tecnica")


def test_hdfs_y_bgl_no_tienen_ningun_nivel_evaluable():
    estado = {"tactica": "no_aplica", "tecnica": "no_aplica",
              "subtecnica": "no_aplica"}
    assert niveles_evaluables(estado) == ()


def test_un_nivel_invalido_se_rechaza():
    with pytest.raises(ValueError, match="nivel inválido"):
        comparar_mitre("c1", [], [], "procedimiento")


# --- D4: rúbrica ---------------------------------------------------------

def _puntuaciones() -> list[PuntuacionRubrica]:
    fixture = FIXTURES["rubrica"]["un_reporte_dos_evaluadores"]
    return [
        PuntuacionRubrica(case_id="bgl_eva_natural_0001",
                          arquitectura="nodex_multiagente",
                          evaluador=p["evaluador"], puntajes=p["puntajes"])
        for p in fixture["puntuaciones"]
    ]


def test_la_rubrica_coincide_con_el_calculo_a_mano():
    esperado = FIXTURES["rubrica"]["un_reporte_dos_evaluadores"]["esperado"]
    resultado = agregar_rubrica(_puntuaciones())
    for criterio, valor in esperado["por_criterio"].items():
        assert resultado.por_criterio[criterio] == pytest.approx(valor), criterio
    assert resultado.promedio_global == pytest.approx(esperado["promedio_global"])
    assert resultado.n_reportes == esperado["n_reportes"]
    assert resultado.n_evaluadores == esperado["n_evaluadores"]
    for clave, valor in esperado["concordancia"].items():
        assert resultado.concordancia[clave] == pytest.approx(valor), clave


def test_un_desacuerdo_de_dos_niveles_se_informa_individualmente():
    resultado = agregar_rubrica(_puntuaciones())
    assert len(resultado.desacuerdos_relevantes) == 1
    assert resultado.desacuerdos_relevantes[0]["criterio"] == (
        "coherencia_con_evidencia")
    assert resultado.desacuerdos_relevantes[0]["diferencia"] == 2


def test_una_rubrica_incompleta_no_se_promedia():
    with pytest.raises(ValueError, match="faltan criterios"):
        PuntuacionRubrica("c1", "nodex_multiagente", "E1",
                          {"completitud": 3})


def test_un_puntaje_fuera_de_la_escala_se_rechaza():
    puntajes = {c: 2 for c in CRITERIOS}
    puntajes["claridad"] = 5
    with pytest.raises(ValueError, match="fuera de la escala"):
        PuntuacionRubrica("c1", "nodex_multiagente", "E1", puntajes)


def test_un_booleano_no_pasa_como_puntaje():
    puntajes = {c: 2 for c in CRITERIOS}
    puntajes["claridad"] = True
    with pytest.raises(ValueError, match="entero"):
        PuntuacionRubrica("c1", "nodex_multiagente", "E1", puntajes)


def test_un_reporte_puntuado_por_uno_solo_no_infla_la_concordancia():
    una = _puntuaciones()[:1]
    resultado = agregar_rubrica(una)
    assert resultado.concordancia["reportes_con_un_evaluador"] == 1
    assert resultado.concordancia["reportes_con_dos_evaluadores"] == 0
    assert resultado.concordancia["acuerdo_exacto"] is None


def test_no_se_publica_ningun_kappa():
    """Elegir el coeficiente es una decisión metodológica pendiente;
    publicar uno calculado con una fórmula nunca ejecutada sería peor que
    no publicarlo."""
    assert agregar_rubrica(_puntuaciones()).to_dict()["kappa"] is None


# --- D5: consumo ---------------------------------------------------------

def test_el_consumo_excluye_las_corridas_fallidas_de_los_promedios():
    """Una corrida cortada consumió menos: promediarla haría parecer más
    eficiente a la arquitectura que falló más."""
    fixture = FIXTURES["consumo"]["dos_completas_una_fallida"]
    resultado = agregar_consumo(fixture["corridas"])
    esperado = fixture["esperado"]
    assert resultado.n_corridas_completas == esperado["n_corridas_completas"]
    assert resultado.n_por_estado_ejecucion == esperado["n_por_estado_ejecucion"]
    for campo in ("tokens_entrada", "latencia_total_s"):
        for clave, valor in esperado[campo].items():
            assert resultado.por_campo[campo][clave] == pytest.approx(valor), (
                f"{campo}.{clave}")


def test_un_campo_de_telemetria_ausente_no_se_rellena_con_cero():
    resultado = agregar_consumo([
        {"estado": "completa", "telemetria": {"tokens_entrada": 100}},
    ])
    assert resultado.campos_ausentes["llamadas_llm"] == 1
    assert resultado.por_campo["llamadas_llm"]["media"] is None


# --- contabilidad y escritura -------------------------------------------

def test_la_contabilidad_cuadra_con_los_cuatro_estados():
    fixture = FIXTURES["contabilidad"]["veinte_casos"]
    estados = []
    for estado, cuantos in fixture["estados"].items():
        estados.extend([estado] * cuantos)
    n_casos, n_evaluables, n_por_estado = contabilidad(estados)
    esperado = fixture["esperado"]
    assert n_casos == esperado["n_casos"]
    assert n_evaluables == esperado["n_evaluables"]
    assert n_por_estado == esperado["n_por_estado"]
    assert n_evaluables + sum(n_por_estado.values()) == esperado["suma_verificada"]


def test_un_estado_desconocido_no_se_contabiliza():
    with pytest.raises(ValueError, match="desconocido"):
        contabilidad(["evaluable", "casi_evaluable"])


def test_la_matriz_tiene_que_sumar_los_evaluables_y_no_los_casos():
    """14 evaluables de 20 casos: la matriz describe 14. Si describiera 20,
    estaría contando casos que no se pudieron puntuar."""
    estados = ["evaluable"] * 14 + ["no_aplica"] * 2 + [
        "referencia_pendiente"] + ["fallido"] * 2 + ["no_evaluable"]
    registro = construir_deteccion(
        arquitectura="nodex_multiagente", dataset="bgl", estados=estados,
        conteos=DetectionCounts(tp=5, fp=3, fn=2, tn=4),
        metricas={"f1": 0.6666666666666666},
    )
    assert registro.n_casos == 20
    assert registro.n_evaluables == 14
    assert registro.conteos.total == 14


def test_una_matriz_que_no_cuadra_se_rechaza():
    with pytest.raises(ValueError, match="matriz de confusión"):
        construir_deteccion(
            arquitectura="nodex_multiagente", dataset="bgl",
            estados=["evaluable"] * 3,
            conteos=DetectionCounts(tp=5, fp=5, fn=5, tn=5),
            metricas={},
        )


def test_los_resultados_no_se_sobrescriben(tmp_path):
    """Una corrección genera un artefacto nuevo: un informe que cita un
    resultado tiene que poder seguir citándolo."""
    registro = MetricsRecord(
        dimension="deteccion", arquitectura="nodex_multiagente", dataset="bgl",
        protocolo_version="1.0",
    )
    # La marca se fija para que el nombre sea el mismo en las dos llamadas;
    # si no, el resultado dependería de si el reloj avanzó un segundo.
    marca = "20261006T120000Z"
    archivo = escribir_resultado([registro], tmp_path, etiqueta="piloto",
                                 marca=marca)
    assert archivo.exists()
    assert "p1.0" in archivo.name
    with pytest.raises(FileExistsError, match="no se sobrescriben"):
        escribir_resultado([registro], tmp_path, etiqueta="piloto", marca=marca)


def test_dos_corridas_distintas_generan_artefactos_distintos():
    """Una corrección no edita el artefacto viejo: genera uno nuevo."""
    import inspect

    assert "marca" in inspect.signature(escribir_resultado).parameters


# --- separación de los agentes ------------------------------------------

def test_ningun_evaluador_importa_el_pipeline_ni_los_agentes():
    """Un evaluador que pudiera invocar al sistema podría evaluar una
    corrida nueva en vez de la guardada.

    Se analiza el AST y no el texto: los docstrings de estos módulos
    *mencionan* `src.pipeline` justamente para explicar que no lo importan,
    así que una búsqueda de subcadenas daría un falso positivo.
    """
    import ast

    import src.experimentation.evaluators as paquete

    prohibidos = ("src.pipeline", "src.agents", "src.graph")
    raiz = Path(paquete.__file__).parent
    for modulo in sorted(raiz.glob("*.py")):
        arbol = ast.parse(modulo.read_text(encoding="utf-8"), filename=str(modulo))
        importados: list[str] = []
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                importados.extend(alias.name for alias in nodo.names)
            elif isinstance(nodo, ast.ImportFrom) and nodo.module:
                importados.append(nodo.module)
        for nombre in importados:
            for prohibido in prohibidos:
                assert not nombre.startswith(prohibido), (
                    f"{modulo.name} importa {nombre}")
