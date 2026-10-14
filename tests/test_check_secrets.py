"""check_secrets.py 동작 테스트: 가짜 키는 FAIL, 환경변수 이름만 있으면 PASS, 값 비출력, 출력 상한."""
import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".claude" / "skills" / "stage-check" / "scripts" / "check_secrets.py"

# 스크립트 자신이 걸리지 않도록 테스트 안에서 조합해 만든 가짜 값
FAKE_GOOGLE = "AI" + "za" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r"
FAKE_OPENAI = "s" + "k-" + "proj-" + "abcdefghij0123456789ABCDEF"
FAKE_BEARER = "Bea" + "rer " + "abcdefghij0123456789.tokenpart"
FAKE_ASSIGN_VALUE = "q9w8e7r6t5y4u3i2o1p0"


def load():
    spec = importlib.util.spec_from_file_location("check_secrets_t", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(paths, env=None):
    mod = load()
    buf = io.StringIO()
    clean = {k: v for k, v in os.environ.items() if k not in ("GEMINI_API_KEY", "OPENAI_API_KEY")}
    clean.update(env or {})
    with mock.patch.dict(os.environ, clean, clear=True), contextlib.redirect_stdout(buf):
        code = mod.main([str(p) for p in paths])
    return code, buf.getvalue()


class CheckSecretsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, text):
        p = self.dir / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_regex_keys_fail_and_values_not_printed(self):
        self.write("a.py", f'x = 1\nk = "{FAKE_GOOGLE}"\n')
        self.write("b.md", f"key {FAKE_OPENAI}\n")
        self.write("c.txt", f"Authorization: {FAKE_BEARER}\n")
        key_name = "api" + "_key"  # 소스 줄이 대입 패턴에 걸리지 않게 이름을 나눠 쓴다
        self.write("d.yaml", key_name + ': "' + FAKE_ASSIGN_VALUE + '"\n')
        code, out = run([self.dir])
        self.assertEqual(code, 1)
        self.assertIn("FAIL:", out)
        self.assertIn("발견 4건", out)
        for secret in (FAKE_GOOGLE, FAKE_OPENAI, FAKE_BEARER, FAKE_ASSIGN_VALUE, FAKE_BEARER.split()[1]):
            self.assertNotIn(secret, out)

    def test_env_var_names_only_pass(self):
        self.write("a.py", 'import os\nk = os.environ["GEMINI_API_KEY"]\nj = os.getenv("OPENAI_API_KEY")\n')
        self.write("s.yaml", 'api_key_env: "GEMINI_API_KEY"\napi_key: "YOUR_API_KEY_HERE_12345"\n'
                             'token: "${OPENAI_API_KEY}_suffix_value"\n')
        code, out = run([self.dir])
        self.assertEqual(code, 0, out)
        self.assertIn("PASS:", out)
        self.assertIn("발견 0건", out)

    def test_env_value_search_and_not_printed(self):
        fake_env_value = "zz" + "Qw7Er5Ty3Ui1Op9"
        self.write("log.txt", f"response header had {fake_env_value} inside\n")
        code, out = run([self.dir], env={"GEMINI_API_KEY": fake_env_value})
        self.assertEqual(code, 1)
        self.assertIn("환경변수 값 일치", out)
        self.assertNotIn(fake_env_value, out)
        # 8자 미만이면 검색하지 않는다
        code2, _ = run([self.dir], env={"GEMINI_API_KEY": "short"})
        self.assertEqual(code2, 0)

    def test_binary_and_non_utf8_skipped(self):
        (self.dir / "bin.dat").write_bytes(b"\x00\x01" + FAKE_GOOGLE.encode())
        (self.dir / "latin.txt").write_bytes(b"caf\xe9 " + FAKE_GOOGLE.encode())
        code, out = run([self.dir])
        self.assertEqual(code, 0)
        self.assertIn("건너뜀 2개", out)

    def test_output_cap(self):
        lines = "".join(f'k{i} = "{FAKE_GOOGLE}"\n' for i in range(60))
        self.write("many.py", lines)
        code, out = run([self.dir])
        self.assertEqual(code, 1)
        self.assertEqual(out.count("발견: "), 50)
        self.assertIn("외 10건", out)
        self.assertIn("발견 60건", out)
        self.assertNotIn(FAKE_GOOGLE, out)

    def test_skip_dirs(self):
        (self.dir / ".venv").mkdir()
        (self.dir / ".venv" / "x.py").write_text(f'k = "{FAKE_GOOGLE}"\n', encoding="utf-8")
        code, out = run([self.dir])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
