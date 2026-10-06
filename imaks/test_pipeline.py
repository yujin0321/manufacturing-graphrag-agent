import unittest
from unittest.mock import patch
import pandas as pd
import numpy as np
from imaks_pipeline import predictions_to_events, evaluate_events, available_history, fit_scores, truth_events


class PipelineTests(unittest.TestCase):
    def test_alarm_segments_split_at_gap_and_sensor(self):
        d=pd.DataFrame({'sensor_id':['a','a','a','b'], 'timestamp':pd.to_datetime([
            '2026-01-08 00:00:00','2026-01-08 00:00:30','2026-01-08 00:02:00','2026-01-08 00:02:00'])})
        p=predictions_to_events(d,[1,1,1,1])
        self.assertEqual(len(p),3)
        self.assertEqual(p.iloc[0]['rows'],2)

    def test_one_to_one_does_not_reward_fragmented_alarms(self):
        p=pd.DataFrame({'sensor_id':['a','a','a'], 'prediction_id':['P1','P2','P3'],
            'start':pd.to_datetime(['2026-01-08 00:01','2026-01-08 00:03','2026-01-08 01:00']),
            'end':pd.to_datetime(['2026-01-08 00:02','2026-01-08 00:04','2026-01-08 01:01'])})
        t=pd.DataFrame({'sensor_id':['a'],'event_id':['E1'],
            'start':pd.to_datetime(['2026-01-08 00:00']),'end':pd.to_datetime(['2026-01-08 00:05'])})
        m,_=evaluate_events(p,t)
        self.assertEqual(m['detected_events'],1)
        self.assertEqual(m['unmatched_alarm_events'],2)
        self.assertEqual(m['pure_false_alarm_events'],1)
        self.assertEqual(m['median_delay_min'],1.)

    def test_history_excludes_future_and_simultaneous_observations(self):
        records=[{'sensor_id':'a','observed_at':f'2026-01-08 {h}:00'} for h in ['07','08','09']]
        result=available_history(records,'2026-01-08 08:00',['a'])
        self.assertEqual(len(result),1)

    def test_trailing_features_cannot_read_future(self):
        times=pd.date_range('2026-01-06 23:50',periods=60,freq='30s')
        d=pd.DataFrame({'sensor_id':'a','timestamp':times,'value':10+np.sin(np.arange(60))})
        altered=d.copy(); altered.loc[40:,'value']=10000.
        with patch('imaks_pipeline.csv'):
            a=fit_scores(d); b=fit_scores(altered)
        pd.testing.assert_frame_equal(a.loc[:39,['z_abs','rolling_z','stuck_flag']],b.loc[:39,['z_abs','rolling_z','stuck_flag']])
        self.assertTrue(pd.isna(a.loc[20,'rolling_z'])) # reset at validation boundary

    def test_label_features_are_rejected(self):
        with self.assertRaises(AssertionError):
            fit_scores(pd.DataFrame({'anomaly_label':['NORMAL']}))

    def test_statistical_detector_rejects_raw_thresholds(self):
        d=pd.DataFrame({'sensor_id':'a', 'timestamp':pd.date_range('2026-01-06 06:00',periods=40,freq='30s'),
                        'value':np.r_[10+np.sin(np.arange(25)),np.repeat(10.,15)]})
        with_metadata=d.assign(nominal=100000.,warn_hi=-100.,crit_hi=-200.,warn_lo=100.,crit_lo=200.)
        with self.assertRaises(AssertionError):
            fit_scores(with_metadata)

    def test_quality_feature_is_rejected(self):
        with self.assertRaises(AssertionError):
            fit_scores(pd.DataFrame({'quality':['UNCERTAIN']}))

    def test_split_cannot_cut_event(self):
        nodes=pd.DataFrame([{'nodeId':'E','gtId':'GT','startTs':'2026-01-06 23:59','endTs':'2026-01-07 00:01','anomalyType':'DRIFT','label':'AnomalyEvent','name':None},
                            {'nodeId':'S','label':'Sensor','name':'sensor'}])
        edges=pd.DataFrame([{'fromId':'S','toId':'E','type':'triggers'}])
        with self.assertRaises(ValueError): truth_events(nodes,edges)

if __name__=='__main__': unittest.main()
