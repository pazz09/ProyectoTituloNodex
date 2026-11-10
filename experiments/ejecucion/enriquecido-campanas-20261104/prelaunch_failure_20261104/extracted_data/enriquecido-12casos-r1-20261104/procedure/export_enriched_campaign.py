"""Extracción literal R1 reutilizada; observabilidad RAG separada y auditoría sin métricas."""
from __future__ import annotations
import argparse
import csv
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
try:
    from tools import export_experimental_data as original
except ImportError:
    import export_experimental_data as original


def read(path):
    return original.read(Path(path))


def lines(path):
    return [json.loads(l) for l in Path(path).read_text(encoding='utf-8').splitlines()] if Path(path).exists() else []


def jsonl(path,rows):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='\n') as f:
        for row in rows:
            f.write(json.dumps(row,ensure_ascii=False)+'\n')


def rag_usage(logs,selection,folder):
    queries,documents,summaries,deliveries=[],[],[],[]
    for row in selection['casos']:
        identity={k:row[k] for k in ('case_id','dataset','run_id','repeticion','config_version')}
        identity.update(condicion_rag='enriquecido',rag_version='rag_enriquecido_30_v1',casos_historicos=30)
        events=lines(logs/f"{row['run_id']}.rag_observation.jsonl")
        requests=[e for e in events if e['event']=='rag_requested']
        memories=[e for e in events if e['event']=='memory_query']
        payloads=[e for e in events if e['event']=='llm_sdk_request']
        responses={e['request_event_index']:e for e in events if e['event']=='llm_sdk_response'}
        returned=[]
        for event in requests:
            queries.append(dict(identity,query_id=event['query_id'],signature=event['signature'],utc=event['utc']))
        for event in memories:
            for candidate in event['candidates']:
                documents.append(dict(identity,query_id=event['query_id'],collection=event['collection'],
                    utc=event['utc'],**candidate,ties_among_top_k=event['ties_among_top_k']))
                if candidate['returned_by_memory']:
                    returned.append(candidate)
        for event in payloads:
            response=responses.get(event['event_index'],{})
            deliveries.append(dict(identity,request_event_index=event['event_index'],agent=event['agent'],
                model=event['model'],prompt_sha256=event['prompt_sha256'],documents_in_payload=event['documents_in_payload'],
                provider_response_success=response.get('success'),model_version=response.get('model_version'),
                causal_influence='not_observable'))
        prediction_path=ROOT/'experiments/nodex'/row['dataset']/f"{row['run_id']}.json"
        prediction=read(prediction_path) if prediction_path.exists() else {}
        # Se buscan referencias solo en la salida final, nunca en el estado que
        # contiene los propios documentos RAG: eso produciría citas ficticias.
        final_output={k:v for k,v in prediction.get('salida',{}).items() if not k.startswith('_')}
        final_text=json.dumps(final_output,ensure_ascii=False)
        citations=[]
        for doc in returned:
            meta=doc['metadata']
            ids=[doc['vector_id'],meta.get('historical_case_id'),meta.get('original_id')]
            matched=[identifier for identifier in ids if identifier and identifier in final_text]
            if matched:
                citations.append(dict(vector_id=doc['vector_id'],literal_identifiers=matched,
                                      causal_influence='not_observable'))
        historical=[d for d in returned if d['knowledge_type']=='historical']
        sent={d.get('vector_id') or d.get('technique_id') for p in payloads for d in p['documents_in_payload']}
        summaries.append(dict(identity,rag_requested=bool(requests),rag_tool_queries=len(requests),
            chroma_queries=len(memories),documents_returned=len(returned),historical_documents_returned=len(historical),
            historical_vector_ids=sorted({d['vector_id'] for d in historical}),
            static_mitre_documents_returned=sum(d['knowledge_type']=='mitre_static' for d in returned),
            historical_datasets=sorted({d['metadata'].get('dataset') for d in historical if d['metadata'].get('dataset')}),
            queries_with_observed_ties=sum(bool(e['ties_among_top_k']) for e in memories),
            documents_observed_in_llm_payload=len(sent),
            historical_documents_observed_in_llm_payload=sorted({d.get('vector_id') for p in payloads
                for d in p['documents_in_payload'] if d['knowledge_type']=='historical' and d.get('vector_id')}),
            explicit_final_identifier_references=citations, influence_in_reasoning='not_observable',
            observer_present=any(e['event']=='observer_installed' for e in events),
            limitations=['Empates solo observables dentro del top-k.',
                'Presencia literal de documentos observada en argumentos del SDK; una respuesta fallida no confirma recepción por el proveedor.',
                'Ausencia de ID literal en la salida no demuestra ausencia de influencia; recuperación y envío tampoco demuestran influencia causal.']))
    jsonl(folder/'rag_usage/queries.jsonl',queries)
    jsonl(folder/'rag_usage/retrieved_documents.jsonl',documents)
    jsonl(folder/'rag_usage/retrieval_summary.jsonl',summaries)
    jsonl(folder/'rag_usage/llm_delivery.jsonl',deliveries)
    original.write_json(folder/'rag_usage/initial_state.json',dict(read(logs/'rag_initial.json'),
        cases=[dict(case_id=r['case_id'],run_id=r['run_id'],repeticion=r['repeticion'],
                    initial_state_evidence=f"../originals/execution/experiments/ejecucion/{logs.name}/{r['run_id']}.isolation.json")
               for r in selection['casos']]))
    return summaries


def verify(folder):
    folder=Path(folder).resolve()
    match=re.fullmatch(r'enriquecido-12casos-r([123])-\d{8}',folder.name)
    if not match:
        raise ValueError('Verificador limitado a extracciones enriquecidas')
    repetition=int(match[1])
    manifest=read(folder/'manifest.json');documents={};copied=0
    for item in manifest:
        if item['available']:
            path=folder/item['export_path']
            assert original.sha(path)==item['sha256_source']==item['sha256_copy'],path
            assert path.stat().st_size==item['size_bytes'],path
            if path.suffix=='.json':
                documents[item['export_path']]=read(path)
            copied+=1
    projected=0
    for path in folder.rglob('*.jsonl'):
        for row in lines(path):
            if 'source_json_pointer' not in row:
                continue
            assert row['repeticion']==repetition and row['condicion_rag']=='enriquecido'
            assert f'__rag30__r{repetition}__' in row['run_id']
            if not row['source_file_available']:
                assert row['present'] is False and 'value' not in row
                continue
            present,value=original.pointer(documents[row['source_export_path']],row['source_json_pointer'])
            assert row['present']==present
            if present:
                assert json.dumps(row['value'],sort_keys=True)==json.dumps(value,sort_keys=True)
            else:
                assert 'value' not in row
            projected+=1
    statuses=lines(folder/'run_status.jsonl')
    assert len(statuses)==12 and len({r['run_id'] for r in statuses})==12
    assert all(r['repeticion']==repetition and r['config_version']==folder.name for r in statuses)
    reports=0
    for row in lines(folder/'reports/text.jsonl'):
        if row['present'] and isinstance(row['value'],str):
            assert (folder/'reports/generated'/f"{row['run_id']}.md").read_bytes()==row['value'].encode('utf-8')
            reports+=1
    summary=lines(folder/'rag_usage/retrieval_summary.jsonl')
    assert len(summary)==12 and all(r['observer_present'] for r in summary)
    isolation=[doc for name,doc in documents.items() if name.endswith('.isolation.json')]
    assert len(isolation)==12
    for doc in isolation:
        assert doc['seed_unchanged_after_case'] and doc['working_copy_discarded'] and doc['independent_working_copy']
        counts={c['name']:c['document_count'] for c in doc['initial_chroma']['collections']}
        assert counts==dict(attack_patterns=30,attack_techniques=697,error_memory=0,host_history=0)
    result=dict(integrity_passed=True,cases=len(statuses),completed=sum(r['estado']=='completa' for r in statuses),
        failed=sum(r['estado']!='completa' for r in statuses),verified_original_files=copied,
        verified_projections=projected,verified_reports=reports,repeticion=repetition,
        rag_queries=sum(r['rag_tool_queries'] for r in summary),
        historical_retrievals=sum(r['historical_documents_returned'] for r in summary),
        cases_with_historical_retrieval=sum(bool(r['historical_documents_returned']) for r in summary),
        no_metrics_calculated=True,required_missing=read(folder/'extraction.json')['required_missing'],
        verifier_sha256=original.sha(Path(__file__)))
    original.write_json(folder/'verification.json',result)
    return result


def export(version):
    from tools import run_enriched_campaign as runner
    runner.check_preservation()
    logs=ROOT/'experiments/ejecucion'/version
    selection=read(logs/'selection.json');repetition=selection['repeticion']
    folder=ROOT/'extracted_data'/version
    if folder.exists():
        result=verify(folder)
        if folder.with_suffix('.zip').exists():
            return dict(result,config_version=version,archive=str(folder.with_suffix('.zip')))
        raise FileExistsError('Extracción previa sin ZIP; no se sobrescribe ni repite la inferencia')
    Base=original.Export
    class EnrichedExport(Base):
        def enrich(self,identity):
            return dict(identity,**runner.EXTRA,repeticion=identity.get('repeticion',repetition),
                        snapshot_sha256=read(logs/'rag_initial.json')['snapshot_tree_sha256'])
        def copy(self,source,identity,category,required=True):
            return super().copy(source,self.enrich(identity),category,required)
        def project(self,table,document,source,identity,paths,items=False):
            return super().project(table,document,source,self.enrich(identity),paths,items)
    with patch.object(original,'Export',EnrichedExport):
        original.export(ROOT,version,folder)
    ex=EnrichedExport(ROOT,folder)
    ex.manifest=read(folder/'manifest.json')
    for name in ('rag_initial.json','compatibility.json'):
        ex.copy(logs/name,dict(config_version=version),'configuration')
    for name in ('preservation_before.json','compatibility.json','rag_initial.json','snapshot_functional_check.json'):
        ex.copy(runner.COORD/name,dict(config_version=version),'configuration')
    for path in sorted(runner.RAG.rglob('*')):
        if path.is_file():
            ex.copy(path,dict(config_version=version),'knowledge')
    for row in selection['casos']:
        for suffix in ('isolation.json','rag_observation.jsonl'):
            ex.copy(logs/f"{row['run_id']}.{suffix}",row,'execution')
    ex.finish()
    # La tabla de estados la crea el extractor base directamente, no mediante
    # project: se añaden solo coordenadas experimentales al nivel superior.
    for path in folder.rglob('*.jsonl'):
        if 'originals' not in path.relative_to(folder).parts:
            jsonl(path,[dict(r,**runner.EXTRA,repeticion=r.get('repeticion',repetition),
                            snapshot_sha256=read(logs/'rag_initial.json')['snapshot_tree_sha256']) for r in lines(path)])
    baseline_folder=ROOT/'extracted_data'/runner.ORIGINALS[0]
    for path in baseline_folder.rglob('*.jsonl'):
        relative=path.relative_to(baseline_folder)
        if 'originals' not in relative.parts and not (folder/relative).exists():
            jsonl(folder/relative,[])
    summaries=rag_usage(logs,selection,folder)
    extraction=read(folder/'extraction.json')
    extraction.update(**runner.EXTRA,repeticion=repetition,
        snapshot_sha256=read(logs/'rag_initial.json')['snapshot_tree_sha256'],
        required_missing=[x['source_path'] for x in ex.manifest if x['required'] and not x['available']],
        wrapper_sha256=original.sha(Path(__file__)))
    original.write_json(folder/'extraction.json',extraction)
    notebook=read(folder/'revision_datos_crudos.ipynb')
    for index,cell in enumerate(notebook['cells']):
        cell['source']=''.join(cell['source']).replace(runner.ORIGINALS[0],version).splitlines(keepends=True)
        cell.setdefault('id',f'cell-{index:03d}')
        if cell['cell_type']=='code':
            compile(''.join(cell['source']),f'cell-{index}','exec')
    original.write_json(folder/'revision_datos_crudos.ipynb',notebook)
    procedure=folder/'procedure';procedure.mkdir(exist_ok=True)
    for name in ('run_enriched_campaign.py','enriched_observation.py','export_enriched_campaign.py','export_experimental_data.py'):
        shutil.copyfile(ROOT/'tools'/name,procedure/name)
    (folder/'README.md').write_text(f'''# NODEX — {version}

Doce casos oficiales en el mismo orden; repetición {repetition}, condición RAG enriquecido. Predicciones y referencias conservan las proyecciones literales originales: detection, reconstruction, mitre, reports y performance. No se normalizaron nuevas técnicas ni se calcularon métricas D1–D4.

`originals/` conserva archivos byte a byte y el snapshot usado. Los manifiestos contienen SHA-256 y procedencia; `present` distingue ausencia de null y los archivos `_items` preservan orden y duplicados. El notebook solo inspecciona datos.

`rag_usage/queries.jsonl` registra solicitudes naturales; `retrieved_documents.jsonl`, candidatos nativos y documentos devueltos por memoria; `llm_delivery.jsonl`, presencia literal del documento en los argumentos reales del SDK y resultado de la solicitud; `retrieval_summary.jsonl`, referencias literales en la salida final y límites de observación. Recuperar o entregar contexto no demuestra influencia causal en el razonamiento. Los empates fuera del top-k no son observables.

Cada caso partió de una copia independiente del mismo snapshot: 30 patrones históricos, 697 técnicas MITRE y memorias de errores/historial vacías. La evidencia individual está en los archivos `.isolation.json`. Los históricos no se borraron al limpiar memoria dinámica.

Se mantienen las limitaciones del corpus: once BGL comparten firmas genéricas entre clases y hay empates sin desempate estable; los UWF históricos son episodios sigilosos y no tienen campaign_id verificable.

El código funcional, prompts, modelo, generación, routers y umbrales coinciden con R1. `compatibility.json` documenta cinco diferencias auxiliares del inventario del runtime actualizado: cuatro versiones quedan ocultas por las originales del venv; artifact_tool no pertenece a NODEX ni se importa. No se afirma identidad absoluta de los paquetes instalados. La instrumentación añade solo observación y metadatos/IDs de campaña, sin modificar decisiones ni argumentos enviados al modelo.

Consultar `verification.json`, `manifest.json`, `extraction.json` y `rag_usage/initial_state.json`. Los errores se conservan en `run_status.jsonl` y no se reintentan experimentalmente. Para verificar las copias/proyecciones: `python procedure/export_enriched_campaign.py --verify .`.
''',encoding='utf-8')
    result=verify(folder)
    # Entradas y ground truth idénticos a R1, comprobados solo después de inferir.
    baseline=read(ROOT/'extracted_data'/runner.ORIGINALS[0]/'manifest.json')
    for category in ('inputs','ground_truth'):
        def hashes(manifest):
            return {r['source_path']:r['sha256_copy'] for r in manifest if r['available'] and r['export_path'].startswith(f'originals/{category}/')}
        assert hashes(baseline)==hashes(ex.manifest),category
    original.write_json(folder/'repetition_integrity.json',dict(input_and_ground_truth_hashes_equal_R1=True,
        original_campaigns_and_snapshot_unchanged=runner.check_preservation(),snapshot_sha256=read(logs/'rag_initial.json')['snapshot_tree_sha256'],
        independent_case_copies=12,functional_source_hashes_match_R1=True))
    archive=folder.with_suffix('.zip')
    if archive.exists():
        raise FileExistsError(archive)
    shutil.make_archive(str(folder),'zip',root_dir=folder)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert {i.filename for i in z.infolist() if not i.is_dir()}=={p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()}
    archive.with_suffix('.zip.sha256').write_text(original.sha(archive)+'  '+archive.name+'\n',encoding='ascii')
    return dict(result,config_version=version,extraction=str(folder),archive=str(archive),archive_sha256=original.sha(archive))


def joint_audit():
    from tools import run_enriched_campaign as runner
    originals=[ROOT/'extracted_data'/v for v in runner.ORIGINALS]
    enriched=sorted((ROOT/'extracted_data').glob('enriquecido-12casos-r[123]-*'))
    enriched=[p for p in enriched if p.is_dir()]
    assert len(enriched)==3
    reference=[r['case_id'] for r in lines(originals[0]/'run_status.jsonl')]
    all_runs=set();reports=[];snapshots=set()
    for folder in originals+enriched:
        statuses=lines(folder/'run_status.jsonl')
        assert [r['case_id'] for r in statuses]==reference
        ids={r['run_id'] for r in statuses}
        assert len(ids)==12 and not all_runs&ids
        all_runs|=ids
        manifest=read(folder/'manifest.json')
        for category in ('inputs','ground_truth'):
            def hashes(m):
                return {r['source_path']:r['sha256_copy'] for r in m if r['available'] and r['export_path'].startswith(f'originals/{category}/')}
            assert hashes(manifest)==hashes(read(originals[0]/'manifest.json'))
        if folder in enriched:
            verification=verify(folder)
            assert folder.with_suffix('.zip').exists()
            snapshots.add(read(folder/'rag_usage/initial_state.json')['snapshot_tree_sha256'])
            reports.append(dict(version=folder.name,**verification))
    assert len(snapshots)==1
    report=dict(status='passed',campaigns=6,cases_per_campaign=12,unique_runs=len(all_runs),
        all_input_hashes_identical=True,all_ground_truth_hashes_identical=True,
        enriched_snapshot_sha256=next(iter(snapshots)),independent_copies_per_enriched_case=True,
        functional_parameters_and_sources_unchanged=True,dependency_inventory_caveat=read(runner.COORD/'compatibility.json'),
        preservation=runner.check_preservation(),enriched=reports,no_metrics_calculated=True)
    original.write_json(runner.COORD/'joint_audit.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--verify',type=Path)
    p.add_argument('--version')
    a=p.parse_args()
    print(json.dumps(verify(a.verify) if a.verify else export(a.version),ensure_ascii=False))
