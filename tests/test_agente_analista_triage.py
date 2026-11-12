"""Tests de `agente_analista_triage` -- en particular, el fix del 11-sep-2026
(Plan-and-Execute, punto 7): antes, la primera pasada fijaba
`necesita_rag=True` de forma incondicional, sin llamar al LLM, así que RAG
se consultaba SIEMPRE sin importar si el lote lo justificaba. Ahora es una
decisión real del LLM, informada por si el plan incluyó un paso "rag".
Mockea `llm_json`, no llama a la API real.
"""

import src.agents.agente_analista_triage as triage_mod


def _estado_base(**extra):
    base = {
        "resumen_logs": {"formato_detectado": "auth_log", "total_lineas": 5, "servicios": {}},
        "contexto_rag": [],
        "necesita_rag": None,
    }
    base.update(extra)
    return base


def test_primera_pasada_no_pide_rag_si_el_llm_decide_que_no_hace_falta(monkeypatch):
    monkeypatch.setattr(
        triage_mod, "llm_json",
        lambda *a, **k: {"necesita_rag": False, "diagnostico": "todo normal", "razon": "evidencia suficiente"},
    )
    resultado = triage_mod.agente_analista_triage(_estado_base())
    assert resultado["necesita_rag"] is False
    assert resultado["diagnostico"] == "todo normal"


def test_primera_pasada_pide_rag_cuando_el_llm_lo_justifica(monkeypatch):
    monkeypatch.setattr(
        triage_mod, "llm_json",
        lambda *a, **k: {"necesita_rag": True, "diagnostico": "", "razon": "hace falta precedente"},
    )
    resultado = triage_mod.agente_analista_triage(_estado_base())
    assert resultado["necesita_rag"] is True
    assert "diagnostico" not in resultado  # no se fabrica un diagnóstico a medias


def test_primera_pasada_llama_al_llm_una_sola_vez_no_hardcodea_true(monkeypatch):
    """Regresión directa del bug: antes esta rama no llamaba al LLM en
    absoluto. Verificamos que efectivamente lo hace."""
    llamadas = []
    monkeypatch.setattr(
        triage_mod, "llm_json",
        lambda *a, **k: (llamadas.append(1), {"necesita_rag": False, "diagnostico": "ok", "razon": "..."})[1],
    )
    triage_mod.agente_analista_triage(_estado_base())
    assert len(llamadas) == 1


def test_primera_pasada_incluye_lo_que_dice_el_plan_sobre_rag(monkeypatch):
    capturado = {}

    def _fake_llm(user_content, system=None, **k):
        capturado["user_content"] = user_content
        return {"necesita_rag": False, "diagnostico": "ok", "razon": "..."}

    monkeypatch.setattr(triage_mod, "llm_json", _fake_llm)
    plan = {"objetivo": "Investigar posible fuerza bruta.",
            "pasos": [{"id": 2, "accion": "rag", "objetivo": "buscar precedentes de este host", "estado": "pendiente"}]}
    triage_mod.agente_analista_triage(_estado_base(plan=plan, plan_objetivo=plan["objetivo"]))
    assert "buscar precedentes de este host" in capturado["user_content"]
    assert plan["objetivo"] in capturado["user_content"]


def test_segunda_pasada_con_contexto_sigue_diagnosticando_como_antes(monkeypatch):
    """No debe romperse el camino existente: con contexto_rag ya poblado,
    diagnostica directamente (rama sin cambios de lógica)."""
    monkeypatch.setattr(triage_mod, "llm_json", lambda *a, **k: {"diagnostico": "fuerza bruta SSH"})
    resultado = triage_mod.agente_analista_triage(
        _estado_base(contexto_rag=[{"texto": "caso previo"}], necesita_rag=True))
    assert resultado["diagnostico"] == "fuerza bruta SSH"
    assert resultado["necesita_rag"] is False


import pytest  # noqa: E402

# NODEX final, Fase B: estas pruebas verifican el flujo de la Fase A (sigue disponible con los
# interruptores de la Fase B apagados). El flujo nuevo lo cubre tests/test_nodex_final_fase_b.py.
pytestmark = pytest.mark.usefixtures("modo_fase_a")
