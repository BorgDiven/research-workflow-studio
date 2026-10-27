import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.check_block import check_block, invoke
from tools.scaffold import KINDS, scaffold
from examples.run_pipeline import run_pipeline


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='rws-template-test-')
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def block(self, kind='inference'):
        return scaffold(kind, self.root / kind)

    def call(self, folder, request):
        return invoke(folder / 'block.py', 'run', request, 10)['output']

    def request(self, folder):
        return json.loads((folder / 'request.json').read_text())

    def test_all_roles_execute_two_cases_and_batch(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                block = self.block(kind)
                evidence = check_block(block, execute=True)
                self.assertEqual(evidence['status'], 'passed', evidence)
                self.assertEqual(len(evidence['executions']), 3)
                self.assertTrue(all(row['status'] == 'passed' for row in evidence['checkEvidence']))
                self.assertFalse(evidence['registrationReady'])
                self.assertIsNone(evidence['identity']['commit'])

    def test_scaffold_refuses_overwrite_and_can_customize_title(self):
        folder = scaffold('analysis', self.root / 'method', title='Reusable signal statistics')
        self.assertEqual(json.loads((folder / 'contract.json').read_text())['spec']['title'], 'Reusable signal statistics')
        sentinel = folder / 'do-not-touch.txt'
        sentinel.write_text('existing work')
        with self.assertRaises(FileExistsError):
            scaffold('inference', folder)
        self.assertEqual(sentinel.read_text(), 'existing work')

    def test_static_check_never_imports_or_executes_block(self):
        folder = self.block()
        (folder / 'block.py').write_text('raise RuntimeError("must never import")\n')
        evidence = check_block(folder)
        self.assertEqual(evidence['status'], 'static-only')
        self.assertEqual(evidence['executions'], [])
        self.assertFalse(evidence['registrationReady'])
        self.assertTrue(all(row['status'] == 'skipped' for row in evidence['checkEvidence'] if row['checkId'] != 'contract-valid'))

    def test_checker_detects_mutating_input(self):
        folder = self.block()
        source = (folder / 'block.py').read_text()
        source = source.replace('selected = cases(request)', "selected = cases(request)\n    request['unexpected-mutation'] = True")
        (folder / 'block.py').write_text(source)
        evidence = check_block(folder, execute=True)
        self.assertEqual(evidence['status'], 'failed')
        self.assertEqual(next(row for row in evidence['checkEvidence'] if row['checkId'] == 'input-immutability')['status'], 'failed')

    def test_checker_detects_case_dependent_batch_algorithm(self):
        folder = self.block()
        source = (folder / 'block.py').read_text()
        source = source.replace("final = [settings['scale'] * v + settings['offset'] for v in original]", "final = [settings['scale'] * v + settings['offset'] + (1 if len(selected) > 1 else 0) for v in original]")
        (folder / 'block.py').write_text(source)
        evidence = check_block(folder, execute=True)
        self.assertEqual(evidence['status'], 'failed')
        self.assertEqual(next(row for row in evidence['checkEvidence'] if row['checkId'] == 'batch-equivalence')['status'], 'failed')

    def test_checker_rejects_escaped_entrypoint_and_duplicate_cases(self):
        folder = self.block()
        contract = json.loads((folder / 'contract.json').read_text())
        contract['entrypoint'] = '../outside.py:run'
        (self.root / 'outside.py').write_text('def run(request): return {}')
        (folder / 'contract.json').write_text(json.dumps(contract))
        evidence = check_block(folder)
        self.assertEqual(evidence['status'], 'failed')
        self.assertIn('inside the block directory', evidence['error'])
        contract['entrypoint'] = 'block.py:run'
        (folder / 'contract.json').write_text(json.dumps(contract))
        fixture = json.loads((folder / 'fixtures.json').read_text())
        fixture['request']['cases'][1]['sampleId'] = fixture['request']['cases'][0]['sampleId']
        (folder / 'fixtures.json').write_text(json.dumps(fixture))
        self.assertEqual(check_block(folder)['status'], 'failed')

    def test_method_accepts_new_case_names_lengths_and_configs(self):
        folder = self.block()
        request = {'requestId': 'custom-execution', 'datasetId': 'new-dataset',
                   'cases': [{'sampleId': 'unseen-case', 'task': 'linear-transform', 'input': {'values': [2, 4, 6, 8]}}],
                   'config': {'scale': 0.5, 'offset': -1, 'diagnosticSteps': 0}, 'inputs': []}
        output = self.call(folder, request)
        self.assertEqual(len(output['artifacts']), 1)
        item = output['artifacts'][0]
        self.assertEqual(item['content']['points'], [[0, 0], [1, 1], [2, 2], [3, 3]])
        self.assertEqual(item['caseIdentity'], {'datasetId': 'new-dataset', 'sampleId': 'unseen-case', 'task': 'linear-transform'})
        self.assertEqual(item['config'], request['config'])

    def test_evaluation_keeps_missing_samples_and_explicit_protocol(self):
        folder = self.block('evaluation')
        request = self.request(folder)
        request['cases'][1].pop('referenceValues')
        output = self.call(folder, request)
        self.assertEqual(output['summary'], {'selected': 2, 'completed': 1, 'missing': 1})
        self.assertEqual(len(output['artifacts']), 1)
        self.assertEqual(output['sampleStatuses'][1]['status'], 'missing')
        self.assertEqual(output['artifacts'][0]['content']['value'], 1)
        self.assertEqual(output['artifacts'][0]['protocol']['preprocessing'], 'none')
        self.assertEqual(output['artifacts'][0]['inputIds'], [request['inputs'][0]['id']])

    def test_analysis_rejects_ambiguous_input_reuse(self):
        folder = self.block('analysis')
        request = self.request(folder)
        duplicate = copy.deepcopy(request['inputs'][0])
        duplicate['id'] = 'other-invocation/same-case/final-output'
        request['inputs'].append(duplicate)
        with self.assertRaisesRegex(ValueError, 'Choose one exact input artifact'):
            self.call(folder, request)

    def test_evaluation_rejects_wrong_dataset_and_reference_order(self):
        folder = self.block('evaluation')
        request = self.request(folder)
        request['inputs'][0]['caseIdentity']['datasetId'] = 'different-dataset'
        with self.assertRaisesRegex(ValueError, 'case identity'):
            self.call(folder, request)
        request = self.request(folder)
        request['inputs'][0]['content']['points'].reverse()
        with self.assertRaisesRegex(ValueError, 'reference positions'):
            self.call(folder, request)

    def test_report_materializes_exact_existing_evidence(self):
        folder = self.block('report')
        request = self.request(folder)
        # A pre-existing score must be copied, not recomputed as a new evaluation.
        request['inputs'][0].update(kind='metric', semantic='evaluation-metric')
        request['inputs'][0]['content'] = {'kind': 'metric', 'name': 'supplied-score', 'value': 1234.5}
        source = self.root / 'report-request.json'
        source.write_text(json.dumps(request))
        output_path = self.root / 'report-output.json'
        command = [sys.executable, str(folder / 'block.py'), '--input', str(source), '--output', str(output_path)]
        subprocess.run(command, check=True, capture_output=True)
        output = json.loads(output_path.read_text())
        self.assertEqual(output['artifacts'][0]['evidenceSnapshot'][0], request['inputs'][0])
        self.assertIn('1234.5', output['artifacts'][0]['markdown'])
        document = self.root / output['artifacts'][0]['content']['uri']
        self.assertEqual(document.read_text(), output['artifacts'][0]['markdown'])
        self.assertEqual(output['artifacts'][0]['content']['availability'], 'available')
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)

    def test_pipeline_reuses_saved_sources_and_creates_reports(self):
        folder = self.root / 'pipeline'
        manifest = run_pipeline(folder)
        self.assertEqual(len(manifest['caseIds']), 2)
        outputs = {kind: json.loads((folder / filename).read_text()) for kind, filename in manifest['outputs'].items()}
        final_ids = {a['id'] for a in outputs['inference']['artifacts'] if a['semantic'] == 'final-output'}
        for kind in ('analysis', 'evaluation'):
            self.assertEqual({a['inputIds'][0] for a in outputs[kind]['artifacts']}, final_ids)
        for report in outputs['report']['artifacts']:
            self.assertEqual(len(report['inputIds']), 3)
            self.assertTrue((folder / report['content']['uri']).is_file())
        with self.assertRaises(FileExistsError):
            run_pipeline(folder)


if __name__ == '__main__':
    unittest.main()
