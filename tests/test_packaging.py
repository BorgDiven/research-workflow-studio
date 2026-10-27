"""Installed wheel assets follow their recorded location, not a global guess."""
from pathlib import Path, PurePosixPath
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
