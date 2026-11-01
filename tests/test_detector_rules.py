import unittest
from datetime import datetime,timedelta
from imaks_kg.detection.rules import evaluate_rule


class RuleTests(unittest.TestCase):
    def rows(self,values,start='2026-01-06T12:00:00'):
        t=datetime.fromisoformat(start)
        return [{'timestamp':(t+timedelta(seconds=i*30)).isoformat(),'value':str(v),'unit':'A','sensor_id':'S'} for i,v in enumerate(values)]
    def rule(self,**kw):
        return dict({'id':'R','kind':'document_rule','unit':'A','op':'gt','value':'13.9','duration_seconds':0},**kw)
    def test_exact_decimal_boundary(self):
        self.assertEqual(evaluate_rule(self.rows(['13.9']),self.rule()),[])
        self.assertEqual(len(evaluate_rule(self.rows(['13.9001']),self.rule())),1)
    def test_duration_is_strict_and_not_sample_count(self):
        rule=self.rule(duration_seconds=300)
        self.assertEqual(evaluate_rule(self.rows([14]*11),rule),[])
        es=evaluate_rule(self.rows([14]*12),rule)
        self.assertEqual(es[0]['trigger_at'],'2026-01-06T12:05:30')
        self.assertEqual(es[0]['condition_start'],'2026-01-06T12:00:00')
    def test_gap_and_normal_sample_reset(self):
        rule=self.rule(duration_seconds=300)
        rows=self.rows([14]*12);rows[6:]=self.rows([14]*6,'2026-01-06T13:00:00')
        self.assertEqual(evaluate_rule(rows,rule),[])
        self.assertEqual(evaluate_rule(self.rows([14]*6+[13]+[14]*6),rule),[])
    def test_split_reset(self):
        self.assertEqual(evaluate_rule(self.rows([14]*12,'2026-01-06T23:57:00'),self.rule(duration_seconds=300)),[])
    def test_stuck_requires_eleven_samples(self):
        rule=self.rule(op='stuck_exact',value='11')
        self.assertEqual(evaluate_rule(self.rows([2]*10),rule),[])
        es=evaluate_rule(self.rows([2]*11),rule)
        self.assertEqual(es[0]['trigger_at'],'2026-01-06T12:05:00')
        self.assertEqual(es[0]['condition_start'],'2026-01-06T12:00:00')
    def test_bad_unit_and_nonfinite_rejected(self):
        rows=self.rows([14]);rows[0]['unit']='bar'
        with self.assertRaises(ValueError):evaluate_rule(rows,self.rule())
        with self.assertRaises(ValueError):evaluate_rule(self.rows(['NaN']),self.rule())
    def test_future_does_not_change_trigger(self):
        early=evaluate_rule(self.rows([14]*12),self.rule(duration_seconds=300))[0]
        later=evaluate_rule(self.rows([14]*20+[12]),self.rule(duration_seconds=300))[0]
        self.assertEqual(early['trigger_at'],later['trigger_at'])
        self.assertEqual(early['trigger_value'],later['trigger_value'])


if __name__=='__main__':unittest.main()
