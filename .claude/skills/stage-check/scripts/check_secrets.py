#!/usr/bin/env python3
"""API 키·토큰이 저장소 파일에 남아 있는지 찾는다. 발견한 값(키 문자열)은 절대 출력하지 않는다.

사용: python check_secrets.py [폴더 또는 파일 ...]
  기본 대상: `git ls-files` 추적 파일 + kg_build, reports, llm_logs 폴더(있으면)
  제외 폴더: .git .venv venv imaks_data __pycache__ node_modules
탐지:
  (1) 환경변수 GEMINI_API_KEY, OPENAI_API_KEY 값(8자 이상)이 파일에 그대로 나오는지
  (2) 키 형식 정규식: Google 키, OpenAI 키(sk-, sk-proj-), Bearer 토큰, 코드·설정의 key/secret/token 대입
  - 환경변수 '이름'만 나오는 것, 자리표시자(YOUR_, xxxx, <...>, ${...}), os.environ/getenv 참조는 허용
출력: 상대 경로, 줄 번호, 패턴 이름만. 최대 50건 표시 후 "외 N건".
종료 코드: 0 발견 없음, 1 발견, 2 사용 오류
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
EXTRA_DIRS = ["kg_build", "reports", "llm_logs"]
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "imaks_data", "node_modules"}
ENV_NAMES = ["GEMINI_API_KEY", "OPENAI_API_KEY"]
MIN_ENV_LEN = 8
MAX_SHOW = 50

PATTERNS = {
    "Google API 키 형식": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "OpenAI 키 형식": re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_\-]{20,}"),
    "Bearer 토큰 형식": re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}"),
    "키/비밀/토큰 대입": re.compile(r"(api[_-]?key|secret|token)\s*[:=]\s*[\"']([^\"'\s]{16,})[\"']", re.I),
}
PLACEHOLDER = re.compile(r"os\.environ|getenv|\$\{|<[^>]*>|YOUR_|xxxx", re.I)
ENV_LIKE = re.compile(r"[A-Z][A-Z0-9]*(_[A-Z0-9]+)+")  # 환경변수 이름 형태 (예: MY_SERVICE_KEY)


def is_placeholder(text: str) -> bool:
    if PLACEHOLDER.search(text):
        return True
    return bool(ENV_LIKE.fullmatch(text))


def line_hits(line: str, env_values: list[str]) -> list[str]:
    """한 줄에서 걸린 패턴 이름 목록 (값은 반환하지 않는다)."""
    names = []
    for pname, pat in PATTERNS.items():
        for m in pat.finditer(line):
            token = m.group(m.lastindex) if m.lastindex and pname == "키/비밀/토큰 대입" else m.group(0)
            if pname == "키/비밀/토큰 대입":
                if is_placeholder(token):
                    continue
            elif PLACEHOLDER.search(token) or re.search(r"x{4,}", token, re.I):
                continue
            names.append(pname)
            break
    for val in env_values:
        if val in line:
            names.append("환경변수 값 일치")
            break
    return names


def scan_file(path: Path, env_values: list[str]):
    """(hits, skipped). 한 줄씩 읽는다. 이진·UTF-8 불가 파일은 skipped=True."""
    hits = []
    try:
        with path.open("rb") as fb:
            if b"\0" in fb.read(8192):
                return [], True
        with path.open(encoding="utf-8", newline=None) as fh:
            for i, line in enumerate(fh, 1):
                for name in line_hits(line, env_values):
                    hits.append((i, name))
    except (UnicodeDecodeError, OSError):
        return [], True
    return hits, False


def tracked_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    except Exception:
        return []
    return [ROOT / s for s in out.decode("utf-8", errors="replace").split("\0") if s]


def expand(paths) -> list[Path]:
    files, seen = [], set()

    def add(f: Path):
        if f in seen or not f.is_file():
            return
        try:
            parts = set(f.relative_to(ROOT).parts[:-1])
        except ValueError:
            parts = set()
        if parts & SKIP_DIRS:
            return
        seen.add(f)
        files.append(f)

    for p in paths:
        p = Path(p)
        p = p if p.is_absolute() else ROOT / p
        if p.is_file():
            add(p)
        elif p.is_dir():
            for f in p.rglob("*"):
                if f.is_file() and not (set(f.relative_to(p).parts[:-1]) & SKIP_DIRS):
                    add(f)
    return files


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if args:
        files = expand(args)
    else:
        files = []
        seen = set()
        for f in tracked_files() + expand([d for d in EXTRA_DIRS if (ROOT / d).exists()]):
            if f not in seen:
                seen.add(f)
                files.append(f)
        files = [f for f in files if f.is_file() and not (set(f.relative_to(ROOT).parts[:-1]) & SKIP_DIRS)]

    env_values = []
    for name in ENV_NAMES:
        v = os.environ.get(name, "")
        if len(v) >= MIN_ENV_LEN:
            env_values.append(v)

    results, scanned, skipped = [], 0, 0
    for f in files:
        rel = f.relative_to(ROOT).as_posix() if f.is_relative_to(ROOT) else f.name
        hits, skip = scan_file(f, env_values)
        if skip:
            skipped += 1
            continue
        scanned += 1
        for i, name in hits:
            results.append((rel, i, name))

    print(f"환경변수 값 검색: {len(env_values)}개 설정됨 (값은 출력하지 않음)")
    for rel, i, name in results[:MAX_SHOW]:
        print(f"발견: {rel}:{i}: {name}")
    if len(results) > MAX_SHOW:
        print(f"외 {len(results) - MAX_SHOW}건")
    print(f"검사한 파일 {scanned}개, 건너뜀 {skipped}개, 발견 {len(results)}건")
    if results:
        print("FAIL: 키·토큰으로 보이는 문자열이 있습니다. 값은 출력하지 않았으니 해당 줄을 직접 확인하세요.")
        return 1
    print("PASS: 키·토큰 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
