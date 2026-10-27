"""A synthetic affine signal transform; case IDs never control the algorithm."""
from _runtime import artifact, cases, cli, config, finite, result


def run(request):
    selected = cases(request)
    settings = config(request, {'scale': 2.0, 'offset': 0.0, 'diagnosticSteps': 3})
    finite(settings['scale'], 'scale')
    finite(settings['offset'], 'offset')
    steps = settings['diagnosticSteps']
    if isinstance(steps, bool) or not isinstance(steps, int) or not 0 <= steps <= 32:
        raise ValueError('diagnosticSteps must be an integer from 0 to 32.')
    outputs, statuses = [], []
    for case in selected:
        values = case.get('input', {}).get('values')
        if not isinstance(values, list) or not values:
            raise ValueError('Each input.values must be a nonempty numeric list.')
        original = [finite(v, 'signal value') for v in values]
        final = [settings['scale'] * v + settings['offset'] for v in original]
        content = lambda ys: {'kind': 'series', 'name': 'Synthetic signal',
            'xAxis': {'label': 'Sample position', 'unit': 'index'},
            'yAxis': {'label': 'Signal', 'unit': 'arbitrary'},
            'points': [[i, finite(v, 'transformed value')] for i, v in enumerate(ys)]}
        outputs.append(artifact(request, case, 'final-output', 'series', content(final), settings))
        for step in range(1, steps + 1):
            fraction = step / (steps + 1)
            ys = [a + fraction * (b - a) for a, b in zip(original, final)]
            item = artifact(request, case, 'intermediate-state', 'series', content(ys), settings,
                            suffix='-' + str(step))
            item['observation'] = {'step': step, 'label': 'Synthetic interpolation; final step ' + str(steps + 1)}
            outputs.append(item)
        statuses.append({'sampleId': case['sampleId'], 'status': 'completed'})
    return result(request, outputs, statuses)


if __name__ == '__main__':
    cli(run)
