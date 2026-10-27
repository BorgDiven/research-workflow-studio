"""User-workflow regressions found after the initial two-project trial."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from rws.core import Store, RwsError


class CoreAuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'audit.sqlite')
        self.seq = 0
        self.store.call('rws_project_create', {'requestId': 'create', 'projectId': 'p', 'name': 'Audit'})

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def call(self, name, actor='model', **args):
        self.seq += 1
        args.update(requestId='audit-' + str(self.seq), projectId='p', expectedRevision=self.store.snapshot('p')['revision'])
        return self.store.call(name, args, actor=actor)['result']

    def research(self, **fields):
        return self.call('rws_research_save', record=dict(title='Question', question='What changes?', **fields))

    def reject(self, fn):
        with self.assertRaises(RwsError) as failure:
            fn()
        self.assertEqual(failure.exception.code, 'validation_error')

    def source(self):
        h = self.research()
        e = self.call('rws_experiment_save', record={'title': 'Experiment', 'researchRef': h['ref'], 'config': {'cfg': 4}})
        c = self.call('rws_code_register', record={'title': 'Code', 'kind': 'inference', 'version': 'v1', 'source': {'path': 'registered-only.py'}})
        r = self.call('rws_run_register', record={'title': 'Run', 'codeRef': c['ref'], 'experimentRef': e['ref'], 'config': {'cfg': 4}, 'status': 'completed', 'inputRefs': []})
        return h, e, c, r

    def artifact(self, run, sample='s1'):
        record = {'title': 'Image', 'kind': 'image', 'producerRef': run['ref'], 'config': {}}
        if sample is not None:
            record['sampleId'] = sample
        return self.call('rws_artifact_register', record=record)

    def evaluation(self, paired=False, extra_sample=False, granularity='sample'):
        h, e, c, r = self.source()
        a = self.artifact(r)
        b = self.artifact(r, 's2') if extra_sample else self.artifact(r)
        ec = self.call('rws_code_register', record={'title': 'Evaluator', 'kind': 'evaluation', 'version': 'v1', 'source': 'evaluator.py'})
        p = self.call('rws_protocol_register', record={'title': 'Protocol', 'version': 'v1', 'inputKind': 'paired-image' if paired else 'artifact', 'metrics': [{'name': 'psnr', 'unit': 'dB', 'direction': 'higher', 'granularity': granularity}], 'preprocessing': 'none', 'aggregation': 'mean', 'missingPolicy': 'explicit'})
        rec = {'title': 'Evaluation', 'protocolRef': p['ref'], 'codeRef': ec['ref'], 'inputRefs': [a['ref'], b['ref']], 'results': [{'kind': 'metric', 'name': 'psnr', 'value': 20, 'unit': 'dB', 'sampleId': 's1'}], 'status': 'completed'}
        if paired:
            rec['pairs'] = [{'sampleId': 's1', 'predictionRef': a['ref'], 'referenceRef': b['ref']}]
        return rec, a, b, r

    def test_partial_research_update_preserves_structure_and_semantics(self):
        parent = self.research()
        saved = self.research(kind='hypothesis', hypothesis='A testable claim', parentRefs=[parent['ref']])
        updated = self.call('rws_research_save', record={'id': saved['record']['id'], 'title': 'Renamed'})
        for key in ('question', 'kind', 'hypothesis', 'parentRefs', 'stage'):
            self.assertEqual(updated['record'][key], saved['record'][key])
        self.assertEqual(updated['ref']['version'], 2)
        self.reject(lambda: self.call('rws_research_save', record={'id': 'new-but-incomplete', 'title': 'No question'}))

    def test_status_only_updates_keep_experiment_and_run_bindings(self):
        h, e, c, r = self.source()
        updated = self.call('rws_experiment_save', record={'id': e['record']['id'], 'status': 'completed'})
        for key in ('researchRef', 'config', 'foundationRevision'):
            self.assertEqual(updated['record'][key], e['record'][key])
        run = self.call('rws_run_register', record={'id': r['record']['id'], 'status': 'partial'})
        for key in ('codeRef', 'experimentRef', 'config', 'inputRefs'):
            self.assertEqual(run['record'][key], r['record'][key])

    def test_current_research_with_historical_experiment_is_valid_context(self):
        h, e, _, _ = self.source()
        current = self.call('rws_research_save', record={'id': h['record']['id'], 'title': 'Current title'})
        context = self.store.call('rws_get_context', {'projectId': 'p', 'researchRef': current['ref'], 'experimentRef': e['ref']})['result']
        self.assertEqual(context['position']['researchRef'], h['ref'])
        self.assertEqual(context['currentResearchRef'], current['ref'])
        self.assertTrue(context['researchVersionNotice'])

    def test_completed_evaluation_requires_real_declared_metric_results(self):
        record, _, _, _ = self.evaluation()
        self.reject(lambda: self.call('rws_evaluation_import', record=dict(record, results=[])))
        self.reject(lambda: self.call('rws_evaluation_import', record=dict(record, results=[{'kind': 'table', 'columns': [], 'rows': []}])))
        self.call('rws_evaluation_import', record=record)

    def test_duplicate_inputs_and_conflicting_metric_values_rejected(self):
        record, a, _, _ = self.evaluation()
        self.reject(lambda: self.call('rws_evaluation_import', record=dict(record, inputRefs=[a['ref'], a['ref']])))
        other = dict(record['results'][0], value=40)
        self.reject(lambda: self.call('rws_evaluation_import', record=dict(record, results=record['results'] + [other])))

    def test_result_direction_and_failure_status_must_match_meaning(self):
        record, _, _, _ = self.evaluation()
        for changes in ({'direction': 'lower'}, {'status': 'failed'}, {'status': 'missing'}):
            bad = dict(record['results'][0], **changes)
            self.reject(lambda bad=bad: self.call('rws_evaluation_import', record=dict(record, results=[bad])))

    def test_completed_sample_metrics_cover_selected_samples(self):
        record, _, _, _ = self.evaluation(extra_sample=True)
        self.reject(lambda: self.call('rws_evaluation_import', record=record))
        self.call('rws_evaluation_import', record=dict(record, status='partial'))

    def test_dataset_metric_must_not_be_mislabeled_as_single_sample(self):
        record, _, _, _ = self.evaluation(granularity='dataset')
        self.reject(lambda: self.call('rws_evaluation_import', record=record))
        aggregate = dict(record['results'][0]); del aggregate['sampleId']
        aggregate.update(sampleIds=['s1'], aggregation='mean')
        self.call('rws_evaluation_import', record=dict(record, results=[aggregate]))

    def test_paired_inputs_cannot_hide_unpaired_artifacts_or_missing_sample(self):
        record, _, _, run = self.evaluation(paired=True)
        extra = self.artifact(run)
        self.reject(lambda: self.call('rws_evaluation_import', record=dict(record, inputRefs=record['inputRefs'] + [extra['ref']])))
        unknown = self.artifact(run, None)
        self.reject(lambda: self.call('rws_evaluation_import', record=dict(record, inputRefs=record['inputRefs'] + [unknown['ref']])))

    def test_protocol_rejects_impossible_declared_range(self):
        self.reject(lambda: self.call('rws_protocol_register', record={'title': 'Invalid', 'version': 'v1', 'metrics': [{'name': 'x', 'unit': '', 'direction': 'higher', 'granularity': 'sample', 'min': 10, 'max': 0}], 'preprocessing': 'none', 'aggregation': 'mean', 'missingPolicy': 'explicit'}))


    def test_unresolved_provenance_is_explicit_without_invented_run(self):
        record = {'title': 'Recovered image', 'kind': 'image', 'provenance': 'unresolved', 'source': {'originalPath': '/archive/output.png', 'manifest': 'legacy.json'}, 'description': 'File exists, producer run and code have not been established.'}
        saved = self.call('rws_artifact_register', record=record)
        self.assertNotIn('producerRef', saved['record'])
        self.assertEqual(saved['record']['provenance'], 'unresolved')
        context = self.store.call('rws_get_context', {'projectId': 'p', 'selectionRefs': [saved['ref']]})['result']
        item = next(v for v in context['objects'] if v['ref'] == saved['ref'])
        self.assertEqual(item['provenance'], 'unresolved')
        self.assertFalse(any(v['ref']['type'] in ('code', 'run') for v in context['objects']))
        for updates in ({'description': ''}, {'source': '   '}, {'source': {}}, {'provenance': 'known'}):
            self.reject(lambda updates=updates: self.call('rws_artifact_register', record=dict(record, **updates)))
        missing = dict(record); del missing['provenance']
        self.reject(lambda: self.call('rws_artifact_register', record=missing))

    def test_unresolved_label_does_not_waive_actual_producer_validation(self):
        code = self.call('rws_code_register', record={'title': 'Code', 'kind': 'inference', 'version': 'v1', 'source': 'x.py'})
        planned = self.call('rws_run_register', record={'title': 'Planned', 'codeRef': code['ref']})
        self.reject(lambda: self.call('rws_artifact_register', record={'title': 'Not produced yet', 'kind': 'image', 'producerRef': planned['ref'], 'provenance': 'unresolved', 'source': 'archive.json', 'description': 'Unresolved producer'}))
        self.reject(lambda: self.call('rws_artifact_register', record={'title': 'Not a run', 'kind': 'image', 'producerRef': code['ref'], 'provenance': 'unresolved', 'source': 'archive.json', 'description': 'Unresolved producer'}))

    def test_chained_reports_flatten_dependencies_and_preserve_exact_history(self):
        artifact = self.call('rws_artifact_register', record={'title': 'Legacy evidence', 'kind': 'image', 'provenance': 'unresolved', 'source': 'legacy.png', 'description': 'Producer unavailable'})
        reports, sizes = [], []
        inputs = [artifact['ref']]
        for index in range(12):
            report = self.call('rws_report_create_revision', record={'title': 'Report ' + str(index), 'markdown': 'Historical conclusion. ' * 12, 'inputRefs': inputs})
            reports.append(copy.deepcopy(report))
            sizes.append(len(json.dumps(report)))
            inputs = [report['ref']]
        snapshot = reports[-1]['record']['snapshot']
        fixed = {json.dumps(v['ref'], sort_keys=True): v for v in snapshot['records']}
        self.assertEqual(len(fixed), 12)  # One artifact and the eleven earlier reports.
        self.assertLess(sizes[-1] / sizes[-2], 1.3)
        self.assertLess(sizes[-1], 40000)
        self.assertEqual(fixed[json.dumps(artifact['ref'], sort_keys=True)]['record'], artifact['record'])
        for envelope in snapshot['records']:
            if envelope['ref']['type'] == 'report':
                nested = envelope['record']['snapshot']
                self.assertNotIn('records', nested)
                for ref in nested['recordRefs']:
                    self.assertIn(json.dumps(ref, sort_keys=True), fixed)
        for original in reports[:-1]:
            reread = self.store.call('rws_record_get', {'ref': original['ref']})['result']
            self.assertEqual(reread, original)

    def test_report_keeps_old_and_cross_project_foundation_bodies(self):
        _, experiment, _, _ = self.source()
        old_foundation = copy.deepcopy(self.store.snapshot('p')['projects'][0]['versions'][0])
        proposal = self.call('rws_overview_propose', fields={'goal': 'New direction'}, reason='Review', baseRevision=1)
        self.call('rws_overview_apply', actor='human', proposalRef=proposal['ref'], baseRevision=1)
        self.store.call('rws_project_create', {'requestId': 'cross-create', 'projectId': 'q', 'name': 'Other', 'goal': 'Foreign project context'})
        foreign_research = self.store.call('rws_research_save', {'requestId': 'cross-r', 'projectId': 'q', 'expectedRevision': 1, 'record': {'title': 'Foreign question', 'question': 'Why?'}})['result']
        foreign_experiment = self.store.call('rws_experiment_save', {'requestId': 'cross-e', 'projectId': 'q', 'expectedRevision': 2, 'record': {'title': 'Foreign experiment', 'researchRef': foreign_research['ref']}})['result']
        report = self.call('rws_report_create_revision', record={'title': 'Context preserved', 'markdown': 'Compare contexts', 'inputRefs': [experiment['ref'], foreign_experiment['ref']]})
        snapshot = report['record']['snapshot']
        self.assertEqual(snapshot['foundation']['revision'], 2)
        contexts = {(v['projectId'], v['foundation']['revision']): v['foundation'] for v in snapshot['projectFoundations']}
        self.assertEqual(set(contexts), {('p', 1), ('p', 2), ('q', 1)})
        self.assertEqual(contexts[('p', 1)], old_foundation)
        self.assertEqual(contexts[('q', 1)]['fields']['goal'], 'Foreign project context')

    def test_revoked_usage_leaves_automatic_context_but_history_remains_readable(self):
        _, experiment, _, _ = self.source()
        self.store.call('rws_project_create', {'requestId': 'q-create', 'projectId': 'q', 'name': 'Source'})
        artifact = self.store.call('rws_artifact_register', {'requestId': 'q-artifact', 'projectId': 'q', 'expectedRevision': 1, 'record': {'title': 'Foreign output', 'kind': 'image', 'provenance': 'unresolved', 'source': 'legacy.png', 'description': 'Unknown producer'}})['result']
        usage = self.call('rws_usage_save', experimentRef=experiment['ref'], artifactRefs=[artifact['ref']], role='baseline')
        before = self.store.call('rws_get_context', {'projectId': 'p', 'experimentRef': experiment['ref']})['result']
        self.assertIn(artifact['ref'], [v['ref'] for v in before['objects']])
        self.call('rws_usage_remove', id=usage['record']['id'])
        after = self.store.call('rws_get_context', {'projectId': 'p', 'experimentRef': experiment['ref']})['result']
        self.assertNotIn(artifact['ref'], [v['ref'] for v in after['objects']])
        historical = self.store.call('rws_get_context', {'projectId': 'p', 'experimentRef': experiment['ref'], 'selectionRefs': [usage['ref']]})['result']
        self.assertIn(artifact['ref'], [v['ref'] for v in historical['objects']])
        self.assertEqual(self.store.call('rws_record_get', {'ref': artifact['ref']})['result'], artifact)

    def test_image_set_references_real_artifacts_with_consistent_sample_labels(self):
        _, _, code, run = self.source()
        artifact = self.artifact(run, 'actual-sample')
        base = {'title': 'Image collection', 'kind': 'image-set', 'producerRef': run['ref']}
        for item in ({'artifactRef': code['ref']}, {'artifactRef': artifact['ref'], 'sampleId': 'different-sample'}):
            self.reject(lambda item=item: self.call('rws_artifact_register', record=dict(base, content={'kind': 'image-set', 'items': [item]})))
        self.call('rws_artifact_register', record=dict(base, content={'kind': 'image-set', 'items': [{'artifactRef': artifact['ref'], 'sampleId': 'actual-sample'}]}))

    def test_conversation_cannot_bind_two_distinct_research_questions(self):
        research, experiment, _, _ = self.source()
        other = self.research()
        base = {'title': 'Discussion', 'uri': 'codex://example', 'experimentRef': experiment['ref']}
        self.reject(lambda: self.call('rws_conversation_save', record=dict(base, researchRef=other['ref'])))
        updated = self.call('rws_research_save', record={'id': research['record']['id'], 'title': 'Current question title'})
        self.call('rws_conversation_save', record=dict(base, researchRef=updated['ref']))

    def test_human_null_judgment_clears_decision_without_rewriting_history(self):
        saved = self.call('rws_research_save', actor='human', record={'title': 'Human judgment', 'question': 'Does it help?', 'kind': 'hypothesis', 'hypothesis': 'It helps.', 'judgment': {'label': '支持'}})
        preserved = self.call('rws_research_save', record={'id': saved['record']['id'], 'title': 'Retitled'})
        self.assertEqual(preserved['record']['judgment'], {'label': '支持'})
        cleared = self.call('rws_research_save', actor='human', record={'id': saved['record']['id'], 'judgment': None})
        self.assertNotIn('judgment', cleared['record'])
        self.assertEqual(cleared['record']['hypothesis'], 'It helps.')
        self.assertEqual(self.store.call('rws_record_get', {'ref': saved['ref']})['result'], saved)

    def test_model_cannot_clear_human_judgment_or_its_hypothesis(self):
        saved = self.call('rws_research_save', actor='human', record={'title': 'Human judgment', 'question': 'Does it help?', 'kind': 'hypothesis', 'hypothesis': 'It helps.', 'judgment': {'label': '支持'}})
        before = self.store.snapshot('p')['revision']
        for changes in ({'judgment': None}, {'kind': 'exploration', 'hypothesis': None}, {'kind': 'exploration', 'hypothesis': None, 'judgment': None}):
            with self.assertRaises(RwsError) as error:
                self.call('rws_research_save', record=dict(id=saved['record']['id'], **changes))
            self.assertEqual(error.exception.code, 'approval_required')
        self.assertEqual(self.store.snapshot('p')['revision'], before)
        self.assertEqual(self.store.call('rws_record_get', {'ref': saved['ref']})['result'], saved)

    def test_human_can_clear_statement_and_decision_when_returning_to_exploration(self):
        saved = self.call('rws_research_save', actor='human', record={'title': 'Human judgment', 'question': 'Does it help?', 'kind': 'hypothesis', 'hypothesis': 'It helps.', 'judgment': {'label': '支持'}})
        self.reject(lambda: self.call('rws_research_save', actor='human', record={'id': saved['record']['id'], 'kind': 'exploration', 'hypothesis': None}))
        # This is the full edit-form payload for clearing both optional fields.
        cleared = self.call('rws_research_save', actor='human', record={'id': saved['record']['id'], 'title': 'Human judgment', 'question': 'Does it help?', 'kind': 'exploration', 'stage': 'idea', 'parentRefs': [], 'hypothesis': None, 'judgment': None})
        self.assertNotIn('hypothesis', cleared['record'])
        self.assertNotIn('judgment', cleared['record'])
        self.assertEqual(cleared['record']['kind'], 'exploration')
        self.assertEqual(cleared['ref']['version'], 2)
        context = self.store.call('rws_get_context', {'projectId': 'p', 'researchRef': cleared['ref']})['result']
        self.assertIsNone(context['currentResearch']['judgment'])

    def test_optional_unjudged_statement_can_clear_but_required_hypothesis_cannot(self):
        optional = self.research(hypothesis='An optional conjecture.')
        cleared = self.call('rws_research_save', record={'id': optional['record']['id'], 'hypothesis': None})
        self.assertNotIn('hypothesis', cleared['record'])
        required = self.research(kind='hypothesis', hypothesis='Required claim.')
        before = self.store.snapshot('p')['revision']
        self.reject(lambda: self.call('rws_research_save', actor='human', record={'id': required['record']['id'], 'hypothesis': None}))
        self.assertEqual(self.store.snapshot('p')['revision'], before)

if __name__ == '__main__':
    unittest.main()
