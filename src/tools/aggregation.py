"""Agregación determinística de logs (sin LLM) — núcleo del escalado.

`parse_log()` fue migrado sin cambios desde la celda 13 del notebook de
Colab del Seminario de Título y sigue siendo la ruta de parsing para logs
estilo auth-log (sshd, Apache, kernel, IDS) — el formato para el que fue
diseñado originalmente (ver Informe, §8.2.1).

A partir del Proyecto de Título esto ya no basta: el sistema debe poder
leer logs "de diferentes tipos" (HDFS, BGL, y en general los datasets de
la Tabla 8.11 del Informe), no solo el formato auth-log del prototipo. En
vez de forzar esos formatos a través de la misma regex (lo que producía
falsos positivos reales — ver `docs`/README, "Parsing multi-formato"), se
introduce una capa de **adaptadores por formato**: cada uno sabe detectar
si un lote de logs es "suyo" y cómo parsear una línea de ese formato. La
detección se hace UNA vez por lote (no línea por línea) porque un lote
real es, en la práctica, homogéneo en su origen — y así se evita que una
línea ambigua "contamine" la clasificación de servicio/evento del resto.

Si ningún adaptador reconoce el formato con suficiente confianza, se cae
al comportamiento original (adaptador auth-log) — el mismo que corría
antes de esta migración — para no regresionar sobre formatos desconocidos.
"""

import csv
import re
from datetime import datetime, timezone

IP_RE = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")
TS_RE = re.compile(r"^([A-Z][a-z]{2}\s+\d+\s+\d{2}:\d{2}:\d{2})")


def parse_log(raw: str) -> dict:
    """Helper por LÍNEA (formato auth-log): extrae IP, usuario, servicio y
    tipo de evento. SIN CAMBIOS respecto a la versión original — incluye el
    comportamiento heredado del notebook donde la regex de usuario prioriza
    por posición, no por especificidad (ver tests/test_aggregation.py)."""
    m = IP_RE.search(raw)
    ip = m.group(1) if m else None
    mu = re.search(r"(?:invalid user|user|for)\s+([A-Za-z0-9._-]+)", raw)
    user = mu.group(1) if mu else None
    low = raw.lower()
    if "sshd" in low:
        servicio = "sshd"
    elif "apache" in low or "http" in low or "get " in low or "post " in low:
        servicio = "apache"
    elif "kernel" in low:
        servicio = "kernel"
    elif "snort" in low or "suricata" in low or "ids" in low:
        servicio = "ids"
    else:
        servicio = "desconocido"
    fallidos = len(re.findall(r"failed password|authentication failure|401|403", low))
    evento = "acceso_fallido" if fallidos else "evento_generico"
    return {"ip": ip, "usuario": user, "servicio": servicio,
            "evento": evento, "intentos_fallidos": fallidos}


# ---------------------------------------------------------------------------
# Adaptadores por formato
# ---------------------------------------------------------------------------
# Cada adaptador expone:
#   detectar(lineas_muestra) -> float en [0, 1]   (confianza de que el lote
#       completo sea de este formato, evaluada sobre una muestra)
#   parsear_linea(linea) -> dict con las mismas claves que parse_log(), más
#       "timestamp" (string ya extraído, o None si la línea no matchea).
#
# El campo "usuario" es, en rigor, el "actor u objeto de la línea": en
# auth-log es un nombre de usuario real; en HDFS es un block id
# (blk_...); en BGL es un identificador de nodo del clúster (p. ej.
# "R02-M1-N0-C:J12-U11"). Se mantiene el mismo nombre de clave por
# compatibilidad con el resto del pipeline (nada aguas abajo depende del
# string literal, solo de que la clave exista), pero es importante no leer
# "usuario" como "persona" fuera del formato auth-log.

_TAMANO_MUESTRA = 50
_UMBRAL_CONFIANZA = 0.5


class _AuthLogAdapter:
    nombre = "auth_log"

    def detectar(self, muestra: list) -> float:
        if not muestra:
            return 0.0
        return sum(1 for l in muestra if TS_RE.match(l)) / len(muestra)

    def parsear_linea(self, linea: str) -> dict:
        info = parse_log(linea)
        m = TS_RE.match(linea)
        info["timestamp"] = m.group(1) if m else None
        return info


_HDFS_RE = re.compile(
    r"^(\d{6})\s+(\d{6})\s+\d+\s+(INFO|WARN|ERROR|FATAL)\s+(\S+):\s*(.*)$"
)
_HDFS_CLASE_A_SERVICIO = {
    "dfs.DataNode$PacketResponder": "hdfs.datanode",
    "dfs.DataNode$DataXceiver": "hdfs.datanode",
    "dfs.DataNode": "hdfs.datanode",
    "dfs.FSNamesystem": "hdfs.fsnamesystem",
    "dfs.FSDataset": "hdfs.fsdataset",
    "dfs.DataBlockScanner": "hdfs.datablockscanner",
}
_HDFS_BLOCK_RE = re.compile(r"(blk_-?\d+)")


class _HdfsAdapter:
    """Logs de Hadoop HDFS (DataNode/FSNamesystem). Formato: LogHub HDFS_2k
    y equivalentes — Tabla 8.11 del Informe. Sin ERROR/FATAL en las muestras
    observadas hasta ahora; WARN se trata como evento crítico (heurística,
    no ground truth — a diferencia de BGL, HDFS no trae una etiqueta de
    anomalía explícita por línea en el archivo crudo)."""

    nombre = "hdfs"

    def detectar(self, muestra: list) -> float:
        if not muestra:
            return 0.0
        return sum(1 for l in muestra if _HDFS_RE.match(l)) / len(muestra)

    def parsear_linea(self, linea: str) -> dict:
        m = _HDFS_RE.match(linea)
        if not m:
            return {"ip": None, "usuario": None, "servicio": "hdfs.otro",
                    "evento": "evento_normal", "intentos_fallidos": 0, "timestamp": None}
        fecha, hora, nivel, clase, msg = m.groups()
        ip_m = IP_RE.search(msg)
        blk_m = _HDFS_BLOCK_RE.search(msg)
        critico = nivel in ("WARN", "ERROR", "FATAL")
        timestamp = f"20{fecha[0:2]}-{fecha[2:4]}-{fecha[4:6]} {hora[0:2]}:{hora[2:4]}:{hora[4:6]}"
        return {
            "ip": ip_m.group(1) if ip_m else None,
            "usuario": blk_m.group(1) if blk_m else None,
            "servicio": _HDFS_CLASE_A_SERVICIO.get(clase, "hdfs.otro"),
            "evento": "evento_critico" if critico else "evento_normal",
            "intentos_fallidos": 1 if critico else 0,
            "timestamp": timestamp,
        }


_BGL_RE = re.compile(
    r"^(\S+)\s+(\d+)\s+(\d{4}\.\d{2}\.\d{2})\s+(\S+)\s+"
    r"(\d{4}-\d{2}-\d{2}-\d{2}\.\d{2}\.\d{2}\.\d+)\s+\S+\s+RAS\s+(\S+)\s+(\S+)\s+(.*)$"
)
_BGL_SUBSISTEMA_A_SERVICIO = {
    "KERNEL": "bgl.kernel",
    "APP": "bgl.app",
    "MMCS": "bgl.mmcs",
    "DISCOVERY": "bgl.discovery",
    "HARDWARE": "bgl.hardware",
}


class _BglAdapter:
    """Logs de BlueGene/L (supercomputador, RAS/kernel). Formato: LogHub
    BGL_2k y equivalentes — Tabla 8.11 del Informe. A diferencia de HDFS,
    BGL SÍ trae una etiqueta de anomalía real por línea: el primer campo
    es "-" para líneas no-alerta, y un código (APPREAD, KERNDTLB, etc.)
    para líneas de alerta — es la convención estándar del dataset (y la
    que usa la literatura de detección de anomalías sobre BGL), así que se
    usa directamente en vez de inferir criticidad por texto libre."""

    nombre = "bgl"

    def detectar(self, muestra: list) -> float:
        if not muestra:
            return 0.0
        return sum(1 for l in muestra if _BGL_RE.match(l)) / len(muestra)

    def parsear_linea(self, linea: str) -> dict:
        # El flag de alerta (ground truth) se lee del primer token de la
        # línea INDEPENDIENTEMENTE de si el resto matchea _BGL_RE. Algunas
        # variantes de línea (p. ej. "NULL DISCOVERY ..." en vez de
        # "RAS KERNEL INFO ...") no matchean el patrón completo, y leer el
        # flag solo del grupo capturado por un match exitoso perdería esas
        # alertas como falso negativo si alguna vez tienen flag != "-"
        # (hallazgo 24-ago-2026, verificado: en BGL_2k.log da 0 casos, pero
        # no hay garantía de que valga también para archivos BGL más
        # grandes).
        partes = linea.split(None, 1)
        flag = partes[0] if partes else None
        es_alerta = flag is not None and flag != "-"
        m = _BGL_RE.match(linea)
        if not m:
            return {"ip": None, "usuario": None, "servicio": "bgl.otro",
                    "evento": "evento_critico" if es_alerta else "evento_normal",
                    "intentos_fallidos": 1 if es_alerta else 0, "timestamp": None}
        _flag, _epoch, _fecha, nodo, ts_legible, subsistema, _severidad, msg = m.groups()
        ip_m = IP_RE.search(msg)
        return {
            "ip": ip_m.group(1) if ip_m else None,
            "usuario": nodo,
            "servicio": _BGL_SUBSISTEMA_A_SERVICIO.get(subsistema, "bgl.otro"),
            "evento": "evento_critico" if es_alerta else "evento_normal",
            "intentos_fallidos": 1 if es_alerta else 0,
            "timestamp": ts_legible,
        }


# ---------------------------------------------------------------------------
# Adaptador CSV/TSV genérico (guiado por nombres de columna)
# ---------------------------------------------------------------------------
# A diferencia de los adaptadores de HDFS y BGL, este NO está atado a un
# dataset: se guía por los NOMBRES DE LAS COLUMNAS de la cabecera, así que
# un mismo código cubre exportaciones CSV de Zeek (UWF-ZeekDataFall22,
# Tabla 8.11 del Informe), Suricata, firewalls y SIEMs. Agregar un esquema
# nuevo es sumar sinónimos a los diccionarios de abajo, no escribir otro
# adaptador.
#
# Diferencia estructural respecto de los otros formatos: un log de FLUJOS
# describe una conversación entre DOS puntas (origen y destino), no un
# evento de una sola máquina. Ver `aggregate_logs` para cómo se agregan
# ambas.

_CSV_DELIMITADORES = (",", ";", "\t", "|")

# Sinónimos por campo, en minúsculas. El orden importa: gana el primero que
# aparezca en la cabecera.
_CSV_COLUMNAS = {
    "ip_origen": ("src_ip_zeek", "id.orig_h", "src_ip", "source_ip", "srcip", "orig_h",
                  "ip_origen", "client_ip", "src_addr", "source", "src"),
    "ip_destino": ("dest_ip_zeek", "id.resp_h", "dest_ip", "dst_ip", "destination_ip",
                   "dstip", "resp_h", "ip_destino", "dest_addr", "destination", "dst"),
    "puerto_destino": ("dest_port_zeek", "id.resp_p", "dest_port", "dst_port", "dstport",
                       "resp_p", "puerto_destino", "destination_port"),
    "servicio": ("service", "servicio", "app_proto", "application", "app"),
    "protocolo": ("proto", "protocol", "transport"),
    "timestamp": ("datetime", "@timestamp", "timestamp", "time", "fecha", "date_time"),
    "timestamp_epoch": ("ts", "epoch", "unix_time", "start_time"),
    "estado_conexion": ("conn_state", "state", "estado", "tcp_flags"),
    "identificador": ("uid", "community_id", "flow_id", "session_id", "id"),
    # Etiqueta de anomalía (ground truth), por prioridad de especificidad.
    "etiqueta": ("label_tactic", "label", "label_binary", "attack", "is_attack",
                 "classification", "alert", "category", "etiqueta", "attack_cat"),
}

# Valores de una columna de etiqueta que significan "esto NO es un ataque".
# Todo lo demás se considera alerta -- conservador a propósito: es preferible
# marcar de más y que el LLM lo matice, a perder una anomalía real.
_CSV_ETIQUETAS_BENIGNAS = {
    "", "-", "0", "0.0", "false", "no", "none", "null", "nan", "n/a",
    "benign", "benigno", "normal", "background", "clean", "ok", "legitimate",
}

# Estados de conexión Zeek que denotan intento fallido / conexión rechazada o
# nunca establecida -- la señal de anomalía cuando el CSV no trae etiqueta.
_CSV_ESTADOS_FALLIDOS = {"REJ", "S0", "RSTO", "RSTR", "RSTOS0", "RSTRH", "SH", "SHR", "OTH"}


class _CsvAdapter:
    """CSV/TSV con cabecera, mapeado por nombre de columna.

    A diferencia de los otros adaptadores, este es CON ESTADO: necesita la
    cabecera del lote para interpretar cada fila, y `parsear_linea()` recibe
    las líneas de a una sin contexto. Por eso `_detectar_formato()` crea una
    instancia NUEVA por lote (ver `_ADAPTERS`), en vez de reutilizar un
    singleton de módulo: dos análisis concurrentes (p. ej. dos pestañas de
    la interfaz web) tendrían cabeceras distintas y se pisarían entre sí.
    """

    nombre = "csv"

    def __init__(self):
        self._delim = None
        self._mapa = {}
        self._cabecera = None
        self._linea_cabecera = None

    # -- detección --------------------------------------------------------
    @staticmethod
    def _partir(linea: str, delim: str) -> list:
        try:
            return next(csv.reader([linea], delimiter=delim))
        except Exception:
            return []

    @classmethod
    def _mapear(cls, cabecera: list) -> dict:
        """columna lógica -> índice en la fila, según los sinónimos conocidos."""
        normalizadas = [c.strip().strip('"').lower() for c in cabecera]
        mapa = {}
        for campo, sinonimos in _CSV_COLUMNAS.items():
            for sin in sinonimos:
                if sin in normalizadas:
                    mapa[campo] = normalizadas.index(sin)
                    break
        return mapa

    def detectar(self, muestra: list) -> float:
        if len(muestra) < 2:
            return 0.0
        mejor_conf, mejor_cfg = 0.0, None
        for delim in _CSV_DELIMITADORES:
            cabecera = self._partir(muestra[0], delim)
            if len(cabecera) < 3:
                continue
            mapa = self._mapear(cabecera)
            # Sin al menos una columna de IP reconocida no reclamamos el
            # formato: el fallback auth-log al menos saca IPs por regex del
            # texto libre, que es mejor que un resumen vacío.
            if "ip_origen" not in mapa and "ip_destino" not in mapa:
                continue
            filas = muestra[1:]
            ok = sum(1 for l in filas if len(self._partir(l, delim)) == len(cabecera))
            conf = ok / len(filas)
            if conf > mejor_conf:
                mejor_conf, mejor_cfg = conf, (delim, cabecera, mapa)
        if mejor_cfg and mejor_conf >= _UMBRAL_CONFIANZA:
            self._delim, self._cabecera, self._mapa = mejor_cfg
            self._linea_cabecera = muestra[0]
        return mejor_conf

    # -- parseo -----------------------------------------------------------
    def _valor(self, fila: list, campo: str):
        i = self._mapa.get(campo)
        if i is None or i >= len(fila):
            return None
        v = fila[i].strip()
        return v or None

    def _es_alerta(self, fila: list) -> bool:
        etiqueta = self._valor(fila, "etiqueta")
        if etiqueta is not None:
            return etiqueta.strip().lower() not in _CSV_ETIQUETAS_BENIGNAS
        estado = self._valor(fila, "estado_conexion")
        if estado is not None:
            return estado.strip().upper() in _CSV_ESTADOS_FALLIDOS
        return False

    def parsear_linea(self, linea: str):
        # La cabecera no es un evento: devolver None hace que aggregate_logs
        # la descarte y no la cuente en total_lineas.
        if self._linea_cabecera is not None and linea == self._linea_cabecera:
            return None
        fila = self._partir(linea, self._delim or ",")
        if not fila:
            return None

        servicio = self._valor(fila, "servicio") or self._valor(fila, "protocolo") or "desconocido"
        puerto = self._valor(fila, "puerto_destino")
        if puerto:
            servicio = f"{servicio}:{puerto}"

        # El timestamp legible se prefiere al epoch: el `ts` de estas
        # exportaciones suele venir en notación científica (p. ej.
        # "1.664883645900091E9", artefacto de Spark/Parquet), que float()
        # parsea pero int() no.
        timestamp = self._valor(fila, "timestamp")
        if timestamp is None:
            epoch = self._valor(fila, "timestamp_epoch")
            if epoch:
                try:
                    timestamp = datetime.fromtimestamp(
                        float(epoch), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, OverflowError, OSError):
                    timestamp = None

        alerta = self._es_alerta(fila)
        return {
            "ip": self._valor(fila, "ip_origen"),
            "ip_destino": self._valor(fila, "ip_destino"),
            # Mismo criterio que blk_ en HDFS o el id de nodo en BGL: el
            # "actor u objeto" de la línea. En un log de flujos es el id de
            # conexión, no una persona.
            "usuario": self._valor(fila, "identificador"),
            "servicio": servicio,
            "evento": "evento_critico" if alerta else "evento_normal",
            "intentos_fallidos": 1 if alerta else 0,
            "timestamp": timestamp,
            "etiqueta": self._valor(fila, "etiqueta"),
        }


# CLASES, no instancias: `_detectar_formato` crea una por lote. El
# adaptador CSV guarda la cabecera del lote en el objeto, así que un
# singleton compartido haría que dos análisis simultáneos (dos pestañas de
# la interfaz web, que FastAPI atiende en hilos distintos) se pisaran la
# cabecera entre sí. Instanciar por lote cuesta nada y elimina el problema.
_ADAPTERS = [_HdfsAdapter, _BglAdapter, _CsvAdapter]
_ADAPTER_AUTH_LOG = _AuthLogAdapter


def _detectar_formato(lineas: list):
    """Elige el adaptador con mayor confianza sobre una muestra del lote.
    Si ninguno supera el umbral, cae al adaptador auth-log (comportamiento
    original) — así un formato no reconocido no pierde total_lineas/ips
    como antes, aunque servicio/evento queden en sus valores por defecto."""
    muestra = lineas[:_TAMANO_MUESTRA]
    mejor, mejor_confianza = None, 0.0
    for clase in _ADAPTERS:
        adapter = clase()
        confianza = adapter.detectar(muestra)
        if confianza > mejor_confianza:
            mejor, mejor_confianza = adapter, confianza
    if mejor is not None and mejor_confianza >= _UMBRAL_CONFIANZA:
        return mejor
    return _ADAPTER_AUTH_LOG()


def _registrar_ip(por_ip: dict, ip: str, info: dict, rol: str) -> None:
    """Suma una aparición de `ip` al agregado, indicando si fue como origen
    o como destino del registro.

    En logs de flujos (CSV de Zeek y similares) cada línea nombra DOS IPs.
    Ambas entran al agregado -- así las dos quedan cubiertas por la
    corroboración de reputación y visibles para el LLM --, pero
    `intentos_fallidos` se acredita SOLO al origen: en un flujo fallido el
    actor es quien inicia, no quien lo recibe. Los contadores por rol dejan
    ver la diferencia entre "esta IP escanea" y "esta IP es escaneada", que
    el conteo plano `n_eventos` no distingue.
    """
    d = por_ip.setdefault(ip, {"intentos_fallidos": 0, "usuarios": set(),
                               "servicios": set(), "n_eventos": 0,
                               "n_como_origen": 0, "n_como_destino": 0})
    d["n_eventos"] += 1
    d["n_como_origen" if rol == "origen" else "n_como_destino"] += 1
    if rol == "origen":
        d["intentos_fallidos"] += info["intentos_fallidos"]
        if info["usuario"]:
            d["usuarios"].add(info["usuario"])
    d["servicios"].add(info["servicio"])


def aggregate_logs(raw: str) -> dict:
    """Fachada de compatibilidad: devuelve el resumen v1 del lote.

    Es el punto donde la migración se activa o se revierte. Según
    `LOG_PREPROCESSING_ENGINE`:

    - ``v1`` (por defecto): corre el agregador original de este módulo, sin
      cambios de comportamiento.
    - ``v2``: corre la tubería de `src/preprocessing/` y **deriva** los
      campos v1 desde su agregación, sin volver a parsear.

    La bandera existe para poder comparar los dos motores sobre las mismas
    entradas y para volver atrás sin tocar código si algo regresiona (§12 y
    §13 del plan). No debe pasar a ``v2`` hasta que la Fase 13 valide la
    migración completa.
    """
    from src.config import LOG_PREPROCESSING_ENGINE

    if LOG_PREPROCESSING_ENGINE == "v2":
        from src.preprocessing.aggregation import derivar_v1
        from src.preprocessing.pipeline import preprocesar
        return derivar_v1(preprocesar(raw))
    return aggregate_logs_v1(raw)


def aggregate_logs_v1(raw: str) -> dict:
    """Preprocesa TODO el lote de forma determinística (sin LLM). Detecta
    el formato una vez por lote y usa el adaptador correspondiente para
    cada línea.

    Un adaptador puede devolver None por una línea que no es un evento (la
    cabecera de un CSV, p. ej.); esas líneas se descartan y no cuentan en
    `total_lineas`.
    """
    lineas = [l for l in raw.splitlines() if l.strip()]
    adapter = _detectar_formato(lineas)
    servicios, eventos, por_ip, etiquetas = {}, {}, {}, {}
    timestamps = []
    n_registros = 0
    for ln in lineas:
        info = adapter.parsear_linea(ln)
        if info is None:
            continue
        n_registros += 1
        servicios[info["servicio"]] = servicios.get(info["servicio"], 0) + 1
        eventos[info["evento"]] = eventos.get(info["evento"], 0) + 1
        etiqueta = info.get("etiqueta")
        if etiqueta:
            etiquetas[etiqueta] = etiquetas.get(etiqueta, 0) + 1
        if info.get("timestamp"):
            timestamps.append(info["timestamp"])
        if info["ip"]:
            _registrar_ip(por_ip, info["ip"], info, "origen")
        if info.get("ip_destino") and info["ip_destino"] != info["ip"]:
            _registrar_ip(por_ip, info["ip_destino"], info, "destino")
    por_ip_ser = {ip: {"intentos_fallidos": v["intentos_fallidos"],
                       "usuarios_objetivo": sorted(v["usuarios"]),
                       "servicios": sorted(v["servicios"]),
                       "n_eventos": v["n_eventos"],
                       "n_como_origen": v["n_como_origen"],
                       "n_como_destino": v["n_como_destino"]} for ip, v in por_ip.items()}
    ips = sorted(por_ip_ser, key=lambda i: por_ip_ser[i]["n_eventos"], reverse=True)
    resumen = {"formato_detectado": adapter.nombre,
               "total_lineas": n_registros,
               "servicios": servicios, "eventos": eventos,
               "ventana_temporal": {"inicio": timestamps[0] if timestamps else None,
                                    "fin": timestamps[-1] if timestamps else None},
               "n_ips_distintas": len(ips),
               "ips_distintas": ips,
               "por_ip": por_ip_ser}
    # Solo aparece si el formato traía una columna de etiqueta (ground truth
    # del dataset, p. ej. label_tactic de UWF-ZeekDataFall22 con tácticas
    # MITRE ATT&CK). Los formatos sin etiquetar no ensucian el resumen.
    if etiquetas:
        resumen["etiquetas"] = etiquetas
    return resumen


def firma_lote(summary: dict, metadatos: dict | None = None) -> str:
    """Firma compacta del lote para embeddings/memoria (no el blob crudo).

    **Va prefijada por versión de esquema** (Fase 11 del plan). Una firma v1
    y una v2 describen el mismo lote con vocabularios distintos, así que sus
    embeddings no son comparables: buscar los patrones más parecidos
    mezclando ambas devolvería vecinos sin sentido. El prefijo hace que una
    búsqueda v2 no recupere firmas v1 por casualidad, y deja el dato
    visible en la propia cadena para poder auditar la memoria.

    Con `metadatos` (el resumen v2) la firma incorpora además decoders,
    productos, severidades y cobertura, que son las señales que el esquema
    nuevo aporta y que el v1 no tenía cómo expresar.
    """
    svc = ",".join(f"{k}:{v}" for k, v in summary.get("servicios", {}).items())
    ev = ",".join(f"{k}:{v}" for k, v in summary.get("eventos", {}).items())
    base = (f"lineas={summary.get('total_lineas')} "
            f"ips={summary.get('n_ips_distintas')} "
            f"servicios=[{svc}] eventos=[{ev}]")

    if not metadatos:
        return f"v1|{base}"

    def _dist(clave: str) -> str:
        return ",".join(f"{k}:{v}" for k, v in (metadatos.get(clave) or {}).items())

    cobertura = (metadatos.get("parsing") or {}).get("coverage")
    return (
        f"v2|{base} "
        f"eventos_totales={metadatos.get('total_eventos')} "
        f"decoders=[{_dist('decoder_distribution')}] "
        f"productos=[{_dist('product_distribution')}] "
        f"severidades=[{_dist('severity_distribution')}] "
        f"categorias=[{_dist('event_categories')}] "
        f"cobertura={cobertura}"
    )
