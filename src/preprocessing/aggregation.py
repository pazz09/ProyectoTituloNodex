"""Agregación v2 y compatibilidad con el resumen v1 (Fase 8 del plan).

Convierte una lista de `NormalizedEvent` en el resumen que consume el resto
del sistema. Dos salidas desde **una sola** pasada sobre los eventos:

- `agregar_v2()`: el resumen genérico, con distribución de decoders,
  productos y severidades, entidades de todo tipo, cobertura y muestras.
- `derivar_v1()`: los campos que los consumidores actuales esperan
  (`formato_detectado`, `total_lineas`, `servicios`, `por_ip`...), para que
  la migración no rompa nada mientras dure.

Los campos v1 se **derivan** del mismo agregado, no se recalculan con un
segundo parseo: si divergieran, el sistema estaría diagnosticando sobre una
cosa y reportando otra.

Sobre las muestras de texto crudo: se omiten cuando el lote trae ground
truth embebido en la línea. En BGL la etiqueta es el primer token del
registro, así que mandar `raw` al LLM reabriría exactamente la fuga que la
Fase 7 cerró.
"""

from src.config import CRONOLOGIA_MAX_EVENTOS
from src.tools.aggregation import (
    _CRONOLOGIA_MAX_MENSAJE,
    _entidades,
    _top,
)
from src.preprocessing.models import NormalizedEvent
from src.preprocessing.result import PreprocessingResult

# Campos del evento que aportan una "entidad" al resumen, y el nombre con
# el que se agrupan.
_ENTIDADES = (
    ("ip", ("source_ip", "destination_ip")),
    ("host", ("source_host", "destination_host")),
    ("usuario", ("source_user", "destination_user")),
    ("proceso", ("process_name",)),
    ("servicio", ("service_name",)),
    ("producto", ("product",)),
)


def _contar(valores) -> dict[str, int]:
    conteo: dict[str, int] = {}
    for v in valores:
        if v is None or v == "":
            continue
        clave = str(v)
        conteo[clave] = conteo.get(clave, 0) + 1
    return {k: conteo[k] for k in sorted(conteo, key=lambda x: (-conteo[x], x))}


def agregar_entidades(eventos: list[NormalizedEvent]) -> dict:
    """Entidades observadas, agrupadas por tipo y ordenadas por frecuencia.

    Reemplaza al `por_ip` de v1, que solo sabía de direcciones IP y por eso
    dejaba fuera cualquier lote sin ellas -- un log de aplicación, por
    ejemplo, quedaba prácticamente vacío en el resumen.
    """
    entidades: dict[str, dict[str, int]] = {}
    for nombre, campos in _ENTIDADES:
        valores = []
        for evento in eventos:
            for campo in campos:
                valores.append(getattr(evento, campo, None))
        conteo = _contar(valores)
        if conteo:
            entidades[nombre] = conteo
    return entidades


def agregar_por_ip(eventos: list[NormalizedEvent]) -> dict:
    """Desglose por IP con el rol de cada aparición.

    Mantiene la forma que `resumen_prompt.py` y la evaluación ya conocen,
    incluidos `n_como_origen` / `n_como_destino`.
    """
    por_ip: dict[str, dict] = {}

    def entrada(ip: str) -> dict:
        return por_ip.setdefault(ip, {
            "intentos_fallidos": 0, "usuarios": set(), "servicios": set(),
            "n_eventos": 0, "n_como_origen": 0, "n_como_destino": 0,
        })

    for evento in eventos:
        # "Intento fallido" se lee del resultado que el propio log declara
        # (`event_outcome`), no de una etiqueta del dataset.
        fallido = 1 if _es_fallido(evento) else 0
        if evento.source_ip:
            d = entrada(evento.source_ip)
            d["n_eventos"] += 1
            d["n_como_origen"] += 1
            d["intentos_fallidos"] += fallido
            if evento.source_user:
                d["usuarios"].add(evento.source_user)
            if evento.service_name:
                d["servicios"].add(evento.service_name)
        if evento.destination_ip and evento.destination_ip != evento.source_ip:
            d = entrada(evento.destination_ip)
            d["n_eventos"] += 1
            d["n_como_destino"] += 1
            if evento.service_name:
                d["servicios"].add(evento.service_name)

    return {ip: {"intentos_fallidos": v["intentos_fallidos"],
                 "usuarios_objetivo": sorted(v["usuarios"]),
                 "servicios": sorted(v["servicios"]),
                 "n_eventos": v["n_eventos"],
                 "n_como_origen": v["n_como_origen"],
                 "n_como_destino": v["n_como_destino"]}
            for ip, v in por_ip.items()}


# Resultados que el propio log declara como fallidos. No es una decisión de
# detección: son estados que el emisor del log escribió.
_RESULTADOS_FALLIDOS = {"rej", "s0", "rsto", "rstr", "rstos0", "rstrh", "sh", "shr",
                        "failure", "failed", "denied", "deny", "block", "blocked",
                        "error", "reject", "rejected"}


def _es_fallido(evento: NormalizedEvent) -> bool:
    valor = (evento.event_outcome or "").strip().lower()
    return valor in _RESULTADOS_FALLIDOS


def _ventana_temporal(eventos: list[NormalizedEvent]) -> dict:
    marcas = [e.timestamp for e in eventos if e.timestamp]
    return {"inicio": marcas[0] if marcas else None,
            "fin": marcas[-1] if marcas else None}


def _muestras(resultado: PreprocessingResult, maximo: int,
              permitir_crudo: bool) -> dict:
    """Muestras representativas para el prompt, acotadas.

    Se elige una por decoder, para que el LLM vea la variedad del lote y no
    las primeras N líneas, que suelen ser todas iguales.
    """
    if maximo <= 0:
        return {}
    if not permitir_crudo:
        return {"nota": ("Se omiten las muestras de texto crudo: el lote trae "
                         "ground truth embebido en la línea y enviarlas "
                         "filtraría la etiqueta al detector.")}
    vistas: dict[str, str] = {}
    for evento in resultado.events:
        if evento.decoder not in vistas:
            vistas[evento.decoder] = evento.raw[:500]
        if len(vistas) >= maximo:
            break
    return {"por_decoder": {k: vistas[k] for k in sorted(vistas)}}


def agregar_v2(resultado: PreprocessingResult, max_muestras: int = 20) -> dict:
    """Resumen genérico del lote, esquema v2."""
    eventos = resultado.events
    # Si las etiquetas venían embebidas en la línea, el crudo las contiene.
    tiene_gt_embebido = any(g.source in ("bgl", "zeek") for g in resultado.ground_truth)

    return {
        "schema_version": resultado.schema_version,
        "total_lineas_fisicas": resultado.total_lineas_fisicas,
        "total_eventos": resultado.total_eventos,
        "decoder_distribution": resultado.distribucion_decoders(),
        "product_distribution": _contar(e.product for e in eventos),
        "profile_distribution": _contar(e.attributes.get("perfil") for e in eventos),
        "severity_distribution": _contar(e.severity for e in eventos),
        "event_categories": _contar(e.event_category for e in eventos),
        "event_outcomes": _contar(e.event_outcome for e in eventos),
        "entities": agregar_entidades(eventos),
        "time_window": _ventana_temporal(eventos),
        "parsing": resultado.resumen_parsing(),
        "segments": [s.to_dict() for s in resultado.segments],
        "warnings": [w.to_dict() for w in resultado.warnings],
        "samples": _muestras(resultado, max_muestras, not tiene_gt_embebido),
    }


def derivar_v1(resultado: PreprocessingResult, resumen_v2: dict | None = None) -> dict:
    """Campos del resumen v1, derivados del mismo agregado.

    Permite que `pipeline.py`, `resumen_prompt.py`, el selector, la
    evaluación y la interfaz sigan funcionando sin cambios mientras dure la
    migración (§12 del plan).
    """
    v2 = resumen_v2 if resumen_v2 is not None else agregar_v2(resultado)
    eventos = resultado.events

    por_ip = agregar_por_ip(eventos)
    ips = sorted(por_ip, key=lambda i: por_ip[i]["n_eventos"], reverse=True)

    # `formato_detectado` en v1 nombraba al ADAPTADOR que había procesado el
    # lote ("hdfs", "bgl", "auth_log"), o sea el producto, no la estructura.
    # Por eso se deriva del producto cuando hay uno, y solo se cae al decoder
    # si ninguna fuente fue reconocida: informar "text" para un lote de HDFS
    # sería exacto respecto de la estructura y confuso para quien lee el
    # reporte.
    #
    # Con lotes heterogéneos un valor único deja de tener sentido, así que se
    # marca "mixto:<dominante>" en vez de elegir uno en silencio y hacer creer
    # que el lote era homogéneo.
    dist = v2.get("profile_distribution") or v2["decoder_distribution"]
    if not dist:
        formato = "desconocido"
    elif len(dist) == 1:
        formato = str(next(iter(dist)))
    else:
        dominante = max(dist, key=lambda k: dist[k])
        formato = f"mixto:{dominante}"

    servicios = _contar(e.service_name for e in eventos)
    if not servicios:
        servicios = {"desconocido": len(eventos)}

    usuarios = _contar(e.source_user for e in eventos)

    return {
        "formato_detectado": formato,
        "total_lineas": resultado.total_eventos,
        "servicios": servicios,
        "eventos": _eventos_v1(eventos),
        "ventana_temporal": v2["time_window"],
        "n_ips_distintas": len(ips),
        "ips_distintas": ips,
        "por_ip": por_ip,
        # Elementos del §8.7.1 agregados el 10-sep-2026. Se derivan acá para
        # que v2 exponga lo mismo que v1: el informe, el PDF y la interfaz
        # consumen estas claves y no deben depender del motor activo.
        "usuarios": _top(usuarios, 10),
        "n_usuarios_distintos": len(usuarios),
        "codigos_respuesta": _contar(e.event_code for e in eventos),
        "entidades": _entidades(ips, por_ip),
        **_cronologia_v2(eventos, tiene_gt_embebido(resultado)),
    }


def tiene_gt_embebido(resultado: PreprocessingResult) -> bool:
    """Si la etiqueta del dataset viaja dentro de la propia línea.

    Mismo criterio que usa `agregar_v2` para omitir las muestras crudas del
    prompt (Fase 7 del plan): en BGL la etiqueta es el primer token y en las
    exportaciones de Zeek es una columna del registro.
    """
    return any(g.source in ("bgl", "zeek") for g in resultado.ground_truth)


def _cronologia_v2(eventos: list[NormalizedEvent], gt_embebido: bool = False) -> dict:
    """Secuencia temporal de los registros relevantes, desde el esquema v2.

    Usa el MISMO criterio de criticidad que `_eventos_v1` (`_es_critico`),
    para que la cronología de v2 y la de v1 seleccionen los mismos registros
    de un lote equivalente. El tope y el recorte del mensaje también son los
    de v1: la sección del informe no cambia de forma según el motor.

    Con `gt_embebido` NO se reproduce `raw`: la etiqueta del dataset vive en
    la línea y copiarla al resumen reabriría la fuga de la Fase 7. Se usa
    `message`, que es la parte del registro ya separada por el decoder.
    """
    entradas, omitidos = [], 0
    for e in eventos:
        if not _es_critico(e):
            continue
        if len(entradas) >= CRONOLOGIA_MAX_EVENTOS:
            omitidos += 1
            continue
        crudo = e.message if gt_embebido else (e.raw or e.message)
        mensaje = (crudo or "").strip()
        if len(mensaje) > _CRONOLOGIA_MAX_MENSAJE:
            mensaje = f"{mensaje[:_CRONOLOGIA_MAX_MENSAJE].rstrip()}…"
        entrada = {
            "n": e.record_number if e.record_number is not None else len(entradas) + 1,
            "timestamp": e.timestamp,
            "servicio": e.service_name,
            "evento": "evento_critico",
            "mensaje": mensaje,
        }
        for clave, valor in (("ip", e.source_ip), ("ip_destino", e.destination_ip),
                             ("usuario", e.source_user), ("codigo_respuesta", e.event_code)):
            if valor:
                entrada[clave] = valor
        entradas.append(entrada)
    return {"cronologia": entradas, "cronologia_omitidos": omitidos}


# Severidades que el propio log declara como graves. Son contenido del
# registro (el emisor las escribió), no una etiqueta agregada por nadie.
_SEVERIDADES_ALTAS = {"fatal", "error", "warning", "warn", "critical", "crit",
                      "severe", "alert", "emerg", "failure"}


def _es_critico(evento: NormalizedEvent) -> bool:
    """¿El log declara este evento como grave?

    Se mira la severidad declarada y el resultado de la operación. **Nunca**
    una etiqueta del dataset: esa distinción es la que separa una señal
    legítima de la fuga de ground truth que tenía el esquema v1.

    Vale la pena registrar por qué esto no reabre la fuga en BGL. Medido
    sobre `BGL_2k.log` (4-sep-2026): de los 2000 eventos, 403 declaran
    severidad alta y solo 143 están etiquetados como alerta. La severidad
    tiene recall 1.00 pero precisión 0.35 respecto de la etiqueta, o sea que
    es una señal ruidosa que el detector todavía tiene que interpretar --
    no la respuesta servida. En HDFS coincide exactamente con los 80 WARN
    que v1 contaba como críticos.
    """
    if _es_fallido(evento):
        return True
    return (evento.severity or "").strip().lower() in _SEVERIDADES_ALTAS


def _eventos_v1(eventos: list[NormalizedEvent]) -> dict:
    """El contador `eventos` de v1, con su vocabulario.

    v1 mezclaba dos vocabularios según el adaptador: auth-log usaba
    `acceso_fallido`/`evento_generico` y HDFS/BGL usaban
    `evento_critico`/`evento_normal`. Acá se unifica en el segundo par.
    """
    criticos = sum(1 for e in eventos if _es_critico(e))
    conteo = {}
    if criticos:
        conteo["evento_critico"] = criticos
    if len(eventos) - criticos:
        conteo["evento_normal"] = len(eventos) - criticos
    return conteo
