import json
import tempfile
import unittest
from pathlib import Path
from imaks_kg.rag import event_explain as x, vector as v


class EventTests(unittest.TestCase):
    def event(self,rule):
        return next(e for e in v.read(x.OUT/'events.json') if e['rule_id']==rule)['id']

    def test_duration_provenance_and_exact_payload(self):
        calls=[]
        def fake(resource,payload,cache):
            calls.append((resource,payload))
            return {'model':payload['model'],'choices':[{'finish_reason':'stop','message':{'content':'mock'}}]},{}
        root=v.REPO_ROOT/'kg_build/live_tests';root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as tmp:
            run=Path(tmp)/'event'
            x.answer(self.event('MAINT-05:main'),run,fake)
            r=v.read(run/'retrieval.json');p=json.loads(calls[0][1]['messages'][1]['content'])
            self.assertEqual(p['evidence'],r['context'])
            self.assertEqual(len(calls),1);self.assertEqual(calls[0][0],'chat/completions')
            self.assertIn('SOP-003:p1:table1:chunk',r['selected_ids'])
            self.assertEqual(r['context']['executable_rule']['duration_seconds'],300)
            self.assertTrue(any(e['p']==str(x.EX.existingRule) for e in r['traversed_edges']))
            self.assertNotIn('anomaly_label',json.dumps(p))
            self.assertFalse(v.read(run/'run_lock.json')['gold_loaded'])

    def test_metadata_does_not_invent_document_source(self):
        _,sources,r,_,_=x.prepare(self.event('METADATA_WARN:ST02_SEALING_TMP'))
        self.assertEqual(sources,[]);self.assertEqual(r['selected_ids'],[])

    def test_unknown_event_rejected_before_api(self):
        with self.assertRaises(ValueError):x.answer('../../fake',Path('unused'),lambda *a:self.fail('API called'))


if __name__=='__main__':unittest.main()
