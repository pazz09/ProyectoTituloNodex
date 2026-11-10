"""Procedencia reproducible para artefactos de evaluación.

La Fase 6 del cierre de auditoría exige que una métrica pueda asociarse al
código, configuración, datasets y entorno que la produjeron. Este módulo
centraliza esa información para que el baseline y la evaluación multiagente
no mantengan contratos distintos.
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


RESULT_SCHEMA_VERSION = "2.0"


def _git(args: list[str], repo_root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return None


def commit_git(repo_root: Path) -> str | None:
    """Hash completo de HEAD o ``None`` si Git no está disponible."""
    return _git(["rev-parse", "HEAD"], repo_root)


def estado_git(repo_root: Path) -> dict:
    """Identifica rama y limpieza del árbol sin impedir una corrida.

    ``working_tree_dirty`` queda en ``None`` cuando el comando no puede
    ejecutarse. Un resultado generado con ``True`` sigue siendo auditable,
    pero no debe publicarse como evidencia final de un commit limpio.
    """
    estado = _git(["status", "--porcelain", "--untracked-files=normal"], repo_root)
    # Los JSON de `results/` son la salida esperada de la evaluación. No son
    # código fuente y, tras la primera corrida, volverían "sucias" todas las
    # corridas siguientes aunque el commit evaluado no cambiara. Se ignoran
    # solo para este indicador; cualquier cambio fuera de results/ sí impide
    # certificar un cierre limpio.
    if estado is None:
        dirty = None
    else:
        lineas_relevantes = []
        for linea in estado.splitlines():
            ruta = linea[3:].strip().strip('"').replace("\\", "/")
            if ruta.startswith("results/"):
                continue
            lineas_relevantes.append(linea)
        dirty = bool(lineas_relevantes)
    return {
        "commit": commit_git(repo_root),
        "git_branch": _git(["rev-parse", "--abbrev-ref", "HEAD"], repo_root),
        "working_tree_dirty": dirty,
        "working_tree_ignored_paths": ["results/"],
    }


def sha256_archivo(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest()


def procedencia_archivos(paths: list[Path], repo_root: Path) -> list[dict]:
    """Nombre, tamaño y hash de cada dataset/label usado en una corrida."""
    salida = []
    for path in paths:
        resolved = path.resolve()
        try:
            nombre = resolved.relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            nombre = str(resolved)
        salida.append({
            "path": nombre,
            "bytes": resolved.stat().st_size,
            "sha256": sha256_archivo(resolved),
        })
    return salida


def procedencia_ejecucion(repo_root: Path) -> dict:
    """Contrato común de procedencia para todos los resultados de Fase 6."""
    from src.config import (
        LOG_NORMALIZATION_SCHEMA_VERSION,
        LOG_PREPROCESSING_ENGINE,
        config_preprocesamiento_efectiva,
    )

    git = estado_git(repo_root)
    requirements = repo_root / "requirements.txt"
    constraints = repo_root / "constraints.txt"
    return {
        "result_schema_version": RESULT_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "motor_preprocesamiento": LOG_PREPROCESSING_ENGINE,
        "schema_version": LOG_NORMALIZATION_SCHEMA_VERSION,
        "config_preprocesamiento": config_preprocesamiento_efectiva(),
        **git,
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "requirements_sha256": sha256_archivo(requirements) if requirements.exists() else None,
        "constraints_sha256": sha256_archivo(constraints) if constraints.exists() else None,
        "python_executable": Path(sys.executable).name,
    }
