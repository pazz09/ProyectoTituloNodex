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

def _telemetria(modelo=PRINCIPAL, tokens=1000, tiempo=10.0, replan=1, correcciones=0):
    return {
        "llm_call_count": 6, "input_tokens": tokens, "output_tokens": 200,
        "total_tokens": None if tokens is None else tokens + 200,
        "execution_time": tiempo, "replan_count": replan,
        "intentos_correccion": correcciones, "invalid_evidence_uid_count": 0,
        "d11_warning_count": 0, "llm_calls": [{"model": modelo}],
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
    estado["telemetry"] = _telemetria(modelo=modelo)
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
        "intentos_correccion": None, "modelo_efectivo": PRINCIPAL}}


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
    assert f["n_evaluables"] == 1          # solo el caso 0000 reconstruyó algo
    assert f["no_evaluables"] == 1         # el 0001 no produjo eventos
    assert f["micro_f1"] == pytest.approx(1.0)
    assert f["exact_match"] == pytest.approx(1.0)


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
    """Todo ocurre en `tmp_path`: `experiments/metrics` del repo sigue vacía."""
    raiz, _ = campana
    consolidacion.consolidar(raiz, "sub", CONFIG, ARQUITECTURAS, marca=MARCA)
    repo = Path(__file__).resolve().parents[2] / "experiments"
    assert not any((repo / "metrics").rglob("*")) if (repo / "metrics").exists() else True
    assert not (repo / "outputs").exists()
