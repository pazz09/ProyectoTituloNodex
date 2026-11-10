"""Verificaciones offline: preservación y ejecución única, sin llamadas a modelos."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import export_experimental_data as exporter
from tools import run_official_experiment as runner
from tools import verify_experimental_export as verifier


class OfficialExtractionTests(unittest.TestCase):
    def test_pointer_distinguishes_missing_null_and_empty(self):
        data = {'a': None, 'b': [], 'c': '', 'a/b': [1, 1]}
        self.assertEqual(exporter.pointer(data, '/a'), (True, None))
        self.assertEqual(exporter.pointer(data, '/missing'), (False, None))
        self.assertEqual(exporter.pointer(data, '/b'), (True, []))
        self.assertEqual(exporter.pointer(data, '/c'), (True, ''))
        self.assertEqual(exporter.pointer(data, '/a~1b/1'), (True, 1))

    def test_literal_projection_keeps_order_and_duplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ex = exporter.Export(root, root / 'out')
            doc = {'events': [{'uid': 'a'}, {'uid': 'a'}], 'empty': [], 'null': None, 'text': ''}
            source = root / 'input.json'
            source.write_bytes(json.dumps(doc).encode() + b'\r\n')
            copy, entry = ex.copy(source, {'case_id': 'x'}, 'inputs')
            ex.project('rows.jsonl', copy, entry, {}, ['/events', '/empty', '/null', '/text', '/missing'], items=True)
            ex.finish()
            self.assertEqual(source.read_bytes(), (ex.output / entry['export_path']).read_bytes())
            rows = [json.loads(line) for line in (ex.output / 'rows.jsonl').read_text().splitlines()]
            self.assertEqual(rows[1]['value'], [])
            self.assertIsNone(rows[2]['value'])
            self.assertEqual(rows[3]['value'], '')
            self.assertFalse(rows[4]['present'])
            self.assertNotIn('value', rows[4])
            items = ex.tables['rows_items.jsonl']
            self.assertEqual([row['value']['uid'] for row in items], ['a', 'a'])
            self.assertEqual([row['source_json_pointer'] for row in items], ['/events/0', '/events/1'])

    def test_input_hash_mismatch_stops_before_inference(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / 'experiments/cases/bgl/evaluacion/bgl_eva_balanceado_0006.log'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'Entrada diferente'):
                runner.validate_inputs(root)

    def test_started_failed_case_is_never_repeated(self):
        with tempfile.TemporaryDirectory() as temp:
            row = dict(case_id='x', run_id='x', dataset='bgl', orden=1)
            folder = Path(temp)
            with patch.object(runner, 'prepare', return_value=([row], folder, {}, {})), \
                 patch('src.experimentation.campana.correr_una', return_value={'estado': 'error_api', 'infraestructura': True}) as run:
                runner.main(['--execute'])
                runner.main(['--execute'])
            self.assertEqual(run.call_count, 1)
            self.assertTrue((folder / 'x.started.json').exists())
            self.assertTrue((folder / 'x.result.json').exists())

    def test_export_missing_outputs_remain_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            identity = dict(case_id='bgl_x', dataset='bgl', particion='evaluacion', run_id='r',
                            arquitectura='nodex_multiagente', repeticion=1, config_version='test', orden=1)
            inp = root / 'experiments/cases/bgl/evaluacion/bgl_x.log'
            inp.parent.mkdir(parents=True)
            inp.write_bytes(b'example\r\n')
            write = exporter.write_json
            write(inp.with_suffix('.json'), {'procedencia': []})
            write(root / 'experiments/ground_truth/bgl/evaluacion/bgl_x.json', {'estado_dimension': {'reconstruccion': 'no_aplica'}})
            folder = root / 'experiments/ejecucion/test'
            write(folder / 'selection.json', {'casos': [dict(identity, input_path=inp.relative_to(root).as_posix(), sha256=hashlib.sha256(inp.read_bytes()).hexdigest())]})
            write(folder / 'environment.json', {'source_sha256': {}})
            write(root / 'experiments/config/config_test.json', {})
            out = root / 'export'
            result = exporter.export(root, 'test', out)
            self.assertEqual(result['cases'], 1)
            self.assertEqual(result['completed'], 0)
            self.assertTrue(result['required_missing'])
            row = json.loads((out / 'detection/predictions.jsonl').read_text().splitlines()[0])
            self.assertFalse(row['source_file_available'])
            self.assertFalse(row['present'])
            checked = verifier.verify(out, execute_notebook=True)
            self.assertEqual(checked['notebook_code_cells_executed'], 10)
            self.assertEqual(checked['verified_reports'], 0)
            self.assertEqual(verifier.verify(out, execute_notebook=True)['notebook_code_cells_executed'], 10)
            with self.assertRaises(FileExistsError):
                exporter.export(root, 'test', out)


if __name__ == '__main__':
    unittest.main()
