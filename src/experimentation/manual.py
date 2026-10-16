"""Evaluación MANUAL: analizar un caso a la vez desde la interfaz y ver sus métricas en «Resultados».

Flujo
-----
1. La persona adjunta en la interfaz un archivo que es un caso del experimento (`uwf_eva_visible_0004.csv`,
   `bgl_eva_natural_0016.log`, ...) y NODEX lo analiza como siempre.
2. Al terminar el análisis, la API llama a `registrar()`: si el nombre del archivo es un caso conocido **y su
   contenido es idéntico al del caso**, guarda el resultado en el mismo formato que el experimento
   (`experiments/nodex/`, `telemetry/`) bajo la configuración `manual-<partición>`.
3. «Resultados» pide `construir_resumen()`: se consolida con la MISMA evaluación del experimento
   (`consolidacion.consolidar`) y se devuelve el `resumen.json` al vuelo, sin acumular carpetas.

Solo NODEX: ni Gemini directo ni el baseline.

## Qué NO hace
- NO le pasa nada de la referencia a NODEX: la etiqueta se lee únicamente al consolidar (`evaluacion.py`), después
  de guardado el análisis y en otra función.
- NO acepta un archivo cuyo nombre sea de un caso pero cuyo contenido difiera: lo rechaza y dice por qué, para
  que unas métricas «del caso X» no se calculen sobre otro texto.
- NO decide qué es reportable. El resumen lleva un aviso: no hay configuración congelada ni verificación del
  entorno; eso lo garantiza quien lo lanza (ver `docs/experimentacion/estado_preparacion.md`, sección 26).
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from src.experimentation.runtime import persistencia
from src.experimentation.runtime.identidad import IdentidadCorrida

ARQUITECTURA = "nodex_multiagente"
PREFIJO_CONFIG = "manual-"
PARTICIONES = {"des": "desarrollo", "eva": "evaluacion"}
_CASO = re.compile(r"^(bgl|uwf|hdfs)_(des|eva)_[a-z]+_[0-9]{4}$")


def config_de(particion: str) -> str:
    return f"{PREFIJO_CONFIG}{particion}"


def _normalizar(texto: str) -> str:
    return texto.replace("\r\n", "\n").replace("\r", "\n")


def _sha(texto: str) -> str:
    return hashlib.sha256(_normalizar(texto).encode("utf-8")).hexdigest()


def identificar_caso(raiz_repo: Path, nombre_archivo: str | None, contenido: str) -> dict:
    """¿El archivo es un caso del experimento? Devuelve `{"reconocido": bool, "motivo": str, ...}`.

    No abre `ground_truth/`: solo el caso (que es lo que se le va a dar a NODEX de todos modos).
    """
    stem = Path(nombre_archivo or "").stem
    m = _CASO.fullmatch(stem)
    if not m:
        return {"reconocido": False,
                "motivo": "el nombre del archivo no es el de un caso del experimento "
                          "(p. ej. uwf_eva_visible_0004.csv): se analiza pero no entra a las métricas"}
    dataset, particion = m.group(1), PARTICIONES[m.group(2)]
    directorio = raiz_repo / "experiments" / "cases" / dataset / particion
    meta_ruta = directorio / f"{stem}.json"
    if not meta_ruta.is_file():
        return {"reconocido": False, "motivo": f"no existe el caso {stem} en el experimento"}
    meta = json.loads(meta_ruta.read_text(encoding="utf-8"))
    original = None
    for extension in ("log", "csv"):
        ruta = directorio / f"{stem}.{extension}"
        if ruta.is_file():
            original = ruta.read_text(encoding="utf-8")
            break
    if original is None:
        return {"reconocido": False, "motivo": f"el caso {stem} no tiene archivo de contenido"}
    if _sha(original) != _sha(contenido):
        return {"reconocido": False,
                "motivo": f"el contenido del archivo NO coincide con el caso {stem} del experimento "
                          f"(se analiza, pero no se calculan métricas sobre otro texto)"}
    return {"reconocido": True, "motivo": "caso del experimento, contenido idéntico",
            "case_id": stem, "dataset": dataset, "particion": particion,
            "tipo_deteccion": meta["tipo_deteccion"],
            "dimensiones": tuple(meta.get("dimensiones_aplicables") or ())}


def _siguiente_repeticion(raiz_repo: Path, caso: dict, config: str) -> int:
    n = 1
    while persistencia.ya_existe(
            IdentidadCorrida(caso["case_id"], caso["dataset"], ARQUITECTURA, n, config), raiz_repo):
        n += 1
    return n


def _configuracion_efectiva() -> dict:
    """Parámetros con los que corrió el análisis (lo que ve `src.config`), para poder auditar la corrida."""
    import src.config as c

    nombres = ("LLM_MODEL_PRIMARY", "LLM_MODEL_FALLBACK", "LLM_SIN_RESPALDO", "TEMPERATURE",
               "REPUTACION_SIN_ENRIQUECIMIENTO", "TOP_K_FEWSHOT", "CHROMA_PATH", "EMBEDDING_MODEL")
    return {n: str(getattr(c, n)) if n == "CHROMA_PATH" else getattr(c, n, None) for n in nombres}


def _asegurar_config(raiz_repo: Path, config: str, efectiva: dict) -> None:
    """Deja `config_<config>.json` con el modelo (lo usa la tabla de consumo para detectar fallback).
    NO es una configuración congelada y lo declara."""
    ruta = raiz_repo / "experiments" / "config" / f"config_{config}.json"
    if ruta.is_file():
        return
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({
        "config_version": config, "congelada": False,
        "aviso": "evaluación manual: NO es una configuración congelada (sin huella ni commit)",
        "parametros": {k: v for k, v in efectiva.items() if k != "CHROMA_PATH"},
    }, indent=2, ensure_ascii=False), encoding="utf-8")


def registrar(raiz_repo: Path, job_id: str, nombre_archivo: str | None, contenido: str,
              reporte: dict | None, error: str | None) -> dict:
    """Guarda un análisis hecho desde la interfaz si es un caso del experimento.

    Devuelve `{"registrado": bool, "motivo": str, ...}`; nunca lanza por no reconocer el archivo.
    """
    from src.experimentation.adapters.nodex import adaptar
    from src.experimentation.runners import nodex
    from src.experimentation.runtime.telemetria import campos_de_modelo

    caso = identificar_caso(raiz_repo, nombre_archivo, contenido)
    if not caso["reconocido"]:
        return {"registrado": False, "motivo": caso["motivo"]}

    config = config_de(caso["particion"])
    efectiva = _configuracion_efectiva()
    _asegurar_config(raiz_repo, config, efectiva)
    repeticion = _siguiente_repeticion(raiz_repo, caso, config)
    identidad = IdentidadCorrida(caso["case_id"], caso["dataset"], ARQUITECTURA, repeticion, config)

    if error or not reporte:
        estado = nodex.clasificar_error(error or "")
        persistencia.guardar_fallo(identidad, raiz_repo, estado=estado, error=error or "sin reporte")
        return {"registrado": False, "motivo": f"el análisis falló ({estado}): quedó como fallo, sin métricas",
                "case_id": caso["case_id"], "repeticion": repeticion}

    # El reporte final del stream ya trae los campos del contrato (veredicto, eventos, técnicas MITRE),
    # así que se adapta igual que el estado final de una corrida del experimento.
    estado_ejecucion = nodex.estado_de_ejecucion({"error": None}, reporte)
    adaptado = adaptar(
        reporte, case_id=caso["case_id"], run_id=identidad.run_id,
        tipo_deteccion=caso["tipo_deteccion"], dimensiones_aplicables=caso["dimensiones"],
        arquitectura=ARQUITECTURA, raw_output_ref=persistencia.rutas(identidad, raiz_repo).crudo.name)
    salida = adaptado.salida.to_dict()
    if estado_ejecucion == "completa" and adaptado.salida.classification is None:
        estado_ejecucion = "error_contrato"
    medido = dict(reporte.get("telemetry") or {})
    telemetria = dict(
        medido, **campos_de_modelo(medido),
        previa_a_d11=False, output_contract_version=reporte.get("output_contract_version"),
        diagnostico_runner={"origen": "interfaz_web", "job_id": job_id, "error": None,
                            "configuracion_efectiva": efectiva},
    )
    persistencia.guardar(
        identidad, raiz_repo, salida=salida,
        crudo={**reporte, "_job_id": job_id, "_configuracion_efectiva": efectiva},
        telemetria=telemetria,
        ejecucion={"estado": estado_ejecucion, "estados_por_dimension": adaptado.estado_por_dimension,
                   "iniciado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    return {"registrado": True, "motivo": "registrado en las métricas manuales", "case_id": caso["case_id"],
            "dataset": caso["dataset"], "particion": caso["particion"], "repeticion": repeticion,
            "run_id": identidad.run_id, "config_version": config}


def particiones_con_analisis(raiz_repo: Path) -> list[str]:
    """Particiones (`desarrollo`/`evaluacion`) que tienen al menos un análisis manual guardado."""
    return [p for p in PARTICIONES.values() if _casos_guardados(raiz_repo, config_de(p))]


def _casos_guardados(raiz_repo: Path, config: str) -> dict[tuple[str, str], int]:
    """`{(dataset, case_id): repeticiones_guardadas}` de la configuración manual."""
    carpeta = raiz_repo / "experiments" / persistencia.CARPETA_POR_ARQUITECTURA[ARQUITECTURA]
    encontrados: dict[tuple[str, str], int] = {}
    if not carpeta.is_dir():
        return encontrados
    for ruta in carpeta.glob("*/*.json"):
        if ruta.name.endswith(".raw.json"):
            continue
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        if datos.get("config_version") != config:
            continue
        clave = (datos["dataset"], datos["case_id"])
        encontrados[clave] = max(encontrados.get(clave, 0), int(datos["repeticion"]))
    return encontrados


def construir_resumen(raiz_repo: Path, particion: str) -> dict | None:
    """El `resumen.json` de las métricas manuales de una partición, o `None` si no hay análisis.

    Consolida con la evaluación del experimento en una carpeta temporal: no acumula consolidaciones.
    Las repeticiones esperadas son las que hay (no las del protocolo): quien analiza decide cuántas veces.
    """
    from src.experimentation import consolidacion

    config = config_de(particion)
    casos = _casos_guardados(raiz_repo, config)
    if not casos:
        return None
    por_estrato: dict[str, dict[str, list[str]]] = {}
    for (dataset, case_id) in sorted(casos):
        condicion = case_id.split("_")[2]
        por_estrato.setdefault(dataset, {}).setdefault(condicion, []).append(case_id)
    nombre = f"manual-{particion}"
    subconjunto = {
        "proposito": "evaluación manual desde la interfaz (derivado de los análisis guardados)",
        "particion": particion,
        "datasets": {d: {c: {"case_ids": ids} for c, ids in conds.items()} for d, conds in por_estrato.items()},
    }
    destino_subconjunto = raiz_repo / "experiments" / "subconjuntos" / f"{nombre}.json"
    destino_subconjunto.parent.mkdir(parents=True, exist_ok=True)
    destino_subconjunto.write_text(json.dumps(subconjunto, indent=2, ensure_ascii=False), encoding="utf-8")

    repeticiones = max(casos.values())
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        carpeta = consolidacion.consolidar(
            raiz_repo, nombre, config, (ARQUITECTURA,), raiz_destino=Path(tmp),
            marca=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            depuracion=particion != "evaluacion", repeticiones=repeticiones)
        resumen = json.loads((carpeta / "resumen.json").read_text(encoding="utf-8"))

    resumen["analisis_manual"] = True
    resumen["integridad"].setdefault("advertencias", []).insert(0, {
        "codigo": "analisis_manual", "severidad": "info", "n": len(casos),
        "mensaje": ("Análisis manual hecho desde la interfaz, solo NODEX: "
                    f"{len(casos)} caso(s) y {sum(casos.values())} análisis. No hay configuración congelada ni "
                    "verificación automática del entorno (modelo, respaldo, reputación, base de conocimiento): "
                    "queda registrada en cada corrida (`configuracion_efectiva`) y es responsabilidad de quien "
                    "lanza la interfaz. Gemini directo y el baseline no forman parte de este análisis."),
    })
    return resumen
