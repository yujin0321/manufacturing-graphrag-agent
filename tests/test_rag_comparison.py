import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from rdflib import Graph, Namespace, Literal
from imaks_kg.rag import comparison as c
from imaks_kg.rag import vector as v


class ComparisonTests(unittest.TestCase):
    def temporary(self):
        root=v.REPO_ROOT/'kg_build/comparison_tests';root.mkdir(parents=True,exist_ok=True)
        return tempfile.TemporaryDirectory(dir=root)

    def test_llm_has_no_retrieval_and_same_generation_settings(self):
        calls=[]
        def fake(resource,payload,cache):
            calls.append((resource,payload))
            return {'model':'gpt-6.1-sol','choices':[{'finish_reason':'stop','message':{'content':'synthetic'}}]},{}
        with self.temporary() as tmp, patch.object(c,'retrieve_graph',side_effect=AssertionError('no retrieval')),patch.object(v,'load_index',side_effect=AssertionError('no corpus')):
            result=c.answer('LLM','Synthetic question',Path(tmp)/'run',fake)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][0],'chat/completions')
        self.assertEqual(json.loads(calls[0][1]['messages'][1]['content'])['untrusted_reference_documents'],'')
        self.assertEqual(calls[0][1]['max_completion_tokens'],v.read(v.CONFIG)['max_completion_tokens'])
        self.assertEqual(result['context_tokens'],0)

    def test_real_kg_hash_and_source_mapping(self):
        g=c.load_graph();corpus,_,_=v.load_index(v.DEFAULT_INDEX)
        links=c.source_links(g,corpus)
        self.assertEqual(len(g),2806)
        self.assertTrue(any(links.values()))
        ids={r['chunk_id'] for r in corpus}
        self.assertTrue(all(set(cs)<=ids for cs in links.values()))

    def test_bounded_two_hop_walk(self):
        g=Graph();ns=Namespace('https://test/')
        for n in ['A','B','C','D']:g.add((ns[n],c.IM.identifier,Literal('NODE-'+n)))
        for a,b in [('A','B'),('B','C'),('C','D')]:g.add((ns[a],c.IM.feedsInto,ns[b]))
        r=c.graph_context('NODE-A',[],[],g,v.read(v.CONFIG))
        self.assertEqual(set(r['visited_nodes']),{str(ns.A),str(ns.B),str(ns.C)})
        self.assertTrue(r['graph_nodes'])
        self.assertLessEqual(r['context_tokens'],4000)
        self.assertNotIn(str(ns.D),r['visited_nodes'])

    def test_identifier_boundaries(self):
        g=Graph();n=Namespace('https://test/').A;g.add((n,c.IM.identifier,Literal('NODE-A')))
        self.assertEqual(c.graph_context('NODE-AB',[],[],g,v.read(v.CONFIG))['exact_identifier_nodes'],[])

    def test_graph_generation_uses_context_and_preserves_failure(self):
        def fake(resource,payload,cache):
            self.assertEqual(json.loads(payload['messages'][1]['content'])['untrusted_reference_documents'],'synthetic graph')
            return {'choices':[{'finish_reason':'length','message':{'content':'partial'}}]},{}
        with self.temporary() as tmp,patch.object(c,'retrieve_graph',return_value={'context':'synthetic graph','context_tokens':3,'selected_ids':[]}):
            run=Path(tmp)/'run'
            with self.assertRaises(ValueError):c.answer('GraphRAG','Synthetic',run,fake)
            self.assertTrue((run/'failure.json').exists());self.assertFalse((run/'answer.json').exists())

    def test_whole_card_and_document_budget(self):
        g=Graph();ns=Namespace('https://test/');g.add((ns.A,c.IM.identifier,Literal('NODE-A')))
        cfg={**v.read(v.CONFIG),'context_token_budget':20}
        # An empty graph selection isolates whole-document budget enforcement.
        hit={'chunk_id':'test','doc_id':'test','page':1,'text':'word '*100,'table_id':None,'source_file_sha256':'x'}
        r=c.graph_context('no entity',[hit],[hit],Graph(),cfg)
        self.assertEqual(r['selected_ids'],[]);self.assertEqual(r['skipped_for_budget'],['test'])


if __name__=='__main__':unittest.main()
