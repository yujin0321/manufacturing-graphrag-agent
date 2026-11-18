import unittest

import numpy as np
import pandas as pd

from build_normalized_windows import normalize_observations
from causal_features import ONE_STEP_FEATURES, POINT_FEATURES, THREE_SAMPLE_FEATURES, add_three_sample_features, feature_table
from imaks_pipeline import detector_flags


class CausalFeatureTests(unittest.TestCase):
    def fixed_frame(self, values):
        return pd.DataFrame({'sensor_id':'a','timestamp':pd.date_range('2026-01-06 06:00',periods=len(values),freq='30s'),
                             'value':values,'median':0.,'robust_scale':1.,'split':'train','_segment':1})

    def test_hand_calculated_statistics_and_actual_elapsed_time_rates(self):
        result = add_three_sample_features(self.fixed_frame([1.,4.,2.]))
        last = result.iloc[-1]
        self.assertAlmostEqual(last.mean_value_3,7/3)
        self.assertAlmostEqual(last.std_value_3,np.sqrt(14)/3)
        self.assertEqual(last.min_value_3,1.)
        self.assertEqual(last.max_value_3,4.)
        self.assertEqual(last.range_value_3,3.)
        self.assertEqual(last.change_value_3,1.)
        self.assertEqual(last.rate_value_3_per_min,1.)  # first->last is 60 s, not nominal 90 s
        self.assertEqual(last.delta_value_1,-2.)
        self.assertEqual(last.rate_value_1_per_min,-4.)
        self.assertEqual(last.change_z_3,1.)
        self.assertEqual(last.delta_z_1,-2.)
        self.assertTrue(result.loc[:1,THREE_SAMPLE_FEATURES].isna().all().all())
        self.assertTrue(result.loc[:0,ONE_STEP_FEATURES].isna().all().all())

    def test_sensor_split_and_gap_segments_reset_differences(self):
        first = self.fixed_frame([1.,4.,2.])
        second = first.assign(timestamp=first.timestamp+pd.Timedelta(days=1),split='validation',_segment=2)
        gap = second.assign(timestamp=second.timestamp+pd.Timedelta(hours=2),_segment=3)
        other = first.assign(sensor_id='b',value=[101.,104.,102.],_segment=4)
        frame = pd.concat([first,second,gap,other],ignore_index=True)
        result = add_three_sample_features(frame)
        for start in [0,3,6,9]:
            self.assertTrue(result.loc[[start],ONE_STEP_FEATURES].isna().all().all())
            self.assertTrue(result.loc[start:start+1,THREE_SAMPLE_FEATURES].isna().all().all())
            self.assertEqual(result.loc[start+2,'change_value_3'],1.)
        self.assertEqual(len(result),len(frame))

    def test_future_values_cannot_change_train_fit_or_earlier_features(self):
        pieces = []
        for day in [6,7,8]:
            pieces.append(pd.DataFrame({'sensor_id':'a','timestamp':pd.date_range(f'2026-01-{day:02d} 06:00',periods=30,freq='30s'),
                                       'value':10+np.sin(np.arange(30))}))
        raw = pd.concat(pieces,ignore_index=True)
        changed = raw.copy()
        changed.loc[50:,'value'] = 99999.
        a,pa = normalize_observations(raw)
        b,pb = normalize_observations(changed)
        pd.testing.assert_frame_equal(pa,pb)
        outputs = []
        for normalized,params in [(a,pa),(b,pb)]:
            fitted = normalized.merge(params[['sensor_id','median','robust_scale']],on='sensor_id',validate='many_to_one')
            outputs.append(add_three_sample_features(fitted,segment_column='segment_id'))
        pd.testing.assert_frame_equal(outputs[0].loc[:49,POINT_FEATURES],outputs[1].loc[:49,POINT_FEATURES])

    def test_short_segments_are_retained_without_padding(self):
        result = add_three_sample_features(self.fixed_frame([1.,2.]))
        self.assertEqual(len(result),2)
        self.assertFalse(result.ready_3.any())
        self.assertFalse(result.ready_11.any())
        self.assertTrue(result[THREE_SAMPLE_FEATURES].isna().all().all())
        self.assertEqual(result.delta_value_1.iloc[1],1.)
        self.assertTrue(result.std_z_11.isna().all())

    def test_labels_thresholds_and_alarm_metadata_are_rejected(self):
        for field in ['anomaly_label','quality','nominal','warn_hi','status','alarms']:
            with self.subTest(field=field),self.assertRaises(ValueError):
                add_three_sample_features(self.fixed_frame([1.,4.,2.]).assign(**{field:0}))

    def test_malformed_segments_are_rejected(self):
        frame = self.fixed_frame([1.,4.,2.])
        gap = frame.copy(); gap.loc[2,'timestamp'] += pd.Timedelta(hours=1)
        split = frame.copy(); split.loc[2,'split'] = 'validation'
        sensor = frame.copy(); sensor.loc[2,'sensor_id'] = 'b'
        for malformed in [gap,split,sensor]:
            with self.assertRaises(ValueError): add_three_sample_features(malformed)

    def test_export_allowlist_and_original_detector_flags(self):
        frame = self.fixed_frame(np.r_[np.arange(15.),np.repeat(10.,15)])
        frame['z_abs'] = frame.value.abs()
        frame['rolling_z'] = frame.value.rolling(3,min_periods=3).mean().abs()
        frame['stuck_flag'] = frame.value.rolling(11,min_periods=11).std(ddof=0).eq(0)
        cfg = {'model':'robust_causal','instant_k':6.,'rolling_k':4.}
        before = detector_flags(frame,cfg)
        enriched = add_three_sample_features(frame)
        np.testing.assert_array_equal(before,detector_flags(enriched,cfg))
        enriched['predicted_anomaly'] = before
        enriched['unrelated_numeric_column'] = 42.
        exported = feature_table(enriched)
        self.assertNotIn('predicted_anomaly',exported)
        self.assertNotIn('unrelated_numeric_column',exported)
        self.assertNotIn('median',exported)
        self.assertNotIn('robust_scale',exported)
        self.assertFalse(enriched.ready_11.iloc[:10].any())
        self.assertTrue(enriched.ready_11.iloc[10:].all())


if __name__=='__main__':
    unittest.main()
