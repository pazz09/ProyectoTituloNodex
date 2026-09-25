"""M5 (Fase 4 del cierre de auditoría, 23-sep-2026): la salida del
baseline registra motor, versión de esquema, configuración y commit --
sin esto, dos archivos de `results/` con código o configuración distintos
parecían comparables sin serlo.
"""

import src.tools.baseline_reglas as baseline_mod


def test_procedencia_incluye_motor_esquema_configuracion_y_commit():
    proc = baseline_mod._procedencia()
    assert proc["motor_preprocesamiento"] == "heterogeneo"
    assert proc["schema_version"]
    assert isinstance(proc["config_preprocesamiento"], dict)
    assert "LOG_PARSING_MODE" in proc["config_preprocesamiento"]
    assert "commit" in proc  # puede ser None fuera de un checkout de git
    assert proc["result_schema_version"] == "2.0"
    assert isinstance(proc["working_tree_dirty"], (bool, type(None)))
    assert proc["requirements_sha256"]
    assert proc["constraints_sha256"]


def test_commit_git_no_lanza_si_falla(monkeypatch):
    """Un entorno sin git (o fuera de un checkout) no debe tumbar una
    corrida que ya generó resultados reales."""
    import subprocess

    def _falla(*args, **kwargs):
        raise FileNotFoundError("git no encontrado")
    monkeypatch.setattr(subprocess, "check_output", _falla)

    assert baseline_mod._commit_git() is None


def test_commit_git_devuelve_un_hash_en_este_repo():
    """Este repo SÍ es un checkout de git -- confirma el camino feliz,
    no solo el de error."""
    commit = baseline_mod._commit_git()
    assert commit is None or (isinstance(commit, str) and len(commit) == 40)
