"""Archivo etiquetado de un piloto (src/experimentation/archivo_piloto.py). Datos ficticios en tmp_path."""

import json

import pytest

from src.experimentation import archivo_piloto as ap

CFG = "piloto-prueba"


def _json(ruta, datos):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos), encoding="utf-8")


@pytest.fixture
def repo(tmp_path):
    exp = tmp_path / "experiments"
    for carpeta in ("nodex", "baseline", "gemini_externo"):
        _json(exp / carpeta / "bgl" / f"c__{carpeta}.json", {"config_version": CFG, "x": carpeta})
        _json(exp / carpeta / "bgl" / "raw" / f"c__{carpeta}.raw.json", {"config_version": CFG})
        _json(exp / carpeta / "bgl" / f"otra__{carpeta}.json", {"config_version": "OTRA"})
    _json(exp / "telemetry" / "bgl" / "c__nodex.json", {"config_version": CFG})
    _json(exp / "telemetry" / "bgl" / "c__nodex.consultas_externas.json", {"config_version": CFG})
    _json(exp / "fallos" / "bgl" / "c__f1.json", {"config_version": CFG})
    _json(exp / "ejecucion" / CFG / "informe_etapa1.json", {"limpia": True})
    _json(exp / "ejecucion" / "OTRA" / "informe_etapa1.json", {"limpia": False})
    _json(exp / "metrics" / CFG / "20261015T000000Z" / "resumen.json", {"datos": 1})
    _json(exp / "config" / f"config_{CFG}.json", {
        "config_version": CFG, "huella": "abc123", "git": {"commit": "deadbeef", "arbol_limpio": True}})
    return tmp_path


def test_copia_solo_lo_de_esa_configuracion(repo):
    m = ap.archivar(repo, CFG)
    nombres = set(m["sha256"])
    assert "nodex/bgl/c__nodex.json" in nombres and "baseline/bgl/c__baseline.json" in nombres
    assert "gemini_externo/bgl/raw/c__gemini_externo.raw.json" in nombres
    assert "telemetry/bgl/c__nodex.consultas_externas.json" in nombres and "fallos/bgl/c__f1.json" in nombres
    assert f"ejecucion/{CFG}/informe_etapa1.json" in nombres
    assert f"metrics/{CFG}/20261015T000000Z/resumen.json" in nombres
    assert f"config/config_{CFG}.json" in nombres
    assert not any("otra" in n or "OTRA" in n for n in nombres)        # nada de otra configuración
    assert m["n_archivos"] == len(nombres) == 12      # 6 corridas + 2 telemetría + 1 fallo + 1 ejecución + 1 métricas + 1 config


def test_el_manifiesto_lleva_etiqueta_config_version_huella_y_commit(repo):
    m = ap.archivar(repo, CFG)
    assert m["etiqueta"] == "piloto, no reportable"
    assert (m["config_version"], m["huella_de_la_configuracion"], m["commit_congelado"]) == (CFG, "abc123", "deadbeef")
    assert "DEPURACIÓN" in m["aviso"] and "originales" in m["es_una_copia"]
    destino = repo / "experiments" / "piloto_no_reportable" / CFG
    assert (destino / "MANIFIESTO.json").is_file()
    assert "PILOTO, NO REPORTABLE" in (destino / "LEEME.txt").read_text(encoding="utf-8")


def test_es_una_copia_y_no_toca_los_originales(repo):
    antes = {p: p.read_bytes() for p in (repo / "experiments").rglob("*.json")}
    ap.archivar(repo, CFG)
    for p, contenido in antes.items():
        assert p.read_bytes() == contenido                         # los originales siguen igual
    assert (repo / "experiments" / "nodex" / "bgl" / "c__nodex.json").exists()


def test_los_hashes_del_manifiesto_coinciden_con_lo_archivado(repo):
    ap.archivar(repo, CFG)
    destino = repo / "experiments" / "piloto_no_reportable" / CFG
    assert ap.verificar(destino) == []


def test_si_un_archivo_archivado_cambia_la_verificacion_lo_dice(repo):
    ap.archivar(repo, CFG)
    destino = repo / "experiments" / "piloto_no_reportable" / CFG
    (destino / "nodex" / "bgl" / "c__nodex.json").write_text("{}", encoding="utf-8")
    (destino / "baseline" / "bgl" / "c__baseline.json").unlink()
    assert sorted(ap.verificar(destino)) == ["baseline/bgl/c__baseline.json", "nodex/bgl/c__nodex.json"]


def test_no_se_sobrescribe_un_archivo_existente(repo):
    ap.archivar(repo, CFG)
    with pytest.raises(FileExistsError):
        ap.archivar(repo, CFG)


def test_sin_resultados_de_esa_configuracion_falla_en_vez_de_dejar_una_carpeta_vacia(repo):
    with pytest.raises(FileNotFoundError):
        ap.archivar(repo, "no-existe")
    assert not (repo / "experiments" / "piloto_no_reportable" / "no-existe").exists()
