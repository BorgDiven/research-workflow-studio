"""Managed materials are readable without exposing source folders or buffering PDFs."""
import tempfile
import threading
import http.client
import unittest
from pathlib import Path
from rws.server import create_server


class ManagedMaterials(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.materials = self.root / 'materials'
        self.materials.mkdir()
        (self.materials / 'figure.png').write_bytes(b'0123456789')
        (self.materials / 'source.html').write_text('<script>danger()</script>')
        (self.root / 'outside.txt').write_text('not a material')
        (self.materials / 'escape.txt').symlink_to(self.root / 'outside.txt')
        self.server = create_server(self.root / 'data.sqlite3', port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def read(self, path, method='GET', headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1])
        conn.request(method, path, headers=headers or {})
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

    def test_media_range_head_and_invalid_ranges(self):
        status, headers, body = self.read('/materials/figure.png', headers={'Range':'bytes=2-5'})
        self.assertEqual((status, body), (206, b'2345'))
        self.assertEqual(headers['Content-Range'], 'bytes 2-5/10')
        self.assertEqual(self.read('/materials/figure.png', headers={'Range':'bytes=-3'})[2], b'789')
        self.assertEqual(self.read('/materials/figure.png', 'HEAD')[2], b'')
        for value in ['bytes=100-', 'bytes=5-2', 'bytes=0-1,4-5', 'bytes=-0']:
            self.assertEqual(self.read('/materials/figure.png', headers={'Range':value})[0], 416)

    def test_no_source_folder_escape_or_active_html(self):
        for path in ['/materials/../outside.txt','/materials/%2e%2e/outside.txt',
                     '/materials/escape.txt','/materials/.secret','/materials/%2fetc/passwd']:
            self.assertEqual(self.read(path)[0], 404)
        status, headers, body = self.read('/materials/source.html')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Disposition'], 'attachment')
        self.assertEqual(headers['Content-Type'], 'application/octet-stream')
        self.assertIn("default-src 'none'", headers['Content-Security-Policy'])
        self.assertEqual(self.read('/materials/figure.png', headers={'Origin':'https://untrusted.example'})[0], 403)
