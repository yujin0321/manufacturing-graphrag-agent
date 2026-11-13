"""Synthetic checks for configurable features; never reads the real dataset."""
import unittest

import numpy as np
import pandas as pd

from causal_features import POINT_FEATURES, add_three_sample_features
from joint_causal_features import add_features, feature_schema, numeric_fields


class JointCausalFeatureTests(unittest.TestCase):
    def frame(self, values, sensor='a', start='2026-01-06 12:00', split='train', segment='a-train'):
        return pd.DataFrame({'sensor_id': sensor,
                             'timestamp': pd.date_range(start, periods=len(values), freq='30s'),
                             'split': split, 'segment_id': segment,
                             'value': np.asarray(values, dtype=float),
                             'median': 100., 'robust_scale': 2.})

    def multi_segment(self):
        frames = []
        for sensor in ['a', 'b']:
            offset = 0 if sensor == 'a' else 20
            for start, split, suffix in [('2026-01-06 12:00', 'train', 'train'),
                                         ('2026-01-07 00:00', 'validation', 'validation'),
                                         ('2026-01-07 01:00', 'validation', 'gap')]:
                frames.append(self.frame(100 + offset + np.arange(12.) * 2,
                                         sensor=sensor, start=start, split=split,
                                         segment=f'{sensor}-{suffix}'))
        return pd.concat(frames, ignore_index=True)

    def test_manual_two_sample_statistics_deltas_and_half_minute_rates(self):
        base = self.frame([100, 102, 106])
        result = add_features(base, 2, 10)
        np.testing.assert_array_equal(result.value_z, [0, 1, 3])
        np.testing.assert_array_equal(result.z_abs, [0, 1, 3])
        expected = {
            'delta_value_1': [np.nan, 2, 4], 'rate_value_1_per_min': [np.nan, 4, 8],
            'delta_z_1': [np.nan, 1, 2], 'rate_z_1_per_min': [np.nan, 2, 4],
            'mean_value_2': [np.nan, 101, 104], 'std_value_2': [np.nan, 1, 2],
            'min_value_2': [np.nan, 100, 102], 'max_value_2': [np.nan, 102, 106],
            'range_value_2': [np.nan, 2, 4], 'change_value_2': [np.nan, 2, 4],
            'rate_value_2_per_min': [np.nan, 4, 8],
            'mean_z_2': [np.nan, .5, 2], 'std_z_2': [np.nan, .5, 1],
            'min_z_2': [np.nan, 0, 1], 'max_z_2': [np.nan, 1, 3],
            'range_z_2': [np.nan, 1, 2], 'change_z_2': [np.nan, 1, 2],
            'rate_z_2_per_min': [np.nan, 2, 4],
        }
        for name, values in expected.items():
            with self.subTest(feature=name):
                np.testing.assert_allclose(result[name], values, rtol=0, atol=0, equal_nan=True)
        self.assertTrue(result.std_z_10.isna().all())
        pd.testing.assert_frame_equal(base, result[base.columns])

    def test_stuck_ten_is_separate_and_warmup_rows_remain_nan(self):
        values = [100, 102, 106, 108, 110, 112, 114, 116, 118, 120, 122, 124]
        result = add_features(self.frame(values), 2, 10)
        self.assertEqual(len(result), len(values))
        self.assertTrue(result.std_z_10.iloc[:9].isna().all())
        self.assertFalse(result.ready_10.iloc[:9].any())
        self.assertTrue(result.ready_10.iloc[9:].all())
        self.assertEqual(result.ready_all.tolist(), [False] * 9 + [True] * 3)
        self.assertAlmostEqual(result.std_z_10.iloc[9], np.std(values[:10], ddof=0) / 2.)
        self.assertNotAlmostEqual(result.std_z_10.iloc[9], result.std_z_2.iloc[9])

    def test_future_values_and_other_sensor_cannot_change_past_features(self):
        base = self.multi_segment()
        changed = base.copy()
        changed.loc[changed.sensor_id.eq('b'), 'value'] += 1e6
        cutoff = pd.Timestamp('2026-01-07 01:04')
        changed.loc[changed.sensor_id.eq('a') & changed.timestamp.ge(cutoff), 'value'] -= 1e6
        original = add_features(base, 2, 10)
        altered = add_features(changed, 2, 10)
        fields, _ = numeric_fields(2, 10)
        past_a = base.sensor_id.eq('a') & base.timestamp.lt(cutoff)
        np.testing.assert_allclose(original.loc[past_a, fields], altered.loc[past_a, fields],
                                   rtol=1e-12, atol=1e-12, equal_nan=True)
        self.assertFalse(np.array_equal(original.value_z, altered.value_z))

    def test_sensor_split_and_gap_segments_restart_all_features(self):
        base = self.multi_segment()
        result = add_features(base, 2, 10)
        position = base.groupby('segment_id', sort=False).cumcount()
        self.assertEqual(base.segment_id.nunique(), 6)
        np.testing.assert_array_equal(result.ready_1step, position >= 1)
        np.testing.assert_array_equal(result.ready_2, position >= 1)
        np.testing.assert_array_equal(result.ready_10, position >= 9)
        self.assertTrue(result.loc[position.eq(0), ['delta_value_1', 'mean_value_2', 'change_value_2']].isna().all().all())
        self.assertTrue(result.loc[position.lt(9), 'std_z_10'].isna().all())
        np.testing.assert_array_equal(result.loc[position.eq(1), 'delta_value_1'], [2.] * 6)

    def test_three_eleven_numeric_features_match_existing_exporter(self):
        base = self.multi_segment()
        previous = add_three_sample_features(base, segment_column='segment_id')
        configurable = add_features(base, 3, 11)
        point_fields, _ = numeric_fields(3, 11)
        self.assertEqual(point_fields, POINT_FEATURES)
        for field in point_fields:
            with self.subTest(feature=field):
                np.testing.assert_allclose(configurable[field], previous[field],
                                           rtol=1e-10, atol=1e-10, equal_nan=True)
        for field in ['ready_1step', 'ready_3', 'ready_11', 'ready_all']:
            np.testing.assert_array_equal(configurable[field], previous[field])

    def test_leaking_fields_nonfinite_sources_and_invalid_scale_are_rejected(self):
        base = self.frame(np.arange(12.) + 100)
        for field in ['quality', 'status', 'alarms', 'anomaly_label', 'dataset_severity',
                      'nominal', 'warn_hi', 'crit_hi', 'warn_lo', 'crit_lo']:
            with self.subTest(field=field), self.assertRaises(ValueError):
                add_features(base.assign(**{field: 0}), 2, 10)
        for field in ['value', 'median', 'robust_scale']:
            for invalid in [np.nan, np.inf, -np.inf]:
                changed = base.copy()
                changed.loc[0, field] = invalid
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ValueError):
                    add_features(changed, 2, 10)
        for invalid in [0., -2.]:
            with self.subTest(scale=invalid), self.assertRaises(ValueError):
                add_features(base.assign(robust_scale=invalid), 2, 10)

    def test_invalid_segment_merges_are_rejected(self):
        base = self.multi_segment()
        for kind in ['sensor', 'split', 'gap']:
            changed = base.copy()
            if kind == 'sensor':
                changed.loc[changed.segment_id.isin(['a-train', 'b-train']), 'segment_id'] = 'merged'
            elif kind == 'split':
                changed.loc[changed.segment_id.isin(['a-train', 'a-validation']), 'segment_id'] = 'merged'
            else:
                changed.loc[changed.segment_id.isin(['a-validation', 'a-gap']), 'segment_id'] = 'merged'
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                add_features(changed, 2, 10)

    def test_feature_schema_distinguishes_observations_decisions_and_stuck_context(self):
        schema = feature_schema(2, 10, 2)
        self.assertEqual(schema['sampling_seconds'], 30)
        self.assertEqual(schema['decision_interval_seconds'], 60)
        self.assertEqual(schema['feature_computation_stride_samples'], 1)
        self.assertEqual(schema['mean_first_to_last_seconds'], 30)
        self.assertEqual(schema['stuck_first_to_last_seconds'], 270)
        self.assertEqual(schema['standard_deviation_ddof'], 0)
        self.assertIn('std_z_10', schema['point_numeric_features'])
        self.assertNotIn('std_z_10', schema['window_numeric_features'])
        self.assertNotIn('std_z_11', schema['point_numeric_features'])
        self.assertNotIn('mean_z_3', schema['point_numeric_features'])


if __name__ == '__main__':
    unittest.main()
