"""산출물·실행 흐름·평가기 연결 시험. mock 공급자와 가짜 응답만 쓴다. 평가기에는 가짜 정답 CSV와 가짜 임베더를 준다."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_b_helpers as h  # noqa: E402

from imaks_kg.eval.cli import run_evaluation  # noqa: E402
from imaks_kg.eval.gold import MANIFEST_PATH, known_doc_ids  # noqa: E402
from imaks_kg.eval.predictions import load_predictions  # noqa: E402
from imaks_kg.extract.artifacts import file_sha256  # noqa: E402
from imaks_kg.extract.providers.mock import ScriptedByDocMock  # noqa: E402
from imaks_kg.extract.run import revalidate, run_extraction  # noqa: E402
from tests_fake_embedder import FakeEmbedder  # noqa: E402


def read_csv(p):
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def do_run(tmp, responses=None, run_id="mock-t1", retries=1, mode="scoring", models=("m1",)):
    store = h.real_store()
    ex, reg = h.make_registered_example(tmp)
    cfg = h.make_cfg(tmp, ex, mode=mode, models=models)
    resp = responses or {"SOP-001": json.dumps(h.sop001_response(store)), "SOP-003": json.dumps(h.sop003_response(store))}
    prov = {"gemini": ScriptedByDocMock("gemini", resp)}
    rr = run_extraction(cfg, docs=["SOP-001", "SOP-003"], run_id=run_id, mock=True, providers=prov, registry_path=reg,
                        out_root=Path(tmp) / "out", validation_retries=retries, sleep=lambda s: None)
    return cfg, rr, prov, reg


class Outputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._t = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._t.name)
        cls.cfg, cls.rr, cls.prov, cls.reg = do_run(cls.tmp)
        cls.d = cls.rr.out_dir

    @classmethod
    def tearDownClass(cls):
        cls._t.cleanup()

    def jl(self, name):
        return [json.loads(x) for x in (self.d / name).read_text(encoding="utf-8").splitlines() if x.strip()]

    def test_six_files_exist(self):
        for n in ("predictions.jsonl", "rules_all.jsonl", "rules_valid.jsonl", "flags.csv", "run_summary.json", "eval_meta.json"):
            self.assertTrue((self.d / n).is_file(), n)

    def test_predictions_keep_flagged_rules_and_valid_excludes_them(self):
        preds, allr, valid = self.jl("predictions.jsonl"), self.jl("rules_all.jsonl"), self.jl("rules_valid.jsonl")
        self.assertEqual((len(preds), len(allr), len(valid)), (6, 6, 3))
        self.assertTrue(all(p["model"] == "m1" for p in preds))
        self.assertEqual(sum(1 for p in preds if p["flags"]), 3)
        self.assertTrue(all(not v["flags"] for v in valid))
        self.assertIn("ruleSeverity", preds[0])

    def test_flags_csv(self):
        rows = read_csv(self.d / "flags.csv")
        self.assertEqual(sorted(r["flag"] for r in rows),
                         ["evidence_not_found", "id_not_in_allowlist", "table_position_out_of_range"])
        self.assertTrue(all(r["excluded_from_kg"] == "yes" for r in rows))

    def test_summary_and_eval_meta(self):
        s = json.loads((self.d / "run_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(s["run_mode"], "scoring")
        self.assertTrue(s["mock"])
        self.assertEqual(s["models_used"], ["m1"])
        self.assertEqual(s["counts"]["rules_all"], 6)
        self.assertEqual(s["by_flag"]["evidence_not_found"], 1)
        for k in ("prompt_sha256", "schema_sha256", "example_sha256"):
            self.assertEqual(len(s[k]), 64)
        m = json.loads((self.d / "eval_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(m["actual_models"], ["gemini/m1"])
        self.assertEqual(m["requested_models"], ["gemini/m1"])
        self.assertEqual(m["example_sha256"], s["example_sha256"])

    def test_no_forbidden_json_keys_in_outputs(self):
        bad = {"status", "quality", "alarms", "day", "shift", "batch_id", "nominal", "sever" + "ity"}

        def keys(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    yield k
                    yield from keys(v)
            elif isinstance(o, list):
                for v in o:
                    yield from keys(v)
        for n in ("predictions.jsonl", "rules_all.jsonl", "rules_valid.jsonl"):
            for r in self.jl(n):
                self.assertFalse(set(keys(r)) & bad, n)
        for n in ("run_summary.json", "eval_meta.json"):
            self.assertFalse(set(keys(json.loads((self.d / n).read_text(encoding="utf-8")))) & bad, n)

    def test_call_log_has_run_mode_and_model(self):
        rows = [json.loads(x) for p in Path(self.cfg.log_dir).glob("calls_*.jsonl") for x in p.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(rows)
        self.assertTrue(all(r["run_mode"] == "scoring" for r in rows))

    def test_cache_marked_validated_and_reused(self):
        prov = {"gemini": ScriptedByDocMock("gemini", {})}
        rr = run_extraction(self.cfg, docs=["SOP-001", "SOP-003"], run_id="mock-t1b", mock=True, providers=prov,
                            registry_path=self.reg, out_root=self.tmp / "out", sleep=lambda s: None)
        self.assertEqual(prov["gemini"].calls, [])          # 검증을 통과한 응답은 캐시에서 재사용(호출 없음)
        self.assertTrue(all(o.cache_hit for o in rr.outcomes))
        self.assertEqual(file_sha256(rr.out_dir / "predictions.jsonl"), file_sha256(self.d / "predictions.jsonl"))

    def test_predictions_load_in_evaluator_loader(self):
        known = known_doc_ids(MANIFEST_PATH)
        preds = load_predictions(self.d / "predictions.jsonl", known)
        self.assertEqual(len(preds), 6)
        self.assertEqual(preds[0].model, "m1")
        self.assertEqual(preds[0].sensors, ("ST02_SEALING_TMP",))

    def test_end_to_end_with_fake_gold_and_fake_embedder(self):
        preds = load_predictions(self.d / "predictions.jsonl", known_doc_ids(MANIFEST_PATH))
        gold = self.tmp / "fake_gold.csv"       # 가짜 정답: 예측 2개와 같은 문장 + 짝 없는 1개
        with gold.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["ruleId", "class", "condition", "action", "source", "sensor"])
            w.writerow(["F1", preds[0].cls, preds[0].condition, preds[0].action, preds[0].doc, "ST02_SEALING_TMP"])
            w.writerow(["F2", preds[1].cls, preds[1].condition, preds[1].action, preds[1].doc, ""])
            w.writerow(["F3", "AccessRule", "totally unrelated made up gold text", "none", "SOP-004", ""])
        out = self.tmp / "eval_out"
        m = run_evaluation(self.d / "predictions.jsonl", out, gold_path=gold, meta_path=self.d / "eval_meta.json",
                           embedder=FakeEmbedder())
        self.assertEqual(m["main_report"]["tp"], 2)
        self.assertEqual(m["main_report"]["fn"], 1)
        self.assertEqual(m["main_report"]["fp"], 4)
        lock = json.loads((out / "pre_evaluation_lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["predictions_sha256"], file_sha256(self.d / "predictions.jsonl"))
        self.assertEqual(lock["meta"]["actual_models"], ["gemini/m1"])


class Failures(unittest.TestCase):
    def test_validation_retry_then_success(self):
        with tempfile.TemporaryDirectory() as t:
            store = h.real_store()
            good = json.dumps(h.sop001_response(store))
            cfg, rr, prov, _ = do_run(t, {"SOP-001": ["{\"rules\": 1}", good], "SOP-003": json.dumps(h.sop003_response(store))})
            o = [x for x in rr.outcomes if x.document_id == "SOP-001"][0]
            self.assertEqual((o.outcome, o.validation_attempts), ("validated", 2))
            self.assertEqual(prov["gemini"].calls.count(("SOP-001", "extract")), 2)

    def test_schema_failure_is_recorded_not_validated_not_cached(self):
        with tempfile.TemporaryDirectory() as t:
            cfg, rr, prov, reg = do_run(t, {"SOP-001": "{\"rules\": 1}"}, retries=1)
            o = [x for x in rr.outcomes if x.document_id == "SOP-001"][0]
            self.assertEqual((o.outcome, o.validation_attempts), ("schema_failed", 2))
            self.assertEqual(rr.summary["counts"]["responses_accepted"], 1)   # SOP-003은 기본 빈 응답이라 통과
            self.assertEqual(list(Path(cfg.cache_dir).glob("*.validated.json")).__len__(), 1)
            rows = read_csv(rr.out_dir / "flags.csv")
            self.assertTrue(any(r["flag"] == "schema_error" and r["document_id"] == "SOP-001" for r in rows))

    def test_call_failure_skips_document(self):
        with tempfile.TemporaryDirectory() as t:
            store = h.real_store()
            ex, reg = h.make_registered_example(Path(t))
            cfg = h.make_cfg(Path(t), ex)
            from imaks_kg.extract.providers.mock import MockProvider
            prov = {"gemini": MockProvider("gemini", ("400",))}
            rr = run_extraction(cfg, docs=["SOP-003"], run_id="mock-f", mock=True, providers=prov, registry_path=reg,
                                out_root=Path(t) / "out", sleep=lambda s: None)
            self.assertEqual(rr.outcomes[0].outcome, "call_failed")
            self.assertEqual(rr.summary["counts"]["predictions"], 0)

    def test_scoring_mode_refuses_two_models_and_empty_model(self):
        with tempfile.TemporaryDirectory() as t:
            ex, reg = h.make_registered_example(Path(t))
            from imaks_kg.extract.config import ConfigError
            with self.assertRaises(ConfigError):
                h.make_cfg(Path(t), ex, mode="scoring", models=("a", "b"))
            cfg = h.make_cfg(Path(t), ex, mode="production", models=("a", "b"))
            self.assertEqual(len(cfg.chain()), 2)
            empty = h.make_cfg(Path(t), ex)
            chain_model = empty.providers["gemini"].models[0]
            object.__setattr__(chain_model, "id", "")
            with self.assertRaises(ConfigError):
                run_extraction(empty, docs=["SOP-003"], registry_path=reg, out_root=Path(t) / "o")


class Revalidate(unittest.TestCase):
    def test_revalidate_same_result_without_llm_calls(self):
        with tempfile.TemporaryDirectory() as t:
            cfg, rr, prov, _ = do_run(t)
            calls_before = {k: list(v.calls) for k, v in prov.items()}
            rr2 = revalidate("mock-t1", cfg, out_run_id="mock-t1-re", out_root=Path(t) / "out")
            self.assertEqual({k: list(v.calls) for k, v in prov.items()}, calls_before)
            self.assertEqual(file_sha256(rr2.out_dir / "predictions.jsonl"), file_sha256(rr.out_dir / "predictions.jsonl"))
            self.assertEqual(file_sha256(rr2.out_dir / "rules_all.jsonl"), file_sha256(rr.out_dir / "rules_all.jsonl"))
            rr3 = revalidate("mock-t1", cfg, out_root=Path(t) / "out")   # 같은 폴더: 내용이 같으면 통과
            self.assertEqual(rr3.run_id, "mock-t1")

    def test_tampered_response_is_detected(self):
        with tempfile.TemporaryDirectory() as t:
            cfg, rr, prov, _ = do_run(t)
            f = next((Path(cfg.log_dir) / "extract_runs" / "mock-t1" / "responses").glob("SOP-001*"))
            f.write_bytes(f.read_bytes() + b" ")
            with self.assertRaises(ValueError):
                revalidate("mock-t1", cfg, out_run_id="x", out_root=Path(t) / "out")


if __name__ == "__main__":
    unittest.main()
