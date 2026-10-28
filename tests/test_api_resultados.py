"""Endpoints de solo lectura de la vista "Resultados".

Sin modelo, sin red y sin tocar el repositorio: todo ocurre en un `tmp_path`
al que se apunta `RAIZ_EXPERIMENTOS`. `experiments/metrics` y
`experiments/outputs` del repositorio no se usan.

Las pruebas más importantes son las de fuga: un archivo centinela en la
carpeta del ground truth NO debe aparecer en ninguna respuesta, y el módulo
no puede contener la ruta ni importar el sistema.
"""

import ast
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import src.api.main as api
from src.api import resultados
from src.experimentation.runtime import persistencia
from src.experimentation.runtime.identidad import IdentidadCorrida

CONFIG = "prueba-001"
SENTINELA = "SENTINELA_GROUND_TRUTH_NO_DEBE_SALIR"
RUN = IdentidadCorrida("uwf_des_visible_0000", "uwf", "nodex_multiagente", 1, CONFIG)


def _resumen(config=CONFIG, marca="20260101T000000Z", ficticio=False) -> dict:
    return {
        "esquema": "resultados-v1", "datos_ficticios": ficticio,
        "config_version": config, "consolidacion": marca,
        "generado_utc": "2026-01-01T00:00:00+00:00", "protocolo_version": "1.0",
        "subconjunto": "sub", "particion": "desarrollo",
        "arquitecturas": ["nodex_multiagente"],
        "integridad": {"corridas_esperadas": 1, "corridas_presentes": 1,
                       "corridas_completas": 1, "corridas_ausentes": [],
                       "corridas_fallidas": [], "corridas_con_fallback": [],
                       "fallback_determinable": True, "modelo_principal": "m",
                       "corridas_con_telemetria_previa_a_d11": 0,
                       "corridas_sin_tokens": 0, "advertencias": []},
        "tablas": {},
    }


def _escribir_resumen(raiz: Path, config=CONFIG, marca="20260101T000000Z", **kw) -> None:
    carpeta = raiz / "experiments" / "metrics" / config / marca
    carpeta.mkdir(parents=True)
    (carpeta / "resumen.json").write_text(json.dumps(_resumen(config, marca, **kw)), encoding="utf-8")


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(resultados, "RAIZ_EXPERIMENTOS", tmp_path / "experiments")
    monkeypatch.setattr(resultados, "MOSTRAR_EXPERIMENTO", True)     # estas pruebas son del listado del experimento
    return TestClient(api.app), tmp_path


# --- listado -----------------------------------------------------------------------

def test_sin_consolidaciones_la_lista_esta_vacia_y_no_es_un_error(cliente):
    c, _ = cliente
    r = c.get("/api/resultados")
    assert r.status_code == 200
    assert r.json() == {"configuraciones": []}


def test_la_lista_trae_las_marcas_y_la_ultima(cliente):
    c, raiz = cliente
    _escribir_resumen(raiz, marca="20260101T000000Z")
    _escribir_resumen(raiz, marca="20260301T000000Z")
    _escribir_resumen(raiz, config="otra-config", marca="20260201T000000Z")
    cfgs = {x["config_version"]: x for x in c.get("/api/resultados").json()["configuraciones"]}
    assert cfgs[CONFIG]["consolidaciones"] == ["20260101T000000Z", "20260301T000000Z"]
    assert cfgs[CONFIG]["ultima"] == "20260301T000000Z"
    assert cfgs["otra-config"]["ultima"] == "20260201T000000Z"


def test_una_carpeta_sin_resumen_no_aparece(cliente):
    c, raiz = cliente
    (raiz / "experiments" / "metrics" / CONFIG / "20260101T000000Z").mkdir(parents=True)
    assert c.get("/api/resultados").json() == {"configuraciones": []}


# --- detalle --------------------------------------------------------------------------

def test_el_detalle_devuelve_el_resumen_de_la_ultima_consolidacion(cliente):
    c, raiz = cliente
    _escribir_resumen(raiz, marca="20260101T000000Z")
    _escribir_resumen(raiz, marca="20260301T000000Z")
    assert c.get(f"/api/resultados/{CONFIG}").json()["consolidacion"] == "20260301T000000Z"


def test_se_puede_pedir_una_consolidacion_anterior(cliente):
    c, raiz = cliente
    _escribir_resumen(raiz, marca="20260101T000000Z")
    _escribir_resumen(raiz, marca="20260301T000000Z")
    r = c.get(f"/api/resultados/{CONFIG}", params={"consolidacion": "20260101T000000Z"})
    assert r.json()["consolidacion"] == "20260101T000000Z"


def test_el_marcador_de_datos_ficticios_llega_intacto(cliente):
    c, raiz = cliente
    _escribir_resumen(raiz, ficticio=True)
    assert c.get(f"/api/resultados/{CONFIG}").json()["datos_ficticios"] is True


def test_una_configuracion_sin_resultados_da_404(cliente):
    c, _ = cliente
    assert c.get("/api/resultados/no-existe").status_code == 404


def test_una_consolidacion_inexistente_da_404(cliente):
    c, raiz = cliente
    _escribir_resumen(raiz)
    r = c.get(f"/api/resultados/{CONFIG}", params={"consolidacion": "20990101T000000Z"})
    assert r.status_code == 404


# --- validacion de la URL ---------------------------------------------------------------

@pytest.mark.parametrize("config", ["a b", "x;y", "-empieza-con-guion", "a" * 80, "con%00nulo"])
def test_un_config_version_invalido_se_rechaza(cliente, config):
    c, _ = cliente
    assert c.get(f"/api/resultados/{config}").status_code in (400, 404)


def _con_secreto_fuera(raiz: Path) -> None:
    """Un archivo fuera de `experiments/` que no debe poder leerse."""
    (raiz / "secreto.json").write_text(json.dumps({"secreto": SENTINELA}), encoding="utf-8")


@pytest.mark.parametrize("intento", ["%2e%2e", "..%2f..%2fsecreto", "%2e%2e%2f%2e%2e%2fsecreto"])
def test_un_config_version_codificado_para_salir_de_la_carpeta_se_rechaza(cliente, intento):
    """Estas variantes SÍ llegan al endpoint (el cliente no las normaliza) y
    la validación las rechaza antes de tocar el disco."""
    c, raiz = cliente
    _con_secreto_fuera(raiz)
    r = c.get(f"/api/resultados/{intento}")
    assert SENTINELA not in r.text
    assert r.status_code in (400, 404, 422), (intento, r.status_code)


@pytest.mark.parametrize("intento", ["..", "../..", "../../secreto"])
def test_los_segmentos_punto_se_normalizan_antes_de_llegar_y_no_filtran(cliente, intento):
    """El cliente HTTP (como un navegador) resuelve `..` antes de enviar, así
    que `/api/resultados/../..` se convierte en `/` y cae en OTRA ruta. Lo
    que se puede afirmar es que nada de fuera de `experiments/` aparece."""
    c, raiz = cliente
    _con_secreto_fuera(raiz)
    r = c.get(f"/api/resultados/{intento}")
    assert SENTINELA not in r.text
    assert r.status_code < 500


def test_la_ruta_resultante_se_comprueba_contra_la_carpeta_de_experimentos(cliente):
    """Defensa en profundidad: aunque una validación fallara, la ruta final
    tiene que quedar dentro de `experiments/`."""
    c, raiz = cliente
    _con_secreto_fuera(raiz)
    with pytest.raises(Exception) as fuera:
        resultados._leer_json(raiz / "secreto.json")
    assert getattr(fuera.value, "status_code", None) == 400


def test_una_marca_con_formato_invalido_se_rechaza(cliente):
    c, raiz = cliente
    _escribir_resumen(raiz)
    r = c.get(f"/api/resultados/{CONFIG}", params={"consolidacion": "../../x"})
    assert r.status_code == 400


@pytest.mark.parametrize("run_id", ["x", "uwf__otro__r1__abcd1234", "../../etc",
                                    "uwf__nodex__r1__ZZZZZZZZ"])
def test_un_run_id_invalido_se_rechaza(cliente, run_id):
    c, _ = cliente
    assert c.get(f"/api/resultados/{CONFIG}/reportes/{run_id}").status_code in (400, 404)


# --- reportes ------------------------------------------------------------------------------

def _guardar_corrida(raiz: Path, reporte="Informe del analisis", config=CONFIG) -> None:
    ident = IdentidadCorrida(RUN.case_id, RUN.dataset, RUN.arquitectura, 1, config)
    persistencia.guardar(
        ident, raiz,
        salida={"classification": "MALICIOUS", "report": {"summary": reporte},
                "_meta": {"motivo_no_evaluable": None}},
        crudo={"muestras_crudas": "LINEA_CRUDA_NO_DEBE_SALIR"},
        telemetria={"llm_call_count": 6},
        ejecucion={"estado": "completa", "estados_por_dimension": {}, "iniciado_utc": "x"},
    )


def test_el_reporte_se_sirve_por_run_id(cliente):
    c, raiz = cliente
    _guardar_corrida(raiz)
    r = c.get(f"/api/resultados/{CONFIG}/reportes/{RUN.run_id}")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["reporte"] == "Informe del analisis"
    assert cuerpo["arquitectura"] == "nodex_multiagente"
    assert cuerpo["estado_ejecucion"] == "completa"
    assert cuerpo["clasificacion"] == "MALICIOUS"


def test_el_reporte_no_expone_el_estado_crudo_ni_la_telemetria(cliente):
    """El crudo puede traer muestras del log: del archivo solo sale el texto."""
    c, raiz = cliente
    _guardar_corrida(raiz)
    texto = c.get(f"/api/resultados/{CONFIG}/reportes/{RUN.run_id}").text
    assert "LINEA_CRUDA_NO_DEBE_SALIR" not in texto
    assert "llm_call_count" not in texto


def test_el_reporte_devuelve_exactamente_los_campos_previstos(cliente):
    """Lo que la API expone se fija por lista, no por exclusión: agregar un
    campo al cuerpo —por ejemplo devolver el archivo entero de la corrida—
    tiene que hacer fallar esta prueba, aunque lo agregado no sea secreto."""
    c, raiz = cliente
    _guardar_corrida(raiz)
    cuerpo = c.get(f"/api/resultados/{CONFIG}/reportes/{RUN.run_id}").json()
    assert set(cuerpo) == {
        "run_id", "case_id", "dataset", "arquitectura", "repeticion",
        "estado_ejecucion", "clasificacion", "motivo_no_evaluable", "reporte",
    }


def test_una_corrida_sin_reporte_devuelve_null_y_no_un_texto_inventado(cliente):
    c, raiz = cliente
    _guardar_corrida(raiz, reporte=None)
    assert c.get(f"/api/resultados/{CONFIG}/reportes/{RUN.run_id}").json()["reporte"] is None


def test_un_reporte_inexistente_da_404(cliente):
    c, _ = cliente
    assert c.get(f"/api/resultados/{CONFIG}/reportes/{RUN.run_id}").status_code == 404


def test_no_se_sirve_la_corrida_de_otra_configuracion_bajo_esta_url(cliente):
    """El run_id lleva la configuración en su hash, pero se comprueba igual."""
    c, raiz = cliente
    _guardar_corrida(raiz)
    # Se pide con una configuración distinta a la del archivo.
    assert c.get(f"/api/resultados/otra-config/reportes/{RUN.run_id}").status_code == 404


# --- fuga del ground truth ---------------------------------------------------------------------

def test_ningun_endpoint_devuelve_el_contenido_del_ground_truth(cliente):
    c, raiz = cliente
    gt = raiz / "experiments" / "ground_truth" / "uwf" / "desarrollo"
    gt.mkdir(parents=True)
    (gt / f"{RUN.case_id}.json").write_text(json.dumps({"secreto": SENTINELA}), encoding="utf-8")
    _escribir_resumen(raiz)
    _guardar_corrida(raiz)
    respuestas = [
        c.get("/api/resultados"),
        c.get(f"/api/resultados/{CONFIG}"),
        c.get(f"/api/resultados/{CONFIG}/reportes/{RUN.run_id}"),
        c.get(f"/api/resultados/{CONFIG}/reportes/{RUN.case_id}"),
    ]
    assert all(SENTINELA not in r.text for r in respuestas)


def _arbol_del_modulo() -> ast.Module:
    return ast.parse(Path(resultados.__file__).read_text(encoding="utf-8"))


def test_el_modulo_no_contiene_la_ruta_al_ground_truth():
    constantes = {n.value for n in ast.walk(_arbol_del_modulo())
                  if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "ground_truth" not in constantes


def test_el_modulo_no_importa_el_sistema_ni_los_modelos():
    importados = set()
    for n in ast.walk(_arbol_del_modulo()):
        if isinstance(n, ast.ImportFrom) and n.module:
            importados.add(n.module)
        elif isinstance(n, ast.Import):
            importados.update(a.name for a in n.names)
    for prohibido in ("src.pipeline", "src.agents", "src.graph", "src.llm",
                      "google", "src.experimentation.evaluacion",
                      "src.experimentation.runners", "src.experimentation.orquestador"):
        assert not any(m == prohibido or m.startswith(prohibido + ".") for m in importados), prohibido


def test_todas_las_rutas_de_resultados_son_de_solo_lectura(cliente):
    c, _ = cliente
    paths = c.app.openapi()["paths"]
    rutas = {p: ops for p, ops in paths.items() if p.startswith("/api/resultados")}
    assert len(rutas) == 3
    for ruta, ops in rutas.items():
        assert set(ops) == {"get"}, ruta


# --- el experimento guardado no se muestra por omisión ------------------------------------------------

def test_por_omision_las_consolidaciones_del_experimento_no_se_listan_pero_siguen_guardadas(cliente, monkeypatch):
    c, raiz = cliente
    _escribir_resumen(raiz, config="piloto-flash38-20261015", marca="20261015T230314Z")
    monkeypatch.setattr(resultados, "MOSTRAR_EXPERIMENTO", False)
    assert c.get("/api/resultados").json() == {"configuraciones": []}            # estado vacío en la interfaz
    assert (raiz / "experiments" / "metrics" / "piloto-flash38-20261015" / "20261015T230314Z"
            / "resumen.json").is_file()                                           # los datos NO se borran
    monkeypatch.setattr(resultados, "MOSTRAR_EXPERIMENTO", True)
    assert [x["config_version"] for x in c.get("/api/resultados").json()["configuraciones"]] \
        == ["piloto-flash38-20261015"]


def test_el_flag_se_lee_de_la_variable_de_entorno(monkeypatch):
    """Se carga una copia del módulo con otro nombre: no toca el módulo real que ya usa la aplicación."""
    import importlib.util

    def cargar():
        spec = importlib.util.spec_from_file_location("resultados_copia", resultados.__file__)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        return modulo.MOSTRAR_EXPERIMENTO

    monkeypatch.delenv("RESULTADOS_MOSTRAR_EXPERIMENTO", raising=False)
    assert cargar() is False
    monkeypatch.setenv("RESULTADOS_MOSTRAR_EXPERIMENTO", "1")
    assert cargar() is True
