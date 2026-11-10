"""Verifica copias, punteros, reportes y celdas del notebook sin ejecutar NODEX."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path

try:
    from .export_experimental_data import pointer, read, sha, write_json
except ImportError:
    from export_experimental_data import pointer, read, sha, write_json


def verify(folder, execute_notebook=False):
    folder = Path(folder).resolve()
    manifest = read(folder / 'manifest.json')
    documents = {}
    copied = 0
    for item in manifest:
        if not item['available']:
            continue
        path = folder / item['export_path']
        assert sha(path) == item['sha256_source'] == item['sha256_copy'], path
        assert path.stat().st_size == item['size_bytes'], path
        copied += 1
        if path.suffix == '.json':
            documents[item['export_path']] = read(path)
    projected = 0
    for path in folder.rglob('*.jsonl'):
        for line in path.read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            if 'source_json_pointer' not in row:
                continue
            if not row['source_file_available']:
                assert row['present'] is False and 'value' not in row
                continue
            present, value = pointer(documents[row['source_export_path']], row['source_json_pointer'])
            assert row['present'] == present, (path, row)
            if present:
                assert json.dumps(row['value'], sort_keys=True) == json.dumps(value, sort_keys=True), (path, row)
            else:
                assert 'value' not in row
            projected += 1
    reports = 0
    for line in (folder / 'reports/text.jsonl').read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        if row['present'] and isinstance(row['value'], str):
            path = folder / 'reports/generated' / f"{row['run_id']}.md"
            assert path.read_bytes() == row['value'].encode('utf-8'), path
            reports += 1
    notebook_path = folder / 'revision_datos_crudos.ipynb'
    notebook = read(notebook_path)
    first_code = next(cell for cell in notebook['cells'] if cell['cell_type'] == 'code')
    code = ''.join(first_code['source'])
    if 'except ImportError:\n    display = print\n' not in code:
        first_code['source'] = code.replace(
            'from IPython.display import display\n',
            'try:\n    from IPython.display import display\nexcept ImportError:\n    display = print\n'
        ).splitlines(keepends=True)
    # Tabla de medidas registradas lista para exploración posterior, sin
    # agregación ni comparación con referencias.
    if not any(cell.get('id') == 'performance-records' for cell in notebook['cells']):
        notebook['cells'].append(dict(cell_type='code', id='performance-records', metadata={},
            execution_count=None, outputs=[], source=[
                "# Medidas originales por corrida; no se calculan métricas.\n",
                "performance_records = [dict(case_id=row['case_id'], run_id=row['run_id'], **row['value']) for row in load('performance/runs.jsonl') if row['present'] and isinstance(row['value'], dict)]\n",
                "table(performance_records)\n"]))
    if not any(cell.get('id') == 'raw-state-inspection' for cell in notebook['cells']):
        notebook['cells'].append(dict(cell_type='code', id='raw-state-inspection', metadata={},
            execution_count=None, outputs=[], source=[
                "# Estado original y trazas de agentes/herramientas del case_id seleccionado.\n",
                "raw_entry = next((item for item in manifest if item.get('case_id') == case_id and item['source_filename'].endswith('.raw.json') and item['available']), None)\n",
                "raw_document = json.loads((BASE / raw_entry['export_path']).read_text(encoding='utf-8')) if raw_entry else {}\n",
                "raw_state = raw_document.get('estado_crudo', {})\n",
                "for field in ['plan', 'historial_ejecucion', 'historial_planes', 'desviaciones_plan']:\n",
                "    display(dict(field=field, present=field in raw_state, **({'value': raw_state[field]} if field in raw_state else {})))\n"]))
    # nbformat 4.5 requiere id por celda. Solo se completa este metadato del
    # producto derivado; los originales y las proyecciones no se alteran.
    for index, cell in enumerate(notebook['cells']):
        cell.setdefault('id', f'cell-{index:03d}')
        if cell['cell_type'] == 'code':
            compile(''.join(cell['source']), f'notebook-cell-{index}', 'exec')
    write_json(notebook_path, notebook)
    executed = 0
    if execute_notebook:
        namespace = {'__name__': '__main__'}
        previous = Path.cwd()
        try:
            os.chdir(folder)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                for index, cell in enumerate(notebook['cells']):
                    if cell['cell_type'] == 'code':
                        exec(compile(''.join(cell['source']), f'notebook-cell-{index}', 'exec'), namespace)
                        executed += 1
        finally:
            os.chdir(previous)
    statuses = [json.loads(line) for line in (folder / 'run_status.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len({row['case_id'] for row in statuses}) == len(statuses)
    assert len({row['run_id'] for row in statuses}) == len(statuses)
    assert all(row['repeticion'] == 1 for row in statuses)
    result = dict(verified_original_files=copied, verified_projections=projected,
                  verified_reports=reports, notebook_code_cells_executed=executed,
                  notebook_cell_ids_completed=True, cases=len(statuses),
                  notebook_plain_python_display_fallback=True,
                  completed=sum(row['estado'] == 'completa' for row in statuses),
                  required_missing=read(folder / 'extraction.json')['required_missing'],
                  verifier_sha256=sha(Path(__file__)),
                  note='Comprobación de integridad; no se califican predicciones ni se calculan métricas.',
                  product_sha256={p.relative_to(folder).as_posix(): sha(p) for p in sorted(folder.rglob('*'))
                                  if p.is_file() and p.name != 'verification.json' and 'originals' not in p.relative_to(folder).parts})
    write_json(folder / 'verification.json', result)
    return {key: value for key, value in result.items() if key != 'product_sha256'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--execute-notebook', action='store_true')
    args = parser.parse_args()
    print(json.dumps(verify(args.folder, args.execute_notebook), ensure_ascii=False, indent=2))
