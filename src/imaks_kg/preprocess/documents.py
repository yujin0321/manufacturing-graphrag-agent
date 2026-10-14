"""SOP·데이터시트 PDF 전처리 (pdfplumber만 사용, 임베딩·LLM 호출 없음).

실행: PYTHONPATH=src .venv/Scripts/python.exe -m imaks_kg.preprocess.documents

- 입력(읽기 전용): imaks_data/rules/*.pdf, imaks_data/datasheets/*.pdf
- 원본 텍스트는 text_raw / rows_raw에 그대로 두고, 정규화본은 따로 만든다.
- 기호 폰트(Symbol, ZapfDingbats) 글자만 코드로 매핑한다. 일반 글꼴 글자는 건드리지 않는다.
  pdfminer는 Symbol 폰트의 바이트를 StandardEncoding 글리프 이름으로 풀어서 유니코드를 내놓는다
  (예: 바이트 0xAE -> 'fi' 합자). 그래서 (유니코드 -> 원래 바이트) 역변환 후 Symbol 코드표로 바꾼다.
"""
import difflib
import json
import re
import sys
from collections import defaultdict

import pdfplumber
from pdfplumber.utils.text import WordExtractor
from pdfplumber.utils import cluster_objects
from pdfplumber.utils.text import get_line_cluster_key

from imaks_kg.common.io_utils import read_csv_rows, write_csv, write_json, write_jsonl
from imaks_kg.common.provenance import sha256_file, sha256_text
from imaks_kg.settings import DOCUMENTS_OUT, RAW_DATASHEETS_DIR, RAW_RULES_DIR, SENSORS_OUT, rel

SYMBOL_FONT_KEYS = ("symbol", "zapfdingbats")
# pdfminer가 StandardEncoding으로 푼 글자 -> 원래 바이트 코드 (실제 추출에서 나온 것만)
STD_TEXT_TO_CODE = {"ﬁ": 0xAE, "ﬂ": 0xAF, "›": 0xAD, "‡": 0xB3, "s": 0x73}
# Symbol 폰트 코드표
SYMBOL_CODE_TO_GLYPH = {0xAE: "→", 0xAD: "↑", 0xAF: "↓", 0xB3: "≥", 0x73: "σ", 0xB1: "±"}

DOC_ID_RE = re.compile(r"Document:\s*([A-Za-z0-9\-]+)\s*\|")
RULE_RE = re.compile(r"^(RULE-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*):")
HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+\S")
ID_COLUMN_HEADERS = {"Station ID", "Station", "Type", "Unit"}
TEXT_CHUNK_MAX = 1000
TEXT_CHUNK_OVERLAP = 200

EXPECTED_DOCS, EXPECTED_PAGES, EXPECTED_TABLES = 7, 10, 24


# ---------- 줄 단위 텍스트 추출 (pdfplumber extract_text 비레이아웃 경로와 동일) ----------
def build_lines(chars):
    if not chars:
        return []
    ex = WordExtractor()
    words = ex.extract_words(chars)
    clusters = cluster_objects(words, get_line_cluster_key(ex.line_dir), 3)
    lines = []
    for cl in clusters:
        lines.append({
            "text": " ".join(w["text"] for w in cl),
            "x0": min(w["x0"] for w in cl), "x1": max(w["x1"] for w in cl),
            "top": min(w["top"] for w in cl), "bottom": max(w["bottom"] for w in cl),
        })
    return lines


def is_symbol_char(c):
    f = c["fontname"].lower()
    return any(k in f for k in SYMBOL_FONT_KEYS)


def fix_glyph_chars(chars):
    """기호 폰트 글자만 치환한 사본과 (인덱스, 전, 코드, 후, 폰트) 기록, 미해결 목록을 돌려준다."""
    out, fixes, unresolved = [], [], []
    for i, c in enumerate(chars):
        if is_symbol_char(c):
            t = c["text"]
            code = STD_TEXT_TO_CODE.get(t)
            glyph = SYMBOL_CODE_TO_GLYPH.get(code) if code is not None else None
            if glyph is not None:
                n = dict(c)
                n["text"] = glyph
                out.append(n)
                fixes.append((i, t, code, glyph, c["fontname"]))
                continue
            unresolved.append((i, t, c["fontname"]))
        out.append(c)
    return out, fixes, unresolved


def center_in(c, bbox):
    cx, cy = (c["x0"] + c["x1"]) / 2, (c["top"] + c["bottom"]) / 2
    return bbox[0] <= cx < bbox[2] and bbox[1] <= cy < bbox[3]


def cell_text(chars, bbox):
    sel = [c for c in chars if center_in(c, bbox)]
    return "\n".join(l["text"] for l in build_lines(sel))


def merge_cell(text, header_cell, id_col):
    """줄바꿈을 정리한다. 헤더 행·ID 열·'-'/'_' 경계는 공백 없이 붙이고(쪼개진 단어), 그 외는 공백으로 잇는다."""
    parts = [p.strip() for p in text.split("\n")]
    out, joined_nospace = parts[0] if parts else "", False
    for nxt in parts[1:]:
        if header_cell or id_col or out.endswith(("-", "_")) or nxt.startswith("_"):
            out += nxt
            joined_nospace = True
        else:
            out += " " + nxt
    return out, joined_nospace


GLYPH_TO_CODE = {v: k for k, v in SYMBOL_CODE_TO_GLYPH.items()}


def diff_spans(a, b):
    """a(원문)와 b(치환본)가 다른 구간 [(i1, i2, j1, j2)]. 합자 'fi'(2자)가 화살표(1자)로 바뀌는 경우도 처리한다."""
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return [(i1, i2, j1, j2) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]


def context_of(s, i, w=20):
    return s[max(0, i - w): i + w].replace("\n", " ")


def glyph_reason(code, glyph):
    if code is None:
        return "symbol font glyph"
    return f"Symbol font code 0x{code:02X} -> {glyph}"


def make_chunk(doc_id, page, kind, chunk_id, text, s, e, file_sha, section=None):
    return {"chunk_id": chunk_id, "doc_id": doc_id, "page": page, "kind": kind, "text": text,
            "char_start": s, "char_end": e, "section": section, "table_id": None, "bbox": None,
            "text_sha256": sha256_text(text), "source_file_sha256": file_sha}


def table_to_text(rec, parent):
    hdr = (parent or rec)["rows_normalized"][0]
    body = rec["rows_normalized"] if parent else rec["rows_normalized"][1:]
    head = f"[{rec['table_id']}]"
    if rec.get("caption"):
        head += f" {rec['caption']}"
    if parent:
        head += f" (continued from {parent['table_id']})"
    lines = [head]
    for r in body:
        lines.append("; ".join(f"{h}: {v}" for h, v in zip(hdr, r)))
    return "\n".join(lines)


def process_pdf(path, doc_ids_seen, fixes_log, warnings):
    file_sha = sha256_file(path)
    pages_out, tables_out, chunks_out = [], [], []
    with pdfplumber.open(path) as pdf:
        first_text = pdf.pages[0].extract_text() or ""
        m = DOC_ID_RE.search(first_text)
        assert m, f"문서 ID를 찾지 못함: {path}"
        doc_id = m.group(1)
        assert doc_id not in doc_ids_seen
        doc_ids_seen.add(doc_id)

        prev_tables = []      # 이전 쪽의 표 레코드
        section = None        # 직전 제목(쪽을 넘어 유지)
        for pno, page in enumerate(pdf.pages, 1):
            chars = page.chars
            mod_chars, glyph_fixes, unresolved = fix_glyph_chars(chars)
            for u in unresolved:
                warnings.append(f"{doc_id} p{pno}: unresolved symbol font char {u}")

            lines_raw = build_lines(chars)
            lines_mod = build_lines(mod_chars)
            assert len(lines_raw) == len(lines_mod)
            text_raw = "\n".join(l["text"] for l in lines_raw)
            assert text_raw == (page.extract_text() or ""), f"{doc_id} p{pno}: extract_text와 불일치"

            # 줄 오프셋(원문 기준), 기호 치환 기록, R&D 오타
            norm_lines, raw_off = [], 0
            for lr, lm in zip(lines_raw, lines_mod):
                for i1, i2, j1, j2 in diff_spans(lr["text"], lm["text"]):
                    a, b = lr["text"][i1:i2], lm["text"][j1:j2]
                    fixes_log.append({
                        "doc_id": doc_id, "page": pno, "scope": "page_text", "location": raw_off + i1,
                        "before": a, "after": b, "reason": glyph_reason(GLYPH_TO_CODE.get(b), b),
                        "context": context_of(lm["text"], j1),
                    })
                t = lm["text"]
                for mm in re.finditer(r"R&D;", t):
                    fixes_log.append({
                        "doc_id": doc_id, "page": pno, "scope": "page_text", "location": raw_off + mm.start(),
                        "before": "R&D;", "after": "R&D", "reason": "source typo",
                        "context": context_of(t, mm.start()),
                    })
                norm_lines.append(t.replace("R&D;", "R&D"))
                raw_off += len(lr["text"]) + 1
            text_norm = "\n".join(norm_lines)
            offs, o = [], 0
            for t in norm_lines:
                offs.append(o)
                o += len(t) + 1

            pages_out.append({"doc_id": doc_id, "page": pno, "text_raw": text_raw, "text_normalized": text_norm,
                              "char_count": len(text_norm), "char_count_raw": len(text_raw)})

            # ---- 표 ----
            found = sorted(page.find_tables(), key=lambda t: (t.bbox[1], t.bbox[0]))
            cur_tables = []
            for tno, t in enumerate(found, 1):
                tid = f"{doc_id}:p{pno}:table{tno}"
                ref = t.extract()
                rows_raw, rows_norm, cells = [], [], []
                for row in t.rows:
                    rows_raw.append([cell_text(chars, bb) if bb else "" for bb in row.cells])
                if [[c or "" for c in r] for r in ref] != rows_raw:
                    warnings.append(f"{tid}: cell re-extraction differs from table.extract() (re-extracted values used)")
                bbox = [round(x, 2) for x in t.bbox]

                # 연속 표 판정: 이전 쪽 마지막 표가 쪽 아래에 붙고, 이 표가 쪽 위에 붙고, 열 수가 같음
                continued_from, parent = None, None
                if tno == 1 and prev_tables:
                    pt = prev_tables[-1]
                    if (pt["bbox"][3] >= page.height * 0.9 and t.bbox[1] <= page.height * 0.15
                            and pt["n_cols"] == len(t.rows[0].cells)):
                        continued_from, parent = pt["table_id"], pt
                header_cells = parent["rows_raw"][0] if parent else rows_raw[0]
                col_headers = [h.replace("\n", "") for h in header_cells]
                for ri, row in enumerate(t.rows):
                    rn = []
                    for ci, bb in enumerate(row.cells):
                        if not bb:
                            rn.append("")
                            continue
                        mc = cell_text(mod_chars, bb)
                        raw_c = rows_raw[ri][ci]
                        if mc != raw_c:
                            for i1, i2, j1, j2 in diff_spans(raw_c, mc):
                                a, b = raw_c[i1:i2], mc[j1:j2]
                                fixes_log.append({
                                    "doc_id": doc_id, "page": pno, "scope": "table_cell",
                                    "location": f"{tid}:r{ri}c{ci}:{i1}", "before": a, "after": b,
                                    "reason": glyph_reason(GLYPH_TO_CODE.get(b), b), "context": context_of(mc, j1)})
                        if "R&D;" in mc:
                            fixes_log.append({"doc_id": doc_id, "page": pno, "scope": "table_cell",
                                              "location": f"{tid}:r{ri}c{ci}", "before": "R&D;", "after": "R&D",
                                              "reason": "source typo", "context": mc.replace("\n", " ")})
                            mc = mc.replace("R&D;", "R&D")
                        is_hdr = (ri == 0 and parent is None)
                        id_col = col_headers[ci] in ID_COLUMN_HEADERS if ci < len(col_headers) else False
                        merged, nospace = merge_cell(mc, is_hdr, id_col)
                        if nospace and "\n" in mc:
                            fixes_log.append({"doc_id": doc_id, "page": pno, "scope": "table_cell",
                                              "location": f"{tid}:r{ri}c{ci}", "before": mc.replace("\n", "\\n"),
                                              "after": merged, "reason": "split-word cell merge (no space)",
                                              "context": ""})
                        rn.append(merged)
                        cells.append({"row": ri, "col": ci, "bbox": [round(x, 2) for x in bb],
                                      "text_raw": raw_c, "text_normalized": merged})
                    rows_norm.append(rn)

                # 표 위 제목 줄(30pt 이내)
                caption = None
                if continued_from is None:
                    above = [i for i, l in enumerate(lines_mod)
                             if l["bottom"] <= t.bbox[1] + 1 and t.bbox[1] - l["bottom"] <= 30]
                    if above:
                        cand = norm_lines[max(above, key=lambda i: lines_mod[i]["bottom"])]
                        caption = None if cand.rstrip().endswith(".") else cand  # 마침표로 끝나는 줄은 제목이 아니라 본문
                else:
                    caption = parent.get("caption")
                rec = {"table_id": tid, "doc_id": doc_id, "page": pno, "bbox": bbox,
                       "n_rows": len(rows_raw), "n_cols": len(t.rows[0].cells),
                       "caption": caption, "continued_from": continued_from, "continues_in": None,
                       "rows_raw": rows_raw, "rows_normalized": rows_norm, "cells": cells}
                cur_tables.append(rec)
                tables_out.append(rec)
                if parent:
                    parent["continues_in"] = tid
            prev_tables = cur_tables

            # ---- 줄을 표/규칙/본문으로 분류 ----
            def line_table(i, cur=cur_tables, lm=lines_mod):
                l = lm[i]
                cy, cx = (l["top"] + l["bottom"]) / 2, (l["x0"] + l["x1"]) / 2
                for rec in cur:
                    b = rec["bbox"]
                    if b[0] - 1 <= cx <= b[2] + 1 and b[1] - 1 <= cy <= b[3] + 1:
                        return rec
                return None

            kinds = []  # (kind, first_line, last_line, extra)
            i, n = 0, len(norm_lines)
            while i < n:
                tr = line_table(i)
                if tr is not None:
                    j = i
                    while j + 1 < n and line_table(j + 1) is tr:
                        j += 1
                    kinds.append(("table", i, j, tr))
                    i = j + 1
                    continue
                mm = RULE_RE.match(norm_lines[i])
                if mm:
                    j = i
                    while (j + 1 < n and line_table(j + 1) is None and not RULE_RE.match(norm_lines[j + 1])
                           and not HEADING_RE.match(norm_lines[j + 1])):
                        j += 1
                    kinds.append(("rule", i, j, mm.group(1)))
                    i = j + 1
                    continue
                j = i
                while j + 1 < n and line_table(j + 1) is None and not RULE_RE.match(norm_lines[j + 1]):
                    j += 1
                kinds.append(("text", i, j, None))
                i = j + 1

            cnt = defaultdict(int)
            for kind, a, b, extra in kinds:
                s, e = offs[a], offs[b] + len(norm_lines[b])
                if kind == "text":
                    for k in range(a, b + 1):
                        if HEADING_RE.match(norm_lines[k]):
                            section = norm_lines[k]
                    pos = s
                    while pos < e:
                        end = min(pos + TEXT_CHUNK_MAX, e)
                        if end < e:
                            ws = text_norm.rfind(" ", pos + TEXT_CHUNK_MAX // 2, end)
                            if ws > 0:
                                end = ws
                        txt = text_norm[pos:end]
                        if txt.strip():
                            cnt["text"] += 1
                            chunks_out.append(make_chunk(doc_id, pno, "text", f"{doc_id}:p{pno}:text{cnt['text']}",
                                                         txt, pos, end, file_sha, section=section))
                        if end >= e:
                            break
                        pos = max(end - TEXT_CHUNK_OVERLAP, pos + 1)
                elif kind == "rule":
                    txt = text_norm[s:e].replace("\n", " ")
                    c = make_chunk(doc_id, pno, "rule", f"{doc_id}:p{pno}:{extra}", txt, s, e, file_sha, section=section)
                    c["rule_id"] = extra
                    chunks_out.append(c)
                else:
                    rec = extra
                    parent = next((t for t in tables_out if t["table_id"] == rec["continued_from"]), None)
                    txt = table_to_text(rec, parent)
                    c = make_chunk(doc_id, pno, "table", f"{rec['table_id']}:chunk", txt, s, e, file_sha, section=section)
                    c["table_id"] = rec["table_id"]
                    c["bbox"] = rec["bbox"]
                    chunks_out.append(c)
    return doc_id, file_sha, pages_out, tables_out, chunks_out


# ---------- 검증 ----------
def check_sop002_thresholds(tables, warnings):
    """SOP-002 임계값 표에서 센서 22행을 뽑아 sensor_thresholds.csv(센서 원본 유래)와 대조한다."""
    sop = [t for t in tables if t["doc_id"] == "SOP-002"]
    by_id = {t["table_id"]: t for t in sop}
    rows = []
    for t in sop:
        parent = by_id.get(t["continued_from"]) if t["continued_from"] else None
        hdr = (parent or t)["rows_normalized"][0]
        if hdr[:2] != ["Sensor", "Unit"]:
            continue
        station = ((parent or t).get("caption") or "").split()[0]
        body = t["rows_normalized"] if parent else t["rows_normalized"][1:]
        for r in body:
            d = dict(zip(hdr, r))
            nom, tol = d["Nominal"].split("±")
            rows.append({"sensor_id": f"{station}_{d['Sensor']}", "unit": d["Unit"],
                         "crit_lo": float(d["CRIT_LO"]), "warn_lo": float(d["WARN_LO"]), "nominal": float(nom),
                         "warn_hi": float(d["WARN_HI"]), "crit_hi": float(d["CRIT_HI"]), "tolerance": float(tol)})
    assert len(rows) == 22, f"SOP-002 센서 행 수 {len(rows)}"
    assert len({r["sensor_id"] for r in rows}) == 22
    matched = None
    thr = SENSORS_OUT / "rules" / "sensor_thresholds.csv"
    if thr.exists():
        _, ref = read_csv_rows(thr)
        refd = {r["sensor_id"]: r for r in ref}
        bad = []
        for r in rows:
            q = refd.get(r["sensor_id"])
            if q is None:
                bad.append((r["sensor_id"], "missing sensor"))
                continue
            for k, col in (("nominal", "nominalValue"), ("warn_lo", "warnLo"), ("warn_hi", "warnHi"),
                           ("crit_lo", "critLo"), ("crit_hi", "critHi")):
                if float(q[col]) != r[k]:
                    bad.append((r["sensor_id"], k, q[col], r[k]))
            if q["unit"] != r["unit"]:
                bad.append((r["sensor_id"], "unit", q["unit"], r["unit"]))
        matched = not bad
        for b in bad:
            warnings.append(f"SOP-002 table vs sensor file mismatch: {b}")
    return rows, matched


def main():
    pdfs = sorted(RAW_RULES_DIR.glob("*.pdf")) + sorted(RAW_DATASHEETS_DIR.glob("*.pdf"))
    assert len(pdfs) == EXPECTED_DOCS, len(pdfs)
    seen, fixes, warnings = set(), [], []
    manifest, pages, tables, chunks = [], [], [], []
    for p in pdfs:
        doc_id, sha, pg, tb, ck = process_pdf(p, seen, fixes, warnings)
        manifest.append({"doc_id": doc_id, "file": rel(p), "pages": len(pg), "file_sha256": sha})
        pages += pg
        tables += tb
        chunks += ck
    manifest.sort(key=lambda m: m["doc_id"])

    out = DOCUMENTS_OUT
    write_csv(out / "doc_manifest.csv", ["doc_id", "file", "pages", "file_sha256"],
              ([m["doc_id"], m["file"], m["pages"], m["file_sha256"]] for m in manifest))
    write_jsonl(out / "pages.jsonl", pages)
    write_jsonl(out / "tables.jsonl", tables)
    write_jsonl(out / "chunks.jsonl", chunks)
    cols = ["doc_id", "page", "scope", "location", "before", "after", "reason", "context"]
    write_csv(out / "glyph_fixes.csv", cols, ([f[c] for c in cols] for f in fixes))

    # ---- 검증 ----
    assert len(manifest) == EXPECTED_DOCS
    assert sum(m["pages"] for m in manifest) == EXPECTED_PAGES == len(pages)
    assert len(tables) == EXPECTED_TABLES, len(tables)
    cont = [t for t in tables if t["continued_from"]]
    assert [(t["table_id"], t["continued_from"]) for t in cont] == [("SOP-002:p2:table1", "SOP-002:p1:table5")], cont
    pg_text = {(p["doc_id"], p["page"]): p["text_normalized"] for p in pages}
    for c in chunks:
        if c["kind"] != "table":
            t = pg_text[(c["doc_id"], c["page"])][c["char_start"]:c["char_end"]]
            assert t.replace("\n", " ") == c["text"].replace("\n", " "), c["chunk_id"]
    r = [c for c in chunks if c["doc_id"] == "SOP-001" and c.get("rule_id") == "RULE-ST02-04"]
    assert len(r) == 1
    assert r[0]["section"].startswith("2.2") and r[0]["text"].startswith("RULE-ST02-04: CUR drift")
    assert r[0]["text"].rstrip().endswith("triggers a WARNING."), r[0]["text"]
    sop_rows, matched = check_sop002_thresholds(tables, warnings)

    kinds = defaultdict(int)
    for c in chunks:
        kinds[c["kind"]] += 1
    glyph_counts = defaultdict(int)
    for f in fixes:
        glyph_counts[f"{f['scope']}|{f['before']}->{f['after']}"] += 1
    profile = {
        "documents": len(manifest), "pages": len(pages), "tables": len(tables),
        "continued_tables": [[t["table_id"], t["continued_from"]] for t in cont],
        "chunks_by_kind": dict(kinds),
        "glyph_fix_records": len(fixes), "glyph_fix_counts": dict(glyph_counts),
        "sop002_sensor_rows": len(sop_rows), "sop002_matches_sensor_file": matched,
        "warnings": warnings,
        "output_sha256": {rel(out / n): sha256_file(out / n) for n in
                          ("doc_manifest.csv", "pages.jsonl", "tables.jsonl", "chunks.jsonl", "glyph_fixes.csv")},
    }
    write_json(out / "doc_profile.json", profile)
    print(json.dumps({k: v for k, v in profile.items() if k != "output_sha256"}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
