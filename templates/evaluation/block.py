"""Measure stored signal error against explicit references; never generate data."""
from _runtime import artifact, cases, cli, config, finite, input_for, result, series_values

PROTOCOL = {'id': 'synthetic-mae', 'version': '1', 'metric': 'mean_absolute_error',
            'unit': 'arbitrary', 'direction': 'lower', 'preprocessing': 'none',
            'aggregation': 'per-case arithmetic mean over paired positions',
            'missingPolicy': 'Keep missing samples; do not replace by zero.'}


def run(request):
    selected = cases(request)
    settings = config(request, {})
    outputs, statuses = [], []
    for case in selected:
        source = input_for(request, case['sampleId'], 'final-output')
        reference = case.get('referenceValues')
        if source is None or reference is None:
            statuses.append({'sampleId': case['sampleId'], 'status': 'missing',
                             'reason': 'Both a selected final-output and referenceValues are required.'})
            continue
        values = series_values(source.get('content', {}))
        if not isinstance(reference, list) or not reference or len(values) != len(reference):
            raise ValueError('Prediction and reference must have equal nonzero length.')
        expected = [finite(v, 'reference') for v in reference]
        value = finite(sum(abs(a-b) for a, b in zip(values, expected)) / len(values), 'mean absolute error')
        metric = {'kind': 'metric', 'name': PROTOCOL['metric'], 'metricId': PROTOCOL['id'],
                  'value': value, 'unit': PROTOCOL['unit'], 'direction': 'lower', 'status': 'completed'}
        item = artifact(request, case, 'evaluation-metric', 'metric', metric, settings,
                        input_ids=[source['id']])
        item['protocol'] = dict(PROTOCOL)
        item['referenceValues'] = expected
        outputs.append(item)
        statuses.append({'sampleId': case['sampleId'], 'status': 'completed'})
    return result(request, outputs, statuses)


if __name__ == '__main__':
    cli(run)
