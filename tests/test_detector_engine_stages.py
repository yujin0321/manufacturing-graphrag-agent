"""Engine stages 2-5: KG overlay, incident tools, v3.2 options, label-free
benchmark, evaluator median. No labels are read; no API calls (mock only)."""
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from rdflib import Literal, RDF, URIRef

from imaks_kg.detection.engine import benchmark, config, overlay, postprocess
from imaks_kg.detection.engine import run as engine
from imaks_kg.rag import agent_contract as contract
from imaks_kg.rag import comparison as c
from imaks_kg.rag import vector as v

INPUT = v.REPO_ROOT / "preprocessed/sensors/input/ts_input.csv"
CHUNKS = v.REPO_ROOT / "preprocessed/documents/chunks.jsonl"
T0 = datetime(2026, 1, 8, 8, 0, 0)


def iso(minutes):
    return (T0 + timedelta(minutes=minutes)).isoformat()


class V32OptionTests(unittest.TestCase):
    CFG = {"id_prefix": {"alarm": "det32-", "incident": "inc32-"}, "monitor_anchor": "warning_trigger",
           "link_policy": "verified", "severity_policy": "with_document_tags"}
    PAIR = {"cause_sensor": "C", "effect_sensor": "E", "rule_ids": ["RULE-ST02-04"], "kg_nodes": ["n"],
            "window_min": 90, "window_rule_id": "SOP-002-EX-27", "effect_direction": "below_nominal"}
    SENSORS = {"E": {"nominal": 1.2}}

    def setUp(self):
        self.alarms = {
            "m": {"id": "m", "kind": "kg_maint_drift", "trigger_at": iso(0), "rule_id": "MAINT-02"},
            "w": {"id": "w", "kind": "kg_threshold_warning", "trigger_at": iso(20), "rule_id": "X:warning"}}
        self.cause = {"id": "inc32-c", "sensor_id": "C", "start": iso(0), "kinds": ["kg_maint_drift", "kg_threshold_warning"],
                      "alarm_ids": ["m", "w"]}

    def signal(self, minutes, value="1.0"):
        return {"id": f"s{minutes}", "sensor_id": "E", "kind": "sop002_drift_slope", "trigger_at": iso(minutes),
                "condition_start": iso(minutes), "last_positive_at": iso(minutes), "trigger_value": value,
                "unit": "m/s", "positive_samples": 1, "report_split": "test"}

    def test_config_v3_2_loads_and_legacy_configs_keep_legacy_policies(self):
        cfg = config.load("v3_2")
        self.assertEqual((cfg["monitor_anchor"], cfg["link_policy"], cfg["severity_policy"]),
                         ("warning_trigger", "verified", "with_document_tags"))
        for name in ("v3", "v3_literal", "v3_1"):
            cfg = config.load(name)
            self.assertEqual((cfg["link_policy"], cfg["severity_policy"]), ("legacy", "sop002_bands"))

    def test_monitor_window_starts_at_warning_alarm(self):
        sigs = [self.signal(10), self.signal(30)]
        legacy, _ = postprocess.monitor([self.cause], sigs, [self.PAIR], self.SENSORS,
                                        {**self.CFG, "monitor_anchor": "incident_start"}, self.alarms)
        new, windows = postprocess.monitor([self.cause], sigs, [self.PAIR], self.SENSORS, self.CFG, self.alarms)
        self.assertEqual([a["source_signal"] for a in legacy], ["s10", "s30"])
        self.assertEqual([a["source_signal"] for a in new], ["s30"])  # 10 min is before the WARNING (20 min)
        self.assertEqual((windows[0]["from"], windows[0]["cause_alarm"]), (iso(20), "w"))
        self.assertEqual(new[0]["monitor_cause_alarm"], "w")

    def _effect(self, start, value="1.0", monitored_by=None):
        alarm = {"id": "e1", "kind": "kg_correlation_monitor" if monitored_by else "kg_threshold_warning",
                 "trigger_at": start, "trigger_value": value, "rule_id": "R"}
        if monitored_by:
            alarm["monitored_by"] = monitored_by
        effect = {"id": "inc32-e", "sensor_id": "E", "start": start, "alarm_ids": ["e1"], "anomaly_type": "DRIFT"}
        return effect, {**self.alarms, "e1": alarm}

    def test_verified_link_requires_window_after_warning_and_direction(self):
        effect, alarms = self._effect(iso(30))
        links = postprocess.verified_links([self.cause, effect], [self.PAIR], alarms, self.SENSORS, self.CFG)
        self.assertEqual((len(links), links[0]["cause_alarm"], effect["anomaly_type"]), (1, "w", "CORRELATED"))
        self.assertEqual(effect["pre_correlation_type"], "DRIFT")
        for start, value in ((iso(10), "1.0"), (iso(30), "1.3"), (iso(200), "1.0")):  # before WARNING, wrong direction, late
            effect, alarms = self._effect(start, value)
            self.assertEqual(postprocess.verified_links([self.cause, effect], [self.PAIR], alarms,
                                                        self.SENSORS, self.CFG), [], start)

    def test_verified_link_reuses_monitoring_cause(self):
        effect, alarms = self._effect(iso(30), monitored_by="inc32-other")
        self.assertEqual(postprocess.verified_links([self.cause, effect], [self.PAIR], alarms, self.SENSORS, self.CFG), [])

    def test_document_severity_tag_raises_but_never_lowers(self):
        tags = {"RULE-SRV01-02": "CRITICAL", "RULE-ST04-01": "WARNING"}
        doc = [{"kind": "kg_document_rule", "rule_id": "RULE-SRV01-02"}]
        self.assertEqual(postprocess.incident_severity(doc, {"severity_policy": "sop002_bands"}, tags), "ADVISORY")
        self.assertEqual(postprocess.incident_severity(doc, self.CFG, tags), "CRITICAL")
        crit = [{"kind": "kg_threshold_critical", "rule_id": "B"}, {"kind": "kg_document_rule", "rule_id": "RULE-ST04-01"}]
        self.assertEqual(postprocess.incident_severity(crit, self.CFG, tags), "CRITICAL")


class EvaluatorMedianTests(unittest.TestCase):
    def test_statistics_median_reported_next_to_legacy_value(self):
        spec = importlib.util.spec_from_file_location("ev", v.REPO_ROOT / "scripts/evaluate_detector_events.py")
        ev = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ev)
        gold = [{"sensor_id": "S", "label": "SPIKE", "start": iso(i * 100), "end": iso(i * 100 + 5)} for i in range(4)]
        dets = [{"sensor_id": "S", "kind": "k", "rule_id": "r", "trigger_at": iso(i * 100 + lag),
                 "last_positive_at": iso(i * 100 + lag)} for i, lag in enumerate((0, 1, 2, 4))]
        r = ev.evaluate(dets, gold, 0)["ALL"]
        self.assertEqual((r["median_latency_min"], r["median_latency_min_statistics"]), (2.0, 1.5))


class BenchmarkScoringTests(unittest.TestCase):
    def test_score_and_summary_on_synthetic_result(self):
        truth = [{"sensor_id": "S", "type": "SPIKE", "variant": "1", "start": iso(0), "end": iso(1)},
                 {"sensor_id": "E", "type": "CORRELATED", "variant": "x", "start": iso(60), "end": iso(90),
                  "cause_sensor": "C", "cause_start": iso(0), "cause_end": iso(2)},
                 {"sensor_id": "E", "type": "DECOY_NO_LINK", "variant": "d", "start": iso(300), "end": iso(330),
                  "cause_sensor": "C", "cause_start": iso(280), "cause_end": iso(312)}]
        inc = [{"id": "a", "sensor_id": "S", "start": iso(0), "end": iso(1), "anomaly_type": "SPIKE"},
               {"id": "c", "sensor_id": "C", "start": iso(0), "end": iso(2), "anomaly_type": "OUT_OF_RANGE"},
               {"id": "e", "sensor_id": "E", "start": iso(70), "end": iso(90), "anomaly_type": "CORRELATED"}]
        res = {"incidents": inc, "correlations": [{"cause_incident": "c", "effect_incident": "e"}]}
        rows = benchmark.score(res, truth)["rows"]
        s = benchmark.summarize(rows)
        self.assertEqual((s["SPIKE"]["detected"], s["CORRELATED"]["link_correct"]), (1, 1))
        self.assertEqual((s["DECOY_NO_LINK"]["detected"], s["DECOY_NO_LINK"]["false_link"]), (0, 0))
        self.assertEqual(s["ALL"]["injected"], 2)  # decoys are not counted as anomalies to detect
        self.assertEqual(rows[1]["latency_min"], 10.0)


@unittest.skipUnless(INPUT.exists() and CHUNKS.exists(), "frozen inputs not present")
class PipelineStageTests(unittest.TestCase):
    """Real engine run -> overlay -> tools (one shared run)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.run_dir, cls.ov_dir = root / "v3_1", root / "overlay"
        engine.run("v3_1", cls.run_dir)
        cls.base = c.load_graph()
        cls.report = overlay.load(cls.run_dir, cls.ov_dir, base=cls.base)
        from imaks_kg.rag import incident_tools as it
        cls.it = it
        cls.store = it.IncidentStore(cls.run_dir, cls.ov_dir, base=cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # ---- stage 2
    def test_overlay_maps_every_incident_and_passes_validation(self):
        incidents = v.read(self.run_dir / "incidents.json")
        self.assertEqual(self.report["events"], len(incidents))
        self.assertEqual((self.report["shacl_blocking"], self.report["loader_errors"], self.report["guards_L4"]), ([], [], []))
        self.assertEqual(self.report["causal_links"], 0)
        g = self.store.overlay
        self.assertFalse(list(g.subjects(RDF.type, c.IM.CausalLink)))
        self.assertEqual(len(list(g.subjects(c.IM.triggers, None))), len(incidents))

    def test_overlay_rejects_broken_graphs(self):
        g0, _ = overlay.build_overlay(self.run_dir, self.base)
        event = next(g0.subjects(RDF.type, c.IM.Correlated))
        g = g0.__class__()
        for t in g0:
            g.add(t)
        g.remove((None, c.IM.triggers, event))
        g.add((event, RDF.type, c.IM.Spike))  # two subclasses
        self.assertTrue(overlay.shacl_checks(g, self.base)["shacl_blocking"])
        g2 = g0.__class__()
        for t in g0:
            g2.add(t)
        g2.add((event, overlay.DET.matchedRule, URIRef("https://example.org/imaks/id/NOT-A-RULE")))
        g2.add((event, overlay.DET.typeReason, Literal("GT-0009")))
        g2.add((event, URIRef(str(c.IM) + "datasetSeverity"), Literal("CRITICAL")))
        errors = overlay.loader_checks(g2, self.base)
        self.assertTrue(any("does not resolve" in e for e in errors))
        self.assertTrue(any("GT-style" in e for e in errors))
        self.assertTrue(any("dataset label" in e for e in errors))
        with self.assertRaises(FileExistsError):
            overlay.load(self.run_dir, self.ov_dir, base=self.base)  # never overwrites

    def test_overlay_refuses_modified_engine_output(self):
        tampered = Path(self.tmp.name) / "tampered"
        tampered.mkdir()
        for p in self.run_dir.iterdir():
            (tampered / p.name).write_bytes(p.read_bytes())
        (tampered / "incidents.json").write_text("[]\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            overlay.load(tampered, Path(self.tmp.name) / "ov_tampered", base=self.base)

    # ---- stage 3
    def test_tool_session_selection_budget_and_errors(self):
        it = self.it
        root = Path(self.tmp.name)
        s = it.IncidentToolSession(root / "s1", store=self.store)
        listed = s.execute("list_incidents", {"anomaly_type": "CORRELATED"})
        self.assertEqual(listed["status"], "ok")
        iid = listed["data"]["items"][0]["id"]
        self.assertEqual(s.execute("get_incident_evidence", {"incident_id": iid})["error"]["code"],
                         "incident_selection_required")
        s2 = it.IncidentToolSession(root / "s2", store=self.store, explicit_incident_ids=[iid])
        ev = s2.execute("get_incident_evidence", {"incident_id": iid})
        self.assertEqual(ev["status"], "ok")
        self.assertIn("RULE-ST02-04", [r["rule_id"] for r in ev["data"]["matched_rules"]])
        self.assertTrue(ev["data"]["untrusted_reference_documents"])
        corr = s2.execute("get_correlated_incidents", {"incident_id": iid})
        self.assertEqual(corr["data"]["correlation_candidates"][0]["status"],
                         "rule_pattern_match_not_confirmed_causality")
        self.assertEqual(s2.execute("list_incidents", {})["status"], "ok")  # 3rd call: still inside the limit
        self.assertEqual(s2.execute("list_incidents", {})["error"]["code"], "tool_limit_exceeded")
        with self.assertRaises(contract.ContractError):
            it.validate_call("get_incident_evidence", {"incident_id": "det-0"})
        with self.assertRaises(contract.ContractError):
            it.validate_call("list_incidents", {"severity": "HIGH"})
        unique = it.IncidentToolSession(root / "s3", store=self.store)
        one = unique.execute("list_incidents", {"anomaly_type": "STUCK"})
        self.assertEqual(one["data"]["total_matches"], 1)
        self.assertEqual(unique.execute("get_incident_evidence", {"incident_id": one["data"]["items"][0]["id"]})["status"], "ok")

    def test_store_refuses_overlay_from_other_run(self):
        other = Path(self.tmp.name) / "other_run"
        engine.run("v3", other)
        with self.assertRaises(ValueError):
            self.it.IncidentStore(other, self.ov_dir, base=self.base)

    def test_incident_explanation_and_demo_paths_with_mock_model(self):
        from imaks_kg.rag import demo, event_explain
        iid = next(i["id"] for i in self.store.incidents if i["anomaly_type"] == "CORRELATED")
        seen = {}

        def fake(endpoint, payload, api_dir):
            seen["payload"] = payload
            return ({"choices": [{"finish_reason": "stop", "message": {"content": "설명"}}], "model": payload["model"],
                     "usage": {}}, {"cache_hit": False})

        out = Path(self.tmp.name) / "answer"
        result = event_explain.answer_incident(iid, out, call=fake, store=self.store)
        self.assertEqual(result["status"], "complete")
        self.assertIn("입증된 인과라고 쓰지 않는다", seen["payload"]["messages"][0]["content"])
        evidence = json.loads(seen["payload"]["messages"][1]["content"])["evidence"]
        self.assertTrue(evidence["correlation_candidates"])
        self.assertEqual(demo.presentation(out)["question"], result["question"])
        self.assertEqual(len(demo.incident_presentation(self.store)["incidents"]), len(self.store.incidents))


if __name__ == "__main__":
    unittest.main()
