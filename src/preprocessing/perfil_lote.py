"""Perfil determinístico del lote, grupos de evidencia y contenido para el prompt.

NODEX final, Fase A (M1, M2 y M6). Todo se calcula sin LLM, a partir de los
eventos ya normalizados, y nunca a partir de una etiqueta del dataset.

- `perfil_lote` (M2): lo que el resumen por IP ocultaba. En logs de red, por
  origen: conexiones, destinos y puertos distintos, ventana y estados;
  `senales` genéricas (barrido de puertos, servicio o protocolo minoritario,
  inversión de rol), que deciden los flujos minoritarios; y un
  `contexto_descriptivo` (pares raros, transferencias atípicas) que describe el
  lote sin señalar nada (Fase A.1). En logs de texto con formato conocido:
  distribución de severidad y componente, y las líneas de severidad alta. Los
  umbrales están en `src/config.py`, con su justificación.
- `grupos_evidencia` (M6): grupos estables (G01, G02...) de registros que
  describen lo mismo. Red: (origen, destino, protocolo, servicio o puerto); un
  barrido de puertos es UN grupo por (origen, destino, protocolo). Texto:
  (componente, severidad, plantilla del mensaje), con los nodos afectados como
  atributo (Fase A.1). El auditor puede citar un grupo en vez de enumerar sus
  uids, y `normalizar_d11` lo expande.
- `contenido_lote` (M1): lo que el triage lee del lote. En texto, las líneas
  (con tope y aviso de recorte). En red, las filas completas de los flujos
  minoritarios. La etiqueta de alerta de BGL, si una línea la trajera, se
  retira antes de entregarla.

Los uids son los mismos que `construir_evidencia` asigna al catálogo
(`uid_de_evento`), así que un grupo y el catálogo hablan de los mismos
registros.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

#: Severidades que el log declara graves (mismo criterio que la agregación).
_SEVERIDADES_ALTAS = {"fatal", "error", "warning", "warn", "critical", "crit",
                      "severe", "alert", "emerg", "failure"}
#: Campo de alerta de BGL (primer token): `-` o un código en mayúsculas.
_FLAG_BGL = re.compile(r"-|[A-Z][A-Z0-9_]*")
#: Líneas de severidad alta que el perfil identifica por uid (el texto está en
#: el contenido del lote). 30 cubre de sobra un lote típico y acota el resumen.
_TOPE_UIDS_SEVERIDAD = 30
#: Campos de red que se copian a las filas completas, en este orden.
_CAMPOS_FILA = ("duration", "orig_bytes", "resp_bytes", "history", "orig_pkts", "resp_pkts")


# --- identidad de los registros ---------------------------------------------

def uids_originales(eventos) -> set[str]:
    return {str(e.attributes.get("uid") or e.attributes.get("flow_id")).strip()
            for e in eventos if e.attributes.get("uid") or e.attributes.get("flow_id")}


def uid_de_evento(evento, indice: int, originales: set[str]) -> str:
    """UID del registro en el catálogo: el `uid`/`flow_id` original o uno
    determinista por posición (1-indexado), sin chocar con los originales."""
    uid = evento.attributes.get("uid") or evento.attributes.get("flow_id")
    if uid:
        return str(uid).strip()
    uid = f"log_record_{indice:06d}"
    while uid in originales:
        uid = "record_" + uid
    return uid


def _uids(eventos) -> list[str]:
    originales = uids_originales(eventos)
    return [uid_de_evento(e, i, originales) for i, e in enumerate(eventos, 1)]


# --- utilidades -------------------------------------------------------------

def _numero(valor):
    try:
        x = float(valor)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _bytes_totales(evento):
    o = _numero(evento.attributes.get("orig_bytes"))
    r = _numero(evento.attributes.get("resp_bytes"))
    if o is None and r is None:
        return None
    return (o or 0.0) + (r or 0.0)


def _percentil(valores: list[float], p: float) -> float:
    """Percentil por rango más cercano (determinístico, sin interpolar)."""
    ordenados = sorted(valores)
    rango = max(1, math.ceil(p / 100.0 * len(ordenados)))
    return ordenados[min(rango, len(ordenados)) - 1]


def segundos_de_evento(evento):
    """Marca de tiempo en segundos (epoch): `ts` de Zeek o el timestamp ISO; None si no hay."""
    from datetime import datetime, timezone
    ts = _numero(evento.attributes.get("ts"))
    if ts is not None:
        return ts
    try:
        momento = datetime.fromisoformat(str(evento.timestamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.timestamp()


def _ventana(eventos) -> str:
    marcas = [s for e in eventos if (s := segundos_de_evento(e)) is not None]
    if len(marcas) < 2:
        return "un instante"
    return f"{max(marcas) - min(marcas):.1f} s"


def es_lote_de_red(eventos) -> bool:
    """La mayoría de los eventos trae origen y destino: es un log de red."""
    if not eventos:
        return False
    con_par = sum(1 for e in eventos if e.source_ip and e.destination_ip)
    return con_par / len(eventos) >= 0.5


def _servicio_o_puerto(e) -> str:
    servicio = (e.service_name or "").strip()
    if servicio and servicio != "-":
        return servicio
    return f"puerto:{e.destination_port}" if e.destination_port is not None else "sin_servicio"


def plantilla_mensaje(mensaje: str) -> str:
    """Mensaje sin los valores que cambian entre repeticiones del mismo evento."""
    texto = re.sub(r"0x[0-9a-fA-F]+", "<hex>", mensaje or "")
    texto = re.sub(r"\d+", "<n>", texto)
    return re.sub(r"\s+", " ", texto).strip()[:120]


def linea_sin_etiqueta(evento) -> str:
    """Línea de texto para el prompt. Retira el campo de alerta de BGL si viniera."""
    from src.config import LOG_PRESERVE_RAW
    if not LOG_PRESERVE_RAW:
        from src.preprocessing.aggregation import _redactar_mensaje
        return _redactar_mensaje(evento.message, evento)
    linea = (evento.raw or evento.message or "").split("\n", 1)[0]
    if evento.attributes.get("perfil") == "bgl":
        partes = linea.split(None, 1)
        if len(partes) == 2 and _FLAG_BGL.fullmatch(partes[0]):
            return partes[1]
    return linea


def fila_de_red(evento, uid: str) -> dict:
    fila = {"uid": uid, "timestamp": evento.timestamp, "source_ip": evento.source_ip,
            "source_port": evento.source_port, "destination_ip": evento.destination_ip,
            "destination_port": evento.destination_port, "protocol": evento.protocol,
            "service": evento.service_name, "conn_state": evento.event_outcome}
    for campo in _CAMPOS_FILA:
        valor = evento.attributes.get(campo)
        if valor not in (None, "", "-"):
            fila[campo] = valor
    return {k: v for k, v in fila.items() if v is not None}


# --- grupos (M6) -------------------------------------------------------------

def _clave_grupo_red(e, barridos: set) -> tuple:
    base = (e.source_ip, e.destination_ip, (e.protocol or "-").lower())
    if base in barridos:
        return base + ("barrido_de_puertos",)
    return base + (_servicio_o_puerto(e),)


def _clave_grupo_texto(e) -> tuple:
    """(componente, severidad, plantilla). Fase A.1: el nodo ya no es parte de la clave.

    En BGL casi cada línea viene de un nodo distinto: con el nodo en la clave, 20
    líneas daban 15 y 20 grupos, y los volcados de memoria repetidos en muchos
    nodos no se agrupaban. Los nodos quedan como atributo del grupo."""
    componente = (e.service_name or e.attributes.get("bgl_subsistema") or e.process_name or "-")
    return (componente, e.severity or "-", plantilla_mensaje(e.message))


def _barridos(eventos, minimo: int) -> dict:
    puertos = defaultdict(set)
    for e in eventos:
        if e.source_ip and e.destination_ip and e.destination_port is not None:
            puertos[(e.source_ip, e.destination_ip, (e.protocol or "-").lower())].add(e.destination_port)
    return {k: v for k, v in puertos.items() if len(v) >= minimo}


def construir_grupos(eventos, uids: list[str], red: bool, barridos: dict) -> tuple[list[dict], list[str]]:
    """Grupos en orden de primera aparición. Devuelve (grupos, group_id por evento)."""
    claves: dict[tuple, dict] = {}
    por_evento = []
    for e, uid in zip(eventos, uids):
        clave = _clave_grupo_red(e, set(barridos)) if red else _clave_grupo_texto(e)
        grupo = claves.get(clave)
        if grupo is None:
            grupo = {"group_id": f"G{len(claves) + 1:02d}", "clave": clave, "uids": [], "nodos": []}
            claves[clave] = grupo
        grupo["uids"].append(uid)
        if not red and e.source_host and e.source_host not in grupo["nodos"]:
            grupo["nodos"].append(e.source_host)
        por_evento.append(grupo["group_id"])
    nombres = (("origen", "destino", "protocolo", "servicio_o_puerto") if red
               else ("componente", "severidad", "plantilla"))
    grupos = []
    for g in claves.values():
        grupo = {"group_id": g["group_id"], "clave": dict(zip(nombres, g["clave"])),
                 "conteo": len(g["uids"]), "uids": g["uids"]}
        if not red:
            grupo.update(nodos=g["nodos"], n_nodos=len(g["nodos"]))
        grupos.append(grupo)
    return grupos, por_evento


# --- perfil (M2) --------------------------------------------------------------

def _perfil_red(eventos, uids, grupos, grupo_de, barridos, cfg) -> tuple[dict, list[dict]]:
    n = len(eventos)
    por_origen: dict[str, dict] = {}
    for e in eventos:
        if not e.source_ip:
            continue
        d = por_origen.setdefault(e.source_ip, {"conexiones": 0, "destinos": set(), "puertos": set(),
                                                "marcas": [], "estados": Counter()})
        d["conexiones"] += 1
        if e.destination_ip:
            d["destinos"].add(e.destination_ip)
        if e.destination_port is not None:
            d["puertos"].add(e.destination_port)
        if e.timestamp:
            d["marcas"].append(e.timestamp)
        d["estados"][e.event_outcome or "-"] += 1
    ordenados = sorted(por_origen.items(), key=lambda kv: (-kv[1]["conexiones"], kv[0]))
    detalle = {ip: {"conexiones": d["conexiones"], "destinos_distintos": len(d["destinos"]),
                    "puertos_destino_distintos": len(d["puertos"]),
                    "primer_registro": min(d["marcas"]) if d["marcas"] else None,
                    "ultimo_registro": max(d["marcas"]) if d["marcas"] else None,
                    "estados": dict(d["estados"].most_common())}
               for ip, d in ordenados[:cfg["max_origenes"]]}

    marcadas: dict[int, set] = defaultdict(set)   # índice de evento -> motivos
    senales: dict = {}
    senales["barrido_de_puertos"] = [
        {"origen": k[0], "destino": k[1], "protocolo": k[2], "puertos_distintos": len(v),
         "conexiones": sum(1 for e in eventos if (e.source_ip, e.destination_ip, (e.protocol or "-").lower()) == k)}
        for k, v in sorted(barridos.items())]
    for i, e in enumerate(eventos):
        if (e.source_ip, e.destination_ip, (e.protocol or "-").lower()) in barridos:
            marcadas[i].add("barrido_de_puertos")

    descriptivo: dict = {}
    grupo_por_par = {}
    for i, e in enumerate(eventos):
        grupo_por_par.setdefault((e.source_ip, e.destination_ip), grupo_de[i])
    proporcionales = n >= cfg["min_filas"]
    if proporcionales:
        # Las filas de un barrido ya forman su propio grupo y su propia señal:
        # sus puertos no son "servicios minoritarios" (cada puerto escaneado
        # aparecería como uno, y la lista se llenaría de ruido).
        en_barrido = {i for i, e in enumerate(eventos)
                      if (e.source_ip, e.destination_ip, (e.protocol or "-").lower()) in barridos}
        resto = [(i, e) for i, e in enumerate(eventos) if i not in en_barrido]
        servicios = Counter(_servicio_o_puerto(e) for _, e in resto)
        protocolos = Counter((e.protocol or "-").lower() for _, e in resto)
        minoritarios = []
        for tipo, conteo, valor_de in (("servicio", servicios, _servicio_o_puerto),
                                       ("protocolo", protocolos, lambda e: (e.protocol or "-").lower())):
            for valor, c in sorted(conteo.items()):
                if c / n < cfg["umbral_minoritario"]:
                    minoritarios.append({"tipo": tipo, "valor": valor, "filas": c, "proporcion": round(c / n, 4)})
                    for i, e in resto:
                        if valor_de(e) == valor:
                            marcadas[i].add(f"{tipo}_minoritario")
        senales["servicio_o_protocolo_minoritario"] = minoritarios

        # Fase A.1: pares raros y transferencias atípicas son CONTEXTO DESCRIPTIVO, no
        # señales. En la prueba de desarrollo aparecían igual en lotes benignos y
        # maliciosos (con 300 filas de fondo, "≤ 2 filas" o "> p95" siempre marca algo),
        # así que no marcan filas para los flujos minoritarios.
        pares = Counter((e.source_ip, e.destination_ip) for e in eventos if e.source_ip and e.destination_ip)
        raros = sorted(p for p, c in pares.items() if c <= cfg["par_raro_max"])
        descriptivo["pares_raros"] = {"total": len(raros), "umbral_filas": cfg["par_raro_max"],
                                      "pares": [{"origen": a, "destino": b, "filas": pares[(a, b)],
                                                 "group_id": grupo_por_par.get((a, b))} for a, b in raros[:20]]}

        con_bytes = [(i, b) for i, e in enumerate(eventos) if (b := _bytes_totales(e)) is not None]
        if len(con_bytes) >= cfg["min_filas"]:
            umbral = _percentil([b for _, b in con_bytes], cfg["percentil"])
            atipicas = sorted(((i, b) for i, b in con_bytes if b > umbral and b > 0), key=lambda t: -t[1])
            descriptivo["transferencias_atipicas"] = {
                "percentil": cfg["percentil"], "umbral_bytes": umbral, "total": len(atipicas),
                "filas": [{"uid": uids[i], "bytes": b, "group_id": grupo_de[i]} for i, b in atipicas[:20]]}
    else:
        senales["nota"] = (f"Lote de {n} filas: la señal de servicio o protocolo minoritario y el contexto "
                           f"descriptivo (pares raros, percentil de bytes) requieren al menos {cfg['min_filas']}.")

    como_origen = Counter(e.source_ip for e in eventos if e.source_ip)
    como_destino = Counter(e.destination_ip for e in eventos if e.destination_ip)
    inversiones = []
    for ip in sorted(set(como_origen) & set(como_destino)):
        if como_origen[ip] > como_destino[ip]:
            servicios_ip = sorted({_servicio_o_puerto(e) for e in eventos if e.destination_ip == ip})
            inversiones.append({"ip": ip, "como_origen": como_origen[ip], "como_destino": como_destino[ip],
                                "servicios_como_destino": servicios_ip[:10]})
            for i, e in enumerate(eventos):
                if e.destination_ip == ip:
                    marcadas[i].add("inversion_de_rol")
    senales["inversion_de_rol"] = inversiones

    # B.1-3a: el MOTIVO FACTUAL de cada señal, por grupo (conteos del lote). Lo lee el
    # auditor reforzado; `contexto_contenido_lote` no lo muestra al triage ni al agente único.
    factuales: dict[str, list[str]] = defaultdict(list)
    motivos_de_grupo: dict[str, set] = defaultdict(set)
    for i, motivos in marcadas.items():
        motivos_de_grupo[grupo_de[i]] |= motivos
    inversion_por_ip = {inv["ip"]: inv for inv in inversiones}
    for g in grupos:
        gid, clave = g["group_id"], g["clave"]
        motivos = motivos_de_grupo.get(gid) or set()
        if "barrido_de_puertos" in motivos:
            filas = [e for e, gg in zip(eventos, grupo_de) if gg == gid]
            puertos = {e.destination_port for e in filas if e.destination_port is not None}
            factuales[gid].append(f"un mismo origen contactó {len(puertos)} puertos de destino distintos de un "
                                  f"mismo destino ({clave['protocolo']}) en {_ventana(filas)} "
                                  f"({len(filas)} conexiones)")
        if "servicio_minoritario" in motivos and proporcionales:
            c = servicios.get(clave["servicio_o_puerto"], 0)
            factuales[gid].append(f"el servicio/puerto {clave['servicio_o_puerto']} aparece en {c} de {n} filas del "
                                  f"lote ({c / n:.1%})" + (" (único flujo con ese servicio en el lote)" if c == 1 else ""))
        if "protocolo_minoritario" in motivos and proporcionales:
            c = protocolos.get(clave["protocolo"], 0)
            factuales[gid].append(f"el protocolo {clave['protocolo']} aparece en {c} de {n} filas del lote "
                                  f"({c / n:.1%})" + (f" (único flujo {clave['protocolo'].upper()} del lote)"
                                                       if c == 1 else ""))
        if "inversion_de_rol" in motivos and clave["destino"] in inversion_por_ip:
            inv = inversion_por_ip[clave["destino"]]
            factuales[gid].append(f"el destino de este grupo actúa como origen en {inv['como_origen']} filas del "
                                  f"lote y como destino solo en {inv['como_destino']}")

    perfil = {"tipo": "red", "filas": n,
              "protocolos": dict(Counter((e.protocol or "-").lower() for e in eventos).most_common()),
              "servicios": dict(Counter(_servicio_o_puerto(e) for e in eventos).most_common(15)),
              "estados": dict(Counter(e.event_outcome or "-" for e in eventos).most_common()),
              "por_origen": detalle, "origenes_omitidos": max(0, len(ordenados) - cfg["max_origenes"]),
              "senales": senales,
              # Fase A.1: describe el lote, no señala nada (ver arriba).
              "contexto_descriptivo": descriptivo}

    # Flujos minoritarios: los GRUPOS que contienen alguna fila señalada, con sus filas completas.
    motivos_por_grupo: dict[str, set] = defaultdict(set)
    for i, motivos in marcadas.items():
        motivos_por_grupo[grupo_de[i]] |= motivos
    indices_por_grupo = defaultdict(list)
    for i, g in enumerate(grupo_de):
        indices_por_grupo[g].append(i)
    # Orden de los grupos señalados: primero los de señales más específicas.
    prioridad = {"barrido_de_puertos": 0, "inversion_de_rol": 1,
                 "servicio_minoritario": 2, "protocolo_minoritario": 2}
    senalados = sorted((g for g in grupos if g["group_id"] in motivos_por_grupo),
                       key=lambda g: (min(prioridad.get(m, 9) for m in motivos_por_grupo[g["group_id"]]),
                                      g["group_id"]))
    # El tope de filas se reparte por turnos entre los grupos señalados: así un
    # barrido grande no deja fuera a los flujos minoritarios pequeños.
    tomadas = {g["group_id"]: [] for g in senalados}
    entregadas, ronda = 0, 0
    while entregadas < cfg["max_filas"]:
        avanzo = False
        for g in senalados:
            indices = indices_por_grupo[g["group_id"]]
            if ronda < len(indices) and entregadas < cfg["max_filas"]:
                tomadas[g["group_id"]].append(indices[ronda])
                entregadas += 1
                avanzo = True
        if not avanzo:
            break
        ronda += 1
    flujos, omitidas = [], 0
    for g in senalados:
        gid = g["group_id"]
        indices = sorted(tomadas[gid])
        omitidas += g["conteo"] - len(indices)
        flujos.append({"group_id": gid, "clave": g["clave"], "conteo": g["conteo"],
                       "motivos": sorted(motivos_por_grupo[gid]),
                       "motivos_factuales": factuales.get(gid, []),
                       "filas_omitidas": g["conteo"] - len(indices),
                       "filas": [fila_de_red(eventos[i], uids[i]) for i in indices]})
    perfil["flujos_minoritarios"] = {"grupos": len(flujos), "filas_entregadas": entregadas,
                                     "filas_omitidas": omitidas}
    return perfil, flujos


def _perfil_texto(eventos, uids, grupo_de, cfg) -> tuple[dict, list[dict]]:
    severidades = Counter(e.severity or "-" for e in eventos)
    componentes = Counter(e.service_name or e.attributes.get("bgl_subsistema") or e.process_name or "-"
                          for e in eventos)
    nodos = Counter(e.source_host for e in eventos if e.source_host)
    altas = [i for i, e in enumerate(eventos) if (e.severity or "").strip().lower() in _SEVERIDADES_ALTAS]
    # El perfil va dentro del resumen, que llega a todos los agentes: aquí solo
    # se identifican las líneas de severidad alta (uid, severidad, grupo). Su
    # texto ya está en el contenido del lote (M1) y en el catálogo de evidencia.
    # Con los mensajes, un HDFS de 2 000 líneas sumaba 14 000 caracteres.
    tope = min(cfg["max_filas"], _TOPE_UIDS_SEVERIDAD)
    perfil = {"tipo": "texto", "filas": len(eventos),
              "con_formato_reconocido": sum(1 for e in eventos if e.severity or e.service_name),
              "severidades": dict(severidades.most_common()),
              "componentes": dict(componentes.most_common(15)),
              "nodos": dict(nodos.most_common(10)), "nodos_distintos": len(nodos),
              "lineas_severidad_alta": {
                  "total": len(altas), "omitidas": max(0, len(altas) - tope),
                  "lineas": [{"uid": uids[i], "severidad": eventos[i].severity, "group_id": grupo_de[i]}
                             for i in altas[:tope]]}}
    return perfil, []


def _config():
    from src import config as c
    return {"min_puertos": c.PERFIL_MIN_PUERTOS_BARRIDO, "umbral_minoritario": c.PERFIL_UMBRAL_MINORITARIO,
            "par_raro_max": c.PERFIL_PAR_RARO_MAX_FILAS, "percentil": c.PERFIL_PERCENTIL_BYTES,
            "min_filas": c.PERFIL_MIN_FILAS_PERCENTIL, "max_filas": c.PERFIL_MAX_FILAS_MINORITARIAS,
            "max_origenes": c.PERFIL_MAX_ORIGENES, "max_lineas": c.TRIAGE_MAX_LINEAS,
            "max_chars": c.TRIAGE_MAX_CHARS}


def _contenido_texto(eventos, uids, cfg) -> dict:
    lineas, chars, recortado = [], 0, False
    for e, uid in zip(eventos, uids):
        texto = f"[{uid}] {linea_sin_etiqueta(e)}"
        if len(lineas) >= cfg["max_lineas"] or chars + len(texto) + 1 > cfg["max_chars"]:
            recortado = True
            break
        lineas.append(texto)
        chars += len(texto) + 1
    return {"tipo": "texto", "lineas": lineas, "total_lineas": len(eventos),
            "lineas_entregadas": len(lineas), "recortado": recortado,
            "topes": {"lineas": cfg["max_lineas"], "caracteres": cfg["max_chars"]}}


def analizar_lote(resultado) -> dict:
    """Perfil, grupos y contenido del lote. Devuelve un dict con las tres vistas."""
    cfg = _config()
    eventos = list(resultado.events)
    uids = _uids(eventos)
    red = es_lote_de_red(eventos)
    barridos = _barridos(eventos, cfg["min_puertos"]) if red else {}
    grupos, grupo_de = construir_grupos(eventos, uids, red, barridos)
    if red:
        perfil, flujos = _perfil_red(eventos, uids, grupos, grupo_de, barridos, cfg)
        contenido = {"tipo": "red", "flujos_minoritarios": flujos,
                     "filas_omitidas": perfil["flujos_minoritarios"]["filas_omitidas"],
                     "tope_filas": cfg["max_filas"]}
    else:
        perfil, _ = _perfil_texto(eventos, uids, grupo_de, cfg)
        contenido = _contenido_texto(eventos, uids, cfg)
    perfil["grupos"] = len(grupos)
    return {"perfil_lote": perfil, "grupos_evidencia": grupos, "contenido_lote": contenido,
            "uids": uids, "group_id_por_registro": grupo_de}
