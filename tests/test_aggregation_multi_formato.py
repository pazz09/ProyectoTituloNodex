"""Tests del soporte multi-formato de aggregate_logs() (HDFS, BGL, y el
respaldo de texto libre para formatos no reconocidos).

Motivación histórica (ver README, "Parsing multi-formato de logs"): al
recibir los datasets HDFS_2k.log y BGL_2k.log (Tabla 8.11 del Informe), un
parser pensado solo para auth-log fallaba en tres formas concretas:
1) no reconocía los timestamps de ninguno de los dos formatos,
2) HDFS caía 100% en servicio="desconocido",
3) un falso positivo real: "PacketResponder ... for block blk_123..."
   hacía que la regex de usuario de auth-log capturara usuario="block".

Las líneas de ejemplo abajo son fragmentos reales de HDFS_2k.log y
BGL_2k.log (no sintéticos), elegidos para cubrir esos tres problemas.

Importante (23-sep-2026): con el preprocesamiento heterogéneo, la
criticidad de un evento (`evento_critico`) ya NO se deriva del flag de
alerta de BGL ni de ninguna otra etiqueta del dataset -- se deriva de lo
que el propio log declara (severidad, resultado de la operación). Ver
`src/preprocessing/enrichers/bgl.py` y `_es_critico()` en
`src/preprocessing/aggregation.py`.
"""

from src.tools.aggregation import aggregate_logs

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

# Variante real de BGL sin el token "RAS" (usa "NULL DISCOVERY ..."). El
# primer campo ("ALERTA" acá, inventado para el test) es el flag de alerta
# del dataset -- ya no debe influir en evento_critico bajo ningún caso.
BGL_MUESTRA_VARIANTE_SIN_RAS = (
    "- 1117838570 2005.06.03 R02-M1-N0-C:J12-U11 2005-06-03-15.42.50.675872 R02-M1-N0-C:J12-U11 RAS KERNEL INFO instruction cache parity error corrected\n"
    "- 1117842440 2005.06.03 R23-M0-NE-C:J05-U01 2005-06-03-16.47.20.730545 R23-M0-NE-C:J05-U01 RAS KERNEL INFO 63543 double-hummer alignment exceptions\n"
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
    # el falso positivo original: "for block blk_..." ya no se confunde con
    # un usuario -- el block id ni siquiera ocupa ese campo (va a un
    # atributo propio, no es una "persona"), así que "usuarios_objetivo"
    # queda vacío para HDFS por diseño, no solo sin "block".
    todos_los_usuarios = {
        u for v in resumen["por_ip"].values() for u in v["usuarios_objetivo"]
    }
    assert "block" not in todos_los_usuarios
    assert todos_los_usuarios == set()
    assert resumen["servicios"]["hdfs.datanode"] == 2
    assert resumen["servicios"]["hdfs.fsnamesystem"] == 1
    # la línea WARN se marca como crítica; las dos INFO no
    assert resumen["eventos"]["evento_critico"] == 1
    assert resumen["eventos"]["evento_normal"] == 2
    assert resumen["ventana_temporal"]["inicio"] == "2008-11-09 20:36:15"


def test_detecta_formato_bgl_y_la_criticidad_viene_de_la_severidad_declarada():
    """La línea APPREAD es la única "alerta" real del flag de BGL, pero acá
    se marca crítica porque su severidad declarada es FATAL (un dato del
    propio log) -- NO porque el flag de alerta lo diga. Las dos líneas "-"
    declaran severidad INFO y quedan normales por la misma razón."""
    resumen = aggregate_logs(BGL_MUESTRA)
    assert resumen["formato_detectado"] == "bgl"
    assert resumen["total_lineas"] == 3
    assert resumen["eventos"]["evento_critico"] == 1
    assert resumen["eventos"]["evento_normal"] == 2
    assert resumen["servicios"]["bgl.kernel"] == 2
    assert resumen["servicios"]["bgl.app"] == 1
    # la IP embebida en el mensaje de la línea de alerta se detecta igual
    assert "172.16.96.116" in resumen["ips_distintas"]


def test_bgl_reconoce_una_variante_sin_el_token_ras_y_el_flag_no_influye():
    """La variante "NULL DISCOVERY ..." (sin "RAS") se reconoce igual y
    queda mapeada a su propio subsistema (bgl.discovery). El flag de alerta
    del primer campo -- "ALERTA" en esta muestra, inventado a propósito para
    el test -- NO debe influir en evento_critico bajo ningún caso: acá la
    línea es crítica porque declara severidad WARNING, no por el flag."""
    resumen = aggregate_logs(BGL_MUESTRA_VARIANTE_SIN_RAS)
    assert resumen["formato_detectado"] == "bgl"
    assert resumen["servicios"]["bgl.discovery"] == 1
    assert resumen["eventos"]["evento_critico"] == 1  # por severidad WARNING, no por el flag
    assert resumen["eventos"]["evento_normal"] == 2


def test_formato_no_reconocido_cae_a_texto_libre_sin_perder_las_lineas():
    resumen = aggregate_logs(TEXTO_NO_RECONOCIDO)
    assert resumen["formato_detectado"] == "text"
    assert resumen["total_lineas"] == 2
    assert resumen["servicios"]["desconocido"] == 2


def test_auth_log_se_detecta_y_marca_los_fallos_como_criticos():
    """Auth-log usa el mismo vocabulario unificado que HDFS/BGL
    (evento_critico/evento_normal), no el acceso_fallido/evento_generico
    de una versión anterior del preprocesamiento."""
    resumen = aggregate_logs(AUTH_LOG_MUESTRA)
    assert resumen["formato_detectado"] == "auth_log"
    assert resumen["servicios"]["sshd"] == 1
    assert resumen["eventos"]["evento_critico"] == 1
