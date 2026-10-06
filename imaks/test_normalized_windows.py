import unittest
import numpy as np
import pandas as pd
from build_normalized_windows import normalize_observations, make_windows


class WindowTests(unittest.TestCase):
    def frame(self, times, values, sensor='a'):
        return pd.DataFrame({'sensor_id':sensor,'timestamp':pd.to_datetime(times),'value':values})

    def test_test_values_cannot_change_training_parameters_or_past_windows(self):
        train = self.frame(pd.date_range('2026-01-06 06:00',periods=20,freq='30s'),np.arange(20.))
        later = self.frame(pd.date_range('2026-01-08 06:00',periods=20,freq='30s'),np.arange(20.))
        original = pd.concat([train,later],ignore_index=True)
        changed = original.copy(); changed.loc[20:,'value'] = 100000.
        a, pa=normalize_observations(original); b, pb=normalize_observations(changed)
        pd.testing.assert_frame_equal(pa,pb)
        xa,ia,_=make_windows(a,10); xb,ib,_=make_windows(b,10)
        self.assertTrue(np.array_equal(xa[ia['split'].eq('train')],xb[ib['split'].eq('train')]))

    def test_future_validation_value_does_not_change_earlier_window(self):
        frame=self.frame(pd.date_range('2026-01-06 23:50',periods=60,freq='30s'),np.arange(60.))
        changed=frame.copy(); changed.loc[50:,'value']=99999.
        a,_=normalize_observations(frame); b,_=normalize_observations(changed)
        xa,ia,_=make_windows(a,11); xb,ib,_=make_windows(b,11)
        before=ia.timestamp.lt(frame.loc[50,'timestamp'])
        np.testing.assert_array_equal(xa[before],xb[before])

    def test_split_and_gap_restart_full_windows(self):
        train=self.frame(pd.date_range('2026-01-06 23:54:30',periods=11,freq='30s'),np.arange(11.))
        val=self.frame(pd.date_range('2026-01-07 00:00',periods=11,freq='30s'),np.arange(11.))
        gap=self.frame(pd.date_range('2026-01-07 01:00',periods=11,freq='30s'),np.arange(11.))
        normalized,_=normalize_observations(pd.concat([train,val,gap],ignore_index=True))
        x,index,_=make_windows(normalized,11)
        self.assertEqual(x.shape,(3,11))
        self.assertEqual(index.segment_id.nunique(),3)
        self.assertEqual(index.timestamp.tolist(),[train.timestamp.iloc[-1],val.timestamp.iloc[-1],gap.timestamp.iloc[-1]])

    def test_sensors_never_mix_and_signed_values_are_retained(self):
        a=self.frame(pd.date_range('2026-01-06 06:00',periods=12,freq='30s'),np.arange(12.),'a')
        b=self.frame(pd.date_range('2026-01-06 06:00',periods=12,freq='30s'),np.arange(12.)+10000.,'b')
        normalized,params=normalize_observations(pd.concat([a,b]).sample(frac=1,random_state=4))
        x,index,_=make_windows(normalized,10)
        self.assertEqual(x.shape,(6,10))
        np.testing.assert_array_equal(x[:3],x[3:])
        self.assertTrue((normalized.value_z<0).any() and (normalized.value_z>0).any())
        lookup=params.set_index('sensor_id')
        restored=normalized.value_z*normalized.sensor_id.map(lookup.robust_scale)+normalized.sensor_id.map(lookup['median'])
        np.testing.assert_allclose(restored,normalized.value)

    def test_constant_training_uses_recorded_scale_floor(self):
        frame=self.frame(pd.date_range('2026-01-06 06:00',periods=12,freq='30s'),[0.]*12)
        normalized,params=normalize_observations(frame)
        self.assertTrue(params.scale_floor_used.iloc[0])
        self.assertEqual(params.robust_scale.iloc[0],1e-8)
        self.assertTrue(np.isfinite(normalized.value_z).all())

    def test_missing_train_sensor_and_leaking_fields_are_rejected(self):
        frame=self.frame(pd.date_range('2026-01-08 06:00',periods=12,freq='30s'),np.arange(12.))
        with self.assertRaises(ValueError):normalize_observations(frame)
        frame['timestamp']=pd.date_range('2026-01-06 06:00',periods=12,freq='30s')
        for field in ['anomaly_label','quality','nominal','warn_hi']:
            with self.subTest(field=field), self.assertRaises(ValueError):normalize_observations(frame.assign(**{field:0}))

    def test_short_segments_are_not_padded(self):
        frame=self.frame(pd.date_range('2026-01-06 06:00',periods=9,freq='30s'),np.arange(9.))
        normalized,_=normalize_observations(frame)
        x,index,features=make_windows(normalized,10)
        self.assertEqual(x.shape,(0,10)); self.assertEqual(len(index),0);self.assertEqual(len(features),0)


if __name__=='__main__':unittest.main()
