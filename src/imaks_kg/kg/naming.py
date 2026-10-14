"""이름공간과 인스턴스 IRI 규칙. seed_to_rdf(③)와 seed_events_post7(⑦ 이후)가 같이 쓴다.

- 어휘: ontology.ttl의 im: (https://example.org/imaks/v1#)
- 인스턴스: ontology_v1/examples와 같은 inst: (https://example.org/imaks/id/)
  - Station·Sensor: 원본 name 그대로 (예: inst:ST02_SEALING, inst:ST02_SEALING_CUR)
  - seed 노드 출처: inst:prov_seed_node_<nodeId>
  - seed 엣지 출처: inst:prov_seed_<관계이름>_<fromNodeId>_<toNodeId>
  - AnomalyEvent(⑦ 이후): inst:event_<nodeId> (평가용 번호를 IRI에 쓰지 않는다)
"""
import re

from rdflib import Namespace

IM = Namespace("https://example.org/imaks/v1#")
INST = Namespace("https://example.org/imaks/id/")

SOURCE_KIND_SEED = "seedCsv"
_SAFE = re.compile(r"^[A-Za-z0-9_]+$")


def _local(name: str) -> str:
    if not _SAFE.match(name):
        raise ValueError(f"IRI에 쓸 수 없는 이름: {name!r}")
    return name


def entity_iri(name: str):
    """Station·Sensor IRI (원본 name)."""
    return INST[_local(name)]


def node_prov_iri(node_id: str):
    return INST[f"prov_seed_node_{_local(node_id)}"]


def edge_prov_iri(relation: str, from_id: str, to_id: str):
    return INST[f"prov_seed_{_local(relation)}_{_local(from_id)}_{_local(to_id)}"]


def event_iri(node_id: str):
    return INST[f"event_{_local(node_id)}"]


def edge_row_id(data_row: int) -> str:
    """edges.csv 행 식별자. 헤더를 뺀 1부터의 데이터 행 번호(파일 줄 번호 = n + 1)."""
    return f"row:{data_row}"


# ---------------------------------------------------------------- B(Rule·Document 승격)용
# - Document: inst:doc_<문서 ID에서 '-'를 '_'로>            (예: inst:doc_SOP_002)
# - MaintenanceRule: inst:rule_<ruleId에서 '-'를 '_'로>        (예: inst:rule_MAINT_01)
# - ThresholdRule: inst:rule_thr_<센서 identifier>              (예: inst:rule_thr_ST02_SEALING_TMP)
# - 문서 표 셀 출처: inst:prov_doc_<tableId의 ':'·'-'를 '_'로>_r<행>_c<열> (행·열은 1부터)
SOURCE_KIND_DOCUMENT = "document"


def _token(text: str) -> str:
    return _local(re.sub(r"[-:]", "_", text))


def document_iri(doc_id: str):
    return INST[f"doc_{_token(doc_id)}"]


def maintenance_rule_iri(rule_id: str):
    return INST[f"rule_{_token(rule_id)}"]


def threshold_rule_iri(sensor_name: str):
    return INST[f"rule_thr_{_local(sensor_name)}"]


def table_cell_prov_iri(table_id: str, row_index: int, col_index: int):
    return INST[f"prov_doc_{_token(table_id)}_r{int(row_index)}_c{int(col_index)}"]
