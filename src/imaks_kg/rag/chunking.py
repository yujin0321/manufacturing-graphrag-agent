"""Table-row chunking for retrieval v3.

The frozen ``chunks.jsonl`` is never rewritten. Row chunks are derived in
memory from table chunks, so every row keeps a pointer to its parent chunk
(the unit the existing answer keys and graders use).

Why: in v1 every retrieval miss was a table chunk (e.g. the 8-row SOP-003
maintenance table ranked 18th/27th) because one embedding has to represent
eight unrelated rules.
"""
from __future__ import annotations

import hashlib

ROW_SEPARATOR = "#r"


def row_chunk_id(parent_id: str, row_number: int) -> str:
    """Row numbers are 1-based data rows (the table title line is row 0)."""
    return f"{parent_id}{ROW_SEPARATOR}{row_number}"


def parent_of(chunk_id: str) -> str:
    return chunk_id.split(ROW_SEPARATOR, 1)[0]


def split_table_rows(records: list[dict]) -> list[dict]:
    """Replace each table chunk with one chunk per data row.

    The table title line is repeated in every row so that a row stays
    self-describing ("ST02_SEALING Thresholds / Sensor: CUR; ...").
    Non-table chunks pass through unchanged.
    """
    out = []
    for record in records:
        lines = [line for line in record["text"].splitlines() if line.strip()]
        if record.get("kind") != "table" or len(lines) < 2:
            out.append({**record, "parent_chunk_id": record["chunk_id"], "row_number": None})
            continue
        title, rows = lines[0], lines[1:]
        for number, row in enumerate(rows, start=1):
            text = f"{title}\n{row}"
            out.append({
                **record,
                "chunk_id": row_chunk_id(record["chunk_id"], number),
                "parent_chunk_id": record["chunk_id"],
                "row_number": number,
                "text": text,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            })
    ids = [r["chunk_id"] for r in out]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate row chunk IDs")
    return out


def provenance_row_number(row_index: str | int | None) -> int | None:
    """KG provenance ``rowIndex`` counts the header row as 1, data rows from 2."""
    if row_index in (None, ""):
        return None
    number = int(row_index) - 1
    return number if number >= 1 else None
