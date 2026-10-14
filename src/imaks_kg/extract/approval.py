"""--execute 비용 승인 게이트(사용자 승인 2026-10-13).

1. --dry-run이 추정 기록 extraction/approvals/<estimate_id>.json을 쓴다.
   - 내용: 모델, 호출 수, 호출당 max_tokens, 입력 토큰(count_tokens 실측 또는 글자 수 추정, 어느 쪽인지 표시),
     출력 상한, 비용 범위(코드 상수 가격표와 가격 기준일), 입력 지문(meta의 input_fingerprint, 프롬프트 해시,
     예시 파일 해시, 스키마 해시, 선택 청크 해시 목록), 생성 시각.
   - estimate_id = 기록 내용(사용 기록 제외)의 정규화 JSON SHA-256 앞 16자리. 전체 해시는 content_sha256에 둔다.
2. --execute는 --approve <estimate_id>가 있어야 한다. 다음이면 클라이언트를 만들기 전에 거부한다:
   플래그 없음, 기록 없음, 기록 내용이 해시와 다름(고침), 이미 다른 실행에 쓰임, 모델·입력 지문·프롬프트·예시·
   스키마·청크 목록이 현재와 다름, 현재 호출 수가 기록의 호출 수보다 많음. 메시지에 사유와 바뀐 값을 적는다.
3. 상태 기계(2026-10-13 사용자 지시). 기록의 state와 history가 상태와 이력을 가진다(내용 해시에는 들어가지 않음).

     unused ──(첫 API 호출 직전 reserve)──▶ reserved ──┬─(HTTP 200이 1번이라도 있음)──────────▶ used
       ▲                                               ├─(AMBIGUOUS가 있음)──────────────────▶ usage_check_required
       └──────────(released: 자동 복원)─────────────────┘   (200 없음 + FATAL_*/TRANSIENT_EXHAUSTED/준비 오류)
     usage_check_required ──(사람이 Console 확인 뒤 resolve --as used|unused)──▶ used 또는 unused

   - reserved·used·usage_check_required인 승인은 다른 실행이 쓸 수 없다.
   - 복원된 승인을 다시 쓸 때도 --execute는 입력 지문을 다시 검사한다.
   - history: reserved / released / used / usage_check_required / resolved 사건마다 run_id, 시각, 사유,
     시도별 (청크, 시도 번호, 오류 분류, 상태 코드)를 남긴다. used에는 부분 실행 정보(완료·미완료 청크)를 남긴다.
   - 실행 기록(meta.json)에 approval_id를 남긴다.
   - 해결: python -m imaks_kg.extract.approval resolve <estimate_id> --as used|unused --note "..." [--approvals-dir DIR]
4. 승인은 두 수를 따로 정한다(2026-10-13 수정): 승인 청크 수(approved_chunks)와 API 시도 상한(approved_attempts =
   min(청크 수 × 청크당 시도 한도, 청크 수 + 실행당 재시도 한도)). CallBudget이 둘 다 막는다. 재시도는 재시도 예산과
   시도 상한(남은 청크의 첫 시도 몫을 뺀 여유) 둘 다에 여유가 있어야 한다.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from imaks_kg.common.provenance import sha256_text
from imaks_kg.extract import ledger, llm, locks
from imaks_kg.extract.common import ExtractError, disp

# 가격표(USD / 100만 토큰), 공급자별. 기준일 이후 가격이 바뀌면 이 상수와 기준일을 함께 고친다.
# Gemini는 무료 등급(결제 미연결 프로젝트)만 쓴다. 비용 0, billing_tier "free". 유료 전환은 별도 결정이며 자동으로 하지 않는다.
PRICE_TABLE = {
    "anthropic": {"claude-opus-5-5": {"input_per_mtok": 4.0, "output_per_mtok": 20.0, "billing_tier": "paid",
                                      "basis_date": "2026-10-06"}},
    "gemini": {"*": {"input_per_mtok": 0.0, "output_per_mtok": 0.0, "billing_tier": "free",
                     "basis_date": "2026-10-13"}},
}
PRICE_BASIS_DATE = PRICE_TABLE["anthropic"]["claude-opus-5-5"]["basis_date"]


def price_for(provider, model):
    table = PRICE_TABLE.get(provider)
    if table is None:
        raise ExtractError(f"가격표에 공급자 {provider}가 없음")
    row = table.get(model) or table.get("*")
    if row is None:
        raise ExtractError(f"가격표에 {provider} 모델 {model}이 없음")
    return row
# 내용 해시에 들어가는 필드(추정 내용). 상태·이력 필드는 해시 밖이다.
ATTEMPT_CAP_FORMULA = "min(approved_chunks × MAX_ATTEMPTS_PER_CHUNK, approved_chunks + MAX_RETRIES_PER_RUN)"


def attempt_cap(n_chunks):
    return min(n_chunks * llm.MAX_ATTEMPTS_PER_CHUNK, n_chunks + llm.MAX_RETRIES_PER_RUN)


BODY_FIELDS = ("approved_chunks", "approved_attempts", "attempt_cap_formula", "model", "calls", "max_tokens_per_call", "input_tokens", "output_cap_tokens", "price", "cost_usd",
               "fingerprint", "created_at", "chunk_filter", "provider", "billing_tier", "pacing")
UNUSED, RESERVED, USED, USAGE_CHECK = "unused", "reserved", "used", "usage_check_required"
STATES = (UNUSED, RESERVED, USED, USAGE_CHECK)


def fingerprint(ctx) -> dict:
    adapter = ctx.get("adapter") or llm.ANTHROPIC
    return {
        "provider": adapter.name,
        "model": adapter.model_id,
        "input_fingerprint": ctx["fingerprint"],
        "prompt_version": ctx["prompt"]["version"],
        "prompt_sha256": ctx["prompt"]["prompt_sha256"],
        "examples_sha256": ctx["prompt"]["examples_sha256"],
        "schema_sha256": sha256_text(json.dumps(ctx["schema"], ensure_ascii=False, sort_keys=True)),
        "chunks": [{"chunk_id": c["chunk_id"], "text_sha256": c["text_sha256"]} for c, _ in ctx["requests"]],
    }


def _cost(tokens, per_mtok):
    return round(tokens * per_mtok / 1_000_000, 4)


def build_estimate(ctx, est, counted=None, created_at=None) -> dict:
    adapter = ctx.get("adapter") or llm.ANTHROPIC
    price = price_for(adapter.name, adapter.model_id)
    calls = len(ctx["requests"])
    if counted is not None:
        tin = {"method": "count_tokens", "value": int(counted), "high": int(counted),
               "note": "messages.count_tokens 실측(구조화 출력 스키마 토큰은 포함되지 않음)"}
    else:
        tin = {"method": "chars_estimate", "value": est["tokens_est"], "high": est["tokens_est_high"],
               "note": f"글자 수 추정(value=글자/4, high=글자/3), 글자 수 {est['chars']}"}
    out_cap = adapter.max_output_tokens * calls
    rec = {
        "provider": adapter.name, "billing_tier": price["billing_tier"],
        "pacing": {"min_interval_s": ctx.get("min_interval_s", 0.0),
                   "max_attempts_per_chunk": llm.MAX_ATTEMPTS_PER_CHUNK, "max_retries_per_run": llm.MAX_RETRIES_PER_RUN},
        "approved_chunks": calls, "approved_attempts": attempt_cap(calls),
        "attempt_cap_formula": f"{ATTEMPT_CAP_FORMULA} = min({calls}×{llm.MAX_ATTEMPTS_PER_CHUNK}, "
                               f"{calls}+{llm.MAX_RETRIES_PER_RUN}) = {attempt_cap(calls)}",
        "model": adapter.model_id, "calls": calls, "max_tokens_per_call": adapter.max_output_tokens,
        "input_tokens": tin, "output_cap_tokens": out_cap,
        "price": {"usd_per_mtok_input": price["input_per_mtok"], "usd_per_mtok_output": price["output_per_mtok"],
                  "basis_date": price["basis_date"]},
        "cost_usd": {
            "input_low": _cost(tin["value"], price["input_per_mtok"]),
            "input_high": _cost(tin["high"], price["input_per_mtok"]),
            "output_max": _cost(out_cap, price["output_per_mtok"]),
            "total_max": round(_cost(tin["high"], price["input_per_mtok"]) + _cost(out_cap, price["output_per_mtok"]), 4),
            "note": "최솟값은 입력만(출력 0) 계산. 최댓값은 입력 상한 + 모든 호출이 max_tokens까지 출력한 경우",
        },
        "fingerprint": fingerprint(ctx),
        "created_at": created_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "chunk_filter": ctx.get("chunk_filter"),
    }
    content = _content_sha(rec)
    rec["content_sha256"] = content
    rec["estimate_id"] = content[:16]
    rec["state"] = UNUSED
    rec["history"] = [{"event": "created", "at": rec["created_at"]}]
    return rec


def _content_sha(rec):
    body = {k: rec.get(k) for k in BODY_FIELDS}
    return sha256_text(json.dumps(body, ensure_ascii=False, sort_keys=True))


def _dump(rec) -> bytes:
    return (json.dumps(rec, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


_write_file = locks.atomic_write_bytes  # 테스트가 "장부 기록 뒤 파일 쓰기 실패"를 흉내 낼 때 바꾼다


def _commit(path, rec, event, run_id=None):
    """상태 변경을 확정한다: 장부에 먼저 적고(fsync) 그다음 승인 파일을 원자적으로 바꾼다.
    파일 쓰기가 실패하면 장부와 파일이 어긋나 verify_approval이 거부한다(닫힌 쪽으로 실패, 추가 호출 없음)."""
    data = _dump(rec)
    ledger.append(event, {Path(path).name: sha256_bytes(data)}, run_id=run_id, estimate_id=rec["estimate_id"],
                  state=rec.get("state"))
    _write_file(path, data)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def write_estimate(rec, approvals_dir) -> Path:
    p = Path(approvals_dir) / f"{rec['estimate_id']}.json"
    with locks.approval_lock(rec["estimate_id"]):
        if p.exists():
            raise ExtractError(f"추정 기록이 이미 있음(덮어쓰지 않음): {disp(p)}")
        _commit(p, rec, "approval_created")
    return p


def _diff(prefix, old, new, out):
    if isinstance(old, dict) and isinstance(new, dict):
        for k in sorted(set(old) | set(new)):
            _diff(f"{prefix}.{k}", old.get(k), new.get(k), out)
    elif old != new:
        if isinstance(old, list) or isinstance(new, list):
            o = {json.dumps(x, sort_keys=True) for x in (old or [])}
            n = {json.dumps(x, sort_keys=True) for x in (new or [])}
            out.append(f"{prefix}: 추정 때 {len(old or [])}개 / 현재 {len(new or [])}개, "
                       f"바뀐 항목 예: {sorted(o ^ n)[:3]}")
        else:
            out.append(f"{prefix}: 추정 때 {old} / 현재 {new}")


def check_approval(estimate_id, approvals_dir, ctx):
    """(기록, 경로) 또는 ExtractError(사유와 바뀐 값). 파일을 쓰지 않는다."""
    if not estimate_id:
        raise ExtractError("실제 실행 거부: --approve <estimate_id>가 없음. 먼저 --dry-run으로 추정 기록을 만들고 "
                           "비용을 승인받은 뒤 그 ID를 준다.")
    if not all(ch in "0123456789abcdef" for ch in estimate_id) or len(estimate_id) != 16:
        raise ExtractError(f"실제 실행 거부: estimate_id 형식이 아님: {estimate_id!r}")
    p = Path(approvals_dir) / f"{estimate_id}.json"
    if not p.exists():
        raise ExtractError(f"실제 실행 거부: 추정 기록이 없음: {disp(p)}")
    if state_of(_load(p)) == RESERVED:
        recover_if_abandoned(p)  # 쥔 프로세스가 죽은 예약은 usage_check_required로(절대 unused로 되돌리지 않음)
    rec = json.loads(p.read_text(encoding="utf-8"))
    errors = []
    content = _content_sha(rec)
    if content != rec.get("content_sha256") or content[:16] != rec.get("estimate_id") or rec.get("estimate_id") != estimate_id:
        errors.append(f"추정 기록 내용이 해시와 다름(기록을 고침): 기록 {rec.get('content_sha256')} / 다시 계산 {content}")
    led = ledger.verify_approval(p)  # 상태 필드는 내용 해시 밖이라 장부로 다시 만든 상태와 대조한다
    state = state_of(rec)
    if led:
        errors.append(ledger_mismatch_message(p, rec, led))
    elif state != UNUSED:
        last = (rec.get("history") or [{}])[-1]
        errors.append(f"쓸 수 없는 승인 상태 {state}(run_id {last.get('run_id')}, {last.get('at')}). "
                      + ("Console에서 사용량을 확인하고 resolve로 해결해야 한다" if state == USAGE_CHECK
                         else "다시 추정·승인 필요" if state == USED else "다른 실행이 예약 중(실행 잠금을 쥐고 있음)"))
    adapter = ctx.get("adapter") or llm.ANTHROPIC
    if rec.get("model") != adapter.model_id or rec.get("provider", "anthropic") != adapter.name:
        errors.append(f"공급자·모델: 추정 때 {rec.get('provider', 'anthropic')}/{rec.get('model')} / "
                      f"현재 {adapter.name}/{adapter.model_id} (자동 전환 없음)")
    _diff("fingerprint", rec.get("fingerprint"), fingerprint(ctx), errors)
    if len(ctx["requests"]) > int(rec.get("approved_chunks", rec.get("calls", 0))):
        errors.append(f"청크 수: 승인 {rec.get('approved_chunks', rec.get('calls'))} < 현재 {len(ctx['requests'])}")
    if errors:
        raise ExtractError("실제 실행 거부(클라이언트를 만들지 않음): 승인 기록과 현재가 다름\n- " + "\n- ".join(errors))
    return rec, p


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ledger_mismatch_message(path, rec, details):
    """장부와 승인 파일이 어긋났을 때의 거부 사유(원인·기대 상태·파일 상태·할 일)."""
    try:
        st = ledger.approval_state(rec.get("estimate_id"))
    except ExtractError:
        st = None
    expected = st[0] if st else "(장부에 기록 없음)"
    return (f"해시 장부와 승인 파일이 어긋남: 장부의 기대 상태 {expected} / 파일의 상태 {state_of(rec)}. "
            f"이 승인은 쓸 수 없다(파일 쓰기 실패나 수동 수정 가능성). --dry-run으로 새 추정을 만들고 다시 승인받는다. "
            f"세부: {'; '.join(details)}")


def state_of(rec):
    if rec.get("state") in STATES:
        return rec["state"]
    return USED if rec.get("used_by_run_id") else UNUSED  # 이전 형식 기록


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _event(rec, event, run_id, **kw):
    rec.setdefault("history", []).append({"event": event, "run_id": run_id, "at": _now(), **kw})


def reserve(path, run_id, journal=None):
    """첫 API 호출 직전에 부른다. 승인 잠금 안에서: 다시 읽기 → 장부 검사 → 상태 확인 → 장부에 reserved 먼저 기록
    → 파일을 원자적으로 바꾼다. unused가 아니면 ExtractError(호출하지 않음). journal: 시도 기록 파일(복구 때 증거)."""
    with locks.approval_lock(Path(path).stem):
        bad = ledger.verify_approval(path)
        if bad:
            raise ExtractError("승인 예약 실패: " + ledger_mismatch_message(path, _load(path), bad))
        rec = _load(path)
        state = state_of(rec)
        if state != UNUSED:
            raise ExtractError(f"승인 예약 실패: 상태 {state}(다른 실행이 쓰는 중이거나 이미 씀)")
        rec["state"] = RESERVED
        rec["reserved_by_run_id"] = run_id
        rec["reserved_at"] = _now()
        _event(rec, "reserved", run_id, journal=(str(journal) if journal else None))
        _commit(path, rec, "reserved", run_id)
    return rec


# ---------------------------------------------------------------- 시도 기록(journal)과 승인 정리

SURE_NO_GENERATION = (llm.FATAL_AUTH, llm.FATAL_BILLING, llm.FATAL_QUOTA, llm.FATAL_REQUEST, llm.TRANSIENT_RATE,
                      llm.TRANSIENT_EXHAUSTED)


def read_journal(path):
    """시도 기록(attempts.jsonl). 없으면 [], 읽을 수 없으면 None(판단 불가)."""
    p = Path(path)
    if not p.exists():
        return []
    out = []
    try:
        for ln in p.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                out.append(json.loads(ln))
    except (OSError, json.JSONDecodeError):
        return None
    return out


def _legacy_events(outcome):
    """journal이 없을 때 outcome의 시도 목록을 단계로 바꾼다(이전 호출 방식 호환)."""
    ev = []
    for a in (outcome or {}).get("attempts", []):
        key = {"chunk_id": a.get("chunk_id"), "attempt": a.get("attempt")}
        # 단계나 상태가 하나라도 있으면 보낸 시도로 본다(보수적, 18장 FAIL 2 수정)
        ev.append(dict(key, phase="sending"))
        if a.get("phase") and a["phase"] not in ("prepared", "sending"):
            ev.append(dict(key, phase=a["phase"], error_class=a.get("error_class"), status=a.get("status")))
            continue
        if a.get("status") == 200:
            ev.append(dict(key, phase="http_200_received", status=200))
        elif a.get("error_class") == llm.AMBIGUOUS:
            ev.append(dict(key, phase="transport_error", error_class=llm.AMBIGUOUS, status=a.get("status")))
        else:
            ev.append(dict(key, phase="http_error_response", error_class=a.get("error_class"), status=a.get("status")))
    return ev


def decide(events, outcome=None, error=""):
    """시도 단계 기록 → (상태, 사유, 요약). 사용하지 않았음이 확실할 때만 unused다. 그 밖에는 보수적으로 정한다.
    - 불확실(보낸 뒤 응답 기록 없음, 전송 오류·타임아웃, 5xx AMBIGUOUS, 기록을 읽을 수 없음) → usage_check_required
      (200이 일부 있어도 불확실한 시도가 있으면 이쪽이 우선이다. 끊긴 그 호출이 생성·소모됐는지 모르기 때문)
    - HTTP 200을 받은 시도가 있음 → used(해석 중 오류여도 200은 잃지 않음)
    - 보낸 시도가 없음 → unused(released)
    - 보낸 시도가 모두 서버의 오류 응답(FATAL_*·TRANSIENT)으로 끝남 → unused(released)
    """
    outcome = outcome or {}
    if events is None:
        return USAGE_CHECK, "시도 기록을 읽을 수 없어 판단 불가", {}
    by_attempt = {}
    for e in events:
        by_attempt.setdefault((e.get("chunk_id"), e.get("attempt")), []).append(e)
    sent = {k: v for k, v in by_attempt.items() if any(x.get("phase") == "sending" for x in v)}
    got200 = sorted({k[0] for k, v in sent.items() if any(x.get("phase") == "http_200_received" for x in v)})
    uncertain, errors_only = [], []
    for k, v in sent.items():
        phases = [x.get("phase") for x in v]
        if "http_200_received" in phases:
            continue
        err = next((x for x in v if x.get("phase") in ("http_error_response", "local_error")), None)
        if "transport_error" in phases or err is None:
            uncertain.append(f"{k[0]}#{k[1]}({phases[-1]})")
        elif err.get("error_class") in SURE_NO_GENERATION:
            errors_only.append(f"{k[0]}#{k[1]}({err.get('error_class')} {err.get('status')})")
        else:
            uncertain.append(f"{k[0]}#{k[1]}({err.get('error_class')} {err.get('status')})")
    n200 = max(len(got200), int(outcome.get("http_200", 0) or 0))
    summary = {"sent_attempts": len(sent), "http_200_chunks": got200, "uncertain": uncertain,
               "server_errors": errors_only}
    if uncertain:
        return USAGE_CHECK, f"불확실한 시도 {len(uncertain)}건(보낸 뒤 응답을 기록하지 못함·전송 오류·5xx): {uncertain[:3]}", summary
    if n200 > 0:
        return USED, "HTTP 200 응답을 받음", summary
    if not sent:
        return UNUSED, "보낸 시도 없음(준비 단계에서 끝남)" + (f": {error}" if error else ""), summary
    return UNUSED, f"보낸 시도가 모두 서버 오류 응답으로 끝남(생성 시작 안 함): {errors_only[:3]}", summary


RANK = {UNUSED: 0, USED: 1, USAGE_CHECK: 2}


def _sent_count(events):
    return len({(e.get("chunk_id"), e.get("attempt")) for e in events or [] if e.get("phase") == "sending"})


def _completed_from(events):
    return {e.get("chunk_id") for e in events or [] if e.get("phase") == "http_200_received"}


def judge(journal, outcome, error=""):
    """증거 두 가지(journal 파일, 메모리 outcome)로 판정한다. 둘 다 보고 더 보수적인 쪽(usage_check > used > unused)을 쓴다.
    - journal을 읽을 수 없음 → usage_check_required
    - journal이 없음(경로가 없거나 파일이 없음): 메모리 outcome이 있고 보낸 시도 0·200 0일 때만 unused,
      그 밖에는 메모리 판정(보낸 시도가 있으면 그 판정, outcome도 없으면 usage_check_required: 증거 없음)
    - journal이 있음: journal 판정과 메모리 판정 중 보수적인 쪽. 둘이 보낸 시도·200에서 다르면 그 사실을 기록한다.
    unused는 적어도 한 증거가 확인하고 어느 증거도 반대하지 않을 때만 나온다."""
    mem = _legacy_events(outcome) if outcome is not None else None
    jev = read_journal(journal) if journal else []
    jmissing = (not journal) or (not Path(journal).exists())
    notes = []
    if jev is None:
        st, why, summ = USAGE_CHECK, "시도 기록(journal)을 읽을 수 없음", {}
        return st, why, summ, set(), notes
    if jmissing:
        if mem is None:
            return USAGE_CHECK, "증거 없음(journal도 메모리 기록도 없음)", {}, set(), notes
        st, why, summ = decide(mem, outcome, error)
        notes.append("journal 없음: 메모리 기록으로 판정")
        return st, why, summ, _completed_from(mem) | set((outcome or {}).get("completed", [])), notes
    st_j, why_j, summ_j = decide(jev, outcome, error)
    completed = _completed_from(jev) | set((outcome or {}).get("completed", []))
    if mem is None:
        return st_j, why_j, summ_j, completed, notes
    st_m, why_m, summ_m = decide(mem, outcome, error)
    completed |= _completed_from(mem)
    if _sent_count(jev) != _sent_count(mem) or _completed_from(jev) != _completed_from(mem):
        notes.append(f"journal과 메모리 기록이 다름: 보낸 시도 {_sent_count(jev)}/{_sent_count(mem)}, "
                     f"200 청크 {sorted(_completed_from(jev))}/{sorted(_completed_from(mem))}")
    if RANK[st_m] > RANK[st_j]:
        return st_m, why_m + "(메모리 기록이 더 보수적)", summ_m, completed, notes
    return st_j, why_j, summ_j, completed, notes


def finalize(path, run_id, outcome, error="", journal=None):
    """실행이 끝난 뒤(정상·중단·예외·인터럽트 모두) 부른다. 이 실행이 예약한 승인만 바꾼다. 새 상태를 돌려준다.
    journal이 있으면 그 단계 기록이 증거다(인터럽트로 outcome이 갱신되지 않아도 판단할 수 있음)."""
    with locks.approval_lock(Path(path).stem):
        rec = _load(path)
        if state_of(rec) != RESERVED or rec.get("reserved_by_run_id") != run_id:
            return state_of(rec)
        if ledger.verify_approval(path):
            return state_of(rec)  # 장부와 어긋나 있으면 바꾸지 않는다(검사가 거부한다: 닫힌 쪽)
        state, decision, summary, done, notes = judge(journal, outcome, error)
        outcome = outcome or {}
        abort = outcome.get("abort") or {}
        reason = abort.get("error_class") or (f"준비·실행 오류: {error}" if error else decision)
        summary = dict(summary, decision=decision, notes=notes)
        attempts = _attempt_rows(outcome)
        # 완료·미완료는 승인한 청크 목록과 시도 기록(200 받은 청크)으로 다시 계산한다(어디서 끊겨도 맞게)
        approved = [c["chunk_id"] for c in (rec.get("fingerprint") or {}).get("chunks", [])]
        order = approved or list(dict.fromkeys(list(outcome.get("completed", [])) + list(outcome.get("not_completed", []))))
        info = {"completed": [c for c in order if c in done] + sorted(done - set(order)),
                "not_completed": [c for c in order if c not in done]}
        if state == USAGE_CHECK:
            rec["state"] = USAGE_CHECK
            _event(rec, USAGE_CHECK, run_id, reason=f"{reason}; {decision}; {llm.USAGE_CHECK_NOTE}", attempts=attempts,
                   evidence=summary, error=error, **info)
            event = USAGE_CHECK
        elif state == USED:
            rec["state"] = USED
            rec["used_by_run_id"], rec["used_at"] = run_id, _now()
            partial = bool(abort) or bool(error) or bool(info["not_completed"])
            if partial:
                rec["partial_run"] = {"run_id": run_id, "reason": reason, **info}
            _event(rec, "used", run_id, partial=partial, reason=reason, attempts=attempts, evidence=summary, **info)
            event = USED
        else:
            rec["state"] = UNUSED
            rec.pop("reserved_by_run_id", None)
            rec.pop("reserved_at", None)
            _event(rec, "released", run_id, reason=reason, evidence=summary, attempts=attempts,
                   note="사용하지 않았음이 확실한 경우(보낸 시도 없음 또는 모두 서버 오류 응답)에만 복원")
            event = "released"
        _commit(path, rec, event, run_id)
        return rec["state"]


def recover_if_abandoned(path):
    """reserved인데 실행 잠금을 쥔 프로세스가 없으면(비정상 종료) usage_check_required로 옮긴다. unused로는 되돌리지 않는다.
    시도 기록(journal)을 증거로 요약해 남긴다. 실행 잠금을 쥔 프로세스가 살아 있으면 아무것도 하지 않는다."""
    eid = Path(path).stem
    try:
        rl = locks.run_lock(eid).acquire()
    except ExtractError:
        return False  # 다른 프로세스가 실행 중
    try:
        with locks.approval_lock(eid):
            rec = _load(path)
            if state_of(rec) != RESERVED or ledger.verify_approval(path):
                return False
            run_id = rec.get("reserved_by_run_id")
            journal = next((h.get("journal") for h in reversed(rec.get("history", []))
                            if h.get("event") == "reserved" and h.get("run_id") == run_id), None)
            events = read_journal(journal) if journal else None
            _, reason, summary = decide(events)
            rec["state"] = USAGE_CHECK
            _event(rec, USAGE_CHECK, run_id, reason="예약한 실행이 끝맺지 못함(프로세스 비정상 종료). " + reason,
                   evidence=summary, journal=journal)
            _commit(path, rec, USAGE_CHECK, run_id)
            return True
    finally:
        rl.release()


def resolve(estimate_id, approvals_dir, as_state, note):
    """usage_check_required 승인을 사람이 Console에서 확인한 뒤 used 또는 unused로 정한다."""
    if as_state not in (USED, UNUSED):
        raise ExtractError("--as는 used 또는 unused")
    if not note.strip():
        raise ExtractError("--note(확인 내용)가 필요하다")
    p = Path(approvals_dir) / f"{estimate_id}.json"
    if not p.exists():
        raise ExtractError(f"추정 기록이 없음: {disp(p)}")
    with locks.approval_lock(estimate_id):
        return _resolve_locked(p, as_state, note)


def _resolve_locked(p, as_state, note):
    rec = _load(p)
    bad = ledger.verify_approval(p)
    if bad:
        raise ExtractError("resolve 거부: 해시 장부와 다름\n- " + "\n- ".join(bad))
    if state_of(rec) != USAGE_CHECK:
        raise ExtractError(f"resolve는 {USAGE_CHECK} 상태에서만 가능(현재 {state_of(rec)})")
    run_id = rec.get("reserved_by_run_id")
    rec["state"] = as_state
    if as_state == USED:
        rec["used_by_run_id"], rec["used_at"] = run_id, _now()
    else:
        rec.pop("reserved_by_run_id", None)
        rec.pop("reserved_at", None)
    _event(rec, "resolved", run_id, resolved_as=as_state, note=note)
    _commit(p, rec, "resolved", run_id)
    return rec


def approved_limits(rec):
    """(승인 청크 수, 승인 시도 상한). 이전 형식 기록(calls만 있음)은 같은 공식으로 계산한다."""
    n = int(rec.get("approved_chunks", rec.get("calls", 0)))
    return n, int(rec.get("approved_attempts", attempt_cap(n)))


class CallBudget:
    """클라이언트 감싸기: 승인 청크 수를 넘는 새 청크와 승인 시도 상한을 넘는 API 시도를 보내기 전에 막는다."""

    def __init__(self, client, max_chunks, max_attempts=None):
        self.client = client
        self.max_chunks = int(max_chunks)
        self.max_attempts = int(attempt_cap(self.max_chunks) if max_attempts is None else max_attempts)
        self.attempts = 0
        self.chunks = []
        self.history = {}

    @property
    def calls(self):  # 이전 이름(호환): API 시도 수
        return self.attempts

    def has_retry_room(self):
        """재시도 1회를 더 해도, 아직 시작하지 않은 승인 청크의 첫 시도 몫이 남는지."""
        return self.attempts + 1 + (self.max_chunks - len(self.chunks)) <= self.max_attempts

    def precheck(self, key):
        """보내기 전 검사(sending 기록 전에 부른다): 승인 청크 수·시도 상한을 넘으면 ExtractError(보내지 않음)."""
        if key not in self.history and len(self.chunks) >= self.max_chunks:
            raise ExtractError(f"승인 청크 수 {self.max_chunks}를 넘는 청크를 막음({key})")
        if self.attempts >= self.max_attempts:
            raise ExtractError(f"승인 API 시도 상한 {self.max_attempts}를 넘는 시도를 막음({key})")

    def create(self, request, key):
        if key not in self.history and len(self.chunks) >= self.max_chunks:
            raise ExtractError(f"승인 청크 수 {self.max_chunks}를 넘는 청크를 막음({key})")
        if self.attempts >= self.max_attempts:
            raise ExtractError(f"승인 API 시도 상한 {self.max_attempts}를 넘는 시도를 막음({key})")
        if key not in self.history:
            self.chunks.append(key)
            self.history[key] = 0
        self.history[key] += 1
        self.attempts += 1
        return self.client.create(request, key)


def summary_lines(rec):
    t = rec["input_tokens"]
    c = rec["cost_usd"]
    return [
        f"추정 기록 estimate_id={rec['estimate_id']}",
        f"  공급자 {rec.get('provider')}, 모델 {rec.get('model') or '미설정'}, 등급 {rec.get('billing_tier')}, "
        f"호출 간격 {rec.get('pacing', {}).get('min_interval_s')}초",
        f"  청크 {approved_limits(rec)[0]}개, API 시도 최대 {approved_limits(rec)[1]}회 ({rec.get('attempt_cap_formula', '')})",
        f"  호출당 max_tokens {rec['max_tokens_per_call']}, 출력 상한 {rec['output_cap_tokens']}",
        f"  입력 토큰({t['method']}): {t['value']} ~ {t['high']}",
        f"  가격(USD/1M, 기준일 {rec['price']['basis_date']}): 입력 {rec['price']['usd_per_mtok_input']}, 출력 {rec['price']['usd_per_mtok_output']}",
        f"  비용 범위(USD): 입력만 {c['input_low']} ~ 최대 {c['total_max']} (출력 최대 {c['output_max']})",
        f"  실제 실행: --execute --approve {rec['estimate_id']} (예시 확정·키 설정 뒤, 입력이 바뀌면 다시 추정)",
    ]



def main(argv=None):
    import argparse
    import sys
    from imaks_kg.settings import EXTRACTION_APPROVALS
    ap = argparse.ArgumentParser(description="비용 승인 기록 관리")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("resolve", help="usage_check_required 승인을 used/unused로 정한다(Console 확인 뒤)")
    r.add_argument("estimate_id")
    r.add_argument("--as", dest="as_state", required=True, choices=[USED, UNUSED])
    r.add_argument("--note", required=True)
    r.add_argument("--approvals-dir", default=None)
    args = ap.parse_args(argv)
    try:
        rec = resolve(args.estimate_id, Path(args.approvals_dir) if args.approvals_dir else EXTRACTION_APPROVALS,
                      args.as_state, args.note)
    except ExtractError as e:
        print(f"멈춤: {e}")
        return 1
    print(f"{rec['estimate_id']}: {rec['state']}")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def _attempt_rows(outcome):
    return [{"chunk_id": a.get("chunk_id"), "attempt": a.get("attempt"), "error_class": a.get("error_class"),
             "status": a.get("status"), "phase": a.get("phase")} for a in (outcome or {}).get("attempts", [])]
