"""Offline checks for graph input boundaries and assignment correctness."""
import itertools
import random
import unittest
from copy import deepcopy

from imaks_kg.kg.build import validate_predictions
from imaks_kg.evaluation.offline import dice, hungarian_max, prf


class PredictionBoundaries(unittest.TestCase):
    def setUp(self):
        self.unit = {"doc_id": "SOP-001", "text": "If pressure >7 bar, inspect valve."}
        self.docs = {"SOP-001": {"inventory": {"sensorIds": ["S_PRS"], "actionTargets": ["S"]}}}
        self.units = {"SOP-001:u1": self.unit}
        self.rule = {"identifier": "SOP-001-EX-001", "ruleClass": "OperationalRule",
                     "conditionText": "pressure >7 bar", "responseText": "inspect valve",
                     "unit_id": "SOP-001:u1", "sourceQuote": self.unit["text"],
                     "sensorIds": ["S_PRS"], "actionTargets": ["S"]}

    def check(self, records):
        validate_predictions(records, self.docs, self.units)

    def test_valid_source_backed_prediction(self):
        self.check([self.rule])

    def test_duplicate_id_rejected(self):
        with self.assertRaises(ValueError):
            self.check([self.rule, deepcopy(self.rule)])

    def test_invented_quote_rejected(self):
        self.rule["sourceQuote"] = "If pressure <7 bar, inspect valve."
        with self.assertRaises(ValueError):
            self.check([self.rule])

    def test_unknown_inventory_rejected(self):
        self.rule["sensorIds"] = ["MODEL_NOT_AN_INSTALLED_SENSOR"]
        with self.assertRaises(ValueError):
            self.check([self.rule])

    def test_nonfinite_number_rejected(self):
        self.rule["numeric"] = {"critHi": float("nan")}
        with self.assertRaises(ValueError):
            self.check([self.rule])

    def test_event_field_rejected(self):
        self.rule["causallyAffects"] = "S2"
        with self.assertRaises(ValueError):
            self.check([self.rule])


class MatchingTests(unittest.TestCase):
    def test_hungarian_beats_greedy(self):
        scores = [[0.9, 0.8], [0.85, 0.1]]
        self.assertEqual(hungarian_max(scores), [(0, 1), (1, 0)])

    def test_rectangular_and_empty(self):
        self.assertEqual(hungarian_max([[0.9], [0.2]]), [(0, 0)])
        self.assertEqual(hungarian_max([[0.2, 0.9]]), [(0, 1)])
        self.assertEqual(hungarian_max([]), [])
        self.assertEqual(hungarian_max([[]]), [])

    def test_against_bruteforce(self):
        rng = random.Random(17)
        for n in (2, 3, 4):
            for _ in range(8):
                scores = [[rng.random() for _ in range(n)] for _ in range(n)]
                expected = max(sum(scores[i][j] for i, j in enumerate(order))
                               for order in itertools.permutations(range(n)))
                actual = sum(scores[i][j] for i, j in hungarian_max(scores))
                self.assertAlmostEqual(actual, expected)

    def test_proxy_is_explicitly_not_negation_safe(self):
        self.assertEqual(dice("pressure >7", "pressure <7"), 1.0)
        self.assertEqual(dice("", ""), 0.0)
        self.assertEqual(prf(1, 2, 4)["f1"], 1 / 3)


if __name__ == "__main__":
    unittest.main()
