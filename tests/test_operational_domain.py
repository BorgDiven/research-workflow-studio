"""Plan approval and measurement provenance, using isolated records only."""
import copy
import unittest

from rws.core import ALLOWED_FIELDS, RwsError, Store, tool_definitions


class WorkflowDomainTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(':memory:')
        self.seq = 0
        self.store.call('rws_project_create', {'requestId': 'project', 'projectId': 'p', 'name': 'Synthetic'})

    def tearDown(self):
        self.store.close()

    def args(self, **fields):
        self.seq += 1
        return dict(projectId='p', expectedRevision=self.store.snapshot('p')['revision'],
                    requestId='write-' + str(self.seq), **fields)

    def write(self, name, actor='model', **fields):
        return self.store.call(name, self.args(**fields), actor=actor)['result']

    def get(self, ref, latest=False):
        if latest:
            ref = {k: v for k, v in ref.items() if k != 'version'}
        return self.store.call('rws_record_get', {'ref': ref})['result']

    def fixture(self, metrics=None, dataset=True, samples=None, unit='loss'):
        server = self.write('rws_server_save', record={'title': 'Local fixture', 'transport': 'local', 'workspaceRoot': '/workspace'})
        repository = self.write('rws_repository_save', record={'title': 'Checkout', 'serverRef': server['ref'], 'path': '/workspace/repo', 'remoteUrl': 'https://example.test/project.git'})
        environment = self.write('rws_environment_save', record={'title': 'Python', 'serverRef': server['ref'], 'repositoryRef': repository['ref'], 'workingDirectory': '/workspace/repo'})
        spec = self.write('rws_spec_save', record={'title': 'Training fixture', 'kind': 'training',
            'schemaVersion': 1, 'status': 'ready', 'purpose': 'Record synthetic learning measurements.',
            'inputs': [], 'outputs': [{'name': 'checkpoint', 'kind': 'attachment', 'semantic': 'checkpoint'}],
            'configSchema': {'type': 'object'}, 'dependencies': [], 'capabilities': ['training'],
            'acceptanceChecks': [{'id': 'fixture', 'description': 'Check fixture.'}],
            'processMetrics': metrics or [{'id': 'loss', 'name': 'Training loss', 'unit': unit,
                                           'axis': 'step', 'scope': 'run', 'splits': ['train']} ]})
        code = self.write('rws_code_register', record={'title': 'Synthetic trainer', 'kind': 'training',
            'version': '1', 'source': 'trainer.py', 'specRef': spec['ref'], 'repositoryRef': repository['ref'],
            'repository': repository['record']['remoteUrl'], 'commit': '1' * 40,
            'modulePath': 'trainer.py', 'entrypoint': 'trainer:run', 'capabilities': ['training'],
            'checkEvidence': [{'checkId': 'fixture', 'status': 'skipped', 'evidence': 'Record-only fixture.'}]})
        selection = {'sampleIds': samples or ['a', 'b']}
        if dataset:
            ds = self.write('rws_dataset_register', record={'title': 'Synthetic data', 'version': '1', 'sampleIds': ['a', 'b', 'c']})
            selection['datasetRef'] = ds['ref']
        run = self.write('rws_run_register', record={'title': 'First run', 'kind': 'training', 'codeRef': code['ref'],
            'environmentRef': environment['ref'], 'repositoryRef': repository['ref'], 'config': {},
            'sampleSelection': selection, 'status': 'planned'})
        return server, repository, environment, spec, code, run

    def launch(self, run, env):
        return self.write('rws_operation_propose', record={'title': 'Launch reviewed fixture', 'kind': 'task.start',
                          'runRef': run['ref'], 'environmentRef': env['ref'],
                          'arguments': {'argv': ['python3', 'trainer.py']}})

    def claim(self, operation, claim_id='claim-a'):
        return self.store.runner_call('claim', self.args(operationRef=operation['ref'], claimId=claim_id,
                                                        runnerId='isolated-test'))['result']

    def update(self, operation, status, result=None, claim_id='claim-a'):
        return self.store.runner_call('update', self.args(operationRef=operation['ref'], claimId=claim_id,
                                                         status=status, result=result or {}))['result']

    def expect(self, code, fn):
        with self.assertRaises(RwsError) as raised:
            fn()
        self.assertEqual(raised.exception.code, code)

    def test_resources_are_versioned_bound_and_never_contain_credentials(self):
        server, repo, env, _, _, run = self.fixture()
        changed = self.write('rws_server_save', record={'id': server['ref']['id'], 'title': 'Renamed'})
        self.assertEqual(self.get(repo['ref'])['record']['serverRef'], server['ref'])
        self.assertNotEqual(changed['ref'], server['ref'])
        env_new = self.write('rws_environment_save', record={'id': env['ref']['id'], 'title': 'New label'})
        self.expect('immutable_source', lambda: self.write('rws_run_register', record={'id': run['ref']['id'], 'environmentRef': env_new['ref']}))
        for record in ({'title': 'Bad SSH', 'transport': 'ssh', 'sshAlias': 'host;id', 'workspaceRoot': '/workspace'},
                       {'title': 'Bad secret', 'transport': 'ssh', 'sshAlias': 'safe', 'workspaceRoot': '/workspace', 'password': 'not-allowed'}):
            self.expect('validation_error', lambda record=record: self.write('rws_server_save', record=record))
        self.expect('validation_error', lambda: self.write('rws_repository_save', record={'title': 'Outside', 'serverRef': server['ref'], 'path': '/other/repo'}))
        self.expect('validation_error', lambda: self.write('rws_repository_save', record={'title': 'Credential URL', 'serverRef': server['ref'], 'path': '/workspace/repo', 'remoteUrl': 'https://user:secret@example.test/repo'}))
        self.expect('validation_error', lambda: self.write('rws_environment_save', record={'title': 'Wrong server version', 'serverRef': changed['ref'], 'repositoryRef': repo['ref'], 'workingDirectory': '/workspace/repo'}))

    def test_approval_exact_plan_and_private_claim_are_separate_from_execution(self):
        _, _, env, _, _, run = self.fixture()
        proposed = self.launch(run, env)
        self.assertEqual(proposed['record']['policy'], 'mutation')
        self.expect('approval_required', lambda: self.write('rws_operation_approve', operationRef=proposed['ref']))
        self.expect('conflict', lambda: self.claim(proposed))
        approved = self.write('rws_operation_approve', actor='human', operationRef=proposed['ref'])
        self.assertEqual(approved['record']['reviewedPlanRef'], proposed['ref'])
        self.expect('revision_conflict', lambda: self.claim(proposed))
        claim_args = self.args(operationRef=approved['ref'], claimId='claim-a', runnerId='test')
        self.expect('not_found', lambda: self.store.call('_rws_operation_claim', claim_args))
        claimed = self.store.runner_call('claim', claim_args)
        self.assertEqual(self.store.runner_call('claim', claim_args), claimed)
        self.assertFalse(any(t['name'].startswith('_rws') for t in tool_definitions()))
        self.assertEqual(self.get(run['ref'], latest=True)['record']['status'], 'planned')
        self.assertTrue(claimed['result']['record']['result']['jobId'])
        self.assertEqual(claimed['result']['record']['result']['processStart'], 'claim-a')
        self.assertNotIn('pid', claimed['result']['record']['result'])
        self.expect('revision_conflict', lambda: self.claim(approved, 'second'))

    def test_running_job_unknown_does_not_restart_or_change_producer(self):
        _, repo, env, _, code, run = self.fixture()
        proposed = self.launch(run, env)
        approved = self.write('rws_operation_approve', actor='human', operationRef=proposed['ref'])
        claimed = self.claim(approved)
        job_id = claimed['record']['result']['jobId']
        observed = self.update(claimed, 'running', {'jobId': job_id, 'pid': 1001, 'observedAt': 'fixture-start',
                              'codeRef': code['ref'], 'repositoryRef': repo['ref'], 'environmentRef': env['ref']})
        current_run = self.get(run['ref'], latest=True)
        self.assertEqual(current_run['record']['status'], 'running')
        self.assertEqual(current_run['record']['codeRef'], run['record']['codeRef'])
        unknown = self.update(observed, 'unknown', {'message': 'Connection dropped.'})
        self.assertEqual(self.get(run['ref'], latest=True)['record']['status'], 'unknown')
        self.expect('conflict', lambda: self.claim(unknown))
        self.expect('immutable_source', lambda: self.update(unknown, 'running', {'pid': 9999}))
        inspect = self.write('rws_operation_propose', record={'title': 'Check original job', 'kind': 'task.inspect',
                              'launchOperationRef': unknown['ref'], 'arguments': {}})
        inspection_claim = self.claim(inspect, 'inspect')
        self.expect('immutable_source', lambda: self.update(inspection_claim, 'completed',
                    {'jobId': 'another-job', 'taskStatus': 'completed'}, 'inspect'))
        inspected = self.update(inspection_claim, 'completed',
                                {'jobId': job_id, 'taskStatus': 'completed', 'exitCode': 0, 'observedAt': 'fixture-check'}, 'inspect')
        self.assertEqual(inspected['record']['launchOperationRef'], unknown['ref'])
        self.assertEqual(self.get(run['ref'], latest=True)['record']['status'], 'completed')
        self.assertEqual(self.get(unknown['ref'], latest=True)['record']['status'], 'unknown')
        later = self.write('rws_operation_propose', record={'title': 'Later unavailable inspection', 'kind': 'task.inspect',
                           'launchOperationRef': unknown['ref'], 'arguments': {}})
        self.update(self.claim(later, 'later'), 'unknown', {'taskStatus': 'unknown'}, 'later')
        self.assertEqual(self.get(run['ref'], latest=True)['record']['status'], 'completed')

    def test_read_only_claim_and_mutation_boundaries(self):
        _, repo, _, _, _, _ = self.fixture()
        inspection = self.write('rws_operation_propose', record={'title': 'Inspect', 'kind': 'git.inspect',
                               'repositoryRef': repo['ref'], 'arguments': {}})
        self.assertEqual(self.claim(inspection)['record']['status'], 'claimed')
        branch = self.write('rws_operation_propose', record={'title': 'Branch', 'kind': 'git.branch',
                           'repositoryRef': repo['ref'], 'arguments': {'name': 'experiment'}})
        self.expect('conflict', lambda: self.claim(branch))
        dismissed = self.write('rws_operation_dismiss', actor='human', operationRef=branch['ref'])
        self.expect('conflict', lambda: self.claim(dismissed))
        for kind, arguments in [('git.commit', {'message': 'Unsafe scope', 'paths': ['../other']}),
                                ('git.push', {'remoteName': 'origin', 'refspec': '+main'}),
                                ('git.push', {'remoteName': 'origin', 'refspec': ':main'}),
                                ('git.branch', {'name': '--track'})]:
            self.expect('validation_error', lambda kind=kind, arguments=arguments: self.write('rws_operation_propose',
                        record={'title': 'Invalid operation', 'kind': kind, 'repositoryRef': repo['ref'], 'arguments': arguments}))

    def test_two_approved_launches_cannot_claim_same_run(self):
        _, _, env, _, _, run = self.fixture()
        one, two = self.launch(run, env), self.launch(run, env)
        one = self.write('rws_operation_approve', actor='human', operationRef=one['ref'])
        two = self.write('rws_operation_approve', actor='human', operationRef=two['ref'])
        self.claim(one)
        self.expect('conflict', lambda: self.claim(two, 'second'))

    def test_moving_git_revision_is_not_an_executable_source(self):
        _, _, env, _, code, run = self.fixture()
        fields = {key: value for key, value in code['record'].items() if key in ALLOWED_FIELDS['code']}
        moving = self.write('rws_code_register', record=dict(fields, id='moving-code', commit='feature-branch'))
        planned = self.write('rws_run_register', record=dict(run['record'], id='moving-run', codeRef=moving['ref']))
        self.expect('validation_error', lambda: self.launch(planned, env))

    def test_optional_resource_fields_clear_explicitly_without_repinning(self):
        ssh = self.write('rws_server_save', record={'title': 'Alias', 'transport': 'ssh', 'workspaceRoot': '/workspace', 'sshAlias': 'fixture-host'})
        local = self.write('rws_server_save', record={'id': ssh['ref']['id'], 'transport': 'local', 'sshAlias': None})
        self.assertNotIn('sshAlias', local['record'])
        self.assertEqual(self.get(ssh['ref'])['record']['sshAlias'], 'fixture-host')
        repo = self.write('rws_repository_save', record={'title': 'Repo', 'serverRef': local['ref'], 'path': '/workspace/repo', 'remoteUrl': 'https://example.test/repo', 'defaultBranch': 'main'})
        changed = self.write('rws_repository_save', record={'id': repo['ref']['id'], 'remoteUrl': None, 'defaultBranch': None})
        self.assertNotIn('remoteUrl', changed['record'])
        self.assertNotIn('defaultBranch', changed['record'])
        self.expect('validation_error', lambda: self.write('rws_operation_propose', record={'title': 'Unbound push', 'kind': 'git.push', 'repositoryRef': changed['ref'], 'arguments': {'remoteName': 'origin', 'refspec': 'refs/heads/main:refs/heads/main'}}))
        bound = self.write('rws_repository_save', record={'id': repo['ref']['id'], 'remoteUrl': '/workspace/remote.git'})
        self.assertEqual(bound['record']['remoteUrl'], '/workspace/remote.git')
        self.expect('validation_error', lambda: self.write('rws_repository_save', record={'id': repo['ref']['id'], 'remoteUrl': '/outside/remote.git'}))

    def test_context_keeps_task_observations_with_their_research_scope(self):
        _, _, env, _, _, run = self.fixture()
        research = self.write('rws_research_save', record={'title': 'Question', 'kind': 'exploration', 'question': 'Observe a synthetic process.'})
        experiment = self.write('rws_experiment_save', record={'title': 'Process observation', 'researchRef': research['ref']})
        scoped_run = self.write('rws_run_register', record=dict(run['record'], id='scoped-run', experimentRef=experiment['ref']))
        proposed = self.launch(scoped_run, env)
        context = self.store.call('rws_get_context', {'projectId': 'p', 'experimentRef': experiment['ref']})['result']
        self.assertIn(proposed['ref'], [item['ref'] for item in context['objects']])
        pending = next(item for item in context['pending'] if item['ref'] == proposed['ref'])
        self.assertTrue(pending['requiresHuman'])
        approved = self.write('rws_operation_approve', actor='human', operationRef=proposed['ref'])
        claimed = self.claim(approved)
        unknown = self.update(claimed, 'unknown', {'observedAt': 'fixture-time'})
        context = self.store.call('rws_get_context', {'projectId': 'p', 'experimentRef': experiment['ref']})['result']
        item = next(item for item in context['objects'] if item['ref'] == unknown['ref'])
        self.assertEqual(item['lastObservation']['jobId'], claimed['record']['result']['jobId'])
        self.assertEqual(item['observedAt'], 'fixture-time')

    def running(self, run):
        return self.write('rws_run_register', record={'id': run['ref']['id'], 'status': 'running'})

    def points(self, run, points, **extra):
        return self.write('rws_metrics_append', runRef=run['ref'], points=points, **extra)

    def query(self, runs, **extra):
        return self.store.call('rws_metrics_query', dict(projectId='p', runRefs=[r['ref'] for r in runs], **extra))['result']

    def point(self, x, value, **extra):
        return dict(metricId='loss', x=x, value=value, split='train', **extra)

    def test_metric_batches_deduplicate_conflicts_rollback_and_missing_is_explicit(self):
        *_, run = self.fixture()
        self.expect('validation_error', lambda: self.points(run, [self.point(0, 1)]))
        run = self.running(run)
        result = self.points(run, [self.point(0, 1), self.point(1, None, reason='Not observed')])
        self.assertEqual((result['inserted'], result['duplicates']), (2, 0))
        duplicate = self.points(run, [self.point(0, 1)])
        self.assertEqual((duplicate['inserted'], duplicate['duplicates']), (0, 1))
        self.expect('metric_conflict', lambda: self.points(run, [self.point(2, .5), self.point(0, 2)]))
        self.assertEqual(self.query([run])['total'], 2)
        self.expect('validation_error', lambda: self.points(run, [self.point(2, None)]))
        self.expect('validation_error', lambda: self.points(run, [dict(self.point(2, 1), metricId='unknown')]))
        self.assertFalse(any(e['ref']['type'] == 'artifact' for e in self.store.snapshot('p')['records']))

    def test_original_run_revision_remains_usable_after_execution_starts(self):
        *_, run = self.fixture()
        self.running(run)
        self.points(run, [self.point(0, 1)])
        result = self.query([run])
        artifact = self.write('rws_metrics_snapshot', runRef=run['ref'], title='Original pinned run', throughSequence=result['throughSequence'])
        self.assertEqual(artifact['record']['producerRef'], run['ref'])

    def test_sample_metrics_require_selected_samples_and_snapshot_is_bounded(self):
        definition = [{'id': 'loss', 'unit': 'loss', 'axis': 'step', 'scope': 'sample', 'splits': ['train']}]
        *_, run = self.fixture(metrics=definition)
        run = self.running(run)
        self.expect('validation_error', lambda: self.points(run, [self.point(0, 1)]))
        self.expect('validation_error', lambda: self.points(run, [self.point(0, 1, sampleId='outside')]))
        for start in range(0, 5001, 1000):
            self.points(run, [self.point(x, x, sampleId='a') for x in range(start, min(start + 1000, 5001))])
        result = self.query([run], limit=5000)
        self.assertTrue(result['truncated'])
        self.expect('validation_error', lambda: self.write('rws_metrics_snapshot', runRef=run['ref'], title='Too broad', throughSequence=result['throughSequence']))
        bounded = self.write('rws_metrics_snapshot', runRef=run['ref'], title='One sample window', throughSequence=result['throughSequence'], toX=2)
        self.assertEqual(bounded['record']['source']['pointCount'], 3)

    def test_metric_history_pagination_and_snapshot_freeze_report_inputs(self):
        *_, run = self.fixture()
        run = self.running(run)
        self.points(run, [self.point(i, 1 / (i + 1)) for i in range(4)])
        first = self.query([run], limit=2)
        self.points(run, [self.point(4, .1)])
        second = self.query([run], limit=2, offset=2, throughSequence=first['throughSequence'])
        self.assertEqual(second['total'], 4)
        self.assertFalse(second['truncated'])
        snapshot = self.write('rws_metrics_snapshot', runRef=run['ref'], title='Four observed points', throughSequence=first['throughSequence'])
        self.assertEqual(snapshot['record']['semantic'], 'metric-history')
        self.assertEqual(snapshot['record']['source']['pointCount'], 4)
        self.assertEqual(snapshot['record']['source']['series'][0]['unit'], 'loss')
        self.assertEqual(snapshot['record']['datasetRef'], run['record']['sampleSelection']['datasetRef'])
        self.assertNotIn('sampleId', snapshot['record'])
        report = self.write('rws_report_create_revision', record={'title': 'Fixed metrics', 'markdown': 'Synthetic only.', 'inputRefs': [snapshot['ref']]})
        before = copy.deepcopy(report)
        self.points(run, [self.point(5, .05)])
        self.assertEqual(self.get(report['ref']), before)
        self.assertEqual(self.get(snapshot['ref'])['record']['source']['pointCount'], 4)
        self.expect('validation_error', lambda: self.write('rws_artifact_register', record={'title': 'Forged snapshot', 'kind': 'table', 'semantic': 'metric-history', 'producerRef': run['ref']}))

    def test_alignment_requires_same_definitions_data_and_samples(self):
        _, _, _, _, code, first = self.fixture()
        second = self.write('rws_run_register', record=dict(first['record'], id='run-second', title='Second run'))
        third = self.write('rws_run_register', record=dict(first['record'], id='run-third', title='Different cases',
                           sampleSelection=dict(first['record']['sampleSelection'], sampleIds=['c'])))
        first, second, third = [self.running(r) for r in (first, second, third)]
        self.points(first, [self.point(0, 2), self.point(2, 1)])
        self.points(second, [self.point(0, 3), self.point(1, 2)])
        self.points(third, [self.point(0, 7)])
        result = self.query([first, second, third])
        self.assertEqual(len(result['aligned']), 2)
        shared = next(g for g in result['aligned'] if len(g['columns']) == 2)
        self.assertEqual(shared['xs'], [0, 1, 2])
        self.assertEqual([c['values'] for c in shared['columns']], [[2, None, 1], [3, 2, None]])
        unknown = self.write('rws_run_register', record=dict(first['record'], id='run-unknown', status='running', sampleSelection={'sampleIds': ['a', 'b']}))
        self.points(unknown, [self.point(0, 9)])
        self.assertEqual(len(self.query([first, unknown])['aligned']), 2)

    def test_metric_contract_revision_and_mlflow_source_are_fixed(self):
        _, _, _, spec, _, run = self.fixture()
        run = self.running(run)
        source = {'kind': 'mlflow', 'baseUrl': 'https://example.test/mlflow', 'runId': 'external-run'}
        self.points(run, [self.point(0, 1)], source=source)
        self.write('rws_spec_save', record={'id': spec['ref']['id'], 'processMetrics': [{'id': 'different', 'unit': '', 'axis': 'time', 'scope': 'run'}]})
        self.points(run, [self.point(1, .9)], source=source)
        item = self.query([run])['series'][0]
        self.assertEqual(item['definitionRef'], spec['ref'])
        self.assertEqual(item['points'][0]['source'], source)
        self.expect('metric_conflict', lambda: self.points(run, [self.point(0, 1)]))
        self.expect('validation_error', lambda: self.points(run, [self.point(3, 1)], source=dict(source, baseUrl='https://secret@example.test/mlflow?token=hidden')))


if __name__ == '__main__':
    unittest.main()
