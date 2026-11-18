import unittest

import numpy as np
import pandas as pd

from sweep_window_sizes import make_base, measure_split, score_window, select_window


class SweepTests(unittest.TestCase):
    def test_selection_rejects_test_and_mixed_splits(self):
        metrics = pd.DataFrame({'split': ['validation', 'test'], 'window_samples': [3, 5],
                                'event_f1': [0.5, 1.], 'unmatched_alarm_events': [1, 0],
                                'row_f1': [0.5, 1.], 'mean_delay_min': [1., 0.]})
        with self.assertRaises(ValueError): select_window(metrics)
        with self.assertRaises(ValueError): select_window(metrics[metrics['split'].eq('test')])

    def test_primary_event_quality_wins_before_row_metric(self):
        metrics = pd.DataFrame({'split': 'validation', 'window_samples': [3, 5, 10],
                                'event_f1': [.9, 1., 1.], 'unmatched_alarm_events': [0, 0, 0],
                                'row_f1': [1., .8, .8], 'mean_delay_min': [0., 1., 1.]})
        selected, _ = select_window(metrics.sample(frac=1, random_state=3))
        self.assertEqual(selected, 5)

    def test_variable_mean_is_causal_and_resets_at_split_and_gap(self):
        training = pd.DataFrame({'sensor_id': 'a', 'timestamp': pd.date_range('2026-01-06 23:50', periods=20, freq='30s'),
                                 'value': 10+np.sin(np.arange(20))})
        validation = pd.DataFrame({'sensor_id': 'a', 'timestamp': pd.date_range('2026-01-07', periods=25, freq='30s'),
                                   'value': 10+np.sin(np.arange(25))})
        after_gap = validation.iloc[:4].copy()
        after_gap['timestamp'] += pd.Timedelta(hours=2)
        observations = pd.concat([training, validation, after_gap], ignore_index=True)
        altered = observations.copy()
        altered.loc[40:, 'value'] = 100000.
        base, params = make_base(observations)
        other, other_params = make_base(altered)
        pd.testing.assert_frame_equal(params, other_params)
        for size in [3, 10, 20]:
            scored = score_window(base, size)
            changed = score_window(other, size)
            pd.testing.assert_frame_equal(scored.loc[:39, ['z_abs', 'rolling_z', 'stuck_flag']],
                                          changed.loc[:39, ['z_abs', 'rolling_z', 'stuck_flag']])
            self.assertTrue(scored.loc[20:20+size-2, 'rolling_z'].isna().all())
            self.assertTrue(scored.loc[45:45+min(size-1, 4)-1, 'rolling_z'].isna().all())
            self.assertEqual(len(scored), len(observations))

    def test_stuck_definition_is_independent_of_mean_window(self):
        observations = pd.DataFrame({'sensor_id': 'a', 'timestamp': pd.date_range('2026-01-06 06:00', periods=50, freq='30s'),
                                     'value': np.r_[10+np.sin(np.arange(30)), np.repeat(10., 20)]})
        base, _ = make_base(observations)
        short = score_window(base, 3)
        long = score_window(base, 30)
        np.testing.assert_array_equal(short.stuck_flag, long.stuck_flag)
        self.assertTrue(short.stuck_flag.iloc[40:].all())
        self.assertFalse(short.stuck_ready.iloc[:10].any())

    def test_warmup_keeps_all_rows_and_instant_detection_active(self):
        training = pd.DataFrame({'sensor_id': 'a', 'timestamp': pd.date_range('2026-01-06 06:00', periods=30, freq='30s'),
                                 'value': 10+np.sin(np.arange(30))})
        validation = pd.DataFrame({'sensor_id': 'a', 'timestamp': pd.date_range('2026-01-07', periods=8, freq='30s'),
                                   'value': 1000.})
        base, _ = make_base(pd.concat([training, validation], ignore_index=True))
        labels = pd.DataFrame({'anomaly_label': np.where(base['split'].eq('validation'), 'SPIKE', 'NORMAL')}, index=base.index)
        truth = pd.DataFrame({'event_id': ['E'], 'sensor_id': ['a'], 'split': ['validation'],
                              'start': [validation.timestamp.iloc[0]], 'end': [validation.timestamp.iloc[-1]]})
        for size in [3, 120]:
            metrics, _, _ = measure_split(score_window(base, size), labels, truth, 'validation', size)
            self.assertEqual(metrics['evaluated_rows'], 8)
            self.assertEqual(metrics['row_tp'], 8)
            self.assertEqual(metrics['detected_events'], 1)
            if size == 120:
                self.assertEqual(metrics['mean_ready_rows'], 0)


if __name__ == '__main__':
    unittest.main()
