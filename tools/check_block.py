#!/usr/bin/env python3
"""Check a code contract; run two cases and a batch only with explicit --execute."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from rws.core import RwsError, record_schema, typed_result_schema, validate_schema

KNOWN_CHECKS = ('contract-valid', 'two-inputs', 'batch-equivalence',
                'input-immutability', 'declared-outputs', 'expected-values')
WORKER = '''import copy, importlib.util, json, pathlib, sys
module, function, request_file, result_file = sys.argv[1:]
sys.path.insert(0, str(pathlib.Path(module).parent))
spec = importlib.util.spec_from_file_location("checked_block", module)
block = importlib.util.module_from_spec(spec)
spec.loader.exec_module(block)
request = json.loads(pathlib.Path(request_file).read_text())
before = copy.deepcopy(request)
output = getattr(block, function)(request)
receipt = {"output": output, "requestUnchanged": request == before}
pathlib.Path(result_file).write_text(json.dumps(receipt, allow_nan=False))
'''


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'),
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Non-finite JSON number: ' + value)))


def local_file(folder, name):
    if not isinstance(name, str) or not name:
        raise ValueError('A nonempty relative filename is required.')
    path = (folder / name).resolve()
    if Path(name).is_absolute() or not path.is_relative_to(folder) or not path.is_file():
        raise ValueError('Contract files must exist inside the block directory.')
    return path


def read_contract(folder):
    contract = load_json(folder / 'contract.json')
    if not isinstance(contract, dict) or contract.get('schemaVersion') != 'rws.block-contract/v1':
        raise ValueError('Unsupported block contract schemaVersion.')
    spec = contract.get('spec')
    validate_schema(spec, record_schema('spec'), 'contract.spec')
    for field, key in (('inputs', 'name'), ('outputs', 'name'), ('acceptanceChecks', 'id')):
        ids = [row[key] for row in spec[field]]
        if len(set(ids)) != len(ids):
            raise ValueError('Contract ' + field + ' IDs must be unique.')
    if not spec['outputs'] or not spec['acceptanceChecks']:
        raise ValueError('A runnable template declares outputs and acceptance checks.')
    parts = contract.get('entrypoint', '').split(':')
    if len(parts) != 2 or not re.fullmatch(r'[A-Za-z_]\w*', parts[1]):
        raise ValueError('Entrypoint must be a local Python file and callable: block.py:run.')
    module = local_file(folder, parts[0])
    if module.suffix != '.py':
        raise ValueError('Entrypoint must identify a Python source file.')
    fixture = load_json(local_file(folder, contract.get('fixture')))
    if not isinstance(fixture, dict) or fixture.get('schemaVersion') != 'rws.block-fixtures/v1':
        raise ValueError('Unsupported fixtures schemaVersion.')
    request = fixture.get('request', {})
    if not isinstance(request, dict) or not isinstance(request.get('datasetId'), str) or not request['datasetId']:
        raise ValueError('Fixture request requires a nonempty datasetId.')
    cases = request.get('cases', [])
    if not isinstance(cases, list) or len(cases) != 2:
        raise ValueError('Fixture must contain exactly two different sample cases.')
    ids = [row.get('sampleId') for row in cases if isinstance(row, dict)]
    if len(ids) != 2 or any(not isinstance(s, str) or not s for s in ids) or len(set(ids)) != 2:
        raise ValueError('Fixture needs two unique, nonempty sampleIds.')
    if {k: v for k, v in cases[0].items() if k != 'sampleId'} == {k: v for k, v in cases[1].items() if k != 'sampleId'}:
        raise ValueError('Fixture cases must differ in input content, not just sampleId.')
    validate_schema(request.get('config', {}), spec['configSchema'], 'fixture.config')
    if not isinstance(request.get('inputs', []), list) or any(not isinstance(item, dict) or not isinstance(item.get('id'), str) for item in request.get('inputs', [])):
        raise ValueError('Fixture inputs must be an array of stored artifacts.')
    expected = fixture.get('expectedArtifacts')
    if not isinstance(expected, list) or {row.get('sampleId') for row in expected if isinstance(row, dict)} != set(ids):
        raise ValueError('Explicit expectedArtifacts must cover both fixture samples.')
    return contract, fixture, module, parts[1]


def git_identity(folder, module):
    def git(*args):
        result = subprocess.run(['git', '-C', str(folder), *args], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        return result.stdout.strip() if result.returncode == 0 else None
    root = git('rev-parse', '--show-toplevel')
    identity = {'repository': None, 'commit': None, 'modulePath': str(module.relative_to(folder)),
                'tracked': False, 'workingTreeModified': None}
    if not root:
        return identity
    root_path = Path(root).resolve()
    module_path = str(module.relative_to(root_path))
    folder_path = str(folder.relative_to(root_path))
    remote = git('remote', 'get-url', 'origin')
    # Do not copy credentials/query strings from a configured remote into a receipt.
    if remote and remote.startswith(('https://', 'http://', 'ssh://')):
        parsed = urlsplit(remote)
        remote = urlunsplit((parsed.scheme, parsed.hostname or '', parsed.path, '', ''))
    elif remote and not re.fullmatch(r'git@[A-Za-z0-9.-]+:[A-Za-z0-9_./-]+', remote):
        remote = None
    identity.update(repository=remote or root_path.name, commit=git('rev-parse', '--verify', 'HEAD'),
                    modulePath=module_path,
                    tracked=git('ls-files', '--error-unmatch', '--', module_path) is not None,
                    workingTreeModified=bool(git('status', '--porcelain', '--untracked-files=all', '--', folder_path)))
    return identity


def invoke(module, function, request, timeout):
    with tempfile.TemporaryDirectory(prefix='rws-block-check-') as temporary:
        directory = Path(temporary)
        source, result = directory / 'request.json', directory / 'result.json'
        source.write_text(json.dumps(request, allow_nan=False), encoding='utf-8')
        process = subprocess.run([sys.executable, '-I', '-c', WORKER, str(module), function, str(source), str(result)],
                                 cwd=directory, capture_output=True, text=True, timeout=timeout)
        if process.returncode:
            # Keep bounded diagnostics; this is supplied local execution evidence.
            raise ValueError('Fixture execution failed: ' + process.stderr[-2000:].strip())
        if not result.is_file():
            raise ValueError('Fixture execution did not produce a result.')
        receipt = load_json(result)
        receipt['requestFileUnchanged'] = load_json(source) == request
        return receipt


def validate_output(output, request, spec):
    if not isinstance(output, dict) or output.get('schemaVersion') != 'rws.block-output/v1':
        raise ValueError('Output must use rws.block-output/v1.')
    if output.get('requestId') != request['requestId']:
        raise ValueError('Output requestId does not match this invocation.')
    artifacts = output.get('artifacts')
    statuses = output.get('sampleStatuses')
    if not isinstance(artifacts, list) or not isinstance(statuses, list):
        raise ValueError('Output must include artifacts and explicit sampleStatuses.')
    if any(not isinstance(row, dict) for row in artifacts + statuses):
        raise ValueError('Output artifacts and sample statuses must be objects.')
    selected = {case['sampleId'] for case in request['cases']}
    status_ids = [row.get('sampleId') for row in statuses]
    if len(status_ids) != len(set(status_ids)) or set(status_ids) != selected:
        raise ValueError('Coverage must include every selected sample exactly once.')
    if any(row.get('status') != 'completed' for row in statuses):
        raise ValueError('The two supplied complete fixtures must complete; missing/failed is not a pass.')
    ids = [row.get('id') for row in artifacts]
    if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError('Output artifact IDs must be nonempty and unique.')
    source_ids = {row['id'] for row in request.get('inputs', [])}
    for item in artifacts:
        sample = item.get('sampleId')
        identity = item.get('caseIdentity', {})
        if sample not in selected or identity.get('sampleId') != sample or identity.get('datasetId') != request['datasetId']:
            raise ValueError('Output lost or changed selected case identity.')
        if item.get('producer', {}).get('requestId') != request['requestId']:
            raise ValueError('Output producer must identify the actual invocation.')
        if not isinstance(item.get('inputIds'), list) or not set(item['inputIds']).issubset(source_ids):
            raise ValueError('Output references an input that was not explicitly selected.')
        if not any(port['kind'] == item.get('kind') and (not port.get('semantic') or port['semantic'] == item.get('semantic')) for port in spec['outputs']):
            raise ValueError('Output kind/semantic is absent from the contract.')
        validate_schema(item.get('content'), typed_result_schema(), 'artifact.content')
        validate_schema(item.get('config'), spec['configSchema'], 'artifact.config')
    for sample in selected:
        for port in spec['outputs']:
            matches = [item for item in artifacts if item['sampleId'] == sample and item['kind'] == port['kind'] and (not port.get('semantic') or item['semantic'] == port['semantic'])]
            if port.get('required', True) and not matches:
                raise ValueError('A required output is missing for sample ' + sample + '.')
            if port.get('multiple', True) is False and len(matches) > 1:
                raise ValueError('A single-valued port returned multiple outputs.')


def per_sample(output, sample):
    items = deepcopy([item for item in output['artifacts'] if item['sampleId'] == sample])
    for item in items:
        item.pop('id', None)
        item.get('producer', {}).pop('requestId', None)
    return sorted(json.dumps(item, sort_keys=True, allow_nan=False) for item in items)


def includes(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(key in actual and includes(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(includes(a, e) for a, e in zip(actual, expected))
    return actual == expected


def check_block(path, execute=False, timeout=10):
    folder = Path(path).resolve()
    evidence = {check: {'checkId': check, 'status': 'skipped', 'evidence': 'Not executed.'} for check in KNOWN_CHECKS}
    receipt = {'schemaVersion': 'rws.block-check/v1', 'checkedAt': datetime.now(timezone.utc).isoformat(),
               'mode': 'execute-fixtures' if execute else 'static', 'validationOrigin': 'supplied',
               'status': 'failed', 'registrationReady': False, 'executions': [],
               'limitations': 'Tests two supplied cases and their batch only. No model, quality, arbitrary-input or remote-execution guarantee.'}
    try:
        contract, fixture, module, function = read_contract(folder)
        spec = contract['spec']
        requested = [check['id'] for check in spec['acceptanceChecks']]
        for check in requested:
            evidence.setdefault(check, {'checkId': check, 'status': 'skipped', 'evidence': 'No checker implementation for this custom acceptance check.'})
        evidence['contract-valid'].update(status='passed', evidence='Validated contract fields, local entrypoint, parameter schema and two distinct fixture cases.')
        receipt.update(entrypoint=contract['entrypoint'], capabilities=spec['capabilities'], kind=spec['kind'],
                       identity=git_identity(folder, module))
        if execute:
            original = fixture['request']
            receipts = []
            for index, case in enumerate(original['cases']):
                request = deepcopy(original)
                request.update(requestId='check-single-' + str(index + 1), cases=[deepcopy(case)],
                               inputs=[deepcopy(item) for item in original.get('inputs', []) if item.get('sampleId') in (None, case['sampleId'])])
                result = invoke(module, function, request, timeout)
                validate_output(result['output'], request, spec)
                receipts.append((request, result))
                receipt['executions'].append({'requestId': request['requestId'], 'sampleIds': [case['sampleId']],
                                              'artifactCount': len(result['output']['artifacts']), 'status': 'completed'})
            batch = deepcopy(original)
            batch['requestId'] = 'check-batch'
            batch_result = invoke(module, function, batch, timeout)
            validate_output(batch_result['output'], batch, spec)
            receipt['executions'].append({'requestId': batch['requestId'], 'sampleIds': [case['sampleId'] for case in batch['cases']],
                                          'artifactCount': len(batch_result['output']['artifacts']), 'status': 'completed'})
            evidence['two-inputs'].update(status='passed', evidence='Executed two distinct single-case requests and confirmed completed coverage with original case identities.')
            evidence['declared-outputs'].update(status='passed', evidence='All three executions returned valid typed content, declared ports, selected case identities and exact selected input IDs.')
            unchanged = all(result['requestUnchanged'] and result['requestFileUnchanged'] for _, result in receipts) and batch_result['requestUnchanged'] and batch_result['requestFileUnchanged']
            evidence['input-immutability'].update(status='passed' if unchanged else 'failed', evidence='Compared request and referenced artifacts before/after each invocation, including the request file.')
            equal = all(per_sample(result['output'], request['cases'][0]['sampleId']) == per_sample(batch_result['output'], request['cases'][0]['sampleId']) for request, result in receipts)
            evidence['batch-equivalence'].update(status='passed' if equal else 'failed', evidence='Compared all per-case artifacts across single and batch requests, ignoring only their invocation/produced IDs.')
            expected = all(any(includes(actual, row) for actual in batch_result['output']['artifacts']) for row in fixture['expectedArtifacts'])
            evidence['expected-values'].update(status='passed' if expected else 'failed', evidence='Compared batch outputs against the explicit expectedArtifacts in fixtures.json.')
        receipt['checkEvidence'] = [evidence[check] for check in requested]
        if execute:
            receipt['status'] = 'passed' if all(check['status'] == 'passed' for check in receipt['checkEvidence']) else 'failed'
        else:
            receipt['status'] = 'static-only'
        identity = receipt['identity']
        receipt['registrationReady'] = bool(receipt['status'] == 'passed' and spec['status'] == 'ready' and identity['commit'] and identity['tracked'] and identity['workingTreeModified'] is False)
    except (ValueError, OSError, KeyError, TypeError, AttributeError, RwsError, subprocess.TimeoutExpired) as error:
        if evidence['contract-valid']['status'] != 'passed':
            evidence['contract-valid'].update(status='failed', evidence=str(error))
        receipt['error'] = str(error)
        receipt['checkEvidence'] = list(evidence.values())
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--execute', action='store_true', help='Explicitly run reviewed local Python code; this is not a sandbox.')
    parser.add_argument('--timeout', type=float, default=10, help='Per-invocation timeout in seconds (default: 10).')
    parser.add_argument('--output', type=Path, help='Write a new evidence receipt; never overwrite an existing file.')
    args = parser.parse_args(argv)
    if not 0 < args.timeout <= 60:
        parser.error('--timeout must be greater than zero and at most 60 seconds.')
    if args.output and args.output.exists():
        parser.error('Evidence output already exists; choose a new path.')
    receipt = check_block(args.path, args.execute, args.timeout)
    payload = json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as handle:
            handle.write(payload)
    print(payload, end='')
    return 1 if receipt['status'] == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
