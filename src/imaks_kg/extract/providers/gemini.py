"""Gemini 어댑터. 기본은 Interactions API(2026-10-14 공식 문서 확인), 설정 api="generate_content"로 레거시 경로도 쓴다.

Interactions: POST {base_url}/interactions, 키는 x-goog-api-key 헤더로만(URL에 넣지 않음).
  본문 input(문자열), response_format{type,mime_type,schema}, generation_config{thinking_level,...}, store=false.
  최대 출력 토큰 필드 이름(generation_config.max_output_tokens)은 공식 문서로 확인하지 못했다(추정): 설정 fields.max_tokens_path.
  system 문구 전용 필드도 확인하지 못해 기본은 input 앞에 이어 붙인다(fields.system_path를 주면 그 위치에 넣음).
  응답 텍스트는 steps 중 type이 model_output인 단계의 content에서 type이 text인 것의 text를 순서대로 이은 것.
  사고 단계는 응답 텍스트에 넣지 않는다.
샘플링 매개변수(temperature, top_p, top_k)는 어느 경로에서도 본문에 넣지 않는다(base.assert_no_sampling이 마지막 방어).
"""
from __future__ import annotations

import json
import urllib.parse

from imaks_kg.extract.providers.base import (HttpProvider, LLMResponse, RefusalOrIncomplete, set_path)
from imaks_kg.extract.providers.schema_compat import to_provider_schema

_REFUSAL_REASONS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "IMAGE_SAFETY", "LANGUAGE"}


class GeminiProvider(HttpProvider):
    def build_request(self, request, model, key=""):
        if self.spec.api == "generate_content":
            return self._build_generate_content(request, model, key)
        return self._build_interactions(request, model, key)

    def parse_response(self, text):
        if self.spec.api == "generate_content":
            return self._parse_generate_content(text)
        return self._parse_interactions(text)

    # ------------------------------------------------------------ Interactions
    def _build_interactions(self, request, model, key):
        f = self.spec.fields
        prompt = request.prompt
        body = {"model": model.id}
        if request.system:
            if f.get("system_path"):
                set_path(body, f["system_path"], request.system)
            else:
                prompt = request.system + "\n\n" + prompt
        body["input"] = prompt
        if request.expect_json:
            rf = {"type": "text", "mime_type": "application/json"}
            if request.response_schema is not None:
                rf["schema"], _ = to_provider_schema("gemini", request.response_schema)
            body["response_format"] = rf
        set_path(body, f.get("thinking_path", ""), model.thinking_level)
        set_path(body, f.get("max_tokens_path", ""), model.max_output_tokens)
        set_path(body, f.get("store_path", "store") or "store", False)   # 서버 저장 끔(항상)
        url = self.spec.base_url + "/interactions"
        return url, {"x-goog-api-key": key}, body

    def _parse_interactions(self, text):
        try:
            j = json.loads(text)
        except ValueError:
            raise RefusalOrIncomplete("응답 본문이 JSON이 아닙니다.", kind="invalid_json", raw_text=text) from None
        if not isinstance(j, dict):
            raise RefusalOrIncomplete("응답 본문이 객체가 아닙니다.", kind="invalid_json", raw_text=text)
        u = j.get("usage") or {}
        usage = {}
        for dst, src in (("input_tokens", "total_input_tokens"), ("output_tokens", "total_output_tokens"),
                         ("thinking_tokens", "total_thought_tokens"), ("cached_tokens", "total_cached_tokens"),
                         ("total_tokens", "total_tokens")):
            if u.get(src) is not None:
                usage[dst] = u[src]
        out = "".join(c.get("text", "") or ""
                      for st in (j.get("steps") or []) if isinstance(st, dict) and st.get("type") == "model_output"
                      for c in (st.get("content") or []) if isinstance(c, dict) and c.get("type") == "text")
        status = j.get("status") or ""
        model_name = j.get("model", "") or ""
        if status == "incomplete":
            raise RefusalOrIncomplete("출력이 불완전합니다(최대 토큰 도달 등, 생각 토큰 포함).", kind="truncated",
                                      raw_text=out, raw_body=text, usage=usage)
        if status in ("failed", "cancelled"):
            raise RefusalOrIncomplete(f"상호작용이 {status} 상태로 끝났습니다.", kind="failed",
                                      raw_text=out, raw_body=text, usage=usage)
        if status != "completed":
            raise RefusalOrIncomplete(f"완료되지 않은 상태입니다: {status or '없음'}", kind="empty",
                                      raw_text=out, raw_body=text, usage=usage)
        if not out.strip():
            raise RefusalOrIncomplete("출력이 비어 있습니다(생각에 한도를 다 썼을 수 있음).", kind="empty",
                                      raw_body=text, usage=usage)
        return LLMResponse(out, text, usage, status, model_name)

    # ------------------------------------------------------------ generateContent(레거시)
    def _build_generate_content(self, request, model, key):
        f = self.spec.fields
        body = {"contents": [{"role": "user", "parts": [{"text": request.prompt}]}]}
        if request.system:
            body["systemInstruction"] = {"parts": [{"text": request.system}]}
        set_path(body, f.get("max_tokens_path", ""), model.max_output_tokens)
        set_path(body, f.get("thinking_path", ""), model.thinking_level)
        if request.expect_json:
            set_path(body, f.get("mime_path", ""), "application/json")
            if request.response_schema is not None:
                schema, _ = to_provider_schema("gemini", request.response_schema)
                set_path(body, f.get("schema_path", ""), schema)
        url = f"{self.spec.base_url}/models/{urllib.parse.quote(model.id, safe='')}:generateContent"
        return url, {"x-goog-api-key": key}, body

    def _parse_generate_content(self, text):
        try:
            j = json.loads(text)
        except ValueError:
            raise RefusalOrIncomplete("응답 본문이 JSON이 아닙니다.", kind="invalid_json", raw_text=text) from None
        u = j.get("usageMetadata") or {}
        usage = {"input_tokens": u.get("promptTokenCount"), "output_tokens": u.get("candidatesTokenCount"),
                 "thinking_tokens": u.get("thoughtsTokenCount"), "total_tokens": u.get("totalTokenCount")}
        block = (j.get("promptFeedback") or {}).get("blockReason")
        if block:
            raise RefusalOrIncomplete(f"입력이 차단되었습니다: {block}", kind="refused", raw_body=text, usage=usage)
        cands = j.get("candidates") or []
        if not cands:
            raise RefusalOrIncomplete("후보 응답이 없습니다.", kind="empty", raw_body=text, usage=usage)
        c = cands[0]
        parts = (c.get("content") or {}).get("parts") or []
        out = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        reason = c.get("finishReason") or ""
        if reason == "MAX_TOKENS":
            raise RefusalOrIncomplete("출력 한도에 닿아 잘렸습니다(생각 토큰 포함).", kind="truncated",
                                      raw_text=out, raw_body=text, usage=usage)
        if reason in _REFUSAL_REASONS:
            raise RefusalOrIncomplete(f"응답이 거부되었습니다: {reason}", kind="refused",
                                      raw_text=out, raw_body=text, usage=usage)
        if reason not in ("STOP", "", "FINISH_REASON_UNSPECIFIED"):
            raise RefusalOrIncomplete(f"비정상 종료: {reason}", kind="truncated", raw_text=out, raw_body=text, usage=usage)
        if not out.strip():
            raise RefusalOrIncomplete("출력이 비어 있습니다(생각에 한도를 다 썼을 수 있음).", kind="empty",
                                      raw_body=text, usage=usage)
        return LLMResponse(out, text, usage, reason, j.get("modelVersion", ""))
