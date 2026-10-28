"""Standard-library transport payload. This file may run under a registered SSH alias."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from datetime import datetime, timezone


SUPERVISOR = r'''
import json, os, signal, subprocess, sys, time
from pathlib import Path
from datetime import datetime, timezone
root = Path(sys.argv[1])
request = json.loads((root / 'request.json').read_text())
def now(): return datetime.now(timezone.utc).isoformat()
state = {'jobId': request['jobId'], 'pid': os.getpid(), 'processStart': request['token'],
         'startedAt': now(), 'taskStatus': 'running'}
def save():
    temporary = root / 'receipt.tmp'
    temporary.write_text(json.dumps(state))
    temporary.replace(root / 'receipt.json')
save()
try:
    with (root / 'stdout.log').open('ab', buffering=0) as stdout, (root / 'stderr.log').open('ab', buffering=0) as stderr:
        child = subprocess.Popen(request['argv'], cwd=request['cwd'], stdout=stdout, stderr=stderr, start_new_session=True)
        started = time.monotonic()
        terminated = False
        while child.poll() is None:
            stop = root / 'stop.json'
            requested = False
            if stop.exists():
                try: requested = json.loads(stop.read_text()).get('token') == request['token']
                except (ValueError, OSError): pass
            timed_out = request.get('timeoutSeconds') and time.monotonic() - started >= request['timeoutSeconds']
            if requested or timed_out:
                terminated = True
                state['message'] = 'Stopped by an approved operation.' if requested else 'Configured timeout reached.'
                try: os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError: pass
                try: child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try: os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    child.wait()
                break
            time.sleep(.05)
        state['exitCode'] = child.wait()
        state['taskStatus'] = 'partial' if terminated else ('completed' if state['exitCode'] == 0 else 'failed')
except Exception as error:
    state.update(taskStatus='failed', message=type(error).__name__ + ': ' + str(error)[:1000])
state['finishedAt'] = now()
save()
'''


def now():
    return datetime.now(timezone.utc).isoformat()


def within(path, root):
    value, base = Path(path).resolve(), Path(root).resolve()
    if not value.is_relative_to(base):
        raise ValueError('Path is outside the registered workspace or repository.')
    return value


def run(argv, cwd, timeout=30):
    return subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True,
                          timeout=timeout, stdin=subprocess.DEVNULL)


def git(repo, *args, timeout=30):
    result = run(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false',
                  '-C', str(repo), *args], repo, timeout)
    if result.returncode:
        raise ValueError('Git command failed: ' + result.stderr[-2000:].strip())
    return result.stdout.strip()


def revision(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]*', value):
        raise ValueError('Use an explicit commit or ordinary branch/tag name.')
    return value


def safe_paths(paths, repo):
    if not isinstance(paths, list) or not paths:
        raise ValueError('Commit requires an explicit nonempty path list.')
    for name in paths:
        if not isinstance(name, str) or not name or name.startswith(('-', ':')) or Path(name).is_absolute():
            raise ValueError('Commit paths must be literal repository-relative paths.')
        if '..' in Path(name).parts or not Path(name).parts or name in ('.', './'):
            raise ValueError('Commit must name bounded files or subdirectories.')
        within(repo / name, repo)
    return paths


def receipt(root, expected):
    file = root / 'receipt.json'
    def read_state():
        if file.is_symlink():
            raise ValueError('A supervisor receipt cannot be a symbolic link.')
        within(file, root)
        if not file.exists():
            return dict(expected, taskStatus='unknown', message='No durable supervisor receipt; do not relaunch.')
        state = json.loads(file.read_text())
        if state.get('jobId') != expected['jobId'] or (expected.get('processStart') and state.get('processStart') != expected['processStart']):
            raise ValueError('Job receipt identity does not match the approved launch.')
        return state
    state = read_state()
    if state.get('taskStatus') == 'running':
        try:
            os.kill(state['pid'], 0)
        except ProcessLookupError:
            state.update(taskStatus='unknown', message='Supervisor disappeared without a final receipt; do not relaunch.')
        except PermissionError:
            state.update(taskStatus='unknown', message='Supervisor status could not be established.')
        if state.get('taskStatus') == 'running':
            command = run(['ps', '-p', str(state['pid']), '-o', 'args='], root)
            if command.returncode or str(root / 'supervisor.py') not in command.stdout:
                state.update(taskStatus='unknown', message='Supervisor process identity is no longer confirmed.')
        if state.get('taskStatus') == 'unknown':
            # The supervisor writes its final receipt before exiting. It may have
            # done both after our first read but before the process identity check.
            latest = read_state()
            if latest.get('taskStatus') in ('completed', 'failed', 'partial'):
                state = latest
    return dict(state, checkedAt=now())


def execute(payload):
    operation, arguments = payload['kind'], payload.get('arguments', {})
    workspace = Path(payload['workspaceRoot']).resolve()
    repo = within(payload['repositoryPath'], workspace)
    if not repo.is_dir():
        raise ValueError('Registered repository directory does not exist.')
    if (operation.startswith('git.') or operation == 'task.start') and Path(git(repo, 'rev-parse', '--show-toplevel')).resolve() != repo:
        raise ValueError('Registered repository must be the Git worktree root.')
    cwd = within(payload.get('workingDirectory', str(repo)), repo)
    if not cwd.is_dir():
        raise ValueError('Registered working directory does not exist.')
    if operation == 'environment.inspect':
        return {'workingDirectory': str(cwd), 'stdout': sys.version,
                'message': 'Resolved Python interpreter: ' + sys.executable, 'checkedAt': now()}
    if operation.startswith('git.'):
        result = {'workingDirectory': str(repo), 'checkedAt': now()}
        if operation == 'git.inspect':
            result.update(headCommit=git(repo, 'rev-parse', '--verify', 'HEAD'),
                          stdout=git(repo, 'status', '--short')[:16384])
            branch = git(repo, 'branch', '--show-current')
            if branch:
                result['branch'] = branch
        elif operation == 'git.branch':
            name = revision(arguments['name'])
            git(repo, 'check-ref-format', '--branch', name)
            start = revision(arguments.get('startPoint', 'HEAD'))
            commit = git(repo, 'rev-parse', '--verify', start + '^{commit}')
            git(repo, 'branch', '--', name, commit)
            result.update(branch=name, headCommit=commit)
        elif operation == 'git.commit':
            paths = safe_paths(arguments['paths'], repo)
            staged = git(repo, 'diff', '--cached', '--name-only').splitlines()
            if any(not any(path == scope or path.startswith(scope.rstrip('/') + '/') for scope in paths) for path in staged):
                raise ValueError('Unrelated staged changes exist; review the index before committing.')
            git(repo, 'add', '--', *paths)
            result['stdout'] = git(repo, 'commit', '--only', '-m', arguments['message'], '--', *paths)[-16384:]
            result['headCommit'] = git(repo, 'rev-parse', '--verify', 'HEAD')
        elif operation == 'git.tag':
            name, target = revision(arguments['name']), revision(arguments.get('revision', 'HEAD'))
            git(repo, 'check-ref-format', 'refs/tags/' + name)
            commit = git(repo, 'rev-parse', '--verify', target + '^{commit}')
            args = ['tag', '-a', name, '-m', arguments['message'], commit] if arguments.get('message') else ['tag', name, commit]
            git(repo, *args)
            result.update(tag=name, headCommit=commit)
        elif operation == 'git.push':
            remote = arguments['remoteName']
            if remote != payload.get('remoteName', 'origin') or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', remote):
                raise ValueError('Push must use the registered remote name.')
            refspec = arguments['refspec']
            if not isinstance(refspec, str) or not re.fullmatch(r'refs/(heads|tags)/[A-Za-z0-9_./-]+:refs/(heads|tags)/[A-Za-z0-9_./-]+', refspec):
                raise ValueError('Push requires an explicit non-force source:destination refspec.')
            source, destination = refspec.split(':')
            if source.split('/')[1] != destination.split('/')[1]:
                raise ValueError('Push cannot change a branch into a tag or vice versa.')
            git(repo, 'check-ref-format', source)
            git(repo, 'check-ref-format', destination)
            configured = git(repo, 'remote', 'get-url', '--push', '--all', remote).splitlines()
            if not payload.get('remoteUrl'):
                raise ValueError('Push requires an explicitly registered destination URL or local mirror path.')
            if configured != [payload['remoteUrl']]:
                raise ValueError('Push requires exactly one destination matching its registered URL.')
            if Path(payload['remoteUrl']).is_absolute():
                within(payload['remoteUrl'], workspace)
            result['stdout'] = git(repo, 'push', '--porcelain', '--', remote, refspec, timeout=60)[-16384:]
            result.update(remoteName=remote, refspec=refspec)
        else:
            raise ValueError('Unsupported Git operation.')
        return result
    job = payload['job']
    jobs = within(cwd / '.rws-jobs', repo)
    root = within(jobs / job['jobId'], jobs)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,180}', job['jobId']):
        raise ValueError('Invalid job identity.')
    paths = {'jobId': job['jobId'], 'receiptPath': str(root / 'receipt.json'),
             'stdoutPath': str(root / 'stdout.log'), 'stderrPath': str(root / 'stderr.log'),
             'workingDirectory': str(cwd)}
    if operation == 'task.start':
        expected = payload['codeCommit']
        if git(repo, 'rev-parse', '--verify', 'HEAD') != git(repo, 'rev-parse', '--verify', revision(expected) + '^{commit}'):
            raise ValueError('Repository HEAD differs from the fixed code commit; synchronize explicitly before launching.')
        if git(repo, 'status', '--porcelain', '--untracked-files=no'):
            raise ValueError('Tracked working tree changes differ from the fixed code commit.')
        argv = arguments['argv']
        if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) or '\0' in arg for arg in argv):
            raise ValueError('Task argv must be a nonempty string array.')
        module_name = payload['codeModulePath']
        if Path(module_name).is_absolute() or '..' in Path(module_name).parts or not module_name.endswith('.py'):
            raise ValueError('Registered modulePath must be a repository-relative Python file.')
        source_path = repo
        for part in Path(module_name).parts:
            source_path = source_path / part
            if source_path.is_symlink():
                raise ValueError('The registered Python source and its package directories cannot be symbolic links.')
        module = within(source_path, repo)
        git(repo, 'cat-file', '-e', expected + ':' + module_name)
        if not module.is_file() or argv[0] != payload['pythonExecutable'] or len(argv) < 2:
            raise ValueError('Only the registered environment Python and exact module entrypoint can launch.')
        if argv[1] == '-m':
            if not module.is_relative_to(cwd) or len(argv) < 3 or argv[2] != str(module.relative_to(cwd).with_suffix('')).replace(os.sep, '.'):
                raise ValueError('Python -m must name the registered code module.')
        elif argv[1].startswith('-') or within(cwd / argv[1], repo) != module:
            raise ValueError('Only a direct Python script or its exact -m module is supported; no shell, -c or launcher.')
        # Resolve a configured name such as python3 once. Running in the checkout
        # must not resolve it again through a cwd-dependent PATH.
        argv = [sys.executable, *argv[1:]]
        jobs.mkdir(mode=0o700, exist_ok=True)
        root.mkdir(mode=0o700)  # Exclusive launch fence; existing/uncertain jobs are never started twice.
        request = dict(job, argv=argv, cwd=str(cwd), timeoutSeconds=arguments.get('timeoutSeconds'))
        (root / 'request.json').write_text(json.dumps(request))
        (root / 'supervisor.py').write_text(SUPERVISOR)
        with (root / 'supervisor.log').open('ab') as log:
            process = subprocess.Popen([sys.executable, str(root / 'supervisor.py'), str(root)],
                cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, close_fds=True)
        deadline = time.monotonic() + 2
        while not (root / 'receipt.json').exists() and time.monotonic() < deadline and process.poll() is None:
            time.sleep(.02)
        observed = receipt(root, {'jobId': job['jobId'], 'processStart': job['token']})
        return dict(paths, **observed, argv=argv)
    expected = dict(jobId=job['jobId'], processStart=job.get('processStart'))
    if operation == 'task.logs':
        identity = receipt(root, expected)
        if not (root / 'receipt.json').is_file():
            return dict(paths, **identity)
        stream = arguments.get('stream', 'stdout')
        if stream not in ('stdout', 'stderr'):
            raise ValueError('Unknown log stream.')
        lines = arguments.get('tailLines', 100)
        if isinstance(lines, bool) or not isinstance(lines, int) or not 1 <= lines <= 1000:
            raise ValueError('tailLines must be between 1 and 1000.')
        file = within(root / (stream + '.log'), root)
        content = ''
        if file.exists():
            with file.open('rb') as handle:
                handle.seek(max(0, file.stat().st_size - 65536))
                content = '\n'.join(handle.read().decode('utf-8', 'replace').splitlines()[-lines:])[-16384:]
        return dict(paths, **{stream: content}, checkedAt=now())
    observed = receipt(root, expected)
    if operation == 'task.stop' and observed.get('taskStatus') == 'running':
        stop = root / 'stop.json'
        if stop.is_symlink():
            raise ValueError('Stop control file cannot be a symbolic link.')
        within(stop, root)
        try:
            descriptor = os.open(str(stop), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if json.loads(stop.read_text()).get('token') != observed['processStart']:
                raise ValueError('An existing stop request belongs to another job identity.')
        else:
            with os.fdopen(descriptor, 'w') as handle:
                json.dump({'token': observed['processStart']}, handle)
        deadline = time.monotonic() + 5
        while True:
            observed = receipt(root, expected)
            if observed.get('taskStatus') in ('completed', 'failed', 'partial'):
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                observed.update(taskStatus='unknown', message='Stop request saved but termination is not confirmed.')
                break
            time.sleep(min(.05, remaining))
    elif operation != 'task.inspect' and operation != 'task.stop':
        raise ValueError('Unsupported task operation.')
    return dict(paths, **observed)


def main():
    os.umask(0o077)
    payload = json.load(sys.stdin)
    try:
        result = execute(payload)
        print(json.dumps({'ok': True, 'result': result}))
    except Exception as error:
        uncertain = isinstance(error, subprocess.TimeoutExpired) or payload.get('kind') == 'git.push'
        print(json.dumps({'ok': False, 'uncertain': uncertain,
                          'error': type(error).__name__ + ': ' + str(error)[:2000]}))


if __name__ == '__main__':
    main()
