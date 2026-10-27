"""Small JSON boundary used by the standalone synthetic teaching blocks."""
import argparse
import json
import math
from pathlib import Path


def finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(name + ' must be a finite number.')
    return value


def cases(request):
    rows = request.get('cases')
    if not isinstance(rows, list) or not rows:
        raise ValueError('cases must contain at least one input case.')
    ids = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('sampleId'), str) or not row['sampleId'].strip():
            raise ValueError('Every case needs a nonempty sampleId.')
        ids.append(row['sampleId'])
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate sampleId in this input selection.')
    if not isinstance(request.get('requestId'), str) or not request['requestId'].strip():
        raise ValueError('requestId is required to identify this invocation.')
    if not isinstance(request.get('datasetId'), str) or not request['datasetId'].strip():
        raise ValueError('datasetId is required to disambiguate sample identity.')
    return rows


def config(request, defaults):
    supplied = request.get('config', {})
    if not isinstance(supplied, dict) or set(supplied) - set(defaults):
        raise ValueError('Unknown configuration keys.')
    return dict(defaults, **supplied)


def selected_artifacts(request):
    inputs = request.get('inputs', [])
    if not isinstance(inputs, list) or any(not isinstance(a, dict) for a in inputs):
        raise ValueError('inputs must be an array of exact existing artifacts.')
    ids = []
    selected = {row['sampleId']: row for row in request['cases']}
    for item in inputs:
        if not isinstance(item.get('id'), str) or not item['id']:
            raise ValueError('Existing artifacts require stable IDs.')
        identity = item.get('caseIdentity', {})
        if identity.get('sampleId') != item.get('sampleId') or identity.get('datasetId') != request.get('datasetId', 'synthetic-signals-v1'):
            raise ValueError('Input artifact case identity must match the selected dataset and sample.')
        case = selected.get(item.get('sampleId'))
        if case and identity.get('task') != case.get('task', 'inspect-signal'):
            raise ValueError('Input artifact task must match the selected case task.')
        if not isinstance(item.get('content'), dict) or item.get('kind') != item['content'].get('kind'):
            raise ValueError('Stored artifact kind must match its typed content.')
        ids.append(item['id'])
    if len(set(ids)) != len(ids):
        raise ValueError('Select each exact artifact ID only once.')
    return inputs


def input_for(request, sample_id, semantic):
    inputs = selected_artifacts(request)
    found = [a for a in inputs if a.get('sampleId') == sample_id and a.get('semantic') == semantic]
    if len(found) > 1:
        raise ValueError('Choose one exact input artifact for ' + sample_id + '; duplicates are not silently selected.')
    return found[0] if found else None


def series_values(content):
    points = content.get('points')
    if content.get('kind') != 'series' or not isinstance(points, list) or not points:
        raise ValueError('Expected a nonempty stored series.')
    values = []
    for index, point in enumerate(points):
        if not isinstance(point, list) or len(point) != 2 or finite(point[0], 'sample position') != index:
            raise ValueError('Synthetic series positions must match the ordered reference positions.')
        values.append(finite(point[1], 'stored signal'))
    return values


def artifact(request, case, semantic, kind, content, settings, suffix='', input_ids=None):
    return {
        'id': request['requestId'] + '/' + case['sampleId'] + '/' + semantic + suffix,
        'sampleId': case['sampleId'],
        'caseIdentity': {'datasetId': request.get('datasetId', 'synthetic-signals-v1'),
                         'sampleId': case['sampleId'], 'task': case.get('task', 'inspect-signal')},
        'kind': kind, 'semantic': semantic, 'config': settings,
        'producer': {'requestId': request['requestId'], 'entrypoint': 'block.py:run'},
        'inputIds': input_ids or [], 'content': content, 'synthetic': True,
    }


def result(request, artifacts, statuses):
    return {'schemaVersion': 'rws.block-output/v1', 'requestId': request['requestId'],
            'synthetic': True, 'artifacts': artifacts, 'sampleStatuses': statuses,
            'summary': {'selected': len(statuses),
                        'completed': sum(row['status'] == 'completed' for row in statuses),
                        'missing': sum(row['status'] == 'missing' for row in statuses)},
            'notice': 'Synthetic CPU example. No model or research result is represented.'}


def cli(run):
    parser = argparse.ArgumentParser(description='Run this synthetic block on explicit JSON inputs.')
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; choose a new output path to preserve earlier evidence.')
    request = json.loads(args.input.read_text(encoding='utf-8'))
    output = run(request)
    documents = []
    for index, item in enumerate(output['artifacts']):
        if 'markdown' in item:
            path = args.output.with_name(args.output.name + '.document-' + str(index + 1) + '.md')
            if path.exists():
                parser.error('A report document already exists; choose a new output path.')
            item['content']['uri'] = path.name
            item['content']['availability'] = 'available'
            documents.append((path, item['markdown']))
    payload = json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for path, document in documents:
        with path.open('x', encoding='utf-8') as handle:
            handle.write(document)
    with args.output.open('x', encoding='utf-8') as handle:
        handle.write(payload + '\n')
