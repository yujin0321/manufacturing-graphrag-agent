"""C: 2단계 사람 검토(1차 양식, 2차 생성, apply의 멈춤 조건과 재검사) (가짜 응답만).

실행: PYTHONPATH=src .venv/Scripts/python.exe -m unittest tests.test_extract_review -v
"""
import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_support as S  # noqa: E402
from imaks_kg.common.provenance import sha256_file  # noqa: E402
from imaks_kg.extract import review  # noqa: E402
from imaks_kg.extract.common import ExtractError, read_jsonl  # noqa: E402

ST0102 = "SOP-001:p1:RULE-ST01-02:r1"
MAINT02 = "SOP-003:p1:table1:chunk:r2"
PATTERN = "SOP-003:p1:table2:chunk:r1"


class Review(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        why = S.needs_inputs()
        if why:
            raise unittest.SkipTest(why)
        cls.ctx = S.ctx()
        cls._tmp = S.tmpdir()
        cls.base = S.fake_run(cls._tmp.name, "t-review-base")
        cls.base_ledger = S.copy_ledger(Path(cls._tmp.name) / "base_ledger.jsonl")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def fresh(self):
        tmp = S.tmpdir()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name) / "run"
        shutil.copytree(self.base, d)
        S.use_ledger(self, S.copy_ledger_from(self.base_ledger, Path(tmp.name) / "ledger.jsonl"))  # 실행과 함께 장부도 복사
        return d

    def test_round1_template(self):
        header, rows = S.read_rows(self.base / "review_round1.csv")
        self.assertEqual(tuple(header), review.ROUND1_FIELDS)
        recs = read_jsonl(self.base / "merged.jsonl")
        cand_rows = [r for r in rows if r["row_type"] == "candidate"]
        self.assertEqual([r["item_id"] for r in cand_rows], [r["candidate_id"] for r in recs])
        conf = [r for r in rows if r["row_type"] == "merge_conflict"]
        _, mc = S.read_rows(self.base / "merge_conflicts.csv")
        self.assertEqual([r["item_id"] for r in conf], [r["conflict_id"] for r in mc])
        self.assertTrue(conf)
        for r in rows:
            self.assertEqual((r["decision"], r["edited_fields"], r["comment"]), ("", "", ""))
        fb = [r for r in cand_rows if r["served_by_fallback"] == "yes"]
        self.assertEqual([r["chunk_id"] for r in fb], ["SOP-001:p2:RULE-SRV01-01"])
        self.assertEqual({r["merged"] for r in cand_rows if r["chunk_id"] == "SOP-003:p1:table1:chunk"}, {"yes"})

    def test_round2_only_edit_hold(self):
        d = self.fresh()
        S.fill_round1(d, overrides={ST0102: ("edit", json.dumps({"conditionText": "If TMP exceeds 26°C"})),
                                    PATTERN: ("hold", ""), f"{MAINT02}#conditionText": ("hold", ""),
                                    "SOP-002:p1:text1:r1": ("reject", "")})
        out = review.make_round2(d)
        self.assertEqual([r["item_id"] for r in out], [ST0102, PATTERN, f"{MAINT02}#conditionText"])
        _, rows = S.read_rows(d / "review_round2.csv")
        self.assertEqual([r["round1_decision"] for r in rows], ["edit", "hold", "hold"])
        with self.assertRaises(ExtractError):
            review.make_round2(d)  # 덮어쓰지 않음

    def test_undecided_stops(self):
        d = self.fresh()
        with self.assertRaises(ExtractError):  # 1차 전부 빈 결정
            review.apply_review(d)
        S.fill_round1(d, overrides={ST0102: ("", "")})
        with self.assertRaises(ExtractError) as cm:
            review.apply_review(d)
        self.assertIn("미결정", str(cm.exception))
        S.fill_round1(d, overrides={ST0102: ("hold", "")})
        with self.assertRaises(ExtractError):  # 2차 파일 없음
            review.apply_review(d)
        review.make_round2(d)
        with self.assertRaises(ExtractError) as cm:  # 2차 빈 결정
            review.apply_review(d)
        self.assertIn("2차 미결정", str(cm.exception))
        S.fill_round2(d, {ST0102: ("hold", "")})
        with self.assertRaises(ExtractError):  # 2차에 hold 불가
            review.apply_review(d)
        self.assertFalse((d / "final.jsonl").exists())

    def test_edits_revalidated(self):
        d = self.fresh()
        S.fill_round1(d, overrides={ST0102: ("edit", json.dumps({"sourceQuote": "If TMP exceeds 26 °C"}))})
        review.make_round2(d)
        S.fill_round2(d, {ST0102: ("accept", "")})
        with self.assertRaises(ExtractError) as cm:
            review.apply_review(d)
        self.assertIn("quote_not_in_chunk", str(cm.exception))

    def test_edit_out_of_list_rejected(self):
        d = self.fresh()
        S.fill_round1(d, overrides={ST0102: ("hold", "")})
        review.make_round2(d)
        S.fill_round2(d, {ST0102: ("edit", json.dumps({"sensors": ["ST01_FILLING_CO2"]}))})
        with self.assertRaises(ExtractError) as cm:
            review.apply_review(d)
        self.assertIn("sensor_not_in_list", str(cm.exception))

    def test_valid_edit_applied_and_reprovenanced(self):
        d = self.fresh()
        S.fill_round1(d, overrides={
            ST0102: ("edit", json.dumps({"sourceQuote": "If TMP exceeds 26°C, reduce speed by 10% and notify QC."})),
            "SOP-002:p1:text1:r1": ("reject", "")})
        review.make_round2(d)
        S.fill_round2(d, {ST0102: ("edit", json.dumps({"conditionText": "If TMP exceeds 26°C"}))})
        before = {p: sha256_file(d / p) for p in ("merged.jsonl", "candidates_premerge.jsonl", "review_round1.csv",
                                                     "review_round2.csv")}
        final, summary = review.apply_review(d)
        rec = next(r for r in final if r["candidate_id"] == ST0102)
        self.assertEqual(rec["conditionText"], "If TMP exceeds 26°C")
        self.assertEqual(rec["review"], {"decision": "edit", "edited_fields": ["conditionText", "sourceQuote"]})
        q = "If TMP exceeds 26°C, reduce speed by 10% and notify QC."
        self.assertEqual(rec["provenance"]["charStart"], 1061 + len("RULE-ST01-02: "))
        self.assertEqual(rec["provenance"]["charEnd"] - rec["provenance"]["charStart"], len(q))
        self.assertNotIn("SOP-002:p1:text1:r1", {r["candidate_id"] for r in final})
        self.assertEqual(summary["counts"]["rejected"], 1)
        # 원본·1차·2차 보존
        for p, h in before.items():
            self.assertEqual(sha256_file(d / p), h)
        self.assertTrue((d / "raw" / "response").is_dir())
        with self.assertRaises(ExtractError):
            review.apply_review(d)  # final.jsonl 덮어쓰지 않음

    def test_merged_candidate_only_quote_editable_and_conflict_no_edit(self):
        d = self.fresh()
        S.fill_round1(d, overrides={MAINT02: ("edit", json.dumps({"conditionText": "x"}))})
        with self.assertRaises(ExtractError):
            review.make_round2(d)
        d = self.fresh()
        S.fill_round1(d, overrides={f"{MAINT02}#conditionText": ("edit", json.dumps({"sourceQuote": "x"}))})
        with self.assertRaises(ExtractError):
            review.make_round2(d)

    def test_template_columns_locked(self):
        d = self.fresh()
        rows = S.fill_round1(d)
        header = list(review.ROUND1_FIELDS)
        rows[0]["conditionText"] = "사람이 양식 열을 직접 고침"
        S.write_rows(d / "review_round1.csv", header, rows)
        with self.assertRaises(ExtractError) as cm:
            review.apply_review(d)
        self.assertIn("양식 열", str(cm.exception))

    def test_edit_changing_merge_stops(self):
        d = self.fresh()
        # 표 행으로 MAINT-04에 병합된 후보의 인용을 MAINT-05 행으로 고치면 병합 대상이 바뀌므로 멈춘다(다시 검토)
        r4 = "SOP-003:p1:table1:chunk:r4"
        S.fill_round1(d, overrides={r4: ("edit", json.dumps({"sourceQuote": "Trigger: TMP >25°C for >5 min"}))})
        review.make_round2(d)
        S.fill_round2(d, {r4: ("accept", "")})
        with self.assertRaises(ExtractError) as cm:
            review.apply_review(d)
        self.assertIn("병합 여부·대상이 바뀜", str(cm.exception))
        self.assertFalse((d / "final.jsonl").exists())

    def test_edit_invented_id_rejected(self):
        d = self.fresh()
        S.fill_round1(d, overrides={PATTERN: ("edit", json.dumps({"ruleIdInText": "MAINT-02"}))})
        review.make_round2(d)
        S.fill_round2(d, {PATTERN: ("accept", "")})
        with self.assertRaises(ExtractError) as cm:
            review.apply_review(d)
        self.assertIn("rule_id_not_in_chunk", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
