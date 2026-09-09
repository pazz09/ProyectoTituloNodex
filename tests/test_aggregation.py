"""Tests de la agregación determinística (no requieren API keys)."""

# Estos tests describen el comportamiento del AGREGADOR v1, así que
# invocan `aggregate_logs_v1` directamente en vez de pasar por la
# fachada `aggregate_logs`, que despacha según
# LOG_PREPROCESSING_ENGINE. De ese modo siguen verificando lo que
# deben verificar aunque el entorno tenga el motor v2 activo -- la
# fidelidad con el prototipo del Seminario se conserva en v1, no en
# el esquema nuevo (ver docs/plan_accion_preprocesamiento_heterogeneo.md).
from src.tools.aggregation import aggregate_logs_v1 as aggregate_logs
from src.tools.aggregation import firma_lote, parse_log


def test_parse_log_detecta_ip_y_servicio_sshd():
    linea = "Jan 10 13:55:36 srv sshd[1]: Failed password for invalid user admin from 203.0.113.10 port 22 ssh2"
    info = parse_log(linea)
    assert info["ip"] == "203.0.113.10"
    assert info["servicio"] == "sshd"
    # NOTA (fiel al notebook original): la regex de usuario prioriza por POSICIÓN
    # en el texto, no por especificidad de la alternativa. En "... for invalid user
    # admin ..." coincide primero con "for" (aparece antes que "invalid user") y
    # captura la palabra siguiente, "invalid" -- no "admin". Es un comportamiento
    # heredado del prototipo del Seminario, no un error de la migración. Ver
    # LLM_Agente_INICIO.ipynb, celda 13 (`parse_log`).
    assert info["usuario"] == "invalid"
    assert info["intentos_fallidos"] == 1


def test_aggregate_logs_agrupa_por_ip():
    logs = (
        "Jan 10 13:55:36 srv sshd[1]: Failed password for invalid user admin from 203.0.113.10 port 22 ssh2\n"
        "Jan 10 13:55:39 srv sshd[2]: Failed password for root from 45.146.0.9 port 22 ssh2\n"
        "Jan 10 13:55:40 srv sshd[3]: Failed password for root from 45.146.0.9 port 22 ssh2\n"
    )
    resumen = aggregate_logs(logs)
    assert resumen["total_lineas"] == 3
    assert resumen["n_ips_distintas"] == 2
    assert resumen["por_ip"]["45.146.0.9"]["n_eventos"] == 2
    assert resumen["servicios"]["sshd"] == 3


def test_firma_lote_es_determinista():
    resumen = aggregate_logs("Jan 10 13:55:36 srv sshd[1]: Failed password for root from 1.2.3.4 port 22 ssh2")
    assert firma_lote(resumen) == firma_lote(resumen)
