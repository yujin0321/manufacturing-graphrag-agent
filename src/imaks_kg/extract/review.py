"""2단계 사람 검토.

  PYTHONPATH=src .venv/Scripts/python.exe -m imaks_kg.extract.review round2 --run-dir extraction/runs/<run_id>
  PYTHONPATH=src .venv/Scripts/python.exe -m imaks_kg.extract.review apply  --run-dir extraction/runs/<run_id>

1차(review_round1.csv, run.py가 만든 양식): 후보 한 행씩(모든 필드, sourceQuote, 청크 ID, 병합 여부, 폴백 여부)
  + merge_conflicts 행. 사람이 decision(accept/edit/reject/hold), edited_fields, comment만 채운다.
  - edited_fields는 JSON 객체(예: {"conditionText": "...", "sensors": ["ST02_SEALING_TMP"]}).
    고칠 수 있는 필드: 병합하지 않은 후보는 EDITABLE 전부, B에 병합된 후보는 sourceQuote만(B 값은 덮어쓰지 않음).
  - merge_conflict 행의 decision은 accept(차이 확인, B 값 유지)/reject(LLM 값이 틀렸다고 판단, B 값 유지)/hold.
    B 값은 어느 경우에도 바뀌지 않는다. 재확인 출처를 붙일지는 그 후보 행의 decision이 정한다.
  - 양식 열(decision·edited_fields·comment 밖)을 고치면 apply가 멈춘다(고칠 값은 edited_fields에만).
2차(review_round2.csv): 1차에서 edit·hold인 항목만. final_decision(accept/edit/reject), final_edited_fields, final_comment.
apply: 1차 + 2차를 적용해 final.jsonl을 만든다. 2차 생성(round2)이 1차 확정이므로 apply 전에 반드시 한다(0행이어도).
  - 입력(seed·B·lock·청크)이 추출 때와 같고, merged.jsonl·1차 파일·2차 고정 열이 기록(review_manifest.json)과
    같아야 한다(guard.py). 그다음 현재 파일에서 문서·seed·B를 새로 읽어 쓴다.
  - 미결정(빈 decision, 2차 없음, 2차 빈 값·hold)이 하나라도 있으면 멈춘다.
  - 고친 값은 validate의 검사(인용 원문 일치, ID 목록)를 다시 통과해야 한다. 실패하면 멈춘다.
  - 고친 뒤 병합을 다시 계산하고, 병합 여부·대상이 1차 양식과 달라지면 멈춘다(다시 검토 필요).
보존: LLM 원본(raw/, candidates_premerge.jsonl, merged.jsonl), review_round1.csv, review_round2.csv, final.jsonl,
review_applied.json(각 파일 SHA-256). 이미 있는 파일은 덮어쓰지 않는다.
"""
import argparse
import csv
import io
import json
import sys
from pathlib import Path

from imaks_kg.common.io_utils import read_csv_rows, write_csv, write_json, write_text
from imaks_kg.common.provenance import sha256_file
from imaks_kg.extract import guard, ledger
from imaks_kg.extract.common import ExtractError, disp, read_jsonl, write_jsonl_sorted
from imaks_kg.extract.merge import merge
from imaks_kg.extract.validate import revalidate

DECISION_COLS = ("decision", "edited_fields", "comment")
ROUND1_FIELDS = (
    "row_type", "item_id", "candidate_id", "chunk_id", "doc_id", "page", "merged", "merge_basis", "b_identifier",
    "identifier", "served_by_fallback", "served_model", "class", "conditionText", "responseText", "ruleSeverity",
    "sensors", "targetStations", "sourceQuote", "ruleIdInText", "actionSteps", "prov_location", "conflict_field",
    "llm_value", "b_value", "b_source", "notes") + DECISION_COLS
ROUND2_EXTRA = ("round1_decision", "round1_edited_fields", "round1_comment",
                "final_decision", "final_edited_fields", "final_comment")
ROUND2_FIELDS = tuple(f for f in ROUND1_FIELDS if f not in DECISION_COLS) + ROUND2_EXTRA
CAND_DECISIONS = ("accept", "edit", "reject", "hold")
CONFLICT_DECISIONS = ("accept", "reject", "hold")
FINAL_DECISIONS = ("accept", "edit", "reject")
EDITABLE = ("class", "conditionText", "responseText", "ruleSeverity", "sensors", "targetStations", "sourceQuote",
            "ruleIdInText")
EDITABLE_MERGED = ("sourceQuote",)
ROW_CANDIDATE, ROW_CONFLICT = "candidate", "merge_conflict"


def _loc(p):
    if "tableId" in p:
        return f"{p['tableId']} row {p['rowIndex']} col {','.join(str(x) for x in p['colIndex'])} bbox {p['bbox']}"
    return f"page {p['page']} char {p['charStart']}-{p['charEnd']}"


def round1_rows(records, conflicts):
    rows = []
    for r in records:
        m = r["merge"]
        rows.append({
            "row_type": ROW_CANDIDATE, "item_id": r["candidate_id"], "candidate_id": r["candidate_id"],
            "chunk_id": r["chunk_id"], "doc_id": r["doc_id"], "page": str(r["page"]),
            "merged": "yes" if m["merged"] else "no", "merge_basis": m["basis"], "b_identifier": m["b_identifier"],
            "identifier": r["identifier"], "served_by_fallback": "yes" if r["fallback_used"] else "no",
            "served_model": r["served_model"], "class": r["class"], "conditionText": r["conditionText"],
            "responseText": r["responseText"], "ruleSeverity": r["ruleSeverity"] or "",
            "sensors": "|".join(r["sensors"]), "targetStations": "|".join(r["targetStations"]),
            "sourceQuote": r["sourceQuote"], "ruleIdInText": r["ruleIdInText"] or "",
            "actionSteps": json.dumps(r["actionSteps"], ensure_ascii=False), "prov_location": _loc(r["provenance"]),
            "conflict_field": "", "llm_value": "", "b_value": "", "b_source": "", "notes": "; ".join(r["notes"]),
        })
    by_cand = {r["candidate_id"]: r for r in records}
    for c in conflicts:
        r = by_cand[c["candidate_id"]]
        rows.append({
            "row_type": ROW_CONFLICT, "item_id": c["conflict_id"], "candidate_id": c["candidate_id"],
            "chunk_id": c["chunk_id"], "doc_id": r["doc_id"], "page": str(r["page"]), "merged": "yes",
            "merge_basis": c["merge_basis"], "b_identifier": c["b_identifier"], "identifier": r["identifier"],
            "served_by_fallback": "yes" if r["fallback_used"] else "no", "served_model": r["served_model"],
            "class": "", "conditionText": "", "responseText": "", "ruleSeverity": "", "sensors": "",
            "targetStations": "", "sourceQuote": r["sourceQuote"], "ruleIdInText": r["ruleIdInText"] or "",
            "actionSteps": "", "prov_location": c["llm_source"], "conflict_field": c["field"],
            "llm_value": c["llm_value"], "b_value": c["b_value"], "b_source": c["b_source"], "notes": "",
        })
    for row in rows:
        for k in DECISION_COLS:
            row[k] = ""
    return rows


def csv_text(fields, rows) -> str:
    """write_csv와 같은 형식의 CSV 문자열(양식 해시를 다시 계산할 때 쓴다)."""
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(fields)
    w.writerows([[row.get(f, "") for f in fields] for row in rows])
    return buf.getvalue()


def _write_new_csv(path, fields, rows):
    if Path(path).exists():
        raise ExtractError(f"이미 있어 덮어쓰지 않음: {disp(path)}")
    write_csv(path, fields, [[row.get(f, "") for f in fields] for row in rows])


def write_round1(run_dir, records, conflicts, paths=None):
    """1차 양식을 쓰고 review_manifest.json에 merged.jsonl·merge_conflicts.csv·양식 해시를 남긴다.
    쓰기 전에 입력이 추출 때와 같은지(guard.check_inputs) 확인한다."""
    run_dir = Path(run_dir)
    guard.check_inputs(run_dir, paths, "1차 검토 양식 생성")
    if (run_dir / guard.MANIFEST).exists():
        raise ExtractError(f"이미 있어 덮어쓰지 않음: {disp(run_dir / guard.MANIFEST)}")
    _write_new_csv(run_dir / "review_round1.csv", ROUND1_FIELDS, round1_rows(records, conflicts))
    guard.write_manifest(run_dir, {**guard.manifest_binding(run_dir), "round1": {
        "merged_jsonl_sha256": sha256_file(run_dir / "merged.jsonl"),
        "merge_conflicts_sha256": sha256_file(run_dir / "merge_conflicts.csv"),
        "template_sha256": sha256_file(run_dir / "review_round1.csv")}})
    ledger.record_run(run_dir, _run_id(run_dir), "round1_created", ["review_round1.csv", guard.MANIFEST])


def _run_id(run_dir):
    return json.loads((Path(run_dir) / "meta.json").read_text(encoding="utf-8"))["run_id"]


def read_round1(run_dir):
    return _read(Path(run_dir) / "review_round1.csv", ROUND1_FIELDS)


def read_round2(run_dir):
    return _read(Path(run_dir) / "review_round2.csv", ROUND2_FIELDS)


def round2_rows(rows1):
    out = []
    for row in rows1:
        if row["decision"] in ("edit", "hold"):
            o = {f: row[f] for f in ROUND1_FIELDS if f not in DECISION_COLS}
            o.update({"round1_decision": row["decision"], "round1_edited_fields": row["edited_fields"],
                      "round1_comment": row["comment"], "final_decision": "", "final_edited_fields": "",
                      "final_comment": ""})
            out.append(o)
    return out


def tally(final, merged):
    """review_applied.json의 개수·결정 집계(to_rdf가 final.jsonl로 다시 계산해 대조한다)."""
    dec = {}
    for r in final:
        d = r["review"]["decision"]
        dec[d] = dec.get(d, 0) + 1
    return {"counts": {"candidates": len(merged), "kept": len(final), "rejected": len(merged) - len(final),
                       "edited": dec.get("edit", 0),
                       "merged_into_b": sum(1 for r in final if r["merge"]["merged"]),
                       "new_rules": sum(1 for r in final if not r["merge"]["merged"])},
            "decision_tally": {"accept": dec.get("accept", 0), "edit": dec.get("edit", 0),
                               "reject": len(merged) - len(final)}}


def _read(path, fields):
    if not Path(path).exists():
        raise ExtractError(f"검토 파일 없음: {disp(path)}")
    header, rows = read_csv_rows(path)
    if tuple(header) != tuple(fields):
        raise ExtractError(f"{disp(path)} 열 구성이 양식과 다름")
    return rows


def _parse_edits(text, where, allowed):
    if text.strip() == "":
        raise ExtractError(f"{where}: edit인데 edited_fields가 비어 있음")
    try:
        edits = json.loads(text)
    except json.JSONDecodeError as e:
        raise ExtractError(f"{where}: edited_fields가 JSON이 아님({e})")
    if not isinstance(edits, dict) or not edits:
        raise ExtractError(f"{where}: edited_fields는 비지 않은 JSON 객체여야 함")
    bad = sorted(set(edits) - set(allowed))
    if bad:
        raise ExtractError(f"{where}: 고칠 수 없는 필드 {bad} (허용: {list(allowed)})")
    return edits


def check_round1(rows, records, conflicts):
    """양식 열이 바뀌지 않았는지, 모든 결정이 허용 값인지(빈 값이면 미결정으로 멈춤)."""
    expected = round1_rows(records, conflicts)
    if [r["item_id"] for r in rows] != [e["item_id"] for e in expected]:
        raise ExtractError("review_round1.csv의 항목 목록·순서가 양식과 다름")
    merged = {r["candidate_id"]: r["merge"]["merged"] for r in records}
    errors, undecided = [], []
    for row, exp in zip(rows, expected):
        changed = [f for f in ROUND1_FIELDS if f not in DECISION_COLS and row[f] != exp[f]]
        if changed:
            errors.append(f"{row['item_id']}: 양식 열을 고침 {changed} (값은 edited_fields로만 고친다)")
        d = row["decision"].strip()
        if d == "":
            undecided.append(row["item_id"])
            continue
        allowed = CAND_DECISIONS if row["row_type"] == ROW_CANDIDATE else CONFLICT_DECISIONS
        if d not in allowed:
            errors.append(f"{row['item_id']}: decision {d!r}는 허용 값 {allowed}가 아님")
        if d == "edit":
            try:
                _parse_edits(row["edited_fields"], row["item_id"],
                             EDITABLE_MERGED if merged[row["candidate_id"]] else EDITABLE)
            except ExtractError as e:
                errors.append(str(e))
    if undecided:
        errors.append(f"1차 미결정 {len(undecided)}건: {undecided[:5]}{' …' if len(undecided) > 5 else ''}")
    if errors:
        raise ExtractError("1차 검토 확인 실패:\n- " + "\n- ".join(errors))


def make_round2(run_dir, paths=None):
    """1차를 확정하고(그때의 1차 파일 해시를 기록) 2차 양식을 만든다. 1차에 edit·hold가 없어도 0행 양식을 만든다."""
    run_dir = Path(run_dir)
    guard.check_inputs(run_dir, paths, "2차 검토 양식 생성")
    man = guard.check_manifest(run_dir, "2차 검토 양식 생성")
    if "round2" in man or (run_dir / "review_round2.csv").exists():
        raise ExtractError("2차 양식이 이미 만들어짐(덮어쓰지 않음)")
    records = read_jsonl(run_dir / "merged.jsonl")
    rows = read_round1(run_dir)
    check_round1(rows, records, _conflicts(run_dir))
    ledger.verify_run(run_dir, "2차 검토 양식 생성")
    out = round2_rows(rows)
    _write_new_csv(run_dir / "review_round2.csv", ROUND2_FIELDS, out)
    man["round2"] = {"round1_sha256": sha256_file(run_dir / "review_round1.csv"),
                     "template_sha256": sha256_file(run_dir / "review_round2.csv")}
    guard.write_manifest(run_dir, man)
    ledger.record_run(run_dir, _run_id(run_dir), "round2_created",
                      ["review_round1.csv", "review_round2.csv", guard.MANIFEST])
    return out


def _check_round2_frozen(run_dir, man, rows1, rows2):
    """1차 파일이 2차 생성(1차 확정) 때와 같고, 2차의 고정 열(final_* 밖)이 1차에서 만든 양식과 같은지."""
    if "round2" not in man:
        raise ExtractError("검토 적용 중단: 2차 양식 생성(round2)을 먼저 해야 한다(1차 확정 기록이 없음)")
    errors = []
    cur1 = sha256_file(Path(run_dir) / "review_round1.csv")
    if cur1 != man["round2"]["round1_sha256"]:
        errors.append(f"review_round1.csv가 2차 생성(1차 확정) 이후 바뀜: 기록 {man['round2']['round1_sha256']} / 현재 {cur1}")
    if rows2 is None:
        errors.append("review_round2.csv가 없음(2차 생성 기록은 있음)")
    else:
        fixed = [f for f in ROUND2_FIELDS if not f.startswith("final_")]
        exp = round2_rows(rows1)
        if [[r[f] for f in fixed] for r in rows2] != [[r[f] for f in fixed] for r in exp]:
            errors.append("review_round2.csv의 고정 열(final_* 밖)이 1차에서 만든 양식과 다름")
    if errors:
        raise ExtractError("검토 적용 중단:\n- " + "\n- ".join(errors))


def read_conflicts(run_dir):
    return _conflicts(run_dir)


def _conflicts(run_dir):
    _, rows = read_csv_rows(Path(run_dir) / "merge_conflicts.csv")
    return rows


def resolve_decisions(rows1, rows2, records):
    """항목별 최종 결정 {item_id: (결정, 고친 값 dict)}. 미결정이면 멈춘다."""
    merged = {r["candidate_id"]: r["merge"]["merged"] for r in records}
    need2 = [r["item_id"] for r in rows1 if r["decision"] in ("edit", "hold")]
    if need2 and rows2 is None:
        raise ExtractError(f"1차 edit·hold {len(need2)}건이 있는데 review_round2.csv가 없음(먼저 round2 생성·검토)")
    rows2 = rows2 or []
    if [r["item_id"] for r in rows2] != need2:
        raise ExtractError("review_round2.csv 항목이 1차의 edit·hold 항목과 다름")
    by2 = {r["item_id"]: r for r in rows2}
    errors, out = [], {}
    for r in rows1:
        iid, d = r["item_id"], r["decision"]
        allowed_fields = EDITABLE_MERGED if merged[r["candidate_id"]] else EDITABLE
        edits = {}
        if d == "edit":
            edits = _parse_edits(r["edited_fields"], iid, allowed_fields)
        if d in ("edit", "hold"):
            r2 = by2[iid]
            if r2["round1_decision"] != d or r2["round1_edited_fields"] != r["edited_fields"]:
                errors.append(f"{iid}: 2차 파일의 1차 기록이 1차 파일과 다름")
            fd = r2["final_decision"].strip()
            if fd == "":
                errors.append(f"{iid}: 2차 미결정")
                continue
            allowed = FINAL_DECISIONS if r["row_type"] == ROW_CANDIDATE else ("accept", "reject")
            if fd not in allowed:
                errors.append(f"{iid}: final_decision {fd!r}는 허용 값 {allowed}가 아님")
                continue
            if fd == "edit":
                try:
                    edits = {**edits, **_parse_edits(r2["final_edited_fields"], iid, allowed_fields)}
                except ExtractError as e:
                    errors.append(str(e))
                    continue
            d = "reject" if fd == "reject" else ("edit" if edits else "accept")
        out[iid] = (d, edits)
    if errors:
        raise ExtractError("검토 적용 실패:\n- " + "\n- ".join(errors))
    return out


def _apply_edits(rec, edits):
    new = json.loads(json.dumps(rec))
    for k, v in edits.items():
        new[k] = v
    return new


def apply_review(run_dir, paths=None):
    """입력(seed·B·lock·청크)과 검토 파일이 기록과 같은지 확인한 뒤, 현재 파일에서 문서·seed·B를 새로 읽어 적용한다.
    final.jsonl과 review_applied.json을 쓴다."""
    run_dir = Path(run_dir)
    for name in ("final.jsonl", guard.APPLIED):
        if (run_dir / name).exists():
            raise ExtractError(f"이미 있어 덮어쓰지 않음: {disp(run_dir / name)}")
    guard.check_inputs(run_dir, paths, "검토 적용")
    man = guard.check_manifest(run_dir, "검토 적용")  # 2차 필수 여부는 1차 확인 뒤 _check_round2_frozen이 본다
    ctx = guard.load_current(paths)
    records = read_jsonl(run_dir / "merged.jsonl")
    conflicts = _conflicts(run_dir)
    rows1 = read_round1(run_dir)
    check_round1(rows1, records, conflicts)
    p2 = run_dir / "review_round2.csv"
    rows2 = read_round2(run_dir) if p2.exists() else None
    _check_round2_frozen(run_dir, man, rows1, rows2)
    decisions = resolve_decisions(rows1, rows2, records)
    seed = ctx["seed"]
    sensors, stations = set(seed["sensors"]), set(seed["stations"])
    kept, errors = [], []
    for rec in records:
        d, edits = decisions[rec["candidate_id"]]
        if d == "reject":
            continue
        base = {k: v for k, v in rec.items() if k not in ("merge", "identifier", "identifier_source", "notes")}
        if d == "edit":
            new, err = revalidate(_apply_edits(base, edits), ctx["docs"], ctx["chunks_by_id"], sensors, stations)
            if err:
                errors.append(f"{rec['candidate_id']}: 고친 값이 검사를 통과하지 못함({err[0]}: {err[1]})")
                continue
            new["review"] = {"decision": "edit", "edited_fields": sorted(edits)}
            kept.append((rec, new))
        else:
            base["review"] = {"decision": "accept", "edited_fields": []}
            kept.append((rec, base))
    if errors:
        raise ExtractError("검토 적용 실패(재검사):\n- " + "\n- ".join(errors))
    final, _ = merge([n for _, n in kept], ctx["b"], ctx["chunks_by_id"])
    for (old, _), new in zip(kept, final):
        if (old["merge"]["merged"], old["merge"]["b_identifier"]) != (new["merge"]["merged"], new["merge"]["b_identifier"]):
            errors.append(f"{old['candidate_id']}: 고친 뒤 병합 여부·대상이 바뀜 "
                          f"({old['merge']['b_identifier'] or '병합 안 함'} → {new['merge']['b_identifier'] or '병합 안 함'})")
    if errors:
        raise ExtractError("검토 적용 실패(병합 변화, 다시 검토 필요):\n- " + "\n- ".join(errors))
    conflict_decisions = {r["item_id"]: decisions[r["item_id"]][0] for r in rows1 if r["row_type"] == ROW_CONFLICT}
    ledger.verify_run(run_dir, "검토 적용")
    write_text(run_dir / "final.jsonl", write_jsonl_sorted(final))
    summary = {
        "round1": {"file": "review_round1.csv", "sha256": sha256_file(run_dir / "review_round1.csv")},
        "round2": ({"file": "review_round2.csv", "sha256": sha256_file(p2)} if p2.exists() else None),
        "merged_jsonl_sha256": sha256_file(run_dir / "merged.jsonl"),
        "merge_conflicts_sha256": sha256_file(run_dir / "merge_conflicts.csv"),
        "final_jsonl_sha256": sha256_file(run_dir / "final.jsonl"),
        **tally(final, records),
        "merge_conflict_decisions": conflict_decisions,
    }
    write_json(run_dir / guard.APPLIED, summary)
    names = ["final.jsonl", guard.APPLIED, "review_round1.csv", guard.MANIFEST]
    if p2.exists():
        names.append("review_round2.csv")
    ledger.record_run(run_dir, _run_id(run_dir), "apply_finished", names)
    return final, summary


def main(argv=None):
    ap = argparse.ArgumentParser(description="C 2단계 사람 검토")
    ap.add_argument("action", choices=["round2", "apply"])
    ap.add_argument("--run-dir", required=True)
    args = ap.parse_args(argv)
    try:
        if args.action == "round2":
            out = make_round2(args.run_dir)
            print(f"2차 검토 양식: {disp(Path(args.run_dir) / 'review_round2.csv')} ({len(out)}행)")
        else:
            final, summary = apply_review(args.run_dir)
            print("검토 적용:", json.dumps(summary["counts"], ensure_ascii=False))
    except ExtractError as e:
        print(f"멈춤: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
