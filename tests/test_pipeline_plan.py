"""Test de integración end-to-end de `analizar_lote_stream()` con el grafo
Plan-and-Execute completo (11-sep-2026). No existía un test que corriera el
grafo compilado de punta a punta (`app.stream()`) -- los tests anteriores
llaman a cada nodo por separado (ver `test_ciclo_correccion.py`). Este
mockea las 5 llamadas LLM (una por agente) según el contenido del
`system prompt`, y verifica que Plan-and-Execute no rompa el streaming: el
plan se genera, se ejecuta, y el reporte final trae los campos nuevos.

Sin cuota real: `llm_json` mockeado en los 5 módulos de agentes. La
reputación de IPs y ChromaDB corren de verdad (son deterministas/locales,
sin credenciales -- ver README "Modelo LLM en la práctica").
"""

import src.agents.agente_analista_triage as triage_mod
import src.agents.agente_auditor_final as auditor_mod
import src.agents.agente_ingeniero_mitigacion as mitigacion_mod
import src.agents.agente_planificador as planificador_mod
import src.agents.agente_selector_herramientas as selector_mod
from src.config import MAX_REPLANS
from src.pipeline import analizar_lote_stream

LOGS = "\n".join([
    "Jan 10 13:55:36 srv sshd[1]: Failed password for invalid user admin "
    "from 203.0.113.10 port 22 ssh2",
    "Jan 10 13:55:39 srv sshd[2]: Failed password for root from 203.0.113.10 port 22 ssh2",
])


def _fake_llm(user_content, system=None, retries=1):
    system = system or ""
    if "planificador" in system:
        return {
            "objetivo": "Determinar si hay un ataque de fuerza bruta SSH.",
            "pasos": [
                {"id": 1, "accion": "triage", "objetivo": "diagnosticar", "estado": "pendiente"},
                {"id": 2, "accion": "mitigacion", "objetivo": "contener", "estado": "pendiente"},
            ],
            "criterios_finalizacion": ["diagnóstico con evidencia suficiente"],
        }
    if "decide si puedes diagnosticar directamente" in system:
        # primera pasada del triage: NO pide RAG, diagnostica directo
        return {"necesita_rag": False, "diagnostico": "fuerza bruta SSH contra el usuario root",
                "razon": "evidencia suficiente en el resumen"}
    if "coordinador de análisis de seguridad" in system:
        return {"usar_cve": False, "razon": "no se identifica un producto buscable"}
    if "ingeniero de sistemas Linux" in system:
        return {"comandos": ["iptables -I INPUT -s 203.0.113.10 -j DROP"]}
    if "Evalúa la solución de seguridad" in system:
        return {"confianza": 0.9, "hay_anomalia": True, "hay_incidente": True,
                "evaluacion": "Fuerza bruta SSH confirmada, mitigación aplicada.",
                "cobertura_auditor": True}
    raise AssertionError(f"system prompt inesperado: {system[:80]!r}")


def test_analizar_lote_stream_corre_de_punta_a_punta_con_plan_and_execute(monkeypatch):
    for mod in (planificador_mod, triage_mod, selector_mod, mitigacion_mod, auditor_mod):
        monkeypatch.setattr(mod, "llm_json", _fake_llm)

    eventos = list(analizar_lote_stream(LOGS, thread_id="test_plan_and_execute"))

    tipos = [e["tipo"] for e in eventos]
    assert tipos[0] == "inicio"
    assert tipos[-1] == "final"
    assert "error" not in tipos

    nombres_nodo = [e["nombre"] for e in eventos if e["tipo"] == "nodo"]
    assert nombres_nodo[0] == "agente_planificador"
    assert "agente_analista_triage" in nombres_nodo
    assert "agente_auditor_final" in nombres_nodo
    # router_selector debió mandar directo a mitigación (usar_cve=False):
    assert "tool_consultar_cve" not in nombres_nodo

    reporte = eventos[-1]["reporte"]
    assert reporte["diagnostico"] == "fuerza bruta SSH contra el usuario root"
    assert reporte["confianza"] == 0.9
    assert reporte["cobertura_suficiente"] is True
    assert reporte["replan_count"] == 0
    plan = reporte["plan"]
    assert [p["accion"] for p in plan["pasos"]] == ["triage", "mitigacion"]
    assert all(p["estado"] == "ejecutado" for p in plan["pasos"])
    assert len(reporte["historial_ejecucion"]) == len(nombres_nodo)


# --- F/G/H: replanificación real, acotada por MAX_REPLANS, con trazabilidad ---

def test_replanificacion_se_dispara_y_respeta_max_replans(monkeypatch):
    """El auditor siempre dice cobertura_auditor=False -- si el tope no
    frenara el ciclo, esto correría para siempre. Verifica que se detiene
    exactamente en MAX_REPLANS y que cada replan queda archivado."""
    llamadas_auditor = {"n": 0}

    def _fake_llm(user_content, system=None, retries=1):
        system = system or ""
        if "planificador" in system:
            return {
                "objetivo": "Determinar si hay un ataque de fuerza bruta SSH.",
                "pasos": [
                    {"id": 1, "accion": "triage", "objetivo": "diagnosticar", "estado": "pendiente"},
                    {"id": 2, "accion": "mitigacion", "objetivo": "contener", "estado": "pendiente"},
                ],
                "criterios_finalizacion": [],
            }
        if "decide si puedes diagnosticar directamente" in system:
            return {"necesita_rag": False, "diagnostico": "actividad sospechosa sin confirmar",
                    "razon": "evidencia parcial"}
        if "coordinador de análisis de seguridad" in system:
            return {"usar_cve": False, "razon": "no se identifica un producto buscable"}
        if "ingeniero de sistemas Linux" in system:
            return {"comandos": ["iptables -I INPUT -s 203.0.113.10 -j DROP"]}
        if "Evalúa la solución de seguridad" in system:
            llamadas_auditor["n"] += 1
            return {"confianza": 0.5, "hay_anomalia": True, "hay_incidente": False,
                    "evaluacion": "cobertura insuficiente", "cobertura_auditor": False,
                    "motivo_cobertura": "falta confirmar con más contexto"}
        raise AssertionError(f"system prompt inesperado: {system[:80]!r}")

    for mod in (planificador_mod, triage_mod, selector_mod, mitigacion_mod, auditor_mod):
        monkeypatch.setattr(mod, "llm_json", _fake_llm)

    eventos = list(analizar_lote_stream(LOGS, thread_id="test_replan_cap"))
    assert "error" not in [e["tipo"] for e in eventos]

    reporte = eventos[-1]["reporte"]
    assert reporte["replan_count"] == MAX_REPLANS
    assert llamadas_auditor["n"] == MAX_REPLANS + 1  # un auditor por ciclo (inicial + cada replan)
    assert len(reporte["historial_planes"]) == MAX_REPLANS  # una entrada archivada por replan
    assert reporte["historial_planes"][0]["version"] == 1
    assert "falta confirmar" in reporte["historial_planes"][0]["motivo_reemplazo"]
    # el plan vigente al final es el de la ÚLTIMA versión, no el primero
    assert reporte["plan"]["plan_version"] == MAX_REPLANS + 1
