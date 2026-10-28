"""Research purposes remain separate from immutable execution evidence."""
import copy
import tempfile
import unittest
from pathlib import Path

from rws.core import RwsError, Store, tool_definitions
from test_transport import MCPClient


class ResearchImplementationLinks(unittest.TestCase):
    def setUp(self):
        self.store = Store(':memory:')
        self.sequence = 0
        for pid in ('p', 'q'):
            self.store.call('rws_project_create', {'projectId': pid, 'name': pid,
                                                  'requestId': self.uid()})

    def tearDown(self):
        self.store.close()

    def uid(self):
        self.sequence += 1
        return 'research-links-' + str(self.sequence)

    def write(self, operation, record, pid='p', actor='model'):
        return self.store.call(operation, {'projectId': pid, 'record': record,
            'requestId': self.uid(), 'expectedRevision': self.store.snapshot(pid)['revision']},
            actor=actor)['result']

    def research(self, links=None, **fields):
        record = {'title': 'Explore a question', 'question': 'What can be observed?',
                  'kind': 'exploration'}
        if links is not None:
            record['implementationLinks'] = links
        record.update(fields)
        return self.write('rws_research_save', record)

    @staticmethod
    def spec_record(status='draft'):
        return {'title': 'Generic diagnostic', 'schemaVersion': 1, 'kind': 'analysis',
                'status': status, 'purpose': 'Inspect existing synthetic observations.',
                'inputs': [], 'outputs': [{'name': 'table', 'kind': 'table'}],
                'configSchema': {'type': 'object'}, 'dependencies': [],
                'acceptanceChecks': [{'id': 'fixture', 'description': 'Check a synthetic table.'}],
                'capabilities': ['inspect']}

    def spec(self, pid='p', status='draft'):
        return self.write('rws_spec_save', self.spec_record(status), pid)

    def code(self, spec=None, pid='p'):
        record = {'title': 'Reusable diagnostic', 'kind': 'analysis', 'version': 'v1',
                  'source': 'synthetic.py'}
        if spec:
            record.update(specRef=spec['ref'], repository='https://example.test/source.git',
                          commit='fixed-fixture-revision', modulePath='synthetic.py',
                          entrypoint='synthetic:inspect', capabilities=['inspect'],
                          checkEvidence=[{'checkId': 'fixture', 'status': 'skipped',
                                          'evidence': 'Registration-only software fixture.'}])
        return self.write('rws_code_register', record, pid)

    @staticmethod
    def link(target, role='diagnostic', **extra):
        return dict(targetRef=target['ref'], role=role, **extra)

    def get(self, ref):
        return self.store.call('rws_record_get', {'ref': ref})['result']

    def context(self, **scope):
        return self.store.call('rws_get_context', dict(projectId='p', **scope))['result']

    def test_declare_draft_contract_before_any_code_or_run(self):
        spec = self.spec()
        research = self.research([self.link(spec, note='Inspect before deciding a method.')])
        context = self.context(researchRef=research['ref'])
        self.assertEqual(context['completed'], [])
        self.assertFalse(context['currentResearch']['hasHypothesis'])
        self.assertEqual(len(context['declaredImplementations']), 1)
        declaration = context['declaredImplementations'][0]
        self.assertEqual(declaration['targetRef'], spec['ref'])
        self.assertEqual(declaration['researchRef'], research['ref'])
        self.assertTrue(declaration['intentOnly'])
        self.assertEqual(declaration['roleLabel'], '诊断')
        self.assertEqual(declaration['researchVersionRole'], 'current')
        self.assertIn(spec['ref'], [o['ref'] for o in context['objects']])
        self.assertFalse(any(o['ref']['type'] in ('run', 'code', 'artifact') for o in context['objects']))

    def test_shared_code_and_cross_project_purpose_do_not_mutate_source(self):
        code = self.code(pid='q')
        before = copy.deepcopy(self.get(code['ref']))
        first = self.research([self.link(code, 'implementation')], title='First question')
        second = self.research([self.link(code, 'control')], title='Second question')
        self.assertEqual(self.get(code['ref']), before)
        for research, role in ((first, 'implementation'), (second, 'control')):
            context = self.context(researchRef=research['ref'])
            self.assertEqual([d['role'] for d in context['declaredImplementations']], [role])
            self.assertEqual(context['declaredImplementations'][0]['researchRef'], research['ref'])
            self.assertIn(code['ref'], [o['ref'] for o in context['objects']])
            self.assertEqual(context['completed'], [])

    def test_exact_spec_revision_survives_ready_update_and_code_registration(self):
        draft = self.spec()
        research = self.research([self.link(draft)])
        ready = self.write('rws_spec_save', {'id': draft['ref']['id'], 'status': 'ready'})
        code = self.code(ready)
        context = self.context(researchRef=research['ref'])
        self.assertEqual(context['declaredImplementations'][0]['targetRef'], draft['ref'])
        self.assertIn(draft['ref'], [o['ref'] for o in context['objects']])
        self.assertNotIn(ready['ref'], [o['ref'] for o in context['objects']])
        self.assertNotIn(code['ref'], [o['ref'] for o in context['objects']])
        updated = self.research([self.link(ready)], id=research['ref']['id'])
        self.assertEqual(self.get(updated['ref'])['record']['implementationLinks'][0]['targetRef'], ready['ref'])
        self.assertEqual(self.get(code['ref'])['record']['specRef'], ready['ref'])
        self.assertEqual(self.get(research['ref'])['record']['implementationLinks'][0]['targetRef'], draft['ref'])

    def test_partial_update_preserves_links_explicit_empty_clears(self):
        original = self.research([self.link(self.code(), note='A declared future use.')])
        updated = self.write('rws_research_save', {'id': original['ref']['id'], 'title': 'New title'})
        self.assertEqual(updated['record']['implementationLinks'], original['record']['implementationLinks'])
        cleared = self.write('rws_research_save', {'id': original['ref']['id'], 'implementationLinks': []})
        self.assertEqual(cleared['record']['implementationLinks'], [])
        self.assertEqual(self.context(researchRef=cleared['ref'])['declaredImplementations'], [])
        self.assertEqual(self.get(original['ref'])['record'], original['record'])

    def test_invalid_links_fail_before_registering_or_repinning(self):
        code = self.code()
        unversioned = {k: v for k, v in code['ref'].items() if k != 'version'}
        invalid = [
            [{'targetRef': unversioned, 'role': 'diagnostic'}],
            [self.link(code, role='observed')],
            [self.link(code, note='x' * 1001)],
            [dict(self.link(code), unexpected=True)],
            [self.link(code), self.link(code, note='different note does not make a new relation')],
            [self.link(code)] * 33,
            None,
        ]
        revision = self.store.snapshot('p')['revision']
        for links in invalid:
            with self.subTest(links=repr(links)[:120]), self.assertRaises(RwsError) as raised:
                self.write('rws_research_save', {'title': 'Invalid', 'question': 'Invalid?',
                                               'implementationLinks': links})
            self.assertEqual(raised.exception.code, 'validation_error')
            self.assertEqual(self.store.snapshot('p')['revision'], revision)
        missing = dict(code['ref'], version=999)
        with self.assertRaises(RwsError) as raised:
            self.research([{'targetRef': missing, 'role': 'control'}])
        self.assertEqual(raised.exception.code, 'not_found')
        research = self.research()
        with self.assertRaises(RwsError) as raised:
            self.research([self.link(research)])
        self.assertEqual(raised.exception.code, 'validation_error')
        # One implementation may legitimately serve different declared roles.
        valid = self.research([self.link(code, 'control'), self.link(code, 'diagnostic')])
        self.assertEqual(len(valid['record']['implementationLinks']), 2)

    def test_old_report_snapshot_keeps_original_links_after_research_changes(self):
        code = self.code()
        research = self.research([self.link(code, 'control')])
        report = self.write('rws_report_create_revision', {
            'title': 'Declared plan snapshot', 'markdown': 'A plan, not completed evidence.',
            'researchRefs': [research['ref']]})
        before = copy.deepcopy(self.get(report['ref']))
        self.write('rws_research_save', {'id': research['ref']['id'], 'implementationLinks': []})
        self.assertEqual(self.get(report['ref']), before)
        snapshot = report['record']['snapshot']['records']
        frozen = next(e for e in snapshot if e['ref'] == research['ref'])
        self.assertEqual(frozen['record']['implementationLinks'], research['record']['implementationLinks'])
        self.assertIn(code['ref'], [e['ref'] for e in snapshot])

    def test_experiment_context_labels_bound_and_current_research_without_unrelated_links(self):
        first_code, next_code = self.code(), self.code()
        bound = self.research([self.link(first_code, 'control')])
        experiment = self.write('rws_experiment_save', {'title': 'Bound experiment',
                                                       'researchRef': bound['ref']})
        current = self.write('rws_research_save', {'id': bound['ref']['id'],
                                                 'implementationLinks': [self.link(next_code)]})
        unrelated = self.research([self.link(first_code)], title='Another question')
        context = self.context(experimentRef=experiment['ref'])
        self.assertEqual(context['position']['researchRef'], bound['ref'])
        self.assertEqual(context['currentResearchRef'], current['ref'])
        declarations = context['declaredImplementations']
        self.assertEqual([(d['researchRef'], d['targetRef'], d['researchVersionRole']) for d in declarations],
                         [(bound['ref'], first_code['ref'], 'bound'),
                          (current['ref'], next_code['ref'], 'current')])
        self.assertFalse(any(d['researchRef'] == unrelated['ref'] for d in declarations))
        self.assertEqual(context['completed'], [])

    def test_context_keeps_object_and_declaration_limits(self):
        links = [self.link(self.code(), note='n' * 1000) for _ in range(32)]
        first = self.research(links, title='One question')
        second = self.research(links, title='Another question')
        context = self.context()
        self.assertEqual(context['declaredImplementationCount'], 64)
        self.assertEqual(len(context['declaredImplementations']), 32)
        self.assertTrue(context['declaredImplementationsTruncated'])
        self.assertTrue(all(len(d['note']) == 200 for d in context['declaredImplementations']))
        self.assertEqual([d['researchRef'] for d in context['declaredImplementations'][:2]],
                         sorted([first['ref'], second['ref']], key=lambda ref: ref['id']))
        self.assertEqual({d['researchRef']['id'] for d in context['declaredImplementations']},
                         {first['ref']['id'], second['ref']['id']})
        self.assertLessEqual(len(context['objects']), 40)

    def test_full_bound_links_do_not_hide_current_revision_links(self):
        links = [self.link(self.code(), 'control') for _ in range(32)]
        bound = self.research(links)
        experiment = self.write('rws_experiment_save', {'title': 'Old plan',
                                                       'researchRef': bound['ref']})
        changed_links = [dict(link, role='diagnostic') for link in links]
        current = self.write('rws_research_save', {'id': bound['ref']['id'],
                                                 'implementationLinks': changed_links})
        context = self.context(experimentRef=experiment['ref'])
        self.assertEqual(context['declaredImplementationCount'], 64)
        self.assertEqual(len(context['declaredImplementations']), 32)
        self.assertTrue(context['declaredImplementationsTruncated'])
        self.assertEqual([d['researchVersionRole'] for d in context['declaredImplementations']],
                         ['bound', 'current'] * 16)
        self.assertEqual(context['declaredImplementations'][0]['researchRef'], bound['ref'])
        self.assertEqual(context['declaredImplementations'][1]['researchRef'], current['ref'])
        self.assertLessEqual(len(context['objects']), 40)

    def test_purpose_links_do_not_grant_scientific_judgment_authority(self):
        links = [self.link(self.code())]
        research = self.research(links, kind='hypothesis', hypothesis='The fixture improves consistency.')
        self.assertTrue(self.context(researchRef=research['ref'])['currentResearch']['hasHypothesis'])
        with self.assertRaises(RwsError) as raised:
            self.write('rws_research_save', {'id': research['ref']['id'],
                                            'judgment': {'label': '支持'}})
        self.assertEqual(raised.exception.code, 'approval_required')
        judged = self.write('rws_research_save', {'id': research['ref']['id'],
                                               'judgment': {'label': '证据不足'}}, actor='human')
        updated = self.write('rws_research_save', {'id': research['ref']['id'], 'implementationLinks': []})
        self.assertEqual(updated['record']['judgment'], judged['record']['judgment'])


class ResearchLinksMCP(unittest.TestCase):
    def test_published_schema_and_stdio_preserve_explicit_intent(self):
        definition = next(t for t in tool_definitions() if t['name'] == 'rws_research_save')
        schema = definition['inputSchema']['properties']['record']['properties']['implementationLinks']
        target = schema['items']['properties']['targetRef']
        self.assertIn('version', target['required'])
        self.assertEqual(target['properties']['type']['enum'], ['spec', 'code'])
        with tempfile.TemporaryDirectory() as directory:
            client = MCPClient(Path(directory) / 'isolated.sqlite3')
            try:
                initialized = client.initialize()
                self.assertIn('implementationLinks', initialized['result']['instructions'])
                client.call('rws_project_create', {'projectId': 'demo', 'name': 'Synthetic test',
                                                   'requestId': 'create'})
                spec = client.call('rws_spec_save', {'projectId': 'demo', 'requestId': 'spec',
                    'expectedRevision': 1, 'record': ResearchImplementationLinks.spec_record()})
                self.assertTrue(spec['ok'], spec)
                research = client.call('rws_research_save', {'projectId': 'demo', 'requestId': 'question',
                    'expectedRevision': spec['revision'], 'record': {'title': 'Inspect first',
                        'question': 'What happens?', 'implementationLinks': [
                            {'targetRef': spec['result']['ref'], 'role': 'diagnostic'}]}})
                self.assertTrue(research['ok'], research)
                context = client.call('rws_get_context', {'projectId': 'demo',
                                                        'researchRef': research['result']['ref']})['result']
                self.assertTrue(context['declaredImplementations'][0]['intentOnly'])
                self.assertEqual(context['completed'], [])
            finally:
                client.close()


if __name__ == '__main__':
    unittest.main()
