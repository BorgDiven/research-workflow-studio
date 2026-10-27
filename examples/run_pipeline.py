#!/usr/bin/env python3
"""Run the supplied CPU-only synthetic blocks through explicit JSON manifests."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.check_block import check_block
from tools.scaffold import scaffold


def write_new(path, value):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')


def run_pipeline(destination, input_request=None):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    blocks = {}
    for kind in ('inference', 'analysis', 'evaluation', 'report'):
        blocks[kind] = scaffold(kind, destination / 'blocks' / kind)
        receipt = check_block(blocks[kind], execute=True)
        write_new(destination / (kind + '-checks.json'), receipt)
        if receipt['status'] != 'passed':
            raise ValueError('Synthetic fixture validation failed for ' + kind + '.')
    request = deepcopy(input_request) if input_request is not None else json.loads((blocks['inference'] / 'request.json').read_text())
    outputs = {}

    def execute(kind, payload):
        input_path = destination / (kind + '-request.json')
        output_path = destination / (kind + '-output.json')
        write_new(input_path, payload)
        subprocess.run([sys.executable, str(blocks[kind] / 'block.py'), '--input', str(input_path), '--output', str(output_path)], check=True)
        outputs[kind] = json.loads(output_path.read_text(encoding='utf-8'))

    request['requestId'] = 'synthetic-pipeline-inference'
    execute('inference', request)
    finals = [item for item in outputs['inference']['artifacts'] if item['semantic'] == 'final-output']
    for kind in ('analysis', 'evaluation'):
        payload = {'requestId': 'synthetic-pipeline-' + kind, 'datasetId': request['datasetId'],
                   'cases': request['cases'], 'config': {}, 'inputs': finals}
        execute(kind, payload)
    evidence = finals + outputs['analysis']['artifacts'] + outputs['evaluation']['artifacts']
    execute('report', {'requestId': 'synthetic-pipeline-report', 'datasetId': request['datasetId'],
                       'cases': request['cases'], 'config': {'title': 'Synthetic pipeline evidence'}, 'inputs': evidence})
    manifest = {'schemaVersion': 'rws.example-pipeline/v1', 'synthetic': True,
                'outputs': {kind: kind + '-output.json' for kind in outputs},
                'caseIds': [case['sampleId'] for case in request['cases']],
                'notice': 'CPU teaching data only. No model, research experiment or RWS project was started.'}
    write_new(destination / 'pipeline-manifest.json', manifest)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True, help='New output directory; existing directories are refused.')
    parser.add_argument('--input', type=Path, help='Optional inference request JSON; defaults to the two supplied synthetic cases.')
    args = parser.parse_args(argv)
    request = json.loads(args.input.read_text(encoding='utf-8')) if args.input else None
    try:
        run_pipeline(args.destination, request)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + '\n')
    print(str(args.destination.resolve() / 'pipeline-manifest.json'))


if __name__ == '__main__':
    main()
