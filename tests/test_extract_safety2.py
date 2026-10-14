"""C 실행 전 보완 검증 PARTIAL 후속(2026-10-14, 보고서 18장): 끊긴 실행의 완료·미완료 정보, journal 없는 정리의 보수성,
해석 실패 200의 원본 저장, 장부 불일치 거부 메시지. 가짜 클라이언트만 쓴다(실제 API 호출 0).

실행: PYTHONPATH=src .venv/Scripts/python.exe -m unittest tests.test_extract_safety2 -v
"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_support as S  # noqa: E402
from test_extract_safety import CHUNKS, Base, InterruptingClient, ok_msg, write_fakes  # noqa: E402
from imaks_kg.common.provenance import sha256_file  # noqa: E402
from imaks_kg.extract import approval, ledger, llm, run  # noqa: E402
from imaks_kg.extract.common import ExtractError  # noqa: E402


class InterruptInterpretAdapter(llm.AnthropicAdapter):
    """n번째 해석에서 KeyboardInterrupt(200을 받은 뒤 해석 중 끊김)."""

    def __init__(self, at):
        super().__init__()
        self.at, self.n = at, 0

    def interpret(self, key, response):
        self.n += 1
        if self.n == self.at:
            raise KeyboardInterrupt()
        return super().interpret(key, response)


class RaisingInterpretAdapter(llm.AnthropicAdapter):
    def interpret(self, key, response):
        raise ValueError("해석기 고장(가짜)")


def journal_of(root, run_id):
    p = Path(root) / "runs" / run_id / "attempts.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]


class PartialInfo(Base):
    def fake(self):
        return llm.FakeClient(write_fakes(self.root / f"fake{len(list(self.root.glob('fake*')))}",
                                          {c: ok_msg(c, i) for i, c in enumerate(CHUNKS)}))

    def last(self, p):
        return self.state(p)["history"][-1]

    def test_interrupt_during_wait_1_of_3(self):
        ctx = dict(self.ctx, min_interval_s=1.0)
        eid, p = self.estimate(ctx)
        with mock.patch.object(run.time, "sleep", side_effect=KeyboardInterrupt()), self.assertRaises(KeyboardInterrupt):
            self.main(["--execute", "--approve", eid, "--run-id", "w"], lambda: self.fake(), ctx=ctx)
        rec = self.state(p)
        self.assertEqual(rec["state"], "used")
        self.assertEqual(rec["partial_run"]["completed"], CHUNKS[:1])
        self.assertEqual(rec["partial_run"]["not_completed"], CHUNKS[1:])
        self.assertEqual((self.last(p)["completed"], self.last(p)["not_completed"]), (CHUNKS[:1], CHUNKS[1:]))

    def test_interrupt_during_interpretation(self):
        ctx = dict(self.ctx, adapter=InterruptInterpretAdapter(at=2))
        eid, p = self.estimate(ctx)
        with self.assertRaises(KeyboardInterrupt):
            self.main(["--execute", "--approve", eid, "--run-id", "ip"], lambda: self.fake(), ctx=ctx)
        rec = self.state(p)
        # 두 번째 청크는 200을 받은 뒤 해석 중 끊김: 200은 받았으므로 완료로 센다(used, 불확실 아님)
        self.assertEqual(rec["state"], "used")
        self.assertEqual(rec["partial_run"]["completed"], CHUNKS[:2])
        self.assertEqual(rec["partial_run"]["not_completed"], CHUNKS[2:])
        # 원본 본문은 해석 전에 저장되어 증거로 남는다
        saved = [j for j in journal_of(self.root, "ip") if j["phase"] == "raw_saved"]
        self.assertEqual([j["chunk_id"] for j in saved], CHUNKS[:2])
        for j in saved:
            self.assertEqual(sha256_file(self.root / "runs" / "ip" / j["file"]), j["sha256"])

    def test_interrupt_while_sending(self):
        eid, p = self.estimate()
        with self.assertRaises(KeyboardInterrupt):
            self.main(["--execute", "--approve", eid, "--run-id", "sd"], lambda: InterruptingClient(self.fake(), 2))
        last = self.last(p)
        self.assertEqual(self.state(p)["state"], "usage_check_required")
        self.assertEqual((last["completed"], last["not_completed"]), (CHUNKS[:1], CHUNKS[1:]))

    def test_outcome_lists_maintained_continuously(self):
        out = {}
        fake = self.fake()

        class StopAfterFirst:
            def __init__(self):
                self.calls = []

            def create(self, req, key):
                self.calls.append(key)
                if len(self.calls) == 2:
                    raise KeyboardInterrupt()
                return fake.create(req, key)

        with self.assertRaises(KeyboardInterrupt):
            run.run_calls(self.ctx, StopAfterFirst(), self.root / "runs" / "cont", "cont", "fake",
                          sleep=lambda s: None, outcome=out)
        self.assertEqual((out["completed"], out["not_completed"]), (CHUNKS[:1], CHUNKS[1:]))


class Evidence(Base):
    def reserved(self):
        eid, p = self.estimate()
        approval.reserve(p, "ev")
        return eid, p

    def test_no_journal_ambiguous_500_usage_check(self):
        _, p = self.reserved()
        out = {"http_200": 0, "attempts": [{"chunk_id": CHUNKS[0], "attempt": 1, "error_class": llm.AMBIGUOUS,
                                            "status": 500, "phase": "http_error_response"}]}
        self.assertEqual(approval.finalize(p, "ev", out, journal=None), "usage_check_required")

    def test_journal_missing_but_memory_has_attempt(self):
        _, p = self.reserved()
        out = {"http_200": 0, "attempts": [{"chunk_id": CHUNKS[0], "attempt": 1, "error_class": llm.AMBIGUOUS,
                                            "status": None, "phase": "transport_error"}]}
        self.assertEqual(approval.finalize(p, "ev", out, journal=self.root / "missing.jsonl"), "usage_check_required")

    def test_journal_missing_memory_zero_attempts_unused(self):
        _, p = self.reserved()
        self.assertEqual(approval.finalize(p, "ev", {"attempts": [], "http_200": 0},
                                           journal=self.root / "missing.jsonl"), "unused")

    def test_no_evidence_at_all_usage_check(self):
        _, p = self.reserved()
        self.assertEqual(approval.finalize(p, "ev", None, journal=self.root / "missing.jsonl"), "usage_check_required")

    def test_journal_and_memory_disagree_conservative(self):
        # journal: 보낸 시도가 서버 401로 끝남(unused 판정) / 메모리: 200을 받음 → used
        _, p = self.reserved()
        j = self.root / "j.jsonl"
        j.write_text("\n".join(json.dumps(x) for x in [
            {"chunk_id": CHUNKS[0], "attempt": 1, "phase": "sending"},
            {"chunk_id": CHUNKS[0], "attempt": 1, "phase": "http_error_response", "error_class": llm.FATAL_AUTH,
             "status": 401}]) + "\n", encoding="utf-8")
        out = {"http_200": 1, "attempts": [{"chunk_id": CHUNKS[1], "attempt": 1, "status": 200,
                                            "phase": "http_200_received"}]}
        self.assertEqual(approval.finalize(p, "ev", out, journal=j), "used")
        self.assertTrue(self.state(p)["history"][-1]["evidence"]["notes"])
        # journal: 보내는 중에 끝남(불확실) / 메모리: 아무것도 없음 → usage_check_required
        eid2, p2 = self.estimate(dict(self.ctx, requests=self.ctx["requests"][:2]))
        approval.reserve(p2, "ev2")
        j2 = self.root / "j2.jsonl"
        j2.write_text(json.dumps({"chunk_id": CHUNKS[0], "attempt": 1, "phase": "sending"}) + "\n", encoding="utf-8")
        self.assertEqual(approval.finalize(p2, "ev2", {"attempts": [], "http_200": 0}, journal=j2),
                         "usage_check_required")

    def test_legacy_attempt_with_phase_counts_as_sent(self):
        ev = approval._legacy_events({"attempts": [{"chunk_id": "c", "attempt": 1, "phase": "http_error_response",
                                                    "error_class": llm.AMBIGUOUS, "status": 500}]})
        self.assertEqual([e["phase"] for e in ev], ["sending", "http_error_response"])
        self.assertEqual(approval.decide(ev)[0], "usage_check_required")


class RawAndMessage(Base):
    def test_interpret_failure_raw_saved(self):
        ctx = dict(self.ctx, adapter=RaisingInterpretAdapter())
        eid, p = self.estimate(ctx)
        fake = llm.FakeClient(write_fakes(self.root / "fake", {c: ok_msg(c, i) for i, c in enumerate(CHUNKS)}))
        code, text = self.main(["--execute", "--approve", eid, "--run-id", "rf"], lambda: fake, ctx=ctx)
        self.assertEqual(code, 0, text)
        saved = [j for j in journal_of(self.root, "rf") if j["phase"] == "raw_saved"]
        self.assertEqual([j["chunk_id"] for j in saved], CHUNKS)
        for j in saved:
            f = self.root / "runs" / "rf" / j["file"]
            self.assertEqual(sha256_file(f), j["sha256"])
            self.assertIn("content", json.loads(f.read_text(encoding="utf-8")))  # 원본 본문(실패 기록이 아님)

    def test_ledger_mismatch_message(self):
        eid, p = self.estimate()
        with mock.patch.object(approval, "_write_file", side_effect=OSError("쓰기 실패(가짜)")):
            with self.assertRaises(OSError):
                approval.reserve(p, "half")
        with self.assertRaises(ExtractError) as cm:
            approval.check_approval(eid, self.approvals, self.ctx)
        msg = str(cm.exception)
        self.assertIn("해시 장부와 승인 파일이 어긋남", msg)
        self.assertIn("장부의 기대 상태 reserved", msg)
        self.assertIn("파일의 상태 unused", msg)
        self.assertIn("새 추정", msg)
        self.assertNotIn("다른 실행이 예약 중", msg)
        with self.assertRaises(ExtractError) as cm:
            approval.reserve(p, "again")
        self.assertIn("어긋남", str(cm.exception))
        self.assertEqual(ledger.approval_state(eid)[0], "reserved")


if __name__ == "__main__":
    unittest.main()
