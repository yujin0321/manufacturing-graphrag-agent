"""검토·입력 무결성 검사(사용자 보완 요청 2026-10-12).

1. 입력 지문(input_fingerprint): 추출 때(run.prepare) seed.ttl, rules_deterministic.ttl, preprocess_lock.json,
   chunks.jsonl의 SHA-256을 meta.json에 남긴다(입력 청크별 text_sha256, 프롬프트 해시는 meta에 따로 있음).
   1차 양식 생성·2차 생성·apply·to_rdf 때 check_inputs가 (a) B의 해시 사슬 검사(check_chain)와 청크 단위 검사,
   (b) 현재 파일 해시 == meta, (c) 현재 입력 청크의 text_sha256과 SHA-256(text) == meta 를 확인하고,
   하나라도 다르면 어떤 입력이 달라졌는지 적어 ExtractError로 멈춘다(출력 전에).
2. 검토 기록
   - review_manifest.json: write_round1이 merged.jsonl·merge_conflicts.csv 해시와 1차 양식 해시를,
     make_round2가 그때의 1차 파일 해시(1차 확정)와 2차 양식 해시를 남긴다.
   - review_applied.json: apply가 final·merged·1차·2차 해시, 개수, 결정 집계를 남긴다.
   - verify_review_record(to_rdf 전): 기록 존재, 해시 재계산 일치, 2차 유무 일치, 개수·결정 집계가 final.jsonl과 일치,
     1차·2차 CSV에서 결정을 다시 계산한 결과가 final.jsonl의 후보·결정과 일치하는지 확인한다.
"""
import json
from pathlib import Path

from imaks_kg.common.provenance import sha256_file, sha256_text
from imaks_kg.extract.common import ExtractError, disp, read_jsonl
from imaks_kg.kg.preprocess_lock import BPaths, check_chain
from imaks_kg.settings import RULES_TTL

MANIFEST = "review_manifest.json"
APPLIED = "review_applied.json"
FP_LABELS = {
    "seed_ttl": "kg_build/seed.ttl",
    "rules_deterministic_ttl": "kg_build/rules_deterministic.ttl(B 산출물)",
    "preprocess_lock": "harness/preprocess_lock.json",
    "chunks_jsonl": "preprocessed/documents/chunks.jsonl",
}


def _fp_paths(paths: BPaths):
    return {"seed_ttl": Path(paths.seed_ttl), "rules_deterministic_ttl": Path(paths.out_dir) / RULES_TTL.name,
            "preprocess_lock": Path(paths.lock_file), "chunks_jsonl": Path(paths.doc_dir) / "chunks.jsonl"}


def file_fingerprint(paths: BPaths = None) -> dict:
    paths = paths or BPaths()
    out = {}
    for k, p in _fp_paths(paths).items():
        out[k] = {"path": disp(p), "sha256": sha256_file(p) if p.exists() else None}
    return out


def _sha_or_none(p):
    p = Path(p)
    return sha256_file(p) if p.exists() else None


def check_inputs(run_dir, paths: BPaths = None, stage: str = ""):
    """현재 입력이 추출 때(meta.json)와 같은지. 다르면 ExtractError(무엇이 다른지 포함)."""
    from imaks_kg.extract.inputs import chunk_errors, load_documents
    paths = paths or BPaths()
    meta = json.loads((Path(run_dir) / "meta.json").read_text(encoding="utf-8"))
    fp = meta.get("input_fingerprint")
    if not fp:
        raise ExtractError(f"{stage} 중단: meta.json에 입력 지문(input_fingerprint)이 없음")
    errors = [f"해시 사슬: {e}" for e in check_chain(paths)]
    for k, p in _fp_paths(paths).items():
        old, new = fp.get(k, {}).get("sha256"), _sha_or_none(p)
        if old != new:
            errors.append(f"{FP_LABELS[k]}가 추출 때와 다름: 추출 때 {old} / 현재 {new}")
    if not errors:
        docs = load_documents(paths)
        lock = json.loads(Path(paths.lock_file).read_text(encoding="utf-8"))
        errors += [f"청크 검사: {e}" for e in chunk_errors(docs, lock.get("input_pdfs", {}))]
        cur = {c["chunk_id"]: c for c in docs["chunks"]}
        for c in meta.get("input_chunks", []):
            now = cur.get(c["chunk_id"])
            if now is None:
                errors.append(f"입력 청크 {c['chunk_id']}가 현재 chunks.jsonl에 없음")
            elif now["text_sha256"] != c["text_sha256"] or sha256_text(now["text"]) != c["text_sha256"]:
                errors.append(f"입력 청크 {c['chunk_id']} 해시가 추출 때와 다름: 추출 때 {c['text_sha256']} / "
                              f"현재 기록 {now['text_sha256']} / 현재 텍스트 {sha256_text(now['text'])}")
    if errors:
        raise ExtractError(f"{stage} 중단(출력 안 씀): 입력이 추출 때와 다름\n- " + "\n- ".join(errors))
    return meta


def load_current(paths: BPaths = None):
    """check_inputs를 통과한 뒤에만 부른다. 현재 파일에서 문서·seed·B 규칙을 새로 읽는다."""
    from imaks_kg.extract.common import seed_ids
    from imaks_kg.extract.inputs import verify_chain
    from imaks_kg.extract.merge import load_b_rules
    paths = paths or BPaths()
    docs, _ = verify_chain(paths)
    seed = seed_ids(paths.seed_ttl)
    return {"paths": paths, "docs": docs, "seed": seed, "chunks_by_id": {c["chunk_id"]: c for c in docs["chunks"]},
            "b": load_b_rules(Path(paths.out_dir) / RULES_TTL.name, seed)}


# ---------------------------------------------------------------- 검토 기록

def read_manifest(run_dir):
    p = Path(run_dir) / MANIFEST
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def write_manifest(run_dir, manifest):
    from imaks_kg.common.io_utils import write_json
    write_json(Path(run_dir) / MANIFEST, manifest)


def _cmp(errors, label, recorded, path):
    cur = _sha_or_none(path)
    if recorded != cur:
        errors.append(f"{label}이(가) 기록 이후 바뀜: 기록 {recorded} / 현재 {cur}")


def fingerprint_sha256(fp) -> str:
    """meta.json input_fingerprint의 정규화 JSON 해시(manifest가 이 실행·입력에 묶여 있는지 확인용)."""
    return sha256_text(json.dumps(fp, ensure_ascii=False, sort_keys=True))


def manifest_binding(run_dir) -> dict:
    meta = json.loads((Path(run_dir) / "meta.json").read_text(encoding="utf-8"))
    return {"run_id": meta["run_id"], "input_fingerprint_sha256": fingerprint_sha256(meta.get("input_fingerprint"))}


def check_manifest(run_dir, stage, require_round2=False):
    """review_manifest.json의 모든 해시를 현재 파일·다시 만든 양식과 대조한다. 다르면 ExtractError(항목과 두 값).
    - 묶음: run_id, input_fingerprint 해시 == meta.json
    - round1: merged.jsonl·merge_conflicts.csv 해시 == 현재, 양식 해시 == 현재 merged·conflicts로 다시 만든 1차 양식
    - round2(있거나 require_round2): 1차 확정 해시 == 현재 review_round1.csv, 양식 해시 == 현재 1차로 다시 만든 2차 양식,
      현재 2차 파일의 고정 열(final_* 밖) == 다시 만든 양식"""
    from imaks_kg.extract import review
    run_dir = Path(run_dir)
    man = read_manifest(run_dir)
    if "round1" not in man:
        raise ExtractError(f"{stage} 중단: {MANIFEST}에 1차 양식 기록이 없음")
    errors = []
    bind = manifest_binding(run_dir)
    for k, v in bind.items():
        if man.get(k) != v:
            errors.append(f"{MANIFEST}의 {k}가 meta.json과 다름: manifest {man.get(k)} / meta {v}")
    r1 = man["round1"]
    _cmp(errors, "merged.jsonl(1차 양식 생성 때)", r1.get("merged_jsonl_sha256"), run_dir / "merged.jsonl")
    _cmp(errors, "merge_conflicts.csv(1차 양식 생성 때)", r1.get("merge_conflicts_sha256"), run_dir / "merge_conflicts.csv")
    try:
        records = read_jsonl(run_dir / "merged.jsonl")
        conflicts = review.read_conflicts(run_dir)
        tpl1 = sha256_text(review.csv_text(review.ROUND1_FIELDS, review.round1_rows(records, conflicts)))
    except (OSError, KeyError, ValueError) as e:
        tpl1 = f"(다시 만들 수 없음: {type(e).__name__})"
    if tpl1 != r1.get("template_sha256"):
        errors.append(f"1차 양식 해시가 다름: manifest {r1.get('template_sha256')} / 현재 merged·conflicts로 다시 만든 양식 {tpl1}")
    if require_round2 and "round2" not in man:
        errors.append(f"{MANIFEST}에 2차 생성(1차 확정) 기록이 없음: round2를 먼저 해야 한다")
    if "round2" in man:
        r2 = man["round2"]
        _cmp(errors, "review_round1.csv(2차 생성 = 1차 확정 때)", r2.get("round1_sha256"), run_dir / "review_round1.csv")
        try:
            rows1 = review.read_round1(run_dir)
            exp2 = review.round2_rows(rows1)
            tpl2 = sha256_text(review.csv_text(review.ROUND2_FIELDS, exp2))
        except ExtractError as e:
            rows1, exp2, tpl2 = None, None, f"(다시 만들 수 없음: {e})"
        if tpl2 != r2.get("template_sha256"):
            errors.append(f"2차 양식 해시가 다름: manifest {r2.get('template_sha256')} / 현재 1차로 다시 만든 양식 {tpl2}")
        p2 = run_dir / "review_round2.csv"
        if not p2.exists():
            errors.append("review_round2.csv가 없음(manifest에는 2차 생성 기록이 있음)")
        elif exp2 is not None:
            rows2 = review.read_round2(run_dir)
            fixed = [f for f in review.ROUND2_FIELDS if not f.startswith("final_")]
            if [[r[f] for f in fixed] for r in rows2] != [[r[f] for f in fixed] for r in exp2]:
                errors.append("review_round2.csv의 고정 열(final_* 밖)이 1차에서 다시 만든 양식과 다름")
    elif (run_dir / "review_round2.csv").exists():
        errors.append(f"review_round2.csv가 있는데 {MANIFEST}에 2차 생성 기록이 없음")
    if errors:
        raise ExtractError(f"{stage} 중단(출력 안 씀): 검토 기록(manifest) 불일치\n- " + "\n- ".join(errors))
    return man


def verify_review_record(run_dir):
    """to_rdf 전: 검토 기록이 있고 파일·개수·결정이 기록과 맞는지. 다르면 ExtractError."""
    from imaks_kg.extract import review
    run_dir = Path(run_dir)
    p = run_dir / APPLIED
    if not p.exists():
        raise ExtractError(f"RDF 출력 중단: 검토 기록 {APPLIED}가 없음(review apply를 먼저 실행)")
    rec = json.loads(p.read_text(encoding="utf-8"))
    errors = []
    _cmp(errors, "final.jsonl", rec.get("final_jsonl_sha256"), run_dir / "final.jsonl")
    _cmp(errors, "merged.jsonl", rec.get("merged_jsonl_sha256"), run_dir / "merged.jsonl")
    _cmp(errors, "merge_conflicts.csv", rec.get("merge_conflicts_sha256"), run_dir / "merge_conflicts.csv")
    _cmp(errors, "review_round1.csv", (rec.get("round1") or {}).get("sha256"), run_dir / "review_round1.csv")
    r2_file = run_dir / "review_round2.csv"
    r2 = rec.get("round2")
    if (r2 is None) != (not r2_file.exists()):
        errors.append(f"2차 검토 유무가 기록과 다름: 기록 {'없음' if r2 is None else '있음'} / "
                      f"파일 {'있음' if r2_file.exists() else '없음'}")
    elif r2 is not None:
        _cmp(errors, "review_round2.csv", r2.get("sha256"), r2_file)
    man = read_manifest(run_dir)
    # applied와 manifest의 같은 항목 대조(한쪽만 다시 쓴 위조를 잡는다)
    pairs = [
        ("merged.jsonl", (man.get("round1") or {}).get("merged_jsonl_sha256"), rec.get("merged_jsonl_sha256")),
        ("merge_conflicts.csv", (man.get("round1") or {}).get("merge_conflicts_sha256"), rec.get("merge_conflicts_sha256")),
        ("review_round1.csv(1차 확정)", (man.get("round2") or {}).get("round1_sha256"), (rec.get("round1") or {}).get("sha256")),
    ]
    for label, mv, av in pairs:
        if mv != av:
            errors.append(f"{label} 해시가 {MANIFEST}와 {APPLIED}에서 다름: manifest {mv} / applied {av}")
    if r2 is None:
        errors.append(f"{APPLIED}에 2차 검토 기록이 없음(apply는 2차 생성 뒤에만 가능)")
    if errors:
        raise ExtractError("RDF 출력 중단(출력 안 씀): 검토 기록과 파일이 다름\n- " + "\n- ".join(errors))
    check_manifest(run_dir, "RDF 출력", require_round2=True)
    # 개수·결정 집계와 CSV에서 다시 계산한 결정
    final = read_jsonl(run_dir / "final.jsonl")
    merged = read_jsonl(run_dir / "merged.jsonl")
    rows1 = review.read_round1(run_dir)
    rows2 = review.read_round2(run_dir) if r2_file.exists() else None
    decisions = review.resolve_decisions(rows1, rows2, merged)
    kept = {r["candidate_id"]: decisions[r["candidate_id"]][0] for r in merged
            if decisions[r["candidate_id"]][0] != "reject"}
    got = {r["candidate_id"]: r.get("review", {}).get("decision") for r in final}
    if got != kept:
        diff = sorted(set(got.items()) ^ set(kept.items()))[:5]
        errors.append(f"final.jsonl의 후보·결정이 검토 CSV에서 다시 계산한 결과와 다름: {diff}")
    else:
        # 값 대조: 고치지 않은 필드는 merged.jsonl 값, 고친 필드는 검토 CSV의 값과 같아야 한다
        from imaks_kg.extract.schema import ITEM_FIELDS
        by_cand = {r["candidate_id"]: r for r in merged}
        for r in final:
            edits = decisions[r["candidate_id"]][1]
            for k in ITEM_FIELDS:
                exp = edits[k] if k in edits else by_cand[r["candidate_id"]][k]
                if r.get(k) != exp:
                    errors.append(f"final.jsonl {r['candidate_id']}의 {k}가 merged.jsonl·검토 CSV로 다시 만든 값과 다름")
    expect = review.tally(final, merged)
    if rec.get("counts") != expect["counts"] or rec.get("decision_tally") != expect["decision_tally"]:
        errors.append(f"{APPLIED}의 개수·결정 집계가 final.jsonl과 다름: 기록 {rec.get('counts')} "
                      f"{rec.get('decision_tally')} / 계산 {expect['counts']} {expect['decision_tally']}")
    if errors:
        raise ExtractError("RDF 출력 중단(출력 안 씀): 검토 기록 불일치\n- " + "\n- ".join(errors))
    return rec
