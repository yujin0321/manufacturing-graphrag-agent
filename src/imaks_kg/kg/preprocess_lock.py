"""전처리 산출물 고정 검증 기록(harness/preprocess_lock.json)과 해시 사슬 검사.

사슬: 원본 PDF → lock(검증 당시 해시) → doc_manifest/pages/tables/chunks/glyph_fixes, sensor_thresholds → B(promote_rules)

- 생성: PYTHONPATH=src .venv/Scripts/python.exe -m imaks_kg.kg.preprocess_lock --init [--force]
  전처리 결과를 검증(reports/preprocess_verify.md)한 뒤 사람이 명시적으로 실행한다. 이미 있으면 --force가 있어야 덮어쓴다.
- 검사: PYTHONPATH=src .venv/Scripts/python.exe -m imaks_kg.kg.preprocess_lock   (쓰기 없음)
  promote_rules는 check_chain()을 불러 lock을 읽기만 한다.

lock의 키는 저장소 기준 상대 경로다. 검사할 때 문서 산출물은 `doc_dir/<파일 이름>`, 전처리 코드는
`code_dir/<파일 이름>`, 임계값 파일은 `thresholds_csv`로 찾는다(테스트가 임시 폴더 사본을 넣을 수 있게).
"""
import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from imaks_kg.common.io_utils import read_csv_rows, write_text
from imaks_kg.common.provenance import sha256_file
from imaks_kg.settings import (
    DOCUMENTS_OUT, KG_BUILD, KG_SEED_DIR, PREPROCESS_CODE_DIR, PREPROCESS_LOCK, PREPROCESS_VERIFY_REPORT,
    REPO_ROOT, REPORTS_DIR, SEED_TTL, SENSOR_THRESHOLDS_CSV,
)

LOCK_VERSION = 1
DOC_OUTPUT_NAMES = ("doc_manifest.csv", "pages.jsonl", "tables.jsonl", "chunks.jsonl", "glyph_fixes.csv")
CODE_NAMES = ("documents.py", "sensors.py")
PROFILE_NAME = "doc_profile.json"
INIT_COMMAND = "python -m imaks_kg.kg.preprocess_lock --init"
CODE_CHANGED_MSG = "전처리 코드가 바뀌었으니 재검증 후 lock 갱신"


@dataclass
class BPaths:
    """B 입력·출력 경로 묶음. 기본값은 settings 상수."""
    repo_root: Path = REPO_ROOT
    doc_dir: Path = DOCUMENTS_OUT
    thresholds_csv: Path = SENSOR_THRESHOLDS_CSV
    lock_file: Path = PREPROCESS_LOCK
    code_dir: Path = PREPROCESS_CODE_DIR
    kg_seed_dir: Path = KG_SEED_DIR
    seed_ttl: Path = SEED_TTL
    out_dir: Path = KG_BUILD
    reports_dir: Path = REPORTS_DIR
    basis_report: Path = PREPROCESS_VERIFY_REPORT
    extra: dict = field(default_factory=dict)


def _repo_key(repo_root: Path, p: Path) -> str:
    try:
        return Path(p).resolve().relative_to(Path(repo_root).resolve()).as_posix()
    except ValueError:
        return Path(p).as_posix()


def _short(h):
    return h if h is None else str(h)


def _manifest_rows(paths: BPaths):
    _, rows = read_csv_rows(paths.doc_dir / "doc_manifest.csv")
    return rows


def build_lock(paths: BPaths, created_at: str) -> dict:
    """현재 파일들로 lock 내용을 만든다(쓰지 않음). 기록 전 일관성(PDF=doc_manifest, doc_profile=현재 파일)을 요구한다."""
    errors = []
    rows = _manifest_rows(paths)
    pdfs = {}
    for r in sorted(rows, key=lambda x: x["file"]):
        cur = sha256_file(paths.repo_root / r["file"])
        if cur != r["file_sha256"]:
            errors.append(f"{r['file']}: 현재 PDF {cur} != doc_manifest {r['file_sha256']}")
        pdfs[r["file"]] = cur
    docs = {_repo_key(paths.repo_root, paths.doc_dir / n): sha256_file(paths.doc_dir / n) for n in DOC_OUTPUT_NAMES}
    errors += _profile_errors(paths)
    if not Path(paths.basis_report).exists():
        errors.append(f"근거 검증 보고서가 없음: {paths.basis_report}")
    if errors:
        raise RuntimeError("lock을 만들 수 없음:\n" + "\n".join(errors))
    return {
        "version": LOCK_VERSION,
        "created_at": created_at,
        "created_by": INIT_COMMAND,
        "basis_report": _repo_key(paths.repo_root, paths.basis_report),
        "input_pdfs": pdfs,
        "document_outputs": docs,
        "sensor_outputs": {_repo_key(paths.repo_root, paths.thresholds_csv): sha256_file(paths.thresholds_csv)},
        "preprocess_code": {_repo_key(paths.repo_root, paths.code_dir / n): sha256_file(paths.code_dir / n)
                            for n in CODE_NAMES},
    }


def _profile_errors(paths: BPaths):
    prof_path = paths.doc_dir / PROFILE_NAME
    if not prof_path.exists():
        return [f"{PROFILE_NAME} 없음: {prof_path}"]
    prof = json.loads(prof_path.read_text(encoding="utf-8")).get("output_sha256", {})
    by_name = {Path(k).name: v for k, v in prof.items()}
    errors = []
    for n in DOC_OUTPUT_NAMES:
        cur = sha256_file(paths.doc_dir / n)
        rec = by_name.get(n)
        if rec != cur:
            errors.append(f"{PROFILE_NAME} output_sha256[{n}] {_short(rec)} != 현재 파일 {cur}")
    return errors


def check_chain(paths: BPaths) -> list:
    """해시 사슬 검사. 틀린 항목의 설명 목록을 돌려준다(빈 목록이면 통과). 파일을 쓰지 않는다."""
    lock_path = Path(paths.lock_file)
    if not lock_path.exists():
        return [f"lock 없음: {lock_path} (검증 후 `{INIT_COMMAND}`로 생성)"]
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("version") != LOCK_VERSION:
        return [f"lock 형식 버전 {lock.get('version')} != {LOCK_VERSION}"]
    errors = []

    # (a) PDF: 현재 == lock == doc_manifest
    lock_pdfs = lock.get("input_pdfs", {})
    rows = _manifest_rows(paths)
    man = {r["file"]: r["file_sha256"] for r in rows}
    if set(man) != set(lock_pdfs):
        errors.append(f"PDF 목록이 다름: doc_manifest {sorted(man)} / lock {sorted(lock_pdfs)}")
    for f in sorted(set(man) | set(lock_pdfs)):
        p = paths.repo_root / f
        cur = sha256_file(p) if p.exists() else None
        if not (cur == lock_pdfs.get(f) == man.get(f)):
            errors.append(f"PDF {f}: 현재 {_short(cur)} / lock {_short(lock_pdfs.get(f))} / doc_manifest file_sha256 {_short(man.get(f))}")

    # (b) 문서 산출물: 현재 == lock
    lock_docs = {Path(k).name: (k, v) for k, v in lock.get("document_outputs", {}).items()}
    if set(lock_docs) != set(DOC_OUTPUT_NAMES):
        errors.append(f"lock document_outputs 항목이 다름: {sorted(lock_docs)}")
    for n in DOC_OUTPUT_NAMES:
        p = paths.doc_dir / n
        cur = sha256_file(p) if p.exists() else None
        key, rec = lock_docs.get(n, (n, None))
        if cur != rec:
            errors.append(f"전처리 산출물 {key}: 현재 {_short(cur)} != lock {_short(rec)}")

    # doc_profile 실행 기록 == 현재 파일
    errors += _profile_errors(paths)

    # (c) 센서 임계값 파일
    sens = lock.get("sensor_outputs", {})
    if len(sens) != 1:
        errors.append(f"lock sensor_outputs 항목 수 {len(sens)} != 1")
    else:
        (key, rec), = sens.items()
        p = Path(paths.thresholds_csv)
        cur = sha256_file(p) if p.exists() else None
        if cur != rec:
            errors.append(f"임계값 파일 {key}: 현재 {_short(cur)} != lock {_short(rec)}")

    # (d) 전처리 코드
    lock_code = {Path(k).name: (k, v) for k, v in lock.get("preprocess_code", {}).items()}
    for n in CODE_NAMES:
        p = paths.code_dir / n
        cur = sha256_file(p) if p.exists() else None
        key, rec = lock_code.get(n, (n, None))
        if cur != rec:
            errors.append(f"{CODE_CHANGED_MSG}: {key} 현재 {_short(cur)} != lock {_short(rec)}")
    return errors


def main(argv=None):
    ap = argparse.ArgumentParser(description="전처리 고정 검증 기록 생성(--init) 또는 검사")
    ap.add_argument("--init", action="store_true", help="현재 파일로 lock을 만든다(검증을 마친 뒤에만)")
    ap.add_argument("--force", action="store_true", help="이미 있는 lock을 덮어쓴다")
    args = ap.parse_args(argv)
    paths = BPaths()
    if args.init:
        if paths.lock_file.exists() and not args.force:
            print(f"이미 있음: {_repo_key(paths.repo_root, paths.lock_file)} (덮어쓰려면 --force)")
            return 2
        created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        lock = build_lock(paths, created)
        write_text(paths.lock_file, json.dumps(lock, ensure_ascii=False, indent=2) + "\n")
        print(f"lock 생성: {_repo_key(paths.repo_root, paths.lock_file)} sha256={sha256_file(paths.lock_file)}")
        return 0
    errors = check_chain(paths)
    for e in errors:
        print("불일치:", e)
    print("PASS: 해시 사슬 일치" if not errors else f"FAIL: 불일치 {len(errors)}건")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
