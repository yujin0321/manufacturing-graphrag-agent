"""check_leakage.py 동작 테스트: 컬럼 전용 목록은 CSV 헤더·JSON 키에만, 일반 목록은 본문에도 적용."""
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".claude" / "skills" / "stage-check" / "scripts" / "check_leakage.py"


def general_words():
    return [l.strip() for l in (ROOT / "harness" / "forbidden_columns.txt").read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def run_check(folder: Path):
    p = subprocess.run([sys.executable, str(SCRIPT), str(folder)], capture_output=True, text=True,
                       encoding="utf-8", env={"PYTHONIOENCODING": "utf-8"})
    return p.returncode, p.stdout


def run_check_rooted(root: Path):
    """ROOT를 임시 폴더로 바꿔 상대 경로(preprocessed/documents/ 등) 규칙을 시험한다."""
    spec = importlib.util.spec_from_file_location("check_leakage_rooted", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ROOT = root
    old = sys.argv
    sys.argv = ["check_leakage.py", str(root)]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = mod.main()
    finally:
        sys.argv = old
    return code, buf.getvalue()


class CheckLeakageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def w(self, name, text):
        p = self.dir / name
        p.write_text(text, encoding="utf-8", newline="\n")
        return p

    def test_header_only_word_in_csv_header_fails(self):
        self.w("a.csv", "timestamp,day,value\n1,2,3\n")
        code, out = run_check(self.dir)
        self.assertEqual(code, 1, out)
        self.assertIn("day", out)

    def test_header_only_word_in_csv_header_case_insensitive_full_match(self):
        self.w("a.csv", "Quality,value\n1,2\n")
        self.assertEqual(run_check(self.dir)[0], 1)

    def test_similar_csv_header_passes(self):
        self.w("a.csv", "timestamp,original_day,original_shift,daytime\n1,2,3,4\n")
        self.assertEqual(run_check(self.dir)[0], 0)

    def test_header_only_word_as_json_key_fails(self):
        self.w("a.json", json.dumps({"rows": [{"status": "RUNNING"}]}))
        code, out = run_check(self.dir)
        self.assertEqual(code, 1, out)
        self.assertIn("status", out)

    def test_header_only_word_as_jsonl_key_fails(self):
        self.w("a.jsonl", '{"id": 1}\n{"meta": {"warn_hi": 2}}\n')
        self.assertEqual(run_check(self.dir)[0], 1)

    def test_header_only_word_as_json_value_passes(self):
        self.w("a.json", json.dumps({"text": "the day shift status is quality"}))
        self.w("b.jsonl", '{"text": "nominal warn_hi day"}\n')
        self.assertEqual(run_check(self.dir)[0], 0)

    def test_header_only_words_in_body_text_pass(self):
        self.w("a.md", "Every day the shift reports status, quality and alarms. nominal warn_hi crit_lo batch_id\n")
        self.w("b.py", "# day shift status quality\nx = 'warn_lo'\n")
        self.w("c.txt", "day\nshift\n")
        code, out = run_check(self.dir)
        self.assertEqual(code, 0, out)

    def test_general_list_applies_to_body_text(self):
        words = general_words()
        self.assertTrue(words)
        self.w("a.md", f"this line mentions {words[0]} in prose\n")
        self.assertEqual(run_check(self.dir)[0], 1)

    def test_general_list_applies_to_jsonl_value_and_csv_header(self):
        words = general_words()
        self.w("a.jsonl", json.dumps({"text": words[1]}) + "\n")
        self.assertEqual(run_check(self.dir)[0], 1)
        (self.dir / "a.jsonl").unlink()
        self.w("b.csv", f"x,{words[2]}\n1,2\n")
        self.assertEqual(run_check(self.dir)[0], 1)

    def test_jsonl_is_scanned_for_general_list_keys(self):
        self.w("a.jsonl", json.dumps({general_words()[0]: 1}) + "\n")
        self.assertEqual(run_check(self.dir)[0], 1)

    def test_documents_folder_values_exempt(self):
        d = self.dir / "preprocessed" / "documents"
        d.mkdir(parents=True)
        (d / "a.jsonl").write_text(json.dumps({"text": f"mentions {general_words()[1]} here"}) + "\n", encoding="utf-8")
        code, out = run_check_rooted(self.dir)
        self.assertEqual(code, 0, out)

    def test_documents_folder_keys_checked(self):
        d = self.dir / "preprocessed" / "documents"
        d.mkdir(parents=True)
        (d / "a.jsonl").write_text(json.dumps({general_words()[1]: 1}) + "\n", encoding="utf-8")
        self.assertEqual(run_check_rooted(self.dir)[0], 1)
        (d / "a.jsonl").write_text(json.dumps({"x": {"status": 1}}) + "\n", encoding="utf-8")
        self.assertEqual(run_check_rooted(self.dir)[0], 1)

    def test_same_case_outside_documents_folder_fails(self):
        d = self.dir / "preprocessed" / "other"
        d.mkdir(parents=True)
        (d / "a.jsonl").write_text(json.dumps({"text": f"mentions {general_words()[1]} here"}) + "\n", encoding="utf-8")
        self.assertEqual(run_check_rooted(self.dir)[0], 1)

    def test_missing_header_only_file_is_ignored(self):
        spec = importlib.util.spec_from_file_location("check_leakage_mod", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.HEADER_ONLY_FILE = self.dir / "does_not_exist.txt"
        self.w("a.csv", "timestamp,day,value\n1,2,3\n")
        old = sys.argv
        sys.argv = ["check_leakage.py", str(self.dir)]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                code = mod.main()
        finally:
            sys.argv = old
        self.assertEqual(code, 0, buf.getvalue())


if __name__ == "__main__":
    unittest.main()
