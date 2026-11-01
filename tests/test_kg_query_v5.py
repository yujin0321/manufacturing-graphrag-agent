import unittest
from imaks_kg.rag.kg_query_v5 import KGEngine,short
from imaks_kg.rag import comparison as c

class QueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.engine=KGEngine()

    def test_all_source_document_matches_preserve_nodes(self):
        plan=self.engine.plan('sourceDocument가 SOP-003인 모든 규칙의 appliesToSensor와 actionTarget')
        nodes={short(n) for n in self.engine.graph.subjects(c.IM.sourceDocument,self.engine.refs['SOP-003'])}
        self.assertTrue(nodes.issubset(plan['selected_nodes']))

    def test_feeds_paths_respect_direction(self):
        g=self.engine
        forward=g.paths(g.refs['ST01_FILLING'],g.refs['ST04_PACKAGING'])
        backward=g.paths(g.refs['ST04_PACKAGING'],g.refs['ST01_FILLING'])
        self.assertTrue(forward)
        self.assertFalse(backward)
        self.assertTrue(all((a,c.IM.feedsInto,b) in g.graph for p in forward for a,b in zip(p,p[1:])))

    def test_no_semantic_merge_of_seed_and_candidate(self):
        plan=self.engine.plan('sourceDocument가 SOP-003인 규칙')
        self.assertIn('MAINT-05',plan['selected_nodes'])
        self.assertIn('candidate-SOP-003::MAINT-05',plan['selected_nodes'])

    def test_missing_sensor_relation_filter(self):
        plan=self.engine.plan('sourceDocument는 있지만 appliesToSensor가 없는 규칙')
        matches=plan['computed']['matching_rules']
        self.assertTrue(matches)
        for node in self.engine.all_rules():
            if short(node) in matches:self.assertFalse(list(self.engine.graph.objects(node,c.IM.appliesToSensor)))

    def test_serializer_is_lossless_for_each_node(self):
        import json
        for row in self.engine.records:
            if row['chunk_id']=='KG:MANIFEST':continue
            facts=json.loads(row['text']);node=self.engine.id_nodes[row['chunk_id']]
            self.assertEqual(sum(len(v) for k,v in facts.items() if k!='node'),len(list(self.engine.graph.predicate_objects(node))))

if __name__=='__main__':unittest.main()
