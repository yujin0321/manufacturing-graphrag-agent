"""C 테스트 공용 도구(가짜 응답 실행, 검토 CSV 채우기, SHACL)."""
import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from pyshacl import validate as shacl_validate  # noqa: E402
from rdflib import Graph  # noqa: E402

import extract_fakes  # noqa: E402
from imaks_kg import settings  # noqa: E402
from imaks_kg.extract import llm, run  # noqa: E402

_CTX = None

# 테스트는 저장소의 해시 장부(harness/extraction_ledger.jsonl)를 건드리지 않는다: 프로세스 전체에 임시 장부를 쓴다.
from imaks_kg.extract import ledger  # noqa: E402
_LEDGER_DIR = tempfile.TemporaryDirectory(prefix="extract_ledger_")
PROCESS_LEDGER = Path(_LEDGER_DIR.name) / "ledger.jsonl"
ledger.LEDGER_OVERRIDE = PROCESS_LEDGER


class FakeClock:
    """테스트용 단조 시계: sleep(s)이 시각을 s만큼 앞당긴다(실제로 기다리지 않음). sleeps에 잔 시간을 모은다."""

    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


from imaks_kg.extract import locks  # noqa: E402
_LOCK_DIR = tempfile.TemporaryDirectory(prefix="extract_locks_")
locks.LOCK_DIR_OVERRIDE = Path(_LOCK_DIR.name)  # 잠금 파일도 임시 폴더(저장소 extraction/을 만들지 않음)


def use_ledger(test, path):
    """이 테스트 동안 장부 위치를 path로 바꾼다(실행 폴더를 복사할 때 장부도 함께 복사해 쓰는 용도)."""
    from unittest import mock
    p = mock.patch.object(ledger, "LEDGER_OVERRIDE", Path(path))
    p.start()
    test.addCleanup(p.stop)


def copy_ledger_from(src, dst):
    import shutil
    shutil.copyfile(src, dst)
    return Path(dst)


def copy_ledger(dst):
    """현재 장부를 dst로 복사하고 경로를 돌려준다."""
    import shutil
    src = ledger.current_path()
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copyfile(src, dst)
    else:
        Path(dst).write_text("", encoding="utf-8")
    return Path(dst)


def needs_inputs():
    """테스트 입력이 있는지(없으면 건너뛸 사유 문자열)."""
    for p in (settings.DOC_CHUNKS, settings.SEED_TTL, settings.RULES_TTL, settings.PREPROCESS_LOCK):
        if not Path(p).exists():
            return f"{p.name} 없음(전처리·seed_to_rdf·promote_rules 먼저 실행)"
    return ""


def ctx():
    """run.prepare() 결과(해시 사슬 검사 포함). 테스트 사이에서 한 번만 만든다(읽기 전용으로만 쓴다)."""
    global _CTX
    if _CTX is None:
        _CTX = run.prepare(provider="anthropic")
    return _CTX


def fake_run(base_dir, run_id="t-run", responses=None):
    base_dir = Path(base_dir)
    fake_dir = extract_fakes.write(base_dir / "fake", responses)
    res = run.run_calls(ctx(), llm.FakeClient(fake_dir), base_dir / "runs" / run_id, run_id, "fake")
    return res["run_dir"]


def read_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames), list(r)


def write_rows(path, header, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, header, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def fill_round1(run_dir, default="accept", overrides=None):
    """1차 양식의 decision을 채운다. overrides: {item_id: (decision, edited_fields 문자열)}."""
    p = Path(run_dir) / "review_round1.csv"
    header, rows = read_rows(p)
    for r in rows:
        d, e = (overrides or {}).get(r["item_id"], (default, ""))
        r["decision"], r["edited_fields"], r["comment"] = d, e, "테스트"
    write_rows(p, header, rows)
    return rows


def fill_round2(run_dir, decisions):
    """decisions: {item_id: (final_decision, final_edited_fields)}"""
    p = Path(run_dir) / "review_round2.csv"
    header, rows = read_rows(p)
    for r in rows:
        d, e = decisions.get(r["item_id"], ("", ""))
        r["final_decision"], r["final_edited_fields"], r["final_comment"] = d, e, "테스트"
    write_rows(p, header, rows)
    return rows


def shacl(graph):
    conforms, _, text = shacl_validate(graph, shacl_graph=Graph().parse(str(settings.SHAPES_TTL)),
                                       ont_graph=Graph().parse(str(settings.ONTOLOGY_TTL)), inference="none")
    return conforms, text


def tmpdir():
    return tempfile.TemporaryDirectory(prefix="extract_test_")
