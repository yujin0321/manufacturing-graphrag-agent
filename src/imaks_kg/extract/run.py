"""C 실행 CLI. 공급자는 --provider gemini(기본) | anthropic(명시할 때만). 공급자·모델 자동 전환은 없다.

  PYTHONPATH=src .venv/Scripts/python.exe -m imaks_kg.extract.run --dry-run [--model M] [--chunk ID ...]
  PYTHONPATH=src .venv/Scripts/python.exe -m imaks_kg.extract.run --fake <가짜 응답 폴더> [--run-id ID] [--out-root DIR]
  PYTHONPATH=src .venv/Scripts/python.exe -m imaks_kg.extract.run --execute --model M --approve <estimate_id>  (실제 호출)
  PYTHONPATH=src .venv/Scripts/python.exe -m imaks_kg.extract.run --list-models   (Gemini 모델 목록 API, 생성 없음)

순서(모든 방식 공통): 해시 사슬 검사 → seed ID 목록 → 입력 선택 → 프롬프트 조립 → (dry-run이면 여기서 끝)
→ 청크마다 호출 → 원본 요청·응답 저장 → 자동 검사(validate) → B 병합(merge) → 1차 검토 CSV 생성.

--execute는 (1) examples.json이 CONFIRMED가 아니면, (2) 공급자 키가 없으면(Gemini: GEMINI_API_KEY 환경변수 또는 .env,
GOOGLE_API_KEY가 있으면 거부), (3) 모델이 정해지지 않았으면, (4) 승인이 맞지 않으면 거부한다(클라이언트·실행 폴더를 만들지 않음).
--dry-run은 호출하지 않는다. --count-tokens는 Anthropic에서만 키가 있을 때 messages.count_tokens를 부른다.
Gemini는 구현하지 않았고 글자 수 추정을 쓴다.
--min-interval-s: 호출 사이 대기(무료 등급의 분당 한도를 미리 피함). 기본은 공급자 어댑터의 상수, meta와 추정 기록에 남는다.

실행 폴더 extraction/runs/<run_id>/ (이미 있으면 거부, 덮어쓰지 않음)
- meta.json: 모델 ID, effort, betas/fallbacks, SDK 버전, 보내지 않은 생성 파라미터와 이유, 프롬프트 버전·해시,
  입력 청크 ID·해시 목록, 제외 청크와 사유, preprocess_lock 해시, 시작·끝 시각, 결과 개수
- raw/request/<청크>.json(키 없음), raw/response/<청크>.json(원본 응답 또는 실패 기록), calls.jsonl(호출 요약)
- candidates_premerge.jsonl(LLM 단독, 병합 전), rejected.csv(거부 사유)
- merged.jsonl(병합 후), merge_conflicts.csv(병합 건의 값 차이), review_round1.csv(1차 검토 양식)
"""
import argparse
import json
import math
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from rdflib import RDF

from imaks_kg.common.io_utils import write_csv, write_json, write_text
from imaks_kg.common.provenance import sha256_file, sha256_text
from imaks_kg.extract import approval, ledger, llm, llm_gemini, locks, resume
from imaks_kg.extract.common import ExtractError, disp, safe_name, seed_ids, write_jsonl_sorted
from imaks_kg.extract.guard import file_fingerprint
from imaks_kg.extract.inputs import select_chunks, verify_chain
from imaks_kg.extract.merge import CONFLICT_FIELDS, load_b_rules, merge
from imaks_kg.extract.prompt import STATUS_CONFIRMED, build_user_message, load_prompt
from imaks_kg.extract.review import write_round1
from imaks_kg.extract.schema import build_schema
from imaks_kg.extract.validate import REJECT_FIELDS, validate_response
from imaks_kg.kg.naming import IM
from imaks_kg.kg.preprocess_lock import BPaths
from imaks_kg.settings import EXTRACTION_APPROVALS, EXTRACTION_RUNS, RULES_TTL

CHARS_PER_TOKEN = 4.0  # 영어 위주 텍스트의 대략값(추정). 기호·ID가 많아 실제는 더 많을 수 있어 상한(3자/토큰)도 함께 보인다.
CHARS_PER_TOKEN_HIGH = 3.0
DEFAULT_PROVIDER = "gemini"
PROVIDERS = ("gemini", "anthropic")


def get_adapter(provider=DEFAULT_PROVIDER, model=None):
    """공급자 어댑터. 공급자를 바꾸는 것은 이 인자뿐이다(실패해도 다른 공급자·모델로 바꾸지 않음)."""
    if provider == "gemini":
        return llm_gemini.GeminiAdapter(model)
    if provider == "anthropic":
        return llm.AnthropicAdapter(model)
    raise ExtractError(f"알 수 없는 공급자: {provider} (허용: {PROVIDERS})")


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def prepare(paths: BPaths = None, prompts_dir=None, chunk_ids=None, provider=DEFAULT_PROVIDER, model=None,
            min_interval_s=None):
    """호출 직전까지(해시 사슬 → 입력 선택 → 프롬프트·요청 조립). 파일을 쓰지 않는다."""
    paths = paths or BPaths()
    adapter = get_adapter(provider, model)
    docs, lock_sha = verify_chain(paths)
    fingerprint = file_fingerprint(paths)  # 추출 때 입력 파일 해시(seed, B, lock, chunks.jsonl). 이후 단계가 대조한다
    seed = seed_ids(paths.seed_ttl)
    chunks_by_id = {c["chunk_id"]: c for c in docs["chunks"]}
    selected, excluded = select_chunks(docs["chunks"])
    chunk_filter = None
    if chunk_ids:
        sel_ids = {c["chunk_id"] for c in selected}
        why = dict(excluded)
        bad = [f"{c}({why.get(c, '청크 없음')})" for c in chunk_ids if c not in sel_ids]
        if bad:
            raise ExtractError("--chunk에 입력 청크가 아닌 것이 있음: " + ", ".join(bad))
        chunk_filter = sorted(set(chunk_ids))
        selected = [c for c in selected if c["chunk_id"] in set(chunk_ids)]
    prompt = load_prompt(seed["sensors"], seed["stations"], prompts_dir=prompts_dir, chunks_by_id=chunks_by_id)
    schema = build_schema(seed["sensors"], seed["stations"])
    rules_ttl = Path(paths.out_dir) / RULES_TTL.name
    b = load_b_rules(rules_ttl, seed)
    titles = {str(next(b["graph"].objects(d, IM.identifier))): str(next(b["graph"].objects(d, IM.title)))
              for d in b["graph"].subjects(RDF.type, IM.Document)}
    requests = []
    for c in selected:
        if c["doc_id"] not in titles:
            raise ExtractError(f"B Document에 {c['doc_id']} 제목이 없음")
        requests.append((c, adapter.build_request(prompt["system"], build_user_message(c, titles[c["doc_id"]]), schema)))
    if adapter.name == "gemini":
        bad = [adapter.outbound_problem(c, docs) for c, _ in requests]
        bad += [adapter.outbound_problem(chunks_by_id.get(x, {"chunk_id": x}), docs) + " (프롬프트 예시 출처)"
                for x in prompt["example_chunk_ids"] if adapter.outbound_problem(chunks_by_id.get(x, {"chunk_id": x}), docs)]
        bad = [b for b in bad if b]
        if bad:
            raise ExtractError("외부 전송 허용 목록 밖(보내지 않음):\n- " + "\n- ".join(bad))
    if file_fingerprint(paths) != fingerprint:
        raise ExtractError("준비 중에 입력 파일(seed·B·lock·chunks)이 바뀜: 다시 실행")
    return {"paths": paths, "docs": docs, "lock_sha256": lock_sha, "fingerprint": fingerprint, "seed": seed,
            "chunks_by_id": chunks_by_id,
            "selected": selected, "excluded": excluded, "prompt": prompt, "schema": schema, "b": b,
            "rules_ttl": rules_ttl, "requests": requests, "chunk_filter": chunk_filter, "adapter": adapter,
            "min_interval_s": float(adapter.default_min_interval_s if min_interval_s is None else min_interval_s)}


def estimate_tokens(requests, adapter=None):
    adapter = adapter or llm.ANTHROPIC
    chars = sum(adapter.request_chars(req) for _, req in requests)
    return {"chars": chars, "tokens_est": math.ceil(chars / CHARS_PER_TOKEN),
            "tokens_est_high": math.ceil(chars / CHARS_PER_TOKEN_HIGH),
            "max_output_tokens_total": adapter.max_output_tokens * len(requests)}


def meta_base(ctx, run_id, mode):
    adapter = ctx.get("adapter") or llm.ANTHROPIC
    return {
        "run_id": run_id, "mode": mode,
        **adapter.meta(),
        "min_interval_s": ctx.get("min_interval_s", 0.0),
        "auto_switch": "없음(공급자·모델·유료 등급으로 자동 전환하지 않음)",
        "generation_settings_sha256": (adapter.settings_sha((ctx.get("all_requests") or ctx["requests"])[0][1])
                                       if (ctx.get("all_requests") or ctx["requests"]) else None),
        "prompt_version": ctx["prompt"]["version"], "prompt_sha256": ctx["prompt"]["prompt_sha256"],
        "prompt_template_sha256": ctx["prompt"]["template_sha256"],
        "examples_sha256": ctx["prompt"]["examples_sha256"], "examples_status": ctx["prompt"]["examples_status"],
        "example_chunk_ids": ctx["prompt"]["example_chunk_ids"],
        "schema_sha256": llm_schema_sha(ctx["schema"]),
        "preprocess_lock": disp(ctx["paths"].lock_file), "preprocess_lock_sha256": ctx["lock_sha256"],
        "input_fingerprint": ctx["fingerprint"],
        "b_rules_ttl": disp(ctx["rules_ttl"]),
        "chunk_filter": ctx.get("chunk_filter"),
        "retry_policy": {k: v for k, v in llm.retry_policy().items() if not k.startswith("sdk_")},
        "input_chunks": [{"chunk_id": c["chunk_id"], "text_sha256": c["text_sha256"],
                          "source_file_sha256": c["source_file_sha256"]} for c in ctx["selected"]],
        "excluded_chunks": [{"chunk_id": cid, "reason": why} for cid, why in ctx["excluded"]],
    }


def llm_schema_sha(schema):
    return sha256_text(json.dumps(schema, ensure_ascii=False, sort_keys=True))


def run_calls(ctx, client, run_dir: Path, run_id: str, mode: str, max_calls=None, approval_id=None,
              sleep=None, on_first_call=None, outcome=None, max_chunks=None, max_attempts=None,
              clock=None):
    """호출 → 저장 → 검사 → 병합 → 1차 검토 양식. 실행 폴더가 이미 있으면 거부.
    - max_chunks(승인 청크 수)·max_attempts(승인 API 시도 상한)가 있으면 CallBudget이 둘 다 막는다. 부를 청크 수가
      승인 청크 수보다 많으면 시작하지 않는다(max_calls는 이전 이름 = max_chunks).
    - ctx["reused"](resume.collect)가 있으면 그 청크는 부르지 않고 이전 성공 응답을 쓴다(원본 파일 복사·출처 기록).
    - 호출은 llm.call_with_policy(오류 분류·제한된 재시도)로 한다. 치명 오류·재시도 소진·AMBIGUOUS가 나오면
      그 자리에서 실행 전체를 중단하고(뒤 청크는 부르지 않음) 병합·검토 양식을 만들지 않는다.
    - Gemini 경로는 보내기 직전에 외부 전송 허용 목록(SOP만)을 다시 확인한다.
    - on_first_call: 첫 API 호출 직전에 부른다(승인 예약). outcome: 진행 상황을 채울 dict(호출자가 승인 정리에 쓴다)."""
    run_dir = Path(run_dir)
    outcome = outcome if outcome is not None else {}
    outcome.update({"aborted": False, "abort": None, "http_200": 0, "completed": [], "not_completed": [],
                    "attempts": []})
    if run_dir.exists():
        raise ExtractError(f"실행 폴더가 이미 있음(덮어쓰지 않음): {disp(run_dir)}")
    max_chunks = max_chunks if max_chunks is not None else max_calls
    budget_client = None
    if max_chunks is not None:
        if len(ctx["requests"]) > int(max_chunks):
            raise ExtractError(f"부를 청크 수 {len(ctx['requests'])}가 승인 청크 수 {max_chunks}를 넘음(시작 안 함)")
        budget_client = approval.CallBudget(client, max_chunks, max_attempts)
        client = budget_client
    reused = ctx.get("reused") or {}
    order = ctx.get("all_requests") or ctx["requests"]
    adapter = ctx.get("adapter") or llm.ANTHROPIC
    meta = meta_base(ctx, run_id, mode)
    meta["approval_id"] = approval_id
    meta["max_calls"] = max_chunks
    meta["approved_chunks"] = max_chunks
    meta["approved_attempts"] = budget_client.max_attempts if budget_client else None
    if adapter.name == "gemini":
        meta["outbound_allowlist"] = llm_gemini.outbound_allowlist()
    meta["started_at"] = _now()
    write_json(run_dir / "meta.json", meta)  # 시작 기록(끝에서 다시 씀)
    calls, cands, rejects = [], [], []
    seed = ctx["seed"]
    sensor_set, station_set = set(seed["sensors"]), set(seed["stations"])
    budget = llm.RetryBudget()
    interval = float(ctx.get("min_interval_s", 0.0))
    sleep = sleep or time.sleep  # 실행할 때 찾는다(테스트가 time.sleep을 바꿀 수 있게)
    pacer = llm.Pacer(interval, sleep, clock or time.monotonic)  # 실행당 하나: 청크 사이와 재시도 모두 마지막 시도 시작 기준
    journal_path = run_dir / "attempts.jsonl"

    def journal(entry):  # 시도 단계 기록(덧붙이기 + flush + fsync). 승인 정리의 증거가 된다
        with open(journal_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(dict(entry, time=_now()), ensure_ascii=False, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
    to_call = [c["chunk_id"] for c, _ in order if c["chunk_id"] not in reused]
    outcome["not_completed"] = list(to_call)  # 청크가 끝날 때마다 갱신(어디서 끊겨도 맞게. 승인 정리는 journal로 다시 계산)
    saved_raw = set()

    def save_raw(key, attempt, raw):  # HTTP 200 본문을 해석 전에 저장하고 경로·해시를 journal에 남긴다
        rel = f"raw/response/{safe_name(key)}.json"
        write_json(run_dir / rel, raw)
        saved_raw.add(key)
        journal({"chunk_id": key, "attempt": attempt, "phase": "raw_saved", "file": rel,
                 "sha256": sha256_file(run_dir / rel)})
    chunk_attempts, reused_from, n_called = {}, {}, 0
    for chunk, req in order:
        cid = chunk["chunk_id"]
        name = safe_name(cid)
        if cid in reused:  # 이전 실행의 성공 응답 재사용(API 호출 없음)
            src = reused[cid]
            dst = run_dir / "raw" / "response" / f"{name}.json"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src["raw_path"], dst)
            reused_from[cid] = dict(src["source"], copied_to=f"raw/response/{name}.json",
                                    copied_sha256=sha256_file(dst))
            res = src["result"]
            calls.append(dict(src["summary"], reused_from=src["source"]["run_id"]))
        else:
            why = adapter.outbound_problem(chunk, ctx["docs"])
            if why:
                raise ExtractError(f"외부 전송 허용 목록 밖(보내지 않음): {why}")
            if n_called == 0 and on_first_call is not None:
                on_first_call()
            n_called += 1
            write_json(run_dir / "raw" / "request" / f"{name}.json", req)
            res = llm.call_with_policy(client, req, cid, budget, sleep, adapter=adapter, journal=journal, pacer=pacer,
                                       save_raw=save_raw)
            outcome["attempts"] += res.attempts
            chunk_attempts[cid] = res.attempts
            if res.http_200:
                outcome["http_200"] += 1
                outcome["completed"].append(cid)
                if cid in outcome["not_completed"]:
                    outcome["not_completed"].remove(cid)
            if cid not in saved_raw:  # 200 본문은 save_raw가 이미 저장했다(같은 내용을 다시 쓰지 않음)
                write_json(run_dir / "raw" / "response" / f"{name}.json",
                           res.raw if res.raw else {"call_failed": res.failure, "request_id": res.request_id,
                                                    "error": res.error, "attempts": res.attempts})
            calls.append(res.summary())
        c_ok, c_rej = validate_response(res, chunk, ctx["docs"], sensor_set, station_set)
        cands += c_ok
        rejects += c_rej
        if res.abort:
            outcome["aborted"] = True
            outcome["abort"] = {"chunk_id": cid, "error_class": res.error_class, "error": res.error}
            outcome["not_completed"] = to_call[to_call.index(cid):]
            break
    meta["retries"] = budget.log
    meta["pacing_waits_s"] = pacer.waits
    meta["reused_from"] = reused_from
    meta["actual_chunks"] = n_called
    meta["actual_attempts"] = sum(len(v) for v in chunk_attempts.values())
    meta["chunk_attempts"] = chunk_attempts
    meta["outcome"] = {k: outcome[k] for k in ("aborted", "abort", "http_200", "completed", "not_completed")}
    if any(a.get("error_class") == llm.AMBIGUOUS for a in outcome["attempts"]):
        meta["usage_check"] = llm.USAGE_CHECK_NOTE
    write_text(run_dir / "calls.jsonl", write_jsonl_sorted(calls))
    write_text(run_dir / "candidates_premerge.jsonl", write_jsonl_sorted(cands))
    write_csv(run_dir / "rejected.csv", REJECT_FIELDS, [[r[k] for k in REJECT_FIELDS] for r in rejects])
    counts = {"calls": len(calls), "calls_failed": sum(1 for c in calls if not c["ok"]),
              "fallback_served": sum(1 for c in calls if c["fallback_used"]),
              "candidates": len(cands), "rejected": len(rejects), "retries": len(budget.log),
              "reused": len(reused_from), "api_chunks": n_called}
    if outcome["aborted"]:
        meta["finished_at"] = _now()
        meta["status"] = "aborted"
        meta["counts"] = counts
        write_json(run_dir / "meta.json", meta)
        ledger.record_run(run_dir, run_id, "run_finished", ["meta.json", "calls.jsonl", "candidates_premerge.jsonl", "rejected.csv", ledger.RAW_BUNDLE])
        return {"run_dir": run_dir, "meta": meta, "records": [], "conflicts": [], "rejects": rejects,
                "aborted": True, "outcome": outcome}
    records, conflicts = merge(cands, ctx["b"], ctx["chunks_by_id"])
    checks = resume.combination_checks(records)
    meta["combination_checks"] = checks
    if reused and not checks["ok"]:
        meta["finished_at"] = _now()
        meta["status"] = "combination_check_failed"
        meta["counts"] = counts
        write_json(run_dir / "meta.json", meta)
        raise ExtractError(f"여러 실행을 합친 결과 검사 실패(병합·검토 양식 안 만듦): {checks}")
    write_text(run_dir / "merged.jsonl", write_jsonl_sorted(records))
    write_csv(run_dir / "merge_conflicts.csv", CONFLICT_FIELDS, [[c[k] for k in CONFLICT_FIELDS] for c in conflicts])
    write_round1(run_dir, records, conflicts, ctx["paths"])
    meta["finished_at"] = _now()
    meta["status"] = "completed"
    counts.update({"merged_into_b": sum(1 for r in records if r["merge"]["merged"]),
                   "new_rules": sum(1 for r in records if not r["merge"]["merged"]), "merge_conflicts": len(conflicts)})
    meta["counts"] = counts
    write_json(run_dir / "meta.json", meta)
    ledger.record_run(run_dir, run_id, "run_finished", ["meta.json", "calls.jsonl", "candidates_premerge.jsonl", "rejected.csv", ledger.RAW_BUNDLE])
    ledger.record_run(run_dir, run_id, "merge_finished", ["merged.jsonl", "merge_conflicts.csv"])
    return {"run_dir": run_dir, "meta": meta, "records": records, "conflicts": conflicts, "rejects": rejects,
            "aborted": False, "outcome": outcome}


def refuse_execute_reason(prompt, adapter=None):
    if prompt["examples_status"] != STATUS_CONFIRMED:
        return (f"실제 실행 거부: examples.json confirmationStatus가 {prompt['examples_status']!r}이다. "
                "사람이 예시를 확인하고 CONFIRMED로 바꾼 뒤 실행한다.")
    adapter = adapter or llm.ANTHROPIC
    problem = adapter.model_problem() or adapter.key_problem()  # 키 값은 보지 않고 있음·없음만
    if problem:
        return f"실제 실행 거부: {problem}"
    return ""


def print_plan(ctx, est, counted=None):
    ad = ctx.get("adapter") or llm.ANTHROPIC
    print(f"공급자 {ad.name}, 모델 {ad.model_id or '미설정'}, 등급 {ad.billing_tier}, 호출 간격 {ctx.get('min_interval_s', 0.0)}초")
    print(f"입력 청크(호출 수): {len(ctx['requests'])}")
    print(f"제외 청크: {len(ctx['excluded'])}")
    for cid, why in ctx["excluded"]:
        print(f"  - {cid}: {why}")
    print(f"프롬프트 {ctx['prompt']['version']} sha256={ctx['prompt']['prompt_sha256']} 예시 상태={ctx['prompt']['examples_status']}")
    print(f"입력 글자 수 합계: {est['chars']}")
    print(f"입력 토큰 추정: 약 {est['tokens_est']} (글자/{CHARS_PER_TOKEN:g}), 상한 추정 {est['tokens_est_high']} (글자/{CHARS_PER_TOKEN_HIGH:g})")
    if counted is not None:
        print(f"입력 토큰(count_tokens, 구조화 출력 스키마 제외): {counted}")
    print(f"출력 토큰 상한(max_tokens x 호출 수): {est['max_output_tokens_total']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="C: SOP 규칙 LLM 추출")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="호출 없이 호출 수·토큰 추정·제외 목록 출력")
    mode.add_argument("--fake", metavar="DIR", help="가짜 응답 폴더를 재생")
    mode.add_argument("--execute", action="store_true", help="실제 호출(예시 확정 + API 키 + 비용 승인 필요)")
    mode.add_argument("--list-models", action="store_true", help="Gemini 모델 목록(API 호출, 생성 없음)")
    ap.add_argument("--provider", default=DEFAULT_PROVIDER, choices=PROVIDERS)
    ap.add_argument("--model", default=None, help="모델 ID(기본: 공급자 상수, Gemini는 사용자가 정한 gemini-3.8-flash. 자동 전환 없음)")
    ap.add_argument("--min-interval-s", type=float, default=None, help="호출 사이 대기 초(기본: 공급자 상수)")
    ap.add_argument("--count-tokens", action="store_true", help="dry-run에서 키가 있으면 count_tokens API로 셈")
    ap.add_argument("--approve", default=None, metavar="ESTIMATE_ID", help="--execute에 필요한 비용 승인 ID(--dry-run이 만듦)")
    ap.add_argument("--approvals-dir", default=None, help=f"추정 기록 폴더(기본 {disp(EXTRACTION_APPROVALS)})")
    ap.add_argument("--chunk", action="append", default=None, metavar="CHUNK_ID",
                    help="이 청크만(여러 번 줄 수 있음). dry-run·execute 모두. 추정·승인·호출 상한이 이 청크 묶음 기준")
    ap.add_argument("--resume-from", action="append", default=None, metavar="RUN_ID",
                    help="이전 실행의 성공 응답을 재사용하고 남은 청크만 부른다(여러 번 가능). dry-run도 남은 청크만 추정")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--out-root", default=None, help=f"실행 폴더의 상위(기본 {disp(EXTRACTION_RUNS)})")
    args = ap.parse_args(argv)
    if args.list_models:
        if args.provider != "gemini":
            print("--list-models는 Gemini만")
            return 2
        try:
            for m in llm_gemini.GeminiClient().list_models():
                print(json.dumps(m, ensure_ascii=False, default=str))
        except ExtractError as e:
            print(f"멈춤: {e}")
            return 1
        return 0
    try:
        ctx = prepare(chunk_ids=args.chunk, provider=args.provider, model=args.model,
                      min_interval_s=args.min_interval_s)
    except ExtractError as e:
        print(f"멈춤: {e}")
        return 1
    adapter = ctx.get("adapter") or llm.ANTHROPIC
    out_root = Path(args.out_root) if args.out_root else EXTRACTION_RUNS
    if args.resume_from:
        try:
            reused = resume.collect([out_root / r for r in args.resume_from], ctx)
        except ExtractError as e:
            print(f"멈춤: {e}")
            return 2
        ctx = resume.restrict(ctx, reused)
        print(f"재사용 {len(reused)}개(이전 실행 {', '.join(args.resume_from)}), 남은 청크 {len(ctx['requests'])}개")
    est = estimate_tokens(ctx["requests"], adapter)
    approvals_dir = Path(args.approvals_dir) if args.approvals_dir else EXTRACTION_APPROVALS
    if args.dry_run:
        counted = None
        if args.count_tokens:
            if not adapter.supports_count_tokens:
                print(f"--count-tokens: {adapter.name}에서는 구현하지 않음(글자 수 추정을 씀)")
            elif not adapter.key_problem():
                client = adapter.make_client()
                counted = sum(client.count_tokens(req) for _, req in ctx["requests"])
        print_plan(ctx, est, counted)
        rec = approval.build_estimate(ctx, est, counted)
        try:
            path = approval.write_estimate(rec, approvals_dir)
            print(f"추정 기록: {disp(path)}")
        except ExtractError as e:
            print(f"추정 기록: {e}")
        for line in approval.summary_lines(rec):
            print(line)
        return 0
    mode_name = "execute" if args.execute else "fake"
    run_id = args.run_id or (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{mode_name}")
    max_calls, max_attempts, approval_id, run_lock = None, None, None, None
    if args.execute:
        why = refuse_execute_reason(ctx["prompt"], adapter)
        if why:
            print(why)
            return 2
        try:
            rec, rec_path = approval.check_approval(args.approve, approvals_dir, ctx)
        except ExtractError as e:
            print(e)
            return 2
        if (out_root / run_id).exists():
            print(f"실제 실행 거부: 실행 폴더가 이미 있음: {disp(out_root / run_id)}")
            return 2
        (max_calls, max_attempts), approval_id = approval.approved_limits(rec), rec["estimate_id"]
        try:  # 실행 내내 쥐는 실행 잠금(같은 승인을 쓰는 다른 프로세스를 막고, 비정상 종료를 알아보는 데 쓴다)
            run_lock = locks.run_lock(approval_id).acquire()
        except ExtractError as e:
            print(f"실제 실행 거부: {e}")
            return 2
        print(f"승인 {approval_id}: 청크 {max_calls}개, API 시도 최대 {max_attempts}회")
        try:
            client = adapter.make_client() if adapter.name != "anthropic" else llm.AnthropicClient()
        except BaseException as e:
            run_lock.release()
            if not isinstance(e, ExtractError):
                raise
            print(f"실제 실행 거부: {e}")
            return 2
        journal_path = out_root / run_id / "attempts.jsonl"
        reserve = lambda: approval.reserve(rec_path, run_id, journal=journal_path)  # noqa: E731  첫 API 호출 직전 예약
    else:
        client = adapter.make_fake_client(args.fake)
        rec_path, reserve = None, None
    outcome, err, interrupted = {}, "", None
    try:
        res = run_calls(ctx, client, out_root / run_id, run_id, mode_name, max_chunks=max_calls,
                        max_attempts=max_attempts, approval_id=approval_id, on_first_call=reserve, outcome=outcome)
    except ExtractError as e:
        err = str(e)
        res = None
    except BaseException as e:  # KeyboardInterrupt, SystemExit 등: 보수적으로 정리한 뒤 다시 던진다
        err = f"{type(e).__name__}(중단)"
        res = None
        interrupted = e
    finally:
        if rec_path is not None:
            try:
                state = approval.finalize(rec_path, run_id, outcome, err, journal=out_root / run_id / "attempts.jsonl")
                print(f"승인 {approval_id} 상태: {state}")
            finally:
                if run_lock is not None:
                    run_lock.release()
    if interrupted is not None:
        raise interrupted
    if res is None:
        print(f"멈춤: {err}")
        return 1
    if res["aborted"]:
        ab = res["outcome"]["abort"]
        print(f"실행 중단: {ab['error_class']} (청크 {ab['chunk_id']}, 상태 {ab['error'].get('status')}); "
              f"완료 {len(res['outcome']['completed'])}, 미완료 {len(res['outcome']['not_completed'])}")
        if res["meta"].get("usage_check"):
            print(res["meta"]["usage_check"])
        print(f"실행 폴더: {disp(res['run_dir'])}")
        return 3
    print(f"실행 폴더: {disp(res['run_dir'])}")
    print("결과:", json.dumps(res["meta"]["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
