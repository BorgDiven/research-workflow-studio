"""Private proxy boundary tests using only temporary databases and loopback HTTP."""

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from rws.__main__ import main
from rws.mcp import MCPConnection
from rws.origin import normalize_web_origin
from rws.server import create_server


PUBLIC_ORIGIN = "https://studio.example-tailnet.ts.net:8443"
PUBLIC_HOST = "studio.example-tailnet.ts.net:8443"
TAILSCALE_USER = "researcher@example.test"


class OriginTests(unittest.TestCase):
    def test_valid_origins_and_canonical_default_ports(self):
        for value, expected in (
                ("http://127.0.0.1:8831/", "http://127.0.0.1:8831"),
                ("http://localhost:80", "http://localhost"),
                (PUBLIC_ORIGIN + "/", PUBLIC_ORIGIN),
                ("https://studio.example-tailnet.ts.net:443", "https://studio.example-tailnet.ts.net")):
            self.assertEqual(normalize_web_origin(value), expected)

    def test_invalid_origins_are_rejected_by_shared_mcp_validation(self):
        invalid = (None, "", " " + PUBLIC_ORIGIN, PUBLIC_ORIGIN + "\n", PUBLIC_ORIGIN + "/folder",
            PUBLIC_ORIGIN + "?", PUBLIC_ORIGIN + "#", PUBLIC_ORIGIN + "?x=1", PUBLIC_ORIGIN + "#fragment",
            "https://user@studio.example-tailnet.ts.net", "https://user:pass@studio.example-tailnet.ts.net",
            "https://@studio.example-tailnet.ts.net", "http://studio.example-tailnet.ts.net",
            "https://example.test", "https://studio.example-tailnet.ts.net.attacker.test",
            "https://-bad.example-tailnet.ts.net", "https://studio..ts.net", "https://studio.ts.net.",
            "http://127.0.0.1:", "http://127.0.0.1:abc", "http://127.0.0.1:0", "http://127.0.0.1:65536",
            "https://studio.example-tailnet.ts.net:08443", "https://studio.example-tailnet.ts.net:65536")
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                MCPConnection(None, web_url=value)

    def test_proxy_configuration_requires_identity_and_https(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "not-created.sqlite3"
            for arguments in ({"public_origin": PUBLIC_ORIGIN}, {"tailscale_user": TAILSCALE_USER},
                    {"public_origin": PUBLIC_ORIGIN, "tailscale_user": ""},
                    {"public_origin": PUBLIC_ORIGIN, "tailscale_user": "a\nb"},
                    {"public_origin": "http://localhost:8831", "tailscale_user": TAILSCALE_USER}):
                with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                    create_server(db, port=0, **arguments)
            self.assertFalse(db.exists())

    def test_cli_requires_both_proxy_arguments(self):
        with patch("sys.stderr"), self.assertRaises(SystemExit) as error:
            main(["serve", "--db", "/unused.sqlite3", "--public-origin", PUBLIC_ORIGIN])
        self.assertEqual(error.exception.code, 2)


class TailscaleTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "test.sqlite3"
        self.server = create_server(self.db, port=0, public_origin=PUBLIC_ORIGIN, tailscale_user=TAILSCALE_USER)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.local_host = "127.0.0.1:%s" % self.port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

    def request(self, path="/api/health", headers=None, payload=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest("POST" if payload else "GET", path, skip_host=True)
        for name, value in headers or [("Host", self.local_host)]:
            conn.putheader(name, value)
        data = json.dumps(payload).encode() if payload else None
        if data:
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", str(len(data)))
        conn.endheaders(data)
        response = conn.getresponse()
        result = (response.status, json.loads(response.read()), dict(response.getheaders()))
        conn.close()
        return result

    def proxy_headers(self):
        return [("Host", PUBLIC_HOST), ("Tailscale-User-Login", TAILSCALE_USER)]

    def test_remote_disabled_by_default(self):
        local = create_server(Path(self.temp.name) / "local.sqlite3", port=0)
        thread = threading.Thread(target=local.serve_forever, daemon=True)
        thread.start()
        original_port = self.port
        try:
            self.port = local.server_address[1]
            self.assertEqual(self.request(headers=self.proxy_headers())[0], 403)
        finally:
            self.port = original_port
            local.shutdown()
            local.server_close()
            thread.join(timeout=3)

    def test_identity_and_exact_origin_are_required(self):
        self.assertEqual(self.request(headers=self.proxy_headers())[0], 200)
        self.assertEqual(self.request(headers=[("Host", PUBLIC_HOST)])[0], 403)
        self.assertEqual(self.request(headers=[("Host", PUBLIC_HOST), ("Tailscale-User-Login", "another@example.test")])[0], 403)
        self.assertEqual(self.request(headers=[("Host", self.local_host), ("Tailscale-User-Login", "another@example.test")])[0], 403)
        for origin in ("http://" + PUBLIC_HOST, "https://studio.example-tailnet.ts.net",
                "https://studio.example-tailnet.ts.net:443", "http://" + self.local_host, "null", ""):
            with self.subTest(origin=origin):
                self.assertEqual(self.request(headers=self.proxy_headers() + [("Origin", origin)])[0], 403)
        self.assertEqual(self.request(headers=self.proxy_headers() + [("Origin", PUBLIC_ORIGIN)])[0], 200)
        self.assertEqual(self.request(headers=self.proxy_headers() + [("Sec-Fetch-Site", "cross-site")])[0], 403)

    def test_duplicate_security_headers_are_rejected(self):
        for name, value in (("Host", PUBLIC_HOST), ("Tailscale-User-Login", TAILSCALE_USER)):
            self.assertEqual(self.request(headers=self.proxy_headers() + [(name, value)])[0], 403)
        headers = self.proxy_headers() + [("Origin", PUBLIC_ORIGIN), ("Origin", PUBLIC_ORIGIN)]
        self.assertEqual(self.request(headers=headers)[0], 403)

    def test_forwarded_headers_do_not_create_trust(self):
        headers = [("Host", "attacker.test"), ("X-Forwarded-Host", PUBLIC_HOST),
            ("X-Forwarded-Proto", "https"), ("Tailscale-User-Login", TAILSCALE_USER)]
        self.assertEqual(self.request(headers=headers)[0], 403)
        headers = [("Host", PUBLIC_HOST), ("X-Forwarded-User", TAILSCALE_USER)]
        self.assertEqual(self.request(headers=headers)[0], 403)

    def test_proxy_cannot_use_local_host_even_with_correct_owner_identity(self):
        headers = [("Host", self.local_host), ("Tailscale-User-Login", TAILSCALE_USER)]
        self.assertEqual(self.request(headers=headers)[0], 403)
        self.assertEqual(self.request()[0], 200)
        self.assertEqual(self.request(headers=self.proxy_headers())[0], 200)

    def test_proxy_markers_reject_local_host_without_identity(self):
        for name in ("Tailscale-User-Name", "Tailscale-User-Profile-Pic", "Forwarded",
                "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "x-forwarded-for"):
            for value in ("proxy-marker", ""):
                with self.subTest(header=name, value=value):
                    self.assertEqual(self.request(headers=[("Host", self.local_host), (name, value)])[0], 403)

    def test_remote_session_and_write_use_same_store_with_csrf(self):
        status, session, response_headers = self.request("/api/session", self.proxy_headers())
        self.assertEqual(status, 200)
        cookie = response_headers["Set-Cookie"]
        for attribute in ("; Secure", "; HttpOnly", "; SameSite=Strict"):
            self.assertIn(attribute, cookie)
        local_cookie = self.request("/api/session")[2]["Set-Cookie"]
        self.assertNotIn("; Secure", local_cookie)
        args = {"name": "rws_project_create", "arguments": {"requestId": "remote-create",
            "projectId": "remote-test", "name": "Synthetic private proxy test", "demo": True}}
        headers = self.proxy_headers() + [("Cookie", cookie.split(";", 1)[0]), ("X-RWS-CSRF", session["csrfToken"])]
        self.assertEqual(self.request("/api/human/call", headers, args)[0], 403)
        headers += [("Origin", PUBLIC_ORIGIN)]
        wrong = [(name, "wrong" if name == "X-RWS-CSRF" else value) for name, value in headers]
        self.assertEqual(self.request("/api/human/call", wrong, args)[0], 403)
        status, result, _ = self.request("/api/human/call", headers, args)
        self.assertEqual(status, 200, result)
        local_state = self.request("/api/state?projectId=remote-test")[1]
        self.assertEqual(local_state["revision"], result["revision"])
        self.assertEqual(local_state["projects"][0]["id"], "remote-test")
        self.server.sessions.clear()
        status, error, _ = self.request("/api/human/call", headers, args)
        self.assertEqual(status, 403)
        self.assertEqual(error["error"]["code"], "session_expired")
        self.assertEqual(self.request("/api/state?projectId=remote-test")[1]["revision"], result["revision"])

    def test_mcp_remote_review_link_retains_model_permission_boundary(self):
        conn = MCPConnection(self.server.store, web_url=PUBLIC_ORIGIN)
        initialized = conn.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "fixture", "version": "1"}}})
        self.assertIn(PUBLIC_ORIGIN, initialized["result"]["instructions"])
        conn.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        response = conn.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "rws_project_stages_set", "arguments": {"requestId": "forbidden-model-decision",
                "projectId": "synthetic", "expectedRevision": 1, "activeStages": ["formal"]}}})
        error = response["result"]["structuredContent"]["error"]
        self.assertEqual(error["code"], "approval_required")
        self.assertEqual(error["reviewUrl"], PUBLIC_ORIGIN + "/?projectId=synthetic&stages=1")


if __name__ == "__main__":
    unittest.main()
