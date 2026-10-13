import tempfile
import unittest
from pathlib import Path

from imaks_kg.eval.metrics import evaluate
from imaks_kg.kg_build.preprocessed_abox import PreprocessedLayout, build_station_sensor
from imaks_kg.kg_build.rule_extract import split_condition_action


class KgValidationTests(unittest.TestCase):
    def test_split_condition_action(self):
        cond, action = split_condition_action("RULE-X: TMP > 210°C (CRITICAL) — emergency stop ST02.")
        self.assertEqual(cond, "TMP > 210°C (CRITICAL)")
        self.assertEqual(action, "emergency stop ST02")

    def test_station_sensor_from_preprocessed_only(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = root / "sensors" / "input"
            p.mkdir(parents=True)
            (p / "ts_input.csv").write_text(
                "timestamp,zone,station_id,sensor_id,sensor_type,value,unit\n"
                "t,Production Area,ST01_FILLING,ST01_FILLING_TMP,TMP,1,°C\n",
                encoding="utf-8",
            )
            layout = PreprocessedLayout(root)
            stations, sensors, rels = build_station_sensor(layout)
            self.assertEqual(len(stations), 1)
            self.assertEqual(len(sensors), 1)
            self.assertEqual(rels[0]["type"], "hasSensor")

    def test_evaluate_content_match(self):
        pred = [{"ruleId": "R1", "class": "OperationalRule", "condition": "TMP > 210 C", "action": "stop"}]
        truth = [{"ruleId": "G1", "class": "OperationalRule", "condition": "TMP > 210 C", "action": "stop"}]
        summary, pairs = evaluate(pred, truth, threshold=0.6)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(summary["matched_count"], 1)


if __name__ == "__main__":
    unittest.main()
