"""Lanzador de la campaña (src/experimentation/campana.py).

Todo con procesos y corredores simulados: ninguna de estas pruebas llama a la API.
Lo que se fija son las reglas del lanzador: sin `--ejecutar` no hace nada, manda la
configuración congelada, el escalonado, el tope y la parada tras tres fallas de
infraestructura seguidas.
"""

import json
import shutil
from pathlib import Path

import pytest

from src.experimentation import campana, orquestador
from src.experimentation.knowledge.aislamiento import configuracion_experimental
from src.experimentation.runtime import persistencia
from src.experimentation.runtime.identidad import IdentidadCorrida

HOY = "2026-10-15"       # precios: USD 0,75 por millón de entrada y 3,75 de salida hasta fin de 2026

RAIZ = Path(__file__).resolve().parents[2]
CONFIG = "piloto-prueba"

CONGELADA = {
    "config_version": CONFIG,
    "git": {"commit": "abc123", "arbol_limpio": True},
    "parametros": {"LLM_MODEL_PRIMARY": "gemini-3.8-flash", "LLM_MODEL_FALLBACK": "gemini-3.8-flash",
                   "LLM_SIN_RESPALDO": True, "TEMPERATURE": 0.0, "TOP_K_FEWSHOT": 3,
                   "LOG_PRESERVE_RAW": True, "AUSENTE": None},
    "credenciales_presentes": {"GEMINI_API_KEY": True},
}


# --- el plan --------------------------------------------------------------------------------

def test_sin_ejecutar_solo_muestra_el_plan_y_no_lanza_ningun_proceso(monkeypatch, capsys):
    def prohibido(*a, **k):
        raise AssertionError("no debía lanzar ningún proceso")

    monkeypatch.setattr(campana, "ejecutar_hijo", prohibido)
    monkeypatch.setattr(campana.subprocess, "run", prohibido)
    monkeypatch.setattr(campana.subprocess, "Popen", prohibido)
    assert campana.main(["--config-version", CONFIG], raiz=RAIZ) == 0
    salida = capsys.readouterr().out
    assert "sin --ejecutar" in salida
    assert "72 pendientes" in salida                       # 24 casos x 3 arquitecturas
    assert "NO un piso" in salida
    assert "orden de magnitud" in salida and "N=1" in salida
    assert "DEPURACIÓN" in salida


def test_el_plan_declara_que_hdfs_no_tiene_medicion_y_no_suma(capsys):
    campana.main(["--config-version", CONFIG], raiz=RAIZ)
    salida = capsys.readouterr().out
    assert "hdfs" in salida and "sin medición (no suma)" in salida
    assert "sin calcular" in salida                        # no se supone ningún precio


def test_ejecutar_exige_env_y_etapa(capsys):
    with pytest.raises(SystemExit) as e:
        campana.main(["--config-version", CONFIG, "--ejecutar"], raiz=RAIZ)
    assert e.value.code == 2


def test_ejecutar_sin_configuracion_congelada_se_niega(monkeypatch, tmp_path):
    monkeypatch.setattr(campana, "ejecutar_etapa", lambda *a, **k: pytest.fail("no debía correr"))
    with pytest.raises(SystemExit) as e:
        campana.main(["--config-version", "no-existe", "--ejecutar", "--etapa", "1",
                      "--env", str(tmp_path / ".env")], raiz=RAIZ)
    assert e.value.code == 2


def test_si_el_codigo_no_es_el_congelado_se_niega_a_ejecutar(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(campana, "leer_configuracion", lambda raiz, v: CONGELADA)
    monkeypatch.setattr(campana, "_git", lambda raiz, *a: "otro-commit" if "rev-parse" in a else "")
    monkeypatch.setattr(campana, "ejecutar_etapa", lambda *a, **k: pytest.fail("no debía correr"))
    codigo = campana.main(["--config-version", CONFIG, "--ejecutar", "--etapa", "1",
                           "--env", str(tmp_path / ".env")], raiz=RAIZ)
    assert codigo == campana.SALIDA_ETAPA_NO_LIMPIA
    assert "NO ES EL CONGELADO" in capsys.readouterr().out


def test_cambios_sin_commitear_en_src_tambien_se_rechazan(monkeypatch):
    monkeypatch.setattr(campana, "_git", lambda raiz, *a: "abc123" if "rev-parse" in a else " M src/llm.py")
    assert campana.comprobar_codigo(RAIZ, CONGELADA) == ["hay cambios sin commitear en src/"]
    monkeypatch.setattr(campana, "_git", lambda raiz, *a: "abc123" if "rev-parse" in a else "")
    assert campana.comprobar_codigo(RAIZ, CONGELADA) == []


# --- la configuración congelada manda ---------------------------------------------------------

def test_el_entorno_del_hijo_usa_lo_congelado_aunque_el_env_diga_otra_cosa(tmp_path):
    base = {"GEMINI_API_KEY": "clave-ficticia", "LLM_MODEL_PRIMARY": "gemini-3.1-pro-preview",
            "LLM_SIN_RESPALDO": "false", "TEMPERATURE": "1", "OTRA": "x"}
    e = campana.entorno_de_la_corrida(base, CONGELADA, tmp_path / "c", tmp_path / "i")
    assert e["LLM_MODEL_PRIMARY"] == "gemini-3.8-flash"
    assert e["LLM_SIN_RESPALDO"] == "true"                 # bool -> texto que lee _env_bool
    assert e["TEMPERATURE"] == "0.0"
    assert e["TOP_K_FEWSHOT"] == "3"
    assert "AUSENTE" not in e                              # un None congelado no se exporta
    assert e["GEMINI_API_KEY"] == "clave-ficticia" and e["OTRA"] == "x"   # el resto se conserva
    assert e["CHROMA_PATH"] == str(tmp_path / "c") and e["IP_CACHE_PATH"] == str(tmp_path / "i")
    assert e["HF_HUB_OFFLINE"] == "1"
    assert base["TEMPERATURE"] == "1"                      # no muta la entrada


def test_la_configuracion_del_piloto_es_flash_sin_respaldo_y_temperatura_cero():
    assert campana.CONFIGURACION_PILOTO == {
        "LLM_MODEL_PRIMARY": "gemini-3.8-flash", "LLM_MODEL_FALLBACK": "gemini-3.8-flash",
        "LLM_SIN_RESPALDO": "true", "TEMPERATURE": "0", "REPUTACION_SIN_ENRIQUECIMIENTO": "true"}
    assert "generateContent" in campana.GENERACION["api"]
    assert "sin enriquecimiento de reputación externa" in campana.RECURSOS_EXTERNOS["politica_campana_final"]
    assert "DECISIÓN PENDIENTE" not in json.dumps(campana.RECURSOS_EXTERNOS)
    assert "hereda" in campana.GENERACION["gemini_directo"]


def test_el_congelado_registra_generacion_y_recursos_externos(tmp_path):
    from types import SimpleNamespace
    from src.experimentation.runtime.configuracion import PARAMETROS_CONGELADOS, congelar, escribir
    modulo = SimpleNamespace(**{n: "x" for n in PARAMETROS_CONGELADOS},
                             GEMINI_API_KEY="no-se-guarda", GOOGLE_API_KEY=None,
                             ABUSEIPDB_API_KEY=None, NVD_API_KEY=None)
    c = congelar("t", RAIZ, modulo_config=modulo, generacion=campana.GENERACION,
                 recursos_externos=campana.RECURSOS_EXTERNOS)
    assert c.generacion["api"].startswith("generateContent")
    assert "sin enriquecimiento de reputación externa" in c.recursos_externos["politica_campana_final"]
    assert c.credenciales_presentes["GEMINI_API_KEY"] is True      # solo presencia
    otro = congelar("t", RAIZ, modulo_config=modulo, generacion={"api": "otra"},
                    recursos_externos=campana.RECURSOS_EXTERNOS)
    assert c.huella != otro.huella                         # la generación cambia la huella
    shutil_raiz = tmp_path / "repo"
    ruta = escribir(c, shutil_raiz)
    assert "no-se-guarda" not in ruta.read_text(encoding="utf-8")   # nunca la credencial


def test_la_verificacion_de_configuracion_efectiva_coincide_con_la_congelada(tmp_path):
    (tmp_path / ".env").write_text("GEMINI_API_KEY=clave-ficticia\nLLM_MODEL_PRIMARY=otro\n",
                                   encoding="utf-8")
    congelada = {"parametros": {"LLM_MODEL_PRIMARY": "gemini-3.8-flash",
                                "LLM_MODEL_FALLBACK": "gemini-3.8-flash",
                                "LLM_SIN_RESPALDO": True, "TEMPERATURE": 0.0}}
    v = campana.verificar_configuracion(RAIZ, tmp_path / ".env", congelada)
    assert v["coincide"] is True, v["distintos"]
    assert v["efectiva"]["LLM_MODEL_PRIMARY"] == "gemini-3.8-flash"   # y no «otro», del .env
    assert v["efectiva"]["LLM_SIN_RESPALDO"] is True


def test_la_verificacion_detecta_un_parametro_congelado_que_el_sistema_no_respeta(tmp_path):
    (tmp_path / ".env").write_text("", encoding="utf-8")
    congelada = {"parametros": {"LLM_MODEL_PRIMARY": "gemini-3.8-flash",
                                "PARAMETRO_QUE_NO_EXISTE": 5}}
    v = campana.verificar_configuracion(RAIZ, tmp_path / ".env", congelada)
    assert v["coincide"] is False
    assert "PARAMETRO_QUE_NO_EXISTE" in v["distintos"]


# --- etapas -------------------------------------------------------------------------------------

def test_la_etapa_1_es_un_solo_caso_con_las_tres_arquitecturas_y_la_2_es_el_resto():
    sub = orquestador.cargar_subconjunto(RAIZ, "piloto")
    plan = orquestador.planificar(RAIZ, sub, CONFIG, campana.ARQUITECTURAS_PILOTO)
    e1 = campana.entradas_de_la_etapa(plan, sub, 1)
    e2 = campana.entradas_de_la_etapa(plan, sub, 2)
    assert len(e1) == 3 and len({e["case_id"] for e in e1}) == 1
    assert {e["arquitectura"] for e in e1} == set(campana.ARQUITECTURAS_PILOTO)
    assert len(e2) == 69 and e1[0]["case_id"] not in {e["case_id"] for e in e2}
    assert len(e1) + len(e2) == len(plan.pendientes) == 72


# --- ejecutar una etapa con corridas simuladas ------------------------------------------------------

@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Un repositorio mínimo con el subconjunto del piloto y una configuración congelada."""
    (tmp_path / "experiments" / "subconjuntos").mkdir(parents=True)
    shutil.copy(RAIZ / "experiments" / "subconjuntos" / "piloto.json",
                tmp_path / "experiments" / "subconjuntos" / "piloto.json")
    (tmp_path / "experiments" / "config").mkdir(parents=True)
    (tmp_path / "experiments" / "config" / f"config_{CONFIG}.json").write_text(
        json.dumps(CONGELADA), encoding="utf-8")
    shutil.copy(RAIZ / "experiments" / "config" / "precios_modelo.json",
                tmp_path / "experiments" / "config" / "precios_modelo.json")
    (tmp_path / ".env").write_text("", encoding="utf-8")
    return tmp_path


def _corrida(entrada, estado="completa", infra=False):
    return {"run_id": f"{entrada['case_id']}__{entrada['arquitectura']}", **{
        k: entrada[k] for k in ("case_id", "dataset", "arquitectura")},
        "estado": estado, "error": None if estado == "completa" else "x",
        "segundos": 1.0, "infraestructura": infra, "tope_alcanzado": False}


def _informe_limpio(raiz, corrida, congelada):
    return {"run_id": corrida["run_id"], "arquitectura": corrida["arquitectura"],
            "dataset": corrida["dataset"], "case_id": corrida["case_id"],
            "estado": corrida["estado"], "error": corrida["error"], "segundos": 1.0,
            "credencial_presente": True, "modelo_pedido": "gemini-3.8-flash",
            "versiones_devueltas": ["gemini-3.8-flash"], "usa_fallback": False,
            "llamadas": 5, "llamadas_fallidas": 0, "tokens": None,
            "intentos_de_consulta_externa": 0}


def test_una_etapa_limpia_termina_con_codigo_0(repo, monkeypatch):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    codigo, informes = campana.ejecutar_etapa(
        repo, repo / ".env", CONFIG, "piloto", 1, correr=lambda r, b, c, e, p, v, l: _corrida(e))
    assert codigo == campana.SALIDA_OK and len(informes) == 3
    guardado = json.loads((repo / "experiments" / "ejecucion" / CONFIG
                           / "informe_etapa1.json").read_text(encoding="utf-8"))
    assert guardado["limpia"] is True and guardado["etiqueta"] == "depuracion_no_reportable"


def test_una_etapa_con_una_corrida_fallida_no_sale_limpia(repo, monkeypatch):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    n = {"i": 0}

    def correr(r, b, c, e, p, v, l):
        n["i"] += 1
        return _corrida(e, estado="error_contrato" if n["i"] == 2 else "completa")

    codigo, _ = campana.ejecutar_etapa(repo, repo / ".env", CONFIG, "piloto", 1, correr=correr)
    assert codigo == campana.SALIDA_ETAPA_NO_LIMPIA


def test_tres_fallas_de_infraestructura_seguidas_detienen_la_campana(repo, monkeypatch):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    lanzadas = []

    def correr(r, b, c, e, p, v, l):
        lanzadas.append(e["case_id"])
        return _corrida(e, estado="error_api", infra=True)

    codigo, informes = campana.ejecutar_etapa(
        repo, repo / ".env", CONFIG, "piloto", 2, correr=correr)
    assert codigo == campana.SALIDA_FALLAS_SEGUIDAS
    assert len(lanzadas) == 3 and len(informes) == 3          # se detuvo, no siguió con las 69
    guardado = json.loads((repo / "experiments" / "ejecucion" / CONFIG
                           / "informe_etapa2.json").read_text(encoding="utf-8"))
    assert guardado["detenido_por_fallas_seguidas"] is True


def test_un_exito_en_medio_reinicia_la_cuenta_de_fallas_seguidas(repo, monkeypatch):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    secuencia = iter(["infra", "infra", "ok", "infra", "infra", "ok"] + ["ok"] * 100)

    def correr(r, b, c, e, p, v, l):
        if next(secuencia) == "infra":
            return _corrida(e, estado="timeout", infra=True)
        return _corrida(e)

    codigo, informes = campana.ejecutar_etapa(
        repo, repo / ".env", CONFIG, "piloto", 2, correr=correr)
    assert codigo != campana.SALIDA_FALLAS_SEGUIDAS
    assert len(informes) == 69                                 # llegó hasta el final


def test_dos_fallas_de_infraestructura_seguidas_no_detienen(repo, monkeypatch):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    secuencia = iter(["infra", "infra"] + ["ok"] * 100)

    def correr(r, b, c, e, p, v, l):
        return _corrida(e, estado="error_api", infra=True) if next(secuencia) == "infra" else _corrida(e)

    _, informes = campana.ejecutar_etapa(repo, repo / ".env", CONFIG, "piloto", 2, correr=correr)
    assert len(informes) == 69


# --- una corrida en su proceso -------------------------------------------------------------------------

@pytest.fixture
def repo_con_chroma(repo):
    chroma = configuracion_experimental(repo).chroma
    chroma.mkdir(parents=True)
    (chroma / "chroma.sqlite3").write_bytes(b"x")
    return repo


ENTRADA = {"case_id": "bgl_des_balanceado_0000", "dataset": "bgl",
           "arquitectura": "gemini_externo", "repeticion": 1}


def _hijo_falso(escribe_salida=True, error=None, vencio=False, capturas=None):
    def falso(comando, cwd, entorno, tope_s):
        if capturas is not None:
            capturas.append({"comando": comando, "entorno": entorno, "tope_s": tope_s})
        destino = Path(comando[-1])
        identidad = IdentidadCorrida(ENTRADA["case_id"], "bgl", "gemini_externo", 1, CONFIG)
        if escribe_salida and not vencio:
            persistencia.guardar(identidad, repo_raiz[0], salida={"x": 1},
                                 ejecucion={"estado": "completa"})
        if not vencio:
            destino.write_text(json.dumps({"error": error}), encoding="utf-8")
        return (None if vencio else 0), "salida ñ", "error", vencio
    return falso


repo_raiz: list = []


def test_una_corrida_que_termina_bien_queda_completa(repo_con_chroma, monkeypatch):
    repo_raiz[:] = [repo_con_chroma]
    capturas = []
    monkeypatch.setattr(campana, "ejecutar_hijo", _hijo_falso(capturas=capturas))
    r = campana.correr_una(repo_con_chroma, {"GEMINI_API_KEY": "k"}, CONGELADA, ENTRADA,
                           "desarrollo", CONFIG, repo_con_chroma / "logs")
    assert r["estado"] == "completa" and r["error"] is None and r["infraestructura"] is False
    assert capturas[0]["tope_s"] == campana.TOPE_CORRIDA_S == 7200
    assert capturas[0]["entorno"]["LLM_MODEL_PRIMARY"] == "gemini-3.8-flash"
    assert capturas[0]["entorno"]["LLM_SIN_RESPALDO"] == "true"
    assert (repo_con_chroma / "logs").is_dir()
    assert any(p.name.endswith(".stdout.txt") for p in (repo_con_chroma / "logs").iterdir())
    assert persistencia.leer_fallos(repo_con_chroma, CONFIG) == []


def test_un_error_del_hijo_se_registra_como_fallo_y_se_clasifica(repo_con_chroma, monkeypatch):
    repo_raiz[:] = [repo_con_chroma]
    monkeypatch.setattr(campana, "ejecutar_hijo",
                        _hijo_falso(escribe_salida=False, error="ServerError: 503 UNAVAILABLE"))
    r = campana.correr_una(repo_con_chroma, {}, CONGELADA, ENTRADA, "desarrollo", CONFIG,
                           repo_con_chroma / "logs")
    assert r["estado"] == "error_api" and r["infraestructura"] is True
    (fallo,) = persistencia.leer_fallos(repo_con_chroma, CONFIG)
    assert fallo["estado"] == "error_api" and "503" in fallo["error"]


def test_una_corrida_que_supera_el_tope_se_registra_como_timeout_y_es_infraestructura(
        repo_con_chroma, monkeypatch):
    repo_raiz[:] = [repo_con_chroma]
    monkeypatch.setattr(campana, "ejecutar_hijo", _hijo_falso(escribe_salida=False, vencio=True))
    r = campana.correr_una(repo_con_chroma, {}, CONGELADA, ENTRADA, "desarrollo", CONFIG,
                           repo_con_chroma / "logs")
    assert r["estado"] == "timeout" and r["tope_alcanzado"] is True
    assert r["infraestructura"] is True
    assert "NoCompletoEnElTiempoPrevisto" in r["error"]
    assert persistencia.leer_fallos(repo_con_chroma, CONFIG)[0]["estado"] == "timeout"


def test_un_hijo_que_muere_sin_dejar_nada_no_se_oculta(repo_con_chroma, monkeypatch):
    repo_raiz[:] = [repo_con_chroma]

    def muerto(comando, cwd, entorno, tope_s):
        return 1, "", "Traceback ...", False

    monkeypatch.setattr(campana, "ejecutar_hijo", muerto)
    r = campana.correr_una(repo_con_chroma, {}, CONGELADA, ENTRADA, "desarrollo", CONFIG,
                           repo_con_chroma / "logs")
    assert r["estado"] == "error_contrato" and "sin dejar salida" in r["error"]
    assert persistencia.leer_fallos(repo_con_chroma, CONFIG)


def test_una_falla_de_api_guardada_por_el_sistema_cuenta_como_infraestructura(
        repo_con_chroma, monkeypatch):
    """Cuando el sistema guarda la corrida con estado `error_api` (Gemini directo lo hace),
    el lanzador la cuenta igual como falla de infraestructura para la regla de parada."""
    repo_raiz[:] = [repo_con_chroma]

    def hijo(comando, cwd, entorno, tope_s):
        identidad = IdentidadCorrida(ENTRADA["case_id"], "bgl", "gemini_externo", 1, CONFIG)
        persistencia.guardar(identidad, repo_con_chroma, salida={"x": 1},
                             ejecucion={"estado": "error_api"})
        Path(comando[-1]).write_text(json.dumps({"error": None}), encoding="utf-8")
        return 0, "", "", False

    monkeypatch.setattr(campana, "ejecutar_hijo", hijo)
    r = campana.correr_una(repo_con_chroma, {}, CONGELADA, ENTRADA, "desarrollo", CONFIG,
                           repo_con_chroma / "logs")
    assert r["estado"] == "error_api" and r["infraestructura"] is True


def test_cada_corrida_usa_una_copia_nueva_de_chroma_y_la_original_no_se_toca(
        repo_con_chroma, monkeypatch):
    repo_raiz[:] = [repo_con_chroma]
    capturas = []
    monkeypatch.setattr(campana, "ejecutar_hijo", _hijo_falso(capturas=capturas))
    campana.correr_una(repo_con_chroma, {}, CONGELADA, ENTRADA, "desarrollo", CONFIG,
                       repo_con_chroma / "logs")
    usada = capturas[0]["entorno"]["CHROMA_PATH"]
    assert usada != str(configuracion_experimental(repo_con_chroma).chroma)
    assert (configuracion_experimental(repo_con_chroma).chroma / "chroma.sqlite3").read_bytes() == b"x"


# --- criterio de «etapa limpia» --------------------------------------------------------------------

def _informe(**cambios):
    base = {"run_id": "r", "arquitectura": "nodex_multiagente", "estado": "completa",
            "error": None, "usa_fallback": False, "versiones_devueltas": ["gemini-3.8-flash"],
            "llamadas_fallidas": 0}
    base.update(cambios)
    return base


@pytest.mark.parametrize("cambios, fragmento", [
    ({"estado": "error_api", "error": "503"}, "estado error_api"),
    ({"usa_fallback": True}, "respaldo"),
    ({"versiones_devueltas": []}, "model_version"),
    ({"versiones_devueltas": ["gemini-3.1-pro-preview"]}, "no corresponde"),
    ({"llamadas_fallidas": 1}, "fallida"),
])
def test_lo_que_hace_que_una_etapa_no_salga_limpia(cambios, fragmento):
    limpia, motivos = campana.etapa_limpia([_informe(**cambios)], CONGELADA)
    assert limpia is False and any(fragmento in m for m in motivos)


def test_una_etapa_sana_sale_limpia_y_el_baseline_no_necesita_version():
    limpia, motivos = campana.etapa_limpia([
        _informe(), _informe(versiones_devueltas=["gemini-3.8-flash-001"]),
        _informe(arquitectura="baseline_reglas", versiones_devueltas=None, llamadas_fallidas=0)],
        CONGELADA)
    assert limpia is True and motivos == []


# --- el proceso hijo ------------------------------------------------------------------------------

def _trabajar_con(monkeypatch, repo, correr_una):
    """Corre `trabajar` con el bloqueo de red y la corrida real reemplazados."""
    from src.experimentation.runtime import consultas_externas as ce

    instalados = []
    monkeypatch.setattr(ce, "instalar", lambda registro: (
        instalados.append(registro),
        registro.consultas.append({"orden": 1, "herramienta": "nvd", "intento_externo": True})))
    monkeypatch.setattr(orquestador, "_correr_una", correr_una)
    monkeypatch.setattr(orquestador, "_metadatos_del_caso", lambda *a: {"tipo_deteccion": "x"})
    monkeypatch.setattr(orquestador, "asegurar_salida_utf8", lambda: {})
    return instalados


def test_el_hijo_instala_el_bloqueo_antes_de_correr_y_guarda_las_consultas(
        repo, monkeypatch, tmp_path):
    orden = []
    instalados = _trabajar_con(monkeypatch, repo, lambda *a: orden.append("corrida"))
    original = campana.orquestador._correr_una
    destino = tmp_path / "r.json"
    assert campana.trabajar(repo, "bgl", "bgl_des_a_0000", "nodex_multiagente", 1, CONFIG,
                            "desarrollo", destino) == 0
    assert len(instalados) == 1 and orden == ["corrida"]
    ident = IdentidadCorrida("bgl_des_a_0000", "bgl", "nodex_multiagente", 1, CONFIG)
    consultas = persistencia.leer_consultas_externas(ident, repo)
    assert consultas == [{"orden": 1, "herramienta": "nvd", "intento_externo": True}]
    assert json.loads(destino.read_text(encoding="utf-8")) == {"error": None}
    assert original is not None


def test_si_la_corrida_revienta_el_hijo_igual_guarda_las_consultas_y_reporta_el_error(
        repo, monkeypatch, tmp_path):
    def revienta(*a):
        raise RuntimeError("503 UNAVAILABLE")

    _trabajar_con(monkeypatch, repo, revienta)
    destino = tmp_path / "r.json"
    campana.trabajar(repo, "bgl", "bgl_des_a_0000", "nodex_multiagente", 1, CONFIG,
                     "desarrollo", destino)
    assert json.loads(destino.read_text(encoding="utf-8"))["error"] == "RuntimeError: 503 UNAVAILABLE"
    ident = IdentidadCorrida("bgl_des_a_0000", "bgl", "nodex_multiagente", 1, CONFIG)
    assert persistencia.leer_consultas_externas(ident, repo) is not None


def test_un_registro_de_consultas_previo_no_hace_fallar_al_hijo(repo, monkeypatch, tmp_path):
    ident = IdentidadCorrida("bgl_des_a_0000", "bgl", "nodex_multiagente", 1, CONFIG)
    persistencia.guardar_consultas_externas(ident, repo, [])
    _trabajar_con(monkeypatch, repo, lambda *a: None)
    campana.trabajar(repo, "bgl", "bgl_des_a_0000", "nodex_multiagente", 1, CONFIG,
                     "desarrollo", tmp_path / "r.json")
    assert persistencia.leer_consultas_externas(ident, repo) == []     # se conserva el primero


# --- JSON válido de NODEX medido por el lanzador ------------------------------------------------------------

def test_el_hijo_de_nodex_cuenta_las_respuestas_json_invalidas_y_las_guarda(
        repo, monkeypatch, tmp_path):
    import src.llm as modulo_llm

    respuestas = iter([{"ok": 1}, {"error": "json_invalido", "raw": "x"}, {"ok": 2}])
    monkeypatch.setattr(modulo_llm, "llm_json", lambda *a, **k: next(respuestas))   # se restaura sola

    def corrida(*a):
        for _ in range(3):
            modulo_llm.llm_json("p")          # lo que harían los nodos del pipeline

    _trabajar_con(monkeypatch, repo, corrida)
    campana.trabajar(repo, "bgl", "bgl_des_a_0000", "nodex_multiagente", 1, CONFIG,
                     "desarrollo", tmp_path / "r.json")
    ident = IdentidadCorrida("bgl_des_a_0000", "bgl", "nodex_multiagente", 1, CONFIG)
    assert persistencia.leer_llm_json(ident, repo) == {"llamadas": 3, "invalidas": 1}


def test_una_corrida_de_nodex_que_no_llama_al_modelo_deja_cero_de_cero_y_no_nada(
        repo, monkeypatch, tmp_path):
    import src.llm as modulo_llm

    monkeypatch.setattr(modulo_llm, "llm_json", lambda *a, **k: {})
    _trabajar_con(monkeypatch, repo, lambda *a: None)
    campana.trabajar(repo, "bgl", "bgl_des_a_0000", "nodex_multiagente", 1, CONFIG,
                     "desarrollo", tmp_path / "r.json")
    ident = IdentidadCorrida("bgl_des_a_0000", "bgl", "nodex_multiagente", 1, CONFIG)
    assert persistencia.leer_llm_json(ident, repo) == {"llamadas": 0, "invalidas": 0}


def test_si_la_corrida_revienta_igual_se_guarda_lo_contado(repo, monkeypatch, tmp_path):
    import src.llm as modulo_llm

    monkeypatch.setattr(modulo_llm, "llm_json", lambda *a, **k: {"error": "json_invalido"})

    def revienta(*a):
        modulo_llm.llm_json("p")
        raise RuntimeError("503 UNAVAILABLE")

    _trabajar_con(monkeypatch, repo, revienta)
    campana.trabajar(repo, "bgl", "bgl_des_a_0000", "nodex_multiagente", 1, CONFIG,
                     "desarrollo", tmp_path / "r.json")
    ident = IdentidadCorrida("bgl_des_a_0000", "bgl", "nodex_multiagente", 1, CONFIG)
    assert persistencia.leer_llm_json(ident, repo) == {"llamadas": 1, "invalidas": 1}


def test_gemini_directo_y_el_baseline_no_instrumentan_llm_json(repo, monkeypatch, tmp_path):
    import src.llm as modulo_llm

    original = lambda *a, **k: {}                                        # noqa: E731
    monkeypatch.setattr(modulo_llm, "llm_json", original)
    _trabajar_con(monkeypatch, repo, lambda *a: None)
    for arq in ("gemini_externo", "baseline_reglas"):
        campana.trabajar(repo, "bgl", "bgl_des_a_0000", arq, 1, CONFIG, "desarrollo",
                         tmp_path / f"{arq}.json")
        ident = IdentidadCorrida("bgl_des_a_0000", "bgl", arq, 1, CONFIG)
        assert persistencia.leer_llm_json(ident, repo) is None
    assert modulo_llm.llm_json is original


def test_el_informe_de_la_corrida_trae_el_json_de_nodex(repo):
    ident = IdentidadCorrida("bgl_des_a_0000", "bgl", "nodex_multiagente", 2, CONFIG)
    persistencia.guardar_llm_json(ident, repo, 7, 2)
    corrida = {"run_id": ident.run_id, "case_id": ident.case_id, "dataset": "bgl",
               "arquitectura": "nodex_multiagente", "repeticion": 2, "estado": "completa",
               "error": None, "segundos": 1.0}
    informe = campana.informe_de_corrida(repo, corrida, {**CONGELADA, "config_version": CONFIG})
    assert (informe["json_llamadas"], informe["json_invalidas"]) == (7, 2)


def test_el_informe_lee_la_repeticion_de_la_corrida_y_no_siempre_la_primera(repo):
    """Con N = 2 la telemetría de la repetición 2 es otro archivo: leer siempre la 1 la confundiría."""
    uno = IdentidadCorrida("bgl_des_a_0000", "bgl", "gemini_externo", 1, CONFIG)
    dos = IdentidadCorrida("bgl_des_a_0000", "bgl", "gemini_externo", 2, CONFIG)
    for ident, n in ((uno, 11), (dos, 22)):
        persistencia.guardar(ident, repo, salida={"x": 1}, ejecucion={"estado": "completa"},
                             telemetria={"llm_calls": [{"input_tokens": n, "output_tokens": 1,
                                                        "model_version": "gemini-3.8-flash"}] * 2,
                                         "input_tokens": n})
    corrida = {"run_id": dos.run_id, "case_id": dos.case_id, "dataset": "bgl",
               "arquitectura": "gemini_externo", "repeticion": 2, "estado": "completa",
               "error": None, "segundos": 1.0}
    informe = campana.informe_de_corrida(repo, corrida, {**CONGELADA, "config_version": CONFIG})
    assert informe["tokens"]["entrada"] == 22


# --- tope de gasto acumulado ---------------------------------------------------------------------------------

def _correr_con_costo(raiz, usd_por_corrida_con_modelo, lanzadas=None, repeticion=1):
    """Corredor simulado: guarda la corrida con una telemetría que cuesta lo pedido (0,75 USD/M de
    entrada). El baseline no usa el modelo y no cuesta."""
    entrada_tokens = round(usd_por_corrida_con_modelo / 0.75 * 1_000_000)

    def correr(r, b, c, e, p, v, l):
        if lanzadas is not None:
            lanzadas.append((e["arquitectura"], e["dataset"], e["case_id"]))
        ident = IdentidadCorrida(e["case_id"], e["dataset"], e["arquitectura"], e["repeticion"], v)
        llamadas = [] if e["arquitectura"] == "baseline_reglas" else [
            {"model": "gemini-3.8-flash", "input_tokens": entrada_tokens, "output_tokens": 0,
             "reasoning_tokens": 0}]
        persistencia.guardar(ident, raiz, salida={"x": 1}, ejecucion={"estado": "completa"},
                             telemetria={"llm_calls": llamadas})
        return {**_corrida(e), "run_id": ident.run_id, "repeticion": e["repeticion"]}
    return correr


def _informe_guardado(repo, nombre="informe_etapa2.json"):
    return json.loads((repo / "experiments" / "ejecucion" / CONFIG / nombre).read_text(encoding="utf-8"))


def test_el_gasto_acumulado_se_informa_por_corrida_y_por_etapa(repo, monkeypatch):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    campana.ejecutar_etapa(repo, repo / ".env", CONFIG, "piloto", 1, hoy=HOY, tope_gasto=100.0,
                           correr=_correr_con_costo(repo, 0.15))
    e1 = _informe_guardado(repo, "informe_etapa1.json")["gasto"]
    assert e1["inicial_usd"] == 0.0 and e1["gasto_acumulado_usd"] == pytest.approx(0.30)
    assert e1["de_la_etapa_usd"] == pytest.approx(0.30) and e1["tope_usd"] == 100.0
    campana.ejecutar_etapa(repo, repo / ".env", CONFIG, "piloto", 2, hoy=HOY, tope_gasto=100.0,
                           correr=_correr_con_costo(repo, 0.15))
    e2 = _informe_guardado(repo)["gasto"]
    assert e2["inicial_usd"] == pytest.approx(0.30)                   # lo de la etapa 1 sigue contando
    assert e2["de_la_etapa_usd"] == pytest.approx(23 * 0.30)
    assert e2["gasto_acumulado_usd"] == pytest.approx(0.30 + 23 * 0.30)
    registro = campana.leer_registro_de_gasto(repo, CONFIG)
    acumulados = [r["gasto_acumulado_usd"] for r in registro]
    assert len(registro) == 3 + 69 and acumulados == sorted(acumulados)
    assert registro[2]["gasto_acumulado_usd"] == pytest.approx(0.30)


def test_el_gasto_de_cada_corrida_se_imprime_acumulado(repo, monkeypatch, capsys):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    campana.ejecutar_etapa(repo, repo / ".env", CONFIG, "piloto", 1, hoy=HOY, tope_gasto=5.0,
                           correr=_correr_con_costo(repo, 0.15))
    assert "gasto acumulado USD 0.3000 de 5.00" in capsys.readouterr().out


def test_se_detiene_ANTES_de_la_corrida_que_haria_superar_el_tope(repo, monkeypatch):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    lanzadas = []
    codigo, informes = campana.ejecutar_etapa(
        repo, repo / ".env", CONFIG, "piloto", 2, hoy=HOY, tope_gasto=1.0,
        correr=_correr_con_costo(repo, 0.15, lanzadas))
    assert codigo == campana.SALIDA_TOPE_DE_GASTO
    assert len(lanzadas) == len(informes) == 9           # 3 casos × (NODEX, baseline, Gemini): 0,90
    gasto = _informe_guardado(repo)["gasto"]
    assert gasto["gasto_acumulado_usd"] == pytest.approx(0.90)
    assert gasto["gasto_acumulado_usd"] <= 1.0
    assert gasto["proyectado_usd"] == pytest.approx(1.05)           # la que NO se lanzó
    assert gasto["proyectado_usd"] > 1.0
    informe = _informe_guardado(repo)
    assert informe["detenido"] is True and informe["detenido_por_fallas_seguidas"] is False
    assert "superaría" in informe["motivo_de_parada"]


def test_la_parada_por_gasto_es_reanudable_y_no_repite_lo_guardado(repo, monkeypatch):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    primeras = []
    campana.ejecutar_etapa(repo, repo / ".env", CONFIG, "piloto", 2, hoy=HOY, tope_gasto=1.0,
                           correr=_correr_con_costo(repo, 0.15, primeras))
    resto = []
    codigo, _ = campana.ejecutar_etapa(repo, repo / ".env", CONFIG, "piloto", 2, hoy=HOY,
                                       tope_gasto=100.0, correr=_correr_con_costo(repo, 0.15, resto))
    assert codigo == campana.SALIDA_OK
    assert len(primeras) == 9 and len(resto) == 60 and not (set(primeras) & set(resto))
    # y el gasto acumulado incluye lo de la primera parte (se recalcula, no se pierde al reanudar)
    assert _informe_guardado(repo, next(
        p.name for p in sorted((repo / "experiments" / "ejecucion" / CONFIG).glob("informe_etapa2_*.json"))
    ))["gasto"]["inicial_usd"] == pytest.approx(0.90)


def test_si_el_gasto_guardado_ya_supera_el_tope_no_se_lanza_nada(repo, monkeypatch):
    """Gasto de un proceso anterior, sin ningún contador aparte: se lee de la telemetría."""
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    previa = IdentidadCorrida("bgl_des_previa", "bgl", "nodex_multiagente", 1, CONFIG)
    persistencia.guardar(previa, repo, salida={"x": 1}, ejecucion={"estado": "completa"},
                         telemetria={"llm_calls": [{"input_tokens": 7_000_000, "output_tokens": 0}]})
    lanzadas = []
    codigo, _ = campana.ejecutar_etapa(repo, repo / ".env", CONFIG, "piloto", 2, hoy=HOY,
                                       tope_gasto=5.0, correr=_correr_con_costo(repo, 0.15, lanzadas))
    assert codigo == campana.SALIDA_TOPE_DE_GASTO and lanzadas == []
    assert "ya supera" in _informe_guardado(repo)["motivo_de_parada"]


def test_una_corrida_que_termina_con_gasto_sobre_el_tope_detiene_la_campana(repo, monkeypatch):
    """Si el costo real de una corrida supera lo que se esperaba, la siguiente ya no se lanza."""
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    lanzadas = []
    codigo, _ = campana.ejecutar_etapa(repo, repo / ".env", CONFIG, "piloto", 2, hoy=HOY,
                                       tope_gasto=0.10, correr=_correr_con_costo(repo, 0.50, lanzadas))
    assert codigo == campana.SALIDA_TOPE_DE_GASTO and len(lanzadas) == 1


def test_el_maximo_de_la_celda_del_piloto_de_referencia_acota_la_primera_corrida(repo, monkeypatch):
    """Sin ninguna medición propia, el máximo observado en el piloto bloquea una corrida cara."""
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    for i, usd in enumerate((0.30, 0.45)):
        ref = IdentidadCorrida(f"bgl_ref_{i}", "bgl", "nodex_multiagente", 1, "piloto-previo")
        persistencia.guardar(ref, repo, salida={"x": 1}, ejecucion={"estado": "completa"},
                             telemetria={"llm_calls": [{"input_tokens": int(usd / 0.75 * 1e6),
                                                        "output_tokens": 0}]})
    lanzadas = []
    codigo, _ = campana.ejecutar_etapa(
        repo, repo / ".env", CONFIG, "piloto", 1, hoy=HOY, tope_gasto=0.40,
        config_referencia="piloto-previo", correr=_correr_con_costo(repo, 0.10, lanzadas))
    assert codigo == campana.SALIDA_TOPE_DE_GASTO and lanzadas == []     # 0 + 0,45 > 0,40
    sin_referencia = []
    codigo, _ = campana.ejecutar_etapa(
        repo, repo / ".env", CONFIG, "piloto", 1, hoy=HOY, tope_gasto=0.40,
        correr=_correr_con_costo(repo, 0.10, sin_referencia))
    assert codigo == campana.SALIDA_OK and len(sin_referencia) == 3


def test_el_baseline_no_se_bloquea_por_gasto_porque_no_cuesta(repo, monkeypatch):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    lanzadas = []
    campana.ejecutar_etapa(repo, repo / ".env", CONFIG, "piloto", 2, hoy=HOY, tope_gasto=0.50,
                           correr=_correr_con_costo(repo, 0.15, lanzadas))
    assert [a for a, _, _ in lanzadas] == ["nodex_multiagente", "baseline_reglas", "gemini_externo",
                                           "nodex_multiagente", "baseline_reglas"]
    # el baseline (costo 0) se lanza aunque falte poco; se detuvo antes de la corrida con modelo


def test_sin_tabla_de_precios_no_se_puede_medir_el_gasto_y_no_se_lanza_nada(repo, monkeypatch, capsys):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    (repo / "experiments" / "config" / "precios_modelo.json").unlink()
    lanzadas = []
    codigo, informes = campana.ejecutar_etapa(
        repo, repo / ".env", CONFIG, "piloto", 1, hoy=HOY, correr=_correr_con_costo(repo, 0.15, lanzadas))
    assert codigo == campana.SALIDA_TOPE_DE_GASTO and lanzadas == [] and informes == []
    assert "NO SE PUEDE MEDIR EL GASTO" in capsys.readouterr().out


def test_los_precios_de_2027_duplican_el_gasto_de_lo_mismo(repo, monkeypatch):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    congelada = campana.leer_configuracion(repo, CONFIG)
    previa = IdentidadCorrida("bgl_des_previa", "bgl", "nodex_multiagente", 1, CONFIG)
    persistencia.guardar(previa, repo, salida={"x": 1}, ejecucion={"estado": "completa"},
                         telemetria={"llm_calls": [{"input_tokens": 1_000_000, "output_tokens": 0}]})
    antes = campana.revisar_tope_de_gasto(repo, congelada, 5.0, "2026-12-31")["gasto_acumulado_usd"]
    despues = campana.revisar_tope_de_gasto(repo, congelada, 5.0, "2027-01-01")["gasto_acumulado_usd"]
    assert antes == pytest.approx(0.75) and despues == pytest.approx(1.50)


def test_una_corrida_con_costo_parcial_se_informa(repo, monkeypatch):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    previa = IdentidadCorrida("bgl_des_previa", "bgl", "gemini_externo", 1, CONFIG)
    persistencia.guardar(previa, repo, salida={"x": 1}, ejecucion={"estado": "error_api"},
                         telemetria={"llm_calls": [{"input_tokens": None, "output_tokens": None}]})
    codigo, _ = campana.ejecutar_etapa(repo, repo / ".env", CONFIG, "piloto", 1, hoy=HOY,
                                       correr=_correr_con_costo(repo, 0.10))
    assert previa.run_id in _informe_guardado(repo, "informe_etapa1.json")["gasto"][
        "corridas_con_costo_parcial"]


def test_el_filtro_por_dataset_lanza_solo_ese_dataset(repo, monkeypatch):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    lanzadas = []
    campana.ejecutar_etapa(repo, repo / ".env", CONFIG, "piloto", 2, hoy=HOY, tope_gasto=100.0,
                           dataset="uwf", correr=_correr_con_costo(repo, 0.01, lanzadas))
    assert lanzadas and {d for _, d, _ in lanzadas} == {"uwf"}


def test_las_corridas_de_las_dos_repeticiones_se_distinguen_y_las_dos_cuestan(repo, monkeypatch):
    for rep in (1, 2):
        ident = IdentidadCorrida("bgl_ev_x", "bgl", "gemini_externo", rep, CONFIG)
        persistencia.guardar(ident, repo, salida={"x": 1}, ejecucion={"estado": "completa"},
                             telemetria={"llm_calls": [{"input_tokens": 1_000_000, "output_tokens": 0}]})
    congelada = campana.leer_configuracion(repo, CONFIG)
    r = campana.revisar_tope_de_gasto(repo, congelada, 5.0, HOY)
    assert r["corridas_con_costo"] == 2 and r["gasto_acumulado_usd"] == pytest.approx(1.50)


def test_el_tope_por_omision_es_5_dolares_y_el_codigo_de_salida_es_el_5():
    assert campana.TOPE_GASTO_USD == 5.00 and campana.SALIDA_TOPE_DE_GASTO == 5
    assert campana.TOPE_CORRIDA_S == 7200 and campana.MAX_FALLAS_DE_INFRAESTRUCTURA_SEGUIDAS == 3


def test_el_plan_muestra_el_tope_de_gasto_y_la_etiqueta_de_la_campana(capsys):
    assert campana.main(["--config-version", "no-existe"]) == campana.SALIDA_OK
    salida = capsys.readouterr().out
    assert "tope de gasto acumulado: USD 5.00" in salida and "DEPURACIÓN" in salida


def test_la_etiqueta_de_los_resultados_depende_de_la_particion():
    assert campana.etiqueta_de_resultados({"particion": "evaluacion"}) == "campana_evaluacion"
    assert campana.etiqueta_de_resultados({"particion": "desarrollo"}) == "depuracion_no_reportable"


def test_gastar_exactamente_el_tope_no_lo_supera_y_la_campana_sigue(repo, monkeypatch):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    lanzadas = []
    codigo, _ = campana.ejecutar_etapa(repo, repo / ".env", CONFIG, "piloto", 1, hoy=HOY,
                                       tope_gasto=0.30, correr=_correr_con_costo(repo, 0.15, lanzadas))
    assert codigo == campana.SALIDA_OK and len(lanzadas) == 3     # 0,15 + 0,15 = 0,30: justo el tope
    assert _informe_guardado(repo, "informe_etapa1.json")["gasto"]["gasto_acumulado_usd"] == pytest.approx(0.30)


def test_si_la_ultima_corrida_de_la_etapa_deja_el_gasto_sobre_el_tope_la_etapa_no_sale_ok(
        repo, monkeypatch):
    """La revisión previa usa el máximo OBSERVADO; una celda sin medición no puede acotar nada. El
    chequeo posterior es la red de seguridad: lo que ya se gastó y pasó el tope se informa y detiene."""
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    barata, cara = _correr_con_costo(repo, 0.10), _correr_con_costo(repo, 0.50)

    def correr(r, b, c, e, p, v, l):         # Gemini cuesta mucho más de lo observado antes
        return (cara if e["arquitectura"] == "gemini_externo" else barata)(r, b, c, e, p, v, l)

    codigo, _ = campana.ejecutar_etapa(repo, repo / ".env", CONFIG, "piloto", 1, hoy=HOY,
                                       tope_gasto=0.55, correr=correr)
    assert codigo == campana.SALIDA_TOPE_DE_GASTO
    assert "acaba de terminar" in _informe_guardado(repo, "informe_etapa1.json")["motivo_de_parada"]


# --- etapas de la campaña: A = repetición 1, B = repetición 2 -------------------------------------------------

@pytest.fixture
def repo_evaluacion(repo):
    """Un subconjunto de EVALUACIÓN ficticio (N=2): 3 casos de BGL y 2 de UWF. Solo ids, sin casos."""
    datos = {"particion": "evaluacion", "datasets": {
        "uwf": {"visible": {"case_ids": ["uwf_eva_visible_0001", "uwf_eva_visible_0002"]}},
        "bgl": {"natural": {"case_ids": ["bgl_eva_natural_0001", "bgl_eva_natural_0002",
                                         "bgl_eva_natural_0003"]}}}}
    (repo / "experiments" / "subconjuntos" / "mini.json").write_text(json.dumps(datos), encoding="utf-8")
    return repo


def _etapa(repo, etapa, usd=0.10, lanzadas=None, tope=5.0, correr=None):
    return campana.ejecutar_etapa(repo, repo / ".env", CONFIG, "mini", etapa, hoy=HOY, tope_gasto=tope,
                                  correr=correr or _correr_con_costo(repo, usd, lanzadas))


def _plan_mini(repo):
    sub = orquestador.cargar_subconjunto(repo, "mini")
    return sub, orquestador.planificar(repo, sub, CONFIG, campana.ARQUITECTURAS_PILOTO)


def test_la_etapa_A_es_la_repeticion_1_de_todos_los_casos_con_BGL_antes_que_UWF(repo_evaluacion, monkeypatch):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    lanzadas = []
    codigo, _ = _etapa(repo_evaluacion, "A", lanzadas=lanzadas)
    assert codigo == campana.SALIDA_OK and len(lanzadas) == 5 * 3          # 5 casos × 3 arquitecturas
    assert [d for _, d, _ in lanzadas] == ["bgl"] * 9 + ["uwf"] * 6
    assert {a for a, _, _ in lanzadas} == {"nodex_multiagente", "baseline_reglas", "gemini_externo"}
    _, plan = _plan_mini(repo_evaluacion)
    assert {e["repeticion"] for e in plan.ya_hechas} == {1}                 # nada de la repetición 2


def test_la_etapa_B_es_la_repeticion_2_solo_de_NODEX_y_Gemini_y_el_baseline_no_se_repite(
        repo_evaluacion, monkeypatch):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    _etapa(repo_evaluacion, "A")
    sub, plan = _plan_mini(repo_evaluacion)
    b = campana.entradas_de_la_etapa(plan, sub, "B")
    assert len(b) == 5 * 2 and {e["repeticion"] for e in b} == {2}
    assert "baseline_reglas" not in {e["arquitectura"] for e in b}
    lanzadas = []
    codigo, _ = _etapa(repo_evaluacion, "B", lanzadas=lanzadas)
    assert codigo == campana.SALIDA_OK and len(lanzadas) == 10


def test_la_campana_lanza_A_completa_y_despues_B_nunca_mezcladas(repo_evaluacion, monkeypatch):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    orden = []
    base = _correr_con_costo(repo_evaluacion, 0.10)

    def correr(r, b, c, e, p, v, l):
        orden.append(e["repeticion"])
        return base(r, b, c, e, p, v, l)

    codigo, resultado = campana.ejecutar_campana_por_etapas(
        repo_evaluacion, repo_evaluacion / ".env", CONFIG, "mini", correr=correr, hoy=HOY)
    assert codigo == campana.SALIDA_OK and resultado["B"]["lanzada"] is True
    assert orden == [1] * 15 + [2] * 10                      # primero todo A, después todo B


def test_si_el_gasto_real_de_A_por_2_no_supera_el_tope_B_se_autoriza(repo_evaluacion, monkeypatch):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    _etapa(repo_evaluacion, "A", usd=0.20)                  # 10 corridas con modelo × 0,20 = 2,00
    congelada = campana.leer_configuracion(repo_evaluacion, CONFIG)
    d = campana.decidir_etapa_b(repo_evaluacion, congelada, 5.0, HOY, pendientes_de_a=0)
    assert d["autorizada"] is True and d["gasto_real_etapa_a_usd"] == pytest.approx(2.0)
    assert d["proyeccion_etapa_b_usd"] == pytest.approx(4.0)


def test_si_el_gasto_real_de_A_por_2_supera_el_tope_B_no_se_lanza_y_se_informa_el_gasto(
        repo_evaluacion, monkeypatch, capsys):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    _etapa(repo_evaluacion, "A", usd=0.30)                  # 10 × 0,30 = 3,00; × 2 = 6,00 > 5,00
    lanzadas = []
    codigo, informes = _etapa(repo_evaluacion, "B", usd=0.30, lanzadas=lanzadas)
    assert codigo == campana.SALIDA_ETAPA_B_NO_AUTORIZADA and lanzadas == [] and informes == []
    informe = _informe_guardado(repo_evaluacion, "informe_etapaB.json")
    decision = informe["decision_etapa_b"]
    assert decision["autorizada"] is False and decision["gasto_real_etapa_a_usd"] == pytest.approx(3.0)
    assert decision["proyeccion_etapa_b_usd"] == pytest.approx(6.0) and decision["tope_usd"] == 5.0
    assert "supera el tope" in informe["motivo_de_parada"]
    assert "Compuerta de la Etapa B" in capsys.readouterr().out


def test_la_proyeccion_exactamente_igual_al_tope_deja_pasar_a_B(repo_evaluacion, monkeypatch):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    # 4.000.000 tokens de entrada a USD 0,75 por millón = 3,00 exactos; × 2 = 6,00 justo.
    ident = IdentidadCorrida("bgl_eva_natural_0001", "bgl", "nodex_multiagente", 1, CONFIG)
    persistencia.guardar(ident, repo_evaluacion, salida={"x": 1}, ejecucion={"estado": "completa"},
                         telemetria={"llm_calls": [{"input_tokens": 4_000_000, "output_tokens": 0}]})
    congelada = campana.leer_configuracion(repo_evaluacion, CONFIG)
    assert campana.decidir_etapa_b(repo_evaluacion, congelada, 6.0, HOY, 0)["autorizada"] is True
    assert campana.decidir_etapa_b(repo_evaluacion, congelada, 5.99, HOY, 0)["autorizada"] is False


def test_la_campana_no_lanza_nada_de_B_si_la_compuerta_la_rechaza(repo_evaluacion, monkeypatch):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    lanzadas = []
    codigo, resultado = campana.ejecutar_campana_por_etapas(
        repo_evaluacion, repo_evaluacion / ".env", CONFIG, "mini", hoy=HOY,
        correr=_correr_con_costo(repo_evaluacion, 0.30, lanzadas))      # A = 3,00; × 2 = 6,00 > 5,00
    assert codigo == campana.SALIDA_ETAPA_B_NO_AUTORIZADA and resultado["B"]["lanzada"] is False
    assert len(lanzadas) == 15                                           # solo la Etapa A
    _, plan = _plan_mini(repo_evaluacion)
    assert all(e["repeticion"] == 1 for e in plan.ya_hechas) and len(plan.ya_hechas) == 15


def test_los_codigos_de_salida_son_distintos_y_el_de_B_es_el_6():
    codigos = [campana.SALIDA_OK, campana.SALIDA_ETAPA_NO_LIMPIA, campana.SALIDA_FALLAS_SEGUIDAS,
               campana.SALIDA_TOPE_DE_GASTO, campana.SALIDA_ETAPA_B_NO_AUTORIZADA]
    assert codigos == [0, 3, 4, 5, 6] and len(set(codigos)) == 5


def test_B_no_se_puede_lanzar_directamente_sin_terminar_A(repo_evaluacion, monkeypatch):
    """La compuerta vive en `ejecutar_etapa`, no en quien la llama: no hay atajo."""
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    lanzadas = []
    codigo, _ = _etapa(repo_evaluacion, "B", lanzadas=lanzadas)
    assert codigo == campana.SALIDA_ETAPA_B_NO_AUTORIZADA and lanzadas == []
    assert "no terminó" in _informe_guardado(repo_evaluacion, "informe_etapaB.json")["motivo_de_parada"]


def test_si_A_no_sale_limpia_la_campana_no_sigue_a_B(repo_evaluacion, monkeypatch):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    base = _correr_con_costo(repo_evaluacion, 0.01)

    def correr(r, b, c, e, p, v, l):
        res = base(r, b, c, e, p, v, l)
        return {**res, "estado": "error_contrato", "error": "x"} if e["case_id"].endswith("_0002") else res

    codigo, resultado = campana.ejecutar_campana_por_etapas(
        repo_evaluacion, repo_evaluacion / ".env", CONFIG, "mini", correr=correr, hoy=HOY)
    assert codigo == campana.SALIDA_ETAPA_NO_LIMPIA and resultado["B"]["lanzada"] is False


def test_el_gasto_de_A_cuenta_solo_la_repeticion_1_aunque_B_ya_haya_corrido(repo_evaluacion, monkeypatch):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    _etapa(repo_evaluacion, "A", usd=0.10)
    _etapa(repo_evaluacion, "B", usd=0.10)
    congelada = campana.leer_configuracion(repo_evaluacion, CONFIG)
    d = campana.decidir_etapa_b(repo_evaluacion, congelada, 5.0, HOY, 0)
    assert d["gasto_real_etapa_a_usd"] == pytest.approx(1.0, abs=1e-4)          # no 2,0


def test_el_informe_de_cada_corrida_lee_su_propia_repeticion(repo_evaluacion):
    """Con N=2 el informe de una corrida de la repetición 2 trae SUS tokens y no los de la 1."""
    for rep, tokens in ((1, 111), (2, 222)):
        ident = IdentidadCorrida("bgl_eva_natural_0001", "bgl", "gemini_externo", rep, CONFIG)
        persistencia.guardar(ident, repo_evaluacion, salida={"x": 1}, ejecucion={"estado": "completa"},
                             telemetria={"llm_calls": [{"input_tokens": tokens, "output_tokens": 1,
                                                        "model_version": "gemini-3.8-flash"}],
                                         "input_tokens": tokens})
    congelada = {**CONGELADA, "config_version": CONFIG}
    for rep, esperado in ((1, 111), (2, 222)):
        ident = IdentidadCorrida("bgl_eva_natural_0001", "bgl", "gemini_externo", rep, CONFIG)
        corrida = {"run_id": ident.run_id, "case_id": ident.case_id, "dataset": "bgl",
                   "arquitectura": "gemini_externo", "repeticion": rep, "estado": "completa",
                   "error": None, "segundos": 1.0}
        assert campana.informe_de_corrida(repo_evaluacion, corrida, congelada)["tokens"]["entrada"] == esperado


def test_correr_una_devuelve_la_repeticion_de_la_corrida(repo_con_chroma, monkeypatch):
    repo_raiz[:] = [repo_con_chroma]
    monkeypatch.setattr(campana, "ejecutar_hijo", _hijo_falso())
    r = campana.correr_una(repo_con_chroma, {}, CONGELADA, ENTRADA, "desarrollo", CONFIG,
                           repo_con_chroma / "logs", tope_s=5)
    assert r["repeticion"] == 1


def test_el_plan_en_seco_muestra_las_etapas_A_y_B(repo_evaluacion, capsys):
    campana.main(["--subconjunto", "mini", "--config-version", CONFIG], raiz=repo_evaluacion)
    salida = capsys.readouterr().out
    assert "A = 15 corridas" in salida and "B = 10 corridas" in salida


# --- verificaciones con una sola arquitectura ----------------------------------------------------------------

def test_una_verificacion_puede_correr_solo_nodex(repo, monkeypatch):
    monkeypatch.setattr(campana, "informe_de_corrida", _informe_limpio)
    lanzadas = []
    codigo, informes = campana.ejecutar_etapa(
        repo, repo / ".env", CONFIG, "piloto", 1, hoy=HOY,
        correr=_correr_con_costo(repo, 0.10, lanzadas), arquitecturas=("nodex_multiagente",))
    assert codigo == campana.SALIDA_OK and [a for a, _, _ in lanzadas] == ["nodex_multiagente"]


def test_el_plan_en_seco_con_arquitecturas_acotadas_lo_dice(repo_evaluacion, capsys):
    campana.main(["--subconjunto", "mini", "--config-version", CONFIG, "--arquitecturas",
                  "nodex_multiagente"], raiz=repo_evaluacion)
    salida = capsys.readouterr().out
    assert "nodex_multiagente" in salida and "gemini_externo " not in salida.split("estimación")[0]


def test_la_campana_completa_no_acepta_arquitecturas_acotadas(repo_evaluacion):
    with pytest.raises(SystemExit):
        campana.main(["--subconjunto", "mini", "--config-version", CONFIG, "--arquitecturas",
                      "nodex_multiagente", "--campana", "--ejecutar", "--env", ".env"], raiz=repo_evaluacion)


def test_arquitecturas_desconocidas_se_rechazan(repo_evaluacion):
    with pytest.raises(SystemExit):
        campana.main(["--subconjunto", "mini", "--config-version", CONFIG, "--arquitecturas", "otra"],
                     raiz=repo_evaluacion)


# --- plan en seco con costo y rango ---------------------------------------------------------------------------

def _sembrar_referencia(repo, config="piloto-ref"):
    """Corridas medidas de referencia: NODEX y Gemini en BGL y UWF, de costo 0,10 / 0,20 / 0,30 USD."""
    for arq in ("nodex_multiagente", "gemini_externo"):
        for ds in ("bgl", "uwf"):
            for i, usd in enumerate((0.10, 0.20, 0.30)):
                ident = IdentidadCorrida(f"{ds}_des_{i}", ds, arq, 1, config)
                persistencia.guardar(ident, repo, salida={"x": 1}, ejecucion={"estado": "completa"},
                                     telemetria={"llm_calls": [{"input_tokens": round(usd / 0.75 * 1e6),
                                                                "output_tokens": 0}]})


def test_el_plan_en_seco_con_referencia_muestra_minimo_media_maximo_riesgo_y_etapa_A(
        repo_evaluacion, capsys):
    _sembrar_referencia(repo_evaluacion)
    campana.main(["--subconjunto", "mini", "--config-version", CONFIG, "--config-referencia", "piloto-ref"],
                 raiz=repo_evaluacion)
    salida = capsys.readouterr().out
    # 3 casos de BGL y 2 de UWF, N=2, NODEX y Gemini: 4 × 6 + 4 × 4... = 20 corridas con modelo,
    # costos por corrida 0,10 / 0,20 / 0,30 -> mínimo 2,00, media 4,00, máximo 6,00.
    assert "mínimo 2.00 | media 4.00 | máximo observado 6.00" in salida
    assert "p5" in salida and "P(> 5.00)" in salida and "margen frente a USD 6,00" in salida
    assert "Etapa A: mínimo 1.00 | media 2.00 | máximo 3.00" in salida


def test_el_plan_en_seco_sin_referencia_no_inventa_un_rango(repo_evaluacion, capsys):
    campana.main(["--subconjunto", "mini", "--config-version", CONFIG], raiz=repo_evaluacion)
    assert "costo con rango" not in capsys.readouterr().out
