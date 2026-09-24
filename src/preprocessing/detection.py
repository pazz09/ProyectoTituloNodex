"""Detección de formato y decodificación del lote (Fase 5 del plan).

Acá se abandona la suposición que sostenía al esquema v1: que un lote es
homogéneo y le corresponde **un** parser. Un archivo puede traer varios
formatos por segmentos, o intercalados, y ambos casos se procesan
completos.

Cuatro modos, configurables por `LOG_PARSING_MODE`:

- `batch`   -- un decoder dominante para todo el lote. Es el comportamiento
               v1 y sirve de control para comparar.
- `chunked` -- un decoder dominante por bloque de N registros.
- `line`    -- detección independiente por registro. El más lento y el más
               tolerante a formatos intercalados.
- `hybrid`  -- bloques con reproceso individual de los registros que el
               decoder dominante no explica bien. Es el recomendado: tiene
               el costo de `chunked` en el caso normal y la precisión de
               `line` donde hace falta.

El contexto CSV (cabecera y delimitador) vive en el `RecordSegment`, no en
el decoder: por eso dos segmentos con cabeceras distintas conviven, y por
eso dos análisis simultáneos no se pisan.

`RecordSegment.decoder`/`.confidence` son el resultado EFECTIVO del
segmento (M3, Fase 4 del cierre de auditoría, 23-sep-2026): se calculan
sobre los eventos ya decodificados, después del reproceso individual del
modo `hybrid` -- no sobre el intento inicial del bloque completo, que ese
mismo reproceso puede haber superado registro por registro. El intento
inicial queda en `decoder_inicial`/`confidence_inicial`.
"""

from dataclasses import dataclass, field

from src.preprocessing.decoders import (
    DECODERS,
    DECODER_TEXTO,
    detectar_cabecera,
)
from src.preprocessing.models import NormalizedEvent, ParsingWarning, RecordSegment
from src.preprocessing.segmentation import RawRecord


@dataclass
class ResultadoDeteccion:
    events: list[NormalizedEvent] = field(default_factory=list)
    segments: list[RecordSegment] = field(default_factory=list)
    warnings: list[ParsingWarning] = field(default_factory=list)


def _mejor_decoder(texto: str, contexto: dict) -> tuple[object, float]:
    """Decoder con mayor confianza para un registro, o el de texto libre."""
    mejor, mejor_conf = DECODER_TEXTO, DECODER_TEXTO.detectar(texto, contexto)
    for decoder in DECODERS:
        conf = decoder.detectar(texto, contexto)
        if conf > mejor_conf:
            mejor, mejor_conf = decoder, conf
    return mejor, mejor_conf


def _decodificar_con(decoder, registro: RawRecord, contexto: dict,
                     segment_index: int) -> NormalizedEvent:
    ev = decoder.decodificar(registro, contexto)
    ev.segment_index = segment_index
    return ev


def _decoder_efectivo(eventos: list[NormalizedEvent]) -> tuple[str, float]:
    """Decoder y confianza REALES de un segmento, recalculados desde sus
    eventos ya decodificados (M3, Fase 4 del cierre de auditoría,
    23-sep-2026) -- no desde el intento inicial sobre el bloque completo,
    que el reproceso individual del modo `hybrid` puede haber superado
    registro por registro. El decoder que explica más eventos del
    segmento gana; su confianza es el promedio de `parsing_confidence`
    entre esos eventos, no la del bloque completo.
    """
    if not eventos:
        return DECODER_TEXTO.nombre, 0.0
    conteo: dict[str, int] = {}
    confianzas: dict[str, list[float]] = {}
    for e in eventos:
        conteo[e.decoder] = conteo.get(e.decoder, 0) + 1
        confianzas.setdefault(e.decoder, []).append(e.parsing_confidence)
    dominante = max(conteo, key=lambda k: (conteo[k], k))
    confianza = sum(confianzas[dominante]) / len(confianzas[dominante])
    return dominante, round(min(max(confianza, 0.0), 1.0), 4)


def _dominante_del_bloque(bloque: list[RawRecord], contexto: dict
                          ) -> tuple[object, float]:
    """Elige el decoder que mejor explica el bloque completo.

    Se promedia la confianza sobre todos los registros en vez de mirar solo
    el primero: un bloque cuyo primer registro es atípico no debe arrastrar
    a los demás a un decoder equivocado.
    """
    if not bloque:
        return DECODER_TEXTO, 0.0
    mejor, mejor_prom = DECODER_TEXTO, DECODER_TEXTO.detectar("", contexto)
    for decoder in DECODERS:
        total = sum(decoder.detectar(r.raw, contexto) for r in bloque)
        promedio = total / len(bloque)
        if promedio > mejor_prom:
            mejor, mejor_prom = decoder, promedio
    return mejor, mejor_prom


def detectar_y_decodificar(
    registros: list[RawRecord],
    modo: str = "hybrid",
    chunk_size: int = 50,
    umbral_formato: float = 0.50,
    umbral_linea: float = 0.70,
    max_no_mapeados: int | None = None,
) -> ResultadoDeteccion:
    """Decodifica todos los registros y describe cómo se interpretó el lote."""
    res = ResultadoDeteccion()
    if not registros:
        return res

    if modo == "line":
        bloques = [[r] for r in registros]
    elif modo == "batch":
        bloques = [registros]
    else:  # chunked | hybrid
        bloques = [registros[i:i + chunk_size]
                   for i in range(0, len(registros), chunk_size)]

    contexto_csv: dict = {}
    if max_no_mapeados is not None:
        contexto_csv["max_no_mapeados"] = max_no_mapeados

    for indice, bloque in enumerate(bloques):
        # Una cabecera CSV puede aparecer en cualquier punto del archivo:
        # al inicio, o a mitad cuando se concatenan dos exportaciones. Al
        # encontrarla, reemplaza el contexto vigente y la fila NO se emite
        # como evento -- es metadatos, no un registro.
        pendientes: list[RawRecord] = []
        for registro in bloque:
            cabecera = detectar_cabecera(registro.raw.split("\n", 1)[0])
            if cabecera is not None:
                delim, columnas = cabecera
                contexto_csv = {
                    **contexto_csv,
                    "csv_delimitador": delim,
                    "csv_cabecera": columnas,
                }
                res.warnings.append(ParsingWarning(
                    codigo="csv_cabecera_detectada",
                    mensaje=(
                        f"Cabecera CSV con {len(columnas)} columnas en la "
                        f"línea {registro.line_start}; se aplica desde acá."
                    ),
                    severidad="info",
                    line_start=registro.line_start,
                ))
                continue
            pendientes.append(registro)

        if not pendientes:
            continue

        contexto = dict(contexto_csv)
        dominante, confianza = _dominante_del_bloque(pendientes, contexto)
        if confianza < umbral_formato:
            dominante, confianza = DECODER_TEXTO, confianza
        confianza_inicial = round(min(max(confianza, 0.0), 1.0), 4)

        eventos_segmento: list[NormalizedEvent] = []
        for registro in pendientes:
            conf_registro = dominante.detectar(registro.raw, contexto)
            usar = dominante
            if modo == "hybrid" and conf_registro < umbral_linea:
                # El decoder dominante no explica bien este registro: se
                # reprocesa por su cuenta en vez de forzarlo.
                candidato, conf_candidato = _mejor_decoder(registro.raw, contexto)
                # El candidato debe alcanzar el umbral de RECONOCIMIENTO de
                # formato, no solo superar al texto libre. Sin esta
                # condición basta con ganarle al 0.10 del fallback, y un
                # decoder que apenas "sospecha" se lleva el registro: sobre
                # BGL_2k.log, 73 líneas con un `ip=` o `cpu=` sueltos dentro
                # del mensaje quedaban decodificadas como clave=valor con
                # confianza 0.35, inflando la cobertura con falsos
                # positivos. Por debajo del umbral, texto libre es la
                # respuesta honesta.
                if conf_candidato > conf_registro and conf_candidato >= umbral_formato:
                    usar = candidato
            evento = _decodificar_con(usar, registro, contexto, indice)
            res.events.append(evento)
            eventos_segmento.append(evento)

        # M3 (Fase 4 del cierre de auditoría, 23-sep-2026): `decoder`/
        # `confidence` del segmento se recalculan desde sus eventos YA
        # decodificados -- no desde el intento inicial sobre el bloque
        # completo, que el reproceso de arriba puede haber superado
        # registro por registro. El intento inicial queda en `decoder_
        # inicial`/`confidence_inicial`, para trazabilidad.
        decoder_efectivo, confianza_efectiva = _decoder_efectivo(eventos_segmento)
        res.segments.append(RecordSegment(
            index=indice,
            decoder=decoder_efectivo,
            confidence=confianza_efectiva,
            decoder_inicial=dominante.nombre,
            confidence_inicial=confianza_inicial,
            line_start=pendientes[0].line_start,
            line_end=pendientes[-1].line_end,
            n_records=len(pendientes),
            context={k: v for k, v in contexto.items() if k != "max_no_mapeados"},
        ))

    return res
