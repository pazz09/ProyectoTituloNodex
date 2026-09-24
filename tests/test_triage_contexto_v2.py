"""Fase 2 del cierre de auditoría (23-sep-2026, hallazgo A2): el contexto de
preprocesamiento (`contexto_preprocesamiento`) llega también a la PRIMERA
pasada del triage, no solo a la segunda. Estos tests verifican, con datos
reales (no sintéticos) donde corresponde:

1. El prompt de la primera pasada contiene el contexto v2 acotado.
2. No supera el presupuesto de caracteres definido, con un lote grande de
   verdad (HDFS_2k, 202 IPs -- el caso que en su momento disparó 58 289
   tokens, ver src/tools/resumen_prompt.py).
3. Ninguno de los dos prompts de triage filtra las etiquetas del dataset
   (BGL, que las trae embebidas como primer token de la línea).
"""

import json
from pathlib import Path

import src.agents.agente_analista_triage as triage_mod
import src.pipeline as pipeline_mod
from src.config import CONTEXTO_PREPROCESAMIENTO_MAX_CHARS
from src.tools.resumen_prompt import acotar_resumen_para_prompt

_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "logs"


def _estado_base(**extra):
    base = {
        "resumen_logs": {"formato_detectado": "auth_log", "total_lineas": 5, "servicios": {}},
        "contexto_rag": [],
        "necesita_rag": None,
    }
    base.update(extra)
    return base


def test_la_primera_pasada_incluye_el_contexto_v2(monkeypatch):
    capturado = {}

    def _fake_llm(user_content, system=None, **k):
        capturado["user_content"] = user_content
        return {"necesita_rag": False, "diagnostico": "ok", "razon": "..."}

    monkeypatch.setattr(triage_mod, "llm_json", _fake_llm)
    estado = _estado_base(
        preprocessing_metadata={
            "total_eventos": 100, "total_lineas_fisicas": 100,
            "decoder_distribution": {"json": 100},
            "severity_distribution": {"ERROR": 5, "INFO": 95},
            "event_categories": {"authentication": 100},
            "parsing": {"coverage": 1.0, "parsed_events": 100, "fallback_events": 0},
        },
        parsing_warnings=[],
        raw_samples=[],
    )
    triage_mod.agente_analista_triage(estado)

    assert "CÓMO SE INTERPRETÓ EL LOTE" in capturado["user_content"]
    assert "ERROR=5" in capturado["user_content"]
    assert "authentication=100" in capturado["user_content"]


def test_sin_metadatos_v2_la_primera_pasada_no_agrega_nada(monkeypatch):
    """Motor v1 (o cualquier estado sin `preprocessing_metadata`): el prompt
    no debe traer una sección vacía ni fabricar contexto que no existe."""
    capturado = {}

    def _fake_llm(user_content, system=None, **k):
        capturado["user_content"] = user_content
        return {"necesita_rag": False, "diagnostico": "ok", "razon": "..."}

    monkeypatch.setattr(triage_mod, "llm_json", _fake_llm)
    triage_mod.agente_analista_triage(_estado_base())

    assert "CÓMO SE INTERPRETÓ EL LOTE" not in capturado["user_content"]


def test_el_contexto_no_supera_el_presupuesto_con_hdfs_real():
    """HDFS_2k: 202 IPs distintas -- el lote que en su momento disparó
    58 289 tokens en el resumen (ver resumen_prompt.py). El contexto v2 no
    escala con la cantidad de IPs (son distribuciones de baja cardinalidad),
    pero este test lo mide contra datos reales en vez de asumirlo."""
    raw = (_DATA_DIR / "HDFS_2k.log").read_text(encoding="utf-8", errors="replace")
    estado, _config, _firma = pipeline_mod._preparar_estado_inicial(raw, "test_presupuesto_hdfs")

    assert estado["resumen_logs"]["n_ips_distintas"] == 202

    contexto_pre = triage_mod._contexto_pre(estado)
    assert len(contexto_pre) <= CONTEXTO_PREPROCESAMIENTO_MAX_CHARS

    resumen_acotado = acotar_resumen_para_prompt(estado["resumen_logs"])
    resumen_txt = json.dumps(resumen_acotado, ensure_ascii=False)
    # Muy por debajo de los ~58 000 tokens (~232 000 caracteres) que el
    # resumen SIN acotar disparaba antes de que existiera acotar_resumen_
    # para_prompt: confirma que sumar el contexto v2 al primer prompt no
    # reabre ese problema.
    assert len(resumen_txt) + len(contexto_pre) < 10_000


def test_los_campos_nuevos_de_m1_no_llegan_al_prompt(monkeypatch):
    """M1 (Fase 4 del cierre de auditoría, 23-sep-2026): `entities`,
    `time_window`, `event_outcomes` y las distribuciones de vendor/
    version/protocol ahora viven en `preprocessing_metadata` (el estado),
    pero `contexto_preprocesamiento()` sigue leyendo la misma allowlist de
    la Fase 2 -- que un campo esté en el estado no implica que esté en el
    prompt. Antonia pidió esto explícito: la ventana temporal (y la
    cronología, que comparte la misma fuente) quedan fuera del prompt por
    riesgo de fuga del ground truth."""
    raw = (_DATA_DIR / "BGL_2k.log").read_text(encoding="utf-8", errors="replace")
    estado, _config, _firma = pipeline_mod._preparar_estado_inicial(raw, "test_m1_no_al_prompt")
    metadatos = estado["preprocessing_metadata"]

    # los campos nuevos SÍ están en el estado (M1 cumplido)
    for clave in ("entities", "time_window", "event_outcomes",
                 "vendor_distribution", "version_distribution", "protocol_distribution"):
        assert clave in metadatos

    contexto_pre = triage_mod._contexto_pre(estado)
    # las claves temporales/de entidad no dejan rastro textual en el prompt
    inicio = metadatos["time_window"].get("inicio")
    if inicio:
        assert inicio not in contexto_pre
    # "producto" se excluye a propósito: coincide con `product_distribution`,
    # que SÍ está en la allowlist desde la Fase 2 (no es una fuga de
    # `entities`, es el mismo dato contado dos veces por caminos distintos).
    for tipo, valores in metadatos["entities"].items():
        if tipo == "producto":
            continue
        for clave_entidad in valores:
            assert str(clave_entidad) not in contexto_pre


def test_ambos_prompts_de_triage_bgl_no_filtran_las_etiquetas_del_dataset(monkeypatch):
    """BGL trae la etiqueta de alerta como primer token de cada línea. Si
    se filtrara al prompt (por las muestras crudas, por ejemplo), el LLM
    podría "diagnosticar" repitiendo la respuesta en vez de razonar sobre
    el log -- exactamente la fuga que cerró la Fase 7 del plan de
    preprocesamiento."""
    raw = (_DATA_DIR / "BGL_2k.log").read_text(encoding="utf-8", errors="replace")

    flags_del_dataset = {
        linea.split(None, 1)[0] for linea in raw.splitlines()
        if linea.strip() and linea.split(None, 1)[0] != "-"
    }
    assert flags_del_dataset  # el lote de verdad trae alertas etiquetadas

    estado, _config, _firma = pipeline_mod._preparar_estado_inicial(raw, "test_fuga_bgl")

    capturas = []

    def _fake_llm(user_content, system=None, **k):
        capturas.append(user_content)
        return {"necesita_rag": True, "diagnostico": "", "razon": "necesito precedentes"}

    monkeypatch.setattr(triage_mod, "llm_json", _fake_llm)
    triage_mod.agente_analista_triage(dict(estado, contexto_rag=[], necesita_rag=None))

    def _fake_llm_segunda(user_content, system=None, **k):
        capturas.append(user_content)
        return {"diagnostico": "posible anomalía de hardware"}

    monkeypatch.setattr(triage_mod, "llm_json", _fake_llm_segunda)
    triage_mod.agente_analista_triage(
        dict(estado, contexto_rag=[{"texto": "caso previo"}], necesita_rag=True))

    assert len(capturas) == 2
    for prompt in capturas:
        for flag in flags_del_dataset:
            assert flag not in prompt, f"la etiqueta {flag!r} se filtró al prompt del triage"
