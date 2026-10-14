#!/usr/bin/env python3
"""imaks_data/ 원본이 바뀌지 않았는지 해시로 확인한다.

사용:
  python check_raw_unchanged.py --init   # 기준 매니페스트 생성 (최초 1회, 원본을 받은 직후)
  python check_raw_unchanged.py          # 비교
종료 코드: 0 일치, 1 불일치, 2 사용 오류
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
RAW = ROOT / "imaks_data"
MANIFEST = ROOT / "harness" / "raw_manifest.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot() -> dict:
    return {
        p.relative_to(RAW).as_posix(): {"sha256": sha256(p), "size": p.stat().st_size}
        for p in sorted(RAW.rglob("*"))
        if p.is_file()
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true")
    args = ap.parse_args()

    if not RAW.is_dir():
        print(f"imaks_data/ 폴더가 없습니다: {RAW}")
        return 2
    now = snapshot()
    if args.init:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(now, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"기준 매니페스트 저장: {len(now)}개 파일 -> {MANIFEST.relative_to(ROOT)}")
        return 0
    if not MANIFEST.exists():
        print("기준 매니페스트가 없습니다. 먼저 --init 으로 만드세요.")
        return 2

    base = json.loads(MANIFEST.read_text(encoding="utf-8"))
    changed = [k for k in base if k in now and base[k]["sha256"] != now[k]["sha256"]]
    missing = [k for k in base if k not in now]
    added = [k for k in now if k not in base]
    if not (changed or missing or added):
        print(f"PASS: imaks_data/ 원본 불변 ({len(now)}개 파일)")
        return 0
    print("FAIL: imaks_data/ 가 기준과 다릅니다.")
    for label, items in (("변경", changed), ("삭제", missing), ("추가", added)):
        for k in items:
            print(f"  {label}: {k}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
