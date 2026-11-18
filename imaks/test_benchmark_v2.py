import json,unittest
from prepare_benchmark_v2 import ROOT,OUT,eligible,graph_paths,pack_context,load_corpus

class BenchmarkV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.docs,cls.graph=load_corpus()

    def test_future_alerts_excluded(self):
        case={'as_of':'2026-01-09 10:50:00','lookback_min':15}
        got={d['source_id'] for d in self.docs if d['kind']=='predicted_alert' and eligible(d,case)}
        self.assertEqual(got,{'E_P00007','E_P00008'})

    def test_pre_alert_window_empty(self):
        case={'as_of':'2026-01-08 09:10:00','lookback_min':30}
        self.assertFalse(any(d['kind']=='predicted_alert' and eligible(d,case) for d in self.docs))

    def test_graph_can_follow_three_process_links(self):
        ids,_=graph_paths(self.graph,'ST01_FILLING_FLW',3)
        byid={d['source_id']:d for d in self.docs}
        edges=[byid[s]['edge'] for s in ids if byid[s]['edge']['relation']=='feeds_into']
        self.assertEqual(len(edges),3)
        self.assertTrue(any(e['target_name']=='ST04_PACKAGING' for e in edges))

    def test_common_budget_and_no_oracle(self):
        import tiktoken
        encoding=tiktoken.get_encoding('cl100k_base')
        contexts=json.loads((OUT/'prepared_contexts.json').read_text(encoding='utf-8'))
        for p in contexts:
            count=len(encoding.encode(json.dumps(p['context'],ensure_ascii=False,separators=(',',':'))))
            self.assertLessEqual(count,1800)
            self.assertNotIn('causedBy',json.dumps(p))
            self.assertNotIn('anomaly_label',json.dumps(p))
            for r in p['context']['graph_paths']+p['context']['sources']:
                self.assertIn(r['source_id'],{d['source_id'] for d in self.docs})

    def test_gold_never_in_generator_input(self):
        requests=[json.loads(s) for s in (OUT/'generation_requests.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(requests),90)
        keys={(r['id'],r['mode'],r['repeat']) for r in requests}
        self.assertEqual(len(keys),90)
        for r in requests:
            p=json.loads(r['messages'][1]['content'])
            self.assertNotIn('expected',p);self.assertNotIn('gold',p)

if __name__=='__main__':unittest.main()
