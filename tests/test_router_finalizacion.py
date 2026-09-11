"""Tests de `router_finalizacion` -- el router del ciclo Plan-and-Execute.

Puramente determinístico (no llama al LLM): verifica que la decisión de
replanificar combine la señal del Auditor con una verificación propia
sobre `state["plan"]`, que el tope MAX_REPLANS corte el ciclo sin
excepción (no hay loop infinito), y que un plan cumplido sin pasos
fallidos/pendientes termine en END.
"""

from langgraph.graph import END

from src.config import MAX_REPLANS
from src.graph.routers import router_finalizacion


def _plan(*estados):
    return {"plan_version": 1, "pasos": [
        {"id": i + 1, "accion": "x", "estado": e} for i, e in enumerate(estados)
    ]}


def test_termina_en_end_con_plan_cumplido_y_cobertura_suficiente():
    estado = {"replan_count": 0, "plan": _plan("ejecutado", "ejecutado"), "cobertura_suficiente": True}
    assert router_finalizacion(estado) == END


def test_replanifica_si_cobertura_suficiente_es_false():
    estado = {"replan_count": 0, "plan": _plan("ejecutado", "ejecutado"), "cobertura_suficiente": False}
    assert router_finalizacion(estado) == "agente_planificador"


# --- R: el router NO depende únicamente del booleano del LLM -------------

def test_replanifica_ante_paso_fallido_aunque_cobertura_suficiente_sea_true():
    """Caso central del punto 8: aunque el Auditor (LLM) diga que la
    cobertura alcanza, un paso "fallido" real en el plan fuerza la
    replanificación -- verificación determinística independiente."""
    estado = {"replan_count": 0, "plan": _plan("ejecutado", "fallido"), "cobertura_suficiente": True}
    assert router_finalizacion(estado) == "agente_planificador"


def test_replanifica_ante_paso_pendiente_aunque_cobertura_suficiente_sea_true():
    estado = {"replan_count": 0, "plan": _plan("ejecutado", "pendiente"), "cobertura_suficiente": True}
    assert router_finalizacion(estado) == "agente_planificador"


# --- F/H: tope MAX_REPLANS, sin excepción -- no hay loop infinito --------

def test_no_replanifica_mas_alla_de_max_replans_aunque_todo_indique_que_deberia():
    estado = {
        "replan_count": MAX_REPLANS,
        "plan": _plan("fallido", "pendiente"),  # ambas señales dirían "replanificar"
        "cobertura_suficiente": False,
    }
    assert router_finalizacion(estado) == END


def test_tope_se_evalua_primero_sin_importar_el_resto_del_estado():
    estado = {"replan_count": MAX_REPLANS + 5, "plan": {}, "cobertura_suficiente": False}
    assert router_finalizacion(estado) == END
