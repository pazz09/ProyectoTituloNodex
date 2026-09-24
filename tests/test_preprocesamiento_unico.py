"""Preprocesamiento único por lote (Fase 1, cierre de auditoría 23-sep-2026).

Hallazgo A1: `preprocesar()` corría dos veces por lote -- una vez dentro de
`aggregate_logs()`, otra en `_metadatos_preprocesamiento()` (pipeline.py) o
en `clasificar_texto()` (baseline_reglas.py), cada una un parseo completo e
independiente del mismo texto. Se resolvió con `preprocesar_lote()`
(`src/tools/aggregation.py`), que calcula `resultado` (preprocesar) y `v2`
(agregar_v2) una sola vez y deriva de ahí tanto el resumen v1 como los
metadatos del estado del grafo.

Estos tests verifican el CONTEO real de invocaciones, no solo el resultado:
como el preprocesamiento es determinístico, dos parseos del mismo texto dan
el mismo resultado -- así que un test que solo mirara la salida no habría
detectado la duplicación que el hallazgo A1 describe.
"""

import src.pipeline as pipeline_mod
import src.preprocessing.aggregation as preprocessing_aggregation_mod
import src.preprocessing.pipeline as preprocessing_pipeline_mod
from src.tools.baseline_reglas import clasificar_texto

LOTE = "\n".join([
    "Jan 10 13:55:36 srv sshd[1]: Failed password for invalid user admin "
    "from 203.0.113.10 port 22 ssh2",
    "Jan 10 13:55:39 srv sshd[2]: Failed password for root from 203.0.113.10 port 22 ssh2",
]) + "\n"


def _contador(fn):
    """Envuelve `fn` para contar invocaciones sin alterar su comportamiento."""
    llamadas = []

    def envoltura(*args, **kwargs):
        llamadas.append(1)
        return fn(*args, **kwargs)

    envoltura.llamadas = llamadas
    return envoltura


def _parchar_contadores(monkeypatch):
    contador_preprocesar = _contador(preprocessing_pipeline_mod.preprocesar)
    contador_agregar_v2 = _contador(preprocessing_aggregation_mod.agregar_v2)
    monkeypatch.setattr(preprocessing_pipeline_mod, "preprocesar", contador_preprocesar)
    monkeypatch.setattr(preprocessing_aggregation_mod, "agregar_v2", contador_agregar_v2)
    return contador_preprocesar, contador_agregar_v2


def test_el_pipeline_preprocesa_el_lote_una_sola_vez(monkeypatch):
    contador_preprocesar, contador_agregar_v2 = _parchar_contadores(monkeypatch)

    pipeline_mod._preparar_estado_inicial(LOTE, "test_contador_pipeline")

    assert len(contador_preprocesar.llamadas) == 1
    assert len(contador_agregar_v2.llamadas) == 1


def test_el_baseline_preprocesa_el_lote_una_sola_vez(monkeypatch):
    contador_preprocesar, contador_agregar_v2 = _parchar_contadores(monkeypatch)

    clasificar_texto(LOTE)

    assert len(contador_preprocesar.llamadas) == 1
    assert len(contador_agregar_v2.llamadas) == 1


def test_los_metadatos_y_el_resumen_v1_salen_del_mismo_resultado():
    """Mismos conteos y misma cobertura entre `resumen_logs` (v1) y
    `preprocessing_metadata` (v2): ambos se derivan de la misma pasada."""
    estado, _config, _firma = pipeline_mod._preparar_estado_inicial(LOTE, "test_consistencia")
    resumen = estado["resumen_logs"]
    metadatos = estado["preprocessing_metadata"]

    assert metadatos["total_eventos"] == resumen["total_lineas"]
    assert sum(metadatos["decoder_distribution"].values()) == metadatos["total_eventos"]
    assert metadatos["parsing"]["coverage"] == round(
        metadatos["parsing"]["parsed_events"] / metadatos["total_eventos"], 4
    )


def test_el_baseline_clasifica_con_metadatos_reales_no_vacios():
    """Antes de este cierre, un fallo en el segundo parseo independiente
    degradaba `clasificar_texto` a `metadatos={}` en silencio. Con una sola
    pasada ya no hay ese segundo parseo que pueda fallar aparte: si el
    preprocesamiento funciona (como acá), el baseline recibe metadatos
    reales."""
    veredicto = clasificar_texto(LOTE)
    assert veredicto["prediccion"] in ("anomalo", "normal")
    assert veredicto["regla"] != ""
