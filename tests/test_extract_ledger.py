"""C: git 추적 해시 장부(harness/extraction_ledger.jsonl) 반례. 2차 검증 FAIL (j) 일관된 위조를 막는지 확인한다.
저장소의 실제 장부는 건드리지 않는다(작업 공간마다 임시 장부).

실행: PYTHONPATH=src .venv/Scripts/python.exe -m unittest tests.test_extract_ledger -v
"""
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_fakes  # noqa: E402
import extract_support as S  # noqa: E402
from imaks_kg import settings  # noqa: E402
from imaks_kg.common.provenance import sha256_file  # noqa: E402
from imaks_kg.extract import approval, ledger, llm, review, run, to_rdf  # noqa: E402
from imaks_kg.extract.common import ExtractError, read_jsonl  # noqa: E402

CHUNKS = ["SOP-001:p1:RULE-ST01-02", "SOP-001:p1:RULE-ST02-02", "SOP-003:p1:table1:chunk", "SOP-004:p1:RULE-ACCESS-02"]
TARGET = "SOP-001:p1:RULE-ST02-02:r1"
OUT_NAMES = (settings.RULES_LLM_TTL.name, settings.RULES_LLM_PREREVIEW_TTL.name, settings.SEED_RULES_LLM_TTL.name)
ALLOWED_KEYS = {"seq", "time", "run_id", "event", "files", "prev_sha256", "estimate_id", "state"}


class Ledger(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        why = S.needs_inputs()
        if why:
            raise unittest.SkipTest(why)
        cls.repo_ledger_sha = sha256_file(settings.EXTRACTION_LEDGER) if settings.EXTRACTION_LEDGER.exists() else None
        cls._tmp = S.tmpdir()
        root = Path(cls._tmp.name)
        cls._before = ledger.LEDGER_OVERRIDE
        cls.ctx = run.prepare(chunk_ids=CHUNKS, provider="anthropic")
        cls.pre = root / "pre"
        cls.pre.mkdir()
        ledger.LEDGER_OVERRIDE = cls.pre / "ledger.jsonl"
        fake = extract_fakes.write(root / "fake", extract_fakes.build(CHUNKS))
        run.run_calls(cls.ctx, llm.FakeClient(fake), cls.pre / "run", "t-ledger", "fake")
        S.fill_round1(cls.pre / "run")
        review.make_round2(cls.pre / "run")
        cls.post = root / "post"
        shutil.copytree(cls.pre, cls.post)
        ledger.LEDGER_OVERRIDE = cls.post / "ledger.jsonl"
        review.apply_review(cls.post / "run")
        to_rdf.run(cls.post / "run", cls.post / "out")
        ledger.LEDGER_OVERRIDE = cls._before

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()
        now = sha256_file(settings.EXTRACTION_LEDGER) if settings.EXTRACTION_LEDGER.exists() else None
        assert now == cls.repo_ledger_sha, "저장소 장부가 바뀜"

    def ws(self, base):
        tmp = S.tmpdir()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name) / "ws"
        shutil.copytree(base, d)
        S.use_ledger(self, d / "ledger.jsonl")
        return d

    def outputs(self, d):
        return {n: ((d / "out" / n).read_bytes(), (d / "out" / n).stat().st_mtime_ns) for n in OUT_NAMES}

    def assert_stops(self, d, *needles):
        before = self.outputs(d)
        with self.assertRaises(ExtractError) as cm:
            to_rdf.run(d / "run", d / "out")
        for n in needles:
            self.assertIn(n, str(cm.exception))
        self.assertEqual(self.outputs(d), before)  # 기존 출력 불변
        return str(cm.exception)

    def test_normal_passes(self):
        d = self.ws(self.post)
        res = to_rdf.run(d / "run", d / "out2")
        ok, text = S.shacl(res["merged_graph"])
        self.assertTrue(ok, text)
        _, entries = ledger.load()
        events = [e["event"] for e in entries]
        for ev in ("run_finished", "merge_finished", "round1_created", "round2_created", "apply_finished", "to_rdf_output"):
            self.assertIn(ev, events)
        for e in entries:
            self.assertLessEqual(set(e), ALLOWED_KEYS)
        text = (d / "ledger.jsonl").read_text(encoding="utf-8")
        for r in read_jsonl(d / "run" / "final.jsonl"):
            self.assertNotIn(r["sourceQuote"], text)  # 규칙 내용·인용은 장부에 없다
            self.assertNotIn(r["responseText"], text)

    def forge_j(self, d):
        """2차 검증 (j): 1차 결정 accept→reject + final에서 그 레코드 삭제 + applied 해시·집계 재계산 +
        manifest round2.round1_sha256까지 위조(applied·manifest·파일이 서로 맞음)."""
        rd = d / "run"
        header, rows = S.read_rows(rd / "review_round1.csv")
        for r in rows:
            if r["item_id"] == TARGET:
                r["decision"] = "reject"
        S.write_rows(rd / "review_round1.csv", header, rows)
        lines = [ln for ln in (rd / "final.jsonl").read_text(encoding="utf-8").splitlines()
                 if f'"candidate_id": "{TARGET}"' not in ln]
        (rd / "final.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        rec = json.loads((rd / "review_applied.json").read_text(encoding="utf-8"))
        rec["round1"]["sha256"] = sha256_file(rd / "review_round1.csv")
        rec["final_jsonl_sha256"] = sha256_file(rd / "final.jsonl")
        rec.update(review.tally(read_jsonl(rd / "final.jsonl"), read_jsonl(rd / "merged.jsonl")))
        (rd / "review_applied.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        man = json.loads((rd / "review_manifest.json").read_text(encoding="utf-8"))
        man["round2"]["round1_sha256"] = sha256_file(rd / "review_round1.csv")
        (rd / "review_manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_j_consistent_forgery_stops(self):
        d = self.ws(self.post)
        self.forge_j(d)
        # 장부 검사가 없으면 통과해 버리는 위조임을 먼저 보인다(검증자 재현)
        with mock.patch.object(ledger, "verify_run", lambda *a, **k: None):
            to_rdf.run(d / "run", d / "out_noledger")
        msg = self.assert_stops(d, "해시 장부", "review_round1.csv")
        self.assertIn("final.jsonl", msg)
        self.assertIn("review_manifest.json", msg)

    def test_middle_entry_deleted_or_edited(self):
        d = self.ws(self.post)
        lines = (d / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
        (d / "ledger.jsonl").write_text("\n".join(lines[:2] + lines[3:]) + "\n", encoding="utf-8")
        self.assert_stops(d, "사슬")
        d = self.ws(self.post)
        lines = (d / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
        e = json.loads(lines[1])
        e["time"] = "2000-01-01T00:00:00+00:00"
        lines[1] = json.dumps(e, ensure_ascii=False, sort_keys=True)
        (d / "ledger.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assert_stops(d, "사슬")

    def test_ledger_missing_or_run_absent(self):
        d = self.ws(self.post)
        (d / "ledger.jsonl").unlink()
        self.assert_stops(d, "해시 장부가 없음")
        d = self.ws(self.post)
        (d / "ledger.jsonl").write_text("", encoding="utf-8")
        self.assert_stops(d, "기록이 없음")

    def test_stages_check_ledger(self):
        d = self.ws(self.pre)  # apply 전: 장부에 이 실행 기록이 없으면 apply도 멈춘다
        rd = d / "run"
        (d / "ledger.jsonl").write_text("", encoding="utf-8")
        with self.assertRaises(ExtractError) as cm:
            review.apply_review(rd)
        self.assertIn("기록이 없음", str(cm.exception))
        self.assertFalse((rd / "final.jsonl").exists())

    def test_approval_used_to_unused_refused(self):
        S.use_ledger(self, Path(self.ws(self.post)) / "ledger.jsonl")
        est = run.estimate_tokens(self.ctx["requests"], self.ctx["adapter"])
        tmp = S.tmpdir()
        self.addCleanup(tmp.cleanup)
        p = approval.write_estimate(approval.build_estimate(self.ctx, est), Path(tmp.name))
        eid = json.loads(p.read_text(encoding="utf-8"))["estimate_id"]
        approval.reserve(p, "t-x")
        self.assertEqual(approval.finalize(p, "t-x", {"http_200": 1, "completed": CHUNKS}), "used")
        rec = json.loads(p.read_text(encoding="utf-8"))
        rec["state"] = "unused"  # 사람이 손으로 used → unused
        rec.pop("used_by_run_id")
        rec.pop("used_at")
        p.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        with self.assertRaises(ExtractError) as cm:
            approval.check_approval(eid, Path(tmp.name), self.ctx)
        self.assertIn("장부", str(cm.exception))
        with self.assertRaises(ExtractError):
            approval.reserve(p, "t-y")
        state, _, last = ledger.approval_state(eid)
        self.assertEqual((state, last["event"]), ("used", "used"))

    def test_min_interval_default(self):
        from imaks_kg.extract import llm_gemini
        self.assertEqual(llm_gemini.DEFAULT_MIN_INTERVAL_S, 7.5)
        self.assertEqual(llm_gemini.GeminiAdapter().default_min_interval_s, 7.5)


if __name__ == "__main__":
    unittest.main()
