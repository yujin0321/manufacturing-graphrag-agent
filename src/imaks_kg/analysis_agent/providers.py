"""생성 모델 제공자 선택: OpenAI(기존 설정) 또는 Gemini(OpenAI 호환 엔드포인트).

Agent는 `call(resource, payload, cache) -> (raw, transport)` 함수만 쓴다. OpenAI는 기존
`rag.vector.api_call`을 그대로 쓰고, Gemini는 아래 `gemini_call`이 같은 규칙으로 동작한다.
* 고정 공식 호스트, 자동 재시도 없음, 원응답 저장, 같은 요청은 저장 응답 재사용(API 0회), 키 기록 안 함.
* 키: 환경변수 GEMINI_API_KEY(.env는 CLI가 읽어 환경변수로 넣는다).
* 무료 등급은 Google AI Studio에서 결제를 연결하지 않은 프로젝트의 키로만 유지된다.
  결제가 연결된 프로젝트의 키는 무료 한도와 관계없이 과금될 수 있다.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from imaks_kg.rag import vector as v

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
GEMINI_DEFAULT_MODEL = "gemini-3.8-flash"
PROVIDERS = ("openai", "gemini")


def default_model(provider: str) -> str:
    if provider == "openai":
        return v.read(v.CONFIG)["generation_model"]
    if provider == "gemini":
        return os.environ.get("GEMINI_MODEL", GEMINI_DEFAULT_MODEL)
    raise ValueError(f"unknown provider: {provider}")


def get(provider: str = "openai", model: str | None = None):
    """(call, model). model은 Agent가 응답 모델과 대조하는 기대값이다."""
    model = model or default_model(provider)
    if provider == "openai":
        return v.api_call, model
    return gemini_call, model


GEMINI_TIMEOUT = 300  # 무료 등급은 짧은 요청도 1~2분 걸린 사례가 있다(2026-11-15 실측 47~152초)


def _gemini_payload(payload: dict) -> dict:
    """OpenAI 전용 필드를 Gemini 호환 필드로 바꾼다.

    reasoning_effort 기본 "none": Gemini는 내부 추론 토큰이 max_tokens에 포함되어 짧은 한도(검증 1024)에서
    답이 잘릴 수 있고, 실측에서도 none이 가장 빨랐다. GEMINI_REASONING_EFFORT로 바꿀 수 있다.
    """
    out = {k: val for k, val in payload.items() if k not in ("store", "max_completion_tokens")}
    if "max_completion_tokens" in payload:
        out["max_tokens"] = payload["max_completion_tokens"]
    out.setdefault("reasoning_effort", os.environ.get("GEMINI_REASONING_EFFORT", "none"))
    return out


def gemini_call(resource: str, payload: dict, cache, *, opener=urlopen) -> tuple[dict, dict]:
    if resource != "chat/completions":
        raise ValueError("Unsupported API resource")
    body = _gemini_payload(payload)
    cache = Path(cache)
    key = v.digest(v.encoded({"provider": "gemini", "resource": resource, "payload": body}))
    raw_path = cache / (key + ".response.json")
    if raw_path.exists():
        return _normalize(v.read(raw_path), body["model"]), {"cache_hit": True, "request_sha256": key, "seconds": 0}
    token = os.environ.get("GEMINI_API_KEY")
    if not token:
        raise RuntimeError("GEMINI_API_KEY가 없습니다. .env 또는 환경변수에 설정해 주세요.")
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / (key + ".attempt.json")).open("x", encoding="utf-8") as f:
        json.dump({"started_at": datetime.now(timezone.utc).isoformat(), "provider": "gemini"}, f)
    v.write(cache / (key + ".request.json"), body)
    req = Request(GEMINI_BASE + resource, data=v.encoded(body),
                  headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    started = time.perf_counter()
    try:
        with opener(req, timeout=GEMINI_TIMEOUT) as response:
            raw = json.load(response)
    except HTTPError as exc:
        v.write(cache / (key + ".error.json"), {"http_status": exc.code, "retry": False})
        hint = " 무료 등급 호출 한도를 넘었을 수 있습니다. 잠시 뒤 다시 질문해 주세요." if exc.code == 429 else ""
        raise RuntimeError(f"Gemini HTTP {exc.code}; 자동 재시도 없음.{hint}") from None
    except (URLError, TimeoutError):
        v.write(cache / (key + ".error.json"), {"transport_error": True, "retry": False})
        raise RuntimeError("Gemini 전송 실패; 자동 재시도 없음") from None
    v.write(raw_path, raw)
    return _normalize(raw, body["model"]), {"cache_hit": False, "request_sha256": key,
                                            "seconds": time.perf_counter() - started}


def _normalize(raw: dict, requested: str) -> dict:
    """Gemini는 모델명을 'models/<id>'나 버전 접미사와 함께 돌려줄 수 있다. 같은 모델이면 요청명으로 맞춘다."""
    returned = str(raw.get("model") or "")
    bare = returned.split("/", 1)[1] if returned.startswith("models/") else returned
    out = dict(raw)
    out["returned_model_raw"] = returned
    if bare == requested or bare.startswith(requested + "-") or (not returned and raw.get("choices")):
        out["model"] = requested
    return out
