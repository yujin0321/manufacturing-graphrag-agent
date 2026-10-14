"""LLM 호출층. 클라이언트는 주입한다(실제: AnthropicClient, 테스트: FakeClient).

호출 설정(work_log 2026-10-12 [C] 결정 #4, 사용자 지시)
- client = anthropic.Anthropic(max_retries=0, timeout=SDK_TIMEOUT_S)
  자격 증명은 환경변수 ANTHROPIC_API_KEY만 쓴다. 코드·로그에 키를 두지 않는다. SDK 내부 재시도는 끄고,
  모든 재시도는 아래 정책(call_with_policy)이 한다.
- client.beta.messages.create(model="claude-opus-5-5", max_tokens=16000, betas=["server-side-fallback-2026-07-01"],
  fallbacks="default", system=..., messages=[...],
  output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}})
- thinking, temperature, top_p, top_k는 보내지 않는다(이 모델에서 temperature 등은 400 오류).

응답 처리(HTTP 200)
- stop_reason이 정상(end_turn)이 아니면(refusal, max_tokens 등) 그 청크만 실패로 기록하고 실행은 계속한다
  (정상 완료된 과금 응답이다).
- 성공이면 content의 첫 text 블록을 json.loads 한다. content에 fallback 블록이 있으면 그 앞은 거절한
  모델의 출력이므로 마지막 fallback 블록 뒤의 첫 text 블록을 쓴다.
- 실제로 답한 모델, 폴백 여부(usage.iterations에 type "fallback_message"가 있는지), usage, request_id를 기록한다.

오류 분류(classify_exception, 2026-10-13 사용자 지시)
| 분류 | 대상 | 처리 |
| FATAL_AUTH | 401, 403, CredentialsError | 실행 전체 즉시 중단 |
| FATAL_BILLING | 402, error.type billing_error, 400 + 크레딧·결제 문구, 429 + 지출·사용 한도 문구 | 즉시 중단(일치한 문구 기록) |
| FATAL_REQUEST | 404, 그 밖의 400/413/422(및 다른 4xx) | 즉시 중단(모든 호출이 같은 이유로 실패) |
| TRANSIENT_RATE | 429(실제 속도 제한), 503, 529 | 청크당 최대 3회 시도, 실행당 재시도 최대 10회. retry-after 우선, 없으면 상한 있는 지수 대기. 다 쓰면 TRANSIENT_EXHAUSTED로 중단 |
| AMBIGUOUS | APITimeoutError, APIConnectionError, 500, 504(및 다른 5xx) | 과금 여부를 알 수 없어 자동 재시도 없이 중단, "사용량 확인 필요" |
"""
import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import anthropic
import httpx2
from anthropic.types.beta import BetaMessage

from imaks_kg.extract.common import ExtractError, safe_name

MODEL_ID = "claude-opus-5-5"
MAX_TOKENS = 16000
EFFORT = "high"
BETAS = ["server-side-fallback-2026-07-01"]
FALLBACKS = "default"
OK_STOP_REASONS = ("end_turn",)
API_KEY_ENV = "ANTHROPIC_API_KEY"
SDK_MAX_RETRIES = 0
SDK_TIMEOUT_S = 600.0
NOT_SENT_PARAMS = {
    "temperature": "보내지 않음: 이 모델은 temperature를 바꾸면 400 오류. 재현성은 모델 ID·effort·프롬프트 해시·입력 해시·원본 응답 저장으로 확보",
    "top_p": "보내지 않음(400 오류)",
    "top_k": "보내지 않음(400 오류)",
    "thinking": "보내지 않음(사용자 지시)",
}

# 오류 분류
FATAL_AUTH = "FATAL_AUTH"
FATAL_BILLING = "FATAL_BILLING"
FATAL_REQUEST = "FATAL_REQUEST"
TRANSIENT_RATE = "TRANSIENT_RATE"
TRANSIENT_EXHAUSTED = "TRANSIENT_EXHAUSTED"
AMBIGUOUS = "AMBIGUOUS"
FATAL_QUOTA = "FATAL_QUOTA"  # Gemini 무료 등급 한도·할당(FATAL_BILLING에 해당)
FATAL_CLASSES = (FATAL_AUTH, FATAL_BILLING, FATAL_QUOTA, FATAL_REQUEST)
# 메시지 문구(소문자 부분 일치). 일치한 문구는 기록에 남긴다.
BILLING_400_PATTERNS = ("credit balance", "billing", "credits", "payment")
SPEND_429_PATTERNS = ("spend limit", "usage limit", "spending limit", "credit", "billing")
USAGE_CHECK_NOTE = "사용량 확인 필요: 요청이 서버에서 처리·과금됐는지 알 수 없음(Console에서 확인)"
# 재시도 정책
MAX_ATTEMPTS_PER_CHUNK = 3
MAX_RETRIES_PER_RUN = 10
BACKOFF_BASE_S = 2.0
BACKOFF_CAP_S = 60.0
RETRY_AFTER_CAP_S = 300.0
_SECRET = re.compile(r"sk-ant-[A-Za-z0-9_\-]+")


def retry_policy() -> dict:
    return {"max_attempts_per_chunk": MAX_ATTEMPTS_PER_CHUNK, "max_retries_per_run": MAX_RETRIES_PER_RUN,
            "backoff_base_s": BACKOFF_BASE_S, "backoff_cap_s": BACKOFF_CAP_S, "retry_after_cap_s": RETRY_AFTER_CAP_S,
            "sdk_max_retries": SDK_MAX_RETRIES, "sdk_timeout_s": SDK_TIMEOUT_S}


def build_request(system: str, user_text: str, schema: dict) -> dict:
    """요청 본문(키 없음). 저장도 이 dict 그대로 한다."""
    return {
        "model": MODEL_ID,
        "max_tokens": MAX_TOKENS,
        "betas": list(BETAS),
        "fallbacks": FALLBACKS,
        "system": system,
        "messages": [{"role": "user", "content": user_text}],
        "output_config": {"effort": EFFORT, "format": {"type": "json_schema", "schema": schema}},
    }


class AnthropicClient:
    """실제 클라이언트. 키는 SDK 기본 방식(환경변수)으로만 읽는다. 키가 없으면 만들지 않는다. SDK 재시도는 끈다."""

    def __init__(self):
        if not os.environ.get(API_KEY_ENV):
            raise ExtractError(f"환경변수 {API_KEY_ENV}가 설정되지 않아 실제 호출을 거부함")
        self._client = anthropic.Anthropic(max_retries=SDK_MAX_RETRIES, timeout=SDK_TIMEOUT_S)

    def create(self, request: dict, key: str):
        return self._client.beta.messages.create(**request)

    def count_tokens(self, request: dict) -> int:
        r = self._client.messages.count_tokens(model=request["model"], system=request["system"],
                                               messages=request["messages"])
        return int(r.input_tokens)


# ---------------------------------------------------------------- 가짜 클라이언트

class FakeClient:
    """저장된 응답을 돌려준다. 폴더의 <안전한 청크 ID>.json 파일(BetaMessage 형식 dict)을 읽는다.
    - {"__raise__": <종류>}: 해당 SDK 예외를 흉내 낸다(FAKE_ERRORS).
    - {"__sequence__": [항목, ...]}: 같은 청크를 다시 부를 때마다 다음 항목을 쓴다(마지막 항목은 반복)."""

    def __init__(self, fake_dir):
        self.dir = Path(fake_dir)
        if not self.dir.is_dir():
            raise ExtractError(f"가짜 응답 폴더가 없음: {fake_dir}")
        self.calls = []

    def create(self, request: dict, key: str):
        n = self.calls.count(key)
        self.calls.append(key)
        p = self.dir / f"{safe_name(key)}.json"
        if not p.exists():
            raise ExtractError(f"가짜 응답 없음: {key}")
        data = json.loads(p.read_text(encoding="utf-8"))
        if "__sequence__" in data:
            seq = data["__sequence__"]
            data = seq[min(n, len(seq) - 1)]
        if "__raise__" in data:
            raise fake_exception(data["__raise__"], data.get("retry_after"))
        msg = BetaMessage.model_validate(data)
        msg._request_id = data.get("_fake_request_id")
        return msg


# 종류 → (예외 클래스, 상태 코드, error.type, 메시지)
FAKE_ERRORS = {
    "auth": ("AuthenticationError", 401, "authentication_error", "invalid x-api-key"),
    "permission": ("PermissionDeniedError", 403, "permission_error", "not allowed"),
    "billing402": ("APIStatusError", 402, "billing_error", "payment required"),
    "billing_type": ("BadRequestError", 400, "billing_error", "account issue"),
    "credit400": ("BadRequestError", 400, "invalid_request_error",
                  "Your credit balance is too low to access the Anthropic API."),
    "spend429": ("RateLimitError", 429, "rate_limit_error", "You have reached your specified API usage limits."),
    "rate_limit": ("RateLimitError", 429, "rate_limit_error", "Number of request tokens has exceeded your rate limit"),
    "overloaded": ("OverloadedError", 529, "overloaded_error", "Overloaded"),
    "unavailable": ("ServiceUnavailableError", 503, "api_error", "service unavailable"),
    "not_found": ("NotFoundError", 404, "not_found_error", "model: claude-opus-5-5"),
    "bad_request": ("BadRequestError", 400, "invalid_request_error", "messages: field required"),
    "too_large": ("RequestTooLargeError", 413, "request_too_large", "request too large"),
    "unprocessable": ("UnprocessableEntityError", 422, "invalid_request_error", "unprocessable"),
    "internal": ("InternalServerError", 500, "api_error", "internal server error"),
    "deadline": ("DeadlineExceededError", 504, "timeout_error", "deadline exceeded"),
    "status": ("InternalServerError", 500, "api_error", "fake"),
}


def fake_exception(kind, retry_after=None):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    if kind == "connection":
        return anthropic.APIConnectionError(request=req)
    if kind == "timeout":
        return anthropic.APITimeoutError(request=req)
    if kind == "credentials":
        return anthropic.CredentialsError("no credentials found")
    cls_name, status, etype, msg = FAKE_ERRORS[kind]
    headers = {"retry-after": str(retry_after)} if retry_after is not None else {}
    body = {"type": "error", "error": {"type": etype, "message": msg}}
    resp = httpx2.Response(status, request=req, json=body, headers=headers)
    return getattr(anthropic, cls_name)(msg, response=resp, body=body)


_fake_exception = fake_exception  # 이전 이름(호환)


# ---------------------------------------------------------------- 분류

@dataclass
class ErrorInfo:
    error_class: str
    exception: str
    status: object = None
    error_type: str = ""
    message: str = ""
    matched_pattern: str = ""
    retry_after_s: object = None
    request_id: str = ""


def _message_of(e):
    body = getattr(e, "body", None)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        m = body["error"].get("message")
        if m:
            return str(m)
    return str(getattr(e, "message", "") or e)


def _match(msg, patterns):
    low = msg.lower()
    return next((p for p in patterns if p in low), "")


def _retry_after(e):
    resp = getattr(e, "response", None)
    if resp is None:
        return None
    v = resp.headers.get("retry-after")
    try:
        return max(0.0, float(v)) if v is not None else None
    except ValueError:
        return None


def classify_exception(e) -> ErrorInfo:
    """SDK 예외 → 분류. 메시지는 키 모양 문자열을 가리고 300자까지만 남긴다."""
    name = type(e).__name__
    if isinstance(e, anthropic.CredentialsError):
        return ErrorInfo(FATAL_AUTH, name, message="자격 증명 없음·오류")
    if isinstance(e, anthropic.APIConnectionError):  # APITimeoutError 포함
        return ErrorInfo(AMBIGUOUS, name, message=USAGE_CHECK_NOTE)
    if not isinstance(e, anthropic.APIStatusError):
        raise TypeError(f"분류 대상이 아닌 예외: {name}")
    status = int(e.status_code)
    etype = str(getattr(e, "type", None) or "")
    msg = _SECRET.sub("[가림]", _message_of(e))[:300]
    info = ErrorInfo("", name, status, etype, msg, request_id=str(getattr(e, "request_id", "") or ""))
    if status in (401, 403):
        info.error_class = FATAL_AUTH
    elif status == 402 or etype == "billing_error":
        info.error_class, info.matched_pattern = FATAL_BILLING, ("status 402" if status == 402 else "type billing_error")
    elif status == 400 and _match(msg, BILLING_400_PATTERNS):
        info.error_class, info.matched_pattern = FATAL_BILLING, _match(msg, BILLING_400_PATTERNS)
    elif status == 429 and _match(msg, SPEND_429_PATTERNS):
        info.error_class, info.matched_pattern = FATAL_BILLING, _match(msg, SPEND_429_PATTERNS)
    elif status in (429, 503, 529):
        info.error_class, info.retry_after_s = TRANSIENT_RATE, _retry_after(e)
    elif 400 <= status < 500:
        info.error_class = FATAL_REQUEST
    else:  # 500, 504와 그 밖의 5xx
        info.error_class = AMBIGUOUS
        info.message = f"{USAGE_CHECK_NOTE}; {msg}"
    return info


# ---------------------------------------------------------------- 호출 결과

@dataclass
class CallResult:
    key: str
    ok: bool
    failure: str = ""
    stop_reason: str = ""
    served_model: str = ""
    fallback_used: bool = False
    request_id: str = ""
    usage: dict = field(default_factory=dict)
    text: str = ""
    parsed: object = None
    raw: dict = field(default_factory=dict)
    http_200: bool = False
    error_class: str = ""
    abort: bool = False
    attempts: list = field(default_factory=list)
    error: dict = field(default_factory=dict)

    def summary(self):
        d = asdict(self)
        d.pop("raw")
        d.pop("parsed")
        d.pop("text")
        return d


def _served_text(content):
    """마지막 fallback 블록 뒤의 첫 text 블록(fallback 블록이 없으면 첫 text 블록)."""
    start = 0
    for i, b in enumerate(content):
        if getattr(b, "type", None) == "fallback":
            start = i + 1
    for b in content[start:]:
        if getattr(b, "type", None) == "text":
            return b.text
    return None


def interpret(key, response) -> CallResult:
    raw = response.model_dump(mode="json", by_alias=True, exclude_none=False)
    usage = response.usage.model_dump(mode="json", by_alias=True) if response.usage is not None else {}
    iterations = (response.usage.iterations or []) if response.usage is not None else []
    fallback = any(getattr(it, "type", None) == "fallback_message" for it in iterations)
    res = CallResult(key=key, ok=False, stop_reason=str(response.stop_reason), served_model=str(response.model),
                     fallback_used=fallback, request_id=str(getattr(response, "_request_id", None) or ""),
                     usage=usage, raw=raw, http_200=True)
    if response.stop_reason not in OK_STOP_REASONS:
        res.failure = f"stop_reason={response.stop_reason}"
        return res
    text = _served_text(response.content)
    if text is None:
        res.failure = "text 블록 없음"
        return res
    res.text = text
    try:
        res.parsed = json.loads(text)
    except json.JSONDecodeError as e:
        res.failure = f"JSON 파싱 실패: {e}"
        return res
    res.ok = True
    return res


SDK_ERRORS = (anthropic.APIStatusError, anthropic.APIConnectionError, anthropic.CredentialsError)


def _error_result(key, info: ErrorInfo, attempts, error_class=None):
    cls = error_class or info.error_class
    return CallResult(key=key, ok=False, failure=f"{cls}: {info.exception} status={info.status}",
                      request_id=info.request_id, error_class=cls, abort=True, attempts=attempts,
                      error=asdict(info))


def call(client, request: dict, key: str, adapter=None) -> CallResult:
    """한 번만 시도한다(재시도 없음). 오류는 분류해서 돌려준다(abort=True)."""
    adapter = adapter or ANTHROPIC
    try:
        response = client.create(request, key)
    except adapter.sdk_errors as e:
        info = adapter.classify(e)
        return _error_result(key, info, [{"attempt": 1, "error_class": info.error_class, "status": info.status,
                                          "wait_s": 0}])
    r = adapter.interpret(key, response)
    r.attempts = [{"attempt": 1, "error_class": "", "status": 200, "wait_s": 0}]
    return r


@dataclass
class RetryBudget:
    """실행 하나의 재시도 예산(실행당 최대 MAX_RETRIES_PER_RUN회)."""
    max_retries: int = MAX_RETRIES_PER_RUN
    used: int = 0
    log: list = field(default_factory=list)


def wait_seconds(info: ErrorInfo, attempt: int) -> float:
    if info.retry_after_s is not None:
        return min(float(info.retry_after_s), RETRY_AFTER_CAP_S)
    return min(BACKOFF_BASE_S * (2 ** (attempt - 1)), BACKOFF_CAP_S)


class Pacer:
    """실행 하나의 호출 간격. 마지막 API 시도를 시작한 시각을 기억하고, 다음 시도 전에 한 번만 잠든다:
    max(0, min_interval - 경과, extra). extra는 재시도의 backoff·retry_after(지금부터 잰 값)다. 이중 대기 없음.
    clock(단조 시계)과 sleep은 주입식이라 테스트가 기다리지 않는다."""

    def __init__(self, min_interval_s=0.0, sleep=None, clock=None):
        self.min_interval_s = float(min_interval_s or 0.0)
        self.sleep, self.clock = sleep or time.sleep, clock or time.monotonic
        self.last_start = None
        self.waits = []

    def wait(self, extra=0.0):
        target = float(extra or 0.0)
        if self.last_start is not None and self.min_interval_s > 0:
            target = max(target, self.min_interval_s - (self.clock() - self.last_start))
        target = max(0.0, target)
        if target > 0:
            self.sleep(target)
        self.waits.append(target)
        return target

    def started(self):
        self.last_start = self.clock()


# 시도 단계(journal): prepared(네트워크 없음) → sending(클라이언트에 넘김) →
#   http_200_received / http_error_response(서버의 HTTP 오류 응답) / transport_error(전송 오류·타임아웃, 불확실) /
#   local_error(보내기 전 로컬 오류: 자격 증명 없음 등) → interpreted / interpret_failed
PHASES = ("prepared", "sending", "http_200_received", "http_error_response", "transport_error", "local_error",
          "interpreted", "interpret_failed")


def _phase_of_error(info: ErrorInfo):
    if info.status not in (None, 0, ""):
        return "http_error_response"
    if info.error_class == AMBIGUOUS:
        return "transport_error"
    return "local_error"


def call_with_policy(client, request: dict, key: str, budget: RetryBudget, sleep=None,
                     adapter=None, journal=None, pacer=None, save_raw=None) -> CallResult:
    """분류 정책대로 부른다. TRANSIENT_RATE만 제한된 횟수로 재시도하고, 나머지 오류는 바로 abort=True로 돌려준다.
    - 시도마다 단계(PHASES)를 journal(호출 가능, 받는 쪽이 flush·fsync)에 순서대로 남긴다. 보내기 직전에 sending을,
      응답이 오면 해석 전에 http_200_received 또는 http_error_response를 남긴다.
    - 해석 중 오류가 나도 200은 잃지 않는다(interpret_failed, 그 청크만 실패).
    - pacer가 있으면 모든 시도 전에 호출 간격을 지키고, 재시도는 max(간격 - 경과, backoff, retry_after)를 한 번만 잔다.
    모든 시도(번호, 상태, 대기 시간, 단계)를 attempts와 budget.log에 남긴다."""
    adapter = adapter or ANTHROPIC
    pacer = pacer or Pacer(0.0, sleep or time.sleep)
    log = journal or (lambda e: None)
    attempts = []
    extra = 0.0
    for attempt in range(1, MAX_ATTEMPTS_PER_CHUNK + 1):
        waited = pacer.wait(extra)
        base = {"chunk_id": key, "attempt": attempt}
        log(dict(base, phase="prepared", waited_s=waited))
        pre = getattr(client, "precheck", None)
        if pre is not None:
            pre(key)  # 승인 상한을 넘으면 보내기 전에 멈춘다(sending 기록 없음 = 보내지 않음)
        log(dict(base, phase="sending"))
        pacer.started()
        try:
            response = client.create(request, key)
        except adapter.sdk_errors as e:
            info = adapter.classify(e)
            phase = _phase_of_error(info)
            log(dict(base, phase=phase, error_class=info.error_class, status=info.status))
            entry = {"chunk_id": key, "attempt": attempt, "error_class": info.error_class, "status": info.status,
                     "retry_after_s": info.retry_after_s, "wait_s": 0, "phase": phase}
            attempts.append(entry)
            if info.error_class != TRANSIENT_RATE:
                return _error_result(key, info, attempts)
            room = getattr(client, "has_retry_room", None)
            no_room = room is not None and not room()
            if attempt >= MAX_ATTEMPTS_PER_CHUNK or budget.used >= budget.max_retries or no_room:
                why = ("청크당 시도 한도" if attempt >= MAX_ATTEMPTS_PER_CHUNK
                       else "실행당 재시도 한도" if budget.used >= budget.max_retries else "승인 API 시도 상한")
                info.message = f"{why} 소진; {info.message}"
                return _error_result(key, info, attempts, TRANSIENT_EXHAUSTED)
            extra = wait_seconds(info, attempt)
            # 실제로 잘 시간 = max(간격 - 경과, backoff·retry_after). 다음 시도 직전에 pacer가 한 번만 잔다.
            elapsed = pacer.clock() - pacer.last_start if pacer.last_start is not None else 0.0
            entry["wait_s"] = max(extra, pacer.min_interval_s - elapsed, 0.0)
            budget.used += 1
            budget.log.append(dict(entry))
            continue
        log(dict(base, phase="http_200_received", status=200))
        attempts.append({"chunk_id": key, "attempt": attempt, "error_class": "", "status": 200, "wait_s": 0,
                         "phase": "http_200_received"})
        raw = None
        if save_raw is not None:  # 해석 전에 원본 본문을 저장한다(해석이 실패·중단돼도 증거가 남음)
            try:
                raw = adapter.raw_dump(response)
            except Exception as e:
                log(dict(base, phase="raw_dump_failed", error=type(e).__name__))
            if raw is not None:
                save_raw(key, attempt, raw)
        try:
            r = adapter.interpret(key, response)
        except Exception as e:  # 해석 실패: 200은 잃지 않는다(승인 used), 그 청크만 실패
            log(dict(base, phase="interpret_failed", error=type(e).__name__))
            r = CallResult(key=key, ok=False, failure=f"응답 해석 실패: {type(e).__name__}: {str(e)[:200]}",
                           http_200=True, raw=raw or {})
            r.attempts = attempts
            return r
        log(dict(base, phase="interpreted", ok=r.ok))
        r.attempts = attempts
        return r
    raise AssertionError("도달하지 않음")


# ---------------------------------------------------------------- 공급자 어댑터(Anthropic)
# 공급자별로 다른 것: 요청 조립, 호출(클라이언트), 응답 해석, 예외 분류, 토큰 세기, 키 확인, 가격, 실행 기록 항목.
# 나머지(재시도 정책, 승인, 가드, 검사·병합·검토·RDF)는 공급자와 무관하다.

class AnthropicAdapter:
    name = "anthropic"
    billing_tier = "paid"
    supports_count_tokens = True
    default_min_interval_s = 0.0
    sdk_errors = SDK_ERRORS
    max_output_tokens = MAX_TOKENS

    def __init__(self, model=None):
        if model not in (None, MODEL_ID):
            raise ExtractError(f"anthropic 공급자의 모델은 {MODEL_ID}만 쓴다(자동 전환 없음): {model}")
        self.model_id = MODEL_ID

    def build_request(self, system, user_text, schema):
        return build_request(system, user_text, schema)

    def settings_sha(self, req):
        """생성 설정 해시: 요청에서 사용자 메시지만 뺀 것(모델, max_tokens, effort, 스키마, system 포함)."""
        body = {k: v for k, v in req.items() if k != "messages"}
        return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def parse_raw(self, raw):
        return BetaMessage.model_validate(raw)

    def raw_dump(self, response):
        return response.model_dump(mode="json", by_alias=True, exclude_none=False)

    def outbound_problem(self, chunk, docs):
        return ""  # Anthropic 경로는 이전 동작 그대로(외부 전송 허용 목록은 Gemini 경로 지시)

    def request_chars(self, req):
        return (len(req["system"]) + sum(len(m["content"]) for m in req["messages"])
                + len(json.dumps(req["output_config"], ensure_ascii=False)))

    def interpret(self, key, response):
        return interpret(key, response)

    def classify(self, e):
        return classify_exception(e)

    def make_client(self):
        return AnthropicClient()

    def make_fake_client(self, fake_dir):
        return FakeClient(fake_dir)

    def key_problem(self):
        return "" if os.environ.get(API_KEY_ENV) else f"환경변수 {API_KEY_ENV}가 설정되지 않았다"

    def model_problem(self):
        return ""

    def price(self):
        return {"billing_tier": self.billing_tier, "usd_per_mtok_input": 4.0, "usd_per_mtok_output": 20.0,
                "basis_date": "2026-10-06"}

    def meta(self):
        return {
            "provider": self.name, "model": MODEL_ID, "max_tokens": MAX_TOKENS, "effort": EFFORT, "betas": BETAS,
            "fallbacks": FALLBACKS, "structured_output": "output_config.format json_schema",
            "params_not_sent": NOT_SENT_PARAMS, "anthropic_sdk_version": anthropic.__version__,
            "sdk_client": {"max_retries": SDK_MAX_RETRIES, "timeout_s": SDK_TIMEOUT_S},
        }


ANTHROPIC = AnthropicAdapter()
