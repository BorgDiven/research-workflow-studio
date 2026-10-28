"""Cross-layer boundaries using isolated local Git and short synthetic jobs."""
import copy
import http.client
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid

from rws.core import Store
from rws.operations import OperationsRunner
from rws.server import create_server
from rws.tracking_client import HTTPClient, TrackingClient


ROOT = Path(__file__).resolve().parents[1]


class V040Integration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rws-integration-')
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Synthetic integration')
        self.git('config', 'user.email', 'fixture@example.invalid')
        (self.repo / 'job.py').write_text('import time,sys\nprint("registered-job", flush=True)\ntime.sleep(float(sys.argv[1]) if len(sys.argv)>1 else 0)\n')
        self.git('add', '--', 'job.py')
        self.git('-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', 'commit', '-m', 'Fixture')
        self.commit = self.git('rev-parse', 'HEAD').strip()
        self.db = self.root / 'studio.sqlite3'
        self.store = Store(self.db)
        self.store.call('rws_project_create', {'projectId': 'p', 'requestId': self.uid(), 'name': 'Synthetic integration'})
        self.server = self.write('rws_server_save', record={'title': 'Local', 'transport': 'local', 'workspaceRoot': str(self.root)})
        self.repository = self.write('rws_repository_save', record={'title': 'Checkout', 'serverRef': self.server['ref'], 'path': str(self.repo)})
        self.environment = self.write('rws_environment_save', record={'title': 'Python', 'serverRef': self.server['ref'], 'repositoryRef': self.repository['ref'], 'workingDirectory': str(self.repo), 'pythonExecutable': sys.executable})
        self.spec = self.write('rws_spec_save', record={'title': 'Synthetic process', 'schemaVersion': 1, 'kind': 'training', 'status': 'ready', 'purpose': 'Check application integration.', 'inputs': [], 'outputs': [{'name': 'log', 'kind': 'attachment', 'semantic': 'training-log'}], 'configSchema': {'type': 'object'}, 'dependencies': [], 'acceptanceChecks': [{'id': 'software', 'description': 'Short local test'}], 'capabilities': ['fixture'], 'processMetrics': [{'id': 'loss', 'unit': 'loss', 'axis': 'step', 'scope': 'run'}]})
        self.code = self.write('rws_code_register', record={'title': 'Registered script', 'kind': 'training', 'version': '1', 'source': 'job.py', 'specRef': self.spec['ref'], 'repositoryRef': self.repository['ref'], 'repository': str(self.repo), 'commit': self.commit, 'modulePath': 'job.py', 'entrypoint': 'job:main', 'capabilities': ['fixture'], 'checkEvidence': [{'checkId': 'software', 'status': 'passed', 'evidence': 'Synthetic fixture.'}]})
        self.dataset = self.write('rws_dataset_register', record={'title': 'Fixture cases', 'version': '1', 'sampleIds': ['one']})
        self.runner = OperationsRunner(self.store)
        self.http_server = create_server(self.db, port=0, web_root=ROOT / 'web')
        self.thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.http_server.server_address[1]
        self.origin = 'http://127.0.0.1:' + str(self.port)

    def tearDown(self):
        self.http_server.shutdown()
        self.http_server.server_close()
        self.thread.join(timeout=3)
        self.store.close()
        self.temp.cleanup()

    def uid(self):
        return 'integration-' + uuid.uuid4().hex

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], check=True, capture_output=True, text=True).stdout

    def arguments(self, **args):
        return dict(projectId='p', requestId=self.uid(), expectedRevision=self.store.snapshot('p')['revision'], **args)

    def write(self, name, actor='model', **args):
        return self.store.call(name, self.arguments(**args), actor=actor)['result']

    def operation(self, kind, arguments=None, approve=False, **refs):
        proposed = self.write('rws_operation_propose', record=dict(title='Fixture ' + kind, kind=kind, arguments=arguments or {}, **refs))
        return self.write('rws_operation_approve', actor='human', operationRef=proposed['ref']) if approve else proposed

    def launch(self, seconds=.05, environment=None, argv=None):
        env = environment or self.environment
        run = self.write('rws_run_register', record={'title': 'Fixture run', 'kind': 'training', 'status': 'planned', 'codeRef': self.code['ref'], 'environmentRef': env['ref'], 'repositoryRef': self.repository['ref'], 'config': {}, 'sampleSelection': {'datasetRef': self.dataset['ref'], 'sampleIds': ['one']}})
        plan = self.operation('task.start', {'argv': argv or [sys.executable, 'job.py', str(seconds)], 'timeoutSeconds': 3}, approve=True, runRef=run['ref'], environmentRef=env['ref'])
        return run, self.runner.execute(plan['ref'])['result']

    def follow(self, launch, kind, arguments=None):
        plan = self.operation(kind, arguments, approve=kind == 'task.stop', launchOperationRef=launch['ref'])
        return self.runner.execute(plan['ref'])['result']

    def http(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        values = {'Content-Type': 'application/json'} if body else {}
        values.update(headers or {})
        connection.request(method, path, json.dumps(body) if body else None, values)
        response = connection.getresponse()
        result = response.status, json.loads(response.read()), dict(response.getheaders())
        connection.close()
        return result

    def human(self):
        status, session, headers = self.http('GET', '/api/session')
        self.assertEqual(status, 200)
        return {'Origin': self.origin, 'Cookie': headers['Set-Cookie'].split(';', 1)[0], 'X-RWS-CSRF': session['csrfToken']}

    def test_cli_inspects_exact_registered_environment_and_git(self):
        for kind, refs in [('environment.inspect', {'environmentRef': self.environment['ref']}), ('git.inspect', {'repositoryRef': self.repository['ref']})]:
            plan = self.operation(kind, **refs)
            command = [sys.executable, '-m', 'rws', 'operate', '--db', str(self.db), '--project-id', 'p', '--operation-id', plan['ref']['id'], '--version', str(plan['ref']['version'])]
            process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
            result = json.loads(process.stdout)['result']['record']
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['result']['workingDirectory'], str(self.repo))
            if kind == 'git.inspect':
                self.assertEqual(result['result']['headCommit'], self.commit)
            retry = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertEqual(retry.returncode, 1)

    def test_http_cannot_claim_and_human_approval_does_not_execute(self):
        plan = self.operation('git.branch', {'name': 'reviewed'}, repositoryRef=self.repository['ref'])
        for endpoint, headers in [('/api/call', {}), ('/api/human/call', self.human())]:
            status, body, _ = self.http('POST', endpoint, {'name': '_rws_operation_claim', 'arguments': {}}, headers)
            self.assertEqual(status, 404, body)
        args = self.arguments(operationRef=plan['ref'])
        status, body, _ = self.http('POST', '/api/call', {'name': 'rws_operation_approve', 'arguments': args})
        self.assertEqual(status, 403, body)
        status, body, _ = self.http('POST', '/api/human/call', {'name': 'rws_operation_approve', 'arguments': args}, self.human())
        self.assertEqual(status, 200, body)
        self.assertEqual(body['result']['record']['status'], 'approved')
        self.assertNotIn('reviewed', self.git('branch', '--list'))

    def test_original_run_ref_http_tracking_and_report_freeze(self):
        run, launch = self.launch()
        client = TrackingClient(HTTPClient(self.origin), 'p', run['ref'], self.root / 'spool')
        client.log('loss', 0, 2, event_id='point-zero')
        self.assertEqual(client.flush()['status'], 'flushed')
        query = self.store.call('rws_metrics_query', {'projectId': 'p', 'runRefs': [run['ref']]})['result']
        snapshot = self.write('rws_metrics_snapshot', runRef=run['ref'], title='Measured history', throughSequence=query['throughSequence'])
        report = self.write('rws_report_create_revision', record={'title': 'Frozen record', 'inputRefs': [snapshot['ref']], 'markdown': 'Synthetic only.'})
        original = copy.deepcopy(report)
        client.log('loss', 1, 1, event_id='point-one')
        self.assertEqual(client.flush()['status'], 'flushed')
        time.sleep(.15)
        self.assertEqual(self.follow(launch, 'task.inspect')['record']['result']['taskStatus'], 'completed')
        self.assertEqual(self.store.call('rws_record_get', {'ref': report['ref']})['result'], original)
        self.assertEqual(snapshot['record']['source']['pointCount'], 1)
        self.assertEqual(snapshot['record']['datasetRef'], self.dataset['ref'])

    def test_python_module_cannot_be_shadowed_from_environment_subdirectory(self):
        folder = self.repo / 'subdir'
        folder.mkdir()
        marker = folder / 'unregistered-ran.txt'
        (folder / 'job.py').write_text('from pathlib import Path\nPath("unregistered-ran.txt").write_text("wrong source")\n')
        env = self.write('rws_environment_save', record={'title': 'Subdirectory', 'serverRef': self.server['ref'], 'repositoryRef': self.repository['ref'], 'workingDirectory': str(folder), 'pythonExecutable': sys.executable})
        _, launch = self.launch(environment=env, argv=[sys.executable, '-m', 'job'])
        time.sleep(.15)
        self.assertEqual(launch['record']['status'], 'failed', 'A matching -m name must not run a different file from cwd.')
        self.assertFalse(marker.exists())

    def test_logs_reject_receipt_from_another_job(self):
        _, launch = self.launch()
        time.sleep(.15)
        path = Path(launch['record']['result']['receiptPath'])
        state = json.loads(path.read_text())
        state['processStart'] = 'different-claim'
        path.write_text(json.dumps(state))
        result = self.follow(launch, 'task.logs', {'stream': 'stdout'})
        self.assertNotEqual(result['record']['status'], 'completed', 'Logs require the same receipt identity as inspect/stop.')
        self.assertNotIn('stdout', result['record']['result'])

    def test_stop_control_file_cannot_write_through_symlink(self):
        _, launch = self.launch(seconds=1)
        root = Path(launch['record']['result']['receiptPath']).parent
        victim = self.root / 'outside-job.json'
        victim.write_text('unchanged')
        stop = root / 'stop.json'
        stop.symlink_to(victim)
        try:
            self.follow(launch, 'task.stop')
            self.assertEqual(victim.read_text(), 'unchanged', 'Approved stop must not write outside its job directory.')
        finally:
            stop.unlink(missing_ok=True)
            self.follow(launch, 'task.stop')

    def test_push_rejects_extra_remote_destinations(self):
        approved_remote = self.root / 'approved.git'
        other_remote = self.root / 'not-approved.git'
        for path in (approved_remote, other_remote):
            subprocess.run(['git', 'init', '--bare', str(path)], check=True, capture_output=True)
        self.git('remote', 'add', 'origin', str(approved_remote))
        self.git('remote', 'set-url', '--add', '--push', 'origin', str(approved_remote))
        self.git('remote', 'set-url', '--add', '--push', 'origin', str(other_remote))
        repository = self.write('rws_repository_save', record={'id': self.repository['ref']['id'], 'remoteUrl': str(approved_remote)})
        plan = self.operation('git.push', {'remoteName': 'origin', 'refspec': 'refs/heads/main:refs/heads/main'}, approve=True, repositoryRef=repository['ref'])
        result = self.runner.execute(plan['ref'])['result']
        refs = subprocess.run(['git', '--git-dir', str(other_remote), 'show-ref'], capture_output=True, text=True)
        self.assertNotIn('refs/heads/main', refs.stdout, 'One approved destination must not authorize extra Git push URLs.')
        self.assertNotEqual(result['record']['status'], 'completed')


if __name__ == '__main__':
    unittest.main()
