"""Installed wheel assets follow their recorded location, not a global guess."""
from pathlib import Path, PurePosixPath
import json
import re
import tempfile
import unittest
from unittest.mock import Mock, patch

from rws.server import default_web_root, metadata


class PackagedResourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='rws-package-test-')
        self.root = Path(self.temporary.name).resolve()
        self.module = self.root / 'site-packages' / 'rws' / 'server.py'

    def tearDown(self):
        self.temporary.cleanup()

    def test_source_checkout_takes_precedence(self):
        web = self.root / 'site-packages' / 'web'
        web.mkdir(parents=True)
        (web / 'index.html').write_text('source frontend')
        with patch('rws.server.__file__', str(self.module)), patch('rws.server.metadata.distribution') as installed:
            self.assertEqual(default_web_root(), web)
            installed.assert_not_called()

    def test_data_file_mapping_covers_public_frontend_assets(self):
        root = Path(__file__).resolve().parents[1]
        config = (root / 'pyproject.toml').read_text(encoding='utf-8')
        section = config.split('[tool.setuptools.data-files]', 1)[1].split('\n[', 1)[0]
        mapped = set()
        for destination, patterns in re.findall(r'^"([^"]+)"\s*=\s*(\[.*\])$', section, re.M):
            for pattern in json.loads(patterns):
                for source in root.glob(pattern):
                    self.assertTrue(source.is_file(), 'Package data glob selected a directory: ' + str(source))
                    mapped.add((source.relative_to(root).as_posix(), destination + '/' + source.name))
        web = root / 'web'
        required = [p for p in web.iterdir() if p.suffix in ('.html', '.css', '.js')]
        for directory in ('assets', 'docs', 'examples'):
            required.extend(p for p in (web / directory).rglob('*') if p.is_file())
        for source in required:
            relative = source.relative_to(root).as_posix()
            self.assertIn((relative, 'share/research-workflow-studio/' + relative), mapped,
                          'Frontend asset missing from its served package location: ' + relative)

    def test_user_install_uses_exact_distribution_record(self):
        web = self.root / 'custom-user-base' / 'share' / 'research-workflow-studio' / 'web'
        web.mkdir(parents=True)
        index = web / 'index.html'
        index.write_text('installed frontend')
        resource = PurePosixPath('../../../share/research-workflow-studio/web/index.html')
        distribution = Mock(files=[PurePosixPath('rws/server.py'), resource])
        distribution.locate_file.return_value = index
        with patch('rws.server.__file__', str(self.module)), patch('rws.server.sys.prefix', str(self.root / 'different-python-prefix')), patch('rws.server.metadata.distribution', return_value=distribution) as locate:
            self.assertEqual(default_web_root(), web)
            locate.assert_called_once_with('research-workflow-studio')
            distribution.locate_file.assert_called_once_with(resource)

    def test_incomplete_source_directory_does_not_mask_installed_frontend(self):
        (self.root / 'site-packages' / 'web').mkdir(parents=True)
        web = self.root / 'installed-web'
        web.mkdir()
        (web / 'index.html').write_text('frontend')
        distribution = Mock(files=[PurePosixPath('../../../share/research-workflow-studio/web/index.html')])
        distribution.locate_file.return_value = web / 'index.html'
        with patch('rws.server.__file__', str(self.module)), patch('rws.server.metadata.distribution', return_value=distribution):
            self.assertEqual(default_web_root(), web)

    def test_missing_metadata_keeps_prefix_fallback(self):
        prefix = self.root / 'python-prefix'
        with patch('rws.server.__file__', str(self.module)), patch('rws.server.sys.prefix', str(prefix)), patch('rws.server.metadata.distribution', side_effect=metadata.PackageNotFoundError):
            self.assertEqual(default_web_root(), prefix / 'share' / 'research-workflow-studio' / 'web')


if __name__ == '__main__':
    unittest.main()
