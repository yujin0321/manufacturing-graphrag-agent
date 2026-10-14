"""C 입력 선택과 해시 사슬 검사.

선택 규칙(사용자 지시 2026-10-12)
- SOP-001, SOP-003, SOP-004: 모든 청크(rule·table·text)
- SOP-002: 표 밖의 text·rule 청크만(table 청크 제외: 임계값 표는 B가 결정적으로 변환했다)
- 데이터시트(DS-*): LLM 입력이 아니다. conflicts.py(수치 충돌, 결정적)에서만 쓴다.

해시 사슬(B와 같은 방식, 하나라도 틀리면 ExtractError로 멈춤)
1. preprocess_lock.check_chain: PDF 현재 해시 == lock == doc_manifest, 문서 산출물(chunks.jsonl 포함) == lock,
   doc_profile 기록 == 현재 파일, 임계값 파일 == lock, 전처리 코드 == lock
2. 청크 단위: text_sha256 == SHA-256(text), source_file_sha256 == lock의 해당 PDF 해시
3. 청크 위치: text·rule 청크는 쪽 텍스트[char_start:char_end](rule은 줄바꿈→공백)와 같아야 한다
"""
import json

from imaks_kg.common.io_utils import read_csv_rows
from imaks_kg.common.provenance import sha256_file, sha256_text
from imaks_kg.extract.common import ExtractError, read_jsonl
from imaks_kg.kg.preprocess_lock import BPaths, check_chain

ALL_CHUNK_DOCS = ("SOP-001", "SOP-003", "SOP-004")
NO_TABLE_DOCS = ("SOP-002",)
REASON_SOP002_TABLE = "SOP-002 table 청크: 임계값 표는 B(promote_rules)가 결정적으로 변환함(LLM 입력 아님)"
REASON_DATASHEET = "데이터시트: LLM 입력 아님(conflicts.py의 수치 충돌 대조에만 사용)"
REASON_OTHER = "선택 규칙에 없는 문서"


def load_documents(paths: BPaths = None):
    paths = paths or BPaths()
    _, manifest = read_csv_rows(paths.doc_dir / "doc_manifest.csv")
    return {
        "chunks": read_jsonl(paths.doc_dir / "chunks.jsonl"),
        "pages": {(p["doc_id"], p["page"]): p for p in read_jsonl(paths.doc_dir / "pages.jsonl")},
        "tables": {t["table_id"]: t for t in read_jsonl(paths.doc_dir / "tables.jsonl")},
        "manifest": {r["doc_id"]: r for r in manifest},
    }


def page_slice_matches(chunk, page_text):
    """text·rule 청크의 쪽 좌표가 맞는지(table 청크는 직렬화 텍스트라 표 좌표로 따로 검사)."""
    s = page_text[chunk["char_start"]:chunk["char_end"]]
    if chunk["kind"] == "rule":
        s = s.replace("\n", " ")
    return s == chunk["text"]


def chunk_errors(docs, lock_pdfs):
    errors = []
    for c in docs["chunks"]:
        cid = c["chunk_id"]
        if sha256_text(c["text"]) != c["text_sha256"]:
            errors.append(f"{cid}: text_sha256 불일치")
        man = docs["manifest"].get(c["doc_id"])
        if man is None:
            errors.append(f"{cid}: doc_manifest에 {c['doc_id']} 없음")
        elif c["source_file_sha256"] != lock_pdfs.get(man["file"]):
            errors.append(f"{cid}: source_file_sha256이 lock의 PDF 해시와 다름")
        page = docs["pages"].get((c["doc_id"], c["page"]))
        if page is None:
            errors.append(f"{cid}: pages.jsonl에 쪽 없음")
        elif c["kind"] in ("text", "rule") and not page_slice_matches(c, page["text_normalized"]):
            errors.append(f"{cid}: 쪽 텍스트 좌표와 청크 텍스트가 다름")
        if c["kind"] == "table" and c.get("table_id") not in docs["tables"]:
            errors.append(f"{cid}: tables.jsonl에 {c.get('table_id')} 없음")
    return errors


def verify_chain(paths: BPaths = None):
    """해시 사슬을 검사하고 (문서 묶음, lock 파일 해시)를 돌려준다. 틀리면 ExtractError(아무것도 쓰지 않음)."""

    paths = paths or BPaths()
    errors = check_chain(paths)
    if errors:
        raise ExtractError("해시 사슬 검사 실패(실행 중단):\n- " + "\n- ".join(errors))
    lock = json.loads(paths.lock_file.read_text(encoding="utf-8"))
    docs = load_documents(paths)
    errors = chunk_errors(docs, lock.get("input_pdfs", {}))
    if errors:
        raise ExtractError("청크 해시·좌표 검사 실패(실행 중단):\n- " + "\n- ".join(errors))
    return docs, sha256_file(paths.lock_file)


def select_chunks(chunks):
    """(선택 청크 목록, 제외 목록[(chunk_id, 사유)]). 순서는 chunks.jsonl 순서 그대로(결정적)."""
    selected, excluded = [], []
    for c in chunks:
        doc = c["doc_id"]
        if doc in ALL_CHUNK_DOCS:
            selected.append(c)
        elif doc in NO_TABLE_DOCS:
            if c["kind"] == "table":
                excluded.append((c["chunk_id"], REASON_SOP002_TABLE))
            else:
                selected.append(c)
        elif doc.startswith("DS-"):
            excluded.append((c["chunk_id"], REASON_DATASHEET))
        else:
            excluded.append((c["chunk_id"], REASON_OTHER))
    ids = [c["chunk_id"] for c in selected]
    if len(ids) != len(set(ids)):
        raise ExtractError("선택한 청크 ID가 중복됨")
    return selected, excluded
