import unittest
from rdflib import Graph,Literal,URIRef,RDF
from imaks_kg.rag import retrieval_v5 as r, comparison as c

class ProvenanceTests(unittest.TestCase):
    def test_valid_syntax_but_wrong_quote_hash_is_rejected(self):
        g=Graph();n=URIRef('urn:rule');p=URIRef('urn:prov')
        for pred,val in [(c.IM.sourceKind,'document'),(c.IM.sourceQuote,'correct quote'),
                         (c.IM.fileSha256,'file'),(c.IM.textSha256,'0'*64)]:g.add((p,pred,Literal(val)))
        g.add((n,c.IM.hasProvenance,p))
        links,audit=r.validated_provenance(g,[{'chunk_id':'row','text':'correct quote','source_file_sha256':'file'}])
        self.assertEqual(links[str(n)],[])
        self.assertFalse(audit[0]['quote_hash_valid'])

    def test_same_table_wrong_row_does_not_match(self):
        import hashlib
        g=Graph();n=URIRef('urn:rule');p=URIRef('urn:prov');quote='Sensor: TMP; Limit: 10'
        for pred,val in [(c.IM.sourceKind,'document'),(c.IM.sourceQuote,quote),
                         (c.IM.fileSha256,'file'),(c.IM.textSha256,hashlib.sha256(quote.encode()).hexdigest())]:g.add((p,pred,Literal(val)))
        g.add((n,c.IM.hasProvenance,p))
        rows=[{'chunk_id':'good','text':'Header\n'+quote,'source_file_sha256':'file'},
              {'chunk_id':'wrong','text':'Sensor: CUR; Limit: 10','source_file_sha256':'file'},
              {'chunk_id':'foreign','text':quote,'source_file_sha256':'other'}]
        links,_=r.validated_provenance(g,rows)
        self.assertEqual(links[str(n)],['good'])

class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.engine=r.Engine(c.load_graph());cls.ids=[x['chunk_id'] for x in cls.engine.rows]

    def test_specific_sensor_does_not_pull_unrelated_direct_rules(self):
        plan=self.engine.plan('ST02_SEALING_CUR에 적용되는 규칙')
        self.assertTrue(plan['direct_rules'])
        self.assertTrue(all('CUR' in s for s in plan['sensors']))

    def test_cross_rule_reference_is_logged_not_promoted_to_causality(self):
        plan=self.engine.plan('RULE-ST04-03의 확인 규칙과 근거')
        self.assertIn('SOP-001:p1:RULE-ST02-04',plan['reference_rows'])
        self.assertTrue(any(e['kind']=='source_text_reference_not_causal_edge' for e in plan['edges']))

    def test_no_graph_baseline_does_not_need_kg(self):
        baseline=r.Engine()
        result=baseline.retrieve('실링 전류',self.ids,'HybridRAG',900)
        self.assertFalse(result['trace']['graph_used'])
        self.assertLessEqual(result['context_tokens'],900)

    def test_direction_is_preserved(self):
        plan=self.engine.plan('ST02_SEALING_CUR에 적용되는 규칙')
        for edge in plan['edges']:
            if edge.get('p')=='appliesToSensor':
                self.assertIn((URIRef(edge['s']),c.IM.appliesToSensor,URIRef(edge['o'])),self.engine.graph)

    def test_source_only_and_small_budget(self):
        result=self.engine.retrieve('서버실 온도 기준',self.ids,'GraphRAG',700)
        self.assertLessEqual(result['context_tokens'],700)
        self.assertNotIn('[KG entity]',result['context'])
        self.assertTrue(all(cid in self.ids for cid in result['selected_ids']))

if __name__=='__main__':unittest.main()
