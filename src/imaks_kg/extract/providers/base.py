"""공급자 공통: 요청/응답 데이터 클래스, 오류 종류, HTTP 공급자 뼈대.

오류 종류(재시도/중단 규칙은 retry.py, fallback.py):
- TransientError: 429/408/5xx/타임아웃. 재시도 대상. possible_duplicate_billing 표시를 가진다.
- PermanentError: 400/404 등. 재시도 금지.
- QuotaOrAuthError: 401/402/403, 크레딧·할당량·인증. 즉시 중단(같은 공급자의 다른 모델로 가지 않음).
- RefusalOrIncomplete: 거부, 잘림, 빈 출력, JSON 아님. 완료로 취급하지 않고 원문을 보존한다.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from imaks_kg.extract.connectivity import mask

SAMPLING_KEYS = ("temperature", "top_p", "top_k")


# ---------------------------------------------------------------- 요청/응답
@dataclass(frozen=True)
class LLMRequest:
    """호출자(2단계 요청 빌더)가 만든 문자열을 그대로 담는다. 해시는 비어 있으면 계산 가능한 것만 채운다."""
    prompt: str
    system: str = ""
    response_schema: dict | None = None
    expect_json: bool = True
    step_name: str = "extract"
    doc_id: str = ""
    prompt_sha256: str = ""    # 프롬프트 템플릿(Role/Task) 파일 해시 (빌더가 줌)
    example_sha256: str = ""   # Example 파일 해시 (빌더가 줌)
    answer_key_supplied: bool = False
    seed_maintenance_text_supplied: bool = False

    @property
    def schema_sha256(self) -> str:
        if self.response_schema is None:
            return ""
        return sha256_text(json.dumps(self.response_schema, sort_keys=True, ensure_ascii=False))

    @property
    def input_sha256(self) -> str:
        return sha256_text(self.system + "\n\x00\n" + self.prompt)


@dataclass
class LLMResponse:
    text: str
    raw_body: str                 # HTTP 응답 본문 원문(보존 대상)
    usage: dict = field(default_factory=dict)  # input_tokens, output_tokens, thinking_tokens, total_tokens
    finish_reason: str = ""
    reported_model: str = ""      # 서버가 알려준 모델 이름(있으면)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 오류
class ExtractError(Exception):
    def __init__(self, message, *, http_status=None, error_kind="", possible_duplicate_billing=False):
        super().__init__(mask(message))
        self.http_status = http_status
        self.error_kind = error_kind
        self.possible_duplicate_billing = possible_duplicate_billing


class TransientError(ExtractError):
    pass


class PermanentError(ExtractError):
    pass


class QuotaOrAuthError(ExtractError):
    pass


class RefusalOrIncomplete(ExtractError):
    """kind: refused | truncated | empty | invalid_json | failed(공급자가 failed/cancelled로 알린 경우)."""

    def __init__(self, message, *, kind, raw_text="", raw_body="", usage=None, **kw):
        super().__init__(message, error_kind=kind, **kw)
        self.kind = kind
        self.raw_text = raw_text
        self.raw_body = raw_body or raw_text
        self.usage = usage or {}


# 크레딧/인증 판별 문구. 공식 문서 미확인 휴리스틱이므로 보고서에 한계로 적었다.
_QUOTA_MARKERS = ("insufficient_quota", "credits are depleted", "billing_hard_limit", "billing hard limit")
_AUTH_MARKERS = ("api key not valid", "api_key_invalid", "invalid_api_key", "incorrect api key")


def error_summary(text, secrets=(), limit=300) -> str:
    msg = text
    try:
        j = json.loads(text)
        err = j.get("error", j) if isinstance(j, dict) else j
        msg = (err.get("message") if isinstance(err, dict) else None) or json.dumps(err, ensure_ascii=False)
    except Exception:
        pass
    return mask(" ".join(str(msg).split()), secrets)[:limit]


def classify_http_error(status: int, text: str, secrets=()) -> ExtractError:
    """HTTP 오류 응답을 종류별 예외로 바꾼다(재시도 가능 여부는 종류로 결정)."""
    summary = error_summary(text, secrets)
    low = (text or "").lower()
    kind = f"http_{status}"
    if any(m in low for m in _QUOTA_MARKERS) or any(m in low for m in _AUTH_MARKERS):
        return QuotaOrAuthError(f"HTTP {status}: {summary}", http_status=status, error_kind=kind)
    if status in (401, 402, 403):
        return QuotaOrAuthError(f"HTTP {status}: {summary}", http_status=status, error_kind=kind)
    if status in (408, 429) or 500 <= status <= 599:
        return TransientError(f"HTTP {status}: {summary}", http_status=status, error_kind=kind)
    return PermanentError(f"HTTP {status}: {summary}", http_status=status, error_kind=kind)


def assert_no_sampling(obj, where="body"):
    """요청 본문 어디에도 샘플링 매개변수 이름이 없어야 한다(보내기 직전 마지막 방어)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in SAMPLING_KEYS:
                raise PermanentError(f"요청 본문에 샘플링 매개변수 {k}가 있습니다({where}). 보내지 않습니다.",
                                     error_kind="sampling_param")
            assert_no_sampling(v, f"{where}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            assert_no_sampling(v, f"{where}[{i}]")


def set_path(body: dict, path: str, value):
    """점 표기 경로에 값을 넣는다. 경로가 빈 문자열이면 아무것도 하지 않는다(그 필드를 보내지 않음)."""
    if not path:
        return
    parts = path.split(".")
    cur = body
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


# ---------------------------------------------------------------- 전송
def urllib_transport(url, headers, body, timeout_s):
    """(HTTP 상태, 본문). 타임아웃은 TimeoutError, 연결 오류는 ConnectionError."""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    hdrs = dict(headers)
    hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return getattr(resp, "status", 200), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            txt = e.read().decode("utf-8", "replace")
        except Exception:
            txt = ""
        return e.code, txt
    except (TimeoutError, socket.timeout):
        raise TimeoutError("요청 시간 초과") from None
    except urllib.error.URLError as e:
        if isinstance(e.reason, (TimeoutError, socket.timeout)):
            raise TimeoutError("요청 시간 초과") from None
        raise ConnectionError(mask(f"연결 오류: {type(e.reason).__name__}")) from None


# ---------------------------------------------------------------- 공급자 인터페이스
class Provider:
    """공급자 인터페이스. generate(request, model) -> LLMResponse, 실패는 ExtractError 하위 예외."""
    name = ""

    def generate(self, request: LLMRequest, model) -> LLMResponse:  # pragma: no cover - 인터페이스
        raise NotImplementedError


class HttpProvider(Provider):
    """REST 공급자 공통 흐름: 본문 만들기 -> 샘플링 검사 -> 전송 -> 상태 분류 -> 파싱."""

    def __init__(self, spec, transport=None, environ=None):
        self.spec = spec
        self.name = spec.name
        self.transport = transport or urllib_transport
        self.environ = environ if environ is not None else os.environ

    def _key(self) -> str:
        val = self.environ.get(self.spec.key_env)
        if not val:
            raise QuotaOrAuthError(f"환경변수 {self.spec.key_env}가 설정되어 있지 않습니다.", error_kind="missing_key")
        return val

    def build_request(self, request, model, key="") -> tuple:  # (url, headers, body)
        raise NotImplementedError

    def parse_response(self, status_text: str) -> LLMResponse:
        raise NotImplementedError

    def generate(self, request, model) -> LLMResponse:
        key = self._key()
        url, headers, body = self.build_request(request, model, key)
        assert_no_sampling(body)
        try:
            status, text = self.transport(url, headers, body, model.timeout_s)
        except TimeoutError:
            raise TransientError("요청 시간 초과(서버가 처리했을 수 있음)", error_kind="timeout",
                                 possible_duplicate_billing=True) from None
        except ConnectionError as e:
            raise TransientError(mask(str(e), [key]), error_kind="network") from None
        if status != 200:
            raise classify_http_error(status, text, [key])
        return self.parse_response(text)
