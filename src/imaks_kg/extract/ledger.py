"""git으로 추적하는 해시 장부(harness/extraction_ledger.jsonl). 2차 검증 FAIL (j)(일관된 위조)를 막는다.

- 추가만 한다. 한 줄 = 한 사건. 담는 것: seq, time, run_id, event, files({파일 이름: SHA-256}), prev_sha256(앞 줄의 SHA-256),
  승인 사건이면 estimate_id와 state. 규칙 내용·인용·키 값은 절대 넣지 않는다.
- 해시 사슬: 각 줄의 prev_sha256 = 바로 앞 줄 텍스트의 SHA-256(첫 줄은 0×64), seq는 1부터 연속. 중간 줄을 지우거나
  고치면 사슬이 끊겨 멈춘다.
- 사건:
  run_finished(meta.json, calls.jsonl, candidates_premerge.jsonl, rejected.csv, raw 응답 묶음 해시),
  merge_finished(merged.jsonl, merge_conflicts.csv), round1_created(review_round1.csv 양식, review_manifest.json),
  round2_created(review_round1.csv 확정본, review_round2.csv 양식, review_manifest.json),
  apply_finished(final.jsonl, review_applied.json, review_round1.csv, review_round2.csv 최종, review_manifest.json),
  to_rdf_output(출력 TTL 각각, 이름 앞에 "out:"),
  approval_created / reserved / used / released / usage_check_required / resolved(승인 기록 파일 전체 해시, state 포함).
- 검사(verify_run, verify_approval): 사슬 무결성 + 그 실행(또는 승인)의 가장 최근 기록이 현재 파일과 같은지.
  장부에 그 run_id(estimate_id)가 없으면 멈춘다(장부 이전 실행은 쓸 수 없음).
  사람이 채우는 파일은 양식 생성 기록 뒤에는 대조하지 않는다(review_round1.csv는 round1_created 뒤, review_round2.csv는
  round2_created 뒤). 그 파일은 다음 단계에서 확정 해시가 기록된다.
- 한계: 장부까지 함께 고치고 커밋하면 잡지 못한다. 남는 방어선은 git diff·이력 리뷰다. 마지막 줄만 고치거나 지우는 것도
  사슬로는 드러나지 않는다(다음 줄이 없음). 이것도 git diff로만 보인다.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from imaks_kg.common.provenance import sha256_file, sha256_text
from imaks_kg.extract.common import ExtractError, disp
from imaks_kg.settings import EXTRACTION_LEDGER

LEDGER_OVERRIDE = None  # 테스트가 임시 장부를 쓰게 할 때만 바꾼다
ENV_LEDGER = "IMAKS_EXTRACTION_LEDGER"  # CLI에서 임시 장부를 쓰고 싶을 때(예: 가짜 실행 확인)
ZERO = "0" * 64
TEMPLATE_EVENTS = {"review_round1.csv": "round1_created", "review_round2.csv": "round2_created"}
EVENT_LABEL = {"run_finished": "추출 끝", "merge_finished": "병합 끝", "round1_created": "1차 양식 생성",
               "round2_created": "2차 생성(1차 확정)", "apply_finished": "검토 적용", "to_rdf_output": "RDF 출력"}
RAW_BUNDLE = "raw_response_bundle"
OUT_PREFIX = "out:"


def current_path() -> Path:
    if LEDGER_OVERRIDE:
        return Path(LEDGER_OVERRIDE)
    return Path(os.environ.get(ENV_LEDGER) or EXTRACTION_LEDGER)


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load(path=None):
    """(줄 목록, 항목 목록). 사슬이 끊겼으면 ExtractError. 장부 파일이 없으면 ExtractError."""
    p = Path(path or current_path())
    if not p.exists():
        raise ExtractError(f"해시 장부가 없음: {disp(p)}")
    lines = [ln for ln in p.read_text(encoding="utf-8").split("\n") if ln]
    entries, prev = [], ZERO
    for i, ln in enumerate(lines, 1):
        try:
            e = json.loads(ln)
        except json.JSONDecodeError:
            raise ExtractError(f"해시 장부 {i}번째 줄을 읽을 수 없음")
        if e.get("seq") != i:
            raise ExtractError(f"해시 장부 사슬 끊김: {i}번째 줄의 seq가 {e.get('seq')}")
        if e.get("prev_sha256") != prev:
            raise ExtractError(f"해시 장부 사슬 끊김: {i}번째 줄의 prev_sha256이 앞 줄 해시와 다름(중간 줄을 지우거나 고침)")
        prev = sha256_text(ln)
        entries.append(e)
    return lines, entries


def append(event, files, run_id=None, estimate_id=None, state=None, path=None):
    """사건 한 줄을 덧붙인다. 장부 잠금 안에서: 읽기 → 사슬 검사(끊기면 멈춤) → seq·prev_sha256 계산 → 덧붙이기 → fsync."""
    from imaks_kg.extract import locks
    p = Path(path or current_path())
    with locks.ledger_lock(p):  # 장부 잠금만 잡는다(승인 잠금 → 장부 잠금 순서)
        if p.exists():
            lines, _ = load(p)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            lines = []
        e = {"seq": len(lines) + 1, "time": _now(), "run_id": run_id, "event": event,
             "files": {k: files[k] for k in sorted(files)}, "prev_sha256": sha256_text(lines[-1]) if lines else ZERO}
        if estimate_id is not None:
            e["estimate_id"] = estimate_id
            e["state"] = state
        with p.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
    return e


def raw_bundle_sha(run_dir):
    """raw/response 아래 파일 (이름, SHA-256) 목록의 해시."""
    d = Path(run_dir) / "raw" / "response"
    items = sorted((f.name, sha256_file(f)) for f in d.glob("*.json")) if d.exists() else []
    return sha256_text(json.dumps(items))


def file_sha(run_dir, name):
    if name == RAW_BUNDLE:
        return raw_bundle_sha(run_dir)
    p = Path(run_dir) / name
    return sha256_file(p) if p.exists() else None


def record_run(run_dir, run_id, event, names):
    files = {n: file_sha(run_dir, n) for n in names}
    missing = [n for n, v in files.items() if v is None]
    if missing:
        raise ExtractError(f"장부 기록 실패: 파일 없음 {missing}")
    return append(event, files, run_id=run_id)


def record_outputs(run_id, paths):
    return append("to_rdf_output", {OUT_PREFIX + Path(p).name: sha256_file(p) for p in paths}, run_id=run_id)


def verify_run(run_dir, stage):
    """사슬 + 이 실행의 최근 기록 == 현재 파일. 틀리면 ExtractError(출력 전에 멈추도록 호출자가 먼저 부른다)."""
    run_dir = Path(run_dir)
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    run_id = meta["run_id"]
    _, entries = load()
    mine = [e for e in entries if e.get("run_id") == run_id and "estimate_id" not in e]
    if not mine:
        raise ExtractError(f"{stage} 중단: 해시 장부에 실행 {run_id} 기록이 없음(장부 이전 실행은 쓸 수 없음)")
    latest = {}
    for e in mine:
        for name, sha in e["files"].items():
            latest[name] = (sha, e["event"], e["seq"])
    errors = []
    for name, (sha, event, seq) in sorted(latest.items()):
        if name.startswith(OUT_PREFIX) or TEMPLATE_EVENTS.get(name) == event:
            continue
        cur = file_sha(run_dir, name)
        if cur != sha:
            errors.append(f"{name}: 장부 기록({EVENT_LABEL.get(event, event)}, {seq}번째 줄) {sha} / 현재 {cur}")
    if errors:
        raise ExtractError(f"{stage} 중단(출력 안 씀): 해시 장부와 현재 파일이 다름\n- " + "\n- ".join(errors))
    return latest


def record_approval(path, event, run_id=None):
    rec = json.loads(Path(path).read_text(encoding="utf-8"))
    return append(event, {Path(path).name: sha256_file(path)}, run_id=run_id, estimate_id=rec["estimate_id"],
                  state=rec.get("state"))


def approval_state(estimate_id):
    """장부의 승인 사건으로 다시 만든 (상태, 기록 파일 해시, 마지막 사건). 사건이 없으면 None."""
    _, entries = load()
    mine = [e for e in entries if e.get("estimate_id") == estimate_id]
    if not mine:
        return None
    last = mine[-1]
    return last.get("state"), next(iter(last["files"].values())), last


def verify_approval(path):
    """승인 기록 파일의 상태·내용이 장부에서 다시 만든 것과 같은지. 틀린 점 목록(빈 목록이면 통과)."""
    try:
        rec = json.loads(Path(path).read_text(encoding="utf-8"))
        st = approval_state(rec.get("estimate_id"))
    except ExtractError as e:
        return [str(e)]
    if st is None:
        return [f"해시 장부에 승인 {rec.get('estimate_id')} 기록이 없음(장부 이전 승인은 쓸 수 없음)"]
    state, sha, last = st
    errors = []
    if rec.get("state") != state:
        errors.append(f"승인 상태가 장부와 다름: 파일 {rec.get('state')} / 장부 {state}({last['event']}, {last['seq']}번째 줄)")
    cur = sha256_file(path)
    if cur != sha:
        errors.append(f"승인 기록 파일이 장부의 마지막 기록과 다름: 장부 {sha} / 현재 {cur}")
    return errors
