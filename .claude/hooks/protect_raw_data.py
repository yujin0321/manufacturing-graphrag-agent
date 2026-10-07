#!/usr/bin/env python3
"""PreToolUse 훅: 원본 데이터 폴더(imaks_data/) 수정 차단.

Claude Code가 stdin으로 넘기는 JSON(tool_name, tool_input, cwd)을 읽고,
imaks_data/ 아래를 쓰거나 지우려는 시도면 exit 2로 차단한다. 읽기는 허용한다.
차단 효과가 있는 종료 코드는 2뿐이다(exit 1은 차단되지 않는다).

한계: python 스크립트가 내부에서 imaks_data/에 파일을 쓰는 경우는 명령어 문자열만으로는
알 수 없다. 그 경우는 check_raw_unchanged.py(해시 비교)가 사후에 잡는다.
"""
import json
import os
import re
import sys

PROTECTED = "imaks_data"

# 대상이 imaks_data인 쓰기·삭제·이동 계열 명령
DESTRUCTIVE = re.compile(
    r"(^|\s)("
    r"rm|rmdir|del|erase|rd|mv|move|rename|ren|"
    r"remove-item|ri|move-item|mi|rename-item|"
    r"set-content|add-content|clear-content|out-file|new-item|"
    r"truncate|tee|"
    r"git\s+(checkout|restore|clean|rm|mv)"
    r")(\s|$)"
)
SED_INPLACE = re.compile(r"(^|\s)sed\s+(-\w*i|--in-place)")
# 복사 계열은 imaks_data가 '목적지(마지막 인자)'일 때만 쓰기로 본다
COPY_VERBS = re.compile(r"(^|\s)(cp|copy|xcopy|robocopy|copy-item|cpi)(\s|$)")
REDIRECT_INTO = re.compile(r">>?\s*['\"]?[^\s'\"|;&<>]*" + PROTECTED)
PY_WRITE = re.compile(r"(to_csv|to_parquet|to_json|write_text|write_bytes|open\([^)]*['\"][wax]\+?b?['\"])")


def norm(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").lower()


def block(reason: str) -> int:
    sys.stderr.write(f"차단됨: {reason}\n")
    sys.stderr.write("원본 데이터는 읽기 전용입니다. 결과는 preprocessed/ 같은 다른 폴더에 쓰세요.\n")
    return 2


def segment_hits(segment: str) -> bool:
    if PROTECTED not in segment:
        return False
    if DESTRUCTIVE.search(segment) or SED_INPLACE.search(segment):
        return True
    if REDIRECT_INTO.search(segment) or PY_WRITE.search(segment):
        return True
    if COPY_VERBS.search(segment):
        tokens = [t for t in segment.split() if not t.startswith("-")]
        if tokens and PROTECTED in tokens[-1]:
            return True
    return False


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
    except Exception:
        return 0  # 입력을 해석할 수 없으면 판단하지 않고 일반 권한 흐름에 맡긴다

    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}
    root = norm(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd())
    protected_dir = f"{root}/{PROTECTED}"

    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        p = norm(path)
        if p == protected_dir or p.startswith(protected_dir + "/"):
            return block(f"{tool}로 {PROTECTED}/ 안의 파일을 수정하려고 했습니다: {path}")

    elif tool in ("Bash", "PowerShell"):
        cmd = (tool_input.get("command") or "").replace("\\", "/")
        for segment in re.split(r"[;&|\n]+", cmd.lower()):
            if segment_hits(segment):
                return block(f"{PROTECTED}/ 를 건드리는 쓰기·삭제성 명령으로 보입니다: {cmd[:200]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
