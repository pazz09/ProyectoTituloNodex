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


def _truncar(texto: str) -> str:
    from src.config import CONTEXTO_PREPROCESAMIENTO_MAX_CHARS
    if len(texto) <= CONTEXTO_PREPROCESAMIENTO_MAX_CHARS:
        return texto
    return texto[:CONTEXTO_PREPROCESAMIENTO_MAX_CHARS].rstrip() + "\n[…contexto recortado por presupuesto de caracteres]"


def contexto_preprocesamiento(metadatos: dict | None,
                              advertencias: list | None = None,
                              muestras: list | None = None,
                              incluir_muestras: bool = False) -> str:
    """Párrafo con cómo se interpretó el lote, o `""` si no hay metadatos."""
    if not metadatos:
        return ""

    parsing = metadatos.get("parsing") or {}
    cobertura = parsing.get("coverage")
    decoders = metadatos.get("decoder_distribution") or {}
    productos = metadatos.get("product_distribution") or {}
    perfiles = metadatos.get("profile_distribution") or {}
    severidades = metadatos.get("severity_distribution") or {}
    categorias = metadatos.get("event_categories") or {}
    segmentos = metadatos.get("segments") or []

    lineas = ["CÓMO SE INTERPRETÓ EL LOTE (preprocesamiento determinístico):"]
    lineas.append(
        f"- {metadatos.get('total_eventos')} eventos lógicos a partir de "
        f"{metadatos.get('total_lineas_fisicas')} líneas físicas."
    )
    if len(decoders) > 1:
        lineas.append(
            f"- Lote HETEROGÉNEO: convivieron {len(decoders)} formatos "
            f"({', '.join(f'{k}={v}' for k, v in decoders.items())}) "
            f"en {len(segmentos)} segmentos."
        )
    elif decoders:
        lineas.append(f"- Formato único: {next(iter(decoders))}.")
    if productos:
        lineas.append(
            f"- Productos reconocidos: "
            f"{', '.join(f'{k} ({v})' for k, v in productos.items())}."
        )
    if perfiles:
        lineas.append(
            f"- Perfiles de enriquecimiento aplicados: "
            f"{', '.join(f'{k} ({v})' for k, v in perfiles.items())}."
        )
    if severidades:
        lineas.append(
            f"- Severidad declarada por el propio log: "
            f"{', '.join(f'{k}={v}' for k, v in severidades.items())}."
        )
    if categorias:
        lineas.append(
            f"- Categorías de evento: "
            f"{', '.join(f'{k}={v}' for k, v in categorias.items())}."
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
        lineas.append(detalle)

    graves = [w for w in (advertencias or [])
              if w.get("severidad") in ("warning", "error")]
    if graves:
        lineas.append(
            f"- {len(graves)} advertencia(s) de parsing: "
            + "; ".join(w.get("mensaje", "") for w in graves[:3])
        )

    if incluir_muestras and muestras:
        lineas.append("- Muestras de registros crudos, una por formato:")
        for m in muestras[:5]:
            etiqueta = m.get("decoder") or "nota"
            lineas.append(f"    [{etiqueta}] {str(m.get('texto', ''))[:300]}")

    return _truncar("\n".join(lineas))
