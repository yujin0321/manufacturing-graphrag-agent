"""extract_b 테스트 공용 도구. 실제 API는 호출하지 않는다(mock 공급자와 가짜 응답만).

- 실제 전처리 문서(preprocessed/documents)와 ③ 산출물(kg_build/instances)을 읽는 시험은 그 파일이 있어야 한다.
- 가짜 응답의 인용문은 실제 청크에서 실행 중에 잘라 만든다(코드에 SOP 문장을 적지 않는다).
- 정답 파일은 읽지 않는다.
"""
import csv
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from extract_a_helpers import make_config  # noqa: E402,F401
from imaks_kg.extract import example_check  # noqa: E402
from imaks_kg.extract.config import config_from_dict  # noqa: E402
from imaks_kg.extract.docdata import DocumentStore, load_allowlist  # noqa: E402
from imaks_kg.extract.request_builder import load_prompt_files, make_units  # noqa: E402

FAKE_EXAMPLE = """Fictional example for tests only.
<<chunk DEMO-001:p1:text1 | page 1>>
Keep the ZQ7_MIXER_TORQ reading under 88 kNm. Beyond 95 kNm the crew closes the feed valve.
{"rules": [], "coverage": []}
"""


def real_store():
    return DocumentStore()


def real_allow():
    return load_allowlist()


def make_registered_example(tmp: Path, text: str = FAKE_EXAMPLE) -> tuple:
    """가짜 Example 파일을 tmp에 쓰고, tmp의 레지스트리에 해시를 직접 등록한다(검증 도구 실행은 example_check 시험이 따로 함)."""
    ex = Path(tmp) / "example_fake.txt"
    ex.write_bytes(text.encode("utf-8"))
    from imaks_kg.extract.docdata import sha256_file
    reg = Path(tmp) / "registry.json"
    reg.write_text(json.dumps({"version": 1, "entries": [{"sha256": sha256_file(ex), "file": ex.name}]}), encoding="utf-8")
    return ex, reg


def make_cfg(tmp: Path, example: Path, mode="scoring", models=("m1",), **extract):
    ids = [{"id": m, "thinking_level": "low", "max_output_tokens": 1000, "timeout_s": 120} for m in models]
    data = {"run": {"provider_order": ["gemini"], "run_mode": mode},
            "paths": {"log_dir": str(Path(tmp) / "llm_logs"), "cache_dir": str(Path(tmp) / "llm_cache")},
            "providers": {"gemini": {"models": ids}},
            "extract": dict({"example_file": str(example)}, **extract)}
    return config_from_dict(data)


# ---------------------------------------------------------------- 가짜 응답 만들기
def ev(chunk_id, quote, supports=("condition",), row=None, col=None):
    return {"chunk_id": chunk_id, "source_quote": quote, "supports": list(supports), "table_row": row, "table_col": col}


def rule(cls, cond, act="", sev="", pid=None, sensors=(), targets=(), evidence=()):
    return {"class": cls, "printed_rule_id": pid, "condition": cond, "action": act, "ruleSeverity": sev,
            "sensors": list(sensors), "action_targets": list(targets), "evidence": list(evidence)}


def sent_ids(store, doc_id):
    return [u.chunk.chunk_id for u in make_units(store.chunks_by_doc[doc_id])]


def coverage(store, doc_id, included: dict):
    """included: {chunk_id: [규칙 번호]}. 나머지 청크는 excluded(not_a_rule)."""
    out = []
    for cid in sent_ids(store, doc_id):
        if cid in included:
            out.append({"chunk_id": cid, "coverage_status": "included", "rules": included[cid], "reason": None})
        else:
            out.append({"chunk_id": cid, "coverage_status": "excluded", "rules": [], "reason": "not_a_rule"})
    return out


def chunk_text(store, chunk_id):
    return store.chunk_by_id[chunk_id].text


def rest_after_colon(store, chunk_id):
    t = chunk_text(store, chunk_id)
    return t.split(": ", 1)[1]


def table_cell(store, table_id, row, col):
    return store.tables[table_id].rows[row - 1][col - 1]


def sop001_response(store) -> dict:
    """SOP-001 가짜 응답: 정상 2개 + 인용 불일치 1개 + 허용 목록 밖 ID 1개."""
    c1, c2 = "SOP-001:p1:RULE-ST02-01", "SOP-001:p2:RULE-SRV01-01"
    q1, q2 = rest_after_colon(store, c1), rest_after_colon(store, c2)
    rules = [
        rule("OperationalRule", q1.rstrip("."), "", "", "RULE-ST02-01", ["ST02_SEALING_TMP"], [],
             [ev(c1, q1, ["condition", "sensors", "printed_rule_id"])]),
        rule("OperationalRule", q2.rstrip("."), "", "", "RULE-SRV01-01", ["SRV01_SERVERROOM_TMP"], [],
             [ev(c2, q2, ["condition", "sensors"])]),
        rule("OperationalRule", "invented condition not in text", "", "", None, [], [],
             [ev(c1, "this sentence is not in the chunk", ["condition"])]),
        rule("OperationalRule", "mentions a sensor outside the list", "", "", None, ["ZZ99_NOPE_TMP"], [],
             [ev(c1, q1[:20], ["condition"])]),
    ]
    return {"rules": rules, "coverage": coverage(store, "SOP-001", {c1: [0, 2, 3], c2: [1]})}


def sop003_response(store) -> dict:
    """SOP-003 가짜 응답: 표 셀 인용 1개(정상), 표 범위 밖 1개. printed_rule_id를 null로 두어 seed 정비 규칙과 ID가 겹치지 않게 한다."""
    tid, cid = "SOP-003:p1:table1", "SOP-003:p1:table1:chunk"
    trig, act = table_cell(store, tid, 3, 4), table_cell(store, tid, 3, 5)
    rules = [
        rule("MaintenanceRule", trig, act, "HIGH", None, ["ST02_SEALING_CUR"], ["ST02_SEALING"],
             [ev(cid, trig, ["condition", "sensors"], 3, 4), ev(cid, act, ["action"], 3, 5)]),
        rule("MaintenanceRule", trig, act, "", None, [], [], [ev(cid, act, ["action"], 99, 2)]),
    ]
    return {"rules": rules, "coverage": coverage(store, "SOP-003", {cid: [0, 1]})}


def write_mock_responses(path: Path, store) -> dict:
    resp = {"SOP-001": json.dumps(sop001_response(store), ensure_ascii=False),
            "SOP-003": json.dumps(sop003_response(store), ensure_ascii=False)}
    Path(path).write_text(json.dumps(resp, ensure_ascii=False), encoding="utf-8")
    return resp


# ---------------------------------------------------------------- 가짜 문서 묶음(요청 빌더의 분할 시험용)
def write_fake_docs(base: Path, specs: dict) -> tuple:
    """specs: {doc_id: [(kind, text_or_table, section)]}. 반환: (documents_dir, instances_dir).

    kind: 'text' | 'table'. table은 {'rows': [[...]], 'continued_from': id|None, 'continues_in': id|None, 'caption': str}.
    """
    base = Path(base)
    docs, inst = base / "documents", base / "instances"
    docs.mkdir(parents=True, exist_ok=True)
    inst.mkdir(parents=True, exist_ok=True)
    chunks, tables, pages, manifest = [], [], {}, []
    for doc, items in specs.items():
        page_text = ""
        n_t = n_tb = 0
        for kind, body, section in items:
            if kind == "text":
                n_t += 1
                start = len(page_text)
                page_text += body + "\n"
                chunks.append({"chunk_id": f"{doc}:p1:text{n_t}", "doc_id": doc, "page": 1, "kind": "text", "text": body,
                               "char_start": start, "char_end": start + len(body), "section": section,
                               "table_id": None, "bbox": None, "text_sha256": "0" * 64, "source_file_sha256": "f" * 64})
            else:
                n_tb += 1
                tid = f"{doc}:p1:table{n_tb}"
                rows = body["rows"]
                cells = [{"row": r, "col": c, "bbox": [1.0 + c, 2.0 + r, 3.0 + c, 4.0 + r], "text_raw": v,
                          "text_normalized": v} for r, row in enumerate(rows) for c, v in enumerate(row)]
                tables.append({"table_id": tid, "doc_id": doc, "page": 1, "bbox": [0, 0, 1, 1], "n_rows": len(rows),
                               "n_cols": len(rows[0]), "caption": body.get("caption"),
                               "continued_from": body.get("continued_from"), "continues_in": body.get("continues_in"),
                               "rows_raw": rows, "rows_normalized": rows, "cells": cells})
                chunks.append({"chunk_id": f"{tid}:chunk", "doc_id": doc, "page": 1, "kind": "table", "text": "x",
                               "char_start": 0, "char_end": 1, "section": section, "table_id": tid, "bbox": None,
                               "text_sha256": "0" * 64, "source_file_sha256": "f" * 64})
        pages[doc] = page_text
        manifest.append({"doc_id": doc, "file": f"x/{doc}.pdf", "pages": 1, "file_sha256": "a" * 64})
    (docs / "chunks.jsonl").write_text("".join(json.dumps(c) + "\n" for c in chunks), encoding="utf-8")
    (docs / "tables.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tables), encoding="utf-8")
    (docs / "pages.jsonl").write_text("".join(json.dumps({"doc_id": d, "page": 1, "text_raw": t, "text_normalized": t,
                                                         "char_count": len(t), "char_count_raw": len(t)}) + "\n"
                                              for d, t in pages.items()), encoding="utf-8")
    with (docs / "doc_manifest.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["doc_id", "file", "pages", "file_sha256"], lineterminator="\n")
        w.writeheader()
        w.writerows(manifest)
    (inst / "stations.csv").write_text("identifier,sourceNodeId\nQX01_MIXER,N1\nQX02_PUMP,N2\n", encoding="utf-8")
    (inst / "sensors.csv").write_text("identifier,sensorType,unit\nQX01_MIXER_TRQ,TRQ,kNm\nQX02_PUMP_FLW,FLW,L/h\n",
                                      encoding="utf-8")
    return docs, inst


def tmpdir():
    return tempfile.TemporaryDirectory()
