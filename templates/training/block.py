"""Fit independent synthetic linear datasets; cases and settings stay external."""
import json

from _runtime import artifact, cases, cli, config, finite, result


def run(request):
    selected = cases(request)
    settings = config(request, {'learningRate': 0.25, 'epochs': 2})
    rate = finite(settings['learningRate'], 'learningRate')
    epochs = settings['epochs']
    if not 0 < rate <= 1:
        raise ValueError('learningRate must be greater than zero and at most one.')
    if isinstance(epochs, bool) or not isinstance(epochs, int) or not 1 <= epochs <= 10000:
        raise ValueError('epochs must be an integer from 1 to 10000.')
    outputs, statuses = [], []
    for case in selected:
        rows = case.get('input', {}).get('pairs')
        if not isinstance(rows, list) or not rows:
            raise ValueError('Each training case needs nonempty input.pairs.')
        if any(not isinstance(row, list) or len(row) != 2 for row in rows):
            raise ValueError('Each training pair must contain x and target y.')
        pairs = [(finite(x, 'x'), finite(y, 'target')) for x, y in rows]
        weight = bias = 0.0
        losses = []
        for step in range(epochs + 1):
            errors = [weight * x + bias - y for x, y in pairs]
            loss = finite(sum(error * error for error in errors) / len(pairs), 'loss')
            losses.append([step, loss])
            if step < epochs:
                weight = finite(weight - rate * 2 * sum(error * x for error, (x, _) in zip(errors, pairs)) / len(pairs), 'weight')
                bias = finite(bias - rate * 2 * sum(errors) / len(pairs), 'bias')
        outputs.append(artifact(request, case, 'training-loss', 'series', {
            'kind': 'series', 'name': 'Synthetic training MSE',
            'xAxis': {'label': 'Optimization step', 'unit': 'step'},
            'yAxis': {'label': 'Mean squared error', 'unit': 'squared signal'},
            'points': losses}, settings))
        checkpoint = artifact(request, case, 'model-checkpoint', 'attachment', {
            'kind': 'attachment', 'uri': 'checkpoint.json', 'mimeType': 'application/json',
            'availability': 'unknown'}, settings)
        checkpoint['jsonDocument'] = {'schemaVersion': 'rws.synthetic-linear/v1',
            'weight': weight, 'bias': bias, 'steps': epochs, 'synthetic': True}
        outputs.append(checkpoint)
        log = artifact(request, case, 'training-log', 'attachment', {
            'kind': 'attachment', 'uri': 'training.jsonl', 'mimeType': 'application/x-ndjson',
            'availability': 'unknown'}, settings)
        log['textLog'] = ''.join(json.dumps({'metricId': 'loss', 'x': step, 'value': loss,
            'sampleId': case['sampleId'], 'eventId': case['sampleId'] + '/loss/' + str(step)}, allow_nan=False) + '\n' for step, loss in losses)
        outputs.append(log)
        statuses.append({'sampleId': case['sampleId'], 'status': 'completed'})
    return result(request, outputs, statuses)


if __name__ == '__main__':
    cli(run)
