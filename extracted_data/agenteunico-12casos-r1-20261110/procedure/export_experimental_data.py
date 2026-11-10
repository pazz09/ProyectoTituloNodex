"""Extrae archivos y proyecciones literales; solo biblioteca estándar, sin inferencia ni métricas."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'oficial-12casos-r1-20261028'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pointer(document, path):
    value = document
    for part in path.strip('/').split('/') if path else []:
        part = part.replace('~1', '/').replace('~0', '~')
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return False, None
    return True, value


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


class Export:
    def __init__(self, root, output):
        self.root, self.output = root, output
        self.manifest, self.tables = [], {}

    def copy(self, source, identity, category, required=True):
        source = Path(source)
        if not source.is_absolute():
            source = self.root / source
        relative = source.relative_to(self.root)
        target = self.output / 'originals' / category / relative
        entry = dict(identity, source_path=relative.as_posix(), source_filename=source.name,
                     export_path=target.relative_to(self.output).as_posix(), available=source.is_file(), required=required)
        self.manifest.append(entry)
        if not entry['available']:
            return None, entry
        target.parent.mkdir(parents=True, exist_ok=True)
        before = sha(source)
        shutil.copyfile(source, target)
        after = sha(source)
        copied = sha(target)
        if before != after or before != copied:
            raise ValueError(f'El original cambió o la copia difiere: {source}')
        entry.update(sha256_source=before, sha256_copy=copied, size_bytes=source.stat().st_size)
        return read(target) if source.suffix == '.json' else None, entry

    def project(self, table, document, source, identity, paths, items=False):
        for path in paths:
            present, value = pointer(document, path) if source['available'] else (False, None)
            row = dict(identity, source_path=source['source_path'], source_export_path=source['export_path'],
                       source_file_available=source['available'], source_json_pointer=path, present=present)
            if present:
                row['value'] = value
            self.tables.setdefault(table, []).append(row)
            if items and isinstance(value, list):
                for index, item in enumerate(value):
                    self.tables.setdefault(table.replace('.jsonl', '_items.jsonl'), []).append(
                        dict(row, source_json_pointer=f'{path}/{index}', array_index=index, value=item))

    def finish(self):
        for name, rows in self.tables.items():
            path = self.output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('w', encoding='utf-8', newline='\n') as stream:
                for row in rows:
                    stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        write_json(self.output / 'manifest.json', self.manifest)
        columns = list(dict.fromkeys(key for row in self.manifest for key in row))
        with (self.output / 'manifest.csv').open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(self.manifest)


def export(root, version, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError('La exportación no se sobrescribe; elija otro --output')
    folder = root / 'experiments/ejecucion' / version
    selection = read(folder / 'selection.json')
    output.mkdir(parents=True)
    ex = Export(root, output)
    config = root / 'experiments/config' / f'config_{version}.json'
    ex.copy(config, dict(config_version=version), 'configuration')
    # Congelado de código y entorno sin incluir .env ni credenciales.
    environment = read(folder / 'environment.json')
    for name, expected in environment['source_sha256'].items():
        if sha(root / name) != expected:
            raise ValueError(f'El código difiere del congelado: {name}')
        ex.copy(root / name, dict(config_version=version), 'configuration')
    for name in ('selection.json', 'environment.json'):
        ex.copy(folder / name, dict(config_version=version), 'configuration')
    statuses = []
    for case in selection['casos']:
        identity = {key: case[key] for key in ('case_id', 'dataset', 'particion', 'run_id', 'arquitectura', 'repeticion', 'config_version', 'orden')}
        case_id, ds, run = case['case_id'], case['dataset'], case['run_id']
        source_input = root / case['input_path']
        if sha(source_input) != case['sha256']:
            raise ValueError(f'La entrada cambió: {case_id}')
        ex.copy(source_input, identity, 'inputs')
        metadata, meta_source = ex.copy(source_input.with_suffix('.json'), identity, 'inputs')
        ex.project('cases.jsonl', metadata, meta_source, identity, [''])
        ex.project('provenance.jsonl', metadata, meta_source, identity, ['/procedencia'], items=True)
        # Estas referencias se abren únicamente al extraer, después de la inferencia.
        gt, gs = ex.copy(Path('experiments/ground_truth') / ds / 'evaluacion' / f'{case_id}.json', identity, 'ground_truth')
        ex.project('detection/ground_truth.jsonl', gt, gs, identity, [''])
        ex.project('reconstruction/reference.jsonl', gt, gs, identity,
                   ['/core_event_uids', '/estado_dimension', '/anotacion'])
        ex.project('mitre/ground_truth.jsonl', gt, gs, identity,
                   ['/referencias_mitre', '/estado_mitre_por_nivel', '/estado_dimension'], items=True)
        prediction, ps = ex.copy(Path('experiments/nodex') / ds / f'{run}.json', identity, 'predictions')
        raw, rs = ex.copy(Path('experiments/nodex') / ds / 'raw' / f'{run}.raw.json', identity, 'predictions')
        ex.project('detection/predictions.jsonl', prediction, ps, identity, ['/salida/classification', '/ejecucion'])
        ex.project('detection/verdicts.jsonl', raw, rs, identity,
                   ['/estado_crudo/' + key for key in ('hay_anomalia', 'hay_incidente', 'confianza')])
        ex.project('reconstruction/predictions.jsonl', raw, rs, identity,
                   ['/estado_crudo/eventos_reconstruidos', '/estado_crudo/secuencia_temporal'], items=True)
        ex.project('reconstruction/normalized.jsonl', prediction, ps, identity,
                   ['/salida/reconstructed_events', '/salida/temporal_sequence'], items=True)
        ex.project('reconstruction/evidence.jsonl', raw, rs, identity,
                   ['/estado_crudo/' + key for key in ('evidencia_logs', 'resumen_logs', 'historial_planes')], items=True)
        ex.project('mitre/attributions.jsonl', raw, rs, identity, ['/estado_crudo/tecnicas_atribuidas'], items=True)
        ex.project('mitre/normalized.jsonl', prediction, ps, identity, ['/salida/mitre'])
        ex.project('mitre/retrieved_candidates.jsonl', raw, rs, identity, ['/estado_crudo/tecnicas_mitre'], items=True)
        ex.project('mitre/retrieved_candidates.jsonl', prediction, ps, identity, ['/salida/_meta/mitre_candidates'], items=True)
        ex.project('reports/sections.jsonl', raw, rs, identity, ['/estado_crudo/' + key for key in
                   ('diagnostico', 'evaluacion_auditor', 'comandos_mitigacion', 'cves_encontrados', 'contexto_rag',
                    'tecnicas_mitre', 'tecnicas_atribuidas', 'evidencia_logs')])
        ex.project('reports/text.jsonl', prediction, ps, identity, ['/salida/report/summary'])
        present, summary = pointer(prediction, '/salida/report/summary') if prediction is not None else (False, None)
        if present and isinstance(summary, str):
            target = output / 'reports/generated' / f'{run}.md'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(summary.encode('utf-8'))
        telemetry, ts = ex.copy(Path('experiments/telemetry') / ds / f'{run}.json', identity, 'telemetry')
        ex.project('performance/runs.jsonl', telemetry, ts, identity, ['/telemetria'])
        ex.project('performance/llm_calls.jsonl', telemetry, ts, identity, ['/telemetria/llm_calls'], items=True)
        for suffix, field in (('consultas_externas', 'consultas'), ('llm_json', 'llm_json')):
            document, source = ex.copy(Path('experiments/telemetry') / ds / f'{run}.{suffix}.json', identity, 'telemetry')
            ex.project(f'performance/{suffix}.jsonl', document, source, identity, ['/' + field], items=True)
        for ending in ('stdout.txt', 'stderr.txt', 'started.json', 'result.json'):
            document, source = ex.copy(folder / f'{run}.{ending}', identity, 'execution')
            if ending == 'result.json':
                ex.project('performance/processes.jsonl', document, source, identity, [''])
                statuses.append(dict(identity, result_available=source['available'],
                                     estado=document.get('estado') if document else None))
        for failure in sorted((root / 'experiments/fallos' / ds).glob(f'{run}__f*.json')):
            ex.copy(failure, identity, 'execution')
    ex.tables['run_status.jsonl'] = statuses
    ex.finish()
    missing = [row['source_path'] for row in ex.manifest if row['required'] and not row['available']]
    write_json(output / 'extraction.json', dict(config_version=version, created_utc=datetime.now(timezone.utc).isoformat(),
        extractor_sha256=sha(Path(__file__)), arguments=sys.argv, cases=len(statuses), required_missing=missing,
        completed=sum(row['estado'] == 'completa' for row in statuses),
        rules=['Copias byte a byte verificadas con SHA-256.', 'JSONL UTF-8: present=false significa campo ausente; value=null es null original.',
               'Listas vacías, cadenas vacías, orden y duplicados se conservan.',
               'source_json_pointer y array_index vinculan las proyecciones al archivo original.',
               'Sin matching, métricas, evaluadores ni conclusiones de desempeño.'],
        limitations=['raw es el estado final preservado, no todas las respuestas HTTP del proveedor.',
                     'CPU, RAM, GPU, costo facturado y duraciones por agente no se inventan si no existen.',
                     'Referencias BGL de reconstrucción/MITRE pueden ser no_aplica; se conservan igual.',
                     'Las procedencias hacia CSV UWF intermedios ausentes se conservan literalmente.',
                     'No se copiaron los Parquet completos: alcance limitado a los 12 casos y sus referencias.']))
    (output / 'README.md').write_text(
        '# Extracción oficial NODEX — 12 casos, repetición 1\n\n'
        'Abrir `revision_datos_crudos.ipynb`. No ejecuta NODEX ni calcula métricas.\n\n'
        'Los archivos originales están en `originals/`; `manifest.json` y `manifest.csv` documentan sus hashes. '
        'Los JSONL son proyecciones literales con procedencia. Los sufijos `_items` contienen una fila por elemento, '
        'sin eliminar duplicados. La tabla padre conserva listas vacías y campos ausentes.\n\n'
        'Escenarios: `detection/`, `reconstruction/`, `mitre/`, `reports/`, `performance/`. '
        'Las referencias están separadas de las predicciones. `run_status.jsonl` conserva el estado de los 12 casos, '
        'incluidos fallos. Consulte `extraction.json` para archivos faltantes y límites.\n', encoding='utf-8')
    make_notebook(output)
    return read(output / 'extraction.json')


def make_notebook(output):
    cells = []
    def cell(kind, text):
        value = dict(cell_type=kind, metadata={}, source=text.splitlines(keepends=True))
        if kind == 'code':
            value.update(execution_count=None, outputs=[])
        cells.append(value)
    cell('markdown', '# Revisión de datos crudos de NODEX\n\n12 casos solicitados, una corrida por caso. Este notebook solo carga, verifica y muestra datos; la evaluación posterior queda a cargo del investigador. No requiere pandas.\n')
    cell('code', "from pathlib import Path\nimport json, hashlib\nfrom IPython.display import display\nBASE = Path.cwd()\nif not (BASE / 'extraction.json').exists():\n    BASE = BASE / 'extracted_data' / 'oficial-12casos-r1-20261028'\nassert (BASE / 'extraction.json').is_file(), 'Abra el notebook desde la carpeta de extracción o ajuste BASE.'\ndef load(name):\n    path = BASE / name\n    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []\ndef table(rows):\n    try:\n        import pandas as pd\n    except ImportError:\n        display(rows)\n    else:\n        display(pd.DataFrame(rows))\nextraction = json.loads((BASE / 'extraction.json').read_text(encoding='utf-8'))\ndisplay(extraction)\n")
    cell('markdown', '## Integridad y estado de la ejecución\nLos hashes verifican las copias; no califican predicciones. Ausente, null, lista vacía y cadena vacía permanecen diferenciados.\n')
    cell('code', "manifest = json.loads((BASE / 'manifest.json').read_text(encoding='utf-8'))\nfor item in manifest:\n    if item['available']:\n        assert hashlib.sha256((BASE / item['export_path']).read_bytes()).hexdigest() == item['sha256_copy'] == item['sha256_source']\ntable(load('run_status.jsonl'))\nmissing = [item for item in manifest if not item['available']]\ntable(missing)\n")
    for title, names in [
        ('E1 · Detección', ['detection/predictions.jsonl', 'detection/verdicts.jsonl', 'detection/ground_truth.jsonl']),
        ('E2 · Reconstrucción', ['reconstruction/predictions_items.jsonl', 'reconstruction/predictions.jsonl', 'reconstruction/reference.jsonl', 'reconstruction/evidence.jsonl']),
        ('E3 · Técnicas MITRE ATT&CK', ['mitre/attributions_items.jsonl', 'mitre/attributions.jsonl', 'mitre/ground_truth.jsonl', 'mitre/retrieved_candidates.jsonl']),
        ('E4 · Reportes', ['reports/text.jsonl', 'reports/sections.jsonl']),
        ('E5 · Rendimiento', ['performance/processes.jsonl', 'performance/runs.jsonl', 'performance/llm_calls_items.jsonl', 'performance/llm_json.jsonl', 'performance/consultas_externas_items.jsonl']),
    ]:
        cell('markdown', f'## {title}\nCada registro incluye identidad y puntero al original. Referencias y predicciones se muestran por separado.\n')
        cell('code', 'for name in ' + repr(names) + ':\n    print(name)\n    table(load(name))\n')
    cell('markdown', '## Inspección de una ejecución\nCambie `case_id` para consultar otro caso. event_id identifica eventos reconstruidos; evidence_uids identifica evidencia citada. Los candidatos RAG no son atribuciones.\n')
    cell('code', "case_id = 'uwf_eva_visible_0004'\nfor name in ['reconstruction/predictions.jsonl', 'mitre/attributions.jsonl', 'reports/text.jsonl', 'performance/runs.jsonl']:\n    print(name)\n    display([row for row in load(name) if row['case_id'] == case_id])\n")
    write_json(output / 'revision_datos_crudos.ipynb', dict(cells=cells, metadata=dict(kernelspec=dict(display_name='Python 3', language='python', name='python3'), language_info=dict(name='python', version='3.12')), nbformat=4, nbformat_minor=5))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-version', default=VERSION)
    parser.add_argument('--output', type=Path, default=ROOT / 'extracted_data' / VERSION)
    args = parser.parse_args()
    print(json.dumps(export(ROOT, args.config_version, args.output), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
