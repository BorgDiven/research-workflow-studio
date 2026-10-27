"""Contract-driven composition and audited history, without executing models."""
import unittest

from rws.core import RwsError, Store
from rws.mcp import MCPConnection


class ContractV3Test(unittest.TestCase):
    def setUp(self):
        self.store = Store(':memory:')
        self.sequence = 0
        for pid in ('p', 'q'):
            self.store.call('rws_project_create', {'requestId': self.uid(), 'projectId': pid, 'name': pid})

    def tearDown(self):
        self.store.close()

    def uid(self):
        self.sequence += 1
        return 'request-' + str(self.sequence)

    def write(self, name, actor='model', pid='p', **args):
        return self.store.call(name, dict(args, requestId=self.uid(), projectId=pid,
                                         expectedRevision=self.store.snapshot(pid)['revision']), actor=actor)['result']

    def save(self, kind, record, pid='p'):
        operation = {'spec': 'save', 'comparison': 'save', 'analysis': 'save',
                     'report': 'create_revision', 'evaluation': 'import'}.get(kind, 'register')
        return self.write('rws_' + kind + '_' + operation, record=record, pid=pid)

    def get(self, ref):
        return self.store.call('rws_record_get', {'ref': ref})['result']

    def expect(self, code, fn):
        with self.assertRaises(RwsError) as raised:
            fn()
        self.assertEqual(raised.exception.code, code)
        return raised.exception

    def spec_record(self, kind='inference'):
        return {'title': 'Reusable ' + kind, 'schemaVersion': 1, 'kind': kind, 'status': 'ready',
                'purpose': 'Describe a method independently of the selected cases.',
                'inputs': [], 'outputs': [{'name': 'output', 'kind': 'image', 'semantic': 'final-image'}],
                'configSchema': {'type': 'object', 'properties': {'cfg': {'type': 'number', 'minimum': 0}},
                                 'required': ['cfg'], 'additionalProperties': False},
                'dependencies': [], 'acceptanceChecks': [{'id': 'fixture', 'description': 'Run the portable fixture.'}],
                'capabilities': ['batch-output']}

    def code_record(self, spec, **extra):
        record = {'title': 'Generic implementation', 'kind': spec['record']['kind'], 'version': 'v1',
                  'source': 'blocks/generic.py', 'specRef': spec['ref'], 'entrypoint': 'generic:run',
                  'modulePath': 'blocks/generic.py', 'repository': 'https://example.org/research.git',
                  'commit': 'fixed-revision-001', 'capabilities': ['batch-output'],
                  'checkEvidence': [{'checkId': 'fixture', 'status': 'passed', 'evidence': 'Client fixture log 1.'}]}
        record.update(extra)
        return record

    def fixture(self):
        spec = self.save('spec', self.spec_record())
        code = self.save('code', self.code_record(spec))
        dataset = self.save('dataset', {'title': 'Two cases', 'version': 'v1', 'sampleIds': ['fish', 'bird']})
        return spec, code, dataset

    def run_record(self, code, dataset=None, samples=None, **extra):
        selection = {'sampleIds': samples or ['fish', 'bird']}
        if dataset:
            selection['datasetRef'] = dataset['ref']
        record = {'title': 'Batch', 'codeRef': code['ref'], 'config': {'cfg': 4}, 'status': 'completed',
                  'sampleSelection': selection, 'inputRefs': [], 'purpose': 'Explore output behavior'}
        record.update(extra)
        return self.save('run', record)

    def output(self, run, sample='fish', dataset=None, **extra):
        record = {'title': sample, 'kind': 'image', 'producerRef': run['ref'], 'sampleId': sample,
                  'semantic': 'final-image', 'inputRefs': [], 'config': {'cfg': 4}}
        if dataset:
            record['datasetRef'] = dataset['ref']
        record.update(extra)
        return self.save('artifact', record)

    def amendment(self, target, patch, pid='p'):
        return self.write('rws_amendment_propose', pid=pid,
                          record={'title': 'Correct source metadata', 'targetRef': target['ref'],
                                  'patch': patch, 'reason': 'Checked original source records.', 'evidenceRefs': []})

    def approve(self, amendment):
        return self.write('rws_amendment_apply', actor='human', amendmentRef=amendment['ref'])

    def test_one_method_serves_two_cases_batch_and_single_reuse(self):
        spec, code, dataset = self.fixture()
        run = self.run_record(code, dataset)
        fish, bird = self.output(run, dataset=dataset), self.output(run, 'bird', dataset)
        single = self.run_record(code, dataset, ['fish'], config={'cfg': 7})
        repeated = self.output(single, dataset=dataset, config={'cfg': 7})
        response = self.store.call('rws_result_query', {'projectId': 'p', 'sampleIds': ['fish'],
                                                      'semantics': ['final-image'], 'codeRefs': [code['ref']]})['result']
        self.assertEqual(response['total'], 2)
        self.assertEqual({item['ref']['id'] for item in response['items']}, {fish['ref']['id'], repeated['ref']['id']})
        self.assertEqual(code['record']['validationOrigin'], 'supplied')
        found = self.store.call('rws_code_find', {'projectId': 'p', 'specRef': spec['ref']})['result']
        self.assertEqual([item['ref'] for item in found['items']], [code['ref']])
        self.assertEqual(bird['record']['producerRef'], run['ref'])

    def test_pinned_contract_revision_survives_draft_edit_and_implementation_immutable(self):
        spec, code, dataset = self.fixture()
        changed = self.save('spec', {'id': spec['ref']['id'], 'purpose': 'New work', 'status': 'draft'})
        self.assertEqual(changed['ref']['version'], 2)
        self.assertEqual(self.get(spec['ref'])['record']['status'], 'ready')
        self.assertEqual(self.get(code['ref'])['record']['specRef'], spec['ref'])
        self.expect('immutable_source', lambda: self.save('code', dict(self.code_record(spec), id=code['ref']['id'])))
        self.expect('validation_error', lambda: self.save('code', self.code_record(changed, commit='fixed-revision-002')))
        self.run_record(code, dataset)

    def test_same_implementation_cannot_be_registered_once_per_case(self):
        spec, code, _ = self.fixture()
        self.expect('duplicate_identity', lambda: self.save('code', self.code_record(spec, title='Bird special')))
        self.expect('validation_error', lambda: self.save('code', self.code_record(spec, commit='HEAD')))
        self.expect('validation_error', lambda: self.save('code', self.code_record(spec, commit='fixed-002', checkEvidence=[])))

    def test_input_kind_semantic_config_and_case_membership_checked(self):
        spec, code, dataset = self.fixture()
        raw = self.save('artifact', {'title': 'Input', 'kind': 'image', 'semantic': 'input-image',
                                    'provenance': 'unresolved', 'description': 'External input.', 'source': 'fixture/input.png'})
        spec_record = self.spec_record()
        spec_record['inputs'] = [{'name': 'source', 'kind': 'image', 'semantic': 'input-image'}]
        input_spec = self.save('spec', spec_record)
        input_code = self.save('code', self.code_record(input_spec, commit='fixed-revision-002'))
        self.expect('validation_error', lambda: self.run_record(input_code, dataset))
        valid = self.run_record(input_code, dataset, inputRefs=[raw['ref']])
        self.output(valid, dataset=dataset, inputRefs=[raw['ref']])
        wrong = self.save('artifact', {'title': 'Wrong input', 'kind': 'image', 'semantic': 'final-image',
                                      'provenance': 'unresolved', 'description': 'Other semantic.', 'source': 'fixture/other.png'})
        self.expect('validation_error', lambda: self.run_record(input_code, dataset, inputRefs=[wrong['ref']]))
        self.expect('validation_error', lambda: self.run_record(code, dataset, config={'cfg': -1}))
        self.expect('validation_error', lambda: self.run_record(code, dataset, ['unknown']))
        self.expect('validation_error', lambda: self.output(valid, 'unknown', dataset))

    def test_outputs_duplicate_and_observation_semantics_are_explicit(self):
        spec_record = self.spec_record()
        spec_record['outputs'].append({'name': 'clean', 'kind': 'image', 'semantic': 'clean-estimate'})
        spec = self.save('spec', spec_record)
        code = self.save('code', self.code_record(spec))
        run = self.run_record(code)
        output = self.output(run)
        self.expect('duplicate_identity', lambda: self.output(run, title='Same output with another title'))
        self.expect('validation_error', lambda: self.output(run, semantic='clean-estimate'))
        one = self.output(run, semantic='clean-estimate', observation={'step': 1})
        two = self.output(run, semantic='clean-estimate', observation={'step': 2})
        self.assertNotEqual(one['ref'], two['ref'])
        self.assertEqual(self.get(output['ref'])['record']['semantic'], 'final-image')

    def test_actual_output_config_validated_without_banning_valid_parameter_sweeps(self):
        _, code, dataset = self.fixture()
        run = self.run_record(code, dataset)
        self.expect('validation_error', lambda: self.output(run, dataset=dataset, config={'cfg': 'not-a-number', 'unknown': True}))
        self.expect('validation_error', lambda: self.output(run, dataset=dataset, config={'cfg': -1}))
        artifact = self.output(run, dataset=dataset, config={'cfg': 7})
        self.assertEqual(artifact['record']['config'], {'cfg': 7})
        self.assertEqual(run['record']['config'], {'cfg': 4})

    def test_report_freezes_comparison_scope_generator_and_later_revisions(self):
        _, code, dataset = self.fixture()
        artifact = self.output(self.run_record(code, dataset), dataset=dataset)
        comparison = self.save('comparison', {'title': 'Fish comparison', 'inputRefs': [artifact['ref']],
                              'fixedConditions': {'cfg': 4}, 'varyingConditions': ['method'],
                              'viewSpec': {'mode': 'single', 'sampleIds': ['fish'], 'axis': 'code',
                                           'filters': {'selections': {'fish': artifact['ref']}}}})
        analysis = self.save('analysis', {'title': 'Limited analysis', 'observations': 'One case only.',
                            'limitations': 'Cannot generalize.', 'comparisonRefs': [comparison['ref']],
                            'scope': {'sampleIds': ['fish', 'bird'], 'description': 'Two-case fixture'},
                            'coverage': {'expected': 2, 'observed': 1, 'missingSampleIds': ['bird']}})
        report_spec = self.save('spec', self.spec_record('report'))
        generator = self.save('code', self.code_record(report_spec, modulePath='report.py', entrypoint='report:run'))
        generator_run = self.run_record(generator, config={'cfg': 4})
        report = self.save('report', {'title': 'Pinned report', 'markdown': 'Only fish observed.',
                          'comparisonRefs': [comparison['ref']], 'analysisRefs': [analysis['ref']],
                          'generatorCodeRef': generator['ref'], 'generatorRunRef': generator_run['ref']})
        self.save('comparison', {'id': comparison['ref']['id'], 'viewSpec': {'mode': 'multi'}})
        self.assertEqual(self.get(report['ref']), report)
        refs = [env['ref'] for env in report['record']['snapshot']['records']]
        for ref in (artifact['ref'], comparison['ref'], analysis['ref'], generator['ref'], generator_run['ref'], report_spec['ref']):
            self.assertIn(ref, refs)

    def test_amendments_preserve_raw_history_old_reports_and_other_projects(self):
        _, code, dataset = self.fixture()
        artifact = self.output(self.run_record(code, dataset), dataset=dataset)
        before = self.save('report', {'title': 'Before', 'markdown': 'Old title.', 'inputRefs': [artifact['ref']]})
        proposal = self.amendment(artifact, {'title': 'Corrected display title', 'taskKey': 'edit'})
        self.assertEqual(self.get(artifact['ref']), artifact)
        self.expect('approval_required', lambda: self.write('rws_amendment_apply', amendmentRef=proposal['ref']))
        approved = self.approve(proposal)
        projected = self.get(artifact['ref'])
        self.assertEqual(projected['record'], artifact['record'])
        self.assertEqual(projected['effectiveRecord']['title'], 'Corrected display title')
        self.assertEqual(projected['amendmentRefs'], [approved['ref']])
        self.assertEqual(self.get(before['ref']), before)
        self.assertEqual(self.store.snapshot('q')['records'], [])
        after = self.save('report', {'title': 'After', 'markdown': 'Corrected source.', 'inputRefs': [artifact['ref']]})
        frozen = next(e for e in after['record']['snapshot']['records'] if e['ref'] == artifact['ref'])
        self.assertEqual(frozen['effectiveRecord']['title'], 'Corrected display title')
        self.assertIn(approved['ref'], [e['ref'] for e in after['record']['snapshot']['records']])
        self.approve(self.amendment(artifact, {'title': 'Another correction'}))
        self.assertEqual(self.get(after['ref']), after)
        self.expect('validation_error', lambda: self.amendment(before, {'title': 'Rewrite report'}))
        self.expect('validation_error', lambda: self.amendment(artifact, {'config': {'cfg': 99}}))
        self.expect('validation_error', lambda: self.amendment(artifact, {'sampleId': 'not-in-dataset'}))
        self.expect('validation_error', lambda: self.amendment(artifact, {'title': 'Foreign'}, pid='q'))

    def test_amendment_exact_versions_stale_review_lineage_and_recovery(self):
        spec, code, dataset = self.fixture()
        first = self.amendment(code, {'title': 'First'})
        second = self.amendment(code, {'title': 'Second'})
        self.approve(first)
        self.expect('revision_conflict', lambda: self.approve(second))
        self.expect('validation_error', lambda: self.amendment(code, {'parentRefs': [code['ref']]}))
        failed = self.run_record(code, dataset, status='failed')
        recovered = self.run_record(code, dataset)
        self.approve(self.amendment(failed, {'recoveredByRef': recovered['ref']}))
        context = self.store.call('rws_get_context', {'projectId': 'p'})['result']
        self.assertNotIn(failed['ref'], [item['ref'] for item in context['pending']])
        fact = next(item for item in context['completed'] if item['ref'] == failed['ref'])
        self.assertEqual(fact['status'], 'recovered')
        self.assertEqual(self.get(failed['ref'])['record']['status'], 'failed')
        different = self.run_record(code, dataset, config={'cfg': 9})
        another_failed = self.run_record(code, dataset, status='failed')
        self.expect('validation_error', lambda: self.amendment(another_failed, {'recoveredByRef': different['ref']}))

    def test_unsupported_schema_cannot_silently_skip_validation(self):
        record = self.spec_record()
        record['configSchema'] = {'type': 'object', 'unknownValidation': True}
        self.expect('validation_error', lambda: self.save('spec', record))
        record['configSchema'] = {'type': 'object', 'properties': {'cfg': {'type': 'made-up'}}}
        self.expect('validation_error', lambda: self.save('spec', record))

    def test_context_balances_objects_and_retains_only_pending_or_selected_amendments(self):
        _, code, dataset = self.fixture()
        artifact = self.output(self.run_record(code, dataset), dataset=dataset)
        research = self.write('rws_research_save', record={'title': 'Research purpose', 'question': 'What changes?'})
        approved = []
        for index in range(41):
            approved.append(self.approve(self.amendment(artifact, {'title': 'Correction ' + str(index)})))
        dismissed = self.amendment(artifact, {'title': 'Dismiss this'})
        self.write('rws_amendment_dismiss', actor='human', amendmentRef=dismissed['ref'])
        pending = self.amendment(artifact, {'title': 'Awaiting review'})
        context = self.store.call('rws_get_context', {'projectId': 'p'})['result']
        visible = {item['ref']['type'] for item in context['objects']}
        self.assertTrue({'research', 'code', 'artifact'} <= visible)
        visible_amendments = [item['ref'] for item in context['objects'] if item['ref']['type'] == 'amendment']
        self.assertEqual(visible_amendments, [pending['ref']])
        self.assertIn(pending['ref'], [item['ref'] for item in context['pending']])
        self.assertTrue(context['suggestedActions'][0]['requiresHuman'])
        self.assertIn('amendments=1', context['suggestedActions'][0]['reviewUrl'])
        selected = self.store.call('rws_get_context', {'projectId': 'p', 'selectionRefs': [approved[0]['ref']]})['result']
        self.assertEqual(selected['objects'][0]['ref'], approved[0]['ref'])
        self.assertEqual(self.get(research['ref'])['record']['question'], 'What changes?')

    def test_mcp_tools_have_contract_guidance_and_no_human_approval_authority(self):
        connection = MCPConnection(self.store)
        init = connection.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                                  'params': {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {}}})
        self.assertIn('rws_code_find', init['result']['instructions'])
        connection.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        _, code, _ = self.fixture()
        proposal = self.amendment(code, {'title': 'Human review'})
        response = connection.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                                      'params': {'name': 'rws_amendment_apply', 'arguments': {
                                          'requestId': self.uid(), 'projectId': 'p',
                                          'expectedRevision': self.store.snapshot('p')['revision'],
                                          'amendmentRef': proposal['ref']}}})
        self.assertTrue(response['result']['isError'])
        self.assertEqual(response['result']['structuredContent']['error']['code'], 'approval_required')
        self.assertIn('amendments=1', response['result']['structuredContent']['error']['reviewUrl'])


if __name__ == '__main__':
    unittest.main()
