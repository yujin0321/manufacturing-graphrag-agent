#!/usr/bin/env python3
"""금지 컬럼명(정답 누수)이 산출물·코드에 나타나는지 검색한다.

사용: python check_leakage.py [폴더 또는 파일 ...]   (기본: preprocessed ontology_v1 kg_build src)
금지 목록: harness/forbidden_columns.txt (한 줄에 하나, # 주석) - CSV 헤더, JSON 키, 본문 텍스트 모두에 적용
컬럼 전용 목록: harness/forbidden_columns_header_only.txt (없으면 무시)
  - CSV 헤더와 .json/.jsonl의 키에만 전체 일치로 적용하고, 코드·문서 본문에는 적용하지 않는다(day 같은 흔한 단어의 오탐 방지)
종료 코드: 0 발견 없음, 1 발견, 2 사용 오류
"""
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
FORBIDDEN_FILE = ROOT / "harness" / "forbidden_columns.txt"
HEADER_ONLY_FILE = ROOT / "harness" / "forbidden_columns_header_only.txt"
# 문서 폴더는 ④ 추출용 원문이라 ⑥ 입력이 아니며 원문에 금지어 단어가 자연스럽게 나온다: json/jsonl은 키만 검사한다.
TEXT_EXEMPT_PREFIXES = ("preprocessed/documents/",)
DEFAULT_PATHS = ["preprocessed", "ontology_v1", "kg_build", "src"]
CODE_EXT = {".py", ".ipynb", ".json", ".jsonl", ".ttl", ".rq", ".md", ".txt", ".yaml", ".yml", ".cypher"}
EVAL_DIRS = {"evaluation", "eval", "tests"}
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "imaks_data", "node_modules"}


def load_list(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def load_forbidden() -> list[str]:
    if not FORBIDDEN_FILE.exists():
        print(f"금지 목록이 없습니다: {FORBIDDEN_FILE}")
        sys.exit(2)
    return load_list(FORBIDDEN_FILE)


def load_header_only() -> list[str]:
    return load_list(HEADER_ONLY_FILE) if HEADER_ONLY_FILE.exists() else []


def json_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from json_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from json_keys(v)


def iter_files(paths):
    for p in paths:
        p = (ROOT / p) if not Path(p).is_absolute() else Path(p)
        if p.is_file():
            yield p
        elif p.is_dir():
            for f in p.rglob("*"):
                if f.is_file() and not (set(f.relative_to(p).parts[:-1]) & SKIP_DIRS):
                    yield f


def main() -> int:
    forbidden = load_forbidden()
    header_only = load_header_only()
    ho_pats = {w: re.compile(re.escape(w), re.I) for w in header_only}
    pats = {w: re.compile(r"(?<![A-Za-z0-9_])" + re.escape(w) + r"(?![A-Za-z0-9_])", re.I) for w in forbidden}
    paths = sys.argv[1:] or DEFAULT_PATHS
    hits, warns, scanned = [], [], 0

    for f in iter_files(paths):
        rel = f.relative_to(ROOT).as_posix() if f.is_relative_to(ROOT) else str(f)
        if f.suffix.lower() == ".csv":
            scanned += 1
            try:
                with f.open(encoding="utf-8-sig", newline="") as fh:
                    header = next(csv.reader(fh), [])
            except Exception as e:
                warns.append(f"{rel}: CSV 헤더를 읽지 못함 ({e})")
                continue
            for col in header:
                for w, pat in pats.items():
                    if pat.fullmatch(col.strip()):
                        hits.append(f"{rel}: CSV 헤더에 금지 컬럼 '{col}'")
                for w, pat in ho_pats.items():
                    if pat.fullmatch(col.strip()):
                        hits.append(f"{rel}: CSV 헤더에 금지 컬럼(컬럼 전용) '{col}'")
        elif f.suffix.lower() in CODE_EXT:
            scanned += 1
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            is_json = f.suffix.lower() in (".json", ".jsonl")
            text_exempt = is_json and rel.startswith(TEXT_EXEMPT_PREFIXES)
            if is_json and (ho_pats or text_exempt):
                docs = []
                try:
                    if f.suffix.lower() == ".jsonl":
                        docs = [json.loads(l) for l in text.splitlines() if l.strip()]
                    else:
                        docs = [json.loads(text)]
                except Exception as e:
                    warns.append(f"{rel}: JSON 키를 읽지 못함 ({e})")
                seen = set()
                for d in docs:
                    for key in json_keys(d):
                        if key in seen:
                            continue
                        seen.add(key)
                        for w, pat in ho_pats.items():
                            if pat.fullmatch(key.strip()):
                                hits.append(f"{rel}: JSON 키에 금지 컬럼(컬럼 전용) '{key}'")
                        if text_exempt:
                            for w, pat in pats.items():
                                if pat.fullmatch(key.strip()):
                                    hits.append(f"{rel}: JSON 키에 금지 컬럼 '{key}'")
            in_eval = bool(set(f.parts) & EVAL_DIRS)
            for i, line in enumerate([] if text_exempt else text.splitlines(), 1):
                for w, pat in pats.items():
                    if pat.search(line):
                        hits.append(f"{rel}:{i}: '{w}' -> {line.strip()[:100]}")
                if not in_eval and "ground_truth" in line.lower():
                    warns.append(f"{rel}:{i}: 평가 폴더 밖에서 ground_truth 사용 -> {line.strip()[:100]}")

    extra = f", 컬럼 전용 {len(header_only)}개" if header_only else ""
    print(f"검사한 파일 {scanned}개, 금지어 {len(forbidden)}개{extra}")
    for w in warns:
        print("경고:", w)
    for h in hits:
        print("발견:", h)
    if hits:
        print(f"FAIL: 금지 컬럼 {len(hits)}건 발견. 오탐 여부는 사람이 확인하세요.")
        return 1
    print("PASS: 금지 컬럼 없음" + (f" (경고 {len(warns)}건)" if warns else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
