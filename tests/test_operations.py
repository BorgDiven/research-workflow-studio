import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from rws.core import RwsError, Store
from rws.operations import OperationsRunner, SubprocessTransport, TransportError
from rws import operations_worker


class ReceiptObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rws-receipt-')
        self.root = Path(self.temp.name).resolve()
        self.job = self.root / '.rws-jobs' / 'job-fixture'
        self.job.mkdir(parents=True)
        self.running = {'jobId': 'job-fixture', 'processStart': 'claim-fixture',
                        'pid': 12345, 'taskStatus': 'running'}
        self.expected = {key: self.running[key] for key in ('jobId', 'processStart')}
        self.file = self.job / 'receipt.json'
        self.file.write_text(json.dumps(self.running))

    def tearDown(self):
        self.temp.cleanup()

    def test_final_receipt_wins_if_supervisor_exits_during_identity_check(self):
        for status, exit_code in [('partial', -15), ('completed', 0), ('failed', 1)]:
            for check in ('kill', 'ps'):
                with self.subTest(status=status, check=check):
                    self.file.write_text(json.dumps(self.running))
                    final = dict(self.running, taskStatus=status, exitCode=exit_code,
                                 finishedAt='2026-10-28T00:00:00+00:00')
                    def supervisor_exits(*args, **kwargs):
                        self.file.write_text(json.dumps(final))
                        if check == 'kill':
                            raise ProcessLookupError
                        return SimpleNamespace(returncode=1, stdout='')
                    with patch.object(operations_worker.os, 'kill', side_effect=supervisor_exits if check == 'kill' else None), \
                            patch.object(operations_worker, 'run', supervisor_exits):
                        observed = operations_worker.receipt(self.job, self.expected)
                    self.assertEqual(observed['taskStatus'], status)
                    self.assertEqual(observed['exitCode'], exit_code)

    def test_reread_final_receipt_must_still_match_launch_identity(self):
        def supervisor_exits(*args, **kwargs):
            self.file.write_text(json.dumps(dict(self.running, processStart='other-claim', taskStatus='partial', exitCode=-15)))
            raise ProcessLookupError
        with patch.object(operations_worker.os, 'kill', side_effect=supervisor_exits):
            with self.assertRaisesRegex(ValueError, 'identity'):
                operations_worker.receipt(self.job, self.expected)

    def test_disappeared_supervisor_without_final_receipt_stays_unknown(self):
        with patch.object(operations_worker.os, 'kill', side_effect=ProcessLookupError):
            observed = operations_worker.receipt(self.job, self.expected)
        self.assertEqual(observed['taskStatus'], 'unknown')
        self.assertNotIn('exitCode', observed)

    def test_stop_waits_through_transient_unknown_for_confirmed_final_receipt(self):
        partial = dict(self.running, taskStatus='partial', exitCode=-15)
        observations = [self.running, dict(self.running, taskStatus='unknown'), partial]
        payload = {'kind': 'task.stop', 'workspaceRoot': str(self.root),
                   'repositoryPath': str(self.root), 'job': self.expected}
        with patch.object(operations_worker, 'receipt', side_effect=observations):
            observed = operations_worker.execute(payload)
        self.assertEqual(observed['taskStatus'], 'partial')
        self.assertEqual(json.loads((self.job / 'stop.json').read_text())['token'], 'claim-fixture')

    def test_stop_without_final_receipt_remains_unknown_after_bounded_wait(self):
        clock = [0.0]
        calls = [0]
        def observe(*args):
            calls[0] += 1
            return dict(self.running, taskStatus='running' if calls[0] == 1 else 'unknown')
        def sleep(seconds):
            clock[0] += seconds
        payload = {'kind': 'task.stop', 'workspaceRoot': str(self.root),
                   'repositoryPath': str(self.root), 'job': self.expected}
        with patch.object(operations_worker, 'receipt', side_effect=observe), \
                patch.object(operations_worker.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(operations_worker.time, 'sleep', side_effect=sleep):
            observed = operations_worker.execute(payload)
        self.assertEqual(observed['taskStatus'], 'unknown')
        self.assertNotIn('exitCode', observed)
        self.assertGreaterEqual(clock[0], 5)
        self.assertLess(clock[0], 5.1)


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rws-operations-')
        self.root = Path(self.temp.name)
        self.repo = self.root / 'registered repo'
        self.repo.mkdir()
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Synthetic Test')
        self.git('config', 'user.email', 'fixture@example.invalid')
        (self.repo / 'job.py').write_text("import pathlib, sys, time\nprint('job started', flush=True)\nprint('diagnostic', file=sys.stderr, flush=True)\npathlib.Path('invocations.txt').open('a').write('once\\n')\ntime.sleep(float(sys.argv[1]))\nprint('job finished', flush=True)\n")
        (self.repo / 'README.md').write_text('Synthetic repository\n')
        self.git('add', '--', 'job.py', 'README.md')
        self.git('-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', 'commit', '-m', 'fixture')
        self.commit = self.git('rev-parse', 'HEAD').strip()
        self.store = Store(':memory:')
        self.store.call('rws_project_create', {'requestId': self.uid(), 'projectId': 'p', 'name': 'Synthetic operations'})
        self.server = self.write('rws_server_save', record={'title': 'Local fixture', 'transport': 'local', 'workspaceRoot': str(self.root)})
        self.repository = self.write('rws_repository_save', record={'title': 'Registered fixture', 'serverRef': self.server['ref'], 'path': str(self.repo)})
        self.environment = self.write('rws_environment_save', record={'title': 'Local Python', 'serverRef': self.server['ref'], 'repositoryRef': self.repository['ref'], 'workingDirectory': str(self.repo), 'pythonExecutable': sys.executable})
        self.spec = self.write('rws_spec_save', record={'title': 'Synthetic process', 'schemaVersion': 1, 'kind': 'training', 'status': 'ready', 'purpose': 'Exercise process lifecycle only.', 'inputs': [], 'outputs': [{'name': 'log', 'kind': 'attachment', 'semantic': 'training-log'}], 'configSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}, 'dependencies': [], 'acceptanceChecks': [{'id': 'fixture', 'description': 'Synthetic process fixture'}], 'capabilities': []})
        self.code = self.write('rws_code_register', record={'title': 'Fixture job', 'kind': 'training', 'version': 'v1', 'source': 'job.py', 'specRef': self.spec['ref'], 'repositoryRef': self.repository['ref'], 'repository': str(self.repo), 'commit': self.commit, 'modulePath': 'job.py', 'entrypoint': 'job:main', 'capabilities': [], 'checkEvidence': [{'checkId': 'fixture', 'status': 'passed', 'evidence': 'Explicit local software test.'}]})
        self.runner = OperationsRunner(self.store)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def uid(self):
        return 'test-' + uuid.uuid4().hex

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], check=True, text=True, capture_output=True).stdout

    def write(self, name, actor='model', **args):
        return self.store.call(name, dict(args, projectId='p', requestId=self.uid(), expectedRevision=self.store.snapshot('p')['revision']), actor=actor)['result']

    def operation(self, kind, arguments=None, approve=True, **refs):
        if not refs:
            refs = {'repositoryRef': self.repository['ref']}
        result = self.write('rws_operation_propose', record=dict(title='Fixture ' + kind, kind=kind, arguments=arguments or {}, **refs))
        if approve:
            result = self.write('rws_operation_approve', operationRef=result['ref'], actor='human')
        return result

    def launch(self, seconds=.2, argv=None, timeout_seconds=4):
        run = self.write('rws_run_register', record={'title': 'Synthetic job', 'kind': 'training', 'codeRef': self.code['ref'], 'status': 'planned', 'config': {}, 'inputRefs': [], 'environmentRef': self.environment['ref'], 'repositoryRef': self.repository['ref'], 'sampleSelection': {'sampleIds': ['fixture']}, 'purpose': 'Software lifecycle test'})
        op = self.operation('task.start', {'argv': argv or [sys.executable, 'job.py', str(seconds)], 'timeoutSeconds': timeout_seconds}, runRef=run['ref'], environmentRef=self.environment['ref'])
        return run, op, self.runner.execute(op['ref'])['result']

    def follow(self, launch, kind, args=None):
        operation = self.operation(kind, args, approve=kind == 'task.stop', launchOperationRef=launch['ref'])
        return self.runner.execute(operation['ref'])['result']

    def test_exact_approval_claim_and_local_job_receipts(self):
        run, approved, launch = self.launch()
        self.assertIn(launch['record']['status'], ('running', 'completed'))
        with self.assertRaises(RwsError):
            self.runner.execute(approved['ref'])
        time.sleep(.3)
        result = self.follow(launch, 'task.inspect')['record']['result']
        self.assertEqual(result['taskStatus'], 'completed')
        self.assertEqual(result['exitCode'], 0)
        self.assertGreater(result['pid'], 0)
        self.assertTrue(Path(result['receiptPath']).is_file())
        log = self.follow(launch, 'task.logs', {'stream': 'stdout', 'tailLines': 10})['record']['result']
        self.assertIn('job finished', log['stdout'])
        self.assertEqual((self.repo / 'invocations.txt').read_text(), 'once\n')
        latest = self.store.call('rws_record_get', {'ref': {k: v for k, v in run['ref'].items() if k != 'version'}})['result']
        self.assertEqual(latest['record']['status'], 'completed')

    def test_explicit_stop_is_confirmed_partial_not_success(self):
        _, _, launch = self.launch(seconds=30, timeout_seconds=60)
        stopped = self.follow(launch, 'task.stop')['record']['result']
        self.assertEqual(stopped['taskStatus'], 'partial')
        self.assertIn('exitCode', stopped)
        self.assertEqual(stopped['message'], 'Stopped by an approved operation.')

    def test_unapproved_mutation_never_calls_transport(self):
        class Never:
            def perform(self, *args):
                raise AssertionError('Transport must not run before approval')
        proposed = self.operation('git.branch', {'name': 'unapproved'}, approve=False)
        with self.assertRaises(RwsError):
            OperationsRunner(self.store, Never()).execute(proposed['ref'])
        self.assertNotIn('unapproved', self.git('branch', '--list'))

    def test_read_only_inspections_can_execute_explicit_proposals(self):
        proposed = self.operation('git.inspect', approve=False)
        observed = self.runner.execute(proposed['ref'])['result']['record']
        self.assertEqual(observed['status'], 'completed')
        self.assertEqual(observed['result']['headCommit'], self.commit)
        environment = self.operation('environment.inspect', approve=False, environmentRef=self.environment['ref'])
        observed = self.runner.execute(environment['ref'])['result']['record']
        self.assertEqual(observed['status'], 'completed')
        self.assertIn('stdout', observed['result'])

    def test_git_scoped_commit_branch_tag_and_nonforce_local_bare_push(self):
        bare = self.root / 'remote.git'
        subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True)
        self.git('remote', 'add', 'origin', str(bare))
        self.repository = self.write('rws_repository_save', record={'id': self.repository['ref']['id'], 'remoteUrl': str(bare)})
        branch = self.operation('git.branch', {'name': 'reviewed-branch'})
        self.assertEqual(self.runner.execute(branch['ref'])['result']['record']['status'], 'completed')
        self.assertEqual(self.git('branch', '--show-current').strip(), 'main')
        (self.repo / 'README.md').write_text('A reviewed scoped change\n')
        (self.repo / 'not-selected.txt').write_text('Must not be committed\n')
        commit = self.operation('git.commit', {'message': 'Scoped fixture change', 'paths': ['README.md']})
        self.assertEqual(self.runner.execute(commit['ref'])['result']['record']['status'], 'completed')
        self.assertNotIn('not-selected.txt', self.git('ls-tree', '-r', '--name-only', 'HEAD'))
        for kind, args in [('git.tag', {'name': 'fixture-v1'}), ('git.push', {'remoteName': 'origin', 'refspec': 'refs/heads/main:refs/heads/main'}), ('git.push', {'remoteName': 'origin', 'refspec': 'refs/tags/fixture-v1:refs/tags/fixture-v1'})]:
            operation = self.operation(kind, args)
            result = self.runner.execute(operation['ref'])['result']['record']
            self.assertEqual(result['status'], 'completed', result)
        refs = subprocess.run(['git', '--git-dir', str(bare), 'show-ref'], check=True, capture_output=True, text=True).stdout
        self.assertIn('refs/heads/main', refs)
        self.assertIn('refs/tags/fixture-v1', refs)

    def test_unrelated_staged_files_are_not_committed(self):
        (self.repo / 'job.py').write_text('print("changed")\n')
        self.git('add', '--', 'job.py')
        (self.repo / 'README.md').write_text('selected change\n')
        operation = self.operation('git.commit', {'message': 'Scoped', 'paths': ['README.md']})
        result = self.runner.execute(operation['ref'])['result']['record']
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.commit)
        self.assertIn('job.py', self.git('diff', '--cached', '--name-only'))

    def test_local_push_destination_cannot_escape_workspace_through_symlink(self):
        with tempfile.TemporaryDirectory(prefix='rws-outside-mirror-') as outside:
            bare = Path(outside) / 'remote.git'
            subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True)
            alias = self.root / 'mirror.git'
            alias.symlink_to(bare, target_is_directory=True)
            self.git('remote', 'add', 'origin', str(alias))
            repository = self.write('rws_repository_save', record={'id': self.repository['ref']['id'], 'remoteUrl': str(alias)})
            plan = self.operation('git.push', {'remoteName': 'origin', 'refspec': 'refs/heads/main:refs/heads/main'}, repositoryRef=repository['ref'])
            result = self.runner.execute(plan['ref'])['result']['record']
            self.assertNotEqual(result['status'], 'completed')
            refs = subprocess.run(['git', '--git-dir', str(bare), 'show-ref'], capture_output=True, text=True)
            self.assertNotIn('refs/heads/main', refs.stdout)

    def test_dirty_checkout_wrong_entrypoint_and_existing_job_do_not_launch(self):
        (self.repo / 'job.py').write_text('print("changed")\n')
        _, _, result = self.launch()
        self.assertEqual(result['record']['status'], 'failed')
        self.assertFalse((self.repo / 'invocations.txt').exists())

    def test_shell_or_inline_python_cannot_impersonate_registered_module(self):
        _, _, result = self.launch(argv=[sys.executable, '-c', 'print("unregistered")', 'job.py'])
        self.assertEqual(result['record']['status'], 'failed')
        self.assertFalse((self.repo / 'invocations.txt').exists())

    def test_disconnect_keeps_identity_unknown_and_cannot_launch_again(self):
        class Disconnected:
            calls = 0
            def perform(self, *args):
                self.calls += 1
                raise TransportError('Uncertain receipt', uncertain=True)
        disconnected = Disconnected()
        self.runner = OperationsRunner(self.store, disconnected)
        _, approved, result = self.launch()
        self.assertEqual(result['record']['status'], 'unknown')
        self.assertTrue(result['record']['result']['receiptPath'].endswith('receipt.json'))
        with self.assertRaises(RwsError):
            self.runner.execute(approved['ref'])
        self.assertEqual(disconnected.calls, 1)

    def test_claimed_launch_survives_crash_before_dispatch_without_restarting(self):
        class CrashBeforeDispatch:
            def perform(self, *args):
                raise SystemExit('Simulated runner termination after durable claim')
        self.runner = OperationsRunner(self.store, CrashBeforeDispatch())
        with self.assertRaises(SystemExit):
            self.launch()
        launches = [item for item in self.store.snapshot('p')['records'] if item['ref']['type'] == 'operation' and item['record']['kind'] == 'task.start']
        launch = launches[0]
        self.assertEqual(launch['record']['status'], 'claimed')
        self.assertTrue(launch['record']['result']['jobId'])
        self.runner = OperationsRunner(self.store)
        observed = self.follow(launch, 'task.inspect')['record']['result']
        self.assertEqual(observed['taskStatus'], 'unknown')
        self.assertFalse((self.repo / 'invocations.txt').exists())
        with self.assertRaises(RwsError):
            self.runner.execute(launch['ref'])

    def test_lost_launch_response_recovers_the_same_completed_job(self):
        class LoseLaunchReceipt:
            def perform(self, *args):
                SubprocessTransport().perform(*args)
                raise TransportError('Receipt was lost after dispatch', uncertain=True)
        self.runner = OperationsRunner(self.store, LoseLaunchReceipt())
        _, _, launch = self.launch(seconds=.1)
        self.assertEqual(launch['record']['status'], 'unknown')
        time.sleep(.2)
        self.runner = OperationsRunner(self.store)
        observed = self.follow(launch, 'task.inspect')['record']['result']
        self.assertEqual(observed['taskStatus'], 'completed')
        self.assertEqual(observed['jobId'], launch['record']['result']['jobId'])
        self.assertEqual((self.repo / 'invocations.txt').read_text(), 'once\n')

    def test_ssh_is_mocked_and_shell_quoted_without_interpolated_parameters(self):
        observed = []
        def mock(command, **kwargs):
            observed.append((command, kwargs))
            return SimpleNamespace(returncode=0, stdout=json.dumps({'ok': True, 'result': {'stdout': 'fixture'}}))
        payload = {'kind': 'git.inspect', 'repositoryPath': "/work/it's a repo; echo unsafe"}
        result = SubprocessTransport(mock).perform({'transport': 'ssh', 'sshAlias': 'research-server'}, '/opt/python3', payload)
        command, kwargs = observed[0]
        self.assertEqual(command[:7], ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '--', 'research-server'])
        self.assertEqual(shlex.split(command[-1])[:2], ['/opt/python3', '-c'])
        self.assertNotIn(payload['repositoryPath'], command[-1])
        self.assertEqual(json.loads(kwargs['input']), payload)
        self.assertEqual(result['stdout'], 'fixture')
        with self.assertRaises(TransportError):
            SubprocessTransport(mock).perform({'transport': 'ssh', 'sshAlias': 'server; touch bad'}, 'python3', payload)
        self.assertEqual(len(observed), 1)


if __name__ == '__main__':
    unittest.main()
