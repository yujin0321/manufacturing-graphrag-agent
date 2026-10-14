"""Gemini API(무료 등급) 어댑터. 기본 공급자다(2026-10-13 사용자 결정). 공급자 사이 자동 전환·모델 폴백·유료 전환은 없다.

키
- 환경변수 GEMINI_API_KEY가 있으면 그 값을, 없으면 저장소 루트 .env(settings.DOTENV_FILE)에서 GEMINI_API_KEY 줄만
  작은 파서로 읽는다(새 의존성 없음). genai.Client(api_key=...)로 명시적으로 넘긴다.
- 환경에 GOOGLE_API_KEY가 있으면 멈춘다(SDK가 다른 키를 조용히 고르는 것을 막음).
- 키가 없으면 클라이언트를 만들기 전에 FATAL_AUTH로 멈춘다. 키 값은 오류 메시지·meta·로그·repr에 넣지 않는다.

SDK 내부 재시도
- google-genai 2.30.0의 _api_client.retry_args(options)는 options(HttpOptions.retry_options)가 None이면
  stop_after_attempt(1)(재시도 없음)이다. HttpRetryOptions를 주면 기본 5회, 408/429/500/502/503/504를 재시도한다.
- 그래서 http_options=types.HttpOptions(timeout=SDK_TIMEOUT_MS)만 주고 retry_options는 절대 넣지 않는다.

요청
- client.models.generate_content(model=MODEL, contents=사용자 메시지, config=GenerateContentConfig(system_instruction,
  temperature=0, response_mime_type="application/json", response_json_schema=Gemini용 스키마 사본,
  max_output_tokens, seed)). thinking_config는 넣지 않는다(모델 기본값, 기록함).
- 스키마: JSON Schema의 type 배열(["string","null"])은 anyOf로 바꾼 사본을 Gemini에 보낸다(지원 여부를 실제로
  확인하지 못해 보수적으로 바꿈). 사후 검사는 원래 스키마(pydantic)를 그대로 쓴다.

응답(HTTP 200): prompt_feedback.block_reason, 후보 없음, finish_reason이 STOP이 아님 → 그 청크만 실패로 기록하고 계속.
성공이면 후보 parts의 text(thought part 제외)를 이어 json.loads 한다.
"""
import copy
import hashlib
import json
import os
import re
from pathlib import Path

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from imaks_kg.extract import llm
from imaks_kg.extract.common import ExtractError, safe_name
from imaks_kg.settings import DOTENV_FILE

try:  # google-genai는 httpx를 쓰고, httpx2가 있으면 그것도 쓴다(_api_client._HTTPX_TRANSIENT_EXC와 같은 범위)
    import httpx2
    _TRANSPORT_ERRORS = (httpx.TransportError, httpx2.TransportError)
except ImportError:  # pragma: no cover
    _TRANSPORT_ERRORS = (httpx.TransportError,)

PROVIDER = "gemini"
GEMINI_MODEL = "gemini-3.8-flash"  # 사용자 지정(2026-10-13). 무료 등급 대상 여부는 첫 호출 전까지 모른다.
# --model로 바꿀 수 있다. FATAL_QUOTA(무료 할당 0 등)가 나면 실행을 멈추고 사용자가 다시 고른다(자동 전환 없음).
KEY_ENV = "GEMINI_API_KEY"
CONFLICT_ENV = "GOOGLE_API_KEY"
MAX_OUTPUT_TOKENS = 8192
TEMPERATURE = 0
SEED = 20261012
SDK_TIMEOUT_MS = 600_000
DEFAULT_MIN_INTERVAL_S = 7.5  # 무료 등급 분당 한도를 미리 피하는 호출 간격(분당 8회 이하). 첫 시험 호출에서 실제 한도를 보고 조정
OK_FINISH = "STOP"
# 외부 전송 허용 목록(2026-10-13 사용자 지시): 이 합성 데이터셋의 SOP만 보낸다.
OUTBOUND_DOCS = ("SOP-001", "SOP-002", "SOP-003", "SOP-004")
OUTBOUND_PATH_PREFIX = "imaks_data/rules/"


def outbound_allowlist():
    return {"docs": list(OUTBOUND_DOCS), "source_file_prefix": OUTBOUND_PATH_PREFIX,
            "rule": "보내기 직전 청크의 doc_id와 원본 파일 경로를 확인, 프롬프트 예시 출처도 같은 규칙"}


def outbound_problem(chunk, docs):
    """허용 목록 밖이면 사유(빈 문자열이면 허용)."""
    doc = chunk.get("doc_id")
    man = docs["manifest"].get(doc) if docs else None
    src = (man or {}).get("file", "")
    if doc not in OUTBOUND_DOCS:
        return f"{chunk.get('chunk_id')}: doc_id {doc}는 외부 전송 허용 목록(SOP-001~004) 밖"
    if not src.startswith(OUTBOUND_PATH_PREFIX):
        return f"{chunk.get('chunk_id')}: 원본 파일 {src or '(없음)'}가 {OUTBOUND_PATH_PREFIX} 밖"
    return ""

# 오류 분류 근거(상수). 일치한 근거는 기록에 남긴다.
API_KEY_REASONS = ("API_KEY_INVALID", "API_KEY_EXPIRED", "API_KEY_SERVICE_BLOCKED")
API_KEY_MESSAGES = ("api key not valid", "api key expired", "api_key_invalid")
DAILY_QUOTA_MARKERS = ("perday", "per_day", "daily")
MINUTE_QUOTA_MARKERS = ("perminute", "per_minute")
FREE_TIER_MESSAGES = ("limit: 0", "billing", "free tier", "free_tier", "enable billing")
QUOTA_NOTE = "무료 등급 한도·할당 도달(유료로 바꾸지 않음)"
_RETRY_DELAY = re.compile(r"^\s*(\d+(?:\.\d+)?)s\s*$")
_SECRETISH = re.compile(r"AIza[0-9A-Za-z_\-]{10,}")
TYPE_ERRORS = "google.rpc.ErrorInfo", "google.rpc.QuotaFailure", "google.rpc.RetryInfo"


# ---------------------------------------------------------------- 키

class KeyMissingError(ExtractError):
    """키 문제(FATAL_AUTH). 메시지에 키 값을 넣지 않는다."""
    error_class = llm.FATAL_AUTH


def _parse_dotenv_line(text, name):
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(rf"^(?:export\s+)?{re.escape(name)}\s*=\s*(.*)$", line)
        if not m:
            continue
        v = m.group(1).strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            return v[1:-1]
        return v.split(" #", 1)[0].strip()
    return None


def load_key(dotenv_path=None):
    """(키, 출처) 또는 KeyMissingError. 출처는 'environment' 또는 '.env'. 키 값은 돌려주기만 하고 출력하지 않는다."""
    if os.environ.get(CONFLICT_ENV):
        raise KeyMissingError(f"FATAL_AUTH: 환경에 {CONFLICT_ENV}가 설정돼 있어 중단(SDK가 다른 키를 고를 수 있음). "
                        f"{CONFLICT_ENV}를 지우고 {KEY_ENV}만 쓴다")
    v = os.environ.get(KEY_ENV)
    if v:
        return v, "environment"
    p = Path(dotenv_path or DOTENV_FILE)
    if p.exists():
        v = _parse_dotenv_line(p.read_text(encoding="utf-8"), KEY_ENV)
        if v:
            return v, ".env"
    raise KeyMissingError(f"FATAL_AUTH: {KEY_ENV}가 환경에도 .env에도 없음(클라이언트를 만들지 않음)")


def key_problem(dotenv_path=None):
    """키가 쓸 수 있는 상태인지(값은 보지 않고 있음·없음만). 문제가 없으면 빈 문자열."""
    try:
        load_key(dotenv_path)
    except KeyMissingError as e:
        return str(e)
    return ""


# ---------------------------------------------------------------- 스키마

def gemini_schema(schema):
    """Gemini에 보낼 스키마 사본과 바뀐 점 목록. type 배열은 anyOf로 바꾼다."""
    changes = []

    def walk(node, path):
        if isinstance(node, dict):
            t = node.get("type")
            if isinstance(t, list):
                rest = {k: v for k, v in node.items() if k != "type"}
                node.clear()
                node["anyOf"] = [{"type": x} for x in t]
                node.update(rest)
                changes.append(f"{path}: type {t} → anyOf")
            for k, v in list(node.items()):
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    out = copy.deepcopy(schema)
    walk(out, "$")
    return out, changes


# ---------------------------------------------------------------- 클라이언트

class GeminiClient:
    """실제 클라이언트. SDK 재시도 없음(retry_options 미설정). repr에 키를 넣지 않는다."""

    def __init__(self, dotenv_path=None):
        key, self.key_source = load_key(dotenv_path)
        self._client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=SDK_TIMEOUT_MS))
        del key

    def __repr__(self):
        return f"GeminiClient(key_source={self.key_source!r})"

    def create(self, request, key):
        cfg = types.GenerateContentConfig(**request["config"])
        return self._client.models.generate_content(model=request["model"], contents=request["contents"], config=cfg)

    def list_models(self):
        """모델 목록(생성 없음). 사용자가 직접 실행할 때만 쓴다."""
        out = []
        for m in self._client.models.list():
            out.append({"name": getattr(m, "name", None), "display_name": getattr(m, "display_name", None),
                        "supported_actions": getattr(m, "supported_actions", None)})
        return out


class GeminiFakeClient:
    """저장된 Gemini 응답(GenerateContentResponse 형식 dict)을 돌려준다.
    {"__raise__": 종류}는 FAKE_ERRORS의 오류를, {"__sequence__": [...]}는 부를 때마다 다음 항목을 쓴다."""

    def __init__(self, fake_dir):
        self.dir = Path(fake_dir)
        if not self.dir.is_dir():
            raise ExtractError(f"가짜 응답 폴더가 없음: {fake_dir}")
        self.calls = []

    def create(self, request, key):
        n = self.calls.count(key)
        self.calls.append(key)
        p = self.dir / f"{safe_name(key)}.json"
        if not p.exists():
            raise ExtractError(f"가짜 응답 없음: {key}")
        data = json.loads(p.read_text(encoding="utf-8"))
        if "__sequence__" in data:
            data = data["__sequence__"][min(n, len(data["__sequence__"]) - 1)]
        if "__raise__" in data:
            raise fake_error(data["__raise__"])
        return types.GenerateContentResponse.model_validate(data)


def _err_json(code, status, message, details=()):
    return {"error": {"code": code, "message": message, "status": status, "details": list(details)}}


def _quota(quota_id, metric="generativelanguage.googleapis.com/generate_content_free_tier_requests", value="10"):
    return {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
            "violations": [{"quotaMetric": metric, "quotaId": quota_id, "quotaValue": value}]}


def _retry(delay):
    return {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}


# 실제 API 오류 본문 모양을 본뜬 가짜(종류 → (클래스, HTTP 코드, 본문))
FAKE_ERRORS = {
    "unauthenticated": ("ClientError", 401, _err_json(401, "UNAUTHENTICATED", "Request had invalid authentication credentials.")),
    "permission": ("ClientError", 403, _err_json(403, "PERMISSION_DENIED", "Method doesn't allow unregistered callers.")),
    "key_invalid": ("ClientError", 400, _err_json(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key.", [
        {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID",
         "domain": "googleapis.com"}])),
    "quota_day": ("ClientError", 429, _err_json(429, "RESOURCE_EXHAUSTED", "You exceeded your current quota.", [
        _quota("GenerateRequestsPerDayPerProjectPerModel-FreeTier", value="250"), _retry("37s")])),
    "quota_zero": ("ClientError", 429, _err_json(429, "RESOURCE_EXHAUSTED", "You exceeded your current quota.", [
        _quota("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", value="0")])),
    "quota_msg": ("ClientError", 429, _err_json(429, "RESOURCE_EXHAUSTED",
                                                "Quota exceeded for metric: generate_content_free_tier_requests, limit: 0")),
    "precondition": ("ClientError", 400, _err_json(400, "FAILED_PRECONDITION",
                                                   "User location is not supported for the API use without a billing account linked.")),
    "rate_minute": ("ClientError", 429, _err_json(429, "RESOURCE_EXHAUSTED", "You exceeded your current quota.", [
        _quota("GenerateRequestsPerMinutePerProjectPerModel-FreeTier"), _retry("7s")])),
    "rate_plain": ("ClientError", 429, _err_json(429, "RESOURCE_EXHAUSTED", "Resource has been exhausted (e.g. check quota).")),
    "unavailable": ("ServerError", 503, _err_json(503, "UNAVAILABLE", "The model is overloaded. Please try again later.")),
    "not_found": ("ClientError", 404, _err_json(404, "NOT_FOUND", "models/xyz is not found for API version v1beta")),
    "invalid": ("ClientError", 400, _err_json(400, "INVALID_ARGUMENT", "Invalid JSON payload received. Unknown name \"foo\"")),
    "too_large": ("ClientError", 413, _err_json(413, "INVALID_ARGUMENT", "Request payload size exceeds the limit")),
    "internal": ("ServerError", 500, _err_json(500, "INTERNAL", "An internal error has occurred.")),
    "deadline": ("ServerError", 504, _err_json(504, "DEADLINE_EXCEEDED", "Deadline expired before operation could complete.")),
}


def fake_error(kind):
    if kind == "timeout":
        return httpx.ReadTimeout("timed out")
    if kind == "connection":
        return httpx.ConnectError("connection refused")
    cls, code, body = FAKE_ERRORS[kind]
    return getattr(genai_errors, cls)(code, copy.deepcopy(body))


# ---------------------------------------------------------------- 분류

def _details(e):
    d = getattr(e, "details", None)
    if isinstance(d, dict):
        err = d.get("error", d)
        items = err.get("details") if isinstance(err, dict) else None
        return items if isinstance(items, list) else []
    return []


def _evidence(e):
    ev = {"reason": "", "quota": [], "retry_delay": None}
    for item in _details(e):
        t = str(item.get("@type", ""))
        if t.endswith("google.rpc.ErrorInfo"):
            ev["reason"] = str(item.get("reason", ""))
        elif t.endswith("google.rpc.QuotaFailure"):
            for v in item.get("violations", []) or []:
                ev["quota"].append({"quotaId": str(v.get("quotaId", "")), "quotaMetric": str(v.get("quotaMetric", "")),
                                    "quotaValue": str(v.get("quotaValue", ""))})
        elif t.endswith("google.rpc.RetryInfo"):
            m = _RETRY_DELAY.match(str(item.get("retryDelay", "")))
            ev["retry_delay"] = float(m.group(1)) if m else None
    return ev


def classify(e) -> llm.ErrorInfo:
    """Gemini 예외 → 분류. 근거(status, reason, quotaId, retryDelay)는 matched_pattern과 message에 남긴다."""
    name = type(e).__name__
    if isinstance(e, KeyMissingError):
        return llm.ErrorInfo(llm.FATAL_AUTH, name, message=str(e))
    if isinstance(e, _TRANSPORT_ERRORS):
        return llm.ErrorInfo(llm.AMBIGUOUS, name, message=llm.USAGE_CHECK_NOTE)
    if not isinstance(e, genai_errors.APIError):
        raise TypeError(f"분류 대상이 아닌 예외: {name}")
    code = int(e.code) if e.code is not None else 0
    status = str(e.status or "")
    msg = _SECRETISH.sub("[가림]", str(e.message or ""))[:300]
    ev = _evidence(e)
    low = msg.lower()
    qids = " ".join((q["quotaId"] + " " + q["quotaMetric"]).lower() for q in ev["quota"])
    info = llm.ErrorInfo("", name, code, status, msg)
    evidence = f"status={status} reason={ev['reason'] or '-'} quotaId={[q['quotaId'] for q in ev['quota']]} " \
               f"retryDelay={ev['retry_delay']}"
    if code == 401 or status == "UNAUTHENTICATED" or code == 403 or status == "PERMISSION_DENIED":
        info.error_class = llm.FATAL_AUTH
    elif code == 400 and (ev["reason"] in API_KEY_REASONS or any(m in low for m in API_KEY_MESSAGES)):
        info.error_class = llm.FATAL_AUTH
    elif code == 429 or status == "RESOURCE_EXHAUSTED":
        daily = any(m in qids for m in DAILY_QUOTA_MARKERS)
        zero = any(q["quotaValue"].strip() in ("0", "0.0") for q in ev["quota"])
        minute = bool(ev["quota"]) and all(any(m in (q["quotaId"] + q["quotaMetric"]).lower()
                                               for m in MINUTE_QUOTA_MARKERS) for q in ev["quota"])
        msg_hit = next((m for m in FREE_TIER_MESSAGES if m in low), "")
        if daily or zero:
            info.error_class = llm.FATAL_QUOTA
            info.matched_pattern = "QuotaFailure " + ("일일 한도" if daily else "quotaValue 0(할당 없음)")
        elif minute:
            info.error_class, info.retry_after_s = llm.TRANSIENT_RATE, ev["retry_delay"]
        elif not ev["quota"] and msg_hit:
            info.error_class, info.matched_pattern = llm.FATAL_QUOTA, f"message '{msg_hit}'"
        else:
            info.error_class, info.retry_after_s = llm.TRANSIENT_RATE, ev["retry_delay"]
        if info.error_class == llm.FATAL_QUOTA:
            info.message = f"{QUOTA_NOTE}; {msg}"
    elif code == 400 and status == "FAILED_PRECONDITION":
        info.error_class, info.matched_pattern = llm.FATAL_QUOTA, "status FAILED_PRECONDITION"
        info.message = f"{QUOTA_NOTE}(지역·결제 조건); {msg}"
    elif code == 503 or status == "UNAVAILABLE":
        info.error_class, info.retry_after_s = llm.TRANSIENT_RATE, ev["retry_delay"]
    elif 400 <= code < 500:
        info.error_class = llm.FATAL_REQUEST
    else:
        info.error_class = llm.AMBIGUOUS
        info.message = f"{llm.USAGE_CHECK_NOTE}; {msg}"
    info.matched_pattern = (info.matched_pattern + "; " if info.matched_pattern else "") + evidence
    return info


# ---------------------------------------------------------------- 응답 해석

def _name(v):
    return getattr(v, "name", None) or (str(v) if v is not None else "")


def interpret(key, response) -> llm.CallResult:
    raw = response.model_dump(mode="json", exclude_none=True, exclude={"sdk_http_response"})
    um = response.usage_metadata
    usage = {k: getattr(um, k, None) for k in ("prompt_token_count", "candidates_token_count",
                                                "thoughts_token_count", "total_token_count")} if um else {}
    res = llm.CallResult(key=key, ok=False, served_model=str(response.model_version or ""),
                         request_id=str(response.response_id or ""), usage=usage, raw=raw, http_200=True)
    pf = response.prompt_feedback
    if pf is not None and pf.block_reason:
        res.stop_reason = f"blocked:{_name(pf.block_reason)}"
        res.failure = f"prompt_feedback.block_reason={_name(pf.block_reason)}"
        return res
    if not response.candidates:
        res.failure = "후보 없음"
        return res
    cand = response.candidates[0]
    res.stop_reason = _name(cand.finish_reason)
    if res.stop_reason != OK_FINISH:
        res.failure = f"finish_reason={res.stop_reason}"
        return res
    parts = (cand.content.parts if cand.content and cand.content.parts else [])
    text = "".join(p.text for p in parts if p.text and not getattr(p, "thought", False))
    if not text:
        res.failure = "text part 없음"
        return res
    res.text = text
    try:
        res.parsed = json.loads(text)
    except json.JSONDecodeError as e:
        res.failure = f"JSON 파싱 실패: {e}"
        return res
    res.ok = True
    return res


# ---------------------------------------------------------------- 어댑터

class GeminiAdapter:
    name = PROVIDER
    billing_tier = "free"
    supports_count_tokens = False  # 지시: Gemini는 구현하지 않고 글자 수 추정을 쓴다
    default_min_interval_s = DEFAULT_MIN_INTERVAL_S
    sdk_errors = (genai_errors.APIError,) + _TRANSPORT_ERRORS
    max_output_tokens = MAX_OUTPUT_TOKENS

    def __init__(self, model=None):
        self.model_id = model or GEMINI_MODEL
        self.schema_changes = []

    def build_request(self, system, user_text, schema):
        gs, self.schema_changes = gemini_schema(schema)
        return {"model": self.model_id, "contents": user_text,
                "config": {"system_instruction": system, "temperature": TEMPERATURE,
                           "response_mime_type": "application/json", "response_json_schema": gs,
                           "max_output_tokens": MAX_OUTPUT_TOKENS, "seed": SEED}}

    def settings_sha(self, req):
        """생성 설정 해시: 요청에서 사용자 메시지(contents)만 뺀 것(모델, temperature, seed, max_output_tokens,
        보낸 스키마, system 포함)."""
        body = {k: v for k, v in req.items() if k != "contents"}
        return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def parse_raw(self, raw):
        return types.GenerateContentResponse.model_validate(raw)

    def raw_dump(self, response):
        return response.model_dump(mode="json", exclude_none=True, exclude={"sdk_http_response"})

    def outbound_problem(self, chunk, docs):
        return outbound_problem(chunk, docs)

    def request_chars(self, req):
        c = req["config"]
        return len(c["system_instruction"]) + len(req["contents"]) + len(
            json.dumps(c["response_json_schema"], ensure_ascii=False))

    def interpret(self, key, response):
        return interpret(key, response)

    def classify(self, e):
        return classify(e)

    def make_client(self):
        return GeminiClient()

    def make_fake_client(self, fake_dir):
        return GeminiFakeClient(fake_dir)

    def key_problem(self):
        return key_problem()

    def model_problem(self):
        return "" if self.model_id else "Gemini 모델이 정해지지 않았다(--model로 사용자가 정한다. 무료 등급 대상 여부는 추측하지 않음)"

    def price(self):
        return {"billing_tier": "free", "usd_per_mtok_input": 0.0, "usd_per_mtok_output": 0.0,
                "basis_date": "2026-10-13", "note": "Gemini API 무료 등급(결제 미연결 프로젝트). 유료 전환은 별도 결정"}

    def meta(self):
        return {
            "provider": self.name, "model": self.model_id or "미설정", "max_tokens": MAX_OUTPUT_TOKENS,
            "temperature": TEMPERATURE, "seed": SEED, "thinking_config": "미설정(모델 기본값)",
            "structured_output": "response_mime_type application/json + response_json_schema",
            "schema_changes_for_gemini": self.schema_changes, "fallbacks": "없음(Gemini 경로에는 폴백이 없다)",
            "google_genai_version": genai.__version__,
            "sdk_client": {"retry_options": "None (never retry)", "timeout_ms": SDK_TIMEOUT_MS},
            "billing_tier": "free",
            "outbound_allowlist": outbound_allowlist(),
        }
