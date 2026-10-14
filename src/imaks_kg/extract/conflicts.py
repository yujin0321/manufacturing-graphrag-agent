"""데이터시트 vs SOP-002 수치 충돌 후보(결정적, LLM 없음).

  PYTHONPATH=src .venv/Scripts/python.exe -m imaks_kg.extract.conflicts [--out extraction/conflicts.csv]

방법
1. SOP-002 쪽: B와 같은 함수(promote_rules.threshold_table_rows)로 센서별 표 행(nominal, WARN, CRIT 셀과 좌표)을 읽는다.
   ThresholdRule identifier(SOP-002:THR:<센서>)가 kg_build/rules_deterministic.ttl에 있는지 확인한다.
2. 데이터시트 쪽: 센서 종류(sensorType)를 정한다.
   - 표: 표 제목의 모델 코드(예: TMP-2210 → TMP). 제목에 코드가 없으면 문서 제목의 종류 이름(DOC_TITLE_TYPES).
   - 본문 주석(Note, Application Note): 같은 쪽에서 바로 앞에 있는 표의 센서 종류.
   값은 다음 세 가지만 모은다(정규식, 아래 상수).
   - range: 표의 '... range' 행 "a to b" (단위가 SOP-002 센서 단위와 같을 때만)
   - upper: 표의 연속·단시간 상한 행(Continuous overload rating, Short-time overload, Max intermittent),
            본문의 "rated maximum for continuous operation is N°C", "rated for continuous operation up to N A"
   - margin: 본문의 "at least K× the accuracy (M bar) from the nominal", "closer than K× accuracy (M bar)"
3. 후보 판정(기록만 하고 통일하거나 어느 쪽이 맞는지 정하지 않는다)
   - range: SOP-002 값(nominal, warnLo, warnHi, critLo, critHi)이 [a, b] 밖
   - upper: SOP-002 값(nominal, warnHi, critHi)이 상한보다 큼
   - margin: SOP-002 경고·위험 값과 nominal의 차이가 M보다 작음
값의 의미가 다를 수 있으므로(운전 한계 vs 경보 임계값) 두 쪽의 원문 라벨을 그대로 적는다.
출처: SOP-002는 표 셀(tableId, 행, 열, bbox, 인용, SHA-256), 데이터시트는 표 셀 또는 쪽 문자 위치(charStart-charEnd)와 인용, SHA-256.
"""
import argparse
import re
import sys
from decimal import Decimal
from pathlib import Path

from rdflib import RDF, Graph

from imaks_kg.common.io_utils import write_csv
from imaks_kg.common.provenance import sha256_text
from imaks_kg.extract.common import ExtractError, disp
from imaks_kg.extract.inputs import verify_chain
from imaks_kg.kg.naming import IM
from imaks_kg.kg.preprocess_lock import BPaths
from imaks_kg.kg.promote_rules import NOMINAL, threshold_table_rows
from imaks_kg.settings import EXTRACTION_CONFLICTS_CSV, RULES_TTL

NUM = r"[-+]?\d+(?:\.\d+)?"
MODEL_CODE = re.compile(r"\b(TMP|PRS|FLW|CUR|SPD|TEN|CNT|VIB|HUM)-\d{4}\b")
DOC_TITLE_TYPES = (("Current Transformer", "CUR"),)  # 표 제목에 모델 코드가 없는 문서(DS-ELEC-3300)
RANGE_LABEL = re.compile(r"\brange\b", re.I)
RANGE_VALUE = re.compile(rf"^({NUM}) to ({NUM})$")
UPPER_LABELS = ("Continuous overload rating", "Short-time overload", "Max intermittent")
UPPER_VALUE = re.compile(rf"^({NUM})$")
TEXT_UPPER = re.compile(rf"(?:rated maximum for continuous operation is|rated for continuous operation up to)\s+({NUM})\s*(°C|A)\b")
TEXT_MARGIN = [
    (re.compile(rf"at\s+least\s+(\d+)×\s+the\s+accuracy\s+\(({NUM})\s+(bar)\)\s+from\s+the\s+nominal\s+operating\s+point"),
     "margin_min"),
    (re.compile(rf"closer\s+than\s+(\d+)×\s+accuracy\s+\(({NUM})\s+(bar)\)\s+are\s+not\s+recommended"), "margin_not_recommended"),
]
SOP_FIELDS = (("nominalValue", "Nominal"), ("warnLo", "WARN_LO"), ("warnHi", "WARN_HI"),
              ("critLo", "CRIT_LO"), ("critHi", "CRIT_HI"))
UPPER_CHECK = ("nominalValue", "warnHi", "critHi")
MARGIN_CHECK = ("warnLo", "warnHi", "critLo", "critHi")
CSV_FIELDS = (
    "conflict_id", "sensor_id", "sensor_type", "b_identifier", "comparison_kind", "comparison",
    "sop_field", "sop_label", "sop_value", "sop_unit", "sop_doc", "sop_page", "sop_table_id", "sop_row", "sop_col",
    "sop_bbox", "sop_quote", "sop_sha256",
    "ds_value", "ds_unit", "ds_label", "ds_doc", "ds_page", "ds_location", "ds_quote", "ds_sha256", "note")


def _unit_head(u):
    return (u or "").split(" ")[0].strip()


def _bbox(b):
    return ",".join(repr(float(v)) for v in b)


def sop_rows(tables, b_idents):
    out = []
    for tr in threshold_table_rows(tables):
        bc = tr["by_col"]
        sensor = f"{tr['station']}_{bc['Sensor']['text_normalized']}"
        ident = f"SOP-002:THR:{sensor}"
        if ident not in b_idents:
            raise ExtractError(f"B ThresholdRule {ident}가 rules_deterministic.ttl에 없음")
        vals = {}
        for prop, col in SOP_FIELDS:
            cell = bc[col]
            text = cell["text_normalized"]
            v = NOMINAL.match(text).group(1) if prop == "nominalValue" else text
            vals[prop] = {"value": Decimal(v), "label": col, "cell": cell}
        out.append({"sensor": sensor, "type": bc["Sensor"]["text_normalized"], "unit": bc["Unit"]["text_normalized"],
                    "ident": ident, "table": tr["table"], "vals": vals})
    return out


def _table_type(t, doc_titles):
    m = MODEL_CODE.search(t.get("caption") or "")
    if m:
        return m.group(1)
    for name, typ in DOC_TITLE_TYPES:
        if name in doc_titles.get(t["doc_id"], ""):
            return typ
    return None


def ds_specs(tables, chunks, pages, doc_titles):
    """데이터시트 값 목록. 각 값: kind, type, lo/hi 또는 limit/margin, unit, label, 출처."""
    specs = []
    ds_tables = [t for t in tables.values() if t["doc_id"].startswith("DS-")]
    for t in sorted(ds_tables, key=lambda x: x["table_id"]):
        typ = _table_type(t, doc_titles)
        if typ is None:
            continue
        hdr = t["rows_normalized"][0]
        if hdr[:3] != ["Parameter", "Value", "Unit"]:
            continue
        cells = {(c["row"], c["col"]): c for c in t["cells"]}
        for r in range(1, t["n_rows"]):
            row = t["rows_normalized"][r]
            label, value, unit = row[0], row[1], row[2]
            notes = row[3] if len(row) > 3 else ""
            vcell = cells[(r, 1)]
            src = {"ds_doc": t["doc_id"], "ds_page": t["page"],
                   "ds_location": f"{t['table_id']} row {r + 1} col 2 bbox {_bbox(vcell['bbox'])}",
                   "ds_quote": vcell["text_normalized"], "ds_sha256": sha256_text(vcell["text_normalized"]),
                   "ds_label": label + (f" ({notes})" if notes else "")}
            m = RANGE_VALUE.match(value)
            if RANGE_LABEL.search(label) and m:
                specs.append({"kind": "range", "type": typ, "lo": Decimal(m.group(1)), "hi": Decimal(m.group(2)),
                              "unit": _unit_head(unit), "value_text": value, **src})
                continue
            m = UPPER_VALUE.match(value)
            if label in UPPER_LABELS and m:
                specs.append({"kind": "upper", "type": typ, "limit": Decimal(m.group(1)), "unit": _unit_head(unit),
                              "value_text": value, **src})
    # 본문 주석: 쪽 텍스트에서 표와 다음 표 사이(마지막 표 뒤는 쪽 끝까지)를 앞 표의 센서 종류로 읽는다.
    # 청크가 아니라 쪽 텍스트를 쓰는 이유: text 청크는 길이 제한으로 겹쳐 잘릴 수 있어 같은 문장을 두 번 읽거나 놓칠 수 있다.
    for (doc, page), pg in sorted(pages.items()):
        if not doc.startswith("DS-"):
            continue
        text = pg["text_normalized"]
        spans = sorted((c["char_start"], c["char_end"], c["table_id"]) for c in chunks
                       if c["doc_id"] == doc and c["page"] == page and c["kind"] == "table")
        for i, (_, t_end, tid) in enumerate(spans):
            typ = _table_type(tables[tid], doc_titles)
            gap_end = spans[i + 1][0] if i + 1 < len(spans) else len(text)
            if typ is None:
                continue
            gap = text[t_end:gap_end]
            for m in TEXT_UPPER.finditer(gap):
                specs.append(_text_spec("upper", typ, doc, page, text, t_end, m, limit=Decimal(m.group(1)),
                                        unit=m.group(2)))
            for pat, kind in TEXT_MARGIN:
                for m in pat.finditer(gap):
                    specs.append(_text_spec(kind, typ, doc, page, text, t_end, m, margin=Decimal(m.group(2)),
                                            unit=m.group(3), factor=m.group(1)))
    return specs


def _text_spec(kind, typ, doc, page, text, base, m, **kw):
    """본문 일치 하나. 위치는 쪽 좌표(base = 표 끝 위치). 라벨은 일치 앞의 가장 가까운 'Note'가 있는 줄의 처음부터 ':' 앞까지."""
    cs, ce = base + m.start(), base + m.end()
    quote = text[cs:ce]
    i = text.rfind("Note", base, cs)
    j = text.find(":", i) if i >= 0 else -1
    ls = text.rfind("\n", 0, i) + 1 if i >= 0 else 0  # 그 줄의 처음부터(예: "Application Note")
    label = text[ls:j].replace("\n", " ").strip() if j > i >= 0 else ""
    return {"kind": kind, "type": typ, "value_text": quote, "ds_doc": doc, "ds_page": page,
            "ds_location": f"page {page} char {cs}-{ce}", "ds_quote": quote, "ds_sha256": sha256_text(quote),
            "ds_label": label, **kw}


def find_conflicts(sops, specs):
    out = []
    for s in sops:
        for sp in specs:
            if sp["type"] != s["type"] or sp["unit"] != _unit_head(s["unit"]):
                continue
            nominal = s["vals"]["nominalValue"]["value"]
            if sp["kind"] == "range":
                hits = [(f, f"SOP-002 {s['vals'][f]['label']} {s['vals'][f]['value']} 이 데이터시트 범위 "
                            f"[{sp['lo']}, {sp['hi']}] 밖") for f, _ in SOP_FIELDS
                        if not (sp["lo"] <= s["vals"][f]["value"] <= sp["hi"])]
                ds_value = f"{sp['lo']} to {sp['hi']}"
            elif sp["kind"] == "upper":
                hits = [(f, f"SOP-002 {s['vals'][f]['label']} {s['vals'][f]['value']} > 데이터시트 상한 {sp['limit']}")
                        for f in UPPER_CHECK if s["vals"][f]["value"] > sp["limit"]]
                ds_value = str(sp["limit"])
            else:
                hits = [(f, f"|SOP-002 {s['vals'][f]['label']} {s['vals'][f]['value']} - Nominal {nominal}| = "
                            f"{abs(s['vals'][f]['value'] - nominal)} < 데이터시트 여유 {sp['margin']} ({sp['factor']}× accuracy)")
                        for f in MARGIN_CHECK if abs(s["vals"][f]["value"] - nominal) < sp["margin"]]
                ds_value = str(sp["margin"])
            for f, comp in hits:
                cell = s["vals"][f]["cell"]
                out.append({
                    "sensor_id": s["sensor"], "sensor_type": s["type"], "b_identifier": s["ident"],
                    "comparison_kind": sp["kind"], "comparison": comp, "sop_field": f,
                    "sop_label": s["vals"][f]["label"], "sop_value": str(s["vals"][f]["value"]), "sop_unit": s["unit"],
                    "sop_doc": "SOP-002", "sop_page": s["table"]["page"], "sop_table_id": s["table"]["table_id"],
                    "sop_row": cell["row"] + 1, "sop_col": cell["col"] + 1, "sop_bbox": _bbox(cell["bbox"]),
                    "sop_quote": cell["text_normalized"], "sop_sha256": sha256_text(cell["text_normalized"]),
                    "ds_value": ds_value, "ds_unit": sp["unit"], "ds_label": sp["ds_label"], "ds_doc": sp["ds_doc"],
                    "ds_page": sp["ds_page"], "ds_location": sp["ds_location"], "ds_quote": sp["ds_quote"],
                    "ds_sha256": sp["ds_sha256"],
                    "note": "기록만 함: 값을 통일하거나 어느 쪽이 맞는지 정하지 않음(의미가 다를 수 있음)",
                })
    out.sort(key=lambda r: (r["sensor_id"], r["sop_field"], r["ds_doc"], r["ds_location"], r["comparison_kind"]))
    for i, r in enumerate(out, 1):
        r["conflict_id"] = f"DSC-{i:03d}"
    return out


def collect(paths: BPaths = None):
    paths = paths or BPaths()
    docs, _ = verify_chain(paths)
    g = Graph().parse(str(Path(paths.out_dir) / RULES_TTL.name), format="turtle")
    b_idents = {str(o) for s in g.subjects(RDF.type, IM.ThresholdRule) for o in g.objects(s, IM.identifier)}
    titles = {str(next(g.objects(d, IM.identifier))): str(next(g.objects(d, IM.title)))
              for d in g.subjects(RDF.type, IM.Document)}
    sops = sop_rows(list(docs["tables"].values()), b_idents)
    specs = ds_specs(docs["tables"], docs["chunks"], docs["pages"], titles)
    return find_conflicts(sops, specs), specs


def main(argv=None):
    ap = argparse.ArgumentParser(description="데이터시트 vs SOP-002 수치 충돌 후보(결정적)")
    ap.add_argument("--out", default=None, help=f"출력 CSV(기본 {disp(EXTRACTION_CONFLICTS_CSV)})")
    args = ap.parse_args(argv)
    try:
        rows, specs = collect()
    except ExtractError as e:
        print(f"멈춤: {e}")
        return 1
    out = Path(args.out) if args.out else EXTRACTION_CONFLICTS_CSV
    write_csv(out, CSV_FIELDS, [[r[k] for k in CSV_FIELDS] for r in rows])
    print(f"데이터시트 값 {len(specs)}개, 충돌 후보 {len(rows)}건 → {disp(out)}")
    for r in rows:
        print(f"  {r['conflict_id']} {r['sensor_id']} {r['sop_field']}={r['sop_value']} vs {r['ds_doc']} "
              f"{r['ds_label']!r} {r['ds_value']} ({r['comparison_kind']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
