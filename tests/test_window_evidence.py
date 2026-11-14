from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from imaks_kg.rag import decision_evidence as d, window_evidence as w, team_runtime as runtime, vector as v
from tests.claim_fixtures import selected_claims


class WindowMetricTests(unittest.TestCase):
    def rows(self, values, step=30):
        start = datetime(2026, 1, 1)
        return [{'timestamp': (start + timedelta(seconds=i * step)).isoformat(), 'value': str(value),
                 'sensor_id': 'S', 'unit': 'U'} for i, value in enumerate(values)]

    def proof(self, rows, params, executor=None, index=-1, **cfg):
        sigma = cfg.pop('sigma', None)
        return w.rule_proof(rows, rows[index]['timestamp'], {'executor': executor, 'params': params},
                            {'sample_seconds': 30, **cfg}, sigma=sigma)

    def test_outside_band_requires_twenty_observations_not_ten_elapsed_minutes(self):
        rows = self.rows([5] * 21)
        params = {'lo': 1, 'hi': 4, 'readings': 20}
        self.assertEqual(self.proof(rows, params, 'outside_run', index=18)['state'], 'inconsistent')
        result = self.proof(rows, params, 'outside_run', index=19)
        self.assertEqual(result['state'], 'consistent')
        self.assertEqual(result['elapsed_seconds'], '570.0')
        self.assertEqual(self.proof(rows, params, 'outside_run', index=20)['state'], 'inconsistent')

    def test_sustained_deviation_uses_inclusive_thirty_minute_window(self):
        rows = self.rows([15] * 62)
        params = {'nominal': 12.4, 'delta': 1, 'min_minutes': 30}
        self.assertEqual(self.proof(rows, params, 'sustained_from_nominal', index=59)['state'], 'inconsistent')
        proof = self.proof(rows, params, 'sustained_from_nominal', index=60)
        self.assertEqual(proof['state'], 'consistent')
        self.assertEqual(proof['elapsed_seconds'], '1800.0')

    def test_exact_stuck_confirmation_and_recorded_plateau_start(self):
        rows = self.rows([2] * 13)
        base = {'op': 'stuck_exact', 'value': '11', 'duration_seconds': 0}
        first = self.proof(rows, base, 'threshold_scan', index=10)
        second = self.proof(rows, {**base, 'confirm_observations': 2}, index=11)
        self.assertEqual(first['state'], 'consistent')
        self.assertEqual(second['state'], 'consistent')
        self.assertEqual(first['condition_start'], rows[0]['timestamp'])
        self.assertEqual(second['condition_start'], rows[0]['timestamp'])
        self.assertEqual(self.proof(rows, {**base, 'confirm_observations': 2}, index=10)['state'], 'inconsistent')

    def test_std_stuck_allows_small_jitter_but_exact_stuck_does_not(self):
        rows = self.rows([2, 2.001] * 5)
        result = self.proof(rows, {'window': 10, 'limit': '.0022'}, 'stuck_std')
        self.assertEqual(result['state'], 'consistent')
        self.assertEqual(result['condition_start'], rows[0]['timestamp'])
        self.assertEqual(self.proof(rows, {'op': 'stuck_exact', 'value': '10'})['state'], 'inconsistent')

    def test_std_uses_population_variance_and_strict_boundary(self):
        rows = self.rows([0, 2])
        self.assertEqual(self.proof(rows, {'window': 2, 'limit': 1}, 'stuck_std')['state'], 'inconsistent')
        result = self.proof(rows, {'window': 2, 'limit': 1.001}, 'stuck_std')
        self.assertEqual(result['state'], 'consistent')
        self.assertEqual(result['metrics']['population_std'], '1')

    def test_signed_delta_has_exact_lookback_and_two_point_confirmation(self):
        rows = self.rows([0, 0, 2, 2])
        params = {'op': 'delta_gt', 'value': 1, 'window_seconds': 60, 'confirm_observations': 2}
        result = self.proof(rows, params)
        self.assertEqual(result['state'], 'consistent')
        self.assertEqual(result['metrics']['baseline_at'], rows[1]['timestamp'])
        self.assertEqual(result['condition_start'], rows[2]['timestamp'])
        self.assertEqual(self.proof(self.rows([2, 2, 0, 0]), params)['state'], 'inconsistent')

    def test_incomplete_or_interrupted_delta_window_is_not_verified(self):
        params = {'op': 'delta_gt', 'value': 1, 'window_seconds': 60, 'confirm_observations': 1}
        rows = self.rows([0, 1, 2])
        self.assertEqual(self.proof(rows, params, index=1)['state'], 'inconsistent')
        del rows[1]
        self.assertEqual(self.proof(rows, params)['state'], 'inconsistent')

    def test_smoothed_change_requires_full_window_and_away_direction(self):
        params = {'window_min': 1, 'delta': 1, 'nominal': 0}
        rows = self.rows([0, 0, 2, 2])
        proof = self.proof(rows, params, 'window_change', smooth_samples=2, maint_direction='away')
        self.assertEqual(proof['state'], 'consistent')
        self.assertEqual(proof['metrics']['absolute_delta'], '2')
        toward = self.rows([4, 4, 2, 2])
        self.assertEqual(self.proof(toward, params, 'window_change', smooth_samples=2, maint_direction='away')['state'], 'inconsistent')
        self.assertEqual(self.proof(toward, params, 'window_change', smooth_samples=2, maint_direction='any')['state'], 'consistent')

    def test_slope_scale_direction_and_consecutive_readings(self):
        params = {'window_min': 1, 'k_sigma_per_min': 1, 'nominal': 0, 'readings': 2}
        rows = self.rows([0, 1, 2])
        result = self.proof(rows, params, 'slope', sigma=1)
        self.assertEqual(result['state'], 'consistent')
        self.assertEqual(result['metrics']['slope_per_minute'], '2')
        self.assertEqual(self.proof(rows, params, 'slope', index=1, sigma=1)['state'], 'inconsistent')
        self.assertEqual(self.proof(self.rows([-3, -2, -1]), params, 'slope', sigma=1)['state'], 'inconsistent')
        self.assertEqual(self.proof(self.rows([0, -1, -2]), params, 'slope', sigma=1)['state'], 'consistent')

    def test_future_values_do_not_affect_a_window_proof(self):
        params = {'op': 'delta_gt', 'value': 1, 'window_seconds': 60, 'confirm_observations': 2}
        rows = self.rows([0, 0, 2, 2, 'NaN'])
        self.assertEqual(self.proof(rows, params, index=3), self.proof(rows[:4], params))

    def test_gap_and_duplicate_timestamp_are_rejected(self):
        rows = self.rows([2] * 10)
        rows[5]['timestamp'] = rows[4]['timestamp']
        with self.assertRaises(ValueError):
            self.proof(rows, {'window': 10, 'limit': .01}, 'stuck_std')
        rows = self.rows([2] * 11)
        del rows[5]
        self.assertEqual(self.proof(rows, {'window': 10, 'limit': .01}, 'stuck_std')['state'], 'inconsistent')

    def test_training_sigma_is_recomputed_and_future_training_is_not_verified(self):
        rows = self.rows([0, 1, 2])
        cfg = {'train_end': '2026-01-02'}
        recorded = {'sigma': 1.4826, 'method': '1.4826*MAD', 'train_samples': 3}
        self.assertEqual(w.calibration(rows, cfg, recorded, '2026-01-03')['state'], 'consistent')
        self.assertEqual(w.calibration(rows, cfg, {**recorded, 'sigma': 9}, '2026-01-03')['state'], 'inconsistent')
        self.assertEqual(w.calibration(rows, cfg, recorded, rows[-1]['timestamp'])['state'], 'unassessed')


@unittest.skipUnless((runtime.directories('main_v3_1')[1] / 'complete.json').exists(), 'restore runtime first')
class MonitorDependencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = runtime.store('main_v3_1')
        cls.alarm = next(a for a in cls.store.alarms.values() if a['kind'] == 'kg_correlation_monitor')
        cls.bundle = w.checked_file(cls.store, 'ir.json')
        cls.params = w.checked_file(cls.store, 'params.json')
        cls.rows, _ = d.observations(cls.alarm['sensor_id'])

    def test_promoted_signal_is_recovered_by_exact_hash_and_recomputed(self):
        retained = w.checked_file(self.store, 'signals.json')
        self.assertNotIn(self.alarm['source_signal'], {s['id'] for s in retained})
        result = w.monitor_proof(self.rows, self.alarm, self.store, self.bundle, self.params)
        self.assertEqual(result['state'], 'consistent')
        self.assertEqual(result['source_signal_reference_status'], 'removed_after_promotion_reconstructed_with_exact_hash')
        self.assertEqual(result['source_trigger_check']['operator'], 'slope')
        self.assertEqual(result['calibration']['state'], 'consistent')

    def test_bad_signal_hash_and_wrong_warning_anchor_are_blocked(self):
        wrong = {**self.alarm, 'source_signal': 'det31-' + '0' * 20}
        self.assertEqual(w.monitor_proof(self.rows, wrong, self.store, self.bundle, self.params)['state'], 'inconsistent')
        params = deepcopy(self.params)
        params['config']['monitor_anchor'] = 'warning_trigger'
        self.assertEqual(w.monitor_proof(self.rows, self.alarm, self.store, self.bundle, params)['state'], 'inconsistent')

    def test_monitor_model_context_includes_the_slope_and_window_source(self):
        from imaks_kg.rag import incident_agent
        scratch = v.REPO_ROOT / 'kg_build/window_tests'
        scratch.mkdir(exist_ok=True)
        self.assertTrue(scratch.resolve().is_relative_to(v.REPO_ROOT.resolve()))
        def call(resource, payload, cache):
            stage = Path(cache).name
            if stage == 'plan':
                text = json.dumps({'intent': 'explain', 'tool': 'get_incident_evidence', 'arguments': {'incident_id': incident['id']}})
            elif stage == 'draft':
                text = selected_claims(json.loads(payload['messages'][-1]['content']))
            else:
                evidence = json.loads(payload['messages'][-1]['content'])['evidence']
                self.assertTrue(any(source['chunk_id'] == 'SOP-002:p2:table6:chunk' for source in evidence['untrusted_reference_documents']))
                self.assertEqual(evidence['decision_validation_summary']['unassessed_trigger_count'], 0)
                text = json.dumps({'approved': True, 'issues': []})
            return {'model': payload['model'], 'choices': [{'finish_reason': 'stop', 'message': {'content': text}}]}, {'mock': True}
        for profile in ('main_v3_1', 'yujin_v3_2'):
            store = runtime.store(profile)
            for incident in store.incidents:
                if not any(store.alarms[aid]['kind'] == 'kg_correlation_monitor' for aid in incident['alarm_ids']):
                    continue
                with self.subTest(profile=profile, incident=incident['id']), tempfile.TemporaryDirectory(dir=scratch) as folder:
                    self.assertTrue(Path(folder).resolve().is_relative_to(scratch.resolve()))
                    result = incident_agent.answer('과거 사건 ' + incident['id'] + ' 설명', Path(folder) / 'run', call,
                                                   store=store, detector_profile=profile)
                    self.assertEqual(result['status'], 'complete', result.get('reason'))
                    self.assertLessEqual(result['xai']['context_tokens'], 4000)


if __name__ == '__main__':
    unittest.main()
