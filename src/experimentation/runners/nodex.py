"""Runner de NODEX multiagente. §13 Fase C del plan de continuación.

Envuelve `analizar_lote()` de `src/pipeline.py` sin modificarlo. El runner
no decide nada del análisis: pasa el caso, recoge el estado final y mide el
tiempo.

## Qué NO hace

- **No toca los agentes, el estado ni el pipeline.** D-11 es implementación
  externa y este módulo no la sustituye ni la anticipa: si los tres campos
  aparecen en el estado final, el adaptador los lee solo.
- **No ve el ground truth.** Recibe el contenido del caso y nada más.
- **No reintenta con otro modelo.** El fallback de `src/llm.py` queda tal
  como está (decisión del 7-oct-2026); el runner solo registra qué modelo
  respondió, para que una corrida con fallback sea identificable y no se
  mezcle en silencio.

## `thread_id` y el checkpointer

`analizar_lote(raw_logs, thread_id)` usa un `MemorySaver` por hilo. Cada
corrida recibe su **propio** `thread_id`, derivado del `run_id`: si dos
corridas compartieran hilo, el checkpoint de la primera contaminaría a la
segunda y la repetición 2 no sería independiente de la 1. Eso rompería
precisamente lo que `N=3` quiere medir.
"""

from __future__ import annotations

import time
from pathlib import Path

#: Claves del estado final que el runner espera. Si falta alguna, no se
#: inventa: el adaptador la marca ausente y la dimensión queda no evaluable.
CLAVES_ESPERADAS = (
    "hay_anomalia",
    "hay_incidente",
    "confianza",
    "diagnostico",
    "evaluacion_auditor",
    "comandos_mitigacion",
)


def thread_id_de(run_id: str) -> str:
    """Hilo propio por corrida, para que el checkpointer no las contamine."""
    return f"exp__{run_id}"


def ejecutar(contenido: str, run_id: str) -> tuple[dict, dict]:
    """Corre NODEX sobre un caso. Devuelve `(estado_final, diagnostico)`.

    **Hace varias llamadas al modelo** (cinco nodos LLM, más los bucles de
    replanificación y corrección). Solo debe invocarse durante una corrida
    autorizada.
    """
    from src.pipeline import analizar_lote

    comenzado = time.monotonic()
    error: str | None = None
    estado: dict = {}
    try:
        estado = analizar_lote(contenido, thread_id=thread_id_de(run_id))
    except Exception as excepcion:  # noqa: BLE001 - se registra, no se oculta
        error = f"{type(excepcion).__name__}: {excepcion}"
    transcurrido = time.monotonic() - comenzado

    ausentes = sorted(c for c in CLAVES_ESPERADAS if c not in estado)
    diagnostico = {
        "arquitectura": "nodex_multiagente",
        "thread_id": thread_id_de(run_id),
        "execution_time": transcurrido,
        "error": error,
        "claves_ausentes_en_el_estado": ausentes,
        # Los dos contadores de bucle del grafo. Sirven para explicar por
        # qué una corrida consumió más que otra.
        "replan_count": estado.get("replan_count"),
        "intentos_correccion": estado.get("intentos_correccion"),
        "historial_ejecucion": len(estado.get("historial_ejecucion") or []),
        # Presencia de los campos de D-11. Mientras sea False, D2 y D3 no
        # son medibles; no se rellenan desde acá.
        "d11_presente_en_el_estado": all(
            campo in estado
            for campo in ("eventos_reconstruidos", "tecnicas_atribuidas")
        ),
    }
    return estado, diagnostico


def clasificar_error(error: str) -> str:
    """Estado de ejecución que corresponde al texto de un error.

    Está aparte de `estado_de_ejecucion` porque el orquestador también la
    necesita para los fallos que llegan como excepción y para Gemini directo:
    clasificar distinto según la arquitectura haría que la misma causa se
    contara en categorías diferentes.
    """
    texto = (error or "").lower()
    if any(s in texto for s in ("resource_exhausted", "quota", "429",
                                "deadline", "unavailable", "503")):
        return "error_api"
    if "preprocesamiento" in texto or "preprocessing" in texto:
        return "error_preprocesamiento"
    if "timeout" in texto:
        return "timeout"
    return "error_contrato"


def estado_de_ejecucion(diagnostico: dict, estado: dict) -> str:
    """Traduce el resultado a un estado de ejecución del contrato.

    Distingue el fallo de API del fallo de contrato porque las causas y las
    acciones son distintas: una cuota agotada se reintenta, un JSON mal
    formado se corrige.
    """
    error = diagnostico.get("error")
    if error:
        return clasificar_error(error)
    if not estado:
        return "error_contrato"
    # Sin ninguno de los dos veredictos no hay nada que evaluar en D1,
    # aunque el grafo haya terminado.
    if not isinstance(estado.get("hay_anomalia"), bool) and not isinstance(
        estado.get("hay_incidente"), bool
    ):
        return "error_contrato"
    return "completa"


def cargar_caso(raiz_repo: Path, dataset: str, particion: str, case_id: str) -> str:
    """Lee el contenido de un caso. **No lee su ground truth.**

    Las tres arquitecturas usan esta misma lectura, sobre el mismo archivo:
    si recibieran entradas distintas, la comparación mediría la entrada.
    """
    directorio = raiz_repo / "experiments" / "cases" / dataset / particion
    for extension in ("log", "csv"):
        archivo = directorio / f"{case_id}.{extension}"
        if archivo.is_file():
            return archivo.read_text(encoding="utf-8")
    raise FileNotFoundError(
        f"no se encontró el contenido del caso {case_id} en {directorio}"
    )
