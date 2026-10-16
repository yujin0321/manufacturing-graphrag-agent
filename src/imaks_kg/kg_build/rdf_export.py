"""Export built KG JSONL artifacts to Turtle for SHACL validation."""
import argparse
import re
from decimal import Decimal
from pathlib import Path

from imaks_kg.common.io_utils import write_text
from imaks_kg.kg_build.document_nodes import load_jsonl
from imaks_kg.settings import REPO_ROOT


NUMERIC_PROPS = {"page", "pageCount", "charStart", "charEnd", "rowIndex", "colIndex"}
DECIMAL_PROPS = {"nominal", "warnHi", "warnLo", "critHi", "critLo"}
RULE_CLASS_PROPS = {
    "condition": "conditionText",
    "action": "responseText",
    "ruleSeverity": "ruleSeverity",
    "extractionMethod": "extractionMethod",
    "critHi": "critHi",
    "critLo": "critLo",
    "warnHi": "warnHi",
    "warnLo": "warnLo",
    "nominal": "nominal",
    "priority": "priority",
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
    elif pred in DECIMAL_PROPS:
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError(f"Nonfinite numeric property: {pred}")
        value, dtype = format(number, "f"), "decimal"
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
        props = {k: v for k, v in n.get("properties", {}).items() if k != "source" and k not in DECIMAL_PROPS}
        lines.append(typed_node(n["id"], labels[0], props))
    for r in rels:
        lines.append(f"inst:{iri_name(r['source'])} im:{r['type']} inst:{iri_name(r['target'])} .\n")
        for pid in r.get("provenanceIds", []):
            lines.append(f"inst:{iri_name(r['source'])} im:hasProvenance inst:{iri_name(pid)} .")
    for d in docs:
        lines.append(typed_node(d["id"], "Document", d.get("properties", {})))
    for p in provs:
        lines.append(typed_node(p["id"], "Provenance", p.get("properties", {})))
    for r in rules:
        rid = r.get("ruleId", "")
        klass = r.get("class", "Rule")
        props = {"identifier": rid}
        for src, dst in RULE_CLASS_PROPS.items():
            if r.get(src) not in (None, ""):
                props[dst] = r[src]
        if r.get("class") == "ThresholdRule":
            props.update({k: v for k, v in r.get("numeric", {}).items() if k in DECIMAL_PROPS and v not in (None, "")})
        lines.append(typed_node(rid, klass, props).rstrip())
        tail = []
        doc = r.get("sourceDocument")
        prov = r.get("provenanceId")
        sensor = r.get("sensor")
        station = r.get("station")
        if doc:
            tail.append(f"inst:{iri_name(rid)} im:sourceDocument inst:{iri_name(doc)} .")
        for pid in r.get("provenanceIds", [prov] if prov else []):
            tail.append(f"inst:{iri_name(rid)} im:hasProvenance inst:{iri_name(pid)} .")
        for sid in r.get("sensors", [sensor] if sensor else []):
            if sid not in sensors:
                raise ValueError(f"Unknown sensor in {rid}: {sid}")
            tail.append(f"inst:{iri_name(rid)} im:appliesToSensor inst:{iri_name(sid)} .")
        for sid in r.get("action_targets", [station] if station else []):
            if sid not in stations:
                raise ValueError(f"Unknown action target in {rid}: {sid}")
            tail.append(f"inst:{iri_name(rid)} im:actionTarget inst:{iri_name(sid)} .")
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
