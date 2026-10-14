"""④ 2단계 공용 입력: 전처리 문서(청크·표·쪽), 문서 목록, 허용 ID 목록(③ 산출물).

- 읽는 것: preprocessed/documents/{chunks,tables,pages}.jsonl, doc_manifest.csv, kg_build/instances/{stations,sensors}.csv의 identifier 열.
- 읽지 않는 것: 정답 파일, seed KG의 정비 규칙 action 문구 파일.
- 표 셀 문자열은 줄바꿈을 공백으로 바꾼 '표시용' 형태 하나만 쓴다(요청에 보이는 글자와 인용 대조가 같은 글자를 보게 하려고).
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from imaks_kg.settings import DOCUMENTS_OUT, KG_BUILD


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def cell_display(text) -> str:
    """표 셀 표시용 문자열: 줄바꿈만 공백으로 바꾼다(그 밖의 글자는 그대로)."""
    return str(text if text is not None else "").replace("\r\n", " ").replace("\n", " ").strip()


@dataclass(frozen=True)
class ChunkInfo:
    chunk_id: str
    doc_id: str
    page: int
    kind: str                 # text | rule | table
    text: str
    char_start: int
    char_end: int
    section: str | None
    table_id: str | None
    text_sha256: str
    source_file_sha256: str


@dataclass
class TableInfo:
    table_id: str
    doc_id: str
    page: int
    n_rows: int
    n_cols: int
    caption: str | None
    continued_from: str | None
    continues_in: str | None
    rows: list                                  # [[표시용 셀 문자열]] 0부터 (행, 열)
    cell_bbox: dict = field(default_factory=dict)   # (row0, col0) -> [x0, y0, x1, y1]
    raw_rows: list = field(default_factory=list)    # 줄바꿈을 지키는 셀 문자열(인용 대조·sourceQuote용; 앞뒤 공백만 제거)


def _read_jsonl(path: Path) -> list:
    out = []
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


class DocumentStore:
    """전처리된 문서 묶음. chunks_by_doc는 chunks.jsonl 파일 순서(= 문서 안 순서)를 그대로 유지한다."""

    def __init__(self, documents_dir: Path = DOCUMENTS_OUT):
        d = Path(documents_dir)
        self.documents_dir = d
        self.chunks_by_doc: dict = {}
        self.chunk_by_id: dict = {}
        for rec in _read_jsonl(d / "chunks.jsonl"):
            c = ChunkInfo(rec["chunk_id"], rec["doc_id"], int(rec["page"]), rec["kind"], rec["text"],
                          int(rec["char_start"]), int(rec["char_end"]), rec.get("section"), rec.get("table_id"),
                          rec.get("text_sha256", ""), rec.get("source_file_sha256", ""))
            self.chunks_by_doc.setdefault(c.doc_id, []).append(c)
            self.chunk_by_id[c.chunk_id] = c
        self.tables: dict = {}
        for rec in _read_jsonl(d / "tables.jsonl"):
            rows = [[cell_display(x) for x in r] for r in rec["rows_normalized"]]
            bbox = {(int(c["row"]), int(c["col"])): c.get("bbox") for c in rec.get("cells", [])}
            self.tables[rec["table_id"]] = TableInfo(rec["table_id"], rec["doc_id"], int(rec["page"]),
                                                     int(rec["n_rows"]), int(rec["n_cols"]), rec.get("caption"),
                                                     rec.get("continued_from"), rec.get("continues_in"), rows, bbox,
                                                     [[str(x if x is not None else "").strip() for x in r]
                                                      for r in rec["rows_normalized"]])
        self.pages: dict = {}
        for rec in _read_jsonl(d / "pages.jsonl"):
            self.pages[(rec["doc_id"], int(rec["page"]))] = rec["text_normalized"]
        self.manifest: dict = {}
        with (d / "doc_manifest.csv").open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                self.manifest[row["doc_id"]] = row

    def doc_ids(self) -> list:
        return list(self.chunks_by_doc)

    def doc_sha256(self, doc_id: str) -> str:
        return self.manifest[doc_id]["file_sha256"]


@dataclass(frozen=True)
class Allowlist:
    stations: tuple
    sensors: tuple

    def sha256(self) -> str:
        return sha256_text(json.dumps({"stations": list(self.stations), "sensors": list(self.sensors)},
                                      ensure_ascii=False, sort_keys=True))


def _identifier_column(path: Path) -> tuple:
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        if "identifier" not in (r.fieldnames or []):
            raise ValueError(f"{Path(path).name}에 identifier 열이 없습니다.")
        return tuple(row["identifier"] for row in r if row["identifier"])


def load_allowlist(instances_dir: Path | None = None) -> Allowlist:
    """③ 산출물의 Station·Sensor identifier만 읽는다(다른 열은 읽지 않는다)."""
    d = Path(instances_dir) if instances_dir else KG_BUILD / "instances"
    return Allowlist(_identifier_column(d / "stations.csv"), _identifier_column(d / "sensors.csv"))
