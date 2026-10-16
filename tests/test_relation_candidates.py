import unittest
import json
from rdflib import Graph,Literal
from pyshacl import validate
from imaks_kg.kg.relation_candidates import OUT,SCHEMA,RC,IM,iri

class RelationCandidateTests(unittest.TestCase):
    def check(self,edit=None):
        g=Graph().parse(OUT/'candidate_kg.ttl')
        if edit:edit(g)
        return validate(g,shacl_graph=Graph().parse(SCHEMA/'shapes.ttl'),inference='none')[0]
    def test_valid_graph(self):self.assertTrue(self.check())
    def test_missing_condition(self):
        self.assertFalse(self.check(lambda g:g.remove((RC['REL-02'],RC.conditionText,None))))
    def test_wrong_target_type(self):
        self.assertFalse(self.check(lambda g:g.set((RC['REL-02'],RC.object,iri('ST04_PACKAGING')))))
    def test_fabricated_approval(self):
        self.assertFalse(self.check(lambda g:g.set((RC['REL-02'],RC.reviewStatus,Literal('approved')))))
    def test_causal_promotion(self):
        self.assertFalse(self.check(lambda g:g.add((RC['REL-02'],IM.causallyAffects,iri('ST04_PACKAGING')))))
    def test_no_approved_relations(self):
        self.assertEqual(len(Graph().parse(OUT/'approved_relations.ttl')),0)
    def test_original_seed_correlation_is_not_new(self):
        data=json.loads((OUT/'candidates.json').read_text(encoding='utf-8'))
        rel=next(x for x in data if x['identifier']=='REL-01')
        self.assertEqual(rel['novelty'],'existing_seed_relation_evidence_enrichment')
        self.assertEqual(rel['raw_seed_semantic_matches'][0]['relation'],'correlates_with')
