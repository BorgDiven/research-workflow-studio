"""Explicit CLI execution of exact approved plans; never called from MCP or HTTP."""
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import uuid

from .core import RwsError


class TransportError(RuntimeError):
    def __init__(self, message, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


class SubprocessTransport:
    def __init__(self, invoke=subprocess.run):
        self.invoke = invoke

    def perform(self, server, executable, payload):
        source = Path(__file__).with_name('operations_worker.py').read_text(encoding='utf-8')
        command = [executable, '-c', source]
        if server['transport'] == 'ssh':
            alias = server.get('sshAlias', '')
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', alias):
                raise TransportError('Use an existing SSH alias without options or credentials.')
            command = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '--', alias, shlex.join(command)]
        elif server['transport'] != 'local':
            raise TransportError('Unsupported server transport.')
        try:
            process = self.invoke(command, input=json.dumps(payload), text=True, capture_output=True, timeout=90)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise TransportError('Transport did not return a confirmed receipt; inspect this operation before any further action.', uncertain=True) from error
        if process.returncode:
            raise TransportError('Transport exited without a confirmed receipt; no automatic retry.', uncertain=True)
        try:
            result = json.loads(process.stdout)
        except (TypeError, ValueError) as error:
            raise TransportError('Transport returned no valid receipt; no automatic retry.', uncertain=True) from error
        if not isinstance(result, dict) or 'ok' not in result:
            raise TransportError('Transport returned an invalid receipt; no automatic retry.', uncertain=True)
        if not result.get('ok'):
            raise TransportError(result.get('error', 'Operation failed.'), uncertain=result.get('uncertain', False))
        if not isinstance(result.get('result'), dict):
            raise TransportError('Transport omitted the result receipt; no automatic retry.', uncertain=True)
        return result['result']


class OperationsRunner:
    def __init__(self, store, transport=None, runner_id=None):
        self.store = store
        self.transport = transport or SubprocessTransport()
        self.runner_id = runner_id or 'cli-' + uuid.uuid4().hex

    def _read(self, ref, latest=False):
        target = {key: value for key, value in ref.items() if key != 'version'} if latest else ref
        return self.store.call('rws_record_get', {'ref': target})['result']

    def _revision(self, project_id):
        return next(p['revision'] for p in self.store.call('rws_project_list', {})['result'] if p['id'] == project_id)

    def _write(self, action, ref, **fields):
        request_id = 'runner-' + uuid.uuid4().hex
        for attempt in range(3):
            args = dict(projectId=ref['projectId'], expectedRevision=self._revision(ref['projectId']),
                        requestId=request_id, operationRef=ref, **fields)
            try:
                return self.store.runner_call(action, args)
            except RwsError as error:
                if error.code != 'revision_conflict' or attempt == 2:
                    raise

    def _payload(self, envelope, claim_id):
        record = envelope['record']
        operation = record['kind']
        launch = self._read(record['launchOperationRef'], latest=True) if record.get('launchOperationRef') else None
        origin = launch['record'] if launch else record
        environment = self._read(origin['environmentRef'])['record'] if origin.get('environmentRef') else None
        repository_ref = origin.get('repositoryRef') or (environment or {}).get('repositoryRef')
        repository = self._read(repository_ref)['record']
        server = self._read(repository['serverRef'])['record']
        if environment and environment['serverRef'] != repository['serverRef']:
            raise ValueError('Environment and repository must refer to the same fixed server.')
        if environment and origin.get('repositoryRef') and environment['repositoryRef'] != origin['repositoryRef']:
            raise ValueError('Operation repository differs from its fixed environment.')
        payload = {'kind': operation, 'arguments': record.get('arguments', {}),
                   'workspaceRoot': server['workspaceRoot'], 'repositoryPath': repository['path'],
                   'remoteName': repository.get('remoteName', 'origin'), 'remoteUrl': repository.get('remoteUrl'),
                   'workingDirectory': (environment or {}).get('workingDirectory', repository['path'])}
        if operation == 'task.start':
            run = self._read(record['runRef'])['record']
            if run.get('environmentRef') != record.get('environmentRef') or run.get('repositoryRef') != repository_ref:
                raise ValueError('Launch must retain the run fixed environment and repository.')
            code = self._read(run['codeRef'])['record']
            source = code.get('source', {})
            commit = code.get('commit') or (source.get('commit') if isinstance(source, dict) else None)
            module = code.get('modulePath') or (source.get('modulePath') if isinstance(source, dict) else None)
            if not commit or not module:
                raise ValueError('Launch requires the registered Git commit and Python modulePath.')
            if code.get('repositoryRef') and code['repositoryRef'] != repository_ref:
                raise ValueError('Code belongs to a different registered repository.')
            payload['codeCommit'] = commit
            payload['codeModulePath'] = module
            payload['job'] = {'jobId': 'job-' + record['id'], 'token': claim_id}
        elif launch:
            prior = origin.get('result', {})
            if not prior.get('jobId'):
                raise ValueError('Launch has no durable job identity to inspect.')
            payload['job'] = {key: prior[key] for key in ('jobId', 'processStart') if key in prior}
        executable = (environment or {}).get('pythonExecutable') or (sys.executable if server['transport'] == 'local' else 'python3')
        payload['pythonExecutable'] = executable
        return server, executable, payload

    def execute(self, operation_ref):
        """Claim once, perform once, then record evidence. Unknown work is never relaunched."""
        envelope = self._read(operation_ref)
        claim_id = 'claim-' + uuid.uuid4().hex
        # Validation is read-only; the backend atomically checks exact approval before effects.
        server, executable, payload = self._payload(envelope, claim_id)
        claimed = self._write('claim', operation_ref, claimId=claim_id, runnerId=self.runner_id)
        current_ref = claimed['result']['ref']
        try:
            result = self.transport.perform(server, executable, payload)
            status = 'running' if envelope['record']['kind'] == 'task.start' and result.get('taskStatus') == 'running' else 'unknown' if result.get('taskStatus') == 'unknown' else 'failed' if result.get('taskStatus') == 'failed' else 'completed'
        except TransportError as error:
            status = 'unknown' if error.uncertain else 'failed'
            result = {'message': str(error)[:4096]}
            if envelope['record']['kind'] == 'task.start':
                from pathlib import PurePosixPath
                directory = PurePosixPath(payload['workingDirectory']) / '.rws-jobs' / payload['job']['jobId']
                result.update(jobId=payload['job']['jobId'], receiptPath=str(directory / 'receipt.json'),
                              stdoutPath=str(directory / 'stdout.log'), stderrPath=str(directory / 'stderr.log'),
                              processStart=claim_id, taskStatus=status)
        latest = self._read(current_ref, latest=True)['ref']
        return self._write('update', latest, claimId=claim_id, status=status, result=result)
