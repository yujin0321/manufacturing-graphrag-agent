"""example_check 시험: 임시 가짜 데이터(가짜 정답 CSV, 가짜 원문, 가짜 이름 목록)만 쓴다. 실제 정답 파일은 열지 않는다."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_b_helpers as h  # noqa: E402

from imaks_kg.extract import example_check as ec  # noqa: E402
from imaks_kg.extract.docdata import sha256_file  # noqa: E402
from imaks_kg.extract.request_builder import require_registered_example  # noqa: E402

SRC_TEXT = "The quick brown fox jumps over the lazy dog near the old river bank today."
GT_UNIQUE = "Zebra crossings must flash amber whenever drizzle persists beyond lunchtime."


class Fixture(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        t = self.tmp = Path(self._t.name)
        self.pages = t / "pages.jsonl"
        self.pages.write_text(json.dumps({"doc_id": "D", "page": 1, "text_normalized": SRC_TEXT + " Hold 12 min at 80 bar."}) + "\n", encoding="utf-8")
        self.gt = t / "gt.csv"
        self.gt.write_text("ruleId,condition,action\nG1," + GT_UNIQUE + ",Do it\n", encoding="utf-8")
        self.inst = t / "inst"
        self.inst.mkdir()
        (self.inst / "stations.csv").write_text("identifier\nAA01_ALPHA\n", encoding="utf-8")
        (self.inst / "sensors.csv").write_text("identifier,unit\nAA01_ALPHA_TMP,bar\n", encoding="utf-8")
        (self.inst / "documents.csv").write_text("identifier\nSOP-777\n", encoding="utf-8")
        self.manifest = t / "m.csv"
        self.manifest.write_text("doc_id,file,pages,file_sha256\nSOP-777,x,1," + "a" * 64 + "\n", encoding="utf-8")
        self.reg = t / "reg.json"

    def tearDown(self):
        self._t.cleanup()

    def run_ex(self, text):
        f = self.tmp / "ex.txt"
        f.write_bytes(text.encode("utf-8"))
        return ec.run_checks(f, registry=self.reg, instances=self.inst, pages=self.pages, manifest=self.manifest,
                             gt=self.gt, sop=self.pages), f

    def cli(self, text):
        f = self.tmp / "ex.txt"
        f.write_bytes(text.encode("utf-8"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = ec.main([str(f), "--registry", str(self.reg), "--instances", str(self.inst), "--pages", str(self.pages),
                            "--manifest", str(self.manifest), "--gt", str(self.gt), "--sop", str(self.pages)])
        return code, buf.getvalue()


class Checks(Fixture):
    CLEAN = "A made up crew of ZQ7_MIXER watches a gauge near the pond. Keep the dial under 88 kNm today.\n"

    def test_clean_example_passes_and_registers(self):
        (ok, res, digest), f = self.run_ex(self.CLEAN)
        self.assertTrue(ok, res)
        self.assertEqual(digest, sha256_file(f))
        reg = json.loads(self.reg.read_text(encoding="utf-8"))
        self.assertEqual([e["sha256"] for e in reg["entries"]], [digest])
        # 등록된 해시는 요청 빌더의 게이트를 통과한다
        require_registered_example(f, self.reg)

    def test_gt_overlap_fails_and_does_not_register(self):
        (ok, res, _), _ = self.run_ex("Intro line.\n" + GT_UNIQUE + "\n")
        self.assertFalse(ok)
        self.assertFalse(res["a_gt_overlap"]["passed"])
        self.assertFalse(self.reg.exists())

    def test_source_overlap_five_words(self):
        (ok, res, _), _ = self.run_ex("ok line\nthe quick brown fox jumps again\n")
        self.assertFalse(res["b_source_overlap"]["passed"])
        self.assertEqual(res["b_source_overlap"]["lines"], [2])
        (ok2, res2, _), _ = self.run_ex("the quick brown fox walks\n")   # 4단어만 겹침
        self.assertTrue(res2["b_source_overlap"]["passed"])

    def test_vocabulary_hits(self):
        cases = {"uses AA01_ALPHA here": "데이터셋 이름 목록과 일치", "see SOP-777 now": "데이터셋 이름 목록과 일치",
                 "see RULE-ST09-01 now": "규칙 ID 형식", "see MAINT-99 now": "규칙 ID 형식",
                 "set 12 min hold": "원문의 수치+단위 조합과 일치", "at 80 bar": "원문의 수치+단위 조합과 일치",
                 "code ST07 here": "스테이션 코드 형식"}
        for text, kind in cases.items():
            (ok, res, _), _ = self.run_ex("clean opener\n" + text + "\n")
            self.assertFalse(res["c_dataset_vocabulary"]["passed"], text)
            self.assertIn(kind, res["c_dataset_vocabulary"]["by_kind"], text)
            self.assertEqual(res["c_dataset_vocabulary"]["lines"], [2], text)
        (ok, res, _), _ = self.run_ex("set 13 min hold and 81 bar\n")   # 다른 수치는 통과
        self.assertTrue(res["c_dataset_vocabulary"]["passed"])

    def test_gt_tool_unverified_is_failure(self):
        f = self.tmp / "ex.txt"
        f.write_text(self.CLEAN, encoding="utf-8")
        ok, res, _ = ec.run_checks(f, registry=self.reg, instances=self.inst, pages=self.pages,
                                   manifest=self.manifest, gt=self.tmp / "missing.csv", sop=self.pages)
        self.assertFalse(ok)
        self.assertTrue(res["a_gt_overlap"]["unverified"])
        self.assertFalse(self.reg.exists())

    def test_output_has_counts_and_lines_but_no_fragments(self):
        code, out = self.cli("opener\n" + GT_UNIQUE + "\nthe quick brown fox jumps again\nuse AA01_ALPHA\n")
        self.assertEqual(code, 1)
        self.assertNotIn("Zebra", out)
        self.assertNotIn("quick brown", out)
        self.assertNotIn("AA01_ALPHA", out)
        self.assertIn("줄 번호", out)
        code, out = self.cli(self.CLEAN)
        self.assertEqual(code, 0)
        self.assertIn("PASS", out)

    def test_unverified_exit_code_2(self):
        f = self.tmp / "ex.txt"
        f.write_text(self.CLEAN, encoding="utf-8")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = ec.main([str(f), "--registry", str(self.reg), "--instances", str(self.inst), "--pages", str(self.pages),
                            "--manifest", str(self.manifest), "--gt", str(self.tmp / "none.csv"), "--sop", str(self.pages)])
        self.assertEqual(code, 2)


class NoGroundTruthRead(unittest.TestCase):
    def test_module_does_not_read_the_answer_file_itself(self):
        src = (Path(h.ROOT) / "src/imaks_kg/extract/example_check.py").read_text(encoding="utf-8")
        self.assertNotIn("ground" + "_truth", src)
        self.assertNotIn("kg_seed", src)


if __name__ == "__main__":
    unittest.main()
