"""Tres campañas enriquecidas secuenciales; una inferencia experimental por caso.

Preparación: python tools/run_enriched_campaign.py
Ejecución autorizada: python tools/run_enriched_campaign.py --execute
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import shutil
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PATHS = [ROOT, ROOT/'.venv/Lib/site-packages']
bootstrap_paths=[str(p) for p in PATHS if p.exists()]
bootstrap_resolved={str(Path(p).resolve()).lower() for p in bootstrap_paths}
sys.path[:]=bootstrap_paths+[p for p in sys.path if str(Path(p or '.').resolve()).lower() not in bootstrap_resolved]
os.environ['PYTHONPATH'] = os.pathsep.join(str(p) for p in PATHS if p.exists())
os.environ['PYTHONUTF8'] = '1'
from tools.run_official_experiment import utc, sha, write_new, validate_inputs
from tools import run_official_repetitions as old
from src.experimentation.knowledge.rag_enriquecido import tree, load_corpus, model_inventory, collection_state

RAG = ROOT/'experiments/knowledge/rag_enriquecido_30_v1'
SNAPSHOT = RAG/'chroma_snapshot'
COORD = ROOT/'experiments/ejecucion/enriquecido-campanas-20261104'
ORIGINALS = ('oficial-12casos-r1-20261028','oficial-12casos-r2-20261103','oficial-12casos-r3-20261103')
EXTRA = dict(condicion_rag='enriquecido', rag_version='rag_enriquecido_30_v1', casos_historicos=30)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def require(ok, message):
    if not ok:
        raise ValueError(message)


def runtime_compatibility():
    ref = old.r1_environment()
    require(sys.version == ref['python'], 'Python distinto de R1')
    for name, value in ref['source_sha256'].items():
        require(sha(ROOT/name) == value, f'Cambio funcional o fuente original modificada: {name}')
    current = Counter((d.metadata['Name'],d.version) for d in importlib.metadata.distributions(path=list(dict.fromkeys(sys.path))) if d.metadata.get('Name'))
    original = Counter(map(tuple,ref['packages']))
    removed, added = sorted((original-current).elements()), sorted((current-original).elements())
    allowed_removed = [('artifact_tool_v2','2.8.106'),('pillow','12.3.0'),('pycparser','3.11'),
                       ('python-dateutil','2.9.0.post0'),('setuptools','84.1.0')]
    allowed_added = [('artifact_tool_v2','2.8.119'),('pillow','13.0.0'),('pycparser','3.12'),
                     ('python-dateutil','3.0.0'),('setuptools','84.2.1')]
    require((not removed and not added) or (removed==allowed_removed and added==allowed_added),
            f'Diferencias de dependencias no revisadas: {removed}; {added}')
    origins = {}
    for module in ('PIL','pycparser','dateutil','setuptools'):
        spec = importlib.util.find_spec(module)
        require(spec and Path(spec.origin).is_relative_to(ROOT/'.venv/Lib/site-packages'),
                f'Paquete auxiliar actualizado en la ruta efectiva: {module}')
        origins[module] = spec.origin
    require(not any('artifact_tool' in (ROOT/p).read_text(encoding='utf-8') for p in ref['source_sha256'] if p.startswith('src/') and p.endswith('.py')),
            'artifact_tool aparece en el código funcional')
    require('artifact_tool_v2' not in sys.modules, 'artifact_tool cargado en el proceso de inferencia')
    rows = validate_inputs()
    reference = old.r1_selection()['casos']
    for row, original_row in zip(rows, reference):
        for key in ('case_id','dataset','input_path','size_bytes','sha256','orden'):
            require(row[key] == original_row[key], f'Entrada u orden distinto: {key}')
    return dict(source_hashes_match_R1=True, python_matches_R1=True, input_hashes_and_order_match_R1=True,
        package_inventory_identical=not removed and not added, package_inventory_removed=removed,
        package_inventory_added=added, effective_original_auxiliary_paths=origins,
        dependency_difference_scope='Cuatro copias actualizadas del runtime están ocultas por las versiones originales del venv. artifact_tool no forma parte de NODEX ni se importa. Se registra la diferencia de inventario; no se afirma identidad completa del entorno.')


def preservation():
    files = set(RAG.rglob('*'))
    for version in ORIGINALS:
        folder = ROOT/'extracted_data'/version
        files.update(folder.rglob('*'))
        files.update(p for p in (folder.with_suffix('.zip'),folder.with_suffix('.zip.sha256')) if p.exists())
        files.update((ROOT/r['source_path']) for r in read(folder/'manifest.json') if r['available'])
    files.update((ROOT/'experiments/knowledge/chroma_v2').rglob('*'))
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(files) if p.is_file()}


def check_preservation():
    path = COORD/'preservation_before.json'
    now = preservation()
    if not path.exists():
        write_new(path, dict(created_utc=utc(),files=now))
    require(read(path)['files'] == now, 'Snapshot, corpus o campañas originales modificados')
    return dict(unchanged=True,files=len(now),inventory_sha256=sha(path))


def snapshot_state():
    frozen = read(RAG/'manifests/snapshot_congelado.json')
    require(tree(SNAPSHOT)==frozen['files'], 'Snapshot enriquecido modificado')
    cases = load_corpus(RAG)
    state = old.inspect_chroma(SNAPSHOT)
    counts = {c['name']:c['document_count'] for c in state['collections']}
    require(counts=={'attack_patterns':30,'attack_techniques':697,'error_memory':0,'host_history':0},'Conteos iniciales incorrectos')
    require(all(c['dimension']==384 for c in state['collections'] if c['document_count']), 'Dimensión diferente de 384')
    require(len(cases)==30 and read(RAG/'validation/validacion_poblado.json')['status']=='passed', 'Corpus/base sin validar')
    model_inventory()
    return dict(state, snapshot_tree_sha256=frozen['tree_sha256'],historical_cases=30,
                dynamic_empty=True, dynamic_definition='error_memory y host_history vacías; attack_patterns contiene solo los 30 históricos congelados')


def identity_context():
    from contextlib import contextmanager
    from src.experimentation.runtime import identidad
    original = identidad.IdentidadCorrida.to_dict
    original_suffix = identidad.IdentidadCorrida.sufijo.fget
    def suffix(self):
        return hashlib.sha256((original_suffix(self)+'|rag30-validated-launch-v1').encode()).hexdigest()[:8]
    def as_dict(self):
        return dict(original(self),**EXTRA)
    @contextmanager
    def context():
        with patch.dict(identidad.ABREVIATURA_ARQUITECTURA,{'nodex_multiagente':'rag30'}), \
             patch.object(identidad.IdentidadCorrida,'to_dict',as_dict), \
             patch.object(identidad.IdentidadCorrida,'sufijo',property(suffix)):
            yield
    return context()


def row_identity(case):
    return {key:case[key] for key in ('case_id','dataset','run_id','arquitectura','repeticion','config_version')}


def base_environment(frozen, chroma, cache):
    from dotenv import dotenv_values
    from src.experimentation import campana
    base = {**os.environ,**{k:v for k,v in dotenv_values(ROOT/'.env').items() if v is not None}}
    require(base.get('GEMINI_API_KEY') or base.get('GOOGLE_API_KEY'),'Falta credencial Gemini')
    return campana.entorno_de_la_corrida(base,frozen,chroma,cache)


def preflight():
    COORD.mkdir(parents=True,exist_ok=True)
    check_preservation()
    compatible = runtime_compatibility()
    state = snapshot_state()
    frozen = old.r1_configuration()
    # Validación sin inferencia, en un proceso con una copia temporal.
    if not (COORD/'snapshot_functional_check.json').exists():
        import subprocess
        with tempfile.TemporaryDirectory(prefix='rag-campaign-preflight-',dir=ROOT/'tmp') as td:
            tmp = Path(td).resolve()
            require(tmp.is_relative_to(ROOT/'tmp'),'Temporal fuera del workspace')
            copy_path = tmp/'chroma'
            shutil.copytree(SNAPSHOT,copy_path)
            require(tree(copy_path)==tree(SNAPSHOT),'Restauración inicial incorrecta')
            env = base_environment(frozen,copy_path,tmp/'ip.json')
            result = subprocess.run([sys.executable,str(Path(__file__).resolve()),'--check-copy',str(copy_path)],
                cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',timeout=600)
            (COORD/'preflight.stdout.txt').write_text(result.stdout,encoding='utf-8')
            (COORD/'preflight.stderr.txt').write_text(result.stderr,encoding='utf-8')
            require(result.returncode==0,'Verificación funcional del snapshot falló; consultar preflight.stderr.txt')
    write_new_if_missing(COORD/'compatibility.json',compatible)
    write_new_if_missing(COORD/'rag_initial.json',state)
    check_preservation()
    return compatible,state


def write_new_if_missing(path,value):
    if not path.exists():
        write_new(path,value)


def check_copy(copy_path):
    from src.config import CHROMA_PATH,EMBEDDING_MODEL,SIMILARITY_FLOOR,SIMILARITY_FLOOR_ATTACK
    require(Path(CHROMA_PATH).resolve()==copy_path.resolve() and copy_path.resolve().is_relative_to(ROOT/'tmp'),'Copia mal aislada')
    from src.tools.tool_consultar_rag import ltm,tool_consultar_rag
    from src.tools.aggregation import preprocesar_lote,firma_lote
    cases = load_corpus(RAG)
    expected = read(RAG/'validation/validacion_poblado.json')
    require(collection_state(ltm.patterns)==expected['patterns'],'Los históricos no coinciden')
    require(collection_state(ltm.attack_techniques)==expected['mitre_after'],'MITRE no coincide')
    require(ltm.history.count()==ltm.errors.count()==0,'Memoria dinámica contaminada')
    require(EMBEDDING_MODEL=='all-MiniLM-L6-v2' and SIMILARITY_FLOOR==.55 and SIMILARITY_FLOOR_ATTACK==.42,'Recuperación distinta')
    queries=[]
    for ds in ('bgl','uwf'):
        for cls in ('normal','anomalo'):
            case=next(c for c in cases if c['dataset']==ds and c['classification']==cls)
            _,v2,summary=preprocesar_lote((RAG/case['corpus_path']).read_text(encoding='utf-8'))
            result=tool_consultar_rag({'firma':firma_lote(summary,v2),'resumen_logs':summary})
            require(result['contexto_rag'],'La herramienta real no recupera históricos')
            queries.append(dict(case_id=case['historical_case_id'],retrieved=[r['meta'].get('vector_id') for r in result['contexto_rag']]))
    write_new(COORD/'snapshot_functional_check.json',dict(status='passed',llm_calls=0,queries=queries,
        original_snapshot_unchanged=tree(SNAPSHOT)==read(RAG/'manifests/snapshot_congelado.json')['files']))


def prepare(repetition,state):
    from src.experimentation.runtime.identidad import IdentidadCorrida
    from src.experimentation import campana
    day=datetime.now(ZoneInfo('America/Santiago')).strftime('%Y%m%d')
    existing=list((ROOT/'experiments/ejecucion').glob(f'enriquecido-12casos-r{repetition}-*/selection.json'))
    require(len(existing)<=1,'Múltiples campañas enriquecidas con igual repetición')
    version=existing[0].parent.name if existing else f'enriquecido-12casos-r{repetition}-{day}'
    folder=ROOT/'experiments/ejecucion'/version
    rows=copy.deepcopy(old.r1_selection()['casos'])
    with identity_context():
        for row in rows:
            row.update(IdentidadCorrida(row['case_id'],row['dataset'],'nodex_multiagente',repetition,version).to_dict())
            row['snapshot_sha256']=state['snapshot_tree_sha256']
    selection=dict(copy.deepcopy(old.r1_selection()),config_version=version,repeticion=repetition,casos=rows,**EXTRA)
    write_new_if_missing(folder/'selection.json',selection)
    require(read(folder/'selection.json')==selection,'Selección enriquecida modificada')
    frozen=copy.deepcopy(old.r1_configuration())
    frozen.update(config_version=version,congelada_utc=utc(),repeticion=repetition,**EXTRA,
        rag_snapshot=dict(path=SNAPSHOT.relative_to(ROOT).as_posix(),sha256=state['snapshot_tree_sha256'],collections=read(RAG/'manifests/snapshot_congelado.json')['collections']))
    frozen.pop('huella',None)
    frozen['huella']=hashlib.sha256(json.dumps({k:v for k,v in frozen.items() if k!='congelada_utc'},sort_keys=True,default=str).encode()).hexdigest()
    config_path=campana.ruta_configuracion(ROOT,version)
    write_new_if_missing(config_path,frozen)
    frozen=read(config_path)
    for key in ('parametros','parametros_ausentes','prompts_sha256','capa_experimental_sha256','datasets','conocimiento','semillas','generacion','recursos_externos'):
        require(frozen[key]==old.r1_configuration()[key],f'Diferencia funcional: {key}')
    write_new_if_missing(folder/'rag_initial.json',state)
    compatibility=runtime_compatibility()
    write_new_if_missing(folder/'compatibility.json',compatibility)
    effective=campana.verificar_configuracion(ROOT,ROOT/'.env',frozen)
    require(effective['coincide'],'Configuración efectiva distinta de la congelada')
    own={f'tools/{name}':sha(ROOT/'tools'/name) for name in ('run_enriched_campaign.py','enriched_observation.py','export_enriched_campaign.py')}
    write_new_if_missing(folder/'environment.json',dict(created_utc=utc(),python=sys.version,executable=sys.executable,
        platform=platform.platform(),packages=sorted((d.metadata['Name'],d.version) for d in importlib.metadata.distributions() if d.metadata.get('Name')),
        source_sha256=old.r1_environment()['source_sha256'],orchestration_sha256=own,effective_configuration=effective,
        compatibility=compatibility,policy=dict(attempts_per_case=1,timeout_seconds=campana.TOPE_CORRIDA_S,
        fallback=False,external=campana.RECURSOS_EXTERNOS),**EXTRA))
    for name,value in read(folder/'environment.json')['orchestration_sha256'].items():
        require(sha(ROOT/name)==value,f'Instrumentación cambió desde la preparación: {name}')
    return version,folder,rows,frozen


def isolated_case(row,folder,frozen,state):
    from src.experimentation import campana
    launch=campana.ejecutar_hijo
    record=dict(row_identity(row),**EXTRA)
    def observe(command,cwd,env,timeout):
        copy_path=Path(env['CHROMA_PATH']).resolve()
        require(copy_path!=SNAPSHOT.resolve() and copy_path.is_relative_to(Path(tempfile.gettempdir()).resolve()),'Copia temporal inválida')
        before=old.inspect_chroma(copy_path)
        require(before['files']==state['files'],'Contaminación: bytes iniciales distintos del snapshot')
        require({c['name']:c['document_count'] for c in before['collections']}==read(RAG/'manifests/snapshot_congelado.json')['collections'], 'Conteos iniciales contaminados')
        require(not Path(env['IP_CACHE_PATH']).exists(),'Caché inicial no vacía')
        record.update(initial_chroma=before,chroma_path=str(copy_path),cache_path=env['IP_CACHE_PATH'],
            initial_dynamic_memory_empty=True,historical_patterns_available=30,
            snapshot_sha256=state['snapshot_tree_sha256'],independent_working_copy=True,checked_utc=utc())
        new_command=[sys.executable,str(Path(__file__).resolve()),'--worker',*command[command.index('--trabajar')+1:]]
        env['RAG_OBSERVATION_PATH']=str(folder/f"{row['run_id']}.rag_observation.jsonl")
        result=launch(new_command,cwd,env,timeout)
        record['final_chroma']=old.inspect_chroma(copy_path)
        if result[0]==2 or not Path(env['RAG_OBSERVATION_PATH']).exists():
            (folder/f"{row['run_id']}.prelaunch.stdout.txt").write_text(result[1],encoding='utf-8')
            (folder/f"{row['run_id']}.prelaunch.stderr.txt").write_text(result[2],encoding='utf-8')
            raise RuntimeError('El proceso no inició NODEX/instrumentación; detener sin lanzar más casos')
        return result
    env=base_environment(frozen,Path('.'),Path('.'))
    try:
        with identity_context(), patch.object(campana,'configuracion_experimental',lambda root:SimpleNamespace(chroma=SNAPSHOT)), \
             patch.object(campana,'ejecutar_hijo',observe):
            outcome=campana.correr_una(ROOT,env,frozen,row,'evaluacion',row['config_version'],folder)
    finally:
        record['seed_unchanged_after_case']=tree(SNAPSHOT)==read(RAG/'manifests/snapshot_congelado.json')['files']
        record['working_copy_discarded']=bool(record.get('chroma_path')) and not Path(record['chroma_path']).exists()
        write_new(folder/f"{row['run_id']}.isolation.json",record)
    require(record['seed_unchanged_after_case'] and record['working_copy_discarded'],'Aislamiento falló')
    return outcome


def worker(arguments):
    from src.experimentation import campana
    from src.experimentation.runtime.identidad import IdentidadCorrida
    dataset,case,architecture,repetition,version,partition,destination=arguments
    require(partition=='evaluacion','Partición distinta de evaluación')
    with identity_context():
        identity=IdentidadCorrida(case,dataset,architecture,int(repetition),version).to_dict()
        runtime_compatibility()
        from tools.enriched_observation import RagObserver
        observer=RagObserver(Path(os.environ['RAG_OBSERVATION_PATH']),identity)
        observer.install()  # antes de que el grafo importe la herramienta
        try:
            return campana.trabajar(ROOT,dataset,case,architecture,int(repetition),version,partition,Path(destination))
        finally:
            observer.close()


def execute():
    compatible,state=preflight()
    from tools.export_enriched_campaign import export, joint_audit
    for repetition in (1,2,3):
        if repetition>1:
            previous=list((ROOT/'extracted_data').glob(f'enriquecido-12casos-r{repetition-1}-*/verification.json'))
            require(len(previous)==1 and read(previous[0])['integrity_passed'],'Repetición anterior sin extraer y validar')
        version,folder,rows,frozen=prepare(repetition,state)
        print(f'REPETITION {repetition}: {version}',flush=True)
        for row in rows:
            started,result=folder/f"{row['run_id']}.started.json",folder/f"{row['run_id']}.result.json"
            if started.exists():
                require(result.exists(),f'Intento previo incompleto: {row["case_id"]}; no se repite')
                print(f"SKIP_RECORDED {row['run_id']}",flush=True)
                continue
            runtime_compatibility()
            snapshot_state()
            write_new(started,dict(row,process_started_utc=utc()))
            print(f"START R{repetition} {row['orden']}/12 {row['case_id']}",flush=True)
            clock=time.perf_counter()
            try:
                outcome=isolated_case(row,folder,frozen,state)
            except Exception as error:
                write_new(result,dict(row,estado='error_lanzador',error=f'{type(error).__name__}: {error}',finished_utc=utc()))
                raise
            outcome.update(process_finished_utc=utc(),wall_seconds=time.perf_counter()-clock,config_version=version,**EXTRA)
            write_new(result,outcome)
            print(f"FINISH R{repetition} {row['orden']}/12 {outcome['estado']} {outcome['wall_seconds']:.1f}s",flush=True)
            # Un fallo se conserva; el modelo efectivo de las llamadas exitosas
            # debe seguir siendo el mismo que respondió en las campañas originales.
            tel=ROOT/'experiments/telemetry'/row['dataset']/f"{row['run_id']}.json"
            if tel.exists():
                for call in read(tel)['telemetria'].get('llm_calls',[]):
                    require(call.get('model')==frozen['parametros']['LLM_MODEL_PRIMARY'],'Otro modelo solicitado')
                    if not call.get('error'):
                        require(call.get('model_version')=='gemini-3.8-flash','El proveedor devolvió una versión efectiva diferente; detener')
            check_preservation()
        report=export(version)
        print('EXTRACTED '+json.dumps(report,ensure_ascii=False),flush=True)
    report=joint_audit()
    print('ALL_CAMPAIGNS_AUDITED '+json.dumps(report,ensure_ascii=False),flush=True)
    return 0


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute',action='store_true')
    p.add_argument('--worker',nargs=7)
    p.add_argument('--check-copy',type=Path)
    args=p.parse_args()
    if args.worker:
        return worker(args.worker)
    if args.check_copy:
        check_copy(args.check_copy)
        return 0
    if args.execute:
        return execute()
    compatible,state=preflight()
    version,folder,rows,frozen=prepare(1,state)
    print(json.dumps(dict(status='prepared_without_inference',version=version,cases=12,
                         snapshot_sha256=state['snapshot_tree_sha256'],compatibility=compatible),ensure_ascii=False),flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
