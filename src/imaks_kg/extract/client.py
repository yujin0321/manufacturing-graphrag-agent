"""고수준 호출: extract_call(config, request) = 캐시 확인 -> fallback 체인 -> 호출 기록 -> 결과.

요청 본문(프롬프트 텍스트)은 호출자(2단계 요청 빌더)가 만들어 넘기며 여기서는 그대로 전달한다.
이 함수는 검증을 하지 않는다. 결과의 status="success"는 '텍스트를 받았다'는 뜻이고,
검증을 통과시키면 호출자가 result.mark_validated()를 불러야 캐시가 재사용된다.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from imaks_kg.extract.cache import ResponseCache, make_cache_key
from imaks_kg.extract.callog import CallLogger
from imaks_kg.extract.config import ExtractConfig, model_fingerprint
from imaks_kg.extract.fallback import run_chain
from imaks_kg.extract.providers.base import LLMRequest
from imaks_kg.extract.providers.gemini import GeminiProvider
from imaks_kg.extract.providers.openai import OpenAIProvider

_PROVIDER_CLASSES = {"gemini": GeminiProvider, "openai": OpenAIProvider}


def build_providers(config: ExtractConfig, transport=None, environ=None) -> dict:
    out = {}
    for name in config.provider_order:
        cls = _PROVIDER_CLASSES.get(name)
        if cls is None:
            raise ValueError(f"알 수 없는 공급자: {name}. providers 인자로 직접 넘기세요.")
        out[name] = cls(config.providers[name], transport=transport, environ=environ)
    return out


@dataclass
class ExtractResult:
    status: str                       # success | failed
    text: str = ""
    provider: str = ""
    model_id: str = ""
    cache_hit: bool = False
    validated: bool = False           # 캐시 적중 때만 True(이전에 검증을 통과한 응답)
    cache_key: str = ""               # 실제로 답한 모델 기준 키(mark_validated에 쓰임)
    call_id: str = ""
    skipped_document: bool = False
    failure_reason: str = ""
    complete: bool = False            # 항상 False로 시작: 완료 판정은 검증기가 한다(캐시 적중은 True)
    possible_duplicate_billing: bool = False
    raw_files: list = field(default_factory=list)
    calls: list = field(default_factory=list)
    _cache: object = None

    def mark_validated(self, validator: str = "") -> None:
        """2단계 검증기가 코드 검증을 통과시킨 뒤 호출한다."""
        if self._cache is None or not self.cache_key:
            raise RuntimeError("캐시에 저장된 응답이 없어 검증 표시를 할 수 없습니다.")
        self._cache.mark_validated(self.cache_key, validator)
        self.validated = True
        self.complete = True


def _request_meta(request: LLMRequest, chain, run_mode: str = "") -> dict:
    return {"run_mode": run_mode, "answer_key_supplied": request.answer_key_supplied,
            "seed_maintenance_text_supplied": request.seed_maintenance_text_supplied,
            "doc_id": request.doc_id, "prompt_sha256": request.prompt_sha256,
            "example_sha256": request.example_sha256, "schema_sha256": request.schema_sha256,
            "input_sha256": request.input_sha256,
            "requested_provider": chain[0][0].name, "requested_model": chain[0][1].id}


def extract_call(config: ExtractConfig, request: LLMRequest, *, providers=None, logger=None, cache=None,
                 use_cache=True, run_id=None, sleep=time.sleep, rng=random.random,
                 clock=time.monotonic) -> ExtractResult:
    if request.answer_key_supplied or request.seed_maintenance_text_supplied:
        raise ValueError("정답 또는 seed 정비 문구가 요청에 포함된 것으로 표시되어 있어 호출을 거부합니다.")
    chain = config.chain()
    if not chain:
        raise ValueError("시도할 모델이 없습니다. 설정에 모델을 채우세요.")
    config.assert_run_mode()  # scoring 모드는 모델 하나만(위반하면 ConfigError)
    providers = providers if providers is not None else build_providers(config)
    logger = logger or CallLogger(config.log_dir, run_id, config.key_env_names())
    cache = cache if cache is not None else (ResponseCache(config.cache_dir) if use_cache else None)
    meta = _request_meta(request, chain, config.run_mode)
    parent_id = logger.new_call_id()

    if cache is not None:
        for pspec, mspec in chain:
            key = make_cache_key(request, model_fingerprint(pspec, mspec))
            hit = cache.get_validated(key)
            if hit is not None:
                logger.append({"record_type": "extract_call", "call_id": parent_id, "parent_id": None,
                               "step_name": request.step_name, "request_meta": meta, "run_mode": config.run_mode, "cache_hit": True,
                               "cache_key": key, "status": "success", "actual_provider": pspec.name,
                               "actual_model": mspec.id, "response_sha256": hit.get("raw_sha256", ""),
                               "attempts": 0, "usage": {}, "possible_duplicate_billing": False})
                return ExtractResult("success", hit["text"], pspec.name, mspec.id, True, True, key, parent_id,
                                     complete=True, _cache=cache)

    cr = run_chain(chain, request, providers, config.retry, logger, parent_id, meta,
                   try_next_provider_on_auth_error=config.try_next_provider_on_auth_error,
                   sleep=sleep, rng=rng, clock=clock)
    key = ""
    if cr.status == "success" and cache is not None:
        by_id = {(p.name, m.id): (p, m) for p, m in chain}
        pspec, mspec = by_id[(cr.provider, cr.model_id)]
        key = make_cache_key(request, model_fingerprint(pspec, mspec))
        raw_sha = next((c.response_sha256 for c in cr.calls if c.model_id == cr.model_id and c.status == "success"), "")
        cache.put(key, {"text": cr.response.text, "provider": cr.provider, "model_id": cr.model_id,
                        "raw_sha256": raw_sha, "doc_id": request.doc_id})
    logger.append({"record_type": "extract_call", "call_id": parent_id, "parent_id": None,
                   "step_name": request.step_name, "request_meta": meta, "run_mode": config.run_mode, "cache_hit": False, "cache_key": key,
                   "status": cr.status, "actual_provider": cr.provider, "actual_model": cr.model_id,
                   "models_tried": [f"{c.provider}/{c.model_id}:{c.status}" for c in cr.calls],
                   "skipped_document": cr.skipped_document, "failure_reason": cr.failure_reason,
                   "possible_duplicate_billing": cr.possible_duplicate_billing,
                   "attempts": sum(c.attempts for c in cr.calls)})
    return ExtractResult(cr.status, cr.response.text if cr.response else "", cr.provider, cr.model_id, False, False,
                         key, parent_id, cr.skipped_document, cr.failure_reason, False,
                         cr.possible_duplicate_billing, cr.raw_files, cr.calls, cache)
