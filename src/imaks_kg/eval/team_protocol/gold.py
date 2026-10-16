"""정답 CSV 로더. 이 모듈이 정답을 읽는 유일한 코드다(describe_gold 포함).

문서 열 값이 알려진 문서 ID(doc_manifest.csv의 doc_id)와 정확히 같지 않으면 중단한다(추정 금지).
"""
import csv
import hashlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from imaks_kg.settings import DOCUMENTS_OUT, IMAKS_DATA
RAW_KG_SEED_DIR = IMAKS_DATA / "kg_seed"

GOLD_PATH = RAW_KG_SEED_DIR / "ground_truth.csv"
MANIFEST_PATH = DOCUMENTS_OUT / "doc_manifest.csv"
REQUIRED = ("ruleId", "class", "condition", "action", "source")


class GoldError(ValueError):
    pass


@dataclass(frozen=True)
class GoldRule:
    rule_id: str
    cls: str
    condition: str
    action: str
    doc: str
    sensor: str = ""


def known_doc_ids(manifest: Path = MANIFEST_PATH) -> set[str]:
    with Path(manifest).open(encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        key = "doc_id" if "doc_id" in (r.fieldnames or []) else "document_id"
        if key not in (r.fieldnames or []):
            raise GoldError("doc_manifest.csv에 doc_id 열이 없습니다")
        return {row[key] for row in r if row[key]}


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_gold(path: Path, known_docs: set[str]) -> list[GoldRule]:
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        header = list(r.fieldnames or [])
        missing = [c for c in REQUIRED if c not in header]
        if missing:
            raise GoldError(f"정답 파일에 열이 없습니다: {', '.join(missing)} (있는 열: {', '.join(header)})")
        rows = list(r)
    out = []
    for n, row in enumerate(rows, 2):
        doc = (row["source"] or "").strip()
        if doc not in known_docs:
            raise GoldError(f"정답 {n}행: 문서 열 값이 알려진 문서 ID가 아닙니다 (ruleId={row['ruleId']!r}); 추정하지 않고 중단")
        out.append(GoldRule(row["ruleId"], row["class"], row["condition"] or "", row["action"] or "", doc,
                            (row.get("sensor") or "").strip()))
    ids = Counter(g.rule_id for g in out)
    dup = [k for k, v in ids.items() if v > 1]
    if dup:
        raise GoldError(f"정답 ruleId 중복: {dup[:5]}")
    return out


def describe_gold(path: Path) -> dict:
    """구조만: 헤더, 행 수, 문서별·클래스별 행 수, 문서 열의 서로 다른 값. 규칙 문장은 반환하지 않는다."""
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        header = list(r.fieldnames or [])
        rows = list(r)
    out = {"header": header, "rows": len(rows)}
    if "source" in header:
        c = Counter(x["source"] for x in rows)
        out["source_distinct_values"] = sorted(c)
        out["rows_per_source"] = dict(sorted(c.items()))
    if "class" in header:
        out["rows_per_class"] = dict(sorted(Counter(x["class"] for x in rows).items()))
    return out
