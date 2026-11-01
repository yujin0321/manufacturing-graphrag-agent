import csv
import sys
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from imaks_kg.detection import kg_rules as k
from imaks_kg.detection import rules as v1
from imaks_kg.rag import comparison as c
from imaks_kg.rag import vector as v

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import evaluate_detector_events as ev  # noqa: E402


def _norm(x):
    return None if x in (None, "None") else str(Decimal(x).normalize())


def _key(rule):
    return (rule["sensor_id"], rule["op"], _norm(rule["value"]), _norm(rule.get("second")), rule["duration_seconds"])


class GrammarTests(unittest.TestCase):
    def test_duration_is_not_read_as_threshold(self):
        p = k.parse_condition("ST01_FILLING pressure <3.3 bar for >15 min.")
        self.assertEqual((p["op"], p["value"], p["duration_seconds"]), ("lt", "3.3", 900))

    def test_relative_to_nominal(self):
        p = k.parse_condition("current (CUR) increases >1.5 A above nominal, sustained >5 min.")
        self.assertTrue(p["relative_to_nominal"])
        self.assertEqual((p["value"], p["duration_seconds"]), ("1.5", 300))

    def test_stuck_more_than_ten_means_eleven(self):
        self.assertEqual(k.parse_condition("TEN is STUCK for >10 consecutive samples")["value"], "11")

    def test_unsupported_is_never_guessed(self):
        for text in ["speed (SPD) drops below 1.00 m/s without an operator command.",
                     "vibration drift >0.05 mm/s over 60 min.",
                     "current (CUR) triggers a WARNING; its drift correlates with ST04"]:
            self.assertIn("unsupported", k.parse_condition(text))


class CompileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = c.load_graph()
        cls.rules, cls.unsupported = k.compile_rules(cls.graph)

    def test_kg_compiled_rules_equal_reviewed_v1_table(self):
        """The human-reviewed v1 table is the oracle for the KG compiler."""
        corpus = {r["chunk_id"]: r for r in v.source_records()[0]}
        with (v.REPO_ROOT / v1.THRESHOLDS).open(encoding="utf-8-sig") as f:
            thresholds = {r["sensor_id"]: r for r in csv.DictReader(f)}
        oracle, oracle_unsupported = v1.definitions(corpus, thresholds)
        compiled = [r for r in self.rules if r["kind"] == "kg_document_rule"]
        self.assertEqual(sorted(map(_key, compiled)), sorted(map(_key, oracle)))
        unsupported_ids = {u["rule_id"] for u in self.unsupported}
        for rule in ["RULE-ST04-03", "RULE-ST02-04", "MAINT-01", "MAINT-02", "MAINT-06", "MAINT-08"]:
            self.assertIn(rule, unsupported_ids)

    def test_nominal_comes_from_threshold_rule_join(self):
        st02 = next(r for r in self.rules if r["rule_id"] == "RULE-ST02-03")
        self.assertEqual(Decimal(st02["value"]), Decimal("13.9"))  # 12.4 nominal + 1.5

    def test_every_rule_points_to_a_kg_node(self):
        for r in self.rules:
            self.assertTrue(r["kg_node"].startswith("https://example.org/imaks/id/"))

    def test_kg_bands_match_sensor_metadata(self):
        with (v.REPO_ROOT / v1.THRESHOLDS).open(encoding="utf-8-sig") as f:
            thresholds = {r["sensor_id"]: r for r in csv.DictReader(f)}
        self.assertEqual(k.threshold_consistency(self.graph, thresholds), [])


class ScanTests(unittest.TestCase):
    def rows(self, values, start="2026-01-06T23:57:00"):
        t = datetime.fromisoformat(start)
        return [{"timestamp": (t + timedelta(seconds=30 * i)).isoformat(), "value": str(x), "unit": "A",
                 "sensor_id": "S"} for i, x in enumerate(values)]

    def rule(self, **kw):
        return {"rule_id": "R", "kind": "kg_document_rule", "unit": "A", "op": "gt", "value": "13.9",
                "second": None, "duration_seconds": 0, **kw}

    def test_persistence_crosses_midnight(self):
        """v1 reset at the train/validation boundary and missed this; v2 does not."""
        rule = self.rule(duration_seconds=300)
        self.assertEqual(v1.evaluate_rule(self.rows([14] * 12), {**rule, "id": "R"}), [])
        events = k.scan(self.rows([14] * 12), rule)
        self.assertEqual(events[0]["trigger_at"], "2026-01-07T00:02:30")

    def test_gap_still_resets(self):
        rows = self.rows([14] * 12)
        rows[6:] = self.rows([14] * 6, "2026-01-07T01:00:00")
        self.assertEqual(k.scan(rows, self.rule(duration_seconds=300)), [])

    def test_strict_boundary(self):
        self.assertEqual(k.scan(self.rows(["13.9"]), self.rule()), [])
        self.assertEqual(len(k.scan(self.rows(["13.9001"]), self.rule())), 1)


class EventEvaluationTests(unittest.TestCase):
    def test_overlap_and_latency(self):
        gold = {"sensor_id": "S", "start": "2026-01-06T10:00:00", "end": "2026-01-06T10:30:00", "label": "DRIFT"}
        det = {"sensor_id": "S", "kind": "x", "rule_id": "R", "trigger_at": "2026-01-06T10:20:00",
               "last_positive_at": "2026-01-06T10:40:00"}
        far = {**det, "trigger_at": "2026-01-06T12:00:00", "last_positive_at": "2026-01-06T12:01:00"}
        report = ev.evaluate([det, far], [gold], grace_minutes=0)["ALL"]
        self.assertEqual((report["events_caught"], report["false_alarms"]), (1, 1))
        self.assertEqual(report["median_latency_min"], 20.0)

    def test_other_sensor_never_matches(self):
        gold = {"sensor_id": "S", "start": "2026-01-06T10:00:00", "end": "2026-01-06T10:30:00", "label": "SPIKE"}
        det = {"sensor_id": "T", "kind": "x", "rule_id": "R", "trigger_at": "2026-01-06T10:00:00",
               "last_positive_at": "2026-01-06T10:00:00"}
        self.assertEqual(ev.evaluate([det], [gold], 0)["ALL"]["events_caught"], 0)


if __name__ == "__main__":
    unittest.main()
