"""Historial de corridas del panel de análisis (Fase A).

Persiste el resultado de cada análisis lanzado desde la interfaz web, para
poder revisarlo después sin volver a correr el grafo — y, con eso, sin
volver a gastar cuota de LLM.

Usa `sqlite3` de la librería estándar: no agrega dependencias, el archivo
vive junto al resto de los datos locales (`data/historial.db`, ignorado por
git como `data/chroma/`), y encaja con el modelo de distribución
autohospedado, donde el cliente instala el sistema en su propia
infraestructura y no queremos obligarlo a levantar un motor de base de
datos aparte.

Este módulo **solo almacena**. No sabe nada del grafo ni del LLM: el enganche
con el streaming vive en `src/api/main.py`, para que `analizar_lote_stream()`
siga libre de responsabilidades de persistencia — lo usan también el runner
de CLI y los tests.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
RUTA_DB = _RAIZ / "data" / "historial.db"

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS corridas (
    job_id                   TEXT PRIMARY KEY,
    timestamp                TEXT NOT NULL,
    archivo_origen           TEXT,
    formato_detectado        TEXT,
    total_lineas             INTEGER,
    motor_preprocesamiento   TEXT,
    diagnostico              TEXT,
    confianza                REAL,
    hay_anomalia             INTEGER,
    hay_incidente            INTEGER,
    requiere_revision_humana INTEGER,
    n_comandos_mitigacion    INTEGER,
    evaluacion_auditor       TEXT,
    tecnicas_mitre           TEXT,
    estado                   TEXT NOT NULL,
    error_mensaje            TEXT,
    feedback_correcto        INTEGER,
    feedback_comentario      TEXT,
    feedback_timestamp       TEXT
);
CREATE INDEX IF NOT EXISTS idx_corridas_timestamp ON corridas (timestamp DESC);
"""

# Columnas en el orden del esquema, para armar el INSERT sin repetirlas.
_COLUMNAS = (
    "job_id", "timestamp", "archivo_origen", "formato_detectado",
    "total_lineas", "motor_preprocesamiento", "diagnostico", "confianza",
    "hay_anomalia", "hay_incidente", "requiere_revision_humana",
    "n_comandos_mitigacion", "evaluacion_auditor", "tecnicas_mitre",
    "estado", "error_mensaje", "feedback_correcto", "feedback_comentario",
    "feedback_timestamp",
)

# Columnas que se guardan como JSON serializado y vuelven deserializadas.
_COLUMNAS_JSON = ("tecnicas_mitre",)

# Columnas que SQLite guarda como entero y el resto del sistema espera como
# booleano. `None` se conserva: en `feedback_correcto` significa "todavía no
# hubo feedback", que es distinto de "el feedback fue negativo".
_COLUMNAS_BOOL = ("hay_anomalia", "hay_incidente", "requiere_revision_humana",
                  "feedback_correcto")


def _conectar(ruta: str | Path | None = None) -> sqlite3.Connection:
    destino = Path(ruta) if ruta is not None else RUTA_DB
    destino.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(destino)
    con.row_factory = sqlite3.Row
    return con


def init_db(ruta: str | Path | None = None) -> None:
    """Crea la tabla si no existe. Idempotente."""
    with _conectar(ruta) as con:
        con.executescript(_ESQUEMA)


def _ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _a_fila(job_id: str, datos: dict) -> dict:
    """Normaliza un dict de corrida a los tipos que espera SQLite."""
    fila = {
        "job_id": job_id,
        "timestamp": datos.get("timestamp") or _ahora(),
        "archivo_origen": datos.get("archivo_origen"),
        "formato_detectado": datos.get("formato_detectado"),
        "total_lineas": datos.get("total_lineas"),
        "motor_preprocesamiento": datos.get("motor_preprocesamiento"),
        "diagnostico": datos.get("diagnostico"),
        "confianza": datos.get("confianza"),
        "hay_anomalia": datos.get("hay_anomalia"),
        "hay_incidente": datos.get("hay_incidente"),
        "requiere_revision_humana": datos.get("requiere_revision_humana"),
        "n_comandos_mitigacion": datos.get("n_comandos_mitigacion"),
        "evaluacion_auditor": datos.get("evaluacion_auditor"),
        "tecnicas_mitre": datos.get("tecnicas_mitre"),
        "estado": datos.get("estado") or "completo",
        "error_mensaje": datos.get("error_mensaje"),
        "feedback_correcto": datos.get("feedback_correcto"),
        "feedback_comentario": datos.get("feedback_comentario"),
        "feedback_timestamp": datos.get("feedback_timestamp"),
    }
    for col in _COLUMNAS_JSON:
        if fila[col] is not None and not isinstance(fila[col], str):
            fila[col] = json.dumps(fila[col], ensure_ascii=False)
    for col in _COLUMNAS_BOOL:
        if fila[col] is not None:
            fila[col] = int(bool(fila[col]))
    return fila


def _desde_fila(fila: sqlite3.Row) -> dict:
    d = dict(fila)
    for col in _COLUMNAS_JSON:
        if d.get(col):
            try:
                d[col] = json.loads(d[col])
            except (TypeError, ValueError):
                # Un JSON corrupto no debe romper la lectura del historial:
                # se devuelve el texto crudo y queda visible el problema.
                pass
        elif col in d:
            d[col] = []
    for col in _COLUMNAS_BOOL:
        if d.get(col) is not None:
            d[col] = bool(d[col])
    return d


def registrar_corrida(job_id: str, datos: dict, ruta: str | Path | None = None) -> None:
    """Guarda (o reemplaza) el resultado de una corrida.

    Es un `INSERT OR REPLACE`: reintentar el mismo `job_id` sobrescribe en
    vez de fallar. En la práctica los `job_id` son únicos por subida, pero
    una escritura idempotente evita que un reintento del hook tumbe la
    respuesta al navegador por una violación de clave primaria.
    """
    init_db(ruta)
    fila = _a_fila(job_id, datos)
    marcadores = ", ".join("?" for _ in _COLUMNAS)
    with _conectar(ruta) as con:
        con.execute(
            f"INSERT OR REPLACE INTO corridas ({', '.join(_COLUMNAS)}) "
            f"VALUES ({marcadores})",
            tuple(fila[c] for c in _COLUMNAS),
        )


def listar_corridas(limit: int = 50, offset: int = 0,
                    ruta: str | Path | None = None) -> list[dict]:
    """Corridas de la más reciente a la más antigua."""
    init_db(ruta)
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    with _conectar(ruta) as con:
        filas = con.execute(
            "SELECT * FROM corridas ORDER BY timestamp DESC, rowid DESC "
            "LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return [_desde_fila(f) for f in filas]


def contar_corridas(ruta: str | Path | None = None) -> int:
    init_db(ruta)
    with _conectar(ruta) as con:
        return con.execute("SELECT COUNT(*) FROM corridas").fetchone()[0]


def obtener_corrida(job_id: str, ruta: str | Path | None = None) -> dict | None:
    """Detalle de una corrida, o `None` si no existe."""
    init_db(ruta)
    with _conectar(ruta) as con:
        fila = con.execute(
            "SELECT * FROM corridas WHERE job_id = ?", (job_id,)
        ).fetchone()
    return _desde_fila(fila) if fila is not None else None


def registrar_feedback(job_id: str, correcto: bool, comentario: str | None = None,
                       ruta: str | Path | None = None) -> bool:
    """Guarda el feedback humano sobre una corrida. `False` si no existe.

    Sobrescribe el feedback previo a propósito: corregirse debe poder
    hacerse. La escritura a la memoria de largo plazo NO ocurre acá — este
    módulo solo almacena; ese enganche vive en la capa de la API (Fase C).
    """
    init_db(ruta)
    with _conectar(ruta) as con:
        cur = con.execute(
            "UPDATE corridas SET feedback_correcto = ?, feedback_comentario = ?, "
            "feedback_timestamp = ? WHERE job_id = ?",
            (int(bool(correcto)), comentario, _ahora(), job_id),
        )
        return cur.rowcount > 0
