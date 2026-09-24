"""Agregación determinística de logs (sin LLM) — núcleo del escalado.

Todo lote pasa por la tubería de preprocesamiento heterogéneo
(`src/preprocessing/`): segmentación en registros lógicos, detección de
formato por confianza (con reproceso por línea donde hace falta),
decodificación estructural y enriquecimiento por producto. `aggregate_logs()`
es la fachada que el resto del sistema usa — deriva el resumen que
`pipeline.py`, `resumen_prompt.py`, el selector, la evaluación y la interfaz
consumen, a partir de esa única agregación (`src/preprocessing/aggregation.py`).

Este módulo conserva los ayudantes que ese resumen necesita y que son
transversales a cualquier formato: registro de entidades del reporte, la
firma de embedding del lote, y la descripción en prosa para la recuperación
de técnicas MITRE ATT&CK.
"""

def _preprocesar_y_agregar(raw: str):
    """`preprocesar()` + `agregar_v2()`, cada uno UNA sola vez.

    Núcleo compartido de `aggregate_logs()` y `preprocesar_lote()`. Import
    diferido a propósito: `src.preprocessing.aggregation` importa
    `_entidades`/`_top`/`_CRONOLOGIA_MAX_MENSAJE` DESDE este módulo (son
    ayudantes compartidos, no exclusivos de un formato); importar a nivel de
    módulo acá arriba crearía un ciclo de imports entre ambos.
    """
    from src.config import LOG_MAX_RAW_SAMPLES
    from src.preprocessing.aggregation import agregar_v2
    from src.preprocessing.pipeline import PreprocesamientoError, preprocesar

    try:
        resultado = preprocesar(raw)
        v2 = agregar_v2(resultado, max_muestras=LOG_MAX_RAW_SAMPLES)
    except PreprocesamientoError:
        raise
    except Exception as e:
        # Punto único donde se envuelve la falla (revisión del camino
        # productivo, cierre de auditoría 23-sep-2026): tanto el pipeline
        # como el baseline pasan por acá, así que web, CLI y evaluador
        # reciben el mismo mensaje claro en vez de cada uno formatear su
        # propia versión del error. Se sigue PROPAGANDO -- no se swallow
        # acá; cada consumidor decide cómo mostrarlo o si aborta.
        raise PreprocesamientoError(
            f"No se pudo preprocesar el lote ({type(e).__name__}: {e})"
        ) from e
    return resultado, v2


def aggregate_logs(raw: str) -> dict:
    """Preprocesa el lote completo y devuelve el resumen estructurado (v1)
    que consume el resto del sistema (agentes, evaluación, interfaz).

    Para quien necesite además el resumen v2 (metadatos de preprocesamiento
    para el estado del grafo, p. ej. `pipeline.py`), usar `preprocesar_lote()`
    en vez de esta función seguida de un segundo cálculo: `preprocesar()` no
    debe correr dos veces sobre el mismo lote (hallazgo A1 de la auditoría
    del 23-sep-2026).
    """
    from src.preprocessing.aggregation import derivar_v1
    resultado, v2 = _preprocesar_y_agregar(raw)
    return derivar_v1(resultado, v2)


def preprocesar_lote(raw: str):
    """`preprocesar()` UNA sola vez, con las tres vistas que el sistema usa.

    Devuelve `(resultado, v2, resumen_v1)`: el resultado crudo del
    preprocesamiento (`PreprocessingResult`), el resumen genérico v2
    (`agregar_v2`) y el resumen compatible v1 (`derivar_v1`), los tres
    derivados de la MISMA pasada -- no de parseos independientes que podrían
    divergir. Punto de entrada para `pipeline.py` y `baseline_reglas.py`,
    que necesitan más de una vista del mismo lote.
    """
    from src.preprocessing.aggregation import derivar_v1
    resultado, v2 = _preprocesar_y_agregar(raw)
    resumen_v1 = derivar_v1(resultado, v2)
    return resultado, v2, resumen_v1


def _top(conteos: dict, n: int) -> dict:
    """Las `n` claves más frecuentes. Acota lo que puede crecer sin techo:
    en HDFS el "usuario" es un block id y hay miles por lote."""
    return dict(sorted(conteos.items(), key=lambda kv: (-kv[1], kv[0]))[:n])


def _entidades(ips: list, por_ip: dict, tope: int = 8) -> list:
    """Entidades involucradas (§8.7.1), acotadas y ya ordenadas por actividad.

    `por_ip` completo puede tener cientos de entradas -- 202 en HDFS_2k -- y
    va al prompt acotado por `resumen_prompt`, pero el REPORTE necesita una
    versión corta y estable que se pueda leer.
    """
    salida = []
    for ip in ips[:tope]:
        datos = por_ip.get(ip) or {}
        salida.append({
            "ip": ip,
            "n_eventos": datos.get("n_eventos", 0),
            "intentos_fallidos": datos.get("intentos_fallidos", 0),
            "usuarios_objetivo": (datos.get("usuarios_objetivo") or [])[:5],
            "servicios": (datos.get("servicios") or [])[:3],
            "n_como_origen": datos.get("n_como_origen", 0),
            "n_como_destino": datos.get("n_como_destino", 0),
        })
    return salida


_CRONOLOGIA_MAX_MENSAJE = 180


def firma_lote(summary: dict, metadatos: dict | None = None) -> str:
    """Firma compacta del lote para embeddings/memoria (no el blob crudo).

    Con `metadatos` (el resumen del preprocesamiento heterogéneo) la firma
    incorpora decoders, productos, severidades y cobertura, además de los
    conteos básicos -- son las señales que permiten distinguir lotes que un
    resumen mínimo no alcanzaría a diferenciar.
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

def _dominante(dist: dict) -> tuple[str, int] | None:
    """Clave con más ocurrencias de una distribución, con su conteo."""
    if not dist:
        return None
    clave = max(dist, key=lambda k: (dist[k], k))
    return clave, dist[clave]


def describir_lote_en_prosa(resumen: dict) -> str:
    """Describe el lote en una o dos oraciones, a partir de los campos que
    `aggregate_logs()` ya agregó. Determinística: no consulta el LLM.

    **Por qué existe.** La colección `attack_techniques` guarda las técnicas
    de MITRE ATT&CK como prosa ("SSH. Adversaries may use Valid Accounts to
    log into remote machines..."). Consultarla con `firma_lote()` -- una
    cadena de conteos del estilo `v2|lineas=23 ips=3 servicios=[sshd:18...]`
    -- comparaba un formato con el otro y no recuperaba nada: medido el
    9-sep-2026 sobre corridas reales, la similitud máxima quedaba en 0.324
    (auth_log) y 0.300 (BGL), bajo el piso de 0.35, de modo que
    `tecnicas_mitre` venía vacío SIEMPRE. Esta función arma el texto de
    consulta en el mismo registro que los documentos indexados.

    `firma_lote()` no cambia: sigue siendo la clave de `patterns`,
    `errors` e `history`, donde ambos lados de la comparación son firmas y
    el formato compacto es el correcto.
    """
    resumen = resumen or {}
    partes = []

    formato = resumen.get("formato_detectado") or "desconocido"
    partes.append(f"Lote de tipo {formato}.")

    ev = _dominante(resumen.get("eventos") or {})
    svc = _dominante(resumen.get("servicios") or {})
    if ev and svc:
        partes.append(f"Predominan eventos de {ev[0]} sobre el servicio "
                      f"{svc[0]} ({ev[1]} eventos).")
    elif ev:
        partes.append(f"Predominan eventos de {ev[0]} ({ev[1]} eventos).")
    elif svc:
        partes.append(f"Predomina el servicio {svc[0]} ({svc[1]} eventos).")

    # La cláusula de fallos se deriva de si el lote es de autenticación
    # (formato_detectado), no de un vocabulario de evento propio: el
    # preprocesamiento heterogéneo unificó "acceso_fallido"/"evento_crítico"
    # en un solo par (evento_critico/evento_normal) para todos los formatos,
    # así que el conteo por sí solo ya no distingue un fallo de login de un
    # fallo de hardware. Describirlo como autenticación cuando no lo es
    # afirmaría algo que el log no dice -- y de paso arrastraría a ATT&CK
    # hacia técnicas de credenciales por un lote de fallas de hardware.
    eventos = resumen.get("eventos") or {}
    n_ips = resumen.get("n_ips_distintas") or 0
    es_auth = formato == "auth_log" or formato.startswith("mixto:auth_log")
    n_fallos = eventos.get("evento_critico", 0) if es_auth else 0
    if n_fallos:
        # `intentos_fallidos` se acredita solo al origen del registro, así
        # que sumarlo sobre `por_ip` no cuenta dos veces las líneas de flujo
        # que nombran dos IPs. Una línea puede tener más de un fallo, por
        # eso se prefiere al conteo de eventos.
        intentos = sum((d or {}).get("intentos_fallidos", 0)
                       for d in (resumen.get("por_ip") or {}).values()) or n_fallos
        partes.append(f"{intentos} intentos fallidos de autenticacion desde "
                      f"{n_ips} IPs distintas.")
    elif eventos.get("evento_critico"):
        partes.append(f"{eventos['evento_critico']} eventos criticos del "
                      f"sistema registrados.")
    if n_ips and not n_fallos:
        partes.append(f"Actividad de {n_ips} IPs distintas.")

    # Cláusula de reputación: solo si AbuseIPDB marcó algo. Una IP limpia no
    # aporta señal y alargar la consulta con "0 IPs maliciosas" solo diluye
    # el embedding.
    reputacion = resumen.get("reputacion_ips") or {}
    marcadas = [ip for ip, d in reputacion.items()
                if (d or {}).get("categoria") in ("malicioso", "sospechoso")]
    if marcadas:
        etiqueta = "IP" if len(marcadas) == 1 else "IPs"
        partes.append(f"{len(marcadas)} {etiqueta} con reputacion maliciosa "
                      f"reportada en AbuseIPDB.")

    return " ".join(partes)
