"""Lanzador local; ejemplo: python tools/prepare_rag_enriquecido.py poblar.

Permite reutilizar las dependencias locales de este checkout con el Python
registrado en R1, aunque el ejecutable base de .venv ya no esté disponible.
No instala paquetes y no cambia configuraciones del equipo.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
local_paths = [ROOT]
for relative in (".venv/Lib/site-packages", "tmp/d11-test-deps", "tmp/rag-preparation-deps"):
    path = ROOT / relative
    if path.is_dir():
        local_paths.append(path)
sys.path[:0] = [str(p) for p in local_paths]
os.environ["PYTHONPATH"] = os.pathsep.join([*[str(p) for p in local_paths], os.environ.get("PYTHONPATH", "")])
os.environ["PYTHONUTF8"] = "1"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from src.experimentation.knowledge.rag_enriquecido import main

if __name__ == "__main__":
    main()
