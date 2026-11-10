"""Controles offline para R2/R3: preservación, aislamiento e identidades."""
import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools import export_experimental_data as extractor
from tools import run_official_repetitions as runner
from tools import verify_official_repetition as verifier
from tools import verify_official_repetitions_joint as joint


def make_seed(path):
    path.mkdir(parents=True)
    with closing(sqlite3.connect(path / 'chroma.sqlite3')) as db:
        db.executescript('CREATE TABLE collections(id,name,dimension,config_json_str,schema_str);'
                         'CREATE TABLE segments(id,collection);CREATE TABLE embeddings(segment_id);')
        db.execute("INSERT INTO collections VALUES ('c','attack_techniques',384,'{}','{}')")
        db.execute("INSERT INTO segments VALUES ('s','c')")
        db.executemany("INSERT INTO embeddings VALUES ('s')", [() for _ in range(697)])
        db.commit()


class RepetitionTests(unittest.TestCase):
    def test_preservation_is_read_only_and_detects_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            r1 = root / 'r1'
            r1.mkdir()
            (r1 / 'manifest.json').write_text('[]', encoding='utf-8')
            original = r1 / 'result.json'
            original.write_bytes(b'{"stable":true}\r\n')
            with patch.multiple(runner, ROOT=root, R1_EXPORT=r1, COORDINATION=root / 'coord'):
                before = runner.tree_hashes(r1)
                self.assertTrue(runner.protect_r1()['unchanged'])
                self.assertEqual(before, runner.tree_hashes(r1))
                original.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'cambiaron'):
                    runner.protect_r1()

    def test_rag_requires_original_bytes_and_empty_memory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            seed = root / 'experiments/knowledge/chroma_v2'
            make_seed(seed)
            knowledge = seed.parent
            snapshot = {'snapshot': {'archivos': {name: {'bytes': row['size_bytes'], 'sha256': row['sha256']}
                for name, row in runner.tree_hashes(seed).items()}}}
            extractor.write_json(knowledge / 'poblado_chroma_v2.json', snapshot)
            extractor.write_json(knowledge / 'inventario_conocimiento_v2.json', {})
            extractor.write_json(knowledge / 'verificacion_chroma_v2.json', {})
            config = {'conocimiento': {key: extractor.sha(knowledge / name) for name, key in [
                ('poblado_chroma_v2.json', 'poblado_v2_sha256'), ('inventario_conocimiento_v2.json', 'inventario_v2_sha256'),
                ('verificacion_chroma_v2.json', 'verificacion_v2_sha256')]}}
            with patch.multiple(runner, ROOT=root, SEED=seed), patch.object(runner, 'r1_configuration', return_value=config):
                self.assertTrue(runner.clean_rag()['dynamic_empty'])
                with closing(sqlite3.connect(seed / 'chroma.sqlite3')) as db:
                    db.execute("INSERT INTO collections VALUES ('bad','host_history',384,'{}','{}')")
                    db.execute("INSERT INTO segments VALUES ('bad-s','bad')")
                    db.execute("INSERT INTO embeddings VALUES ('bad-s')")
                    db.commit()
                with self.assertRaisesRegex(ValueError, 'idéntica'):
                    runner.clean_rag()

    def isolation_fixture(self, root, dirty_cache=False):
        seed = root / 'seed'
        make_seed(seed)
        row = dict(run_id='case__nodex__r2__test', case_id='case', repeticion=2, config_version='r2')
        calls = []
        def launch(*args):
            calls.append(args)
            return (0, '', '', False)
        campaign = SimpleNamespace(ejecutar_hijo=launch)
        def run(*args):
            with tempfile.TemporaryDirectory() as temp:
                copied, cache = Path(temp) / 'chroma', Path(temp) / 'ip.json'
                shutil.copytree(seed, copied)
                if dirty_cache:
                    cache.write_text('{}', encoding='utf-8')
                campaign.ejecutar_hijo(['mock-child'], root, {'CHROMA_PATH': str(copied), 'IP_CACHE_PATH': str(cache)}, 5)
            return {'estado': 'completa'}
        campaign.correr_una = run
        folder = root / 'logs'
        frozen = {'parametros': {'LLM_MODEL_PRIMARY': 'gemini-3.8-flash'}}
        with patch.multiple(runner, ROOT=root, SEED=seed):
            if dirty_cache:
                with self.assertRaisesRegex(ValueError, 'caché'):
                    runner.isolated_case(campaign, row, folder, {}, frozen, runner.inspect_chroma(seed))
                self.assertEqual(len(calls), 0)
            else:
                outcome = runner.isolated_case(campaign, row, folder, {}, frozen, runner.inspect_chroma(seed))
                self.assertEqual(outcome['estado'], 'completa')
                self.assertEqual(len(calls), 1)
                record = runner.read(folder / f"{row['run_id']}.isolation.json")
                self.assertTrue(record['cache_absent_before_inference'])
                self.assertTrue(record['working_copy_discarded'])
                self.assertTrue(record['seed_unchanged_after_case'])

    def test_case_uses_clean_copy_then_discards_it(self):
        with tempfile.TemporaryDirectory() as temp:
            self.isolation_fixture(Path(temp))

    def test_preexisting_cache_blocks_inference(self):
        with tempfile.TemporaryDirectory() as temp:
            self.isolation_fixture(Path(temp), dirty_cache=True)

    def test_verifier_refuses_r1_without_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'oficial-12casos-r1-20261028'
            folder.mkdir()
            before = runner.tree_hashes(folder)
            with self.assertRaisesRegex(ValueError, 'R1'):
                verifier.verify(folder)
            self.assertEqual(before, runner.tree_hashes(folder))

    def test_r2_notebook_loads_and_mixed_repetitions_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            version = 'oficial-12casos-r2-20261103'
            case = dict(case_id='bgl_x', dataset='bgl', particion='evaluacion',
                run_id='bgl_x__nodex__r2__test', arquitectura='nodex_multiagente',
                repeticion=2, config_version=version, orden=1)
            input_path = root / 'experiments/cases/bgl/evaluacion/bgl_x.log'
            input_path.parent.mkdir(parents=True)
            input_path.write_bytes(b'example\r\n')
            extractor.write_json(input_path.with_suffix('.json'), {'procedencia': []})
            extractor.write_json(root / 'experiments/ground_truth/bgl/evaluacion/bgl_x.json', {})
            logs = root / 'experiments/ejecucion' / version
            extractor.write_json(logs / 'selection.json', {'casos': [dict(case,
                input_path=input_path.relative_to(root).as_posix(), sha256=extractor.sha(input_path))]})
            extractor.write_json(logs / 'environment.json', {'source_sha256': {}})
            extractor.write_json(root / 'experiments/config' / f'config_{version}.json', {})
            output = root / version
            extractor.export(root, version, output)
            result = verifier.verify(output, execute_notebook=True)
            self.assertEqual(result['repeticion'], 2)
            self.assertEqual(result['notebook_code_cells_executed'], 10)
            status = output / 'run_status.jsonl'
            row = json.loads(status.read_text(encoding='utf-8').splitlines()[0])
            row['repeticion'] = 3
            status.write_text(json.dumps(row) + '\n', encoding='utf-8')
            with self.assertRaises(AssertionError):
                verifier.verify(output)

    def test_joint_notebook_loads_36_distinct_run_identities(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            versions = {rep: f'synthetic-r{rep}' for rep in (1, 2, 3)}
            for rep, name in versions.items():
                folder = root / name
                extractor.write_json(folder / 'extraction.json', {})
                extractor.write_json(folder / 'manifest.json', [])
                with (folder / 'run_status.jsonl').open('w', encoding='utf-8') as stream:
                    for case in range(12):
                        stream.write(json.dumps(dict(case_id=f'case{case}', repeticion=rep,
                            run_id=f'case{case}__r{rep}__test', config_version=name)) + '\n')
            with patch.object(joint, 'ROOT', root):
                self.assertEqual(joint.notebook(versions, root / 'joint.ipynb'), 5)


if __name__ == '__main__':
    unittest.main()
