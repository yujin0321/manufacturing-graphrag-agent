"""C 실행 전 보완 3건(2026-10-14): 인터럽트·불확실 상태의 승인 처리, 프로세스 사이 잠금, 재시도에도 호출 간격.
가짜 클라이언트만 쓴다(실제 API 호출 0). 동시성은 실제 자식 프로세스(subprocess)로 확인한다.

실행: PYTHONPATH=src .venv/Scripts/python.exe -m unittest tests.test_extract_safety -v
"""
import io
import json
import os
import subprocess
import sys
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_fakes  # noqa: E402
import extract_support as S  # noqa: E402
from imaks_kg.extract import approval, ledger, llm, locks, prompt, run  # noqa: E402
from imaks_kg.extract.common import ExtractError, safe_name  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "tests" / "extract_proc_helper.py"
CHUNKS = ["SOP-001:p1:RULE-ST01-01", "SOP-001:p1:RULE-ST01-03", "SOP-001:p1:RULE-ST02-01"]
DUMMY_KEY = "x-test-not-a-key"


def ok_msg(cid, n=0):
    return extract_fakes.message(cid, {"rules": []}, n=n)


def write_fakes(d, mapping):
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    for cid, data in mapping.items():
        (d / f"{safe_name(cid)}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return d


class InterruptingClient:
    """n번째 create에서 KeyboardInterrupt(보내는 중 끊김)."""

    def __init__(self, inner, at):
        self.inner, self.at, self.calls = inner, at, []

    def create(self, request, key):
        self.calls.append(key)
        if len(self.calls) == self.at:
            raise KeyboardInterrupt()
        return self.inner.create(request, key)


class BadInterpretAdapter(llm.AnthropicAdapter):
    def interpret(self, key, response):
        raise ValueError("해석기 고장(가짜)")


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        why = S.needs_inputs()
        if why:
            raise unittest.SkipTest(why)
        ctx = run.prepare(chunk_ids=CHUNKS, provider="anthropic")
        cls.ctx = dict(ctx, prompt=dict(ctx["prompt"], examples_status=prompt.STATUS_CONFIRMED))

    def setUp(self):
        tmp = S.tmpdir()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        S.use_ledger(self, self.root / "ledger.jsonl")
        self.approvals = self.root / "approvals"
        self.repo_ledger = (ROOT / "harness" / "extraction_ledger.jsonl").read_bytes()

    def tearDown(self):
        self.assertEqual((ROOT / "harness" / "extraction_ledger.jsonl").read_bytes(), self.repo_ledger)

    def estimate(self, ctx=None):
        ctx = ctx or self.ctx
        rec = approval.build_estimate(ctx, run.estimate_tokens(ctx["requests"], ctx["adapter"]))
        p = approval.write_estimate(rec, self.approvals)
        return rec["estimate_id"], p

    def state(self, p):
        return json.loads(Path(p).read_text(encoding="utf-8"))

    def main(self, args, client_factory, ctx=None):
        real = mock.Mock(side_effect=AssertionError("실제 클라이언트 생성 금지"))
        out = io.StringIO()
        with mock.patch.object(run, "prepare", return_value=ctx or self.ctx), \
                mock.patch.dict(os.environ, {llm.API_KEY_ENV: DUMMY_KEY}), \
                mock.patch("anthropic.Anthropic", real), \
                mock.patch.object(run.llm, "AnthropicClient", mock.Mock(side_effect=client_factory)), \
                redirect_stdout(out):
            try:
                code = run.main(args + ["--approvals-dir", str(self.approvals), "--out-root", str(self.root / "runs")])
            finally:
                self.assertEqual(real.call_count, 0)
        return code, out.getvalue()


class Interrupts(Base):
    def fake(self, mapping=None):
        return llm.FakeClient(write_fakes(self.root / f"fake{len(list(self.root.glob('fake*')))}",
                                          mapping or {c: ok_msg(c, i) for i, c in enumerate(CHUNKS)}))

    def test_preparation_error_before_call_unused(self):
        eid, p = self.estimate()
        real_write = run.write_json

        def failing(path, obj):
            if "request" in str(path):
                raise ExtractError("준비 단계 오류(가짜): 요청 파일을 쓸 수 없음")
            return real_write(path, obj)

        with mock.patch.object(run, "write_json", side_effect=failing):
            code, text = self.main(["--execute", "--approve", eid, "--run-id", "i1"], lambda: self.fake())
        self.assertEqual(code, 1, text)
        rec = self.state(p)
        self.assertEqual(rec["state"], "unused")
        self.assertEqual(rec["history"][-1]["event"], "released")
        self.assertEqual(rec["history"][-1]["evidence"]["sent_attempts"], 0)

    def test_keyboard_interrupt_first_call_usage_check(self):
        eid, p = self.estimate()
        with self.assertRaises(KeyboardInterrupt):
            self.main(["--execute", "--approve", eid, "--run-id", "i2"], lambda: InterruptingClient(self.fake(), 1))
        rec = self.state(p)
        self.assertEqual(rec["state"], "usage_check_required")
        self.assertTrue(rec["history"][-1]["evidence"]["uncertain"])
        journal = [json.loads(x) for x in (self.root / "runs" / "i2" / "attempts.jsonl").read_text(
            encoding="utf-8").splitlines()]
        self.assertEqual([j["phase"] for j in journal], ["prepared", "sending"])
        self.assertEqual(ledger.approval_state(eid)[0], "usage_check_required")
        # 불확실한 승인은 resolve 전까지 다시 실행할 수 없다
        code, text = self.main(["--execute", "--approve", eid, "--run-id", "i2b"], lambda: self.fake())
        self.assertEqual(code, 2)
        self.assertIn("usage_check_required", text)

    def test_interpret_failure_after_200_used(self):
        bad = dict(self.ctx, adapter=BadInterpretAdapter())
        eid, p = self.estimate(bad)
        code, text = self.main(["--execute", "--approve", eid, "--run-id", "i3"], lambda: self.fake(), ctx=bad)
        self.assertEqual(code, 0, text)
        self.assertEqual(self.state(p)["state"], "used")
        _, rows = S.read_rows(self.root / "runs" / "i3" / "rejected.csv")
        self.assertTrue(all(r["reason_code"] == "call_failed" and "해석 실패" in r["reason"] for r in rows))
        self.assertEqual(len(rows), len(CHUNKS))
        phases = [json.loads(x)["phase"] for x in (self.root / "runs" / "i3" / "attempts.jsonl").read_text(
            encoding="utf-8").splitlines()]
        self.assertIn("interpret_failed", phases)

    def test_interrupt_in_flight_after_success_usage_check(self):
        # 앞 청크는 200, 다음 청크를 보내는 중 끊김 → usage_check_required(끊긴 호출이 생성·소모됐는지 모름).
        # 부분 실행 정보(200 받은 청크)는 증거로 남긴다.
        eid, p = self.estimate()
        with self.assertRaises(KeyboardInterrupt):
            self.main(["--execute", "--approve", eid, "--run-id", "i4"], lambda: InterruptingClient(self.fake(), 2))
        rec = self.state(p)
        self.assertEqual(rec["state"], "usage_check_required")
        self.assertEqual(rec["history"][-1]["evidence"]["http_200_chunks"], [CHUNKS[0]])

    def test_interrupt_between_calls_after_success_used(self):
        # 앞 청크 200 뒤, 다음 청크를 보내기 전(호출 간격 대기 중) 끊김 → 보낸 시도는 모두 응답을 받음 → used + 부분 실행
        eid, p = self.estimate(dict(self.ctx, min_interval_s=1.0))
        ctx = dict(self.ctx, min_interval_s=1.0)
        with mock.patch.object(run.time, "sleep", side_effect=KeyboardInterrupt()), self.assertRaises(KeyboardInterrupt):
            self.main(["--execute", "--approve", eid, "--run-id", "i5"], lambda: self.fake(), ctx=ctx)
        rec = self.state(p)
        self.assertEqual(rec["state"], "used")
        self.assertEqual(rec["partial_run"]["completed"], [CHUNKS[0]])
        self.assertEqual(rec["history"][-1]["evidence"]["uncertain"], [])

    def test_server_errors_only_restored(self):
        eid, p = self.estimate()
        m = {c: ok_msg(c) for c in CHUNKS}
        m[CHUNKS[0]] = {"__raise__": "auth"}
        code, text = self.main(["--execute", "--approve", eid, "--run-id", "i6"], lambda: self.fake(m))
        self.assertEqual(code, 3)
        self.assertEqual(self.state(p)["state"], "unused")

    def test_timeout_or_5xx_usage_check(self):
        for kind in ("timeout", "internal"):
            with self.subTest(kind):
                self.approvals = self.root / f"approvals-{kind}"  # 같은 초에 만든 추정은 ID가 같으므로 폴더를 나눔
                eid, p = self.estimate()
                m = {c: ok_msg(c) for c in CHUNKS}
                m[CHUNKS[0]] = {"__raise__": kind}
                code, _ = self.main(["--execute", "--approve", eid, "--run-id", f"i7{kind}"], lambda: self.fake(m))
                self.assertEqual(code, 3)
                self.assertEqual(self.state(p)["state"], "usage_check_required")

    def test_decide_unreadable_journal(self):
        self.assertEqual(approval.decide(None)[0], "usage_check_required")
        self.assertEqual(approval.decide([])[0], "unused")


def env_for(test):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    env[ledger.ENV_LEDGER] = str(ledger.current_path())
    env[locks.ENV_LOCKS] = str(locks.lock_dir())
    env.pop(llm.API_KEY_ENV, None)
    return env


def spawn(test, *args):
    return subprocess.Popen([sys.executable, str(HELPER), *map(str, args)], env=env_for(test),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")


class Processes(Base):
    def test_concurrent_reserve_exactly_one(self):
        eid, p = self.estimate()
        start = self.root / "go"
        procs = [spawn(self, "reserve", p, f"p{i}", start) for i in range(4)]
        time.sleep(0.5)
        start.write_text("go", encoding="utf-8")
        outs = [pr.communicate(timeout=60) for pr in procs]
        codes = [pr.returncode for pr in procs]
        self.assertEqual(sorted(codes), [0, 1, 1, 1], outs)
        rec = self.state(p)
        self.assertEqual(rec["state"], "reserved")
        self.assertEqual(ledger.verify_approval(p), [])
        self.assertEqual(sum(1 for h in rec["history"] if h["event"] == "reserved"), 1)

    def test_concurrent_ledger_appends_chain_valid(self):
        start = self.root / "go"
        procs = [spawn(self, "append", f"{i:016x}", 15, start) for i in range(4)]
        time.sleep(0.5)
        start.write_text("go", encoding="utf-8")
        for pr in procs:
            out, err = pr.communicate(timeout=60)
            self.assertEqual(pr.returncode, 0, err)
        _, entries = ledger.load()  # 사슬 검사 포함
        self.assertEqual([e["seq"] for e in entries], list(range(1, 61)))

    def test_killed_while_reserved_next_run_usage_check(self):
        eid, p = self.estimate()
        ready = self.root / "ready"
        journal = self.root / "runs" / "dead" / "attempts.jsonl"
        journal.parent.mkdir(parents=True)
        pr = spawn(self, "hold", p, "dead", journal, ready)
        end = time.monotonic() + 30
        while not ready.exists():
            self.assertLess(time.monotonic(), end, pr.stderr.read() if pr.poll() is not None else "")
            time.sleep(0.02)
        with self.assertRaises(ExtractError) as cm:  # 살아 있는 동안: 다른 실행이 쥐고 있음
            approval.check_approval(eid, self.approvals, self.ctx)
        self.assertIn("reserved", str(cm.exception))
        pr.kill()
        pr.communicate(timeout=30)
        with self.assertRaises(ExtractError) as cm:  # 죽은 뒤: usage_check_required(unused 아님)
            approval.check_approval(eid, self.approvals, self.ctx)
        self.assertIn("usage_check_required", str(cm.exception))
        rec = self.state(p)
        self.assertEqual(rec["state"], "usage_check_required")
        self.assertTrue(rec["history"][-1]["evidence"]["uncertain"])
        with locks.approval_lock(eid, timeout=2):  # 잠금도 다시 잡을 수 있다
            pass

    def test_failed_reserve_makes_zero_calls(self):
        eid, p = self.estimate(dict(self.ctx, requests=self.ctx["requests"][:1]))
        fake = write_fakes(self.root / "fake", {CHUNKS[0]: ok_msg(CHUNKS[0])})
        start = self.root / "go"
        procs = [spawn(self, "run", p, f"r{i}", self.root / "runs", fake, CHUNKS[0], start) for i in range(2)]
        time.sleep(1.5)
        start.write_text("go", encoding="utf-8")
        results = []
        for pr in procs:
            out, err = pr.communicate(timeout=120)
            calls = [ln for ln in out.splitlines() if ln.startswith("CALLS")]
            self.assertTrue(calls, err)
            results.append((pr.returncode, int(calls[-1].split()[1])))
        self.assertEqual(sorted(results), [(0, 1), (1, 0)], results)  # 예약에 진 쪽은 가짜 호출 0회

    def test_failure_between_ledger_and_file_closed(self):
        eid, p = self.estimate()
        with mock.patch.object(approval, "_write_file", side_effect=OSError("디스크 쓰기 실패(가짜)")):
            with self.assertRaises(OSError):
                approval.reserve(p, "half")
        self.assertEqual(ledger.approval_state(eid)[0], "reserved")  # 장부에는 먼저 적힘
        self.assertEqual(self.state(p)["state"], "unused")           # 파일은 그대로
        with self.assertRaises(ExtractError) as cm:
            approval.check_approval(eid, self.approvals, self.ctx)   # 어긋남 → 거부(추가 호출 없음)
        self.assertIn("장부", str(cm.exception))
        with self.assertRaises(ExtractError):
            approval.reserve(p, "again")

    def test_lock_timeout_message(self):
        with locks.approval_lock("abc", timeout=1):
            t0 = time.monotonic()
            with self.assertRaises(ExtractError) as cm:
                locks.approval_lock("abc", timeout=0.2).acquire()
            self.assertLess(time.monotonic() - t0, 2.0)
        self.assertIn("잠금을 얻지 못함", str(cm.exception))


class Pacing(unittest.TestCase):
    def setUp(self):
        tmp = S.tmpdir()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def client(self, mapping):
        return llm.FakeClient(write_fakes(self.root / f"f{len(list(self.root.glob('f*')))}", mapping))

    def call(self, client, key, interval, clock):
        pacer = llm.Pacer(interval, clock.sleep, clock)
        return llm.call_with_policy(client, {}, key, llm.RetryBudget(), adapter=llm.ANTHROPIC, pacer=pacer), pacer

    def test_chunk_to_chunk(self):
        clock = S.FakeClock()
        pacer = llm.Pacer(7.5, clock.sleep, clock)
        for _ in range(3):
            pacer.wait()
            pacer.started()
        self.assertEqual(clock.sleeps, [7.5, 7.5])

    def test_retry_same_chunk_paced(self):
        clock = S.FakeClock()
        c = self.client({"k": {"__sequence__": [{"__raise__": "rate_limit"}, ok_msg("k")]}})
        r, _ = self.call(c, "k", 7.5, clock)
        self.assertTrue(r.ok)
        self.assertEqual(clock.sleeps, [7.5])  # backoff 2초가 아니라 간격 7.5초(한 번만)

    def test_retry_after_shorter_and_longer(self):
        for ra, expect in ((3, 7.5), (20, 20.0)):
            with self.subTest(ra):
                clock = S.FakeClock()
                c = self.client({"k": {"__sequence__": [{"__raise__": "rate_limit", "retry_after": ra}, ok_msg("k")]}})
                r, _ = self.call(c, "k", 7.5, clock)
                self.assertEqual(clock.sleeps, [expect])
                self.assertEqual(r.attempts[0]["wait_s"], expect)

    def test_next_chunk_after_retry_and_caps(self):
        why = S.needs_inputs()
        if why:
            self.skipTest(why)
        S.use_ledger(self, self.root / "ledger.jsonl")
        ctx = dict(run.prepare(chunk_ids=CHUNKS[:2], provider="anthropic"), min_interval_s=7.5)
        m = {CHUNKS[0]: {"__sequence__": [{"__raise__": "rate_limit", "retry_after": 20}, ok_msg(CHUNKS[0])]},
             CHUNKS[1]: ok_msg(CHUNKS[1])}
        clock = S.FakeClock()
        res = run.run_calls(ctx, self.client(m), self.root / "run", "pace", "fake", sleep=clock.sleep, clock=clock,
                            max_chunks=2, max_attempts=approval.attempt_cap(2))
        self.assertEqual(clock.sleeps, [20.0, 7.5])  # 재시도 20초, 다음 청크는 마지막 시도 기준 7.5초
        meta = res["meta"]
        self.assertEqual((meta["approved_chunks"], meta["approved_attempts"]), (2, 6))
        self.assertEqual((meta["actual_chunks"], meta["actual_attempts"]), (2, 3))
        self.assertEqual(len(meta["retries"]), 1)
        self.assertEqual(meta["retries"][0]["wait_s"], 20.0)


if __name__ == "__main__":
    unittest.main()
