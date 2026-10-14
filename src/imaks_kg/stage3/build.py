"""Convert seed facts and verified extraction records to RDF and offline Neo4j import.

Does not read ground_truth.csv. Every asserted triple receives a source ledger entry.
"""
import argparse
import json
from decimal import Decimal
from collections import Counter
from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, RDF, XSD
from pyshacl import validate

from imaks_kg.settings import REPO_ROOT
from .common import DOCS, OUT, digest, read_csv, read_jsonl, write_json, write_jsonl

IM = Namespace("https://example.org/imaks/v1#")
INST = Namespace("https://example.org/imaks/instance/")


def decimal_literal(value):
    text = format(Decimal(value), 'f')
    if '.' not in text:
        text += '.0'
    return Literal(text, datatype=XSD.decimal)


class Builder:
    def __init__(self):
        self.graph = Graph()
        self.graph.bind("im", IM)
        self.graph.bind("inst", INST)
        self.ledger = []

    def uri(self, category, identifier):
        return INST[category + "/" + quote(identifier, safe="")]

    def add(self, s, p, o, sources):
        self.graph.add((s, p, o))
        self.ledger.append({"subject": str(s), "predicate": str(p), "object": o.n3(), "sources": sources})

    def node(self, kind, identifier, props, sources):
        u = self.uri(kind, identifier)
        self.add(u, RDF.type, IM[kind], sources)
        for key, value in {"identifier": identifier, **props}.items():
            if value is not None and value != "":
                self.add(u, IM[key], value if isinstance(value, Literal) else Literal(value), sources)
        return u

    def provenance(self, owner, identifier, props, sources):
        p = self.node("Provenance", identifier, props, sources)
        self.add(owner, IM.hasProvenance, p, sources)


def build(predictions=None, supplement=None):
    b = Builder()
    seed = REPO_ROOT / "imaks_data/kg_seed"
    paths = {name: seed / name for name in ("nodes.csv", "edges.csv")}
    hashes = {name: digest(p.read_bytes()) for name, p in paths.items()}
    rows = read_csv(paths["nodes.csv"])
    nodes = {r["nodeId"]: r for r in rows}
    manifest = read_csv(DOCS / "doc_manifest.csv")
    chunks = read_jsonl(DOCS / "chunks.jsonl")
    tables = {r["table_id"]: r for r in read_jsonl(DOCS / "tables.jsonl")}
    docs = {}
    for d in manifest:
        if digest((REPO_ROOT / d["file"]).read_bytes()) != d["file_sha256"]:
            raise ValueError("PDF hash mismatch: " + d["doc_id"])
        source = [{"file": d["file"], "sha256": d["file_sha256"]}]
        docs[d["doc_id"]] = b.node("Document", d["doc_id"], {
            "title": next(c["text"].splitlines()[0] for c in chunks if c["doc_id"] == d["doc_id"]),
            "sourcePath": d["file"], "sourceSha256": d["file_sha256"],
            "pageCount": Literal(int(d["pages"]), datatype=XSD.positiveInteger),
        }, source)
    mapped, mapping = {}, []
    for row in rows:
        kind = {"Component": "Station", "Sensor": "Sensor", "Maintenance": "MaintenanceRule"}.get(row["label"])
        if not kind:
            continue
        identifier = row["ruleId"] if kind == "MaintenanceRule" else row["name"]
        src = [{"file": "imaks_data/kg_seed/nodes.csv", "rowId": row["nodeId"], "sha256": hashes["nodes.csv"]}]
        props = {"sourceNodeId": row["nodeId"]}
        if kind == "Station":
            props.update(stationType=row["stationType"], zone=row["zone"])
        elif kind == "Sensor":
            props.update(sensorType=row["sensorType"], unit=row["unit"])
        else:
            props.update(responseText=row["action"], priority=row["priority"], extractionMethod="seedCsv")
        u = mapped[row["nodeId"]] = b.node(kind, identifier, props, src)
        b.provenance(u, "seed:" + row["nodeId"], {
            "sourceKind": "seedCsv", "fileName": src[0]["file"],
            "sourceRowId": row["nodeId"], "fileSha256": hashes["nodes.csv"],
        }, src)
        if kind == "MaintenanceRule":
            # Verify the ID in the actual SOP table before assigning sourceDocument.
            matches = [(t, i, cells) for t in tables.values() if t["doc_id"] == "SOP-003"
                       for i, cells in enumerate(t["rows_normalized"]) if identifier in cells]
            if len(matches) != 1:
                raise ValueError("Ambiguous/missing SOP row: " + identifier)
            table, ri, cells = matches[0]
            text = " | ".join(x or "" for x in cells)
            evidence = [{"document": "SOP-003", "tableId": table["table_id"], "rowIndex": ri + 1}]
            b.add(u, IM.sourceDocument, docs["SOP-003"], evidence)
            b.provenance(u, "seed-doc:" + identifier, {
                "sourceKind": "document", "page": table["page"], "tableId": table["table_id"],
                "rowIndex": ri + 1, "colIndex": 1, "sourceQuote": text, "textSha256": digest(text),
            }, evidence)
            mapping.append({"ruleId": identifier, "seedAction": row["action"], "documentRow": text,
                            "tableId": table["table_id"], "rowIndex": ri + 1, "method": "ID lookup, not LLM extraction"})
    excluded = Counter()
    for i, e in enumerate(read_csv(paths["edges.csv"]), start=2):
        left, right = nodes[e["fromId"]], nodes[e["toId"]]
        a, z, relation = e["fromId"], e["toId"], None
        if e["type"] == "monitors" and {left["label"], right["label"]} == {"Component", "Sensor"}:
            if left["label"] == "Sensor":
                a, z = z, a
            relation = "hasSensor"
        elif e["type"] == "feeds_into" and left["label"] == right["label"] == "Component":
            relation = "feedsInto"
        elif e["type"] in ("triggers", "resolves") and {left["label"], right["label"]} == {"Maintenance", "Sensor"}:
            if left["label"] == "Sensor":
                a, z = z, a
            relation = "appliesToSensor"
        if relation:
            b.add(mapped[a], IM[relation], mapped[z], [{"file": "imaks_data/kg_seed/edges.csv",
                  "rowId": str(i), "sha256": hashes["edges.csv"], "originalRelation": e["type"]}])
        else:
            excluded[e["type"]] += 1
    if predictions or supplement:
        from .extract import validate_rules, evidence_of
        records = validate_rules((read_jsonl(predictions) if predictions else []) + (read_jsonl(supplement) if supplement else []))
        for r in records:
            method = r.get('extraction_method','LLM')
            origin_prefix = "llm:" if method == "LLM" else "source:"
            src = [{"chunkId": ev["chunk_id"], "sourceQuote": ev["source_quote"], "method": method}
                   for ev in evidence_of(r)]
            # Separate namespace avoids silently overwriting seed maintenance wording.
            u = b.node(r["class"], origin_prefix + r["prediction_id"], {
                "conditionText": r["condition"], "responseText": r["action"],
                "ruleSeverity": r["severity"], "extractionMethod": method,
                **{k: decimal_literal(v) for k,v in r.get('numeric',{}).items()},
            }, src)
            b.add(u, IM.sourceDocument, docs[r["doc_id"]], src)
            for sensor in r["sensors"]:
                b.add(u, IM.appliesToSensor, b.uri("Sensor", sensor), src)
            for station in r["action_targets"]:
                b.add(u, IM.actionTarget, b.uri("Station", station), src)
            for index, ev in enumerate(evidence_of(r)):
                c = next(c for c in chunks if c["chunk_id"] == ev["chunk_id"])
                props = {"sourceKind": "document", "page": c["page"], "sourceQuote": ev["source_quote"],
                         "textSha256": digest(ev["source_quote"]), "fileSha256": c["source_file_sha256"]}
                if c["kind"] == "table":
                    props.update(tableId=c["table_id"], rowIndex=ev["table_row"] + 1, colIndex=ev["table_col"] + 1)
                else:
                    start = c["char_start"] + c["text"].index(ev["source_quote"])
                    props.update(charStart=start, charEnd=start + len(ev["source_quote"]))
                b.provenance(u, origin_prefix + r["prediction_id"] + ":" + str(index), props, src)
    OUT.mkdir(parents=True, exist_ok=True)
    stem = "enriched_with_supplement" if supplement else ("enriched" if predictions else "seed")
    for kind, expected in (("Station", 9), ("Sensor", 22), ("Document", 7)):
        if len(list(b.graph.subjects(RDF.type, IM[kind]))) != expected:
            raise ValueError("Unexpected instance count: " + kind)
    for rel, expected in (("hasSensor", 22), ("feedsInto", 3)):
        if len(list(b.graph.triples((None, IM[rel], None)))) != expected:
            raise ValueError("Unexpected relation count: " + rel)
    conforms, _, report = validate(b.graph, shacl_graph=str(REPO_ROOT / "ontology_v1/shapes.ttl"),
                                  ont_graph=str(REPO_ROOT / "ontology_v1/ontology.ttl"), inference="none")
    (OUT / (stem + "_shacl.txt")).write_text(report, encoding="utf-8")
    if not conforms:
        raise ValueError("SHACL failed; see " + stem + "_shacl.txt")
    b.graph.serialize(OUT / (stem + ".ttl"), format="turtle")
    write_jsonl(OUT / (stem + "_triple_sources.jsonl"), b.ledger)
    write_json(OUT / "maintenance_mapping.json", mapping)
    classes = Counter(str(o).split("#")[-1] for _, _, o in b.graph.triples((None, RDF.type, None)))
    summary = {"classes": dict(classes), "triples": len(b.graph), "shacl_conforms": bool(conforms),
               "relations": {k: len(list(b.graph.triples((None, IM[k], None)))) for k in ("hasSensor", "feedsInto", "appliesToSensor")},
               "excluded_seed_edges": dict(excluded), "seed_hashes": hashes,
               "prediction_sha256": digest(predictions.read_bytes()) if predictions else None,
               "supplement_sha256": digest(supplement.read_bytes()) if supplement else None,
               "supplement_is_llm_output": False,
               "causal_discovery_performed": False, "ground_truth_events_loaded": False}
    write_json(OUT / (stem + "_summary.json"), summary)
    export_cypher(b.graph, OUT / (stem + "_import.cypher"))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def export_cypher(graph, path):
    """Offline idempotent import. No credentials or automatic DB writes."""
    def value(v):
        return json.dumps(v.toPython() if isinstance(v, Literal) else str(v), ensure_ascii=False, default=str)
    lines = ["CREATE CONSTRAINT imaks_uri IF NOT EXISTS FOR (n:ImaksEntity) REQUIRE n.uri IS UNIQUE;"]
    for s in sorted(set(graph.subjects()), key=str):
        types = sorted(str(t).split("#")[-1] for t in graph.objects(s, RDF.type))
        props = {}
        for p, o in graph.predicate_objects(s):
            if isinstance(o, Literal):
                props.setdefault(str(p).split("#")[-1], []).append(o)
        assignments = ["n.`" + k + "` = " + (value(v[0]) if len(v) == 1 else "[" + ",".join(map(value, v)) + "]") for k, v in sorted(props.items())]
        lines.append("MERGE (n:ImaksEntity {uri: " + value(s) + "}) SET n:" + ":".join("`" + t + "`" for t in types) + (", " + ", ".join(assignments) if assignments else "") + ";")
    for s, p, o in sorted(graph, key=lambda t: tuple(map(str, t))):
        if p != RDF.type and not isinstance(o, Literal):
            lines.append("MATCH (a:ImaksEntity {uri: " + value(s) + "}), (b:ImaksEntity {uri: " + value(o) + "}) MERGE (a)-[:`" + str(p).split("#")[-1] + "`]->(b);")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--supplement", type=Path)
    args=parser.parse_args()
    build(args.predictions,args.supplement)
