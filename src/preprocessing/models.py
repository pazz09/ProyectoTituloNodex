"""Modelos normalizados del preprocesamiento v2 (Fase 1 del plan).

Estas estructuras reemplazan, a futuro, al dict por línea que devuelven hoy
los adaptadores de `src/tools/aggregation.py`. En esta fase solo se definen:
NADA en el sistema las consume todavía y el contrato v1 queda intacto.

Tres decisiones de diseño que vale la pena dejar explícitas, porque
corrigen problemas concretos de la línea base (ver
`docs/preprocessing_baseline.md`, "Riesgos confirmados"):

1. **Un campo por concepto.** El esquema v1 reutiliza `usuario` para un
   usuario real, un `blk_...` de HDFS, un nodo de BGL y un id de flujo de
   Zeek. Acá cada cosa tiene su lugar: `source_user` es una persona,
   mientras que un identificador de objeto va a `attributes`, con su
   nombre de origen.

2. **No pérdida.** `raw` conserva el registro original y `attributes`
   los campos que ningún mapeo reconoció. Un formato desconocido no
   pierde información: queda en texto libre con confianza baja.

3. **Ground truth aislado.** `GroundTruthRecord` vive en un canal aparte
   y `PreprocessingResult.to_dict()` NO lo incluye por defecto. Es la
   contramedida a la fuga de etiquetas detectada en BGL, donde el flag de
   alerta del dataset alimentaba `evento_critico`, o sea la propia
   feature que el detector observa.
"""

from dataclasses import asdict, dataclass, field

# Severidades admitidas para una advertencia de parsing, de menor a mayor.
SEVERIDADES_ADVERTENCIA = ("info", "warning", "error")

# Cotas de `parsing_confidence`. Se validan en vez de recortarse: una
# confianza fuera de rango es un error de programación del decoder, no un
# dato del log que convenga tolerar en silencio.
CONFIANZA_MIN = 0.0
CONFIANZA_MAX = 1.0


@dataclass
class ParsingWarning:
    """Algo que el preprocesamiento no pudo interpretar del todo.

    No aborta el lote: se acumula y se reporta. Es la base del criterio de
    observabilidad del plan (§5.8) -- un parsing parcial nunca debe pasar
    inadvertido.
    """

    codigo: str
    mensaje: str
    severidad: str = "warning"
    record_number: int | None = None
    line_start: int | None = None

    def __post_init__(self) -> None:
        if not self.codigo:
            raise ValueError("ParsingWarning.codigo no puede estar vacío")
        if self.severidad not in SEVERIDADES_ADVERTENCIA:
            raise ValueError(
                f"ParsingWarning.severidad inválida: {self.severidad!r}. "
                f"Valores admitidos: {', '.join(SEVERIDADES_ADVERTENCIA)}"
            )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RecordSegment:
    """Tramo contiguo del lote interpretado con un mismo decoder.

    Un archivo homogéneo produce un único segmento; uno heterogéneo, varios.
    Que esto sea una lista y no un valor único es lo que permite abandonar
    la suposición de homogeneidad de la línea base (riesgo 4).
    """

    index: int
    # `decoder`/`confidence` son el resultado EFECTIVO del segmento,
    # recalculado desde sus eventos ya decodificados (M3, Fase 4 del
    # cierre de auditoría, 23-sep-2026) -- no el intento inicial sobre el
    # bloque completo, que en modo `hybrid` el reproceso individual puede
    # haber superado registro por registro. Antes de M3 estos dos campos
    # SÍ eran el intento inicial; un lote con eventos JSON/syslog/texto
    # mezclados en un mismo bloque podía quedar reportado como "text @
    # 0.33" aunque casi todos sus registros se hubieran decodificado bien.
    #
    # `decoder` es el decoder con MÁS eventos en el segmento -- no
    # necesariamente una mayoría: con un empate (p. ej. 2 json / 2
    # syslog), se desempata por orden alfabético del nombre del decoder,
    # únicamente para que el resultado sea determinista, no porque uno
    # sea "mejor". `decoder_distribution` trae el conteo completo, así
    # que un empate queda visible en vez de escondido detrás de una sola
    # etiqueta (corregido tras una revisión de Antonia: la primera
    # versión de este campo no existía, y el mensaje del commit describía
    # el resultado como "la mayoría real" incluso en casos de empate).
    decoder: str
    line_start: int
    line_end: int
    n_records: int = 0
    confidence: float = 0.0
    # El intento inicial (antes del reproceso individual), conservado
    # para trazabilidad -- decisión de Antonia: recalcular la etiqueta
    # principal en vez de agregar SOLO un campo aparte con la distribución
    # efectiva, pero sin perder el dato del primer intento.
    decoder_inicial: str | None = None
    confidence_inicial: float | None = None
    # Conteo real de decoders entre los eventos del segmento, de mayor a
    # menor -- p. ej. {"syslog": 3, "json": 1}. `decoder` es simplemente
    # la primera clave de este dict; se guarda aparte para no obligar a
    # quien lo consume a asumir un orden de iteración de dict, y porque
    # "el segmento tiene distribución de decoders X" es, en sí, un dato
    # más informativo que solo el ganador.
    decoder_distribution: dict = field(default_factory=dict)
    # Contexto propio del segmento: p. ej. la cabecera de un CSV. Que viva
    # acá y no en el decoder evita el estado compartido entre análisis
    # concurrentes que hubo que resolver en el adaptador CSV v1.
    context: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.line_end < self.line_start:
            raise ValueError(
                f"RecordSegment {self.index}: line_end ({self.line_end}) es "
                f"anterior a line_start ({self.line_start})"
            )
        _validar_confianza(self.confidence, f"RecordSegment {self.index}.confidence")
        if self.confidence_inicial is not None:
            _validar_confianza(self.confidence_inicial,
                              f"RecordSegment {self.index}.confidence_inicial")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["context"] = _dict_ordenado(self.context)
        return d


@dataclass
class NormalizedEvent:
    """Un evento lógico, ya normalizado, independiente de su formato de origen.

    Un evento puede abarcar varias líneas físicas (un stack trace) o
    ninguna estructura reconocible (texto libre). Ninguno de los campos
    semánticos es obligatorio: un log sin IP, sin usuario y sin timestamp
    es un evento perfectamente válido -- otro de los límites del esquema v1,
    donde un registro sin IP quedaba subrepresentado.
    """

    raw: str
    message: str
    timestamp: str | None = None

    source_ip: str | None = None
    source_port: int | None = None
    source_host: str | None = None
    source_user: str | None = None

    destination_ip: str | None = None
    destination_port: int | None = None
    destination_host: str | None = None
    destination_user: str | None = None

    service_name: str | None = None
    process_name: str | None = None
    process_id: str | None = None
    protocol: str | None = None

    event_category: str | None = None
    event_action: str | None = None
    event_outcome: str | None = None
    severity: str | None = None
    event_code: str | None = None

    product: str | None = None
    vendor: str | None = None
    version: str | None = None

    decoder: str = "text"
    parsing_confidence: float = 0.0
    attributes: dict = field(default_factory=dict)

    # --- procedencia ---
    record_number: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    segment_index: int | None = None
    is_multiline: bool = False
    warnings: list[ParsingWarning] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.raw is None:
            raise ValueError("NormalizedEvent.raw no puede ser None (usa '' si el registro venía vacío)")
        if self.message is None:
            raise ValueError("NormalizedEvent.message no puede ser None")
        if not self.decoder:
            raise ValueError("NormalizedEvent.decoder no puede estar vacío")
        _validar_confianza(self.parsing_confidence, "NormalizedEvent.parsing_confidence")

    @property
    def es_fallback(self) -> bool:
        """True si no se entendió la estructura NI el producto del evento.

        Alimenta la métrica de cobertura: un lote con muchos fallback se
        procesó completo, pero se entendió poco -- y eso hay que decirlo.

        Que un enriquecedor haya reconocido el producto cuenta como
        entendido aunque el decoder sea `text`. HDFS y BGL son justamente
        eso: formatos de producto sin estructura genérica, que el decoder
        no puede reclamar pero de los que sí se extraen timestamp,
        servicio, severidad e identificadores. Medir solo por decoder les
        daba cobertura 0 % estando completamente interpretados, y el
        contexto que se le pasa al agente llegaba a advertirle que el lote
        "no pudo interpretarse" cuando sí se había interpretado
        (medido el 4-sep-2026 sobre HDFS_2k.log y BGL_2k.log).
        """
        return self.decoder == "text" and self.product is None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["attributes"] = _dict_ordenado(self.attributes)
        d["warnings"] = [w.to_dict() for w in self.warnings]
        return d


@dataclass
class GroundTruthRecord:
    """Etiqueta de evaluación, en un canal SEPARADO de las features.

    `scope` indica a qué se refiere la clave: un evento puntual, un bloque
    (HDFS etiqueta por `blk_...`) o una ventana temporal (BGL). Nunca debe
    llegar al detector: existe solo para calcular métricas DESPUÉS del
    análisis.
    """

    key: str
    label: str
    scope: str = "evento"
    source: str | None = None

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("GroundTruthRecord.key no puede estar vacía")
        if not self.label:
            raise ValueError("GroundTruthRecord.label no puede estar vacía")

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _validar_confianza(valor: float, nombre: str) -> None:
    if not isinstance(valor, (int, float)) or isinstance(valor, bool):
        raise ValueError(f"{nombre} debe ser numérica, no {type(valor).__name__}")
    if not (CONFIANZA_MIN <= valor <= CONFIANZA_MAX):
        raise ValueError(
            f"{nombre} debe estar entre {CONFIANZA_MIN} y {CONFIANZA_MAX}, "
            f"recibido {valor}"
        )


def _dict_ordenado(d: dict) -> dict:
    """Ordena las claves para que la serialización sea determinística.

    Dos corridas sobre la misma entrada deben producir el mismo JSON: de
    eso depende que las firmas para ChromaDB y la comparación v1/v2 de la
    Fase 8 sean reproducibles.
    """
    return {k: d[k] for k in sorted(d, key=str)}
