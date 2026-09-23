"""Tests de la configuración del preprocesamiento v2 (Fase 2 del plan).

Cubren los tres criterios de aceptación de la fase:
1. Configuración inválida produce mensajes claros.
2. Los defaults permiten reproducir una corrida.
3. La configuración no cambia el parser v1 todavía.

Los helpers `_env_*` se prueban directamente porque las constantes del
módulo se resuelven al importarlo: recargar `src.config` en cada test para
manipular el entorno sería frágil y afectaría a otros módulos ya
importados. Para la validación de combinaciones se monkeypatchean las
constantes ya resueltas, que es lo que la función realmente lee.
"""

import importlib
import os

import pytest

import src.config as cfg


# --- criterio 1: mensajes claros ------------------------------------------

def test_entero_invalido_nombra_la_variable(monkeypatch):
    """Un `ValueError: invalid literal for int()` pelado no le dice a nadie
    qué variable del .env está mal escrita."""
    monkeypatch.setenv("LOG_DETECTION_CHUNK_SIZE", "cincuenta")
    with pytest.raises(ValueError, match="LOG_DETECTION_CHUNK_SIZE debe ser un entero"):
        cfg._env_int("LOG_DETECTION_CHUNK_SIZE", 50)


def test_flotante_invalido_nombra_la_variable(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT_CONFIDENCE_THRESHOLD", "medio")
    with pytest.raises(ValueError, match="LOG_FORMAT_CONFIDENCE_THRESHOLD debe ser un número"):
        cfg._env_float("LOG_FORMAT_CONFIDENCE_THRESHOLD", 0.5)


def test_booleano_invalido_nombra_la_variable(monkeypatch):
    monkeypatch.setenv("LOG_ENABLE_MULTILINE", "quizas")
    with pytest.raises(ValueError, match="LOG_ENABLE_MULTILINE debe ser booleano"):
        cfg._env_bool("LOG_ENABLE_MULTILINE", True)


def test_booleano_acepta_las_formas_habituales(monkeypatch):
    for crudo, esperado in (("true", True), ("1", True), ("yes", True), ("sí", True),
                            ("false", False), ("0", False), ("off", False),
                            ("TRUE", True), ("  no  ", False)):
        monkeypatch.setenv("X_BOOL", crudo)
        assert cfg._env_bool("X_BOOL", None) is esperado, crudo


def test_variable_ausente_o_vacia_usa_el_default_sin_lanzar(monkeypatch):
    """Importar la config en un clon limpio no debe fallar -- es la lección
    de la Fase 0, donde una validación en importación rompía la suite."""
    monkeypatch.delenv("X_AUSENTE", raising=False)
    assert cfg._env_int("X_AUSENTE", 7) == 7
    monkeypatch.setenv("X_VACIA", "   ")
    assert cfg._env_int("X_VACIA", 7) == 7
    assert cfg._env_bool("X_VACIA", True) is True


def test_modo_de_parsing_invalido_lista_los_admitidos(monkeypatch):
    monkeypatch.setattr(cfg, "LOG_PARSING_MODE", "magico")
    with pytest.raises(ValueError) as exc:
        cfg.validar_config_preprocesamiento()
    assert "LOG_PARSING_MODE inválido" in str(exc.value)
    assert "hybrid" in str(exc.value)  # enumera las opciones válidas


def test_umbral_fuera_de_rango_se_rechaza(monkeypatch):
    monkeypatch.setattr(cfg, "LOG_FORMAT_CONFIDENCE_THRESHOLD", 1.4)
    with pytest.raises(ValueError, match="entre 0.0 y 1.0"):
        cfg.validar_config_preprocesamiento()


def test_chunk_size_menor_a_uno_se_rechaza(monkeypatch):
    monkeypatch.setattr(cfg, "LOG_DETECTION_CHUNK_SIZE", 0)
    with pytest.raises(ValueError, match="LOG_DETECTION_CHUNK_SIZE debe ser >= 1"):
        cfg.validar_config_preprocesamiento()


def test_limites_de_volumen_deben_ser_positivos(monkeypatch):
    monkeypatch.setattr(cfg, "LOG_MAX_EVENTS", 0)
    with pytest.raises(ValueError, match="LOG_MAX_EVENTS debe ser >= 1"):
        cfg.validar_config_preprocesamiento()


def test_se_acumulan_todos_los_problemas_en_un_solo_mensaje(monkeypatch):
    """Reportar de a un error por corrida obliga a iterar a ciegas."""
    monkeypatch.setattr(cfg, "LOG_PARSING_MODE", "magico")
    monkeypatch.setattr(cfg, "LOG_DETECTION_CHUNK_SIZE", -5)
    monkeypatch.setattr(cfg, "LOG_MAX_EVENTS", 0)
    with pytest.raises(ValueError) as exc:
        cfg.validar_config_preprocesamiento()
    mensaje = str(exc.value)
    assert "LOG_PARSING_MODE" in mensaje
    assert "LOG_DETECTION_CHUNK_SIZE" in mensaje
    assert "LOG_MAX_EVENTS" in mensaje


def test_hybrid_sin_margen_de_reproceso_se_rechaza(monkeypatch):
    """Si ningún registro puede caer por debajo del umbral de reproceso,
    'hybrid' se comporta como 'chunked' y el reproceso nunca ocurre: es un
    no-op silencioso, no una configuración válida."""
    monkeypatch.setattr(cfg, "LOG_PARSING_MODE", "hybrid")
    monkeypatch.setattr(cfg, "LOG_FORMAT_CONFIDENCE_THRESHOLD", 0.80)
    monkeypatch.setattr(cfg, "LOG_LINE_FALLBACK_THRESHOLD", 0.50)
    with pytest.raises(ValueError) as exc:
        cfg.validar_config_preprocesamiento()
    assert "equivale a 'chunked'" in str(exc.value)


def test_esa_misma_combinacion_es_valida_en_modo_chunked(monkeypatch):
    """La combinación solo es un error porque contradice al modo hybrid."""
    monkeypatch.setattr(cfg, "LOG_PARSING_MODE", "chunked")
    monkeypatch.setattr(cfg, "LOG_FORMAT_CONFIDENCE_THRESHOLD", 0.80)
    monkeypatch.setattr(cfg, "LOG_LINE_FALLBACK_THRESHOLD", 0.50)
    cfg.validar_config_preprocesamiento()  # no lanza


# --- criterio 2: defaults reproducibles -----------------------------------

def test_los_defaults_son_validos():
    """Un clon sin ninguna variable LOG_* debe poder correr."""
    cfg.validar_config_preprocesamiento()


def test_defaults_coinciden_con_los_documentados_en_el_plan():
    efectiva = cfg.config_preprocesamiento_efectiva()
    assert efectiva["LOG_PARSING_MODE"] == "hybrid"
    assert efectiva["LOG_DETECTION_CHUNK_SIZE"] == 50
    assert efectiva["LOG_FORMAT_CONFIDENCE_THRESHOLD"] == 0.50
    assert efectiva["LOG_LINE_FALLBACK_THRESHOLD"] == 0.70
    assert efectiva["LOG_NORMALIZATION_SCHEMA_VERSION"] == "2.0"
    assert efectiva["LOG_MAX_FILE_BYTES"] == 52428800
    assert efectiva["LOG_MAX_EVENTS"] == 100000


def test_config_efectiva_es_determinista_y_ordenada():
    """Se guarda en cada resultado: si el orden variara, dos corridas
    idénticas producirían archivos distintos."""
    a = cfg.config_preprocesamiento_efectiva()
    b = cfg.config_preprocesamiento_efectiva()
    assert a == b
    assert list(a) == sorted(a)


def test_config_efectiva_incluye_todas_las_variables_log(monkeypatch):
    efectiva = cfg.config_preprocesamiento_efectiva()
    esperadas = {
        "LOG_PREPROCESSING_ENGINE", "LOG_PARSING_MODE", "LOG_DETECTION_CHUNK_SIZE",
        "LOG_FORMAT_CONFIDENCE_THRESHOLD", "LOG_LINE_FALLBACK_THRESHOLD",
        "LOG_ENABLE_MULTILINE", "LOG_PRESERVE_RAW", "LOG_MAX_RAW_SAMPLES",
        "LOG_MAX_UNMAPPED_FIELDS", "LOG_NORMALIZATION_SCHEMA_VERSION",
        "LOG_MAX_FILE_BYTES", "LOG_MAX_EVENTS",
    }
    assert set(efectiva) == esperadas


# --- criterio 3: el parser v1 no cambia -----------------------------------

def test_la_config_nueva_no_altera_el_comportamiento_del_parser_v1():
    """Regresión explícita: agregar variables LOG_* no debe mover ni un
    conteo del agregador actual."""
    from src.tools.aggregation import aggregate_logs
    logs = (
        "Jan 10 13:55:36 srv sshd[1]: Failed password for invalid user admin "
        "from 203.0.113.10 port 22 ssh2\n"
        "Jan 10 13:55:39 srv sshd[2]: Failed password for root from 45.146.0.9 port 22 ssh2\n"
    )
    r = aggregate_logs(logs)
    assert r["formato_detectado"] == "auth_log"
    assert r["total_lineas"] == 2
    assert r["servicios"]["sshd"] == 2
    assert r["n_ips_distintas"] == 2


def test_el_modulo_de_config_se_importa_sin_ninguna_variable_log(monkeypatch):
    """Recarga limpia sin variables LOG_* en el entorno: no debe lanzar."""
    for nombre in [k for k in os.environ if k.startswith("LOG_")]:
        monkeypatch.delenv(nombre, raising=False)
    recargado = importlib.reload(cfg)
    assert recargado.LOG_PARSING_MODE == "hybrid"
    recargado.validar_config_preprocesamiento()
