"""Mapeo de campos arbitrarios al esquema normalizado (Fase 4 del plan).

Los decodificadores estructurales (JSON, CSV, `clave=valor`, CEF, LEEF)
producen todos lo mismo: un diccionario de pares nombre/valor. Lo que
cambia entre ellos es cómo se llega a ese diccionario, no cómo se
interpreta. Este módulo concentra la interpretación, así que agregar un
formato nuevo no obliga a repetir la tabla de sinónimos.

Generaliza la tabla que el adaptador CSV del esquema v1 tenía cableada, y
agrega los nombres de Elastic Common Schema, Zeek, Suricata y CEF/LEEF.

Dos reglas que sostienen el principio de no pérdida:

- Lo que **no** se reconoce no se descarta: vuelve en `attributes`, con su
  nombre original.
- Un valor vacío o `-` (el "sin dato" de Zeek y de los access logs) se
  trata como ausente, no como el texto `"-"`.
"""

import re
from datetime import datetime, timezone

# Nombre canónico -> sinónimos, en minúsculas. El orden importa: gana el
# primero que aparezca en los datos.
MAPA_CAMPOS: dict[str, tuple[str, ...]] = {
    # El orden ES la prioridad: los nombres legibles ganan a los epoch. En
    # el CSV de UWF-ZeekDataFall22 conviven `datetime` (ISO-8601) y `ts`
    # (epoch en notación científica de Spark); se prefiere el primero.
    "timestamp": ("timestamp", "@timestamp", "datetime", "date_time", "time",
                  "eventtime", "fecha", "rt", "ts", "epoch", "unix_time",
                  "start_time"),
    "source_ip": ("src_ip_zeek", "id.orig_h", "src_ip", "source_ip", "sourceaddress",
                  "srcip", "orig_h", "ip_origen", "client_ip", "src_addr", "src",
                  "source.ip", "source"),
    "source_port": ("src_port_zeek", "id.orig_p", "src_port", "source_port",
                    "sourceport", "srcport", "orig_p", "puerto_origen", "source.port"),
    "source_host": ("src_host", "source_host", "sourcehostname", "hostname", "host",
                    "shost", "source.domain"),
    "source_user": ("user", "username", "usuario", "src_user", "source_user",
                    "suser", "account", "user.name", "login"),
    "destination_ip": ("dest_ip_zeek", "id.resp_h", "dest_ip", "dst_ip",
                       "destination_ip", "destinationaddress", "dstip", "resp_h",
                       "ip_destino", "dest_addr", "destination.ip", "dst"),
    "destination_port": ("dest_port_zeek", "id.resp_p", "dest_port", "dst_port",
                         "destination_port", "destinationport", "dstport", "resp_p",
                         "puerto_destino", "destination.port"),
    "destination_host": ("dest_host", "destination_host", "destinationhostname",
                         "dhost", "destination.domain"),
    "destination_user": ("dest_user", "destination_user", "duser", "target_user"),
    "service_name": ("service", "servicio", "app_proto", "application", "app",
                     "service.name"),
    "process_name": ("process", "process_name", "proc", "program", "appname",
                     "process.name", "sproc"),
    "process_id": ("pid", "process_id", "procid", "process.pid"),
    "protocol": ("proto", "protocol", "transport", "network.transport"),
    "event_category": ("category", "categoria", "event_type", "event.category",
                       "cat", "type"),
    "event_action": ("action", "accion", "event_action", "event.action", "act",
                     "operation"),
    "event_outcome": ("outcome", "result", "resultado", "status", "event.outcome",
                      "conn_state", "success"),
    "severity": ("severity", "severidad", "level", "loglevel", "log.level",
                 "priority", "sev"),
    "event_code": ("event_id", "eventid", "event_code", "code", "signature_id",
                   "sid", "deviceeventclassid"),
    "product": ("product", "producto", "device_product", "deviceproduct",
                "observer.product"),
    "vendor": ("vendor", "device_vendor", "devicevendor", "observer.vendor"),
    "version": ("version", "device_version", "deviceversion", "observer.version"),
    "message": ("message", "mensaje", "msg", "content", "text", "description",
                "name", "event.original"),
}

# Índice inverso: sinónimo -> (campo canónico, prioridad). La prioridad es
# la posición dentro de la tupla de sinónimos, así que cuando dos columnas
# del mismo registro mapean al mismo campo gana la declarada antes -- no la
# que aparezca primero en los datos, que sería un criterio arbitrario y
# dependiente del orden de las columnas del archivo.
_INDICE_SINONIMOS: dict[str, tuple[str, int]] = {}
for _campo, _sinonimos in MAPA_CAMPOS.items():
    for _prioridad, _s in enumerate(_sinonimos):
        _INDICE_SINONIMOS.setdefault(_s, (_campo, _prioridad))

# Valores que significan "sin dato" en los formatos habituales.
_VACIOS = {"", "-", "null", "none", "n/a", "nan", "(empty)"}

# Columnas cuyo valor se conserva AUNQUE parezca vacío. Son las de
# etiqueta de los datasets: en UWF-ZeekDataFall22, el tráfico benigno se
# marca con `label_tactic=none`, y `none` está en `_VACIOS`. Descartarlo
# dejaba sin etiqueta justamente a las filas negativas, de modo que la
# evaluación solo habría visto ataques -- un sesgo que habría inflado
# cualquier métrica calculada sobre ese ground truth.
_CLAVES_PRESERVAR_VACIO = {"label", "label_tactic", "label_technique",
                           "label_binary", "etiqueta", "class"}

IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")

# Campos que deben terminar como entero.
_CAMPOS_ENTEROS = ("source_port", "destination_port")


def es_vacio(valor) -> bool:
    if valor is None:
        return True
    if isinstance(valor, str):
        return valor.strip().lower() in _VACIOS
    return False


def normalizar_nombre(nombre: str) -> str:
    """Un nombre de columna/clave a su forma comparable."""
    return nombre.strip().strip('"').strip().lower()


def _a_entero(valor):
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def normalizar_timestamp(valor) -> str | None:
    """Devuelve un timestamp legible, o `None` si no se pudo interpretar.

    Acepta epoch en segundos, incluida la notación científica que producen
    los exports de Spark (`1.664883645900091E9`), donde `int()` fallaría.
    Un valor ya legible se devuelve tal cual: no se reformatea, para no
    perder la precisión ni la zona horaria del original.
    """
    if es_vacio(valor):
        return None
    texto = str(valor).strip()
    # ¿Epoch numérico?
    try:
        numero = float(texto)
    except ValueError:
        return texto
    # Rango razonable de epoch en segundos (1973..2286).
    if 1e8 <= numero <= 1e10:
        return datetime.fromtimestamp(numero, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S")
    # Epoch en milisegundos.
    if 1e11 <= numero <= 1e13:
        return datetime.fromtimestamp(numero / 1000, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S")
    return texto


def mapear_campos(datos: dict, max_no_mapeados: int | None = None
                  ) -> tuple[dict, dict]:
    """Separa `datos` en (campos canónicos, atributos no reconocidos).

    Cuando dos claves del mismo registro mapean al mismo campo canónico,
    gana la que esté declarada antes en `MAPA_CAMPOS`, no la que aparezca
    primero en los datos: el orden de las columnas de un archivo es
    arbitrario y no debería decidir qué dato se conserva. El perdedor va a
    `attributes` con su nombre original, así que no se pierde nada.

    Los valores vacíos se omiten de ambos diccionarios: no aportan y
    ensucian el prompt del LLM.
    """
    canonicos: dict = {}
    prioridades: dict[str, int] = {}
    # Valor y nombre ORIGINALES de cada campo ganador: si después llega un
    # sinónimo de mejor prioridad, el desplazado vuelve a `attributes` tal
    # como vino, no convertido. Guardar la versión convertida perdería el
    # dato de origen, que es justo lo que el principio de no pérdida evita.
    originales: dict[str, tuple[str, object]] = {}
    atributos: dict = {}

    for clave, valor in datos.items():
        nombre = normalizar_nombre(str(clave))
        if es_vacio(valor) and nombre not in _CLAVES_PRESERVAR_VACIO:
            continue
        entrada = _INDICE_SINONIMOS.get(nombre)
        if entrada is None:
            atributos[str(clave)] = valor
            continue
        campo, prioridad = entrada

        if campo in canonicos and prioridades[campo] <= prioridad:
            # Ya hay un sinónimo mejor o igual: este se conserva aparte.
            atributos[str(clave)] = valor
            continue

        convertido = _convertir(campo, valor)
        if convertido is None:
            # No se pudo convertir al tipo del campo (p. ej. un puerto que
            # no es numérico): se guarda crudo en vez de descartarlo.
            atributos[str(clave)] = valor
            continue

        if campo in originales:
            # Este sinónimo tiene mejor prioridad: desplaza al anterior,
            # que pasa a atributos con su nombre y su valor originales.
            clave_anterior, valor_anterior = originales[campo]
            atributos[clave_anterior] = valor_anterior

        canonicos[campo] = convertido
        prioridades[campo] = prioridad
        originales[campo] = (str(clave), valor)

    if max_no_mapeados is not None and len(atributos) > max_no_mapeados:
        conservados = dict(list(sorted(atributos.items()))[:max_no_mapeados])
        conservados["_atributos_omitidos"] = len(atributos) - max_no_mapeados
        atributos = conservados

    return canonicos, atributos


def _convertir(campo: str, valor):
    """Convierte al tipo del campo canónico. `None` si no se pudo."""
    if campo in _CAMPOS_ENTEROS:
        return _a_entero(valor)
    if campo == "timestamp":
        return normalizar_timestamp(valor)
    return str(valor).strip()


def ips_del_texto(texto: str) -> list[str]:
    """IPv4 encontradas en texto libre, en orden de aparición y sin repetir."""
    vistas: list[str] = []
    for ip in IP_RE.findall(texto):
        if ip not in vistas:
            vistas.append(ip)
    return vistas
