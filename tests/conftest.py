"""Fixtures compartidos de la suite.

`modo_fase_a` (NODEX final, Fase B): apaga los interruptores de la Fase B para
las pruebas que verifican el flujo de la Fase A (triage <-> RAG, grafo de 8
nodos, contrato D-11 sin categorías). Ese flujo sigue disponible con los
interruptores apagados, así que sus pruebas siguen protegiéndolo; el
comportamiento nuevo lo cubren `tests/test_nodex_final_fase_b.py`. También
descarta el grafo cacheado del pipeline para que se reconstruya con los
interruptores vigentes.
"""

import pytest

INTERRUPTORES_FASE_B = ("RAG_POR_HIPOTESIS", "CORRECCION_AUDITOR", "HISTORICO_ACTIVO",
                        "EVENTOS_POR_CATEGORIA", "AUDITOR_REFORZADO")


@pytest.fixture
def modo_fase_a(monkeypatch):
    import src.config as config
    import src.pipeline as pipeline
    for nombre in INTERRUPTORES_FASE_B:
        monkeypatch.setattr(config, nombre, False)
    monkeypatch.setattr(pipeline, "_app", None)
    yield
