"""Tests de `agente_planificador` (Plan-and-Execute, 11-sep-2026).

Mockea `llm_json`, no llama a la API real. Cubre: generación de un plan
válido, respeto de MAX_PLAN_STEPS, vocabulario cerrado, manejo explícito de
fallos, aislamiento de ground truth en el prompt, y que el modo
replanificación reciba la ejecución anterior completa (plan_anterior,
historial, diagnóstico, evaluación) en vez de repetir la misma entrada.
"""

import pytest

import src.agents.agente_planificador as planificador_mod
from src.agents.agente_planificador import (
    PlanInvalidoError,
    _construir_prompt,
    _validar_y_normalizar,
    agente_planificador,
    preparar_replanificacion,
)


def _estado_base(**extra):
    base = {
        "resumen_logs": {
            "formato_detectado": "auth_log",
            "total_lineas": 30,
            "servicios": {"sshd": 30},
            "eventos": {"acceso_fallido": 28, "acceso_exitoso": 2},
            "n_ips_distintas": 1,
        },
        "preprocessing_metadata": {},
        "parsing_warnings": [],
    }
    base.update(extra)
    return base


def _plan_llm(pasos=("triage", "rag", "cve", "mitigacion")):
    return {
        "objetivo": "Determinar si hay un ataque de fuerza bruta.",
        "pasos": [
            {"id": i + 1, "accion": a, "objetivo": f"objetivo de {a}", "estado": "pendiente"}
            for i, a in enumerate(pasos)
        ],
        "criterios_finalizacion": ["diagnóstico con evidencia suficiente"],
    }


# --- A: genera un plan válido -----------------------------------------

def test_genera_un_plan_valido(monkeypatch):
    monkeypatch.setattr(planificador_mod, "llm_json", lambda *a, **k: _plan_llm())
    resultado = agente_planificador(_estado_base())
    plan = resultado["plan"]
    assert plan["plan_version"] == 1
    assert [p["accion"] for p in plan["pasos"]] == ["triage", "rag", "cve", "mitigacion"]
    assert all(p["estado"] == "pendiente" for p in plan["pasos"])
    assert resultado["plan_objetivo"] == plan["objetivo"]
    assert resultado["paso_actual"] == plan["pasos"][0]["id"]
    assert resultado["historial_ejecucion"][0]["nodo"] == "agente_planificador"


def test_plan_mas_corto_es_valido_sin_pasos_opcionales(monkeypatch):
    """No se obliga a incluir rag/cve -- un plan sin ellos es válido."""
    monkeypatch.setattr(planificador_mod, "llm_json", lambda *a, **k: _plan_llm(pasos=("triage", "mitigacion")))
    resultado = agente_planificador(_estado_base())
    assert [p["accion"] for p in resultado["plan"]["pasos"]] == ["triage", "mitigacion"]


def test_acciones_obligatorias_se_inyectan_si_el_llm_las_omite(monkeypatch):
    monkeypatch.setattr(planificador_mod, "llm_json", lambda *a, **k: _plan_llm(pasos=("rag",)))
    resultado = agente_planificador(_estado_base())
    acciones = [p["accion"] for p in resultado["plan"]["pasos"]]
    assert "triage" in acciones and "mitigacion" in acciones


# --- B: respeta MAX_PLAN_STEPS ------------------------------------------

def test_plan_respeta_max_plan_steps(monkeypatch):
    monkeypatch.setattr(planificador_mod, "MAX_PLAN_STEPS", 3)
    monkeypatch.setattr(planificador_mod, "llm_json", lambda *a, **k: _plan_llm())  # 4 acciones
    resultado = agente_planificador(_estado_base())
    pasos = resultado["plan"]["pasos"]
    assert len(pasos) == 3
    # se descartan las opcionales primero (cve antes que rag), nunca las obligatorias
    acciones = {p["accion"] for p in pasos}
    assert {"triage", "mitigacion"} <= acciones
    assert "cve" not in acciones


# --- S: vocabulario cerrado ----------------------------------------------

def test_accion_fuera_del_vocabulario_se_descarta(monkeypatch, capsys):
    plan = _plan_llm(pasos=("triage", "mitigacion"))
    plan["pasos"].append({"id": 99, "accion": "exfiltrar_datos", "objetivo": "inventado", "estado": "pendiente"})
    monkeypatch.setattr(planificador_mod, "llm_json", lambda *a, **k: plan)
    resultado = agente_planificador(_estado_base())
    acciones = [p["accion"] for p in resultado["plan"]["pasos"]]
    assert "exfiltrar_datos" not in acciones
    assert "fuera del vocabulario cerrado" in capsys.readouterr().out


def test_validar_y_normalizar_deduplica_acciones_repetidas():
    plan = _plan_llm(pasos=("triage", "triage", "mitigacion"))
    normalizado = _validar_y_normalizar(plan, plan_version=1)
    assert [p["accion"] for p in normalizado["pasos"]].count("triage") == 1


# --- K: fallo del Planificador se maneja explícitamente ------------------

def test_json_invalido_lanza_planinvalidoerror_no_plan_vacio_silencioso(monkeypatch):
    monkeypatch.setattr(planificador_mod, "llm_json",
                         lambda *a, **k: {"error": "json_invalido", "raw": "no es json"})
    with pytest.raises(PlanInvalidoError):
        agente_planificador(_estado_base())


def test_plan_solo_con_acciones_invalidas_igual_produce_las_obligatorias(monkeypatch):
    """'inventada' se descarta por vocabulario cerrado, pero triage/
    mitigacion se inyectan igual -- el plan resultante SÍ es válido, no
    lanza. Documenta la garantía: siempre hay un plan ejecutable, nunca uno
    vacío por culpa de que el LLM solo propuso acciones inválidas."""
    monkeypatch.setattr(planificador_mod, "llm_json",
                         lambda *a, **k: {"objetivo": "...", "pasos": [{"accion": "inventada"}]})
    resultado = agente_planificador(_estado_base())
    assert {p["accion"] for p in resultado["plan"]["pasos"]} == {"triage", "mitigacion"}


def test_pasos_no_es_una_lista_lanza_planinvalidoerror(monkeypatch):
    monkeypatch.setattr(planificador_mod, "llm_json",
                         lambda *a, **k: {"objetivo": "...", "pasos": "no es una lista"})
    with pytest.raises(PlanInvalidoError):
        agente_planificador(_estado_base())


def test_plan_no_es_un_diccionario_lanza_planinvalidoerror(monkeypatch):
    monkeypatch.setattr(planificador_mod, "llm_json", lambda *a, **k: ["no", "es", "un", "dict"])
    with pytest.raises(PlanInvalidoError):
        agente_planificador(_estado_base())


# --- I: ground truth nunca aparece en el input del Planificador ----------

def test_prompt_nunca_incluye_ground_truth():
    """Construye el prompt (sin llamar al LLM) sobre un resumen que --si se
    filtrara-- contendría la fuga de la Fase 7: en BGL la etiqueta de
    anomalía del dataset es el primer token de la línea, y `cronologia`
    reproduce texto crudo. Igual que `resumen_prompt.py` hace para el
    Triage, estos campos no deben llegar al texto del prompt."""
    estado = _estado_base(resumen_logs={
        "formato_detectado": "bgl",
        "total_lineas": 10,
        "servicios": {"bgl.kernel": 10},
        "eventos": {"evento_critico": 3},
        "n_ips_distintas": 0,
        # Campos de presentación que NUNCA deben llegar al prompt del LLM
        # (mismo criterio que src/tools/resumen_prompt.py):
        "cronologia": [{"linea_cruda": "APPSEVERE 2005-06-03-15.42.50 R02-M1-N0 RAS KERNEL FATAL"}],
        "entidades": ["APPSEVERE"],
    })
    sys_instruction, user_content = _construir_prompt(estado)
    texto = sys_instruction + user_content
    assert "APPSEVERE" not in texto
    assert "linea_cruda" not in texto
    assert "cronologia" not in texto.lower()


# --- D: el Triage recibe un plan ya existente (verificado del lado del plan) ---

def test_plan_objetivo_queda_disponible_para_el_triage(monkeypatch):
    monkeypatch.setattr(planificador_mod, "llm_json", lambda *a, **k: _plan_llm())
    resultado = agente_planificador(_estado_base())
    assert resultado["plan_objetivo"]  # no vacío -- agente_analista_triage.py lo consume


# --- U: el prompt de replanificación incluye la ejecución anterior -------

def test_prompt_de_replan_incluye_plan_anterior_e_historial():
    plan_anterior = _plan_llm()
    plan_anterior["plan_version"] = 1
    estado = _estado_base(
        plan=plan_anterior,
        historial_ejecucion=[{"nodo": "agente_analista_triage", "estado": "ejecutado"}],
        diagnostico="fuerza bruta SSH sin confirmar",
        contexto_rag=[{"texto": "caso previo similar"}],
        cves_encontrados=[{"id": "CVE-2024-0001"}],
        comandos_validos=False,
        motivos_rechazo=[["comando peligroso"]],
        evaluacion_auditor="cobertura insuficiente: falta contexto histórico",
        motivo_replanificacion="pasos fallidos: ['mitigacion']",
    )
    _, user_content = _construir_prompt(estado)
    assert "PLAN ANTERIOR" in user_content
    assert "fuerza bruta SSH sin confirmar" in user_content
    assert "caso previo similar" in user_content
    assert "CVE-2024-0001" in user_content
    assert "cobertura insuficiente" in user_content
    assert "pasos fallidos" in user_content


def test_replan_incrementa_version_y_replan_count_y_archiva_el_plan_anterior(monkeypatch):
    monkeypatch.setattr(planificador_mod, "llm_json", lambda *a, **k: _plan_llm(pasos=("triage", "mitigacion")))
    plan_anterior = _plan_llm()
    plan_anterior["plan_version"] = 1
    plan_anterior["pasos"][3]["estado"] = "fallido"  # mitigacion falló
    estado = _estado_base(
        plan=plan_anterior, replan_count=0,
        diagnostico="diagnóstico del ciclo anterior",
        evaluacion_auditor="evaluación del ciclo anterior",
        motivo_replanificacion="pasos fallidos: ['mitigacion']",
    )
    resultado = agente_planificador(estado)
    assert resultado["plan"]["plan_version"] == 2
    assert resultado["replan_count"] == 1
    assert len(resultado["historial_planes"]) == 1
    archivo = resultado["historial_planes"][0]
    assert archivo["version"] == 1
    assert archivo["resultados_asociados"]["diagnostico"] == "diagnóstico del ciclo anterior"
    assert archivo["resultados_asociados"]["n_pasos_fallidos"] == 1


# --- Q: preparar_replanificacion resetea sin defaults optimistas ---------

def test_preparar_replanificacion_resetea_sin_defaults_optimistas():
    estado = _estado_base(comandos_validos=True, cobertura_auditor=True, cobertura_suficiente=True)
    reset = preparar_replanificacion(estado)
    assert reset["comandos_validos"] is None
    assert reset["cobertura_auditor"] is None
    assert reset["cobertura_suficiente"] is None
    assert reset["diagnostico"] == ""
    assert reset["evaluacion_auditor"] == ""
    assert reset["intentos_correccion"] == 0
    assert reset["requiere_replanificacion"] is False


def test_preparar_replanificacion_no_toca_la_evidencia_conservada():
    reset = preparar_replanificacion(_estado_base())
    for clave in ("contexto_rag", "tecnicas_mitre", "cves_encontrados",
                  "historial_ejecucion", "historial_planes", "desviaciones_plan"):
        assert clave not in reset
