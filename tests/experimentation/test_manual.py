"""Evaluación manual (src/experimentation/manual.py): analizar un caso a la vez desde la interfaz, solo NODEX.

Todo con un repositorio en miniatura y reportes fabricados: no se llama al modelo.
"""

import json
from pathlib import Path

import pytest

from src.experimentation import manual
from src.experimentation.runtime import persistencia
from src.experimentation.runtime.identidad import IdentidadCorrida
from tests.experimentation import test_consolidacion as T

CONTENIDO_UWF = "uid,ts\n" + "\n".join(f"U{i},{i}" for i in range(1, 6)) + "\n"
CONTENIDO_BGL = "linea\n"


def _contenido(cid):
    return CONTENIDO_UWF if cid.startswith("uwf") else CONTENIDO_BGL


def _reporte(cid):
    """El reporte final que emitiría la interfaz para ese caso (mismos estados que el experimento)."""
    estado, _ = T._nodex_ejecutar("x", f"{cid}__nodex__r1__x")
    return estado


@pytest.fixture
def raiz(tmp_path):
    T._construir_repo(tmp_path)
    return tmp_path


def _registrar(raiz, cid, nombre=None, contenido=None, reporte=..., error=None):
    ext = "csv" if cid.startswith("uwf") else "log"
    return manual.registrar(
        raiz, f"job-{cid}", nombre or f"{cid}.{ext}", _contenido(cid) if contenido is None else contenido,
        _reporte(cid) if reporte is ... else reporte, error)


# --- reconocer el caso --------------------------------------------------------------------------------

def test_un_archivo_con_nombre_y_contenido_del_caso_se_reconoce(raiz):
    r = manual.identificar_caso(raiz, "uwf_des_visible_0000.csv", CONTENIDO_UWF)
    assert r["reconocido"] and r["case_id"] == "uwf_des_visible_0000"
    assert (r["dataset"], r["particion"]) == ("uwf", "desarrollo")
    assert r["tipo_deteccion"] == "seguridad" and "mitre" in r["dimensiones"]


def test_el_salto_de_linea_de_windows_no_hace_que_el_contenido_parezca_distinto(raiz):
    assert manual.identificar_caso(raiz, "uwf_des_visible_0000.csv", CONTENIDO_UWF.replace("\n", "\r\n"))["reconocido"]


def test_un_nombre_que_no_es_de_un_caso_no_se_reconoce_y_dice_por_que(raiz):
    r = manual.identificar_caso(raiz, "mi_log.txt", "x")
    assert not r["reconocido"] and "no es el de un caso" in r["motivo"]
    assert not manual.identificar_caso(raiz, None, "x")["reconocido"]


def test_el_nombre_de_un_caso_con_contenido_distinto_se_rechaza(raiz):
    r = manual.identificar_caso(raiz, "uwf_des_visible_0000.csv", CONTENIDO_UWF + "U99,99\n")
    assert not r["reconocido"] and "NO coincide" in r["motivo"]


def test_un_caso_que_no_existe_en_el_experimento_no_se_reconoce(raiz):
    r = manual.identificar_caso(raiz, "uwf_des_visible_0099.csv", CONTENIDO_UWF)
    assert not r["reconocido"] and "no existe el caso" in r["motivo"]


def test_hdfs_y_las_dos_particiones_se_distinguen_por_el_nombre():
    assert manual.PARTICIONES == {"des": "desarrollo", "eva": "evaluacion"}
    assert manual.config_de("evaluacion") == "manual-evaluacion"


# --- registrar -----------------------------------------------------------------------------------------

def test_registrar_guarda_el_analisis_en_el_formato_del_experimento(raiz):
    r = _registrar(raiz, "uwf_des_visible_0000")
    assert r["registrado"] and r["repeticion"] == 1 and r["config_version"] == "manual-desarrollo"
    ident = IdentidadCorrida("uwf_des_visible_0000", "uwf", "nodex_multiagente", 1, "manual-desarrollo")
    guardado = persistencia.leer_salida(persistencia.rutas(ident, raiz).salida)
    assert guardado["ejecucion"]["estado"] == "completa"
    assert guardado["salida"]["classification"] == "MALICIOUS"
    assert guardado["salida"]["reconstructed_events"]            # D2 viaja con la salida
    assert persistencia.leer_telemetria(ident, raiz)["diagnostico_runner"]["origen"] == "interfaz_web"
    assert (raiz / "experiments" / "config" / "config_manual-desarrollo.json").is_file()


def test_la_configuracion_efectiva_queda_en_la_telemetria_y_el_crudo(raiz):
    _registrar(raiz, "bgl_des_natural_0000")
    ident = IdentidadCorrida("bgl_des_natural_0000", "bgl", "nodex_multiagente", 1, "manual-desarrollo")
    tel = persistencia.leer_telemetria(ident, raiz)
    efectiva = tel["diagnostico_runner"]["configuracion_efectiva"]
    assert {"LLM_MODEL_PRIMARY", "LLM_SIN_RESPALDO", "TEMPERATURE", "REPUTACION_SIN_ENRIQUECIMIENTO"} <= set(efectiva)
    crudo = json.loads(persistencia.rutas(ident, raiz).crudo.read_text(encoding="utf-8"))
    assert crudo["estado_crudo"]["_job_id"] == "job-bgl_des_natural_0000"


def test_analizar_el_mismo_caso_otra_vez_es_otra_repeticion(raiz):
    assert _registrar(raiz, "bgl_des_natural_0000")["repeticion"] == 1
    assert _registrar(raiz, "bgl_des_natural_0000")["repeticion"] == 2
    assert _registrar(raiz, "bgl_des_natural_0001")["repeticion"] == 1


def test_un_archivo_que_no_es_un_caso_no_guarda_nada(raiz):
    r = manual.registrar(raiz, "j", "mi_log.txt", "x", _reporte("bgl_des_natural_0000"), None)
    assert r["registrado"] is False and "no es el de un caso" in r["motivo"]
    assert not (raiz / "experiments" / "nodex").exists() or not list((raiz / "experiments" / "nodex").rglob("*.json"))


def test_un_analisis_fallido_queda_como_fallo_sin_salida_ni_metricas(raiz):
    r = _registrar(raiz, "bgl_des_natural_0000", reporte=None, error="503 UNAVAILABLE")
    assert r["registrado"] is False and "error_api" in r["motivo"]
    ident = IdentidadCorrida("bgl_des_natural_0000", "bgl", "nodex_multiagente", 1, "manual-desarrollo")
    assert not persistencia.ya_existe(ident, raiz)
    assert persistencia.rutas_fallos(ident, raiz)
    assert manual.construir_resumen(raiz, "desarrollo") is None


def test_un_reporte_sin_veredicto_queda_como_error_de_contrato(raiz):
    reporte = _reporte("bgl_des_natural_0000")
    reporte["hay_anomalia"] = reporte["hay_incidente"] = None
    _registrar(raiz, "bgl_des_natural_0000", reporte=reporte)
    ident = IdentidadCorrida("bgl_des_natural_0000", "bgl", "nodex_multiagente", 1, "manual-desarrollo")
    assert persistencia.leer_salida(persistencia.rutas(ident, raiz).salida)["ejecucion"]["estado"] == "error_contrato"


def test_registrar_no_necesita_ni_lee_el_ground_truth(raiz, monkeypatch):
    import shutil
    shutil.rmtree(raiz / "experiments" / "ground_truth")
    assert _registrar(raiz, "uwf_des_visible_0000")["registrado"] is True


# --- las métricas -------------------------------------------------------------------------------------

def test_sin_analisis_no_hay_resumen(raiz):
    assert manual.particiones_con_analisis(raiz) == []
    assert manual.construir_resumen(raiz, "desarrollo") is None


def test_el_resumen_trae_las_metricas_de_detencion_de_nodex_y_solo_de_nodex(raiz):
    for cid in ("uwf_des_visible_0000", "uwf_des_visible_0001", "uwf_des_visible_0002", "uwf_des_visible_0003"):
        assert _registrar(raiz, cid)["registrado"]
    resumen = manual.construir_resumen(raiz, "desarrollo")
    assert resumen["arquitecturas"] == ["nodex_multiagente"]
    filas = resumen["tablas"]["d1_deteccion"]["filas"]
    assert [f["arquitectura"] for f in filas] == ["nodex_multiagente"]
    f = filas[0]
    assert (f["tp"], f["fp"], f["fn"], f["tn"]) == (1, 1, 1, 1)          # los cuatro cuadrantes, como en el experimento
    assert f["precision"] == pytest.approx(0.5) and f["recall"] == pytest.approx(0.5)
    assert f["f1"] == pytest.approx(0.5) and f["accuracy"] == pytest.approx(0.5)
    assert f["accuracy_ic"] and f["precision_ic"] and f["recall_ic"]      # intervalos de Wilson
    assert resumen["tablas"]["d1_deteccion"]["aviso"]                      # aviso de muestras chicas


def test_el_resumen_trae_reconstruccion_mitre_y_consumo(raiz):
    for cid in ("uwf_des_visible_0000", "uwf_des_visible_0001"):
        _registrar(raiz, cid)
    t = manual.construir_resumen(raiz, "desarrollo")["tablas"]
    assert t["d2_reconstruccion"]["filas"] and t["d3_mitre"]["filas"]
    assert t["consumo"]["filas"][0]["n_completas"] == 2
    assert t["consumo"]["filas"][0]["tokens_totales_medios"] is not None


def test_las_repeticiones_del_mismo_caso_alimentan_la_consistencia(raiz):
    for _ in range(2):
        _registrar(raiz, "bgl_des_natural_0000")
    resumen = manual.construir_resumen(raiz, "desarrollo")
    cons = resumen["tablas"]["consistencia_repeticiones"]["filas"]
    assert cons and cons[0]["n_comparables"] == 1 and cons[0]["concordancia"] == 1.0


def test_un_solo_analisis_por_caso_no_se_marca_como_falta(raiz):
    _registrar(raiz, "bgl_des_natural_0000")
    resumen = manual.construir_resumen(raiz, "desarrollo")
    codigos = {a["codigo"] for a in resumen["integridad"]["advertencias"]}
    assert "corridas_ausentes" not in codigos


def test_el_resumen_avisa_que_es_manual_y_sin_configuracion_congelada(raiz):
    _registrar(raiz, "bgl_des_natural_0000")
    resumen = manual.construir_resumen(raiz, "desarrollo")
    assert resumen["analisis_manual"] is True
    primero = resumen["integridad"]["advertencias"][0]
    assert primero["codigo"] == "analisis_manual" and "no hay configuración congelada" in primero["mensaje"].lower()
    assert "Gemini directo y el baseline no forman parte" in primero["mensaje"]


def test_desarrollo_es_de_depuracion_y_evaluacion_no(raiz, tmp_path):
    _registrar(raiz, "bgl_des_natural_0000")
    assert manual.construir_resumen(raiz, "desarrollo")["depuracion"] is True


def test_las_particiones_se_consolidan_por_separado(raiz):
    _registrar(raiz, "bgl_des_natural_0000")
    assert manual.particiones_con_analisis(raiz) == ["desarrollo"]
    assert manual.construir_resumen(raiz, "evaluacion") is None


def test_construir_el_resumen_no_deja_consolidaciones_acumuladas(raiz):
    _registrar(raiz, "bgl_des_natural_0000")
    manual.construir_resumen(raiz, "desarrollo")
    manual.construir_resumen(raiz, "desarrollo")
    assert not (raiz / "experiments" / "metrics").exists()


# --- la API ---------------------------------------------------------------------------------------------

@pytest.fixture
def api(raiz, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from src.api import historial, main, resultados

    monkeypatch.setattr(historial, "RUTA_DB", tmp_path / "historial.db")
    monkeypatch.setattr(main, "RAIZ_REPO", raiz)
    monkeypatch.setattr(resultados, "RAIZ_EXPERIMENTOS", raiz / "experiments")
    return TestClient(main.app), main


def _stream_falso(cid, error=None):
    def stream(raw_logs, thread_id=None):
        yield {"tipo": "inicio", "resumen": {"formato_detectado": "x", "total_lineas": 1}}
        if error:
            yield {"tipo": "error", "mensaje": error}
            return
        yield {"tipo": "final", "reporte": _reporte(cid)}
    return stream


def _eventos(respuesta):
    return [json.loads(l[6:]) for l in respuesta.text.splitlines() if l.startswith("data: ")]


def _analizar(cliente, main, monkeypatch, cid, nombre=None, contenido=None, error=None):
    monkeypatch.setattr(main, "analizar_lote_stream", _stream_falso(cid, error))
    ext = "csv" if cid.startswith("uwf") else "log"
    r = cliente.post("/api/analizar", files={"archivo": (nombre or f"{cid}.{ext}", (contenido or _contenido(cid)).encode())})
    return _eventos(cliente.get(f"/api/stream/{r.json()['job_id']}"))


def test_desde_la_interfaz_un_caso_conocido_queda_registrado_y_se_avisa(api, monkeypatch):
    cliente, main = api
    eventos = _analizar(cliente, main, monkeypatch, "uwf_des_visible_0000")
    registro = next(e for e in eventos if e["tipo"] == "registro_manual")
    assert registro["registrado"] is True and registro["case_id"] == "uwf_des_visible_0000"
    assert registro["config_version"] == "manual-desarrollo"
    # Va ANTES de `final`: la interfaz cierra el stream al recibir `final` y no vería un aviso posterior.
    assert eventos.index(registro) < next(i for i, e in enumerate(eventos) if e["tipo"] == "final")


def test_un_archivo_cualquiera_se_analiza_igual_y_avisa_que_no_entra_a_las_metricas(api, monkeypatch):
    cliente, main = api
    eventos = _analizar(cliente, main, monkeypatch, "uwf_des_visible_0000", nombre="otro.csv")
    assert any(e["tipo"] == "final" for e in eventos)
    registro = next(e for e in eventos if e["tipo"] == "registro_manual")
    assert registro["registrado"] is False and "no es el de un caso" in registro["motivo"]


def test_un_analisis_con_error_no_rompe_el_stream_y_queda_como_fallo(api, monkeypatch):
    cliente, main = api
    eventos = _analizar(cliente, main, monkeypatch, "bgl_des_natural_0000", error="503 UNAVAILABLE")
    assert next(e for e in eventos if e["tipo"] == "registro_manual")["registrado"] is False


def test_resultados_lista_y_sirve_las_metricas_manuales(api, monkeypatch):
    cliente, main = api
    assert cliente.get("/api/resultados").json()["configuraciones"] == []
    for cid in ("uwf_des_visible_0000", "uwf_des_visible_0001"):
        _analizar(cliente, main, monkeypatch, cid)
    configs = cliente.get("/api/resultados").json()["configuraciones"]
    assert [c["config_version"] for c in configs] == ["manual-desarrollo"]
    resumen = cliente.get("/api/resultados/manual-desarrollo").json()
    f = resumen["tablas"]["d1_deteccion"]["filas"][0]
    assert f["arquitectura"] == "nodex_multiagente" and (f["tp"], f["fn"]) == (1, 1)


def test_el_reporte_de_un_analisis_manual_se_puede_abrir_desde_resultados(api, monkeypatch):
    cliente, main = api
    eventos = _analizar(cliente, main, monkeypatch, "uwf_des_visible_0000")
    run_id = next(e for e in eventos if e["tipo"] == "registro_manual")["run_id"]
    r = cliente.get(f"/api/resultados/manual-desarrollo/reportes/{run_id}")
    assert r.status_code == 200 and r.json()["clasificacion"] == "MALICIOUS"


def test_una_configuracion_manual_sin_analisis_o_desconocida_es_404(api):
    cliente, _ = api
    assert cliente.get("/api/resultados/manual-desarrollo").status_code == 404
    assert cliente.get("/api/resultados/manual-otra").status_code == 404


def test_las_configuraciones_del_experimento_siguen_funcionando(api):
    cliente, _ = api
    assert cliente.get("/api/resultados/campana-que-no-existe").status_code == 404


def test_el_feedback_se_bloquea_en_modo_evaluacion(api, monkeypatch):
    cliente, main = api
    monkeypatch.setenv("NODEX_MODO_EVALUACION", "1")
    r = cliente.post("/api/feedback/cualquiera", json={"correcto": True, "comentario": ""})
    assert r.status_code == 409 and "modo evaluación" in r.json()["detail"]


def test_el_feedback_sigue_igual_fuera_del_modo_evaluacion(api, monkeypatch):
    cliente, _ = api
    monkeypatch.delenv("NODEX_MODO_EVALUACION", raising=False)
    assert cliente.post("/api/feedback/inexistente", json={"correcto": True}).status_code == 404
