"""Tests del soporte multi-formato de aggregate_logs() (HDFS, BGL, y el
fallback a auth-log para formatos no reconocidos).

Motivación (ver README, "Parsing multi-formato de logs"): al recibir los
datasets HDFS_2k.log y BGL_2k.log (Tabla 8.11 del Informe), el parser
original —diseñado para auth-log— fallaba en tres formas concretas:
1) no reconocía los timestamps de ninguno de los dos formatos,
2) HDFS caía 100% en servicio="desconocido",
3) un falso positivo real: "PacketResponder ... for block blk_123..."
   hacía que la regex de usuario auth-log capturara usuario="block".

Las líneas de ejemplo abajo son fragmentos reales de HDFS_2k.log y
BGL_2k.log (no sintéticos), elegidos para cubrir esos tres problemas.
"""

# Estos tests describen el comportamiento del AGREGADOR v1, así que
# invocan `aggregate_logs_v1` directamente en vez de pasar por la
# fachada `aggregate_logs`, que despacha según
# LOG_PREPROCESSING_ENGINE. De ese modo siguen verificando lo que
# deben verificar aunque el entorno tenga el motor v2 activo -- la
# fidelidad con el prototipo del Seminario se conserva en v1, no en
# el esquema nuevo (ver docs/plan_accion_preprocesamiento_heterogeneo.md).
from src.tools.aggregation import aggregate_logs_v1 as aggregate_logs

HDFS_MUESTRA = (
    "081109 203615 148 INFO dfs.DataNode$PacketResponder: PacketResponder 1 for block blk_38865049064139660 terminating\n"
    "081109 204005 35 INFO dfs.FSNamesystem: BLOCK* NameSystem.addStoredBlock: blockMap updated: 10.251.73.220:50010 is added to blk_7128370237687728475 size 67108864\n"
    "081109 214043 2561 WARN dfs.DataNode$DataXceiver: 10.251.30.85:50010:Got exception while serving blk_-2918118818249673980 to /10.251.90.64:\n"
)

BGL_MUESTRA = (
    "- 1117838570 2005.06.03 R02-M1-N0-C:J12-U11 2005-06-03-15.42.50.675872 R02-M1-N0-C:J12-U11 RAS KERNEL INFO instruction cache parity error corrected\n"
    "- 1117842440 2005.06.03 R23-M0-NE-C:J05-U01 2005-06-03-16.47.20.730545 R23-M0-NE-C:J05-U01 RAS KERNEL INFO 63543 double-hummer alignment exceptions\n"
    "APPREAD 1117869872 2005.06.04 R04-M1-N4-I:J18-U11 2005-06-04-00.24.32.432192 R04-M1-N4-I:J18-U11 RAS APP FATAL ciod: failed to read message prefix on control stream (CioStream socket to 172.16.96.116:33569\n"
)

BGL_MUESTRA_CON_ALERTA_SIN_RAS = (
    "- 1117838570 2005.06.03 R02-M1-N0-C:J12-U11 2005-06-03-15.42.50.675872 R02-M1-N0-C:J12-U11 RAS KERNEL INFO instruction cache parity error corrected\n"
    "- 1117842440 2005.06.03 R23-M0-NE-C:J05-U01 2005-06-03-16.47.20.730545 R23-M0-NE-C:J05-U01 RAS KERNEL INFO 63543 double-hummer alignment exceptions\n"
    # variante real de BGL sin el token "RAS" (usa "NULL DISCOVERY ..."), con
    # un flag de alerta inventado para el test -- en BGL_2k.log estas líneas
    # siempre tienen flag "-", pero el parser no debe asumirlo.
    "ALERTA 1119977619 2005.06.28 R02-M1-NE 2005-06-28-09.53.39.479164 R02-M1-NE NULL DISCOVERY WARNING Node card is not fully functional\n"
)

AUTH_LOG_MUESTRA = (
    "Jan 10 13:55:36 srv sshd[1]: Failed password for invalid user admin from 203.0.113.10 port 22 ssh2\n"
)

TEXTO_NO_RECONOCIDO = (
    "esto no es un log de ningun formato conocido, solo texto libre\n"
    "otra linea de texto libre sin timestamp reconocible\n"
)


def test_detecta_formato_hdfs_y_evita_falso_positivo_block():
    resumen = aggregate_logs(HDFS_MUESTRA)
    assert resumen["formato_detectado"] == "hdfs"
    assert resumen["total_lineas"] == 3
    # el falso positivo original: "for block blk_..." ya no se confunde con un usuario
    todos_los_usuarios = {
        u for v in resumen["por_ip"].values() for u in v["usuarios_objetivo"]
    }
    assert "block" not in todos_los_usuarios
    # en cambio, el block id real queda como el "actor" de la línea
    assert any(u.startswith("blk_") for u in todos_los_usuarios)
    assert resumen["servicios"]["hdfs.datanode"] == 2
    assert resumen["servicios"]["hdfs.fsnamesystem"] == 1
    # la línea WARN se marca como crítica; las dos INFO no
    assert resumen["eventos"]["evento_critico"] == 1
    assert resumen["eventos"]["evento_normal"] == 2
    assert resumen["ventana_temporal"]["inicio"] == "2008-11-09 20:36:15"


def test_detecta_formato_bgl_y_usa_flag_de_alerta_como_ground_truth():
    resumen = aggregate_logs(BGL_MUESTRA)
    assert resumen["formato_detectado"] == "bgl"
    assert resumen["total_lineas"] == 3
    # las dos líneas "-" son no-alerta; la línea APPREAD es la única alerta real
    assert resumen["eventos"]["evento_critico"] == 1
    assert resumen["eventos"]["evento_normal"] == 2
    assert resumen["servicios"]["bgl.kernel"] == 2
    assert resumen["servicios"]["bgl.app"] == 1
    # la IP embebida en el mensaje de la línea de alerta se detecta igual
    assert "172.16.96.116" in resumen["ips_distintas"]


def test_bgl_no_pierde_alertas_en_lineas_que_no_matchean_el_patron_completo():
    """Regresión sobre un hallazgo real (24-ago-2026, reportado por el
    Claude Code local de Antonia): si el flag de alerta se leyera solo del
    grupo capturado por un match exitoso de _BGL_RE, una línea de alerta
    real que no matchea el patrón completo (p. ej. la variante "NULL
    DISCOVERY ..." en vez de "RAS ...") se perdería como falso negativo.
    El flag debe leerse del texto crudo, independiente del resto del match."""
    resumen = aggregate_logs(BGL_MUESTRA_CON_ALERTA_SIN_RAS)
    assert resumen["formato_detectado"] == "bgl"
    assert resumen["eventos"]["evento_critico"] == 1  # la línea sin RAS, pero con flag de alerta
    assert resumen["eventos"]["evento_normal"] == 2
    assert resumen["servicios"]["bgl.otro"] == 1  # se pierde la etiqueta de servicio, no la alerta


def test_formato_no_reconocido_cae_a_auth_log_sin_perder_las_lineas():
    resumen = aggregate_logs(TEXTO_NO_RECONOCIDO)
    assert resumen["formato_detectado"] == "auth_log"
    assert resumen["total_lineas"] == 2
    assert resumen["servicios"]["desconocido"] == 2


def test_auth_log_sigue_funcionando_igual_que_antes():
    """Regresión: un lote 100% auth-log debe seguir detectándose como tal
    y con exactamente el mismo comportamiento que antes de esta migración."""
    resumen = aggregate_logs(AUTH_LOG_MUESTRA)
    assert resumen["formato_detectado"] == "auth_log"
    assert resumen["servicios"]["sshd"] == 1
    assert resumen["eventos"]["acceso_fallido"] == 1
