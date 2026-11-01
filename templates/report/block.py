"""Compose a bounded reading summary without changing selected evidence."""
from copy import deepcopy
from _runtime import artifact, cases, cli, config, result, selected_artifacts


MAX_READING_SOURCES = 12
MAX_TABLE_ROWS = 5
MAX_TABLE_COLUMNS = 6
MAX_CELL_CHARACTERS = 160


def inline(value):
    """Display short scalar metadata; never expand nested data into the report."""
    if isinstance(value, (dict, list)):
        return '[structured data; see fixed evidence]'
    if value is None:
        return 'not supplied'
    text = str(value).replace('\n', ' ').replace('\r', ' ')
    if len(text) > MAX_CELL_CHARACTERS:
        text = text[:MAX_CELL_CHARACTERS] + '… [truncated]'
    for char in ('\\', '`', '*', '_', '[', ']', '<', '>', '|'):
        text = text.replace(char, '\\' + char)
    return text


def reading_summary(content):
    """Describe stored values only; scientific statistics belong to analysis."""
    kind = content['kind']
    if kind == 'metric':
        name = content.get('name') or content.get('metricId') or 'Stored metric'
        value = content.get('value')
        line = '- ' + inline(name) + ': ' + inline(value)
        if content.get('unit'):
            line += ' ' + inline(content['unit'])
        if value is None:
            line += ' (' + inline(content.get('status') or 'missing') + ')'
        lines = [line]
        for field in ('aggregation', 'reason'):
            if content.get(field):
                lines.append('- ' + field.capitalize() + ': ' + inline(content[field]))
        return lines
    if kind == 'series':
        points = content.get('points', [])
        lines = ['- Stored curve: ' + inline(content.get('name') or 'unnamed') + '.',
                 '- ' + str(len(points)) + ' points retained in fixed evidence; no points copied into this document.']
        for key, name in (('xAxis', 'Horizontal axis'), ('yAxis', 'Vertical axis')):
            axis = content.get(key) or {}
            if axis.get('label'):
                lines.append('- ' + name + ': ' + inline(axis['label']) +
                             (' (' + inline(axis['unit']) + ')' if axis.get('unit') else ''))
        return lines
    rows, columns = content.get('rows', []), content.get('columns', [])
    lines = ['- Stored analysis table: ' + str(len(rows)) + ' rows, ' + str(len(columns)) + ' columns.',
             '- Reading excerpt: first ' + str(min(len(rows), MAX_TABLE_ROWS)) +
             ' rows and ' + str(min(len(columns), MAX_TABLE_COLUMNS)) + ' columns; complete table remains in fixed evidence.']
    for index, row in enumerate(rows[:MAX_TABLE_ROWS]):
        values = []
        for position, column in enumerate(columns[:MAX_TABLE_COLUMNS]):
            key = column.get('key', '') if isinstance(column, dict) else column
            label = (column.get('label') or key) if isinstance(column, dict) else key
            if isinstance(row, dict):
                value = row.get(key)
            else:
                value = row[position] if isinstance(row, list) and position < len(row) else None
            values.append(inline(label) + ': ' + inline(value))
        lines.append('- Row ' + str(index + 1) + ': ' + '; '.join(values))
    return lines


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
                 '', '## Scope', '', '- Dataset: ' + inline(request['datasetId']),
                 '- Case: ' + inline(case['sampleId']), '- Task: ' + inline(case.get('task', 'inspect-signal')),
                 '- Fixed selection: ' + str(len(sources)) + ' existing artifacts.', '', '## Selected evidence']
        for source in sources[:MAX_READING_SOURCES]:
            lines.extend(['', '### ' + str(source.get('semantic', 'Evidence')), '',
                          'Source: `' + source['id'].replace('`', '').replace('\n', ' ') + '`', ''])
            lines.extend(reading_summary(source['content']))
        if len(sources) > MAX_READING_SOURCES:
            lines.extend(['', str(len(sources) - MAX_READING_SOURCES) +
                          ' additional selected artifacts are retained in inputIds and evidenceSnapshot; omitted from this reading summary.'])
        note = case.get('note')
        if note:
            if not isinstance(note, str):
                raise ValueError('note must be text.')
            lines.extend(['', '## Supplied interpretation', '', note])
        else:
            lines.extend(['', '## Supplied interpretation', '', 'No interpretation supplied.'])
        lines.extend(['', '## Reading limits', '',
                      'This document summarizes the fixed selection only. Excerpts are not the complete evidence and do not establish a conclusion. '
                      'Use the exact selected originals for evaluation and further analysis; the complete selected records remain in evidenceSnapshot.'])
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
