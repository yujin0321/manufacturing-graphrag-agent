"""사람 검토 기록 시험: 1·2단계 파일, 표본 시드 재현, 적용 시 predictions 불변."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_b_helpers as h  # noqa: E402
from test_extract_b_outputs import do_run, read_csv  # noqa: E402

from imaks_kg.extract import review  # noqa: E402
from imaks_kg.extract.artifacts import file_sha256  # noqa: E402


def fill(path, edits):
    """edits: {rule_key: dict(열=값)}. 머리 주석을 유지한 채 값을 채운다."""
    head, rows = review.read_review_csv(path)
    for r in rows:
        r.update(edits.get(r["rule_key"], {}))
    review.write_review_csv(path, head, rows)


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


R = {"reviewer": "tester", "reviewed_at": "2026-10-14T10:00:00"}


class Review(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.cfg, self.rr, _, _ = do_run(self.tmp)
        self.root = self.tmp / "out"
        self.d = self.rr.out_dir

    def tearDown(self):
        self._t.cleanup()

    def init(self, stage, **kw):
        return review.init_review("mock-t1", stage, out_root=self.root, **kw)

    def test_stage1_lists_flagged_rules_with_notice_and_input_columns(self):
        self.init(1)
        text = (self.d / "review_stage1.csv").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# 사람 검토 1단계. 검토 기준은 SOP 원문뿐입니다. 정답 파일과 비교해 고치지 마세요."))
        head, rows = review.read_review_csv(self.d / "review_stage1.csv")
        self.assertEqual(len(rows), 3)
        self.assertEqual(list(rows[0])[-7:], ["decision", "edited_condition", "edited_action", "edited_identifier",
                                              "reason", "reviewer", "reviewed_at"])
        self.assertEqual({r["flags"] for r in rows}, {"evidence_not_found", "id_not_in_allowlist", "table_position_out_of_range"})
        self.assertIn("SOP 원문뿐", review.NOTICE)
        with self.assertRaises(review.ReviewError):
            self.init(1)   # 덮어쓰지 않는다

    def test_stage2_requires_stage1_and_sample_is_seed_reproducible(self):
        with self.assertRaises(review.ReviewError):
            self.init(2)
        self.init(1)
        keys = [r["rule_key"] for r in review.read_review_csv(self.d / "review_stage1.csv")[1]]
        fill(self.d / "review_stage1.csv", {keys[0]: dict(decision="accept", **R), keys[1]: dict(decision="reject", reason="x", **R)})
        self.init(2, seed=7, fraction=0.5)
        meta = json.loads((self.d / "review_stage2.meta.json").read_text(encoding="utf-8"))
        # 모집단 = 플래그 없는 3 + 1단계 accept 1 = 4, 표본 = 2
        self.assertEqual((meta["seed"], meta["pool_size"], meta["sampled"]), (7, 4, 2))
        first = (self.d / "review_stage2.csv").read_text(encoding="utf-8")
        self.assertIn("seed=7", first)
        (self.d / "review_stage2.csv").unlink()
        self.init(2, seed=7, fraction=0.5)
        self.assertEqual((self.d / "review_stage2.csv").read_text(encoding="utf-8"), first)
        (self.d / "review_stage2.csv").unlink()
        self.init(2, seed=8, fraction=0.5)
        # 시드가 다르면 (우연히 같을 수 있으나) 시드는 기록이 달라진다
        self.assertIn("seed=8", (self.d / "review_stage2.csv").read_text(encoding="utf-8"))

    def test_default_fraction_is_about_20_percent_and_seed_recorded(self):
        self.init(1)
        self.init(2)
        meta = json.loads((self.d / "review_stage2.meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["fraction"], 0.2)
        self.assertIsInstance(meta["seed"], int)
        self.assertEqual(meta["sampled"], max(1, round(0.2 * meta["pool_size"])))

    def test_apply_keeps_predictions_and_records_history(self):
        pred = self.d / "predictions.jsonl"
        before = file_sha256(pred)
        valid_before = file_sha256(self.d / "rules_valid.jsonl")
        self.init(1)
        rows = review.read_review_csv(self.d / "review_stage1.csv")[1]
        by_flag = {r["flags"]: r["rule_key"] for r in rows}
        fill(self.d / "review_stage1.csv", {
            by_flag["evidence_not_found"]: dict(decision="reject", reason="인용이 원문에 없음", **R),
            by_flag["id_not_in_allowlist"]: dict(decision="edit", edited_condition="fixed condition text", reason="조건 정정", **R),
            by_flag["table_position_out_of_range"]: dict(decision="accept", reason="원문 확인", **R)})
        self.init(2, seed=1, fraction=1.0)
        s2 = review.read_review_csv(self.d / "review_stage2.csv")[1]
        fill(self.d / "review_stage2.csv", {s2[0]["rule_key"]: dict(decision="edit", edited_action="new action", reason="보완", **R)})
        msg = review.apply_review("mock-t1", out_root=self.root)
        self.assertEqual(file_sha256(pred), before)                       # 자동 추출 결과 불변
        self.assertEqual(file_sha256(self.d / "rules_valid.jsonl"), valid_before)
        final = jl(self.d / "rules_final.jsonl")
        self.assertEqual(len(final), 5)   # 6개 - reject 1
        self.assertTrue(all("human_reviewed" in r for r in final))
        edited = [r for r in final if r["condition"] == "fixed condition text"][0]
        h0 = edited["review_history"][0]
        self.assertEqual((h0["field"], h0["after"], h0["reason"], h0["reviewer"], h0["reviewed_at"]),
                         ("condition", "fixed condition text", "조건 정정", "tester", "2026-10-14T10:00:00"))
        self.assertEqual(h0["before"], "mentions a sensor outside the list")
        self.assertTrue(edited["human_reviewed"])
        self.assertIn("id_not_in_allowlist", edited["flags_at_extraction"])
        self.assertEqual(sum(1 for r in final if r["human_reviewed"]), 3)
        log = jl(self.d / "review_log.jsonl")
        self.assertTrue(any(x["decision"] == "reject" for x in log))
        self.assertIn("predictions.jsonl 해시 불변", msg)

    def test_pending_flagged_rules_are_excluded_and_counted(self):
        self.init(1)
        review.apply_review("mock-t1", out_root=self.root)
        final = jl(self.d / "rules_final.jsonl")
        self.assertEqual(len(final), 3)    # 결정 없는 플래그 규칙 3개는 제외
        self.assertFalse(any(r["human_reviewed"] for r in final))
        summ = json.loads((self.d / "review_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summ["stage1_pending_excluded"], 3)

    def test_invalid_rows_rejected(self):
        self.init(1)
        key = review.read_review_csv(self.d / "review_stage1.csv")[1][0]["rule_key"]
        for row in (dict(decision="maybe", **R), dict(decision="accept", reviewer="x"), dict(decision="edit", **R),
                    dict(decision="reject", **R)):
            fill(self.d / "review_stage1.csv", {key: row})
            with self.assertRaises(review.ReviewError, msg=str(row)):
                review.apply_review("mock-t1", out_root=self.root)
            fill(self.d / "review_stage1.csv", {key: dict(decision="", edited_condition="", reviewer="", reviewed_at="", reason="")})


if __name__ == "__main__":
    unittest.main()
