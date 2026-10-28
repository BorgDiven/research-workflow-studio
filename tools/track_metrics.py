#!/usr/bin/env python3
"""Batch explicit JSONL observations, retry a spool, or read an MLflow metric history."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rws.core import Store
from rws.tracking_client import HTTPClient, MLflowImporter, TrackingClient


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument('--db', help='Explicit local Studio database')
    destination.add_argument('--studio-url', help='Explicit Studio model-authority HTTP endpoint')
    parser.add_argument('--project', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--run-version', required=True, type=int)
    parser.add_argument('--spool', required=True, type=Path)
    parser.add_argument('--input', type=Path, help='JSONL points with metricId, x, value and optional eventId/dimensions')
    parser.add_argument('--mlflow-url', help='Explicit credential-free MLflow base URL; read only')
    parser.add_argument('--mlflow-run-id')
    parser.add_argument('--mlflow-split', help='Explicit registered metric split for this import, such as train')
    parser.add_argument('--metric', action='append', default=[], help='MLflow-key=registered-metric-id; repeat as needed')
    args = parser.parse_args(argv)
    if bool(args.mlflow_url) != bool(args.mlflow_run_id) or (args.mlflow_url and not args.metric):
        parser.error('MLflow import needs --mlflow-url, --mlflow-run-id and explicit --metric mappings.')
    if args.input and args.mlflow_url:
        parser.error('Choose JSONL input or MLflow history for each invocation.')
    if args.mlflow_split and not args.mlflow_url:
        parser.error('--mlflow-split requires an explicit MLflow import.')
    store = Store(args.db) if args.db else None
    try:
        client = TrackingClient(store.call if store else HTTPClient(args.studio_url), args.project,
            {'projectId': args.project, 'type': 'run', 'id': args.run_id, 'version': args.run_version}, args.spool)
        if args.mlflow_url:
            mappings = {}
            for item in args.metric:
                key, separator, value = item.partition('=')
                if not separator or not key or not value or key in mappings:
                    parser.error('Metric mappings must have unique nonempty key=id entries.')
                mappings[key] = value
            result = MLflowImporter(args.mlflow_url, args.mlflow_run_id, client).import_history(mappings, split=args.mlflow_split)
        else:
            if args.input:
                with args.input.open(encoding='utf-8') as handle:
                    for line in handle:
                        if not line.strip():
                            continue
                        point = json.loads(line)
                        if set(point) - {'metricId', 'x', 'value', 'eventId', 'split', 'sampleId', 'timestamp', 'reason'}:
                            raise ValueError('JSONL contains unsupported metric fields.')
                        client.log(point['metricId'], point['x'], point['value'], event_id=point.get('eventId'),
                            split=point.get('split'), sample_id=point.get('sampleId'), timestamp=point.get('timestamp'), reason=point.get('reason'))
            result = client.flush()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get('status', result.get('delivery', {}).get('status')) == 'pending' else 0
    finally:
        if store:
            store.close()


if __name__ == '__main__':
    raise SystemExit(main())
