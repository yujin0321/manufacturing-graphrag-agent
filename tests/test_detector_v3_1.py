"""Rule detector v3.1 post-hoc fixes. Synthetic series only; no labels."""
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from imaks_kg.detection import kg_rules_v3 as k3
from imaks_kg.detection import kg_rules_v3_1 as k31
from imaks_kg.rag import comparison as c

T0 = datetime(2026, 1, 8, 8, 0, 0)


def rows(values, start=T0):
    return [{"timestamp": (start + timedelta(seconds=30 * i)).isoformat(), "value": str(x), "unit": "u",
             "sensor_id": "S"} for i, x in enumerate(values)]


def signal(sensor, t, value, sid):
    return {"id": sid, "sensor_id": sensor, "kind": "sop002_drift_slope", "rule_id": "SOP-002-EX-24:DRIFT",
            "trigger_at": t.isoformat(), "condition_start": t.isoformat(), "last_positive_at": t.isoformat(),
            "trigger_value": str(value), "unit": "m/s", "positive_samples": 1, "report_split": "test"}


PAIR = {"cause_sensor": "C", "effect_sensor": "E", "rule_ids": ["RULE-ST02-04"], "kg_nodes": [],
        "window_min": 90, "window_rule_id": "W", "effect_direction": "below_nominal"}
SENSORS = {"E": {"nominal": 1.2}}


class MaintDirectionTests(unittest.TestCase):
    def test_rise_away_from_nominal_fires(self):
        _, x, seg = k3._arrays(rows([4.0] * 40 + [7.0] * 10))
        self.assertTrue(k31.window_change_away_condition(x, seg, 30, 2.0, nominal=4.0)[-1])

    def test_recovery_toward_nominal_is_silent(self):
        _, x, seg = k3._arrays(rows([10.0] * 40 + [6.0] * 10))
        self.assertFalse(k31.window_change_away_condition(x, seg, 30, 2.0, nominal=4.0).any())
        self.assertTrue(k3.window_change_condition(x, seg, 30, 2.0)[-1])  # v3 fired here


class MonitorTests(unittest.TestCase):
    def cause(self, kinds):
        return {"id": "cause", "sensor_id": "C", "start": T0.isoformat(), "kinds": kinds}

    def test_signal_inside_window_and_direction_is_promoted(self):
        sig = signal("E", T0 + timedelta(minutes=60), 1.0, "s1")
        alarms, windows = k31.monitor_alarms([self.cause(["kg_threshold_warning"])], [sig], [PAIR], SENSORS)
        self.assertEqual(len(windows), 1)
        self.assertEqual([a["source_signal"] for a in alarms], ["s1"])
        self.assertEqual(alarms[0]["kind"], "kg_correlation_monitor")

    def test_outside_window_wrong_direction_or_no_warning_are_not(self):
        late = signal("E", T0 + timedelta(minutes=120), 1.0, "late")
        up = signal("E", T0 + timedelta(minutes=10), 1.4, "up")
        self.assertEqual(k31.monitor_alarms([self.cause(["kg_threshold_warning"])], [late, up], [PAIR], SENSORS)[0], [])
        inside = signal("E", T0 + timedelta(minutes=10), 1.0, "in")
        self.assertEqual(k31.monitor_alarms([self.cause(["kg_maint_drift"])], [inside], [PAIR], SENSORS)[0], [])


class KgTests(unittest.TestCase):
    def test_effect_direction_from_kg_rules(self):
        g = c.load_graph()
        pair, = k31.pair_directions(g, k3.compile_v3(g)["correlation_pairs"])
        self.assertEqual(pair["effect_direction"], "below_nominal")

    def test_v31_never_reads_labels(self):
        src = Path(k31.__file__).read_text(encoding="utf-8")
        for banned in ("row_labels", "anomaly_label", "timeseries_annotated", "ground_truth"):
            self.assertNotIn(banned, src)


if __name__ == "__main__":
    unittest.main()
