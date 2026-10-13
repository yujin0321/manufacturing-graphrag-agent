"""Execute real SHACL validation, counterexamples, and competency queries."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from datetime import date
from pathlib import Path

from pyshacl import validate
from rdflib import Graph, Literal, RDF, SH, XSD
from rdflib.compare import to_canonical_graph

from build_ontology_v1 import IM, INST, ROOT, OUT, new_graph, resource, sha256, write_json

BASE = ROOT / "ontology_v1"
CHECKS = BASE / "validation"
EXAMPLES = BASE / "examples"
QUERIES = BASE / "queries"
PREFIX = "PREFIX im: <https://example.org/imaks/v1#>\nPREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
COMPETENCY_QUERIES = {
    "CQ1": PREFIX + '''SELECT ?stationId ?zoneName ?sensorId ?sensorType ?unit WHERE {
        ?station a im:Station; im:identifier "ST02_SEALING"; im:identifier ?stationId;
                 im:locatedIn ?zone; im:hasSensor ?sensor.
        ?zone im:name ?zoneName.
        ?sensor im:identifier ?sensorId; im:sensorType ?sensorType; im:unit ?unit.
    } ORDER BY ?sensorId''',
    "CQ2": PREFIX + '''SELECT ?fromId ?checkSensorId ?ruleId ?docId ?page ?quote WHERE {
        ?sensor im:identifier "ST02_SEALING_CUR"; im:identifier ?fromId; im:correlatesWith ?other.
        ?other im:identifier ?checkSensorId.
        ?statement rdf:subject ?sensor; rdf:predicate im:correlatesWith;
                   rdf:object ?other; im:ruleReference ?ruleId.
        ?rule a im:Rule; im:identifier ?ruleId; im:monitorsSensor ?other;
              im:sourceDocument ?doc; im:sourcePage ?page; im:sourceQuote ?quote.
        ?doc im:identifier ?docId.
    }''',
    "CQ3": PREFIX + '''SELECT ?measured ?limit ?targetId ?ruleId ?response ?docId ?page WHERE {
        VALUES ?measured { 2.12e2 }
        ?sensor im:identifier "ST02_SEALING_TMP".
        ?thresholdRule a im:ThresholdRule; im:appliesToSensor ?sensor; im:critHi ?limit.
        FILTER (?measured > ?limit)
        ?rule a im:Rule; im:identifier "RULE-ST02-02"; im:identifier ?ruleId;
              im:appliesToSensor ?sensor; im:actionTarget ?target; im:responseText ?response;
              im:sourceDocument ?doc; im:sourcePage ?page.
        ?target im:identifier ?targetId.
        ?doc im:identifier ?docId.
    } ORDER BY ?targetId''',
    "CQ4": PREFIX + '''SELECT ?sensorId ?unit ?nominal ?warnHi ?critHi ?sopId ?page ?datasheetId ?datasheetNote WHERE {
        ?sensor im:identifier "ST02_SEALING_CUR"; im:identifier ?sensorId.
        ?rule a im:ThresholdRule; im:appliesToSensor ?sensor; im:unit ?unit;
              im:nominal ?nominal; im:warnHi ?warnHi; im:critHi ?critHi;
              im:sourceDocument ?sop; im:sourcePage ?page.
        ?sop im:identifier ?sopId.
        ?datasheet a im:Document; im:identifier "DS_ELECTRICAL_SENSORS";
                   im:identifier ?datasheetId; im:documentText ?fullText.
        BIND(STRAFTER(?fullText, "Note 2 — Continuous Overload Rating:") AS ?datasheetNote)
    }''',
    "CQ5": PREFIX + '''SELECT ?personId ?role ?zoneName ?conditionDocId ?condition ?matrixDocId ?matrixExcerpt WHERE {
        ?person a im:Person; im:identifier "P043"; im:identifier ?personId;
                im:role ?role; im:authorizedFor ?zone.
        ?zone a im:Zone; im:name "Chemical Storage"; im:name ?zoneName.
        ?doc a im:Document; im:identifier "SOP-001"; im:identifier ?conditionDocId; im:documentText ?fullText.
        BIND(STRBEFORE(STRAFTER(?fullText, "RULE-CHM01-03:"), "2.8 RND01_RDLAB") AS ?condition)
        ?matrixDoc a im:Document; im:identifier "SOP-004"; im:identifier ?matrixDocId; im:documentText ?matrixText.
        BIND(STRBEFORE(STRAFTER(?matrixText, "1. Role-Zone Authorisation Matrix"), "2. Maximum Occupancy per Zone") AS ?matrixExcerpt)
    }''',
}


def report_json(report):
    results = []
    for result in report.subjects(RDF.type, SH.ValidationResult):
        item = {}
        for name, pred in [("focus_node", SH.focusNode), ("path", SH.resultPath),
                           ("component", SH.sourceConstraintComponent), ("message", SH.resultMessage)]:
            values = sorted(str(v) for v in report.objects(result, pred))
            if values:
                item[name] = values[0] if len(values) == 1 else values
        shape = report.value(result, SH.sourceShape)
        if shape is not None:
            item["source_shape"] = str(shape) if str(shape).startswith("http") else "anonymous property shape"
        results.append(item)
    return sorted(results, key=lambda item: json.dumps(item, sort_keys=True))


def check(graph, shapes, *, meta=False):
    # No remote imports, JS, OWL inference, or SHACL rules are executed.
    conforms, report, report_text = validate(graph, shacl_graph=shapes,
                                            inference="none", meta_shacl=meta,
                                            advanced=False, js=False, do_owl_imports=False)
    return bool(conforms), report, report_json(report), report_text


def save_report(path, report):
    # Stable blank-node labels make report files reproducible.
    canonical = to_canonical_graph(report).serialize(format="nt")
    path.write_text("\n".join(sorted(canonical.splitlines())) + "\n", encoding="utf-8")


def verify_recorded_hashes():
    """Verify stored results without invalid self-hashes or reading gold labels."""
    build_manifest = json.loads((OUT / "build_manifest.json").read_text(encoding="utf-8"))
    validation_manifest_path = CHECKS / "validation_manifest.json"
    validation_manifest = json.loads(validation_manifest_path.read_text(encoding="utf-8"))
    if validation_manifest["generated_manifest_sha256"] != sha256(OUT / "build_manifest.json"):
        raise ValueError("Generated manifest differs from the validated version")
    for name, expected in build_manifest["output_files_sha256"].items():
        if sha256(OUT / name) != expected:
            raise ValueError(f"Build output hash mismatch: {name}")
    if str(validation_manifest_path.relative_to(ROOT)).replace("\\", "/") in validation_manifest["files_sha256"]:
        raise ValueError("A manifest cannot record its own final hash")
    for name, expected in validation_manifest["files_sha256"].items():
        if sha256(ROOT / name) != expected:
            raise ValueError(f"Validation file hash mismatch: {name}")
    if sha256(ROOT / "build_ontology_v1.py") != build_manifest["builder_sha256"]:
        raise ValueError("Builder source differs from recorded source")
    for name, expected in build_manifest["common_files_sha256"].items():
        if sha256(ROOT / "preprocessed" / "common_v1" / name) != expected:
            raise ValueError(f"Consumed common file changed: {name}")
    return len(build_manifest["output_files_sha256"]) + len(validation_manifest["files_sha256"])


def copy_subject(source, target, subject, exclude=()):
    for s, p, o in source.triples((subject, None, None)):
        if p not in exclude:
            target.add((s, p, o))


def base_example(source):
    graph = new_graph()
    for node in [INST.N0001, INST.N0002, INST.N0013, INST.N0014, IM.InputData]:
        copy_subject(source, graph, node, exclude=[IM.contains, IM.hasSensor, IM.feedsInto])
    graph.add((INST.N0013, IM.hasSensor, INST.N0014))
    return graph


def fixtures(source):
    examples = {}
    base = base_example(source)
    examples["C1"] = (base, "센서 ID·유형·단위와 소속 스테이션이 있다.", "ST02 TMP 센서의 unit을 제거한다.")

    graph = base_example(source)
    obs = resource("example", "observation")
    graph.add((obs, RDF.type, IM.Observation))
    graph.add((obs, IM.observedBy, INST.N0014))
    graph.add((obs, IM.timestamp, Literal("2026-01-06T06:00:00", datatype=XSD.dateTime)))
    # Deliberately extreme value: observations must not be rejected as anomalies.
    graph.add((obs, IM.value, Literal(1000000.0, datatype=XSD.double)))
    graph.add((obs, IM.unit, Literal("°C")))
    examples["C2"] = (graph, "큰 이상값도 올바른 시각·수치형·센서·단위이면 통과한다.", "TMP 관측 단위를 °C에서 A로 바꾼다.")

    graph = base_example(source)
    manual = resource("rule", "RULE-ST02-02")
    copy_subject(source, graph, manual, exclude=[IM.actionTarget])
    copy_subject(source, graph, resource("document", "SOP-001"), exclude=[IM.documentText])
    examples["C3"] = (graph, "실재 문서와 p.1, 원문 인용·조건·대응·추출 방식이 있다.", "2쪽 문서의 sourcePage를 99로 바꾼다.")

    graph = base_example(source)
    rule = resource("rule", "SOP002-THRESHOLD-ST02_SEALING_TMP")
    copy_subject(source, graph, rule)
    copy_subject(source, graph, resource("document", "SOP-002"), exclude=[IM.documentText])
    examples["C4"] = (graph, "165 < 175 < 185 < 195 < 210 °C 순서의 임계값이 있다.", "critLo를 200으로 바꿔 하한 순서를 깨뜨린다.")

    graph = base_example(source)
    graph.set((IM.InputData, IM.inputProfile, Literal("ml_metadata")))
    examples["C5"] = (graph, "ML 메타데이터 그래프에 정답·문서·임계값이 없다.", "gt_id=GT-0007을 입력 그래프에 추가한다.")
    changes = {
        "C1": lambda g: g.remove((INST.N0014, IM.unit, None)),
        "C2": lambda g: g.set((obs, IM.unit, Literal("A"))),
        "C3": lambda g: g.set((manual, IM.sourcePage, Literal(99, datatype=XSD.positiveInteger))),
        "C4": lambda g: g.set((rule, IM.critLo, Literal(200.0, datatype=XSD.double))),
        "C5": lambda g: g.add((IM.InputData, IM.gt_id, Literal("GT-0007"))),
    }
    for key, (passing, pass_description, fail_description) in examples.items():
        failing = new_graph()
        for triple in passing:
            failing.add(triple)
        changes[key](failing)
        yield key, passing, failing, pass_description, fail_description


def run_queries(graph):
    answers = []
    expected = {"CQ1": 3, "CQ2": 1, "CQ3": 3, "CQ4": 1, "CQ5": 1}
    scope = {
        "CQ1": "정적 소속·단위 조회; 실제 고장 원인 판정 아님",
        "CQ2": "문서가 지시한 추가 확인 센서; 실제 사건의 인과 확정 아님",
        "CQ3": "212°C를 가정한 규칙 조회 예제; 실제 경보 입력·설비 제어 실행 아님",
        "CQ4": "SOP와 일반 데이터시트 비교; 해당 모델의 실제 설치나 적용성을 단정하지 않음",
        "CQ5": "권한 기록 조회; 교육 이수 및 문서 조건 충돌 때문에 현재 입장 허용 여부는 미확정",
    }
    for key, query in COMPETENCY_QUERIES.items():
        (QUERIES / f"{key}.rq").write_text(query + "\n", encoding="utf-8")
        result = graph.query(query)
        rows = [{str(var): str(row[var]) for var in result.vars if row[var] is not None} for row in result]
        if len(rows) != expected[key]:
            raise AssertionError(f"{key}: expected {expected[key]} rows, got {len(rows)}")
        if key == "CQ1" and {(r["sensorId"], r["unit"]) for r in rows} != {
            ("ST02_SEALING_CUR", "A"), ("ST02_SEALING_PRS", "bar"), ("ST02_SEALING_TMP", "°C")}:
            raise AssertionError("CQ1: sensor/unit identities differ")
        if key == "CQ2" and (rows[0]["checkSensorId"], rows[0]["ruleId"], rows[0]["docId"], rows[0]["page"]) != (
            "ST04_PACKAGING_SPD", "RULE-ST02-04", "SOP-001", "1"):
            raise AssertionError("CQ2: sensor/rule provenance differs")
        if key == "CQ3" and ({r["targetId"] for r in rows} != {"ST02_SEALING", "ST03_LABELLING", "ST04_PACKAGING"}
                             or any(float(r["limit"]) != 210.0 for r in rows)):
            raise AssertionError("CQ3: critical threshold or action targets differ")
        if key == "CQ4" and (float(rows[0]["warnHi"]) != 13.5 or float(rows[0]["critHi"]) != 15.0
                             or "14 A" not in rows[0]["datasheetNote"] or "60 seconds" not in rows[0]["datasheetNote"]):
            raise AssertionError("CQ4: document comparison evidence differs")
        if key == "CQ5" and (rows[0]["role"] != "security" or rows[0]["conditionDocId"] != "SOP-001"
                             or rows[0]["matrixDocId"] != "SOP-004" or "hazmat training" not in rows[0]["condition"]
                             or "security" not in rows[0]["matrixExcerpt"]):
            raise AssertionError("CQ5: permission/qualification source evidence differs")
        answers.append({"question_id": key, "rows": rows, "scope": scope[key]})
    write_json(CHECKS / "competency_answers.json", answers)
    return answers


def verify(*, record_date=None):
    if record_date is not None:
        date.fromisoformat(record_date)
    for folder in [CHECKS, EXAMPLES, QUERIES]:
        folder.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((OUT / "build_manifest.json").read_text(encoding="utf-8"))
    for relative, expected in manifest["output_files_sha256"].items():
        if sha256(OUT / relative) != expected:
            raise ValueError(f"Generated input hash mismatch: {relative}")
    shapes = Graph().parse(BASE / "shapes.ttl", format="turtle")
    Graph().parse(BASE / "ontology.ttl", format="turtle")  # syntax check; no entailment
    outcomes = []
    graphs = {}
    for filename in ["ml_metadata.ttl", "rule_context.ttl"]:
        graph = Graph().parse(OUT / filename, format="turtle")
        graphs[filename] = graph
        conforms, report, details, _ = check(graph, shapes, meta=filename == "ml_metadata.ttl")
        save_report(CHECKS / (filename.replace(".ttl", "_report.ttl")), report)
        outcomes.append({"input": filename, "conforms": conforms, "violations": details})
        if not conforms:
            write_json(CHECKS / "validation_results.json", outcomes)
            raise AssertionError(f"Actual graph failed SHACL: {filename}: {details}")
    for key, passing, failing, pass_text, fail_text in fixtures(graphs["rule_context.ttl"]):
        for suffix, graph, expected, description in [("pass", passing, True, pass_text), ("fail", failing, False, fail_text)]:
            name = f"{key}_{suffix}"
            graph.serialize(destination=EXAMPLES / f"{name}.ttl", format="turtle")
            conforms, report, details, _ = check(graph, shapes)
            save_report(CHECKS / f"{name}_report.ttl", report)
            outcomes.append({"input": f"examples/{name}.ttl", "expected_conforms": expected,
                             "conforms": conforms, "description": description, "violations": details})
            if conforms != expected:
                raise AssertionError(f"Counterexample did not behave as expected: {name}: {details}")
    # Extra profile guard: a valid rule graph must fail if assigned to ML.
    wrong_profile = Graph().parse(OUT / "rule_context.ttl", format="turtle")
    wrong_profile.set((IM.InputData, IM.inputProfile, Literal("ml_metadata")))
    conforms, _, details, _ = check(wrong_profile, shapes)
    if conforms:
        raise AssertionError("Rule/document graph was accepted as ML input")
    outcomes.append({"input": "rule_context with ml_metadata profile", "expected_conforms": False,
                     "conforms": conforms, "violations": details})
    answers = run_queries(graphs["rule_context.ttl"])
    versions = {package: importlib.metadata.version(package) for package in
                ["rdflib", "pyshacl", "owlrl", "html5rdf", "prettytable", "pyparsing", "packaging", "wcwidth"]}
    summary = {"record_date": record_date, "date_source": "caller supplied; host clock not inferred", "engine_versions": versions,
               "meta_shacl_passed": True, "inference": "none", "remote_imports": False,
               "actual_graphs_passed": 2, "passing_examples": 5, "failing_examples_rejected": 5,
               "ml_document_rule_guard_rejected": True, "competency_queries_passed": len(answers),
               "results": outcomes}
    write_json(CHECKS / "validation_results.json", summary)
    tracked = [BASE / "ontology.ttl", BASE / "shapes.ttl", ROOT / "build_ontology_v1.py", ROOT / "verify_ontology_v1.py", ROOT / "test_ontology_v1.py", ROOT / "requirements-ontology.txt", ROOT / "README_ONTOLOGY_V1.md"]
    tracked += sorted(BASE.glob("*.md"))
    tracked += sorted(EXAMPLES.glob("*.ttl")) + sorted(QUERIES.glob("*.rq"))
    tracked += [p for p in sorted(CHECKS.glob("*.json")) if p.name != "validation_manifest.json"]
    tracked += sorted(CHECKS.glob("*.ttl"))
    write_json(CHECKS / "validation_manifest.json", {"files_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p) for p in tracked},
               "generated_manifest_sha256": sha256(OUT / "build_manifest.json")})
    verify_recorded_hashes()
    print(json.dumps({k: summary[k] for k in ["actual_graphs_passed", "passing_examples", "failing_examples_rejected", "competency_queries_passed"]}))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-date", help="Client/project date as YYYY-MM-DD; omitted means undated")
    verify(record_date=parser.parse_args().record_date)
