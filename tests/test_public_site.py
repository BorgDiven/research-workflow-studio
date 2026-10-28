"""Public packaging uses fresh fictional inputs and works below a URL prefix."""
import json
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

from rws.core import Store
from tools.build_site import ROOT, build_site, context_key, export_showcase, relative_assets, selection_key
from tools.seed_showcase import MAIN_PROJECT, PROJECTS, seed


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        self.urls += [value for name, value in attrs if name in ('src', 'href') and value]


class PublicSiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temp.name) / 'public'
        cls.before = {path: path.read_bytes() for path in (ROOT / 'web').rglob('*') if path.is_file()}
        build_site(cls.output)
        cls.data = json.loads((cls.output / 'demo/showcase.json').read_text())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_build_does_not_modify_production_web(self):
        self.assertEqual(self.before, {path: path.read_bytes() for path in (ROOT / 'web').rglob('*') if path.is_file()})
        self.assertNotIn('demo-api', (ROOT / 'web/index.html').read_text())
        self.assertIn('15000', (ROOT / 'web/studio.js').read_text())
        self.assertNotIn('15000', (self.output / 'demo/studio.js').read_text())

    def test_package_contains_only_static_demo_data(self):
        self.assertEqual(set(self.data['snapshots']), set(PROJECTS))
        self.assertTrue(all(p['demo'] for p in self.data['home']['projects']))
        self.assertFalse((self.output / 'demo/live-api.js').exists())
        for path in self.output.rglob('*'):
            self.assertFalse(path.is_symlink())
            if path.is_file():
                self.assertNotIn(path.suffix, ('.sqlite3', '.sqlite', '.db', '.py'))
                if path.suffix in ('.js', '.json', '.html', '.css', '.md', '.txt'):
                    content = path.read_text()
                    forbidden_values = ['/Users/', '/home/wenbo', '.tail94b566.', '100.65.30.107', '/api/', '/materials/']
                    if path.is_relative_to(self.output / 'demo'):
                        forbidden_values += ['localhost', '127.0.0.1']
                    for forbidden in forbidden_values:
                        self.assertNotIn(forbidden, content, str(path.relative_to(self.output)))
        self.assertLess((self.output / 'demo/showcase.json').stat().st_size, 1_000_000)

    def test_nested_base_path_resolves_html_assets_and_frozen_image_links(self):
        prefix = '/research-workflow-studio/'
        origin = 'https://example.test'
        for path in self.output.rglob('*.html'):
            document = Links()
            document.feed(path.read_text())
            base = origin + prefix + path.relative_to(self.output).as_posix()
            for url in document.urls:
                resolved = urlparse(urljoin(base, url))
                if resolved.scheme not in ('http', 'https') or resolved.netloc != 'example.test':
                    continue
                self.assertTrue(resolved.path.startswith(prefix), (path, url))
                local = self.output / unquote(resolved.path.removeprefix(prefix))
                if resolved.path.endswith('/'):
                    local /= 'index.html'
                self.assertTrue(local.is_file(), (path, url))

        def walk(value):
            if isinstance(value, dict):
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
            elif isinstance(value, str):
                self.assertFalse(value.startswith('/assets/'))
                if value.startswith('assets/showcase/'):
                    self.assertTrue((self.output / 'demo' / value).is_file(), value)
        walk(self.data)
        records = self.data['snapshots'][MAIN_PROJECT]['records']
        final = [r for r in records if r['record'].get('semantic') == 'final-image']
        self.assertEqual(len(final), 8)
        self.assertFalse(any(r['record'].get('sampleId') == 'hexagon' and r['record']['producerRef']['id'] == 'R-MULTI' for r in final))
        report = next(r for r in records if r['ref']['type'] == 'report')
        self.assertTrue(report['record']['snapshot']['records'])

    def test_exported_context_is_exact_store_result_including_code_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'fresh.sqlite3'
            metadata = seed(db, Path(directory) / 'assets')
            data = export_showcase(db, metadata)
            store = Store(db)
            try:
                for record in data['snapshots'][MAIN_PROJECT]['records']:
                    if record['ref']['type'] != 'experiment':
                        continue
                    args = {'projectId': MAIN_PROJECT, 'researchRef': record['record']['researchRef'], 'experimentRef': record['ref']}
                    selected = [e['ref'] for e in data['snapshots'][MAIN_PROJECT]['records'] if e['ref']['id'] in ('C1', 'R-LOCAL')]
                    selected.sort(key=lambda ref: ref['type'] != 'code')
                    item = data['contexts'][context_key(args)]
                    variant = item['variants'][selection_key(selected)]
                    reconstructed = dict(item['base'], objectCount=variant['objectCount'], objectsTruncated=variant['objectsTruncated'], objects=[data['contextObjects'][i] for i in variant['objectIndexes']])
                    actual = store.call('rws_get_context', dict(args, selectionRefs=selected))['result']
                    self.assertEqual(reconstructed, relative_assets(actual))
                self.assertEqual(len(data['contexts']), 25)  # Project, research and experiment scopes including training.
            finally:
                store.close()

    def test_specification_only_selection_retains_exact_research_context(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'fresh.sqlite3'
            metadata = seed(db, Path(directory) / 'assets')
            data = export_showcase(db, metadata)
            records = data['snapshots'][MAIN_PROJECT]['records']
            experiment = next(e for e in records if e['ref']['type'] == 'experiment' and e['ref']['id'] == 'E7')
            spec = next(e for e in records if e['ref']['type'] == 'spec' and e['ref']['id'] == 'SPEC-INFERENCE')
            args = {'projectId': MAIN_PROJECT, 'researchRef': experiment['record']['researchRef'],
                    'experimentRef': experiment['ref']}
            selected = [spec['ref']]
            item = data['contexts'][context_key(args)]
            variant = item['variants'][selection_key(selected)]
            reconstructed = dict(item['base'], objectCount=variant['objectCount'],
                                 objectsTruncated=variant['objectsTruncated'],
                                 objects=[data['contextObjects'][i] for i in variant['objectIndexes']])
            store = Store(db)
            try:
                actual = store.call('rws_get_context', dict(args, selectionRefs=selected))['result']
                self.assertEqual(reconstructed, relative_assets(actual))
                self.assertTrue(any(e['ref'] == spec['ref'] for e in reconstructed['objects']))
            finally:
                store.close()

    def test_no_database_input_option_and_no_overwrite_of_unrelated_directory(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/build_site.py'), '--db', 'private.sqlite3'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / 'keep.txt'
            sentinel.write_text('unrelated')
            with self.assertRaisesRegex(ValueError, 'nonempty'):
                build_site(directory)
            self.assertEqual(sentinel.read_text(), 'unrelated')
        with self.assertRaisesRegex(ValueError, 'dedicated'):
            build_site(ROOT / 'web')

if __name__ == '__main__':
    unittest.main()
