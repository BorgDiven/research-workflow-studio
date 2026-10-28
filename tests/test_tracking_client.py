import json
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit

from rws.core import RwsError, Store
from rws.tracking_client import MLflowImporter, TrackingClient, safe_base_url


RUN = {'projectId': 'p', 'type': 'run', 'id': 'R', 'version': 1}


class MetricEndpoint:
    def __init__(self):
        self.revision, self.requests, self.points, self.calls = 1, {}, [], []
        self.offline = self.lose_receipt = False

    def __call__(self, name, args):
        self.calls.append((name, json.loads(json.dumps(args))))
        if self.offline:
            raise ConnectionError('Unavailable')
        if name == 'rws_project_list':
            return {'ok': True, 'result': [{'id': 'p', 'revision': self.revision}]}
        request = args['requestId']
        if request in self.requests:
            if self.requests[request] != args:
                raise RwsError('idempotency_conflict', 'Changed retry')
            return {'ok': True, 'result': {}}
        if args['expectedRevision'] != self.revision:
            raise RwsError('revision_conflict', 'Changed project')
        self.requests[request] = json.loads(json.dumps(args))
        self.points.extend(args['points'])
        self.revision += 1
        if self.lose_receipt:
            self.lose_receipt = False
            raise ConnectionError('Accepted but response lost')
        return {'ok': True, 'result': {}}


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.endpoint = MetricEndpoint()

    def tearDown(self):
        self.temp.cleanup()

    def client(self, size=1000):
        return TrackingClient(self.endpoint, 'p', RUN, self.root / 'spool', batch_size=size)

    def test_batching_event_identity_and_restart(self):
        client = self.client(2)
        for index in range(5):
            client.log('loss', index, 1 / (index + 1), event_id='e' + str(index))
        client.log('loss', 0, 1, event_id='e0')
        with self.assertRaisesRegex(ValueError, 'event ID'):
            client.log('loss', 0, 9, event_id='e0')
        result = self.client(2).flush()
        self.assertEqual((result['sentBatches'], result['acknowledgedEvents']), (3, 5))
        self.assertEqual(len(self.endpoint.points), 5)
        self.client().log('loss', 0, 1, event_id='e0')
        self.assertEqual(self.client().flush()['sentBatches'], 0)

    def test_offline_queue_retries_exact_request_after_lost_acknowledgement(self):
        client = self.client()
        client.log('loss', 1, .5, event_id='one')
        self.endpoint.offline = True
        self.assertEqual(client.flush()['pendingEvents'], 1)
        self.endpoint.offline = False
        self.endpoint.lose_receipt = True
        self.assertEqual(client.flush()['status'], 'pending')
        submitted = [args for name, args in self.endpoint.calls if name == 'rws_metrics_append'][-1]
        result = self.client().flush()
        retried = [args for name, args in self.endpoint.calls if name == 'rws_metrics_append'][-1]
        self.assertEqual(submitted, retried)
        self.assertEqual(result['status'], 'flushed')
        self.assertEqual(len(self.endpoint.points), 1)

    def test_explicit_revision_conflict_allows_revision_refresh(self):
        endpoint, client = self.endpoint, self.client()
        client.log('loss', 0, 1)
        original = endpoint.__call__
        changed = [False]
        def concurrent(name, args):
            if name == 'rws_metrics_append' and not changed[0]:
                endpoint.revision += 1
                changed[0] = True
            return original(name, args)
        client.call = concurrent
        self.assertEqual(client.flush()['status'], 'flushed')
        self.assertEqual(len(endpoint.points), 1)

    def test_invalid_values_scope_and_credential_urls(self):
        client = self.client()
        for value in (float('nan'), float('inf'), True):
            with self.assertRaises(ValueError):
                client.log('loss', 0, value)
        with self.assertRaises(ValueError):
            client.log('loss', 1, None)
        client.log('loss', 1, None, reason='No observation')
        other = TrackingClient(self.endpoint, 'p', dict(RUN, id='other'), self.root / 'spool')
        with self.assertRaisesRegex(ValueError, 'another exact run'):
            other.flush()
        for url in ('https://user:secret@example.org', 'https://example.org?token=secret', 'file:///tmp/mlflow'):
            with self.assertRaises(ValueError):
                safe_base_url(url)

    def test_explicit_mlflow_history_is_paginated_read_only_and_keeps_source(self):
        requests = []
        class Fixture(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlsplit(self.path)
                requests.append((self.command, parsed.path, parse_qs(parsed.query), self.headers.get('Authorization')))
                query = parse_qs(parsed.query)
                second = query.get('page_token') == ['next']
                body = {'metrics': [{'key': 'train/loss', 'step': 1 if second else 0,
                                     'value': .5 if second else 1, 'timestamp': 1700000001000 if second else 1700000000000}]}
                if not second:
                    body['next_page_token'] = 'next'
                payload = json.dumps(body).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = 'http://127.0.0.1:' + str(server.server_address[1])
            importer = MLflowImporter(base, 'external-run', self.client(), headers_provider=lambda: {'Authorization': 'Bearer fixture-secret'})
            result = importer.import_history({'train/loss': 'training-loss'})
            self.assertEqual(result['readObservations'], 2)
            self.assertEqual(len(self.endpoint.points), 2)
            self.assertEqual([p['x'] for p in self.endpoint.points], [0, 1])
            self.assertTrue(all(method == 'GET' and path.endswith('/metrics/get-history') for method, path, _, _ in requests))
            self.assertTrue(all(query['run_id'] == ['external-run'] for _, _, query, _ in requests))
            submitted = next(iter(self.endpoint.requests.values()))
            self.assertEqual(submitted['source'], {'kind': 'mlflow', 'baseUrl': base, 'runId': 'external-run'})
            self.assertNotIn('fixture-secret', (self.root / 'spool' / 'metrics-spool.json').read_text())
            importer.import_history({'train/loss': 'training-loss'})
            self.assertEqual(len(self.endpoint.points), 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_mlflow_train_split_delivers_to_actual_store_under_fixed_metric_contract(self):
        with_store = Store(':memory:')
        try:
            counter = [0]
            def write(name, **args):
                counter[0] += 1
                return with_store.call(name, dict(args, projectId='p', expectedRevision=with_store.snapshot('p')['revision'], requestId='actual-' + str(counter[0])))['result']
            with_store.call('rws_project_create', {'projectId': 'p', 'name': 'Synthetic', 'requestId': 'actual-project'})
            spec = write('rws_spec_save', record={'title': 'Training', 'schemaVersion': 1, 'kind': 'training', 'status': 'ready', 'purpose': 'Fixture', 'inputs': [], 'outputs': [{'name': 'loss', 'kind': 'series'}], 'configSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}, 'dependencies': [], 'capabilities': [], 'acceptanceChecks': [{'id': 'fixture', 'description': 'Fixture'}], 'processMetrics': [{'id': 'loss', 'unit': '', 'axis': 'step', 'scope': 'run', 'splits': ['train']}]})
            code = write('rws_code_register', record={'title': 'Training', 'kind': 'training', 'version': 'v1', 'source': 'train.py', 'specRef': spec['ref'], 'repository': 'https://example.invalid/fixture', 'commit': 'fixture-commit', 'modulePath': 'train.py', 'entrypoint': 'train:run', 'capabilities': [], 'checkEvidence': [{'checkId': 'fixture', 'status': 'passed', 'evidence': 'Software fixture'}]})
            run = write('rws_run_register', record={'title': 'Recorded execution', 'kind': 'training', 'codeRef': code['ref'], 'status': 'running', 'config': {}, 'inputRefs': [], 'purpose': 'Fixture', 'sampleSelection': {'sampleIds': ['s']}})
            client = TrackingClient(with_store.call, 'p', run['ref'], self.root / 'actual')
            class HistoryFixture:
                def open(self, request, timeout):
                    if request.method != 'GET' or not request.full_url.startswith('http://127.0.0.1:5000/api/2.0/mlflow/metrics/get-history?'):
                        raise AssertionError('Import must only read the explicit metric history.')
                    return io.BytesIO(json.dumps({'metrics': [{'key': 'train_loss', 'step': 0, 'value': 2, 'timestamp': 1700000000000}]}).encode())
            importer = MLflowImporter('http://127.0.0.1:5000', 'fixed-source', client, opener=HistoryFixture())
            imported = importer.import_history({'train_loss': 'loss'}, split='train')
            self.assertEqual(imported['delivery']['status'], 'flushed')
            query = with_store.call('rws_metrics_query', {'projectId': 'p', 'runRefs': [run['ref']]})['result']
            self.assertEqual(query['total'], 1)
            self.assertIn('fixed-source', json.dumps(query))
            self.assertEqual(query['series'][0]['split'], 'train')
            self.assertFalse(query['series'][0].get('sampleId'))
            self.assertEqual(with_store.call('rws_record_get', {'ref': run['ref']})['result']['record']['status'], 'running')
        finally:
            with_store.close()


if __name__ == '__main__':
    unittest.main()
