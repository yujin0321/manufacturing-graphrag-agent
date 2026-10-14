"""중단된 실행 이어서 하기(--resume-from <run_id>, 여러 번 가능). 2026-10-13 사용자 지시.

이전 실행의 성공 응답(HTTP 200, 정상 종료, JSON 파싱 성공, 그 청크에 거부 행 없음)만 재사용하고 남은 청크만 부른다.
재사용 조건(하나라도 다르면 그 실행의 재사용을 거부하고 차이를 적어 멈춘다):
- 공급자, 모델 ID. 응답의 served model은 요청 모델과 정확히 같거나 요청 모델 + 숫자 버전 접미사(-NNN)만 허용
  (정규식 ^<모델>(-숫자3자리)?$, 2차 검증 FAIL 수정: -lite·-pro·-preview·-8b 같은 다른 모델 접미사는 거부). 두 공급자 공통.
  또 원본 응답에서 다시 읽은 served model이 원래 실행의 calls.jsonl에 기록된 served model과 같아야 하고,
  재사용하는 응답들(여러 실행 포함)의 served model이 모두 같아야 한다.
- 생성 설정 해시(generation_settings_sha256: 요청에서 사용자 메시지만 뺀 것. temperature·seed·max tokens·보낸 스키마 포함)
- 프롬프트 해시, 예시 해시
- 입력 지문 전체(seed, B, lock, chunks.jsonl)와 재사용하는 각 청크의 text_sha256
같은 청크의 성공 응답이 여러 실행에 있으면 멈춘다(청크마다 출처는 하나).
재사용 응답은 원래 run_id·request_id·원본 응답 파일 경로를 출처로 남기고, 새 실행 폴더로 복사해 해시를 기록한다.
"""
import json
import re
from pathlib import Path

from imaks_kg.common.provenance import sha256_file
from imaks_kg.extract.common import ExtractError, disp, read_jsonl, safe_name


def _meta(run_dir):
    p = Path(run_dir) / "meta.json"
    if not p.exists():
        raise ExtractError(f"재사용 거부: 실행 기록이 없음: {disp(p)}")
    return json.loads(p.read_text(encoding="utf-8"))


def current_signature(ctx):
    adapter = ctx["adapter"]
    reqs = ctx.get("all_requests") or ctx["requests"]
    return {
        "provider": adapter.name,
        "model": adapter.model_id,
        "generation_settings_sha256": adapter.settings_sha(reqs[0][1]) if reqs else None,
        "prompt_sha256": ctx["prompt"]["prompt_sha256"],
        "examples_sha256": ctx["prompt"]["examples_sha256"],
        "input_fingerprint": ctx["fingerprint"],
    }


def _served_ok(served, model):
    """served model이 요청 모델과 정확히 같거나 요청 모델 + 숫자 3자리 버전 접미사(예: -001)일 때만 참."""
    if not served or not model:
        return False
    return re.fullmatch(rf"{re.escape(model)}(-\d{{3}})?", served) is not None


def collect(prev_dirs, ctx):
    """{chunk_id: {"result": CallResult, "summary": 이전 호출 요약, "source": 출처}}. 문제가 있으면 ExtractError."""
    adapter = ctx["adapter"]
    cur = current_signature(ctx)
    cur_chunks = {c["chunk_id"]: c for c, _ in (ctx.get("all_requests") or ctx["requests"])}
    reused, owner, served_seen = {}, {}, {}
    from imaks_kg.extract import ledger
    for d in prev_dirs:
        d = Path(d)
        meta = _meta(d)
        ledger.verify_run(d, f"재사용({meta.get('run_id', d.name)})")
        rid = meta.get("run_id", d.name)
        diffs = []
        old = {"provider": meta.get("provider", "anthropic"), "model": meta.get("model"),
               "generation_settings_sha256": meta.get("generation_settings_sha256"),
               "prompt_sha256": meta.get("prompt_sha256"), "examples_sha256": meta.get("examples_sha256"),
               "input_fingerprint": meta.get("input_fingerprint")}
        for k, v in cur.items():
            if old[k] != v:
                diffs.append(f"{k}: 이전 {old[k] if k != 'input_fingerprint' else '(지문)'} / 현재 "
                             f"{v if k != 'input_fingerprint' else '(지문)'}")
        if diffs:  # 실행 단위 조건이 다르면 응답을 열어 보지 않고 거부
            raise ExtractError(f"재사용 거부({rid}): 조건이 다름\n- " + "\n- ".join(diffs))
        prev_hash = {c["chunk_id"]: c["text_sha256"] for c in meta.get("input_chunks", [])}
        calls = read_jsonl(d / "calls.jsonl") if (d / "calls.jsonl").exists() else []
        rejected = set()
        if (d / "rejected.csv").exists():
            from imaks_kg.common.io_utils import read_csv_rows
            _, rows = read_csv_rows(d / "rejected.csv")
            rejected = {r["chunk_id"] for r in rows}
        found = {}
        for c in calls:
            cid = c["key"]
            if not c.get("ok") or cid in rejected or cid not in cur_chunks:
                continue  # 실패(거절·MAX_TOKENS·파싱 실패·거부 행)는 재사용하지 않는다
            if prev_hash.get(cid) != cur_chunks[cid]["text_sha256"]:
                diffs.append(f"청크 {cid} text_sha256: 이전 {prev_hash.get(cid)} / 현재 {cur_chunks[cid]['text_sha256']}")
                continue
            raw_p = d / "raw" / "response" / f"{safe_name(cid)}.json"
            if not raw_p.exists():
                diffs.append(f"청크 {cid}: 원본 응답 파일 없음")
                continue
            res = adapter.interpret(cid, adapter.parse_raw(json.loads(raw_p.read_text(encoding="utf-8"))))
            if not res.ok:
                continue
            res.request_id = c.get("request_id", res.request_id) or res.request_id
            if not _served_ok(res.served_model, cur["model"]):
                diffs.append(f"청크 {cid} served model: {res.served_model} / 요청 모델 {cur['model']} "
                             "(정확히 같거나 -NNN 버전 접미사만 허용)")
                continue
            recorded = c.get("served_model") or ""
            if res.served_model != recorded:
                diffs.append(f"청크 {cid} served model: 원본 응답 {res.served_model} / 원래 실행 기록 {recorded}")
                continue
            found[cid] = {"result": res, "summary": c,
                          "source": {"run_id": rid, "request_id": res.request_id, "raw_path": disp(raw_p),
                                     "raw_sha256": sha256_file(raw_p)}, "raw_path": raw_p}
        if diffs:
            raise ExtractError(f"재사용 거부({rid}): 조건이 다름\n- " + "\n- ".join(diffs))
        for cid, v in found.items():
            if cid in owner:
                raise ExtractError(f"재사용 중단: 청크 {cid}의 성공 응답이 여러 실행에 있음({owner[cid]}, {rid}). "
                                   "청크마다 출처는 하나여야 한다")
            owner[cid] = rid
            reused[cid] = v
            served_seen.setdefault(v["result"].served_model, []).append(f"{rid}:{cid}")
    if len(served_seen) > 1:
        raise ExtractError("재사용 거부: 재사용할 응답들의 served model이 서로 다름: "
                           + "; ".join(f"{k} ← {', '.join(v[:3])}" for k, v in sorted(served_seen.items())))
    return reused


def restrict(ctx, reused):
    """재사용한 청크를 뺀 요청만 부르도록 ctx를 바꾼 사본. 추정·승인·호출 상한은 남은 청크 기준이다."""
    all_reqs = ctx.get("all_requests") or ctx["requests"]
    return dict(ctx, all_requests=all_reqs, requests=[(c, r) for c, r in all_reqs if c["chunk_id"] not in reused],
                reused=reused)


def combination_checks(records):
    """병합 뒤 검사: 식별자 중복, (청크, 인용 위치) 중복, 서로 다른 청크의 새 규칙이 같은 정규화 ruleIdInText를 가짐."""
    from imaks_kg.extract.merge import norm_id
    ids, locs, by_norm = {}, {}, {}
    dup_ids, dup_locs, dup_norm = [], [], []
    for r in records:
        if not r["merge"]["merged"]:
            if r["identifier"] in ids:
                dup_ids.append(r["identifier"])
            ids[r["identifier"]] = r["candidate_id"]
            if r.get("ruleIdInText"):
                by_norm.setdefault(norm_id(r["ruleIdInText"]), set()).add(r["chunk_id"])
        p = r["provenance"]
        loc = (r["chunk_id"], p["offset_in_chunk"], len(r["sourceQuote"]))
        if loc in locs:
            dup_locs.append(f"{loc[0]}@{loc[1]}+{loc[2]}")
        locs[loc] = r["candidate_id"]
    dup_norm = sorted(k for k, v in by_norm.items() if len(v) > 1)
    return {"duplicate_identifiers": sorted(dup_ids), "duplicate_quote_locations": sorted(dup_locs),
            "normalized_rule_id_in_multiple_chunks": dup_norm,
            "ok": not (dup_ids or dup_locs or dup_norm)}
