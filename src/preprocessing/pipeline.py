"""Tubería de preprocesamiento (esquema v2, único motor del sistema).

Ensambla las etapas en orden:

    ingesta -> segmentación -> detección -> decodificación -> enriquecimiento -> resultado

`preprocesar()` es el único camino de preprocesamiento hacia el grafo
multiagente: `src/tools/aggregation.py::preprocesar_lote()` y
`aggregate_logs()` lo llaman exactamente una vez por lote (ver
docs/pipeline_preprocesamiento.md para el flujo completo y quién llama a
quién).

Ningún agente participa acá: el preprocesamiento es determinístico y no
usa LLM.
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


class PreprocesamientoError(Exception):
    """El preprocesamiento determinístico falló sobre el lote.

    Mensaje pensado para mostrarse tal cual al usuario -- interfaz web, CLI
    o evaluador (§ cierre de auditoría, 23-sep-2026, revisión del camino
    productivo tras la Fase 1): no es un detalle interno de depuración, es
    la explicación de por qué el lote no se pudo analizar. Quien la atrapa
    no debe envolverla en un "error inesperado del servidor" genérico.
    """


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
    # M6 (Fase 4 del cierre de auditoría, 23-sep-2026): rechaza, no trunca.
    # Antes, un lote sobre LOG_MAX_FILE_BYTES se recortaba y se seguía
    # analizando -- inconsistente con la API (`/api/analizar`), que
    # siempre rechazó con HTTP 413 el mismo caso. Ambos caminos ahora dan
    # la misma respuesta: nunca se analiza "una parte" del lote sin que
    # quien lo pidió lo sepa de antemano. `PreprocesamientoError` ya la
    # atrapan el CLI (mensaje claro + exit 1) y el evaluador (se registra
    # el lote como error y sigue con el resto) desde la Fase 1.
    bytes_entrada = len(texto.encode("utf-8", errors="replace"))
    if bytes_entrada > max_bytes:
        raise PreprocesamientoError(
            f"El lote pesa {bytes_entrada} bytes y supera el límite de "
            f"{max_bytes} (LOG_MAX_FILE_BYTES). Subí un lote más chico o "
            "ajustá esa variable."
        )

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
