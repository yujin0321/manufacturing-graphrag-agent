"""재시도와 fallback 테스트: mock 공급자와 주입한 sleep/난수만 쓴다."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_a_helpers import Sleeper, make_config, mocks, read_log, zero_rng  # noqa: E402

from imaks_kg.extract.client import extract_call  # noqa: E402
from imaks_kg.extract.config import RetryPolicy  # noqa: E402
from imaks_kg.extract.providers.base import LLMRequest, TransientError  # noqa: E402
from imaks_kg.extract.retry import backoff_delay, run_with_retry  # noqa: E402

REQ = LLMRequest(prompt="doc", doc_id="DOC-X")


def go(cfg, provs, req=REQ, rng=zero_rng):
    sl = Sleeper()
    res = extract_call(cfg, req, providers=provs, sleep=sl, rng=rng, use_cache=False)
    return res, sl


class RetryTests(unittest.TestCase):
    def test_backoff_sequence_1_2_4_8_and_five_attempts(self):
        sl = Sleeper()
        def boom():
            raise TransientError("x", error_kind="http_503")
        out = run_with_retry(boom, RetryPolicy(), sl, zero_rng)
        self.assertFalse(out.ok)
        self.assertEqual(out.attempts, 5)  # 재시도 4회 = 총 5회 시도
        self.assertEqual(sl.delays, [1.0, 2.0, 4.0, 8.0])
        self.assertEqual(out.retry_reasons, ["http_503"] * 4)

    def test_delay_cap_and_longer_sequence(self):
        pol = RetryPolicy(max_retries=8, base_delay_s=1, max_delay_s=60, jitter_ratio=0)
        self.assertEqual([backoff_delay(i, pol, zero_rng) for i in range(1, 9)], [1, 2, 4, 8, 16, 32, 60, 60])

    def test_jitter_adds_up_to_ratio_but_is_capped(self):
        pol = RetryPolicy(base_delay_s=1, max_delay_s=60, jitter_ratio=0.25)
        self.assertEqual(backoff_delay(1, pol, lambda: 1.0), 1.25)
        self.assertEqual(backoff_delay(7, pol, lambda: 1.0), 60)

    def test_no_retry_for_400_402_403(self):
        for kind in ("400", "402", "auth"):
            with tempfile.TemporaryDirectory() as t:
                cfg = make_config(t, gemini=("g1",), openai=("o1",))
                provs = mocks(g=(kind,), o=(kind,))
                res, sl = go(cfg, provs)
                self.assertEqual(sl.delays, [], kind)
                self.assertEqual(len(provs["gemini"].calls), 1, kind)

    def test_retry_then_success_for_429_503_timeout(self):
        for kind in ("429", "503", "timeout"):
            with tempfile.TemporaryDirectory() as t:
                cfg = make_config(t)
                provs = mocks(g=(kind, "ok"))
                res, sl = go(cfg, provs)
                self.assertEqual(res.status, "success", kind)
                self.assertEqual(res.model_id, "g1")
                self.assertEqual(sl.delays, [1.0])
                self.assertEqual(provs["gemini"].calls, ["g1", "g1"])

    def test_possible_duplicate_billing_recorded_after_timeout_retry(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_config(t)
            res, _ = go(cfg, mocks(g=("timeout", "ok")))
            self.assertTrue(res.possible_duplicate_billing)
            rows = [r for r in read_log(cfg) if r["record_type"] == "model_call"]
            self.assertTrue(rows[0]["possible_duplicate_billing"])
            self.assertEqual(rows[0]["retry_reasons"], ["timeout"])
            self.assertEqual(rows[0]["attempts"], 2)

    def test_no_duplicate_flag_for_plain_503(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_config(t)
            res, _ = go(cfg, mocks(g=("503", "ok")))
            self.assertFalse(res.possible_duplicate_billing)


class FallbackTests(unittest.TestCase):
    def test_order_same_model_then_other_model_then_other_provider(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_config(t)
            provs = mocks(g=("503",), o=("ok",))
            res, sl = go(cfg, provs)
            self.assertEqual(provs["gemini"].calls, ["g1"] * 5 + ["g2"] * 5)
            self.assertEqual(provs["openai"].calls, ["o1"])
            self.assertEqual((res.status, res.provider, res.model_id), ("success", "openai", "o1"))
            self.assertEqual(sl.delays, [1.0, 2.0, 4.0, 8.0] * 2)

    def test_second_model_of_same_provider_answers(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_config(t)
            provs = mocks(g=("400", "ok"))
            res, _ = go(cfg, provs)
            self.assertEqual((res.provider, res.model_id), ("gemini", "g2"))
            self.assertEqual(provs["openai"].calls, [])

    def test_all_fail_records_failure_and_skips_document_without_exception(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_config(t)
            res, _ = go(cfg, mocks(g=("503",), o=("429",)))
            self.assertEqual(res.status, "failed")
            self.assertTrue(res.skipped_document)
            self.assertFalse(res.complete)
            self.assertEqual(res.text, "")
            self.assertIn("모든 모델 실패", res.failure_reason)
            parent = [r for r in read_log(cfg) if r["record_type"] == "extract_call"][0]
            self.assertEqual(parent["status"], "failed")
            self.assertTrue(parent["skipped_document"])
            self.assertEqual(len(parent["models_tried"]), 3)

    def test_auth_error_halts_provider_but_tries_next_provider_by_default(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_config(t)
            provs = mocks(g=("402",), o=("ok",))
            res, _ = go(cfg, provs)
            self.assertEqual(provs["gemini"].calls, ["g1"])  # g2는 시도하지 않음
            self.assertEqual((res.provider, res.model_id), ("openai", "o1"))

    def test_auth_error_stops_everything_when_configured(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_config(t, try_next_provider_on_auth_error=False)
            provs = mocks(g=("auth",), o=("ok",))
            res, _ = go(cfg, provs)
            self.assertEqual(res.status, "failed")
            self.assertEqual(provs["openai"].calls, [])

    def test_truncated_refused_invalid_json_are_not_complete_and_keep_raw(self):
        cases = {"incomplete": ("truncated", '{"rules": [{"cl'), "refusal": ("refused", "sorry, no"),
                 "invalid_json": ("failed", "plain words not json")}
        for kind, (status, raw) in cases.items():
            with tempfile.TemporaryDirectory() as t:
                cfg = make_config(t, gemini=("g1",), openai=("o1",))
                provs = mocks(g=((kind, raw),), o=((kind, raw),))
                res, sl = go(cfg, provs)
                self.assertEqual(res.status, "failed", kind)
                self.assertFalse(res.complete, kind)
                self.assertEqual(sl.delays, [], kind)  # 재시도하지 않음
                self.assertEqual([c.status for c in res.calls], [status, status], kind)
                self.assertEqual(len(res.raw_files), 2, kind)
                for rel in res.raw_files:
                    self.assertEqual((Path(cfg.log_dir) / rel).read_text(encoding="utf-8"), raw, kind)

    def test_incomplete_then_next_model_succeeds_and_both_recorded_per_model(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_config(t)
            provs = mocks(g=("incomplete", "ok"))
            res, _ = go(cfg, provs)
            self.assertEqual((res.provider, res.model_id), ("gemini", "g2"))
            rows = [r for r in read_log(cfg) if r["record_type"] == "model_call"]
            self.assertEqual([(r["actual_model"], r["status"]) for r in rows], [("g1", "truncated"), ("g2", "success")])
            self.assertTrue(all(r["requested_model"] == "g1" for r in rows))

    def test_unexpected_exception_does_not_kill_run(self):
        class Bad:
            name = "gemini"
            def generate(self, request, model):
                raise RuntimeError("boom")
        with tempfile.TemporaryDirectory() as t:
            cfg = make_config(t, gemini=("g1",), openai=("o1",))
            res, _ = go(cfg, {"gemini": Bad(), "openai": mocks(o=("ok",))["openai"]})
            self.assertEqual(res.provider, "openai")

    def test_request_flags_for_answer_key_are_refused(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_config(t)
            with self.assertRaises(ValueError):
                extract_call(cfg, LLMRequest(prompt="x", answer_key_supplied=True), providers=mocks(), use_cache=False)


if __name__ == "__main__":
    unittest.main()
