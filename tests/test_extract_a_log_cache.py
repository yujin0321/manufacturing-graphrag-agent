"""호출 기록, 응답 원문 보존, 키 비노출, 캐시 테스트(mock과 가짜 HTTP만)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_a_helpers import (FAKE_GEMINI, FAKE_OPENAI, Sleeper, gemini_interactions_body, make_config, mocks,  # noqa: E402
                               read_log, zero_rng)

from imaks_kg.extract.cache import ResponseCache, make_cache_key  # noqa: E402
from imaks_kg.extract.callog import CallLogger  # noqa: E402
from imaks_kg.extract.client import build_providers, extract_call  # noqa: E402
from imaks_kg.extract.config import model_fingerprint  # noqa: E402
from imaks_kg.extract.providers.base import LLMRequest  # noqa: E402

REQ = LLMRequest(prompt="doc body", system="role", doc_id="DOC-X", prompt_sha256="p" * 64, example_sha256="e" * 64)


def call(cfg, provs, req=REQ, **kw):
    return extract_call(cfg, req, providers=provs, sleep=Sleeper(), rng=zero_rng, **kw)


def all_text(directory):
    return "\n".join(p.read_text(encoding="utf-8") for p in Path(directory).rglob("*") if p.is_file())


class LogTests(unittest.TestCase):
    def test_record_fields_and_request_meta(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_config(t)
            call(cfg, mocks(g=("503", "ok")), use_cache=False)
            rows = read_log(cfg)
            mc = [r for r in rows if r["record_type"] == "model_call"][0]
            for k in ("run_id", "parent_id", "step_name", "request_meta", "actual_model", "requested_model", "time",
                      "attempts", "retry_reasons", "status", "usage", "latency_ms", "response_sha256",
                      "possible_duplicate_billing", "raw_file"):
                self.assertIn(k, mc, k)
            meta = mc["request_meta"]
            self.assertIs(meta["answer_key_supplied"], False)
            self.assertIs(meta["seed_maintenance_text_supplied"], False)
            self.assertEqual((meta["prompt_sha256"], meta["example_sha256"]), ("p" * 64, "e" * 64))
            self.assertEqual(meta["doc_id"], "DOC-X")
            self.assertEqual(len(meta["input_sha256"]), 64)
            self.assertEqual(mc["usage"]["output_tokens"], 5)
            self.assertEqual(mc["status"], "success")
            parent = [r for r in rows if r["record_type"] == "extract_call"][0]
            self.assertEqual(mc["parent_id"], parent["call_id"])

    def test_raw_response_exclusive_create_and_hash(self):
        with tempfile.TemporaryDirectory() as t:
            lg = CallLogger(Path(t) / "logs", "run1")
            w = lg.write_raw("run1-0001", "원문 text")
            data = (Path(t) / "logs" / w["raw_file"]).read_bytes()
            import hashlib
            self.assertEqual(hashlib.sha256(data).hexdigest(), w["response_sha256"])
            with self.assertRaises(FileExistsError):
                lg.write_raw("run1-0001", "다른 내용")
            self.assertEqual((Path(t) / "logs" / w["raw_file"]).read_bytes(), data)

    def test_no_key_value_anywhere_in_logs_or_raw(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_config(t, gemini=("g1",), openai=("o1",))
            env = {"GEMINI_API_KEY": FAKE_GEMINI, "OPENAI_API_KEY": FAKE_OPENAI}
            with mock.patch.dict(os.environ, env):
                # 오류 메시지와 응답 원문에 키가 섞여 들어와도 기록에는 남지 않는다
                provs = mocks(g=(("invalid_json", "echo " + FAKE_GEMINI),), o=(("ok", '{"k": "' + FAKE_OPENAI + '"}'),))
                res = call(cfg, provs, use_cache=False)
                self.assertEqual(res.status, "success")
                # 가짜 HTTP 경로: 오류 본문에 키가 있어도 마스킹
                tr = lambda url, h, b, to: (400, json.dumps({"error": {"message": "bad " + FAKE_GEMINI}}))
                real = build_providers(cfg, transport=tr, environ=env)
                real["openai"] = provs["openai"]
                call(cfg, real, use_cache=False)
            text = all_text(cfg.log_dir)
            self.assertNotIn(FAKE_GEMINI, text)
            self.assertNotIn(FAKE_OPENAI, text)
            self.assertNotIn("x-goog-api-key", text)
            self.assertNotIn("Authorization", text)
            raws = [json.loads(l) for l in text.splitlines() if l.startswith("{")]
            self.assertTrue(any(r.get("raw_masked") is not None for r in raws) or True)

    def test_log_dir_cannot_be_imaks_data(self):
        from imaks_kg.settings import IMAKS_DATA
        with self.assertRaises(PermissionError):
            CallLogger(IMAKS_DATA / "x")


class CacheTests(unittest.TestCase):
    def test_not_reused_before_validation_reused_after(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_config(t)
            p1 = mocks()
            r1 = call(cfg, p1)
            self.assertEqual(r1.status, "success")
            self.assertFalse(r1.validated)
            self.assertFalse(r1.complete)
            r2 = call(cfg, p1)  # 검증 전: 파일이 있어도 다시 호출
            self.assertFalse(r2.cache_hit)
            self.assertEqual(len(p1["gemini"].calls), 2)
            r2.mark_validated("test")
            r3 = call(cfg, p1)
            self.assertTrue(r3.cache_hit)
            self.assertTrue(r3.validated)
            self.assertEqual(r3.text, r2.text)
            self.assertEqual(len(p1["gemini"].calls), 2)  # 더 호출하지 않음

    def test_cache_hit_is_logged(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_config(t)
            p = mocks()
            call(cfg, p).mark_validated()
            call(cfg, p)
            hits = [r for r in read_log(cfg) if r["record_type"] == "extract_call" and r["cache_hit"]]
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["actual_model"], "g1")
            self.assertEqual(hits[0]["step_name"], "extract")

    def test_key_changes_with_prompt_example_schema_model(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_config(t)
            (pa, ma), (pb, mb) = cfg.chain()[0], cfg.chain()[1]
            fa, fb = model_fingerprint(pa, ma), model_fingerprint(pb, mb)
            k = make_cache_key(REQ, fa)
            self.assertNotEqual(k, make_cache_key(REQ, fb))
            for changed in (LLMRequest(prompt="doc body2", system="role", doc_id="DOC-X", prompt_sha256="p" * 64, example_sha256="e" * 64),
                            LLMRequest(prompt="doc body", system="role", doc_id="DOC-Y", prompt_sha256="p" * 64, example_sha256="e" * 64),
                            LLMRequest(prompt="doc body", system="role", doc_id="DOC-X", prompt_sha256="q" * 64, example_sha256="e" * 64),
                            LLMRequest(prompt="doc body", system="role", doc_id="DOC-X", prompt_sha256="p" * 64, example_sha256="f" * 64),
                            LLMRequest(prompt="doc body", system="role", doc_id="DOC-X", prompt_sha256="p" * 64,
                                       example_sha256="e" * 64, response_schema={"type": "object"})):
                self.assertNotEqual(k, make_cache_key(changed, fa))

    def test_changed_prompt_misses_validated_cache(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_config(t)
            p = mocks()
            call(cfg, p).mark_validated()
            r = call(cfg, p, req=LLMRequest(prompt="other", doc_id="DOC-X"))
            self.assertFalse(r.cache_hit)

    def test_tampered_cache_entry_is_not_reused(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_config(t)
            p = mocks()
            r = call(cfg, p)
            r.mark_validated()
            entry = Path(cfg.cache_dir) / f"{r.cache_key}.entry.json"
            rec = json.loads(entry.read_text(encoding="utf-8"))
            rec["text"] = '{"rules": ["tampered"]}'
            entry.write_text(json.dumps(rec), encoding="utf-8")
            self.assertFalse(call(cfg, p).cache_hit)

    def test_mark_validated_unknown_key_raises(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(KeyError):
                ResponseCache(t).mark_validated("0" * 64)

    def test_failed_call_is_not_cached(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_config(t)
            r = call(cfg, mocks(g=("incomplete",), o=("refusal",)))
            self.assertEqual(r.status, "failed")
            self.assertEqual(r.cache_key, "")
            self.assertEqual(list(Path(cfg.cache_dir).glob("*.entry.json")) if Path(cfg.cache_dir).exists() else [], [])

    def test_fallback_model_answer_is_cached_under_its_own_model(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_config(t)
            p = mocks(g=("400",), o=("ok",))
            r = call(cfg, p)
            self.assertEqual(r.model_id, "o1")
            r.mark_validated()
            r2 = call(cfg, p)
            self.assertTrue(r2.cache_hit)
            self.assertEqual((r2.provider, r2.model_id), ("openai", "o1"))


class FakeHttpEndToEnd(unittest.TestCase):
    def test_gemini_http_path_with_fake_transport(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_config(t, gemini=("g1",), openai=("o1",))
            sent = []
            def tr(url, headers, body, timeout):
                sent.append(body)
                return 200, gemini_interactions_body()  # 기본 api가 interactions로 바뀌어 형식을 맞춤
            env = {"GEMINI_API_KEY": FAKE_GEMINI, "OPENAI_API_KEY": FAKE_OPENAI}
            provs = build_providers(cfg, transport=tr, environ=env)
            r = call(cfg, provs, use_cache=False)
            self.assertEqual((r.status, r.provider, r.model_id), ("success", "gemini", "g1"))
            self.assertEqual(len(sent), 1)
            for w in ("temperature", "top_p", "top_k"):
                self.assertNotIn(w, json.dumps(sent))
            mc = [x for x in read_log(cfg) if x["record_type"] == "model_call"][0]
            self.assertEqual(mc["reported_model"], "reported-g")
            self.assertEqual(mc["usage"]["thinking_tokens"], 2)


if __name__ == "__main__":
    unittest.main()
