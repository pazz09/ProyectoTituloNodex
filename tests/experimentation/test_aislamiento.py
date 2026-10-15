"""Controles de aislamiento del experimento (Fase 3, acción 8).

**ESCRITAS, NO EJECUTADAS** (ver `tests/experimentation/__init__.py`).

Estas pruebas no miden nada del sistema: verifican que la frontera entre lo
que el agente puede ver y lo que solo ve el evaluador siga en su lugar. Son
las que tienen que fallar el día que alguien, sin querer, meta una etiqueta
en un caso o apunte el experimento a la base de producción.
"""

import json
from pathlib import Path

import pytest

from src.experimentation.contracts.casos import GroundTruth, ReferenciaMitre
from src.experimentation.knowledge.aislamiento import (
    HISTORIAL_NO_CONFIGURABLE_POR_ENTORNO,
    POLITICA_RECURSOS_EXTERNOS,
    VARIABLES_AISLAMIENTO,
    configuracion_experimental,
    plan_poblado_chroma,
)
from src.experimentation.knowledge.inventario import (
    COLECCIONES_CONOCIMIENTO,
    COLECCIONES_MEMORIA,
    inventariar_chroma,
)

RAIZ = Path(__file__).resolve().parents[2]
EXPERIMENTS = RAIZ / "experiments"


# --- separación física caso / referencia ---------------------------------

def test_los_casos_y_las_referencias_viven_en_arboles_distintos():
    assert (EXPERIMENTS / "cases").is_dir()
    assert (EXPERIMENTS / "ground_truth").is_dir()
    # Ningún archivo puede estar en los dos lados.
    casos = {p.relative_to(EXPERIMENTS / "cases")
             for p in (EXPERIMENTS / "cases").rglob("*") if p.is_file()}
    referencias = {p.relative_to(EXPERIMENTS / "ground_truth")
                   for p in (EXPERIMENTS / "ground_truth").rglob("*")
                   if p.is_file()}
    # Comparten los nombres de los JSON por diseño (`case_id.json`), pero
    # los casos además tienen el archivo de contenido.
    assert any(p.suffix in (".log", ".csv") for p in casos)
    assert all(p.suffix == ".json" for p in referencias)


@pytest.mark.parametrize("dataset", ["hdfs", "bgl", "uwf"])
def test_cada_caso_tiene_exactamente_una_referencia(dataset):
    casos = {p.stem for p in (EXPERIMENTS / "cases" / dataset).rglob("*.json")}
    referencias = {p.stem for p in
                   (EXPERIMENTS / "ground_truth" / dataset).rglob("*.json")}
    assert casos == referencias


@pytest.mark.parametrize("dataset,prohibidas", [
    ("hdfs", ("Anomaly", "Normal")),
    ("bgl", ("KERNDTLB", "KERNSTOR", "APPSEV")),
    ("uwf", ("label_binary", "label_tactic", "label_technique",
             "Reconnaissance", "Resource Development", "T1587")),
])
def test_el_contenido_del_caso_no_contiene_su_etiqueta(dataset, prohibidas):
    """El control central: lo que la arquitectura va a leer no puede traer
    la respuesta. Es la fuga que el proyecto ya tuvo con BGL."""
    for contenido in (EXPERIMENTS / "cases" / dataset).rglob("*"):
        if contenido.suffix not in (".log", ".csv"):
            continue
        texto = contenido.read_text(encoding="utf-8")
        for prohibida in prohibidas:
            assert prohibida not in texto, f"{contenido.name}: {prohibida}"


@pytest.mark.parametrize("dataset", ["hdfs", "bgl", "uwf"])
def test_el_json_del_caso_no_trae_campos_de_referencia(dataset):
    prohibidos = {"etiqueta_deteccion", "etiqueta_original", "es_positivo",
                  "anotacion", "core_event_uids", "referencias_mitre",
                  "estado_dimension", "estado_mitre_por_nivel"}
    for meta in (EXPERIMENTS / "cases" / dataset).rglob("*.json"):
        datos = json.loads(meta.read_text(encoding="utf-8"))
        assert not prohibidos & set(datos)
        # Tampoco anidados en las notas.
        assert not prohibidos & set(datos.get("notas", {}))


# --- coherencia de las referencias ---------------------------------------

def test_ninguna_referencia_proviene_de_nodex():
    for referencia in (EXPERIMENTS / "ground_truth").rglob("*.json"):
        datos = json.loads(referencia.read_text(encoding="utf-8"))
        assert datos["anotacion"]["fuente"] != "nodex"


def test_el_contrato_rechaza_una_referencia_construida_con_nodex():
    with pytest.raises(ValueError, match="no puede provenir de NODEX"):
        GroundTruth(case_id="x", anotacion={"fuente": "nodex"})


def test_la_subtecnica_es_no_aplica_en_todas_las_referencias():
    """UWF no trae subtécnicas y el plan prohíbe inferirlas."""
    for referencia in (EXPERIMENTS / "ground_truth").rglob("*.json"):
        datos = json.loads(referencia.read_text(encoding="utf-8"))
        assert datos["estado_mitre_por_nivel"]["subtecnica"] == "no_aplica"


def test_ninguna_referencia_mitre_es_una_subtecnica():
    for referencia in (EXPERIMENTS / "ground_truth").rglob("*.json"):
        datos = json.loads(referencia.read_text(encoding="utf-8"))
        for mitre in datos["referencias_mitre"]:
            if mitre["nivel"] == "tecnica":
                assert "." not in mitre["id"], mitre["id"]


def test_un_nivel_no_aplica_con_referencias_de_ese_nivel_se_rechaza():
    """Marcar un nivel no puntuable y a la vez darle referencias es una
    contradicción que el evaluador no podría resolver."""
    with pytest.raises(ValueError, match="no_aplica"):
        GroundTruth(
            case_id="x",
            referencias_mitre=[ReferenciaMitre(nivel="tactica", id="TA0007")],
            estado_mitre_por_nivel={"tactica": "no_aplica"},
        )


def test_hdfs_y_bgl_no_declaran_referencias_mitre_ni_de_reconstruccion():
    for dataset in ("hdfs", "bgl"):
        for referencia in (EXPERIMENTS / "ground_truth" / dataset).rglob("*.json"):
            datos = json.loads(referencia.read_text(encoding="utf-8"))
            assert datos["referencias_mitre"] == []
            assert datos["core_event_uids"] == []
            assert datos["estado_dimension"]["mitre"] == "no_aplica"
            assert datos["estado_dimension"]["reconstruccion"] == "no_aplica"


def test_el_reporte_sigue_pendiente_en_todas_las_referencias():
    """La rúbrica está definida y su submuestra elegida, pero nadie puntuó
    nada: la dimensión no se cierra hasta que dos evaluadores trabajen."""
    for referencia in (EXPERIMENTS / "ground_truth").rglob("*.json"):
        datos = json.loads(referencia.read_text(encoding="utf-8"))
        assert datos["estado_dimension"]["reporte"] == "referencia_pendiente"
        assert datos["rubrica_aplicada"] is False


# --- aislamiento de almacenamiento ---------------------------------------

def test_la_configuracion_experimental_no_apunta_a_produccion():
    configuracion = configuracion_experimental(RAIZ)
    for valor in configuracion.variables_entorno().values():
        assert "experiments" in valor.replace("\\", "/")
    for defecto in VARIABLES_AISLAMIENTO.values():
        assert defecto not in configuracion.variables_entorno().values()


def test_solo_hay_dos_variables_de_entorno_porque_el_historial_no_es_una():
    """`src/config.py` solo lee CHROMA_PATH e IP_CACHE_PATH. No existe
    DB_PATH: el historial se aísla pasando `ruta` explícitamente."""
    configuracion = configuracion_experimental(RAIZ)
    assert set(configuracion.variables_entorno()) == {
        "CHROMA_PATH", "IP_CACHE_PATH"}
    assert HISTORIAL_NO_CONFIGURABLE_POR_ENTORNO["mecanismo_de_aislamiento"]


def test_las_colecciones_de_memoria_no_son_de_conocimiento():
    """`host_history` y `error_memory` acumulan corridas previas: dentro de
    un experimento le darían al sistema información que no vino del caso."""
    assert not set(COLECCIONES_CONOCIMIENTO) & set(COLECCIONES_MEMORIA)
    assert "attack_techniques" in COLECCIONES_CONOCIMIENTO
    assert "host_history" in COLECCIONES_MEMORIA
    assert "error_memory" in COLECCIONES_MEMORIA


def test_el_plan_de_poblado_excluye_la_memoria_y_no_recalcula_vectores():
    configuracion = configuracion_experimental(RAIZ)
    plan = plan_poblado_chroma(Path("/origen/chroma"), configuracion)
    assert plan["colecciones_a_copiar"] == list(COLECCIONES_CONOCIMIENTO)
    assert set(plan["colecciones_a_excluir"]) == set(COLECCIONES_MEMORIA)
    assert plan["requiere_autorizacion"] is True
    assert plan["estado"] == "NO_EJECUTADO"


def test_la_base_experimental_tiene_solo_conocimiento_y_ninguna_memoria():
    """La base se pobló el 4-oct-2026 (Fase 3, acción 6, autorizada) con el
    catálogo ATT&CK. Lo que importa para el aislamiento es QUÉ contiene: solo
    `attack_techniques`, con las 697 técnicas, y ninguna colección de
    memoria. La versión anterior de esta prueba afirmaba que estaba vacía,
    lo que dejó de ser cierto al poblarla, por diseño."""
    configuracion = configuracion_experimental(RAIZ)
    inventario = inventariar_chroma(configuracion.chroma)
    assert inventario["existe"] is True
    nombres = {c["nombre"] for c in inventario["colecciones"]}
    assert nombres == set(COLECCIONES_CONOCIMIENTO)
    assert not nombres & set(COLECCIONES_MEMORIA)
    catalogo = inventario["catalogo_mitre"]
    assert catalogo["total"] == 697
    assert catalogo["tecnicas_padre"] + catalogo["subtecnicas"] == 697


def test_la_politica_prohibe_consultas_de_prueba_a_los_tres_recursos():
    for recurso in ("abuseipdb", "nvd", "gemini"):
        assert "prohibidas" in POLITICA_RECURSOS_EXTERNOS[recurso][
            "consultas_de_prueba"]


def test_la_cache_de_reputacion_se_congela_antes_de_la_campana():
    """Si la caché se llenara durante la corrida, la segunda arquitectura
    evaluada tendría respuestas que la primera tuvo que ir a buscar, y la
    diferencia de tiempo no mediría la arquitectura."""
    assert POLITICA_RECURSOS_EXTERNOS["abuseipdb"]["estado"] == (
        "congelado_antes_de_ejecutar")
    assert POLITICA_RECURSOS_EXTERNOS["abuseipdb"][
        "modo_durante_campana"] == "solo_lectura"


def test_gemini_no_se_cachea_porque_es_la_variable_medida():
    assert POLITICA_RECURSOS_EXTERNOS["gemini"]["estado"] == "sin_cache"


# --- subconjuntos preseleccionados ---------------------------------------

def test_el_piloto_sale_solo_de_desarrollo():
    """Depurar contra los casos de evaluación los deja de ser reservados."""
    piloto = json.loads(
        (EXPERIMENTS / "subconjuntos" / "piloto.json").read_text(encoding="utf-8")
    )
    assert piloto["particion"] == "desarrollo"
    for condiciones in piloto["datasets"].values():
        for detalle in condiciones.values():
            for case_id in detalle["case_ids"]:
                assert "_des_" in case_id


def test_la_rubrica_sale_de_evaluacion_y_excluye_hdfs():
    rubrica = json.loads(
        (EXPERIMENTS / "subconjuntos" / "rubrica.json").read_text(encoding="utf-8")
    )
    assert rubrica["particion"] == "evaluacion"
    assert "hdfs" not in rubrica["datasets"]
    for condiciones in rubrica["datasets"].values():
        for detalle in condiciones.values():
            for case_id in detalle["case_ids"]:
                assert "_eva_" in case_id


def test_la_rubrica_quedo_fijada_antes_de_existir_resultados():
    rubrica = json.loads(
        (EXPERIMENTS / "subconjuntos" / "rubrica.json").read_text(encoding="utf-8")
    )
    assert rubrica["preseleccionada_antes_de_resultados"] is True
    assert rubrica["semilla"]


def test_los_subconjuntos_no_se_solapan():
    """El piloto es de desarrollo y la rúbrica de evaluación, así que no
    pueden compartir ningún caso."""
    piloto = json.loads(
        (EXPERIMENTS / "subconjuntos" / "piloto.json").read_text(encoding="utf-8"))
    rubrica = json.loads(
        (EXPERIMENTS / "subconjuntos" / "rubrica.json").read_text(encoding="utf-8"))

    def ids(seleccion):
        return {c for condiciones in seleccion["datasets"].values()
                for d in condiciones.values() for c in d["case_ids"]}

    assert not ids(piloto) & ids(rubrica)
