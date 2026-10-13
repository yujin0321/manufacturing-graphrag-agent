"""Small synthetic regression checks; no dataset reads or exhaustive search."""
import unittest

import numpy as np
import pandas as pd

from imaks_pipeline import detector_flags
from joint_window_core import stride_flags
from sweep_joint_windows import CONFIG, calculate_windows, make_base, phase_stride_flags, scored_features, select_combination


class JointWindowSweepTests(unittest.TestCase):
    def observations(self):
        records = []
        for sensor in ['a', 'b']:
            offset = 0. if sensor == 'a' else -200.
            segments = [
                (pd.date_range('2026-01-06 12:00', periods=20, freq='30s'), 100. + offset + np.arange(20.) % 7),
                (pd.date_range('2026-01-07 00:00', periods=16, freq='30s'), np.full(16, 100. + offset)),
                (pd.date_range('2026-01-07 01:00', periods=16, freq='30s'), np.full(16, 500. + offset)),
            ]
            for times, values in segments:
                records.extend({'sensor_id': sensor, 'timestamp': timestamp, 'value': value}
                               for timestamp, value in zip(times, values))
        return pd.DataFrame(records)

    def candidate(self, mean=3, stuck=11, stride=1, **updates):
        row = dict(mean_window_samples=mean, stuck_window_samples=stuck, stride_samples=stride,
                   split='validation', event_f1=.8, unmatched_alarm_events=1,
                   row_f1=.7, mean_delay_min=.5)
        row.update(updates)
        return row

    def test_selection_rejects_nonvalidation_empty_and_duplicate_candidates(self):
        for split in ['train', 'test']:
            with self.subTest(split=split), self.assertRaises(ValueError):
                select_combination(pd.DataFrame([self.candidate(split=split)]))
        with self.assertRaises(ValueError):
            select_combination(pd.DataFrame([self.candidate(), self.candidate(mean=5, split='test')]))
        with self.assertRaises(ValueError):
            select_combination(pd.DataFrame())
        with self.assertRaises(ValueError):
            select_combination(pd.DataFrame([self.candidate(), self.candidate(event_f1=.9)]))

    def test_selection_uses_full_precision_before_other_tie_breaks(self):
        lower = self.candidate(mean=2, stride=1, event_f1=.8, unmatched_alarm_events=0, row_f1=.99, mean_delay_min=0.)
        higher = self.candidate(mean=100, stride=10, event_f1=.8 + 1e-12, unmatched_alarm_events=99, row_f1=.1, mean_delay_min=100.)
        selected, ranking = select_combination(pd.DataFrame([lower, higher]))
        self.assertEqual(selected['mean_window_samples'], 100)
        self.assertGreater(ranking.event_f1.iloc[0], ranking.event_f1.iloc[1])

    def test_equal_metrics_prefer_stride_then_mean_then_stuck(self):
        candidates = [self.candidate(mean=2, stuck=2, stride=2),
                      self.candidate(mean=5, stuck=2, stride=1),
                      self.candidate(mean=3, stuck=20, stride=1),
                      self.candidate(mean=3, stuck=11, stride=1)]
        selected, _ = select_combination(pd.DataFrame(candidates))
        self.assertEqual(selected, dict(mean_window_samples=3, stuck_window_samples=11, stride_samples=1))

    def test_missing_delay_is_ranked_after_a_measured_delay(self):
        rows = [self.candidate(mean=2, mean_delay_min=np.nan),
                self.candidate(mean=20, mean_delay_min=3.)]
        selected, _ = select_combination(pd.DataFrame(rows))
        self.assertEqual(selected['mean_window_samples'], 20)

    def test_future_validation_changes_cannot_affect_past_features(self):
        observations = self.observations()
        change_at = pd.Timestamp('2026-01-07 01:04')
        changed = observations.copy()
        changed.loc[changed.timestamp.ge(change_at), 'value'] += 1e6
        original_base, original_parameters = make_base(observations)
        changed_base, changed_parameters = make_base(changed)
        pd.testing.assert_frame_equal(original_parameters, changed_parameters)
        instant_a, means_a, stucks_a = calculate_windows(original_base, (2, 3, 5), (2, 5, 11))
        instant_b, means_b, stucks_b = calculate_windows(changed_base, (2, 3, 5), (2, 5, 11))
        earlier = original_base.timestamp.lt(change_at).to_numpy()
        np.testing.assert_array_equal(instant_a[earlier], instant_b[earlier])
        for size in means_a:
            np.testing.assert_array_equal(means_a[size][earlier], means_b[size][earlier])
        for size in stucks_a:
            np.testing.assert_array_equal(stucks_a[size][earlier], stucks_b[size][earlier])
        scored_a = scored_features(original_base, 3, 11)
        scored_b = scored_features(changed_base, 3, 11)
        np.testing.assert_allclose(scored_a.mean_z[earlier], scored_b.mean_z[earlier], equal_nan=True)
        np.testing.assert_allclose(scored_a.std_z[earlier], scored_b.std_z[earlier], equal_nan=True)
        np.testing.assert_array_equal(scored_a.stuck_flag[earlier], scored_b.stuck_flag[earlier])

    def test_every_sensor_split_and_gap_segment_restarts_windows(self):
        base, _ = make_base(self.observations())
        self.assertEqual(base.segment_id.nunique(), 6)
        self.assertEqual(base.groupby('segment_id').segment_position.first().tolist(), [0] * 6)
        scored = scored_features(base, 3, 5)
        position = base.segment_position.to_numpy()
        np.testing.assert_array_equal(scored.mean_ready, position >= 2)
        np.testing.assert_array_equal(scored.stuck_ready, position >= 4)
        self.assertTrue(scored.mean_z[position < 2].isna().all())
        self.assertTrue(scored.std_z[position < 4].isna().all())
        self.assertFalse(scored.stuck_flag[position < 4].any())
        _, means, stucks = calculate_windows(base, (3,), (5,))
        self.assertFalse(means[3][position < 2].any())
        self.assertFalse(stucks[5][position < 4].any())
        # Constant validation runs really become STUCK after five observations.
        self.assertTrue(scored.loc[base['split'].eq('validation') & (position >= 4), 'stuck_flag'].all())

    def test_precomputed_flags_equal_scored_detector_for_all_small_pairs(self):
        base, _ = make_base(self.observations())
        means_to_check, stucks_to_check = (2, 3, 5), (2, 5, 11)
        instant, means, stucks = calculate_windows(base, means_to_check, stucks_to_check)
        for mean in means_to_check:
            for stuck in stucks_to_check:
                with self.subTest(mean=mean, stuck=stuck):
                    scored = scored_features(base, mean, stuck)
                    expected = detector_flags(scored, CONFIG)
                    np.testing.assert_array_equal(instant | means[mean] | stucks[stuck], expected)
        self.assertEqual(len(instant), len(base))

    def test_quality_labels_and_threshold_fields_are_rejected(self):
        observations = self.observations()
        base, _ = make_base(observations)
        for field in ['quality', 'anomaly_label', 'nominal', 'warn_hi']:
            with self.subTest(field=field), self.assertRaises(ValueError):
                make_base(observations.assign(**{field: 0}))
            with self.subTest(rolling_field=field), self.assertRaises(ValueError):
                calculate_windows(base.assign(**{field: 0}), (3,), (5,))

    def test_phase_zero_exactly_matches_existing_stride_behavior(self):
        raw = np.random.default_rng(731).random(22) < .4
        positions = np.r_[np.arange(12), np.arange(10)]
        for stride in [1, 2, 3, 10]:
            with self.subTest(stride=stride):
                expected_flags, expected_decisions = stride_flags(raw, positions, stride)
                held, decisions = phase_stride_flags(raw, positions, stride, phase=0)
                np.testing.assert_array_equal(held, expected_flags)
                np.testing.assert_array_equal(decisions, expected_decisions)

    def test_phase_one_manual_hold_segment_restart_and_future_independence(self):
        raw = np.array([False, True, False, False, True, True, False,
                        False, False, True, True, False])
        positions = np.r_[np.arange(7), np.arange(5)]
        held, decisions = phase_stride_flags(raw, positions, 2, phase=1)
        np.testing.assert_array_equal(held, [False, True, True, False, False, True, True,
                                             False, False, False, True, True])
        np.testing.assert_array_equal(decisions, [True, True, False, True, False, True, False,
                                                  True, True, False, True, False])
        self.assertTrue(held[6])
        self.assertFalse(held[7])  # A new segment makes its own immediate decision.
        changed = raw.copy()
        changed[5:] = ~changed[5:]
        changed_held, changed_decisions = phase_stride_flags(changed, positions, 2, phase=1)
        np.testing.assert_array_equal(changed_held[:5], held[:5])
        np.testing.assert_array_equal(changed_decisions, decisions)

    def test_invalid_phase_is_rejected(self):
        raw = np.array([False, True, False])
        positions = np.arange(3)
        for phase in [-1, 2, 3, True, 1.5, '1', None]:
            with self.subTest(phase=phase), self.assertRaises(ValueError):
                phase_stride_flags(raw, positions, 2, phase=phase)


if __name__ == '__main__':
    unittest.main()
