"""Reading renditions preserve originals and only discard their own cache files."""
import concurrent.futures
import contextlib
import http.client
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from rws.storage import MaterialStorage, PreviewError, managed_relative
from rws.server import create_server
from rws.pdf_reading import pdf_converter_available

try:
    from PIL import Image
except ImportError:
    Image = None

APP = Path(__file__).resolve().parents[1]


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.originals = self.root / 'originals'
        self.originals.mkdir()
        self.cache = self.root / 'cache'
        self.storage = MaterialStorage(self.root / 'data.sqlite3', self.originals, self.cache, 1)

    def tearDown(self):
        self.tmp.cleanup()

    def source(self, name='one.png', data=b'original unchanged'):
        (self.originals / name).write_bytes(data)
        return '/materials/' + name

    @staticmethod
    def fake_convert(source, destination):
        destination.write_bytes(b'reading:' + source.read_bytes())
        return 1, 1

    @contextlib.contextmanager
    def converter(self, function=None):
        with patch('rws.storage._pillow', return_value=(None, None)), patch.object(
                MaterialStorage, '_convert', side_effect=function or self.fake_convert) as convert:
            yield convert

    def preview(self, uri):
        stream, info = self.storage.preview(uri)
        with stream:
            return stream.read(), info

    def test_managed_uri_validation_and_symlink_escape(self):
        for value in ['http://example/x.png', 'file:///etc/passwd', '/assets/a.png',
                      '/materials/../outside.png', '/materials/%2e%2e/outside.png',
                      '/materials//etc/passwd', '/materials/%2fetc/passwd',
                      '/materials/a\\b', '/materials/.secret', '/materials/%00x',
                      '/materials/a.png?q=1', '/materials/a.png#section',
                      '/materials/a/%2e/b', '//evil/materials/x', '/materials/a\nx']:
            with self.subTest(value=value), self.assertRaises(PreviewError):
                managed_relative(value)
        self.assertEqual(managed_relative('/materials/a%20b.png'), 'a b.png')
        outside = self.root / 'outside.png'
        outside.write_bytes(b'private')
        (self.originals / 'escape.png').symlink_to(outside)
        with self.assertRaises(PreviewError):
            self.storage.preview('/materials/escape.png')
        # Broken symlinks escaping the root are rejected before offline cache lookup.
        outside.unlink()
        with self.assertRaises(PreviewError):
            self.storage.preview('/materials/escape.png')

    def test_roots_cannot_overlap_including_aliases(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.originals, target_is_directory=True)
        for cache in [self.originals, self.originals / 'cache', self.root, alias]:
            with self.subTest(cache=cache), self.assertRaises(ValueError):
                MaterialStorage(self.root / 'db', self.originals, cache)
        for limit in [0, -1, True, 1.5, 65537]:
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                MaterialStorage(self.root / 'db', self.originals, self.cache, limit)

    def test_cached_exact_uri_survives_offline_root_and_revalidates_after_return(self):
        uri = self.source()
        with self.converter() as convert:
            first, first_info = self.preview(uri)
            self.assertTrue(first_info['originalAvailable'])
            moved = self.root / 'unmounted'
            self.originals.rename(moved)
            with patch('rws.storage._pillow', side_effect=PreviewError('missing converter')):
                cached, info = self.preview(uri)
                self.assertEqual(cached, first)
                self.assertFalse(info['originalAvailable'])
            self.assertFalse(self.originals.exists())
            moved.rename(self.originals)
            self.source(data=b'changed original bytes')
            refreshed, _ = self.preview(uri)
            self.assertNotEqual(refreshed, first)
            self.assertEqual(convert.call_count, 2)
            self.assertEqual((self.originals / 'one.png').read_bytes(), b'changed original bytes')

    def test_no_original_fallback_when_converter_missing_or_source_removed(self):
        uri = self.source()
        with patch('rws.storage._pillow', side_effect=PreviewError('missing converter')):
            with self.assertRaisesRegex(PreviewError, 'missing converter'):
                self.storage.preview(uri)
        self.assertEqual((self.originals / 'one.png').read_bytes(), b'original unchanged')
        with self.converter():
            self.preview(uri)
            (self.originals / 'one.png').unlink()
            with self.assertRaises(PreviewError):
                self.storage.preview(uri)

    def test_changed_originals_root_invalidates_cached_bytes_despite_equal_stat(self):
        uri = self.source(data=b'root A pixels')
        other = self.root / 'other-originals'
        other.mkdir()
        (other / 'one.png').write_bytes(b'root B pixels')
        source_stat = (self.originals / 'one.png').stat()
        os.utime(other / 'one.png', ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
        alternate = MaterialStorage(self.root / 'db', other, self.cache, 1)
        with self.converter() as convert:
            first, _ = self.preview(uri)
            stream, _ = alternate.preview(uri)
            with stream:
                second = stream.read()
        self.assertEqual(first, b'reading:root A pixels')
        self.assertEqual(second, b'reading:root B pixels')
        self.assertEqual(convert.call_count, 2)
        self.assertEqual((self.originals / 'one.png').read_bytes(), b'root A pixels')
        self.assertEqual((other / 'one.png').read_bytes(), b'root B pixels')

    def test_offline_other_root_and_unbound_cache_cannot_reuse_previous_root(self):
        uri = self.source()
        with self.converter():
            self.preview(uri)
        alternate = MaterialStorage(self.root / 'db', self.root / 'offline-other-root', self.cache, 1)
        with self.assertRaises(PreviewError):
            alternate.preview(uri)
        self.assertEqual(alternate.status()['previewCount'], 0)
        with self.converter():
            self.preview(uri)
        # Legacy/unbound entries must not be adopted merely because their URI
        # matches. The ordinary offline path remains covered separately.
        with self.storage._exclusive() as conn:
            conn.execute("DELETE FROM cache_config WHERE key='originals_root'")
        self.originals.rename(self.root / 'unmounted')
        with self.assertRaises(PreviewError):
            self.preview(uri)
        self.assertEqual(self.storage.status()['previewCount'], 0)

    def test_eviction_leaves_originals_and_unknown_cache_files_untouched(self):
        one, two = self.source('one.png'), self.source('two.png')
        def large(source, destination):
            destination.write_bytes(b'p' * 650000)
            return 1, 1
        with self.converter(large):
            self.preview(one)
            self.cache.joinpath('user-kept-note.txt').write_bytes(b'not cache-owned')
            self.preview(two)
        stats = self.storage.status(prune=True)
        self.assertLessEqual(stats['previewBytes'], 1024 * 1024)
        self.assertEqual(stats['previewCount'], 1)
        self.assertEqual((self.cache / 'user-kept-note.txt').read_bytes(), b'not cache-owned')
        for name in ('one.png', 'two.png'):
            self.assertEqual((self.originals / name).read_bytes(), b'original unchanged')

    def test_failed_and_interrupted_encoding_reclaims_only_journaled_files(self):
        uri = self.source()
        def fail(source, destination):
            destination.write_bytes(b'partial reading')
            raise ValueError('incomplete converter')
        with self.converter(fail), self.assertRaises(PreviewError):
            self.storage.preview(uri)
        self.assertEqual(self.storage.status()['previewCount'], 0)
        self.assertFalse(list(self.cache.glob('*.tmp')))
        filename = 'rws-preview-' + '1' * 32 + '.webp'
        with self.storage._exclusive() as conn:
            conn.execute('INSERT INTO previews VALUES (?,?,?,?,?,?,?,?,?,0)',
                         ('pending.png', 'profile', filename, 5, 0, 0, 0, 0, 0))
        (self.cache / filename).write_bytes(b'interrupted output')
        (self.cache / filename).with_suffix('.tmp').write_bytes(b'interrupted temporary')
        self.storage.status(prune=True)
        self.assertFalse((self.cache / filename).exists())
        self.assertFalse((self.cache / filename).with_suffix('.tmp').exists())
        self.assertEqual((self.originals / 'one.png').read_bytes(), b'original unchanged')

    def test_parallel_requests_encode_once_and_active_stream_survives_eviction(self):
        uri = self.source()
        with self.converter() as convert:
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                values = list(pool.map(lambda _: self.preview(uri)[0], range(12)))
            self.assertEqual(len(set(values)), 1)
            self.assertEqual(convert.call_count, 1)
        stream, _ = self.storage.preview(uri)
        with self.storage._exclusive() as conn:
            self.storage._remove(conn, conn.execute('SELECT * FROM previews').fetchone())
        with stream:
            self.assertEqual(stream.read(), values[0])

    def test_cached_hit_does_not_walk_all_cached_files(self):
        uri = self.source()
        with self.converter():
            expected, _ = self.preview(uri)
        # These indexed renditions have been removed externally. Ordinary reads
        # must not stat all of them; an explicit prune reconciles their absence.
        with self.storage._exclusive() as conn:
            conn.executemany('INSERT INTO previews VALUES (?,?,?,?,?,?,?,?,?,1)',
                             [('missing-%s.png' % n, 'profile',
                               'rws-preview-%032x.webp' % n, 1, 0, 1, 1, 1, 0)
                              for n in range(800)])
        with patch.object(self.storage, '_cache_path', wraps=self.storage._cache_path) as paths:
            actual, _ = self.preview(uri)
        self.assertEqual(actual, expected)
        self.assertLessEqual(paths.call_count, 3)
        self.assertEqual(self.storage.status()['previewCount'], 801)
        self.assertEqual(self.storage.status(prune=True)['previewCount'], 1)

    def test_cache_index_symlink_is_not_followed(self):
        self.cache.mkdir()
        private = self.root / 'private.sqlite3'
        private.write_bytes(b'private untouched')
        (self.cache / 'preview-index.sqlite3').symlink_to(private)
        with self.assertRaises(PreviewError):
            self.storage.status()
        self.assertEqual(private.read_bytes(), b'private untouched')

    def test_cli_status_prune_and_explicit_warm(self):
        base = [sys.executable, '-m', 'rws', 'preview-cache', '--db', str(self.root / 'db'),
                '--materials-root', str(self.originals), '--preview-cache-root', str(self.cache)]
        status = subprocess.run(base + ['status'], cwd=APP, text=True, capture_output=True)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(json.loads(status.stdout)['previewCount'], 0)
        result = subprocess.run(base + ['warm', '--uri', 'file:///private'], cwd=APP, text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['failures'][0]['code'], 'not_found')
        self.assertNotIn(str(self.originals), status.stdout)
        for arguments in [['warm'], ['status', '--uri', '/materials/a.png'], ['prune', '--preview-cache-mb', '0']]:
            result = subprocess.run(base + arguments, cwd=APP, text=True, capture_output=True)
            self.assertEqual(result.returncode, 2)

    @unittest.skipUnless(Image, 'Optional Pillow converter is not installed')
    def test_real_preview_limits_dimensions_preserves_alpha_and_original_bytes(self):
        source = self.originals / 'alpha.png'
        Image.new('RGBA', (2560, 1440), (20, 30, 40, 128)).save(source, compress_level=0)
        before = source.read_bytes()
        reading, info = self.preview('/materials/alpha.png')
        self.assertLess(len(reading), len(before) // 10)
        self.assertEqual((info['width'], info['height']), (1280, 720))
        with Image.open(io.BytesIO(reading)) as decoded:
            self.assertEqual(decoded.mode, 'RGBA')
            self.assertEqual(decoded.getpixel((0, 0))[3], 128)
        self.assertEqual(source.read_bytes(), before)
        Image.new('RGB', (32, 16)).save(self.originals / 'tiny.png')
        _, info = self.preview('/materials/tiny.png')
        self.assertEqual((info['width'], info['height']), (32, 16))

    @unittest.skipUnless(Image, 'Optional Pillow converter is not installed')
    def test_scientific_integer_float_images_require_explicit_display_transform(self):
        import array
        gradient = Image.frombytes('I;16', (256, 8), array.array('H', [value * 257 for value in range(256)] * 8).tobytes())
        gradient.save(self.originals / 'uint16.png')
        floating = Image.new('F', (8, 8), 0.25)
        floating.save(self.originals / 'float.tiff')
        for filename in ['uint16.png', 'float.tiff']:
            original = (self.originals / filename).read_bytes()
            with self.subTest(filename=filename), self.assertRaisesRegex(PreviewError, '显示范围'):
                self.preview('/materials/' + filename)
            self.assertEqual((self.originals / filename).read_bytes(), original)
        self.assertEqual(self.storage.status()['previewCount'], 0)

    @unittest.skipUnless(Image, 'Optional Pillow converter is not installed')
    def test_animated_images_are_not_silently_flattened(self):
        Image.new('RGB', (20, 20), 'red').save(self.originals / 'animation.gif', save_all=True,
                                             append_images=[Image.new('RGB', (20, 20), 'blue')])
        with self.assertRaisesRegex(PreviewError, '动态图'):
            self.preview('/materials/animation.gif')


class StorageTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.originals = self.root / 'external' / 'originals'
        self.originals.mkdir(parents=True)
        self.server = create_server(self.root / 'local' / 'studio.sqlite3', port=0,
                                    materials_root=self.originals,
                                    preview_cache_root=self.root / 'local' / 'readings')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def read(self, path, method='GET', headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=10)
        conn.request(method, path, headers=headers or {})
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

    def test_legacy_uri_custom_root_and_explicit_download(self):
        (self.originals / 'test.png').write_bytes(b'0123456789')
        status, headers, body = self.read('/materials/test.png?download=1', headers={'Range': 'bytes=2-4'})
        self.assertEqual((status, body), (206, b'234'))
        self.assertEqual(headers['Content-Disposition'], 'attachment')
        self.assertEqual(self.read('/materials/test.png?download=other')[0], 400)
        status, _, body = self.read('/api/storage')
        self.assertEqual(status, 200)
        self.assertNotIn(str(self.originals).encode(), body)
        self.assertNotIn(str(self.root).encode(), body)

    def test_invalid_preview_requests_never_serve_original(self):
        (self.originals / 'test.png').write_bytes(b'original')
        for query in ['', '?uri=', '?uri=a&uri=b', '?uri=%2Fmaterials%2Ftest.png&extra=x']:
            self.assertIn(self.read('/api/preview' + query)[0], (400, 404))
        with patch('rws.storage._pillow', side_effect=PreviewError('missing converter')):
            status, _, body = self.read('/api/preview?uri=%2Fmaterials%2Ftest.png')
            self.assertEqual(status, 503)
            self.assertEqual(json.loads(body)['error']['code'], 'preview_unavailable')
        self.assertEqual(self.read('/api/preview?uri=' + quote('https://example/private'))[0], 404)
        self.assertEqual(self.read('/api/preview?uri=%2Fmaterials%2Ftest.png',
                                   headers={'Origin': 'https://untrusted.example'})[0], 403)

    @unittest.skipUnless(Image, 'Optional Pillow converter is not installed')
    def test_real_http_preview_bytes_range_and_offline_read(self):
        path = self.originals / 'large.png'
        Image.new('RGB', (2560, 1440), (10, 20, 30)).save(path, compress_level=0)
        original = path.read_bytes()
        uri = '/api/preview?uri=%2Fmaterials%2Flarge.png'
        status, headers, body = self.read(uri)
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'image/webp')
        self.assertEqual(headers['X-RWS-Rendition'], 'reading')
        self.assertLess(len(body), len(original) // 10)
        self.assertEqual(self.read(uri, 'HEAD')[2], b'')
        self.assertEqual(self.read(uri, headers={'Range': 'bytes=2-8'})[2], body[2:9])
        self.originals.rename(self.root / 'unmounted')
        status, headers, cached = self.read(uri)
        self.assertEqual((status, cached), (200, body))
        self.assertEqual(headers['X-RWS-Original-Available'], 'false')
        self.assertEqual(self.read('/materials/large.png')[0], 404)
        self.assertEqual((self.root / 'unmounted' / 'large.png').read_bytes(), original)


    @unittest.skipUnless(pdf_converter_available(), 'Optional PDF converter is not installed')
    def test_pdf_reading_route_cache_range_and_missing_converter(self):
        import random
        from pypdf import PdfWriter, PdfReader
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject
        source = self.originals / 'report.pdf'
        writer = PdfWriter()
        page = writer.add_blank_page(width=600, height=400)
        image = DecodedStreamObject()
        image.set_data(random.Random(4).randbytes(600 * 400 * 3))
        image.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'),
                      NameObject('/Width'): NumberObject(600), NameObject('/Height'): NumberObject(400),
                      NameObject('/ColorSpace'): NameObject('/DeviceRGB'), NameObject('/BitsPerComponent'): NumberObject(8)})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): DictionaryObject({NameObject('/Im0'): writer._add_object(image)})})
        content = DecodedStreamObject()
        content.set_data(b'q 600 0 0 400 0 0 cm /Im0 Do Q')
        page[NameObject('/Contents')] = writer._add_object(content)
        with source.open('wb') as stream:
            writer.write(stream)
        original = source.read_bytes()
        uri = '/api/preview?uri=%2Fmaterials%2Freport.pdf'
        with patch('rws.pdf_reading.pdf_converter_available', return_value=False):
            self.assertEqual(self.read(uri)[0], 503)
        status, headers, reading = self.read(uri)
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'application/pdf')
        self.assertLess(len(reading), len(original))
        self.assertEqual(len(PdfReader(io.BytesIO(reading)).pages), 1)
        self.assertEqual(self.read(uri, headers={'Range': 'bytes=0-4'})[2], b'%PDF-')
        with patch('rws.pdf_reading.pdf_converter_available', return_value=False):
            self.assertEqual(self.read(uri)[2], reading)
        self.assertEqual(source.read_bytes(), original)
        self.originals.rename(self.root / 'unmounted')
        self.assertEqual(self.read(uri)[2], reading)

if __name__ == '__main__':
    unittest.main()
