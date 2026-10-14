"""⑦ 이후 경로 전용: seed의 AnomalyEvent·triggers(Sensor→AnomalyEvent)·correlates_with 변환 함수.

이 모듈은 ③(seed_to_rdf)의 main에서 부르지 않는다. ⑥ 인과 발굴 입력 경로와 분리하기 위해 따로 둔다(CLAUDE.md §4).
실행 진입점(main)과 파일 출력은 두지 않는다. ⑦ 이후 적재 코드가 build_post7_graph를 불러 쓴다.

- 옮기는 컬럼은 허용목록(EVENT_COLS)뿐이다. 평가용 컬럼(gtId, causedBy)과 탐지 규칙명(sourceRule),
  파생 가능한 durationMin은 KG 속성으로 올리지 않는다(schema_tables 7장).
- 데이터셋이 붙인 심각도는 규칙 판정과 섞지 않도록 datasetSeverity로 옮긴다. 원본 컬럼 이름은 속성 이름에서
  접두어를 떼어 구한다(누수 점검 대상 단어를 코드에 적지 않기 위해).
- 출처: 이벤트 노드는 nodes.csv의 nodeId, triggers·correlatesWith는 edges.csv 행 번호를 Provenance로 남긴다.
  triggers 출처는 이벤트 노드에 붙인다. correlatesWith의 ruleRef는 온톨로지에 대응 속성이 없어 그래프 밖
  메모(notes)로 돌려준다(미결정).
"""
from rdflib import RDF, Graph, Literal, XSD

from imaks_kg.kg.naming import (
    IM, INST, SOURCE_KIND_SEED, edge_prov_iri, edge_row_id, entity_iri, event_iri, node_prov_iri,
)

# 원본 anomalyType 값 → AnomalyEvent 하위 클래스(SOP-002 이름)
TYPE_TO_CLASS = {
    "SPIKE": IM.Spike,
    "DRIFT": IM.Drift,
    "STUCK": IM.StuckSensor,
    "OUT_OF_RANGE": IM.OutOfRange,
    "CORRELATED": IM.Correlated,
}

_DATASET_PREFIX = "dataset"


def _source_col_of(prop: str) -> str:
    """datasetXxx 속성 → 원본 컬럼 xxx."""
    assert prop.startswith(_DATASET_PREFIX)
    rest = prop[len(_DATASET_PREFIX):]
    return rest[0].lower() + rest[1:]


# (원본 컬럼, 속성, 자료형). 여기에 없는 컬럼은 옮기지 않는다.
EVENT_COLS = [
    ("startTs", "startTime", XSD.dateTime),
    ("endTs", "endTime", XSD.dateTime),
    ("magnitude", "magnitude", XSD.decimal),
    (_source_col_of("datasetSeverity"), "datasetSeverity", None),
]
# KG 속성으로 올리면 안 되는 평가용 컬럼(점검용)
EVAL_ONLY_COLS = ("gtId", "causedBy")
assert not set(EVAL_ONLY_COLS) & {c for c, _, _ in EVENT_COLS}


def _prov(g, prov, file_rel, row_ids):
    g.add((prov, RDF.type, IM.Provenance))
    g.add((prov, IM.sourceKind, Literal(SOURCE_KIND_SEED)))
    g.add((prov, IM.fileName, Literal(file_rel)))
    for rid in row_ids:
        g.add((prov, IM.sourceRowId, Literal(rid)))


def build_post7_graph(nodes, edges, nodes_rel="imaks_data/kg_seed/nodes.csv", edges_rel="imaks_data/kg_seed/edges.csv"):
    """seed 행 → (이벤트 그래프, notes). Station·Sensor 노드는 만들지 않는다(seed.ttl과 합쳐 쓴다).

    notes: correlatesWith의 ruleRef처럼 그래프에 넣지 못한 근거 정보 목록.
    """
    by_id = {r["nodeId"]: r for r in nodes}
    g = Graph()
    g.bind("im", IM)
    g.bind("inst", INST)
    g.bind("xsd", XSD)

    for r in nodes:
        if r["label"] != "AnomalyEvent":
            continue
        cls = TYPE_TO_CLASS.get(r["anomalyType"])
        if cls is None:
            raise ValueError(f"{r['nodeId']}: 모르는 이상 유형 {r['anomalyType']!r}")
        ev = event_iri(r["nodeId"])
        g.add((ev, RDF.type, cls))
        for col, prop, dt in EVENT_COLS:
            v = r.get(col, "")
            if v != "":
                g.add((ev, IM[prop], Literal(v, datatype=dt) if dt else Literal(v)))
        prov = node_prov_iri(r["nodeId"])
        _prov(g, prov, nodes_rel, [r["nodeId"]])
        g.add((ev, IM.hasProvenance, prov))

    notes = []
    for i, e in enumerate(edges, 1):
        fr, to = by_id.get(e["fromId"]), by_id.get(e["toId"])
        if fr is None or to is None:
            continue
        if e["type"] == "triggers" and fr["label"] == "Sensor" and to["label"] == "AnomalyEvent":
            ev = event_iri(to["nodeId"])
            g.add((entity_iri(fr["name"]), IM.triggers, ev))
            prov = edge_prov_iri("triggers", fr["nodeId"], to["nodeId"])
            _prov(g, prov, edges_rel, [edge_row_id(i)])
            g.add((ev, IM.hasProvenance, prov))
        elif e["type"] == "correlates_with" and fr["label"] == "Sensor" and to["label"] == "Sensor":
            g.add((entity_iri(fr["name"]), IM.correlatesWith, entity_iri(to["name"])))
            notes.append({"relation": "correlatesWith", "from": fr["name"], "to": to["name"],
                          "ruleRef": e.get("ruleRef", ""), "fileName": edges_rel, "sourceRowId": edge_row_id(i)})
    return g, notes
