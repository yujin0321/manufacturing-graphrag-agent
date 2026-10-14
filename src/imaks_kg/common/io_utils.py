"""파일 쓰기 도구. imaks_data 아래로 쓰는 시도는 거부한다. 모든 출력은 UTF-8, 줄바꿈 LF."""
import csv
import json
from pathlib import Path

from imaks_kg.settings import IMAKS_DATA


def _check_target(path: Path) -> Path:
    p = Path(path).resolve()
    if p == IMAKS_DATA or IMAKS_DATA in p.parents:
        raise PermissionError(f"imaks_data는 읽기 전용입니다. 쓰기 거부: {p}")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def write_text(path: Path, text: str) -> Path:
    p = _check_target(path)
    with p.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return p


def write_csv(path: Path, header, rows) -> Path:
    p = _check_target(path)
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    return p


def write_json(path: Path, obj) -> Path:
    return write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def write_jsonl(path: Path, records) -> Path:
    p = _check_target(path)
    with p.open("w", encoding="utf-8", newline="\n") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return p


def read_csv_rows(path: Path):
    """헤더와 행(dict, 모든 값은 원본 문자열)을 읽는다."""
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        header = list(r.fieldnames or [])
        rows = list(r)
    return header, rows
