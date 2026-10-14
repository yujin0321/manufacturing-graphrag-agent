"""mock 공급자: 스크립트로 정한 순서대로 성공/오류를 돌려준다. 네트워크를 쓰지 않는다.

스크립트 항목은 문자열 종류 이름 또는 (종류, 값) 튜플이다.
  "ok" 또는 ("ok", 텍스트)   성공
  "429", "503", "408"        일시 오류(재시도 대상)
  "timeout"                  타임아웃(possible_duplicate_billing)
  "400"                      영구 오류
  "402", "auth"              크레딧/인증 오류
  "invalid_json"             성공 응답이지만 본문이 JSON이 아님
  "incomplete"               잘림
  "refusal"                  거부
스크립트가 끝나면 마지막 항목을 반복한다.
"""
from __future__ import annotations

from imaks_kg.extract.providers.base import (LLMResponse, PermanentError, Provider, QuotaOrAuthError,
                                             RefusalOrIncomplete, TransientError, classify_http_error)

DEFAULT_OK = '{"rules": [], "coverage": []}'


class MockProvider(Provider):
    def __init__(self, name="mock", script=("ok",)):
        self.name = name
        self.script = list(script) or ["ok"]
        self.calls = []  # [(model.id, step_index)]

    def generate(self, request, model):
        i = len(self.calls)
        item = self.script[min(i, len(self.script) - 1)]
        self.calls.append(model.id)
        kind, val = (item if isinstance(item, tuple) else (item, None))
        if kind == "ok":
            text = DEFAULT_OK if val is None else val
            return LLMResponse(text, text, {"input_tokens": 10, "output_tokens": 5, "thinking_tokens": 3,
                                            "total_tokens": 18}, "stop", model.id)
        if kind in ("429", "503", "408", "500"):
            raise classify_http_error(int(kind), '{"error": {"message": "mock ' + kind + '"}}')
        if kind == "timeout":
            raise TransientError("요청 시간 초과(mock)", error_kind="timeout", possible_duplicate_billing=True)
        if kind == "400":
            raise PermanentError("HTTP 400: mock", http_status=400, error_kind="http_400")
        if kind in ("402", "auth"):
            raise QuotaOrAuthError("HTTP 402: mock" if kind == "402" else "HTTP 403: mock",
                                   http_status=402 if kind == "402" else 403, error_kind="http_" + ("402" if kind == "402" else "403"))
        usage = {"input_tokens": 10, "output_tokens": 5, "thinking_tokens": 3, "total_tokens": 18}
        if kind == "invalid_json":
            text = val if val is not None else "not json {"
            # 성공 응답이지만 JSON이 아님: 호출 계층의 JSON 검사가 잡는다.
            return LLMResponse(text, text, usage, "stop", model.id)
        if kind == "incomplete":
            text = val if val is not None else '{"rules": [{"class": "Thr'
            raise RefusalOrIncomplete("출력 한도에 닿아 잘렸습니다(mock).", kind="truncated", raw_text=text, usage=usage)
        if kind == "refusal":
            text = val if val is not None else "I cannot help with that."
            raise RefusalOrIncomplete("응답이 거부되었습니다(mock).", kind="refused", raw_text=text, usage=usage)
        raise ValueError(f"알 수 없는 mock 항목: {item!r}")


class ScriptedByDocMock(Provider):
    """문서 ID(request.doc_id)별로 정해 둔 응답 텍스트를 돌려주는 mock. 네트워크를 쓰지 않는다.

    responses: {doc_id: 텍스트 또는 [시도별 텍스트...]}. 목록이 끝나면 마지막 항목을 반복한다.
    없는 문서는 빈 규칙 응답(DEFAULT_OK)을 돌려준다.
    """

    def __init__(self, name="mock", responses=None):
        self.name = name
        self.responses = dict(responses or {})
        self.calls = []   # [(doc_id, step_name)]
        self._count = {}

    def generate(self, request, model):
        key = request.doc_id
        n = self._count.get((key, request.step_name), 0)
        self._count[(key, request.step_name)] = n + 1
        self.calls.append((request.doc_id, request.step_name))
        item = self.responses.get(key, DEFAULT_OK)
        if isinstance(item, (list, tuple)):
            item = item[min(n, len(item) - 1)]
        usage = {"input_tokens": 10, "output_tokens": 5, "thinking_tokens": 3, "total_tokens": 18}
        return LLMResponse(item, item, usage, "stop", model.id)
