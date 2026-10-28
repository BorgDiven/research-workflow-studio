"""Durable, batched process-metric logging and explicit read-only MLflow import."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import math
from pathlib import Path
import uuid
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .core import RwsError


def safe_base_url(value):
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Use an explicit HTTP(S) address without credentials, query or fragment.')
    return value.rstrip('/')


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HTTPClient:
    """Model-authority endpoint only. Optional authorization stays in memory."""
    def __init__(self, base_url, headers_provider=None, opener=None, timeout=10):
        self.base_url = safe_base_url(base_url)
        self.headers_provider = headers_provider or (lambda: {})
        self.opener = opener or build_opener(NoRedirects())
        self.timeout = timeout

    def __call__(self, name, arguments):
        origin = urlsplit(self.base_url)
        headers = dict(self.headers_provider(), **{'Content-Type': 'application/json',
                        'Origin': origin.scheme + '://' + origin.netloc})
        request = Request(self.base_url + '/api/call', data=json.dumps({'name': name, 'arguments': arguments}, allow_nan=False).encode(), headers=headers)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                result = json.load(response)
        except HTTPError as error:
            try:
                result = json.load(error)
            except (ValueError, OSError):
                raise ConnectionError('Metrics endpoint rejected the request.') from None
            detail = result.get('error', {})
            raise RwsError(detail.get('code', 'http_error'), detail.get('message', 'Metrics request failed.')) from None
        if not result.get('ok'):
            detail = result.get('error', {})
            raise RwsError(detail.get('code', 'request_failed'), detail.get('message', 'Metrics request failed.'))
        return result


class TrackingClient:
    def __init__(self, call, project_id, run_ref, spool_dir, batch_size=1000):
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or not 1 <= batch_size <= 1000:
            raise ValueError('batch_size must be between 1 and 1000.')
        if run_ref.get('projectId') != project_id or run_ref.get('type') != 'run' or not isinstance(run_ref.get('version'), int):
            raise ValueError('Supply the exact run reference belonging to this project.')
        self.call, self.project_id, self.run_ref = call, project_id, json.loads(json.dumps(run_ref))
        self.directory, self.batch_size = Path(spool_dir), batch_size
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.state_path = self.directory / 'metrics-spool.json'

    @contextmanager
    def _locked(self):
        with (self.directory / 'metrics.lock').open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {
                'schemaVersion': 1, 'projectId': self.project_id, 'runRef': self.run_ref,
                'events': {}, 'batches': []}
            if state.get('projectId') != self.project_id or state.get('runRef') != self.run_ref:
                raise ValueError('This spool belongs to another exact run; use a separate directory.')
            yield state

    def _save(self, state):
        temporary = self.state_path.with_suffix('.tmp')
        with temporary.open('w', encoding='utf-8') as handle:
            json.dump(state, handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            import os
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        temporary.replace(self.state_path)

    def log(self, metric_id, x, value, event_id=None, *, split=None, sample_id=None,
            timestamp=None, reason=None, source=None):
        if not isinstance(metric_id, str) or not metric_id:
            raise ValueError('metric_id must name a declared process metric.')
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0:
            raise ValueError('Metric coordinate must be a finite nonnegative number.')
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise ValueError('Metric value must be finite or explicitly missing.')
        if value is None and not reason:
            raise ValueError('A missing metric requires a reason.')
        point = {'metricId': metric_id, 'x': x, 'value': value}
        for key, item in (('split', split), ('sampleId', sample_id), ('timestamp', timestamp), ('reason', reason)):
            if item is not None:
                if not isinstance(item, str):
                    raise ValueError(key + ' must be a string.')
                point[key] = item
        if source is not None:
            if set(source) != {'kind', 'baseUrl', 'runId'} or source['kind'] != 'mlflow' or not isinstance(source['runId'], str) or not source['runId']:
                raise ValueError('MLflow source requires its explicit address and run ID.')
            source = dict(source, baseUrl=safe_base_url(source['baseUrl']))
        event_id = event_id or 'event-' + uuid.uuid4().hex
        if not isinstance(event_id, str) or not event_id or len(event_id) > 2048:
            raise ValueError('event_id must be a nonempty string of at most 2048 characters.')
        event = {'point': point, 'source': source}
        with self._locked() as state:
            previous = state['events'].get(event_id)
            if previous and any(previous[key] != event[key] for key in event):
                raise ValueError('An event ID cannot be reused for a different metric observation.')
            if not previous:
                state['events'][event_id] = dict(event, acknowledged=False)
                self._save(state)
        return event_id

    def _revision(self):
        projects = self.call('rws_project_list', {})['result']
        return next(project['revision'] for project in projects if project['id'] == self.project_id)

    def flush(self):
        acknowledged, sent = 0, 0
        with self._locked() as state:
            while True:
                if not state['batches']:
                    pending = [(key, event) for key, event in state['events'].items() if not event['acknowledged']]
                    if not pending:
                        break
                    source = pending[0][1]['source']
                    selected = [(key, event) for key, event in pending if event['source'] == source][:self.batch_size]
                    state['batches'].append({'eventIds': [key for key, _ in selected],
                        'arguments': {'projectId': self.project_id, 'runRef': self.run_ref,
                            'requestId': 'metrics-' + uuid.uuid4().hex,
                            'points': [event['point'] for _, event in selected],
                            **({'source': source} if source else {})}})
                    self._save(state)
                batch = state['batches'][0]
                try:
                    arguments = batch['arguments']
                    if 'expectedRevision' not in arguments:
                        arguments['expectedRevision'] = self._revision()
                        self._save(state)
                    for attempt in range(3):
                        try:
                            self.call('rws_metrics_append', arguments)
                            break
                        except RwsError as error:
                            if error.code != 'revision_conflict' or attempt == 2:
                                raise
                            # Only an explicit rejection permits updating the revision.
                            arguments['expectedRevision'] = self._revision()
                            self._save(state)
                    for event_id in batch['eventIds']:
                        state['events'][event_id]['acknowledged'] = True
                    acknowledged += len(batch['eventIds'])
                    sent += 1
                    state['batches'].pop(0)
                    self._save(state)
                except (OSError, ConnectionError, TimeoutError, RwsError) as error:
                    return {'acknowledgedEvents': acknowledged, 'sentBatches': sent,
                            'pendingEvents': sum(not e['acknowledged'] for e in state['events'].values()),
                            'status': 'pending', 'error': error.code if isinstance(error, RwsError) else type(error).__name__}
            return {'acknowledgedEvents': acknowledged, 'sentBatches': sent, 'pendingEvents': 0, 'status': 'flushed'}


class MLflowImporter:
    """Read metric history only. Run status is neither queried nor inferred."""
    def __init__(self, base_url, run_id, client, opener=None, headers_provider=None):
        self.base_url = safe_base_url(base_url)
        if not isinstance(run_id, str) or not run_id:
            raise ValueError('An explicit MLflow run ID is required.')
        self.run_id, self.client = run_id, client
        self.opener = opener or build_opener(NoRedirects())
        self.headers_provider = headers_provider or (lambda: {})

    def import_history(self, metric_ids, *, split=None):
        if not isinstance(metric_ids, dict) or not metric_ids:
            raise ValueError('Provide an explicit MLflow metric key → registered metric ID mapping.')
        if split is not None and (not isinstance(split, str) or not split):
            raise ValueError('split must be an explicitly named metric split.')
        count = 0
        source = {'kind': 'mlflow', 'baseUrl': self.base_url, 'runId': self.run_id}
        for external_key, metric_id in metric_ids.items():
            token, visited = None, set()
            for _ in range(1000):
                query = {'run_id': self.run_id, 'metric_key': external_key, 'max_results': 1000}
                if token:
                    query['page_token'] = token
                request = Request(self.base_url + '/api/2.0/mlflow/metrics/get-history?' + urlencode(query), headers=self.headers_provider(), method='GET')
                with self.opener.open(request, timeout=15) as response:
                    result = json.load(response)
                for point in result.get('metrics', []):
                    if point.get('key') != external_key:
                        raise ValueError('MLflow response contains another metric key.')
                    timestamp = point.get('timestamp')
                    iso = datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat() if timestamp is not None else None
                    identity = [self.base_url, self.run_id, external_key, point['step'], timestamp]
                    if split is not None:
                        identity.append(split)
                    event = 'mlflow:' + json.dumps(identity, separators=(',', ':'))
                    self.client.log(metric_id, point['step'], point['value'], event_id=event, timestamp=iso, source=source, split=split)
                    count += 1
                token = result.get('next_page_token')
                if not token:
                    break
                if token in visited:
                    raise ValueError('MLflow returned a repeated pagination token.')
                visited.add(token)
            else:
                raise ValueError('MLflow metric history exceeds the explicit pagination limit.')
        return {'readObservations': count, 'source': source, 'delivery': self.client.flush(),
                'notice': 'Imported recorded metric history only; no run completion or research conclusion inferred.'}
