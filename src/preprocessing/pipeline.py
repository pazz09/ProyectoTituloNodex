"""Tubería de preprocesamiento v2 (Fase 5 del plan).

Ensambla las etapas en el orden del §6 del plan:

    ingesta -> segmentación -> detección -> decodificación -> resultado

Nada de esto está conectado todavía al grafo multiagente: `aggregate_logs()`
sigue siendo el camino productivo hasta la Fase 8. Esta función existe para
poder comparar salidas v1 y v2 sobre las mismas entradas, que es lo que la
estrategia de migración del §12 pide antes de cambiar de motor.

Ningún agente participa acá: el preprocesamiento es determinístico y no
usa LLM (principio 1 del plan).
"""

from src.config import (
    LOG_DETECTION_CHUNK_SIZE,
    LOG_ENABLE_MULTILINE,
    LOG_FORMAT_CONFIDENCE_THRESHOLD,
    LOG_LINE_FALLBACK_THRESHOLD,
    LOG_MAX_EVENTS,
    LOG_MAX_FILE_BYTES,
    LOG_MAX_UNMAPPED_FIELDS,
    LOG_NORMALIZATION_SCHEMA_VERSION,
    LOG_PARSING_MODE,
    config_preprocesamiento_efectiva,
    validar_config_preprocesamiento,
)
from src.preprocessing.detection import detectar_y_decodificar
from src.preprocessing.enrichers import ENRICHERS
from src.preprocessing.models import ParsingWarning
from src.preprocessing.result import PreprocessingResult
from src.preprocessing.segmentation import segmentar


def preprocesar(
    texto: str,
    modo: str | None = None,
    chunk_size: int | None = None,
    umbral_formato: float | None = None,
    umbral_linea: float | None = None,
    enable_multiline: bool | None = None,
    max_eventos: int | None = None,
    max_bytes: int | None = None,
    max_no_mapeados: int | None = None,
    aplicar_enriquecedores: bool = True,
) -> PreprocessingResult:
    """Preprocesa un lote de logs y devuelve el resultado v2.

    Los parámetros en `None` toman su valor de `src/config.py`; se admiten
    explícitos para poder probar cada modo sin manipular el entorno.
    """
    validar_config_preprocesamiento()

    modo = modo if modo is not None else LOG_PARSING_MODE
    chunk_size = chunk_size if chunk_size is not None else LOG_DETECTION_CHUNK_SIZE
    umbral_formato = (umbral_formato if umbral_formato is not None
                      else LOG_FORMAT_CONFIDENCE_THRESHOLD)
    umbral_linea = (umbral_linea if umbral_linea is not None
                    else LOG_LINE_FALLBACK_THRESHOLD)
    enable_multiline = (enable_multiline if enable_multiline is not None
                        else LOG_ENABLE_MULTILINE)
    max_eventos = max_eventos if max_eventos is not None else LOG_MAX_EVENTS
    max_bytes = max_bytes if max_bytes is not None else LOG_MAX_FILE_BYTES
    max_no_mapeados = (max_no_mapeados if max_no_mapeados is not None
                       else LOG_MAX_UNMAPPED_FIELDS)

    warnings: list[ParsingWarning] = []

    # --- ingesta: límite de tamaño ---
    bytes_entrada = len(texto.encode("utf-8", errors="replace"))
    if bytes_entrada > max_bytes:
        # Se recorta por caracteres y se avisa: procesar medio archivo con
        # constancia es preferible a rechazarlo entero o a agotar memoria.
        proporcion = max_bytes / bytes_entrada
        corte = int(len(texto) * proporcion)
        texto = texto[:corte]
        warnings.append(ParsingWarning(
            codigo="limite_de_bytes",
            mensaje=(
                f"La entrada superaba LOG_MAX_FILE_BYTES ({max_bytes}); se "
                f"procesaron los primeros {corte} caracteres de "
                f"{bytes_entrada} bytes."
            ),
            severidad="error",
        ))

    # --- segmentación ---
    seg = segmentar(texto, enable_multiline=enable_multiline,
                    max_eventos=max_eventos)
    warnings.extend(seg.warnings)

    # --- detección y decodificación ---
    det = detectar_y_decodificar(
        seg.records,
        modo=modo,
        chunk_size=chunk_size,
        umbral_formato=umbral_formato,
        umbral_linea=umbral_linea,
        max_no_mapeados=max_no_mapeados,
    )
    warnings.extend(det.warnings)

    # --- enriquecimiento por producto + desvío del ground truth ---
    ground_truth = []
    if aplicar_enriquecedores:
        for evento in det.events:
            for enricher in ENRICHERS:
                if not enricher.aplica(evento):
                    continue
                # ORDEN OBLIGATORIO: primero la etiqueta, después el
                # enriquecimiento. `ZeekEnricher.enriquecer()` retira del
                # evento las columnas `label_*`, así que invertir esto
                # dejaría el canal de ground truth vacío sin que nada
                # falle visiblemente (ver `enrichers/base.py`).
                etiqueta = enricher.extraer_ground_truth(evento)
                if etiqueta is not None:
                    ground_truth.append(etiqueta)
                enricher.enriquecer(evento)
                # Nombre corto del perfil aplicado. `formato_detectado` de
                # v1 nombraba al adaptador ("hdfs", "bgl"), no al producto
                # comercial, así que la fachada de compatibilidad necesita
                # este identificador y no "BlueGene/L".
                evento.attributes["perfil"] = enricher.nombre
                break   # un producto por evento

    config = config_preprocesamiento_efectiva()
    # Los parámetros explícitos pisan a los del entorno en el registro de
    # procedencia: si no, el resultado diría que corrió con una
    # configuración distinta de la real.
    config.update({
        "LOG_PARSING_MODE": modo,
        "LOG_DETECTION_CHUNK_SIZE": chunk_size,
        "LOG_FORMAT_CONFIDENCE_THRESHOLD": umbral_formato,
        "LOG_LINE_FALLBACK_THRESHOLD": umbral_linea,
        "LOG_ENABLE_MULTILINE": enable_multiline,
        "LOG_MAX_EVENTS": max_eventos,
        "LOG_MAX_FILE_BYTES": max_bytes,
        "LOG_MAX_UNMAPPED_FIELDS": max_no_mapeados,
    })

    return PreprocessingResult(
        schema_version=LOG_NORMALIZATION_SCHEMA_VERSION,
        total_lineas_fisicas=seg.total_lineas_fisicas,
        events=det.events,
        segments=det.segments,
        warnings=warnings,
        ground_truth=ground_truth,
        config={k: config[k] for k in sorted(config)},
    )
