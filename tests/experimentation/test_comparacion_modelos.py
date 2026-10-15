"""Comparación mínima entre modelos (src/experimentation/comparacion_modelos.py).

Todo con corredores y clientes simulados: ninguna de estas pruebas llama a la
API. Lo que se fija es el diseño que se decidió ANTES de ejecutar:

  - los casos se eligen con un criterio fijo (primero alfabético por dataset);
  - hay seis criterios de validez y NINGUNO mide acierto;
  - la regla de decisión es mecánica;
  - sin `--ejecutar` no se hace nada, y el respaldo va apagado.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.experimentation import comparacion_modelos as cm

RAIZ = Path(__file__).resolve().parents[2]


# --- elección de casos y plan ----------------------------------------------------

def _repo_con_subconjunto(tmp_path, ids_bgl, ids_uwf):
    ruta = tmp_path / "experiments" / "subconjuntos" / "piloto.json"
    ruta.parent.mkdir(parents=True)
    ruta.write_text(json.dumps({"datasets": {
        "bgl": {"a": {"case_ids": ids_bgl[:2]}, "b": {"case_ids": ids_bgl[2:]}},
        "uwf": {"x": {"case_ids": ids_uwf}},
        "hdfs": {"y": {"case_ids": ["hdfs_des_z_0000"]}},
    }}), encoding="utf-8")
    return tmp_path


def test_el_caso_es_el_primero_alfabetico_de_cada_dataset_sin_importar_el_orden(tmp_path):
    raiz = _repo_con_subconjunto(
        tmp_path, ["bgl_des_c_0002", "bgl_des_a_0009", "bgl_des_a_0001"],
        ["uwf_des_z_0000", "uwf_des_b_0007"])
    assert cm.elegir_casos(raiz) == {"bgl": "bgl_des_a_0001", "uwf": "uwf_des_b_0007"}


def test_los_casos_del_repositorio_son_los_registrados_antes_de_ejecutar():
    """Si cambia el subconjunto, esta prueba avisa: la elección ya está
    registrada en el documento de estado y no debe moverse en silencio."""
    assert cm.elegir_casos(RAIZ) == {
        "bgl": "bgl_des_balanceado_0000", "uwf": "uwf_des_sigiloso_0004"}


def test_hdfs_no_entra_en_la_comparacion(tmp_path):
    raiz = _repo_con_subconjunto(tmp_path, ["bgl_des_a_0", "bgl_des_a_1", "bgl_des_a_2"],
                                 ["uwf_des_a_0"])
    assert {c.dataset for c in cm.planificar(raiz)} == {"bgl", "uwf"}


def test_el_plan_son_8_corridas_y_28_llamadas_minimas():
    plan = cm.planificar(RAIZ)
    assert len(plan) == 8
    assert cm.llamadas_minimas(plan) == 28          # 2 casos x 2 modelos x (6 + 1)
    combinaciones = {(c.modelo, c.arquitectura, c.dataset) for c in plan}
    assert len(combinaciones) == 8                  # sin repetidos
    assert {c.modelo for c in plan} == {"gemini-3.1-pro-preview", "gemini-3.8-flash"}
    assert {c.arquitectura for c in plan} == {"nodex_multiagente", "gemini_externo"}


def test_el_baseline_no_entra_porque_no_usa_el_modelo():
    assert "baseline_reglas" not in cm.ARQUITECTURAS


def test_el_modulo_no_contiene_ninguna_ruta_al_ground_truth():
    import inspect
    codigo = inspect.getsource(cm)
    # el nombre aparece en la documentación para decir que NO se lee; no en una ruta
    assert 'ground_truth"' not in codigo and "ground_truth/" not in codigo.replace(
        "`ground_truth/`", "")


def test_no_hay_ningun_criterio_de_acierto():
    for criterio in cm.CRITERIOS:
        for palabra in ("f1", "precision", "recall", "acierto", "correct", "label"):
            assert palabra not in criterio
    assert len(cm.CRITERIOS) == 6


# --- sin --etapa no se hace nada ----------------------------------------------------

def test_sin_etapa_solo_muestra_el_plan_y_no_lanza_ningun_proceso(monkeypatch, capsys):
    def prohibido(*a, **k):
        raise AssertionError("no debía lanzar ningún proceso")

    monkeypatch.setattr(cm.subprocess, "run", prohibido)
    assert cm.main([], raiz_repo=RAIZ) == 0
    salida = capsys.readouterr().out
    assert "28 llamadas minimas" in salida
    assert "sin --etapa" in salida


def test_la_etapa_exige_env_y_salida(capsys):
    with pytest.raises(SystemExit) as e:
        cm.main(["--etapa", "1"], raiz_repo=RAIZ)
    assert e.value.code == 2


def test_la_salida_no_puede_estar_dentro_de_experiments(monkeypatch, tmp_path):
    monkeypatch.setattr(cm.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("no debía lanzar nada")))
    with pytest.raises(SystemExit) as e:
        cm.main(["--etapa", "1", "--env", str(tmp_path / ".env"),
                 "--salida", str(RAIZ / "experiments" / "metrics" / "x")], raiz_repo=RAIZ)
    assert e.value.code == 2
    assert not (RAIZ / "experiments" / "metrics" / "x").exists()


# --- el entorno de cada corrida --------------------------------------------------------

def test_el_entorno_apaga_el_respaldo_y_fija_modelo_y_temperatura(tmp_path):
    base = {"GEMINI_API_KEY": "clave-ficticia", "LLM_SIN_RESPALDO": "false",
            "LLM_MODEL_PRIMARY": "otro", "TEMPERATURE": "1"}
    e = cm.entorno_de_la_corrida(base, "gemini-3.8-flash", tmp_path / "c", tmp_path / "i")
    assert e["LLM_SIN_RESPALDO"] == "true"          # aunque el .env diga lo contrario
    assert e["LLM_MODEL_PRIMARY"] == "gemini-3.8-flash"
    assert e["LLM_MODEL_FALLBACK"] == "gemini-3.8-flash"
    assert e["TEMPERATURE"] == "0"
    assert e["CHROMA_PATH"] == str(tmp_path / "c")
    assert e["IP_CACHE_PATH"] == str(tmp_path / "i")
    assert e["HF_HUB_OFFLINE"] == "1"
    assert base["TEMPERATURE"] == "1"               # no muta el entorno de entrada


def test_el_plan_impreso_no_contiene_credenciales(monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "clave-ficticia-12345")
    cm.main([], raiz_repo=RAIZ)
    assert "clave-ficticia-12345" not in capsys.readouterr().out


# --- los seis criterios, uno por uno --------------------------------------------------

UIDS = frozenset({"U1", "U2", "U3"})


def _valida(arquitectura="nodex_multiagente", modelo="m"):
    """Una corrida que cumple todo. Cada prueba rompe UNA cosa."""
    return {
        "arquitectura": arquitectura, "excepcion": None,
        "llm_json": {"llamadas": 6, "invalidas": 0},
        "diagnostico": {"error": None},
        "telemetria": {"input_tokens": 100, "output_tokens": 20,
                       "llm_calls": [{"model": modelo, "model_version": "m-001"}] * 3},
        "estado": {"veredicto_presente": True, "uids_citados": ["U1", "U2"],
                   "invalid_evidence_uid_count": 0},
    }


def test_una_corrida_sana_cumple_los_seis():
    assert all(cm.evaluar_criterios(_valida(), "m", UIDS).values())
    assert set(cm.evaluar_criterios(_valida(), "m", UIDS)) == set(cm.CRITERIOS)


def test_json_invalido_en_nodex_rompe_solo_el_criterio_1():
    r = _valida()
    r["llm_json"] = {"llamadas": 6, "invalidas": 1}
    c = cm.evaluar_criterios(r, "m", UIDS)
    assert c["json_objeto_valido"] is False
    assert [k for k, v in c.items() if not v] == ["json_objeto_valido"]


def test_nodex_sin_ninguna_llamada_a_llm_json_no_cuenta_como_json_valido():
    r = _valida()
    r["llm_json"] = {"llamadas": 0, "invalidas": 0}
    assert cm.evaluar_criterios(r, "m", UIDS)["json_objeto_valido"] is False


def test_gemini_directo_con_respuesta_que_no_es_objeto_rompe_el_criterio_1():
    r = _valida("gemini_externo")
    r["diagnostico"] = {"error": "la respuesta no es un objeto JSON"}
    assert cm.evaluar_criterios(r, "m", UIDS)["json_objeto_valido"] is False


def test_sin_veredicto_rompe_el_criterio_2():
    r = _valida()
    r["estado"]["veredicto_presente"] = False
    assert cm.evaluar_criterios(r, "m", UIDS)["veredicto_presente"] is False


def test_un_uid_inventado_rompe_el_criterio_3_aunque_el_contador_diga_cero():
    r = _valida()
    r["estado"]["uids_citados"] = ["U1", "U99"]
    assert cm.evaluar_criterios(r, "m", UIDS)["evidencia_valida"] is False


def test_un_contador_de_nodex_distinto_de_cero_rompe_el_criterio_3():
    r = _valida()
    r["estado"]["invalid_evidence_uid_count"] = 2
    assert cm.evaluar_criterios(r, "m", UIDS)["evidencia_valida"] is False


def test_un_contador_ausente_en_nodex_no_se_da_por_cero():
    r = _valida()
    r["estado"]["invalid_evidence_uid_count"] = None
    assert cm.evaluar_criterios(r, "m", UIDS)["evidencia_valida"] is False


def test_gemini_directo_no_tiene_contador_y_se_valida_solo_por_los_uids():
    r = _valida("gemini_externo")
    r["estado"]["invalid_evidence_uid_count"] = None
    assert cm.evaluar_criterios(r, "m", UIDS)["evidencia_valida"] is True
    r["estado"]["uids_citados"] = ["U404"]
    assert cm.evaluar_criterios(r, "m", UIDS)["evidencia_valida"] is False


def test_en_un_caso_sin_uids_citar_alguno_es_invalido():
    r = _valida()
    r["estado"]["uids_citados"] = ["U1"]
    assert cm.evaluar_criterios(r, "m", None)["evidencia_valida"] is False
    r["estado"]["uids_citados"] = []
    assert cm.evaluar_criterios(r, "m", None)["evidencia_valida"] is True


def test_una_corrida_que_fallo_no_aparenta_evidencia_valida():
    r = _valida("gemini_externo")
    r["estado"] = {}
    r["diagnostico"] = {"error": "TimeoutError: x"}
    assert cm.evaluar_criterios(r, "m", UIDS)["evidencia_valida"] is False


@pytest.mark.parametrize("falta", [
    {"input_tokens": None}, {"output_tokens": None},
    {"input_tokens": True}, {"output_tokens": "20"},
])
def test_sin_tokens_de_entrada_y_salida_registrados_rompe_el_criterio_4(falta):
    r = _valida()
    r["telemetria"].update(falta)
    assert cm.evaluar_criterios(r, "m", UIDS)["tokens_registrados"] is False


def test_un_error_o_una_excepcion_rompen_el_criterio_5():
    r = _valida()
    r["diagnostico"] = {"error": "TimeoutError: x"}
    assert cm.evaluar_criterios(r, "m", UIDS)["sin_timeout_ni_error"] is False
    r = _valida()
    r["excepcion"] = "RuntimeError: x"
    assert cm.evaluar_criterios(r, "m", UIDS)["sin_timeout_ni_error"] is False


def test_una_llamada_con_otro_modelo_rompe_el_criterio_6():
    r = _valida()
    r["telemetria"]["llm_calls"][-1] = {"model": "otro", "model_version": "otro-001"}
    assert cm.evaluar_criterios(r, "m", UIDS)["solo_el_modelo_pedido"] is False


def test_sin_llamadas_registradas_el_criterio_6_no_se_da_por_cumplido():
    r = _valida()
    r["telemetria"]["llm_calls"] = []
    assert cm.evaluar_criterios(r, "m", UIDS)["solo_el_modelo_pedido"] is False


def test_la_version_devuelta_distinta_del_nombre_pedido_no_rompe_el_criterio_6():
    """`gemini-x` pedido y `gemini-x-001` devuelto es normal, no un cambio de modelo."""
    r = _valida()
    assert cm.evaluar_criterios(r, "m", UIDS)["solo_el_modelo_pedido"] is True


# --- la regla de decisión ---------------------------------------------------------------

def _fila(modelo, cumple=True, rompe=None, arquitectura="nodex_multiagente", dataset="uwf",
          rompe_original=None, tiene_estado=True):
    """Una fila del resumen. `rompe` rompe el criterio en AMBOS veredictos;
    `rompe_original` solo en el original (lo que hace la enmienda)."""
    criterios = {c: cumple for c in cm.CRITERIOS}
    enmendados = dict(criterios)
    if rompe:
        criterios[rompe] = enmendados[rompe] = False
    if rompe_original:
        criterios[rompe_original] = False
    return {"modelo": modelo, "etiqueta": f"{modelo}__{arquitectura}__{dataset}",
            "arquitectura": arquitectura, "dataset": dataset, "criterios": criterios,
            "criterios_enmendados": enmendados, "tiene_estado": tiene_estado}


def test_si_flash_cumple_todo_la_regla_lo_propone_como_principal():
    filas = [_fila(cm.MODELO_ACTUAL) for _ in range(4)] + [_fila(cm.MODELO_CANDIDATO) for _ in range(4)]
    d = cm.aplicar_regla(filas)
    assert d["cumple_todos"] is True
    assert d["resultado_de_la_regla"] == cm.MODELO_CANDIDATO
    assert d["criterios_fallidos"] == []


def test_si_flash_falla_uno_solo_se_mantiene_el_pro_y_se_dice_cual():
    filas = [_fila(cm.MODELO_ACTUAL) for _ in range(4)]
    filas += [_fila(cm.MODELO_CANDIDATO) for _ in range(3)]
    filas += [_fila(cm.MODELO_CANDIDATO, rompe="evidencia_valida")]
    d = cm.aplicar_regla(filas)
    assert d["cumple_todos"] is False
    assert d["resultado_de_la_regla"] == cm.MODELO_ACTUAL
    assert d["criterios_fallidos"] == [
        {"corrida": f"{cm.MODELO_CANDIDATO}__nodex_multiagente__uwf", "criterio": "evidencia_valida"}]


def test_que_el_pro_falle_otro_criterio_no_cambia_la_regla():
    """La regla solo mira al candidato; el Pro es la referencia, no se juzga."""
    filas = [_fila(cm.MODELO_ACTUAL, rompe="json_objeto_valido")]
    filas += [_fila(cm.MODELO_CANDIDATO) for _ in range(4)]
    assert cm.aplicar_regla(filas)["resultado_de_la_regla"] == cm.MODELO_CANDIDATO


def test_sin_corridas_del_candidato_la_regla_no_propone_el_cambio():
    d = cm.aplicar_regla([_fila(cm.MODELO_ACTUAL)])
    assert d["cumple_todos"] is False
    assert d["resultado_de_la_regla"] == cm.MODELO_ACTUAL


# --- enmienda del criterio 3 (15-oct-2026, posterior al primer resultado) ------------------

def _gemext_bgl(modelo, original_ok, enmendado_ok=True):
    fila = _fila(modelo, arquitectura="gemini_externo", dataset="bgl")
    fila["criterios"]["evidencia_valida"] = original_ok
    fila["criterios_enmendados"]["evidencia_valida"] = enmendado_ok
    return fila


def _caso_flash_falla_solo_el_original(pro_original_ok):
    """Flash incumple el criterio 3 ORIGINAL en BGL/Gemini directo (como la primera
    corrida real) y lo cumple con el enmendado; el resto cumple todo."""
    return [
        _gemext_bgl(cm.MODELO_CANDIDATO, original_ok=False),
        _gemext_bgl(cm.MODELO_ACTUAL, original_ok=pro_original_ok),
        _fila(cm.MODELO_CANDIDATO), _fila(cm.MODELO_CANDIDATO, dataset="bgl"),
        _fila(cm.MODELO_CANDIDATO, arquitectura="gemini_externo"),
    ]


def test_si_el_pro_tambien_incumple_el_original_la_decision_usa_el_enmendado():
    d = cm.aplicar_regla(_caso_flash_falla_solo_el_original(pro_original_ok=False))
    assert d["criterio_usado"] == "enmendado"
    assert "no discrimina" in d["motivo_del_criterio_usado"]
    assert d["resultado_de_la_regla"] == cm.MODELO_CANDIDATO
    # y quedan visibles los dos veredictos
    assert d["con_criterio_original"]["resultado_de_la_regla"] == cm.MODELO_ACTUAL
    assert d["con_criterio_enmendado"]["resultado_de_la_regla"] == cm.MODELO_CANDIDATO


def test_si_el_pro_cumple_el_original_y_flash_no_se_mantiene_la_regla_original_y_el_pro():
    d = cm.aplicar_regla(_caso_flash_falla_solo_el_original(pro_original_ok=True))
    assert d["criterio_usado"] == "original"
    assert d["resultado_de_la_regla"] == cm.MODELO_ACTUAL
    assert [f["criterio"] for f in d["criterios_fallidos"]] == ["evidencia_valida"]
    # el enmendado habría dado otro resultado, pero NO se usa: sería cambiar la regla a posteriori
    assert d["con_criterio_enmendado"]["resultado_de_la_regla"] == cm.MODELO_CANDIDATO


def test_si_la_corrida_del_pro_en_bgl_no_se_hizo_vale_la_regla_original():
    filas = [f for f in _caso_flash_falla_solo_el_original(False)
             if not (f["modelo"] == cm.MODELO_ACTUAL)]
    d = cm.aplicar_regla(filas)
    assert d["criterio_usado"] == "original"
    assert d["resultado_de_la_regla"] == cm.MODELO_ACTUAL


def test_si_el_pro_no_devolvio_respuesta_no_se_concluye_que_el_criterio_no_discrimina():
    """Una caída de infraestructura del Pro no demuestra nada sobre el criterio."""
    filas = _caso_flash_falla_solo_el_original(pro_original_ok=False)
    for f in filas:
        if f["modelo"] == cm.MODELO_ACTUAL:
            f["tiene_estado"] = False
    d = cm.aplicar_regla(filas)
    assert d["criterio_usado"] == "original"


def test_con_el_enmendado_un_fallo_en_otro_criterio_sigue_siendo_fallo():
    filas = _caso_flash_falla_solo_el_original(pro_original_ok=False)
    filas.append(_fila(cm.MODELO_CANDIDATO, rompe="veredicto_presente"))
    d = cm.aplicar_regla(filas)
    assert d["criterio_usado"] == "enmendado"
    assert d["resultado_de_la_regla"] == cm.MODELO_ACTUAL
    assert [f["criterio"] for f in d["criterios_fallidos"]] == ["veredicto_presente"]


def test_la_enmienda_no_juzga_la_evidencia_de_gemini_directo_en_un_dataset_sin_uid():
    """El caso real de la primera corrida: 19 «uids» citados en BGL, que no tiene uid."""
    r = _valida("gemini_externo")
    r["estado"]["uids_citados"] = ["1129456912", "1129501476"]
    r["estado"]["invalid_evidence_uid_count"] = None
    assert cm.evaluar_criterios(r, "m", None)["evidencia_valida"] is False             # original
    assert cm.evaluar_criterios(r, "m", None, enmendado=True)["evidencia_valida"] is True


def test_la_enmienda_en_nodex_sin_uid_solo_cuenta_su_contador():
    r = _valida()
    r["estado"]["uids_citados"] = ["1129456912"]
    assert cm.evaluar_criterios(r, "m", None, enmendado=True)["evidencia_valida"] is True
    r["estado"]["invalid_evidence_uid_count"] = 3
    assert cm.evaluar_criterios(r, "m", None, enmendado=True)["evidencia_valida"] is False
    r["estado"]["invalid_evidence_uid_count"] = None          # ausente no se da por 0
    assert cm.evaluar_criterios(r, "m", None, enmendado=True)["evidencia_valida"] is False


def test_la_enmienda_no_cambia_nada_en_un_dataset_con_uid():
    r = _valida("gemini_externo")
    r["estado"]["uids_citados"] = ["U1", "U404"]               # U404 no existe en el caso
    assert cm.evaluar_criterios(r, "m", UIDS)["evidencia_valida"] is False
    assert cm.evaluar_criterios(r, "m", UIDS, enmendado=True)["evidencia_valida"] is False


def test_la_enmienda_no_da_por_valida_una_corrida_sin_respuesta():
    r = _valida("gemini_externo")
    r["estado"] = {}
    r["diagnostico"] = {"error": "TimeoutError: x"}
    assert cm.evaluar_criterios(r, "m", None, enmendado=True)["evidencia_valida"] is False


def test_la_enmienda_solo_toca_el_criterio_3():
    r = _valida("gemini_externo")
    r["estado"]["uids_citados"] = ["1", "2"]
    original = cm.evaluar_criterios(r, "m", None)
    enmendado = cm.evaluar_criterios(r, "m", None, enmendado=True)
    assert {c for c in cm.CRITERIOS if original[c] != enmendado[c]} == {"evidencia_valida"}


def test_una_corrida_anterior_a_la_enmienda_conserva_su_veredicto_original_tal_cual():
    """La primera corrida real quedó guardada sin `criterios_enmendados`: al resumir se
    calcula el enmendado, pero el original NO se recalcula."""
    final = _crudo_de(cm.Corrida("m", "gemini_externo", "bgl", "bgl_des_a_0000"))
    final["criterios"] = {c: True for c in cm.CRITERIOS} | {"evidencia_valida": False}
    final["tipo_fallo"] = cm.FALLO_CONTENIDO
    final["repetida_por_infraestructura"] = False
    final["intentos"] = [final]
    final["estado"]["uids_citados"] = ["1129456912"]
    fila = cm.resumen_de_corrida(final, None)
    assert fila["criterios"]["evidencia_valida"] is False          # original, como se guardó
    assert fila["criterios_enmendados"]["evidencia_valida"] is True
    assert fila["cumple_original"] is False and fila["cumple_enmendado"] is True


def test_cada_corrida_nueva_guarda_los_dos_veredictos():
    final = cm.correr_corrida(CORRIDA, _Lanzador(_crudo()), UIDS)
    assert set(final["criterios"]) == set(final["criterios_enmendados"]) == set(cm.CRITERIOS)


@pytest.mark.parametrize("texto, esperado", [
    ("2", [1]), ("3-8", [2, 3, 4, 5, 6, 7]), ("2,5-6", [1, 4, 5]), ("1-2", [0, 1])])
def test_corridas_se_numeran_desde_1(texto, esperado):
    assert cm._parsear_corridas(texto, 8) == esperado


@pytest.mark.parametrize("texto", ["0", "9", "5-3", "1-9"])
def test_corridas_fuera_del_plan_son_un_error(texto):
    with pytest.raises(ValueError):
        cm._parsear_corridas(texto, 8)


# --- instrumentos del trabajador ------------------------------------------------------

def test_el_contador_de_json_invalido_cuenta_las_respuestas_con_error():
    respuestas = iter([{"ok": 1}, {"error": "json_invalido", "raw": "x"}, [1], {"ok": 2}])
    modulo = SimpleNamespace(llm_json=lambda *a, **k: next(respuestas))
    cuenta = cm._instrumentar_llm_json(modulo)
    for _ in range(4):
        modulo.llm_json("p")
    assert cuenta == {"llamadas": 4, "invalidas": 2}


def test_el_bloqueo_de_red_impide_la_peticion_y_anota_a_donde_iba():
    class Sesion:
        def request(self, *a, **k):
            return "salio a la red"

    intentos = cm._bloquear_red(Sesion)
    with pytest.raises(ConnectionError):
        Sesion().request("GET", "https://services.nvd.nist.gov/rest/json/cves/2.0?x=1")
    with pytest.raises(ConnectionError):
        Sesion().request("GET", "https://api.abuseipdb.com/api/v2/check")
    assert intentos == ["https://services.nvd.nist.gov/rest/json/cves/2.0",
                        "https://api.abuseipdb.com/api/v2/check"]


def test_el_resumen_del_estado_no_incluye_el_texto_del_reporte():
    estado = {"hay_incidente": True, "diagnostico": "texto largo del reporte",
              "eventos_reconstruidos": [{"evidence_uids": ["U1", "U2"]}],
              "tecnicas_atribuidas": [{"evidence_uids": ["U2", "U3"]}],
              "invalid_evidence_uid_count": 0}
    r = cm._resumen_del_estado(estado)
    assert r["uids_citados"] == ["U1", "U2", "U3"]
    assert r["veredicto_presente"] is True
    assert "texto largo del reporte" not in json.dumps(r)
    assert r["largo_diagnostico"] == len("texto largo del reporte")


def test_sin_veredicto_booleano_el_resumen_lo_declara():
    assert cm._resumen_del_estado({"hay_incidente": None})["veredicto_presente"] is False


# --- el trabajador con un corredor simulado --------------------------------------------

class _CorredorFalso:
    def __init__(self, estado, diagnostico, falla=None):
        self._estado, self._diag, self._falla = estado, diagnostico, falla
        self.llamado_con = None

    def cargar_caso(self, raiz, dataset, particion, case_id):
        return f"contenido de {case_id} ({particion})"

    def ejecutar(self, contenido, run_id):
        self.llamado_con = (contenido, run_id)
        if self._falla:
            raise self._falla
        return self._estado, self._diag


def test_el_trabajador_escribe_el_resumen_con_la_configuracion_efectiva(tmp_path):
    corredor = _CorredorFalso(
        {"hay_incidente": True, "telemetry": {"input_tokens": 5, "output_tokens": 2,
                                              "llm_calls": [{"model": "m"}]}},
        {"error": None, "execution_time": 1.5})
    destino = tmp_path / "r.json"
    corrida = cm.Corrida("m", "gemini_externo", "bgl", "bgl_des_a_0000")
    r = cm.trabajar(corrida, RAIZ, destino, runner=corredor)
    assert json.loads(destino.read_text(encoding="utf-8")) == json.loads(json.dumps(r))
    assert r["estado"]["veredicto_presente"] is True
    assert r["telemetria"]["input_tokens"] == 5
    assert set(r["configuracion_efectiva"]) == {
        "LLM_MODEL_PRIMARY", "LLM_MODEL_FALLBACK", "LLM_SIN_RESPALDO", "TEMPERATURE"}
    assert corredor.llamado_con[0].endswith("(desarrollo)")      # partición de desarrollo
    assert "bgl_des_a_0000" in corredor.llamado_con[1]


def test_una_excepcion_del_corredor_se_registra_y_no_se_oculta(tmp_path):
    corredor = _CorredorFalso({}, {}, falla=RuntimeError("503 UNAVAILABLE"))
    corrida = cm.Corrida("m", "nodex_multiagente", "bgl", "bgl_des_a_0000")
    r = cm.trabajar(corrida, RAIZ, tmp_path / "r.json", runner=corredor)
    assert "RuntimeError: 503 UNAVAILABLE" in r["excepcion"]
    assert r["estado"] == {}
    c = cm.evaluar_criterios(r | {"arquitectura": "nodex_multiagente"}, "m", UIDS)
    assert c["sin_timeout_ni_error"] is False
    assert c["evidencia_valida"] is False
    assert c["veredicto_presente"] is False


# --- orden de ejecución ----------------------------------------------------------------

def test_el_orden_es_bgl_primero_y_el_candidato_antes_que_el_pro():
    plan = cm.planificar(RAIZ)
    primeras = [(c.dataset, c.modelo, c.arquitectura) for c in plan[:cm.ETAPA_1]]
    assert primeras == [
        ("bgl", cm.MODELO_CANDIDATO, "gemini_externo"),
        ("bgl", cm.MODELO_CANDIDATO, "nodex_multiagente"),
    ]
    assert cm.ETAPA_1 == 2
    assert {c.dataset for c in plan[:4]} == {"bgl"}      # BGL completo antes que UWF
    assert {c.dataset for c in plan[4:]} == {"uwf"}


# --- regla de repetición -----------------------------------------------------------------

def _crudo(error=None, excepcion=None, **cambios):
    r = _valida("gemini_externo", modelo="m") | {
        "etiqueta": "x", "modelo": "m", "dataset": "bgl", "case_id": "c"}
    r["diagnostico"] = {"error": error}
    r["excepcion"] = excepcion
    r.update(cambios)
    return r


@pytest.mark.parametrize("error", [
    "TimeoutError: timed out", "503 UNAVAILABLE: the model is overloaded",
    "429 RESOURCE_EXHAUSTED: quota", "DeadlineExceeded: x",
])
def test_timeout_503_y_429_son_fallas_de_infraestructura(error):
    assert cm.clasificar_fallo(_crudo(error=error), {c: False for c in cm.CRITERIOS}) == (
        cm.FALLO_INFRAESTRUCTURA)


def test_un_error_que_no_es_de_infraestructura_es_otro_y_no_se_repite():
    assert cm.clasificar_fallo(_crudo(error="400 INVALID_ARGUMENT: x"), {}) == cm.FALLO_OTRO


def test_si_hay_error_manda_el_error_aunque_falten_los_tokens():
    """Un timeout deja sin tokens y sin veredicto: no es una falla de contenido."""
    criterios = {c: False for c in cm.CRITERIOS}
    assert cm.clasificar_fallo(_crudo(error="TimeoutError: x"), criterios) == (
        cm.FALLO_INFRAESTRUCTURA)


def test_sin_error_un_criterio_roto_es_falla_de_contenido():
    criterios = {c: True for c in cm.CRITERIOS} | {"json_objeto_valido": False}
    assert cm.clasificar_fallo(_crudo(), criterios) == cm.FALLO_CONTENIDO
    assert cm.clasificar_fallo(_crudo(), {c: True for c in cm.CRITERIOS}) is None


class _Lanzador:
    """Entrega resultados predefinidos, uno por intento."""

    def __init__(self, *resultados):
        self._resultados = list(resultados)
        self.intentos = []

    def __call__(self, corrida, n):
        self.intentos.append(n)
        return dict(self._resultados.pop(0))


CORRIDA = cm.Corrida("m", "gemini_externo", "bgl", "bgl_des_a_0000")


def test_una_corrida_sana_se_hace_una_sola_vez():
    lanzar = _Lanzador(_crudo())
    final = cm.correr_corrida(CORRIDA, lanzar, UIDS)
    assert lanzar.intentos == [1]
    assert final["tipo_fallo"] is None
    assert final["repetida_por_infraestructura"] is False


def test_una_falla_de_infraestructura_se_repite_una_vez_y_se_conservan_los_dos_intentos():
    lanzar = _Lanzador(_crudo(error="503 UNAVAILABLE: x"), _crudo())
    final = cm.correr_corrida(CORRIDA, lanzar, UIDS)
    assert lanzar.intentos == [1, 2]
    assert final["repetida_por_infraestructura"] is True
    assert [i["tipo_fallo"] for i in final["intentos"]] == [cm.FALLO_INFRAESTRUCTURA, None]
    assert final["tipo_fallo"] is None                  # el repetido salió bien


def test_si_el_repetido_tambien_falla_cuenta_como_fallo_y_no_hay_tercer_intento():
    lanzar = _Lanzador(_crudo(error="503 UNAVAILABLE: x"),
                       _crudo(error="TimeoutError: y"), _crudo())
    final = cm.correr_corrida(CORRIDA, lanzar, UIDS)
    assert lanzar.intentos == [1, 2]                    # nunca un tercero
    assert final["tipo_fallo"] == cm.FALLO_INFRAESTRUCTURA
    assert len(final["intentos"]) == 2
    assert final["criterios"]["sin_timeout_ni_error"] is False


def test_una_falla_de_contenido_no_se_repite():
    malo = _crudo(estado={"veredicto_presente": False, "uids_citados": [],
                          "invalid_evidence_uid_count": None})
    lanzar = _Lanzador(malo, _crudo())
    final = cm.correr_corrida(CORRIDA, lanzar, UIDS)
    assert lanzar.intentos == [1]
    assert final["tipo_fallo"] == cm.FALLO_CONTENIDO
    assert final["repetida_por_infraestructura"] is False
    assert final["criterios"]["veredicto_presente"] is False


def test_un_error_de_otro_tipo_no_se_repite():
    lanzar = _Lanzador(_crudo(error="400 INVALID_ARGUMENT: x"), _crudo())
    final = cm.correr_corrida(CORRIDA, lanzar, UIDS)
    assert lanzar.intentos == [1]
    assert final["tipo_fallo"] == cm.FALLO_OTRO


def test_el_numero_de_intento_queda_en_cada_registro():
    lanzar = _Lanzador(_crudo(error="429 RESOURCE_EXHAUSTED"), _crudo())
    final = cm.correr_corrida(CORRIDA, lanzar, UIDS)
    assert [i["intento"] for i in final["intentos"]] == [1, 2]


# --- revisión inmediata de la API real ----------------------------------------------------

def _con_llamadas(*llamadas):
    return {"telemetria": {"llm_calls": list(llamadas)}, "diagnostico": {}, "excepcion": None}


def test_una_revision_limpia_no_devuelve_avisos():
    r = _con_llamadas({"model": "m", "model_version": "m", "reasoning_tokens": 12},
                      {"model": "m", "model_version": "m-001", "reasoning_tokens": None})
    assert cm.revision_inmediata(r, "m") == []


def test_razonamiento_none_es_aceptable_porque_el_proveedor_puede_no_informarlo():
    r = _con_llamadas({"model": "m", "model_version": "m", "reasoning_tokens": None})
    assert cm.revision_inmediata(r, "m") == []


@pytest.mark.parametrize("llamada, fragmento", [
    ({"model": "m", "model_version": None}, "model_version es None"),
    ({"model": "m", "model_version": "otro-modelo"}, "no corresponde"),
    ({"model": "m", "model_version": "mx"}, "no corresponde"),     # no es "m-..."
    ({"model": "otro", "model_version": "otro"}, "se pidió"),
    ({"model": "m", "model_version": "m", "reasoning_tokens": -1}, "reasoning_tokens inválido"),
    ({"model": "m", "model_version": "m", "reasoning_tokens": "7"}, "reasoning_tokens inválido"),
])
def test_lo_inesperado_se_reporta(llamada, fragmento):
    avisos = cm.revision_inmediata(_con_llamadas(llamada), "m")
    assert any(fragmento in a for a in avisos), avisos


def test_sin_llamadas_registradas_es_inesperado():
    assert cm.revision_inmediata(_con_llamadas(), "m")


def test_un_error_de_la_corrida_se_reporta_en_la_revision():
    r = _con_llamadas({"model": "m", "model_version": "m"})
    r["diagnostico"] = {"error": "TimeoutError: x"}
    assert any("terminó con error" in a for a in cm.revision_inmediata(r, "m"))


# --- ejecutar / resumir con un lanzador simulado -----------------------------------------------

def _crudo_de(corrida, **cambios):
    r = _valida(corrida.arquitectura, modelo=corrida.modelo)
    r.update({"etiqueta": corrida.etiqueta, "modelo": corrida.modelo,
              "arquitectura": corrida.arquitectura, "dataset": corrida.dataset,
              "case_id": corrida.case_id})
    r["telemetria"] = r["telemetria"] | {"llm_call_count": 1, "reasoning_tokens": 5}
    r["diagnostico"] = {"error": None, "execution_time": 2.0}
    # Los casos reales no tienen los uids U1..U3 de los otros tests: aquí no se cita ninguno.
    r["estado"] = r["estado"] | {"uids_citados": []}
    r.update(cambios)
    return r


def _lanzar_todo_bien(corrida, n):
    return _crudo_de(corrida)


def test_ejecutar_escribe_un_final_por_corrida_y_no_sobrescribe(tmp_path):
    salida = tmp_path / "salida"
    finales = cm.ejecutar(RAIZ, Path("sin-env"), salida, [0, 1], lanzar=_lanzar_todo_bien)
    assert len(finales) == 2
    assert len(list(salida.glob("*.final.json"))) == 2
    with pytest.raises(FileExistsError):
        cm.ejecutar(RAIZ, Path("sin-env"), salida, [0], lanzar=_lanzar_todo_bien)


def test_resumir_aplica_la_regla_y_declara_lo_que_falta(tmp_path):
    salida = tmp_path / "salida"
    cm.ejecutar(RAIZ, Path("sin-env"), salida, [0, 1], lanzar=_lanzar_todo_bien)
    resumen = cm.resumir(RAIZ, salida)
    assert len(resumen["filas"]) == 2
    assert len(resumen["corridas_que_faltan"]) == 6
    assert resumen["decision"]["corridas_evaluadas"] == 2
    fila = resumen["filas"][0]
    assert fila["tokens_razonamiento"] == 5 and fila["n_intentos"] == 1
    assert fila["versiones_devueltas"] == [f"{fila['modelo']}-001"] or fila[
        "versiones_devueltas"] == ["m-001"]


def test_resumir_completo_con_todo_en_regla_propone_el_candidato(tmp_path):
    salida = tmp_path / "salida"
    cm.ejecutar(RAIZ, Path("sin-env"), salida, list(range(8)), lanzar=_lanzar_todo_bien)
    resumen = cm.resumir(RAIZ, salida)
    assert resumen["corridas_que_faltan"] == []
    assert resumen["decision"]["cumple_todos"] is True
    assert resumen["decision"]["corridas_evaluadas"] == 4


def test_una_falla_de_contenido_del_candidato_hace_que_la_regla_mantenga_el_pro(tmp_path):
    def lanzar(corrida, n):
        if (corrida.modelo == cm.MODELO_CANDIDATO and corrida.dataset == "uwf"
                and corrida.arquitectura == "nodex_multiagente"):
            return _crudo_de(corrida, estado={
                "veredicto_presente": True, "uids_citados": ["U999999"],
                "invalid_evidence_uid_count": 1})
        return _crudo_de(corrida)

    salida = tmp_path / "salida"
    cm.ejecutar(RAIZ, Path("sin-env"), salida, list(range(8)), lanzar=lanzar)
    d = cm.resumir(RAIZ, salida)["decision"]
    assert d["resultado_de_la_regla"] == cm.MODELO_ACTUAL
    assert [f["criterio"] for f in d["criterios_fallidos"]] == ["evidencia_valida"]


# --- los procesos hijos se leen en UTF-8 -----------------------------------------------

def test_todo_subprocess_que_captura_salida_la_decodifica_en_utf8():
    """Los hijos escriben UTF-8 (PYTHONIOENCODING). Si el padre usa el códec por
    omisión de Windows (cp1252), el hilo lector falla con UnicodeDecodeError y se
    pierde el stderr, justo lo que sirve para diagnosticar una caída."""
    import ast
    import inspect
    from src.experimentation.knowledge import verificar_base
    for modulo in (cm, verificar_base):
        arbol = ast.parse(inspect.getsource(modulo))
        llamadas = [n for n in ast.walk(arbol)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "run" and getattr(n.func.value, "id", "") == "subprocess"]
        assert llamadas, modulo.__name__
        for llamada in llamadas:
            claves = {k.arg: k.value for k in llamada.keywords}
            assert "encoding" in claves, f"{modulo.__name__}:{llamada.lineno} sin encoding"
            assert getattr(claves["encoding"], "value", None) == "utf-8"
