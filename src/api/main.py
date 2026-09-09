"""API web de NODEX: panel de análisis con progreso del grafo en vivo.

Interfaz de demostración sobre `src.pipeline.analizar_lote_stream` -- no
reemplaza el CLI (`src/tools/log_runner.py`) ni las corridas usadas para el
informe, que siguen corriendo `analizar_lote` directamente. El propósito de
esta capa es exclusivamente visual: subir un lote de logs y ver, en vivo,
qué nodo del grafo multiagente se está ejecutando (Triage → RAG → Selector
→ CVE → Mitigación → Validador → Auditor), y el reporte final.

Uso:
    uvicorn src.api.main:app --reload
    (abre http://127.0.0.1:8000 en el navegador)

Nota de diseño: el progreso se transmite por Server-Sent Events (SSE), no
por WebSocket -- es unidireccional (servidor -> navegador) y no necesita
reconexión ni protocolo bidireccional para este caso de uso, así que SSE
es más simple y con menos piezas que puedan fallar el día de la demo.
"""

import json
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

from src.api import historial
from src.api.informe_pdf import generar_informe_pdf
from src.pipeline import analizar_lote_stream, commit_feedback

app = FastAPI(title="NODEX — Panel de análisis")

_STATIC_DIR = Path(__file__).parent / "static"

# Cola de lotes pendientes de analizar, en memoria:
# job_id -> (texto del lote, nombre del archivo subido). El nombre hace
# falta para el historial, porque el stream no lo recibe de ningún otro lado.
# Alcanza para un proceso de demostración de un solo usuario; no está
# pensado para producción ni para varios workers (uvicorn --workers > 1
# perdería jobs entre procesos, porque este dict vive en memoria de uno).
_JOBS: dict[str, tuple[str, str]] = {}


@app.get("/")
def index():
    return FileResponse(_STATIC_DIR / "index.html")


@app.post("/api/analizar")
async def crear_analisis(archivo: UploadFile = File(...)):
    """Recibe el archivo de logs, lo guarda en memoria bajo un job_id y
    devuelve ese id -- el análisis en sí corre recién al conectarse el
    cliente a `/api/stream/{job_id}` (así el navegador puede mostrar la
    barra de progreso desde el primer evento, no solo al final)."""
    contenido = await archivo.read()

    # Validaciones de ingesta (Fase 12 del plan). Se aplican ANTES de
    # decodificar y de guardar el lote en memoria: rechazar temprano un
    # archivo desmedido o binario cuesta mucho menos que descubrirlo a
    # mitad del análisis.
    from src.config import LOG_MAX_FILE_BYTES

    if len(contenido) > LOG_MAX_FILE_BYTES:
        raise HTTPException(
            413,
            f"El archivo pesa {len(contenido)} bytes y el límite es "
            f"{LOG_MAX_FILE_BYTES}. Subí un lote más chico o ajustá "
            "LOG_MAX_FILE_BYTES.",
        )
    if b"\x00" in contenido[:8192]:
        raise HTTPException(
            415,
            "El archivo parece binario (contiene bytes nulos). Se esperan "
            "logs de texto: .log, .csv o .txt.",
        )

    raw_logs = contenido.decode("utf-8", errors="replace")

    if not raw_logs.strip():
        raise HTTPException(400, "El archivo está vacío.")

    job_id = uuid.uuid4().hex
    _JOBS[job_id] = (raw_logs, archivo.filename or "(sin nombre)")
    return {"job_id": job_id, "nombre_archivo": archivo.filename}


def _sse(evento: dict) -> str:
    return f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"


def _datos_para_historial(nombre_archivo: str | None, resumen: dict,
                          reporte: dict | None, error: str | None) -> dict:
    """Arma la fila del historial a partir de los eventos del stream.

    Se construye acá, en la capa de la API, y no dentro de
    `analizar_lote_stream()`: esa función la usan también el runner de CLI
    y los tests, y no debe cargar con responsabilidades de persistencia.
    """
    from src.config import LOG_PREPROCESSING_ENGINE

    reporte = reporte or {}
    return {
        "archivo_origen": nombre_archivo,
        "formato_detectado": resumen.get("formato_detectado"),
        "total_lineas": resumen.get("total_lineas"),
        "motor_preprocesamiento": LOG_PREPROCESSING_ENGINE,
        "diagnostico": reporte.get("diagnostico"),
        "confianza": reporte.get("confianza"),
        "hay_anomalia": reporte.get("hay_anomalia"),
        "hay_incidente": reporte.get("hay_incidente"),
        "requiere_revision_humana": reporte.get("requiere_revision_humana"),
        "n_comandos_mitigacion": len(reporte.get("comandos_mitigacion") or []),
        "evaluacion_auditor": reporte.get("evaluacion_auditor"),
        "tecnicas_mitre": reporte.get("tecnicas_mitre") or [],
        "estado": "error" if error else "completo",
        "error_mensaje": error,
        # Copia íntegra, para que el informe en PDF (Fase B) pueda armar sus
        # secciones sin volver a correr el grafo: la lista de comandos, la
        # ventana temporal, los servicios y los CVEs no tienen columna
        # propia y se perderían de otro modo.
        "resumen_json": resumen,
        "reporte_json": reporte or {},
    }


@app.get("/api/historial")
def listar_historial(limit: int = 50, offset: int = 0):
    """Corridas anteriores, de la más reciente a la más antigua."""
    return {
        "total": historial.contar_corridas(),
        "limit": limit,
        "offset": offset,
        "corridas": historial.listar_corridas(limit=limit, offset=offset),
    }


@app.get("/api/historial/{job_id}")
def detalle_historial(job_id: str):
    """Detalle de una corrida ya ejecutada.

    Devuelve el mismo shape que el evento `final` del streaming, para que
    la interfaz pueda reusar su función de render sin duplicar lógica.
    """
    corrida = historial.obtener_corrida(job_id)
    if corrida is None:
        raise HTTPException(404, f"No hay ninguna corrida con job_id {job_id}.")
    return corrida


@app.get("/api/historial/{job_id}/pdf")
def descargar_informe(job_id: str):
    """Informe de la corrida en PDF.

    Se arma con lo que quedó persistido: NO vuelve a correr el grafo, así
    que descargar el informe no cuesta cuota de LLM.
    """
    corrida = historial.obtener_corrida(job_id)
    if corrida is None:
        raise HTTPException(404, f"No hay ninguna corrida con job_id {job_id}.")
    pdf = generar_informe_pdf(corrida)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename=informe_{job_id}.pdf'},
    )



class Feedback(BaseModel):
    """Veredicto de un analista humano sobre una corrida."""

    correcto: bool
    comentario: str | None = None


@app.post("/api/feedback/{job_id}")
def registrar_feedback(job_id: str, cuerpo: Feedback):
    """Guarda el veredicto humano y lo propaga a la memoria de largo plazo.

    Es una escritura REAL a ChromaDB: lo que se guarda acá cambia lo que el
    RAG le muestra al Triage en corridas futuras. Por eso la interfaz pide
    confirmación antes de llamar a este endpoint.

    Sobrescribe un feedback previo a propósito: corregirse debe poder
    hacerse. La escritura a memoria vuelve a ocurrir en ese caso -- las
    colecciones son append-only, así que quedan las dos entradas; es el
    comportamiento de `commit_feedback()` y no se altera acá.
    """
    corrida = historial.obtener_corrida(job_id)
    if corrida is None:
        raise HTTPException(404, f"No hay ninguna corrida con job_id {job_id}.")

    historial.registrar_feedback(job_id, cuerpo.correcto, cuerpo.comentario)

    # `commit_feedback()` lee la firma del lote de `_firma`. El historial no
    # tiene columna propia para ella: viaja dentro del reporte. Las corridas
    # anteriores a que se guardara el reporte completo no la tienen, y sin
    # firma el documento que iría a ChromaDB sería la cadena vacía. En ese
    # caso el veredicto se guarda igual en la tabla y se avisa que no se
    # propagó -- decisión de Antonia (9-sep-2026), preferida sobre rechazar
    # el feedback o sobre reconstruir una firma que podría no coincidir con
    # la que realmente se usó en la corrida.
    firma = (corrida.get("reporte_json") or {}).get("firma")
    if not firma:
        return {
            "guardado": True,
            "memoria": None,
            "detalle": "La corrida no conserva la firma del lote (es anterior "
                       "al registro del reporte completo), así que el veredicto "
                       "no se propagó a la memoria de largo plazo.",
        }

    estado = {
        "_firma": firma,
        "diagnostico": corrida.get("diagnostico"),
        "confianza": corrida.get("confianza"),
    }

    correccion = None
    if not cuerpo.correcto:
        correccion = {
            "veredicto_humano": "incorrecto",
            "comentario": cuerpo.comentario or "",
            # `commit_feedback()` mergea `correccion` sobre el reporte ANTES
            # de llamar a `commit_validated()`, que promueve a
            # `attack_patterns` cuando la confianza supera AUTO_PROMOTE.
            # Sin este 0.0, marcar un diagnóstico como incorrecto lo dejaría
            # igual como ejemplar few-shot del Triage: verificado con un stub
            # el 9-sep-2026 sobre una corrida real de confianza 1.00, donde
            # `attack_patterns` pasaba de 1 a 2 documentos. La corrida sí
            # queda en `host_history`, para no perder la trazabilidad.
            "confianza": 0.0,
        }

    try:
        resultado = commit_feedback(estado, host="web", correccion=correccion)
    except Exception as e:  # noqa: BLE001
        # El veredicto ya quedó guardado en la tabla: un fallo de ChromaDB no
        # debe hacerlo perder ni devolver un 500 que sugiera lo contrario.
        return {"guardado": True, "memoria": None,
                "detalle": f"El veredicto se guardó, pero falló la escritura "
                           f"a la memoria de largo plazo: {e}"}

    return {"guardado": True, "memoria": resultado}

@app.get("/api/stream/{job_id}")
def stream_analisis(job_id: str):
    """Corre el pipeline sobre el lote guardado bajo `job_id` y transmite
    cada transición del grafo como un evento SSE. El job se consume al
    conectarse (no se puede volver a leer el mismo job_id dos veces) --
    si el navegador se recarga a mitad de un análisis, hay que subir el
    archivo de nuevo.

    Al cerrar el stream se registra el resultado en el historial
    (`src/api/historial.py`), tanto si terminó bien como si colapsó.
    """
    trabajo = _JOBS.pop(job_id, None)
    if trabajo is None:
        raise HTTPException(404, "job_id no encontrado o ya consumido. Sube el archivo de nuevo.")
    raw_logs, nombre_archivo = trabajo

    def generador():
        thread_id = f"web_{job_id}_{int(time.time())}"
        resumen: dict = {}
        reporte: dict | None = None
        error: str | None = None
        try:
            for evento in analizar_lote_stream(raw_logs, thread_id=thread_id):
                if evento.get("tipo") == "inicio":
                    resumen = evento.get("resumen") or {}
                elif evento.get("tipo") == "final":
                    reporte = evento.get("reporte") or {}
                elif evento.get("tipo") == "error":
                    error = evento.get("mensaje")
                yield _sse(evento)
        except Exception as e:
            # Salvaguarda: analizar_lote_stream ya captura errores de la API
            # del LLM y emite su propio evento "error", pero esto cubre
            # cualquier excepción que escape de esa captura (p. ej. un bug
            # en la agregación) para que el navegador reciba una señal
            # clara en vez de quedarse esperando indefinidamente.
            error = f"Error inesperado del servidor: {e}"
            yield _sse({"tipo": "error", "mensaje": error})
        finally:
            # Va en `finally` para que una desconexión del navegador a mitad
            # del análisis no pierda el resultado: el grafo igual corrió y
            # gastó cuota, así que el registro debe quedar.
            try:
                historial.registrar_corrida(
                    job_id,
                    _datos_para_historial(nombre_archivo, resumen, reporte, error),
                )
            except Exception as e:  # noqa: BLE001
                # Un fallo al guardar no debe romper el stream ya entregado.
                print(f"   ⚠️ No se pudo registrar la corrida {job_id} en el historial: {e}")

    return StreamingResponse(generador(), media_type="text/event-stream")
