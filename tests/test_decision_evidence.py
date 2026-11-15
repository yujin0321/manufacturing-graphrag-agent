from copy import deepcopy
from datetime import datetime, timedelta
import unittest

from imaks_kg.rag import decision_evidence as d, incident_tools, vector as v


class PredicateTests(unittest.TestCase):
    def rows(self, values, step=30):
        t = datetime(2026, 1, 1)
        return [{'timestamp': (t + timedelta(seconds=i * step)).isoformat(), 'sensor_id': 'S',
                 'value': str(value), 'unit': 'C'} for i, value in enumerate(values)]

    def test_strict_thresholds_and_band_boundaries(self):
        self.assertFalse(d.predicate('210', {'op': 'gt', 'value': '210'}))
        self.assertTrue(d.predicate('210.0001', {'op': 'gt', 'value': '210'}))
        self.assertFalse(d.predicate('175', {'op': 'lt', 'value': '175'}))
        for value in ('175', '195'):
            self.assertFalse(d.predicate(value, {'op': 'outside', 'value': '175', 'second': '195'}))
        self.assertTrue(d.predicate('174.999', {'op': 'outside', 'value': '175', 'second': '195'}))

    def test_duration_is_strict_and_first_trigger_is_checked(self):
        rows = self.rows([26] * 14)
        params = {'op': 'gt', 'value': '25', 'duration_seconds': 300}
        at = lambda i: rows[i]['timestamp']
        self.assertEqual(d.threshold_proof(rows, at(10), params)['state'], 'inconsistent')
        self.assertEqual(d.threshold_proof(rows, at(11), params)['state'], 'consistent')
        self.assertEqual(d.threshold_proof(rows, at(12), params)['state'], 'inconsistent')
        self.assertEqual(d.threshold_proof(rows, at(11), params, confirm=2)['state'], 'inconsistent')
        self.assertEqual(d.threshold_proof(rows, at(12), params, confirm=2)['state'], 'consistent')

    def test_two_point_confirmation_resets_on_a_gap(self):
        rows = self.rows([212, 212, 212])
        params = {'op': 'gt', 'value': '210'}
        self.assertEqual(d.threshold_proof(rows, rows[0]['timestamp'], params, confirm=2)['state'], 'inconsistent')
        self.assertEqual(d.threshold_proof(rows, rows[1]['timestamp'], params, confirm=2)['state'], 'consistent')
        del rows[1]
        self.assertEqual(d.threshold_proof(rows, rows[1]['timestamp'], params, confirm=2)['state'], 'inconsistent')

    def test_normal_observation_resets_persistence(self):
        rows = self.rows([26] * 11 + [24, 26])
        proof = d.threshold_proof(rows, rows[-1]['timestamp'], {'op': 'gt', 'value': '25', 'duration_seconds': 300})
        self.assertEqual(proof['state'], 'inconsistent')
        self.assertEqual(proof['elapsed_seconds'], '0.0')

    def test_future_values_do_not_change_trigger_proof(self):
        rows = self.rows([212, 212, 1, 999])
        params = {'op': 'gt', 'value': '210'}
        self.assertEqual(d.threshold_proof(rows, rows[1]['timestamp'], params, confirm=2),
                         d.threshold_proof(rows[:2], rows[1]['timestamp'], params, confirm=2))

    def test_complex_features_are_explicitly_unassessed(self):
        for op in ('stuck_exact', 'delta_gt', None):
            self.assertEqual(d.threshold_proof([], 'unused', {'op': op})['state'], 'unassessed')

    def test_nonfinite_duplicate_times_and_mixed_units_are_rejected(self):
        for value in ('NaN', 'Infinity', '-Infinity'):
            with self.assertRaises(ValueError):
                d.predicate(value, {'op': 'gt', 'value': '210'})
        rows = self.rows([212, 212])
        rows[1]['timestamp'] = rows[0]['timestamp']
        with self.assertRaises(ValueError):
            d.threshold_proof(rows, rows[0]['timestamp'], {'op': 'gt', 'value': '210'})
        rows = self.rows([212, 212])
        rows[0]['unit'] = 'F'
        with self.assertRaises(ValueError):
            d.threshold_proof(rows, rows[1]['timestamp'], {'op': 'gt', 'value': '210'}, confirm=2)


@unittest.skipUnless((incident_tools.ENGINE_OVERLAY / 'complete.json').exists(), 'restore runtime first')
class GroundingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = incident_tools.IncidentStore()
        cls.evidence = incident_tools.get_incident_evidence(cls.store, {'incident_id': cls.store.incidents[0]['id']})
        cls.rows, cls.checksum = d.observations(cls.evidence['incident']['sensor_id'])

    def build(self, change=None):
        evidence = deepcopy(self.evidence)
        if change:
            change(evidence)
        return d.build(evidence, self.store, rows=self.rows, input_sha256=self.checksum)

    def test_raw_observation_threshold_and_sources_are_bound(self):
        report = self.build()
        self.assertEqual(report['status'], 'consistent')
        self.assertEqual(len(report['items']), 4)
        self.assertTrue(all(item['trigger_check']['state'] == 'consistent' for item in report['items']))
        self.assertTrue(all(item['rule']['source_chunks'] for item in report['items']))

    def test_wrong_unit_value_and_other_incident_alarm_are_blocked(self):
        mutations = [lambda e: e['alarms'][0].update(unit='F'),
                     lambda e: e['alarms'][0].update(trigger_value='2120'),
                     lambda e: e['alarms'][0].update(id='det31-' + '0' * 20)]
        for mutation in mutations:
            self.assertEqual(self.build(mutation)['status'], 'inconsistent')

    def test_missing_altered_and_conflicting_source_links_are_blocked(self):
        mutations = [lambda e: e['untrusted_reference_documents'].pop(),
                     lambda e: e['untrusted_reference_documents'][0].update(text='tampered source'),
                     lambda e: e['matched_rules'][0].update(source_chunks=['SOP-003:p1:table1:chunk']),
                     lambda e: e['matched_rules'][0].update(response_text='invented response')]
        for mutation in mutations:
            self.assertEqual(self.build(mutation)['status'], 'inconsistent')

    def test_modified_execution_parameter_is_blocked(self):
        ir = v.read(self.store.run_dir / 'ir.json')['rules']
        rule = next(r for r in ir if r['rule_id'] == self.evidence['alarms'][0]['rule_id'] and r['sensor_id'] == self.evidence['incident']['sensor_id'])
        def mutate(evidence):
            evidence['execution_parameters'] = [{'ir_id': rule['ir_id'], 'params': {'op': 'gt', 'value': '999'}}]
        self.assertEqual(self.build(mutate)['status'], 'inconsistent')

    @unittest.skipUnless((v.REPO_ROOT / 'kg_build/graphrag_live/team_main_20261113_01/answer.json').exists(), 'restore saved example first')
    def test_saved_answer_is_preserved_during_free_recheck(self):
        run = v.REPO_ROOT / 'kg_build/graphrag_live/team_main_20261113_01'
        before = (run / 'answer.json').read_bytes()
        result = d.for_saved_run(run)
        self.assertEqual(result['new_api_calls'], 0)
        self.assertEqual(result['decision_evidence']['status'], 'consistent')
        self.assertEqual(before, (run / 'answer.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
