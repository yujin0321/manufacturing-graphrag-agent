"""④ 사람 검토 2단계 기록 (설계서 §9).

1단계: 자동 점검이 KG 적재 제외 플래그를 붙인 규칙 전부(evidence_not_found, id_not_in_allowlist,
       table_position_out_of_range, duplicate_identifier, position_unresolved, empty_content)를 검토한다.
       coverage_gap만 붙은 규칙은 KG 적재 대상이라 2단계 모집단에 두고 flags.csv에서 확인한다.
2단계: 플래그 없이 통과한 규칙 + 1단계에서 accept된 규칙 중 약 20%를 무작위로 뽑아(시드 기록) 검토한다.
검토 기준은 SOP 원문뿐이다. 정답 파일과 비교해 고치지 않는다.
검토 결과는 rules_final.jsonl(이력 포함)과 review_log.jsonl에 따로 쓴다. predictions.jsonl(자동 추출 결과)은 바꾸지 않는다.
"""
from __future__ import annotations

import csv
import io
import json
import random
import secrets
from pathlib import Path

from imaks_kg.common.io_utils import write_json, write_jsonl
from imaks_kg.extract.artifacts import EXTRACTION_ROOT, file_sha256, run_dir
from imaks_kg.extract.validator import EXCLUDING_FLAGS

NOTICE = ("검토 기준은 SOP 원문뿐입니다. 정답 파일과 비교해 고치지 마세요. "
          "(수정·삭제·승인과 이유, 검토자, 시각을 이 파일에 기록합니다.)")
DECISIONS = ("accept", "edit", "reject")
INPUT_COLUMNS = ["decision", "edited_condition", "edited_action", "edited_identifier", "reason", "reviewer", "reviewed_at"]
SHOW_COLUMNS = ["rule_key", "identifier", "flags", "document_id", "chunk_id", "source_quote", "condition", "action"]
DEFAULT_FRACTION = 0.2


class ReviewError(ValueError):
    pass


def rule_key(r: dict) -> str:
    return f"{r['document_id']}#{r['rule_index']}"


def has_excluding_flag(r: dict) -> bool:
    return bool(set(r["flags"]) & set(EXCLUDING_FLAGS))


def _read_jsonl(path: Path) -> list:
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def read_review_csv(path: Path) -> tuple:
    """(머리 주석 줄들, 행 dict 목록). '#'로 시작하는 머리 줄은 건너뛴다."""
    text = Path(path).read_bytes().decode("utf-8-sig")
    head = []
    while text.startswith("#"):
        line, _, text = text.partition(chr(10))
        head.append(line.rstrip(chr(13)))
    rows = list(csv.DictReader(io.StringIO(text, newline="")))
    return head, rows


def write_review_csv(path: Path, head: list, rows: list) -> None:
    cols = SHOW_COLUMNS + INPUT_COLUMNS
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        for h in head:
            f.write(h + "\n")
        w = csv.writer(f, lineterminator="\n")
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in cols])


def _row_for(r: dict) -> dict:
    ev = r["evidence"][0] if r["evidence"] else {"chunk_id": "", "source_quote": ""}
    return {"rule_key": rule_key(r), "identifier": r["identifier"], "flags": ";".join(r["flags"]),
            "document_id": r["document_id"], "chunk_id": ev["chunk_id"], "source_quote": ev["source_quote"],
            "condition": r["condition"], "action": r["action"]}


def _head(stage: int, extra: str = "") -> list:
    return [f"# 사람 검토 {stage}단계. {NOTICE}",
            "# decision 열: accept(승인) | edit(수정; edited_* 열에 새 값) | reject(삭제; reason 필수). "
            "reviewer와 reviewed_at(예: 2026-10-14T15:00:00)을 함께 적습니다."] + ([extra] if extra else [])


def init_review(run_id: str, stage: int, *, seed: int | None = None, fraction: float = DEFAULT_FRACTION,
                out_root: Path | None = None) -> str:
    d = run_dir(run_id, out_root)
    rules = _read_jsonl(d / "rules_all.jsonl")
    if stage == 1:
        target = [r for r in rules if has_excluding_flag(r)]
        p = d / "review_stage1.csv"
        if p.exists():
            raise ReviewError(f"{p.name}이 이미 있습니다. 검토 기록을 덮어쓰지 않습니다.")
        write_review_csv(p, _head(1, f"# 대상: KG 적재 제외 플래그가 붙은 규칙 {len(target)}개 (전체 규칙 {len(rules)}개)"),
                         [_row_for(r) for r in target])
        return f"1단계 검토 파일: {p} (규칙 {len(target)}개)"
    p1 = d / "review_stage1.csv"
    if not p1.is_file():
        raise ReviewError("review_stage1.csv가 없습니다. 1단계를 먼저 만들고 검토하세요.")
    p2 = d / "review_stage2.csv"
    if p2.exists():
        raise ReviewError(f"{p2.name}이 이미 있습니다. 검토 기록을 덮어쓰지 않습니다.")
    if not 0 < fraction <= 1:
        raise ReviewError("fraction은 0 초과 1 이하여야 합니다.")
    _, s1rows = read_review_csv(p1)
    s1 = {x["rule_key"]: x for x in s1rows}
    accepted = {k for k, x in s1.items() if x["decision"].strip() == "accept"}
    pending = sum(1 for x in s1rows if not x["decision"].strip())
    pool = [r for r in rules if (not has_excluding_flag(r)) or rule_key(r) in accepted]
    pool.sort(key=lambda r: (r["document_id"], r["rule_index"]))
    if seed is None:
        seed = secrets.randbelow(2 ** 31)
    k = min(len(pool), max(1, round(fraction * len(pool)))) if pool else 0
    sample = sorted(random.Random(seed).sample(pool, k), key=lambda r: (r["document_id"], r["rule_index"]))
    meta = {"run_id": run_id, "seed": seed, "fraction": fraction, "pool_size": len(pool), "sampled": k,
            "stage1_accepted_in_pool": len(accepted), "stage1_pending_not_in_pool": pending,
            "sampling": "random.Random(seed).sample(pool sorted by (document_id, rule_index), k)"}
    write_review_csv(p2, _head(2, f"# 무작위 표본: seed={seed} fraction={fraction} 모집단={len(pool)} 표본={k}"),
                     [_row_for(r) for r in sample])
    write_json(d / "review_stage2.meta.json", meta)
    return f"2단계 검토 파일: {p2} (표본 {k}/{len(pool)}개, seed={seed}; 1단계 미결정 {pending}개는 모집단에서 제외)"


def _validate_row(stage: int, row: dict, line: int) -> dict | None:
    dec = (row.get("decision") or "").strip()
    if not dec:
        return None
    if dec not in DECISIONS:
        raise ReviewError(f"{stage}단계 검토 파일 {line}번째 행: decision은 accept, edit, reject 중 하나여야 합니다({dec!r}).")
    for c in ("reviewer", "reviewed_at"):
        if not (row.get(c) or "").strip():
            raise ReviewError(f"{stage}단계 검토 파일 {line}번째 행: 결정을 적었으면 {c}도 적어야 합니다.")
    edits = {f: (row.get("edited_" + f) or "") for f in ("condition", "action", "identifier")}
    if dec == "edit" and not any(v.strip() for v in edits.values()):
        raise ReviewError(f"{stage}단계 검토 파일 {line}번째 행: edit인데 edited_* 열이 모두 비었습니다.")
    if dec == "reject" and not (row.get("reason") or "").strip():
        raise ReviewError(f"{stage}단계 검토 파일 {line}번째 행: reject는 reason이 필요합니다.")
    return {"decision": dec, "edits": {k: v for k, v in edits.items() if v.strip()}, "reason": row.get("reason") or "",
            "reviewer": row["reviewer"].strip(), "reviewed_at": row["reviewed_at"].strip()}


def _load_stage(d: Path, stage: int) -> dict:
    p = d / f"review_stage{stage}.csv"
    if not p.is_file():
        return {}
    _, rows = read_review_csv(p)
    out = {}
    for i, row in enumerate(rows, 1):
        dec = _validate_row(stage, row, i)
        if dec is not None:
            out[row["rule_key"]] = dec
    return out


def apply_review(run_id: str, out_root: Path | None = None) -> str:
    d = run_dir(run_id, out_root)
    pred = d / "predictions.jsonl"
    before = file_sha256(pred)
    rules = _read_jsonl(d / "rules_all.jsonl")
    s1, s2 = _load_stage(d, 1), _load_stage(d, 2)
    known = {rule_key(r) for r in rules}
    for st, dd in ((1, s1), (2, s2)):
        unknown = [k for k in dd if k not in known]
        if unknown:
            raise ReviewError(f"{st}단계 검토 파일에 이 실행에 없는 규칙 키가 있습니다: {unknown[:3]}")
    final, log = [], []
    counts = {"auto_valid": 0, "accepted_stage1": 0, "edited": 0, "rejected": 0, "stage1_pending_excluded": 0,
              "stage2_decided": 0}
    for r in rules:
        k = rule_key(r)
        flagged = has_excluding_flag(r)
        decisions = []
        if flagged and k in s1:
            decisions.append((1, s1[k]))
        if k in s2:
            decisions.append((2, s2[k]))
        if flagged and k not in s1:
            counts["stage1_pending_excluded"] += 1
            continue
        rec = json.loads(json.dumps(r))
        rec["flags_at_extraction"] = list(r["flags"])
        history, rejected = [], False
        for stage, dec in decisions:
            if dec["decision"] == "reject":
                rejected = True
            if dec["decision"] == "edit":
                for field, new in dec["edits"].items():
                    key = field
                    before_v = rec[key]
                    rec[key] = new
                    history.append({"stage": stage, "decision": "edit", "field": field, "before": before_v, "after": new,
                                    "reason": dec["reason"], "reviewer": dec["reviewer"], "reviewed_at": dec["reviewed_at"]})
                if "identifier" in dec["edits"]:
                    rec["identifier_source"] = "reviewer"
            else:
                history.append({"stage": stage, "decision": dec["decision"], "field": None, "before": None,
                                "after": None, "reason": dec["reason"], "reviewer": dec["reviewer"],
                                "reviewed_at": dec["reviewed_at"]})
        rec["review_history"] = history
        rec["human_reviewed"] = bool(history)
        log += [dict(h, rule_key=k, identifier=r["identifier"], document_id=r["document_id"]) for h in history]
        if rejected:
            counts["rejected"] += 1
            continue
        if any(h["decision"] == "edit" for h in history):
            counts["edited"] += 1
        elif flagged:
            counts["accepted_stage1"] += 1
        else:
            counts["auto_valid"] += 1
        counts["stage2_decided"] += 1 if k in s2 else 0
        final.append(rec)
    ids = [x["identifier"] for x in final]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise ReviewError(f"최종 규칙에 identifier 중복이 남았습니다: {dup[:5]}. edited_identifier로 고치세요.")
    write_jsonl(d / "rules_final.jsonl", final)
    write_jsonl(d / "review_log.jsonl", log)
    after = file_sha256(pred)
    if after != before:  # 방어: 코드가 predictions를 건드리지 않음을 실행 때마다 확인
        raise RuntimeError("predictions.jsonl이 바뀌었습니다. 자동 추출 결과는 고정입니다.")
    summary = dict(counts, run_id=run_id, final_rules=len(final), human_reviewed=sum(1 for x in final if x["human_reviewed"]),
                   predictions_sha256=after)
    write_json(d / "review_summary.json", summary)
    return (f"rules_final.jsonl {len(final)}개 (사람 검토 {summary['human_reviewed']}개, 수정 {counts['edited']}, "
            f"삭제 {counts['rejected']}, 1단계 미결정으로 제외 {counts['stage1_pending_excluded']}); "
            f"predictions.jsonl 해시 불변 {after[:12]}")
