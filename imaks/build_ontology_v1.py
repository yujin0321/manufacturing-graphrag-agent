"""Build a source-grounded RDF draft without reading evaluation references.

The 22 observations are schema examples. The complete sensor CSV remains the
detector input; this script does not alter the detection pipeline.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, RDF, XSD

from common_detection_data import OBSERVATIONS, read_verified

ROOT = Path(__file__).resolve().parent
COMMON = ROOT / "preprocessed" / "common_v1"
OUT = ROOT / "ontology_v1" / "generated"
IM = Namespace("https://example.org/imaks/v1#")
INST = Namespace("https://example.org/imaks/id/")
CLASS_MAP = {"System": IM.System, "Zone": IM.Zone, "Component": IM.Station,
             "Sensor": IM.Sensor, "Person": IM.Person}
EDGE_MAP = {"contains": IM.contains, "part_of": IM.partOf,
            "has_sensor": IM.hasSensor, "feeds_into": IM.feedsInto,
            "correlates_with": IM.correlatesWith, "authorized_for": IM.authorizedFor}
ATTR_MAP = {"name": IM.name, "stationType": IM.stationType,
            "sensorType": IM.sensorType, "unit": IM.unit, "line": IM.line,
            "personId": IM.personId, "role": IM.role, "dept": IM.department,
            "csiSubject": IM.csiSubject}
TABLE_STATIONS = {
    "SOP-002:p1:table1": "ST01_FILLING", "SOP-002:p1:table2": "ST02_SEALING",
    "SOP-002:p1:table3": "ST03_LABELLING", "SOP-002:p1:table4": "ST04_PACKAGING",
    "SOP-002:p1:table5": "SRV01_SERVERROOM", "SOP-002:p2:table1": "SRV01_SERVERROOM",
    "SOP-002:p2:table2": "WRH01_WAREHOUSE", "SOP-002:p2:table3": "CHM01_CHEMICALSTORAGE",
    "SOP-002:p2:table4": "RND01_RDLAB", "SOP-002:p2:table5": "CAF01_CAFETERIA",
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def new_graph():
    graph = Graph()
    graph.bind("im", IM)
    graph.bind("inst", INST)
    graph.bind("xsd", XSD)
    return graph


def resource(kind, identifier):
    return INST[f"{kind}/{quote(identifier, safe='')}"]


class VerifiedSources:
    """Only explicitly requested common files are consumed, never evaluation/."""
    def __init__(self, base):
        self.base = Path(base)
        self.manifest = json.loads((self.base / "manifest.json").read_text(encoding="utf-8"))
        self.consumed = {"manifest.json": sha256(self.base / "manifest.json")}

    def file(self, relative):
        relative = relative.replace("\\", "/")
        if relative.startswith("evaluation/") or "ground_truth" in relative or "nodes_factory" in relative:
            raise ValueError("Evaluation and discarded sources cannot enter the ontology builder")
        expected = self.manifest["output_files_sha256"].get(relative)
        if expected is None:
            expected = self.manifest["output_files_sha256"].get(relative.replace("/", "\\"))
        path = self.base / relative
        if expected is None or not path.is_file() or sha256(path) != expected:
            raise ValueError(f"Unverified common source: {relative}")
        self.consumed[relative] = expected
        return path

    def csv(self, relative):
        with self.file(relative).open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def json(self, relative):
        return json.loads(self.file(relative).read_text(encoding="utf-8"))


def build_static(sources):
    graph = new_graph()
    nodes = sources.csv("inputs/kg/nodes_static.csv")
    edges = sources.csv("inputs/kg/edges_static.csv")
    mapping = sources.csv("metadata/sensor_id_mapping.csv")
    by_id = {row["nodeId"]: row for row in nodes}
    if len(by_id) != len(nodes) or len(nodes) != 83 or len(edges) != 269:
        raise ValueError("Unexpected static KG version")
    zones = {n["name"]: INST[n["nodeId"]] for n in nodes if n["label"] == "Zone"}
    for node in nodes:
        subj = INST[node["nodeId"]]
        kind = node["label"]
        if kind not in CLASS_MAP:
            raise ValueError(f"Unsupported class: {kind}")
        graph.add((subj, RDF.type, CLASS_MAP[kind]))
        identifier = node["name"] if kind in {"Component", "Sensor"} else node["personId"] if kind == "Person" else node["nodeId"]
        if not identifier:
            raise ValueError("Missing identifier")
        graph.add((subj, IM.identifier, Literal(identifier)))
        graph.add((subj, IM.sourceLabel, Literal(kind)))
        for col, pred in ATTR_MAP.items():
            if node[col]:
                graph.add((subj, pred, Literal(node[col])))
        if kind == "Component":
            graph.add((subj, IM.locatedIn, zones[node["zone"]]))
    for edge in edges:
        if edge["fromId"] not in by_id or edge["toId"] not in by_id:
            raise ValueError("Orphan edge")
        subj, obj, pred = INST[edge["fromId"]], INST[edge["toId"]], EDGE_MAP[edge["type"]]
        graph.add((subj, pred, obj))
        # Preserve canonical common edge IDs; original rows are in audit/edge_lineage.csv.
        statement = resource("edge", edge["edge_id"])
        graph.add((statement, RDF.type, RDF.Statement))
        graph.add((statement, RDF.subject, subj))
        graph.add((statement, RDF.predicate, pred))
        graph.add((statement, RDF.object, obj))
        graph.add((statement, IM.identifier, Literal(edge["edge_id"])))
        graph.add((statement, IM.sourcePath, Literal("inputs/kg/edges_static.csv")))
        if edge["ruleRef"]:
            graph.add((statement, IM.ruleReference, Literal(edge["ruleRef"])))
    for row in mapping:
        sensor, station = INST[row["sensor_node_id"]], INST[row["station_node_id"]]
        if (station, IM.hasSensor, sensor) not in graph:
            raise ValueError("Sensor/station mapping disagrees with KG")
        if str(graph.value(sensor, IM.identifier)) != row["sensor_id"] or str(graph.value(sensor, IM.unit)) != row["unit"]:
            raise ValueError("Sensor identity/unit disagreement")
    graph.add((IM.InputData, RDF.type, IM.InputGraph))
    graph.add((IM.InputData, IM.inputProfile, Literal("ml_metadata")))
    return graph, mapping, nodes, edges


def add_documents(graph, sources):
    documents = sources.json("documents/document_manifest.json")
    pages = sources.json("documents/pages.json")
    by_id = {document["doc_id"]: document for document in documents}
    for document in documents:
        doc_id = document["doc_id"]
        doc = resource("document", doc_id)
        doc_pages = sorted([p for p in pages if p["doc_id"] == doc_id], key=lambda p: p["page"])
        if len(doc_pages) != document["pages"]:
            raise ValueError("Document page count differs")
        pdf = sources.file(document["pdf_path"])
        if sha256(pdf) != document["sha256"]:
            raise ValueError("PDF manifest hash differs")
        title_lines = []
        for line in doc_pages[0]["text"].splitlines():
            if line.startswith("Document:"):
                break
            title_lines.append(line.strip())
        graph.add((doc, RDF.type, IM.Document))
        for pred, val in [(IM.identifier, doc_id), (IM.title, " ".join(title_lines)),
                          (IM.sourcePath, document["source"]), (IM.sourceSha256, document["sha256"]),
                          (IM.documentText, "\n".join(f"[page {p['page']}]\n{p['text']}" for p in doc_pages))]:
            graph.add((doc, pred, Literal(val)))
        graph.add((doc, IM.pageCount, Literal(document["pages"], datatype=XSD.positiveInteger)))
    return documents, pages, by_id


def add_threshold_rules(graph, sources, mapping):
    tables = sources.json("documents/tables.json")
    sensors = {row["sensor_id"]: INST[row["sensor_node_id"]] for row in mapping}
    lineage = []
    seen = set()
    for table in tables:
        table_id = table["table_id"]
        if table_id not in TABLE_STATIONS:
            continue
        station = TABLE_STATIONS[table_id]
        if table_id == "SOP-002:p2:table1" and table["continues_table"] != "SOP-002:p1:table5":
            raise ValueError("Server-room table continuation lost")
        rows = table["cells"]
        for row_index, cells in enumerate(rows, start=1):
            if cells[0] == "Sensor":
                continue
            if len(cells) != 8:
                raise ValueError("Unexpected SOP-002 table structure")
            sensor_type, unit = cells[0].replace("\n", ""), cells[1].replace("\n", "")
            sensor_id = f"{station}_{sensor_type}"
            if sensor_id in seen or sensor_id not in sensors:
                raise ValueError("Duplicate/unmapped threshold row")
            seen.add(sensor_id)
            sensor = sensors[sensor_id]
            if str(graph.value(sensor, IM.unit)) != unit:
                raise ValueError("Document/sensor unit disagreement")
            nominal = re.fullmatch(r"\s*([-+]?\d+(?:\.\d+)?)\s*±\s*(\d+(?:\.\d+)?)\s*", cells[4])
            if not nominal:
                raise ValueError("Nominal tolerance was not parsed explicitly")
            values = [float(cells[2]), float(cells[3]), float(nominal[1]), float(cells[5]), float(cells[6])]
            if not all(math.isfinite(v) for v in values):
                raise ValueError("Nonfinite threshold")
            rule_id = f"SOP002-THRESHOLD-{sensor_id}"
            rule = resource("rule", rule_id)
            graph.add((rule, RDF.type, IM.Rule))
            graph.add((rule, RDF.type, IM.ThresholdRule))
            graph.add((rule, IM.appliesToSensor, sensor))
            graph.add((rule, IM.sourceDocument, resource("document", "SOP-002")))
            graph.add((rule, IM.sourcePage, Literal(table["page"], datatype=XSD.positiveInteger)))
            graph.add((rule, IM.sourceRow, Literal(row_index, datatype=XSD.positiveInteger)))
            for pred, text in [(IM.identifier, rule_id), (IM.unit, unit), (IM.nominalText, cells[4]),
                               (IM.sourceTable, table_id), (IM.sourceQuote, json.dumps(cells, ensure_ascii=False)),
                               (IM.conditionText, "CRIT_LO < WARN_LO < NOMINAL < WARN_HI < CRIT_HI; CRITICAL response applies outside critical bounds."),
                               (IM.responseText, " ".join(cells[7].split())),
                               (IM.extractionMethod, "deterministic SOP-002 corrected table mapping; not LLM extraction")]:
                graph.add((rule, pred, Literal(text)))
            for pred, value in zip([IM.critLo, IM.warnLo, IM.nominal, IM.warnHi, IM.critHi], values):
                graph.add((rule, pred, Literal(value, datatype=XSD.double)))
            graph.add((rule, IM.nominalTolerance, Literal(float(nominal[2]), datatype=XSD.double)))
            lineage.append({"rule_id": rule_id, "sensor_id": sensor_id, "doc_id": "SOP-002",
                            "source_page": table["page"], "source_table": table_id, "source_row": row_index,
                            "source_cells": cells, "thresholds": dict(zip(["critLo", "warnLo", "nominal", "warnHi", "critHi"], values)),
                            "nominal_tolerance": float(nominal[2]), "method": "deterministic table mapping"})
    if len(seen) != 22:
        raise ValueError("Expected one SOP-002 threshold row per sensor")
    return lineage


def add_sop_examples(graph, pages):
    page = next(p for p in pages if p["page_id"] == "SOP-001:p1")
    specifications = {
        "RULE-ST02-02": ("TMP > 210°C (CRITICAL)", "emergency stop ST02, ST03, ST04.", IM.actionTarget, [INST.N0013, INST.N0017, INST.N0021], INST.N0014),
        "RULE-ST02-04": ("CUR drift at ST02_SEALING; CUR triggers a WARNING", "Monitor ST04_PACKAGING-SPD whenever ST02_SEALING-CUR triggers a WARNING.", IM.monitorsSensor, [INST.N0024], INST.N0016),
    }
    lineage = []
    for rule_id, (condition, response, target_pred, targets, sensor) in specifications.items():
        # Copy the entire original rule block and keep exact text offsets.
        start = page["text"].index(rule_id + ":")
        after_start = page["text"][start:]
        next_header = re.search(r"\n(?:RULE-[A-Z0-9-]+:|2\.\d+\s)", after_start)
        end = start + next_header.start() if next_header else len(page["text"])
        source_quote = page["text"][start:end].rstrip()
        if rule_id == "RULE-ST02-02" and "210°C" not in source_quote:
            raise ValueError("Emergency rule quote differs")
        if rule_id == "RULE-ST02-04" and "ST04_PACKAGING-SPD" not in source_quote:
            raise ValueError("Correlation rule quote differs")
        rule = resource("rule", rule_id)
        graph.add((rule, RDF.type, IM.Rule))
        graph.add((rule, IM.sourceDocument, resource("document", "SOP-001")))
        graph.add((rule, IM.sourcePage, Literal(1, datatype=XSD.positiveInteger)))
        graph.add((rule, IM.appliesToSensor, sensor))
        for pred, text in [(IM.identifier, rule_id), (IM.conditionText, condition), (IM.responseText, response),
                           (IM.sourceQuote, source_quote), (IM.extractionMethod, "manual source-grounded example; not LLM extraction")]:
            graph.add((rule, pred, Literal(text)))
        for target in targets:
            graph.add((rule, target_pred, target))
        lineage.append({"rule_id": rule_id, "doc_id": "SOP-001", "source_page": 1,
                        "text_start": start, "text_end": start + len(source_quote),
                        "source_quote": source_quote, "method": "manual source-grounded example"})
    return lineage


def add_sample_observations(graph, sources, mapping):
    relative = "inputs/sensors/timeseries_ml_input.csv"
    sources.file(relative)
    frame = read_verified(sources.base, relative, sources.manifest)
    if list(frame) != OBSERVATIONS or len(frame) != 211200:
        raise ValueError("Detector source schema/version differs")
    if frame.duplicated(["sensor_id", "timestamp"]).any() or not frame["value"].map(math.isfinite).all():
        raise ValueError("Invalid observation key/value")
    lookup = {row["sensor_id"]: row for row in mapping}
    for row in frame.sort_values(["sensor_id", "timestamp"], kind="stable").groupby("sensor_id", sort=True).head(1).itertuples(index=False):
        match = lookup[row.sensor_id]
        if row.station_id != match["station_id"] or row.unit != match["unit"] or row.sensor_type != match["sensor_type"]:
            raise ValueError("Observation sensor/station/unit mismatch")
        obs = resource("observation", row.sensor_id + "@" + row.timestamp.isoformat())
        graph.add((obs, RDF.type, IM.Observation))
        graph.add((obs, IM.observedBy, INST[match["sensor_node_id"]]))
        graph.add((obs, IM.timestamp, Literal(row.timestamp.isoformat(), datatype=XSD.dateTime)))
        graph.add((obs, IM.value, Literal(float(row.value), datatype=XSD.double)))
        graph.add((obs, IM.unit, Literal(row.unit)))
        graph.add((obs, IM.sourcePath, Literal(relative)))
    return len(frame)


def build(base=COMMON, output=OUT, *, record_date=None):
    if record_date is not None:
        date.fromisoformat(record_date)
    sources = VerifiedSources(base)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    graph, mapping, nodes, edges = build_static(sources)
    ml_graph = new_graph()
    for triple in graph:
        ml_graph.add(triple)
    ml_graph.serialize(destination=output / "ml_metadata.ttl", format="turtle")
    graph.set((IM.InputData, IM.inputProfile, Literal("rule_context")))
    documents, pages, _ = add_documents(graph, sources)
    rules = add_threshold_rules(graph, sources, mapping)
    manual_rules = add_sop_examples(graph, pages)
    rows = add_sample_observations(graph, sources, mapping)
    graph.serialize(destination=output / "rule_context.ttl", format="turtle")
    write_json(output / "rule_lineage.json", {"threshold_rules": rules, "manual_source_examples": manual_rules})
    counts = Counter(str(kind).removeprefix(str(IM)) for _, _, kind in graph.triples((None, RDF.type, None)) if str(kind).startswith(str(IM)))
    summary = {"record_date": record_date, "date_source": "caller supplied; host clock not inferred", "common_manifest_sha256": sources.consumed["manifest.json"],
               "source_archive_sha256": sources.manifest["source_archive_sha256"], "consumed_common_files": sources.consumed,
               "static_nodes": len(nodes), "static_source_edges": len(edges), "derived_located_in_edges": 9,
               "classes_in_rule_context": dict(sorted(counts.items())), "documents": len(documents),
               "threshold_rules": len(rules), "manual_source_rules": len(manual_rules),
               "source_sensor_rows": rows, "rdf_observation_examples": 22,
               "ml_metadata_triples": len(ml_graph), "rule_context_triples": len(graph),
               "component_mapping": "Component -> Station; sourceLabel and original node IRI retained",
               "evaluation_files_read": [], "llm_extraction_run": False, "detector_changed": False,
               "timezone": "Source timezone unspecified; xsd:dateTime has no fabricated timezone offset",
               "limits": ["22 RDF observations are schema examples, not the full time series",
                          "Rule instances come from source documents, not the 86 evaluation rules",
                          "No installed internal components, datasheet model assignments, or quality defect instances inferred",
                          "No seeded or detected event instances exported in this v1",
                          "ml_metadata contains no Document/Rule/ThresholdRule; detector still uses its seven-column CSV"]}
    write_json(output / "build_summary.json", summary)
    outputs = {p.name: sha256(p) for p in sorted(output.iterdir()) if p.name in {"ml_metadata.ttl", "rule_context.ttl", "rule_lineage.json", "build_summary.json"}}
    write_json(output / "build_manifest.json", {"builder_sha256": sha256(__file__), "output_files_sha256": outputs,
               "common_files_sha256": sources.consumed})
    print(json.dumps({"static_nodes": 83, "static_edges": 269, "documents": 7, "rules": 24,
                      "observation_examples": 22, "output": str(output)}, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-date", help="Client/project date as YYYY-MM-DD; omitted means undated")
    build(record_date=parser.parse_args().record_date)
