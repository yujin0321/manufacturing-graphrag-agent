"""fallback 체인: 같은 모델 재시도 -> 같은 공급자의 다음 모델 -> 다음 공급자 -> 모두 실패하면 기록 후 문서 건너뜀.

- 전체가 예외로 죽지 않는다. 결과 객체(ChainResult)에 상태를 담는다.
- 크레딧/인증 오류: 그 공급자의 남은 모델은 시도하지 않는다. 다음 공급자는 설정(try_next_provider_on_auth_error)에 따른다.
- 영구 오류(400), 거부, 잘림, 빈 출력, JSON 아님: 같은 모델 재시도 없이 다음 모델로 넘어간다(같은 입력이 같은 한도에서 또 잘리는 비용 방지).
- 어느 모델이 실제로 답했는지 ChainResult.provider/model_id와 모델 호출 기록(calls)에 남긴다.
- 성공(status=success)은 '호출이 끝나 텍스트를 받았다'는 뜻이며 검증 통과가 아니다(validated는 캐시 표시로만 정해진다).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from imaks_kg.extract.providers.base import (QuotaOrAuthError, RefusalOrIncomplete)
from imaks_kg.extract.retry import run_with_retry


@dataclass
class ModelCall:
    provider: str
    model_id: str
    call_id: str
    status: str                      # success | failed | refused | truncated
    error_kind: str = ""
    error_message: str = ""
    attempts: int = 0
    retry_reasons: list = field(default_factory=list)
    delays_s: list = field(default_factory=list)
    possible_duplicate_billing: bool = False
    usage: dict = field(default_factory=dict)
    raw_file: str = ""
    response_sha256: str = ""
    latency_ms: int = 0
    reported_model: str = ""
    raw_masked: bool = False


@dataclass
class ChainResult:
    status: str                      # success | failed
    response: object = None
    provider: str = ""
    model_id: str = ""
    calls: list = field(default_factory=list)
    failure_reason: str = ""
    skipped_document: bool = False   # 모두 실패해 이 문서를 건너뜀
    possible_duplicate_billing: bool = False

    @property
    def raw_files(self) -> list:
        return [c.raw_file for c in self.calls if c.raw_file]


def _status_of(err) -> str:
    if isinstance(err, RefusalOrIncomplete):
        return {"refused": "refused", "truncated": "truncated", "empty": "truncated"}.get(err.kind, "failed")
    return "failed"


def run_chain(chain, request, providers, policy, logger, parent_id, request_meta, *,
              try_next_provider_on_auth_error=True, sleep, rng, clock) -> ChainResult:
    result = ChainResult(status="failed")
    halted = set()
    abort = False
    for pspec, mspec in chain:
        if abort:
            break
        if pspec.name in halted:
            continue
        provider = providers[pspec.name]
        call_id = logger.new_call_id()

        def attempt(provider=provider, mspec=mspec):
            resp = provider.generate(request, mspec)
            if request.expect_json:
                try:
                    json.loads(resp.text)
                except ValueError:
                    raise RefusalOrIncomplete("응답이 JSON으로 해석되지 않습니다.", kind="invalid_json",
                                              raw_text=resp.text, raw_body=resp.raw_body, usage=resp.usage) from None
            return resp

        t0 = clock()
        out = run_with_retry(attempt, policy, sleep, rng)
        latency_ms = int((clock() - t0) * 1000)
        mc = ModelCall(pspec.name, mspec.id, call_id, "success" if out.ok else "failed", attempts=out.attempts,
                       retry_reasons=list(out.retry_reasons), delays_s=list(out.delays_s),
                       possible_duplicate_billing=out.possible_duplicate_billing, latency_ms=latency_ms)
        raw_text = ""
        if out.ok:
            mc.usage = dict(out.response.usage)
            mc.reported_model = out.response.reported_model
            raw_text = out.response.raw_body
        else:
            err = out.error
            mc.status = _status_of(err)
            mc.error_kind = getattr(err, "error_kind", "") or type(err).__name__
            mc.error_message = logger.clean(str(err))
            if isinstance(err, RefusalOrIncomplete):
                mc.usage = dict(err.usage)
                raw_text = err.raw_body or err.raw_text  # 거부, 잘림, JSON 아님: 원문 보존
        if raw_text:
            w = logger.write_raw(call_id, raw_text)
            mc.raw_file, mc.response_sha256, mc.raw_masked = w["raw_file"], w["response_sha256"], w["raw_masked"]
        result.calls.append(mc)
        result.possible_duplicate_billing = result.possible_duplicate_billing or mc.possible_duplicate_billing
        logger.append({"record_type": "model_call", "call_id": call_id, "parent_id": parent_id,
                       "step_name": request.step_name, "request_meta": request_meta,
                       "run_mode": request_meta.get("run_mode", ""),
                       "requested_provider": chain[0][0].name, "requested_model": chain[0][1].id,
                       "actual_provider": pspec.name, "actual_model": mspec.id,
                       "reported_model": mc.reported_model, "thinking_level": mspec.thinking_level,
                       "status": mc.status, "error_kind": mc.error_kind, "error_message": mc.error_message,
                       "attempts": mc.attempts, "retry_reasons": mc.retry_reasons, "backoff_delays_s": mc.delays_s,
                       "usage": mc.usage, "latency_ms": mc.latency_ms, "raw_file": mc.raw_file,
                       "response_sha256": mc.response_sha256,
                       "possible_duplicate_billing": mc.possible_duplicate_billing})
        if out.ok:
            result.status = "success"
            result.response = out.response
            result.provider, result.model_id = pspec.name, mspec.id
            return result
        if isinstance(out.error, QuotaOrAuthError):
            halted.add(pspec.name)
            if not try_next_provider_on_auth_error:
                abort = True
    last = result.calls[-1] if result.calls else None
    result.skipped_document = True
    result.failure_reason = (f"모든 모델 실패({len(result.calls)}회 호출 묶음). 마지막: {last.provider}/{last.model_id} "
                             f"{last.status} {last.error_kind}") if last else "시도할 모델이 없습니다."
    return result
