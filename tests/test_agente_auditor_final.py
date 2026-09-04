"""Tests de `agente_auditor_final` -- en particular, que `hay_incidente` y
`hay_anomalia` (agregados 3-sep-2026, en dos rondas el mismo día) se lean
del LLM de forma independiente entre sí y de `confianza`, sin confundirse.
Mockea `llm_json`, no llama a la API real.

Motivación ronda 1 (hallazgo real, 3-sep-2026): antes de `hay_incidente`,
`src/tools/eval_deteccion.py` usaba `confianza >= CONFIDENCE_THRESHOLD`
como proxy de "hay un incidente", lo que clasificaba mal un "todo normal"
con confianza alta como "anómalo".

Motivación ronda 2 (mismo día): con `hay_incidente` ya en uso, BGL dio
recall 0.0 porque el auditor distinguía correctamente anomalías operativas
(p. ej. hardware) de incidentes de seguridad, pero BGL/HDFS etiquetan
cualquier anomalía de sistema, no solo las de seguridad. Se agregó
`hay_anomalia` para esa distinción. Ver `test_eval_deteccion.py` para el
test que verifica que la evaluación usa el campo correcto por dataset.
"""

import src.agents.agente_auditor_final as auditor_mod


def _estado_base():
    return {
        "diagnostico": "fuerza bruta SSH",
        "comandos_mitigacion": ["iptables -I INPUT -s 1.2.3.4 -j DROP"],
        "cves_encontrados": [],
        "contexto_rag": [],
    }


def test_confianza_alta_con_hay_incidente_false_no_se_confunden(monkeypatch):
    """El caso exacto que rompía la evaluación (ronda 1): un diagnóstico de
    'todo normal' bien fundamentado -- confianza alta, pero SIN incidente
    ni anomalía."""
    monkeypatch.setattr(
        auditor_mod, "llm_json",
        lambda *a, **k: {
            "confianza": 1.0,
            "hay_anomalia": False,
            "hay_incidente": False,
            "evaluacion": "Comportamiento normal del sistema, sin anomalías.",
        },
    )
    resultado = auditor_mod.agente_auditor_final(_estado_base())
    assert resultado["confianza"] == 1.0
    assert resultado["hay_anomalia"] is False
    assert resultado["hay_incidente"] is False


def test_hay_incidente_true_con_confianza_baja(monkeypatch):
    """El caso inverso: el auditor puede estar seguro de que SÍ hay un
    incidente, pero con menos confianza en el detalle del diagnóstico --
    ambos campos son independientes en cualquier dirección. Un incidente de
    seguridad real también es una anomalía."""
    monkeypatch.setattr(
        auditor_mod, "llm_json",
        lambda *a, **k: {
            "confianza": 0.6,
            "hay_anomalia": True,
            "hay_incidente": True,
            "evaluacion": "Hay evidencia de ataque pero el diagnóstico específico es incierto.",
        },
    )
    resultado = auditor_mod.agente_auditor_final(_estado_base())
    assert resultado["confianza"] == 0.6
    assert resultado["hay_anomalia"] is True
    assert resultado["hay_incidente"] is True


def test_hay_anomalia_true_con_hay_incidente_false_no_se_confunden(monkeypatch):
    """El caso exacto que rompía la evaluación (ronda 2, mismo día): una
    anomalía real de sistema (p. ej. hardware) que el auditor correctamente
    NO clasifica como incidente de seguridad -- ambos campos deben quedar
    en direcciones distintas, no colapsar al mismo valor."""
    monkeypatch.setattr(
        auditor_mod, "llm_json",
        lambda *a, **k: {
            "confianza": 0.9,
            "hay_anomalia": True,
            "hay_incidente": False,
            "evaluacion": (
                "Al tratarse de un problema de estabilidad y mantenimiento de "
                "hardware, no constituye un incidente de seguridad, aunque sí "
                "una anomalía operativa que requiere atención del equipo de "
                "infraestructura."
            ),
        },
    )
    resultado = auditor_mod.agente_auditor_final(_estado_base())
    assert resultado["hay_anomalia"] is True
    assert resultado["hay_incidente"] is False


def test_hay_incidente_ausente_usa_confianza_como_respaldo(monkeypatch):
    """Si el LLM no devuelve 'hay_incidente' (respuesta malformada o un
    modelo que no sigue el prompt), no debe reventar -- cae a un respaldo
    basado en confianza, igual que antes de que existiera el campo."""
    monkeypatch.setattr(
        auditor_mod, "llm_json",
        lambda *a, **k: {"confianza": 0.85, "hay_anomalia": True, "evaluacion": "sin el campo nuevo"},
    )
    resultado = auditor_mod.agente_auditor_final(_estado_base())
    assert resultado["hay_incidente"] is True  # 0.85 >= 0.70


def test_hay_incidente_tipo_invalido_usa_confianza_como_respaldo(monkeypatch):
    """Un valor no-booleano (p. ej. el LLM devuelve el string 'true') se
    trata igual que ausente -- no se confía en un tipo inesperado."""
    monkeypatch.setattr(
        auditor_mod, "llm_json",
        lambda *a, **k: {"confianza": 0.5, "hay_anomalia": True, "hay_incidente": "true", "evaluacion": "..."},
    )
    resultado = auditor_mod.agente_auditor_final(_estado_base())
    assert resultado["hay_incidente"] is False  # 0.5 < 0.70


def test_hay_anomalia_ausente_usa_hay_incidente_como_respaldo(monkeypatch):
    """Si 'hay_anomalia' viene ausente pero 'hay_incidente' sí vino y es
    True, el respaldo debe usar eso (todo incidente de seguridad es también
    una anomalía) antes de caer a confianza."""
    monkeypatch.setattr(
        auditor_mod, "llm_json",
        lambda *a, **k: {"confianza": 0.2, "hay_incidente": True, "evaluacion": "sin hay_anomalia"},
    )
    resultado = auditor_mod.agente_auditor_final(_estado_base())
    assert resultado["hay_anomalia"] is True  # hay_incidente=True lo implica, aunque confianza sea baja


def test_hay_anomalia_ausente_sin_incidente_usa_confianza_como_respaldo(monkeypatch):
    """Si 'hay_anomalia' viene ausente y 'hay_incidente' es False (o viene
    ausente también), el respaldo final cae a confianza."""
    monkeypatch.setattr(
        auditor_mod, "llm_json",
        lambda *a, **k: {"confianza": 0.9, "hay_incidente": False, "evaluacion": "sin hay_anomalia"},
    )
    resultado = auditor_mod.agente_auditor_final(_estado_base())
    assert resultado["hay_anomalia"] is True  # 0.9 >= 0.70


def test_evaluacion_auditor_se_persiste(monkeypatch):
    """Hallazgo real (3-sep-2026, tercera ronda): el texto de 'evaluacion'
    que devuelve el LLM se imprimía por consola pero nunca se guardaba en
    el estado -- así que una corrida real no dejaba registro de POR QUÉ el
    auditor clasificó cada lote como clasificó (necesario para justificar
    falsos positivos/negativos en el informe). Debe venir en el resultado
    bajo 'evaluacion_auditor'."""
    texto = (
        "El lote muestra eventos críticos e intentos fallidos, compatibles "
        "con una anomalía operativa (errores de bloques, fallos de "
        "replicación), no con actividad maliciosa."
    )
    monkeypatch.setattr(
        auditor_mod, "llm_json",
        lambda *a, **k: {
            "confianza": 0.8,
            "hay_anomalia": True,
            "hay_incidente": False,
            "evaluacion": texto,
        },
    )
    resultado = auditor_mod.agente_auditor_final(_estado_base())
    assert resultado["evaluacion_auditor"] == texto
