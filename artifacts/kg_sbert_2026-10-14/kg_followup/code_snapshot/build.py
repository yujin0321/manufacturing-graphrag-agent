"""Build a local RDF KG from seed structure and frozen, source-backed predictions.

No ground-truth argument, API call, automatic rule extraction, or live DB write.
"""
import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, RDF, URIRef, XSD
from pyshacl import validate

IM = Namespace("https://example.org/imaks/v1#")
BASE = "https://example.org/imaks/id/"
DOC_IDS = ("SOP-001", "SOP-002", "SOP-003", "SOP-004",
           "DS-ELEC-3300", "DS-MECH-4400", "DS-THERM-2200")
CLASSES = {"OperationalRule", "ThresholdRule", "MaintenanceRule", "AccessRule"}
FIELDS = {"identifier", "ruleClass", "conditionText", "responseText", "unit_id",
          "sourceQuote", "sensorIds", "actionTargets"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def text_sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False) + "\n", encoding="utf-8")


def uri(kind, ident):
    return URIRef(BASE + kind + "/" + quote(ident, safe=""))


def load_sources(source_dir):
    source_dir = Path(source_dir)
    manifest = json.loads((source_dir / "input_manifest.json").read_text(encoding="utf-8-sig"))["sha256"]
    expected = {d + ".json" for d in DOC_IDS} | {"ontology.ttl", "shapes.ttl"}
    if set(manifest) != expected:
        raise ValueError("Unexpected source manifest entries")
    for name, digest in manifest.items():
        if sha(source_dir / name) != digest:
            raise ValueError("Input hash mismatch: " + name)
    docs = {d: json.loads((source_dir / (d + ".json")).read_text(encoding="utf-8-sig")) for d in DOC_IDS}
    units = {}
    for doc_id, doc in docs.items():
        if doc["document_id"] != doc_id:
            raise ValueError("Source document identity mismatch")
        for unit in doc["units"]:
            key = unit["unit_id"]
            if key in units or text_sha(unit["text"]) != unit["text_sha256"]:
                raise ValueError("Duplicate unit or bad unit hash: " + key)
            units[key] = unit
    return docs, units


def validate_predictions(predictions, docs, units):
    seen = set()
    for r in predictions:
        if not FIELDS <= r.keys() or set(r) - (FIELDS | {"numeric", "priority"}):
            raise ValueError("Invalid prediction fields")
        if not all(isinstance(r[k], str) for k in FIELDS - {"sensorIds", "actionTargets"}):
            raise ValueError("Invalid prediction string type")
        if not r["identifier"] or not r["conditionText"] or r["identifier"] in seen:
            raise ValueError("Empty/duplicate prediction identifier or condition")
        seen.add(r["identifier"])
        if r["ruleClass"] not in CLASSES or r["unit_id"] not in units:
            raise ValueError("Invalid rule class or unit")
        unit = units[r["unit_id"]]
        if not r["sourceQuote"] or r["sourceQuote"] not in unit["text"]:
            raise ValueError("Quote is not an exact source substring")
        inventory = docs[unit["doc_id"]]["inventory"]
        for field in ("sensorIds", "actionTargets"):
            if (not isinstance(r[field], list) or
                    any(not isinstance(x, str) for x in r[field]) or
                    len(set(r[field])) != len(r[field]) or
                    not set(r[field]) <= set(inventory[field])):
                raise ValueError("Invalid inventory reference")
        if "numeric" in r:
            numeric = r["numeric"]
            if (not isinstance(numeric, dict) or
                    set(numeric) - {"nominal", "warnLo", "warnHi", "critLo", "critHi"} or
                    any(type(v) not in (int, float) or not math.isfinite(v) for v in numeric.values())):
                raise ValueError("Invalid/nonfinite numeric value")
        if "priority" in r and not isinstance(r["priority"], str):
            raise ValueError("Invalid priority")


def build(nodes_path, edges_path, source_dir, predictions_path, ontology, shapes, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError("Use a new output directory")
    docs, units = load_sources(source_dir)
    predictions = [json.loads(line) for line in Path(predictions_path).read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    validate_predictions(predictions, docs, units)
    nodes, edges = read_csv(nodes_path), read_csv(edges_path)
    by_id = {n["nodeId"]: n for n in nodes}
    if len(by_id) != len(nodes):
        raise ValueError("Duplicate seed node ID")
    selected = [n for n in nodes if n["label"] in {"Component", "Station", "Sensor"}]
    if len({n["name"] for n in selected}) != len(selected):
        raise ValueError("Ambiguous seed identity")
    stations = {n["name"]: n for n in selected if n["label"] in {"Component", "Station"}}
    sensors = {n["name"]: n for n in selected if n["label"] == "Sensor"}
    for doc in docs.values():
        if not set(doc["inventory"]["sensorIds"]) <= sensors.keys() or not set(doc["inventory"]["actionTargets"]) <= stations.keys():
            raise ValueError("Document inventory missing from seed structure")
    graph, lineage = Graph(), defaultdict(list)

    def add(s, p, o, evidence):
        triple = (s, p, o)
        graph.add(triple)
        if evidence not in lineage[triple]:
            lineage[triple].append(evidence)

    def prop(s, key, value, evidence, datatype=None):
        add(s, IM[key], Literal(value, datatype=datatype), evidence)

    def seed_prov(file_name, row_id, digest):
        evidence = {"kind": "seedCsv", "file": file_name, "row": row_id, "sha256": digest}
        pv = uri("provenance", file_name + ":" + row_id)
        add(pv, RDF.type, IM.Provenance, evidence)
        for k, v in {"sourceKind": "seedCsv", "fileName": file_name,
                     "sourceRowId": row_id, "fileSha256": digest}.items():
            prop(pv, k, v, evidence)
        return pv, evidence

    node_hash, edge_hash = sha(nodes_path), sha(edges_path)
    seed_uri = {}
    for n in selected:
        cls = "Sensor" if n["label"] == "Sensor" else "Station"
        entity = uri(cls.lower(), n["name"])
        seed_uri[n["nodeId"]] = entity
        pv, evidence = seed_prov("nodes.csv", n["nodeId"], node_hash)
        add(entity, RDF.type, IM[cls], evidence)
        add(entity, IM.hasProvenance, pv, evidence)
        for k, v in {"identifier": n["name"], "sourceNodeId": n["nodeId"]}.items():
            prop(entity, k, v, evidence)
        for k in (["sensorType", "unit"] if cls == "Sensor" else ["stationType", "zone"]):
            if not n[k]:
                raise ValueError("Missing seed field: " + k)
            prop(entity, k, n[k], evidence)
    skipped_edges, owners = Counter(), defaultdict(set)
    for index, edge in enumerate(edges, start=2):
        a, b = by_id.get(edge["fromId"]), by_id.get(edge["toId"])
        if a is None or b is None:
            raise ValueError("Dangling seed edge")
        pair, relation = None, None
        if edge["type"] == "monitors":
            if a["label"] == "Sensor" and b["name"] in stations:
                a, b = b, a
            if a["name"] in stations and b["name"] in sensors:
                pair, relation = (seed_uri[a["nodeId"]], seed_uri[b["nodeId"]]), IM.hasSensor
                owners[b["name"]].add(a["name"])
        elif edge["type"] == "feeds_into" and a["name"] in stations and b["name"] in stations:
            pair, relation = (seed_uri[a["nodeId"]], seed_uri[b["nodeId"]]), IM.feedsInto
        if pair:
            pv, evidence = seed_prov("edges.csv", "line:" + str(index), edge_hash)
            add(*pair[:1], relation, pair[1], evidence)
            add(pair[0], IM.hasProvenance, pv, evidence)
        else:
            skipped_edges[edge["type"]] += 1
    if set(owners) != set(sensors) or any(len(v) != 1 for v in owners.values()):
        raise ValueError("Each sensor must have exactly one seed station")

    for doc_id, doc in docs.items():
        d = uri("document", doc_id)
        source_hashes = {u["source_file_sha256"] for u in doc["units"]}
        if len(source_hashes) != 1:
            raise ValueError("Inconsistent original PDF hash")
        evidence = {"kind": "documentSnapshot", "document_id": doc_id,
                    "sha256": sha(Path(source_dir) / (doc_id + ".json"))}
        add(d, RDF.type, IM.Document, evidence)
        prop(d, "identifier", doc_id, evidence)
        prop(d, "sourceSha256", next(iter(source_hashes)), evidence)
        prop(d, "pageCount", max(u["page"] for u in doc["units"]), evidence, XSD.positiveInteger)

    pred_hash = sha(predictions_path)
    for r in predictions:
        u = units[r["unit_id"]]
        evidence = {"kind": "document", "document_id": u["doc_id"], "unit_id": u["unit_id"],
                    "source_snapshot_sha256": sha(Path(source_dir) / (u["doc_id"] + ".json")),
                    "prediction_sha256": pred_hash, "identifier": r["identifier"],
                    "quote_offset_in_unit": u["text"].index(r["sourceQuote"]),
                    "coordinates_scope": "source unit; not recomputed PDF character offsets"}
        entity, pv = uri("rule", r["identifier"]), uri("provenance", r["identifier"])
        add(entity, RDF.type, IM.Rule, evidence)
        add(entity, RDF.type, IM[r["ruleClass"]], evidence)
        add(entity, IM.sourceDocument, uri("document", u["doc_id"]), evidence)
        add(entity, IM.hasProvenance, pv, evidence)
        for k in ("identifier", "conditionText", "responseText"):
            prop(entity, k, r[k], evidence)
        prop(entity, "extractionMethod", "새 대화에서 수행한 문서 전체 LLM 추출", evidence)
        if "priority" in r:
            prop(entity, "priority", r["priority"], evidence)
        for k, v in r.get("numeric", {}).items():
            prop(entity, k, str(v), evidence, XSD.decimal)
        for sid in r["sensorIds"]:
            add(entity, IM.appliesToSensor, uri("sensor", sid), evidence)
        for target in r["actionTargets"]:
            add(entity, IM.actionTarget, uri("station", target), evidence)
        add(pv, RDF.type, IM.Provenance, evidence)
        for k, v in {"sourceKind": "document", "sourceQuote": r["sourceQuote"],
                     "textSha256": text_sha(r["sourceQuote"])}.items():
            prop(pv, k, v, evidence)
        prop(pv, "page", u["page"], evidence, XSD.positiveInteger)
        if u["kind"] == "table":
            prop(pv, "tableId", u["table_id"], evidence)
            prop(pv, "rowIndex", u["row_index"], evidence, XSD.integer)
            # A whole-row quote spans the existing columns, not an invented cell.
            for column in range(1, len(u["cells"]) + 1):
                prop(pv, "colIndex", column, evidence, XSD.integer)
            prop(pv, "bbox", json.dumps(u["bbox"]), evidence)
        else:
            prop(pv, "charStart", u["char_start"], evidence, XSD.integer)
            prop(pv, "charEnd", u["char_end"], evidence, XSD.integer)

    maintenance = []
    migrated_maintenance_edges = 0
    for n in nodes:
        if n["label"] != "Maintenance":
            continue
        matches = [r for r in predictions if r["identifier"] == n["ruleId"]]
        linked, source_edges = set(), []
        for edge_index, edge in enumerate(edges, start=2):
            other = (edge["toId"] if edge["fromId"] == n["nodeId"] else
                     edge["fromId"] if edge["toId"] == n["nodeId"] else None)
            if other and by_id[other]["label"] == "Sensor" and edge["type"] in {"triggers", "resolves"}:
                linked.add(by_id[other]["name"])
                source_edges.append((edge_index, edge, by_id[other]["name"]))
        # Preserve the seed identity without replacing the document-derived action.
        if len(matches) == 1 and matches[0]["ruleClass"] == "MaintenanceRule":
            entity = uri("rule", n["ruleId"])
            pv, evidence = seed_prov("nodes.csv", n["nodeId"], node_hash)
            prop(entity, "sourceNodeId", n["nodeId"], evidence)
            add(entity, IM.hasProvenance, pv, evidence)
            if set(matches[0]["sensorIds"]) == linked:
                for index, edge, sensor in source_edges:
                    pv, evidence = seed_prov("edges.csv", "line:" + str(index), edge_hash)
                    add(entity, IM.appliesToSensor, uri("sensor", sensor), evidence)
                    add(entity, IM.hasProvenance, pv, evidence)
                    skipped_edges[edge["type"]] -= 1
                    migrated_maintenance_edges += 1
        maintenance.append({"source_node_id": n["nodeId"], "rule_id": n["ruleId"],
                            "seed_action": n["action"], "seed_priority": n["priority"],
                            "seed_sensors": sorted(linked),
                            "prediction_ids": [r["identifier"] for r in matches],
                            "prediction_actions": [r["responseText"] for r in matches],
                            "class_matches": len(matches) == 1 and matches[0]["ruleClass"] == "MaintenanceRule",
                            "sensors_match": len(matches) == 1 and set(matches[0]["sensorIds"]) == linked,
                            "priority_matches": len(matches) == 1 and matches[0].get("priority") == n["priority"]})
    conforms, report_graph, report_text = validate(
        graph, shacl_graph=Graph().parse(shapes), ont_graph=Graph().parse(ontology), inference="none")
    forbidden = {IM.AnomalyEvent, IM.Person, IM.CausalLink, IM.Spike, IM.Drift, IM.StuckSensor, IM.OutOfRange, IM.Correlated}
    if any(t in forbidden for t in graph.objects(None, RDF.type)) or any(graph.triples((None, IM.causallyAffects, None))):
        raise ValueError("Excluded event/person/causal instance generated")
    output.mkdir(parents=True)
    ordered = sorted(graph, key=lambda t: tuple(x.n3() for x in t))
    (output / "graph.ttl").write_text("\n".join(" ".join(x.n3() for x in t) + " ." for t in ordered) + "\n", encoding="utf-8")
    with (output / "triple_lineage.jsonl").open("w", encoding="utf-8") as f:
        for t in ordered:
            f.write(json.dumps({"triple": [x.n3() for x in t], "sources": lineage[t]}, ensure_ascii=False) + "\n")
    (output / "shacl_report.txt").write_text(report_text, encoding="utf-8")
    write_json(output / "maintenance_mapping.json", maintenance)
    if len(Graph().parse(output / "graph.ttl")) != len(graph):
        raise ValueError("RDF serialization lost triples")
    counts = Counter(str(t).split("#")[-1] for t in graph.objects(None, RDF.type))
    summary = {"status": "PASS" if conforms else "FAIL", "shacl_conforms": bool(conforms),
               "inference": "none", "nodes_by_class": dict(counts),
               "unique_nodes": len(set(graph.subjects())), "triples": len(graph),
               "hasSensor": len(list(graph.triples((None, IM.hasSensor, None)))),
               "feedsInto": len(list(graph.triples((None, IM.feedsInto, None)))),
               "rule_sensor_links": len(list(graph.triples((None, IM.appliesToSensor, None)))),
               "action_target_links": len(list(graph.triples((None, IM.actionTarget, None)))),
               "triple_lineage_complete": len(lineage) == len(graph),
               "migrated_maintenance_source_edges": migrated_maintenance_edges,
               "seed_node_counts": dict(Counter(n["label"] for n in nodes)),
               "skipped_edges": dict(skipped_edges), "ground_truth_used_for_build": False,
               "neo4j_loaded": False,
               "input_hashes": {"nodes.csv": node_hash, "edges.csv": edge_hash,
                                "predictions.jsonl": pred_hash, "ontology.ttl": sha(ontology), "shapes.ttl": sha(shapes)}}
    write_json(output / "summary.json", summary)
    if not conforms:
        raise ValueError("SHACL validation failed; see report")
    export_cypher(graph, output / "neo4j_import.cypher")
    return summary


def export_cypher(graph, target):
    lines = ["// Generated for review/import only; not executed against any Neo4j database.",
             "CREATE CONSTRAINT imaks_uri IF NOT EXISTS FOR (n:KGNode) REQUIRE n.uri IS UNIQUE;"]
    for subject in sorted(set(graph.subjects()), key=str):
        labels = sorted(str(t).split("#")[-1] for t in graph.objects(subject, RDF.type))
        values = defaultdict(list)
        for pred, obj in graph.predicate_objects(subject):
            if isinstance(obj, Literal):
                value = obj.toPython()
                if obj.datatype == XSD.decimal:
                    value = float(value)
                values[str(pred).split("#")[-1]].append(value)
        props = {k: v[0] if len(v) == 1 else sorted(v, key=str) for k, v in values.items()}
        encoded = "{" + ", ".join("`" + k + "`: " + json.dumps(v, ensure_ascii=False) for k, v in sorted(props.items())) + "}"
        lines.append("MERGE (n:KGNode {uri: " + json.dumps(str(subject)) + "}) SET n:" + ":".join(labels) + " SET n += " + encoded + ";")
    for s, p, o in sorted(graph, key=lambda t: tuple(map(str, t))):
        if p != RDF.type and isinstance(o, URIRef):
            relation = str(p).split("#")[-1]
            lines.append("MATCH (a:KGNode {uri: " + json.dumps(str(s)) + "}), (b:KGNode {uri: " + json.dumps(str(o)) + "}) MERGE (a)-[:" + relation + "]->(b);")
    Path(target).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("nodes", "edges", "source-dir", "predictions", "ontology", "shapes", "output"):
        p.add_argument("--" + key, required=True, type=Path)
    a = p.parse_args()
    result = build(a.nodes, a.edges, a.source_dir, a.predictions, a.ontology, a.shapes, a.output)
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
