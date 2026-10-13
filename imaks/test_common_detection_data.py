"""Regression checks for keyed label alignment and the separate model inputs."""
import unittest
import pandas as pd
from common_detection_data import align_by_keys, load_common_detection_data, THRESHOLDS
from imaks_pipeline import fit_scores, rule_threshold_flags


class CommonInputTests(unittest.TestCase):
    def setUp(self):
        self.obs = pd.DataFrame({'sensor_id':['b','a'], 'timestamp':pd.to_datetime(['2026-01-08','2026-01-07'])},index=[7,3])
        self.labels = self.obs.reset_index(drop=True).assign(anomaly_label=['SPIKE','NORMAL'])

    def test_shuffled_labels_align_by_key_and_keep_observation_index(self):
        aligned = align_by_keys(self.obs, self.labels.iloc[::-1].reset_index(drop=True), ['anomaly_label'])
        self.assertEqual(aligned.index.tolist(),[7,3])
        self.assertEqual(aligned.anomaly_label.tolist(),['SPIKE','NORMAL'])

    def test_missing_label_fails_instead_of_becoming_normal(self):
        with self.assertRaises(ValueError):
            align_by_keys(self.obs,self.labels.iloc[:1],['anomaly_label'])

    def test_extra_label_fails(self):
        extra = self.labels.iloc[:1].assign(sensor_id='other')
        with self.assertRaises(ValueError):
            align_by_keys(self.obs,pd.concat([self.labels,extra]),['anomaly_label'])

    def test_duplicate_label_fails(self):
        with self.assertRaises(ValueError):
            align_by_keys(self.obs,pd.concat([self.labels,self.labels.iloc[:1]]),['anomaly_label'])

    def test_real_inputs_separate_rule_features_and_fit(self):
        data = load_common_detection_data()
        self.assertEqual(len(data.ml),211200)
        self.assertEqual(len(data.events),14)
        self.assertFalse(set(THRESHOLDS)&set(data.ml))
        self.assertTrue(set(THRESHOLDS)<=set(data.rule))
        self.assertNotIn('anomaly_label',data.ml)
        # A rule input cannot be accidentally accepted by the statistical model.
        with self.assertRaises(AssertionError):
            fit_scores(data.rule)
        self.assertEqual(data.labels.anomaly_label.ne('NORMAL').sum(),1460)

    def test_missing_preprocessing_never_falls_back_to_zip(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as path, self.assertRaises(FileNotFoundError):
            load_common_detection_data(path)

    def test_threshold_rule_uses_its_separate_limits(self):
        frame=pd.DataFrame({'value':[9.,10.,11.], 'warn_lo':[0.]*3,'warn_hi':[10.]*3})
        self.assertEqual(rule_threshold_flags(frame).tolist(),[False,False,True])


if __name__=='__main__': unittest.main()
