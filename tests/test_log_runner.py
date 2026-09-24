"""Camino de error del CLI (`src/tools/log_runner.py`).

Revisión del camino productivo, cierre de auditoría técnica (23-sep-2026):
antes de esto, un fallo de `preprocesar()` no tenía ningún try/except propio
en el CLI -- se propagaba como traceback crudo de Python hasta la terminal.
Estos tests verifican que ahora da un mensaje claro por stderr y termina con
un código de salida distinto de cero, sin traceback.
"""

import sys

import pytest

import src.tools.log_runner as log_runner_mod
from src.preprocessing.pipeline import PreprocesamientoError

LOTE = ("Jan 10 13:55:36 srv sshd[1]: Failed password for invalid user admin "
       "from 203.0.113.10 port 22 ssh2\n")


def test_un_fallo_de_preprocesamiento_no_deja_pasar_un_traceback(tmp_path, monkeypatch, capsys):
    archivo = tmp_path / "lote.log"
    archivo.write_text(LOTE, encoding="utf-8")

    def falla(*args, **kwargs):
        raise PreprocesamientoError("No se pudo preprocesar el lote (ValueError: boom)")
    monkeypatch.setattr(log_runner_mod, "analizar_lote", falla)
    monkeypatch.setattr(sys, "argv", ["log_runner.py", str(archivo), "--no-guardar"])

    with pytest.raises(SystemExit) as excinfo:
        log_runner_mod._main()

    assert excinfo.value.code == 1
    salida = capsys.readouterr()
    assert "No se pudo preprocesar el lote" in salida.err
    assert "Traceback" not in salida.err
    assert "Traceback" not in salida.out


def test_una_corrida_exitosa_no_se_ve_afectada(tmp_path, monkeypatch, capsys):
    """El wrapping no debe alterar el camino feliz: el CLI corre igual que
    antes cuando el preprocesamiento no falla."""
    archivo = tmp_path / "lote.log"
    archivo.write_text(LOTE, encoding="utf-8")

    def ok(raw_logs, thread_id=None):
        return {"resumen_logs": {"formato_detectado": "auth_log", "total_lineas": 1},
                "preprocessing_metadata": {}, "diagnostico": "prueba", "confianza": 0.5}
    monkeypatch.setattr(log_runner_mod, "analizar_lote", ok)
    monkeypatch.setattr(sys, "argv", ["log_runner.py", str(archivo), "--no-guardar"])

    log_runner_mod._main()

    salida = capsys.readouterr()
    assert "REPORTE FINAL" in salida.out
