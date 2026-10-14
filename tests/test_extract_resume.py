"""C: 청크 수·API 시도 상한 분리, 이어서 하기(--resume-from), 외부 전송 허용 목록(Gemini, SOP만).
가짜 Gemini 응답만 쓰고 genai.Client는 만들지 않는다.

실행: PYTHONPATH=src .venv/Scripts/python.exe -m unittest tests.test_extract_resume -v
"""
import io
import json
import os
import shutil
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_fakes  # noqa: E402
import extract_support as S  # noqa: E402
from imaks_kg import settings  # noqa: E402
from imaks_kg.common.provenance import sha256_file  # noqa: E402
from imaks_kg.extract import approval, llm, llm_gemini as G, resume, run  # noqa: E402
from imaks_kg.extract.common import ExtractError, read_jsonl, safe_name  # noqa: E402

MODEL = extract_fakes.FAKE_GEMINI_MODEL
ONE = ["SOP-001:p1:RULE-ST02-04"]
FOUR = ["SOP-001:p1:RULE-ST01-02", "SOP-001:p1:RULE-ST02-02", "SOP-001:p1:RULE-ST03-02", "SOP-003:p1:table1:chunk"]


def rerecord(run_dir):
    """장부까지 고친 공격을 흉내 낸다: 고친 실행 파일의 해시를 장부에 다시 적는다(사슬은 이어짐)."""
    from imaks_kg.extract import ledger
    meta = json.loads((Path(run_dir) / "meta.json").read_text(encoding="utf-8"))
    ledger.record_run(run_dir, meta["run_id"], "run_finished",
                      ["meta.json", "calls.jsonl", "candidates_premerge.jsonl", "rejected.csv", ledger.RAW_BUNDLE])


class Base(unittest.TestCase):
    def setUp(self):
        tmp = S.tmpdir()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        S.use_ledger(self, self.root / "ledger.jsonl")  # 테스트마다 임시 장부
        gen = mock.Mock(side_effect=AssertionError("실제 genai.Client 생성 금지"))
        env = {k: v for k, v in os.environ.items() if k not in (G.KEY_ENV, G.CONFLICT_ENV)}
        for p in (mock.patch.object(G.genai, "Client", gen), mock.patch.object(G, "DOTENV_FILE", self.root / "no.env"),
                  mock.patch.dict(os.environ, env, clear=True)):
            p.start()
            self.addCleanup(p.stop)
        self.gen = gen

    def tearDown(self):
        self.assertEqual(self.gen.call_count, 0)

    def fakes(self, name, mapping):
        d = self.root / name
        d.mkdir()
        for cid, data in mapping.items():
            (d / f"{safe_name(cid)}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return d

    def ok(self, cids):
        allf = extract_fakes.build(cids, provider="gemini")
        return {c: allf[c] for c in cids}

    def go(self, ctx, mapping, run_id, **kw):
        client = G.GeminiFakeClient(self.fakes(f"fake-{run_id}", mapping))
        self.sleeps = []
        res = run.run_calls(ctx, client, self.root / "runs" / run_id, run_id, "fake", sleep=self.sleeps.append, **kw)
        return res, client


class Budget(Base):
    @classmethod
    def setUpClass(cls):
        why = S.needs_inputs()
        if why:
            raise unittest.SkipTest(why)
        cls.ctx = run.prepare(chunk_ids=ONE, provider="gemini", model=MODEL, min_interval_s=0)
        cls.ctx2 = run.prepare(chunk_ids=FOUR[:2], provider="gemini", model=MODEL, min_interval_s=0)

    def test_attempt_cap_formula_in_estimate(self):
        est = run.estimate_tokens(self.ctx["requests"], self.ctx["adapter"])
        rec = approval.build_estimate(self.ctx, est)
        self.assertEqual((rec["approved_chunks"], rec["approved_attempts"]), (1, 3))
        self.assertIn("min(1×3, 1+10) = 3", rec["attempt_cap_formula"])
        self.assertIn("청크 1개, API 시도 최대 3회", "\n".join(approval.summary_lines(rec)))
        self.assertEqual(approval.attempt_cap(20), 30)
        self.assertEqual(approval.attempt_cap(2), 6)

    def test_one_chunk_429_then_200(self):
        ok = self.ok(ONE)
        m = {ONE[0]: {"__sequence__": [{"__raise__": "rate_minute"}, ok[ONE[0]]]}}
        res, client = self.go(self.ctx, m, "b1", max_chunks=1, max_attempts=approval.attempt_cap(1))
        self.assertFalse(res["aborted"])
        meta = res["meta"]
        self.assertEqual((meta["approved_chunks"], meta["approved_attempts"]), (1, 3))
        self.assertEqual((meta["actual_chunks"], meta["actual_attempts"]), (1, 2))
        self.assertEqual([a["status"] for a in meta["chunk_attempts"][ONE[0]]], [429, 200])

    def test_one_chunk_429x3_exhausted_and_restored(self):
        rec = approval.build_estimate(self.ctx, run.estimate_tokens(self.ctx["requests"], self.ctx["adapter"]))
        p = approval.write_estimate(rec, self.root / "ap")
        approval.reserve(p, "b2")
        outcome = {}
        client = G.GeminiFakeClient(self.fakes("fake-b2", {ONE[0]: {"__raise__": "rate_minute"}}))
        res = run.run_calls(self.ctx, client, self.root / "runs" / "b2", "b2", "execute", max_chunks=1,
                            max_attempts=3, approval_id=rec["estimate_id"], sleep=lambda s: None, outcome=outcome)
        self.assertEqual(res["outcome"]["abort"]["error_class"], llm.TRANSIENT_EXHAUSTED)
        self.assertEqual(len(client.calls), 3)
        self.assertEqual((res["meta"]["actual_chunks"], res["meta"]["actual_attempts"]), (1, 3))
        self.assertEqual(approval.finalize(p, "b2", outcome), "unused")

    def test_chunk_beyond_approved_blocked(self):
        with self.assertRaises(ExtractError) as cm:
            self.go(self.ctx2, self.ok(FOUR[:2]), "b3", max_chunks=1)
        self.assertIn("승인 청크 수", str(cm.exception))
        self.assertFalse((self.root / "runs" / "b3").exists())

    def test_attempt_beyond_cap_blocked(self):
        ok = self.ok(ONE)
        m = {ONE[0]: {"__sequence__": [{"__raise__": "rate_minute"}, ok[ONE[0]]]}}
        res, client = self.go(self.ctx, m, "b4", max_chunks=1, max_attempts=1)
        self.assertEqual(res["outcome"]["abort"]["error_class"], llm.TRANSIENT_EXHAUSTED)
        self.assertIn("승인 API 시도 상한", res["outcome"]["abort"]["error"]["message"])
        self.assertEqual(len(client.calls), 1)
        self.assertEqual((res["meta"]["approved_attempts"], res["meta"]["actual_attempts"]), (1, 1))


class Resume(Base):
    @classmethod
    def setUpClass(cls):
        why = S.needs_inputs()
        if why:
            raise unittest.SkipTest(why)
        cls.ctx = run.prepare(chunk_ids=FOUR, provider="gemini", model=MODEL, min_interval_s=0)

    def full_and_stopped(self):
        ok = self.ok(FOUR)
        full, _ = self.go(self.ctx, ok, "full")
        stop_map = dict(ok)
        stop_map[FOUR[2]] = {"__raise__": "quota_day"}
        stopped, _ = self.go(self.ctx, stop_map, "stopped")
        self.assertTrue(stopped["aborted"])
        return ok, full, stopped

    def test_normal_resume_equals_full(self):
        ok, full, stopped = self.full_and_stopped()
        reused = resume.collect([stopped["run_dir"]], self.ctx)
        self.assertEqual(sorted(reused), sorted(FOUR[:2]))
        ctx_r = resume.restrict(self.ctx, reused)
        self.assertEqual([c["chunk_id"] for c, _ in ctx_r["requests"]], FOUR[2:])
        # 남은 청크만 추정·승인
        rec = approval.build_estimate(ctx_r, run.estimate_tokens(ctx_r["requests"], ctx_r["adapter"]))
        self.assertEqual(rec["approved_chunks"], 2)
        res, client = self.go(ctx_r, ok, "resumed", max_chunks=2)
        self.assertEqual(client.calls, FOUR[2:])
        for name in ("candidates_premerge.jsonl", "merged.jsonl", "rejected.csv", "merge_conflicts.csv"):
            self.assertEqual(sha256_file(res["run_dir"] / name), sha256_file(full["run_dir"] / name), name)
        rf = res["meta"]["reused_from"]
        self.assertEqual(sorted(rf), sorted(FOUR[:2]))
        for cid, v in rf.items():
            self.assertEqual(v["run_id"], "stopped")
            self.assertEqual(v["raw_sha256"], v["copied_sha256"])
            self.assertTrue(v["request_id"].startswith("gemini_fake_"))
        self.assertTrue(res["meta"]["combination_checks"]["ok"])
        # 끝까지(검토 → final) 같은 결과
        from imaks_kg.extract import review
        for r in (full, res):
            S.fill_round1(r["run_dir"])
            review.make_round2(r["run_dir"])
            review.apply_review(r["run_dir"])
        self.assertEqual(sha256_file(res["run_dir"] / "final.jsonl"), sha256_file(full["run_dir"] / "final.jsonl"))

    def test_reuse_refused_on_changes(self):
        _, _, stopped = self.full_and_stopped()
        cases = {
            "model": dict(self.ctx, adapter=G.GeminiAdapter("other-model")),
            "prompt": dict(self.ctx, prompt=dict(self.ctx["prompt"], prompt_sha256="e" * 64)),
            "examples": dict(self.ctx, prompt=dict(self.ctx["prompt"], examples_sha256="d" * 64)),
            "provider": dict(self.ctx, adapter=llm.AnthropicAdapter()),
            "fingerprint": dict(self.ctx, fingerprint=dict(self.ctx["fingerprint"], seed_ttl={"sha256": "0"})),
        }
        reqs = [(c, json.loads(json.dumps(r))) for c, r in self.ctx["requests"]]
        reqs[0][1]["config"]["temperature"] = 0.7
        cases["generation"] = dict(self.ctx, requests=reqs)
        for name, ctx in cases.items():
            with self.subTest(name), self.assertRaises(ExtractError) as cm:
                resume.collect([stopped["run_dir"]], ctx)
            self.assertIn("재사용 거부", str(cm.exception))
        # 재사용하는 청크의 해시가 다름
        mp = stopped["run_dir"] / "meta.json"
        meta = json.loads(mp.read_text(encoding="utf-8"))
        meta["input_chunks"][0]["text_sha256"] = "f" * 64
        mp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(ExtractError) as cm:  # 먼저 해시 장부가 잡는다
            resume.collect([stopped["run_dir"]], self.ctx)
        self.assertIn("해시 장부", str(cm.exception))
        rerecord(stopped["run_dir"])  # 장부까지 고친 경우에도 청크 해시 대조가 잡는다
        with self.assertRaises(ExtractError) as cm:
            resume.collect([stopped["run_dir"]], self.ctx)
        self.assertIn("text_sha256", str(cm.exception))

    def test_same_chunk_in_two_runs_stops(self):
        _, full, stopped = self.full_and_stopped()
        with self.assertRaises(ExtractError) as cm:
            resume.collect([stopped["run_dir"], full["run_dir"]], self.ctx)
        self.assertIn("여러 실행", str(cm.exception))

    def test_failed_responses_not_reused(self):
        ok = self.ok(FOUR)
        m = dict(ok)
        m[FOUR[0]] = extract_fakes.gemini_message({"rules": []}, finish="MAX_TOKENS")
        bad_rule = extract_fakes.R("OperationalRule", "x", "y", "not in source text", [], [], None)
        m[FOUR[1]] = extract_fakes.gemini_message({"rules": [bad_rule]})  # 거부 행이 생기는 응답
        prev, _ = self.go(self.ctx, m, "prev")
        reused = resume.collect([prev["run_dir"]], self.ctx)
        self.assertEqual(sorted(reused), sorted(FOUR[2:]))

    def test_duplicate_rules_across_runs_caught(self):
        a, b = "SOP-001:p2:RULE-ST04-03", "SOP-001:p1:RULE-ST02-04"
        ctx_a = run.prepare(chunk_ids=[a], provider="gemini", model=MODEL, min_interval_s=0)
        ctx_b = run.prepare(chunk_ids=[b], provider="gemini", model=MODEL, min_interval_s=0)
        wrong = extract_fakes.R("OperationalRule", "SPD drops", "verify RULE-ST02-04.", "verify RULE-ST02-04.",
                                ["ST04_PACKAGING_SPD"], [], "RULE-ST02-04")
        ra, _ = self.go(ctx_a, {a: extract_fakes.gemini_message({"rules": [wrong]})}, "ra")
        rb, _ = self.go(ctx_b, self.ok([b]), "rb")
        ctx_ab = run.prepare(chunk_ids=[a, b], provider="gemini", model=MODEL, min_interval_s=0)
        reused = resume.collect([ra["run_dir"], rb["run_dir"]], ctx_ab)
        ctx_r = resume.restrict(ctx_ab, reused)
        self.assertEqual(ctx_r["requests"], [])
        with self.assertRaises(ExtractError) as cm:
            self.go(ctx_r, {}, "rab")
        self.assertIn("RULE-ST02-04", str(cm.exception))
        meta = json.loads((self.root / "runs" / "rab" / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["combination_checks"]["normalized_rule_id_in_multiple_chunks"], ["RULE-ST02-04"])
        self.assertFalse((self.root / "runs" / "rab" / "merged.jsonl").exists())

    def test_cli_resume_dry_run_estimates_remaining(self):
        _, _, stopped = self.full_and_stopped()
        out = io.StringIO()
        with mock.patch.object(run, "prepare", return_value=self.ctx), redirect_stdout(out):
            code = run.main(["--dry-run", "--provider", "gemini", "--resume-from", "stopped",
                             "--out-root", str(self.root / "runs"), "--approvals-dir", str(self.root / "ap")])
        self.assertEqual(code, 0, out.getvalue())
        rec = json.loads(next((self.root / "ap").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(rec["approved_chunks"], 2)
        self.assertEqual([c["chunk_id"] for c in rec["fingerprint"]["chunks"]], FOUR[2:])
        self.assertIn("재사용 2개", out.getvalue())


class Outbound(Base):
    def test_datasheet_chunk_refused(self):
        why = S.needs_inputs()
        if why:
            self.skipTest(why)
        ctx = run.prepare(chunk_ids=ONE, provider="gemini", model=MODEL, min_interval_s=0)
        ds = ctx["docs"]["chunks"][[c["chunk_id"] for c in ctx["docs"]["chunks"]].index("DS-ELEC-3300:p1:text2")]
        self.assertIn("허용 목록", G.outbound_problem(ds, ctx["docs"]))
        self.assertEqual(G.outbound_problem(ctx["requests"][0][0], ctx["docs"]), "")
        req = ctx["adapter"].build_request("s", ds["text"], ctx["schema"])
        bad = dict(ctx, requests=[(ds, req)])
        client = G.GeminiFakeClient(self.fakes("fake-ds", {ds["chunk_id"]: extract_fakes.gemini_message({"rules": []})}))
        with self.assertRaises(ExtractError) as cm:
            run.run_calls(bad, client, self.root / "runs" / "ds", "ds", "fake", sleep=lambda s: None)
        self.assertIn("외부 전송 허용 목록", str(cm.exception))
        self.assertEqual(client.calls, [])
        with self.assertRaises(ExtractError):
            run.prepare(chunk_ids=["DS-ELEC-3300:p1:text2"], provider="gemini", model=MODEL)
        res, _ = self.go(ctx, self.ok(ONE), "ok1")
        self.assertEqual(res["meta"]["outbound_allowlist"]["docs"], ["SOP-001", "SOP-002", "SOP-003", "SOP-004"])

    def test_example_source_checked(self):
        why = S.needs_inputs()
        if why:
            self.skipTest(why)
        pd = self.root / "prompts"
        shutil.copytree(settings.EXTRACT_PROMPTS_DIR, pd)
        exp = pd / "v1" / "examples.json"
        ex = json.loads(exp.read_text(encoding="utf-8"))
        line = "Note 2 — Continuous Overload Rating: The sensor is rated for continuous operation up to 14 A. Operation between"
        ex["examples"].append({"source_chunk_id": "DS-ELEC-3300:p1:text2", "doc_id": "DS-ELEC-3300", "page": 1,
                               "section": None, "kind": "text", "input_text": line,
                               "output": {"rules": [extract_fakes.R("OperationalRule", "c", "r", "up to 14 A", [], [])]}})
        exp.write_text(json.dumps(ex, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(ExtractError) as cm:
            run.prepare(chunk_ids=ONE, provider="gemini", model=MODEL, prompts_dir=pd)
        self.assertIn("프롬프트 예시 출처", str(cm.exception))
        run.prepare(chunk_ids=ONE, provider="anthropic", prompts_dir=pd)  # Anthropic 경로는 이전 동작 그대로

    def test_default_model(self):
        self.assertEqual(G.GEMINI_MODEL, "gemini-3.8-flash")
        self.assertEqual(G.GeminiAdapter().model_id, "gemini-3.8-flash")
        self.assertEqual(G.GeminiAdapter("x-model").model_id, "x-model")


class ServedModel(Base):
    """2차 검증 FAIL 수정: served model은 요청 모델과 정확히 같거나 -NNN 버전 접미사만 허용."""

    @classmethod
    def setUpClass(cls):
        why = S.needs_inputs()
        if why:
            raise unittest.SkipTest(why)
        cls.ctx = run.prepare(chunk_ids=FOUR[:2], provider="gemini", model=MODEL, min_interval_s=0)
        cls.single = {c: run.prepare(chunk_ids=[c], provider="gemini", model=MODEL, min_interval_s=0) for c in FOUR[:2]}

    def test_rule(self):
        for m in (MODEL, "gemini-3.8-flash", "claude-opus-5-5"):
            self.assertTrue(resume._served_ok(m, m))
            self.assertTrue(resume._served_ok(m + "-001", m))
            for suf in ("-lite", "-pro", "-preview", "-8b", "-01", "-0011", "-001-lite", "x"):
                self.assertFalse(resume._served_ok(m + suf, m), m + suf)
        self.assertFalse(resume._served_ok("", MODEL))
        self.assertFalse(resume._served_ok("gemini-3.8", "gemini-3.8-flash"))

    def prev(self, run_id, served, cids=None):
        cids = cids or FOUR[:2]
        m = {c: extract_fakes.gemini_message({"rules": []}, n=i, model=served) for i, c in enumerate(cids)}
        ctx = self.ctx if len(cids) == 2 else self.single[cids[0]]
        res, _ = self.go(ctx, m, run_id)
        return res["run_dir"]

    def test_other_model_suffix_refused(self):
        for suf in ("-lite", "-pro", "-preview", "-8b"):
            with self.subTest(suf):
                d = self.prev(f"p{suf}", MODEL + suf)
                with self.assertRaises(ExtractError) as cm:
                    resume.collect([d], self.ctx)
                self.assertIn("served model", str(cm.exception))

    def test_version_suffix_and_exact_allowed(self):
        self.assertEqual(sorted(resume.collect([self.prev("p001", MODEL + "-001")], self.ctx)), sorted(FOUR[:2]))
        self.assertEqual(sorted(resume.collect([self.prev("pexact", MODEL)], self.ctx)), sorted(FOUR[:2]))

    def test_recorded_served_model_must_match(self):
        d = self.prev("prec", MODEL)
        rows = [json.loads(x) for x in (d / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
        rows[0]["served_model"] = MODEL + "-001"
        (d / "calls.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        with self.assertRaises(ExtractError) as cm:
            resume.collect([d], self.ctx)
        self.assertIn("해시 장부", str(cm.exception))
        rerecord(d)
        with self.assertRaises(ExtractError) as cm:
            resume.collect([d], self.ctx)
        self.assertIn("원래 실행 기록", str(cm.exception))

    def test_served_model_differs_between_runs_refused(self):
        a = self.prev("pa", MODEL, FOUR[:1])
        b = self.prev("pb", MODEL + "-001", FOUR[1:2])
        with self.assertRaises(ExtractError) as cm:
            resume.collect([a, b], self.ctx)
        self.assertIn("서로 다름", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
