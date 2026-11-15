from datetime import datetime, timedelta
import unittest

from imaks_kg.rag import rule_explanations as x


def rows(values, seconds=None):
    start = datetime(2026, 1, 1)
    return [{'timestamp': (start + timedelta(seconds=t)).isoformat(), 'value': str(value),
             'sensor_id': 'S', 'unit': 'A'} for t, value in zip(seconds or range(0, len(values)*30, 30), values)]


class RuleExplanationTests(unittest.TestCase):
    def test_strict_boundaries_have_no_fabricated_minimum_intervention(self):
        for op, below, above in [('gt', False, True), ('lt', True, False)]:
            result = x.boundary({'params': {'op': op, 'value': '1.25'}}, {'sample_seconds': 30})
            self.assertEqual((result['axes'][0]['below'], result['axes'][0]['equal'], result['axes'][0]['above']),
                             (below, False, above))
            self.assertFalse(result['minimal_physical_intervention'])

    def test_strict_duration_and_two_confirmations_start_at_the_correct_sample(self):
        report = x.boundary({'params': {'op': 'gt', 'value': 1, 'duration_seconds': 60,
                                       'confirm_observations': 2}}, {'sample_seconds': 30})
        self.assertEqual(report['time_policy']['earliest_trigger_elapsed_from_feature_streak_seconds'], 120)
        self.assertFalse(report['time_policy']['at_duration_boundary_qualifies'])

    def test_outside_includes_endpoints_as_nonviolating_even_for_degenerate_band(self):
        result = x.boundary({'params': {'op': 'outside', 'value': 4, 'second': 4}}, {'sample_seconds': 30})
        self.assertFalse(result['axes'][0]['at_lower'])
        self.assertFalse(result['axes'][0]['at_upper'])
        self.assertTrue(result['axes'][0]['degenerate_interval'])

    def test_stuck_equal_count_is_inclusive_and_delta_is_signed(self):
        exact = x.boundary({'params': {'op': 'stuck_exact', 'value': 11}}, {'sample_seconds': 30})
        self.assertTrue(exact['axes'][0]['equal'])
        delta = x.boundary({'params': {'op': 'delta_gt', 'value': 1}}, {'sample_seconds': 30})
        self.assertIn('signed', delta['axes'][0]['feature'])

    def test_slope_requires_positive_calibration_and_direction_gate(self):
        rule = {'executor': 'slope', 'params': {'k_sigma_per_min': 2, 'readings': 3}}
        self.assertEqual(x.boundary(rule, {'sample_seconds': 30})['state'], 'unassessed')
        report = x.boundary(rule, {'sample_seconds': 30}, sigma='0.5')
        self.assertEqual(report['axes'][0]['boundary'], '1.0')
        self.assertEqual(report['time_policy']['earliest_trigger_elapsed_from_feature_streak_seconds'], 60)
        self.assertTrue(any('signed_slope' in gate for gate in report['other_required_gates']))

    def test_single_clear_is_rule_release_not_machine_recovery(self):
        data = rows([5, 6, 0])
        result = x.closure(data, {'trigger_at': data[0]['timestamp'], 'last_positive_at': data[1]['timestamp']},
                           [True, True, False])
        self.assertEqual(result['state'], 'consistent')
        self.assertEqual(result['closure_kind'], 'rule_condition_cleared')
        self.assertEqual(result['normal_confirmed_at'], data[2]['timestamp'])
        self.assertFalse(result['machine_recovery_verified'])

    def test_one_nonqualifying_point_is_bridged_only_with_two_clear_policy(self):
        data = rows([5, 0, 6, 0, 0])
        alarm = {'trigger_at': data[0]['timestamp'], 'last_positive_at': data[2]['timestamp'],
                 'status': 'recovered', 'normal_confirmed_at': data[4]['timestamp'],
                 'clear_started_at': data[3]['timestamp'], 'closed_at': data[4]['timestamp']}
        result = x.closure(data, alarm, [True, False, True, False, False], clear=2)
        self.assertEqual(result['state'], 'consistent')
        self.assertEqual(result['normal_confirmed_at'], data[4]['timestamp'])
        self.assertEqual(x.closure(data, alarm, [True, False, True, False, False], clear=1)['state'], 'inconsistent')

    def test_gap_and_data_end_never_report_recovery(self):
        for data, expected in [(rows([5, 5]), 'open_at_data_end'),
                               (rows([5, 5], [0, 90]), 'data_gap_unconfirmed')]:
            last = data[-1]['timestamp'] if expected == 'open_at_data_end' else data[0]['timestamp']
            result = x.closure(data, {'trigger_at': data[0]['timestamp'], 'last_positive_at': last}, [True, True])
            self.assertEqual(result['closure_kind'], expected)
            self.assertIsNone(result['normal_confirmed_at'])

    def test_altered_last_positive_and_normal_confirmation_are_detected(self):
        data = rows([5, 0, 0])
        alarm = {'trigger_at': data[0]['timestamp'], 'last_positive_at': data[1]['timestamp'],
                 'status': 'recovered', 'normal_confirmed_at': data[1]['timestamp'], 'closed_at': data[1]['timestamp']}
        result = x.closure(data, alarm, [True, False, False], clear=2)
        self.assertEqual(result['state'], 'inconsistent')
        self.assertFalse(result['checks']['last_positive_at'])
        self.assertFalse(result['checks']['normal_confirmed_at'])

    def test_incomplete_feature_does_not_count_as_normal(self):
        data = rows([5, 0])
        result = x.closure(data, {'trigger_at': data[0]['timestamp'], 'last_positive_at': data[0]['timestamp']}, [True, None])
        self.assertEqual(result['closure_kind'], 'feature_unavailable')
        self.assertIsNone(result['normal_confirmed_at'])


if __name__ == '__main__':
    unittest.main()
