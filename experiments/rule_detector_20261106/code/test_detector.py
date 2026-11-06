import unittest,tempfile,csv,json
from pathlib import Path
from datetime import datetime,timedelta
import detector as d
from evaluate import metrics,maximum_match

TEMP_ROOT=Path(__file__).resolve().parent.parent/'test_scratch'
TEMP_ROOT.mkdir(exist_ok=True)

def rows(values,step=30):
    return [{'timestamp':(datetime(2026,1,1)+timedelta(seconds=i*step)).isoformat(),
             'sensor_id':'S','station_id':'ST','unit':'C','value':str(v)} for i,v in enumerate(values)]
def rule(**kw):return dict(rule_id='R',sensor_id='S',unit='C',kind='test',op='gt',value='25',second=None,duration_seconds=0,**kw)

class DetectorTests(unittest.TestCase):
    def test_single_outlier_rejected(self):self.assertEqual(d.scan(rows([24,26,24,24]),rule()),[])
    def test_two_points_confirm(self):self.assertEqual(d.scan(rows([26,26]),rule())[0]['trigger_at'],rows([26,26])[1]['timestamp'])
    def test_equality_not_violation(self):self.assertEqual(d.scan(rows([25,25]),rule()),[])
    def test_two_normals_clear(self):
        e=d.scan(rows([26,26,24,24]),rule());self.assertEqual(len(e),1);self.assertEqual(e[0]['normal_confirmed_at'],rows([0]*4)[3]['timestamp'])
    def test_one_normal_does_not_clear(self):
        e=d.scan(rows([26,26,24,26,24,24]),rule());self.assertEqual(len(e),1);self.assertEqual(e[0]['nonqualifying_observations'],3)
    def test_end_of_file_not_recovery(self):self.assertEqual(d.scan(rows([26,26,24]),rule())[0]['status'],'open_at_data_end')
    def test_gap_resets_confirmation(self):self.assertEqual(d.scan(rows([26,26],60),rule()),[])
    def test_gap_truncates_not_recovers(self):
        r=rows([26]*4);r[2]['timestamp']='2026-01-01T00:02:00';r[3]['timestamp']='2026-01-01T00:02:30'
        e=d.scan(r,rule());self.assertEqual(len(e),2);self.assertEqual(e[0]['status'],'data_gap_unconfirmed')
    def test_missing_value(self):
        r=rows([26,26,'NaN',26,26]);e=d.scan(r,rule());self.assertEqual(len(e),2);self.assertEqual(e[0]['status'],'data_gap_unconfirmed')
    def test_duration_strict_and_two_qualified(self):
        r=rule();r['duration_seconds']=300
        self.assertEqual(d.scan(rows([26]*12),r),[])
        self.assertEqual(d.scan(rows([26]*13),r)[0]['trigger_at'],'2026-01-01T00:06:00')
    def test_duration_interruption_resets(self):
        r=rule();r['duration_seconds']=300;self.assertEqual(d.scan(rows([26]*7+[24]+[26]*7),r),[])
    def test_stuck_two_fully_qualified(self):
        r=rule();r.update(op='stuck_exact',value='11')
        self.assertEqual(d.scan(rows([5]*11),r),[]);self.assertEqual(len(d.scan(rows([5]*12),r)),1)
    def test_outside_endpoints(self):
        r=rule();r.update(op='outside',value='10',second='20');self.assertEqual(d.scan(rows([10,20,10,20]),r),[])
    def test_lower_limit(self):
        r=rule();r.update(op='lt');self.assertEqual(len(d.scan(rows([24,24]),r)),1)
    def test_drift_no_early_warmup(self):
        r=rule(window_seconds=60);r.update(op='delta_gt',value='0.05');self.assertEqual(d.scan(rows([0,0.1,0.2]),r),[])
    def test_drift_exact_threshold(self):
        r=rule(window_seconds=60);r.update(op='delta_gt',value='0.05');self.assertEqual(d.scan(rows([0,0,0.05,0.05]),r),[])
    def test_drift_delta(self):
        r=rule(window_seconds=60);r.update(op='delta_gt',value='0.05');e=d.scan(rows([0,0,0.06,0.06]),r)
        self.assertEqual(e[0]['feature_value'],'0.06');self.assertEqual(e[0]['baseline_at'],'2026-01-01T00:00:30')
    def test_decrease_not_positive_drift(self):
        r=rule(window_seconds=60);r.update(op='delta_gt',value='0.05');self.assertEqual(d.scan(rows([1,1,0,0]),r),[])
    def test_drift_gap_requires_new_window(self):
        r=rule(window_seconds=60);r.update(op='delta_gt',value='0.05');self.assertEqual(d.scan(rows([0,1,2,3],60),r),[])
    def test_unit_mismatch(self):
        r=rows([26,26]);r[1]['unit']='K'
        with self.assertRaises(ValueError):d.scan(r,rule())
    def test_no_future_changes_past_alarm(self):
        a=d.scan(rows([26]*4),rule())[0];b=d.scan(rows([26]*4+[100,100,24,24]),rule())[0]
        for k in ['trigger_at','trigger_value','condition_start']:self.assertEqual(a[k],b[k])
    def test_unknown_needs_expert_and_is_not_discovery(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as td:
            p=Path(td)/'x.json';d.write(p,[dict(sensor_id='X',start='2026-01-01',end='2026-01-02',origin='external',evidence='reviewed candidate')])
            e=d.external_candidates(p,[rule()])[0];self.assertTrue(e['expert_review_required']);self.assertFalse(e['automatically_discovered'])
    def test_no_external_input_no_unknown_events(self):self.assertEqual(d.external_candidates(None,[rule()]),[])
    def test_duplicate_input_rejected(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as td:
            p=Path(td)/'x.csv'
            with p.open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=d.FIELDS);w.writeheader();x={k:'' for k in d.FIELDS};x.update(timestamp='2026-01-01',sensor_id='S',value='1');w.writerow(x);w.writerow(x)
            with self.assertRaises(ValueError):d.read_observations(p)
    def test_gold_fields_rejected(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as td:
            p=Path(td)/'x.csv';p.write_text(','.join(d.FIELDS+['anomaly_label'])+'\n')
            with self.assertRaises(ValueError):d.read_observations(p)
    def test_sample_count_not_time(self):
        r=rows([1,1,1]);self.assertEqual((datetime.fromisoformat(r[-1]['timestamp'])-datetime.fromisoformat(r[0]['timestamp'])).total_seconds(),60)
    def test_early_alarm_not_new_detection(self):
        e=[dict(sensor_id='S',rule_id='R',trigger_at='2026-01-01T00:00:00',last_positive_at='2026-01-01T00:10:00')]
        g=[dict(sensor_id='S',label='X',start='2026-01-01T00:05:00',end='2026-01-01T00:08:00')]
        m=metrics(e,g);self.assertEqual(m['events_covered'],1);self.assertEqual(m['events_with_new_alarm'],0);self.assertEqual(m['preexisting_alarm_events'],1)
    def test_multiple_rules_do_not_inflate_event_tp(self):
        e=[dict(sensor_id='S',rule_id=r,trigger_at='2026-01-01T00:00:00',last_positive_at='2026-01-01T00:10:00') for r in ['A','B']]
        g=[dict(sensor_id='S',label='X',start='2026-01-01T00:00:00',end='2026-01-01T00:08:00')]
        m=metrics(e,g);self.assertEqual(m['one_to_one_TP'],1);self.assertEqual(m['merged_episode_count'],1)

if __name__=='__main__':unittest.main(verbosity=2)
