"""Rule·Document 노드 승격(B, 결정적 변환). 모델 호출·네트워크 접근 없음.

실행: PYTHONPATH=src .venv/Scripts/python.exe -m imaks_kg.kg.promote_rules

입력(읽기 전용, 이 목록 밖의 파일은 읽지 않는다)
- preprocessed/documents/doc_manifest.csv, pages.jsonl, tables.jsonl
- preprocessed/sensors/rules/sensor_thresholds.csv (대조용)
- imaks_data/kg_seed/nodes.csv, edges.csv (Maintenance 행, Sensor 임계값 대조, triggers/resolves, monitors)
- imaks_data/rules/*.pdf, imaks_data/datasheets/*.pdf (SHA-256 확인용으로 바이트만 읽음)
- kg_build/seed.ttl (appliesToSensor가 가리킬 Sensor IRI 확인)
- harness/preprocess_lock.json (고정 검증 기록, 읽기만. 생성은 imaks_kg.kg.preprocess_lock --init)

사전 검사(파일을 하나라도 쓰기 전에 모두 수행, 하나라도 틀리면 PromoteError로 멈추고 아무것도 쓰지 않음)
1. 해시 사슬(preprocess_lock.check_chain): PDF 현재 해시 == lock == doc_manifest, 문서 산출물 == lock,
   doc_profile.json output_sha256 == 현재 파일, 임계값 파일 == lock, 전처리 코드 == lock
2. 변환 중 결정성 검사(행 찾기·센서 매핑 등)
3. 의미 검사: SOP-002 표 22행 수치·단위 == 전처리 임계값 파일

출력
- kg_build/rules_deterministic.ttl: Document 7, MaintenanceRule 8, ThresholdRule 22, 각 Provenance
- kg_build/seed_plus_rules.ttl: seed.ttl + rules 합본(SHACL 확인용)
- reports/maint_mapping.md: seed Maintenance 문구 vs SOP-003 표 대조(8행)
- reports/threshold_mapping.md: seed Sensor 임계값 vs SOP-002 표 vs 전처리 임계값 파일 대조(22행)

규칙
- 행 찾기·센서 매핑은 정확 일치만 쓴다. 못 찾거나 여러 개면 PromoteError로 멈춘다.
- 원문에 없는 값(등급 등)은 만들지 않는다. 다른 값은 통일하지 않고 보고서에 둘 다 적는다.
- 표 출처는 셀 단위 Provenance(tableId, rowIndex, colIndex, bbox, page, sourceQuote, textSha256)다.
  rowIndex·colIndex는 1부터(표 tables.jsonl의 0부터인 row·col + 1). 이어지는 표는 그 표 자체의 행 번호다.
"""
import difflib
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path
from decimal import Decimal, InvalidOperation

from rdflib import RDF, XSD, Graph, Literal

from imaks_kg.common.io_utils import read_csv_rows, write_text
from imaks_kg.common.provenance import sha256_file, sha256_text
from imaks_kg.kg.naming import (
    IM, INST, SOURCE_KIND_DOCUMENT, SOURCE_KIND_SEED, document_iri, edge_prov_iri, edge_row_id,
    entity_iri, maintenance_rule_iri, node_prov_iri, table_cell_prov_iri, threshold_rule_iri,
)
from imaks_kg.kg.preprocess_lock import BPaths, check_chain
from imaks_kg.settings import KG_SEED_DIR, REPORTS_DIR, RULES_TTL, SEED_PLUS_RULES_TTL, SEED_TTL

NODES_FILE = KG_SEED_DIR / "nodes.csv"
EDGES_FILE = KG_SEED_DIR / "edges.csv"
OUT_MAINT_MD = REPORTS_DIR / "maint_mapping.md"
OUT_THR_MD = REPORTS_DIR / "threshold_mapping.md"

EXPECTED = {"Document": 7, "MaintenanceRule": 8, "ThresholdRule": 22}
THRESHOLD_DOC = "SOP-002"
MAINT_DOC = "SOP-003"
THRESHOLD_CAPTION = re.compile(r"^([A-Z0-9_]+) Thresholds$")
THRESHOLD_HEADER = ["Sensor", "Unit", "CRIT_LO", "WARN_LO", "Nominal", "WARN_HI", "CRIT_HI", "CRITICAL Response"]
MAINT_HEADER = ["Rule ID", "Sensor", "Station", "Trigger", "Action", "Priority"]
MAINT_ID = re.compile(r"^MAINT-\d{2}$")
NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
NOMINAL = re.compile(r"^(-?\d+(?:\.\d+)?)(?:\s*±\s*(\d+(?:\.\d+)?))?$")
DOC_LINE = re.compile(r"^Document: (\S+) \|")
# 임계값 속성 (온톨로지 이름, SOP-002 열 이름, 임계값 파일·seed 컬럼 이름)
THRESHOLD_FIELDS = [
    ("nominalValue", "Nominal"), ("warnLo", "WARN_LO"), ("warnHi", "WARN_HI"),
    ("critLo", "CRIT_LO"), ("critHi", "CRIT_HI"),
]
EXTRACTION_TABLE = "table"

TTL_HEADER = (
    "# 생성 파일: imaks_kg.kg.promote_rules (직접 고치지 말 것)\n"
    "# 입력: preprocessed/documents/{doc_manifest.csv, pages.jsonl, tables.jsonl}, imaks_data/kg_seed/{nodes.csv, edges.csv}\n"
    "# 포함: Document, MaintenanceRule(SOP-003·seed), ThresholdRule(SOP-002 표, 센서당 1개), Provenance. 스키마: ontology_v1/ontology.ttl\n\n"
)
MERGED_HEADER = (
    "# 생성 파일: imaks_kg.kg.promote_rules (SHACL 확인용 합본, 직접 고치지 말 것)\n"
    "# = kg_build/seed.ttl + kg_build/rules_deterministic.ttl\n\n"
)


class PromoteError(RuntimeError):
    """결정적으로 정할 수 없는 입력(없음·중복·불일치). 추측하지 않고 멈춘다."""


# ---------------------------------------------------------------- 입력

def _read_jsonl(path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _disp(paths, p):
    """출력용 경로 표기: 저장소 안이면 상대 경로, 밖(테스트 임시 폴더)이면 그대로."""
    try:
        return Path(p).resolve().relative_to(Path(paths.repo_root).resolve()).as_posix()
    except ValueError:
        return Path(p).as_posix()


def load_inputs(paths=None):
    """입력 경로 묶음(BPaths, 기본값은 settings 상수)에서 읽는다. 해시 사슬 검사는 하지 않는다(run이 먼저 한다)."""
    paths = paths or BPaths()
    _, manifest = read_csv_rows(paths.doc_dir / "doc_manifest.csv")
    _, nodes = read_csv_rows(paths.kg_seed_dir / NODES_FILE.name)
    _, edges = read_csv_rows(paths.kg_seed_dir / EDGES_FILE.name)
    _, thr_csv = read_csv_rows(paths.thresholds_csv)
    if not Path(paths.seed_ttl).exists():
        raise PromoteError(f"{_disp(paths, paths.seed_ttl)} 없음: 먼저 imaks_kg.kg.seed_to_rdf를 실행하세요")
    return {
        "manifest": manifest,
        "pages": _read_jsonl(paths.doc_dir / "pages.jsonl"),
        "tables": _read_jsonl(paths.doc_dir / "tables.jsonl"),
        "nodes": nodes,
        "edges": edges,
        "thr_csv": thr_csv,
        "seed_graph": Graph().parse(str(paths.seed_ttl), format="turtle"),
        "pdf_sha": {r["file"]: sha256_file(paths.repo_root / r["file"]) for r in manifest},
    }


# ---------------------------------------------------------------- seed 색인

def seed_index(nodes, edges):
    """seed에서 Sensor·Station·Maintenance 행과 (Station name, sensorType) → Sensor 행 색인."""
    by_id = {}
    for r in nodes:
        if r["nodeId"] in by_id:
            raise PromoteError(f"nodeId 중복: {r['nodeId']}")
        by_id[r["nodeId"]] = r
    station_sensors = {}  # (station name, sensorType) -> [sensor row]
    for e in edges:
        fr, to = by_id.get(e["fromId"]), by_id.get(e["toId"])
        if e["type"] == "monitors" and fr and to and fr["label"] == "Component" and to["label"] == "Sensor":
            station_sensors.setdefault((fr["name"], to["sensorType"]), []).append(to)
    return by_id, station_sensors


def map_sensor(station_sensors, station, abbr, where):
    """표의 스테이션 이름 + Sensor 열 약어 → seed Sensor 행(monitors 엣지 기준). 정확히 1개가 아니면 멈춘다."""
    hits = station_sensors.get((station, abbr), [])
    if len(hits) != 1:
        raise PromoteError(f"{where}: 센서 매핑 실패({station}, {abbr}) → 후보 {len(hits)}개")
    row = hits[0]
    if row["name"] != f"{station}_{abbr}":
        raise PromoteError(f"{where}: 매핑된 센서 이름이 규칙과 다름: {row['name']}")
    return row


# ---------------------------------------------------------------- 표 읽기

def _cell_grid(table):
    grid = {}
    for c in table["cells"]:
        key = (c["row"], c["col"])
        if key in grid:
            raise PromoteError(f"{table['table_id']}: 셀 중복 {key}")
        grid[key] = c
    return grid


def _row_cells(table, grid, row, n_cols):
    cells = []
    for col in range(n_cols):
        c = grid.get((row, col))
        if c is None:
            raise PromoteError(f"{table['table_id']}: 셀 없음 row={row} col={col}")
        cells.append(c)
    if [c["text_normalized"] for c in cells] != table["rows_normalized"][row]:
        raise PromoteError(f"{table['table_id']}: cells와 rows_normalized가 다름 row={row}")
    return cells


def _decimal(text, where):
    if not NUMBER.match(text):
        raise PromoteError(f"{where}: 수치로 읽을 수 없음 {text!r}")
    return Decimal(text)


def threshold_table_rows(tables):
    """SOP-002 '<STATION> Thresholds' 표(이어지는 표 포함)의 센서 행. 헤더가 정확히 같아야 한다."""
    by_id = {t["table_id"]: t for t in tables}
    out = []
    for t in tables:
        if t["doc_id"] != THRESHOLD_DOC:
            continue
        m = THRESHOLD_CAPTION.match(t.get("caption") or "")
        if not m:
            continue
        station = m.group(1)
        grid = _cell_grid(t)
        if t.get("continued_from"):
            head = by_id.get(t["continued_from"])
            if head is None or head.get("caption") != t["caption"] or head.get("continues_in") != t["table_id"]:
                raise PromoteError(f"{t['table_id']}: 이어지는 표의 앞 표가 맞지 않음")
            header, first = head["rows_normalized"][0], 0
        else:
            header, first = t["rows_normalized"][0], 1
        if header != THRESHOLD_HEADER or t["n_cols"] != len(THRESHOLD_HEADER):
            raise PromoteError(f"{t['table_id']}: 임계값 표 헤더가 예상과 다름 {header}")
        for row in range(first, t["n_rows"]):
            cells = _row_cells(t, grid, row, len(THRESHOLD_HEADER))
            out.append({"table": t, "station": station, "row": row, "cells": cells,
                        "by_col": dict(zip(THRESHOLD_HEADER, cells))})
    return out


def maint_table_rows(tables):
    """SOP-003의 헤더가 MAINT_HEADER인 표의 데이터 행을 Rule ID로 색인. ID 중복이면 멈춘다."""
    out = {}
    for t in tables:
        if t["doc_id"] != MAINT_DOC or not t["rows_normalized"] or t["rows_normalized"][0] != MAINT_HEADER:
            continue
        grid = _cell_grid(t)
        for row in range(1, t["n_rows"]):
            cells = _row_cells(t, grid, row, len(MAINT_HEADER))
            rid = cells[0]["text_normalized"]
            if rid in out:
                raise PromoteError(f"SOP-003 표에서 {rid}가 여러 행에 있음")
            out[rid] = {"table": t, "row": row, "cells": cells, "by_col": dict(zip(MAINT_HEADER, cells))}
    return out


# ---------------------------------------------------------------- 그래프 조립

def _add_cell_prov(g, table, cell):
    r, c = cell["row"] + 1, cell["col"] + 1
    prov = table_cell_prov_iri(table["table_id"], r, c)
    quote = cell["text_normalized"]
    g.add((prov, RDF.type, IM.Provenance))
    g.add((prov, IM.sourceKind, Literal(SOURCE_KIND_DOCUMENT)))
    g.add((prov, IM.page, Literal(int(table["page"]), datatype=XSD.positiveInteger)))
    g.add((prov, IM.tableId, Literal(table["table_id"])))
    g.add((prov, IM.rowIndex, Literal(r, datatype=XSD.positiveInteger)))
    g.add((prov, IM.colIndex, Literal(c, datatype=XSD.positiveInteger)))
    g.add((prov, IM.bbox, Literal(",".join(repr(float(v)) for v in cell["bbox"]))))
    g.add((prov, IM.sourceQuote, Literal(quote)))
    g.add((prov, IM.textSha256, Literal(sha256_text(quote))))
    return prov


def _add_seed_prov(g, prov, file_rel, row_ids):
    g.add((prov, RDF.type, IM.Provenance))
    g.add((prov, IM.sourceKind, Literal(SOURCE_KIND_SEED)))
    g.add((prov, IM.fileName, Literal(file_rel)))
    for rid in row_ids:
        g.add((prov, IM.sourceRowId, Literal(rid)))


def build_documents(g, manifest, pages, pdf_sha):
    pages_by_doc = {}
    for p in pages:
        pages_by_doc.setdefault(p["doc_id"], []).append(p)
    docs = OrderedDict()
    for r in sorted(manifest, key=lambda x: x["doc_id"]):
        did = r["doc_id"]
        if did in docs:
            raise PromoteError(f"doc_manifest 문서 ID 중복: {did}")
        if pdf_sha.get(r["file"]) != r["file_sha256"]:
            raise PromoteError(f"{did}: PDF SHA-256이 doc_manifest와 다름")
        plist = sorted(pages_by_doc.get(did, []), key=lambda p: p["page"])
        if [p["page"] for p in plist] != list(range(1, int(r["pages"]) + 1)):
            raise PromoteError(f"{did}: pages.jsonl 쪽 수가 doc_manifest({r['pages']})와 다름")
        # 제목: 1쪽 텍스트에서 'Document: <ID> |' 줄 앞의 줄들을 공백으로 이은 것
        lines = plist[0]["text_normalized"].split("\n")
        idx = [i for i, ln in enumerate(lines) if DOC_LINE.match(ln)]
        if not idx or DOC_LINE.match(lines[idx[0]]).group(1) != did or idx[0] == 0:
            raise PromoteError(f"{did}: 1쪽에서 제목·문서 ID 줄을 찾지 못함")
        title = " ".join(ln.strip() for ln in lines[:idx[0]])
        d = document_iri(did)
        g.add((d, RDF.type, IM.Document))
        g.add((d, IM.identifier, Literal(did)))
        g.add((d, IM.title, Literal(title)))
        g.add((d, IM.sourcePath, Literal(r["file"])))
        g.add((d, IM.sourceSha256, Literal(r["file_sha256"])))
        g.add((d, IM.pageCount, Literal(int(r["pages"]), datatype=XSD.positiveInteger)))
        docs[did] = {"iri": d, "title": title, "file": r["file"], "sha": r["file_sha256"], "pages": int(r["pages"])}
    return docs


def _seed_sensor_iri(seed_graph, name):
    s = entity_iri(name)
    if (s, RDF.type, IM.Sensor) not in seed_graph:
        raise PromoteError(f"seed.ttl에 Sensor {s} 가 없음")
    return s


def build_maintenance(g, inp, docs, by_id, station_sensors, nodes_rel, edges_rel):
    seed_rows = [r for r in inp["nodes"] if r["label"] == "Maintenance"]
    ids = [r["ruleId"] for r in seed_rows]
    if len(ids) != len(set(ids)) or not all(MAINT_ID.match(i) for i in ids):
        raise PromoteError(f"seed Maintenance ruleId가 유일한 MAINT-nn 형식이 아님: {ids}")
    table_rows = maint_table_rows(inp["tables"])
    if set(table_rows) != set(ids):
        raise PromoteError(f"SOP-003 표 ID {sorted(table_rows)}와 seed ID {sorted(ids)}가 다름")

    # triggers(Sensor→Maintenance)와 resolves(Maintenance→Sensor): 같은 쌍이어야 한다
    trig, reso = {}, {}
    for i, e in enumerate(inp["edges"], 1):
        fr, to = by_id.get(e["fromId"]), by_id.get(e["toId"])
        if not fr or not to:
            continue
        if e["type"] == "triggers" and fr["label"] == "Sensor" and to["label"] == "Maintenance":
            trig.setdefault(to["nodeId"], []).append((fr["nodeId"], i))
        elif e["type"] == "resolves" and fr["label"] == "Maintenance" and to["label"] == "Sensor":
            reso.setdefault(fr["nodeId"], []).append((to["nodeId"], i))

    infos = []
    for r in sorted(seed_rows, key=lambda x: x["ruleId"]):
        nid, rid = r["nodeId"], r["ruleId"]
        rs, tg = reso.get(nid, []), trig.get(nid, [])
        if len(rs) != 1 or len(tg) != 1:
            raise PromoteError(f"{rid}: resolves {len(rs)}개, triggers {len(tg)}개(각 1개여야 함)")
        (sensor_nid, reso_row), (trig_sensor_nid, trig_row) = rs[0], tg[0]
        if sensor_nid != trig_sensor_nid:
            raise PromoteError(f"{rid}: resolves 대상 {sensor_nid}와 triggers 출발 {trig_sensor_nid}가 다름")
        sensor = by_id[sensor_nid]
        trow = table_rows[rid]
        doc_sensor = map_sensor(station_sensors, trow["by_col"]["Station"]["text_normalized"],
                                trow["by_col"]["Sensor"]["text_normalized"], f"SOP-003 {rid}")
        if doc_sensor["nodeId"] != sensor_nid:
            raise PromoteError(f"{rid}: SOP-003 표의 센서 {doc_sensor['name']}와 seed resolves 대상 {sensor['name']}가 다름")
        for col in ("action", "priority"):
            if r.get(col, "") == "":
                raise PromoteError(f"{rid}: seed {col}가 비어 있음")
        # 2026-10-12 사용자 결정: 조건·조치 문구는 SOP-003 원문 셀. priority·센서는 seed와 같아야 한다(다르면 멈춤).
        doc_priority = trow["by_col"]["Priority"]["text_normalized"]
        if doc_priority != r["priority"]:
            raise PromoteError(f"{rid}: priority가 seed {r['priority']!r}와 SOP-003 {doc_priority!r}로 다름")
        condition = trow["by_col"]["Trigger"]["text_normalized"]
        response = trow["by_col"]["Action"]["text_normalized"]
        if condition == "" or response == "":
            raise PromoteError(f"{rid}: SOP-003 Trigger 또는 Action 셀이 비어 있음")

        s = maintenance_rule_iri(rid)
        g.add((s, RDF.type, IM.MaintenanceRule))
        g.add((s, IM.identifier, Literal(rid)))
        g.add((s, IM.sourceNodeId, Literal(nid)))
        g.add((s, IM.conditionText, Literal(condition)))
        g.add((s, IM.responseText, Literal(response)))
        g.add((s, IM.priority, Literal(r["priority"])))
        g.add((s, IM.extractionMethod, Literal(EXTRACTION_TABLE)))
        g.add((s, IM.appliesToSensor, _seed_sensor_iri(inp["seed_graph"], sensor["name"])))
        g.add((s, IM.sourceDocument, docs[MAINT_DOC]["iri"]))
        for cell in trow["cells"]:
            g.add((s, IM.hasProvenance, _add_cell_prov(g, trow["table"], cell)))
        np_ = node_prov_iri(nid)
        _add_seed_prov(g, np_, nodes_rel, [nid])
        g.add((s, IM.hasProvenance, np_))
        ep = edge_prov_iri("appliesToSensor", nid, sensor_nid)
        _add_seed_prov(g, ep, edges_rel, [edge_row_id(trig_row), edge_row_id(reso_row)])
        g.add((s, IM.hasProvenance, ep))
        infos.append({"rid": rid, "nid": nid, "seed": r, "sensor": sensor["name"], "table_row": trow,
                      "edge_rows": (trig_row, reso_row)})
    return infos


def build_thresholds(g, inp, docs, station_sensors):
    rows = threshold_table_rows(inp["tables"])
    infos, seen = [], set()
    for tr in rows:
        bc = tr["by_col"]
        where = f"{tr['table']['table_id']} row={tr['row']}"
        sensor = map_sensor(station_sensors, tr["station"], bc["Sensor"]["text_normalized"], where)
        if sensor["name"] in seen:
            raise PromoteError(f"{where}: 센서 {sensor['name']}의 행이 두 번 나옴")
        seen.add(sensor["name"])
        m = NOMINAL.match(bc["Nominal"]["text_normalized"])
        if not m:
            raise PromoteError(f"{where}: Nominal 셀 형식이 예상과 다름 {bc['Nominal']['text_normalized']!r}")
        values = OrderedDict()
        values["nominalValue"] = Decimal(m.group(1))
        for prop, col in THRESHOLD_FIELDS[1:]:
            values[prop] = _decimal(bc[col]["text_normalized"], f"{where} {col}")
        response = bc["CRITICAL Response"]["text_normalized"]
        if response == "":
            raise PromoteError(f"{where}: CRITICAL Response 셀이 비어 있음")

        ident = f"{THRESHOLD_DOC}:THR:{sensor['name']}"
        s = threshold_rule_iri(sensor["name"])
        g.add((s, RDF.type, IM.ThresholdRule))
        g.add((s, IM.identifier, Literal(ident)))
        for prop, v in values.items():
            g.add((s, IM[prop], Literal(str(v), datatype=XSD.decimal)))
        g.add((s, IM.responseText, Literal(response)))
        g.add((s, IM.extractionMethod, Literal(EXTRACTION_TABLE)))
        g.add((s, IM.appliesToSensor, _seed_sensor_iri(inp["seed_graph"], sensor["name"])))
        g.add((s, IM.sourceDocument, docs[THRESHOLD_DOC]["iri"]))
        for cell in tr["cells"]:
            g.add((s, IM.hasProvenance, _add_cell_prov(g, tr["table"], cell)))
        infos.append({"ident": ident, "sensor": sensor, "values": values, "tolerance": m.group(2),
                      "unit": bc["Unit"]["text_normalized"], "table_row": tr, "response": response})
    return sorted(infos, key=lambda x: x["sensor"]["name"])


def build_graph(inp, nodes_rel="imaks_data/kg_seed/nodes.csv", edges_rel="imaks_data/kg_seed/edges.csv"):
    """입력 dict → (Graph, 정보). 파일을 쓰지 않는 순수 함수(테스트용)."""
    g = Graph()
    g.bind("im", IM)
    g.bind("inst", INST)
    g.bind("xsd", XSD)
    by_id, station_sensors = seed_index(inp["nodes"], inp["edges"])
    docs = build_documents(g, inp["manifest"], inp["pages"], inp["pdf_sha"])
    for need in (THRESHOLD_DOC, MAINT_DOC):
        if need not in docs:
            raise PromoteError(f"doc_manifest에 {need} 없음")
    maint = build_maintenance(g, inp, docs, by_id, station_sensors, nodes_rel, edges_rel)
    thr = build_thresholds(g, inp, docs, station_sensors)
    counts = {"Document": len(docs), "MaintenanceRule": len(maint), "ThresholdRule": len(thr)}
    for k, v in EXPECTED.items():
        if counts[k] != v:
            raise PromoteError(f"{k} 개수 {counts[k]} != 기대 {v}")
    return g, {"docs": docs, "maint": maint, "thr": thr, "counts": counts, "by_id": by_id}


def serialize(g, header=TTL_HEADER) -> str:
    """결정적 Turtle(rdflib turtle 직렬화는 주어·속성·값을 정렬한다)."""
    return header + g.serialize(format="turtle")


def merged_graph(seed_graph, rules_graph):
    m = Graph()
    m.bind("im", IM)
    m.bind("inst", INST)
    m.bind("xsd", XSD)
    for t in seed_graph:
        m.add(t)
    for t in rules_graph:
        m.add(t)
    return m


# ---------------------------------------------------------------- 대조 보고서

def _md(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def _word_diff(a, b):
    """단어 단위 차이 설명(결정적). a=seed, b=SOP-003."""
    sm = difflib.SequenceMatcher(a=a.split(), b=b.split(), autojunk=False)
    parts = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        x, y = " ".join(a.split()[i1:i2]), " ".join(b.split()[j1:j2])
        if op == "insert":
            parts.append(f"SOP-003에만 '{y}'")
        elif op == "delete":
            parts.append(f"seed에만 '{x}'")
        elif op == "replace":
            parts.append(f"'{x}'(seed) ↔ '{y}'(SOP-003)")
    return "; ".join(parts)


def maint_mapping_md(maint):
    lines = [
        "# MAINT-01~08 대조표: seed(nodes.csv/edges.csv) vs SOP-003 표", "",
        "생성: `imaks_kg.kg.promote_rules` (직접 고치지 말 것). 2026-10-12 사용자 결정에 따라 KG의 "
        "`conditionText` = SOP-003 Trigger 셀, `responseText` = SOP-003 Action 셀 원문이다(셀 Provenance 연결). "
        "seed action은 KG 속성으로 두지 않고 이 표와 seed Provenance(nodes.csv 행)에만 남긴다. "
        "priority·센서는 seed와 SOP-003이 같아야 하며 다르면 변환이 멈춘다. 문구는 통일하지 않는다.", "",
        "- seed 센서: edges.csv resolves(Maintenance→Sensor) 대상. triggers(Sensor→Maintenance)와 같은 쌍임을 코드가 확인했다.",
        "- SOP-003 센서: 표의 Station 열 + Sensor 열 → seed monitors 엣지로 찾은 Sensor.",
        "- seed 조건: nodes.csv Maintenance 행에는 조건(Trigger) 컬럼 값이 없다. 그래서 판정에서 조건은 제외하고 SOP-003 원문만 적는다.",
        "- 판정은 센서·조치·우선순위의 문자열 정확 일치로 정한다.", "",
        "| ID | seed 센서 | seed 조건 | seed 조치 | seed 우선순위 | SOP-003 셀(표 위치) | SOP-003 센서 | SOP-003 Trigger | SOP-003 Action | SOP-003 Priority | 판정 | 차이 설명 | KG conditionText·responseText 출처 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    n_diff, kinds = 0, OrderedDict()
    for m in maint:
        bc = m["table_row"]["by_col"]
        doc_sensor = f"{bc['Station']['text_normalized']}_{bc['Sensor']['text_normalized']}"
        diffs = []
        if doc_sensor != m["sensor"]:
            diffs.append(f"센서 다름({m['sensor']} ↔ {doc_sensor})")
            kinds["센서"] = kinds.get("센서", 0) + 1
        sa, da = m["seed"]["action"], bc["Action"]["text_normalized"]
        if sa != da:
            diffs.append("조치 문구: " + _word_diff(sa, da))
            kinds["조치 문구"] = kinds.get("조치 문구", 0) + 1
        sp, dp = m["seed"]["priority"], bc["Priority"]["text_normalized"]
        if sp != dp:
            diffs.append(f"우선순위 다름({sp} ↔ {dp})")
            kinds["우선순위"] = kinds.get("우선순위", 0) + 1
        verdict = "다름" if diffs else "같음"
        n_diff += bool(diffs)
        loc = f"{m['table_row']['table']['table_id']} 행 {m['table_row']['row'] + 1}"
        lines.append("| " + " | ".join(_md(x) for x in [
            m["rid"], m["sensor"], "(seed에 없음)", sa, sp, loc, doc_sensor,
            bc["Trigger"]["text_normalized"], da, dp, verdict, "; ".join(diffs) or "-",
            f"SOP-003 (Trigger 열 {bc['Trigger']['col'] + 1}, Action 열 {bc['Action']['col'] + 1})"]) + " |")
    lines += ["", "## 요약", "", f"- 행 수: {len(maint)}, 같음 {len(maint) - n_diff}, 다름 {n_diff}"]
    for k, v in kinds.items():
        lines.append(f"- 차이 유형 '{k}': {v}행")
    lines.append("")
    return "\n".join(lines), {"rows": len(maint), "diff": n_diff, "kinds": dict(kinds)}


def _dec_or_none(text):
    try:
        return Decimal(text)
    except (InvalidOperation, TypeError):
        return None


def threshold_mapping_md(thr, thr_csv):
    csv_by = {}
    for r in thr_csv:
        if r["sensor_id"] in csv_by:
            raise PromoteError(f"임계값 파일 sensor_id 중복: {r['sensor_id']}")
        csv_by[r["sensor_id"]] = r
    lines = [
        "# 센서 임계값 대조표: seed nodes.csv Sensor 행 vs SOP-002 표(ThresholdRule) vs 전처리 임계값 파일", "",
        "생성: `imaks_kg.kg.promote_rules` (직접 고치지 말 것). KG의 ThresholdRule 값은 SOP-002 표에서 왔다. "
        "seed와 임계값 파일은 대조만 하고 KG에 넣지 않는다. 다른 값은 셋 다 적고 통일하지 않는다.", "",
        "- 비교는 수치(Decimal) 기준이다. 수치는 같고 표기만 다르면(예: 120 vs 120.0) '같음(표기 다름)'으로 적는다.",
        "- 칸 표기: 셋이 같으면 값 하나, 다르면 `seed=… / SOP-002=… / csv=…`.",
        "- Nominal 옆 '±' 허용오차는 온톨로지에 속성이 없어 KG 속성으로 만들지 않았다(원문은 Provenance sourceQuote와 해시로 남음). 참고로 아래 표에 적는다.", "",
        "| 센서 | ThresholdRule identifier | SOP-002 위치 | 단위 | nominalValue | warnLo | warnHi | critLo | critHi | ± 허용오차(원문, KG 미반영) | 판정 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    n_diff, n_fmt, field_diff = 0, 0, OrderedDict()
    for t in thr:
        name = t["sensor"]["name"]
        crow = csv_by.get(name)
        if crow is None:
            raise PromoteError(f"임계값 파일에 {name} 행이 없음")
        cells, row_diff, row_fmt = [], False, False
        units = (t["sensor"]["unit"], t["unit"], crow["unit"])
        if len(set(units)) == 1:
            cells.append(units[0])
        else:
            cells.append(f"seed={units[0]} / SOP-002={units[1]} / csv={units[2]}")
            row_diff = True
            field_diff["unit"] = field_diff.get("unit", 0) + 1
        for prop, col in THRESHOLD_FIELDS:
            doc_v = t["values"][prop]
            seed_s, csv_s = t["sensor"].get(prop, ""), crow.get(prop, "")
            seed_v, csv_v = _dec_or_none(seed_s), _dec_or_none(csv_s)
            if seed_v == doc_v and csv_v == doc_v:
                doc_s = t["table_row"]["by_col"][col]["text_normalized"]
                doc_s = NOMINAL.match(doc_s).group(1) if prop == "nominalValue" else doc_s
                if seed_s == csv_s == doc_s:
                    cells.append(doc_s)
                else:
                    cells.append(f"같음(표기 다름: seed={seed_s} / SOP-002={doc_s} / csv={csv_s})")
                    row_fmt = True
            else:
                cells.append(f"seed={seed_s or '(없음)'} / SOP-002={doc_v} / csv={csv_s or '(없음)'}")
                row_diff = True
                field_diff[prop] = field_diff.get(prop, 0) + 1
        n_diff += row_diff
        n_fmt += row_fmt and not row_diff
        loc = f"{t['table_row']['table']['table_id']} 행 {t['table_row']['row'] + 1}"
        verdict = "다름" if row_diff else ("같음(표기 다름)" if row_fmt else "같음")
        lines.append("| " + " | ".join(_md(x) for x in [name, t["ident"], loc] + cells + [t["tolerance"] or "-", verdict]) + " |")
    extra = sorted(set(csv_by) - {t["sensor"]["name"] for t in thr})
    lines += ["", "## 요약", "", f"- 센서 {len(thr)}개 중 수치·단위 불일치 {n_diff}개, 수치는 같고 표기만 다름 {n_fmt}개"]
    for k, v in field_diff.items():
        lines.append(f"- 불일치 필드 '{k}': {v}개 센서")
    lines.append(f"- 임계값 파일에만 있는 센서: {', '.join(extra) if extra else '없음'}")
    lines.append("")
    return "\n".join(lines), {"sensors": len(thr), "diff": n_diff, "format_only": n_fmt, "fields": dict(field_diff)}


# ---------------------------------------------------------------- 실행

def semantic_threshold_errors(thr, thr_csv):
    """의미 검사: SOP-002 표에서 읽은 22행의 수치·단위가 전처리 임계값 파일과 같은지(해시 사슬의 두 번째 방어선).
    seed 값과의 차이는 여기서 보지 않는다(보고서에 기록만, 통일 금지)."""
    csv_by = {r["sensor_id"]: r for r in thr_csv}
    errors = []
    if len(csv_by) != len(thr_csv) or set(csv_by) != {t["sensor"]["name"] for t in thr}:
        errors.append(f"임계값 파일 센서 집합이 SOP-002 표와 다름: 파일 {sorted(csv_by)}")
    for t in thr:
        row = csv_by.get(t["sensor"]["name"])
        if row is None:
            continue
        if row["unit"] != t["unit"]:
            errors.append(f"{t['sensor']['name']} unit: SOP-002 표 {t['unit']!r} != 임계값 파일 {row['unit']!r}")
        for prop, _ in THRESHOLD_FIELDS:
            if _dec_or_none(row.get(prop)) != t["values"][prop]:
                errors.append(f"{t['sensor']['name']} {prop}: SOP-002 표 {t['values'][prop]} != 임계값 파일 {row.get(prop)}")
    return errors


def output_paths(paths):
    return {
        "rules": paths.out_dir / RULES_TTL.name,
        "merged": paths.out_dir / SEED_PLUS_RULES_TTL.name,
        "maint_md": paths.reports_dir / OUT_MAINT_MD.name,
        "thr_md": paths.reports_dir / OUT_THR_MD.name,
    }


def run(paths=None):
    """사전 검사(해시 사슬 → 변환 → 의미 검사)를 모두 통과한 뒤에만 출력 4개를 쓴다. 틀리면 PromoteError, 쓰기 없음."""
    paths = paths or BPaths()
    errors = check_chain(paths)
    if errors:
        raise PromoteError("해시 사슬 검사 실패(출력 안 씀):\n- " + "\n- ".join(errors))
    inp = load_inputs(paths)
    g, info = build_graph(inp, _disp(paths, paths.kg_seed_dir / NODES_FILE.name),
                          _disp(paths, paths.kg_seed_dir / EDGES_FILE.name))
    errors = semantic_threshold_errors(info["thr"], inp["thr_csv"])
    if errors:
        raise PromoteError("의미 검사 실패: SOP-002 표와 임계값 파일이 다름(출력 안 씀):\n- " + "\n- ".join(errors))
    text = serialize(g)
    merged = serialize(merged_graph(inp["seed_graph"], g), MERGED_HEADER)
    maint_md, maint_sum = maint_mapping_md(info["maint"])
    thr_md, thr_sum = threshold_mapping_md(info["thr"], inp["thr_csv"])
    outs = output_paths(paths)
    # 여기까지 모든 검사와 계산이 끝났다. 이제부터만 파일을 쓴다.
    for key, content in (("rules", text), ("merged", merged), ("maint_md", maint_md), ("thr_md", thr_md)):
        write_text(outs[key], content)
    return {"info": info, "text": text, "maint": maint_sum, "thr": thr_sum, "outs": outs}


def main(paths=None):
    paths = paths or BPaths()
    try:
        res = run(paths)
    except PromoteError as e:
        print(f"멈춤: {e}")
        return 1
    rg = Graph().parse(data=res["text"], format="turtle")
    print(f"개수: {res['info']['counts']}, Provenance {len(set(rg.subjects(RDF.type, IM.Provenance)))}, 트리플 {len(rg)}")
    print(f"MAINT 대조: {res['maint']}")
    print(f"임계값 대조: {res['thr']}")
    print("산출물:", *(_disp(paths, p) for p in res["outs"].values()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
