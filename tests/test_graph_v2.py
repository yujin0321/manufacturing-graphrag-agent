import unittest
from unittest.mock import patch
from rdflib import Graph,Namespace,Literal
from imaks_kg.rag import graph_v2 as m,vector as v,comparison as c


def fixture():
    ns=Namespace('https://test/');g=Graph();corpus=[]
    for i,doc in enumerate(['DOC-101','DOC-202']):
        cid=doc+':table';text=f'Rule ID: MAINT-{i+81}; Action: synthetic action'
        corpus.append({'chunk_id':cid,'doc_id':doc,'page':1,'section':None,'table_id':cid,'source_file_sha256':doc,'text':text})
        node=ns[f'r{i}'];prov=ns[f'p{i}']
        g.add((node,c.IM.identifier,Literal(f'candidate-{doc}::MAINT-{i+81}')))
        g.add((node,c.IM.hasProvenance,prov));g.add((prov,c.IM.sourceKind,Literal('document')))
        g.add((prov,c.IM.fileSha256,Literal(doc)));g.add((prov,c.IM.tableId,Literal(cid)))
    g.add((ns.r0,c.IM.responseText,Literal('Verify MAINT-82.')))
    return g,corpus


class GraphV2Tests(unittest.TestCase):
    def test_korean_particle_and_longer_identifiers(self):
        self.assertTrue(m.matches('MAINT-81','MAINT-81의 조건'))
        self.assertTrue(m.matches('DOC-101','DOC-101과 DOC-202를 비교'))
        for text in ['XMAINT-81','MAINT-810','MAINT-81-A','MAINT-81_extra']:
            self.assertFalse(m.matches('MAINT-81',text))

    def test_alias_and_provenance_survive_no_card_budget(self):
        g,rows=fixture();cfg={**v.read(m.POLICY_PATH),'max_graph_tokens':0}
        r=m.context('MAINT-81의 조치',rows,list(reversed(rows)),g,cfg)
        self.assertTrue(r['exact_identifier_nodes'])
        self.assertEqual(r['selected_ids'][0],'DOC-101:table')
        self.assertEqual(r['graph_nodes'],[])

    def test_cross_document_coverage(self):
        g,rows=fixture();r=m.context('DOC-101과 DOC-202를 비교',rows,rows,g)
        self.assertEqual(r['uncovered_explicit_documents'],[])
        self.assertEqual(r['explicit_documents'],['DOC-101','DOC-202'])

    def test_reference_traversal_does_not_mutate_graph(self):
        g,rows=fixture();before=set(g)
        r=m.context('MAINT-81의 조치',rows,rows,g)
        self.assertTrue(any(e['kind']=='text_reference_not_new_fact' for e in r['traversed_edges']))
        self.assertEqual(before,set(g))
        self.assertTrue(all(e['depth']<=2 for e in r['traversed_edges']))

    def test_budget_and_missing_document_report(self):
        g,rows=fixture();cfg={**v.read(m.POLICY_PATH),'context_token_budget':1}
        r=m.context('DOC-101과 DOC-202',rows,rows,g,cfg)
        self.assertEqual(r['selected_ids'],[])
        self.assertEqual(r['uncovered_explicit_documents'],['DOC-101','DOC-202'])
        self.assertLessEqual(r['context_tokens'],1)

    def test_deterministic_selection(self):
        g,rows=fixture();a=m.context('synthetic action',rows,rows,g);b=m.context('synthetic action',rows,rows,g)
        self.assertEqual(a,b)

    def test_missing_cache_never_calls_network(self):
        with patch.object(v,'urlopen',side_effect=AssertionError('No network')):
            with self.assertRaises(FileNotFoundError):
                m.cached_embeddings('embeddings',{'input':'synthetic never cached'},v.REPO_ROOT/'kg_build/nonexistent_test_cache')


if __name__=='__main__':unittest.main()
