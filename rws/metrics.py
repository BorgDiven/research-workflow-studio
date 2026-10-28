"""Append-only process measurements and bounded, explicitly frozen read views."""
import json
from collections import OrderedDict
from urllib.parse import urlsplit

from .core import dump, fail, ref_schema, validate_schema


def exact_ref(kind=None):
    schema = ref_schema(kind)
    schema['required'].append('version')
    return schema


def metric_definitions_schema():
    return {'type': 'array', 'maxItems': 64, 'items': {'type': 'object', 'properties': {
        'id': {'type': 'string', 'pattern': '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'},
        'name': {'type': 'string', 'minLength': 1, 'maxLength': 160},
        'unit': {'type': 'string', 'maxLength': 64}, 'axis': {'enum': ['step', 'epoch', 'time']},
        'scope': {'enum': ['run', 'sample']}, 'direction': {'enum': ['higher', 'lower', 'none']},
        'splits': {'type': 'array', 'maxItems': 32, 'uniqueItems': True,
                   'items': {'type': 'string', 'minLength': 1, 'maxLength': 80}},
        'protocolRef': exact_ref('protocol')},
        'required': ['id', 'unit', 'axis', 'scope'], 'additionalProperties': False}}


def metric_tools(common):
    source = {'type': 'object', 'properties': {'kind': {'const': 'mlflow'},
              'baseUrl': {'type': 'string', 'minLength': 1, 'maxLength': 4096},
              'runId': {'type': 'string', 'minLength': 1, 'maxLength': 256}},
              'required': ['kind', 'baseUrl', 'runId'], 'additionalProperties': False}
    point = {'type': 'object', 'properties': {
        'metricId': {'type': 'string', 'minLength': 1}, 'x': {'type': 'number', 'minimum': 0},
        'value': {'type': ['number', 'null']}, 'split': {'type': 'string', 'maxLength': 80},
        'sampleId': {'type': 'string', 'minLength': 1, 'maxLength': 160},
        'timestamp': {'type': 'string', 'maxLength': 80}, 'reason': {'type': 'string', 'maxLength': 1000}},
        'required': ['metricId', 'x', 'value'], 'additionalProperties': False}
    filters = {'metricIds': {'type': 'array', 'maxItems': 64, 'uniqueItems': True,
                             'items': {'type': 'string', 'minLength': 1}},
               'fromX': {'type': 'number', 'minimum': 0}, 'toX': {'type': 'number', 'minimum': 0},
               'throughSequence': {'type': 'integer', 'minimum': 0}}
    def tool(name, props, required, description, read=False):
        return {'name': name, 'description': description,
                'inputSchema': {'type': 'object', 'properties': props, 'required': required, 'additionalProperties': False},
                'annotations': {'readOnlyHint': read, 'destructiveHint': False, 'idempotentHint': True, 'openWorldHint': False}}
    return [
        tool('rws_metrics_append', dict(common, runRef=exact_ref('run'), source=source,
             points={'type': 'array', 'minItems': 1, 'maxItems': 1000, 'items': point}),
             list(common) + ['runRef', 'points'],
             'Append actual process measurements in batches under the run\'s pinned processMetrics contract. Identical points deduplicate; conflicting values never overwrite. Does not run a model.'),
        tool('rws_metrics_query', dict(filters, projectId={'type': 'string'},
             runRefs={'type': 'array', 'minItems': 1, 'maxItems': 20, 'items': exact_ref('run')},
             limit={'type': 'integer', 'minimum': 1, 'maximum': 5000}, offset={'type': 'integer', 'minimum': 0}),
             ['projectId', 'runRefs'], 'Read bounded process series and compatible alignments. Reuse throughSequence on every page; null stays missing, with no interpolation.', True),
        tool('rws_metrics_snapshot', dict(common, **filters, runRef=exact_ref('run'),
             title={'type': 'string', 'minLength': 1, 'maxLength': 240}),
             list(common) + ['runRef', 'title', 'throughSequence'],
             'Freeze the selected run metrics through a previously read sequence into one immutable metric-history artifact. Includes complete definitions and points; rejects over 5000 points instead of silently truncating.')]


def validate_definitions(store, conn, definitions):
    seen = set()
    for definition in definitions:
        if definition['id'] in seen:
            fail('Process metric IDs must be unique.')
        seen.add(definition['id'])
        if definition.get('protocolRef'):
            store._get(conn, definition['protocolRef'], ['protocol'])


def contract(store, conn, run_ref, project=None):
    run = store._get(conn, run_ref, ['run'], project)
    if not run['record'].get('codeRef'):
        fail('Process metrics require a registered implementation with a pinned metric contract.')
    code = store._get(conn, run['record']['codeRef'], ['code'])
    if not code['record'].get('specRef'):
        fail('Process metrics require a pinned specification; legacy runs retain their existing artifacts.')
    spec = store._get(conn, code['record']['specRef'], ['spec'])
    definitions = {d['id']: d for d in spec['record'].get('processMetrics', [])}
    if not definitions:
        fail('The pinned specification declares no processMetrics.')
    return run, spec, definitions


def bounds(args):
    if args.get('fromX', 0) > args.get('toX', float('inf')):
        fail('fromX must not exceed toX.')


def require_observed_run(store, conn, run):
    current = store._get(conn, {k: v for k, v in run['ref'].items() if k != 'version'}, ['run'])
    if current['record'].get('status') == 'planned':
        fail('A planned run has no actual metrics; record execution first.')


def append(store, conn, args, project):
    run, spec, definitions = contract(store, conn, args['runRef'], project['id'])
    require_observed_run(store, conn, run)
    source = args.get('source')
    if source:
        if any(character.isspace() for character in source['baseUrl']) or not source['runId'].strip():
            fail('MLflow source requires a literal URL and a nonempty run identity.')
        try:
            url = urlsplit(source['baseUrl'])
        except ValueError:
            fail('MLflow source URL is malformed.')
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
            fail('MLflow baseUrl must be credential-free HTTP(S), without user info, query or fragment.')
    inserted, duplicates = 0, 0
    for point in args['points']:
        definition = definitions.get(point['metricId'])
        if not definition:
            fail('Metric is absent from the run\'s pinned processMetrics.', details={'metricId': point['metricId']})
        split, sample = point.get('split', ''), point.get('sampleId', '')
        if split not in (definition.get('splits') or ['']):
            fail('Metric split is absent from the pinned definition.')
        selection = run['record'].get('sampleSelection', {})
        if definition['scope'] == 'sample':
            if not sample or sample not in selection.get('sampleIds', []):
                fail('Sample-scoped metrics must identify a selected sample.')
        elif sample:
            fail('Run-scoped metrics cannot declare a sampleId.')
        if point['value'] is None and not point.get('reason', '').strip():
            fail('A missing measurement needs an explicit reason.')
        key = (project['id'], run['ref']['id'], point['metricId'], split, sample, point['x'])
        previous = conn.execute('SELECT document FROM metric_points WHERE project_id=? AND run_id=? AND metric_id=? AND split=? AND sample_id=? AND x=?', key).fetchone()
        if previous:
            old = json.loads(previous['document'])
            if old['value'] != point['value'] or old.get('source') != source or (point['value'] is None and old.get('reason') != point.get('reason')):
                fail('A measurement already exists at this coordinate with different content.', 'metric_conflict',
                     {'metricId': point['metricId'], 'x': point['x'], 'split': split, 'sampleId': sample})
            duplicates += 1
            continue
        document = dict(point, runRef=run['ref'], definitionRef=spec['ref'])
        if source:
            document['source'] = source
        conn.execute('INSERT INTO metric_points(project_id,run_id,metric_id,split,sample_id,x,document) VALUES(?,?,?,?,?,?,?)', key + (dump(document),))
        inserted += 1
    sequence = conn.execute('SELECT COALESCE(MAX(sequence),0) FROM metric_points').fetchone()[0]
    return {'runRef': run['ref'], 'inserted': inserted, 'duplicates': duplicates, 'throughSequence': sequence}


def query(store, conn, args):
    store._project(conn, args['projectId'])
    bounds(args)
    refs, seen, definitions_by_run = args['runRefs'], set(), {}
    for ref in refs:
        key = (ref['projectId'], ref['id'])
        if key in seen:
            fail('Choose each run identity only once, even when revisions differ.')
        seen.add(key)
        definitions_by_run[key] = contract(store, conn, ref)
    current_sequence = conn.execute('SELECT COALESCE(MAX(sequence),0) FROM metric_points').fetchone()[0]
    through = args.get('throughSequence', current_sequence)
    if through > current_sequence:
        fail('throughSequence cannot name a future measurement.')
    clauses, params = [], []
    for project_id, run_id in seen:
        clauses.append('(project_id=? AND run_id=?)')
        params.extend((project_id, run_id))
    where = '(' + ' OR '.join(clauses) + ') AND sequence<=?'
    params.append(through)
    if args.get('metricIds'):
        where += ' AND metric_id IN (' + ','.join('?' for _ in args['metricIds']) + ')'
        params.extend(args['metricIds'])
    for field, comparison in (('fromX', '>='), ('toX', '<=')):
        if field in args:
            where += ' AND x' + comparison + '?'
            params.append(args[field])
    total = conn.execute('SELECT COUNT(*) FROM metric_points WHERE ' + where, params).fetchone()[0]
    limit, offset = args.get('limit', 1000), args.get('offset', 0)
    rows = conn.execute('SELECT * FROM metric_points WHERE ' + where + ' ORDER BY sequence LIMIT ? OFFSET ?', params + [limit, offset]).fetchall()
    series = OrderedDict()
    for row in rows:
        run, spec, definitions = definitions_by_run[(row['project_id'], row['run_id'])]
        definition = definitions[row['metric_id']]
        key = (row['project_id'], row['run_id'], row['metric_id'], row['split'], row['sample_id'])
        if key not in series:
            selection = run['record'].get('sampleSelection', {})
            series[key] = {'runRef': run['ref'], 'metricId': definition['id'],
                           'name': definition.get('name', definition['id']), 'unit': definition['unit'],
                           'axis': definition['axis'], 'scope': definition['scope'],
                           'split': row['split'], 'sampleId': row['sample_id'] or None,
                           'protocolRef': definition.get('protocolRef'), 'definitionRef': spec['ref'],
                           'datasetRef': selection.get('datasetRef'), 'sampleSelection': selection, 'points': []}
        document = json.loads(row['document'])
        point = {key: document[key] for key in ('x', 'value', 'timestamp', 'reason', 'source') if key in document}
        point['sequence'] = row['sequence']
        series[key]['points'].append(point)
    aligned = OrderedDict()
    for item in series.values():
        item['points'].sort(key=lambda p: p['x'])
        selection = dict(item['sampleSelection'], sampleIds=sorted(item['sampleSelection'].get('sampleIds', [])))
        grouping = [item[k] for k in ('metricId', 'unit', 'axis', 'scope', 'split', 'sampleId')]
        grouping += [item['protocolRef'] or item['definitionRef'], item['datasetRef'], selection]
        if item['datasetRef'] is None:
            grouping.append(item['runRef'])  # Unknown data identity is not comparability.
        key = dump(grouping)
        if key not in aligned:
            aligned[key] = {k: item[k] for k in ('metricId', 'unit', 'axis', 'scope', 'split', 'sampleId', 'protocolRef', 'definitionRef', 'datasetRef', 'sampleSelection')}
            aligned[key]['series'] = []
        aligned[key]['series'].append(item)
    for group in aligned.values():
        items = group.pop('series')
        xs = sorted({p['x'] for item in items for p in item['points']})
        group['xs'] = xs
        group['columns'] = []
        for item in items:
            values = {p['x']: p['value'] for p in item['points']}
            group['columns'].append({'runRef': item['runRef'], 'values': [values.get(x) for x in xs]})
    return {'series': list(series.values()), 'aligned': list(aligned.values()), 'total': total,
            'offset': offset, 'limit': limit, 'truncated': offset + len(rows) < total,
            'throughSequence': through}


def snapshot(store, conn, args, project):
    run, _, _ = contract(store, conn, args['runRef'], project['id'])
    require_observed_run(store, conn, run)
    filters = {k: args[k] for k in ('metricIds', 'fromX', 'toX', 'throughSequence') if k in args}
    result = query(store, conn, dict(filters, projectId=project['id'], runRefs=[run['ref']], limit=5000))
    if not result['total']:
        fail('The selected measurement history is empty.')
    if result['truncated']:
        fail('A snapshot is limited to 5000 points; narrow the metric or coordinate range.', details={'total': result['total']})
    rows = [{'metric': s['metricId'], 'split': s['split'], 'sample': s['sampleId'],
             'x': p['x'], 'value': p['value'], 'sequence': p['sequence']}
            for s in result['series'] for p in s['points']]
    content = {'kind': 'table', 'columns': [{'key': k, 'type': t} for k, t in
                (('metric', 'string'), ('split', 'string'), ('sample', 'string'), ('x', 'number'), ('value', 'number'), ('sequence', 'number'))], 'rows': rows}
    store._result(content, conn=conn)
    record = {'title': args['title'], 'kind': 'table', 'semantic': 'metric-history',
              'producerRef': run['ref'], 'provenance': 'known', 'availability': 'available',
              'config': run['record'].get('config', {}), 'content': content,
              'source': {'kind': 'metric-history-snapshot', 'schemaVersion': 1,
                         'throughSequence': result['throughSequence'], 'pointCount': result['total'],
                         'query': dict(filters, runRef=run['ref']), 'series': result['series']}}
    selection = run['record'].get('sampleSelection', {})
    if selection.get('datasetRef'):
        record['datasetRef'] = selection['datasetRef']
    if run['record'].get('inputRefs'):
        record['inputRefs'] = run['record']['inputRefs']
    return store._put(conn, project['id'], 'artifact', record)


def mutate(store, conn, name, args, project):
    return append(store, conn, args, project) if name == 'rws_metrics_append' else snapshot(store, conn, args, project)
