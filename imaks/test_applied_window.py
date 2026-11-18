import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import imaks_pipeline as pipeline
from sweep_window_sizes import make_base, score_window


CONFIG = {'model':'robust_causal','instant_k':6.,'rolling_k':4.,'mean_window_samples':3,
          'stuck_window_samples':11,'sampling_seconds':30,'stride_samples':1}


class AppliedWindowTests(unittest.TestCase):
    def observations(self):
        pieces = []
        for day in [6, 7, 8]:
            pieces.append(pd.DataFrame({'sensor_id':'a','station_id':'station',
                'timestamp':pd.date_range(f'2026-01-{day:02d} 06:00',periods=30,freq='30s'),
                'value':10+np.sin(np.arange(30))+(0 if day == 6 else 20)}))
        return pd.concat(pieces,ignore_index=True)

    def test_default_three_and_explicit_ten_match_sweep_features(self):
        raw = self.observations()
        base, _ = make_base(raw)
        with patch('imaks_pipeline.csv'):
            default = pipeline.fit_scores(raw)
            baseline = pipeline.fit_scores(raw, mean_window_samples=10)
        self.assertEqual(default.attrs['window_config']['mean_window_samples'], 3)
        for scored, size in [(default, 3), (baseline, 10)]:
            swept = score_window(base, size)
            np.testing.assert_allclose(scored.rolling_z, swept.rolling_z, equal_nan=True)
            np.testing.assert_allclose(scored.z_abs, swept.z_abs)
            np.testing.assert_array_equal(scored.stuck_flag, swept.stuck_flag)
        np.testing.assert_array_equal(default.stuck_flag, baseline.stuck_flag)

    def test_direct_fitting_does_not_rewrite_previous_outputs(self):
        with patch('imaks_pipeline.csv') as writer:
            pipeline.fit_scores(self.observations())
        writer.assert_not_called()

    def test_frozen_config_does_not_change_when_validation_labels_change(self):
        raw = self.observations()
        with patch('imaks_pipeline.csv'):
            scored = pipeline.fit_scores(raw)
        labels = raw[['sensor_id','timestamp']].assign(anomaly_label='NORMAL')
        changed = labels.copy()
        changed.loc[scored['split'].eq('validation'),'anomaly_label'] = 'SPIKE'
        truth = pd.DataFrame([{'event_id':split,'sensor_id':'a','start':group.timestamp.min(),
                               'end':group.timestamp.max(),'split':split}
                              for split, group in scored.groupby('split')])
        rule = raw.assign(nominal=10., warn_hi=50., crit_hi=100., warn_lo=0., crit_lo=-10.)
        with patch('imaks_pipeline.csv') as written, patch('imaks_pipeline.write_json'), \
                patch.object(pd.DataFrame,'to_csv'), patch('matplotlib.figure.Figure.savefig'):
            before, _, _ = pipeline.run_detection(scored,labels,truth,rule,CONFIG)
            after, _, _ = pipeline.run_detection(scored,changed,truth,rule,CONFIG)
        self.assertEqual(before, CONFIG)
        self.assertEqual(after, CONFIG)
        self.assertNotIn('validation_selection.csv', [call.args[1] for call in written.call_args_list])

    def test_config_and_computed_window_mismatch_is_rejected(self):
        with patch('imaks_pipeline.csv'):
            scored = pipeline.fit_scores(self.observations(), mean_window_samples=10)
        with self.assertRaisesRegex(ValueError,'Scored windows differ'):
            pipeline.run_detection(scored,pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),CONFIG)

    def test_applied_config_matches_frozen_selection(self):
        config, source = pipeline.load_applied_config()
        self.assertEqual(config, CONFIG)
        self.assertFalse(source['retuned_on_application'])
        with self.assertRaisesRegex(ValueError,'Current input differs'):
            pipeline.load_applied_config({'manifest_sha256':'changed'})


if __name__ == '__main__':
    unittest.main()
