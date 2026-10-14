"""같은 모델에 대한 재시도(설계 6장). 일시 오류만 지수 백오프+지터로 재시도한다.

- 재시도: TransientError(429/408/5xx/타임아웃)만. 재시도 횟수 = policy.max_retries(기본 4 -> 총 5회 시도, 대기 1, 2, 4, 8초). 대기 = min(max_delay, base * 2^(n-1) * (1 + jitter_ratio * 난수)).
- 재시도 금지: PermanentError(400 등), RefusalOrIncomplete(잘림, 거부, 빈 출력, JSON 아님).
- 즉시 중단: QuotaOrAuthError(크레딧, 할당량, 인증).
- sleep과 난수는 주입한다(테스트가 실제로 기다리지 않음).
- 타임아웃 뒤 재시도는 허용하되 possible_duplicate_billing을 남긴다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from imaks_kg.extract.providers.base import ExtractError, PermanentError, TransientError
from imaks_kg.extract.connectivity import mask


@dataclass
class RetryResult:
    ok: bool
    response: object = None
    error: Exception | None = None
    attempts: int = 0
    retry_reasons: list = field(default_factory=list)
    delays_s: list = field(default_factory=list)
    possible_duplicate_billing: bool = False


def backoff_delay(retry_index: int, policy, rng) -> float:
    """retry_index: 1이면 첫 재시도 앞의 대기. 1, 2, 4, 8초 형태에 지터를 더하고 상한을 씌운다."""
    raw = policy.base_delay_s * (2 ** (retry_index - 1))
    return min(policy.max_delay_s, raw * (1.0 + policy.jitter_ratio * rng()))


def run_with_retry(fn, policy, sleep, rng) -> RetryResult:
    res = RetryResult(ok=False)
    for attempt in range(1, policy.total_attempts + 1):
        res.attempts = attempt
        try:
            res.response = fn()
            res.ok = True
            return res
        except TransientError as e:
            res.error = e
            if e.possible_duplicate_billing:
                res.possible_duplicate_billing = True
            if attempt >= policy.total_attempts:
                return res
            res.retry_reasons.append(e.error_kind or "transient")
            d = backoff_delay(attempt, policy, rng)
            res.delays_s.append(d)
            sleep(d)
        except ExtractError as e:  # Permanent, QuotaOrAuth, RefusalOrIncomplete: 재시도 안 함
            res.error = e
            return res
        except Exception as e:  # 예기치 못한 오류도 전체를 죽이지 않고 영구 오류로 기록(키 마스킹)
            res.error = PermanentError(f"예기치 못한 오류 {type(e).__name__}: {mask(str(e))}",
                                       error_kind="unexpected")
            return res
    return res
