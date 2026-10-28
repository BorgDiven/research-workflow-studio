"""Public showcase stays isolated, reproducible and explicit about synthetic data."""
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from rws.core import Store
from tools.seed_showcase import MAIN_PROJECT, PROJECTS, SAMPLES, seed


class ShowcaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / 'showcase.sqlite3'
        self.assets = self.root / 'assets'

    def tearDown(self):
        self.temp.cleanup()

    def snapshots(self):
        store = Store(self.db)
        try:
            return {pid: store.snapshot(pid) for pid in PROJECTS}
        finally:
            store.close()

    def test_replay_preserves_every_record_and_revision(self):
        first = seed(self.db, self.assets)
        before = self.snapshots()
        second = seed(self.db, self.assets)
        self.assertEqual(first, second)
        self.assertEqual(before, self.snapshots())
        self.assertTrue(all(p['demo'] for p in before[MAIN_PROJECT]['projects']))

    def test_refuses_a_database_containing_other_projects(self):
        store = Store(self.db)
        try:
            store.call('rws_project_create', {'requestId': 'ordinary-create', 'projectId': 'ordinary',
                                             'name': 'Unrelated project'})
            before = store.snapshot('ordinary')
            with self.assertRaisesRegex(ValueError, 'empty database'):
                seed(self.db, self.assets)
            self.assertEqual(before, store.snapshot('ordinary'))
            self.assertFalse(self.assets.exists())
        finally:
            store.close()

    def test_declared_purpose_exists_without_execution_and_does_not_move_sources(self):
        seed(self.db, self.assets)
        entries = self.snapshots()[MAIN_PROJECT]['records']
        by_id = {e['ref']['id']: e for e in entries}
        planned = by_id['H7']['record']['implementationLinks']
        self.assertEqual(planned[0]['targetRef'], by_id['SPEC-INFERENCE']['ref'])
        self.assertEqual(by_id['SPEC-INFERENCE']['record']['status'], 'draft')
        self.assertFalse(any(e['ref']['type'] == 'run' and
                             e['record'].get('experimentRef', {}).get('id') == 'E7'
                             for e in entries))
        self.assertEqual(by_id['A-CIRCLE-BASE']['record']['producerRef']['id'], 'R-BASE')
        self.assertEqual(by_id['R-BASE']['record']['experimentRef']['id'], 'E5')
        self.assertEqual(by_id['H2']['record']['implementationLinks'][0], {
            'targetRef': by_id['C0']['ref'], 'role': 'control',
            'note': '虚构研究用途；是否已有材料请查看实际使用与引用。'})

    def test_showcase_graph_materials_and_frozen_report_are_self_contained(self):
        result = seed(self.db, self.assets)
        snapshot = self.snapshots()[MAIN_PROJECT]
        by_type = {}
        for entry in snapshot['records']:
            by_type.setdefault(entry['ref']['type'], []).append(entry)
        research = by_type['research']
        self.assertEqual(len(research), 9)
        self.assertEqual({e['record']['stage'] for e in research}, {'idea', 'formal', 'ablation'})
        self.assertTrue(any(len(e['record']['parentRefs']) == 2 for e in research))
        stages = {e['ref']['id']: e['record']['stage'] for e in research}
        self.assertTrue(any(stages[p['id']] != e['record']['stage'] for e in research for p in e['record']['parentRefs']))

        codes = by_type['code']
        self.assertEqual({e['record']['kind'] for e in codes}, {'inference', 'evaluation', 'analysis', 'report'})
        self.assertTrue(all('commit' not in e['record'] and 'commit' not in e['record']['source'] for e in codes))
        for code in codes:
            source = code['record']['source']
            self.assertEqual(source['execution'], 'none')
            self.assertTrue((self.assets / source['uri'].removeprefix('/assets/showcase/')).is_file())

        final = [e['record'] for e in by_type['artifact'] if e['record'].get('semantic') == 'final-image']
        self.assertEqual(len(final), 8)
        self.assertEqual({a['sampleId'] for a in final}, set(SAMPLES))
        self.assertFalse(any(a['sampleId'] == 'hexagon' and a['producerRef']['id'] == 'R-MULTI' for a in final))
        for artifact in by_type['artifact']:
            uri = artifact['record'].get('uri')
            if uri:
                self.assertTrue(uri.startswith('/assets/showcase/'))
                path = self.assets / uri.removeprefix('/assets/showcase/')
                document = path.read_text(encoding='utf-8')
                ET.fromstring(document)
                self.assertIn('SYNTHETIC ILLUSTRATION', document)
                self.assertIn('NO MODEL EXECUTION', document)
                self.assertNotIn('<image', document)

        evaluations = [e['record'] for e in by_type['evaluation']]
        self.assertEqual(len(evaluations), 3)
        self.assertEqual(len({json.dumps(e['protocolRef'], sort_keys=True) for e in evaluations}), 1)
        self.assertEqual(len({json.dumps(e['codeRef'], sort_keys=True) for e in evaluations}), 1)
        report = by_type['report'][0]['record']
        self.assertEqual(report['comparisonRefs'], [result['comparison']])
        pinned = report['snapshot']['records']
        self.assertTrue(all(e['ref']['version'] >= 1 for e in pinned))
        self.assertTrue(any(e['ref']['type'] == 'analysis' for e in pinned))
        self.assertTrue(any(e['ref']['type'] == 'evaluation' for e in pinned))
        self.assertIn('虚构演示', report['markdown'])


if __name__ == '__main__':
    unittest.main()
