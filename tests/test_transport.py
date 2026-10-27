"""Isolated transport tests; no production workspace or model is accessed."""

import concurrent.futures
import http.client
import json
import os
import select
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from rws.mcp import MCPConnection, SUPPORTED_VERSIONS
from rws.server import create_server


APP_ROOT = Path(__file__).resolve().parents[1]


class MCPClient:
    def __init__(self, db_path):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "rws", "mcp", "--db", str(db_path)],
            cwd=str(APP_ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        self.seq = 0

    def message(self, value, response=True):
        self.proc.stdin.write((json.dumps(value) + "\n").encode())
        self.proc.stdin.flush()
        if not response:
            return None
        ready, _, _ = select.select([self.proc.stdout], [], [], 8)
        if not ready:
            raise AssertionError("MCP response timed out")
        line = self.proc.stdout.readline()
        if not line:
            raise AssertionError("MCP exited: " + self.proc.stderr.read().decode())
        return json.loads(line)

    def request(self, method, params=None):
        self.seq += 1
        return self.message({"jsonrpc": "2.0", "id": self.seq, "method": method,
                             "params": {} if params is None else params})

    def initialize(self, version="2025-11-25"):
        result = self.request("initialize", {"protocolVersion": version,
            "capabilities": {}, "clientInfo": {"name": "studio-test", "version": "1"}})
        self.message({"jsonrpc": "2.0", "method": "notifications/initialized"}, False)
        return result

    def call(self, name, arguments):
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        self.last_response = result
        return result["result"]["structuredContent"]

    def close(self):
        if self.proc.stdin:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            self.proc.wait(timeout=3)
        self.proc.stdout.close()
        self.proc.stderr.close()


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "isolated" / "studio.sqlite3"
        self.web = self.root / "web"
        self.web.mkdir()
        (self.web / "index.html").write_text("<h1>Isolated transport fixture</h1>")
        (self.root / "private.txt").write_text("must not be served")
        (self.web / "outside.txt").symlink_to(self.root / "private.txt")
        self.start_server()
        self.mcp = None

    def start_server(self):
        self.server = create_server(self.db, port=0, web_root=self.web)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.origin = "http://127.0.0.1:%s" % self.port

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def tearDown(self):
        if self.mcp:
            self.mcp.close()
        self.stop_server()
        self.temp.cleanup()

    def http(self, method, path, value=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        request_headers = {"Content-Type": "application/json"} if value is not None else {}
        request_headers.update(headers or {})
        conn.request(method, path, json.dumps(value) if value is not None else None,
                     request_headers)
        response = conn.getresponse()
        data = response.read()
        result_headers = dict(response.getheaders())
        status = response.status
        conn.close()
        parsed = json.loads(data) if "application/json" in result_headers.get("Content-Type", "") else data.decode()
        return status, parsed, result_headers

    def call(self, name, arguments, human_headers=None):
        return self.http("POST", "/api/human/call" if human_headers else "/api/call",
                         {"name": name, "arguments": arguments}, human_headers)

    def create_project(self, project_id="alpha"):
        status, result, _ = self.call("rws_project_create", {
            "requestId": "create-" + project_id, "projectId": project_id,
            "name": "Synthetic " + project_id, "goal": "Transport verification", "demo": True})
        self.assertEqual(status, 200, result)
        return result["result"]

    def human_headers(self):
        status, session, headers = self.http("GET", "/api/session")
        self.assertEqual(status, 200)
        return {"Origin": self.origin, "Cookie": headers["Set-Cookie"].split(";", 1)[0],
                "X-RWS-CSRF": session["csrfToken"]}

    def connect_mcp(self):
        self.mcp = MCPClient(self.db)
        result = self.mcp.initialize()
        self.assertEqual(result["result"]["protocolVersion"], "2025-11-25")
        self.assertEqual(result["result"]["capabilities"], {"tools": {"listChanged": False}})
        return self.mcp

    def test_http_static_read_security_and_empty_state(self):
        status, state, _ = self.http("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(state["projects"], [])
        status, page, headers = self.http("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Isolated transport fixture", page)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        for path in ("/../private.txt", "/%2e%2e/private.txt", "/outside.txt", "/api/missing"):
            self.assertEqual(self.http("GET", path)[0], 404, path)
        self.assertEqual(self.http("GET", "/api/state", headers={"Host": "attacker.invalid"})[0], 403)
        self.assertEqual(self.http("GET", "/api/session", headers={"Origin": "https://attacker.invalid"})[0], 403)
        self.assertEqual(self.http("GET", "/api/session", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)

    def test_http_mcp_read_write_consistency_and_restart(self):
        self.create_project()
        client = self.connect_mcp()
        projects = client.call("rws_project_list", {})["result"]
        self.assertEqual([p["id"] for p in projects], ["alpha"])
        result = client.call("rws_project_create", {"requestId": "mcp-beta",
            "projectId": "beta", "name": "Synthetic beta", "demo": True})
        self.assertTrue(result["ok"])
        status, state, _ = self.http("GET", "/api/state?projectId=beta")
        self.assertEqual(status, 200)
        self.assertEqual(state["projectId"], "beta")
        self.assertEqual(len(state["projects"]), 2)
        self.stop_server()
        self.start_server()
        self.assertEqual(len(self.http("GET", "/api/state")[1]["projects"]), 2)
        # Close/reopen the independent MCP process against the same file.
        client.close()
        self.mcp = None
        client = self.connect_mcp()
        self.assertEqual(len(client.call("rws_project_list", {})["result"]), 2)

    def test_human_session_required_and_model_cannot_spoof_authority(self):
        project = self.create_project()
        args = {"requestId": "stage-choice", "projectId": project["id"],
                "expectedRevision": project["revision"], "activeStages": ["idea"]}
        status, result, _ = self.call("rws_project_stages_set", args)
        self.assertEqual(status, 403, result)
        self.assertEqual(result["error"]["code"], "approval_required")
        envelope = {"name": "rws_project_stages_set", "arguments": args, "actor": "human"}
        self.assertEqual(self.http("POST", "/api/call", envelope)[0], 400)
        status, _, _ = self.http("POST", "/api/human/call",
            {"name": "rws_project_stages_set", "arguments": args}, {"Origin": self.origin})
        self.assertEqual(status, 403)
        headers = self.human_headers()
        wrong = dict(headers, Origin="https://attacker.invalid")
        self.assertEqual(self.call("rws_project_stages_set", args, wrong)[0], 403)
        missing_origin = dict(headers)
        del missing_origin["Origin"]
        self.assertEqual(self.call("rws_project_stages_set", args, missing_origin)[0], 403)
        self.server.sessions.clear()
        expired_status, expired, _ = self.call("rws_project_stages_set", args, headers)
        self.assertEqual(expired_status, 403)
        self.assertEqual(expired['error']['code'], 'session_expired')
        self.assertEqual(self.http('GET', '/api/state?projectId=alpha')[1]['revision'], project['revision'])
        headers = self.human_headers()
        status, result, _ = self.call("rws_project_stages_set", args, headers)
        self.assertEqual(status, 200, result)
        self.assertEqual(self.http("GET", "/api/state?projectId=alpha")[1]["projects"][0]["activeStages"], ["idea"])
        mcp = self.connect_mcp()
        denied = mcp.call("rws_project_stages_set", dict(args, requestId="mcp-denied",
                          expectedRevision=result["revision"]))
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["error"]["code"], "approval_required")
        self.assertEqual(denied["error"]["reviewPath"], "/?projectId=alpha&stages=1")
        self.assertEqual(denied["error"]["reviewUrl"], "http://127.0.0.1:8831/?projectId=alpha&stages=1")
        self.assertTrue(mcp.last_response["result"]["isError"])

    def test_retry_and_competing_http_writes(self):
        project = self.create_project()
        args = {"requestId": "first-research", "projectId": "alpha",
                "expectedRevision": project["revision"], "record": {
                    "id": "question-one", "title": "Where does loss change?",
                    "question": "Observe registered values", "kind": "exploration", "stage": "idea"}}
        first = self.call("rws_research_save", args)
        self.assertEqual(first[0], 200, first[1])
        repeat = self.call("rws_research_save", args)
        self.assertEqual(first[1], repeat[1])
        changed = dict(args, record=dict(args["record"], title="Changed payload"))
        self.assertIn(self.call("rws_research_save", changed)[0], (400, 409))
        revision = first[1]["revision"]
        barrier = threading.Barrier(2)
        def compete(index):
            barrier.wait()
            return self.call("rws_research_save", {"requestId": "compete-%s" % index,
                "projectId": "alpha", "expectedRevision": revision, "record": {
                    "id": "branch-%s" % index, "title": "Independent branch %s" % index,
                    "question": "Observe", "kind": "exploration", "stage": "idea"}})[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(compete, (1, 2)))
        self.assertEqual(sorted(statuses), [200, 409])
        state = self.http("GET", "/api/state?projectId=alpha")[1]
        self.assertEqual(state["revision"], revision + 1)
        self.assertEqual(len(state["records"]), 2)

    def test_mcp_protocol_and_notification_behavior(self):
        client = MCPClient(self.db)
        self.mcp = client
        self.assertEqual(client.request("tools/list")["error"]["code"], -32002)
        self.assertEqual(client.request("ping")["result"], {})
        initialized = client.initialize("future-unsupported")
        self.assertEqual(initialized["result"]["protocolVersion"], SUPPORTED_VERSIONS[0])
        tools = client.request("tools/list")["result"]["tools"]
        self.assertIn("rws_project_create", [t["name"] for t in tools])
        self.assertTrue(all(t["inputSchema"]["type"] == "object" for t in tools))
        self.assertEqual(client.request("tools/call", {"name": "shell", "arguments": {}})["error"]["code"], -32602)
        self.assertEqual(client.request("tools/call", {"name": "rws_project_list", "arguments": {}, "actor": "human"})["error"]["code"], -32602)
        self.assertEqual(client.request("resources/read", {"uri": "/etc/passwd"})["error"]["code"], -32601)
        # The initialized notification emitted no stdout line; the next request ID matches.
        ping = client.request("ping")
        self.assertEqual(ping["id"], client.seq)
        self.assertEqual(ping["result"], {})

    def test_http_rejects_unstructured_or_cross_origin_writes(self):
        payload = {"name": "rws_project_list", "arguments": {}}
        self.assertEqual(self.http("POST", "/api/call", payload,
                                  {"Origin": "https://attacker.invalid"})[0], 403)
        self.assertEqual(self.http("POST", "/api/call", payload,
                                  {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.http("POST", "/api/call", {"name": "rws_project_list"})[0], 400)
        self.assertEqual(self.http("OPTIONS", "/api/call")[0], 405)
        self.assertEqual(self.http("GET", "/api/state?projectId=a&projectId=b")[0], 400)


if __name__ == "__main__":
    unittest.main()
