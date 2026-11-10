"""Endpoints de solo lectura para la vista "Resultados".

Sirven lo que `src/experimentation/consolidacion.py` dejó escrito en
`experiments/metrics/` y los reportes de las corridas guardadas. Nada más.

## Lo que este módulo NO hace, a propósito

- **No abre `experiments/ground_truth/`.** La referencia solo la ve el
  evaluador. Este módulo ni siquiera contiene esa ruta, y una prueba lo
  verifica por AST; otra deja un archivo centinela en esa carpeta y comprueba
  que ningún endpoint lo devuelva.
- **No invoca modelos ni importa el pipeline, los agentes o el cliente LLM.**
  Leer resultados no cuesta cuota.
- **No escribe.** Todas las rutas son GET.
- **No lee el estado crudo de las corridas** (`raw/`), que puede traer
  muestras del log. Del archivo de salida solo sale el texto del reporte y
  los metadatos de la corrida.

## Validación de la URL

`config_version`, la marca de consolidación y el `run_id` se validan con
expresiones regulares estrictas antes de tocar el disco, y la ruta resultante
se comprueba contra la carpeta de experimentos. Sin eso, un `config_version`
con `..` permitiría leer fuera de `experiments/`.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from src.experimentation.runtime.persistencia import CARPETA_POR_ARQUITECTURA

router = APIRouter(prefix="/api/resultados", tags=["resultados"])

#: ¿«Resultados» lista también las consolidaciones del EXPERIMENTO (piloto y campaña) que hay en
#: `experiments/metrics/`? Por omisión NO: la pantalla muestra solo las métricas de los análisis manuales hechos
#: desde la interfaz y, mientras no haya ninguno, el estado vacío. Los datos del experimento siguen guardados y
#: se pueden ver con `RESULTADOS_MOSTRAR_EXPERIMENTO=1`. Es una variable de módulo para poder probarla.
MOSTRAR_EXPERIMENTO: bool = os.environ.get("RESULTADOS_MOSTRAR_EXPERIMENTO") == "1"

#: Carpeta de experimentos. Es una variable de módulo para que las pruebas la
#: puedan apuntar a un directorio temporal.
RAIZ_EXPERIMENTOS: Path = Path(__file__).resolve().parents[2] / "experiments"

_CONFIG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MARCA = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")
_RUN_ID = re.compile(r"^[a-z0-9_]+__(nodex|gemext|unico|reglas)__r[0-9]+__[0-9a-f]{8}$")


def _validar(patron: re.Pattern, valor: str, nombre: str) -> str:
    if not patron.fullmatch(valor):
        raise HTTPException(status_code=400, detail=f"{nombre} con formato inválido")
    return valor


def _dentro_de_experimentos(ruta: Path) -> Path:
    """Falla si `ruta` queda fuera de la carpeta de experimentos."""
    base = RAIZ_EXPERIMENTOS.resolve()
    real = ruta.resolve()
    if not real.is_relative_to(base):
        raise HTTPException(status_code=400, detail="ruta fuera de experiments/")
    return real


def _leer_json(ruta: Path) -> dict:
    return json.loads(_dentro_de_experimentos(ruta).read_text(encoding="utf-8"))


def _marcas(config_dir: Path) -> list[str]:
    """Consolidaciones de una configuración que tienen `resumen.json`."""
    if not config_dir.is_dir():
        return []
    return sorted(
        d.name for d in config_dir.iterdir()
        if d.is_dir() and _MARCA.fullmatch(d.name) and (d / "resumen.json").is_file()
    )


@router.get("")
def listar_resultados():
    """Configuraciones con al menos una consolidación, y sus marcas.

    Sin consolidaciones devuelve una lista vacía, no un error: es el estado
    normal antes de que exista ninguna campaña.
    """
    raiz = RAIZ_EXPERIMENTOS / "metrics"
    configuraciones = []
    if MOSTRAR_EXPERIMENTO and raiz.is_dir():
        for carpeta in sorted(raiz.iterdir()):
            if not carpeta.is_dir() or not _CONFIG.fullmatch(carpeta.name):
                continue
            marcas = _marcas(carpeta)
            if marcas:
                configuraciones.append({
                    "config_version": carpeta.name,
                    "consolidaciones": marcas,
                    "ultima": marcas[-1],
                })
    # Métricas de la evaluación manual (solo NODEX), armadas al vuelo desde los análisis guardados.
    from datetime import datetime, timezone
    from src.experimentation import manual
    ahora = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for particion in manual.particiones_con_analisis(RAIZ_EXPERIMENTOS.parent):
        configuraciones.append({"config_version": manual.config_de(particion),
                                "consolidaciones": [ahora], "ultima": ahora})
    return {"configuraciones": configuraciones}


@router.get("/{config_version}")
def obtener_resultados(config_version: str, consolidacion: str | None = None):
    """El `resumen.json` de una consolidación (la última, si no se indica)."""
    _validar(_CONFIG, config_version, "config_version")
    from src.experimentation import manual
    if config_version.startswith(manual.PREFIJO_CONFIG):
        particion = config_version[len(manual.PREFIJO_CONFIG):]
        if particion not in manual.PARTICIONES.values():
            raise HTTPException(status_code=404, detail="partición manual desconocida")
        resumen = manual.construir_resumen(RAIZ_EXPERIMENTOS.parent, particion)
        if resumen is None:
            raise HTTPException(status_code=404, detail="todavía no hay análisis manuales guardados")
        return resumen
    carpeta = RAIZ_EXPERIMENTOS / "metrics" / config_version
    marcas = _marcas(carpeta)
    if not marcas:
        raise HTTPException(status_code=404, detail="no hay resultados para esa configuración")
    if consolidacion is None:
        marca = marcas[-1]
    else:
        marca = _validar(_MARCA, consolidacion, "consolidacion")
        if marca not in marcas:
            raise HTTPException(status_code=404, detail="no existe esa consolidación")
    return _leer_json(carpeta / marca / "resumen.json")


@router.get("/{config_version}/reportes/{run_id}")
def obtener_reporte(config_version: str, run_id: str):
    """El reporte que produjo una corrida, y nada más de ella.

    Devuelve el texto y los metadatos del archivo de salida. No devuelve el
    estado crudo ni la telemetría.
    """
    _validar(_CONFIG, config_version, "config_version")
    _validar(_RUN_ID, run_id, "run_id")

    for carpeta in sorted(set(CARPETA_POR_ARQUITECTURA.values())):
        for archivo in sorted((RAIZ_EXPERIMENTOS / carpeta).glob(f"*/{run_id}.json")):
            datos = _leer_json(archivo)
            if datos.get("run_id") != run_id:
                continue
            # El mismo run_id no puede existir en dos configuraciones (la
            # configuración entra en su hash), pero se comprueba igual: no se
            # sirve la corrida de otra campaña bajo esta URL.
            if datos.get("config_version") != config_version:
                raise HTTPException(status_code=404, detail="la corrida es de otra configuración")
            salida = datos.get("salida") or {}
            meta = salida.get("_meta") or {}
            ejecucion = datos.get("ejecucion") or {}
            return {
                "run_id": run_id,
                "case_id": datos.get("case_id"),
                "dataset": datos.get("dataset"),
                "arquitectura": datos.get("arquitectura"),
                "repeticion": datos.get("repeticion"),
                "estado_ejecucion": ejecucion.get("estado"),
                "clasificacion": salida.get("classification"),
                "motivo_no_evaluable": meta.get("motivo_no_evaluable"),
                "reporte": (salida.get("report") or {}).get("summary"),
            }
    raise HTTPException(status_code=404, detail="no existe esa corrida")
