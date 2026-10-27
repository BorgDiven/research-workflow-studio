import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from rws.core import Store, RwsError, tool_definitions


class CoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'studio.sqlite'
        self.store = Store(self.path)
        self.seq = 0
        self.create('p')
        self.create('q')

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def uid(self):
        self.seq += 1
        return 'request-' + str(self.seq)

    def create(self, pid):
        return self.store.call('rws_project_create', {'projectId': pid, 'name': pid, 'goal': 'Find out why', 'requestId': self.uid()})

    def write(self, op, pid='p', actor='model', **args):
        args.update(projectId=pid, expectedRevision=self.store.snapshot(pid)['revision'], requestId=self.uid())
        return self.store.call(op, args, actor=actor)['result']

    def record(self, record_type, pid='p', **record):
        names = {'research': 'save', 'experiment': 'save', 'analysis': 'save', 'comparison': 'save', 'evaluation': 'import', 'report': 'create_revision', 'conversation': 'save'}
        return self.write('rws_' + record_type + '_' + names.get(record_type, 'register'), pid, record=record)

    def fixture(self, pid='p'):
        h = self.record('research', pid, id='H1', title='Observation', question='What changes?', kind='exploration')
        e = self.record('experiment', pid, id='E1', title='Probe', researchRef=h['ref'], config={}, status='planned')
        c = self.record('code', pid, id='C1', title='Source', kind='inference', version='v1', source='source.py')
        r = self.record('run', pid, id='R1', title='Run', kind='inference', codeRef=c['ref'], config={'cfg': 4}, status='completed', inputRefs=[], experimentRef=e['ref'])
        a = self.record('artifact', pid, id='A1', title='Output', kind='image', producerRef=r['ref'], sampleId='S1', config={'cfg': 4}, availability='unknown')
        return h, e, c, r, a

    def expect(self, code, func):
        with self.assertRaises(RwsError) as cm:
            func()
        self.assertEqual(cm.exception.code, code)
        return cm.exception

    def test_projects_isolated_and_no_fixture_inheritance(self):
        snap = self.store.snapshot('q')
        self.assertEqual(snap['records'], [])
        self.assertEqual(snap['references'], [])
        self.assertEqual(len(snap['projects']), 2)
        self.assertEqual(snap['projects'][0]['activeStages'], [])
        self.assertIsNone(snap['projects'][0]['stagesConfirmedAt'])

    def test_retry_exact_response_and_different_payload_rejected(self):
        args = {'requestId': 'same-request', 'name': 'Third', 'projectId': 'third'}
        first = self.store.call('rws_project_create', args)
        self.assertEqual(first, self.store.call('rws_project_create', args))
        self.expect('idempotency_conflict', lambda: self.store.call('rws_project_create', dict(args, name='different')))
        self.assertEqual(len(self.store.snapshot()['projects']), 3)

    def test_stale_revision_rolls_back_and_request_can_be_retried_after_fix(self):
        args = {'requestId': 'stale', 'projectId': 'p', 'expectedRevision': 0, 'record': {'title': 'Q', 'question': 'why'}}
        self.expect('validation_error', lambda: self.store.call('rws_research_save', args))
        args['expectedRevision'] = 1
        self.store.call('rws_research_save', args)
        self.assertEqual(len(self.store.snapshot('p')['records']), 1)
        self.expect('revision_conflict', lambda: self.store.call('rws_research_save', dict(args, requestId='stale-again')))

    def test_concurrent_writes_only_one_expected_revision_wins(self):
        args = {'projectId': 'p', 'expectedRevision': 1, 'record': {'title': 'Q', 'question': 'why'}}
        def run(i):
            try:
                return self.store.call('rws_research_save', dict(args, requestId='race-' + str(i)))['ok']
            except RwsError as e:
                return e.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(run, [1, 2]))
        self.assertEqual(result.count(True), 1)
        self.assertEqual(result.count('revision_conflict'), 1)
        self.assertEqual(self.store.snapshot('p')['revision'], 2)

    def test_restart_retains_records_and_retry_result(self):
        args = {'requestId': 'restart-request', 'name': 'Restart', 'projectId': 'restart'}
        result = self.store.call('rws_project_create', args)
        reopened = Store(self.path)
        try:
            self.assertEqual(reopened.call('rws_project_create', args), result)
            self.assertEqual(reopened.snapshot('restart')['revision'], 1)
        finally:
            reopened.close()

    def test_research_optional_hypothesis_and_judgment_control(self):
        self.record('research', title='Probe', question='What happens?', kind='exploration')
        self.expect('validation_error', lambda: self.record('research', title='Missing', question='why', kind='hypothesis'))
        self.expect('approval_required', lambda: self.record('research', title='Claim', question='why', kind='hypothesis', hypothesis='It helps', judgment='supported'))

    def test_research_dag_rejects_cycles_and_foreign_parent(self):
        a = self.record('research', id='A', title='A', question='A?')
        b = self.record('research', id='B', title='B', question='B?', parentRefs=[a['ref']])
        self.expect('validation_error', lambda: self.record('research', id='A', title='A', question='A?', parentRefs=[b['ref']]))
        self.expect('validation_error', lambda: self.record('research', 'q', title='Q', question='Q?', parentRefs=[a['ref']]))

    def test_code_artifact_and_run_producer_immutability(self):
        h, e, c, r, a = self.fixture()
        self.expect('immutable_source', lambda: self.record('code', **c['record']))
        self.expect('immutable_source', lambda: self.record('artifact', **dict(a['record'], producerRef=r['ref'])))
        changed = dict(r['record'], config={'cfg': 5})
        self.expect('immutable_source', lambda: self.record('run', **changed))
        second = self.record('run', **dict(r['record'], status='partial'))
        self.assertEqual(second['ref']['version'], 2)
        self.assertEqual(self.store.call('rws_record_get', {'ref': a['ref']})['result']['record']['producerRef']['version'], 1)

    def test_planned_run_cannot_claim_artifacts(self):
        c = self.record('code', title='C', kind='inference', version='v1', source='code')
        r = self.record('run', title='R', codeRef=c['ref'], status='planned')
        self.expect('validation_error', lambda: self.record('artifact', title='A', kind='image', producerRef=r['ref'], config={}))

    def test_cross_project_usage_revoke_preserves_producer(self):
        _, _, _, _, a = self.fixture()
        h = self.record('research', 'q', title='Q', question='why')
        e = self.record('experiment', 'q', title='E', researchRef=h['ref'])
        u = self.write('rws_usage_save', 'q', experimentRef=e['ref'], artifactRefs=[a['ref']], role='control')
        external = self.store.snapshot('q')['references']
        self.assertTrue(any(x['ref'] == a['ref'] for x in external))
        self.write('rws_usage_remove', 'q', id=u['record']['id'])
        self.assertEqual(self.store.call('rws_record_get', {'ref': a['ref']})['result'], a)
        self.assertTrue(any(x['record'].get('revoked') for x in self.store.snapshot('q')['records']))

    def test_usage_cannot_silently_target_other_project_experiment(self):
        _, e, _, _, a = self.fixture()
        self.expect('validation_error', lambda: self.write('rws_usage_save', 'q', experimentRef=e['ref'], artifactRefs=[a['ref']], role='control'))

    def proposal(self, **fields):
        return self.write('rws_overview_propose', fields=fields or {'consensus': 'A tentative implication'}, reason='Please review', baseRevision=1)

    def test_model_cannot_apply_foundation_or_stage(self):
        p = self.proposal()
        error = self.expect('approval_required', lambda: self.write('rws_overview_apply', proposalRef=p['ref'], baseRevision=1))
        self.assertEqual(error.details['reviewUrl'], '/?projectId=p&review=1')
        self.expect('approval_required', lambda: self.write('rws_project_stages_set', activeStages=['formal']))
        self.create('p:scope')
        encoded = self.expect('approval_required', lambda: self.write('rws_project_stages_set', 'p:scope', activeStages=['formal']))
        self.assertEqual(encoded.details['reviewUrl'], '/?projectId=p%3Ascope&stages=1')
        args = {'requestId': self.uid(), 'projectId': 'p', 'expectedRevision': self.store.snapshot('p')['revision'], 'proposalRef': p['ref'], 'baseRevision': 1, 'approved': True}
        self.expect('validation_error', lambda: self.store.call('rws_overview_apply', args))

    def test_human_applies_exact_draft_only_and_preserves_experiment_foundation(self):
        _, exp, _, _, _ = self.fixture()
        first = self.proposal()
        replacement = self.proposal(consensus='Replacement')
        self.expect('revision_conflict', lambda: self.write('rws_overview_apply', actor='human', proposalRef=first['ref'], baseRevision=1))
        result = self.write('rws_overview_apply', actor='human', proposalRef=replacement['ref'], baseRevision=1)
        self.assertEqual(result['foundation']['revision'], 2)
        self.assertEqual(self.store.call('rws_record_get', {'ref': exp['ref']})['result']['record']['foundationRevision'], 1)
        ctx = self.store.call('rws_get_context', {'projectId': 'p', 'experimentRef': exp['ref']})['result']
        self.assertEqual(ctx['foundation']['revision'], 1)
        self.assertEqual(ctx['latestFoundationRevision'], 2)

    def test_stage_metadata_does_not_modify_foundation(self):
        self.write('rws_project_stages_set', actor='human', activeStages=['formal', 'idea'])
        p = next(x for x in self.store.snapshot()['projects'] if x['id'] == 'p')
        self.assertEqual(p['activeStages'], ['idea', 'formal'])
        self.assertEqual(len(p['versions']), 1)
        self.store.call('rws_get_context', {'projectId': 'p'})
        self.assertEqual(self.store.snapshot('p')['revision'], p['revision'])

    def test_report_keeps_frozen_transitive_inputs_after_source_revision(self):
        h, e, c, r, a = self.fixture()
        report = self.record('report', id='REPORT', title='Report', inputRefs=[a['ref']], analysisRefs=[], evaluationRefs=[], markdown='Initial')
        self.record('run', **dict(r['record'], status='partial'))
        proposal = self.proposal()
        self.write('rws_overview_apply', actor='human', proposalRef=proposal['ref'], baseRevision=1)
        new_report = self.record('report', id='REPORT', title='Report', inputRefs=[a['ref']], analysisRefs=[], evaluationRefs=[], markdown='Next')
        self.assertEqual(new_report['ref']['version'], 2)
        self.assertEqual(new_report['record']['foundationRevision'], 2)
        original = self.store.call('rws_record_get', {'ref': report['ref']})['result']
        self.assertEqual(original, report)
        saved_run = next(x for x in original['record']['snapshot']['records'] if x['ref']['type'] == 'run')
        self.assertEqual(saved_run['record']['status'], 'completed')
        self.assertEqual(saved_run['ref']['version'], 1)

    def eval_fixture(self, paired=False):
        h, e, c, r, a = self.fixture()
        b = self.record('artifact', title='Reference', kind='image', producerRef=r['ref'], sampleId='S1', config={})
        ec = self.record('code', title='Evaluator', kind='evaluation', version='v1', source='eval.py')
        protocol = self.record('protocol', title='P', version='v1', inputKind='paired-image' if paired else 'artifact', metrics=[{'name': 'score', 'unit': 'dB', 'direction': 'higher', 'granularity': 'sample', 'min': 0, 'max': 100}], preprocessing='none', aggregation='successful mean', missingPolicy='explicit')
        record = {'title': 'Eval', 'protocolRef': protocol['ref'], 'codeRef': ec['ref'], 'inputRefs': [a['ref'], b['ref']], 'results': [{'kind': 'metric', 'name': 'score', 'unit': 'dB', 'value': 0, 'sampleId': 'S1'}], 'status': 'completed'}
        return record, a, b

    def test_metric_zero_is_value_unknown_is_explicit(self):
        record, _, _ = self.eval_fixture()
        result = self.record('evaluation', **record)
        self.assertEqual(result['record']['results'][0]['value'], 0)
        for bad in ({'value': None}, {'value': float('nan')}, {'unit': 'percent'}, {'sampleId': 'missing'}, {'value': 101}):
            item = copy.deepcopy(record)
            item['results'][0].update(bad)
            self.expect('validation_error', lambda item=item: self.record('evaluation', **item))

    def test_failed_sample_cannot_be_numeric_or_completed(self):
        record, _, _ = self.eval_fixture()
        record['sampleStatuses'] = [{'sampleId': 'S1', 'status': 'failed', 'reason': 'missing input'}]
        self.expect('validation_error', lambda: self.record('evaluation', **record))
        record['results'] = [{'kind': 'metric', 'name': 'score', 'unit': 'dB', 'value': None, 'sampleId': 'S1', 'status': 'failed', 'reason': 'missing input'}]
        record['status'] = 'partial'
        self.record('evaluation', **record)

    def test_pairing_must_be_explicit_and_match_input_sample(self):
        record, a, b = self.eval_fixture(paired=True)
        self.expect('validation_error', lambda: self.record('evaluation', **record))
        record['pairs'] = [{'sampleId': 'S1', 'predictionRef': a['ref'], 'referenceRef': b['ref']}]
        self.record('evaluation', **record)
        wrong = copy.deepcopy(record)
        wrong['pairs'][0]['sampleId'] = 'S2'
        self.expect('validation_error', lambda: self.record('evaluation', **wrong))
        wrong['pairs'][0]['sampleId'] = 'S1'
        wrong['pairs'][0]['referenceRef'] = a['ref']
        self.expect('validation_error', lambda: self.record('evaluation', **wrong))

    def test_series_table_attachment_and_image_set(self):
        _, _, _, r, a = self.fixture()
        results = [
            {'kind': 'series', 'xAxis': {'label': 'step', 'unit': 'step'}, 'yAxis': {'label': 'loss', 'unit': ''}, 'points': [{'x': 0, 'y': 1}, {'x': 1, 'y': .5}]},
            {'kind': 'table', 'columns': [{'key': 'value', 'type': 'number'}], 'rows': [{'value': 0}, {'value': None}]},
            {'kind': 'attachment', 'uri': 'unresolved://data', 'mimeType': 'text/plain'},
            {'kind': 'image-set', 'items': [{'artifactRef': a['ref'], 'sampleId': 'S1'}]},
        ]
        for result in results:
            self.record('artifact', title='Typed', kind=result['kind'], producerRef=r['ref'], config={}, content=result)
        bad = copy.deepcopy(results[0]); bad['points'][0]['y'] = 'not a number'
        self.expect('validation_error', lambda: self.record('artifact', title='Bad', kind='series', producerRef=r['ref'], content=bad))
        bad = copy.deepcopy(results[1]); bad['rows'][0]['value'] = 'string'
        self.expect('validation_error', lambda: self.record('artifact', title='Bad', kind='table', producerRef=r['ref'], content=bad))

    def test_context_mismatch_and_source_identity_rejection(self):
        h, e, _, _, _ = self.fixture()
        other = self.record('research', title='Other', question='Other?')
        self.expect('validation_error', lambda: self.store.call('rws_get_context', {'projectId': 'p', 'researchRef': other['ref'], 'experimentRef': e['ref']}))
        self.expect('validation_error', lambda: self.store.call('rws_get_context', {'projectId': 'q', 'researchRef': h['ref']}))
        self.expect('not_found', lambda: self.store.call('rws_record_get', {'ref': dict(h['ref'], type='run')}))
        ctx = self.store.call('rws_get_context', {'projectId': 'p', 'experimentRef': e['ref']})['result']
        self.assertEqual(len(ctx['completed']), 1)
        self.assertTrue(ctx['suggestedActions'])

    def test_model_update_preserves_human_judgment_and_cannot_change_stage(self):
        saved = self.write('rws_research_save', actor='human', record={'id': 'J', 'title': 'Claim', 'question': 'Does it work?', 'kind': 'hypothesis', 'hypothesis': 'It helps', 'stage': 'idea', 'judgment': 'insufficient'})
        revised = dict(saved['record'])
        del revised['judgment']
        updated = self.write('rws_research_save', record=revised)
        self.assertEqual(updated['record']['judgment'], 'insufficient')
        self.expect('approval_required', lambda: self.write('rws_research_save', record=dict(revised, stage='formal')))
        self.expect('approval_required', lambda: self.write('rws_research_save', record=dict(revised, hypothesis='Entirely different claim')))

    def test_context_contains_source_objects_but_not_report_body(self):
        h, e, c, r, a = self.fixture()
        self.write('rws_usage_save', experimentRef=e['ref'], artifactRefs=[a['ref']], role='observation')
        report = self.record('report', title='Report', inputRefs=[a['ref']], analysisRefs=[], evaluationRefs=[], markdown='DO NOT EXPAND THIS BODY')
        context = self.store.call('rws_get_context', {'projectId': 'p', 'experimentRef': e['ref'], 'selectionRefs': [report['ref']]})['result']
        types = {o['ref']['type'] for o in context['objects']}
        self.assertTrue({'code', 'run', 'artifact', 'report'} <= types)
        self.assertNotIn('DO NOT EXPAND THIS BODY', json.dumps(context))
        self.assertFalse(context['objectsTruncated'])

    def test_context_missing_evaluation_matches_exact_protocol(self):
        evaluation, a, b = self.eval_fixture()
        h = self.record('research', title='Claim', question='Does it work?', kind='hypothesis', hypothesis='It helps')
        e = self.record('experiment', title='Expected protocol', researchRef=h['ref'], protocolRef=evaluation['protocolRef'])
        self.write('rws_usage_save', experimentRef=e['ref'], artifactRefs=[a['ref']], role='treatment')
        other_protocol = self.record('protocol', title='Other', version='v2', metrics=[{'name': 'score', 'unit': 'dB', 'direction': 'higher', 'granularity': 'sample'}], preprocessing='none', aggregation='mean', missingPolicy='explicit')
        self.record('evaluation', **dict(evaluation, protocolRef=other_protocol['ref']))
        def gaps():
            c = self.store.call('rws_get_context', {'projectId': 'p', 'experimentRef': e['ref']})['result']
            return [x for x in c['pending'] if x.get('protocolRef')]
        self.assertEqual(len(gaps()), 1)
        self.record('evaluation', **evaluation)
        self.assertEqual(gaps(), [])

    def test_published_schemas_describe_record_fields_and_typed_results(self):
        defs = {d['name']: d for d in tool_definitions()}
        schema = defs['rws_evaluation_import']['inputSchema']['properties']['record']
        self.assertTrue({'protocolRef', 'codeRef', 'inputRefs', 'results'} <= set(schema['required']))
        self.assertEqual(len(schema['properties']['results']['items']['oneOf']), 5)
        for definition in defs.values():
            for field in definition['inputSchema']['properties'].values():
                self.assertTrue(field)
        self.expect('validation_error', lambda: self.record('research', title='Q', question='why', parentRefs='bad type'))

    def test_write_guidance_is_scoped_and_saved_with_idempotent_response(self):
        created = self.create('new-guidance')
        self.assertEqual(created['guidance']['scope'], 'project')
        self.assertIsNone(created['guidance']['position']['researchRef'])
        h, e, c, r, a = self.fixture()
        args = {'projectId': 'p', 'expectedRevision': self.store.snapshot('p')['revision'], 'requestId': 'guidance-retry', 'experimentRef': e['ref'], 'artifactRefs': [a['ref']], 'role': 'observation'}
        first = self.store.call('rws_usage_save', args)
        guidance = first['guidance']
        self.assertEqual(guidance['position']['experimentRef'], e['ref'])
        self.assertEqual(guidance['revision'], first['revision'])
        self.assertTrue({'code', 'run', 'artifact'} <= {o['ref']['type'] for o in guidance['objects']})
        self.record('research', title='Later unrelated change', question='Later?')
        self.assertEqual(self.store.call('rws_usage_save', args), first)
        self.assertEqual(guidance['scope'], 'affected-experiment')

    def test_proposal_guidance_requires_human_and_omits_large_fields(self):
        h, e, c, r, a = self.fixture()
        args = {'projectId': 'p', 'expectedRevision': self.store.snapshot('p')['revision'], 'requestId': self.uid(), 'record': {'title': 'Large report', 'markdown': 'BIG-CONTENT-' * 5000, 'inputRefs': [a['ref']]}}
        report = self.store.call('rws_report_create_revision', args)
        self.assertNotIn('BIG-CONTENT-', json.dumps(report['guidance']))
        result = self.store.call('rws_overview_propose', {'projectId': 'p', 'expectedRevision': report['revision'], 'requestId': self.uid(), 'fields': {'consensus': 'Review me'}, 'reason': 'Example', 'baseRevision': 1})
        action = result['guidance']['suggestedActions'][0]
        self.assertTrue(action['requiresHuman'])
        self.assertEqual(action['reviewUrl'], '/?projectId=p&review=1')
        self.assertEqual(action['targetRef'], result['result']['ref'])
        self.assertEqual(result['guidance']['scope'], 'project')

    def test_project_list_summary_counts_latest_own_records(self):
        h, e, c, r, a = self.fixture()
        projects = self.store.call('rws_project_list', {})['result']
        summary = next(p for p in projects if p['id'] == 'p')['summary']
        self.assertEqual(summary, {'researchCount': 1, 'completedRunCount': 1, 'plannedExperimentCount': 1, 'evaluationCount': 0, 'artifactCount': 1})
        self.assertEqual(next(p for p in projects if p['id'] == 'q')['summary']['artifactCount'], 0)
        self.record('run', **dict(r['record'], status='partial'))
        summary = next(p for p in self.store.snapshot('p')['projects'] if p['id'] == 'p')['summary']
        self.assertEqual(summary['completedRunCount'], 0)
        self.assertEqual(summary['researchCount'], 1)
        self.assertEqual(summary['artifactCount'], 1)

    def test_project_summary_reads_do_not_write_document_or_revision(self):
        self.fixture()
        connection = self.store._connect()
        before = connection.execute('SELECT document FROM projects WHERE id=?', ('p',)).fetchone()['document']
        self.store.snapshot()
        self.store.call('rws_project_list', {})
        after = connection.execute('SELECT document FROM projects WHERE id=?', ('p',)).fetchone()['document']
        connection.close()
        self.assertEqual(before, after)
        self.assertNotIn('summary', json.loads(after))

    def test_bound_experiment_context_exposes_current_human_judgment_separately(self):
        research = self.record('research', title='Claim', question='Does it help?', kind='hypothesis', hypothesis='It may help')
        experiment = self.record('experiment', title='Original experiment', researchRef=research['ref'])
        current = self.write('rws_research_save', actor='human', record=dict(research['record'], judgment={'label': 'insufficient', 'summary': 'Need more evidence'}))
        context = self.store.call('rws_get_context', {'projectId': 'p', 'experimentRef': experiment['ref']})['result']
        self.assertEqual(context['position']['researchRef'], research['ref'])
        self.assertEqual(context['currentResearchRef'], current['ref'])
        self.assertEqual(context['currentResearch']['judgment']['label'], 'insufficient')
        self.assertEqual(context['foundation']['revision'], 1)
        self.assertIn('r1', context['researchVersionNotice'])
        self.assertIn('r2', context['researchVersionNotice'])
        research_refs = [item['ref'] for item in context['objects'] if item['ref']['type'] == 'research']
        self.assertIn(research['ref'], research_refs)
        self.assertIn(current['ref'], research_refs)
        unchanged = self.store.call('rws_record_get', {'ref': experiment['ref']})['result']
        self.assertEqual(unchanged, experiment)

    def test_strict_fields_and_tools_no_execution_or_arbitrary_write(self):
        self.expect('validation_error', lambda: self.record('research', title='Q', question='why', arbitrary=True))
        self.expect('not_found', lambda: self.store.call('run_shell', {'command': 'nothing'}))
        defs = tool_definitions()
        self.assertTrue(all(x['inputSchema']['additionalProperties'] is False for x in defs))
        self.assertEqual(len({x['name'] for x in defs}), len(defs))


if __name__ == '__main__':
    unittest.main()
