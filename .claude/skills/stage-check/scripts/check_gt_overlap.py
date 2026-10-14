#!/usr/bin/env python3
"""프롬프트·Example·청킹 산출물이 정답 규칙(ground_truth.csv)의 고유 문구를 복사했는지 n-gram 겹침으로 잰다.

정답 규칙은 SOP 원문에서 나왔으므로 SOP 원문과의 겹침은 허용한다. 정답 규칙의 단어 n-gram 중
SOP 원문에 없는 것(정답 고유 표현)만 세고, 대상 파일에 나타난 비율이 기준 이상이면 의심으로 보고한다.

사용: python check_gt_overlap.py [옵션] 대상파일_또는_폴더 ...
  --gt PATH           정답 CSV (기본: imaks_data 안에서 ground_truth.csv를 이름으로 찾음)
  --gt-column NAMES   규칙 문장 열 이름. 쉼표로 여러 개 가능 (기본: condition,action)
  --sop PATH          SOP·데이터시트 원문 jsonl (기본: preprocessed/documents/pages.jsonl의 text_normalized)
  -n N                단어 n-gram 길이 (기본 6)
  --threshold R       규칙 하나의 고유 n-gram 중 대상 파일에 나타난 비율 기준 (기본 0.3, 이상이면 의심)
대상 확장자(폴더 안): .txt .md .json .jsonl .py .yaml .yml .csv
출력: 파일 상대 경로, 정답 규칙 행 번호(1부터), 겹침 비율, 겹침 개수만. 정답 문구는 출력하지 않는다.
종료 코드: 0 기준 초과 없음, 1 기준 초과 있음, 2 정답·SOP 파일이 없거나 사용 오류(검사하지 못함, 미확인)
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
GT_NAME = "ground_truth.csv"
DEFAULT_SOP = "preprocessed/documents/pages.jsonl"
DEFAULT_GT_COLUMNS = "condition,action"
TARGET_EXT = {".txt", ".md", ".json", ".jsonl", ".py", ".yaml", ".yml", ".csv"}
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "imaks_data", "node_modules"}
MAX_SHOW = 30

_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)


def normalize(text: str) -> list[str]:
    """소문자, 구두점은 공백, 연속 공백은 하나로 -> 단어 목록."""
    return _NON_WORD.sub(" ", text.lower()).split()


def ngrams(words: list[str], n: int) -> set[str]:
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def find_gt() -> Path | None:
    base = ROOT / "imaks_data"
    if not base.is_dir():
        return None
    for f in sorted(base.rglob(GT_NAME)):
        if f.is_file():
            return f
    return None


def load_gt(path: Path, columns: list[str], n: int):
    """규칙별 n-gram 집합 목록. 열은 따로 n-gram을 만들어 합친다(열 경계를 넘지 않음)."""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        missing = [c for c in columns if c not in header]
        if missing:
            raise ValueError(f"정답 파일에 열이 없습니다: {', '.join(missing)} (있는 열: {', '.join(header)})")
        rules = []
        for row in reader:
            grams = set()
            for c in columns:
                grams |= ngrams(normalize(row.get(c) or ""), n)
            rules.append(grams)
    return rules


def load_sop_ngrams(path: Path, n: int) -> set[str]:
    """페이지별 text_normalized를 이어 붙인 원문의 n-gram (페이지 경계는 넘지 않게 페이지별로 만든다)."""
    out = set()
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            rec = json.loads(line)
            out |= ngrams(normalize(rec.get("text_normalized") or ""), n)
    return out


def iter_targets(paths, exclude: set[Path]):
    for p in paths:
        p = Path(p)
        p = p if p.is_absolute() else ROOT / p
        if p.is_file():
            if p.resolve() not in exclude:
                yield p
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if (f.is_file() and f.suffix.lower() in TARGET_EXT
                        and not (set(f.relative_to(p).parts[:-1]) & SKIP_DIRS)
                        and f.resolve() not in exclude):
                    yield f


def file_ngrams(path: Path, n: int) -> set[str] | None:
    """파일을 한 번 읽어 n-gram 집합으로 만든다. 줄 경계는 넘지 않는다."""
    grams = set()
    try:
        with path.open(encoding="utf-8", errors="strict") as fh:
            for line in fh:
                grams |= ngrams(normalize(line), n)
    except (UnicodeDecodeError, OSError):
        return None
    return grams


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="정답 규칙 고유 문구 복사 여부(n-gram 겹침) 검사")
    ap.add_argument("targets", nargs="*", help="검사 대상 파일·폴더")
    ap.add_argument("--gt", default=None)
    ap.add_argument("--gt-column", default=DEFAULT_GT_COLUMNS)
    ap.add_argument("--sop", default=None)
    ap.add_argument("-n", type=int, default=6)
    ap.add_argument("--threshold", type=float, default=0.3)
    args = ap.parse_args(argv)

    if args.n < 1:
        print("-n은 1 이상이어야 합니다.")
        return 2
    if not args.targets:
        print("검사 대상 파일·폴더를 하나 이상 지정하세요.")
        return 2

    gt = Path(args.gt) if args.gt else find_gt()
    if gt is not None and not gt.is_absolute():
        gt = ROOT / gt
    if gt is None or not gt.is_file():
        print("정답 파일이 없어 검사하지 못함(미확인)")
        return 2
    sop = Path(args.sop) if args.sop else ROOT / DEFAULT_SOP
    if not sop.is_absolute():
        sop = ROOT / sop
    if not sop.is_file():
        print("SOP 원문 파일이 없어 검사하지 못함(미확인): 고유 n-gram을 가릴 수 없습니다.")
        return 2

    columns = [c.strip() for c in args.gt_column.split(",") if c.strip()]
    try:
        rules = load_gt(gt, columns, args.n)
        sop_grams = load_sop_ngrams(sop, args.n)
    except (ValueError, json.JSONDecodeError, OSError) as e:
        print(f"입력을 읽지 못해 검사하지 못함(미확인): {type(e).__name__}")
        if isinstance(e, ValueError) and not isinstance(e, json.JSONDecodeError):
            print(str(e))
        return 2

    unique = [(i, g - sop_grams) for i, g in enumerate(rules, 1)]
    unique = [(i, u) for i, u in unique if u]

    exclude = {gt.resolve(), sop.resolve()}
    pairs, files = [], 0
    for f in iter_targets(args.targets, exclude):
        grams = file_ngrams(f, args.n)
        if grams is None:
            continue
        files += 1
        rel = f.relative_to(ROOT).as_posix() if f.is_relative_to(ROOT) else f.name
        for i, u in unique:
            hit = len(u & grams)
            if hit:
                ratio = hit / len(u)
                if ratio >= args.threshold:
                    pairs.append((rel, i, ratio, hit))

    pairs.sort(key=lambda t: (-t[2], t[0], t[1]))
    for rel, i, ratio, hit in pairs[:MAX_SHOW]:
        print(f"의심: {rel}: 정답 규칙 {i}행, 고유 n-gram 겹침 비율 {ratio:.2f}, 겹침 {hit}개")
    if len(pairs) > MAX_SHOW:
        print(f"외 {len(pairs) - MAX_SHOW}건")
    print(f"정답 규칙 {len(rules)}개, 고유 n-gram이 있는 규칙 {len(unique)}개, 검사한 파일 {files}개, 기준 초과 {len(pairs)}건")
    if pairs:
        print("FAIL: 정답 규칙 고유 표현과 겹치는 파일이 있습니다. 문구는 출력하지 않았으니 해당 파일·행을 직접 확인하세요.")
        return 1
    print(f"PASS: 기준({args.threshold:.2f}) 이상 겹침 없음 (n={args.n})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
