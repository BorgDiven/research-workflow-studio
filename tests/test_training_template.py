import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.check_block import check_block, invoke
from tools.scaffold import scaffold


class TrainingTemplateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.block = scaffold('training', self.root / 'training')
        self.request = json.loads((self.block / 'request.json').read_text())

    def tearDown(self):
        self.temp.cleanup()

    def test_training_contract_and_independent_case_batches(self):
        checked = check_block(self.block, execute=True)
        self.assertEqual(checked['status'], 'passed', checked)
        self.assertEqual(checked['kind'], 'training')
        output = invoke(self.block / 'block.py', 'run', self.request, 10)['output']
        losses = [a for a in output['artifacts'] if a['semantic'] == 'training-loss']
        self.assertEqual(losses[0]['content']['points'], [[0, 4.0], [1, 1.0], [2, .25]])
        checkpoint = next(a for a in output['artifacts'] if a['sampleId'] == 'slope' and a['semantic'] == 'model-checkpoint')
        self.assertEqual((checkpoint['jsonDocument']['weight'], checkpoint['jsonDocument']['bias']), (1.5, 0))

    def test_cli_materializes_checkpoint_log_without_overwriting(self):
        output = self.root / 'results.json'
        argv = [sys.executable, str(self.block / 'block.py'), '--input', str(self.block / 'request.json'), '--output', str(output)]
        subprocess.run(argv, check=True, capture_output=True)
        data = json.loads(output.read_text())
        for item in data['artifacts']:
            if item['kind'] != 'attachment':
                continue
            path = self.root / item['content']['uri']
            self.assertTrue(path.is_file())
            self.assertEqual(item['content']['availability'], 'available')
            if item['semantic'] == 'model-checkpoint':
                self.assertEqual(json.loads(path.read_text()), item['jsonDocument'])
            else:
                self.assertEqual(len(path.read_text().splitlines()), 3)
                point = json.loads(path.read_text().splitlines()[0])
                self.assertEqual(point['metricId'], 'loss')
                self.assertEqual(point['sampleId'], item['sampleId'])
                self.assertIn('eventId', point)
        self.assertNotEqual(subprocess.run(argv, capture_output=True).returncode, 0)

    def test_case_names_do_not_change_algorithm_and_invalid_training_rejects(self):
        request = dict(self.request, cases=[dict(self.request['cases'][0], sampleId='unseen-dataset')])
        output = invoke(self.block / 'block.py', 'run', request, 10)['output']
        self.assertTrue(all(item['sampleId'] == 'unseen-dataset' for item in output['artifacts']))
        for settings in ({'epochs': True}, {'learningRate': 0}, {'epochs': 10001}):
            with self.assertRaises(ValueError):
                invoke(self.block / 'block.py', 'run', dict(request, config=settings), 10)


if __name__ == '__main__':
    unittest.main()
