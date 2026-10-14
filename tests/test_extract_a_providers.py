"""공급자 어댑터 테스트: 가짜 HTTP 전송만 쓴다(네트워크 없음)."""
import copy
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_a_helpers import (FAKE_GEMINI, FAKE_OPENAI, gemini_interactions_body, gemini_ok_body,  # noqa: E402
                               openai_ok_body)

from imaks_kg.extract.config import ConfigError, config_from_dict  # noqa: E402
from imaks_kg.extract.providers.base import (LLMRequest, PermanentError, QuotaOrAuthError,  # noqa: E402
                                             RefusalOrIncomplete, TransientError, assert_no_sampling,
                                             classify_http_error, urllib_transport)
from imaks_kg.extract.providers.gemini import GeminiProvider  # noqa: E402
from imaks_kg.extract.providers.openai import OpenAIProvider  # noqa: E402
from imaks_kg.extract.providers.schema_compat import (SchemaIncompatible, schema_lint,  # noqa: E402
                                                      to_provider_schema)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILE = ROOT / "src" / "imaks_kg" / "extract" / "prompts" / "response_schema_v1.json"

# OpenAI strict 규칙(모든 속성 required, additionalProperties false)을 지킨 시험용 스키마
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["rules"],
          "properties": {"rules": {"type": "array", "items": {"type": "string"}}}}


def cfg(gemini_api=None):
    g = {"models": [{"id": "g1", "max_output_tokens": 500}]}
    if gemini_api:
        g["api"] = gemini_api
    return config_from_dict({"providers": {"gemini": g,
                                           "openai": {"models": [{"id": "o1", "thinking_level": "medium"}]}}})


class FakeTransport:
    def __init__(self, status=200, text="", exc=None):
        self.status, self.text, self.exc, self.sent = status, text, exc, []

    def __call__(self, url, headers, body, timeout_s):
        self.sent.append((url, headers, body, timeout_s))
        if self.exc:
            raise self.exc
        return self.status, self.text


def gem(tr, key=FAKE_GEMINI, api=None):
    c = cfg(api)
    return GeminiProvider(c.providers["gemini"], tr, {"GEMINI_API_KEY": key}), c.providers["gemini"].models[0]


def oai(tr, key=FAKE_OPENAI):
    c = cfg()
    return OpenAIProvider(c.providers["openai"], tr, {"OPENAI_API_KEY": key}), c.providers["openai"].models[0]


REQ = LLMRequest(prompt="doc text", system="role text", response_schema=SCHEMA)


class RequestBodyTests(unittest.TestCase):
    def test_gemini_interactions_body_fields_store_false_no_sampling_key_in_header(self):
        tr = FakeTransport(200, gemini_interactions_body())
        p, m = gem(tr)
        p.generate(REQ, m)
        url, headers, body, timeout = tr.sent[0]
        s = json.dumps(body)
        for w in ("temperature", "top_p", "top_k"):
            self.assertNotIn(w, s)
        self.assertEqual(headers, {"x-goog-api-key": FAKE_GEMINI})
        self.assertNotIn(FAKE_GEMINI, url + s)
        self.assertNotIn("key=", url)
        self.assertTrue(url.endswith("/v1beta/interactions"))
        self.assertEqual(body["model"], "g1")
        self.assertEqual(body["input"], "role text\n\ndoc text")   # system은 input 앞에 이어 붙임(전용 필드 미확인)
        self.assertIs(body["store"], False)
        self.assertEqual(body["generation_config"], {"thinking_level": "low", "max_output_tokens": 500})
        self.assertEqual(body["response_format"], {"type": "text", "mime_type": "application/json", "schema": SCHEMA})
        self.assertNotIn("contents", body)
        self.assertGreaterEqual(timeout, 120)

    def test_gemini_interactions_field_names_configurable_and_store_always_false(self):
        c = config_from_dict({"providers": {"gemini": {
            "fields": {"max_tokens_path": "generation_config.max_tokens_x", "system_path": "system_instruction",
                       "thinking_path": ""}, "models": [{"id": "g1"}]}, "openai": {"models": [{"id": "o1"}]}}})
        tr = FakeTransport(200, gemini_interactions_body())
        GeminiProvider(c.providers["gemini"], tr, {"GEMINI_API_KEY": FAKE_GEMINI}).generate(
            REQ, c.providers["gemini"].models[0])
        body = tr.sent[0][2]
        self.assertEqual(body["generation_config"], {"max_tokens_x": 16384})
        self.assertEqual(body["system_instruction"], "role text")
        self.assertEqual(body["input"], "doc text")
        self.assertIs(body["store"], False)

    def test_gemini_default_api_is_interactions_and_bad_values_rejected(self):
        self.assertEqual(cfg().providers["gemini"].api, "interactions")
        self.assertEqual(cfg("generate_content").providers["gemini"].api, "generate_content")
        with self.assertRaises(ConfigError):
            cfg("v2")
        with self.assertRaises(ConfigError):
            config_from_dict({"providers": {"gemini": {"models": [{"id": "g", "thinking_level": "minimal"}]},
                                            "openai": {"models": [{"id": "o"}]}}})
        with self.assertRaises(ConfigError):
            config_from_dict({"providers": {"gemini": {"models": [{"id": "g"}]},
                                            "openai": {"models": [{"id": "o", "thinking_level": "none"}]}}})

    def test_gemini_interactions_json_off_omits_response_format(self):
        tr = FakeTransport(200, gemini_interactions_body("hi"))
        p, m = gem(tr)
        p.generate(LLMRequest(prompt="x", expect_json=False), m)
        self.assertNotIn("response_format", tr.sent[0][2])
        self.assertIs(tr.sent[0][2]["store"], False)

    def test_gemini_legacy_generate_content_body(self):
        tr = FakeTransport(200, gemini_ok_body())
        p, m = gem(tr, api="generate_content")
        p.generate(REQ, m)
        url, headers, body, timeout = tr.sent[0]
        s = json.dumps(body)
        for w in ("temperature", "top_p", "top_k"):
            self.assertNotIn(w, s)
        self.assertEqual(headers, {"x-goog-api-key": FAKE_GEMINI})
        self.assertNotIn(FAKE_GEMINI, url + s)
        self.assertEqual(body["generationConfig"]["thinkingConfig"]["thinkingLevel"], "low")
        self.assertEqual(body["generationConfig"]["maxOutputTokens"], 500)
        self.assertEqual(body["generationConfig"]["responseJsonSchema"], SCHEMA)
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(body["systemInstruction"]["parts"][0]["text"], "role text")
        self.assertTrue(url.endswith("/models/g1:generateContent"))
        self.assertGreaterEqual(timeout, 120)

    def test_openai_body_has_no_sampling_params_and_key_only_in_header(self):
        tr = FakeTransport(200, openai_ok_body())
        p, m = oai(tr)
        p.generate(REQ, m)
        url, headers, body, _ = tr.sent[0]
        s = json.dumps(body)
        for w in ("temperature", "top_p", "top_k", "logprobs"):
            self.assertNotIn(w, s)
        self.assertEqual(headers, {"Authorization": "Bearer " + FAKE_OPENAI})
        self.assertNotIn(FAKE_OPENAI, url + s)
        self.assertEqual(body["reasoning_effort"], "medium")
        self.assertEqual(body["model"], "o1")
        self.assertIn("max_completion_tokens", body)
        self.assertNotIn("max_tokens", body)
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertIs(body["response_format"]["json_schema"]["strict"], True)
        self.assertEqual(body["response_format"]["json_schema"]["schema"], SCHEMA)
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertTrue(url.endswith("/chat/completions"))

    def test_field_paths_are_configurable_and_empty_disables(self):
        c = config_from_dict({"providers": {
            "gemini": {"api": "generate_content",
                       "fields": {"thinking_path": "generationConfig.thinkingConfig.thinkingBudgetLevel",
                                  "schema_path": ""},
                       "models": [{"id": "g1"}]}, "openai": {"fields": {"schema_mode": "json_object"},
                                                             "models": [{"id": "o1"}]}}})
        tr = FakeTransport(200, gemini_ok_body())
        p = GeminiProvider(c.providers["gemini"], tr, {"GEMINI_API_KEY": FAKE_GEMINI})
        p.generate(REQ, c.providers["gemini"].models[0])
        gc = tr.sent[0][2]["generationConfig"]
        self.assertIn("thinkingBudgetLevel", gc["thinkingConfig"])
        self.assertNotIn("responseJsonSchema", gc)
        tr2 = FakeTransport(200, openai_ok_body())
        q = OpenAIProvider(c.providers["openai"], tr2, {"OPENAI_API_KEY": FAKE_OPENAI})
        q.generate(REQ, c.providers["openai"].models[0])
        self.assertEqual(tr2.sent[0][2]["response_format"], {"type": "json_object"})

    def test_last_line_guard_rejects_sampling_in_body(self):
        with self.assertRaises(PermanentError):
            assert_no_sampling({"generationConfig": {"temperature": 0}})
        with self.assertRaises(PermanentError):
            assert_no_sampling({"a": [{"top_k": 1}]})
        with self.assertRaises(PermanentError):
            assert_no_sampling({"generation_config": {"top_p": 1}})

    def test_missing_key_env_is_auth_error_without_calling(self):
        tr = FakeTransport()
        c = cfg()
        p = GeminiProvider(c.providers["gemini"], tr, {})
        with self.assertRaises(QuotaOrAuthError):
            p.generate(REQ, c.providers["gemini"].models[0])
        self.assertEqual(tr.sent, [])


class ResponseParseTests(unittest.TestCase):
    def test_success_usage_and_reported_model(self):
        p, m = gem(FakeTransport(200, gemini_interactions_body()))
        r = p.generate(REQ, m)
        self.assertEqual(r.text, '{"rules": []}')
        self.assertEqual(r.usage, {"input_tokens": 7, "output_tokens": 3, "thinking_tokens": 2,
                                   "cached_tokens": 1, "total_tokens": 12})
        self.assertEqual(r.reported_model, "reported-g")
        self.assertEqual(r.finish_reason, "completed")
        p, m = gem(FakeTransport(200, gemini_ok_body()), api="generate_content")
        r = p.generate(REQ, m)
        self.assertEqual(r.usage["thinking_tokens"], 2)
        self.assertEqual(r.reported_model, "reported-g")
        p, m = oai(FakeTransport(200, openai_ok_body()))
        r = p.generate(REQ, m)
        self.assertEqual(r.usage["thinking_tokens"], 2)
        self.assertEqual(r.usage["output_tokens"], 3)

    def test_interactions_joins_model_output_text_in_order_and_skips_thought_steps(self):
        steps = [{"type": "thought", "content": [{"type": "text", "text": "THINK"}]},
                 {"type": "model_output", "content": [{"type": "text", "text": '{"rul'},
                                                      {"type": "image", "text": "IMG"}]},
                 {"type": "thought_summary", "content": [{"type": "text", "text": "SUMMARY"}]},
                 {"type": "model_output", "content": [{"type": "text", "text": 'es": []}'}]}]
        p, m = gem(FakeTransport(200, gemini_interactions_body(steps=steps)))
        r = p.generate(REQ, m)
        self.assertEqual(r.text, '{"rules": []}')
        self.assertIn("THINK", r.raw_body)   # 원문은 그대로 보존

    def test_interactions_incomplete_is_truncated_failed_cancelled_are_failures(self):
        m = gem(FakeTransport())[1]
        body = gemini_interactions_body('{"ru', status="incomplete")
        with self.assertRaises(RefusalOrIncomplete) as cm:
            gem(FakeTransport(200, body))[0].generate(REQ, m)
        self.assertEqual(cm.exception.kind, "truncated")
        self.assertEqual(cm.exception.raw_text, '{"ru')
        self.assertEqual(cm.exception.raw_body, body)
        self.assertEqual(cm.exception.usage["thinking_tokens"], 2)
        for st in ("failed", "cancelled"):
            with self.assertRaises(RefusalOrIncomplete) as cm:
                gem(FakeTransport(200, gemini_interactions_body("", status=st)))[0].generate(REQ, m)
            self.assertEqual(cm.exception.kind, "failed")
        with self.assertRaises(RefusalOrIncomplete) as cm:
            gem(FakeTransport(200, gemini_interactions_body("x", status="queued")))[0].generate(REQ, m)
        self.assertEqual(cm.exception.kind, "empty")

    def test_interactions_empty_text_and_non_json_body(self):
        m = gem(FakeTransport())[1]
        steps = [{"type": "thought", "content": [{"type": "text", "text": "only thinking"}]}]
        with self.assertRaises(RefusalOrIncomplete) as cm:
            gem(FakeTransport(200, gemini_interactions_body(steps=steps)))[0].generate(REQ, m)
        self.assertEqual(cm.exception.kind, "empty")
        with self.assertRaises(RefusalOrIncomplete) as cm:
            gem(FakeTransport(200, "<html>"))[0].generate(REQ, m)
        self.assertEqual(cm.exception.kind, "invalid_json")

    def test_gemini_legacy_truncated_refused_empty_keep_raw(self):
        body = json.dumps({"candidates": [{"content": {"parts": [{"text": '{"ru'}]}, "finishReason": "MAX_TOKENS"}]})
        p, m = gem(FakeTransport(200, body), api="generate_content")
        with self.assertRaises(RefusalOrIncomplete) as cm:
            p.generate(REQ, m)
        self.assertEqual(cm.exception.kind, "truncated")
        self.assertEqual(cm.exception.raw_text, '{"ru')
        self.assertEqual(cm.exception.raw_body, body)
        for body, kind in ((json.dumps({"candidates": [{"finishReason": "SAFETY"}]}), "refused"),
                           (json.dumps({"promptFeedback": {"blockReason": "OTHER"}}), "refused"),
                           (json.dumps({"candidates": [{"content": {"parts": []}, "finishReason": "STOP"}]}), "empty")):
            with self.assertRaises(RefusalOrIncomplete) as cm:
                gem(FakeTransport(200, body), api="generate_content")[0].generate(REQ, m)
            self.assertEqual(cm.exception.kind, kind)

    def test_openai_missing_reasoning_tokens_key_is_skipped(self):
        body = json.dumps({"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                           "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}})
        r = oai(FakeTransport(200, body))[0].generate(REQ, oai(FakeTransport())[1])
        self.assertNotIn("thinking_tokens", r.usage)

    def test_openai_length_refusal_empty(self):
        m = oai(FakeTransport())[1]

        def body(content, reason, refusal=None):
            return json.dumps({"choices": [{"message": {"content": content, "refusal": refusal},
                                            "finish_reason": reason}]})
        for text, kind in ((body('{"a', "length"), "truncated"), (body(None, "stop", "no"), "refused"),
                           (body("x", "content_filter"), "refused"), (body("", "stop"), "empty")):
            with self.assertRaises(RefusalOrIncomplete) as cm:
                oai(FakeTransport(200, text))[0].generate(REQ, m)
            self.assertEqual(cm.exception.kind, kind)


class ErrorClassTests(unittest.TestCase):
    def test_status_to_exception_kind(self):
        for st, cls in ((400, PermanentError), (404, PermanentError), (401, QuotaOrAuthError),
                        (402, QuotaOrAuthError), (403, QuotaOrAuthError), (408, TransientError),
                        (429, TransientError), (500, TransientError), (503, TransientError)):
            self.assertIsInstance(classify_http_error(st, "{}"), cls, st)

    def test_quota_and_bad_key_markers(self):
        e = classify_http_error(429, json.dumps({"error": {"code": "insufficient_quota", "message": "x"}}))
        self.assertIsInstance(e, QuotaOrAuthError)
        e = classify_http_error(400, json.dumps({"error": {"message": "API key not valid. Please pass a valid API key."}}))
        self.assertIsInstance(e, QuotaOrAuthError)

    def test_http_errors_through_provider_and_key_masked_in_message(self):
        body = json.dumps({"error": {"message": "bad " + FAKE_GEMINI}})
        p, m = gem(FakeTransport(400, body))
        with self.assertRaises(PermanentError) as cm:
            p.generate(REQ, m)
        self.assertNotIn(FAKE_GEMINI, str(cm.exception))

    def test_interactions_http_errors(self):
        for st, cls in ((429, TransientError), (503, TransientError), (408, TransientError), (400, PermanentError),
                        (402, QuotaOrAuthError), (403, QuotaOrAuthError)):
            p, m = gem(FakeTransport(st, json.dumps({"error": {"message": "x"}})))
            with self.assertRaises(cls, msg=st):
                p.generate(REQ, m)

    def test_openai_400_is_permanent_and_sent_once(self):
        tr = FakeTransport(400, json.dumps({"error": {"message": "Unsupported parameter"}}))
        p, m = oai(tr)
        with self.assertRaises(PermanentError):
            p.generate(REQ, m)
        self.assertEqual(len(tr.sent), 1)   # max_tokens로 바꿔 재시도하지 않음

    def test_timeout_is_transient_with_duplicate_billing_flag(self):
        p, m = gem(FakeTransport(exc=TimeoutError("x")))
        with self.assertRaises(TransientError) as cm:
            p.generate(REQ, m)
        self.assertTrue(cm.exception.possible_duplicate_billing)
        self.assertEqual(cm.exception.error_kind, "timeout")

    def test_connection_error_is_transient_without_duplicate_flag(self):
        p, m = gem(FakeTransport(exc=ConnectionError("down")))
        with self.assertRaises(TransientError) as cm:
            p.generate(REQ, m)
        self.assertFalse(cm.exception.possible_duplicate_billing)

    def test_urllib_transport_maps_timeout_without_network(self):
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("t")):
            with self.assertRaises(TimeoutError):
                urllib_transport("http://example.invalid/x", {}, {"a": 1}, 1)
        err = urllib.error.URLError(TimeoutError("t"))
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(TimeoutError):
                urllib_transport("http://example.invalid/x", {}, {"a": 1}, 1)


class SchemaCompatTests(unittest.TestCase):
    def test_non_strict_schema_is_converted_in_openai_request_and_original_untouched(self):
        sch = {"type": "object", "required": ["a", "b"], "properties": {
            "a": {"type": ["integer", "null"], "minimum": 1},
            "b": {"type": "array", "minItems": 1, "items": {"type": "string"}}}}
        orig = copy.deepcopy(sch)
        tr = FakeTransport(200, openai_ok_body())
        p, m = oai(tr)
        p.generate(LLMRequest(prompt="x", response_schema=sch), m)
        sent = tr.sent[0][2]["response_format"]["json_schema"]["schema"]
        self.assertIs(sent["additionalProperties"], False)
        self.assertNotIn("minimum", json.dumps(sent))
        self.assertNotIn("minItems", json.dumps(sent))
        self.assertEqual(sch, orig)

    def test_optional_property_is_not_silently_changed(self):
        sch = {"type": "object", "required": [], "properties": {"a": {"type": "string"}}}
        p, m = oai(FakeTransport(200, openai_ok_body()))
        with self.assertRaises(SchemaIncompatible):
            p.generate(LLMRequest(prompt="x", response_schema=sch), m)

    def test_current_schema_lint_and_conversion(self):
        sch = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
        before = json.dumps(sch, sort_keys=True)
        oa = schema_lint("openai", sch)
        self.assertTrue(oa)
        self.assertEqual({i.code for i in oa}, {"unsupported_keyword"})
        self.assertTrue(all(i.auto_fix and not i.changes_meaning for i in oa))
        self.assertEqual(schema_lint("gemini", sch), [])
        conv, notes = to_provider_schema("openai", sch)
        self.assertEqual(schema_lint("openai", conv), [])
        self.assertTrue(notes)
        self.assertEqual(conv["required"], sch["required"])
        ev = conv["properties"]["rules"]["items"]["properties"]["evidence"]
        self.assertNotIn("minItems", ev)
        self.assertEqual(ev["items"]["properties"]["table_row"]["type"], ["integer", "null"])
        self.assertIn(None, conv["properties"]["coverage"]["items"]["properties"]["reason"]["enum"])
        to_provider_schema("gemini", sch)
        self.assertEqual(json.dumps(sch, sort_keys=True), before)   # 원본 불변

    def test_lint_detects_each_rule(self):
        bad = {"type": "object", "properties": {
            "a": {"type": ["string", "null"], "enum": ["x"]}, "b": {"type": "string", "pattern": "^x"},
            "c": {"type": "object", "properties": {"d": {"type": "string"}}, "required": ["d"]}},
            "required": ["a", "b"]}
        codes = {(i.path, i.code) for i in schema_lint("openai", bad)}
        self.assertIn(("$.properties.a", "null_not_in_enum"), codes)
        self.assertIn(("$.properties.b", "unsupported_keyword"), codes)
        self.assertIn(("$", "missing_additional_properties"), codes)
        self.assertIn(("$.properties.c", "missing_additional_properties"), codes)
        self.assertIn(("$.properties.c", "optional_property"), codes)
        g = schema_lint("gemini", {"type": "object", "patternProperties": {}, "properties": {}})
        self.assertEqual([i.code for i in g], ["unknown_keyword"])
        with self.assertRaises(ValueError):
            schema_lint("other", {})


if __name__ == "__main__":
    unittest.main()
