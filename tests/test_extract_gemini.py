"""C: Gemini(무료 등급) 어댑터. 가짜 응답·가짜 오류만 쓰고 genai.Client는 실제로 만들지 않는다(목, 호출 0회).
저장소의 .env는 읽지 않는다(모든 테스트가 llm_gemini.DOTENV_FILE을 임시 경로로 바꾼다).

실행: PYTHONPATH=src .venv/Scripts/python.exe -m unittest tests.test_extract_gemini -v
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_fakes  # noqa: E402
import extract_support as S  # noqa: E402
from google.genai import types  # noqa: E402
from imaks_kg.extract import approval, llm, llm_gemini as G, prompt, review, run, to_rdf  # noqa: E402
from imaks_kg.extract.common import ExtractError, safe_name  # noqa: E402

MODEL = extract_fakes.FAKE_GEMINI_MODEL
DUMMY = "dummy-not-a-real-key-123"
CHUNKS = ["SOP-001:p1:RULE-ST01-01", "SOP-001:p1:RULE-ST01-03", "SOP-001:p1:RULE-ST02-01", "SOP-001:p1:RULE-ST02-04"]
EXPECT = {
    "unauthenticated": llm.FATAL_AUTH, "permission": llm.FATAL_AUTH, "key_invalid": llm.FATAL_AUTH,
    "quota_day": llm.FATAL_QUOTA, "quota_zero": llm.FATAL_QUOTA, "quota_msg": llm.FATAL_QUOTA,
    "precondition": llm.FATAL_QUOTA,
    "rate_minute": llm.TRANSIENT_RATE, "rate_plain": llm.TRANSIENT_RATE, "unavailable": llm.TRANSIENT_RATE,
    "not_found": llm.FATAL_REQUEST, "invalid": llm.FATAL_REQUEST, "too_large": llm.FATAL_REQUEST,
    "internal": llm.AMBIGUOUS, "deadline": llm.AMBIGUOUS, "timeout": llm.AMBIGUOUS, "connection": llm.AMBIGUOUS,
}


class NoEnvMixin:
    """저장소 .env를 읽지 않게 하고, GEMINI_API_KEY·GOOGLE_API_KEY를 환경에서 지운다. genai.Client는 목."""

    def setUp(self):
        tmp = S.tmpdir()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        S.use_ledger(self, self.root / "ledger.jsonl")  # 테스트마다 임시 장부
        self.dotenv = self.root / "no.env"
        env = {k: v for k, v in os.environ.items() if k not in (G.KEY_ENV, G.CONFLICT_ENV)}
        for p in (mock.patch.object(G, "DOTENV_FILE", self.dotenv), mock.patch.dict(os.environ, env, clear=True)):
            p.start()
            self.addCleanup(p.stop)
        self.genai_client = mock.Mock(side_effect=AssertionError("테스트에서 실제 genai.Client 생성 금지"))
        p = mock.patch.object(G.genai, "Client", self.genai_client)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self.assertEqual(self.genai_client.call_count, 0)


class Key(NoEnvMixin, unittest.TestCase):
    def test_dotenv_and_env_precedence(self):
        self.dotenv.write_text('# 주석\nOTHER=1\nGEMINI_API_KEY="from-dotenv-123"\n', encoding="utf-8")
        self.assertEqual(G.load_key(), ("from-dotenv-123", ".env"))
        with mock.patch.dict(os.environ, {G.KEY_ENV: "from-env-456"}):
            self.assertEqual(G.load_key(), ("from-env-456", "environment"))
        self.dotenv.write_text("export GEMINI_API_KEY=plain789 # memo\n", encoding="utf-8")
        self.assertEqual(G.load_key()[0], "plain789")

    def test_google_api_key_conflict_stops(self):
        self.dotenv.write_text(f"GEMINI_API_KEY={DUMMY}\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {G.CONFLICT_ENV: "other-key-000"}):
            with self.assertRaises(G.KeyMissingError) as cm:
                G.load_key()
        self.assertIn("GOOGLE_API_KEY", str(cm.exception))
        self.assertNotIn("other-key-000", str(cm.exception))
        self.assertNotIn(DUMMY, str(cm.exception))

    def test_missing_key_fatal_auth_before_client(self):
        with self.assertRaises(G.KeyMissingError) as cm:
            G.GeminiClient()
        self.assertTrue(str(cm.exception).startswith("FATAL_AUTH"))
        self.assertEqual(G.classify(cm.exception).error_class, llm.FATAL_AUTH)
        self.assertIn("FATAL_AUTH", G.key_problem())

    def test_client_without_retry_options(self):
        self.dotenv.write_text(f"GEMINI_API_KEY={DUMMY}\n", encoding="utf-8")
        ctor = mock.Mock()
        with mock.patch.object(G.genai, "Client", ctor):
            c = G.GeminiClient()
        ctor.assert_called_once()
        kw = ctor.call_args.kwargs
        self.assertEqual(kw["api_key"], DUMMY)
        self.assertIsInstance(kw["http_options"], types.HttpOptions)
        self.assertIsNone(kw["http_options"].retry_options)
        self.assertEqual(kw["http_options"].timeout, 600_000)
        self.assertNotIn(DUMMY, repr(c))
        self.assertNotIn(DUMMY, str(vars(c).get("key_source")))
        self.assertFalse(any(DUMMY == v for v in vars(c).values() if isinstance(v, str)))

    def test_sdk_never_retry_when_retry_options_none(self):
        from google.genai import _api_client
        args = _api_client.retry_args(None)
        self.assertEqual(args["stop"].max_attempt_number, 1)


class RequestAndResponse(NoEnvMixin, unittest.TestCase):
    def test_request_fields(self):
        schema = {"type": "object", "properties": {"x": {"type": ["string", "null"]}}, "required": ["x"],
                  "additionalProperties": False}
        ad = G.GeminiAdapter(MODEL)
        req = ad.build_request("SYS", "USER", schema)
        self.assertEqual(req["model"], MODEL)
        cfg = req["config"]
        self.assertEqual(cfg["temperature"], 0)
        self.assertEqual(cfg["seed"], G.SEED)
        self.assertEqual(cfg["response_mime_type"], "application/json")
        self.assertNotIn("thinking_config", cfg)
        self.assertEqual(cfg["response_json_schema"]["properties"]["x"], {"anyOf": [{"type": "string"}, {"type": "null"}]})
        self.assertEqual(schema["properties"]["x"]["type"], ["string", "null"])  # 원본 스키마는 그대로
        self.assertTrue(ad.schema_changes)
        types.GenerateContentConfig(**cfg)  # 2.30.0에 있는 필드만 씀
        meta = ad.meta()
        self.assertEqual(meta["sdk_client"], {"retry_options": "None (never retry)", "timeout_ms": 600000})
        self.assertIn("없음", meta["fallbacks"])

    def resp(self, data):
        return types.GenerateContentResponse.model_validate(data)

    def test_interpret_cases(self):
        ok = G.interpret("k", self.resp(extract_fakes.gemini_message({"rules": []}, thought=True)))
        self.assertTrue(ok.ok)
        self.assertEqual(ok.parsed, {"rules": []})
        self.assertEqual(ok.usage["thoughts_token_count"], 120)
        self.assertEqual(ok.served_model, MODEL)
        self.assertTrue(ok.request_id.startswith("gemini_fake_"))
        for data, why in [(extract_fakes.gemini_message({}, blocked="SAFETY"), "block_reason"),
                          (extract_fakes.gemini_message({"rules": []}, finish="SAFETY"), "finish_reason=SAFETY"),
                          (extract_fakes.gemini_message({"rules": []}, finish="MAX_TOKENS"), "MAX_TOKENS"),
                          (extract_fakes.gemini_message({"rules": []}, finish="RECITATION"), "RECITATION"),
                          ({"model_version": MODEL, "candidates": []}, "후보 없음")]:
            r = G.interpret("k", self.resp(data))
            self.assertFalse(r.ok)
            self.assertTrue(r.http_200)
            self.assertIn(why, r.failure)
            self.assertIsNone(r.parsed)


class Classification(NoEnvMixin, unittest.TestCase):
    def test_table(self):
        for kind, exp in EXPECT.items():
            with self.subTest(kind):
                self.assertEqual(G.classify(G.fake_error(kind)).error_class, exp)

    def test_evidence(self):
        day = G.classify(G.fake_error("quota_day"))
        self.assertIn("일일 한도", day.matched_pattern)
        self.assertIn("PerDay", day.matched_pattern)
        self.assertIn("무료 등급", day.message)
        self.assertIn("quotaValue 0", G.classify(G.fake_error("quota_zero")).matched_pattern)
        minute = G.classify(G.fake_error("rate_minute"))
        self.assertEqual(minute.retry_after_s, 7.0)
        self.assertIn("RESOURCE_EXHAUSTED", minute.matched_pattern)
        self.assertIn("API_KEY_INVALID", G.classify(G.fake_error("key_invalid")).matched_pattern)
        self.assertIn("사용량 확인 필요", G.classify(G.fake_error("timeout")).message)


class Pipeline(NoEnvMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        why = S.needs_inputs()
        if why:
            raise unittest.SkipTest(why)
        cls.ctx = run.prepare(chunk_ids=CHUNKS, provider="gemini", model=MODEL, min_interval_s=6.0)

    def go(self, mapping, run_id="g"):
        d = self.root / f"fake-{run_id}"
        d.mkdir()
        for cid, data in mapping.items():
            (d / f"{safe_name(cid)}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        clock = S.FakeClock()
        self.sleeps = clock.sleeps
        client = G.GeminiFakeClient(d)
        res = run.run_calls(self.ctx, client, self.root / run_id, run_id, "fake", sleep=clock.sleep, clock=clock)
        return res, client

    def ok_map(self):
        return {c: extract_fakes.gemini_message({"rules": []}, n=i) for i, c in enumerate(CHUNKS)}

    def test_pacing_between_calls(self):
        res, client = self.go(self.ok_map())
        self.assertFalse(res["aborted"])
        self.assertEqual(self.sleeps, [6.0] * (len(CHUNKS) - 1))
        meta = json.loads((res["run_dir"] / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["min_interval_s"], 6.0)
        self.assertEqual(meta["provider"], "gemini")
        self.assertIn("없음", meta["auto_switch"])

    def test_fatal_quota_aborts_no_switch(self):
        m = self.ok_map()
        m[CHUNKS[0]] = {"__raise__": "quota_day"}
        res, client = self.go(m)
        self.assertEqual(client.calls, [CHUNKS[0]])
        self.assertEqual(res["outcome"]["abort"]["error_class"], llm.FATAL_QUOTA)
        self.assertEqual(self.sleeps, [])

    def test_all_fatal_and_ambiguous_one_call(self):
        for kind, exp in EXPECT.items():
            if exp in (llm.TRANSIENT_RATE,):
                continue
            with self.subTest(kind):
                m = self.ok_map()
                m[CHUNKS[0]] = {"__raise__": kind}
                res, client = self.go(m, f"g-{kind}")
                self.assertEqual(len(client.calls), 1)
                self.assertEqual(res["outcome"]["abort"]["error_class"], exp)

    def test_minute_rate_retry_delay(self):
        m = self.ok_map()
        m[CHUNKS[1]] = {"__sequence__": [{"__raise__": "rate_minute"}, m[CHUNKS[1]]]}
        res, client = self.go(m)
        self.assertFalse(res["aborted"])
        self.assertEqual(client.calls.count(CHUNKS[1]), 2)
        self.assertIn(7.0, self.sleeps)  # RetryInfo.retryDelay
        self.assertEqual(self.sleeps.count(6.0), len(CHUNKS) - 1)

    def test_unavailable_exhausted(self):
        m = self.ok_map()
        m[CHUNKS[0]] = {"__raise__": "unavailable"}
        res, client = self.go(m)
        self.assertEqual(client.calls, [CHUNKS[0]] * 3)
        self.assertEqual(res["outcome"]["abort"]["error_class"], llm.TRANSIENT_EXHAUSTED)


class EndToEnd(NoEnvMixin, unittest.TestCase):
    def test_full_fake_path_shacl(self):
        why = S.needs_inputs()
        if why:
            self.skipTest(why)
        ctx = run.prepare(provider="gemini", model=MODEL, min_interval_s=0)
        fake = extract_fakes.write(self.root / "fake", provider="gemini")
        res = run.run_calls(ctx, G.GeminiFakeClient(fake), self.root / "run", "g-e2e", "fake", sleep=lambda s: None)
        self.assertFalse(res["aborted"])
        self.assertEqual(res["meta"]["counts"]["fallback_served"], 0)
        recs = {r["candidate_id"]: r for r in res["records"]}
        self.assertIn("SOP-001:p1:RULE-ST02-01:r1", recs)  # thought part 건너뜀
        S.fill_round1(res["run_dir"])
        review.make_round2(res["run_dir"])
        review.apply_review(res["run_dir"])
        out = to_rdf.run(res["run_dir"], self.root / "kg")
        ok, text = S.shacl(out["merged_graph"])
        self.assertTrue(ok, text)
        _, rej = S.read_rows(res["run_dir"] / "rejected.csv")
        self.assertIn(("SOP-001:p2:text5", "call_failed"), {(r["chunk_id"], r["reason_code"]) for r in rej})


class CliAndApproval(NoEnvMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        why = S.needs_inputs()
        if why:
            raise unittest.SkipTest(why)
        ctx = run.prepare(chunk_ids=CHUNKS[:2], provider="gemini", model=MODEL, min_interval_s=0)
        cls.ctx = dict(ctx, prompt=dict(ctx["prompt"], examples_status=prompt.STATUS_CONFIRMED))

    def main(self, args, ctx=None, mapping=None):
        fake = self.root / f"fake{len(list(self.root.glob('fake*')))}"
        fake.mkdir()
        for cid, data in (mapping or {c: extract_fakes.gemini_message({"rules": []}) for c in CHUNKS[:2]}).items():
            (fake / f"{safe_name(cid)}.json").write_text(json.dumps(data), encoding="utf-8")
        factory = mock.Mock(side_effect=lambda: G.GeminiFakeClient(fake))
        out = io.StringIO()
        with mock.patch.object(run, "prepare", return_value=ctx or self.ctx), \
                mock.patch.object(run.llm_gemini, "GeminiClient", factory), redirect_stdout(out):
            code = run.main(args + ["--provider", "gemini", "--approvals-dir", str(self.root / "ap"),
                                    "--out-root", str(self.root / "runs")])
        return code, out.getvalue(), factory

    def test_dry_run_free_tier_record(self):
        code, text, _ = self.main(["--dry-run"])
        self.assertEqual(code, 0, text)
        rec = json.loads(next((self.root / "ap").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(rec["provider"], "gemini")
        self.assertEqual(rec["billing_tier"], "free")
        self.assertEqual(rec["cost_usd"]["total_max"], 0.0)
        self.assertEqual(rec["pacing"]["min_interval_s"], 0.0)
        self.assertEqual(rec["max_tokens_per_call"], G.MAX_OUTPUT_TOKENS)

    def test_count_tokens_not_for_gemini(self):
        code, text, factory = self.main(["--dry-run", "--count-tokens"])
        self.assertEqual(code, 0)
        self.assertIn("구현하지 않음", text)
        self.assertEqual(factory.call_count, 0)

    def test_execute_refusals(self):
        with mock.patch.object(G, "GEMINI_MODEL", None):
            unset = dict(self.ctx, adapter=G.GeminiAdapter(None))
        code, text, f = self.main(["--execute"], ctx=unset)
        self.assertEqual(code, 2)
        self.assertIn("모델이 정해지지 않았다", text)
        code, text, f = self.main(["--execute"])
        self.assertEqual(code, 2)
        self.assertIn("GEMINI_API_KEY", text)  # 키 없음(값은 출력하지 않음)
        with mock.patch.dict(os.environ, {G.KEY_ENV: DUMMY, G.CONFLICT_ENV: "x-other"}):
            code, text, f = self.main(["--execute"])
        self.assertEqual(code, 2)
        self.assertIn("GOOGLE_API_KEY", text)
        self.assertNotIn(DUMMY, text)
        self.assertEqual(f.call_count, 0)

    def test_approved_fake_and_quota_restore(self):
        self.main(["--dry-run"])
        p = next((self.root / "ap").glob("*.json"))
        eid = json.loads(p.read_text(encoding="utf-8"))["estimate_id"]
        with mock.patch.dict(os.environ, {G.KEY_ENV: DUMMY}):
            m = {c: extract_fakes.gemini_message({"rules": []}) for c in CHUNKS[:2]}
            m[CHUNKS[0]] = {"__raise__": "quota_day"}
            code, text, f = self.main(["--execute", "--approve", eid, "--run-id", "g-q"], mapping=m)
            self.assertEqual(code, 3, text)
            self.assertNotIn(DUMMY, text)
            rec = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(rec["state"], "unused")
            self.assertEqual(rec["history"][-1]["reason"], llm.FATAL_QUOTA)
            code, text, f = self.main(["--execute", "--approve", eid, "--run-id", "g-ok"])
            self.assertEqual(code, 0, text)
        self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["state"], "used")
        meta = json.loads((self.root / "runs" / "g-ok" / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["approval_id"], eid)
        self.assertNotIn(DUMMY, json.dumps(meta))

    def test_model_change_refused(self):
        self.main(["--dry-run"])
        eid = json.loads(next((self.root / "ap").glob("*.json")).read_text(encoding="utf-8"))["estimate_id"]
        other = dict(self.ctx, adapter=G.GeminiAdapter("another-model"))
        with mock.patch.dict(os.environ, {G.KEY_ENV: DUMMY}):
            code, text, f = self.main(["--execute", "--approve", eid, "--run-id", "g-m"], ctx=other)
        self.assertEqual(code, 2)
        self.assertIn("자동 전환 없음", text)
        self.assertEqual(f.call_count, 0)

    def test_price_table(self):
        self.assertEqual(approval.price_for("gemini", "anything")["billing_tier"], "free")
        self.assertEqual(approval.price_for("anthropic", "claude-opus-5-5")["billing_tier"], "paid")
        with self.assertRaises(ExtractError):
            approval.price_for("anthropic", "other")

    def test_anthropic_model_fixed(self):
        with self.assertRaises(ExtractError):
            run.get_adapter("anthropic", "claude-other")
        with self.assertRaises(ExtractError):
            run.get_adapter("openai")


if __name__ == "__main__":
    unittest.main()
