"""LLM 응답 자동 검사와 Provenance 좌표 계산(결정적).

항목마다 순서대로 검사하고 처음 걸린 사유 하나로 거부한다(rejected.csv에 사유와 원본 항목을 남김).
1. schema: 최상위가 {"rules": [...]}만 있는 객체인지, 항목이 RuleItem(추가 키 금지, 타입 엄격)에 맞는지
2. sensor_not_in_list / station_not_in_list: seed의 센서 22개·공정 9개 목록 밖 ID
3. quote_empty / quote_not_in_chunk: sourceQuote가 청크 텍스트에 글자 그대로 없음
4. rule_id_not_in_chunk: ruleIdInText가 청크 텍스트에 글자 그대로 없음(만든 ID 금지)
5. rule_severity_not_in_chunk: ruleSeverity가 청크 텍스트에 글자 그대로 없음(원문에 없으면 null이어야 함)
6. 좌표: text·rule 청크는 쪽 좌표(charStart = 청크 char_start + 청크 안 위치, charEnd = charStart + 길이)를 쪽 텍스트와
   대조한다(rule 청크는 쪽 줄바꿈이 공백으로 바뀐 텍스트라 줄바꿈→공백으로 비교). table 청크의 텍스트는 표 행을
   "열: 값; …"으로 직렬화한 것이라 쪽 문자 위치가 없다. 그래서 인용이 놓인 표 행·열을 찾아 표 좌표(tableId, rowIndex,
   colIndex, bbox)를 쓴다. 인용이 두 행 이상이나 머리 줄에 걸치면 quote_spans_table_rows로 거부한다.
textSha256 = SHA-256(sourceQuote).

통과한 항목의 후보 ID: <chunk_id>:r<n>, n은 청크 안 인용 시작 위치(같으면 끝 위치, 항목 순서) 순으로 1부터.
"""
import json

from pydantic import ValidationError

from imaks_kg.common.provenance import sha256_text
from imaks_kg.extract.schema import ITEM_FIELDS, RuleItem

REJECT_FIELDS = ("chunk_id", "item_index", "reason_code", "reason", "item_json")


def _bbox_str(boxes):
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    return ",".join(repr(float(v)) for v in (x0, y0, x1, y1))


def table_layout(chunk, table, parent):
    """표 청크 텍스트에서 각 데이터 행·열 값의 위치. 전처리의 직렬화(table_to_text)를 다시 계산해 대조한다.
    맞지 않으면 None(그 청크의 표 인용은 모두 거부된다)."""
    hdr = (parent or table)["rows_normalized"][0]
    body = range(0, table["n_rows"]) if parent else range(1, table["n_rows"])
    head = f"[{table['table_id']}]"
    if table.get("caption"):
        head += f" {table['caption']}"
    if parent:
        head += f" (continued from {parent['table_id']})"
    text = chunk["text"]
    if not text.startswith(head + ("\n" if len(body) else "")):
        return None
    pos, rows = len(head) + 1, []
    for r in body:
        vals = table["rows_normalized"][r]
        cur, segs = pos, []
        for ci, (h, v) in enumerate(zip(hdr, vals)):
            if ci:
                cur += 2
            start = cur
            cur += len(h) + 2 + len(v)
            segs.append({"col": ci, "start": start, "end": cur})
        line = "; ".join(f"{h}: {v}" for h, v in zip(hdr, vals))
        if text[pos:cur] != line:
            return None
        rows.append({"row": r, "start": pos, "end": cur, "segs": segs})
        pos = cur + 1
    if pos - 1 != len(text):
        return None
    return {"head_end": len(head), "rows": rows}


def table_coords(chunk, docs, off, length):
    table = docs["tables"][chunk["table_id"]]
    parent = docs["tables"].get(table.get("continued_from")) if table.get("continued_from") else None
    lay = table_layout(chunk, table, parent)
    if lay is None:
        return None, "표 청크 텍스트를 표 행으로 되짚을 수 없음"
    qs, qe = off, off + length
    rows = [r for r in lay["rows"] if r["start"] <= qs and qe <= r["end"]]
    if len(rows) != 1:
        return None, "인용이 표의 한 데이터 행 안에 있지 않음(머리 줄 또는 여러 행에 걸침)"
    row = rows[0]
    cols = [s["col"] for s in row["segs"] if s["start"] < qe and qs < s["end"]]
    if not cols:
        return None, "인용이 표 셀 값과 겹치지 않음"
    cells = {(c["row"], c["col"]): c for c in table["cells"]}
    boxes = [cells[(row["row"], c)]["bbox"] for c in cols]
    return {"tableId": table["table_id"], "rowIndex": row["row"] + 1, "colIndex": [c + 1 for c in cols],
            "bbox": _bbox_str(boxes)}, ""


def text_coords(chunk, docs, off, quote):
    page_text = docs["pages"][(chunk["doc_id"], chunk["page"])]["text_normalized"]
    cs = chunk["char_start"] + off
    ce = cs + len(quote)
    s = page_text[cs:ce]
    if chunk["kind"] == "rule":
        s = s.replace("\n", " ")
    if s != quote:
        return None, f"쪽 좌표 [{cs}:{ce}]의 텍스트가 인용과 다름"
    return {"charStart": cs, "charEnd": ce}, ""


def _reject(chunk_id, idx, code, reason, item):

    return {"chunk_id": chunk_id, "item_index": idx, "reason_code": code, "reason": reason,
            "item_json": json.dumps(item, ensure_ascii=False, sort_keys=True)}


def validate_item(item, chunk, docs, sensor_ids, station_ids):
    """(후보 dict, None) 또는 (None, (사유 코드, 사유))."""
    try:
        parsed = RuleItem.model_validate(item)
    except ValidationError as e:
        msgs = "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['type']}" for err in e.errors())
        return None, ("schema", f"스키마 위반: {msgs}")
    d = parsed.as_dict()
    bad = [s for s in d["sensors"] if s not in sensor_ids]
    if bad:
        return None, ("sensor_not_in_list", f"센서 목록 밖: {bad}")
    bad = [s for s in d["targetStations"] if s not in station_ids]
    if bad:
        return None, ("station_not_in_list", f"공정 목록 밖: {bad}")
    text, quote = chunk["text"], d["sourceQuote"]
    if quote.strip() == "":
        return None, ("quote_empty", "sourceQuote가 비어 있음")
    off = text.find(quote)
    if off < 0:
        return None, ("quote_not_in_chunk", "sourceQuote가 청크 원문에 글자 그대로 없음")
    if d["ruleIdInText"] is not None and d["ruleIdInText"] not in text:
        return None, ("rule_id_not_in_chunk", f"ruleIdInText {d['ruleIdInText']!r}가 청크 원문에 없음")
    if d["ruleSeverity"] is not None and d["ruleSeverity"] not in text:
        return None, ("rule_severity_not_in_chunk", f"ruleSeverity {d['ruleSeverity']!r}가 청크 원문에 없음")
    if chunk["kind"] == "table":
        coords, why = table_coords(chunk, docs, off, len(quote))
        if coords is None:
            return None, ("quote_spans_table_rows", why)
    else:
        coords, why = text_coords(chunk, docs, off, quote)
        if coords is None:
            return None, ("page_coordinate_mismatch", why)
    prov = {
        "doc_id": chunk["doc_id"], "page": chunk["page"], "chunk_id": chunk["chunk_id"], "chunk_kind": chunk["kind"],
        "chunk_text_sha256": chunk["text_sha256"], "source_file_sha256": chunk["source_file_sha256"],
        "offset_in_chunk": off, "sourceQuote": quote, "textSha256": sha256_text(quote),
        "quote_occurrences": text.count(quote),
    }
    prov.update(coords)
    cand = {k: d[k] for k in ITEM_FIELDS}
    cand.update({"chunk_id": chunk["chunk_id"], "doc_id": chunk["doc_id"], "page": chunk["page"],
                 "provenance": prov})
    return cand, None


def validate_response(call_result, chunk, docs, sensor_ids, station_ids):
    """청크 하나의 호출 결과 → (후보 목록, 거부 목록). 후보에는 candidate_id와 호출 정보가 붙는다."""
    cid = chunk["chunk_id"]
    if not call_result.ok:
        return [], [_reject(cid, -1, "call_failed", f"호출 실패: {call_result.failure}", {})]
    data = call_result.parsed
    if not isinstance(data, dict) or set(data) != {"rules"} or not isinstance(data["rules"], list):
        return [], [_reject(cid, -1, "schema", "스키마 위반: 최상위는 {\"rules\": [...]}만 허용",
                            data if isinstance(data, (dict, list)) else {"value": str(data)})]
    cands, rejects = [], []
    for i, item in enumerate(data["rules"]):
        cand, err = validate_item(item, chunk, docs, sensor_ids, station_ids)
        if err:
            rejects.append(_reject(cid, i, err[0], err[1], item))
            continue
        cand["item_index"] = i
        cand["served_model"] = call_result.served_model
        cand["fallback_used"] = call_result.fallback_used
        cand["request_id"] = call_result.request_id
        cands.append(cand)
    cands.sort(key=lambda c: (c["provenance"]["offset_in_chunk"],
                              c["provenance"]["offset_in_chunk"] + len(c["sourceQuote"]), c["item_index"]))
    for n, c in enumerate(cands, 1):
        c["candidate_id"] = f"{cid}:r{n}"
    return cands, rejects


def revalidate(cand, docs, chunks_by_id, sensor_ids, station_ids):
    """검토에서 고친 값을 같은 검사로 다시 확인한다. (새 후보, None) 또는 (None, (코드, 사유))."""
    item = {k: cand[k] for k in ITEM_FIELDS}
    new, err = validate_item(item, chunks_by_id[cand["chunk_id"]], docs, sensor_ids, station_ids)
    if err:
        return None, err
    for k in ("item_index", "served_model", "fallback_used", "request_id", "candidate_id"):
        new[k] = cand[k]
    return new, None
