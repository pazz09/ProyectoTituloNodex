"""Contexto de preprocesamiento para los prompts de los agentes
(Fase 10 del plan).

Traduce los metadatos del preprocesamiento v2 a un párrafo corto que los
agentes puedan usar. Existe como módulo aparte porque tres nodos distintos
—triage, selector y auditor— necesitan la misma información y no conviene
que cada uno arme su propia versión: divergirían.

Lo importante que este contexto aporta es la **incertidumbre**. Un lote con
cobertura 0.30 significa que el 70 % de los registros no se entendió
estructuralmente, y un diagnóstico sobre eso vale menos que uno sobre un
lote completamente decodificado. Sin decírselo al agente, este no tiene
forma de saberlo y responde con la misma seguridad en ambos casos.

Con el motor v1 devuelve cadena vacía: esos metadatos no existen y
fabricarlos sería peor que omitirlos.

**Allowlist (Fase 2 del cierre de auditoría, 23-sep-2026, hallazgo A2).**
Esta función solo lee: esquema/totales, distribución de decoders,
productos, perfiles, severidad, categorías de evento, cobertura del
parsing, cantidad de segmentos, advertencias graves y muestras normalizadas
(truncadas). Nunca lee `cronologia`, `entidades` ni ningún campo de
verdad-terreno -- ni siquiera si `metadatos` los trajera colgando, porque
ninguna línea de acá abajo los referencia. Ver
tests/test_triage_contexto_v2.py.
"""

# Por debajo de esta cobertura, el lote se declara explícitamente poco
# confiable en vez de solo informar el número: un agente que lee "0.28"
# puede no dimensionar lo que significa.
COBERTURA_BAJA = 0.60


_MARCA_OMITIDO = "[…se omitieron algunos detalles del preprocesamiento por presupuesto de caracteres]"
_MARCA_RECORTADO = "[…contexto recortado por presupuesto de caracteres]"


def contexto_preprocesamiento(metadatos: dict | None,
                              advertencias: list | None = None,
                              muestras: list | None = None,
                              incluir_muestras: bool = False) -> str:
    """Párrafo con cómo se interpretó el lote, o `""` si no hay metadatos.

    **Prioridad de recorte (confirmada por Antonia, cierre de auditoría,
    23-sep-2026).** Si el resultado supera `CONTEXTO_PREPROCESAMIENTO_MAX_CHARS`,
    lo primero que se quita son las muestras crudas y las distribuciones
    (listas que pueden crecer); los conteos globales, la cobertura del
    parsing y las advertencias de parsing NUNCA se recortan -- son la
    señal de incertidumbre que esta función existe para transmitir (ver
    docstring del módulo), así que quitarlas primero sería contradecir su
    propio propósito.
    """
    if not metadatos:
        return ""

    from src.config import CONTEXTO_PREPROCESAMIENTO_MAX_CHARS

    parsing = metadatos.get("parsing") or {}
    cobertura = parsing.get("coverage")
    decoders = metadatos.get("decoder_distribution") or {}
    productos = metadatos.get("product_distribution") or {}
    perfiles = metadatos.get("profile_distribution") or {}
    severidades = metadatos.get("severity_distribution") or {}
    categorias = metadatos.get("event_categories") or {}
    segmentos = metadatos.get("segments") or []

    # --- núcleo: protegido, nunca se recorta ---
    nucleo = ["CÓMO SE INTERPRETÓ EL LOTE (preprocesamiento determinístico):"]
    nucleo.append(
        f"- {metadatos.get('total_eventos')} eventos lógicos a partir de "
        f"{metadatos.get('total_lineas_fisicas')} líneas físicas."
    )
    if cobertura is not None:
        detalle = (
            f"- Cobertura del parsing: {cobertura:.0%} "
            f"({parsing.get('parsed_events')} decodificados, "
            f"{parsing.get('fallback_events')} en texto libre)."
        )
        if cobertura < COBERTURA_BAJA:
            detalle += (
                " ATENCIÓN: buena parte del lote no pudo interpretarse "
                "estructuralmente, así que el resumen puede estar incompleto. "
                "Tenlo en cuenta al fijar tu nivel de confianza."
            )
        nucleo.append(detalle)
    graves = [w for w in (advertencias or [])
              if w.get("severidad") in ("warning", "error")]
    if graves:
        nucleo.append(
            f"- {len(graves)} advertencia(s) de parsing: "
            + "; ".join(w.get("mensaje", "") for w in graves[:3])
        )

    # --- bloques recortables, de MENOR a MAYOR prioridad de conservación:
    # si no alcanza el presupuesto, se quita primero el bloque 0 (muestras),
    # después el 1, y así sucesivamente. ---
    bloques: list[list[str]] = []
    if incluir_muestras and muestras:
        lineas_m = ["- Muestras de registros crudos, una por formato:"]
        for m in muestras[:5]:
            etiqueta = m.get("decoder") or "nota"
            lineas_m.append(f"    [{etiqueta}] {str(m.get('texto', ''))[:300]}")
        bloques.append(lineas_m)
    if categorias:
        bloques.append([
            f"- Categorías de evento: "
            f"{', '.join(f'{k}={v}' for k, v in categorias.items())}."
        ])
    if severidades:
        bloques.append([
            f"- Severidad declarada por el propio log: "
            f"{', '.join(f'{k}={v}' for k, v in severidades.items())}."
        ])
    if perfiles:
        bloques.append([
            f"- Perfiles de enriquecimiento aplicados: "
            f"{', '.join(f'{k} ({v})' for k, v in perfiles.items())}."
        ])
    if productos:
        bloques.append([
            f"- Productos reconocidos: "
            f"{', '.join(f'{k} ({v})' for k, v in productos.items())}."
        ])
    if len(decoders) > 1:
        bloques.append([
            f"- Lote HETEROGÉNEO: convivieron {len(decoders)} formatos "
            f"({', '.join(f'{k}={v}' for k, v in decoders.items())}) "
            f"en {len(segmentos)} segmentos."
        ])
    elif decoders:
        bloques.append([f"- Formato único: {next(iter(decoders))}."])

    # Se intenta con todos los bloques; si sobra presupuesto se van quitando
    # de a uno, del de menor prioridad al de mayor, hasta que entre.
    restantes = list(bloques)
    while True:
        lineas = list(nucleo)
        for bloque in restantes:
            lineas.extend(bloque)
        texto = "\n".join(lineas)
        if len(texto) <= CONTEXTO_PREPROCESAMIENTO_MAX_CHARS or not restantes:
            break
        restantes.pop(0)

    if len(texto) > CONTEXTO_PREPROCESAMIENTO_MAX_CHARS:
        # Caso extremo: incluso el núcleo solo (p. ej. muchas advertencias
        # largas) supera el presupuesto. Único caso con recorte ciego --
        # ya no queda nada de menor prioridad que quitar.
        return texto[:CONTEXTO_PREPROCESAMIENTO_MAX_CHARS].rstrip() + "\n" + _MARCA_RECORTADO
    if len(restantes) < len(bloques):
        texto += "\n" + _MARCA_OMITIDO
    return texto


def contexto_contenido_lote(contenido: dict | None) -> str:
    """Bloque con el contenido del lote para el prompt (M1, NODEX final).

    Compartido por el triage de NODEX y el agente único, para que las dos
    arquitecturas lean lo mismo. En logs de texto entrega las líneas
    (`[uid] línea`, sin el campo de alerta de BGL) con tope de líneas y de
    caracteres, y lo dice si recorta. En logs de red entrega las filas
    completas de los flujos minoritarios que señaló el perfil del lote; el
    resto del tráfico está resumido en `perfil_lote`. Vacío si
    `CONTEXTO_LOTE_COMPLETO` está apagado o no hay contenido.
    """
    import json

    from src.config import CONTEXTO_LOTE_COMPLETO
    if not CONTEXTO_LOTE_COMPLETO or not contenido:
        return ""
    if contenido.get("tipo") == "texto":
        lineas = contenido.get("lineas") or []
        partes = ["CONTENIDO DEL LOTE (líneas observadas, formato [uid] línea):"]
        partes.extend(lineas)
        if contenido.get("recortado"):
            topes = contenido.get("topes") or {}
            partes.append(
                f"ATENCIÓN: se entregan {contenido.get('lineas_entregadas')} de "
                f"{contenido.get('total_lineas')} líneas (tope de {topes.get('lineas')} líneas o "
                f"{topes.get('caracteres')} caracteres). Las líneas omitidas no se muestran.")
        return "\n".join(partes)
    flujos = contenido.get("flujos_minoritarios") or []
    if not flujos:
        return ("FLUJOS MINORITARIOS: ninguna señal del perfil del lote marcó flujos "
                "minoritarios; el tráfico está resumido en perfil_lote.")
    partes = ["FLUJOS MINORITARIOS (filas completas de los grupos que cumplen alguna señal "
              "del perfil del lote; el resto del tráfico está resumido en perfil_lote):"]
    for flujo in flujos:
        # B.1-3a: el motivo factual de la señal es entrada del auditor reforzado, no del triage ni
        # del agente único (que siguen leyendo lo mismo que en la Fase B).
        partes.append(json.dumps({k: v for k, v in flujo.items() if k != "motivos_factuales"},
                                 ensure_ascii=False))
    if contenido.get("filas_omitidas"):
        partes.append(f"ATENCIÓN: se omitieron {contenido['filas_omitidas']} filas de flujos "
                      f"minoritarios por el tope de {contenido.get('tope_filas')} filas.")
    return "\n".join(partes)
