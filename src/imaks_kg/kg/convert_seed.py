"""③ 기존 KG(seed) 변환 + Rule·Document 노드 승격 (작업 A·B). LLM 호출 없음.

실행: PYTHONPATH=src .venv/Scripts/python.exe -m imaks_kg.kg.convert_seed

- 입력(읽기 전용): imaks_data/kg_seed/nodes.csv, edges.csv,
  preprocessed/documents/doc_manifest.csv, tables.jsonl, chunks.jsonl
  (nodes_factory.csv는 nodeId 충돌 6건이 있어 쓰지 않는다.)
- 출력: kg_build/instances/*.csv, instances.ttl, kg_build/mapping/*.csv, kg_build/summary.json
- 값은 원본 문자열 그대로 보존한다(보간·삭제·통일 없음). 변환 규칙은 ontology_v1/schema_tables.md 7장.
- 적재하지 않는 것: AnomalyEvent, triggers(Sensor->AnomalyEvent), correlates_with(⑦ 이후),
  Person, authorized_for, SafetyEvent, involves, detected_in, Zone, System, contains, part_of.
- 트리플 단위 출처 장부: kg_build/instances/triple_sources.jsonl (모든 트리플에 근거 1개 이상, 아니면 예외).
- MaintenanceRule마다 seedCsv Provenance + SOP-003 표 위치 document Provenance(rowIndex·colIndex는 1부터,
  표 헤더 행 = 1, 첫 열 = 1). 위치는 tables.jsonl의 rows_normalized에서 ID가 정확히 1번 나오는 곳만 인정한다.
- 가정이 깨지면(양방향 불일치, 센서당 스테이션 1개 아님 등) 조용히 넘어가지 않고 ValueError를 낸다.
"""
import json
import sys
from collections import Counter, defaultdict

from rdflib import RDF, XSD, Graph, Literal, Namespace

from imaks_kg.common.io_utils import read_csv_rows, write_csv, write_json, write_jsonl, write_text
from imaks_kg.common.provenance import sha256_file, sha256_text
from imaks_kg.settings import DOCUMENTS_OUT, KG_BUILD, RAW_KG_SEED_DIR, REPO_ROOT, rel

IM = Namespace("https://example.org/imaks/v1#")
INST = Namespace("https://example.org/imaks/id/")

NODES_FILE = RAW_KG_SEED_DIR / "nodes.csv"
EDGES_FILE = RAW_KG_SEED_DIR / "edges.csv"
MANIFEST_FILE = DOCUMENTS_OUT / "doc_manifest.csv"
TABLES_FILE = DOCUMENTS_OUT / "tables.jsonl"
CHUNKS_FILE = DOCUMENTS_OUT / "chunks.jsonl"

OUT_DIR = KG_BUILD / "instances"
MAP_DIR = KG_BUILD / "mapping"
MAINT_DOC_ID = "SOP-003"

LEDGER_FILE = OUT_DIR / "triple_sources.jsonl"
DOC_PROV_FILE = OUT_DIR / "provenance_document.csv"
FORBIDDEN_TYPES = ("AnomalyEvent", "Spike", "Drift", "StuckSensor", "OutOfRange", "Correlated",
                   "Person", "CausalLink")
FORBIDDEN_PREDICATES = ("causallyAffects", "triggers", "correlatesWith")

EXPECTED = {"Station": 9, "Sensor": 22, "hasSensor": 22, "feedsInto": 3,
            "MaintenanceRule": 8, "Document": 7, "appliesToSensor": 8,
            "Provenance": 47}


def read_jsonl(path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def edge_ref(line_no):
    """edges.csv의 행 위치(헤더가 1행)."""
    return f"{rel(EDGES_FILE)}:L{line_no}"


def load_seed():
    _, nodes = read_csv_rows(NODES_FILE)
    _, edges = read_csv_rows(EDGES_FILE)
    for i, e in enumerate(edges):
        e["_line"] = i + 2
    by_id = {n["nodeId"]: n for n in nodes}
    if len(by_id) != len(nodes):
        raise ValueError("nodes.csv에 nodeId 중복이 있습니다")
    return nodes, edges, by_id


def build_stations_sensors(nodes, edges, by_id):
    sens = [n for n in nodes if n["label"] == "Sensor"]

    pairs = defaultdict(list)  # (Component id, Sensor id) -> [edge lines]
    seen = {}
    for e in edges:
        if e["type"] != "monitors":
            continue
        a, b = e["fromId"], e["toId"]
        la, lb = by_id[a]["label"], by_id[b]["label"]
        if (la, lb) == ("Component", "Sensor"):
            pairs[(a, b)].append(e["_line"])
        elif (la, lb) == ("Sensor", "Component"):
            pairs[(b, a)].append(e["_line"])
        else:
            raise ValueError(f"monitors 끝점 라벨이 예상과 다릅니다: {a}->{b} ({la},{lb})")
        seen[(a, b)] = seen.get((a, b), 0) + 1
    for (c, s), lines in pairs.items():
        if len(lines) != 2 or seen.get((c, s)) != 1 or seen.get((s, c)) != 1:
            raise ValueError(f"monitors 양방향 쌍이 아닙니다: {c},{s} {lines}")
    per_sensor = Counter(s for (_, s) in pairs)
    bad = [s["nodeId"] for s in sens if per_sensor[s["nodeId"]] != 1]
    if bad or len(pairs) != len(sens):
        raise ValueError(f"센서당 스테이션이 정확히 1개가 아닙니다: {bad}")

    feeds = [(e["fromId"], e["toId"], e["_line"]) for e in edges if e["type"] == "feeds_into"]
    for a, b, _ in feeds:
        if by_id[a]["label"] != "Component" or by_id[b]["label"] != "Component":
            raise ValueError(f"feeds_into 끝점이 Component가 아닙니다: {a}->{b}")
    return sorted(pairs.items()), feeds


def build_maintenance_links(nodes, edges, by_id):
    """Sensor->Maintenance triggers와 Maintenance->Sensor resolves가 같은 쌍인지 확인하고 합친다."""
    maint_ids = {n["nodeId"] for n in nodes if n["label"] == "Maintenance"}
    trig = {(e["fromId"], e["toId"]): e["_line"] for e in edges
            if e["type"] == "triggers" and e["toId"] in maint_ids}
    res = {(e["toId"], e["fromId"]): e["_line"] for e in edges
           if e["type"] == "resolves" and e["fromId"] in maint_ids}
    if set(trig) != set(res):
        raise ValueError("triggers(Sensor->Maintenance)와 resolves(Maintenance->Sensor)가 같은 쌍이 아닙니다: "
                         f"한쪽만 {sorted(set(trig) ^ set(res))}")
    if any(by_id[s]["label"] != "Sensor" for s, _ in trig):
        raise ValueError("Maintenance 연결의 반대쪽이 Sensor가 아닙니다")
    per_m = Counter(m for _, m in trig)
    if any(per_m[m] != 1 for m in maint_ids):
        raise ValueError(f"Maintenance마다 센서 1개가 아닙니다: {per_m}")
    return sorted((m, s, trig[(s, m)], res[(s, m)]) for (s, m) in trig)


def verify_sop003(maint_nodes):
    """SOP-003 표에 MAINT ID가 실제 있는지 표(tables.jsonl)와 청크(chunks.jsonl) 양쪽에서 확인한다."""
    tables = [t for t in read_jsonl(TABLES_FILE) if t["doc_id"] == MAINT_DOC_ID]
    chunks = [c for c in read_jsonl(CHUNKS_FILE) if c["doc_id"] == MAINT_DOC_ID]
    found = {}
    for t in tables:
        hdr = t["rows_normalized"][0]
        if not hdr or hdr[0] != "Rule ID":
            continue
        for ri in range(1, len(t["rows_normalized"])):
            rn, rr = t["rows_normalized"][ri], t["rows_raw"][ri]
            found[rn[0]] = {"table_id": t["table_id"], "row_index": ri, "page": t["page"],
                            "norm": dict(zip(hdr, rn)), "raw": dict(zip(t["rows_raw"][0], rr))}
    table_chunk_text = "\n".join(c["text"] for c in chunks if c["kind"] == "table")
    verified = {}
    for m in maint_nodes:
        rid = m["ruleId"]
        if rid in found and f"Rule ID: {rid};" in table_chunk_text:
            verified[rid] = found[rid]
    return verified


class Ledger:
    """Graph 위에 얹은 얇은 래퍼. add()가 트리플과 근거를 함께 받아 장부를 모은다."""

    def __init__(self, graph):
        self.g = graph
        self.sources = {}  # (s, p, o) -> [evidence dict]

    def add(self, s, p, o, evidence):
        evs = [evidence] if isinstance(evidence, dict) else list(evidence)
        if not evs:
            raise ValueError(f"근거 없는 트리플: {s} {p} {o}")
        self.g.add((s, p, o))
        lst = self.sources.setdefault((s, p, o), [])
        for ev in evs:
            if ev not in lst:  # 서로 다른 근거(예: 양방향 두 줄)는 모두 보존
                lst.append(ev)


def check_ledger_complete(graph, sources):
    """그래프의 모든 트리플이 장부에 근거 1개 이상을 가져야 한다(장부에만 있는 트리플도 오류)."""
    missing = [t for t in graph if not sources.get(t)]
    extra = [t for t in sources if t not in graph]
    if missing or extra:
        raise ValueError(f"출처 장부 불완전: 근거 없는 트리플 {len(missing)}개 {missing[:3]}, "
                         f"그래프에 없는 장부 항목 {len(extra)}개")
    return True


def ledger_records(sources):
    recs = []
    for t, evs in sources.items():
        recs.append({"triple": [x.n3() for x in t],
                     "sources": sorted(evs, key=lambda e: json.dumps(e, sort_keys=True, ensure_ascii=False))})
    recs.sort(key=lambda r: r["triple"])
    return recs


def assert_no_later_stage_items(graph):
    """⑦ 이후 경로(AnomalyEvent 등)와 ⑥ 산출(causallyAffects 등)이 섞이지 않았는지 확인한다."""
    for c in FORBIDDEN_TYPES:
        if any(True for _ in graph.subjects(RDF.type, IM[c])):
            raise ValueError(f"금지 타입 노드가 있습니다: {c}")
    for p in FORBIDDEN_PREDICATES:
        if any(True for _ in graph.triples((None, IM[p], None))):
            raise ValueError(f"금지 관계 트리플이 있습니다: {p}")


def verify_manifest_hashes(manifest, root=REPO_ROOT):
    """doc_manifest의 file_sha256을 믿지 않고 PDF를 실제로 읽어 다시 계산해 대조한다(읽기 전용)."""
    actual = {}
    for d in manifest:
        path = root / d["file"]
        if not path.is_file():
            raise ValueError(f"문서 파일이 없습니다: {d['file']}")
        h = sha256_file(path)
        if h != d["file_sha256"]:
            raise ValueError(f"PDF 해시 불일치 {d['doc_id']}: manifest={d['file_sha256']} 실제={h}")
        actual[d["doc_id"]] = h
    return actual


def locate_in_tables(tables, rule_id, doc_id=MAINT_DOC_ID):
    """rows_normalized 전체에서 rule_id와 같은 셀이 정확히 1개일 때만 위치를 돌려준다.
    rowIndex·colIndex는 1부터 센다(헤더 행 = 1, 첫 열 = 1)."""
    hits = []
    for t in tables:
        if t["doc_id"] != doc_id:
            continue
        for ri, row in enumerate(t["rows_normalized"]):
            for ci, cell in enumerate(row):
                if cell == rule_id:
                    hits.append((t, ri, ci))
    if len(hits) != 1:
        raise ValueError(f"{rule_id}가 {doc_id} 표에서 {len(hits)}번 나옵니다(정확히 1번이어야 함)")
    t, ri, ci = hits[0]
    quote = " | ".join(t["rows_normalized"][ri])
    return {"tableId": t["table_id"], "page": t["page"], "rowIndex": ri + 1, "colIndex": ci + 1,
            "sourceQuote": quote, "textSha256": sha256_text(quote)}


def check_row_index_consistent(rule_id, mapping_row_index, provenance_row_index):
    """매핑표 sop003RowIndex와 문서 Provenance rowIndex는 같은 규약(1부터)이어야 한다."""
    if mapping_row_index != provenance_row_index:
        raise ValueError(f"{rule_id}: 매핑표 행 번호 {mapping_row_index} != Provenance rowIndex {provenance_row_index}")


def main():
    nodes, edges, by_id = load_seed()
    mon_pairs, feeds = build_stations_sensors(nodes, edges, by_id)
    comps = [n for n in nodes if n["label"] == "Component"]
    sens = [n for n in nodes if n["label"] == "Sensor"]
    maints = [n for n in nodes if n["label"] == "Maintenance"]
    maint_links = build_maintenance_links(nodes, edges, by_id)
    _, manifest = read_csv_rows(MANIFEST_FILE)
    actual_pdf_sha = verify_manifest_hashes(manifest)
    verified = verify_sop003(maints)
    all_tables = read_jsonl(TABLES_FILE)
    doc_locs = {m["ruleId"]: locate_in_tables(all_tables, m["ruleId"]) for m in maints}
    sop3_ok = (all(m["ruleId"] in verified for m in maints)
               and any(d["doc_id"] == MAINT_DOC_ID for d in manifest))

    nodes_rel, nodes_sha = rel(NODES_FILE), sha256_file(NODES_FILE)
    edges_rel, edges_sha = rel(EDGES_FILE), sha256_file(EDGES_FILE)
    manifest_rel, manifest_sha = rel(MANIFEST_FILE), sha256_file(MANIFEST_FILE)

    def node_ev(node):
        return {"file": nodes_rel, "rowId": node["nodeId"], "sha256": nodes_sha}

    def edge_ev(line):
        return {"file": edges_rel, "line": line, "sha256": edges_sha}
    ident = {n["nodeId"]: n["name"] for n in comps + sens}
    ident.update({m["nodeId"]: m["ruleId"] for m in maints})

    g = Graph()
    g.bind("im", IM)
    g.bind("inst", INST)
    L = Ledger(g)
    prov_rows = []
    doc_prov_rows = []

    def add_prov(subject_id, node):
        pid = f"prov_{node['nodeId']}"
        ev = node_ev(node)
        L.add(INST[pid], RDF.type, IM.Provenance, ev)
        L.add(INST[pid], IM.sourceKind, Literal("seedCsv"), ev)
        L.add(INST[pid], IM.fileName, Literal(nodes_rel), ev)
        L.add(INST[pid], IM.sourceRowId, Literal(node["nodeId"]), ev)
        L.add(INST[pid], IM.fileSha256, Literal(nodes_sha), ev)
        L.add(INST[subject_id], IM.hasProvenance, INST[pid], ev)
        prov_rows.append([pid, "seedCsv", nodes_rel, node["nodeId"], nodes_sha, subject_id])
        return pid

    st_rows, se_rows, mr_rows = [], [], []
    for n in comps:
        s = INST[n["name"]]
        L.add(s, RDF.type, IM.Station, node_ev(n))
        L.add(s, IM.identifier, Literal(n["name"]), node_ev(n))
        L.add(s, IM.sourceNodeId, Literal(n["nodeId"]), node_ev(n))
        L.add(s, IM.stationType, Literal(n["stationType"]), node_ev(n))
        L.add(s, IM.zone, Literal(n["zone"]), node_ev(n))
        pid = add_prov(n["name"], n)
        st_rows.append([n["name"], n["nodeId"], n["stationType"], n["zone"], pid])
    for n in sens:
        s = INST[n["name"]]
        L.add(s, RDF.type, IM.Sensor, node_ev(n))
        L.add(s, IM.identifier, Literal(n["name"]), node_ev(n))
        L.add(s, IM.sensorType, Literal(n["sensorType"]), node_ev(n))
        L.add(s, IM.unit, Literal(n["unit"]), node_ev(n))
        L.add(s, IM.sourceNodeId, Literal(n["nodeId"]), node_ev(n))
        pid = add_prov(n["name"], n)
        se_rows.append([n["name"], n["sensorType"], n["unit"], n["nodeId"], pid])

    hs_rows = []
    for (c, s), lines in mon_pairs:
        L.add(INST[ident[c]], IM.hasSensor, INST[ident[s]], [edge_ev(x) for x in sorted(lines)])
        hs_rows.append([ident[c], ident[s], c, s, ";".join(edge_ref(x) for x in sorted(lines))])
    fi_rows = []
    for a, b, line in feeds:
        L.add(INST[ident[a]], IM.feedsInto, INST[ident[b]], edge_ev(line))
        fi_rows.append([ident[a], ident[b], a, b, edge_ref(line)])

    doc_rows = []
    for d in manifest:
        s = INST[d["doc_id"]]
        mev = {"file": manifest_rel, "rowId": d["doc_id"], "sha256": manifest_sha}
        pev = {"file": d["file"], "sha256": actual_pdf_sha[d["doc_id"]]}
        L.add(s, RDF.type, IM.Document, mev)
        L.add(s, IM.identifier, Literal(d["doc_id"]), mev)
        L.add(s, IM.sourcePath, Literal(d["file"]), [mev, pev])
        L.add(s, IM.sourceSha256, Literal(d["file_sha256"]), [mev, pev])
        L.add(s, IM.pageCount, Literal(d["pages"], datatype=XSD.positiveInteger), mev)
        doc_rows.append([d["doc_id"], d["file"], d["file_sha256"], d["pages"]])

    ap_rows = []
    maint_sensor = {m: (s, tl, rl) for m, s, tl, rl in maint_links}
    for n in maints:
        s = INST[n["ruleId"]]
        nev = node_ev(n)
        loc = doc_locs[n["ruleId"]]
        dev = {"document": MAINT_DOC_ID, "tableId": loc["tableId"], "rowIndex": loc["rowIndex"],
               "textSha256": loc["textSha256"]}
        L.add(s, RDF.type, IM.MaintenanceRule, nev)
        L.add(s, IM.identifier, Literal(n["ruleId"]), nev)
        L.add(s, IM.sourceNodeId, Literal(n["nodeId"]), nev)
        L.add(s, IM.responseText, Literal(n["action"]), nev)
        L.add(s, IM.priority, Literal(n["priority"]), nev)
        L.add(s, IM.extractionMethod, Literal("seedCsv"), nev)
        if sop3_ok:
            L.add(s, IM.sourceDocument, INST[MAINT_DOC_ID], dev)
        pid = add_prov(n["ruleId"], n)
        # SOP-003 문서 위치 Provenance (규칙당 seedCsv 1 + document 1)
        did = f"prov_doc_{n['ruleId']}"
        D = INST[did]
        L.add(D, RDF.type, IM.Provenance, dev)
        L.add(D, IM.sourceKind, Literal("document"), dev)
        L.add(D, IM.page, Literal(loc["page"], datatype=XSD.positiveInteger), dev)
        L.add(D, IM.tableId, Literal(loc["tableId"]), dev)
        L.add(D, IM.rowIndex, Literal(loc["rowIndex"], datatype=XSD.positiveInteger), dev)
        L.add(D, IM.colIndex, Literal(loc["colIndex"], datatype=XSD.positiveInteger), dev)
        L.add(D, IM.sourceQuote, Literal(loc["sourceQuote"]), dev)
        L.add(D, IM.textSha256, Literal(loc["textSha256"]), dev)
        L.add(s, IM.hasProvenance, D, dev)
        doc_prov_rows.append([did, "document", MAINT_DOC_ID, loc["page"], loc["tableId"], loc["rowIndex"],
                              loc["colIndex"], loc["sourceQuote"], loc["textSha256"], n["ruleId"]])
        sid, tl, rl = maint_sensor[n["nodeId"]]
        L.add(s, IM.appliesToSensor, INST[ident[sid]], [edge_ev(tl), edge_ev(rl)])
        mr_rows.append([n["ruleId"], n["nodeId"], n["action"], n["priority"],
                        MAINT_DOC_ID if sop3_ok else "", pid])
        ap_rows.append([n["ruleId"], ident[sid], n["nodeId"], sid, edge_ref(tl), edge_ref(rl)])

    # 매핑표: 원본 Maintenance 노드 vs SOP-003 표 행. 두 쪽 텍스트는 그대로 두고 일치 여부만 표시한다.
    sensor_by_id = {n["nodeId"]: n for n in sens}
    station_of = {s: c for (c, s), _ in mon_pairs}
    map_rows = []
    for n in maints:
        sid = maint_sensor[n["nodeId"]][0]
        sn = sensor_by_id[sid]
        stn = by_id[station_of[sid]]
        v = verified.get(n["ruleId"])
        if not v:
            map_rows.append([n["ruleId"], n["nodeId"]] + [""] * 17)
            continue
        norm, raw = v["norm"], v["raw"]
        map_row_index = v["row_index"] + 1  # 매핑표도 Provenance와 같이 1부터(헤더 행 = 1)
        check_row_index_consistent(n["ruleId"], map_row_index, doc_locs[n["ruleId"]]["rowIndex"])
        map_rows.append([
            n["ruleId"], n["nodeId"], v["table_id"], v["page"], map_row_index,
            n["action"], raw["Action"], norm["Action"], str(n["action"] == norm["Action"]).lower(),
            n["priority"], norm["Priority"], str(n["priority"] == norm["Priority"]).lower(),
            sn["sensorType"], norm["Sensor"], str(sn["sensorType"] == norm["Sensor"]).lower(),
            stn["name"], norm["Station"], str(stn["name"] == norm["Station"]).lower(),
            norm["Trigger"],
        ])
    map_header = ["ruleId", "seedNodeId", "sop003TableId", "sop003Page", "sop003RowIndex",
                  "seedAction", "sop003ActionRaw", "sop003ActionNormalized", "actionExactMatch",
                  "seedPriority", "sop003Priority", "priorityMatch",
                  "seedSensorType", "sop003Sensor", "sensorTypeMatch",
                  "seedStation", "sop003Station", "stationMatch", "sop003Trigger"]

    write_csv(OUT_DIR / "stations.csv", ["identifier", "sourceNodeId", "stationType", "zone", "provenanceId"], st_rows)
    write_csv(OUT_DIR / "sensors.csv", ["identifier", "sensorType", "unit", "sourceNodeId", "provenanceId"], se_rows)
    write_csv(OUT_DIR / "documents.csv", ["identifier", "sourcePath", "sourceSha256", "pageCount"], doc_rows)
    write_csv(OUT_DIR / "maintenance_rules.csv",
              ["identifier", "sourceNodeId", "responseText", "priority", "sourceDocument", "provenanceId"], mr_rows)
    write_csv(OUT_DIR / "has_sensor.csv", ["station", "sensor", "stationNodeId", "sensorNodeId", "sourceEdgeRows"], hs_rows)
    write_csv(OUT_DIR / "feeds_into.csv", ["fromStation", "toStation", "fromNodeId", "toNodeId", "sourceEdgeRow"], fi_rows)
    write_csv(OUT_DIR / "applies_to_sensor.csv",
              ["rule", "sensor", "ruleNodeId", "sensorNodeId", "sourceEdgeRowSensorToRule", "sourceEdgeRowRuleToSensor"], ap_rows)
    write_csv(OUT_DIR / "provenance.csv",
              ["provenanceId", "sourceKind", "fileName", "sourceRowId", "fileSha256", "subject"], prov_rows)
    write_csv(MAP_DIR / "maint_seed_vs_sop003.csv", map_header, map_rows)
    write_csv(DOC_PROV_FILE, ["provenanceId", "sourceKind", "document", "page", "tableId", "rowIndex",
                              "colIndex", "sourceQuote", "textSha256", "subject"], doc_prov_rows)

    assert_no_later_stage_items(g)
    check_ledger_complete(g, L.sources)
    ttl_path = write_text(OUT_DIR / "instances.ttl", g.serialize(format="turtle"))
    ledger_path = write_jsonl(LEDGER_FILE, ledger_records(L.sources))

    counts = {
        "Station": len(st_rows), "Sensor": len(se_rows), "hasSensor": len(hs_rows), "feedsInto": len(fi_rows),
        "MaintenanceRule": len(mr_rows), "Document": len(doc_rows), "appliesToSensor": len(ap_rows),
        "Provenance": len(prov_rows) + len(doc_prov_rows),
    }
    summary = {
        "counts": counts,
        "expected": EXPECTED,
        "seedNodesTotal": len(nodes), "seedEdgesTotal": len(edges),
        "seedNodeLabelCounts": dict(sorted(Counter(n["label"] for n in nodes).items())),
        "seedEdgeTypeCounts": dict(sorted(Counter(e["type"] for e in edges).items())),
        "triggersEqualsResolves": True,
        "sop003Verified": sop3_ok,
        "tripleCount": len(g),
        "ledgerComplete": True,
        "pdfHashesRecomputed": True,
        "inputSha256": {rel(p): sha256_file(p) for p in
                        (NODES_FILE, EDGES_FILE, MANIFEST_FILE, TABLES_FILE, CHUNKS_FILE)},
        "outputSha256": {rel(ttl_path): sha256_file(ttl_path), rel(ledger_path): sha256_file(ledger_path)},
    }
    write_json(KG_BUILD / "summary.json", summary)
    print(json.dumps(counts, ensure_ascii=False))
    bad = {k: (counts[k], v) for k, v in EXPECTED.items() if counts[k] != v}
    print("개수 불일치:" if bad else "개수 일치", bad if bad else "")
    print(f"SOP-003 연결 확인: {sop3_ok}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
