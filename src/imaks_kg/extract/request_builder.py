"""④ 2단계 요청 빌더. 문서 하나 = 요청 하나(길이 한도를 넘으면 section 경계로 분할, 이어지는 표는 같은 요청).

- 입력: preprocessed/documents 청크·표·쪽, 허용 ID 목록(③), 프롬프트·스키마 파일, 사용자가 쓴 Example 파일.
- Example은 `prompts/example_registry.json`에 파일 SHA-256이 등록돼 있어야 한다(example_check 통과 기록). 없으면 실행 거부.
- 정답 파일과 seed 정비 action 문구는 읽지도 요청에 넣지도 않는다(요청 메타에 false로 기록).
- API는 호출하지 않는다.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from imaks_kg.extract.config import ExtractConfig
from imaks_kg.extract.docdata import (Allowlist, ChunkInfo, DocumentStore, TableInfo, sha256_file, sha256_text)
from imaks_kg.extract.providers.base import LLMRequest
from imaks_kg.settings import REPO_ROOT

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
ROLE_TASK_FILE = PROMPT_DIR / "role_task_v1.txt"
SCHEMA_FILE = PROMPT_DIR / "response_schema_v1.json"
REGISTRY_FILE = PROMPT_DIR / "example_registry.json"
PROMPT_VERSION = "role_task_v1"
TITLE_MAX_CHARS = 30   # 이보다 짧은(미만) 한 줄 텍스트 청크는 다음 청크의 섹션 제목으로 붙인다


class ExampleError(ValueError):
    """Example 파일이 없거나 검증 통과 기록이 없을 때. 메시지는 한국어 안내."""


class SplitError(ValueError):
    """길이 한도를 넘는데 section 경계로도 나눌 수 없을 때. 임의로 자르지 않는다."""


# ---------------------------------------------------------------- Example 게이트
def load_registry(registry_path: Path | None = None) -> dict:
    p = Path(registry_path) if registry_path else REGISTRY_FILE
    if not p.is_file():
        return {"version": 1, "entries": []}
    return json.loads(p.read_text(encoding="utf-8"))


def require_registered_example(example_file, registry_path: Path | None = None, repo_root: Path = REPO_ROOT) -> tuple:
    """(Example 텍스트, SHA-256). 파일이 없거나 레지스트리에 해시가 없으면 ExampleError."""
    if not example_file:
        raise ExampleError("설정 extract.example_file이 비어 있습니다. 사용자가 직접 쓴 Example 파일의 경로를 채우세요"
                           "(이 코드는 Example을 만들지 않습니다).")
    p = Path(example_file)
    if not p.is_absolute():
        p = repo_root / p
    if not p.is_file():
        raise ExampleError(f"Example 파일이 없습니다: {p.name}. 사용자가 쓴 파일을 설정 경로에 두세요.")
    digest = sha256_file(p)
    reg = load_registry(registry_path)
    if digest not in {e.get("sha256") for e in reg.get("entries", [])}:
        raise ExampleError(f"Example 파일({p.name})의 SHA-256이 검증 통과 기록(example_registry.json)에 없습니다. "
                           "`python -m imaks_kg.extract.example_check <Example 파일>`을 먼저 통과해야 하며, "
                           "통과 뒤 파일을 한 글자라도 고치면 다시 검증해야 합니다.")
    return p.read_bytes().decode("utf-8"), digest


# ---------------------------------------------------------------- 청크 단위(제목 병합)
@dataclass
class Unit:
    chunk: ChunkInfo
    titles: list = field(default_factory=list)       # 이 청크에 붙은 제목 청크들
    section: str | None = None                       # 유효 섹션 이름(제목 병합 또는 청크의 section)


def is_title_chunk(c: ChunkInfo) -> bool:
    t = c.text.strip()
    return c.kind == "text" and "\n" not in t and len(t) < TITLE_MAX_CHARS


def make_units(chunks: list) -> list:
    units, pending = [], []
    for c in chunks:
        if is_title_chunk(c):
            pending.append(c)
            continue
        u = Unit(c, pending)
        u.section = " / ".join(t.text.strip() for t in pending) if pending else c.section
        units.append(u)
        pending = []
    if pending:  # 문서 끝의 제목: 붙일 다음 청크가 없으면 따로 보낸다
        for t in pending:
            units.append(Unit(t, [], t.text.strip()))
    return units


# ---------------------------------------------------------------- 표시 형식
def render_table(c: ChunkInfo, tb: TableInfo) -> str:
    lines = [f"[table {tb.table_id}]" + (f" caption: {tb.caption}" if tb.caption else "")]
    if tb.continued_from:
        lines.append(f"(continued from {tb.continued_from}; this fragment's rows are numbered from 1)")
    for r, row in enumerate(tb.rows, 1):
        cells = " ".join(f"[열{k}] {v}" for k, v in enumerate(row, 1))
        lines.append(f"[행 {r}] {cells}")
    return "\n".join(lines)


def render_unit(u: Unit, store: DocumentStore) -> str:
    c = u.chunk
    out = [f"<<chunk {c.chunk_id} | page {c.page}>>"]
    if u.section:
        out.append(f"Section: {u.section}")
    if c.kind == "table":
        tb = store.tables.get(c.table_id or "")
        if tb is None:
            raise ValueError(f"표 정보가 없습니다: {c.table_id} (청크 {c.chunk_id})")
        out.append(render_table(c, tb))
    else:
        out.append(c.text)
    return "\n".join(out)


def estimate_tokens(text: str, chars_per_token: float) -> int:
    return int(math.ceil(len(text) / chars_per_token))


# ---------------------------------------------------------------- 분할
def section_groups(units: list, store: DocumentStore) -> list:
    """section 경계로 묶은 단위 목록. 이어지는 표(continued_from)는 앞 그룹에 붙인다."""
    groups: list = []
    prev_section = None
    for u in units:
        boundary = False
        sec = u.section
        if groups and sec is not None and sec != prev_section:
            boundary = True
        c = u.chunk
        if c.kind == "table":
            tb = store.tables.get(c.table_id or "")
            if tb is not None and tb.continued_from:
                boundary = False
        if boundary or not groups:
            groups.append([])
        groups[-1].append(u)
        if sec is not None:
            prev_section = sec
    return groups


@dataclass
class BuiltRequest:
    doc_id: str
    part: int
    n_parts: int
    request: LLMRequest
    meta: dict
    sent_chunk_ids: list           # coverage가 덮어야 하는 청크(제목 병합 청크 제외)
    merged_title_ids: list
    est_input_tokens: int


def _compose(doc_id, example_text, allowlist, body, part, n_parts) -> str:
    part_note = f" (part {part} of {n_parts}; cover only the chunks in this part)" if n_parts > 1 else ""
    return "\n".join([
        "# EXAMPLE", example_text.rstrip(), "",
        "# ALLOWED ID LIST",
        "Stations (for action_targets): " + ", ".join(allowlist.stations),
        "Sensors (for sensors): " + ", ".join(allowlist.sensors), "",
        f"# DOCUMENT {doc_id}{part_note}", body, "",
        "Return the JSON object only."])


def build_doc_requests(doc_id: str, store: DocumentStore, allowlist: Allowlist, *, role_task: str, schema: dict,
                       example_text: str, example_sha256: str, config: ExtractConfig,
                       requested_model: str = "") -> list:
    chunks = store.chunks_by_doc.get(doc_id)
    if not chunks:
        raise ValueError(f"알 수 없는 문서 ID: {doc_id}")
    units = make_units(chunks)
    blocks = [(u, render_unit(u, store)) for u in units]
    system = role_task
    prompt_sha = sha256_text(role_task)
    limit, cpt = config.max_input_tokens_est, config.chars_per_token

    def total_est(sel) -> int:
        body = "\n\n".join(b for _, b in sel)
        return estimate_tokens(system + _compose(doc_id, example_text, allowlist, body, 1, 1), cpt)

    if total_est(blocks) <= limit:
        parts = [blocks]
    else:
        group_ids = section_groups(units, store)
        by_unit = {id(u): b for u, b in blocks}
        groups = [[(u, by_unit[id(u)]) for u in g] for g in group_ids]
        parts, cur = [], []
        for g in groups:
            if total_est(g) > limit:
                title = g[0][0].section or g[0][0].chunk.chunk_id
                raise SplitError(f"{doc_id}: 섹션 '{title}' 하나가 입력 추정 상한({limit} 토큰)을 넘어 더 나눌 수 없습니다. "
                                 "임의로 자르지 않고 중단합니다. 상한(extract.max_input_tokens_est)을 확인하세요.")
            if cur and total_est(cur + g) > limit:
                parts.append(cur)
                cur = []
            cur = cur + g
        if cur:
            parts.append(cur)
    out = []
    n = len(parts)
    for i, sel in enumerate(parts, 1):
        body = "\n\n".join(b for _, b in sel)
        prompt = _compose(doc_id, example_text, allowlist, body, i, n)
        sent = [u.chunk.chunk_id for u, _ in sel]
        merged = [t.chunk_id for u, _ in sel for t in u.titles]
        step = "extract" if n == 1 else f"extract_part{i}of{n}"
        req = LLMRequest(prompt=prompt, system=system, response_schema=schema, expect_json=True, step_name=step,
                         doc_id=doc_id, prompt_sha256=prompt_sha, example_sha256=example_sha256,
                         answer_key_supplied=False, seed_maintenance_text_supplied=False)
        meta = {"answer_key_supplied": False, "seed_maintenance_text_supplied": False,
                "document_id": doc_id, "part": i, "n_parts": n, "step_name": step,
                "prompt_version": PROMPT_VERSION, "prompt_sha256": prompt_sha, "schema_sha256": req.schema_sha256,
                "example_sha256": example_sha256,
                "input_sha256": req.input_sha256, "document_input_sha256": sha256_text(body),
                "document_pdf_sha256": store.doc_sha256(doc_id), "allowlist_sha256": allowlist.sha256(),
                "requested_model": requested_model, "run_mode": config.run_mode,
                "est_input_tokens": estimate_tokens(system + prompt, cpt),
                "chunk_ids": sent, "merged_title_chunk_ids": merged}
        out.append(BuiltRequest(doc_id, i, n, req, meta, sent, merged, meta["est_input_tokens"]))
    return out


def load_prompt_files() -> tuple:
    """(role_task 텍스트, 스키마 dict). 파일은 prompts/ 아래 고정."""
    return (ROLE_TASK_FILE.read_bytes().decode("utf-8"),
            json.loads(SCHEMA_FILE.read_bytes().decode("utf-8")))


def requested_model_name(config: ExtractConfig) -> str:
    chain = config.chain()
    return f"{chain[0][0].name}/{chain[0][1].id}" if chain else ""


def smallest_doc(store: DocumentStore, doc_ids: list | None = None) -> str:
    """가장 작은 문서(청크 본문 글자 수 합이 가장 적은 것). 동률이면 문서 ID 순."""
    ids = doc_ids or store.doc_ids()
    return sorted(ids, key=lambda d: (sum(len(c.text) for c in store.chunks_by_doc[d]), d))[0]


def build_all(doc_ids: list, store: DocumentStore, allowlist: Allowlist, config: ExtractConfig, *,
              example_text: str, example_sha256: str) -> list:
    role_task, schema = load_prompt_files()
    model = requested_model_name(config)
    out = []
    for d in doc_ids:
        out += build_doc_requests(d, store, allowlist, role_task=role_task, schema=schema, example_text=example_text,
                                  example_sha256=example_sha256, config=config, requested_model=model)
    return out
