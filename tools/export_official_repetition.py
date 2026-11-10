"""Extrae y verifica R2/R3 con el esquema R1; nunca escribe en R1."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import export_experimental_data as extractor
from tools import run_official_repetitions as repetition_runner
from tools.verify_official_repetition import verify


def identity_check(folder, repetition):
    rows = [json.loads(line) for line in (folder / 'run_status.jsonl').read_text(encoding='utf-8').splitlines()]
    selection = repetition_runner.r1_selection()['casos']
    if len(rows) != 12:
        raise ValueError('La extracción debe conservar los doce casos, incluso los fallidos')
    for row, original in zip(rows, selection):
        if row['case_id'] != original['case_id'] or row['orden'] != original['orden'] or row['repeticion'] != repetition:
            raise ValueError('Identidad, orden o repetición incorrectos')
    # Referencias idénticas a la copia reservada de R1. Solo se abren al extraer.
    previous = extractor.read(repetition_runner.R1_EXPORT / 'manifest.json')
    current = extractor.read(folder / 'manifest.json')
    for category in ('inputs', 'ground_truth'):
        before = {r['source_path']: r['sha256_copy'] for r in previous if r['available'] and r['export_path'].startswith('originals/' + category + '/')}
        after = {r['source_path']: r['sha256_copy'] for r in current if r['available'] and r['export_path'].startswith('originals/' + category + '/')}
        if before != after:
            raise ValueError(f'Las entradas o referencias difieren de R1: {category}')
    return dict(cases=12, repetition=repetition, identities_separate=True,
                input_copies_equal_r1=True, ground_truth_copies_equal_r1=True,
                schema='Mismas proyecciones R1 y sufijos _items; sin transformación de valores')


def export(version):
    match = re.fullmatch(r'oficial-12casos-r([23])-\d{8}', version)
    if not match:
        raise ValueError('Solo se admiten identificadores R2/R3; R1 es de solo lectura')
    repetition = int(match.group(1))
    folder = ROOT / 'extracted_data' / version
    logs = ROOT / 'experiments/ejecucion' / version
    preservation = repetition_runner.protect_r1()
    extractor.export(ROOT, version, folder)
    # Adjunta la evidencia adicional de aislamiento sin modificar las proyecciones R1.
    ex = extractor.Export(ROOT, folder)
    ex.manifest = extractor.read(folder / 'manifest.json')
    identity = dict(config_version=version, repeticion=repetition)
    for name in ('rag_initial.json', 'compatibility.json', 'r1_preservation_after.json'):
        ex.copy(logs / name, identity, 'configuration')
    ex.copy(repetition_runner.COORDINATION / 'r1_preservation_before.json', identity, 'configuration')
    for path in sorted(repetition_runner.SEED.rglob('*')):
        if path.is_file():
            ex.copy(path, identity, 'knowledge')
    for name in ('poblado_chroma_v2.json', 'inventario_conocimiento_v2.json', 'verificacion_chroma_v2.json'):
        ex.copy(ROOT / 'experiments/knowledge' / name, identity, 'knowledge')
    for row in extractor.read(logs / 'selection.json')['casos']:
        ex.copy(logs / f"{row['run_id']}.isolation.json", dict(identity, case_id=row['case_id'], run_id=row['run_id']), 'execution')
    ex.finish()
    extraction = extractor.read(folder / 'extraction.json')
    extraction.update(repeticion=repetition, referencia_r1=repetition_runner.R1,
        required_missing=[row['source_path'] for row in ex.manifest if row['required'] and not row['available']],
        repetition_wrapper_sha256=extractor.sha(Path(__file__)))
    extractor.write_json(folder / 'extraction.json', extraction)
    notebook_path = folder / 'revision_datos_crudos.ipynb'
    notebook = extractor.read(notebook_path)
    for cell in notebook['cells']:
        code = ''.join(cell['source'])
        code = code.replace(repetition_runner.R1, version)
        code = code.replace('una corrida por caso', f'R{repetition}: una corrida por caso')
        cell['source'] = code.splitlines(keepends=True)
    extractor.write_json(notebook_path, notebook)
    agreement = identity_check(folder, repetition)
    agreement.update(r1_preservation=preservation, seed_unchanged_after_repetition=repetition_runner.clean_rag())
    extractor.write_json(folder / 'repetition_integrity.json', agreement)
    procedure = folder / 'procedure'
    procedure.mkdir()
    for name in ('export_experimental_data.py', 'export_official_repetition.py',
                 'verify_official_repetition.py', 'run_official_repetitions.py', 'run_official_experiment.py'):
        shutil.copyfile(ROOT / 'tools' / name, procedure / name)
    document = ROOT / 'docs/experimentacion/repeticiones_oficiales_r2_r3_20261103.md'
    shutil.copyfile(document, procedure / document.name)
    (folder / 'README.md').write_text(
        f'# NODEX — R{repetition}: {version}\n\n'
        'Doce casos en el orden de R1, una ejecución por caso. Abrir `revision_datos_crudos.ipynb`. '
        'Las proyecciones conservan el esquema R1: detección, reconstrucción, MITRE, reportes y rendimiento. '
        'Los archivos `_items` mantienen orden y duplicados; `present` distingue ausencia de null.\n\n'
        'Las entradas y referencias reservadas son idénticas a R1. Los estados de todos los casos, incluidos fallos, '
        'están en `run_status.jsonl`. Los reportes almacenados están en `reports/generated/`. '
        'El estado inicial del RAG y la comprobación de cada copia temporal se conservan en los originales. '
        'También se incluye una copia byte a byte de la semilla MITRE.\n\n'
        'Consulte `manifest.json`, `extraction.json`, `verification.json` y `repetition_integrity.json`. '
        'La carpeta `procedure/` conserva los scripts y el procedimiento. '
        'Rendimiento contiene las medidas registradas por NODEX; no se inventan CPU/RAM/GPU ni costo facturado. '
        'raw es el estado final preservado, no todas las respuestas HTTP del proveedor.\n\n'
        'Para Google Colab, descomprima el ZIP en una carpeta con su mismo nombre y abra el notebook; '
        'si hace falta, ajuste BASE a esa carpeta. La carga conjunta usa case_id, repeticion y run_id. '
        'No se ejecuta NODEX desde el notebook ni se calculan métricas.\n\n'
        f'Para verificar únicamente esta extracción: `python procedure/verify_official_repetition.py . --execute-notebook`.\n',
        encoding='utf-8')
    result = verify(folder, execute_notebook=True)
    archive = folder.with_suffix('.zip')
    if archive.exists():
        raise FileExistsError(archive)
    shutil.make_archive(str(folder), 'zip', root_dir=folder)
    with zipfile.ZipFile(archive) as compressed:
        if compressed.testzip() is not None:
            raise ValueError('ZIP inválido')
    archive.with_suffix('.zip.sha256').write_text(extractor.sha(archive) + '  ' + archive.name + '\n', encoding='ascii')
    if not repetition_runner.protect_r1()['unchanged']:
        raise ValueError('R1 cambió')
    return dict(result, config_version=version, extraction=str(folder), archive=str(archive),
                archive_sha256=extractor.sha(archive))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-version', required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.config_version), ensure_ascii=False, indent=2))
