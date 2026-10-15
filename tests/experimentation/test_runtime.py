"""Identidad, almacenamiento y exportación de corridas.

Cubre lo que durante la preparación solo se había ejercitado con un script
suelto: que cada corrida tenga una identidad estable, que el almacenamiento
no sobrescriba, y que CADA arquitectura del vocabulario tenga dónde guardarse.

Esta última prueba existe por un defecto real: `gemini_externo` estaba en el
vocabulario y en el `run_id`, pero faltaba en la tabla de carpetas, así que
planificar con esa arquitectura lanzaba `KeyError`. Las pruebas unitarias no
lo veían porque nadie le pedía a `rutas()` una ruta de esa arquitectura; lo
encontró el plan en seco.
"""

import json

import pytest

from src.experimentation.contracts.enums import ARQUITECTURAS
from src.experimentation.runtime import persistencia
from src.experimentation.runtime.identidad import (
    IdentidadCorrida,
    partes_del_run_id,
    verificar,
)


def _identidad(**extra) -> IdentidadCorrida:
    base = dict(case_id="uwf_eva_visible_0003", dataset="uwf",
                arquitectura="nodex_multiagente", repeticion=2,
                config_version="piloto-001")
    base.update(extra)
    return IdentidadCorrida(**base)


# --- identidad -------------------------------------------------------------

def test_el_run_id_es_determinista():
    assert _identidad().run_id == _identidad().run_id


def test_cambiar_la_config_version_cambia_el_run_id():
    """Una campaña nueva no pisa los artefactos de la anterior."""
    assert _identidad().run_id != _identidad(config_version="final-001").run_id


def test_cada_repeticion_tiene_su_propio_run_id():
    assert _identidad(repeticion=1).run_id != _identidad(repeticion=2).run_id


@pytest.mark.parametrize("arquitectura", ARQUITECTURAS)
def test_cada_arquitectura_del_vocabulario_puede_tener_un_run_id(arquitectura):
    identidad = _identidad(arquitectura=arquitectura)
    assert partes_del_run_id(identidad.run_id)["repeticion"] == 2
    assert verificar(identidad, identidad.run_id)


@pytest.mark.parametrize("campos", [
    {"repeticion": 0}, {"dataset": "marte"}, {"config_version": ""},
    {"arquitectura": "inventada"},
])
def test_una_identidad_incompleta_o_invalida_se_rechaza(campos):
    with pytest.raises(ValueError):
        _identidad(**campos)


# --- almacenamiento ---------------------------------------------------------

@pytest.mark.parametrize("arquitectura", ARQUITECTURAS)
def test_cada_arquitectura_tiene_una_carpeta_de_almacenamiento(arquitectura, tmp_path):
    """Defecto real: `gemini_externo` no figuraba y `rutas()` lanzaba
    KeyError al planificar. Cubre toda la clase de error, no solo ese caso."""
    assert arquitectura in persistencia.CARPETA_POR_ARQUITECTURA
    rutas = persistencia.rutas(_identidad(arquitectura=arquitectura), tmp_path)
    assert rutas.salida.parent.parent.name == (
        persistencia.CARPETA_POR_ARQUITECTURA[arquitectura]
    )


def test_la_estructura_incluye_la_carpeta_de_cada_arquitectura(tmp_path):
    persistencia.preparar_estructura(tmp_path)
    for carpeta in persistencia.CARPETA_POR_ARQUITECTURA.values():
        assert (tmp_path / "experiments" / carpeta).is_dir(), carpeta


def test_guardar_escribe_las_tres_piezas_con_la_identidad(tmp_path):
    identidad = _identidad()
    persistencia.guardar(identidad, tmp_path, salida={"classification": "MALICIOUS"},
                         crudo={"hay_incidente": True}, telemetria={"llm_call_count": 6})
    rutas = persistencia.rutas(identidad, tmp_path)
    for ruta in (rutas.salida, rutas.crudo, rutas.telemetria):
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        assert datos["run_id"] == identidad.run_id
        assert datos["config_version"] == "piloto-001"
        assert datos["repeticion"] == 2


def test_una_corrida_guardada_no_se_sobrescribe(tmp_path):
    identidad = _identidad()
    persistencia.guardar(identidad, tmp_path, salida={"classification": "MALICIOUS"})
    with pytest.raises(FileExistsError, match="ya tiene"):
        persistencia.guardar(identidad, tmp_path, salida={"classification": "BENIGN"})
    guardado = persistencia.leer_salida(persistencia.rutas(identidad, tmp_path).salida)
    assert guardado["salida"]["classification"] == "MALICIOUS"


def test_ya_existe_permite_reanudar_una_campana(tmp_path):
    identidad = _identidad()
    assert persistencia.ya_existe(identidad, tmp_path) is False
    persistencia.guardar(identidad, tmp_path, salida={})
    assert persistencia.ya_existe(identidad, tmp_path) is True


def test_leer_salida_exige_la_identidad_completa(tmp_path):
    archivo = tmp_path / "suelto.json"
    archivo.write_text(json.dumps({"salida": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="identidad"):
        persistencia.leer_salida(archivo)


# --- campos_de_modelo: puente entre la telemetría del sistema y esta capa ------------

from src.experimentation.runtime import exportacion as _exportacion
from src.experimentation.runtime.telemetria import campos_de_modelo


def test_campos_de_modelo_suma_el_razonamiento_y_lista_las_versiones():
    medido = {"llm_calls": [
        {"model": "m", "model_version": "m-001", "reasoning_tokens": 5,
         "input_tokens": 1, "output_tokens": 1},
        {"model": "m", "model_version": "m-001", "reasoning_tokens": 7,
         "input_tokens": 1, "output_tokens": 1},
    ]}
    campos = campos_de_modelo(medido)
    assert campos["reasoning_tokens"] == 12
    assert campos["modelos_efectivos"] == ["m-001"]        # sin repetir
    assert campos["campos_parciales"] == {}


def test_campos_de_modelo_none_sigue_siendo_none():
    for medido in (None, {}, {"llm_calls": []},
                   {"llm_calls": [{"model": "m", "reasoning_tokens": None}]}):
        campos = campos_de_modelo(medido)
        assert campos["reasoning_tokens"] is None, medido
        assert campos["modelos_efectivos"] == [], medido


def test_campos_de_modelo_declara_la_suma_parcial():
    medido = {"llm_calls": [{"model": "m", "reasoning_tokens": 5},
                            {"model": "m", "reasoning_tokens": None}]}
    campos = campos_de_modelo(medido)
    assert campos["reasoning_tokens"] == 5
    assert campos["campos_parciales"]["reasoning_tokens"] == {"informadas": 1, "totales": 2}


def test_campos_de_modelo_rechaza_valores_que_no_son_enteros_ni_textos():
    medido = {"llm_calls": [{"model": "m", "model_version": "", "reasoning_tokens": True},
                            {"model": "m", "model_version": 3, "reasoning_tokens": -1},
                            "no es un dict"]}
    campos = campos_de_modelo(medido)
    assert campos["reasoning_tokens"] is None
    assert campos["modelos_efectivos"] == []


def test_la_exportacion_incluye_razonamiento_y_versiones_sin_convertir_none_en_cero():
    assert "reasoning_tokens" in _exportacion.COLUMNAS
    assert "modelos_efectivos" in _exportacion.COLUMNAS
    ident = {"case_id": "c", "dataset": "d", "arquitectura": "a", "repeticion": 1}
    con = _exportacion.fila(ident, {}, telemetria={
        "reasoning_tokens": 12, "modelos_efectivos": ["m-001", "n-002"]})
    assert con["reasoning_tokens"] == 12
    assert con["modelos_efectivos"] == "m-001; n-002"
    sin = _exportacion.fila(ident, {}, telemetria={})
    assert sin["reasoning_tokens"] is None
    assert sin["modelos_efectivos"] is None
    cero = _exportacion.fila(ident, {}, telemetria={"reasoning_tokens": 0})
    assert cero["reasoning_tokens"] == 0          # un cero informado sí es un cero
