"""check_gt_overlap.py 동작 테스트: 모두 임시 가짜 정답·가짜 SOP로 한다(실제 정답 파일은 읽지 않는다)."""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".claude" / "skills" / "stage-check" / "scripts" / "check_gt_overlap.py"

SOP_SENTENCE = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda"
GT_UNIQUE = "quokka juggles seventeen purple lanterns beneath midnight rainbows"
GT_SOP_PART = "alpha beta gamma delta epsilon zeta eta theta"


def load():
    spec = importlib.util.spec_from_file_location("check_gt_overlap_t", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CheckGtOverlapTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        self.gt = self.d / "gt.csv"
        self.gt.write_text(
            "ruleId,class,condition,action\n"
            f"R1,X,{GT_UNIQUE},\n"
            f"R2,X,{GT_SOP_PART},\n", encoding="utf-8")
        self.sop = self.d / "pages.jsonl"
        self.sop.write_text(json.dumps({"doc_id": "S", "text_normalized": SOP_SENTENCE}) + "\n", encoding="utf-8")
        self.targets = self.d / "targets"
        self.targets.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def run_main(self, *extra, gt=None, sop=None):
        mod = load()
        buf = io.StringIO()
        argv = ["--gt", str(gt or self.gt), "--sop", str(sop or self.sop), *extra]
        with contextlib.redirect_stdout(buf):
            code = mod.main(argv)
        return code, buf.getvalue()

    def test_copy_of_gt_unique_phrase_fails_without_leaking_text(self):
        (self.targets / "prompt.txt").write_text(f"Example: {GT_UNIQUE.upper()}!\n", encoding="utf-8")
        code, out = self.run_main(str(self.targets))
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL:", out)
        self.assertIn("정답 규칙 1행", out)
        self.assertIn("1.00", out)
        self.assertNotIn("quokka", out.lower())
        self.assertNotIn("lanterns", out.lower())
        self.assertIn("정답 규칙 2개, 고유 n-gram이 있는 규칙 1개, 검사한 파일 1개, 기준 초과 1건", out)

    def test_sop_only_copy_passes(self):
        (self.targets / "chunk.md").write_text(SOP_SENTENCE + "\n", encoding="utf-8")
        code, out = self.run_main(str(self.targets))
        self.assertEqual(code, 0, out)
        self.assertIn("PASS:", out)

    def test_missing_gt_returns_2(self):
        code, out = self.run_main(str(self.targets), gt=self.d / "nope.csv")
        self.assertEqual(code, 2)
        self.assertIn("미확인", out)

    def test_normalization_and_threshold(self):
        # 구두점·대소문자·공백이 달라도 같은 n-gram. 일부만 복사하면 비율이 낮다.
        (self.targets / "a.txt").write_text("Quokka,  JUGGLES;seventeen\tpurple-lanterns beneath\n\nmidnight rainbows", encoding="utf-8")
        mod = load()
        self.assertEqual(mod.normalize("A,  B;c-D\n e_f"), ["a", "b", "c", "d", "e", "f"])
        # 줄이 나뉘면 줄 경계를 넘는 n-gram은 세지 않으므로 앞 줄만 6-gram이 된다 -> 비율 1/3
        code, out = self.run_main(str(self.targets), "--threshold", "0.3")
        self.assertEqual(code, 1, out)
        self.assertIn("0.33", out)
        code2, out2 = self.run_main(str(self.targets), "--threshold", "0.5")
        self.assertEqual(code2, 0, out2)

    def test_ngram_length_option(self):
        (self.targets / "a.txt").write_text("quokka juggles seventeen\n", encoding="utf-8")
        code, _ = self.run_main(str(self.targets), "-n", "6")
        self.assertEqual(code, 0)
        code, out = self.run_main(str(self.targets), "-n", "3", "--threshold", "0.1")
        self.assertEqual(code, 1, out)

    def test_output_cap_30(self):
        rows = "".join(f"R{i},X,w{i}a w{i}b w{i}c w{i}d w{i}e w{i}f w{i}g,\n" for i in range(35))
        gt = self.d / "gt35.csv"
        gt.write_text("ruleId,class,condition,action\n" + rows, encoding="utf-8")
        (self.targets / "t.txt").write_text(
            "\n".join(f"w{i}a w{i}b w{i}c w{i}d w{i}e w{i}f w{i}g" for i in range(35)), encoding="utf-8")
        code, out = self.run_main(str(self.targets), gt=gt)
        self.assertEqual(code, 1)
        self.assertEqual(out.count("의심: "), 30)
        self.assertIn("외 5건", out)


if __name__ == "__main__":
    unittest.main()
