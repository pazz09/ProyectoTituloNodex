import json
from pathlib import Path

from tools.enriched_observation import RagObserver,contains_document
from tools import run_enriched_campaign as runner
from tools import export_enriched_campaign as exporter


def test_identifier_namespace_preserves_canonical_identity():
    from src.experimentation.runtime.identidad import IdentidadCorrida
    identity=IdentidadCorrida('bgl_case','bgl','nodex_multiagente',2,'enriquecido-version')
    before=identity.to_dict()
    with runner.identity_context():
        value=identity.to_dict()
        assert '__rag30__r2__' in value['run_id']
        assert value['case_id']==before['case_id'] and value['arquitectura']==before['arquitectura']
        assert value['condicion_rag']=='enriquecido' and value['casos_historicos']==30
        assert value['run_id'].split('__')[-1]!=before['run_id'].split('__')[-1]
        assert identity.to_dict()==value
    assert identity.to_dict()==before


def test_delivery_requires_full_document_not_identifier_alone():
    document={'texto':'signature','meta':{'vector_id':'historical-id'},'similitud':.9}
    assert not contains_document('Mencionado historical-id',document)
    assert contains_document('CONTEXTO: '+json.dumps([document],ensure_ascii=False),document)


def test_observer_event_has_independent_identity_and_utf8(tmp_path):
    path=tmp_path/'events.jsonl';identity={'case_id':'case','run_id':'run','repeticion':3}
    observer=RagObserver(path,identity)
    observer.emit('example',value='descripción')
    observer.emit('example',value=None)
    rows=exporter.lines(path)
    assert [r['event_index'] for r in rows]==[1,2]
    assert all(r['run_id']=='run' and r['repeticion']==3 for r in rows)
    assert rows[0]['value']=='descripción' and rows[1]['value'] is None


def test_snapshot_inventory_is_verified_without_modifying_it():
    before=runner.tree(runner.SNAPSHOT)
    state=runner.snapshot_state()
    assert state['historical_cases']==30 and state['dynamic_empty']
    assert state['files']==runner.old.inspect_chroma(runner.SNAPSHOT)['files']
    assert runner.tree(runner.SNAPSHOT)==before


def test_functional_sources_and_effective_dependency_paths_match():
    compatibility=runner.runtime_compatibility()
    assert compatibility['source_hashes_match_R1']
    assert compatibility['input_hashes_and_order_match_R1']
    assert len(compatibility['effective_original_auxiliary_paths'])==4


def test_jsonl_preserves_null_lists_and_duplicates(tmp_path):
    value=[{'present':True,'value':None},{'present':True,'value':[]},
           {'present':True,'value':['T1590','T1590']},{'present':False}]
    exporter.jsonl(tmp_path/'projection.jsonl',value)
    assert exporter.lines(tmp_path/'projection.jsonl')==value


def test_worker_cli_accepts_the_seven_original_launcher_arguments(monkeypatch):
    received=[]
    arguments=['bgl','case','nodex_multiagente','1','version','evaluacion','output.json']
    monkeypatch.setattr(runner.sys,'argv',['run_enriched_campaign.py','--worker',*arguments])
    monkeypatch.setattr(runner,'worker',lambda values:received.append(values) or 0)
    assert runner.main()==0
    assert received==[arguments]
