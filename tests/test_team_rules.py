import itertools
import unittest
import numpy as np
from imaks_kg.eval.team_rules import assign,match

class TeamMatchingTests(unittest.TestCase):
    def test_hungarian_against_exhaustive_assignment(self):
        rng=np.random.default_rng(42)
        for n in range(1,5):
            for _ in range(15):
                a=rng.normal(size=(n,n+1))
                expected=min(sum(a[i,j] for i,j in enumerate(p))
                    for p in itertools.permutations(range(n+1),n))
                self.assertAlmostEqual(sum(a[i,j] for i,j in assign(a)),expected,places=8)

    def test_cardinality_precedes_similarity(self):
        s=np.array([[.99,.6],[.6,.59]])
        pairs=match(s,np.ones_like(s,dtype=bool),.6)
        self.assertEqual({(i,j) for i,j,_ in pairs},{(0,1),(1,0)})

    def test_invalid_scores_do_not_affect_tie_break(self):
        s=np.array([[.9,.8],[.59,0.]])
        pairs=match(s,np.ones_like(s,dtype=bool),.6)
        self.assertEqual([(i,j) for i,j,_ in pairs],[(0,0)])

    def test_document_exclusion(self):
        self.assertEqual(match(np.ones((2,2)),np.zeros((2,2),dtype=bool),.6),[])
