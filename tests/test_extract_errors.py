"""C: 오류 분류, 중단·재시도 정책, SDK 재시도 끔, 승인 상태 기계, 단일 청크 모드(가짜 클라이언트만, 네트워크 없음).

실행: PYTHONPATH=src .venv/Scripts/python.exe -m unittest tests.test_extract_errors -v
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
from imaks_kg.extract import approval, llm, prompt, run  # noqa: E402
from imaks_kg.extract.common import ExtractError, safe_name  # noqa: E402

CHUNKS = ["SOP-001:p1:RULE-ST01-01", "SOP-001:p1:RULE-ST01-03", "SOP-001:p1:RULE-ST02-01",
          "SOP-001:p1:RULE-ST02-02", "SOP-001:p1:RULE-ST02-03", "SOP-001:p1:RULE-ST02-04"]
EXPECT = {
    "auth": llm.FATAL_AUTH, "permission": llm.FATAL_AUTH, "credentials": llm.FATAL_AUTH,
    "billing402": llm.FATAL_BILLING, "billing_type": llm.FATAL_BILLING, "credit400": llm.FATAL_BILLING,
    "spend429": llm.FATAL_BILLING,
    "not_found": llm.FATAL_REQUEST, "bad_request": llm.FATAL_REQUEST, "too_large": llm.FATAL_REQUEST,
    "unprocessable": llm.FATAL_REQUEST,
    "rate_limit": llm.TRANSIENT_RATE, "overloaded": llm.TRANSIENT_RATE, "unavailable": llm.TRANSIENT_RATE,
    "internal": llm.AMBIGUOUS, "deadline": llm.AMBIGUOUS, "timeout": llm.AMBIGUOUS, "connection": llm.AMBIGUOUS,
}
DUMMY_KEY = "x-test-not-a-key"


def ok_msg(cid, n=0):
    return extract_fakes.message(cid, {"rules": []}, n=n)


def write_fakes(d, mapping):
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    for cid, data in mapping.items():
        (d / f"{safe_name(cid)}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return d


class Classification(unittest.TestCase):
    def test_classes(self):
        for kind, exp in EXPECT.items():
            with self.subTest(kind):
                self.assertEqual(llm.classify_exception(llm.fake_exception(kind)).error_class, exp)

    def test_billing_patterns_recorded(self):
        info = llm.classify_exception(llm.fake_exception("credit400"))
        self.assertEqual(info.matched_pattern, "credit balance")
        self.assertIn("credit balance", info.message)
        self.assertEqual(llm.classify_exception(llm.fake_exception("spend429")).matched_pattern, "usage limit")
        self.assertEqual(llm.classify_exception(llm.fake_exception("billing402")).matched_pattern, "status 402")

    def test_secret_masked(self):
        import anthropic
        import httpx2
        req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        body = {"type": "error", "error": {"type": "authentication_error", "message": "bad key sk-ant-abc123XYZ"}}
        e = anthropic.AuthenticationError("x", response=httpx2.Response(401, request=req, json=body), body=body)
        info = llm.classify_exception(e)
        self.assertNotIn("sk-ant-abc123XYZ", info.message)

    def test_wait_seconds(self):
        info = llm.classify_exception(llm.fake_exception("rate_limit", retry_after=7))
        self.assertEqual(info.retry_after_s, 7.0)
        self.assertEqual(llm.wait_seconds(info, 1), 7.0)
        info = llm.classify_exception(llm.fake_exception("overloaded"))
        self.assertEqual([llm.wait_seconds(info, a) for a in (1, 2, 3, 10)], [2.0, 4.0, 8.0, llm.BACKOFF_CAP_S])
        big = llm.classify_exception(llm.fake_exception("rate_limit", retry_after=99999))
        self.assertEqual(llm.wait_seconds(big, 1), llm.RETRY_AFTER_CAP_S)

    def test_sdk_retries_off(self):
        ctor = mock.Mock()
        with mock.patch("anthropic.Anthropic", ctor), mock.patch.dict(os.environ, {llm.API_KEY_ENV: DUMMY_KEY}):
            llm.AnthropicClient()
        ctor.assert_called_once_with(max_retries=0, timeout=llm.SDK_TIMEOUT_S)
        self.assertEqual(llm.SDK_TIMEOUT_S, 600.0)


class Policy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        why = S.needs_inputs()
        if why:
            raise unittest.SkipTest(why)
        cls.ctx = run.prepare(chunk_ids=CHUNKS, provider="anthropic")

    def setUp(self):
        tmp = S.tmpdir()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        S.use_ledger(self, self.root / "ledger.jsonl")  # 테스트마다 임시 장부
        self.sleeps = []

    def go(self, mapping, run_id="t"):
        client = llm.FakeClient(write_fakes(self.root / "fake", mapping))
        res = run.run_calls(self.ctx, client, self.root / run_id, run_id, "fake", sleep=self.sleeps.append)
        return res, client

    def test_chunk_mode_selection(self):
        self.assertEqual([c["chunk_id"] for c, _ in self.ctx["requests"]], CHUNKS)
        self.assertEqual(self.ctx["chunk_filter"], sorted(CHUNKS))
        with self.assertRaises(ExtractError) as cm:
            run.prepare(chunk_ids=["DS-ELEC-3300:p1:text1"])
        self.assertIn("데이터시트", str(cm.exception))

    def test_fatal_aborts_after_one_call(self):
        for kind, exp in EXPECT.items():
            if exp not in llm.FATAL_CLASSES and exp != llm.AMBIGUOUS:
                continue
            with self.subTest(kind):
                mapping = {c: ok_msg(c) for c in CHUNKS}
                mapping[CHUNKS[0]] = {"__raise__": kind}
                res, client = self.go(mapping, f"t-{kind}")
                self.assertEqual(len(client.calls), 1)  # 뒤 청크는 부르지 않음, 재시도 없음
                self.assertTrue(res["aborted"])
                self.assertEqual(res["outcome"]["abort"]["error_class"], exp)
                self.assertEqual(res["outcome"]["not_completed"], CHUNKS)
                self.assertEqual(self.sleeps, [])
                self.assertFalse((res["run_dir"] / "merged.jsonl").exists())
                self.assertFalse((res["run_dir"] / "review_round1.csv").exists())
                meta = json.loads((res["run_dir"] / "meta.json").read_text(encoding="utf-8"))
                self.assertEqual(meta["status"], "aborted")
                self.assertEqual(meta["sdk_client"], {"max_retries": 0, "timeout_s": 600.0})
                if exp == llm.AMBIGUOUS:
                    self.assertIn("사용량 확인 필요", meta["usage_check"])
                if exp == llm.FATAL_BILLING:
                    self.assertTrue(res["outcome"]["abort"]["error"]["matched_pattern"])

    def test_abort_midway_keeps_completed(self):
        mapping = {c: ok_msg(c) for c in CHUNKS}
        mapping[CHUNKS[2]] = {"__raise__": "credit400"}
        res, client = self.go(mapping)
        self.assertEqual(client.calls, CHUNKS[:3])
        self.assertEqual(res["outcome"]["completed"], CHUNKS[:2])
        self.assertEqual(res["outcome"]["not_completed"], CHUNKS[2:])

    def test_retry_after_honored(self):
        mapping = {c: ok_msg(c) for c in CHUNKS}
        mapping[CHUNKS[0]] = {"__sequence__": [{"__raise__": "rate_limit", "retry_after": 7}, ok_msg(CHUNKS[0])]}
        res, client = self.go(mapping)
        self.assertFalse(res["aborted"])
        self.assertEqual(self.sleeps, [7.0])
        self.assertEqual(client.calls.count(CHUNKS[0]), 2)
        meta = json.loads((res["run_dir"] / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(len(meta["retries"]), 1)
        self.assertEqual(meta["retries"][0]["attempt"], 1)
        self.assertEqual(meta["retries"][0]["status"], 429)
        self.assertEqual(meta["retries"][0]["wait_s"], 7.0)
        self.assertEqual(meta["status"], "completed")

    def test_overloaded_retried_with_backoff(self):
        mapping = {c: ok_msg(c) for c in CHUNKS}
        mapping[CHUNKS[1]] = {"__sequence__": [{"__raise__": "overloaded"}, {"__raise__": "unavailable"},
                                               ok_msg(CHUNKS[1])]}
        res, _ = self.go(mapping)
        self.assertFalse(res["aborted"])
        self.assertEqual(self.sleeps, [2.0, 4.0])

    def test_per_chunk_limit(self):
        mapping = {c: ok_msg(c) for c in CHUNKS}
        mapping[CHUNKS[0]] = {"__raise__": "rate_limit"}
        res, client = self.go(mapping)
        self.assertEqual(client.calls, [CHUNKS[0]] * 3)
        self.assertEqual(res["outcome"]["abort"]["error_class"], llm.TRANSIENT_EXHAUSTED)
        self.assertEqual(len(self.sleeps), 2)

    def test_per_run_limit(self):
        seq = lambda c: {"__sequence__": [{"__raise__": "rate_limit"}, {"__raise__": "rate_limit"}, ok_msg(c)]}  # noqa: E731
        res, client = self.go({c: seq(c) for c in CHUNKS})
        # 청크 5개가 2번씩 재시도(=10회)한 뒤 6번째 청크의 첫 429에서 실행당 한도 소진
        self.assertEqual(len(self.sleeps), llm.MAX_RETRIES_PER_RUN)
        self.assertEqual(res["outcome"]["completed"], CHUNKS[:5])
        self.assertEqual(res["outcome"]["abort"]["error_class"], llm.TRANSIENT_EXHAUSTED)
        self.assertEqual(client.calls.count(CHUNKS[5]), 1)

    def test_200_refusal_continues(self):
        mapping = {c: ok_msg(c) for c in CHUNKS}
        mapping[CHUNKS[0]] = extract_fakes.message(CHUNKS[0], {"rules": []}, stop="refusal")
        res, client = self.go(mapping)
        self.assertFalse(res["aborted"])
        self.assertEqual(len(client.calls), len(CHUNKS))
        self.assertEqual(res["meta"]["counts"]["calls_failed"], 1)


class ApprovalStates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        why = S.needs_inputs()
        if why:
            raise unittest.SkipTest(why)
        ctx = run.prepare(chunk_ids=CHUNKS[:3], provider="anthropic")
        cls.ctx = dict(ctx, prompt=dict(ctx["prompt"], examples_status=prompt.STATUS_CONFIRMED))

    def setUp(self):
        tmp = S.tmpdir()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        S.use_ledger(self, self.root / "ledger.jsonl")  # 테스트마다 임시 장부
        self.approvals = self.root / "approvals"
        self.n = 0

    def main(self, args, mapping=None):
        self.n += 1
        fake = write_fakes(self.root / f"fake{self.n}", mapping or {c: ok_msg(c) for c in CHUNKS[:3]})
        real = mock.Mock(side_effect=AssertionError("실제 클라이언트 생성 금지"))
        factory = mock.Mock(side_effect=lambda: llm.FakeClient(fake))
        out = io.StringIO()
        with mock.patch.object(run, "prepare", return_value=self.ctx), \
                mock.patch.dict(os.environ, {llm.API_KEY_ENV: DUMMY_KEY}), \
                mock.patch("anthropic.Anthropic", real), \
                mock.patch.object(run.llm, "AnthropicClient", factory), \
                mock.patch.object(run.time, "sleep", side_effect=AssertionError("대기 금지")), redirect_stdout(out):
            code = run.main(args + ["--approvals-dir", str(self.approvals), "--out-root", str(self.root / "runs")])
        self.assertEqual(real.call_count, 0)
        return code, out.getvalue()

    def estimate(self):
        code, text = self.main(["--dry-run"])
        self.assertEqual(code, 0, text)
        files = sorted(self.approvals.glob("*.json"))
        self.assertEqual(len(files), 1)
        rec = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(rec["calls"], 3)
        self.assertEqual(rec["state"], "unused")
        self.assertEqual(rec["chunk_filter"], sorted(CHUNKS[:3]))
        return rec["estimate_id"], files[0]

    def rec(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def test_auth_first_call_restored_and_reusable(self):
        eid, p = self.estimate()
        for kind in ("auth", "credit400", "not_found", "credentials"):
            mapping = {c: ok_msg(c) for c in CHUNKS[:3]}
            mapping[CHUNKS[0]] = {"__raise__": kind}
            code, text = self.main(["--execute", "--approve", eid, "--run-id", f"t-{kind}"], mapping)
            self.assertEqual(code, 3, text)
            r = self.rec(p)
            self.assertEqual(r["state"], "unused", kind)
            self.assertEqual([h["event"] for h in r["history"]][-2:], ["reserved", "released"])
            self.assertEqual(r["history"][-1]["reason"], EXPECT[kind])
            self.assertEqual(r["history"][-1]["attempts"][0]["error_class"], EXPECT[kind])
        # 재사용 가능(입력 지문은 다시 검사됨)
        code, text = self.main(["--execute", "--approve", eid, "--run-id", "t-ok"])
        self.assertEqual(code, 0, text)
        r = self.rec(p)
        self.assertEqual(r["state"], "used")
        self.assertEqual(r["used_by_run_id"], "t-ok")
        events = [h["event"] for h in r["history"]]
        self.assertEqual(events, ["created"] + ["reserved", "released"] * 4 + ["reserved", "used"])

    def test_restored_still_checks_fingerprint(self):
        eid, p = self.estimate()
        mapping = {c: ok_msg(c) for c in CHUNKS[:3]}
        mapping[CHUNKS[0]] = {"__raise__": "auth"}
        self.main(["--execute", "--approve", eid, "--run-id", "t-a"], mapping)
        self.assertEqual(self.rec(p)["state"], "unused")
        changed = dict(self.ctx, prompt=dict(self.ctx["prompt"], prompt_sha256="e" * 64))
        with mock.patch.object(self, "ctx", changed):
            code, text = self.main(["--execute", "--approve", eid, "--run-id", "t-b"])
        self.assertEqual(code, 2)
        self.assertIn("prompt_sha256", text)

    def test_credit_after_success_used_partial(self):
        eid, p = self.estimate()
        mapping = {c: ok_msg(c) for c in CHUNKS[:3]}
        mapping[CHUNKS[1]] = {"__raise__": "credit400"}
        code, text = self.main(["--execute", "--approve", eid, "--run-id", "t-part"], mapping)
        self.assertEqual(code, 3, text)
        r = self.rec(p)
        self.assertEqual(r["state"], "used")
        self.assertEqual(r["partial_run"]["completed"], [CHUNKS[0]])
        self.assertEqual(r["partial_run"]["not_completed"], CHUNKS[1:3])
        self.assertEqual(r["partial_run"]["reason"], llm.FATAL_BILLING)
        code, text = self.main(["--execute", "--approve", eid, "--run-id", "t-again"])
        self.assertEqual(code, 2)

    def test_timeout_usage_check_then_resolve(self):
        eid, p = self.estimate()
        mapping = {c: ok_msg(c) for c in CHUNKS[:3]}
        mapping[CHUNKS[0]] = {"__raise__": "timeout"}
        code, text = self.main(["--execute", "--approve", eid, "--run-id", "t-to"], mapping)
        self.assertEqual(code, 3)
        self.assertIn("사용량 확인 필요", text)
        self.assertEqual(self.rec(p)["state"], "usage_check_required")
        code, text = self.main(["--execute", "--approve", eid, "--run-id", "t-to2"])
        self.assertEqual(code, 2)
        self.assertIn("resolve", text)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(approval.main(["resolve", eid, "--as", "unused", "--note", "Console에서 과금 0 확인",
                                            "--approvals-dir", str(self.approvals)]), 0)
            self.assertEqual(approval.main(["resolve", eid, "--as", "used", "--note", "x",
                                            "--approvals-dir", str(self.approvals)]), 1)  # 이미 해결됨
        r = self.rec(p)
        self.assertEqual(r["state"], "unused")
        self.assertEqual(r["history"][-1]["event"], "resolved")
        self.assertEqual(r["history"][-1]["note"], "Console에서 과금 0 확인")
        code, text = self.main(["--execute", "--approve", eid, "--run-id", "t-to3"])
        self.assertEqual(code, 0, text)

    def test_reserved_cannot_be_used_by_other_run(self):
        eid, p = self.estimate()
        from imaks_kg.extract import locks
        other = locks.run_lock(eid).acquire()  # 살아 있는 다른 실행이 실행 잠금을 쥐고 예약함
        try:
            approval.reserve(p, "other-run")
            code, text = self.main(["--execute", "--approve", eid, "--run-id", "t-x"])
            self.assertEqual(code, 2)
            self.assertIn("reserved", text)
            self.assertEqual(approval.finalize(p, "t-x", {"http_200": 0}), "reserved")  # 남의 예약은 안 바뀜
            with self.assertRaises(ExtractError):
                approval.reserve(p, "third")
        finally:
            other.release()
        # 쥔 프로세스가 없어지면(비정상 종료) 다음 검사가 usage_check_required로 옮긴다(unused 아님)
        code, text = self.main(["--execute", "--approve", eid, "--run-id", "t-y"])
        self.assertEqual(code, 2)
        self.assertIn("usage_check_required", text)

    def test_retry_exhausted_without_200_restored(self):
        eid, p = self.estimate()
        mapping = {c: ok_msg(c) for c in CHUNKS[:3]}
        mapping[CHUNKS[0]] = {"__raise__": "rate_limit", "retry_after": 0}
        with mock.patch.object(llm.time, "sleep"):
            fake = write_fakes(self.root / "fake-rate", mapping)
            outcome = {}
            client = llm.FakeClient(fake)
            approval.reserve(p, "t-rate")
            res = run.run_calls(self.ctx, client, self.root / "runs" / "t-rate", "t-rate", "execute",
                                max_calls=3, approval_id=eid, sleep=lambda s: None, outcome=outcome)
            state = approval.finalize(p, "t-rate", outcome)
        self.assertEqual(res["outcome"]["abort"]["error_class"], llm.TRANSIENT_EXHAUSTED)
        self.assertEqual(state, "unused")
        self.assertEqual(len(self.rec(p)["history"][-1]["attempts"]), 3)


class SingleChunkDryRun(unittest.TestCase):
    def test_dry_run_one_chunk(self):
        why = S.needs_inputs()
        if why:
            self.skipTest(why)
        with S.tmpdir() as tmp, redirect_stdout(io.StringIO()) as out, \
                mock.patch("anthropic.Anthropic", mock.Mock(side_effect=AssertionError)):
            code = run.main(["--dry-run", "--provider", "anthropic", "--chunk", "SOP-001:p1:RULE-ST02-04", "--approvals-dir", str(Path(tmp) / "ap")])
            self.assertEqual(code, 0)
            rec = json.loads(next((Path(tmp) / "ap").glob("*.json")).read_text(encoding="utf-8"))
        self.assertIn("입력 청크(호출 수): 1", out.getvalue())
        self.assertEqual(rec["calls"], 1)
        self.assertEqual(rec["output_cap_tokens"], 16000)
        self.assertEqual([c["chunk_id"] for c in rec["fingerprint"]["chunks"]], ["SOP-001:p1:RULE-ST02-04"])


if __name__ == "__main__":
    unittest.main()
