import unittest
from rule_matching import content_text, match_matrix, metrics


class Matching(unittest.TestCase):
    def test_one_reference_cannot_match_two_predictions(self):
        pairs, result = match_matrix([[0.9], [0.8]], 1)
        self.assertEqual((result["tp"], result["fp"], result["fn"]), (1, 1, 0))
        self.assertAlmostEqual(result["f1_content"], 2/3)

    def test_global_assignment_and_threshold(self):
        pairs, result = match_matrix([[0.9, 0.8], [0.85, 0.1]], 2)
        self.assertEqual({(p["prediction_index"], p["reference_index"]) for p in pairs}, {(0, 1), (1, 0)})
        self.assertEqual(result["tp"], 2)
        self.assertEqual(match_matrix([[0.599, 0.6]], 2)[1]["tp"], 1)

    def test_empty_cases_and_invalid_matrix(self):
        self.assertEqual(match_matrix([], 86)[1]["fn"], 86)
        self.assertEqual(match_matrix([[]], 0)[1]["fp"], 1)
        with self.assertRaises(ValueError):
            match_matrix([[float("nan")]], 1)

    def test_no_identifier_or_class_in_content(self):
        self.assertEqual(content_text({"identifier": "X", "class": "Y", "condition": "a  b", "response": "c"}), "a b c")


if __name__ == "__main__":
    unittest.main()
