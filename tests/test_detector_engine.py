"""Rule detector engine (stage 1). No labels are read.

Unit tests use the frozen KG and synthetic series. The equivalence tests run
legacy v3 / v3-literal / v3.1 and the engine on the frozen sensor input and
compare outputs; they are skipped when preprocessed/sensors is not present.
"""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import numpy as np
from rdflib import Literal, RDF

from imaks_kg.detection import kg_rules_v3 as k3
from imaks_kg.detection import kg_rules_v3_1 as k31
from imaks_kg.detection.engine import compiler, config, executor, postprocess
from imaks_kg.rag import comparison as c
from imaks_kg.rag import vector as v

T0 = datetime(2026, 1, 8, 8, 0, 0)
INPUT = v.REPO_ROOT / "preprocessed/sensors/input/ts_input.csv"


def rows(values, sensor="S", start=T0):
    return [{"timestamp": (start + timedelta(seconds=30 * i)).isoformat(), "value": str(x), "unit": "u",
             "sensor_id": sensor} for i, x in enumerate(values)]


class ConfigTests(unittest.TestCase):
    def test_three_configs_load_and_expose_interpretations(self):
        expected = {"v3": ("signal", "abs", None), "v3_literal": ("alarm", "abs", None),
                    "v3_1": ("signal", "away", "warning_any")}
        for name, triple in expected.items():
            cfg = config.load(name)
            self.assertEqual((cfg["slope_mode"], cfg["maint_direction"], cfg["monitor_gate"]), triple)

    def test_invalid_values_are_rejected(self):
        base = config.load("v3_1")
        base.pop("_path")
        for key, bad in (("slope_mode", "x"), ("maint_direction", "x"), ("monitor_gate", "x"),
                         ("monitor_anchor", "x"), ("link_policy", "x"), ("severity_policy", "x"),
                         ("sample_seconds", 60), ("incident_gap_min", 0)):
            cfg = {**base, key: bad}
            with self.assertRaises(config.ConfigError, msg=key):
                config.validate(cfg)
        with self.assertRaises(config.ConfigError):  # monitoring needs slope signals
            config.validate({**base, "slope_mode": "alarm"})


class CompilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = c.load_graph()
        cls.bundle = compiler.compile_ir(cls.graph)

    def test_every_ir_record_is_traceable(self):
        for r in self.bundle["rules"]:
            for key in ("ir_id", "rule_id", "kg_rule_id", "kg_node", "condition_text", "kind", "executor",
                        "interpretation", "params", "param_sources", "sensor_id", "unit"):
                self.assertIn(key, r, r.get("ir_id"))
            self.assertTrue(set(r["params"]) <= set(r["param_sources"]), r["ir_id"])
            self.assertTrue(r["kg_node"].startswith("https://example.org/imaks/id/"))

    def test_suffixed_execution_ids_map_to_kg_rule(self):
        warning = next(r for r in self.bundle["rules"] if r["rule_id"].endswith(":warning"))
        self.assertEqual(warning["kg_rule_id"], warning["rule_id"].split(":")[0])
        drift = next(r for r in self.bundle["rules"] if r["kind"] == "sop002_drift_slope")
        self.assertEqual((drift["rule_id"], drift["kg_rule_id"]), ("SOP-002-EX-24:DRIFT", "SOP-002-EX-24"))

    def test_parameter_sources_separate_kg_and_team_values(self):
        drift = next(r for r in self.bundle["rules"] if r["kind"] == "sop002_drift_slope")
        self.assertEqual(drift["param_sources"]["k_sigma_per_min"], "kg:conditionText")
        self.assertTrue(drift["param_sources"]["sigma"].startswith("calibration:"))
        maint = next(r for r in self.bundle["rules"] if r["executor"] == "window_change")
        self.assertEqual(maint["param_sources"]["smooth_samples"], "config.smooth_samples")
        band = next(r for r in self.bundle["rules"] if r["kind"] == "kg_threshold_critical")
        self.assertEqual(band["param_sources"]["value"], "kg:ThresholdRule.critLo")

    def test_ir_matches_legacy_compile_counts(self):
        legacy = k3.compile_v3(self.graph)
        kinds = [r["kind"] for r in self.bundle["rules"]]
        n = len(legacy["sensors"])
        self.assertEqual(len(kinds), len(legacy["v2_rules"]) + 3 * n + len(legacy["maint_drift"]) + len(legacy["partial"]))
        self.assertEqual([u["rule_id"] for u in self.bundle["unsupported"]],
                         [u["rule_id"] for u in legacy["unsupported"]])
        self.assertEqual(self.bundle["correlation_pairs"][0]["effect_direction"], "below_nominal")

    def test_broken_type_definition_reports_kg_node(self):
        g = copy.deepcopy(self.graph)
        node = next(n for n in g.subjects(RDF.type, c.IM.ThresholdRule)
                    if g.value(n, c.IM.appliesToSensor) is None and str(g.value(n, c.IM.responseText)) == "STUCK")
        g.set((node, c.IM.conditionText, Literal("Unchanged readings; criterion reworded.")))
        with self.assertRaises(compiler.CompileError) as ctx:
            compiler.compile_ir(g)
        self.assertIn("STUCK", str(ctx.exception))


class ExecutorTests(unittest.TestCase):
    CFG = {"sample_seconds": 30, "smooth_samples": 10, "maint_direction": "abs", "train_end": "2026-01-07"}

    def _ir(self, executor_name, params, kind="kg_maint_drift"):
        return {"ir_id": "R@S", "rule_id": "R", "kind": kind, "executor": executor_name, "sensor_id": "S",
                "unit": "u", "params": params, "alarm_extra": {}}

    def test_executor_never_touches_the_kg(self):
        series = rows([1.0] * 140 + [1.0 + 0.01 * i for i in range(80)])
        ir = [self._ir("window_change", {"delta": 0.05, "window_min": 30, "nominal": 1.0})]
        with mock.patch.object(c, "load_graph", side_effect=AssertionError("KG read")), \
                mock.patch("rdflib.Graph.value", side_effect=AssertionError("KG query")):
            alarms = executor.execute({"S": series}, ir, {"S": {"sigma": 0.1}}, self.CFG)
        self.assertTrue(alarms)

    def test_window_change_matches_legacy_both_directions(self):
        x = np.array([1.0] * 140 + [1.4] * 60 + [1.0] * 80)
        seg = np.zeros(len(x), dtype=int)
        abs_new = executor.window_change_condition(x, seg, 60, 0.05, 10, "abs", 1.0)
        away_new = executor.window_change_condition(x, seg, 60, 0.05, 10, "away", 1.0)
        np.testing.assert_array_equal(abs_new, k3.window_change_condition(x, seg, 60, 0.05))
        np.testing.assert_array_equal(away_new, k31.window_change_away_condition(x, seg, 60, 0.05, 1.0))
        self.assertGreater(abs_new.sum(), away_new.sum())  # recovery counted only by 'abs'

    def test_away_direction_marks_alarm(self):
        series = rows([1.0] * 140 + [1.4] * 60)
        ir = [self._ir("window_change", {"delta": 0.05, "window_min": 30, "nominal": 1.0})]
        alarms = executor.execute({"S": series}, ir, {"S": {"sigma": 0.1}}, {**self.CFG, "maint_direction": "away"})
        self.assertEqual({a.get("direction") for a in alarms}, {"away_from_nominal"})

    def test_slope_skipped_when_sigma_zero(self):
        ir = self._ir("slope", {"k_sigma_per_min": 0.1, "readings": 5, "window_min": 15, "nominal": 0.0},
                      kind="sop002_drift_slope")
        series = rows(list(range(100)))
        self.assertEqual(executor.execute({"S": series}, [ir], {"S": {"sigma": 0.0}}, self.CFG), [])

    def test_train_sigma_uses_only_train_period(self):
        early = rows([0.0, 1.0, 2.0, 3.0], start=datetime(2026, 1, 6, 0, 0))
        late = rows([1000.0] * 10, start=datetime(2026, 1, 8, 0, 0))
        self.assertEqual(executor.train_sigma(early + late, "2026-01-07"), k3.train_sigma(early + late))
        self.assertEqual(executor.train_sigma(early + late, "2026-01-07")["train_samples"], 4)


class PostprocessTests(unittest.TestCase):
    def test_split_signals_by_mode(self):
        a = [{"kind": "sop002_drift_slope"}, {"kind": "kg_maint_drift"}]
        self.assertEqual(postprocess.split_signals(a, "alarm"), (a, []))
        self.assertEqual(postprocess.split_signals(a, "signal"), ([a[1]], [a[0]]))

    def test_monitor_ids_follow_config_prefix(self):
        t = T0
        cause = {"id": "inc", "sensor_id": "C", "start": t.isoformat(), "kinds": ["kg_threshold_warning"]}
        sig = {"id": "s1", "sensor_id": "E", "kind": "sop002_drift_slope", "trigger_at": (t + timedelta(minutes=30)).isoformat(),
               "condition_start": t.isoformat(), "last_positive_at": t.isoformat(), "trigger_value": "1.0",
               "unit": "m/s", "positive_samples": 1, "report_split": "test"}
        pair = {"cause_sensor": "C", "effect_sensor": "E", "rule_ids": ["RULE-ST02-04"], "window_min": 90,
                "effect_direction": "below_nominal"}
        cfg = {"id_prefix": {"alarm": "det31-", "incident": "inc3-"}}
        new, windows = postprocess.monitor([cause], [sig], [pair], {"E": {"nominal": 1.2}}, cfg)
        old, old_windows = k31.monitor_alarms([cause], [sig], [pair], {"E": {"nominal": 1.2}})
        self.assertEqual((new, windows), (old, old_windows))


@unittest.skipUnless(INPUT.exists(), "frozen sensor input not present")
class EquivalenceTests(unittest.TestCase):
    """Legacy vs engine on the frozen input: byte-identical outputs."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location("cmp", v.REPO_ROOT / "scripts/compare_detector_engine.py")
        cls.cmp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.cmp)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.results = cls.cmp.compare(Path(cls.tmp.name) / "work")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _check(self, name):
        rows_ = self.results[name]
        self.assertTrue(rows_)
        for r in rows_:
            self.assertEqual(r["result"], "bytes_equal", json.dumps(r, ensure_ascii=False)[:400])

    def test_v3(self):
        self._check("v3")

    def test_v3_literal(self):
        self._check("v3_literal")

    def test_v3_1(self):
        self._check("v3_1")
        self.assertIn("monitor_windows.json", [r["file"] for r in self.results["v3_1"]])


if __name__ == "__main__":
    unittest.main()
