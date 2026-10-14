"""OpenAI /v1/chat/completions 어댑터. 키는 Authorization 헤더로만 보낸다.

Chat Completions를 고른 이유: 연결 확인(connectivity.py)에서 이 엔드포인트가 실제로 동작했고, 요청/응답 모양이
단순하다(Responses API는 입력/출력 항목 구조가 달라 파서가 더 복잡). 추론이 켜진 모델이라 temperature 등은 보내지 않는다.
2026-10-14 공식 문서 확인 내용: 추론 모델 계열이 도구 없는 Chat Completions를 지원, 생각 수준 reasoning_effort(low/medium/high/xhigh/max),
최대 출력 max_completion_tokens(추론 토큰 포함), response_format json_schema strict(모든 속성 required, additionalProperties false).
필드 이름은 설정(fields)으로 바꿀 수 있다. max_completion_tokens -> max_tokens 재시도는 이 어댑터에 없다(이 모델 계열에 필요 없음).
strict 규칙에 맞추기 위해 스키마는 schema_compat.to_provider_schema로 변환한 복사본을 보낸다(원본은 그대로).
"""
from __future__ import annotations

import json

from imaks_kg.extract.providers.base import (HttpProvider, LLMResponse, RefusalOrIncomplete, set_path)
from imaks_kg.extract.providers.schema_compat import to_provider_schema


class OpenAIProvider(HttpProvider):
    def build_request(self, request, model, key=""):
        f = self.spec.fields
        msgs = []
        if request.system:
            msgs.append({"role": "system", "content": request.system})
        msgs.append({"role": "user", "content": request.prompt})
        body = {"model": model.id, "messages": msgs}
        set_path(body, f.get("max_tokens_path", ""), model.max_output_tokens)
        set_path(body, f.get("thinking_path", ""), model.thinking_level)
        mode = f.get("schema_mode", "json_schema")
        if request.expect_json and mode != "none":
            if mode == "json_schema" and request.response_schema is not None:
                schema, _ = to_provider_schema("openai", request.response_schema)
                body["response_format"] = {"type": "json_schema", "json_schema": {
                    "name": "extraction", "strict": True, "schema": schema}}
            else:
                body["response_format"] = {"type": "json_object"}
        return self.spec.base_url + "/chat/completions", {"Authorization": "Bearer " + key}, body

    def parse_response(self, text):
        try:
            j = json.loads(text)
        except ValueError:
            raise RefusalOrIncomplete("응답 본문이 JSON이 아닙니다.", kind="invalid_json", raw_text=text) from None
        u = j.get("usage") or {}
        usage = {"input_tokens": u.get("prompt_tokens"), "output_tokens": u.get("completion_tokens"),
                 "total_tokens": u.get("total_tokens")}
        reasoning = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
        if reasoning is not None:   # 없으면 건너뜀
            usage["thinking_tokens"] = reasoning
        ch = j.get("choices") or []
        if not ch:
            raise RefusalOrIncomplete("choices가 없습니다.", kind="empty", raw_body=text, usage=usage)
        msg = ch[0].get("message") or {}
        out = msg.get("content") or ""
        reason = ch[0].get("finish_reason") or ""
        if msg.get("refusal") or reason == "content_filter":
            raise RefusalOrIncomplete("응답이 거부되었습니다.", kind="refused", raw_text=out, raw_body=text, usage=usage)
        if reason == "length":
            raise RefusalOrIncomplete("출력 한도에 닿아 잘렸습니다(추론 토큰 포함).", kind="truncated",
                                      raw_text=out, raw_body=text, usage=usage)
        if not out.strip():
            raise RefusalOrIncomplete("출력이 비어 있습니다.", kind="empty", raw_body=text, usage=usage)
        return LLMResponse(out, text, usage, reason, j.get("model", ""))
