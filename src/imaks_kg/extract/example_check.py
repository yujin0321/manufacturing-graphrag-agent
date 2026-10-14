"""Example 파일 누수 방지 검증 (설계서 §8-2). 모두 통과하면 파일 SHA-256을 prompts/example_registry.json에 등록한다.

사용: PYTHONPATH=src python -m imaks_kg.extract.example_check <example 파일> [--registry PATH]

검사 4종
  (a) 정답 고유 문구 겹침: 기존 check_gt_overlap.py를 하위 프로세스로 -n 5, --threshold 0.01(1건이라도 걸림)로 실행.
      종료 코드 0만 통과. 2(정답 파일 없음 등)는 '미확인'이라 실패로 본다. 이 코드는 정답 파일을 직접 읽지 않는다.
  (b) SOP·데이터시트 원문(pages.jsonl의 정규화 텍스트)과 5단어 조각 겹침 0건.
  (c) 데이터셋 어휘 미사용: ID형 토큰(스테이션·센서·문서·규칙 ID 형식), 원문에 나오는 수치+단위 조합.
  (d) 파일 해시(SHA-256) 계산.
출력에는 겹친 조각의 내용을 쓰지 않고 개수와 줄 번호만 쓴다. 이 코드는 Example을 만들지 않는다.
종료 코드: 0 통과·등록, 1 검증 실패(등록 안 함), 2 사용 오류/검사 불가(미확인)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from imaks_kg.extract.docdata import sha256_file
from imaks_kg.extract.request_builder import REGISTRY_FILE
from imaks_kg.settings import DOCUMENTS_OUT, KG_BUILD, REPO_ROOT

GT_TOOL = REPO_ROOT / ".claude" / "skills" / "stage-check" / "scripts" / "check_gt_overlap.py"
NGRAM_N = 5
MAX_LINES_SHOWN = 20
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)

# ID형 토큰 정규식: 규칙 ID, 문서 ID, 스테이션·센서 이름 형태
ID_PATTERNS = {
    "규칙 ID 형식": re.compile(r"(?<![A-Za-z0-9])(?:RULE|MAINT)-(?=[A-Z0-9-]*\d)[A-Z0-9-]+"),
    "문서 ID 형식": re.compile(r"(?<![A-Za-z0-9])(?:SOP|DS)-(?=[A-Z0-9-]*\d)[A-Z0-9-]+"),
    "스테이션·센서 이름 형식": re.compile(r"(?<![A-Za-z0-9])[A-Z]{2,4}\d{2}(?:_[A-Z0-9]+)+(?![A-Za-z0-9])"),
    "스테이션 코드 형식": re.compile(r"(?<![A-Za-z0-9])ST\d{2}(?![A-Za-z0-9])"),
}


class CheckUnavailable(RuntimeError):
    """검사를 수행하지 못함(입력 파일 없음 등). 실패가 아니라 미확인."""


def words(text: str) -> list:
    return _NON_WORD.sub(" ", text.lower()).split()


def ngram_set(ws: list, n: int) -> set:
    return {" ".join(ws[i:i + n]) for i in range(len(ws) - n + 1)}


def _lines(path: Path) -> list:
    return path.read_bytes().decode("utf-8").splitlines()


# ---------------------------------------------------------------- (a) 정답 고유 문구 겹침
def check_gt(example: Path, gt: Path | None = None, sop: Path | None = None, runner=subprocess.run) -> dict:
    cmd = [sys.executable, str(GT_TOOL), "-n", "5", "--threshold", "0.01", str(example.resolve())]
    if gt is not None:
        cmd += ["--gt", str(gt)]
    if sop is not None:
        cmd += ["--sop", str(sop)]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = runner(cmd, capture_output=True, cwd=str(REPO_ROOT), env=env)
    out = (p.stdout or b"").decode("utf-8", "replace")
    if p.returncode == 2:
        return {"passed": False, "unverified": True, "count": None,
                "message": "정답 겹침 검사 도구가 검사하지 못했습니다(종료 코드 2: 정답 파일 없음 등). 미확인이므로 실패로 처리합니다."}
    m = re.search(r"검사한 파일 (\d+)개, 기준 초과 (\d+)건", out)
    files = int(m.group(1)) if m else 0
    over = int(m.group(2)) if m else None
    if p.returncode == 0 and files < 1:
        return {"passed": False, "unverified": True, "count": None,
                "message": "정답 겹침 도구가 Example 파일을 읽지 않았습니다(확장자 .txt/.md/.json 등을 쓰세요). 미확인이므로 실패로 처리합니다."}
    if p.returncode == 0:
        return {"passed": True, "unverified": False, "count": 0, "message": "정답 고유 문구와 겹침 0건"}
    return {"passed": False, "unverified": False, "count": over,
            "message": f"정답 고유 문구와 겹치는 규칙 {over}건(내용은 출력하지 않음). 문장을 다시 쓰세요."}


# ---------------------------------------------------------------- (b) 원문 5단어 조각 겹침
def check_source_overlap(lines: list, pages_path: Path) -> dict:
    if not pages_path.is_file():
        raise CheckUnavailable("pages.jsonl이 없어 원문 겹침을 검사하지 못했습니다.")
    src = set()
    with pages_path.open(encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                src |= ngram_set(words(json.loads(ln).get("text_normalized") or ""), NGRAM_N)
    hit_lines, total = [], 0
    for i, line in enumerate(lines, 1):
        h = ngram_set(words(line), NGRAM_N) & src
        if h:
            hit_lines.append(i)
            total += len(h)
    return {"passed": not hit_lines, "count": total, "lines": hit_lines,
            "message": f"원문과 {NGRAM_N}단어 조각 겹침 {total}개 ({len(hit_lines)}개 줄)"}


# ---------------------------------------------------------------- (c) 데이터셋 어휘
def _ids_from_csv(path: Path, column: str = "identifier") -> list:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        return [row[column] for row in r if row.get(column)]


def _units_from_sensors(instances: Path) -> list:
    p = instances / "sensors.csv"
    if not p.is_file():
        return []
    with p.open(encoding="utf-8-sig", newline="") as f:
        return sorted({row["unit"] for row in csv.DictReader(f) if row.get("unit")})


def _canon_unit(u: str) -> str:
    low = u.lower()
    if low.startswith("min"):
        return "min"
    if low.startswith(("hour", "hr")) or low == "h":
        return "h"
    if low.startswith("sec") or low == "s":
        return "s"
    if low.startswith("sample"):
        return "samples"
    if low in ("°c",):
        return "°C"
    return u


def number_unit_pairs(text: str, extra_units: list) -> set:
    base = ["%RH", "°C", "L/min", "pcs/min", "mm/s", "m/s", "bar", "minutes", "minute", "min", "hours", "hour", "hrs",
            "hr", "seconds", "second", "secs", "sec", "samples", "sample", "%", "h", "s", "A", "N"]
    units = sorted(set(base) | set(extra_units), key=lambda x: (-len(x), x))
    pat = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(" + "|".join(re.escape(u) for u in units) + r")(?![A-Za-z/])")
    out = set()
    for m in pat.finditer(text):
        out.add((f"{float(m.group(1)):g}", _canon_unit(m.group(2))))
    return out


def check_vocabulary(lines: list, instances: Path, pages_path: Path, manifest_path: Path) -> dict:
    names = (_ids_from_csv(instances / "stations.csv") + _ids_from_csv(instances / "sensors.csv")
             + _ids_from_csv(instances / "documents.csv"))
    if manifest_path.is_file():
        names += _ids_from_csv(manifest_path, "doc_id")
    if not names:
        raise CheckUnavailable("kg_build/instances의 identifier 목록을 읽지 못해 어휘 검사를 할 수 없습니다.")
    codes = {n.split("_", 1)[0] for n in names if "_" in n}      # ST01, SRV01 같은 코드
    vocab = sorted(set(names) | codes, key=lambda x: (-len(x), x))
    name_pat = re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(v) for v in vocab) + r")(?![A-Za-z0-9])", re.I)
    units = _units_from_sensors(instances)
    src_pairs = set()
    if pages_path.is_file():
        with pages_path.open(encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    src_pairs |= number_unit_pairs(json.loads(ln).get("text_normalized") or "", units)
    else:
        raise CheckUnavailable("pages.jsonl이 없어 수치+단위 조합을 대조하지 못했습니다.")
    by_kind: dict = {}
    for i, line in enumerate(lines, 1):
        for kind, pat in ID_PATTERNS.items():
            if pat.search(line):
                by_kind.setdefault(kind, []).append(i)
        if name_pat.search(line):
            by_kind.setdefault("데이터셋 이름 목록과 일치", []).append(i)
        if number_unit_pairs(line, units) & src_pairs:
            by_kind.setdefault("원문의 수치+단위 조합과 일치", []).append(i)
    all_lines = sorted({n for v in by_kind.values() for n in v})
    return {"passed": not by_kind, "count": sum(len(v) for v in by_kind.values()), "lines": all_lines,
            "by_kind": {k: sorted(set(v)) for k, v in by_kind.items()},
            "message": "데이터셋 어휘 일치 " + (", ".join(f"{k} {len(set(v))}줄" for k, v in by_kind.items()) or "0건")}


# ---------------------------------------------------------------- 등록
def register(example: Path, digest: str, results: dict, registry: Path) -> dict:
    reg = {"version": 1, "entries": []}
    if registry.is_file():
        reg = json.loads(registry.read_text(encoding="utf-8"))
    if digest not in {e.get("sha256") for e in reg["entries"]}:
        reg["entries"].append({"sha256": digest, "file": example.name,
                               "registered_at": datetime.now().isoformat(timespec="seconds"),
                               "checks": results})
        registry.parent.mkdir(parents=True, exist_ok=True)
        tmp = registry.with_suffix(".tmp")
        tmp.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        os.replace(tmp, registry)
    return reg


def run_checks(example: Path, *, registry: Path | None = None, instances: Path | None = None,
               pages: Path | None = None, manifest: Path | None = None, gt: Path | None = None,
               sop: Path | None = None, do_register: bool = True, runner=subprocess.run) -> tuple:
    """(전체 통과 여부, 결과 dict, 해시). 통과하면 레지스트리에 등록한다."""
    example = Path(example)
    instances = Path(instances) if instances else KG_BUILD / "instances"
    pages = Path(pages) if pages else DOCUMENTS_OUT / "pages.jsonl"
    manifest = Path(manifest) if manifest else DOCUMENTS_OUT / "doc_manifest.csv"
    registry = Path(registry) if registry else REGISTRY_FILE
    lines = _lines(example)
    digest = sha256_file(example)
    results = {"a_gt_overlap": check_gt(example, gt, sop, runner),
               "b_source_overlap": check_source_overlap(lines, pages),
               "c_dataset_vocabulary": check_vocabulary(lines, instances, pages, manifest),
               "d_sha256": digest}
    ok = all(results[k]["passed"] for k in ("a_gt_overlap", "b_source_overlap", "c_dataset_vocabulary"))
    if ok and do_register:
        slim = {k: {"passed": v["passed"], "count": v.get("count")} for k, v in results.items() if isinstance(v, dict)}
        register(example, digest, slim, registry)
    return ok, results, digest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="imaks_kg.extract.example_check", description="Example 누수 방지 검증·등록")
    ap.add_argument("example", help="사용자가 쓴 Example 파일")
    ap.add_argument("--registry", default=None, help="기본: prompts/example_registry.json")
    ap.add_argument("--instances", default=None)
    ap.add_argument("--pages", default=None)
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--gt", default=None, help="(시험용) 정답 CSV 경로를 도구에 넘긴다. 기본은 도구가 찾는다")
    ap.add_argument("--sop", default=None)
    args = ap.parse_args(argv)
    ex = Path(args.example)
    if not ex.is_file():
        print(f"Example 파일이 없습니다: {ex.name}", file=sys.stderr)
        return 2
    try:
        ok, res, digest = run_checks(ex, registry=args.registry, instances=args.instances, pages=args.pages,
                                     manifest=args.manifest, gt=args.gt, sop=args.sop)
    except CheckUnavailable as e:
        print(f"검사 불가(미확인): {e}", file=sys.stderr)
        return 2
    except UnicodeDecodeError:
        print("Example 파일이 UTF-8이 아닙니다.", file=sys.stderr)
        return 2
    for key, label in (("a_gt_overlap", "(a) 정답 고유 문구 겹침"), ("b_source_overlap", "(b) 원문 5단어 조각 겹침"),
                       ("c_dataset_vocabulary", "(c) 데이터셋 어휘")):
        r = res[key]
        print(f"{label}: {'통과' if r['passed'] else '실패'} - {r['message']}")
        lines = r.get("lines")
        if lines:
            shown = ", ".join(map(str, lines[:MAX_LINES_SHOWN])) + (" ..." if len(lines) > MAX_LINES_SHOWN else "")
            print(f"    줄 번호: {shown}")
    print(f"(d) 파일 SHA-256: {digest}")
    if ok:
        print("PASS: 검증 4종 통과. 레지스트리에 해시를 등록했습니다.")
        return 0
    print("FAIL: 검증 실패. 등록하지 않았습니다. 겹침은 화이트리스트로 넘기지 말고 문장을 다시 쓰세요.")
    return 2 if res["a_gt_overlap"].get("unverified") else 1


if __name__ == "__main__":
    sys.exit(main())
