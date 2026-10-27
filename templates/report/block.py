"""Compose exact stored evidence into Markdown; does not compute metrics."""
import json
from copy import deepcopy
from _runtime import artifact, cases, cli, config, result, selected_artifacts


def run(request):
    selected = cases(request)
    settings = config(request, {'title': 'Synthetic evidence report'})
    if not isinstance(settings['title'], str) or not settings['title'].strip():
        raise ValueError('title must be nonempty text.')
    inputs = selected_artifacts(request)
    allowed = {('series', 'final-output'), ('metric', 'evaluation-metric'), ('table', 'signal-summary')}
    if any((item.get('kind'), item.get('semantic')) not in allowed for item in inputs):
        raise ValueError('Report inputs must match the declared final signal, evaluation metric or analysis table ports.')
    outputs, statuses = [], []
    for case in selected:
        sources = [a for a in inputs if a.get('sampleId') == case['sampleId']]
        if not sources:
            statuses.append({'sampleId': case['sampleId'], 'status': 'missing', 'reason': 'No selected evidence.'})
            continue
        lines = ['# ' + settings['title'].replace('\n', ' '), '', 'Synthetic example; no scientific conclusion.',
                 '', '## Case: ' + case['sampleId'].replace('\n', ' ')]
        for source in sources:
            lines.extend(['', '### ' + str(source.get('semantic', 'Evidence')), '',
                          'Source: `' + source['id'].replace('`', '') + '`', '', '```json',
                          json.dumps(source.get('content'), ensure_ascii=False, indent=2, allow_nan=False), '```'])
        note = case.get('note')
        if note:
            if not isinstance(note, str):
                raise ValueError('note must be text.')
            lines.extend(['', '## Supplied interpretation', '', note])
        item = artifact(request, case, 'report-document', 'attachment',
                        {'kind': 'attachment', 'uri': 'urn:rws:unmaterialized-report',
                         'mimeType': 'text/markdown', 'availability': 'unavailable'}, settings,
                        input_ids=[a['id'] for a in sources])
        item['markdown'] = '\n'.join(lines) + '\n'
        item['evidenceSnapshot'] = deepcopy(sources)
        outputs.append(item)
        statuses.append({'sampleId': case['sampleId'], 'status': 'completed'})
    return result(request, outputs, statuses)


if __name__ == '__main__':
    cli(run)
