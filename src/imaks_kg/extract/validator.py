"""④ 2단계 응답 파서·검증기 (설계서 §5의 8단계).

원칙: LLM은 규칙 내용과 인용만 말한다. 쪽·문자 위치·표 좌표·해시는 여기서 코드가 계산한다.
- 차단 오류(응답 전체가 쓸모없음): JSON 아님, 스키마 불량. 이 경우 mark_validated를 부르지 않는다.
- 규칙별 플래그: evidence_not_found, id_not_in_allowlist, table_position_out_of_range, duplicate_identifier,
  position_unresolved, empty_content, coverage_gap. 비차단 정보 플래그: quote_whitespace_adjusted, split_from_printed_id. 점수용 예측에서는 숨기지 않고 KG 적재용(rules_valid)에서만 제외한다.
- 같은 응답은 항상 같은 결과를 낸다(난수·시각 미사용).
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field

from imaks_kg.extract.docdata import Allowlist, ChunkInfo, DocumentStore, TableInfo, sha256_text

FLAG_EVIDENCE = "evidence_not_found"
FLAG_ID = "id_not_in_allowlist"
FLAG_TABLE = "table_position_out_of_range"
FLAG_DUP = "duplicate_identifier"
FLAG_POS = "position_unresolved"
FLAG_EMPTY = "empty_content"
FLAG_COVERAGE = "coverage_gap"
FLAG_WS = "quote_whitespace_adjusted"     # 비차단 정보 플래그: 인용이 공백만 달라 일치(KG 적재 제외 사유 아님)
FLAG_SPLIT = "split_from_printed_id"      # 비차단 정보 플래그: 중복 인쇄 ID에 접미사를 붙임(KG 적재 제외 사유 아님)

# KG 적재(rules_valid)에서 제외하는 플래그. coverage_gap은 사람 검토 대상으로만 표시한다.
EXCLUDING_FLAGS = (FLAG_EVIDENCE, FLAG_ID, FLAG_TABLE, FLAG_DUP, FLAG_POS, FLAG_EMPTY)
INFO_FLAGS = (FLAG_WS, FLAG_SPLIT)
ALL_FLAGS = EXCLUDING_FLAGS + (FLAG_COVERAGE,) + INFO_FLAGS
VALIDATOR_NAME = "extract_validator_v1"


# ---------------------------------------------------------------- 최소 JSON 스키마 검사기(추가 패키지 없이)
def _type_ok(value, t: str) -> bool:
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    if t == "string":
        return isinstance(value, str)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "null":
        return value is None
    raise ValueError(f"지원하지 않는 스키마 type: {t}")


def schema_errors(value, schema: dict, path: str = "$", limit: int = 30) -> list:
    """스키마 위반 목록(경로와 이유). 지원: type, enum, required, properties, additionalProperties=false,
    items, minItems, minimum."""
    errs: list = []

    def walk(v, sc, p):
        if len(errs) >= limit:
            return
        t = sc.get("type")
        if t is not None:
            types = t if isinstance(t, list) else [t]
            if not any(_type_ok(v, x) for x in types):
                errs.append(f"{p}: 형식이 {types}이(가) 아닙니다")
                return
        if "enum" in sc and v not in sc["enum"]:
            errs.append(f"{p}: 허용된 값이 아닙니다")
            return
        if isinstance(v, dict):
            for k in sc.get("required", []):
                if k not in v:
                    errs.append(f"{p}: 필수 항목 '{k}'가 없습니다")
            props = sc.get("properties", {})
            if sc.get("additionalProperties") is False:
                for k in v:
                    if k not in props:
                        errs.append(f"{p}: 스키마에 없는 항목 '{k}'")
            for k, sub in props.items():
                if k in v:
                    walk(v[k], sub, f"{p}.{k}")
        elif isinstance(v, list):
            if "minItems" in sc and len(v) < sc["minItems"]:
                errs.append(f"{p}: 항목이 {sc['minItems']}개 이상이어야 합니다")
            if "items" in sc:
                for i, x in enumerate(v):
                    walk(x, sc["items"], f"{p}[{i}]")
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            if "minimum" in sc and v < sc["minimum"]:
                errs.append(f"{p}: {sc['minimum']} 이상이어야 합니다")

    walk(value, schema, path)
    return errs


# ---------------------------------------------------------------- 인용 위치 계산
# 인용 일치 정의(2026-10-14 확정): 인용과 대상 텍스트를 각각 '연속된 공백류(스페이스·탭·줄바꿈·비분리 공백 등
# str.isspace()가 참인 글자)를 공백 하나로' 바꾸고 앞뒤 공백을 지운 뒤 비교한다. 그 밖(대소문자·구두점·숫자·단어)은 엄격하다.
# 일치하면 정규화 위치를 원문 위치로 되돌려 매핑하고, 저장하는 sourceQuote·textSha256은 원문에서 잘라 낸 실제 구간으로 만든다.
def collapse_ws(text: str) -> tuple:
    """(정규화 문자열, 정규화 위치 -> 원문 위치 목록). 공백 run은 그 run의 첫 글자 위치로 매핑한다."""
    out: list = []
    idx: list = []
    pending = None
    for i, ch in enumerate(text):
        if ch.isspace():
            if out and pending is None:
                pending = i
        else:
            if pending is not None:
                out.append(" ")
                idx.append(pending)
                pending = None
            out.append(ch)
            idx.append(i)
    return "".join(out), idx


def _find_all(text: str, sub: str) -> list:
    """겹치는 경우를 포함한 모든 시작 위치."""
    hits, i = [], text.find(sub)
    while i != -1:
        hits.append(i)
        i = text.find(sub, i + 1)
    return hits


def _orig_span(idx: list, start: int, length: int) -> tuple:
    """정규화 구간 [start, start+length)에 해당하는 원문 구간 [s, e). 정규화 구간은 공백으로 시작·끝나지 않는다."""
    return idx[start], idx[start + length - 1] + 1


def _ws_equal(a: str, b: str) -> bool:
    """길이가 같고 서로 다른 글자는 둘 다 공백류인 경우만 같다고 본다(줄바꿈 vs 공백)."""
    return len(a) == len(b) and all(x == y or (x.isspace() and y.isspace()) for x, y in zip(a, b))


def _bbox_str(box) -> str | None:
    if not box:
        return None
    return ",".join(f"{v:g}" if isinstance(v, (int, float)) else str(v) for v in box)


def resolve_evidence(ev: dict, chunk: ChunkInfo, store: DocumentStore, doc_pdf_sha: str) -> tuple:
    """(플래그 [(flag, detail)], 출처 dict). 인용이 청크에 없으면 출처는 None이고 위치를 계산하지 않는다.
    출처의 sourceQuote·textSha256은 원문에서 잘라 낸 구간(찾은 경우)이다. 모델이 준 인용은 호출자가 model_quote로 보존한다."""
    quote = ev["source_quote"]
    flags: list = []
    base = {"sourceKind": "document", "chunkId": chunk.chunk_id, "page": chunk.page, "sourceQuote": quote,
            "textSha256": sha256_text(quote), "documentSha256": doc_pdf_sha, "resolved": False}
    row, col = ev.get("table_row"), ev.get("table_col")
    if not quote.strip():
        return [(FLAG_EVIDENCE, "인용이 비어 있습니다")], None
    nq, _ = collapse_ws(quote)

    def set_segment(seg: str) -> None:
        base["sourceQuote"], base["textSha256"] = seg, sha256_text(seg)
        if seg != quote:
            flags.append((FLAG_WS, "인용이 원문과 공백(줄바꿈·연속 공백·앞뒤 공백)만 달라 원문 구간으로 바꿔 저장했습니다"))

    if chunk.kind != "table":
        if row is not None or col is not None:
            flags.append((FLAG_TABLE, "표가 아닌 청크에 표 좌표가 있습니다"))
        nt, tidx = collapse_ws(chunk.text)
        hits = _find_all(nt, nq)
        if not hits:
            flags.append((FLAG_EVIDENCE, "인용이 청크 원문에 (공백 정규화 후에도) 없습니다"))
            return flags, None
        page_text = store.pages.get((chunk.doc_id, chunk.page))
        if len(hits) != 1:
            flags.append((FLAG_POS, f"인용이 청크 안에 {len(hits)}번 나와 위치를 하나로 정할 수 없습니다"))
            return flags, base
        s, e = _orig_span(tidx, hits[0], len(nq))
        if page_text is None or not _ws_equal(page_text[chunk.char_start:chunk.char_end], chunk.text):
            flags.append((FLAG_POS, "청크와 쪽 텍스트가 글자 단위로 대응하지 않습니다"))
            set_segment(chunk.text[s:e])
            return flags, base
        cs = chunk.char_start + s
        base.update({"charStart": cs, "charEnd": chunk.char_start + e, "resolved": True})
        set_segment(page_text[cs:chunk.char_start + e])
        return flags, base

    # ---- 표 청크 (셀 텍스트 기준)
    tb: TableInfo | None = store.tables.get(chunk.table_id or "")
    if tb is None:
        return [(FLAG_POS, "표 정보를 찾지 못했습니다")], base
    rows = tb.raw_rows or tb.rows
    cell_n = [[collapse_ws(v) for v in rw] for rw in rows]
    joined = [" | ".join(r) for r in rows]
    joined_n = [collapse_ws(j) for j in joined]
    cell_hits = [(r, c) for r, rw in enumerate(cell_n) for c, (nv, _) in enumerate(rw) if nq in nv]
    row_hits = [r for r, (nj, _) in enumerate(joined_n) if nq in nj]
    bad = []
    if row is not None and not 1 <= row <= tb.n_rows:
        bad.append(f"행 {row}이(가) 표 범위(1~{tb.n_rows}) 밖입니다")
    if col is not None and not 1 <= col <= tb.n_cols:
        bad.append(f"열 {col}이(가) 표 범위(1~{tb.n_cols}) 밖입니다")
    if col is not None and row is None:
        bad.append("열만 있고 행이 없습니다")
    for b in bad:
        flags.append((FLAG_TABLE, b))
    if not cell_hits and not row_hits:
        flags.append((FLAG_EVIDENCE, "인용이 표 셀 또는 한 행의 셀 이음(' | ')에 (공백 정규화 후에도) 없습니다"))
        return flags, None
    if bad:
        return flags, base

    def cell_segment(r0, c0) -> str:
        nv, vidx = cell_n[r0][c0]
        s, e = _orig_span(vidx, nv.find(nq), len(nq))
        return rows[r0][c0][s:e]

    def done(r0, c0, seg):
        base.update({"tableId": tb.table_id, "rowIndex": r0 + 1, "colIndex": c0 + 1,
                     "bbox": _bbox_str(tb.cell_bbox.get((r0, c0))), "resolved": True})
        set_segment(seg)
        return flags, base

    def start_col(r0):
        """(시작 열, 원문 구간) 또는 None."""
        nj, jidx = joined_n[r0]
        hs = _find_all(nj, nq)
        if len(hs) != 1:
            return None
        s, e = _orig_span(jidx, hs[0], len(nq))
        off = 0
        for c0, v in enumerate(rows[r0]):
            if off <= s < off + len(v):
                return c0, joined[r0][s:e]
            off += len(v) + 3
        return None

    if row is not None and col is not None:
        if nq in cell_n[row - 1][col - 1][0]:
            return done(row - 1, col - 1, cell_segment(row - 1, col - 1))
        flags.append((FLAG_POS, "인용이 지정한 셀 안에 없습니다"))
        return flags, base
    if row is not None:
        sc = start_col(row - 1) if nq in joined_n[row - 1][0] else None
        if sc is None:
            flags.append((FLAG_POS, "지정한 행에서 인용의 시작 열을 하나로 정할 수 없습니다"))
            return flags, base
        return done(row - 1, sc[0], sc[1])
    if len(cell_hits) == 1:
        return done(*cell_hits[0], cell_segment(*cell_hits[0]))
    if not cell_hits and len(row_hits) == 1:
        sc = start_col(row_hits[0])
        if sc is not None:
            return done(row_hits[0], sc[0], sc[1])
    flags.append((FLAG_POS, "표 좌표가 없고 인용이 여러 곳에 맞거나 위치를 하나로 정할 수 없습니다"))
    return flags, base


# ---------------------------------------------------------------- 결과 구조
@dataclass
class ValidationResult:
    doc_id: str
    part: int = 1
    accepted: bool = False               # JSON·스키마 통과 + 차단 오류 없음 -> 1단계 캐시 mark_validated 대상
    blocking_errors: list = field(default_factory=list)
    rules: list = field(default_factory=list)
    doc_flags: list = field(default_factory=list)   # 문서 수준 플래그(coverage_gap 등)
    n_chunks_sent: int = 0


def rule_is_valid_for_kg(rule: dict) -> bool:
    return not (set(rule.get("flags", [])) & set(EXCLUDING_FLAGS))


def _add(rule: dict, flag: str, detail: str, evidence_index=None) -> None:
    if flag not in rule["flags"]:
        rule["flags"].append(flag)
    item = {"flag": flag, "evidenceIndex": evidence_index, "detail": detail}
    if item not in rule["flag_details"]:
        rule["flag_details"].append(item)


def validate_response(text: str, *, doc_id: str, store: DocumentStore, allowlist: Allowlist, sent_chunk_ids: list,
                      merged_title_ids: list = (), schema: dict, part: int = 1, model_info: dict | None = None
                      ) -> ValidationResult:
    res = ValidationResult(doc_id, part, n_chunks_sent=len(sent_chunk_ids))
    info = model_info or {}
    # 1) JSON 파싱, 스키마
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        res.blocking_errors.append("json_parse_error: 응답이 JSON으로 해석되지 않습니다")
        return res
    errs = schema_errors(data, schema)
    if errs:
        res.blocking_errors += [f"schema_error: {e}" for e in errs]
        return res
    res.accepted = True

    visible = set(sent_chunk_ids) | set(merged_title_ids)
    doc_sha = store.doc_sha256(doc_id)
    stations, sensors = set(allowlist.stations), set(allowlist.sensors)
    counters: Counter = Counter()
    referenced: set = set()
    cov = data["coverage"]

    # 7) coverage: 모든 청크를 덮는지, 규칙 번호가 실제 규칙을 가리키는지
    n_rules = len(data["rules"])
    seen = Counter(c["chunk_id"] for c in cov)
    for cid in sent_chunk_ids:
        if seen[cid] == 0:
            res.doc_flags.append({"flag": FLAG_COVERAGE, "chunkId": cid, "detail": "coverage에 이 청크가 없습니다"})
        elif seen[cid] > 1:
            res.doc_flags.append({"flag": FLAG_COVERAGE, "chunkId": cid, "detail": "coverage에 이 청크가 여러 번 있습니다"})
    for c in cov:
        if c["chunk_id"] not in set(sent_chunk_ids):
            res.doc_flags.append({"flag": FLAG_COVERAGE, "chunkId": c["chunk_id"],
                                  "detail": "요청에 보낸 적 없는 청크가 coverage에 있습니다"})
        bad_idx = [i for i in c["rules"] if i >= n_rules]
        if bad_idx:
            res.doc_flags.append({"flag": FLAG_COVERAGE, "chunkId": c["chunk_id"],
                                  "detail": f"규칙 번호 {bad_idx}이(가) 실제 규칙 수({n_rules})를 벗어납니다"})
        if c["coverage_status"] == "included" and not c["rules"]:
            res.doc_flags.append({"flag": FLAG_COVERAGE, "chunkId": c["chunk_id"],
                                  "detail": "included인데 규칙 번호가 없습니다"})
        if c["coverage_status"] == "excluded" and not c["reason"]:
            res.doc_flags.append({"flag": FLAG_COVERAGE, "chunkId": c["chunk_id"],
                                  "detail": "excluded인데 이유 코드가 없습니다"})
        referenced |= {i for i in c["rules"] if i < n_rules}

    for idx, raw in enumerate(data["rules"]):
        printed = raw["printed_rule_id"].strip() if isinstance(raw["printed_rule_id"], str) else None
        printed = printed or None
        rule = {"document_id": doc_id, "part": part, "rule_index": idx, "printed_rule_id": printed,
                "class": raw["class"], "condition": raw["condition"], "action": raw["action"],
                "ruleSeverity": raw["ruleSeverity"], "sensors": list(raw["sensors"]),
                "action_targets": list(raw["action_targets"]), "evidence": [], "flags": [], "flag_details": [],
                "extractionMethod": "LLM", "model": info.get("model", ""), "provider": info.get("provider", ""),
                "response_sha256": info.get("response_sha256", ""), "call_id": info.get("call_id", "")}
        # 2·4·5) 인용 대조, 표 범위, 위치·해시 계산
        for ei, ev in enumerate(raw["evidence"]):
            chunk = store.chunk_by_id.get(ev["chunk_id"])
            entry = {"chunk_id": ev["chunk_id"], "source_quote": ev["source_quote"],
                     "model_quote": ev["source_quote"], "supports": list(ev["supports"]),
                     "table_row": ev["table_row"], "table_col": ev["table_col"], "provenance": None}
            if chunk is None or chunk.doc_id != doc_id or ev["chunk_id"] not in visible:
                _add(rule, FLAG_EVIDENCE, "이 요청에 보낸 이 문서의 청크가 아닙니다", ei)
            else:
                fl, prov = resolve_evidence(ev, chunk, store, doc_sha)
                for f, d in fl:
                    _add(rule, f, d, ei)
                entry["provenance"] = prov
                if prov is not None:   # source_quote = 원문에서 잘라 낸 구간, model_quote = 모델이 준 인용(감사용)
                    entry["source_quote"] = prov["sourceQuote"]
            rule["evidence"].append(entry)
        # 3) 허용 ID 목록
        out_s = [x for x in rule["sensors"] if x not in sensors]
        out_t = [x for x in rule["action_targets"] if x not in stations]
        if out_s or out_t:
            _add(rule, FLAG_ID, f"목록 밖 sensors {len(out_s)}개, action_targets {len(out_t)}개")
        if not rule["condition"].strip() and not rule["action"].strip():
            _add(rule, FLAG_EMPTY, "condition과 action이 모두 비어 있습니다(평가기가 읽을 수 없어 점수 대상에서 뺍니다)")
        if idx not in referenced:
            _add(rule, FLAG_COVERAGE, "어느 coverage 항목도 이 규칙 번호를 가리키지 않습니다")
        # 6) identifier
        if printed:
            rule["identifier"], rule["identifier_source"] = printed, "printed"
        else:
            first = raw["evidence"][0]["chunk_id"] if raw["evidence"] else "nochunk"
            local = first.split(":", 1)[1] if first.startswith(doc_id + ":") else first
            counters[(doc_id, first)] += 1
            rule["identifier"] = f"{doc_id}:{local}:{counters[(doc_id, first)]}"
            rule["identifier_source"] = "assigned"
        res.rules.append(rule)
    return res


def apply_identifier_suffixes(rules: list, reserved=()) -> int:
    """같은 문서 안에서 인쇄 ID가 이미 쓰였으면 두 번째부터 '<ID>-2', '<ID>-3'을 identifier로 쓴다(첫 규칙은 그대로).

    접미사 후보가 다른 identifier(모든 규칙의 현재 identifier, reserved = ③ seed 노드 identifier 등)와 겹치면 번호를 올린다.
    printed_rule_id는 바꾸지 않는다. 접미사가 붙은 규칙에 split_from_printed_id를 붙이고 그 수를 돌려준다.
    다른 문서의 같은 인쇄 ID는 건드리지 않는다(남으면 apply_duplicate_flags가 표시). 규칙 목록 순서가 같으면 결과도 같다."""
    taken = {r["identifier"] for r in rules} | set(reserved)
    seen: set = set()
    n = 0
    for r in rules:
        if r.get("identifier_source") != "printed":
            continue
        key = (r["document_id"], r["printed_rule_id"])
        if FLAG_SPLIT in r["flags"]:   # 이미 접미사를 받은 규칙(다시 불러도 결과가 같다)
            seen.add(key)
            continue
        if key not in seen:
            seen.add(key)
            continue
        base_id, k = r["printed_rule_id"], 2
        while f"{base_id}-{k}" in taken:
            k += 1
        r["identifier"] = f"{base_id}-{k}"
        taken.add(r["identifier"])
        _add(r, FLAG_SPLIT, f"같은 문서에 인쇄 ID '{base_id}'가 이미 있어 identifier를 '{r['identifier']}'로 구분했습니다")
        n += 1
    return n


def apply_duplicate_flags(rules: list) -> int:
    """실행 전체에서 identifier가 둘 이상인 규칙 모두에 duplicate_identifier를 붙인다. 붙인 규칙 수를 돌려준다."""
    cnt = Counter(r["identifier"] for r in rules)
    n = 0
    for r in rules:
        if cnt[r["identifier"]] > 1:
            _add(r, FLAG_DUP, f"같은 identifier가 {cnt[r['identifier']]}개 규칙에 있습니다")
            n += 1
    return n
