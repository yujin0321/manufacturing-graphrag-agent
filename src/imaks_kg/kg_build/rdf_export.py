"""Export built KG JSONL artifacts to Turtle for SHACL validation."""
import argparse
import re
from pathlib import Path

from imaks_kg.common.io_utils import write_text
from imaks_kg.kg_build.document_nodes import load_jsonl
from imaks_kg.settings import REPO_ROOT


NUMERIC_PROPS = {"page", "pageCount", "charStart", "charEnd", "rowIndex", "colIndex"}
RULE_CLASS_PROPS = {
    "condition": "conditionText",
    "action": "responseText",
    "ruleSeverity": "ruleSeverity",
    "extractionMethod": "extractionMethod",
    "critHi": "critHi",
    "critLo": "critLo",
    "warnHi": "warnHi",
    "warnLo": "warnLo",
}


def iri_name(value):
    return re.sub(r"[^A-Za-z0-9_\\-]", "_", str(value))


def lit(value, datatype=None):
    text = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{text}"^^xsd:{datatype}' if datatype else f'"{text}"'


def prop_line(pred, value):
    if value in (None, ""):
        return None
    dtype = None
    if pred in NUMERIC_PROPS:
        dtype = "positiveInteger" if pred in {"page", "pageCount", "rowIndex", "colIndex"} else "nonNegativeInteger"
    return f"    im:{pred} {lit(value, dtype)}"


def typed_node(subject, klass, props):
    lines = [f"inst:{iri_name(subject)} a im:{klass}"]
    for key, value in props.items():
        line = prop_line(key, value)
        if line:
            lines.append(line)
    return " ;\n".join(lines) + " .\n"


def load_optional(path):
    return load_jsonl(path) if Path(path).exists() else []


def export_ttl(build_dir=None, out_path=None):
    root = Path(build_dir or (REPO_ROOT / "kg_build" / "latest"))
    out = Path(out_path or (root / "kg.ttl"))
    nodes = load_optional(root / "nodes.jsonl")
    rels = load_optional(root / "relationships.jsonl")
    docs = load_optional(root / "documents.jsonl")
    provs = load_optional(root / "provenance.jsonl")
    rules = load_optional(root / "rules_extracted.jsonl")
    sensors = {n["id"] for n in nodes if "Sensor" in n.get("labels", [])}
    stations = {n["id"] for n in nodes if "Station" in n.get("labels", [])}

    lines = [
        "@prefix im: <https://example.org/imaks/v1#> .",
        "@prefix inst: <https://example.org/imaks/instance/> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
    ]

    for n in nodes:
        labels = n.get("labels") or []
        if not labels:
            continue
        lines.append(typed_node(n["id"], labels[0], n.get("properties", {})))
    for r in rels:
        lines.append(f"inst:{iri_name(r['source'])} im:{r['type']} inst:{iri_name(r['target'])} .\n")
    for d in docs:
        lines.append(typed_node(d["id"], "Document", d.get("properties", {})))
    for p in provs:
        lines.append(typed_node(p["id"], "Provenance", p.get("properties", {})))
    for r in rules:
        rid = r.get("ruleId", "")
        klass = r.get("class", "Rule")
        props = {"identifier": rid}
        for src, dst in RULE_CLASS_PROPS.items():
            if r.get(src):
                props[dst] = r[src]
        lines.append(typed_node(rid, klass, props).rstrip())
        tail = []
        doc = r.get("sourceDocument")
        prov = r.get("provenanceId")
        sensor = r.get("sensor")
        station = r.get("station")
        if doc:
            tail.append(f"inst:{iri_name(rid)} im:sourceDocument inst:{iri_name(doc)} .")
        if prov:
            tail.append(f"inst:{iri_name(rid)} im:hasProvenance inst:{iri_name(prov)} .")
        if sensor in sensors:
            tail.append(f"inst:{iri_name(rid)} im:appliesToSensor inst:{iri_name(sensor)} .")
        if station in stations:
            tail.append(f"inst:{iri_name(rid)} im:actionTarget inst:{iri_name(station)} .")
        lines.extend(tail)
        lines.append("")

    write_text(out, "\n".join(lines).rstrip() + "\n")
    return out


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    out = export_ttl(args.build_dir, args.out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
