"""Tests del ciclo de corrección de comandos (agente_ingeniero_mitigacion <-> tool_validar_comandos).

Este ciclo nunca se había ejercitado: en las tres corridas end-to-end reales
hasta el 23-ago-2026, los comandos pasaron la validación al primer intento.
En vez de depender de que un LLM real "decida" proponer un comando peligroso
-- no determinista, y además gastaría cuota del tier gratuito (ver README,
"Modelo LLM en la práctica") -- estos tests mockean `llm_json` dentro de
`agente_ingeniero_mitigacion` para forzar los dos caminos del router
`router_validacion` de forma determinista y sin llamar a la API real.

Simulan manualmente lo que LangGraph hace automáticamente al mezclar el
`dict` que devuelve cada nodo en el estado (incluyendo el reducer de
`motivos_rechazo` definido en `src/state.py`), porque acá se llama a los
nodos directamente en vez de correr el grafo compilado.
"""

import src.agents.agente_ingeniero_mitigacion as mitigacion_mod
from src.config import MAX_INTENTOS_CORRECCION
from src.graph.routers import router_validacion
from src.state import limpiar_o_acumular
from src.tools.tool_validar_comandos import tool_validar_comandos


def _estado_inicial():
    return {
        "diagnostico": "fuerza bruta SSH",
        "cves_encontrados": [],
        "contexto_rag": [],
        "comandos_mitigacion": [],
        "comandos_validos": True,
        "motivos_rechazo": [],
        "intentos_correccion": 0,
    }


def _aplicar_validacion(state: dict) -> dict:
    """Corre tool_validar_comandos y mezcla el resultado en `state` aplicando
    el mismo reducer que usa LogGuardState para motivos_rechazo."""
    delta = tool_validar_comandos(state)
    state["motivos_rechazo"] = limpiar_o_acumular(state["motivos_rechazo"], delta["motivos_rechazo"])
    state["comandos_validos"] = delta["comandos_validos"]
    return state


def test_correccion_exitosa_en_segundo_intento(monkeypatch):
    respuestas = iter([
        {"comandos": ["rm -rf / --no-preserve-root"]},               # intento 1: peligroso, rechazado
        {"comandos": ["iptables -I INPUT -s 1.2.3.4 -j DROP"]},        # intento 2: válido
    ])
    monkeypatch.setattr(mitigacion_mod, "llm_json", lambda *a, **k: next(respuestas))

    state = _estado_inicial()

    state.update(mitigacion_mod.agente_ingeniero_mitigacion(state))
    assert state["intentos_correccion"] == 1
    _aplicar_validacion(state)
    assert state["comandos_validos"] is False
    assert any("PELIGROSO" in m for grupo in state["motivos_rechazo"] for m in grupo)
    assert router_validacion(state) == "agente_ingeniero_mitigacion"

    state.update(mitigacion_mod.agente_ingeniero_mitigacion(state))
    assert state["intentos_correccion"] == 2
    _aplicar_validacion(state)
    assert state["comandos_validos"] is True
    assert state["motivos_rechazo"] == []  # el reducer resetea la lista tras un éxito
    assert router_validacion(state) == "agente_auditor_final"


def test_agota_intentos_y_escala_con_comandos_invalidos(monkeypatch):
    monkeypatch.setattr(
        mitigacion_mod, "llm_json",
        lambda *a, **k: {"comandos": ["rm -rf / --no-preserve-root"]},  # siempre peligroso
    )

    state = _estado_inicial()
    llamadas_mitigacion = 0
    ruta = None
    for _ in range(MAX_INTENTOS_CORRECCION + 5):  # cota de seguridad del test, no del sistema
        state.update(mitigacion_mod.agente_ingeniero_mitigacion(state))
        llamadas_mitigacion += 1
        _aplicar_validacion(state)
        ruta = router_validacion(state)
        if ruta == "agente_auditor_final":
            break

    assert ruta == "agente_auditor_final"
    assert llamadas_mitigacion == MAX_INTENTOS_CORRECCION  # el cap frena el loop, no un límite externo
    assert state["intentos_correccion"] == MAX_INTENTOS_CORRECCION
    assert state["comandos_validos"] is False  # escala honestamente, sin ocultar que no se corrigió
