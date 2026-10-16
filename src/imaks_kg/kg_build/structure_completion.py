"""Source-only process flow and ontology completeness audits."""
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from imaks_kg.kg_build.document_nodes import load_jsonl, manifest_by_doc


def document_flows(layout, stations):
    flows, provs = [], []
    manifests = manifest_by_doc(layout)
    for t in load_jsonl(layout.tables_jsonl):
        rows = t.get("rows", [])
        if not rows or not {"Station ID", "Downstream Effect"} <= set(rows[0]):
            continue
        head = rows[0]
        for ri, row in enumerate(rows[1:], 2):
            source = row[head.index("Station ID")]
            quote = row[head.index("Downstream Effect")]
            match = re.match(r"Feeds\s+([A-Z0-9_]+)\b", quote)
            if not match:
                continue
            candidates = [s for s in stations if s == match[1] or s.split("_")[0] == match[1]]
            if source not in stations or len(candidates) != 1:
                raise ValueError("Ambiguous source process flow")
            target = candidates[0]
            pid = f"prov:flow:{t['table_id']}:{ri}"
            props = {"sourceKind": "document", "page": t["page"], "tableId": t["table_id"],
                     "rowIndex": ri, "colIndex": head.index("Downstream Effect") + 1,
                     "sourceQuote": quote, "textSha256": hashlib.sha256(quote.encode()).hexdigest(),
                     "fileSha256": manifests[t["document_id"]]["file_sha256"]}
            if t.get("bbox"):
                props["bbox"] = json.dumps(t["bbox"])
            provs.append({"id": pid, "labels": ["Provenance"], "properties": props})
            flows.append({"source": source, "target": target, "type": "feedsInto",
                          "provenanceIds": [pid], "sourceDocument": t["document_id"]})
    if len({(r["source"], r["target"]) for r in flows}) != len(flows):
        raise ValueError("Duplicate flow evidence requires explicit consolidation")
    return flows, provs


def audit_graph(root):
    from rdflib import Graph, Namespace, RDF, XSD
    from imaks_kg.kg_build.rdf_export import iri_name
    root = Path(root)
    im = Namespace("https://example.org/imaks/v1#")
    inst = Namespace("https://example.org/imaks/instance/")
    g = Graph().parse(root / "kg.ttl")
    types = Counter(str(o).split("#")[-1] for _, o in g.subject_objects(RDF.type))
    relations = {k: len(list(g.triples((None, im[k], None)))) for k in
                 ["hasSensor", "feedsInto", "appliesToSensor", "actionTarget", "sourceDocument", "hasProvenance"]}
    errors = []
    for k, n in {"Station": 9, "Sensor": 22, "Document": 7}.items():
        if types[k] != n:
            errors.append(f"{k}: expected {n}, got {types[k]}")
    for k, n in {"hasSensor": 22, "feedsInto": 3}.items():
        if relations[k] != n:
            errors.append(f"{k}: expected {n}, got {relations[k]}")
    for key in ["nominal", "critHi", "critLo", "warnHi", "warnLo"]:
        for s, o in g.subject_objects(im[key]):
            if (s, RDF.type, im.ThresholdRule) not in g or o.datatype != XSD.decimal:
                errors.append(f"Invalid {key} domain or datatype")
    for s in g.subjects(im.priority, None):
        if (s, RDF.type, im.MaintenanceRule) not in g:
            errors.append("Invalid priority domain")
    rules = load_jsonl(root / "rules_extracted.jsonl")
    for row in rules:
        s = inst[iri_name(row["ruleId"])]
        if len(list(g.objects(s, im.appliesToSensor))) != len(set(row.get("sensors", []))):
            errors.append("Sensor targets lost during export")
        if len(list(g.objects(s, im.actionTarget))) != len(set(row.get("action_targets", []))):
            errors.append("Action targets lost during export")
    return {"triple_count": len(g), "classes": dict(types), "relations": relations,
            "priority_count": len(list(g.triples((None, im.priority, None)))),
            "decimal_count": sum(o.datatype == XSD.decimal for o in g.objects() if hasattr(o, "datatype")),
            "errors": errors, "passed": not errors}
