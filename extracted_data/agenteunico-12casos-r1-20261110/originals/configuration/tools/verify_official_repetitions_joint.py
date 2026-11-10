"""Verificación conjunta R1/R2/R3 y notebook de carga para Colab, sin métricas."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.export_experimental_data import read, sha, write_json
from tools.run_official_repetitions import R1, protect_r1, r1_configuration, r1_selection, r1_environment


def jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def notebook(versions, target):
    cells = []
    def cell(kind, source):
        item = dict(cell_type=kind, id=f'joint-{len(cells):03d}', metadata={}, source=source.splitlines(keepends=True))
        if kind == 'code':
            item.update(execution_count=None, outputs=[])
        cells.append(item)
    cell('markdown', '# NODEX · Revisión conjunta R1, R2 y R3\n\n'
         'Carga de datos originales para análisis posterior, sin inferencia ni cálculo de métricas. '
         'En Colab, suba los tres ZIP al panel Archivos. Este notebook puede descomprimir cada uno en una carpeta '
         'con su identificador si la carpeta aún no existe. También funciona con las carpetas ya extraídas. '
         'Las claves son case_id, repeticion y run_id.\n')
    cell('code', "from pathlib import Path\nimport json, hashlib, zipfile\n"
         "try:\n    from IPython.display import display\nexcept ImportError:\n    display = print\n"
         f"VERSIONS = {versions!r}\nBASE = Path.cwd()\n"
         "def locate(version):\n"
         "    for directory in [BASE / version, BASE / 'extracted_data' / version]:\n"
         "        if (directory / 'extraction.json').is_file():\n            return directory\n"
         "    for archive in [BASE / (version + '.zip'), BASE / 'extracted_data' / (version + '.zip')]:\n"
         "        if archive.is_file():\n"
         "            directory = archive.parent / version\n"
         "            if directory.exists():\n                raise ValueError('Carpeta existente incompleta: ' + str(directory))\n"
         "            with zipfile.ZipFile(archive) as z:\n"
         "                for item in z.infolist():\n"
         "                    if not (directory / item.filename).resolve().is_relative_to(directory.resolve()):\n                        raise ValueError('Ruta ZIP inválida')\n"
         "                z.extractall(directory)\n            return directory\n"
         "    raise FileNotFoundError('Suba el ZIP o ajuste BASE para ' + version)\n"
         "FOLDERS = {rep: locate(version) for rep, version in VERSIONS.items()}\n"
         "def load(folder, name):\n    path = folder / name\n    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []\n"
         "def table(rows):\n"
         "    try:\n        import pandas as pd\n    except ImportError:\n        display(rows)\n    else:\n        display(pd.DataFrame(rows))\n")
    cell('markdown', '## Identidades e integridad\nEstos controles comprueban archivos e identidades; no califican predicciones.\n')
    cell('code', "run_index = [row for rep, folder in FOLDERS.items() for row in load(folder, 'run_status.jsonl')]\n"
         "assert len(run_index) == 36\nassert len({row['run_id'] for row in run_index}) == 36\n"
         "assert len({(row['case_id'], row['repeticion']) for row in run_index}) == 36\n"
         "for rep, folder in FOLDERS.items():\n"
         "    for item in json.loads((folder / 'manifest.json').read_text(encoding='utf-8')):\n"
         "        if item['available']:\n"
         "            assert hashlib.sha256((folder / item['export_path']).read_bytes()).hexdigest() == item['sha256_copy'] == item['sha256_source']\n"
         "table(run_index)\n")
    names = ['detection/predictions.jsonl', 'detection/verdicts.jsonl', 'detection/ground_truth.jsonl',
             'reconstruction/predictions.jsonl', 'reconstruction/predictions_items.jsonl', 'reconstruction/reference.jsonl',
             'mitre/attributions.jsonl', 'mitre/attributions_items.jsonl', 'mitre/ground_truth.jsonl',
             'mitre/retrieved_candidates.jsonl', 'reports/text.jsonl', 'reports/sections.jsonl',
             'performance/runs.jsonl', 'performance/llm_calls_items.jsonl', 'performance/processes.jsonl']
    cell('markdown', '## Carga de los cinco escenarios\nLos registros permanecen sin transformar. Referencias, predicciones y candidatos RAG se mantienen en tablas separadas.\n')
    cell('code', f"FILES = {names!r}\n"
         "tables = {name: [row for rep, folder in FOLDERS.items() for row in load(folder, name)] for name in FILES}\n"
         "for name in FILES:\n    print(name, '· registros cargados:', len(tables[name]))\n")
    cell('markdown', '## Inspección del mismo caso en las tres repeticiones\nCambie case_id. event_id y evidence_uids conservan sus significados originales.\n')
    cell('code', "case_id = 'uwf_eva_visible_0004'\n"
         "for name in ['detection/predictions.jsonl', 'reconstruction/predictions_items.jsonl', 'mitre/attributions_items.jsonl', 'reports/text.jsonl']:\n"
         "    print(name)\n    table([row for row in tables[name] if row['case_id'] == case_id])\n")
    cell('markdown', '## Medidas de rendimiento registradas\nUna fila por corrida; no se calculan promedios, métricas ni diferencias.\n')
    cell('code', "performance_records = [dict(case_id=row['case_id'], repeticion=row['repeticion'], run_id=row['run_id'], **row['value']) for row in tables['performance/runs.jsonl'] if row['present'] and isinstance(row['value'], dict)]\n"
         "table(performance_records)\n")
    write_json(target, dict(cells=cells, metadata=dict(kernelspec=dict(display_name='Python 3', language='python', name='python3'),
        language_info=dict(name='python', version='3.12')), nbformat=4, nbformat_minor=5))
    namespace = {'__name__': '__main__'}
    previous = Path.cwd()
    executed = 0
    try:
        os.chdir(ROOT)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            for item in cells:
                if item['cell_type'] == 'code':
                    exec(compile(''.join(item['source']), item['id'], 'exec'), namespace)
                    executed += 1
    finally:
        os.chdir(previous)
    return executed


def verify(r2, r3):
    versions = {1: R1, 2: r2, 3: r3}
    original = r1_configuration()
    original_environment = r1_environment()
    baseline = r1_selection()['casos']
    summary, known_runs, known_keys = {}, set(), set()
    initial = None
    reference_model_versions = None
    for rep, version in versions.items():
        folder = ROOT / 'extracted_data' / version
        rows = jsonl(folder / 'run_status.jsonl')
        if len(rows) != 12:
            raise ValueError(f'{version}: no conserva doce casos')
        configuration = read(folder / 'originals/configuration/experiments/config' / f'config_{version}.json')
        environment = read(folder / 'originals/configuration/experiments/ejecucion' / version / 'environment.json')
        for key in ('python', 'platform', 'packages'):
            if environment[key] != original_environment[key]:
                raise ValueError(f'Entorno diferente de R1: {version}, {key}')
        for key in ('parametros', 'prompts_sha256', 'capa_experimental_sha256', 'conocimiento', 'generacion', 'recursos_externos'):
            if configuration[key] != original[key]:
                raise ValueError(f'Diferencia experimental {version}: {key}')
        manifests = read(folder / 'manifest.json')
        for row, reference in zip(rows, baseline):
            if row['case_id'] != reference['case_id'] or row['repeticion'] != rep or row['config_version'] != version:
                raise ValueError(f'Identidad mezclada en {version}')
            if row['run_id'] in known_runs or (row['case_id'], rep) in known_keys:
                raise ValueError('Identificador duplicado')
            known_runs.add(row['run_id'])
            known_keys.add((row['case_id'], rep))
        if rep > 1:
            evidence = read(folder / 'repetition_integrity.json')
            if not evidence['ground_truth_copies_equal_r1'] or not evidence['input_copies_equal_r1']:
                raise ValueError('Entradas o referencias diferentes')
            startup = read(folder / 'originals/configuration/experiments/ejecucion' / version / 'rag_initial.json')
            if not startup['dynamic_empty'] or not startup['seed_matches_r1_record']:
                raise ValueError('RAG inicial incompatible')
            if initial is not None and startup['files'] != initial:
                raise ValueError('Semillas diferentes entre R2 y R3')
            initial = startup['files']
            for case in baseline:
                entry = next(r for r in manifests if r.get('case_id') == case['case_id'] and r['source_filename'].endswith('.isolation.json'))
                isolation = read(folder / entry['export_path'])
                for key in ('independent_working_copy', 'cache_absent_before_inference', 'seed_unchanged_after_case', 'working_copy_discarded'):
                    if isolation.get(key) is not True:
                        raise ValueError(f'Aislamiento no confirmado: {key}')
        verification = read(folder / 'verification.json')
        effective_versions = set()
        for entry in manifests:
            if entry['available'] and entry['source_path'].startswith('experiments/telemetry/') and 'telemetria' in read(folder / entry['export_path']):
                telemetry = read(folder / entry['export_path'])['telemetria']
                effective_versions.update(call['model_version'] for call in telemetry.get('llm_calls', []) if call.get('model_version'))
        if rep == 1:
            reference_model_versions = effective_versions
        elif not effective_versions.issubset(reference_model_versions):
            raise ValueError(f'Versión efectiva del modelo distinta de R1: {effective_versions}')
        summary[f'R{rep}'] = dict(config_version=version, cases_processed=sum(row['result_available'] for row in rows),
            cases_completed=sum(row['estado'] == 'completa' for row in rows),
            cases_failed=sum(row['result_available'] and row['estado'] != 'completa' for row in rows),
            files_exported=sum(p.is_file() for p in folder.rglob('*')),
            original_files_exported=sum(row['available'] for row in manifests),
            verified_projections=verification['verified_projections'],
            effective_model_versions=sorted(effective_versions),
            validation_passed=True, rag_reset_verified=True if rep > 1 else 'Semilla registrada R1',
            extraction_path=str(folder), zip_path=str(folder.with_suffix('.zip')),
            zip_sha256=sha(folder.with_suffix('.zip')))
    preservation = protect_r1()
    target = ROOT / 'extracted_data/revision_conjunta_r1_r2_r3_20261103.ipynb'
    if target.exists():
        raise FileExistsError(target)
    executed = notebook(versions, target)
    result = dict(repetitions=summary, r1_unchanged=preservation, unique_run_ids=len(known_runs),
        unique_case_repetition_pairs=len(known_keys), joint_loading_verified=True,
        joint_notebook=str(target), joint_notebook_code_cells_executed=executed, joint_notebook_sha256=sha(target),
        experimental_configuration_equivalent=True, initial_static_knowledge_equivalent=True,
        note='Equivalencia de configuración, código, entorno y conocimiento verificados; no se evalúa calidad ni estabilidad de resultados.')
    write_json(ROOT / 'extracted_data/validacion_conjunta_r1_r2_r3_20261103.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--r2', required=True)
    parser.add_argument('--r3', required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.r2, args.r3), ensure_ascii=False, indent=2))
