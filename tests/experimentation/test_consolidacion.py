"""Recorrido completo con corridas SIMULADAS: ejecutar → guardar → evaluar → consolidar.

Ningún corredor real se invoca: `nodex.ejecutar`, `gemini_externo.ejecutar` y
`baseline.ejecutar` se reemplazan por funciones que devuelven estados
fabricados. No se llama al modelo, no se corre el preprocesamiento sobre
ningún caso y no se usa `ejecutar_campana(ejecucion_habilitada=True)`: el
bucle se ejerce con `ejecutar_plan`.

Todo ocurre en un `tmp_path`. Las carpetas `experiments/outputs` y
`experiments/metrics` del repositorio no se tocan.

## Por qué existe esta prueba

Las piezas se probaron por separado y pasaban, pero nadie había recorrido el
camino entero. Al conectarlas aparecieron tres defectos que ninguna prueba
unitaria veía:

1. Las corridas guardaban su salida pero NO cómo habían terminado ni qué
   dimensiones eran puntuables; el evaluador lo leía de ahí, no lo encontraba
   y daba toda dimensión por no evaluable. Habría producido tablas vacías
   que se confunden con un sistema que falla.
2. El evaluador de consumo esperaba nombres de campo que la telemetría real
   no produce.
3. Un fallo solo vivía en el valor de retorno de `ejecutar_campana`, que se
   pierde al terminar el proceso.

El primer escenario de cada grupo es la regresión de uno de esos defectos.
"""

import csv
import json
from pathlib import Path

import pytest

from src.experimentation import consolidacion, orquestador
from src.experimentation.contracts import CONTRATO_VERSION
from src.experimentation.contracts.casos import GroundTruth, ReferenciaMitre
from src.experimentation.contracts.salida import ExperimentalOutput
from src.experimentation.runners import baseline, gemini_externo, nodex
from src.experimentation.runtime import exportacion, persistencia
from src.experimentation.runtime.identidad import IdentidadCorrida
from src.experimentation.runtime.telemetria import Telemetria

CONFIG = "prueba-001"
PRINCIPAL = "gemini-principal"
RESPALDO = "gemini-respaldo"
MARCA = "20260101T000000Z"
ARQUITECTURAS = ("nodex_multiagente", "baseline_reglas", "gemini_externo")

#: Casos de la partición `desarrollo` (N=1). La condición es el 3.er token.
CASOS = {
    "uwf_des_visible_0000": dict(dataset="uwf", positivo=True, nucleo=("U1", "U2"), tecnica="T1046"),
    "uwf_des_visible_0001": dict(dataset="uwf", positivo=True, nucleo=("U3",), tecnica="T1595"),
    "uwf_des_visible_0002": dict(dataset="uwf", positivo=False),
    "uwf_des_visible_0003": dict(dataset="uwf", positivo=False),
    "bgl_des_natural_0000": dict(dataset="bgl", positivo=True),
    "bgl_des_natural_0001": dict(dataset="bgl", positivo=False),
}


# --- construcción de un repositorio en miniatura -------------------------------

def _json(ruta: Path, datos: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")


def _referencia(cid: str, c: dict) -> GroundTruth:
    if c["dataset"] == "uwf" and c["positivo"]:
        return GroundTruth(
            case_id=cid,
            estado_dimension={"deteccion": "evaluable", "reconstruccion": "evaluable",
                              "mitre": "evaluable", "reporte": "referencia_pendiente",
                              "consumo": "evaluable"},
            etiqueta_deteccion="anomalo", etiqueta_original="True",
            core_event_uids=c["nucleo"],
            referencias_mitre=[ReferenciaMitre(nivel="tecnica", id=c["tecnica"],
                                               evidence_uids=c["nucleo"])],
            estado_mitre_por_nivel={"tactica": "no_aplica", "tecnica": "evaluable",
                                    "subtecnica": "no_aplica"},
            anotacion={"fuente": "dataset"},
        )
    return GroundTruth(
        case_id=cid,
        estado_dimension={"deteccion": "evaluable", "reconstruccion": "no_aplica",
                          "mitre": "no_aplica", "reporte": "referencia_pendiente",
                          "consumo": "evaluable"},
        etiqueta_deteccion="anomalo" if c["positivo"] else "normal",
        etiqueta_original="x",
        estado_mitre_por_nivel={"tactica": "no_aplica", "tecnica": "no_aplica",
                                "subtecnica": "no_aplica"},
        anotacion={"fuente": "dataset"},
    )


def _construir_repo(raiz: Path) -> None:
    exp = raiz / "experiments"
    for cid, c in CASOS.items():
        ds, part = c["dataset"], "desarrollo"
        _json(exp / "cases" / ds / part / f"{cid}.json", {
            "case_id": cid, "particion": part,
            "tipo_deteccion": "seguridad" if ds == "uwf" else "operativa",
            "dimensiones_aplicables": (
                ["deteccion", "reconstruccion", "mitre", "reporte", "consumo"]
                if ds == "uwf" else ["deteccion", "reporte", "consumo"]),
        })
        if ds == "uwf":
            (exp / "cases" / ds / part / f"{cid}.csv").write_text(
                "uid,ts\n" + "\n".join(f"U{i},{i}" for i in range(1, 6)) + "\n",
                encoding="utf-8")
        else:
            (exp / "cases" / ds / part / f"{cid}.log").write_text("linea\n", encoding="utf-8")
        _json(exp / "ground_truth" / ds / part / f"{cid}.json", _referencia(cid, c).to_dict())

    por_ds: dict = {}
    for cid, c in CASOS.items():
        por_ds.setdefault(c["dataset"], {}).setdefault(cid.split("_")[2], {"case_ids": []})[
            "case_ids"].append(cid)
    _json(exp / "subconjuntos" / "sub.json", {"particion": "desarrollo", "datasets": por_ds})
    _json(exp / "config" / f"config_{CONFIG}.json", {"parametros": {"LLM_MODEL_PRIMARY": PRINCIPAL}})


# --- corredores simulados -------------------------------------------------------

def _telemetria(modelo=PRINCIPAL, tokens=1000, tiempo=10.0, replan=1, correcciones=0,
                razonamiento=40):
    """`razonamiento=None` simula un proveedor que no informó esos tokens.

    La versión devuelta por la API lleva un sufijo (`-001`) a propósito: es
    DISTINTA del nombre pedido, como puede ocurrir de verdad, y aun así no debe
    contar como fallback.
    """
    return {
        "llm_call_count": 6, "input_tokens": tokens, "output_tokens": 200,
        "total_tokens": None if tokens is None else tokens + 200,
        "execution_time": tiempo, "replan_count": replan,
        "intentos_correccion": correcciones, "invalid_evidence_uid_count": 0,
        "d11_warning_count": 0,
        # Las llamadas llevan sus tokens, como en la telemetría real; con `tokens=None`
        # simulan un proveedor que no los informó.
        "llm_calls": [{"model": modelo, "model_version": f"{modelo}-001",
                       "input_tokens": tokens, "output_tokens": None if tokens is None else 200,
                       "total_tokens": None if tokens is None else tokens + 200,
                       "reasoning_tokens": razonamiento, "duration_s": 3.0, "error": None}],
    }


def _estado_base(cid: str, incidente: bool, anomalia: bool) -> dict:
    return {
        "hay_incidente": incidente, "hay_anomalia": anomalia, "confianza": 0.9,
        "diagnostico": f"diagnostico de {cid}", "evaluacion_auditor": "ok",
        "comandos_mitigacion": [], "output_contract_version": "d11-v1",
        "eventos_reconstruidos": [], "secuencia_temporal": [],
        "tecnicas_atribuidas": [], "invalid_evidence_uid_count": 0,
        "d11_warnings": [], "tecnicas_mitre": [], "resumen_logs": {},
    }


def _evento(uids):
    return {"event_id": "event_001", "evidence_uids": list(uids), "timestamp": None,
            "event_type": "x", "description": "x", "confidence": 0.5}


def _tecnica(tid, uids):
    return {"technique_id": tid, "technique_name": None, "evidence_uids": list(uids),
            "justification": "x", "confidence": 0.5}


def _nodex_ejecutar(contenido, run_id):
    cid = run_id.split("__")[0]
    c = CASOS[cid]
    if c["dataset"] == "bgl":
        estado = _estado_base(cid, False, c["positivo"])
    elif cid == "uwf_des_visible_0000":     # acierta todo
        estado = _estado_base(cid, True, True)
        estado["eventos_reconstruidos"] = [_evento(["U1", "U2"])]
        estado["secuencia_temporal"] = ["event_001"]
        estado["tecnicas_atribuidas"] = [_tecnica("T1046", ["U1"])]
    elif cid == "uwf_des_visible_0001":     # falso negativo
        estado = _estado_base(cid, False, False)
    elif cid == "uwf_des_visible_0002":     # falso positivo
        estado = _estado_base(cid, True, True)
        estado["eventos_reconstruidos"] = [_evento(["U4"])]
    else:                                   # verdadero negativo
        estado = _estado_base(cid, False, False)
    # Una corrida cayó al modelo de respaldo.
    modelo = RESPALDO if cid == "uwf_des_visible_0000" else PRINCIPAL
    # En BGL el proveedor "no informó" los tokens de razonamiento.
    estado["telemetry"] = _telemetria(
        modelo=modelo, razonamiento=None if c["dataset"] == "bgl" else 40)
    return estado, {"execution_time": 10.5, "error": None,
                    "replan_count": 1, "intentos_correccion": 0}


def _gemini_ejecutar(contenido, run_id):
    cid = run_id.split("__")[0]
    if cid == "bgl_des_natural_0001":
        raise RuntimeError("503 UNAVAILABLE: el modelo no respondio")
    c = CASOS[cid]
    estado = _estado_base(cid, True, True)           # siempre afirma que hay problema
    if cid == "uwf_des_visible_0000":
        estado["eventos_reconstruidos"] = [_evento(["U1", "U99"])]   # U99 no existe
        estado["secuencia_temporal"] = ["event_001"]
        estado["tecnicas_atribuidas"] = [_tecnica("T1046", ["U1"])]
    elif cid == "uwf_des_visible_0001":
        estado["eventos_reconstruidos"] = [_evento(["U3"])]
        estado["secuencia_temporal"] = ["event_001"]
        estado["tecnicas_atribuidas"] = [_tecnica("T1595", ["U3"])]
    return estado, {"execution_time": 4.0, "error": None, "telemetry": {
        "llm_call_count": 1, "input_tokens": 300, "output_tokens": 100,
        "total_tokens": 400, "execution_time": 4.0, "replan_count": None,
        "intentos_correccion": None, "reasoning_tokens": 12,
        "modelo_solicitado": PRINCIPAL, "modelo_efectivo": f"{PRINCIPAL}-001",
        "llm_calls": [{"model": PRINCIPAL, "model_version": f"{PRINCIPAL}-001",
                       "input_tokens": 300, "output_tokens": 100,
                       "total_tokens": 400, "reasoning_tokens": 12}]}}


def _baseline_ejecutar(contenido, identidad, tipo_deteccion):
    c = CASOS[identidad.case_id]
    maligno = c["positivo"] and c["dataset"] == "bgl"   # solo ve las fallas operativas
    salida = ExperimentalOutput(
        case_id=identidad.case_id, run_id=identidad.run_id,
        arquitectura="baseline_reglas", contrato_version=CONTRATO_VERSION,
        classification="MALICIOUS" if maligno else "BENIGN",
        veredicto_booleano_presente=True)
    return salida, Telemetria(run_id=identidad.run_id, execution_time=0.1,
                              previa_a_d11=False), {"regla": "x"}


@pytest.fixture
def campana(tmp_path, monkeypatch):
    _construir_repo(tmp_path)
    for modulo in (nodex, gemini_externo, baseline):
        monkeypatch.setattr(modulo, "cargar_caso", lambda *a, **k: "contenido")
    monkeypatch.setattr(nodex, "ejecutar", _nodex_ejecutar)
    monkeypatch.setattr(gemini_externo, "ejecutar", _gemini_ejecutar)
    monkeypatch.setattr(baseline, "ejecutar", _baseline_ejecutar)

    subconjunto = orquestador.cargar_subconjunto(tmp_path, "sub")
    plan = orquestador.planificar(tmp_path, subconjunto, CONFIG, ARQUITECTURAS)
    resultado = orquestador.ejecutar_plan(tmp_path, subconjunto, plan, CONFIG)
    return tmp_path, resultado


def _consolidar(raiz: Path) -> dict:
    destino = consolidacion.consolidar(raiz, "sub", CONFIG, ARQUITECTURAS, marca=MARCA)
    return json.loads((destino / "resumen.json").read_text(encoding="utf-8"))


def _fila(resumen: dict, tabla: str, dataset: str, arquitectura: str) -> dict:
    return next(f for f in resumen["tablas"][tabla]["filas"]
                if f["dataset"] == dataset and f["arquitectura"] == arquitectura)


# --- regresión 1: la corrida guarda cómo terminó ---------------------------------

def test_la_corrida_guarda_su_estado_y_sus_dimensiones_puntuables(campana):
    raiz, _ = campana
    ident = IdentidadCorrida("uwf_des_visible_0000", "uwf", "nodex_multiagente", 1, CONFIG)
    guardado = persistencia.leer_salida(persistencia.rutas(ident, raiz).salida)
    assert guardado["ejecucion"]["estado"] == "completa"
    assert guardado["ejecucion"]["estados_por_dimension"]["deteccion"] == "evaluable"
    assert guardado["ejecucion"]["estados_por_dimension"]["reconstruccion"] == "evaluable"


def test_sin_los_metadatos_de_ejecucion_la_evaluacion_lo_declara(tmp_path):
    """Un archivo en el formato anterior no trae `ejecucion`. No se infiere
    nada: queda no evaluable Y marcado, para que el vacío no se confunda con
    un sistema que falla."""
    _construir_repo(tmp_path)
    ident = IdentidadCorrida("bgl_des_natural_0000", "bgl", "nodex_multiagente", 1, CONFIG)
    persistencia.guardar(ident, tmp_path, salida={"classification": "MALICIOUS"})
    from src.experimentation.evaluacion import evaluar_corridas
    ev = evaluar_corridas(tmp_path, "sub", CONFIG, ("nodex_multiagente",))
    assert ev.registros[0].sin_metadatos_de_ejecucion is True
    assert ev.registros[0].estados["deteccion"] == "no_evaluable"
    destino = consolidacion.consolidar(tmp_path, "sub", CONFIG, ("nodex_multiagente",), marca=MARCA)
    resumen = json.loads((destino / "resumen.json").read_text(encoding="utf-8"))
    codigos = {a["codigo"] for a in resumen["integridad"]["advertencias"]}
    assert "sin_metadatos_de_ejecucion" in codigos


# --- D1 ----------------------------------------------------------------------------

def test_d1_de_nodex_en_uwf_cuenta_los_cuatro_cuadrantes(campana):
    raiz, _ = campana
    f = _fila(_consolidar(raiz), "d1_deteccion", "uwf", "nodex_multiagente")
    assert (f["tp"], f["fp"], f["fn"], f["tn"]) == (1, 1, 1, 1)
    assert f["precision"] == pytest.approx(0.5)
    assert f["recall"] == pytest.approx(0.5)
    assert f["f1"] == pytest.approx(0.5)


def test_los_datasets_no_se_mezclan_en_una_sola_matriz(campana):
    """El evaluador anterior juntaba BGL y UWF —preguntas distintas— en una
    matriz por arquitectura."""
    raiz, _ = campana
    resumen = _consolidar(raiz)
    uwf = _fila(resumen, "d1_deteccion", "uwf", "nodex_multiagente")
    bgl = _fila(resumen, "d1_deteccion", "bgl", "nodex_multiagente")
    assert uwf["n_evaluables"] == 4 and bgl["n_evaluables"] == 2
    assert (bgl["tp"], bgl["fp"], bgl["fn"], bgl["tn"]) == (1, 0, 0, 1)


def test_f1_cero_y_precision_indefinida_se_distinguen_de_punta_a_punta(campana):
    """El baseline nunca marca nada en UWF: no predijo ningún positivo
    (precisión indefinida, `None`) y no detectó ninguno de los 2 reales
    (exhaustividad y F1 valen 0). Dos situaciones distintas."""
    raiz, _ = campana
    f = _fila(_consolidar(raiz), "d1_deteccion", "uwf", "baseline_reglas")
    assert f["precision"] is None
    assert f["recall"] == 0.0
    assert f["f1"] == 0.0
    assert f["fnr"] == 1.0


def test_las_celdas_sin_dato_van_vacias_en_el_csv_y_los_ceros_van_como_cero(campana):
    raiz, _ = campana
    destino = consolidacion.consolidar(raiz, "sub", CONFIG, ARQUITECTURAS, marca=MARCA)
    with (destino / "d1_deteccion.csv").open(encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f))
    base = next(r for r in filas if r["dataset"] == "uwf" and r["arquitectura"] == "baseline_reglas")
    assert base["precision"] == ""        # indefinida
    assert float(base["recall"]) == 0.0   # cero real


def test_la_media_entre_repeticiones_con_una_sola_es_none_y_no_cero(campana):
    raiz, _ = campana
    f = _fila(_consolidar(raiz), "d1_deteccion", "uwf", "nodex_multiagente")
    assert f["f1_media_repeticiones"] == pytest.approx(0.5)
    assert f["f1_desv_repeticiones"] is None   # una observación no tiene dispersión


# --- D2 y D3 -----------------------------------------------------------------------

def test_d2_solo_aparece_donde_corresponde(campana):
    """HDFS/BGL no tienen identificador estable y el baseline no reconstruye."""
    raiz, _ = campana
    filas = _consolidar(raiz)["tablas"]["d2_reconstruccion"]["filas"]
    assert {(f["dataset"], f["arquitectura"]) for f in filas} == {
        ("uwf", "nodex_multiagente"), ("uwf", "gemini_externo")}


def test_d2_compara_por_evidence_uids(campana):
    raiz, _ = campana
    f = _fila(_consolidar(raiz), "d2_reconstruccion", "uwf", "nodex_multiagente")
    # Regla v2 (15-oct-2026): el caso 0001 no produjo eventos pero la corrida es válida y la
    # referencia existe: es una OMISIÓN y cuenta (antes salía como «no evaluable»).
    assert f["n_evaluables"] == 2 and f["n_omisiones"] == 1
    assert f["no_evaluables"] == 0
    assert f["micro_f1"] == pytest.approx(0.8)
    assert f["exact_match"] == pytest.approx(0.5)


def test_un_uid_inventado_se_cuenta_aparte(campana):
    """Gemini directo cita U99, que no está en el caso."""
    raiz, _ = campana
    f = _fila(_consolidar(raiz), "d2_reconstruccion", "uwf", "gemini_externo")
    assert f["uids_inventados"] == 1
    assert f["micro_precision"] == pytest.approx(2 / 3)
    assert f["micro_recall"] == pytest.approx(2 / 3)


def test_d3_se_puntua_solo_a_nivel_de_tecnica(campana):
    raiz, _ = campana
    resumen = _consolidar(raiz)
    f = _fila(resumen, "d3_mitre", "uwf", "gemini_externo")
    assert f["n_evaluables"] == 2 and f["exact_match"] == pytest.approx(1.0)
    assert "tactica" not in json.dumps(resumen["tablas"]["d3_mitre"]["columnas"])


# --- consumo ---------------------------------------------------------------------------

def test_el_consumo_usa_los_nombres_reales_de_la_telemetria(campana):
    """Regresión 2: el evaluador esperaba `tokens_entrada`/`latencia_total_s`
    y con la telemetría real habría dado todo ausente."""
    raiz, _ = campana
    f = _fila(_consolidar(raiz), "consumo", "uwf", "nodex_multiagente")
    assert f["tokens_entrada_medios"] == pytest.approx(1000)
    assert f["llamadas_medias"] == pytest.approx(6)
    assert f["replan_medio"] == pytest.approx(1)


def test_el_baseline_no_inventa_tokens(campana):
    raiz, _ = campana
    f = _fila(_consolidar(raiz), "consumo", "uwf", "baseline_reglas")
    assert f["tokens_entrada_medios"] is None
    assert f["tiempo_medio_s"] == pytest.approx(0.1)


def test_para_el_baseline_los_tokens_y_el_fallback_no_aplican_y_no_son_cero(campana):
    """Lo mostró la revisión visual de la vista: el baseline figuraba con
    «sin tokens informados: 4». No usa el modelo, así que no hay tokens que
    informar ni modelo de respaldo; un 0 diría lo contrario de «no aplica»."""
    raiz, _ = campana
    resumen = _consolidar(raiz)
    for dataset in ("uwf", "bgl"):
        f = _fila(resumen, "consumo", dataset, "baseline_reglas")
        assert f["n_sin_tokens"] is None
        assert f["n_con_fallback"] is None
    nodex_f = _fila(resumen, "consumo", "uwf", "nodex_multiagente")
    assert nodex_f["n_sin_tokens"] == 0          # a NODEX sí le aplica, y vale 0
    assert nodex_f["n_con_fallback"] == 1


# --- integridad -----------------------------------------------------------------------

def test_el_fallback_se_detecta_comparando_con_el_modelo_congelado(campana):
    raiz, _ = campana
    i = _consolidar(raiz)["integridad"]
    assert i["fallback_determinable"] is True
    assert i["modelo_principal"] == PRINCIPAL
    assert i["corridas_con_fallback"] == [
        IdentidadCorrida("uwf_des_visible_0000", "uwf", "nodex_multiagente", 1, CONFIG).run_id]


def test_sin_configuracion_congelada_el_fallback_no_se_da_por_inexistente(campana):
    raiz, _ = campana
    (raiz / "experiments" / "config" / f"config_{CONFIG}.json").unlink()
    i = _consolidar(raiz)["integridad"]
    assert i["fallback_determinable"] is False
    assert "fallback_no_determinable" in {a["codigo"] for a in i["advertencias"]}


def test_regresion_3_el_fallo_queda_en_disco_y_se_muestra(campana):
    """Regresión 3: antes el fallo solo vivía en el valor de retorno."""
    raiz, resultado = campana
    assert len(resultado["fallos"]) == 1
    ident = IdentidadCorrida("bgl_des_natural_0001", "bgl", "gemini_externo", 1, CONFIG)
    assert len(persistencia.rutas_fallos(ident, raiz)) == 1
    i = _consolidar(raiz)["integridad"]
    assert [f["run_id"] for f in i["corridas_fallidas"]] == [ident.run_id]
    assert i["corridas_fallidas"][0]["estado"] == "error_api"
    # Fallida NO es lo mismo que ausente: no se cuenta dos veces.
    assert ident.run_id not in i["corridas_ausentes"]


def test_una_corrida_fallida_no_se_da_por_hecha(campana):
    """`ya_existe` mira la salida: una reanudación vuelve a intentarla."""
    raiz, _ = campana
    ident = IdentidadCorrida("bgl_des_natural_0001", "bgl", "gemini_externo", 1, CONFIG)
    assert persistencia.ya_existe(ident, raiz) is False


def test_los_reintentos_del_mismo_fallo_se_cuentan_una_vez(campana):
    raiz, _ = campana
    ident = IdentidadCorrida("bgl_des_natural_0001", "bgl", "gemini_externo", 1, CONFIG)
    persistencia.guardar_fallo(ident, raiz, "error_api", "otro intento")
    assert len(persistencia.rutas_fallos(ident, raiz)) == 2
    assert len(_consolidar(raiz)["integridad"]["corridas_fallidas"]) == 1


def test_las_corridas_ausentes_se_declaran(campana):
    raiz, _ = campana
    ident = IdentidadCorrida("uwf_des_visible_0003", "uwf", "baseline_reglas", 1, CONFIG)
    persistencia.rutas(ident, raiz).salida.unlink()
    i = _consolidar(raiz)["integridad"]
    assert i["corridas_ausentes"] == [ident.run_id]
    assert "corridas_ausentes" in {a["codigo"] for a in i["advertencias"]}


def test_la_telemetria_previa_a_d11_se_declara(campana):
    raiz, _ = campana
    i = _consolidar(raiz)["integridad"]
    # Sin src/state.py con los campos de D-11 en el repo de prueba, las
    # corridas LLM quedan marcadas como previas.
    assert i["corridas_con_telemetria_previa_a_d11"] > 0


# --- 11.6 y 11.7 ------------------------------------------------------------------------

def test_en_uwf_la_comparacion_con_el_baseline_se_marca_contextual(campana):
    raiz, _ = campana
    filas = _consolidar(raiz)["tablas"]["comparacion"]["filas"]
    d1_uwf = next(f for f in filas if f["dataset"] == "uwf" and f["metrica"] == "D1_f1")
    d1_bgl = next(f for f in filas if f["dataset"] == "bgl" and f["metrica"] == "D1_f1")
    assert d1_uwf["comparable"] == "contextual"
    assert d1_bgl["comparable"] == "pareada"


def test_los_errores_listan_cada_fp_y_fn_con_su_corrida(campana):
    raiz, _ = campana
    filas = _consolidar(raiz)["tablas"]["errores_d1"]["filas"]
    nodex_uwf = {f["case_id"]: f["resultado"] for f in filas
                 if f["arquitectura"] == "nodex_multiagente" and f["dataset"] == "uwf"}
    assert nodex_uwf == {"uwf_des_visible_0001": "FN", "uwf_des_visible_0002": "FP"}
    assert all(f["run_id"].startswith(f["case_id"]) for f in filas)


# --- D4 -----------------------------------------------------------------------------------

def _puntajes(raiz: Path, filas: list[list]) -> None:
    ruta = raiz / "experiments" / "rubrica" / CONFIG / "puntajes.csv"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    cab = ["case_id", "arquitectura", "repeticion", "evaluador",
           "completitud", "correccion_factual", "coherencia_con_evidencia",
           "claridad", "informacion_no_sustentada"]
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cab)
        w.writerows(filas)


def test_sin_puntajes_la_rubrica_queda_sin_datos_y_no_se_inventa(campana):
    raiz, _ = campana
    assert _consolidar(raiz)["tablas"]["d4_rubrica"]["filas"] == []


def test_la_rubrica_se_agrega_y_una_fila_invalida_se_declara(campana):
    raiz, _ = campana
    _puntajes(raiz, [
        ["uwf_des_visible_0000", "nodex_multiagente", 1, "E1", 3, 2, 2, 3, 3],
        ["uwf_des_visible_0000", "nodex_multiagente", 1, "E2", 2, 2, 0, 3, 3],
        ["uwf_des_visible_0000", "nodex_multiagente", 1, "E3", 9, 2, 2, 3, 3],  # fuera de escala
    ])
    resumen = _consolidar(raiz)
    f = _fila(resumen, "d4_rubrica", "uwf", "nodex_multiagente")
    assert f["completitud"] == pytest.approx(2.5)
    assert f["promedio_global"] == pytest.approx(2.3)
    assert f["acuerdo_exacto"] == pytest.approx(0.6)
    assert f["desacuerdos_relevantes"] == 1
    assert "rubrica_filas_invalidas" in {a["codigo"] for a in resumen["integridad"]["advertencias"]}


# --- escritura -----------------------------------------------------------------------------

def test_la_consolidacion_no_sobrescribe(campana):
    raiz, _ = campana
    consolidacion.consolidar(raiz, "sub", CONFIG, ARQUITECTURAS, marca=MARCA)
    with pytest.raises(FileExistsError, match="no se sobrescriben"):
        consolidacion.consolidar(raiz, "sub", CONFIG, ARQUITECTURAS, marca=MARCA)


def test_se_escriben_las_tablas_el_contrato_y_la_tabla_14(campana):
    raiz, _ = campana
    destino = consolidacion.consolidar(raiz, "sub", CONFIG, ARQUITECTURAS, marca=MARCA)
    nombres = {p.name for p in destino.iterdir()}
    for esperado in ("resumen.json", "registros.json", "tabla_14.csv",
                     "d1_deteccion.csv", "d2_reconstruccion.csv", "consumo.csv",
                     "comparacion.csv", "errores_d1.csv"):
        assert esperado in nombres, esperado
    assert any(n.startswith("metricas_p") and n.endswith("_contrato.json") for n in nombres)
    with (destino / "tabla_14.csv").open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        filas = list(lector)
        assert tuple(lector.fieldnames) == exportacion.COLUMNAS
    assert len(filas) == 17        # 18 esperadas menos la que falló


def test_la_consolidacion_no_toca_las_carpetas_de_resultados_del_repositorio(campana):
    """Todo ocurre en `tmp_path`: lo que haya en `experiments/metrics` y `experiments/outputs` del
    repo (p. ej. los resultados reales del piloto) queda exactamente igual."""
    raiz, _ = campana
    repo = Path(__file__).resolve().parents[2] / "experiments"

    def instantanea():
        return {str(p.relative_to(repo)): p.stat().st_mtime_ns
                for carpeta in ("metrics", "outputs") if (repo / carpeta).exists()
                for p in (repo / carpeta).rglob("*")}

    antes = instantanea()
    consolidacion.consolidar(raiz, "sub", CONFIG, ARQUITECTURAS, marca=MARCA)
    assert instantanea() == antes


# --- línea de comandos ---------------------------------------------------------------

def test_la_linea_de_comandos_se_niega_a_consolidar_si_no_hay_corridas(tmp_path, capsys):
    """Una invocación accidental no debe dejar carpetas vacías en
    experiments/metrics/."""
    _construir_repo(tmp_path)
    codigo = consolidacion.main(
        ["--subconjunto", "sub", "--config", CONFIG], raiz_repo=tmp_path)
    assert codigo == 2
    assert "No se crea ninguna consolidación" in capsys.readouterr().out
    assert not (tmp_path / "experiments" / "metrics").exists()


def test_la_linea_de_comandos_consolida_y_resume_la_integridad(campana, capsys):
    raiz, _ = campana
    codigo = consolidacion.main(
        ["--subconjunto", "sub", "--config", CONFIG, "--arquitecturas",
         "nodex_multiagente", "baseline_reglas", "gemini_externo", "--marca", MARCA],
        raiz_repo=raiz)
    salida = capsys.readouterr().out
    assert codigo == 0
    assert (raiz / "experiments" / "metrics" / CONFIG / MARCA / "resumen.json").is_file()
    assert "fallidas 1" in salida
    assert "[alta]" in salida          # la corrida fallida y el fallback se anuncian


def test_la_linea_de_comandos_exige_subconjunto_y_configuracion():
    with pytest.raises(SystemExit):
        consolidacion.main(["--subconjunto", "sub"])


# --- versión devuelta por la API y tokens de razonamiento ------------------------
#
# La instrumentación vive en src/llm.py; acá se prueba que lo que registra llegue
# a lo que se ve: la telemetría guardada, la tabla de consumo, la tabla del §14 y
# los avisos de integridad. Regla: lo que el proveedor no informa queda vacío
# (`None`), nunca en 0.

def _telemetria_guardada(raiz, cid, dataset, arquitectura="nodex_multiagente") -> dict:
    ident = IdentidadCorrida(cid, dataset, arquitectura, 1, CONFIG)
    return persistencia.leer_telemetria(ident, raiz)


def test_la_telemetria_guardada_lleva_los_tokens_de_razonamiento_y_la_version(campana):
    """El orquestador alimenta `campos_de_modelo` al guardar la corrida."""
    raiz, _ = campana
    uwf = _telemetria_guardada(raiz, "uwf_des_visible_0001", "uwf")
    assert uwf["reasoning_tokens"] == 40
    assert uwf["modelos_efectivos"] == [f"{PRINCIPAL}-001"]
    bgl = _telemetria_guardada(raiz, "bgl_des_natural_0000", "bgl")
    assert bgl["reasoning_tokens"] is None            # no informado: None, no 0
    assert bgl["modelos_efectivos"] == [f"{PRINCIPAL}-001"]


def test_los_tokens_de_razonamiento_y_la_version_llegan_a_la_tabla_de_consumo(campana):
    raiz, _ = campana
    resumen = _consolidar(raiz)
    nodex_uwf = _fila(resumen, "consumo", "uwf", "nodex_multiagente")
    assert nodex_uwf["tokens_razonamiento_medios"] == pytest.approx(40)
    # una corrida cayó al respaldo: se ven las dos versiones
    assert nodex_uwf["versiones_devueltas"] == f"{PRINCIPAL}-001; {RESPALDO}-001"
    gemini = _fila(resumen, "consumo", "uwf", "gemini_externo")
    assert gemini["tokens_razonamiento_medios"] == pytest.approx(12)
    assert gemini["versiones_devueltas"] == f"{PRINCIPAL}-001"


def test_lo_que_el_proveedor_no_informo_queda_vacio_y_no_es_cero(campana):
    raiz, _ = campana
    resumen = _consolidar(raiz)
    bgl = _fila(resumen, "consumo", "bgl", "nodex_multiagente")
    assert bgl["tokens_razonamiento_medios"] is None
    assert bgl["versiones_devueltas"] == f"{PRINCIPAL}-001"   # la versión sí vino
    baseline = _fila(resumen, "consumo", "uwf", "baseline_reglas")
    assert baseline["tokens_razonamiento_medios"] is None
    assert baseline["versiones_devueltas"] is None            # no usa el modelo


def test_la_tabla_14_exporta_razonamiento_y_versiones_con_celdas_vacias_donde_no_hay(campana):
    raiz, _ = campana
    destino = consolidacion.consolidar(raiz, "sub", CONFIG, ARQUITECTURAS, marca=MARCA)
    with (destino / "tabla_14.csv").open(encoding="utf-8", newline="") as f:
        filas = {(r["case_id"], r["architecture"]): r for r in csv.DictReader(f)}
    uwf = filas[("uwf_des_visible_0001", "nodex_multiagente")]
    assert uwf["reasoning_tokens"] == "40"
    assert uwf["modelos_efectivos"] == f"{PRINCIPAL}-001"
    bgl = filas[("bgl_des_natural_0000", "nodex_multiagente")]
    assert bgl["reasoning_tokens"] == ""              # vacío, no "0"
    assert filas[("uwf_des_visible_0000", "nodex_multiagente")]["modelos_efectivos"] == (
        f"{RESPALDO}-001")
    base = filas[("uwf_des_visible_0001", "baseline_reglas")]
    assert base["reasoning_tokens"] == "" and base["modelos_efectivos"] == ""


def test_una_version_distinta_del_nombre_pedido_no_cuenta_como_fallback():
    """La API puede devolver `modelo-001` cuando se pidió `modelo`: eso no es
    un respaldo. El fallback se decide con el nombre pedido en cada llamada."""
    telemetria = {"llm_calls": [{"model": PRINCIPAL, "model_version": f"{PRINCIPAL}-001"}]}
    assert consolidacion.uso_fallback(telemetria, PRINCIPAL) is False
    caida = {"llm_calls": [{"model": PRINCIPAL}, {"model": RESPALDO}]}
    assert consolidacion.uso_fallback(caida, PRINCIPAL) is True


def test_los_avisos_de_integridad_declaran_lo_no_informado(campana):
    raiz, _ = campana
    avisos = {a["codigo"]: a for a in _consolidar(raiz)["integridad"]["advertencias"]}
    assert avisos["razonamiento_no_informado"]["n"] == 2      # las 2 de NODEX en BGL
    assert avisos["razonamiento_no_informado"]["severidad"] == "info"
    assert "version_de_modelo_no_informada" not in avisos     # todas la informaron


def test_las_corridas_guardadas_antes_de_la_instrumentacion_no_inventan_datos(campana):
    """Una telemetría vieja (sin `model_version` ni `reasoning_tokens`) queda
    como no informada; no se rellena con 0 ni con el nombre pedido."""
    raiz, _ = campana
    ident = IdentidadCorrida("uwf_des_visible_0001", "uwf", "nodex_multiagente", 1, CONFIG)
    ruta = persistencia.rutas(ident, raiz).telemetria
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    tel = datos["telemetria"]
    for clave in ("reasoning_tokens", "modelos_efectivos", "campos_parciales"):
        tel.pop(clave)
    for llamada in tel["llm_calls"]:
        llamada.pop("reasoning_tokens")
        llamada.pop("model_version")
    ruta.write_text(json.dumps(datos), encoding="utf-8")

    resumen = _consolidar(raiz)
    avisos = {a["codigo"]: a for a in resumen["integridad"]["advertencias"]}
    assert avisos["razonamiento_no_informado"]["n"] == 3
    assert avisos["version_de_modelo_no_informada"]["n"] == 1
    # el promedio de las que sí informaron no se arrastra hacia 0
    f = _fila(resumen, "consumo", "uwf", "nodex_multiagente")
    assert f["tokens_razonamiento_medios"] == pytest.approx(40)


# --- totales None por una llamada fallida: suma parcial rotulada ------------------------------
#
# `src/telemetry.py` calcula los totales de tokens de forma todo-o-nada: una llamada
# fallida deja los de TODA la corrida en None (corrida 4 de la comparación de modelos).
# El consolidador muestra lo que sí se sabe como un PISO rotulado, nunca como total, y esas
# corridas quedan fuera de las medias.

def _llamada_ok(entrada, salida, razonamiento):
    return {"model": PRINCIPAL, "model_version": f"{PRINCIPAL}-001", "input_tokens": entrada,
            "output_tokens": salida, "total_tokens": entrada + salida + razonamiento,
            "reasoning_tokens": razonamiento, "duration_s": 2.0, "error": None}


def _llamada_fallida():
    return {"model": PRINCIPAL, "model_version": None, "input_tokens": None,
            "output_tokens": None, "total_tokens": None, "reasoning_tokens": None,
            "duration_s": 90.0, "error": "ServerError(503)"}


def test_tokens_de_la_corrida_distingue_completa_parcial_y_sin_datos():
    ok = _llamada_ok(10, 5, 3)
    completa = consolidacion.tokens_de_la_corrida({"llm_calls": [ok, dict(ok)]})
    assert completa["completa"] is True and completa["n_fallidas"] == 0
    parcial = consolidacion.tokens_de_la_corrida({"llm_calls": [ok, _llamada_fallida(), dict(ok)]})
    assert parcial["completa"] is False
    assert (parcial["n_llamadas"], parcial["n_con_tokens"], parcial["n_fallidas"]) == (3, 2, 1)
    assert (parcial["entrada"], parcial["salida"], parcial["razonamiento"]) == (20, 10, 6)
    vacia = consolidacion.tokens_de_la_corrida({"llm_calls": []})
    assert vacia["completa"] is False and vacia["entrada"] is None
    assert consolidacion.tokens_de_la_corrida(None)["n_llamadas"] == 0


def test_una_corrida_es_parcial_solo_si_el_total_es_none_y_algunas_llamadas_informaron():
    ok = _llamada_ok(10, 5, 3)
    assert consolidacion.es_parcial({"total_tokens": None, "llm_calls": [ok, _llamada_fallida()]})
    # total completo: no es parcial
    assert not consolidacion.es_parcial({"total_tokens": 36, "llm_calls": [ok, dict(ok)]})
    # ninguna informó: no hay suma parcial que mostrar (es «sin tokens»)
    assert not consolidacion.es_parcial(
        {"total_tokens": None, "llm_calls": [_llamada_fallida(), _llamada_fallida()]})


def test_la_suma_parcial_va_con_piso_y_con_cuantas_llamadas_la_sustentan():
    ok = _llamada_ok(9000, 2000, 9800)
    texto = consolidacion.texto_tokens_parciales(
        [{"llm_calls": [ok] * 11 + [_llamada_fallida()]}])
    assert texto == "≥ 99.000 entrada · ≥ 22.000 salida · ≥ 107.800 razonamiento (11 de 12 llamadas)"
    assert consolidacion.texto_tokens_parciales([]) is None
    assert consolidacion.texto_tokens_parciales([{"llm_calls": [_llamada_fallida()]}]) is None


def _reescribir_telemetria(raiz, cid, dataset, llamadas, totales=None):
    ident = IdentidadCorrida(cid, dataset, "nodex_multiagente", 1, CONFIG)
    ruta = persistencia.rutas(ident, raiz).telemetria
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["telemetria"]["llm_calls"] = llamadas
    datos["telemetria"]["llm_call_count"] = len(llamadas)
    datos["telemetria"].update({"input_tokens": None, "output_tokens": None,
                                "total_tokens": None} if totales is None else totales)
    ruta.write_text(json.dumps(datos), encoding="utf-8")


def test_una_corrida_con_llamada_fallida_queda_fuera_de_la_media_y_se_muestra_como_parcial(campana):
    raiz, _ = campana
    _reescribir_telemetria(raiz, "uwf_des_visible_0001", "uwf",
                           [_llamada_ok(10, 5, 3), _llamada_fallida(), _llamada_ok(20, 7, 4)])
    f = _fila(_consolidar(raiz), "consumo", "uwf", "nodex_multiagente")
    # la media de las otras 3 corridas completas (1000 cada una) NO se mezcla con el piso
    assert f["tokens_entrada_medios"] == pytest.approx(1000)
    assert f["n_sin_tokens"] == 1                      # corridas con total None
    assert f["n_llamadas_fallidas"] == 1
    assert f["tokens_parciales"] == "≥ 30 entrada · ≥ 12 salida · ≥ 7 razonamiento (2 de 3 llamadas)"


def test_los_grupos_sin_corridas_parciales_no_muestran_suma_parcial(campana):
    raiz, _ = campana
    resumen = _consolidar(raiz)
    for dataset, arq in (("uwf", "nodex_multiagente"), ("bgl", "nodex_multiagente"),
                         ("uwf", "gemini_externo")):
        assert _fila(resumen, "consumo", dataset, arq)["tokens_parciales"] is None
    # el baseline no usa el modelo: estas celdas no aplican
    baseline = _fila(resumen, "consumo", "uwf", "baseline_reglas")
    assert baseline["tokens_parciales"] is None and baseline["n_llamadas_fallidas"] is None


def test_el_aviso_tokens_parciales_lista_la_corrida_y_no_se_confunde_con_tokens_no_informados(campana):
    raiz, _ = campana
    _reescribir_telemetria(raiz, "uwf_des_visible_0001", "uwf",
                           [_llamada_ok(10, 5, 3), _llamada_fallida()])
    integridad = _consolidar(raiz)["integridad"]
    avisos = {a["codigo"]: a for a in integridad["advertencias"]}
    assert avisos["tokens_parciales"]["n"] == 1
    assert avisos["tokens_parciales"]["severidad"] == "media"
    assert "tokens_no_informados" not in avisos        # esta SÍ tiene datos parciales
    detalle = integridad["corridas_con_tokens_parciales"]
    assert len(detalle) == 1
    assert (detalle[0]["n_llamadas"], detalle[0]["n_con_tokens"],
            detalle[0]["n_llamadas_fallidas"]) == (2, 1, 1)
    assert detalle[0]["tokens_entrada_parcial"] == 10


def test_una_corrida_sin_ningun_token_sigue_siendo_tokens_no_informados_y_no_parcial(campana):
    raiz, _ = campana
    _reescribir_telemetria(raiz, "uwf_des_visible_0001", "uwf",
                           [_llamada_fallida(), _llamada_fallida()])
    resumen = _consolidar(raiz)
    integridad = resumen["integridad"]
    avisos = {a["codigo"]: a for a in integridad["advertencias"]}
    assert avisos["tokens_no_informados"]["n"] == 1
    assert "tokens_parciales" not in avisos
    assert integridad["corridas_con_tokens_parciales"] == []
    f = _fila(resumen, "consumo", "uwf", "nodex_multiagente")
    assert f["tokens_parciales"] is None and f["n_llamadas_fallidas"] == 2


def test_una_llamada_con_error_cuenta_como_fallida_aunque_traiga_tokens():
    """El error registrado manda: una llamada que falló después de responder (p. ej. al
    leer el consumo) no es una llamada sana. Y una sin error ni tokens (telemetría
    anterior a este registro) tampoco se da por sana."""
    con_error = {"input_tokens": 5, "output_tokens": 2, "error": "KeyError"}
    sin_nada = {"model": PRINCIPAL}
    sana = _llamada_ok(1, 1, 1)
    d = consolidacion.tokens_de_la_corrida({"llm_calls": [con_error, sin_nada, sana]})
    assert d["n_fallidas"] == 2


# --- depuración y consultas externas ----------------------------------------------------------

def test_los_resultados_de_desarrollo_se_marcan_de_depuracion_y_no_reportables(campana):
    raiz, _ = campana
    resumen = _consolidar(raiz)
    assert resumen["depuracion"] is True and resumen["reportable"] is False
    avisos = {a["codigo"]: a for a in resumen["integridad"]["advertencias"]}
    assert avisos["resultados_de_depuracion"]["severidad"] == "alta"
    assert "no son reportables" in avisos["resultados_de_depuracion"]["mensaje"]


def test_la_depuracion_se_puede_apagar_explicitamente_para_una_campana_reportable(campana):
    raiz, _ = campana
    destino = consolidacion.consolidar(raiz, "sub", CONFIG, ARQUITECTURAS, marca=MARCA,
                                       depuracion=False)
    resumen = json.loads((destino / "resumen.json").read_text(encoding="utf-8"))
    assert resumen["depuracion"] is False and resumen["reportable"] is True
    assert "resultados_de_depuracion" not in {
        a["codigo"] for a in resumen["integridad"]["advertencias"]}


def test_los_datos_ficticios_nunca_son_reportables(campana):
    raiz, _ = campana
    destino = consolidacion.consolidar(raiz, "sub", CONFIG, ARQUITECTURAS, marca=MARCA,
                                       datos_ficticios=True, depuracion=False)
    resumen = json.loads((destino / "resumen.json").read_text(encoding="utf-8"))
    assert resumen["reportable"] is False


def _guardar_consultas(raiz, cid, dataset, consultas, arquitectura="nodex_multiagente"):
    ident = IdentidadCorrida(cid, dataset, arquitectura, 1, CONFIG)
    persistencia.guardar_consultas_externas(ident, raiz, consultas)


def _consulta(herramienta, intento=True, respaldo=True):
    return {"herramienta": herramienta, "parametros": {}, "intento_externo": intento,
            "bloqueado": intento, "respaldo_respondio": respaldo, "fuente_respuesta": "fallback"}


def _fila_ext(resumen, dataset, arquitectura, herramienta):
    return next(f for f in resumen["tablas"]["consultas_externas"]["filas"]
                if (f["dataset"], f["arquitectura"], f["herramienta"]) ==
                (dataset, arquitectura, herramienta))


def test_la_tabla_de_consultas_externas_cuenta_por_arquitectura_dataset_y_herramienta(campana):
    raiz, _ = campana
    _guardar_consultas(raiz, "uwf_des_visible_0000", "uwf",
                       [_consulta("abuseipdb"), _consulta("abuseipdb"), _consulta("nvd")])
    _guardar_consultas(raiz, "uwf_des_visible_0001", "uwf", [_consulta("nvd", intento=False)])
    _guardar_consultas(raiz, "uwf_des_visible_0002", "uwf", [])         # no consultó nada
    resumen = _consolidar(raiz)
    ab = _fila_ext(resumen, "uwf", "nodex_multiagente", "abuseipdb")
    assert (ab["n_corridas"], ab["n_con_registro"]) == (4, 3)            # la 0003 no tiene registro
    assert (ab["n_consultas"], ab["n_intentos_externos"], ab["n_bloqueados"],
            ab["n_respaldo_respondio"], ab["n_corridas_con_intentos"]) == (2, 2, 2, 2, 1)
    nvd = _fila_ext(resumen, "uwf", "nodex_multiagente", "nvd")
    assert (nvd["n_consultas"], nvd["n_intentos_externos"], nvd["n_respaldo_respondio"]) == (2, 1, 2)


def test_cero_consultas_registradas_es_cero_y_no_se_confunde_con_sin_registro(campana):
    raiz, _ = campana
    for cid in ("uwf_des_visible_0000", "uwf_des_visible_0001", "uwf_des_visible_0002",
                "uwf_des_visible_0003"):
        _guardar_consultas(raiz, cid, "uwf", [])
    resumen = _consolidar(raiz)
    con = _fila_ext(resumen, "uwf", "nodex_multiagente", "nvd")
    assert con["n_consultas"] == 0 and con["n_intentos_externos"] == 0       # medido: cero
    sin = _fila_ext(resumen, "bgl", "nodex_multiagente", "nvd")              # nadie guardó nada
    assert sin["n_consultas"] is None and sin["estado"] == "sin registro"    # no medido: None


def test_gemini_directo_y_el_baseline_no_usan_herramientas_y_sus_celdas_no_aplican(campana):
    raiz, _ = campana
    resumen = _consolidar(raiz)
    for arq in ("gemini_externo", "baseline_reglas"):
        f = _fila_ext(resumen, "uwf", arq, "abuseipdb")
        assert f["n_consultas"] is None and f["n_intentos_externos"] is None
        assert f["estado"] == "no aplica"


def test_el_aviso_cuenta_los_intentos_bloqueados_y_es_informativo(campana):
    raiz, _ = campana
    _guardar_consultas(raiz, "uwf_des_visible_0000", "uwf",
                       [_consulta("abuseipdb"), _consulta("nvd"), _consulta("nvd", intento=False)])
    avisos = {a["codigo"]: a for a in _consolidar(raiz)["integridad"]["advertencias"]}
    assert avisos["consultas_externas_bloqueadas"]["n"] == 2
    assert avisos["consultas_externas_bloqueadas"]["severidad"] == "info"
    assert "pendiente" in avisos["consultas_externas_bloqueadas"]["mensaje"]


def test_sin_registros_de_consultas_no_hay_aviso_de_bloqueos(campana):
    raiz, _ = campana
    avisos = {a["codigo"] for a in _consolidar(raiz)["integridad"]["advertencias"]}
    assert "consultas_externas_bloqueadas" not in avisos


def test_la_tabla_de_consultas_externas_se_escribe_como_csv(campana):
    raiz, _ = campana
    destino = consolidacion.consolidar(raiz, "sub", CONFIG, ARQUITECTURAS, marca=MARCA)
    assert (destino / "consultas_externas.csv").is_file()


def test_la_tabla_de_consultas_externas_no_lleva_texto_largo_por_fila(campana):
    """Defecto de la vista: una columna «Nota» con una frase larga partía las celdas y estiraba
    las filas de NODEX. Cada fila lleva un estado corto; la explicación va en la descripción."""
    raiz, _ = campana
    _guardar_consultas(raiz, "uwf_des_visible_0000", "uwf", [_consulta("nvd")])
    tabla = _consolidar(raiz)["tablas"]["consultas_externas"]
    claves = [c["clave"] for c in tabla["columnas"]]
    assert "nota" not in claves and "estado" in claves
    assert {f["estado"] for f in tabla["filas"]} == {"medido", "no aplica", "sin registro"}
    assert all(len(f["estado"]) <= 12 for f in tabla["filas"])
    assert "no aplica" in tabla["descripcion"] and "respaldo local" in tabla["descripcion"]


def test_las_etiquetas_de_consumo_son_cortas_y_la_explicacion_va_en_la_descripcion(campana):
    raiz, _ = campana
    tabla = _consolidar(raiz)["tablas"]["consumo"]
    etiquetas = {c["clave"]: c["etiqueta"] for c in tabla["columnas"]}
    assert etiquetas["n_sin_tokens"] == "Corridas con total None"
    assert etiquetas["tokens_parciales"].startswith("Tokens parciales")
    assert all(len(e) <= 34 for e in etiquetas.values()), etiquetas
    assert "Corridas con total None" in tabla["descripcion"]


# --- salud estructural del piloto (solo lee lo guardado) ------------------------------------------

def _salud(raiz):
    from src.experimentation import salud_piloto
    _consolidar(raiz)
    return salud_piloto.analizar(raiz, "sub", CONFIG, ARQUITECTURAS)


def _celda(r, arq, ds):
    return next(x for x in r["resumen"] if x["arquitectura"] == arq and x["dataset"] == ds)


def test_la_salud_estructural_tiene_una_fila_por_corrida_y_una_celda_por_arquitectura_y_dataset(campana):
    raiz, _ = campana
    r = _salud(raiz)
    assert len(r["filas"]) == 18                                  # 6 casos × 3 arquitecturas
    assert {(x["arquitectura"], x["dataset"]) for x in r["resumen"]} == {
        (a, d) for a in ARQUITECTURAS for d in ("bgl", "uwf")}
    assert "no es un resultado reportable" in r["aviso"] and "ni mide acierto" in r["aviso"]


def test_una_corrida_que_fallo_no_se_cuenta_como_guardada_ni_como_json_valido(campana):
    raiz, _ = campana
    g = _celda(_salud(raiz), "gemini_externo", "bgl")
    assert g["corridas"] == 2 and g["guardadas"] == 1             # bgl_des_natural_0001 reventó
    assert g["json_valido_n"] == "1/1"                            # el denominador son las guardadas


def test_json_valido_solo_se_informa_donde_se_puede_medir(campana):
    raiz, _ = campana
    r = _salud(raiz)
    assert _celda(r, "gemini_externo", "uwf")["json_valido_pct"] == 100.0
    nodex = _celda(r, "nodex_multiagente", "uwf")
    assert nodex["json_valido_pct"] is None and nodex["json_valido_n"] is None   # no medido: None
    assert nodex["proxy_json_valido_pct"] == 100.0                               # el proxy va aparte
    base = _celda(r, "baseline_reglas", "uwf")
    assert base["json_valido_pct"] is None and base["proxy_json_valido_pct"] is None


def test_el_veredicto_presente_lleva_su_denominador(campana):
    raiz, _ = campana
    c = _celda(_salud(raiz), "nodex_multiagente", "uwf")
    assert c["veredicto_presente_n"] == "4/4" and c["veredicto_presente_pct"] == 100.0


def test_d2_y_d3_distinguen_evaluable_no_evaluable_y_no_aplica(campana):
    raiz, _ = campana
    r = _salud(raiz)
    uwf = _celda(r, "nodex_multiagente", "uwf")
    assert uwf["d2_con_contenido"] == 2 and uwf["d3_con_contenido"] == 1
    # Estado FINAL (salida cruzada con la referencia): solo los 2 casos con incidente tienen
    # referencia de reconstrucción; en los 2 normales la dimensión NO APLICA aunque el sistema
    # haya devuelto eventos (el caso 0002, un falso positivo, los devolvió).
    # Regla v2: el caso positivo SIN eventos (falso negativo) en una corrida válida es una OMISIÓN y
    # cuenta como evaluable (exhaustividad 0); ya no es «no evaluable».
    assert (uwf["d2_evaluable"], uwf["d2_no_evaluable"], uwf["d2_no_aplica"]) == (2, 0, 2)
    assert (uwf["d3_evaluable"], uwf["d3_no_evaluable"], uwf["d3_no_aplica"]) == (2, 0, 2)
    bgl = _celda(r, "nodex_multiagente", "bgl")
    assert bgl["d2_no_aplica"] == 2 and bgl["d3_no_aplica"] == 2  # BGL: no aplica


def test_los_uids_inventados_se_cuentan_por_celda_y_solo_para_las_arquitecturas_con_modelo(campana):
    raiz, _ = campana
    r = _salud(raiz)
    assert _celda(r, "gemini_externo", "uwf")["uids_inventados_d2_mayor_que_0"] == 1   # U99
    assert _celda(r, "nodex_multiagente", "uwf")["uids_inventados_d2_mayor_que_0"] == 0
    assert _celda(r, "baseline_reglas", "uwf")["uids_inventados_d2_mayor_que_0"] is None


def test_el_contador_de_evidencia_invalida_del_sistema_solo_existe_para_nodex(campana):
    raiz, _ = campana
    r = _salud(raiz)
    assert _celda(r, "nodex_multiagente", "uwf")["invalid_uid_contador_mayor_que_0"] == 0
    assert _celda(r, "gemini_externo", "uwf")["invalid_uid_contador_mayor_que_0"] is None


def test_la_matriz_de_confusion_cuenta_los_cuatro_cuadrantes_por_celda(campana):
    raiz, _ = campana
    d1 = _celda(_salud(raiz), "nodex_multiagente", "uwf")["d1"]
    assert (d1["TP"], d1["FP"], d1["FN"], d1["TN"]) == (1, 1, 1, 1) and d1["NA"] == 0
    assert sum(d1.values()) == 4


def test_la_salud_estructural_se_niega_a_correr_sobre_la_particion_de_evaluacion(campana, tmp_path):
    from src.experimentation import salud_piloto
    raiz, _ = campana
    _consolidar(raiz)                      # primero se consolida, como de desarrollo
    ruta = raiz / "experiments" / "subconjuntos" / "sub.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["particion"] = "evaluacion"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    with pytest.raises(ValueError, match="SOLO de casos de desarrollo"):
        salud_piloto.analizar(raiz, "sub", CONFIG, ARQUITECTURAS)


def test_el_modulo_de_salud_no_abre_ground_truth_ni_ejecuta_arquitecturas():
    import ast
    import inspect
    from src.experimentation import salud_piloto
    arbol = ast.parse(inspect.getsource(salud_piloto))
    docs = {id(n.body[0].value) for n in ast.walk(arbol)
            if isinstance(n, (ast.Module, ast.FunctionDef)) and n.body
            and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    cadenas = [n.value for n in ast.walk(arbol) if isinstance(n, ast.Constant)
               and isinstance(n.value, str) and id(n) not in docs]
    assert not any("ground_truth" in c for c in cadenas)
    importados = {n.module for n in ast.walk(arbol) if isinstance(n, ast.ImportFrom)}
    assert not any(m and "runners" in m for m in importados)
    assert not any(m and "evaluacion" == m.rsplit(".", 1)[-1] for m in importados)


def test_una_salida_sin_veredicto_baja_el_porcentaje_de_veredicto_presente(campana):
    raiz, _ = campana
    ident = IdentidadCorrida("uwf_des_visible_0003", "uwf", "nodex_multiagente", 1, CONFIG)
    ruta = persistencia.rutas(ident, raiz).salida
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["salida"]["_meta"]["veredicto_booleano_presente"] = False
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    c = _celda(_salud(raiz), "nodex_multiagente", "uwf")
    assert c["veredicto_presente_n"] == "3/4" and c["veredicto_presente_pct"] == 75.0
    assert c["proxy_json_valido_pct"] == 75.0           # el proxy también lo refleja


def test_el_estado_de_la_salida_se_conserva_aparte_del_estado_final(campana):
    raiz, _ = campana
    filas = {f["case_id"]: f for f in _salud(raiz)["filas"] if f["arquitectura"] == "nodex_multiagente"}
    fp = filas["uwf_des_visible_0002"]           # falso positivo: devolvió eventos pero no hay referencia
    assert fp["estado_d2_salida"] == "evaluable" and fp["estado_d2"] == "no_aplica"
    fn = filas["uwf_des_visible_0001"]           # falso negativo: hay referencia pero no devolvió nada
    # la salida no trajo nada (no_evaluable del lado de la salida), pero la corrida es válida y hay
    # referencia: el estado FINAL es «evaluable» por omisión (regla v2)
    assert fn["estado_d2_salida"] == "no_evaluable" and fn["estado_d2"] == "evaluable"


# --- ENMIENDA D2/D3 (15-oct-2026, fijada antes de la campaña): la omisión cuenta ----------------------
#
# Observación del piloto de desarrollo: los casos con incidente en que el sistema no atribuyó ninguna
# técnica (ni dio eventos) salían de la métrica como «no evaluables», y la exhaustividad quedaba calculada
# solo sobre los casos en que el sistema sí habló. Ahora, con la corrida válida y completa y la referencia
# existente, la omisión cuenta: exhaustividad 0 y precisión indefinida. Una corrida fallida o de formato
# inválido sigue «no evaluable» y se informa aparte.

def _registros_de(raiz):
    destino = consolidacion.consolidar(raiz, "sub", CONFIG, ARQUITECTURAS, marca=MARCA)
    return {r["run_id"]: r for r in json.loads((destino / "registros.json").read_text(encoding="utf-8"))}


def _id(cid, arq="nodex_multiagente", ds="uwf"):
    return IdentidadCorrida(cid, ds, arq, 1, CONFIG).run_id


def _modificar_salida(raiz, cid, cambio, arq="nodex_multiagente"):
    ident = IdentidadCorrida(cid, "uwf", arq, 1, CONFIG)
    ruta = persistencia.rutas(ident, raiz).salida
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    cambio(datos)
    ruta.write_text(json.dumps(datos), encoding="utf-8")


def test_una_omision_cuenta_con_exhaustividad_cero_y_precision_indefinida(campana):
    """El caso 0001 es un incidente en que NODEX no dio eventos: antes salía de la métrica."""
    raiz, _ = campana
    reg = _registros_de(raiz)[_id("uwf_des_visible_0001")]
    assert reg["omision_d2"] is True and reg["omision_d3"] is True
    assert reg["estados"]["reconstruccion"] == "evaluable" and reg["estados"]["mitre"] == "evaluable"
    assert (reg["d2"]["tp"], reg["d2"]["fp"], reg["d2"]["fn"]) == (0, 0, 1)
    assert (reg["d3"]["tp"], reg["d3"]["fp"], reg["d3"]["fn"]) == (0, 0, 1)


def test_la_exhaustividad_ya_no_se_calcula_solo_sobre_los_casos_en_que_el_sistema_hablo(campana):
    raiz, _ = campana
    f = _fila(_consolidar(raiz), "d2_reconstruccion", "uwf", "nodex_multiagente")
    assert f["micro_recall"] == pytest.approx(2 / 3)       # antes 1,0: el caso callado no contaba
    assert f["micro_precision"] == pytest.approx(1.0)      # sin predicciones no hay falsos positivos
    assert f["macro_recall"] == pytest.approx(0.5)         # (1 + 0) / 2: la omisión pesa como 0
    assert f["macro_precision"] == pytest.approx(1.0)      # la precisión indefinida NO se promedia como 0
    assert f["micro_f1"] == pytest.approx(0.8)             # 2·2 / (2·2 + 0 + 1)
    assert f["exact_match"] == pytest.approx(0.5)


def test_la_precision_de_una_omision_es_indefinida_y_no_cero(campana):
    from src.experimentation.evaluators.conjuntos import ComparacionConjuntos
    raiz, _ = campana
    reg = _registros_de(raiz)[_id("uwf_des_visible_0001")]
    c = ComparacionConjuntos(case_id="x", propuesto=frozenset(), referencia=frozenset({"U3"}))
    assert (c.tp, c.fp, c.fn) == (reg["d2"]["tp"], reg["d2"]["fp"], reg["d2"]["fn"])
    from src.experimentation.evaluators.conjuntos import _metricas_de_conteos
    m = _metricas_de_conteos(c.tp, c.fp, c.fn)
    assert m["precision"] is None and m["recall"] == 0.0 and m["f1"] == 0.0


def test_la_cobertura_y_las_omisiones_se_publican_junto_a_cada_cifra(campana):
    raiz, _ = campana
    resumen = _consolidar(raiz)
    d2 = _fila(resumen, "d2_reconstruccion", "uwf", "nodex_multiagente")
    assert d2["cobertura"] == "2 de 2" and d2["n_omisiones"] == 1 and d2["no_evaluables"] == 0
    d3 = _fila(resumen, "d3_mitre", "uwf", "nodex_multiagente")
    assert d3["cobertura"] == "2 de 2" and d3["n_omisiones"] == 1
    g = _fila(resumen, "d2_reconstruccion", "uwf", "gemini_externo")
    assert g["cobertura"] == "2 de 2" and g["n_omisiones"] == 0
    tabla = resumen["tablas"]["d2_reconstruccion"]
    assert "Cobertura" in [c["etiqueta"] for c in tabla["columnas"]][3]
    assert "Omisión" in tabla["descripcion"] and "enmienda" in tabla["descripcion"]


def test_la_cobertura_cuenta_solo_las_corridas_a_las_que_la_dimension_aplica(campana):
    """UWF tiene 4 casos por arquitectura, pero solo 2 con incidente: los normales no tienen
    referencia de reconstrucción, así que el denominador es 2, no 4."""
    raiz, _ = campana
    d2 = _fila(_consolidar(raiz), "d2_reconstruccion", "uwf", "nodex_multiagente")
    assert d2["n_corridas"] == 4 and d2["cobertura"] == "2 de 2"


def test_sin_referencia_el_silencio_no_es_una_omision(campana):
    """Un caso normal (sin referencia de eventos) en que el sistema no entrega nada es correcto."""
    raiz, _ = campana
    reg = _registros_de(raiz)[_id("uwf_des_visible_0003")]          # verdadero negativo
    assert reg["estados"]["reconstruccion"] == "no_aplica" and reg["omision_d2"] is False
    assert reg["d2"] is None


def test_un_sistema_que_entrega_algo_no_es_una_omision(campana):
    raiz, _ = campana
    reg = _registros_de(raiz)[_id("uwf_des_visible_0000")]
    assert reg["omision_d2"] is False and reg["omision_d3"] is False


@pytest.mark.parametrize("cambio, motivo", [
    (lambda d: d["ejecucion"].update({"estado": "error_contrato"}), "corrida con error de contrato"),
    (lambda d: d["ejecucion"].update({"estado": "error_api"}), "corrida con error de API"),
    (lambda d: d["ejecucion"].update({"estado": "timeout"}), "corrida con timeout"),
    (lambda d: d["salida"]["_meta"].update({"veredicto_booleano_presente": False}), "formato inválido"),
    (lambda d: d.pop("ejecucion"), "sin metadatos de ejecución"),
])
def test_una_corrida_fallida_o_de_formato_invalido_sigue_no_evaluable_y_se_informa_aparte(
        campana, cambio, motivo):
    raiz, _ = campana
    _modificar_salida(raiz, "uwf_des_visible_0001", cambio)
    resumen = _consolidar(raiz)
    d2 = _fila(resumen, "d2_reconstruccion", "uwf", "nodex_multiagente")
    assert d2["no_evaluables"] == 1 and d2["n_omisiones"] == 0, motivo
    assert d2["cobertura"] == "1 de 2", motivo           # la cobertura baja: se ve que falta un caso
    assert d2["micro_recall"] == pytest.approx(1.0), motivo   # y NO se le inventa un cero
    d3 = _fila(resumen, "d3_mitre", "uwf", "nodex_multiagente")
    assert d3["no_evaluables"] == 1 and d3["n_omisiones"] == 0, motivo


def test_el_aviso_de_integridad_cuenta_las_omisiones_y_nombra_la_regla(campana):
    raiz, _ = campana
    resumen = _consolidar(raiz)
    avisos = {a["codigo"]: a for a in resumen["integridad"]["advertencias"]}
    assert avisos["omisiones_d2_d3"]["n"] >= 1 and avisos["omisiones_d2_d3"]["severidad"] == "info"
    assert "v2" in avisos["omisiones_d2_d3"]["mensaje"]
    regla = resumen["reglas_de_evaluacion"]["d2_d3"]
    assert regla["version"] == "v2-omision-cuenta" and regla["enmienda"] == "2026-10-15"
    assert "piloto de desarrollo" in regla["motivo"]


def test_la_regla_es_una_funcion_pura_de_la_corrida_y_no_toca_a_d1(campana):
    from src.experimentation.evaluacion import corrida_valida_y_completa
    ok = {"estado": "completa"}
    salida = {"_meta": {"veredicto_booleano_presente": True}}
    assert corrida_valida_y_completa(ok, salida) is True
    assert corrida_valida_y_completa({"estado": "timeout"}, salida) is False
    assert corrida_valida_y_completa(ok, {"_meta": {"veredicto_booleano_presente": False}}) is False
    assert corrida_valida_y_completa(None, salida) is False
    assert corrida_valida_y_completa(ok, {}) is False
    raiz, _ = campana
    d1 = _fila(_consolidar(raiz), "d1_deteccion", "uwf", "nodex_multiagente")
    assert (d1["tp"], d1["fp"], d1["fn"], d1["tn"]) == (1, 1, 1, 1)
