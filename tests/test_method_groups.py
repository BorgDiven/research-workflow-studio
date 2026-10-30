"""Exact comparison selections across implementations; no model execution."""
import copy
import unittest

from rws.core import RwsError, Store


class MethodGroupsTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(':memory:')
        self.sequence = 0
        self.store.call('rws_project_create', dict(projectId='p', name='Synthetic comparison', requestId='project'))
        self.a = self.put('code_register', title='Native', kind='inference', version='v1', source='native.py')
        self.b = self.put('code_register', title='Controlled', kind='inference', version='v1', source='controlled.py', parentRefs=[self.a['ref']])
        self.r1 = self.put('run_register', title='Old batch', codeRef=self.a['ref'], config={'cfg': 4}, status='completed')
        self.r2 = self.put('run_register', title='Two configurations', codeRef=self.b['ref'], config={'modes': ['native', 'controlled']}, status='completed')
        self.outputs = [self.output(self.r1, 0), self.output(self.r2, 0), self.output(self.r2, .5)]

    def tearDown(self):
        self.store.close()

    def put(self, operation, **record):
        return self.call(operation, record=record)

    def call(self, operation, actor='model', **arguments):
        self.sequence += 1
        return self.store.call('rws_' + operation, dict(projectId='p', requestId='write-' + str(self.sequence),
                              expectedRevision=self.store.snapshot('p')['revision'], **arguments), actor=actor)['result']

    def get(self, ref):
        return self.store.call('rws_record_get', {'ref': ref})['result']

    def output(self, run, strength):
        return self.put('artifact_register', title='Synthetic fish', kind='image', semantic='final-image',
                        sampleId='fish', taskKey='change fish to shark', producerRef=run['ref'],
                        config={'cfg': 4, 'strength': strength}, availability='unknown')

    def comparison(self, groups=None):
        return dict(title='Native and controlled', inputRefs=[x['ref'] for x in self.outputs],
                    fixedConditions={'cfg': 4}, varyingConditions=['method', 'strength'],
                    viewSpec={'mode': 'multi', 'axis': 'method', 'methodGroups': groups if groups is not None else [
                        {'id': 'native', 'label': 'Native', 'artifactRefs': [x['ref'] for x in self.outputs[:2]]},
                        {'id': 'controlled', 'label': 'Controlled', 'artifactRefs': [self.outputs[2]['ref']]}]})

    def test_one_run_has_multiple_configs_and_comparison_preserves_both_producers(self):
        before = copy.deepcopy(self.outputs)
        comparison = self.put('comparison_save', **self.comparison())
        self.assertEqual(comparison['record']['viewSpec']['methodGroups'][0]['artifactRefs'], [x['ref'] for x in self.outputs[:2]])
        self.assertEqual([self.get(x['ref']) for x in self.outputs], before)
        self.assertEqual(self.outputs[1]['record']['producerRef'], self.outputs[2]['record']['producerRef'])
        self.assertNotEqual(self.outputs[1]['record']['config'], self.outputs[2]['record']['config'])
        self.assertEqual(self.get(self.r2['ref'])['record']['codeRef'], self.b['ref'])

    def test_report_keeps_fixed_comparison_members_when_new_results_arrive(self):
        comparison = self.put('comparison_save', **self.comparison())
        report = self.put('report_create_revision', title='Selected evidence', markdown='Synthetic test only.', comparisonRefs=[comparison['ref']])
        self.output(self.r2, .8)
        self.put('comparison_save', id=comparison['ref']['id'], viewSpec={'mode': 'multi', 'axis': 'implementation'})
        self.assertEqual(self.get(report['ref']), report)
        pinned = next(x for x in report['record']['snapshot']['records'] if x['ref'] == comparison['ref'])
        self.assertEqual(pinned['record']['viewSpec'], comparison['record']['viewSpec'])

    def test_groups_reject_ambiguous_or_unpinned_members(self):
        base = self.comparison()['viewSpec']['methodGroups']
        extra = self.output(self.r2, 1)['ref']
        invalid = []
        outsider = copy.deepcopy(base); outsider[0]['artifactRefs'].append(extra); invalid.append(outsider)
        duplicate = copy.deepcopy(base); duplicate[1]['artifactRefs'].append(self.outputs[0]['ref']); invalid.append(duplicate)
        duplicate_id = copy.deepcopy(base); duplicate_id[1]['id'] = duplicate_id[0]['id']; invalid.append(duplicate_id)
        unpinned = copy.deepcopy(base); del unpinned[0]['artifactRefs'][0]['version']; invalid.append(unpinned)
        wrong_type = copy.deepcopy(base); wrong_type[0]['artifactRefs'] = [self.r1['ref']]; invalid.append(wrong_type)
        empty = copy.deepcopy(base); empty[0]['artifactRefs'] = []; invalid.append(empty)
        for groups in invalid:
            with self.subTest(groups=groups), self.assertRaises(RwsError):
                self.put('comparison_save', **self.comparison(groups))

    def test_input_amendment_cannot_remove_grouped_material(self):
        comparison = self.put('comparison_save', **self.comparison())
        revision = self.store.snapshot('p')['revision']
        with self.assertRaisesRegex(RwsError, 'Method group members must be exact artifacts'):
            self.put('amendment_propose', title='Remove selected input', targetRef=comparison['ref'],
                     patch={'inputRefs': [self.outputs[2]['ref']]}, reason='Synthetic correction', evidenceRefs=[])
        self.assertEqual(self.store.snapshot('p')['revision'], revision)
        self.assertEqual(self.get(comparison['ref']), comparison)

    def test_valid_input_amendments_preserve_groups_and_legacy_comparisons(self):
        for grouped in (False, True):
            with self.subTest(grouped=grouped):
                record = self.comparison()
                if grouped:
                    record['viewSpec']['methodGroups'] = record['viewSpec']['methodGroups'][:1]
                else:
                    del record['viewSpec']['methodGroups']
                comparison = self.put('comparison_save', **record)
                before = self.put('report_create_revision', title='Before correction', markdown='Synthetic only.',
                                  comparisonRefs=[comparison['ref']])
                inputs = [x['ref'] for x in self.outputs[:2]]
                proposal = self.put('amendment_propose', title='Narrow selected inputs', targetRef=comparison['ref'],
                                    patch={'inputRefs': inputs}, reason='Remove ungrouped material', evidenceRefs=[])
                self.call('amendment_apply', actor='human', amendmentRef=proposal['ref'])
                current = self.get(comparison['ref'])
                self.assertEqual(current['record'], comparison['record'])
                self.assertEqual(current['effectiveRecord']['inputRefs'], inputs)
                self.assertEqual(current['effectiveRecord']['viewSpec'], comparison['record']['viewSpec'])
                self.assertEqual(self.get(before['ref']), before)
                after = self.put('report_create_revision', title='After correction', markdown='Synthetic only.',
                                 comparisonRefs=[comparison['ref']])
                pinned = next(e for e in after['record']['snapshot']['records'] if e['ref'] == comparison['ref'])
                self.assertEqual(pinned['effectiveRecord']['inputRefs'], inputs)
                self.assertEqual(pinned['effectiveRecord']['viewSpec'], comparison['record']['viewSpec'])
