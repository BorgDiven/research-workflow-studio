"""The design preview never turns another model's materials into evidence."""
import tempfile
import unittest
from pathlib import Path

from rws.core import Store
from tools.build_site import export_showcase
from tools.seed_showcase import MAIN_PROJECT, seed


class FoundationPreviewSeedTest(unittest.TestCase):
    def test_models_share_methods_but_not_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db, assets = root / 'preview.sqlite3', root / 'assets'
            metadata = seed(db, assets, preview_models=True)
            store = Store(db)
            try:
                before = store.snapshot(MAIN_PROJECT)
            finally:
                store.close()
            entries = before['records']
            by_id = {e['ref']['id']: e for e in entries}
            self.assertEqual(len([e for e in entries if e['ref']['type'] == 'code']), 7)
            self.assertEqual(len([e for e in entries if e['ref']['type'] == 'research']), 9)
            exp_a, exp_b = by_id['E5']['record'], by_id['E-MODEL-B']['record']
            self.assertEqual(exp_a['researchRef'], exp_b['researchRef'])
            self.assertEqual(exp_b['status'], 'planned')
            self.assertEqual(exp_b['config']['base_model'], '轮廓模型 B')
            self.assertEqual(exp_b['config']['model_version'], 'b1')
            self.assertEqual(exp_b['config']['comparison_code_refs'],
                             [by_id['C0']['ref'], by_id['C2']['ref']])
            for entry in entries:
                if entry['ref']['type'] in ('run', 'artifact'):
                    self.assertEqual(entry['record']['config']['base_model'], '轮廓模型 A')
                    self.assertEqual(entry['record']['config']['model_version'], 'a1')
                if entry['ref']['type'] in ('run', 'usage', 'evaluation'):
                    self.assertNotEqual(entry['record'].get('experimentRef'), by_id['E-MODEL-B']['ref'])
            report = by_id['REPORT-SHAPES']['record']
            self.assertIn('不能判断通用性', report['markdown'])
            self.assertFalse(any(e['ref']['id'] == 'E-MODEL-B' for e in report['snapshot']['records']))
            project = next(p for p in before['projects'] if p['id'] == MAIN_PROJECT)
            self.assertEqual(report['snapshot']['foundation']['fields']['foundations'],
                             project['versions'][-1]['fields']['foundations'])
            exported = export_showcase(db, metadata)
            contexts = [item['base'] for item in exported['contexts'].values()
                        if item['base']['projectId'] == MAIN_PROJECT]
            self.assertTrue(contexts)
            self.assertTrue(all('轮廓模型 A / a1' in item['foundation']['fields']['foundations'] for item in contexts))
            self.assertEqual(metadata, seed(db, assets, preview_models=True))
            with self.assertRaisesRegex(ValueError, 'separate database'):
                seed(db, assets)
            store = Store(db)
            try:
                self.assertEqual(before, store.snapshot(MAIN_PROJECT))
            finally:
                store.close()

    def test_public_showcase_stays_model_free_and_rejects_mode_switch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db, assets = root / 'public.sqlite3', root / 'assets'
            seed(db, assets)
            store = Store(db)
            try:
                before = store.snapshot(MAIN_PROJECT)
                self.assertFalse(any(e['ref']['id'] == 'E-MODEL-B' for e in before['records']))
                self.assertTrue(all('base_model' not in e['record'].get('config', {}) for e in before['records']))
                with self.assertRaisesRegex(ValueError, 'separate database'):
                    seed(db, assets, preview_models=True)
                self.assertEqual(before, store.snapshot(MAIN_PROJECT))
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
