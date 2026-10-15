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
        "LLM_SIN_RESPALDO": "true", "TEMPERATURE": "0"}
    assert "generateContent" in campana.GENERACION["api"]
    assert "DECISIÓN PENDIENTE" in campana.RECURSOS_EXTERNOS["politica_campana_final"]
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
    assert "DECISIÓN PENDIENTE" in c.recursos_externos["politica_campana_final"]
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
