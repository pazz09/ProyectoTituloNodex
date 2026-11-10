"""R2/R3: reutiliza el lanzador R1 sin modificar NODEX ni los archivos de R1."""
from __future__ import annotations

import argparse
import copy
import importlib.metadata
import json
import os
import platform
import sqlite3
import sys
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.run_official_experiment import sha, utc, write_new

R1 = 'oficial-12casos-r1-20261028'
R1_EXPORT = ROOT / 'extracted_data' / R1
COORDINATION = ROOT / 'experiments/ejecucion/repeticiones-oficiales-20261103'
SEED = ROOT / 'experiments/knowledge/chroma_v2'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def r1_configuration():
    return read(R1_EXPORT / 'originals/configuration/experiments/config' / f'config_{R1}.json')


def r1_environment():
    return read(R1_EXPORT / 'originals/configuration/experiments/ejecucion' / R1 / 'environment.json')


def r1_selection():
    return read(R1_EXPORT / 'originals/configuration/experiments/ejecucion' / R1 / 'selection.json')


def tree_hashes(folder):
    return {p.relative_to(folder).as_posix(): dict(size_bytes=p.stat().st_size, sha256=sha(p))
            for p in sorted(folder.rglob('*')) if p.is_file()}


def protect_r1():
    """Solo lee R1; el registro de preservación se escribe en otra carpeta."""
    path = COORDINATION / 'r1_preservation_before.json'
    files = set(p for p in R1_EXPORT.rglob('*') if p.is_file())
    files.update(p for p in (R1_EXPORT.with_suffix('.zip'), R1_EXPORT.with_suffix('.zip.sha256')) if p.exists())
    for row in read(R1_EXPORT / 'manifest.json'):
        source = ROOT / row['source_path']
        if row['available']:
            files.add(source)
    for extra in ('tools/verify_experimental_export.py', 'tests/experimentation/test_official_extraction.py',
                  'docs/experimentacion/prueba_oficial_12casos_20261028.md'):
        if (ROOT / extra).is_file():
            files.add(ROOT / extra)
    current = {p.relative_to(ROOT).as_posix(): dict(size_bytes=p.stat().st_size, sha256=sha(p)) for p in sorted(files)}
    if path.exists():
        if read(path)['files'] != current:
            raise ValueError('R1 o sus fuentes cambiaron desde el registro de preservación')
    else:
        write_new(path, dict(created_utc=utc(), files=current, extraction_tree=tree_hashes(R1_EXPORT)))
    if tree_hashes(R1_EXPORT) != read(path)['extraction_tree']:
        raise ValueError('La carpeta R1 cambió')
    return dict(unchanged=True, checked_files=len(current), snapshot_sha256=sha(path))


def inspect_chroma(folder):
    folder = Path(folder)
    with closing(sqlite3.connect((folder / 'chroma.sqlite3').resolve().as_uri() + '?mode=ro', uri=True)) as db:
        collections = []
        for cid, name, dimension, config, schema in db.execute(
                'SELECT id,name,dimension,config_json_str,schema_str FROM collections ORDER BY name'):
            count = db.execute('SELECT COUNT(*) FROM embeddings WHERE segment_id IN '
                               '(SELECT id FROM segments WHERE collection=?)', (cid,)).fetchone()[0]
            collections.append(dict(name=name, dimension=dimension, document_count=count,
                                    config_json=config, schema_json=schema))
    counts = {c['name']: c['document_count'] for c in collections}
    dynamic = {name: counts.get(name, 0) for name in ('attack_patterns', 'error_memory', 'host_history')}
    return dict(collections=collections, dynamic_counts=dynamic,
                dynamic_empty=all(count == 0 for count in dynamic.values()),
                files=tree_hashes(folder))


def clean_rag():
    """La semilla de R1 ya está intacta. Cada caso usa una copia temporal nueva."""
    frozen = r1_configuration()
    for name, key in [('inventario_conocimiento_v2.json', 'inventario_v2_sha256'),
                      ('poblado_chroma_v2.json', 'poblado_v2_sha256'),
                      ('verificacion_chroma_v2.json', 'verificacion_v2_sha256')]:
        if sha(ROOT / 'experiments/knowledge' / name) != frozen['conocimiento'][key]:
            raise ValueError(f'Registro de conocimiento distinto de R1: {name}')
    expected = read(ROOT / 'experiments/knowledge/poblado_chroma_v2.json')['snapshot']['archivos']
    actual = inspect_chroma(SEED)
    expected = {name: dict(size_bytes=row['bytes'], sha256=row['sha256']) for name, row in expected.items()}
    if actual['files'] != expected:
        raise ValueError('La base inicial no es idéntica byte a byte a la semilla registrada para R1')
    if [c['name'] for c in actual['collections']] != ['attack_techniques'] or not actual['dynamic_empty']:
        raise ValueError('La base experimental contiene memoria dinámica o colecciones no previstas')
    if actual['collections'][0]['document_count'] != 697:
        raise ValueError('El catálogo MITRE no contiene las 697 técnicas de R1')
    actual.update(verified_utc=utc(), source_path=SEED.relative_to(ROOT).as_posix(),
        reset_method='Semilla R1 intacta verificada; copia temporal nueva y caché inexistente por caso con campana.correr_una().',
        redundant_repopulation=False, embeddings_recalculated=False, seed_matches_r1_record=True)
    return actual


def compatibility():
    from tools.run_official_experiment import validate_inputs
    source = r1_environment()
    for name, expected in source['source_sha256'].items():
        if sha(ROOT / name) != expected:
            raise ValueError(f'Código o archivo de dependencia distinto de R1: {name}')
    packages = sorted((d.metadata['Name'], d.version) for d in importlib.metadata.distributions() if d.metadata['Name'])
    if packages != sorted(tuple(item) for item in source['packages']) or sys.version != source['python']:
        raise ValueError('Python o dependencias distintos de R1')
    rows = validate_inputs()
    reference = r1_selection()['casos']
    if len(reference) != 12 or len(rows) != 12:
        raise ValueError('El corpus debe contener doce casos')
    for row, original in zip(rows, reference):
        for key in ('orden', 'case_id', 'dataset', 'particion', 'input_path', 'size_bytes', 'sha256'):
            if row[key] != original[key]:
                raise ValueError(f'Entrada u orden distintos de R1: {key}')
    inventory = read(ROOT / 'experiments/knowledge/inventario_conocimiento_v2.json')
    model = inventory['conocimiento']['modelo_embeddings']
    cache = Path(os.environ.get('HF_HOME', Path.home() / '.cache/huggingface'))
    if cache.name != 'hub':
        cache = cache / 'hub'
    revision = cache / ('models--sentence-transformers--' + model['modelo']) / 'snapshots' / model['revision']
    for item in model['archivos']:
        file = revision / item['nombre']
        if file.stat().st_size != item['bytes'] or sha(file) != item['sha256']:
            raise ValueError(f'Archivo del modelo de embeddings distinto de R1: {file.name}')
    return dict(checked_utc=utc(), source_hashes_match_r1=True, dependency_versions_match_r1=True,
                python_matches_r1=True, inputs_and_order_match_r1=True,
                embedding_revision=model['revision'], embedding_files_match_r1_inventory=True)


def prepare(repetition):
    from dotenv import dotenv_values
    from src.experimentation import campana
    from src.experimentation.runtime.identidad import IdentidadCorrida
    preservation = protect_r1()
    compatible = compatibility()
    # La fecha se obtiene en la zona horaria del usuario, no en UTC.
    day = datetime.now(ZoneInfo('America/Santiago')).strftime('%Y%m%d')
    version = f'oficial-12casos-r{repetition}-{day}'
    folder = ROOT / 'experiments/ejecucion' / version
    rows = copy.deepcopy(r1_selection()['casos'])
    for row in rows:
        row.update(IdentidadCorrida(row['case_id'], row['dataset'], 'nodex_multiagente', repetition, version).to_dict())
    selection = copy.deepcopy(r1_selection())
    selection.update(config_version=version, repeticiones=1, repeticion=repetition, casos=rows,
                     referencia_r1=R1)
    for name, value in [('selection.json', selection), ('compatibility.json', compatible)]:
        target = folder / name
        if target.exists():
            if name == 'selection.json' and read(target) != value:
                raise ValueError('Selección congelada diferente')
        else:
            write_new(target, value)
    frozen_path = campana.ruta_configuracion(ROOT, version)
    if not frozen_path.exists():
        campana.congelar_piloto(ROOT, ROOT / '.env', version)
    frozen = campana.leer_configuracion(ROOT, version)
    original = r1_configuration()
    for key in ('parametros', 'parametros_ausentes', 'prompts_sha256', 'capa_experimental_sha256',
                'datasets', 'conocimiento', 'semillas', 'd11_integrado', 'generacion', 'recursos_externos'):
        if frozen[key] != original[key]:
            raise ValueError(f'Configuración experimental incompatible con R1: {key}')
    problems = campana.comprobar_codigo(ROOT, frozen)
    if problems:
        raise ValueError('; '.join(problems))
    effective = campana.verificar_configuracion(ROOT, ROOT / '.env', frozen)
    if not effective['coincide']:
        raise ValueError('La configuración efectiva no coincide con la congelada')
    base = {**os.environ, **{k: v for k, v in dotenv_values(ROOT / '.env').items() if v is not None}}
    if not (base.get('GEMINI_API_KEY') or base.get('GOOGLE_API_KEY')):
        raise ValueError('Falta credencial Gemini')
    environment = folder / 'environment.json'
    if not environment.exists():
        files = sorted(p for directory in ('src', 'tools') for p in (ROOT / directory).rglob('*.py'))
        files += [ROOT / 'requirements.txt', ROOT / 'constraints.txt']
        write_new(environment, dict(created_utc=utc(), python=sys.version, executable=sys.executable,
            platform=platform.platform(), packages=sorted((d.metadata['Name'], d.version) for d in importlib.metadata.distributions() if d.metadata['Name']),
            source_sha256={p.relative_to(ROOT).as_posix(): sha(p) for p in files},
            effective_configuration=effective, referencia_r1=R1,
            policy=dict(attempts_per_case=1, repeated_failed_runs=False, external=campana.RECURSOS_EXTERNOS,
                        timeout_seconds=campana.TOPE_CORRIDA_S, isolation='campana.correr_una sin modificación'),
            nota='Mismo Python y versiones instaladas que R1; los scripts nuevos solo gestionan repeticiones y verificaciones.'))
    else:
        for name, expected in read(environment)['source_sha256'].items():
            if sha(ROOT / name) != expected:
                raise ValueError(f'El código cambió desde la preparación: {name}')
    return version, folder, rows, base, frozen, preservation


def isolated_case(campana, row, folder, base, frozen, seed_state):
    """Observa el entorno creado por R1 inmediatamente antes de lanzar el hijo."""
    original_launch = campana.ejecutar_hijo
    record = dict(run_id=row['run_id'], case_id=row['case_id'], repeticion=row['repeticion'],
                  config_version=row['config_version'])
    def observe(command, cwd, environment, timeout):
        copy_path = Path(environment['CHROMA_PATH'])
        cache = Path(environment['IP_CACHE_PATH'])
        before = inspect_chroma(copy_path)
        if before['files'] != seed_state['files'] or not before['dynamic_empty']:
            raise ValueError('La copia de trabajo no coincide con la semilla limpia')
        if copy_path.resolve() == SEED.resolve() or cache.exists():
            raise ValueError('El caso no está aislado o la caché ya contiene datos')
        record.update(checked_utc=utc(), chroma_path=str(copy_path), cache_path=str(cache),
            cache_absent_before_inference=True, initial_chroma=before,
            independent_working_copy=True, subprocess_command=command,
            expected_model=frozen['parametros']['LLM_MODEL_PRIMARY'])
        outcome = original_launch(command, cwd, environment, timeout)
        record['final_chroma'] = inspect_chroma(copy_path)
        return outcome
    try:
        with patch.object(campana, 'ejecutar_hijo', observe):
            outcome = campana.correr_una(ROOT, base, frozen, row, 'evaluacion', row['config_version'], folder)
    finally:
        record['seed_unchanged_after_case'] = tree_hashes(SEED) == seed_state['files']
        if record.get('chroma_path'):
            record['working_copy_discarded'] = not Path(record['chroma_path']).exists()
        write_new(folder / f"{row['run_id']}.isolation.json", record)
    if not record['seed_unchanged_after_case']:
        raise ValueError('La semilla se modificó durante el caso')
    return outcome


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repetition', type=int, choices=(2, 3), required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    version, folder, rows, base, frozen, preservation = prepare(args.repetition)
    print(f'R{args.repetition}: {version}; 12 casos verificados contra R1.', flush=True)
    if not args.execute:
        print('Preparación sin inferencia.', flush=True)
        return 0
    if args.repetition == 3:
        completed_r2 = list((ROOT / 'extracted_data').glob('oficial-12casos-r2-*/verification.json'))
        if len(completed_r2) != 1 or read(completed_r2[0])['cases'] != 12:
            raise ValueError('R2 debe estar extraída y validada antes de iniciar R3')
    clean = clean_rag()
    startup = folder / 'rag_initial.json'
    if not startup.exists():
        write_new(startup, clean)
    elif read(startup)['files'] != clean['files']:
        raise ValueError('La semilla cambió respecto al inicio de la repetición')
    from src.experimentation import campana
    infrastructure = 0
    for row in rows:
        started = folder / f"{row['run_id']}.started.json"
        result = folder / f"{row['run_id']}.result.json"
        if started.exists():
            print(f"Omitido sin repetir: {row['case_id']}", flush=True)
            continue
        if result.exists():
            raise FileExistsError(result)
        compatibility()
        started_utc, clock = utc(), time.perf_counter()
        write_new(started, dict(**row, process_started_utc=started_utc))
        print(f"[R{args.repetition} {row['orden']}/12] Iniciando {row['case_id']}", flush=True)
        try:
            outcome = isolated_case(campana, row, folder, base, frozen, clean)
        except Exception as error:
            outcome = dict(run_id=row['run_id'], case_id=row['case_id'], dataset=row['dataset'],
                repeticion=args.repetition, estado='error_lanzador', error=f'{type(error).__name__}: {error}', infraestructura=True)
        outcome.update(config_version=version, process_started_utc=started_utc, process_finished_utc=utc(),
                       wall_seconds=time.perf_counter()-clock)
        write_new(result, outcome)
        print(f"[R{args.repetition} {row['orden']}/12] {outcome['estado']}: {outcome['wall_seconds']:.1f} s", flush=True)
        infrastructure = infrastructure + 1 if outcome.get('infraestructura') else 0
        if infrastructure >= 3 or outcome['estado'] == 'error_lanzador':
            print('Detenido; se conservan los intentos. No se reintentan casos.', flush=True)
            return 4
    write_new(folder / 'r1_preservation_after.json', dict(checked_utc=utc(), **protect_r1()))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
