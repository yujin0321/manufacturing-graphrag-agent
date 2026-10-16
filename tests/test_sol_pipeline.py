import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from imaks_kg.kg_build import sol_extract as sol
from imaks_kg.eval.team_protocol.match import assign
from imaks_kg.eval.team_protocol.metrics import evaluate
from imaks_kg.eval.team_protocol.predictions import Prediction
from imaks_kg.eval.team_protocol.gold import GoldRule
from imaks_kg.eval import sol_evaluate


def packet():
    return {"document_id": "SOP-001", "source_sha256": "a" * 64,
            "allowed_stations": ["QZ_MIXER"], "allowed_sensors": [],
            "units": [{"unit_id": "u1", "kind": "text", "page": 1,
                       "text": "When violet flashes,\n latch the hatch."}],
            "page_context": [{"page": 1, "text": "Title\nWhen violet flashes,\n latch the hatch."}]}


def value():
    return {"rules": [{"class": "OperationalRule", "printed_rule_id": "",
                      "condition": "Violet flashes", "action": "Latch the hatch", "ruleSeverity": "",
                      "priority": "", "numeric": {k: "" for k in ["nominal", "critLo", "warnLo", "warnHi", "critHi"]},
                      "sensors": [], "action_targets": ["QZ_MIXER"],
                      "evidence": [{"unit_id": "u1", "quote": "When violet flashes, latch the hatch."}]}],
            "coverage": [{"unit_id": "u1", "disposition": "included"}]}


def response():
    return {"status": "completed", "model": sol.MODEL,
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(value())}]}],
            "usage": {"input_tokens": 30, "output_tokens": 20}}


class SolTests(unittest.TestCase):
    def test_source_quote_offsets_and_hash(self):
        rows, prov, audit = sol.normalize(value(), packet())
        self.assertTrue(rows[0]["kg_eligible"])
        props = prov[0]["properties"]
        source = packet()["page_context"][0]["text"]
        self.assertEqual(source[props["charStart"]:props["charEnd"]], props["sourceQuote"])
        self.assertEqual(sol.digest(props["sourceQuote"].encode()), props["textSha256"])
        self.assertFalse(audit["coverage"]["missing_units"])

    def test_invalid_quote_is_not_silently_removed_from_predictions(self):
        v = value()
        v["rules"][0]["evidence"][0]["quote"] = "Not in the document"
        rows, _, _ = sol.normalize(v, packet())
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["kg_eligible"])
        self.assertIn("evidence_not_found", rows[0]["validation_flags"])

    def test_duplicate_printed_ids_preserve_both_rules(self):
        v = value()
        v["rules"].append(copy.deepcopy(v["rules"][0]))
        rows, _, _ = sol.normalize(v, packet())
        self.assertEqual(len({r["identifier"] for r in rows}), 2)

    def test_refusal_incomplete_wrong_model_fail(self):
        for changed in [{"status": "incomplete"}, {"model": "different-model"},
                        {"output": [{"content": [{"type": "refusal"}]}]}]:
            with self.assertRaises(ValueError):
                sol.parse_response({**response(), **changed})

    def test_request_has_full_input_and_single_model_schema(self):
        p = packet()
        p["units"][0]["text"] = "x" * 5000
        r = sol.request_for(p)
        self.assertIn("x" * 5000, r["input"][1]["content"])
        self.assertEqual(r["model"], sol.MODEL)
        self.assertTrue(r["text"]["format"]["strict"])
        self.assertNotIn("temperature", r)
        self.assertFalse(r["store"])

    def test_resume_does_not_rebill_and_tamper_fails(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            packets = {"SOP-001": packet()}
            requests = {"SOP-001": sol.request_for(packet())}
            manifest = {"requested_model": sol.MODEL, "documents": ["SOP-001"],
                        "request_sha256": {"SOP-001": sol.digest(sol.json_bytes(requests["SOP-001"]))}}
            client = Mock()
            client.responses.create.return_value.model_dump.return_value = response()
            with patch.object(sol, "prepare", return_value=(packets, requests, manifest)), \
                 patch.object(sol, "build_station_sensor", return_value=([], [], [])), \
                 patch("imaks_kg.kg_build.structure_completion.document_flows", return_value=([], [])), \
                 patch.object(sol, "build_documents", return_value=[]):
                sol.run(out=out, client=client)
                sol.run(out=out, client=client)
                self.assertEqual(client.responses.create.call_count, 1)
                (out / "responses/SOP-001.json").write_text("{}")
                with self.assertRaises(ValueError):
                    sol.run(out=out, client=client)
                self.assertEqual(client.responses.create.call_count, 1)

    def test_failed_attempt_is_not_automatically_retried(self):
        with tempfile.TemporaryDirectory() as d:
            client = Mock()
            client.responses.create.side_effect = TimeoutError("sensitive text")
            manifest = {"request_sha256": {"SOP-001": "hash"}}
            with patch.object(sol, "prepare", return_value=({"SOP-001": packet()}, {"SOP-001": {}}, manifest)):
                for _ in range(2):
                    with self.assertRaises(RuntimeError):
                        sol.run(out=d, client=client)
            self.assertEqual(client.responses.create.call_count, 1)
            self.assertNotIn("sensitive text", (Path(d) / "responses/SOP-001.error.json").read_text())


class EvaluationTests(unittest.TestCase):
    def test_cardinality_precedes_similarity(self):
        pairs = assign(np.array([[1, .6], [.6, .59]]), .6)
        self.assertEqual({(a, b) for a, b, _ in pairs}, {(0, 1), (1, 0)})

    def test_invalid_pairs_never_contribute_and_threshold_is_exact(self):
        a = np.array([[.8, .9], [.59, .01]])
        self.assertEqual([(i, j) for i, j, _ in assign(a, .6)], [(0, 1)])
        self.assertEqual(assign(np.array([[.6 - 1e-10]]), .6), [])

    def test_same_document_class_unrestricted_datasheet_excluded(self):
        class SameEmbedder:
            def encode(self, texts):
                return np.tile([1., 0.], (len(texts), 1))
        preds = [Prediction("p1", "SOP-001", "AccessRule", "c", "a"),
                 Prediction("p2", "DS-DEMO", "AccessRule", "c", "a")]
        gold = [GoldRule("g1", "OperationalRule", "c", "a", "SOP-001"),
                GoldRule("g2", "AccessRule", "c", "a", "SOP-002")]
        m, _, _ = evaluate(preds, gold, SameEmbedder(), processed_docs={"SOP-001", "SOP-002"})
        self.assertEqual((m["main_report"]["tp"], m["main_report"]["fp"], m["main_report"]["fn"]), (1, 0, 1))
        self.assertEqual(m["main_report"]["class_aware"]["tp"], 0)
        self.assertEqual(m["processed_scope_report"]["n_gold"], 2)

    def test_lock_written_before_gold_open(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); build = root / "build"; build.mkdir()
            pred = {"document_id": "SOP-001", "class": "OperationalRule", "condition": "c", "action": "a", "model": sol.MODEL}
            (build / "predictions.jsonl").write_text(json.dumps(pred) + "\n")
            meta = {"state": "complete", "actual_models": [sol.MODEL], "prediction_count": 1,
                    "documents": ["SOP-001"], "prediction_sha256": sol_evaluate.file_sha256(build / "predictions.jsonl")}
            (build / "extraction_summary.json").write_text(json.dumps(meta))
            manifest = root / "manifest.csv"; manifest.write_text("doc_id\nSOP-001\n")
            def gold_loader(*args):
                self.assertTrue((root / "eval/pre_evaluation_lock.json").exists())
                raise RuntimeError("stop before reading reference")
            fake = SimpleNamespace(model_name="test-only", revision="test-only")
            with patch.object(sol_evaluate.PreprocessedLayout, "detect", return_value=SimpleNamespace(doc_manifest=manifest)), \
                 patch.object(sol_evaluate, "load_gold", side_effect=gold_loader):
                with self.assertRaisesRegex(RuntimeError, "stop before"):
                    sol_evaluate.run(build, root / "unused.csv", root / "eval", embedder=fake)


if __name__ == "__main__":
    unittest.main()
