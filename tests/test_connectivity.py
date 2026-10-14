"""connectivity.py 테스트: 네트워크 없이 urlopen을 mock한다. 가짜 키는 테스트 안에서 조합한다."""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from imaks_kg.extract import connectivity as C  # noqa: E402

FAKE_GEMINI = "AI" + "za" + "Zx9Yw8Vu7Ts6Rq5Po4Nm3Lk2Ji1Hg0FeDcBa"
FAKE_OPENAI = "s" + "k-" + "proj-" + "Qq1Ww2Ee3Rr4Tt5Yy6Uu7Ii8"
FAKE_HF = "h" + "f_" + "Aa1Bb2Cc3Dd4Ee5Ff6Gg7Hh8"


class FakeResp:
    def __init__(self, body, status=200):
        self._b = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.status = status

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code, body):
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(json.dumps(body).encode("utf-8")))


class Base(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"GEMINI_API_KEY": FAKE_GEMINI, "OPENAI_API_KEY": FAKE_OPENAI,
                                                "HF_TOKEN": FAKE_HF}, clear=False)
        self.env.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.env.stop)
        self.lines = []
        self.out = self.lines.append

    def logs_text(self):
        return "".join(p.read_text(encoding="utf-8") for p in Path(self.tmp.name).glob("*.json"))

    def all_text(self):
        return "\n".join(self.lines) + self.logs_text()


class TestLeak(Base):
    def test_error_does_not_leak_key(self):
        leaky = {"error": {"message": f"bad key {FAKE_OPENAI} in Bearer {FAKE_OPENAI} url?key={FAKE_GEMINI}"}}
        with mock.patch("urllib.request.urlopen", side_effect=http_error(401, leaky)):
            rc = C.cmd_ping("openai", "m", out=self.out, log_dir=self.tmp.name)
        self.assertEqual(rc, 1)
        txt = self.all_text()
        for k in (FAKE_GEMINI, FAKE_OPENAI, FAKE_HF):
            self.assertNotIn(k, txt)
        self.assertLessEqual(max(len(l) for l in self.lines if l.startswith("오류")), 310)

    def test_network_error_masked(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError(f"fail {FAKE_GEMINI}")):
            rc = C.cmd_ping("gemini", "m", out=self.out, log_dir=self.tmp.name)
        self.assertEqual(rc, 1)
        self.assertNotIn(FAKE_GEMINI, self.all_text())

    def test_gemini_key_in_header_not_url(self):
        seen = {}

        def fake(req, timeout=None):
            seen["url"] = req.full_url
            seen["hdr"] = {k.lower(): v for k, v in req.header_items()}
            return FakeResp({"candidates": [{"content": {"parts": [{"text": "OK"}]}}],
                             "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 1}})
        with mock.patch("urllib.request.urlopen", side_effect=fake):
            rc = C.cmd_ping("gemini", "m", json_mode=True, out=self.out, log_dir=self.tmp.name)
        self.assertEqual(rc, 0)
        self.assertNotIn(FAKE_GEMINI, seen["url"])
        self.assertEqual(seen["hdr"]["x-goog-api-key"], FAKE_GEMINI)
        self.assertIn("입력 7", "\n".join(self.lines))
        self.assertNotIn(FAKE_GEMINI, self.all_text())
        self.assertEqual(len(list(Path(self.tmp.name).glob("connectivity_*.json"))), 1)

    def test_mask_function(self):
        s = f"a {FAKE_GEMINI} b Bearer {FAKE_HF} c ?key={FAKE_OPENAI}&x=1"
        m = C.mask(s)
        for k in (FAKE_GEMINI, FAKE_OPENAI, FAKE_HF):
            self.assertNotIn(k, m)


class TestStatus(Base):
    def test_status_no_values(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("HF_TOKEN", None)
            C.cmd_status(out=self.out)
        txt = "\n".join(self.lines)
        self.assertIn("GEMINI_API_KEY: 설정됨", txt)
        self.assertIn("HF_TOKEN: 없음", txt)
        for k in (FAKE_GEMINI, FAKE_OPENAI):
            self.assertNotIn(k, txt)
            self.assertNotIn(k[:4], txt.replace("GEMINI_API_KEY", "").replace("OPENAI_API_KEY", ""))


class TestEnvLoader(unittest.TestCase):
    def test_no_overwrite_and_parsing(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text('# c\n\nGEMINI_API_KEY="from_file"\nOPENAI_API_KEY=file_o # note\nHF_TOKEN=\nOTHER=1\n',
                         encoding="utf-8")
            with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "preset"}, clear=False):
                os.environ.pop("OPENAI_API_KEY", None)
                os.environ.pop("HF_TOKEN", None)
                n = C.load_env(p)
                self.assertEqual(os.environ["GEMINI_API_KEY"], "preset")
                self.assertEqual(os.environ["OPENAI_API_KEY"], "file_o")
                self.assertNotIn("HF_TOKEN", os.environ)
                self.assertNotIn("OTHER", os.environ)
                self.assertEqual(n, 1)

    def test_missing_file_ok(self):
        self.assertEqual(C.load_env(Path(tempfile.gettempdir()) / "no_such_dir_x" / ".env"), 0)


class TestList(Base):
    def test_gemini_pagination(self):
        pages = [
            {"models": [{"name": "models/b", "supportedGenerationMethods": ["generateContent"]}],
             "nextPageToken": "T2"},
            {"models": [{"name": "models/a", "supportedGenerationMethods": ["embedContent"]}]},
        ]
        urls = []

        def fake(req, timeout=None):
            urls.append(req.full_url)
            return FakeResp(pages[len(urls) - 1])
        with mock.patch("urllib.request.urlopen", side_effect=fake):
            rc = C.cmd_list_models("gemini", [], out=self.out, log_dir=self.tmp.name)
        self.assertEqual(rc, 0)
        self.assertEqual(len(urls), 2)
        self.assertIn("pageToken=T2", urls[1])
        self.assertIn("전체 2개", self.lines[0])
        self.assertTrue(self.lines[1].startswith("a ") and "미지원" in self.lines[1])
        self.assertTrue(self.lines[2].startswith("b ") and "generateContent 지원" in self.lines[2])

    def test_contains_filter(self):
        data = {"data": [{"id": "x-mini"}, {"id": "y-big"}, {"id": "z-Mini2"}]}
        with mock.patch("urllib.request.urlopen", return_value=FakeResp(data)):
            C.cmd_list_models("openai", ["mini"], out=self.out, log_dir=self.tmp.name)
        self.assertIn("전체 3개, 표시 대상 2개", self.lines[0])
        self.assertEqual(self.lines[1:], ["x-mini", "z-Mini2"])

    def test_cap_80_lines(self):
        data = {"data": [{"id": f"m{i:03d}"} for i in range(100)]}
        with mock.patch("urllib.request.urlopen", return_value=FakeResp(data)):
            C.cmd_list_models("hf", [], out=self.out, log_dir=self.tmp.name)
        body = self.lines[1:]
        self.assertEqual(len(body), 81)
        self.assertEqual(body[-1], "외 20건")


class TestPingRetry(Base):
    def test_max_completion_tokens_then_max_tokens(self):
        bodies = []

        def fake(req, timeout=None):
            b = json.loads(req.data.decode("utf-8"))
            bodies.append(b)
            if len(bodies) == 1:
                raise http_error(400, {"error": {"message": "Unsupported parameter: 'max_completion_tokens'"}})
            return FakeResp({"choices": [{"message": {"content": "OK"}}],
                             "usage": {"prompt_tokens": 9, "completion_tokens": 2}})
        with mock.patch("urllib.request.urlopen", side_effect=fake):
            rc = C.cmd_ping("hf", "m", out=self.out, log_dir=self.tmp.name)
        self.assertEqual(rc, 0)
        self.assertEqual(len(bodies), 2)
        self.assertIn("max_completion_tokens", bodies[0])
        self.assertIn("max_tokens", bodies[1])
        self.assertNotIn("max_completion_tokens", bodies[1])
        self.assertNotIn("temperature", bodies[0])  # 기본은 온도를 보내지 않는다

    def test_explicit_temperature_is_sent_and_default_is_omitted(self):
        bodies = []

        def fake(req, timeout=None):
            bodies.append(json.loads(req.data.decode("utf-8")))
            return FakeResp({"choices": [{"message": {"content": "OK"}}],
                             "usage": {"prompt_tokens": 9, "completion_tokens": 2}})
        with mock.patch("urllib.request.urlopen", side_effect=fake):
            C.cmd_ping("openai", "m", temperature=0.0, out=self.out, log_dir=self.tmp.name)
            C.cmd_ping("openai", "m", out=self.out, log_dir=self.tmp.name)
        self.assertEqual(bodies[0]["temperature"], 0.0)
        self.assertNotIn("temperature", bodies[1])

    def test_no_retry_for_other_400_and_hint(self):
        calls = []

        def fake(req, timeout=None):
            calls.append(1)
            raise http_error(400, {"error": {"message": "Unsupported value: 'temperature' does not support 0"}})
        with mock.patch("urllib.request.urlopen", side_effect=fake):
            rc = C.cmd_ping("openai", "m", out=self.out, log_dir=self.tmp.name)
        self.assertEqual(rc, 1)
        self.assertEqual(len(calls), 1)
        self.assertTrue(any("temperature" in l and l.startswith("힌트") for l in self.lines))

    def test_json_mode_body(self):
        seen = {}

        def fake(req, timeout=None):
            seen.update(json.loads(req.data.decode("utf-8")))
            return FakeResp({"choices": [{"message": {"content": "{\"reply\": \"OK\"}"}}]})
        with mock.patch("urllib.request.urlopen", side_effect=fake):
            C.cmd_ping("openai", "m", json_mode=True, out=self.out, log_dir=self.tmp.name)
        self.assertEqual(seen["response_format"], {"type": "json_object"})
        self.assertIn("JSON 파싱: 가능", self.lines)


if __name__ == "__main__":
    unittest.main()
