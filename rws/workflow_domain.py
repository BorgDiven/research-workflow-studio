"""Versioned execution resources and reviewed operation plans; no side effects."""
import re
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from .core import dump, fail, now, ref_schema

READ_ONLY = {'git.inspect', 'task.inspect', 'task.logs', 'environment.inspect'}
ACTION_ARGUMENTS = {
    'git.inspect': {},
    'git.branch': {'name': 'string', 'startPoint': 'string'},
    'git.commit': {'message': 'string', 'paths': 'paths'},
    'git.tag': {'name': 'string', 'revision': 'string', 'message': 'string'},
    'git.push': {'remoteName': 'string', 'refspec': 'string'},
    'task.start': {'argv': 'argv', 'timeoutSeconds': 'timeout'},
    'task.inspect': {}, 'task.logs': {'stream': 'stream', 'tailLines': 'lines'},
    'task.stop': {}, 'environment.inspect': {},
}


def exact_ref(kind=None):
    schema = ref_schema(kind)
    schema['required'].append('version')
    return schema


def string(maximum=4096):
    return {'type': 'string', 'minLength': 1, 'maxLength': maximum}


def resource_schema(kind, partial=False):
    props = {'id': string(128), 'title': string(240), 'description': {'type': 'string', 'maxLength': 2000}}
    additions = {
        'server': {'transport': {'enum': ['local', 'ssh']}, 'sshAlias': string(128), 'workspaceRoot': string()},
        'repository': {'serverRef': exact_ref('server'), 'path': string(), 'remoteName': string(128),
                       'remoteUrl': string(), 'defaultBranch': string(256)},
        'environment': {'serverRef': exact_ref('server'), 'repositoryRef': exact_ref('repository'),
                        'workingDirectory': string(), 'pythonExecutable': string()}}
    required = {'server': ['transport', 'workspaceRoot'], 'repository': ['serverRef', 'path'],
                'environment': ['serverRef', 'repositoryRef', 'workingDirectory']}[kind]
    props.update(additions[kind])
    for field in ('sshAlias', 'remoteUrl', 'defaultBranch'):
        if field in props:
            props[field] = {'anyOf': [props[field], {'type': 'null'}]}
    full = {'type': 'object', 'properties': props, 'required': ['title'] + required, 'additionalProperties': False}
    if partial:
        return {'type': 'object', 'properties': props, 'additionalProperties': False,
                'anyOf': [{'required': ['id']}, full]}
    return full


def safe_path(value, root=None, relative=False):
    if any(c in value for c in ('\x00', '\n', '\r', '\\')):
        fail('Paths must be explicit POSIX paths without control characters.')
    path = PurePosixPath(value)
    if '..' in path.parts or path.is_absolute() == relative:
        fail('Use a relative checkout path.' if relative else 'Use an absolute workspace path without traversal.')
    if root:
        try:
            path.relative_to(PurePosixPath(root))
        except ValueError:
            fail('Path lies outside the registered workspace.')
    return str(path)


def safe_name(value, label='name'):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,255}', value) or any(part in value for part in ('..', '//', '@{')) or value.endswith(('/', '.', '.lock')):
        fail(label + ' is not a supported literal Git/SSH name.')


def safe_remote(value):
    if re.fullmatch(r'git@[A-Za-z0-9.-]+:[A-Za-z0-9_./-]+', value):
        return
    if any(character.isspace() for character in value):
        fail('remoteUrl cannot contain whitespace.')
    try:
        parsed = urlsplit(value)
    except ValueError:
        fail('remoteUrl is malformed.')
    if parsed.scheme not in ('https', 'http', 'ssh') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        fail('remoteUrl must be a credential-free repository URL or git@host:path; use the SSH alias for authentication.')


def validate_resource(store, conn, kind, record, pid):
    for field in ('sshAlias', 'remoteUrl', 'defaultBranch'):
        if field in record and record[field] is None:
            record.pop(field)
    if kind == 'server':
        record['workspaceRoot'] = safe_path(record['workspaceRoot'])
        if record['transport'] == 'ssh':
            alias = record.get('sshAlias', '')
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', alias):
                fail('SSH servers require one configured SSH alias, not credentials or a shell command.')
        elif record.get('sshAlias'):
            fail('A local server must not declare an SSH alias.')
    elif kind == 'repository':
        server = store._get(conn, record['serverRef'], ['server'], pid)['record']
        record['path'] = safe_path(record['path'], server['workspaceRoot'])
        record.setdefault('remoteName', 'origin')
        safe_name(record['remoteName'], 'remoteName')
        if record.get('remoteUrl'):
            if record['remoteUrl'].startswith('/') and server['transport'] == 'local':
                record['remoteUrl'] = safe_path(record['remoteUrl'], server['workspaceRoot'])
            else:
                safe_remote(record['remoteUrl'])
        if record.get('defaultBranch'):
            safe_name(record['defaultBranch'], 'defaultBranch')
    else:
        server = store._get(conn, record['serverRef'], ['server'], pid)['record']
        repository = store._get(conn, record['repositoryRef'], ['repository'], pid)['record']
        if repository['serverRef'] != record['serverRef']:
            fail('Environment and checkout must pin the same server revision.')
        record['workingDirectory'] = safe_path(record['workingDirectory'], repository['path'])
        safe_path(record['workingDirectory'], server['workspaceRoot'])
        record.setdefault('pythonExecutable', 'python3')
        if not re.fullmatch(r'[A-Za-z0-9_./-]+', record['pythonExecutable']) or record['pythonExecutable'].startswith('-'):
            fail('pythonExecutable must be one executable path/name, without shell prefixes or arguments.')


def validate_code_repository(store, conn, record, pid):
    repository = store._get(conn, record['repositoryRef'], ['repository'], pid)['record']
    if record.get('repository') not in (repository['path'], repository.get('remoteUrl')):
        fail('Code repository identity must equal the registered checkout path or remote URL.')


def validate_run_resources(store, conn, record, pid):
    repository = None
    if record.get('repositoryRef'):
        repository = store._get(conn, record['repositoryRef'], ['repository'], pid)
    if record.get('environmentRef'):
        environment = store._get(conn, record['environmentRef'], ['environment'], pid)
        if not repository or environment['record']['repositoryRef'] != repository['ref']:
            fail('A run environment requires its exact repositoryRef.')
    if repository and record.get('codeRef'):
        code = store._get(conn, record['codeRef'], ['code'])['record']
        if code.get('repositoryRef') and code['repositoryRef'] != repository['ref']:
            fail('Run and implementation must pin the same registered checkout.')
        identity = code.get('repository')
        if identity and identity not in (repository['record']['path'], repository['record'].get('remoteUrl')):
            fail('Run checkout does not match its implementation repository.')


def result_schema():
    props = {k: string() for k in ('jobId', 'processStart', 'jobDirectory', 'receiptPath', 'stdoutPath',
             'stderrPath', 'observedAt', 'startedAt', 'finishedAt', 'checkedAt', 'headCommit', 'branch',
             'tag', 'remoteName', 'refspec', 'workingDirectory', 'message')}
    props.update(stdout={'type': 'string', 'maxLength': 16384}, stderr={'type': 'string', 'maxLength': 16384},
                 exitCode={'type': 'integer'}, pid={'type': 'integer', 'minimum': 1},
                 processGroupId={'type': 'integer', 'minimum': 1},
                 argv={'type': 'array', 'minItems': 1, 'maxItems': 128, 'items': string()},
                 taskStatus={'enum': ['running', 'completed', 'failed', 'unknown', 'partial']})
    for name, kind in (('codeRef', 'code'), ('environmentRef', 'environment'), ('repositoryRef', 'repository')):
        props[name] = exact_ref(kind)
    return {'type': 'object', 'properties': props, 'additionalProperties': False}


def _definition(name, props, required, description):
    return {'name': name, 'description': description,
            'inputSchema': {'type': 'object', 'properties': props, 'required': required, 'additionalProperties': False},
            'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': True, 'openWorldHint': False}}


def operation_definitions(common):
    records = []
    required_arguments = {'git.branch': ['name'], 'git.commit': ['message', 'paths'], 'git.tag': ['name'],
                          'git.push': ['remoteName', 'refspec'], 'task.start': ['argv'], 'task.logs': ['stream']}
    for kind, fields in ACTION_ARGUMENTS.items():
        props = {}
        for name, typ in fields.items():
            props[name] = {'string': string(), 'paths': {'type': 'array', 'minItems': 1, 'maxItems': 128, 'items': string()},
                          'argv': {'type': 'array', 'minItems': 1, 'maxItems': 128, 'items': string()},
                          'timeout': {'type': 'number', 'minimum': 0.1, 'maximum': 604800},
                          'stream': {'enum': ['stdout', 'stderr']},
                          'lines': {'type': 'integer', 'minimum': 1, 'maximum': 1000}}[typ]
        required_refs = (['repositoryRef'] if kind.startswith('git.') else ['runRef', 'environmentRef'] if kind == 'task.start'
                         else ['environmentRef'] if kind == 'environment.inspect' else ['launchOperationRef'])
        record = {'type': 'object', 'properties': {'id': string(128), 'title': string(240), 'kind': {'const': kind},
                  'arguments': {'type': 'object', 'properties': props, 'required': required_arguments.get(kind, []), 'additionalProperties': False}},
                  'required': ['title', 'kind', 'arguments'] + required_refs, 'additionalProperties': False}
        for field in required_refs:
            record['properties'][field] = exact_ref({'launchOperationRef': 'operation'}.get(field, field[:-3]))
        records.append(record)
    return [
        _definition('rws_operation_propose', dict(common, record={'oneOf': records}), list(common) + ['record'],
                    'Propose a literal reviewed Git/task operation. No execution occurs. Read-only inspections may be claimed by an explicit local runner; workspace/process mutations need exact human approval.'),
        *[_definition('rws_operation_' + action, dict(common, operationRef=exact_ref('operation')),
                     list(common) + ['operationRef'], 'Human only: ' + action + ' this exact operation plan. Approval never launches it.')
          for action in ('approve', 'dismiss')]]


def runner_definitions():
    common = {'projectId': string(128), 'expectedRevision': {'type': 'integer', 'minimum': 1},
              'requestId': string(128), 'operationRef': exact_ref('operation'), 'claimId': string(128)}
    return [_definition('_rws_operation_claim', dict(common, runnerId=string(160)),
                        list(common) + ['runnerId'], 'Private atomic runner claim.'),
            _definition('_rws_operation_update', dict(common,
                        status={'enum': ['running', 'completed', 'failed', 'unknown']}, result=result_schema()),
                        list(common) + ['status', 'result'], 'Private runner observation update.')]


def _latest_operation(store, conn, ref, pid):
    env = store._get(conn, ref, ['operation'], pid)
    latest = store._get(conn, {k: v for k, v in ref.items() if k != 'version'}, ['operation'], pid)
    if env['ref'] != latest['ref']:
        fail('Operation changed; review or observe the exact current revision.', 'revision_conflict', {'currentRef': latest['ref']})
    return env


def _validate_plan(store, conn, record, pid):
    kind, args = record['kind'], record['arguments']
    if kind.startswith('git.'):
        repository = store._get(conn, record['repositoryRef'], ['repository'], pid)
        record['serverRef'] = repository['record']['serverRef']
        for field in ('name', 'startPoint', 'revision'):
            if field in args:
                safe_name(args[field], field)
        if kind == 'git.commit':
            for path in args['paths']:
                safe_path(path, relative=True)
                if path.startswith('-') or path in ('.', '') or any(c in path for c in '*?[]'):
                    fail('A commit must name explicit relative file paths.')
        if kind == 'git.push':
            if not repository['record'].get('remoteUrl'):
                fail('Push requires a fixed registered remoteUrl; register its exact destination before proposing a push.')
            if args['remoteName'] != repository['record']['remoteName']:
                fail('Push remote must match the registered remoteName.')
            parts = args['refspec'].split(':')
            if len(parts) > 2 or any(not p for p in parts):
                fail('Only a non-deleting literal push refspec is supported.')
            for part in parts:
                safe_name(part, 'refspec')
    elif kind in ('task.start', 'environment.inspect'):
        environment = store._get(conn, record['environmentRef'], ['environment'], pid)
        record['repositoryRef'] = environment['record']['repositoryRef']
        record['serverRef'] = environment['record']['serverRef']
        if kind == 'task.start':
            run = store._get(conn, record['runRef'], ['run'], pid)
            current = store._get(conn, {k: v for k, v in run['ref'].items() if k != 'version'}, ['run'], pid)
            if current['record']['status'] != 'planned':
                fail('Launch requires a fresh planned run. An unknown/previous run must be inspected, never silently restarted.')
            if run['record'].get('environmentRef') != environment['ref'] or run['record'].get('repositoryRef') != record['repositoryRef']:
                fail('Launch must use the run\'s pinned environment and repository.')
            code = store._get(conn, run['record'].get('codeRef'), ['code'])
            if not re.fullmatch(r'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})', code['record'].get('commit', '')):
                fail('Launch needs a full immutable Git commit ID; branches, tags and unknown revisions cannot launch.')
            record['codeRef'] = code['ref']
            if any('\x00' in arg or '\n' in arg or '\r' in arg for arg in args['argv']):
                fail('Launch argv cannot contain control characters.')
            if any(re.search(r'(?i)(?:^|[-_])(password|token|secret|api[-_]?key)(?:=|$)', arg) for arg in args['argv']):
                fail('Do not put credentials into stored command arguments; configure them outside the workbench.')
    else:
        launch = store._get(conn, record['launchOperationRef'], ['operation'], pid)
        if launch['record']['kind'] != 'task.start':
            fail('Task inspection/log/stop must reference the original launch operation.')
        for field in ('runRef', 'environmentRef', 'repositoryRef', 'serverRef', 'codeRef'):
            record[field] = launch['record'][field]
        if kind == 'task.stop' and not launch['record'].get('result', {}).get('jobId'):
            fail('A stop plan needs the launch revision containing the observed job identity.')


def _update_run_status(store, conn, operation, status, pid):
    if not operation.get('runRef'):
        return
    ref = {k: v for k, v in operation['runRef'].items() if k != 'version'}
    run = store._get(conn, ref, ['run'], pid)
    if run['record'].get('status') in ('completed', 'failed', 'partial'):
        return  # A later lost connection or stale poll cannot undo observed completion.
    if run['record'].get('status') != status:
        record = dict(run['record'], status=status)
        store._put(conn, pid, 'run', record)


def mutate_operation(store, conn, name, args, actor, project):
    pid = project['id']
    if name == 'rws_operation_propose':
        record = store._freeze(conn, args['record'])
        if record.get('id') and conn.execute('SELECT 1 FROM records WHERE project_id=? AND type=? AND id=?', (pid, 'operation', record['id'])).fetchone():
            fail('Operation plans cannot be edited; dismiss this plan and propose a new one.', 'immutable_source')
        _validate_plan(store, conn, record, pid)
        record.update(status='proposed', policy='read-only' if record['kind'] in READ_ONLY else 'mutation',
                      proposedAt=now(), result={})
        return store._put(conn, pid, 'operation', record)
    env = _latest_operation(store, conn, args['operationRef'], pid)
    record = dict(env['record'])
    if name in ('rws_operation_approve', 'rws_operation_dismiss'):
        if record['status'] != 'proposed':
            fail('Only a proposed operation can be approved or dismissed.', 'conflict')
        record['status'] = 'approved' if name.endswith('approve') else 'dismissed'
        record['reviewedPlanRef'] = env['ref']
        record['reviewedAt'] = now()
    elif name == '_rws_operation_claim':
        if actor != 'runner':
            fail('Runner authority is required.', 'permission_denied')
        allowed = ('proposed', 'approved') if record['policy'] == 'read-only' else ('approved',)
        if record['status'] not in allowed:
            fail('Operation is not claimable; claimed or unknown work must be inspected instead of relaunched.', 'conflict')
        if record['kind'] == 'task.start':
            for other in store._latest(conn, pid):
                r = other['record']
                if other['ref']['type'] == 'operation' and other['ref']['id'] != env['ref']['id'] and r.get('kind') == 'task.start' and r.get('runRef', {}).get('id') == record['runRef']['id'] and r.get('status') in ('claimed', 'running', 'completed', 'failed', 'unknown'):
                    fail('This run already has a claimed launch. Inspect its original task.', 'conflict')
            run = store._get(conn, {k: v for k, v in record['runRef'].items() if k != 'version'}, ['run'], pid)
            if run['record'].get('status') != 'planned':
                fail('A non-planned run cannot be launched again.', 'conflict')
            job_id = 'job-' + record['id']
            record['result'] = {'jobId': job_id, 'processStart': args['claimId'],
                                'codeRef': record['codeRef'], 'repositoryRef': record['repositoryRef'],
                                'environmentRef': record['environmentRef']}
        record.update(status='claimed', claimId=args['claimId'], runnerId=args['runnerId'], claimedAt=now())
    elif name == '_rws_operation_update':
        if actor != 'runner' or record.get('claimId') != args['claimId']:
            fail('The original runner claim is required.', 'permission_denied')
        if record['status'] not in ('claimed', 'running', 'unknown'):
            fail('A finished operation cannot be rewritten.', 'conflict')
        previous = record.get('result', {})
        result = store._freeze(conn, args['result'])
        for key in ('jobId', 'pid', 'processGroupId', 'processStart', 'codeRef', 'repositoryRef', 'environmentRef'):
            if key in previous and key in result and previous[key] != result[key]:
                fail('Observed task identity cannot be rebound.', 'immutable_source', {'field': key})
        for key in ('codeRef', 'repositoryRef', 'environmentRef'):
            if key in result and result[key] != record.get(key):
                fail('Runner result must retain the reviewed resource/implementation binding.')
        if record.get('launchOperationRef'):
            launch_ref = {k: v for k, v in record['launchOperationRef'].items() if k != 'version'}
            launch = store._get(conn, launch_ref, ['operation'], pid)['record']
            for key in ('jobId', 'pid', 'processGroupId', 'processStart'):
                pinned = launch.get('result', {}).get(key)
                if pinned is not None and key in result and pinned != result[key]:
                    fail('Task observation does not identify the pinned launch job.', 'immutable_source', {'field': key})
        record['result'] = dict(previous, **result)
        record.update(status=args['status'], observedAt=result.get('observedAt', now()))
        if record['kind'] == 'task.start':
            _update_run_status(store, conn, record, result.get('taskStatus', args['status']), pid)
        elif record['kind'] in ('task.inspect', 'task.stop') and result.get('taskStatus'):
            _update_run_status(store, conn, record, result['taskStatus'], pid)
    else:
        fail('Unknown operation transition.')
    return store._put(conn, pid, 'operation', record)
