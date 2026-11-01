import json
import unittest
from rdflib import Graph, Literal, XSD
from pyshacl import validate
from imaks_kg.kg.finalize_stage6 import OUT, RC, IM, REPO_ROOT, sha


class FinalStage6Tests(unittest.TestCase):
    def check(self, edit=None):
        g = Graph().parse(OUT / 'document_kg.ttl')
        if edit:
            edit(g)
        return validate(g, shacl_graph=Graph().parse(OUT / 'shapes.ttl'), inference='none')[0]

    def test_final_graph_valid(self):
        self.assertTrue(self.check())

    def test_missing_operator_context_rejected(self):
        self.assertFalse(self.check(lambda g: g.remove((RC['REL-03'], RC.withoutOperatorCommand, None))))

    def test_wrong_threshold_comparator_rejected(self):
        self.assertFalse(self.check(lambda g: g.set((RC['REL-04'], RC.comparisonOperator, Literal('>=')))))

    def test_generic_stop_rejected(self):
        self.assertFalse(self.check(lambda g: g.set((RC['REL-05'], RC.action, Literal('shutdown')))))

    def test_ungrouped_stop_rejected(self):
        self.assertFalse(self.check(lambda g: g.remove((RC['REL-06'], RC.obligationGroup, None))))

    def test_fabricated_thermal_threshold_rejected(self):
        self.assertFalse(self.check(lambda g: g.add((RC['REL-07'], RC.thresholdValue, Literal('210', datatype=XSD.decimal)))))

    def test_human_approval_not_inferred(self):
        self.assertFalse(self.check(lambda g: g.set((RC['REL-02'], RC.humanReviewStatus, Literal('approved')))))
        self.assertEqual(len(Graph().parse(OUT / 'human_approved_relations.ttl')), 0)

    def test_missing_document_rejected(self):
        self.assertFalse(self.check(lambda g: g.remove((None, RC.sourceDocument, None))))

    def test_no_causal_promotion(self):
        self.assertFalse(self.check(lambda g: g.add((RC['REL-07'], IM.causallyAffects, RC['REL-02']))))

    def test_release_hashes_and_frozen_inputs(self):
        manifest = json.loads((OUT / 'release_manifest.json').read_text(encoding='utf-8'))
        for path, expected in manifest['inputs'].items():
            self.assertEqual(sha(REPO_ROOT / path), expected)
        for path, expected in manifest['outputs'].items():
            self.assertEqual(sha(OUT / path), expected)


if __name__ == '__main__':
    unittest.main()
