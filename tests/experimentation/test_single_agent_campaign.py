"""Campaña agente único: pruebas offline. El modelo está simulado; ninguna prueba llama a la API.

`generate_content` se reemplaza por un doble y `_asegurar_credenciales` por un no-op, de modo que
`llm_json` real (con su telemetría) corre sin red. La memoria RAG es un doble con dos candidatos.
"""
import json
import shutil
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tools import run_single_agent_campaign as campana_au
from tools import single_agent_runner as runner

ROOT = Path(__file__).resolve().parents[2]
CASO_UWF = ("uwf", "uwf_eva_sigiloso_0013")
CASO_BGL = ("bgl", "bgl_eva_balanceado_0006")
CANDIDATOS = [
    {"texto": "Network Service Discovery. Adversaries may attempt to get a listing of services.",
     "meta": {"technique_id": "T1046", "name": "Network Service Discovery", "tactics": "discovery",
              "is_subtechnique": False, "url": ""}, "similitud": 0.512},
    {"texto": "Remote System Discovery. Adversaries may attempt to get a listing of other systems.",
     "meta": {"technique_id": "T1018", "name": "Remote System Discovery", "tactics": "discovery",
              "is_subtechnique": False, "url": ""}, "similitud": 0.47},
]
RESPUESTA = {"diagnostico": "Conexiones de reconocimiento hacia puertos poco comunes.",
             "hay_anomalia": True, "hay_incidente": True, "confianza": 0.8,
             "evaluacion": "Patrón de escaneo observado en el catálogo.", "comandos_mitigacion": [],
             "eventos_reconstruidos": [], "secuencia_temporal": [], "tecnicas_atribuidas": []}


class MemoriaFalsa:
    def __init__(self, candidatos=CANDIDATOS):
        self.candidatos, self.consultas = candidatos, []

    def retrieve_attack_techniques(self, texto):
        self.consultas.append(texto)
        return [dict(c) for c in self.candidatos]


@pytest.fixture
def modelo_simulado(monkeypatch):
    """`llm_json` real sobre un cliente simulado: telemetría real, cero red."""
    import src.llm as llm
    enviados = []

    def generar(**kwargs):
        enviados.append(kwargs)
        return SimpleNamespace(text=json.dumps(RESPUESTA), model_version="gemini-3.8-flash",
                               usage_metadata=SimpleNamespace(prompt_token_count=1000, candidates_token_count=200,
                                                              thoughts_token_count=300, total_token_count=1500))
    monkeypatch.setattr(llm, "_asegurar_credenciales", lambda: None)
    monkeypatch.setattr(llm.client.models, "generate_content", generar)
    return enviados


def repo_temporal(tmp_path, *casos):
    """Un repositorio mínimo: los casos (entrada + metadatos) y lo que lee `detectar_d11`."""
    raiz = tmp_path / "repo"
    for dataset, case_id in casos:
        origen = ROOT / "experiments" / "cases" / dataset / "evaluacion"
        destino = raiz / "experiments" / "cases" / dataset / "evaluacion"
        destino.mkdir(parents=True, exist_ok=True)
        for archivo in origen.glob(case_id + ".*"):
            shutil.copy2(archivo, destino / archivo.name)
    shutil.copytree(ROOT / "src" / "agents", raiz / "src" / "agents")
    shutil.copy2(ROOT / "src" / "state.py", raiz / "src" / "state.py")
    return raiz


def identidad(case_id, dataset, arquitectura="agente_unico", repeticion=1, version="agenteunico-12casos-r1-test"):
    from src.experimentation.runtime.identidad import IdentidadCorrida
    return IdentidadCorrida(case_id, dataset, arquitectura, repeticion, version)


def metadatos(raiz, dataset, case_id):
    from src.experimentation import orquestador
    return orquestador._metadatos_del_caso(raiz, dataset, "evaluacion", case_id)


# --- 1. despacho ----------------------------------------------------------------------------------

def test_el_despacho_llega_a_analizar_lote_agente_unico(tmp_path, modelo_simulado):
    import src.single_agent as single
    from src.experimentation import orquestador
    dataset, case_id = CASO_UWF
    raiz = repo_temporal(tmp_path, CASO_UWF)
    ident = identidad(case_id, dataset)
    # Sin el parche, el orquestador original no conoce agente_unico.
    with pytest.raises(KeyError):
        orquestador._correr_una(raiz, ident, "evaluacion", metadatos(raiz, dataset, case_id))
    llamadas = []
    original = single.analizar_lote_agente_unico

    def espia(*args, **kwargs):
        llamadas.append(kwargs)
        return original(*args, **kwargs)

    obs = tmp_path / "obs"
    despacho = partial(runner.correr_una_agente_unico, carpeta_observacion=obs, ltm=MemoriaFalsa())
    with patch.object(single, "analizar_lote_agente_unico", espia), \
            patch.object(orquestador, "_correr_una", despacho):
        resultado = orquestador._correr_una(raiz, ident, "evaluacion", metadatos(raiz, dataset, case_id))
    assert len(llamadas) == 1 and llamadas[0]["thread_id"] == f"exp__{ident.run_id}"
    assert [c["meta"]["technique_id"] for c in llamadas[0]["tecnicas_mitre"]] == ["T1046", "T1018"]
    assert resultado["identidad"]["arquitectura"] == "agente_unico"
    assert resultado["salida"]["_meta"]["arquitectura"] == "agente_unico"
    assert [c["id"] for c in resultado["salida"]["_meta"]["mitre_candidates"]] == ["T1046", "T1018"]
    assert resultado["estado"] == "completa"
    assert (raiz / "experiments" / "single_agent" / dataset / f"{ident.run_id}.json").is_file()
    # El parche era temporal: fuera del bloque vuelve el original.
    assert orquestador._correr_una is not despacho
    assert len(modelo_simulado) == 1


# --- 2. candidatos en el prompt --------------------------------------------------------------------

def test_los_candidatos_mitre_llegan_completos_al_prompt(tmp_path, modelo_simulado):
    dataset, case_id = CASO_UWF
    raiz = repo_temporal(tmp_path, CASO_UWF)
    ident = identidad(case_id, dataset)
    memoria = MemoriaFalsa()
    runner.correr_una_agente_unico(raiz, ident, "evaluacion", metadatos(raiz, dataset, case_id),
                                   carpeta_observacion=tmp_path / "obs", ltm=memoria)
    enviado = modelo_simulado[0]["contents"]
    enviado = enviado if isinstance(enviado, str) else json.dumps(enviado, ensure_ascii=False)
    bloque = enviado.split(runner.ENCABEZADO_CANDIDATOS, 1)[1]
    assert bloque.startswith(json.dumps(CANDIDATOS, ensure_ascii=False))
    registro = json.loads((tmp_path / "obs" / f"{ident.run_id}.mitre_retrieval.json").read_text(encoding="utf-8"))
    assert registro["llegada_al_prompt"][0]["lista_completa_en_bloque"] is True
    assert registro["llegada_al_prompt"][0]["ids_en_bloque"] == {"T1046": True, "T1018": True}
    assert [c["similitud"] for c in registro["candidatos"]] == [0.512, 0.47]
    # Misma consulta que NODEX (`describir_lote_en_prosa` del resumen) y la misma dentro del agente.
    assert memoria.consultas == [registro["consulta"]] and registro["consulta_interna_igual"] == [True]
    assert registro["llm_json"] == {"llamadas": 1, "invalidas": 0}
    entrada = json.loads((tmp_path / "obs" / f"{ident.run_id}.llm_input.json").read_text(encoding="utf-8"))
    assert runner.ENCABEZADO_CANDIDATOS in entrada["solicitudes"][0]["prompt"]


def test_la_consulta_es_la_misma_que_la_de_la_herramienta_rag_de_nodex(tmp_path):
    """La consulta del agente único es `describir_lote_en_prosa(resumen_logs)`, como `tool_consultar_rag`."""
    from src.pipeline import _preparar_estado_inicial
    from src.tools.aggregation import describir_lote_en_prosa
    contenido = runner.cargar_caso(ROOT, CASO_UWF[0], "evaluacion", CASO_UWF[1])
    memoria = MemoriaFalsa()
    recuperado = runner.recuperar_candidatos(contenido, memoria)
    estado, _, _ = _preparar_estado_inicial(contenido)
    assert recuperado["consulta"] == describir_lote_en_prosa(estado["resumen_logs"])
    assert recuperado["segundos_recuperacion_mitre"] >= 0


# --- 3. mismo esquema que NODEX ---------------------------------------------------------------------

def test_la_salida_pasa_por_adaptar_y_persistencia_con_el_esquema_de_nodex(tmp_path, modelo_simulado):
    import src.single_agent as single
    from src.experimentation import orquestador
    from src.experimentation.runners import nodex
    from src.experimentation.runtime import persistencia
    dataset, case_id = CASO_UWF
    raiz = repo_temporal(tmp_path, CASO_UWF)
    au = identidad(case_id, dataset)
    runner.correr_una_agente_unico(raiz, au, "evaluacion", metadatos(raiz, dataset, case_id), ltm=MemoriaFalsa())
    # NODEX, por el orquestador ORIGINAL, con un estado final producido igual (sin modelo real).
    contenido = runner.cargar_caso(raiz, dataset, "evaluacion", case_id)
    estado = single.analizar_lote_agente_unico(contenido, thread_id="x", tecnicas_mitre=[])
    nx = identidad(case_id, dataset, "nodex_multiagente")
    with patch.object(nodex, "ejecutar", lambda c, r: (estado, {"execution_time": 1.0, "error": None})):
        orquestador._correr_una(raiz, nx, "evaluacion", metadatos(raiz, dataset, case_id))
    rutas_au, rutas_nx = persistencia.rutas(au, raiz), persistencia.rutas(nx, raiz)
    assert rutas_au.salida.parent.parent.name == "single_agent"
    leer = lambda p: json.loads(p.read_text(encoding="utf-8"))  # noqa: E731
    sa, sn = leer(rutas_au.salida), leer(rutas_nx.salida)
    assert set(sa) == set(sn)
    assert set(sa["salida"]) == set(sn["salida"])
    assert set(sa["ejecucion"]) - set(sn["ejecucion"]) == {"resultado_incompleto"}
    assert set(sn["ejecucion"]) <= set(sa["ejecucion"])
    ta, tn = leer(rutas_au.telemetria)["telemetria"], leer(rutas_nx.telemetria)["telemetria"]
    assert set(tn) <= set(ta)
    assert set(ta) - set(tn) == {"segundos_recuperacion_mitre", "segundos_preprocesamiento_consulta_mitre",
                                 "segundos_carga_memoria_rag", "n_candidatos_mitre"}
    assert set(leer(rutas_au.crudo)) == set(leer(rutas_nx.crudo))
    assert ta["modelos_efectivos"] == ["gemini-3.8-flash"] and ta["llm_call_count"] == 1
    assert ta["n_candidatos_mitre"] == 2
    assert persistencia.leer_llm_json(au, raiz) == {"llamadas": 1, "invalidas": 0}


# --- 4. identificadores ----------------------------------------------------------------------------

def test_los_run_id_son_nuevos_y_distintos_entre_repeticiones():
    existentes = set()
    for seleccion in (ROOT / "experiments" / "ejecucion").glob("*/selection.json"):
        if seleccion.parent.name.startswith(campana_au.PREFIJO):
            continue      # la preparación de esta misma campaña
        existentes |= {c.get("run_id") for c in json.loads(seleccion.read_text(encoding="utf-8")).get("casos", [])}
    for carpeta in ("nodex", "single_agent", "gemini_externo", "baseline"):
        for p in (ROOT / "experiments" / carpeta).glob("*/*.json"):
            if not json.loads(p.read_text(encoding="utf-8")).get("config_version", "").startswith(campana_au.PREFIJO):
                existentes.add(p.stem)
    propios = [f["run_id"] for r in (1, 2, 3)
               for f in campana_au.filas_de(f"agenteunico-12casos-r{r}-20261110", r)]
    assert len(propios) == len(set(propios)) == 36
    assert not set(propios) & existentes
    assert all("__unico__" in r for r in propios)
    from src.experimentation.runtime.identidad import partes_del_run_id
    assert {partes_del_run_id(r)["repeticion"] for r in propios} == {1, 2, 3}


# --- 5. un caso iniciado no se repite ----------------------------------------------------------------

def _filas():
    return campana_au.filas_de("agenteunico-12casos-r1-pruebaoffline", 1)


def _gasto(usd=0.0):
    return lambda: {"usd": usd, "por_dataset": {}}


def test_un_caso_iniciado_no_se_repite_aunque_no_tenga_resultado(tmp_path):
    filas = _filas()
    from tools.run_official_experiment import write_new
    write_new(tmp_path / f"{filas[0]['run_id']}.started.json", {"x": 1})          # sin resultado
    write_new(tmp_path / f"{filas[1]['run_id']}.started.json", {"x": 1})
    write_new(tmp_path / f"{filas[1]['run_id']}.result.json", {"estado": "completa"})
    lanzados, mensajes = [], []

    def lanzar(fila):
        lanzados.append(fila["case_id"])
        return {"run_id": fila["run_id"], "estado": "completa", "infraestructura": False}

    codigo = campana_au.correr_casos(filas, tmp_path, lanzar, 2.5, {"bgl": .02, "uwf": .1}, {"parametros": {}},
                                     gasto=_gasto(), log=mensajes.append)
    assert codigo == 0
    assert lanzados == [f["case_id"] for f in filas[2:]]
    assert any("SIN resultado" in m for m in mensajes)
    # Una segunda pasada no lanza nada.
    lanzados.clear()
    campana_au.correr_casos(filas, tmp_path, lanzar, 2.5, {"bgl": .02, "uwf": .1}, {"parametros": {}},
                            gasto=_gasto(), log=mensajes.append)
    assert lanzados == []


def test_un_fallo_se_registra_y_no_se_reintenta(tmp_path):
    filas = _filas()[:4]
    lanzados = []

    def lanzar(fila):
        lanzados.append(fila["case_id"])
        return {"run_id": fila["run_id"], "estado": "error_api", "infraestructura": True}

    codigo = campana_au.correr_casos(filas, tmp_path, lanzar, 2.5, {"bgl": .02, "uwf": .1}, {"parametros": {}},
                                     gasto=_gasto(), log=lambda m: None)
    assert codigo == campana_au.SALIDA_DETENIDA and len(lanzados) == 3          # tres fallas seguidas
    assert all((tmp_path / f"{f['run_id']}.result.json").exists() for f in filas[:3])
    assert not (tmp_path / f"{filas[3]['run_id']}.started.json").exists()


def test_el_tope_de_gasto_detiene_antes_de_lanzar(tmp_path):
    filas = _filas()
    lanzados = []
    codigo = campana_au.correr_casos(filas, tmp_path, lambda f: lanzados.append(f) or {}, 2.5,
                                     {"bgl": .02, "uwf": .1}, {"parametros": {}},
                                     gasto=_gasto(2.49), log=lambda m: None)    # 2,49 + 0,02 (BGL) > 2,50
    assert codigo == campana_au.SALIDA_TOPE_DE_GASTO and lanzados == []
    assert not list(tmp_path.glob("*.started.json"))
    assert list(tmp_path.glob("detenido_por_gasto_*.json"))


def test_el_costo_maximo_usa_lo_observado_y_la_cota_previa():
    gasto = {"usd": 1.0, "por_dataset": {"uwf": [0.05, 0.12]}}
    assert campana_au.costo_maximo_siguiente("uwf", gasto, {"uwf": 0.08}) == 0.12
    assert campana_au.costo_maximo_siguiente("bgl", gasto, {"bgl": 0.02}) == 0.02
    with pytest.raises(ValueError):
        campana_au.costo_maximo_siguiente("bgl", gasto, {})


# --- 6. clasificación igual a NODEX ------------------------------------------------------------------

@pytest.mark.parametrize("estado, esperado, incompleto", [
    ({"hay_anomalia": True, "hay_incidente": False, "_error_api": runner.CONTRATO_INCOMPLETO[0]}, "completa", True),
    ({"hay_anomalia": None, "hay_incidente": None, "_error_api": runner.CONTRATO_INCOMPLETO[0]}, "error_contrato", True),
    ({"hay_anomalia": True, "hay_incidente": True, "_error_api": runner.CONTRATO_INCOMPLETO[1]}, "completa", True),
    ({"_error_api": "ServerError: 503 UNAVAILABLE"}, "error_api", False),
    ({"_error_api": "ClientError: 429 RESOURCE_EXHAUSTED"}, "error_api", False),
    ({"hay_anomalia": False, "hay_incidente": False, "_error_api": None}, "completa", False),
])
def test_la_regla_de_completa_es_la_de_nodex(monkeypatch, estado, esperado, incompleto):
    import src.single_agent as single
    monkeypatch.setattr(single, "analizar_lote_agente_unico", lambda *a, **k: dict(estado))
    final, diagnostico = runner.ejecutar("x", "run", [])
    assert runner.estado_de_ejecucion(diagnostico, final) == esperado
    assert (diagnostico["resultado_incompleto"] is not None) == incompleto


# --- 7. contrato del proceso hijo y compatibilidad de fuentes ----------------------------------------

def test_el_worker_recibe_los_siete_argumentos_del_lanzador_original():
    comando = ["py", "-m", "src.experimentation.campana", "--trabajar", "uwf", "caso", "agente_unico", "1",
               "agenteunico-12casos-r1-x", "evaluacion", "destino.json"]
    nuevo = campana_au.comando_del_worker(comando)
    assert nuevo[2] == "--worker" and nuevo[3:] == comando[4:]
    with pytest.raises(ValueError):
        campana_au.comando_del_worker(comando[:-1])


def test_el_worker_instala_el_despacho_solo_mientras_corre_trabajar(tmp_path, monkeypatch):
    from src.experimentation import campana, orquestador
    original = orquestador._correr_una
    visto = {}

    def trabajar_falso(raiz, dataset, case_id, arquitectura, repeticion, version, particion, destino):
        visto["despacho"] = orquestador._correr_una
        visto["args"] = (dataset, case_id, arquitectura, repeticion, version, particion)
        return 0

    monkeypatch.setenv(campana_au.OBS_ENV, str(tmp_path))
    monkeypatch.setattr(campana, "trabajar", trabajar_falso)
    codigo = campana_au.worker(["uwf", "uwf_eva_sigiloso_0013", "agente_unico", "2",
                                "agenteunico-12casos-r2-x", "evaluacion", str(tmp_path / "r.json")])
    assert codigo == 0
    assert visto["despacho"].func is runner.correr_una_agente_unico
    assert visto["despacho"].keywords == {"carpeta_observacion": tmp_path}
    assert visto["args"] == ("uwf", "uwf_eva_sigiloso_0013", "agente_unico", 2, "agenteunico-12casos-r2-x", "evaluacion")
    assert orquestador._correr_una is original
    assert len(list(tmp_path.glob("*__unico__r2__*.worker.json"))) == 1


def test_el_parser_del_proceso_hijo_acepta_los_siete_argumentos(tmp_path):
    """Incidente de las campañas enriquecidas: el parser esperaba 6 argumentos. Sin modelo ni red."""
    import os
    import subprocess
    import sys
    entorno = {k: v for k, v in os.environ.items() if k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY")}
    entorno[campana_au.OBS_ENV] = str(tmp_path)
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "run_single_agent_campaign.py"), "--worker",
                        "uwf", "caso", "nodex_multiagente", "1", "v", "evaluacion", str(tmp_path / "r.json")],
                       cwd=ROOT, env=entorno, capture_output=True, text=True, encoding="utf-8", errors="replace")
    # Pasa el parser (código 2 sería argparse) y lo rechaza la validación propia: solo agente_unico.
    assert r.returncode == 1 and "Worker solo para agente_unico" in r.stderr
    assert not list(tmp_path.iterdir())


def test_el_hijo_del_preflight_no_recupera_la_credencial_desde_env():
    """`src/config.py` llama a `load_dotenv()`; con la variable vacía no se recarga desde `.env`."""
    import os
    import subprocess
    import sys
    entorno = dict(os.environ, GEMINI_API_KEY="", GOOGLE_API_KEY="", CHROMA_PATH=str(campana_au.SEED))
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "run_single_agent_campaign.py"), "--preflight-case",
                        "bgl", "bgl_eva_balanceado_0006"], cwd=ROOT, env=entorno, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    # Supera los dos controles de credencial y se detiene en el de la copia: no abre la semilla.
    assert r.returncode == 1 and "copia de la semilla" in r.stderr
    assert "credencial" not in r.stderr.split("ValueError:")[-1]


def test_los_saltos_de_linea_no_cuentan_como_cambio_de_codigo_pero_el_contenido_si():
    import hashlib
    lf = b"a = 1\nb = 2\n"
    registrado = hashlib.sha256(lf).hexdigest()
    assert campana_au.misma_fuente(lf, registrado, None) == "bytes"
    assert campana_au.misma_fuente(lf.replace(b"\n", b"\r\n"), registrado, None) == "contenido_lf"
    mezcla = b"a = 1\r\nb = 2\n"
    assert campana_au.misma_fuente(lf.replace(b"\n", b"\r\n"), hashlib.sha256(mezcla).hexdigest(), mezcla) \
        == "contenido_igual_a_copia_r1"
    assert campana_au.misma_fuente(b"a = 1\nb = 3\n", registrado, lf) is None


def test_los_scripts_no_leen_ground_truth():
    for modulo in (runner, campana_au):
        assert "ground_truth" not in Path(modulo.__file__).read_text(encoding="utf-8")


# --- 8. preflight sin modelo ------------------------------------------------------------------------

@pytest.mark.parametrize("caso", [CASO_UWF, CASO_BGL])
def test_el_preflight_no_llama_al_modelo(monkeypatch, caso):
    import src.llm as llm

    def prohibido(**kwargs):
        raise AssertionError("el preflight intentó llamar al modelo")
    monkeypatch.setattr(llm.client.models, "generate_content", prohibido)
    dato = campana_au.preflight_caso(*caso, ltm=MemoriaFalsa())
    assert dato["llamadas_reales_al_modelo"] == 0
    assert dato["llegada_al_prompt"]["lista_completa_en_bloque"] is True
    assert dato["consulta_interna_igual"] is True
    assert [c["technique_id"] for c in dato["candidatos"]] == ["T1046", "T1018"]


def test_los_candidatos_de_nodex_r1_se_leen_del_estado_crudo_con_similitud():
    nodex = campana_au.candidatos_nodex_r1()
    assert len(nodex) == 12
    uwf = [c for k, v in nodex.items() if k.startswith("uwf") for c in v]
    assert uwf and all(c["technique_id"] and isinstance(c["similitud"], float) for c in uwf)
    assert all(v == [] for k, v in nodex.items() if k.startswith("bgl"))


def test_el_exportador_lee_predicciones_del_agente_unico_y_no_acepta_otras_campanas(tmp_path):
    from tools import export_single_agent_campaign as exportador
    assert exportador._mapear(Path("experiments/nodex/uwf/raw/x.raw.json"), ROOT) == \
        Path("experiments/single_agent/uwf/raw/x.raw.json")
    assert exportador._mapear(ROOT / "experiments/nodex/bgl/x.json", ROOT) == Path("experiments/single_agent/bgl/x.json")
    assert exportador._mapear(Path("experiments/telemetry/bgl/x.json"), ROOT) == Path("experiments/telemetry/bgl/x.json")
    for nombre in ("oficial-12casos-r1-20261028", "enriquecido-12casos-r2-20261104", "agenteunico-12casos-r4-20261110"):
        with pytest.raises(ValueError):
            exportador.export(nombre, salida=tmp_path / nombre)


def test_el_zip_se_compara_byte_a_byte_y_jsonl_rechaza_nan(tmp_path):
    import shutil as sh
    from tools import export_single_agent_campaign as exportador
    carpeta = tmp_path / "c"
    (carpeta / "d").mkdir(parents=True)
    (carpeta / "d" / "a.jsonl").write_text('{"v": null}\n', encoding="utf-8")
    sh.make_archive(str(carpeta), "zip", root_dir=carpeta)
    assert exportador.comprobar_zip(carpeta, carpeta.with_suffix(".zip")) == 1
    assert exportador.jsonl_estrictos(carpeta) == (1, 1)
    (carpeta / "d" / "a.jsonl").write_text('{"v": NaN}\n', encoding="utf-8")
    with pytest.raises(ValueError):
        exportador.comprobar_zip(carpeta, carpeta.with_suffix(".zip"))
    with pytest.raises(ValueError):
        exportador.jsonl_estrictos(carpeta)


def test_la_comparacion_con_nodex_detecta_ids_y_redondeo():
    a = [{"technique_id": "T1046", "similitud": 0.512}, {"technique_id": "T1018", "similitud": 0.47}]
    assert campana_au.comparar_con_nodex(a, a) == {"ids_iguales": True, "diferencia_maxima_similitud": 0.0}
    b = [{"technique_id": "T1046", "similitud": 0.513}, {"technique_id": "T1018", "similitud": 0.47}]
    assert campana_au.comparar_con_nodex(a, b)["diferencia_maxima_similitud"] == pytest.approx(0.001)
    assert campana_au.comparar_con_nodex(a, list(reversed(a)))["ids_iguales"] is False
