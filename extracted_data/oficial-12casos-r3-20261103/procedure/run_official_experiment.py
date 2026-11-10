"""Una ejecución de NODEX por caso; nunca reintenta una corrida iniciada.

Preparación sin inferencia: python tools/run_official_experiment.py
Ejecución autorizada:      python tools/run_official_experiment.py --execute
No carga referencias ni ejecuta evaluadores. Usa el lanzador experimental existente.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
VERSION = "oficial-12casos-r1-20261028"
SELECTION = [
    ("bgl_eva_balanceado_0006", 4508, "2a2bcc77d048"),
    ("uwf_eva_visible_0004", 54423, "0d4071a365a4"),
    ("bgl_eva_natural_0031", 2883, "20652575733d"),
    ("bgl_eva_balanceado_0005", 3561, "2008dee210b9"),
    ("bgl_eva_natural_0016", 3854, "f1c3d8073b9d"),
    ("uwf_eva_visible_0027", 55827, "238147cd629c"),
    ("uwf_eva_sigiloso_0018", 55837, "06b7f50fbf3a"),
    ("bgl_eva_natural_0002", 3649, "3e940e80ba8c"),
    ("bgl_eva_balanceado_0001", 3377, "d9f611c54de7"),
    ("uwf_eva_sigiloso_0024", 55789, "088b5c7eb207"),
    ("uwf_eva_visible_0028", 55798, "9900e2ceead9"),
    ("uwf_eva_sigiloso_0013", 55954, "ad62ecef6ee0"),
]


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def validate_inputs(root=ROOT):
    rows = []
    for order, (case, size, prefix) in enumerate(SELECTION, 1):
        ds = case[:3]
        path = Path("experiments/cases") / ds / "evaluacion" / (case + (".log" if ds == "bgl" else ".csv"))
        actual = sha(root / path)
        if (root / path).stat().st_size != size or not actual.startswith(prefix):
            raise ValueError(f"Entrada diferente de la solicitada: {case}")
        # Solo metadatos de entrada; ninguna referencia reservada.
        metadata = json.loads((root / path.with_suffix(".json")).read_text(encoding="utf-8"))
        if metadata["case_id"] != case or metadata["particion"] != "evaluacion":
            raise ValueError(f"Metadatos incompatibles: {case}")
        rows.append(dict(orden=order, case_id=case, dataset=ds, particion="evaluacion",
                         input_path=path.as_posix(), size_bytes=size, sha256=actual,
                         expected_sha256_prefix=prefix, arquitectura="nodex_multiagente", repeticion=1))
    return rows


def prepare(version):
    from dotenv import dotenv_values
    from src.experimentation import campana
    from src.experimentation.runtime import configuracion
    from src.experimentation.runtime.identidad import IdentidadCorrida

    rows = validate_inputs()
    folder = ROOT / "experiments/ejecucion" / version
    selection_path = folder / "selection.json"
    for row in rows:
        row.update(IdentidadCorrida(row["case_id"], row["dataset"], "nodex_multiagente", 1, version).to_dict())
    selection = dict(config_version=version, particion="evaluacion", repeticiones=1,
                     escenarios=["deteccion", "reconstruccion", "tecnicas", "reporte", "rendimiento"],
                     casos=rows, nota_sha_caso_3="Se eliminó el espacio tipográfico del prefijo proporcionado.")
    if selection_path.exists():
        if json.loads(selection_path.read_text(encoding="utf-8")) != selection:
            raise ValueError("La selección congelada no coincide")
    else:
        write_new(selection_path, selection)
    base = {**os.environ, **{k: v for k, v in dotenv_values(ROOT / '.env').items() if v is not None}}
    config_path = campana.ruta_configuracion(ROOT, version)
    if not config_path.exists():
        campana.congelar_piloto(ROOT, ROOT / '.env', version)
    frozen = campana.leer_configuracion(ROOT, version)
    problems = campana.comprobar_codigo(ROOT, frozen)
    if problems:
        raise ValueError("; ".join(problems))
    effective = campana.verificar_configuracion(ROOT, ROOT / '.env', frozen)
    if not effective["coincide"]:
        raise ValueError(f"La configuración efectiva difiere: {effective['distintos']}")
    if not base.get("GEMINI_API_KEY", base.get("GOOGLE_API_KEY")):
        raise ValueError("Falta credencial Gemini")
    if not (ROOT / 'experiments/knowledge/chroma_v2/chroma.sqlite3').is_file():
        raise FileNotFoundError("Falta base MITRE experimental")
    # Se comprueban los hashes del sistema evaluado incluso al reanudar.
    if configuracion.hashes_de_prompts(ROOT) != frozen["prompts_sha256"]:
        raise ValueError("Los agentes cambiaron después del congelado")
    snapshot = folder / "environment.json"
    if not snapshot.exists():
        files = sorted(p for directory in ("src", "tools") for p in (ROOT / directory).rglob('*.py'))
        files += [ROOT / "requirements.txt", ROOT / "constraints.txt"]
        versions = sorted((d.metadata['Name'], d.version) for d in importlib.metadata.distributions() if d.metadata['Name'])
        write_new(snapshot, dict(created_utc=utc(), python=sys.version, executable=sys.executable,
            platform=platform.platform(), packages=versions,
            source_sha256={p.relative_to(ROOT).as_posix(): sha(p) for p in files},
            effective_configuration=effective,
            nota="Se usa Python 3.12 disponible y las dependencias de .venv por PYTHONPATH; su Python original falta.",
            policy=dict(attempts_per_case=1, repeated_failed_runs=False, external=campana.RECURSOS_EXTERNOS,
                timeout_seconds=campana.TOPE_CORRIDA_S, internal_llm_retries="Sin cambios; pueden existir varias solicitudes por corrida")))
    else:
        recorded = json.loads(snapshot.read_text(encoding="utf-8"))
        for name, expected in recorded['source_sha256'].items():
            if sha(ROOT / name) != expected:
                raise ValueError(f"Código cambió desde la preparación: {name}")
    return rows, folder, base, frozen


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-version', default=VERSION)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    if not args.config_version or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in args.config_version):
        parser.error('config-version no válida')
    rows, folder, base, frozen = prepare(args.config_version)
    print(f"Preparados {len(rows)} casos, NODEX, repetición 1. Configuración: {args.config_version}", flush=True)
    if not args.execute:
        print('Sin inferencia. Use --execute para la corrida autorizada.', flush=True)
        return 0
    from src.experimentation import campana
    infra = 0
    for row in rows:
        started = folder / (row['run_id'] + '.started.json')
        result = folder / (row['run_id'] + '.result.json')
        if started.exists():
            print(f"Omitido: ya se inició {row['case_id']} (no se repite).", flush=True)
            continue
        if result.exists():
            raise FileExistsError(result)
        begin, clock = utc(), time.perf_counter()
        write_new(started, dict(**row, process_started_utc=begin))
        print(f"[{row['orden']}/12] Iniciando {row['case_id']}", flush=True)
        try:
            outcome = campana.correr_una(ROOT, base, frozen, row, 'evaluacion', args.config_version, folder)
        except Exception as error:
            outcome = dict(run_id=row['run_id'], case_id=row['case_id'], dataset=row['dataset'],
                           estado='error_lanzador', error=f'{type(error).__name__}: {error}', infraestructura=True)
        outcome.update(process_started_utc=begin, process_finished_utc=utc(), wall_seconds=time.perf_counter()-clock)
        write_new(result, outcome)
        print(f"Finalizó {row['case_id']}: {outcome['estado']}, {outcome['wall_seconds']:.1f} s", flush=True)
        infra = infra + 1 if outcome.get('infraestructura') else 0
        if infra >= 3:
            print('Detenido: tres fallas consecutivas de infraestructura. No se repite ningún intento.', flush=True)
            return 4
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
