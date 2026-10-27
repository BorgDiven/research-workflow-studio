"""Summarize stored synthetic signals without invoking inference."""
from _runtime import artifact, cases, cli, config, finite, input_for, result, series_values


def run(request):
    selected = cases(request)
    settings = config(request, {})
    outputs, statuses = [], []
    for case in selected:
        source = input_for(request, case['sampleId'], 'final-output')
        if source is None:
            statuses.append({'sampleId': case['sampleId'], 'status': 'missing', 'reason': 'No selected final-output artifact.'})
            continue
        values = series_values(source.get('content', {}))
        table = {'kind': 'table', 'columns': [{'key': 'statistic', 'type': 'string'},
                 {'key': 'value', 'type': 'number'}],
                 'rows': [{'statistic': 'minimum', 'value': min(values)},
                          {'statistic': 'maximum', 'value': max(values)},
                          {'statistic': 'mean', 'value': finite(sum(values) / len(values), 'mean')}]}
        outputs.append(artifact(request, case, 'signal-summary', 'table', table, settings,
                                input_ids=[source['id']]))
        statuses.append({'sampleId': case['sampleId'], 'status': 'completed'})
    return result(request, outputs, statuses)


if __name__ == '__main__':
    cli(run)
