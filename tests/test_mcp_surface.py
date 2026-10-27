"""Exercise every advertised tool through a real stdio client in an isolated DB."""
import tempfile
import unittest
from pathlib import Path
from test_transport import MCPClient


class MCPSurface(unittest.TestCase):
    def test_all_tools_and_human_only_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            client = MCPClient(Path(folder) / 'isolated.sqlite3')
            client.initialize()
            advertised = {x['name'] for x in client.request('tools/list')['result']['tools']}
            called = set()
            seq, revision = 0, 1

            def call(name, args, write=False, deny=False):
                nonlocal seq, revision
                called.add(name)
                if write:
                    seq += 1
                    args = dict(args, requestId='surface-%s' % seq, projectId='audit', expectedRevision=revision)
                result = client.call(name, args)
                if deny:
                    self.assertFalse(result['ok'])
                    self.assertEqual(result['error']['code'], 'approval_required')
                else:
                    self.assertTrue(result['ok'], result)
                    revision = result.get('revision', revision)
                    if name == 'rws_amendment_propose':
                        self.assertIn('amendments=1', result['guidance']['suggestedActions'][0]['reviewUrl'])
                return result.get('result', result)

            def rec(name, **record):
                return call(name, {'record':record}, write=True)['ref']

            try:
                call('rws_project_create', {'requestId':'surface-create','projectId':'audit','name':'Tool coverage','demo':True})
                self.assertEqual(len(call('rws_project_list', {})), 1)
                research = rec('rws_research_save', id='H', title='Open question', question='Inspect stored data', kind='exploration', stage='idea')
                dataset = rec('rws_dataset_register', id='D', title='Sample list', version='1', sampleIds=['s1'])
                protocol = rec('rws_protocol_register', id='P', title='Metric convention', version='1',
                    inputKind='artifact', metrics=[{'name':'distance','unit':'px','direction':'lower','granularity':'sample'}],
                    preprocessing='none', aggregation='none', missingPolicy='explicit')
                experiment = rec('rws_experiment_save', id='E', title='Observation plan', researchRef=research, protocolRef=protocol)
                spec = rec('rws_spec_save', id='SP', title='Reusable image contract', schemaVersion=1,
                    kind='inference', status='ready', purpose='Exercise the registered interface.', inputs=[],
                    outputs=[{'name':'images','kind':'image','semantic':'final-image'}], configSchema={'type':'object'},
                    dependencies=[], acceptanceChecks=[{'id':'fixture','description':'Check a synthetic output.'}], capabilities=['images'])
                code = rec('rws_code_register', id='C', title='Synthetic source identity', kind='inference', version='1',
                    source={'description':'test fixture only'}, specRef=spec, repository='https://example.test/source.git',
                    commit='fixed-fixture-revision', modulePath='fixture.py', entrypoint='fixture:run', capabilities=['images'],
                    checkEvidence=[{'checkId':'fixture','status':'skipped','evidence':'This stdio test records metadata; no model is executed.'}])
                found = call('rws_code_find', {'projectId':'audit','specRef':spec})
                self.assertEqual([item['ref'] for item in found['items']], [code])
                run = rec('rws_run_register', id='R', title='Synthetic record', kind='inference', codeRef=code, experimentRef=experiment,
                    status='completed', config={}, sampleSelection={'datasetRef':dataset,'sampleIds':['s1']})
                artifact = rec('rws_artifact_register', id='A', title='Synthetic image', kind='image', producerRef=run,
                    sampleId='s1', datasetRef=dataset, semantic='final-image', inputRefs=[], uri='/materials/test.png', availability='unknown')
                queried = call('rws_result_query', {'projectId':'audit','sampleIds':['s1'],'semantics':['final-image'],'codeRefs':[code]})
                self.assertEqual([item['ref'] for item in queried['items']], [artifact])
                usage = call('rws_usage_save', {'id':'U','experimentRef':experiment,'artifactRefs':[artifact],'role':'observation'}, write=True)
                rec('rws_comparison_save', id='CMP', title='Fixed input selection', inputRefs=[artifact], fixedConditions={'sample':'s1'}, varyingConditions=[])
                evaluation_code = rec('rws_code_register', id='EC', title='Metric importer', kind='evaluation', version='1', source='fixture.py')
                evaluation = rec('rws_evaluation_import', id='EV', title='Imported metric', protocolRef=protocol, codeRef=evaluation_code,
                    inputRefs=[artifact], experimentRef=experiment, status='completed',
                    results=[{'kind':'metric','name':'distance','value':0,'unit':'px','direction':'lower','sampleId':'s1'}])
                analysis = rec('rws_analysis_save', id='AN', title='Recorded observation', experimentRefs=[experiment], inputRefs=[evaluation],
                    observations='Fixture value is zero.', limitations='Not a model result.')
                report = rec('rws_report_create_revision', id='RP', title='Fixed record', inputRefs=[artifact], evaluationRefs=[evaluation], analysisRefs=[analysis], markdown='# Fixture\nNo research claim.')
                rec('rws_conversation_save', id='S', title='Existing conversation', uri='https://example.test/existing-session')
                context = call('rws_get_context', {'projectId':'audit','experimentRef':experiment})
                self.assertEqual(context['position']['researchRef'], research)
                self.assertEqual(call('rws_record_get', {'ref':report})['ref'], report)
                proposal = call('rws_overview_propose', {'fields':{'approach':'Proposed change'},'baseRevision':1,'reason':'Test human decision','sourceRefs':[analysis]}, write=True)
                for name in ['rws_overview_apply','rws_overview_dismiss']:
                    call(name, {'proposalRef':proposal['ref'],'baseRevision':1}, write=True, deny=True)
                call('rws_project_stages_set', {'activeStages':['formal']}, write=True, deny=True)
                amendment = call('rws_amendment_propose', {'record': {'title':'Source correction proposal',
                    'targetRef':artifact,'patch':{'title':'Corrected title'},'reason':'Review-only fixture.','evidenceRefs':[report]}}, write=True)
                amendment_context = call('rws_get_context', {'projectId':'audit'})
                self.assertIn('amendments=1', amendment_context['suggestedActions'][0]['reviewUrl'])
                for name in ['rws_amendment_apply','rws_amendment_dismiss']:
                    denied = call(name, {'amendmentRef':amendment['ref']}, write=True, deny=True)
                    self.assertIn('amendments=1', denied['error']['reviewUrl'])
                self.assertEqual(call('rws_record_get', {'ref':artifact})['record']['title'], 'Synthetic image')
                call('rws_usage_remove', {'id':'U'}, write=True)
                self.assertEqual(call('rws_record_get', {'ref':artifact})['record']['producerRef'], run)
                self.assertEqual(called, advertised)
            finally:
                client.close()
