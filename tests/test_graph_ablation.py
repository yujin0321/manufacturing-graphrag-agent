import unittest
from unittest.mock import patch
from imaks_kg.rag import ablation as a,graph_v2 as g,vector as v


class AblationTests(unittest.TestCase):
    def rows(self):
        return [{'chunk_id':'d1','doc_id':'DOC-101','page':1,'section':None,'text':'RULE-TEST-81: alpha.'},
                {'chunk_id':'d2','doc_id':'DOC-202','page':1,'section':None,'text':'RULE-TEST-82: beta.'}]

    def test_empty_graph_is_identical_control(self):
        rows=self.rows();b=a.select('synthetic query',rows,rows)
        c=a.select('synthetic query',rows,rows,{'visited_nodes':[],'source_links':{}})
        self.assertEqual(b['context'],c['context']);self.assertEqual(b['selected_ids'],c['selected_ids'])

    def test_only_graph_candidate_insertion_changes_selection(self):
        rows=self.rows();policy={**v.read(g.POLICY_PATH),'max_source_candidates':1}
        with patch.object(a.v,'read',return_value=policy):
            b=a.select('synthetic query',rows,rows)
            c=a.select('synthetic query',rows,rows,{'visited_nodes':['node'],'source_links':{'node':['d2']}})
        self.assertEqual(b['shared_prefix'],c['shared_prefix'])
        self.assertEqual(b['shared_ranked_ids'],c['shared_ranked_ids'])
        self.assertEqual(b['selected_ids'],['d1']);self.assertEqual(c['selected_ids'],['d2'])
        self.assertEqual(c['graph_cards'],0)

    def test_literal_identifier_without_kg(self):
        rows=self.rows();r=a.select('RULE-TEST-82의 조건',rows,rows)
        self.assertEqual(r['selected_ids'][0],'d2')
        self.assertEqual(r['literal_identifiers'],['RULE-TEST-82'])


if __name__=='__main__':unittest.main()
