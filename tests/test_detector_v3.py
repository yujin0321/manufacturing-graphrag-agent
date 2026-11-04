"""Rule detector v3: KG parsing, new conditions, incident grouping, correlation.
Synthetic series only; no labels are read."""
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from imaks_kg.detection import kg_rules_v3 as k3
from imaks_kg.rag import comparison as c

T0 = datetime(2026, 1, 7, 10, 0, 0)


def rows(values, start=T0, sensor="S"):
    return [{"timestamp": (start + timedelta(seconds=30 * i)).isoformat(), "value": str(x), "unit": "u",
             "sensor_id": sensor} for i, x in enumerate(values)]


def alarm(kind, t0, t1, sensor="S", rule="R"):
    a = {"sensor_id": sensor, "rule_id": rule, "kind": kind, "trigger_at": t0.isoformat(),
         "last_positive_at": t1.isoformat(), "condition_start": t0.isoformat()}
    a["id"] = f"{kind}-{t0.isoformat()}"
    return a


DEFS = {"SPIKE": {"max_minutes": 5}}


class KgCompileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiled = k3.compile_v3(c.load_graph())

    def test_sop002_type_parameters_come_from_kg_text(self):
        d = self.compiled["type_definitions"]
        self.assertEqual((d["DRIFT"]["sigma_per_min"], d["DRIFT"]["readings"], d["DRIFT"]["window_min"]), (0.1, 5, 15))
        self.assertEqual((d["STUCK"]["window"], d["STUCK"]["nominal_fraction"]), (10, 0.001))
        self.assertEqual(d["OUT_OF_RANGE"]["readings"], 20)
        self.assertEqual(d["SPIKE"]["max_minutes"], 5)
        self.assertEqual(d["CORRELATED"]["window_min"], 90)

    def test_all_maint_drift_rules_compile(self):
        got = {m["rule_id"]: (m["mode"], m["delta"]) for m in self.compiled["maint_drift"]}
        self.assertEqual(got, {"MAINT-01": ("window_change", 0.05), "MAINT-02": ("sustained_from_nominal", 1.0),
                               "MAINT-06": ("window_change", 2.0), "MAINT-08": ("window_change", 10.0)})

    def test_correlation_pair_from_kg(self):
        pair, = self.compiled["correlation_pairs"]
        self.assertEqual((pair["cause_sensor"], pair["effect_sensor"]), ("ST02_SEALING_CUR", "ST04_PACKAGING_SPD"))
        self.assertIn("RULE-ST02-04", pair["rule_ids"])

    def test_non_sensor_patterns_stay_unsupported(self):
        self.assertEqual({u["rule_id"] for u in self.compiled["unsupported"]}, {"SOP-003-EX-02", "SOP-003-EX-03"})

    def test_partial_rule_is_flagged(self):
        p, = self.compiled["partial"]
        self.assertEqual((p["rule_id"], p["value"]), ("RULE-ST04-03", 1.0))
        self.assertIn("precondition_unobserved", p["flag"])


class ConditionTests(unittest.TestCase):
    def test_slope_fires_on_ramp_away_from_nominal_only(self):
        ramp = np.r_[np.zeros(40), np.arange(40) * 0.5]       # +1.0/min after flat start
        _, x, seg = k3._arrays(rows(ramp))
        up = k3.slope_condition(x, seg, 30, sigma=1.0, nominal=0.0, k=0.1)
        self.assertTrue(up[-1])
        self.assertFalse(up[:40].any())
        back = k3.slope_condition(x[::-1].copy(), seg, 30, sigma=1.0, nominal=0.0, k=0.1)
        self.assertFalse(back[-10:].any())  # returning toward nominal is not a deviation

    def test_stuck_std_tolerates_tiny_noise(self):
        vals = [5.0, 5.001, 5.0, 5.001, 5.0, 5.001, 5.0, 5.001, 5.0, 5.001]
        _, x, seg = k3._arrays(rows(vals))
        self.assertTrue(k3.stuck_condition(x, seg, 10, 0.001 * 5.0)[-1])

    def test_window_change(self):
        vals = [0.0] * 40 + [3.0] * 10
        _, x, seg = k3._arrays(rows(vals))
        cond = k3.window_change_condition(x, seg, 30, 2.0)
        self.assertTrue(cond[-1])
        self.assertFalse(cond[:40].any())

    def test_runs_needs_consecutive_readings_and_gap_resets(self):
        r = rows([1] * 25)
        r[10:] = rows([1] * 15, T0 + timedelta(hours=1))
        data = {"_arrays": k3._arrays(r)}
        rule = {"sensor_id": "S", "rule_id": "R", "kind": "k", "unit": "u"}
        self.assertEqual(k3.runs(data, np.ones(25, bool), 20, rule), [])
        self.assertEqual(len(k3.runs(data, np.ones(25, bool), 15, rule)), 1)


class IncidentTests(unittest.TestCase):
    def test_alarms_within_gap_merge(self):
        a = alarm("kg_threshold_warning", T0, T0 + timedelta(minutes=3))
        b = alarm("kg_document_rule", T0 + timedelta(minutes=8), T0 + timedelta(minutes=9))
        far = alarm("kg_threshold_warning", T0 + timedelta(minutes=40), T0 + timedelta(minutes=41))
        inc = k3.group_incidents([a, b, far], DEFS)
        self.assertEqual([len(i["alarm_ids"]) for i in inc], [2, 1])

    def test_signals_inform_type_but_never_create_incidents(self):
        sig = alarm("sop002_drift_slope", T0, T0 + timedelta(minutes=20))
        lone = alarm("sop002_drift_slope", T0 + timedelta(hours=5), T0 + timedelta(hours=6))
        w = alarm("kg_threshold_warning", T0 + timedelta(minutes=15), T0 + timedelta(minutes=30))
        inc = k3.group_incidents([w], DEFS, signals=[sig, lone])
        self.assertEqual(len(inc), 1)
        self.assertEqual(inc[0]["anomaly_type"], "DRIFT")
        self.assertEqual(inc[0]["onset_estimate"], T0.isoformat())
        self.assertEqual(inc[0]["alarm_ids"], [w["id"]])

    def test_spike_short_critical(self):
        a = alarm("kg_threshold_critical", T0, T0 + timedelta(minutes=1))
        drift = alarm("sop002_drift_slope", T0 + timedelta(minutes=2), T0 + timedelta(minutes=12))
        self.assertEqual(k3.classify([a, drift], DEFS)[0], "SPIKE")

    def test_drift_before_threshold(self):
        d = alarm("sop002_drift_slope", T0, T0 + timedelta(minutes=30))
        o = alarm("sop002_out_of_range", T0 + timedelta(minutes=20), T0 + timedelta(minutes=40))
        self.assertEqual(k3.classify([d, o], DEFS)[0], "DRIFT")

    def test_step_then_sustained_is_out_of_range(self):
        w = alarm("kg_threshold_warning", T0, T0 + timedelta(minutes=30))
        o = alarm("sop002_out_of_range", T0 + timedelta(minutes=10), T0 + timedelta(minutes=30))
        d = alarm("sop002_drift_slope", T0 + timedelta(minutes=2), T0 + timedelta(minutes=8))
        self.assertEqual(k3.classify([w, o, d], DEFS)[0], "OUT_OF_RANGE")

    def test_stuck_wins(self):
        s = alarm("sop002_stuck_std", T0, T0 + timedelta(minutes=5))
        w = alarm("kg_threshold_warning", T0, T0 + timedelta(minutes=5))
        self.assertEqual(k3.classify([s, w], DEFS)[0], "STUCK")

    def test_correlation_links_effect_within_window(self):
        cause = alarm("kg_threshold_warning", T0, T0 + timedelta(minutes=5), sensor="C")
        effect = alarm("kg_document_rule_partial", T0 + timedelta(minutes=60), T0 + timedelta(minutes=70), sensor="E")
        late = alarm("kg_document_rule_partial", T0 + timedelta(minutes=200), T0 + timedelta(minutes=201), sensor="E")
        inc = k3.group_incidents([cause, effect, late], DEFS)
        pair = {"cause_sensor": "C", "effect_sensor": "E", "rule_ids": ["R1"], "kg_nodes": [], "window_min": 90,
                "window_rule_id": "W"}
        links = k3.link_correlations(inc, [pair])
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["lag_min"], 60.0)
        types = {i["start"]: i["anomaly_type"] for i in inc if i["sensor_id"] == "E"}
        self.assertEqual(types[(T0 + timedelta(minutes=60)).isoformat()], "CORRELATED")
        self.assertNotEqual(types[(T0 + timedelta(minutes=200)).isoformat()], "CORRELATED")


class LeakageTests(unittest.TestCase):
    def test_detector_never_reads_labels(self):
        src = Path(k3.__file__).read_text(encoding="utf-8")
        for banned in ("row_labels", "anomaly_label", "timeseries_annotated", "ground_truth", "severity\"]"):
            self.assertNotIn(banned, src)

    def test_sigma_uses_train_period_only(self):
        r = rows([0, 1] * 10, datetime(2026, 1, 6, 23, 50)) + rows([1000] * 10, datetime(2026, 1, 7, 0, 0))
        s = k3.train_sigma(r)
        self.assertEqual(s["train_samples"], 20)
        self.assertLess(s["sigma"], 2)


if __name__ == "__main__":
    unittest.main()
