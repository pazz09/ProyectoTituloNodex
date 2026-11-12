"""Tests del validador de comandos de mitigación (no requieren API keys)."""

from src.tools.validation import validate_solution


def test_comando_seguro_es_valido():
    resultado = validate_solution(["iptables -A INPUT -s 203.0.113.10 -j DROP"])
    assert resultado["valido"] is True


def test_comando_destructivo_es_rechazado():
    resultado = validate_solution(["rm -rf /"])
    assert resultado["valido"] is False
    assert any("PELIGROSO" in m for m in resultado["motivos"])


def test_binario_no_reconocido_se_reporta_pero_no_invalida(monkeypatch):
    # NOTA (fiel al notebook original): un binario fuera de la lista blanca
    # se agrega a `motivos`, pero `valido` solo se pone en False ante un
    # patrón PELIGROSO explícito (ver `_PELIGROSO` en src/tools/validation.py).
    # Es un comportamiento heredado del prototipo, no un error de la migración.
    # Desde NODEX final (M7) es el modo NO estricto; el estricto es el de omisión.
    import src.config as config
    monkeypatch.setattr(config, "VALIDACION_COMANDOS_ESTRICTA", False)
    resultado = validate_solution(["shutdown -h now"])
    assert resultado["valido"] is True
    assert any("binario no reconocido" in m for m in resultado["motivos"])


def test_en_modo_estricto_el_binario_no_reconocido_invalida():
    resultado = validate_solution(["frobnicate --now"])
    assert resultado["valido"] is False
    assert resultado["rechazados"][0]["motivos"] == ["BINARIO_NO_RECONOCIDO: 'frobnicate'"]
