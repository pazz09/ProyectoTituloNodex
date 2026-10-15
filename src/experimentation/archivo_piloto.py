"""Archivo etiquetado de los resultados crudos de un piloto: «piloto, no reportable».

Copia (NO mueve) todo lo que produjo una `config_version` a una carpeta propia y deja un
`MANIFIESTO.json` con la `config_version`, la huella de la configuración congelada, el commit, y el
SHA-256 de cada archivo copiado. Así la trazabilidad no depende de que las carpetas de trabajo
(`experiments/nodex`, `experiments/telemetry`...) sigan intactas.

Qué entra: los JSON de esas carpetas cuyo campo `config_version` es el pedido (las corridas, su
estado crudo, su telemetría, sus consultas externas y sus fallos), los registros de ejecución, las
consolidaciones y la configuración congelada. No entra nada de otra configuración.

Solo LEE los originales y no abre `ground_truth/`.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

CARPETAS_DE_CORRIDAS = ("nodex", "baseline", "gemini_externo", "telemetry", "fallos")
ETIQUETA = "piloto, no reportable"
NOMBRE_CARPETA = "piloto_no_reportable"


def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _config_version_de(ruta: Path) -> str | None:
    try:
        return json.loads(ruta.read_text(encoding="utf-8")).get("config_version")
    except (ValueError, OSError):
        return None


def archivos_de(raiz_repo: Path, config_version: str) -> list[tuple[Path, Path]]:
    """`[(origen, ruta_relativa_dentro_del_archivo)]` de todo lo de esa configuración."""
    exp = raiz_repo / "experiments"
    encontrados: list[tuple[Path, Path]] = []
    for carpeta in CARPETAS_DE_CORRIDAS:
        base = exp / carpeta
        for ruta in sorted(base.rglob("*.json")) if base.is_dir() else []:
            if _config_version_de(ruta) == config_version:
                encontrados.append((ruta, Path(carpeta) / ruta.relative_to(base)))
    for carpeta in ("ejecucion", "metrics"):
        base = exp / carpeta / config_version
        for ruta in sorted(p for p in base.rglob("*") if p.is_file()) if base.is_dir() else []:
            encontrados.append((ruta, Path(carpeta) / config_version / ruta.relative_to(base)))
    config = exp / "config" / f"config_{config_version}.json"
    if config.is_file():
        encontrados.append((config, Path("config") / config.name))
    return encontrados


def archivar(raiz_repo: Path, config_version: str, destino_base: Path | None = None) -> dict:
    """Copia los resultados crudos a `experiments/piloto_no_reportable/<config_version>/`."""
    destino_base = destino_base or (raiz_repo / "experiments" / NOMBRE_CARPETA)
    destino = destino_base / config_version
    if destino.exists():
        raise FileExistsError(f"{destino} ya existe: un archivo de piloto no se sobrescribe")
    archivos = archivos_de(raiz_repo, config_version)
    if not archivos:
        raise FileNotFoundError(f"no hay resultados de {config_version} para archivar")
    config_ruta = raiz_repo / "experiments" / "config" / f"config_{config_version}.json"
    config = json.loads(config_ruta.read_text(encoding="utf-8")) if config_ruta.is_file() else {}

    hashes, por_carpeta = {}, {}
    for origen, relativa in archivos:
        copia = destino / relativa
        copia.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origen, copia)
        hashes[relativa.as_posix()] = _sha256(copia)
        por_carpeta[relativa.parts[0]] = por_carpeta.get(relativa.parts[0], 0) + 1
    manifiesto = {
        "etiqueta": ETIQUETA,
        "aviso": ("Resultados de DEPURACIÓN. No son reportables y no se citan en el informe. Se "
                  "guardan solo para que la trazabilidad no se pierda."),
        "config_version": config_version,
        "huella_de_la_configuracion": config.get("huella"),
        "commit_congelado": (config.get("git") or {}).get("commit"),
        "arbol_limpio_al_congelar": (config.get("git") or {}).get("arbol_limpio"),
        "archivado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "es_una_copia": "los originales siguen en experiments/<carpeta>/; este archivo no los reemplaza",
        "n_archivos": len(hashes), "archivos_por_carpeta": por_carpeta,
        "sha256": hashes,
    }
    (destino / "MANIFIESTO.json").write_text(
        json.dumps(manifiesto, indent=2, ensure_ascii=False), encoding="utf-8")
    (destino / "LEEME.txt").write_text(
        f"{ETIQUETA.upper()}\n\nconfig_version: {config_version}\n"
        f"huella: {config.get('huella')}\n\nEstos resultados son de DEPURACIÓN.\n"
        f"No se citan en el informe. Ver MANIFIESTO.json para el hash de cada archivo.\n",
        encoding="utf-8")
    return manifiesto


def verificar(destino: Path) -> list[str]:
    """Compara cada archivo archivado con su hash del manifiesto. Devuelve los que no coinciden."""
    manifiesto = json.loads((destino / "MANIFIESTO.json").read_text(encoding="utf-8"))
    malos = []
    for relativa, esperado in manifiesto["sha256"].items():
        ruta = destino / relativa
        if not ruta.is_file() or _sha256(ruta) != esperado:
            malos.append(relativa)
    return malos
