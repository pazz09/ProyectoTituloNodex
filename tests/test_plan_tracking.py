"""Tests de `src/graph/plan_tracking.py` -- lógica pura, sin LLM ni ChromaDB.

Verifica que el plan realmente gobierne la ejecución (no solo la
represente): cada paso termina en un estado terminal verificable, las
desviaciones quedan explícitas (nunca insertadas retroactivamente como si
siempre hubieran sido parte del plan), y `paso_actual` sigue al paso
LÓGICAMENTE activo -- no "el primer pendiente".
"""

from src.graph.plan_tracking import actualizar_plan


def _plan(*acciones, version=1):
    return {
        "plan_version": version,
        "objetivo": "...",
        "pasos": [
            {"id": i + 1, "accion": a, "objetivo": f"objetivo {a}", "estado": "pendiente"}
            for i, a in enumerate(acciones)
        ],
        "criterios_finalizacion": [],
    }


def _estado(plan, **extra):
    base = {"plan": plan, "paso_actual": plan["pasos"][0]["id"] if plan["pasos"] else None}
    base.update(extra)
    return base


# --- M: cada paso termina en un estado terminal verificable --------------

def test_triage_con_diagnostico_marca_el_paso_ejecutado():
    plan = _plan("triage", "mitigacion")
    delta = actualizar_plan(_estado(plan), "agente_analista_triage",
                             {"diagnostico": "fuerza bruta SSH", "necesita_rag": False})
    assert delta["plan"]["pasos"][0]["estado"] == "ejecutado"


def test_mitigacion_se_marca_fallido_cuando_se_agotan_los_reintentos(monkeypatch):
    import src.graph.plan_tracking as pt
    monkeypatch.setattr(pt, "MAX_INTENTOS_CORRECCION", 2)
    plan = _plan("triage", "mitigacion")
    estado = _estado(plan, intentos_correccion=2)  # ya se agotaron
    delta = actualizar_plan(estado, "tool_validar_comandos", {"comandos_validos": False, "motivos_rechazo": [["x"]]})
    assert delta["plan"]["pasos"][1]["estado"] == "fallido"
    assert delta["historial_ejecucion"][0]["estado"] == "fallido"


def test_mitigacion_sigue_pendiente_mientras_quedan_reintentos(monkeypatch):
    import src.graph.plan_tracking as pt
    monkeypatch.setattr(pt, "MAX_INTENTOS_CORRECCION", 2)
    plan = _plan("triage", "mitigacion")
    estado = _estado(plan, intentos_correccion=1)  # queda 1 reintento
    delta = actualizar_plan(estado, "tool_validar_comandos", {"comandos_validos": False, "motivos_rechazo": [["x"]]})
    assert delta["plan"]["pasos"][1]["estado"] == "pendiente"


def test_mitigacion_ejecutado_cuando_valida():
    plan = _plan("triage", "mitigacion")
    delta = actualizar_plan(_estado(plan), "tool_validar_comandos", {"comandos_validos": True, "motivos_rechazo": []})
    assert delta["plan"]["pasos"][1]["estado"] == "ejecutado"


# --- N/O: rag se omite u ejecuta según la decisión real del triage -------

def test_rag_se_omite_cuando_el_triage_decide_que_no_hace_falta():
    plan = _plan("triage", "rag", "mitigacion")
    delta = actualizar_plan(_estado(plan), "agente_analista_triage",
                             {"diagnostico": "todo normal", "necesita_rag": False})
    paso_rag = next(p for p in delta["plan"]["pasos"] if p["accion"] == "rag")
    assert paso_rag["estado"] == "omitido"
    assert "motivo" in paso_rag


def test_rag_se_ejecuta_y_marca_cuando_el_tool_corre():
    plan = _plan("triage", "rag", "mitigacion")
    plan["pasos"][0]["estado"] = "pendiente"  # triage aún no resuelto (pidió RAG)
    delta = actualizar_plan(_estado(plan), "tool_consultar_rag",
                             {"contexto_rag": [{"texto": "x"}], "tecnicas_mitre": []})
    paso_rag = next(p for p in delta["plan"]["pasos"] if p["accion"] == "rag")
    assert paso_rag["estado"] == "ejecutado"


# --- Desviaciones: nunca se insertan retroactivamente en plan["pasos"] ---

def test_rag_ejecutado_sin_estar_planificado_es_una_desviacion_explicita():
    plan = _plan("triage", "mitigacion")  # sin "rag"
    delta = actualizar_plan(_estado(plan), "tool_consultar_rag", {"contexto_rag": [], "tecnicas_mitre": []})
    acciones_en_plan = [p["accion"] for p in delta["plan"]["pasos"]]
    assert "rag" not in acciones_en_plan  # no se insertó retroactivamente
    assert len(delta["desviaciones_plan"]) == 1
    assert delta["desviaciones_plan"][0]["accion"] == "rag"
    assert delta["desviaciones_plan"][0]["motivo"]


def test_cve_ejecutado_sin_estar_planificado_es_una_desviacion_explicita():
    plan = _plan("triage", "mitigacion")  # sin "cve"
    delta = actualizar_plan(_estado(plan), "tool_consultar_cve", {"cves_encontrados": []})
    assert len(delta["desviaciones_plan"]) == 1
    assert delta["desviaciones_plan"][0]["accion"] == "cve"


def test_selector_omite_cve_planificado_con_motivo_real():
    plan = _plan("triage", "cve", "mitigacion")
    delta = actualizar_plan(_estado(plan), "agente_selector_herramientas",
                             {"usar_cve": False, "razon_seleccion": "no se identifica un servicio buscable"})
    paso_cve = next(p for p in delta["plan"]["pasos"] if p["accion"] == "cve")
    assert paso_cve["estado"] == "omitido"
    assert paso_cve["motivo"] == "no se identifica un servicio buscable"


# --- P: paso_actual sigue al nodo LÓGICO activo, no "el primer pendiente" ---

def test_paso_actual_apunta_a_rag_mientras_rag_corre_no_a_triage():
    """Triage -> RAG -> Triage: mientras tool_consultar_rag corre,
    paso_actual debe apuntar a "rag" (lo que se está ejecutando AHORA),
    aunque "triage" siga pendiente (no se resolvió en la primera pasada)."""
    plan = _plan("triage", "rag", "mitigacion")
    # 1) primera pasada de triage: pide RAG, no resuelve su propio paso
    estado = _estado(plan)
    delta1 = actualizar_plan(estado, "agente_analista_triage", {"necesita_rag": True})
    assert delta1["plan"]["pasos"][0]["estado"] == "pendiente"  # triage sin resolver
    paso_triage_id = delta1["plan"]["pasos"][0]["id"]
    assert delta1["paso_actual"] == paso_triage_id  # apunta a triage mientras triage corrió

    # 2) tool_consultar_rag corre: paso_actual debe moverse a "rag"
    estado2 = {"plan": delta1["plan"], "paso_actual": delta1["paso_actual"]}
    delta2 = actualizar_plan(estado2, "tool_consultar_rag", {"contexto_rag": [], "tecnicas_mitre": []})
    paso_rag_id = next(p for p in delta2["plan"]["pasos"] if p["accion"] == "rag")["id"]
    assert delta2["paso_actual"] == paso_rag_id
    assert delta2["paso_actual"] != paso_triage_id

    # 3) segunda pasada de triage (con diagnóstico): paso_actual vuelve a triage
    estado3 = {"plan": delta2["plan"], "paso_actual": delta2["paso_actual"]}
    delta3 = actualizar_plan(estado3, "agente_analista_triage",
                              {"diagnostico": "fuerza bruta SSH", "necesita_rag": False})
    assert delta3["paso_actual"] == paso_triage_id


def test_paso_actual_no_se_mueve_en_mecanismos_internos():
    plan = _plan("triage", "cve", "mitigacion")
    plan["pasos"][0]["estado"] = "ejecutado"
    estado = _estado(plan)
    estado["paso_actual"] = plan["pasos"][0]["id"]
    delta = actualizar_plan(estado, "agente_selector_herramientas", {"usar_cve": True, "razon_seleccion": "..."})
    assert delta["paso_actual"] == plan["pasos"][0]["id"]  # sigue en triage, selector no lo mueve
