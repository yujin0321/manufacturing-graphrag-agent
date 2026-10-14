"""원본 KG(seed CSV) → ontology_v1 스키마 RDF 변환(③).

실행: PYTHONPATH=src .venv/Scripts/python.exe -m imaks_kg.kg.seed_to_rdf

- 입력(읽기 전용): imaks_data/kg_seed/nodes.csv, edges.csv 두 파일만 읽는다. 같은 폴더의 다른 파일
  (평가용 정답 규칙 파일 등)은 읽지 않는다.
- 출력: kg_build/seed.ttl, reports/seed_to_rdf_counts.md(개수 대조표, 코드가 생성)
- 이번 출력에 넣는 것: Station 9(Component), Sensor 22, hasSensor 22(monitors 44줄), feedsInto 3, 각각의 Provenance.
- 이월(B): Maintenance 노드, Sensor→Maintenance triggers, resolves, Sensor 임계값 컬럼.
- 이월(⑦): AnomalyEvent 노드, Sensor→AnomalyEvent triggers, correlates_with. 변환 함수는 seed_events_post7.py에
  있으며 이 모듈은 그것을 부르지 않는다.
- 노드·엣지 종류는 아래 계획표(NODE_PLAN, EDGE_PLAN)에 있는 것만 허용한다. 모르는 종류가 나오면 멈춘다.
- 값은 원본 문자열 그대로 쓴다(수치 변환·정규화 없음).
"""
import sys
from collections import Counter, OrderedDict

from rdflib import RDF, Graph, Literal, XSD

from imaks_kg.common.io_utils import read_csv_rows, write_text
from imaks_kg.common.provenance import sha256_file
from imaks_kg.kg.naming import (
    IM, INST, SOURCE_KIND_SEED, edge_prov_iri, edge_row_id, entity_iri, node_prov_iri,
)
from imaks_kg.settings import KG_BUILD, KG_SEED_DIR, REPORTS_DIR, rel

NODES_FILE = KG_SEED_DIR / "nodes.csv"
EDGES_FILE = KG_SEED_DIR / "edges.csv"
OUT_TTL = KG_BUILD / "seed.ttl"
OUT_COUNTS = REPORTS_DIR / "seed_to_rdf_counts.md"

EXPECTED_NODES = 115
EXPECTED_EDGES = 341
# 출력 TTL에서 다시 세었을 때 나와야 하는 개수
EXPECTED_TTL = {"Station": 9, "Sensor": 22, "hasSensor": 22, "feedsInto": 3}

CONVERT, DEFER_B, DEFER_7, EXCLUDE = "변환", "이월(B)", "이월(⑦)", "제외"
CATEGORIES = [CONVERT, DEFER_B, DEFER_7, EXCLUDE]

# 노드 label → (처리, 사유)
NODE_PLAN = OrderedDict([
    ("Component", (CONVERT, "Station으로 1:1 매핑(CLAUDE.md §3)")),
    ("Sensor", (CONVERT, "Sensor. 임계값 컬럼은 넣지 않음(B의 ThresholdRule 몫)")),
    ("Maintenance", (DEFER_B, "MaintenanceRule은 Rule·Document와 함께 B에서 변환")),
    ("AnomalyEvent", (DEFER_7, "⑦ 이후 경로(seed_events_post7.py). ⑥ 입력에 넣지 않음")),
    ("System", (EXCLUDE, "질문 5개에 불필요. 처리 미결정(schema_tables 6·9장)")),
    ("Zone", (EXCLUDE, "Zone 클래스 없음. Station.zone 속성으로 흡수")),
    ("Person", (EXCLUDE, "범위 밖(CLAUDE.md §3: Person 만들지 않음)")),
    ("SafetyEvent", (EXCLUDE, "범위 밖(Layer 2 성격, schema_tables 6장)")),
])

# 엣지 (type, from label, to label) → (처리, 대상 관계, 사유)
EDGE_PLAN = OrderedDict([
    (("monitors", "Component", "Sensor"), (CONVERT, "hasSensor", "정방향 줄. 역방향 줄과 한 관계로 합침")),
    (("monitors", "Sensor", "Component"), (CONVERT, "hasSensor", "역방향 줄. 정방향 줄과 한 관계로 합침")),
    (("feeds_into", "Component", "Component"), (CONVERT, "feedsInto", "그대로")),
    (("triggers", "Sensor", "Maintenance"), (DEFER_B, "appliesToSensor", "resolves와 합쳐 B에서 변환")),
    (("resolves", "Maintenance", "Sensor"), (DEFER_B, "appliesToSensor", "triggers(Sensor→Maintenance)와 합쳐 B에서 변환")),
    (("triggers", "Sensor", "AnomalyEvent"), (DEFER_7, "triggers", "⑦ 이후 경로")),
    (("correlates_with", "Sensor", "Sensor"), (DEFER_7, "correlatesWith", "⑦ 이후 경로")),
    (("contains", "System", "Zone"), (EXCLUDE, "", "System·Zone 적재 안 함")),
    (("contains", "Zone", "Component"), (EXCLUDE, "", "Zone 적재 안 함(Station.zone으로 흡수)")),
    (("part_of", "Component", "System"), (EXCLUDE, "", "System 적재 안 함")),
    (("authorized_for", "Person", "Zone"), (EXCLUDE, "", "Person·권한 범위 밖")),
    (("involves", "SafetyEvent", "Person"), (EXCLUDE, "", "SafetyEvent·Person 범위 밖")),
    (("detected_in", "SafetyEvent", "Zone"), (EXCLUDE, "", "SafetyEvent·Zone 범위 밖")),
])

# 원본 컬럼 → 온톨로지 속성 (허용목록. 여기에 없는 컬럼은 옮기지 않는다)
STATION_COLS = [("name", "identifier"), ("nodeId", "sourceNodeId"), ("stationType", "stationType"), ("zone", "zone")]
SENSOR_COLS = [("name", "identifier"), ("nodeId", "sourceNodeId"), ("sensorType", "sensorType"), ("unit", "unit")]
# Sensor 행에 있지만 이번에 넣지 않고 B(ThresholdRule)로 넘기는 컬럼. 위 허용목록에 들어가면 안 된다.
SENSOR_DEFERRED_B_COLS = ("nominalValue", "warnLo", "warnHi", "critLo", "critHi")
assert not set(SENSOR_DEFERRED_B_COLS) & {c for c, _ in SENSOR_COLS}

TTL_HEADER = (
    "# 생성 파일: imaks_kg.kg.seed_to_rdf (직접 고치지 말 것)\n"
    "# 입력: imaks_data/kg_seed/nodes.csv, edges.csv. 스키마: ontology_v1/ontology.ttl\n"
    "# 포함: Station, Sensor, hasSensor, feedsInto, Provenance(seedCsv). 이벤트·규칙은 포함하지 않음.\n\n"
)


def _add_prov(g, prov, file_rel, row_ids):
    g.add((prov, RDF.type, IM.Provenance))
    g.add((prov, IM.sourceKind, Literal(SOURCE_KIND_SEED)))
    g.add((prov, IM.fileName, Literal(file_rel)))
    for rid in row_ids:
        g.add((prov, IM.sourceRowId, Literal(rid)))


def _add_entity(g, row, cls, cols, nodes_rel):
    for c, _ in cols:
        if row.get(c, "") == "":
            raise ValueError(f"{row.get('nodeId')}: 필수 컬럼 {c}가 비어 있음")
    s = entity_iri(row["name"])
    g.add((s, RDF.type, cls))
    for c, prop in cols:
        g.add((s, IM[prop], Literal(row[c])))
    prov = node_prov_iri(row["nodeId"])
    _add_prov(g, prov, nodes_rel, [row["nodeId"]])
    g.add((s, IM.hasProvenance, prov))
    return s


def build_graph(nodes, edges, nodes_rel="imaks_data/kg_seed/nodes.csv", edges_rel="imaks_data/kg_seed/edges.csv"):
    """seed 행 → (Graph, 집계). 파일을 쓰지 않는 순수 함수(테스트용)."""
    by_id = {}
    for r in nodes:
        if r["nodeId"] in by_id:
            raise ValueError(f"nodeId 중복: {r['nodeId']}")
        if r["label"] not in NODE_PLAN:
            raise ValueError(f"계획표에 없는 노드 종류: {r['label']} ({r['nodeId']})")
        by_id[r["nodeId"]] = r

    g = Graph()
    g.bind("im", IM)
    g.bind("inst", INST)
    g.bind("xsd", XSD)

    node_rows = Counter()
    node_made = Counter()
    for r in nodes:
        lab = r["label"]
        node_rows[lab] += 1
        if lab == "Component":
            _add_entity(g, r, IM.Station, STATION_COLS, nodes_rel)
            node_made[lab] += 1
        elif lab == "Sensor":
            _add_entity(g, r, IM.Sensor, SENSOR_COLS, nodes_rel)
            node_made[lab] += 1

    edge_rows = Counter()
    monitors = {}  # (stationNodeId, sensorNodeId) -> {"fwd": row번호, "rev": row번호}
    feeds = []
    for i, e in enumerate(edges, 1):
        fr, to = by_id.get(e["fromId"]), by_id.get(e["toId"])
        if fr is None or to is None:
            raise ValueError(f"edges.csv {edge_row_id(i)}: 없는 노드를 가리킴 {e['fromId']}→{e['toId']}")
        key = (e["type"], fr["label"], to["label"])
        if key not in EDGE_PLAN:
            raise ValueError(f"계획표에 없는 엣지 종류: {key} ({edge_row_id(i)})")
        edge_rows[key] += 1
        if key == ("monitors", "Component", "Sensor"):
            slot = monitors.setdefault((fr["nodeId"], to["nodeId"]), {})
            assert "fwd" not in slot, f"monitors 정방향 중복: {key} {edge_row_id(i)}"
            slot["fwd"] = i
        elif key == ("monitors", "Sensor", "Component"):
            slot = monitors.setdefault((to["nodeId"], fr["nodeId"]), {})
            assert "rev" not in slot, f"monitors 역방향 중복: {key} {edge_row_id(i)}"
            slot["rev"] = i
        elif key == ("feeds_into", "Component", "Component"):
            feeds.append((i, fr, to))

    rel_made = Counter()
    # hasSensor: 양방향 두 줄이 모두 있어야 한 관계를 만든다. 출처는 Sensor에 붙인다(센서당 hasSensor가 1개라 1:1).
    for (st_id, se_id), slot in sorted(monitors.items()):
        if set(slot) != {"fwd", "rev"}:
            raise ValueError(f"monitors 쌍이 불완전: {st_id}-{se_id} {slot}")
        st, se = entity_iri(by_id[st_id]["name"]), entity_iri(by_id[se_id]["name"])
        g.add((st, IM.hasSensor, se))
        prov = edge_prov_iri("hasSensor", st_id, se_id)
        _add_prov(g, prov, edges_rel, [edge_row_id(slot["fwd"]), edge_row_id(slot["rev"])])
        g.add((se, IM.hasProvenance, prov))
        rel_made["hasSensor"] += 1
    # feedsInto: 출처는 원인 쪽(주어) Station에 붙인다.
    for i, fr, to in feeds:
        s, o = entity_iri(fr["name"]), entity_iri(to["name"])
        g.add((s, IM.feedsInto, o))
        prov = edge_prov_iri("feedsInto", fr["nodeId"], to["nodeId"])
        _add_prov(g, prov, edges_rel, [edge_row_id(i)])
        g.add((s, IM.hasProvenance, prov))
        rel_made["feedsInto"] += 1

    # 옮기지 않은(비어 있지 않은) 컬럼 기록
    mapped = {"Component": {c for c, _ in STATION_COLS}, "Sensor": {c for c, _ in SENSOR_COLS}}
    not_carried = {}
    for lab, cols in mapped.items():
        seen = set()
        for r in nodes:
            if r["label"] == lab:
                seen |= {c for c, v in r.items() if v != "" and c != "label"}
        not_carried[lab] = sorted(seen - cols)

    stats = {
        "node_rows": node_rows, "node_made": node_made, "edge_rows": edge_rows,
        "rel_made": rel_made, "not_carried": not_carried,
        "n_nodes": len(nodes), "n_edges": len(edges),
    }
    return g, stats


def serialize(g) -> str:
    """결정적 Turtle 텍스트(rdflib turtle 직렬화는 주어·속성·값을 정렬한다)."""
    return TTL_HEADER + g.serialize(format="turtle")


def ttl_counts(ttl_text: str) -> dict:
    """출력 TTL을 다시 읽어 실제 트리플 기준으로 센다."""
    g = Graph().parse(data=ttl_text, format="turtle")
    return {
        "Station": len(set(g.subjects(RDF.type, IM.Station))),
        "Sensor": len(set(g.subjects(RDF.type, IM.Sensor))),
        "Provenance": len(set(g.subjects(RDF.type, IM.Provenance))),
        "hasSensor": len(list(g.triples((None, IM.hasSensor, None)))),
        "feedsInto": len(list(g.triples((None, IM.feedsInto, None)))),
        "hasProvenance": len(list(g.triples((None, IM.hasProvenance, None)))),
        "triples": len(g),
    }


def counts_table(stats, ttl, input_hashes) -> tuple[str, dict]:
    """개수 대조표(Markdown)와 합계. 합계가 원본 개수와 다르면 AssertionError."""
    lines = ["# seed → RDF 개수 대조표 (③)", "",
             "생성: `imaks_kg.kg.seed_to_rdf` (직접 고치지 말 것). 원본 개수는 CSV에서 센 값이다.", "",
             "## 입력", "", "| 파일 | 데이터 행 | SHA-256 |", "|---|---|---|"]
    for f, (n, h) in input_hashes.items():
        lines.append(f"| `{f}` | {n} | `{h}` |")

    lines += ["", "## 노드 (nodes.csv `label`)", "",
              "| 종류 | 원본 | 변환 | 이월(B) | 이월(⑦) | 제외 | 결과(seed.ttl) | 사유 |",
              "|---|---|---|---|---|---|---|---|"]
    node_tot = Counter()
    for lab, (cat, why) in NODE_PLAN.items():
        n = stats["node_rows"].get(lab, 0)
        node_tot["원본"] += n
        node_tot[cat] += n
        cells = [str(n) if c == cat else "0" for c in CATEGORIES]
        made = {"Component": f"Station {stats['node_made'].get(lab, 0)}",
                "Sensor": f"Sensor {stats['node_made'].get(lab, 0)}"}.get(lab, "-")
        lines.append(f"| {lab} | {n} | " + " | ".join(cells) + f" | {made} | {why} |")
    lines.append(f"| **합계** | **{node_tot['원본']}** | " + " | ".join(str(node_tot[c]) for c in CATEGORIES) + " | | |")

    lines += ["", "## 엣지 (edges.csv `type`, 양 끝 노드 종류)", "",
              "| 종류 | 원본 | 변환 | 이월(B) | 이월(⑦) | 제외 | 대상 관계 | 사유 |",
              "|---|---|---|---|---|---|---|---|"]
    edge_tot = Counter()
    for key, (cat, target, why) in EDGE_PLAN.items():
        n = stats["edge_rows"].get(key, 0)
        edge_tot["원본"] += n
        edge_tot[cat] += n
        cells = [str(n) if c == cat else "0" for c in CATEGORIES]
        t, a, b = key
        lines.append(f"| {t} ({a}→{b}) | {n} | " + " | ".join(cells) + f" | {target or '-'} | {why} |")
    lines.append(f"| **합계** | **{edge_tot['원본']}** | " + " | ".join(str(edge_tot[c]) for c in CATEGORIES) + " | | |")

    lines += ["", "## 결과 관계 수 (변환 줄 → 생성 관계)", "",
              "| 관계 | 원본 줄 | 생성(변환 코드) | seed.ttl 실제 트리플 |", "|---|---|---|---|"]
    mon = stats["edge_rows"].get(("monitors", "Component", "Sensor"), 0) + stats["edge_rows"].get(("monitors", "Sensor", "Component"), 0)
    lines.append(f"| hasSensor | monitors {mon}줄(양방향) | {stats['rel_made']['hasSensor']} | {ttl['hasSensor']} |")
    lines.append(f"| feedsInto | feeds_into {stats['edge_rows'].get(('feeds_into', 'Component', 'Component'), 0)}줄 "
                 f"| {stats['rel_made']['feedsInto']} | {ttl['feedsInto']} |")

    lines += ["", "## seed.ttl 실제 트리플 기준 개수", "", "| 항목 | 개수 | 기대 |", "|---|---|---|"]
    for k in ["Station", "Sensor", "hasSensor", "feedsInto", "Provenance", "hasProvenance", "triples"]:
        lines.append(f"| {k} | {ttl[k]} | {EXPECTED_TTL.get(k, '-')} |")

    lines += ["", "## 옮기지 않은 컬럼 (비어 있지 않은 원본 컬럼 중)", "", "| 노드 종류 | 컬럼 | 처리 |", "|---|---|---|"]
    for lab, cols in stats["not_carried"].items():
        for c in cols:
            how = "이월(B): ThresholdRule 몫" if c in SENSOR_DEFERRED_B_COLS else "미반영: 온톨로지에 대응 속성 없음"
            lines.append(f"| {lab} | {c} | {how} |")
    lines.append("")

    assert node_tot["원본"] == stats["n_nodes"] == EXPECTED_NODES, f"노드 합계 불일치 {node_tot['원본']} / {stats['n_nodes']}"
    assert sum(node_tot[c] for c in CATEGORIES) == EXPECTED_NODES
    assert edge_tot["원본"] == stats["n_edges"] == EXPECTED_EDGES, f"엣지 합계 불일치 {edge_tot['원본']} / {stats['n_edges']}"
    assert sum(edge_tot[c] for c in CATEGORIES) == EXPECTED_EDGES
    for k, v in EXPECTED_TTL.items():
        assert ttl[k] == v, f"seed.ttl {k} 개수 {ttl[k]} != 기대 {v}"
    assert ttl["hasSensor"] == stats["rel_made"]["hasSensor"] and ttl["feedsInto"] == stats["rel_made"]["feedsInto"]
    return "\n".join(lines), {"nodes": dict(node_tot), "edges": dict(edge_tot)}


def load_inputs():
    _, nodes = read_csv_rows(NODES_FILE)
    _, edges = read_csv_rows(EDGES_FILE)
    return nodes, edges


def main():
    nodes, edges = load_inputs()
    g, stats = build_graph(nodes, edges, rel(NODES_FILE), rel(EDGES_FILE))
    text = serialize(g)
    ttl = ttl_counts(text)
    hashes = {rel(NODES_FILE): (len(nodes), sha256_file(NODES_FILE)),
              rel(EDGES_FILE): (len(edges), sha256_file(EDGES_FILE))}
    table, totals = counts_table(stats, ttl, hashes)
    write_text(OUT_TTL, text)
    write_text(OUT_COUNTS, table)
    print(f"노드 합계 {totals['nodes']}")
    print(f"엣지 합계 {totals['edges']}")
    print(f"seed.ttl: {ttl}")
    print("산출물:", rel(OUT_TTL), rel(OUT_COUNTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
