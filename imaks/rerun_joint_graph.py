"""Rebuild isolated RDF and export a source-grounded Neo4j import bundle.

This module never starts a server or changes the original ontology_v1 outputs.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import date
from pathlib import Path

from rdflib import Graph, Literal, RDF, URIRef, XSD
from rdflib.compare import isomorphic

from build_ontology_v1 import COMMON, IM, INST, ROOT, build, sha256, write_json
from verify_ontology_v1 import COMPETENCY_QUERIES, check, fixtures, save_report

DEFAULT_OUTPUT = ROOT / "experiments" / "joint_preprocessing_rerun_v1" / "graph"
ENTITY_CLASSES = {
    "System", "Zone", "Station", "Sensor", "Person", "Document", "Rule", "ThresholdRule"
}
FORBIDDEN_CLASSES = {"AnomalyEvent", "SafetyEvent", "MaintenanceEvent", "QualityDefect", "InternalComponent"}
FORBIDDEN_FIELDS = {
    "quality", "anomaly_label", "severity", "dataset_severity", "alarm_flag", "gt_id",
    "day", "shift", "batch_id", "status", "alarms"
}


def original_hashes():
    paths = list((ROOT / "ontology_v1").rglob("*"))
    paths += [ROOT / name for name in (
        "build_ontology_v1.py", "verify_ontology_v1.py", "test_ontology_v1.py",
        "README_ONTOLOGY_V1.md", "requirements-ontology.txt"
    )]
    return {str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p)
            for p in sorted(paths) if p.is_file()}


def local_name(term):
    value = str(term)
    if not value.startswith(str(IM)):
        raise ValueError(f"Unexpected vocabulary: {value}")
    return value[len(str(IM)):]


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def validate_rdf(output):
    """Real SHACL checks and CQ comparisons without the old verifier's writes."""
    validation = output / "validation"
    validation.mkdir(parents=True, exist_ok=True)
    shapes = Graph().parse(ROOT / "ontology_v1" / "shapes.ttl", format="turtle")
    graphs = {}
    outcomes = []
    for filename in ("ml_metadata.ttl", "rule_context.ttl"):
        graph = Graph().parse(output / "rdf" / filename, format="turtle")
        old = Graph().parse(ROOT / "ontology_v1" / "generated" / filename, format="turtle")
        if not isomorphic(graph, old):
            raise AssertionError(f"Rebuilt RDF differs semantically: {filename}")
        graphs[filename] = graph
        conforms, report, violations, _ = check(graph, shapes, meta=filename == "ml_metadata.ttl")
        save_report(validation / filename.replace(".ttl", "_report.ttl"), report)
        outcomes.append({"input": filename, "conforms": conforms, "violations": violations})
        if not conforms:
            raise AssertionError(f"Rebuilt graph failed SHACL: {filename}")
    for key, passing, failing, pass_text, fail_text in fixtures(graphs["rule_context.ttl"]):
        for name, graph, expected, description in (
            (f"{key}_pass", passing, True, pass_text),
            (f"{key}_fail", failing, False, fail_text)
        ):
            conforms, report, violations, _ = check(graph, shapes)
            save_report(validation / f"{name}_report.ttl", report)
            outcomes.append({"input": name, "conforms": conforms, "expected_conforms": expected,
                             "description": description, "violations": violations})
            if conforms != expected:
                raise AssertionError(f"Counterexample did not behave as expected: {name}")
    wrong_profile = Graph()
    for triple in graphs["rule_context.ttl"]:
        wrong_profile.add(triple)
    wrong_profile.set((IM.InputData, IM.inputProfile, Literal("ml_metadata")))
    if check(wrong_profile, shapes)[0]:
        raise AssertionError("Rule/document data accepted as ML input")
    old_answers = json.loads((ROOT / "ontology_v1" / "validation" / "competency_answers.json")
                             .read_text(encoding="utf-8"))
    expected = {entry["question_id"]: entry["rows"] for entry in old_answers}
    answers = []
    for key, query in COMPETENCY_QUERIES.items():
        result = graphs["rule_context.ttl"].query(query)
        rows = [{str(var): str(row[var]) for var in result.vars if row[var] is not None}
                for row in result]
        canonical = lambda values: sorted(json.dumps(row, sort_keys=True, ensure_ascii=False) for row in values)
        if canonical(rows) != canonical(expected[key]):
            raise AssertionError(f"Competency query changed: {key}")
        answers.append({"question_id": key, "rows": rows, "same_as_original": True})
    write_json(validation / "competency_answers.json", answers)
    summary = {"actual_graphs_passed": 2, "passing_examples": 5,
               "failing_examples_rejected": 5, "ml_document_rule_guard_rejected": True,
               "competency_queries_passed": len(answers), "rdf_semantically_equals_original": True,
               "results": outcomes}
    write_json(validation / "validation_results.json", summary)
    return graphs["rule_context.ttl"], summary


def export_neo4j(graph, output):
    """Flatten domain entities; retain canonical source-edge IDs and provenance."""
    output.mkdir(parents=True, exist_ok=True)
    entities = {}
    property_types = {}
    for subject, _, kind in graph.triples((None, RDF.type, None)):
        if isinstance(kind, URIRef) and str(kind).startswith(str(IM)):
            label = local_name(kind)
            if label in FORBIDDEN_CLASSES:
                raise AssertionError(f"Forbidden event/inferred component class: {label}")
            if label in ENTITY_CLASSES:
                entities.setdefault(subject, set()).add(label)
    if len(entities) != 114:
        raise AssertionError(f"Expected 83 static + 7 Document + 24 Rule entities; got {len(entities)}")
    node_rows = []
    literal_properties = {}
    for subject, labels in sorted(entities.items(), key=lambda item: str(item[0])):
        row = {"iri": str(subject), "labels": ";".join(sorted(labels))}
        literals = {}
        for predicate, value in graph.predicate_objects(subject):
            if isinstance(value, Literal):
                key = local_name(predicate)
                if key in FORBIDDEN_FIELDS:
                    raise AssertionError(f"Forbidden label field: {key}")
                if key in row:
                    raise AssertionError(f"Duplicate scalar node field: {key}")
                row[key] = str(value)
                literals[key] = value
                field_type = "float" if value.datatype in {XSD.double, XSD.float, XSD.decimal} else (
                    "integer" if value.datatype in {XSD.integer, XSD.positiveInteger, XSD.nonNegativeInteger} else "string")
                if key in property_types and property_types[key] != field_type:
                    raise AssertionError(f"Mixed property type: {key}")
                property_types[key] = field_type
        if "identifier" not in row or row["identifier"].startswith("GT-"):
            raise AssertionError("Missing or evaluation entity identifier")
        literal_properties[subject] = literals
        node_rows.append(row)
    rel_rows = []
    source_triples = set()
    for statement in sorted(graph.subjects(RDF.type, RDF.Statement), key=str):
        s, p, o = (graph.value(statement, field) for field in (RDF.subject, RDF.predicate, RDF.object))
        if s not in entities or o not in entities or (s, p, o) not in graph:
            raise AssertionError("Invalid canonical relationship endpoints")
        source_triples.add((s, p, o))
        edge_id = str(graph.value(statement, IM.identifier))
        rel_rows.append({"edge_id": edge_id, "start_iri": str(s), "type": local_name(p),
                         "end_iri": str(o), "source_kind": "original_static_edge",
                         "source_path": str(graph.value(statement, IM.sourcePath)),
                         "rule_reference": str(graph.value(statement, IM.ruleReference) or "")})
    if len(rel_rows) != 269 or len(source_triples) != 269:
        raise AssertionError("Original static edges were lost or duplicated")
    derived = sorted(((s, p, o) for s, p, o in graph if s in entities and o in entities
                      and p != RDF.type and (s, p, o) not in source_triples), key=lambda t: tuple(map(str, t)))
    for index, (s, p, o) in enumerate(derived, 1):
        pred = local_name(p)
        rel_rows.append({"edge_id": f"D{index:04d}", "start_iri": str(s), "type": pred,
                         "end_iri": str(o), "source_kind": "station_zone_field" if pred == "locatedIn" else "document_rule",
                         "source_path": "inputs/kg/nodes_static.csv" if pred == "locatedIn" else "rdf/rule_lineage.json",
                         "rule_reference": str(graph.value(s, IM.identifier)) if "Rule" in entities[s] else ""})
    fields = ["iri", "labels"] + sorted(property_types)
    rel_fields = ["edge_id", "start_iri", "type", "end_iri", "source_kind", "source_path", "rule_reference"]
    write_csv(output / "nodes.csv", node_rows, fields)
    write_csv(output / "relationships.csv", rel_rows, rel_fields)
    # Exact CSV round-trip includes Unicode, multiline document text and all numeric strings.
    read_nodes = read_csv(output / "nodes.csv")
    expected_nodes = [{key: row.get(key, "") for key in fields} for row in node_rows]
    if read_nodes != expected_nodes or read_csv(output / "relationships.csv") != rel_rows:
        raise AssertionError("Neo4j CSV round-trip changed data")
    node_ids = {row["iri"] for row in read_nodes}
    edge_ids = {row["edge_id"] for row in rel_rows}
    if len(node_ids) != len(read_nodes) or len(edge_ids) != len(rel_rows):
        raise AssertionError("Duplicate Neo4j node or edge identifiers")
    if any(row["start_iri"] not in node_ids or row["end_iri"] not in node_ids for row in rel_rows):
        raise AssertionError("Neo4j orphan relationship")
    exported_triples = {(URIRef(row["start_iri"]), IM[row["type"]], URIRef(row["end_iri"])) for row in rel_rows}
    expected_triples = {(s, p, o) for s, p, o in graph if s in entities and o in entities and p != RDF.type}
    if exported_triples != expected_triples:
        raise AssertionError("Neo4j relationships differ from RDF domain relationships")
    # No APOC, dynamic relationship syntax or server-side script execution is required.
    # Run only in a dedicated review database: the script exports but never executes Cypher.
    cypher = [
        "// Copy nodes.csv and relationships.csv into the chosen Neo4j import directory.",
        "// Execute in a dedicated database. This file has not been executed by the exporter.",
        "CREATE CONSTRAINT imaks_entity_iri IF NOT EXISTS FOR (n:ImaksEntity) REQUIRE n.iri IS UNIQUE;",
        "LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row",
        "MERGE (n:ImaksEntity {iri: row.iri})",
        "SET n.ontology_labels = split(row.labels, ';')"
    ]
    for key, field_type in sorted(property_types.items()):
        if not key.replace("_", "").isalnum():
            raise AssertionError("Unsafe Cypher property name")
        conversion = f"toFloat(row.{key})" if field_type == "float" else (
            f"toInteger(row.{key})" if field_type == "integer" else f"row.{key}")
        cypher.append(f"SET n.{key} = CASE WHEN row.{key} = '' THEN null ELSE {conversion} END")
    labels = sorted({label for values in entities.values() for label in values})
    for label in labels:
        cypher.append(f"FOREACH (ignored IN CASE WHEN '{label}' IN split(row.labels, ';') THEN [1] ELSE [] END | SET n:{label})")
    cypher[-1] += ";"
    for kind in sorted({row["type"] for row in rel_rows}):
        if not kind.isalnum():
            raise AssertionError("Unsafe relationship type")
        cypher += [
            "LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row",
            f"WITH row WHERE row.type = '{kind}'",
            "MATCH (source:ImaksEntity {iri: row.start_iri}), (target:ImaksEntity {iri: row.end_iri})",
            f"MERGE (source)-[r:{kind} {{edge_id: row.edge_id}}]->(target)",
            "SET r.source_kind = row.source_kind, r.source_path = row.source_path, r.rule_reference = row.rule_reference;"
        ]
    (output / "load_csv.cypher").write_text("\n".join(cypher) + "\n", encoding="utf-8")
    counts = Counter(label for values in entities.values() for label in values)
    relationships = Counter(row["type"] for row in rel_rows)
    summary = {"nodes": len(node_rows), "relationships": len(rel_rows), "node_labels": dict(sorted(counts.items())),
               "relationship_types": dict(sorted(relationships.items())), "original_static_edges": 269,
               "derived_edges": len(derived), "csv_roundtrip_passed": True,
               "rdf_domain_relationships_preserved": True, "orphan_relationships": 0,
               "duplicate_node_ids": 0, "duplicate_edge_ids": 0,
               "server_import_executed": False, "server_installation_performed": False,
               "excluded_rdf_subjects": ["22 schema-example Observations", "269 RDF.Statement provenance records", "InputGraph control node"],
               "profile": "rule_context; thresholds/documents must not be used as ML detector features",
               "property_types": property_types}
    write_json(output / "export_summary.json", summary)
    (output / "README_ko.md").write_text(
        "# Neo4j 변환 결과\n\n"
        "노드 114개(기존 정적 83개 + Document 7개 + Rule 24개)와 관계 "
        f"{len(rel_rows)}개를 CSV로 내보냈습니다. 원래 정적 관계 269개와 zone 필드 기반 locatedIn 9개, 문서·규칙 연결을 보존했습니다.\n\n"
        "nodes.csv는 원문 텍스트·출처·단위·수치 속성을 포함하고 relationships.csv는 원래 edge_id와 rule_reference를 보존합니다. "
        "Rule 24개 중 22개는 임계값 표 변환, 2개는 원문 수동 예제입니다. LLM 추출 결과는 아닙니다.\n\n"
        "LOAD CSV용 load_csv.cypher도 생성했으나 서버 설치나 적재는 실행하지 않았습니다. "
        "선택한 Neo4j의 import 폴더로 두 CSV를 복사한 후 전용 데이터베이스에서 실행할 수 있습니다. APOC 플러그인은 필요하지 않습니다. "
        "데이터베이스에 기존 자료가 있는 경우 실행 전 별도 검토가 필요합니다.\n\n"
        "관측 22개는 RDF 스키마 예제이므로 이 CSV에 포함하지 않았으며 전체 시계열도 적재하지 않았습니다. "
        "RDF.Statement 출처 정보는 별도 노드 대신 관계 속성에 저장했습니다. "
        "임계값·문서·Rule이 있는 설명용 그래프이며 ML 탐지 입력으로 사용하면 안 됩니다. "
        "정답 이벤트와 사후 로그, 모터·베어링의 실제 설치 사실은 넣지 않았습니다.\n",
        encoding="utf-8")
    return summary


def run_graph(output=DEFAULT_OUTPUT, *, record_date="2026-10-06"):
    date.fromisoformat(record_date)
    output = Path(output).resolve()
    if output == (ROOT / "ontology_v1").resolve() or (ROOT / "ontology_v1").resolve() in output.parents:
        raise ValueError("Separate output directory required")
    before = original_hashes()
    output.mkdir(parents=True, exist_ok=True)
    source_summary = build(base=COMMON, output=output / "rdf", record_date=record_date)
    graph, validation = validate_rdf(output)
    neo4j = export_neo4j(graph, output / "neo4j")
    if original_hashes() != before:
        raise AssertionError("Original ontology files changed")
    schema = Graph().parse(ROOT / "ontology_v1" / "ontology.ttl", format="turtle")
    from rdflib import OWL
    named_counts = {name: sum(1 for subject in schema.subjects(RDF.type, kind)
                             if isinstance(subject, URIRef) and str(subject).startswith(str(IM)))
                    for name, kind in (("named_classes", OWL.Class), ("object_properties", OWL.ObjectProperty),
                                       ("datatype_properties", OWL.DatatypeProperty))}
    summary = {"record_date": record_date, "original_files_preserved": len(before),
               "ontology_schema": named_counts, "rdf_build": source_summary,
               "shacl": {key: value for key, value in validation.items() if key != "results"},
               "neo4j": neo4j, "evaluation_rules_86_used": False,
               "evaluation_events_14_used": False, "llm_extraction_run": False,
               "installed_motor_bearing_instances": 0, "quality_defect_instances": 0,
               "graph_rag_connected": False}
    write_json(output / "summary.json", summary)
    write_json(output / "preservation_check.json", {"preserved": True, "original_files_sha256": before})
    outputs = {str(path.relative_to(output)).replace("\\", "/"): sha256(path)
               for path in sorted(output.rglob("*")) if path.is_file() and path.name != "manifest.json"}
    write_json(output / "manifest.json", {"runner_sha256": sha256(__file__), "files_sha256": outputs})
    print(json.dumps({"graph_output": str(output), "rdf_static_nodes": 83,
                      "neo4j_nodes": neo4j["nodes"], "neo4j_relationships": neo4j["relationships"],
                      "shacl_passed": True, "original_files_preserved": len(before)}, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--record-date", default="2026-10-06")
    args = parser.parse_args()
    run_graph(args.output, record_date=args.record_date)
