"""Frozen, single-model document extraction. No reference-answer access."""
import argparse
import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal, InvalidOperation

from imaks_kg.common.io_utils import write_json, write_jsonl
from imaks_kg.kg_build.document_nodes import build_documents, load_chunks, load_jsonl, manifest_by_doc
from imaks_kg.kg_build.preprocessed_abox import PreprocessedLayout, build_station_sensor
from imaks_kg.settings import REPO_ROOT

MODEL = "gpt-6.1-sol"
PROMPTS = Path(__file__).parent / "prompts"
VERSION = "sumin-sol-v1"
CLASSES = ["OperationalRule", "ThresholdRule", "MaintenanceRule", "AccessRule"]


def obj(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


STRING = {"type": "string"}
STRINGS = {"type": "array", "items": STRING}
SCHEMA = obj({
    "rules": {"type": "array", "items": obj({
        "class": {"type": "string", "enum": CLASSES}, "printed_rule_id": STRING,
        "condition": STRING, "action": STRING, "ruleSeverity": STRING,
        "priority": STRING,
        "numeric": obj({k: STRING for k in ["nominal", "critLo", "warnLo", "warnHi", "critHi"]}),
        "sensors": STRINGS, "action_targets": STRINGS,
        "evidence": {"type": "array", "items": obj({"unit_id": STRING, "quote": STRING})},
    })},
    "coverage": {"type": "array", "items": obj({
        "unit_id": STRING,
        "disposition": {"type": "string", "enum": ["included", "duplicate", "heading", "not_a_rule"]},
    })},
})


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def freeze(path, data):
    """Create once, or verify identical bytes; never overwrite experimental evidence."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"Frozen artifact differs: {path}. Use a new experiment directory.")
    else:
        with path.open("xb") as f:
            f.write(data)


def now():
    return datetime.now(timezone.utc).isoformat()


def source_packets(layout):
    manifests = manifest_by_doc(layout)
    chunks = load_chunks(layout)
    pages = load_jsonl(layout.pages_jsonl)
    tables = load_jsonl(layout.tables_jsonl)
    stations, sensors, _ = build_station_sensor(layout)
    packets = {}
    for doc, manifest in sorted(manifests.items()):
        units = []
        for c in chunks:
            if c.get("document_id") == doc and c.get("kind") != "table" and c.get("text", "").strip():
                units.append({"unit_id": c["chunk_id"], "kind": "text", "page": c["page"], "text": c["text"]})
        for t in tables:
            if t.get("document_id", t.get("doc_id")) != doc:
                continue
            for i, row in enumerate(t["rows"], 1):
                units.append({"unit_id": f"{t['table_id']}:row{i}", "kind": "table",
                              "table_id": t["table_id"], "row_index": i, "page": t["page"],
                              "text": " | ".join(str(v or "") for v in row),
                              "header": t["rows"][0], "bbox": t.get("bbox")})
        packets[doc] = {
            "document_id": doc, "source_sha256": manifest["file_sha256"],
            "allowed_stations": [s["id"] for s in stations],
            "allowed_sensors": [s["id"] for s in sensors],
            "page_context": [{"page": p["page"], "text": p["text"]} for p in pages if p.get("document_id") == doc],
            "units": units,
        }
    return packets


def request_for(packet):
    role = (PROMPTS / "sol_v1.txt").read_text(encoding="utf-8")
    example = (PROMPTS / "sol_example_v1.json").read_text(encoding="utf-8")
    return {"model": MODEL, "store": False, "reasoning": {"effort": "low"},
            "max_output_tokens": 24000, "service_tier": "default",
            "input": [{"role": "system", "content": role + "\nExample (fictional)\n" + example},
                      {"role": "user", "content": json.dumps(packet, ensure_ascii=False)}],
            "text": {"format": {"type": "json_schema", "name": "manufacturing_rules", "strict": True, "schema": SCHEMA}}}


def parse_response(response):
    if response.get("status") != "completed":
        raise ValueError("API response is not completed; raw response retained, no automatic retry")
    texts = []
    for output in response.get("output", []):
        for c in output.get("content", []):
            if c.get("type") == "refusal":
                raise ValueError("Model refused; raw response retained")
            if c.get("type") == "output_text":
                texts.append(c["text"])
    value = json.loads("".join(texts))
    from jsonschema import validate
    validate(value, SCHEMA)
    if response.get("model") != MODEL:
        raise ValueError("Actual model differs from requested model; do not mix experiments")
    return value


def quote_span(text, quote):
    """Match whitespace only flexibly, returning original offsets and original quote."""
    words = re.findall(r"\S+", quote)
    if not words:
        return None
    match = re.search(r"\s+".join(re.escape(w) for w in words), text)
    return (match.start(), match.end(), match.group()) if match else None


def normalize(value, packet):
    """Keep all model rules in predictions; only grounded rules enter candidate KG."""
    units = {u["unit_id"]: u for u in packet["units"]}
    pages = {p["page"]: p["text"] for p in packet["page_context"]}
    rules, provs, audits = [], [], []
    for index, raw in enumerate(value["rules"], 1):
        rid = f"{packet['document_id']}:sol:{index:04d}"
        flags, pids = [], []
        if not (raw["condition"].strip() or raw["action"].strip()):
            raise ValueError("Empty rule; preserve raw response and stop before evaluation")
        if set(raw["sensors"]) - set(packet["allowed_sensors"]):
            flags.append("unknown_sensor")
        if set(raw["action_targets"]) - set(packet["allowed_stations"]):
            flags.append("unknown_action_target")
        if not raw["evidence"]:
            flags.append("missing_evidence")
        source_text = "\n".join(units[e["unit_id"]]["text"] for e in raw["evidence"] if e["unit_id"] in units)
        for key, number in raw.get("numeric", {}).items():
            if number:
                try:
                    valid = Decimal(number).is_finite()
                except InvalidOperation:
                    valid = False
                source_numbers = re.findall(r"(?<![A-Za-z0-9])[-+]?\d+(?:\.\d+)?", source_text)
                if not valid or raw["class"] != "ThresholdRule" or not any(Decimal(s) == Decimal(number) for s in source_numbers):
                    flags.append(f"unsupported_numeric_{key}")
        if raw.get("priority") and (raw["class"] != "MaintenanceRule" or raw["priority"] not in source_text):
            flags.append("unsupported_priority")
        for eidx, evidence in enumerate(raw["evidence"], 1):
            unit = units.get(evidence["unit_id"])
            span = quote_span(unit["text"], evidence["quote"]) if unit else None
            if span is None:
                flags.append("evidence_not_found")
                continue
            quote = span[2]
            props = {"sourceKind": "document", "page": unit["page"],
                     "fileSha256": packet["source_sha256"]}
            if unit["kind"] == "table":
                first_col = unit["text"][:span[0]].count(" | ") + 1
                props.update(tableId=unit["table_id"], rowIndex=unit["row_index"], colIndex=first_col)
                if unit.get("bbox"):
                    props["bbox"] = json.dumps(unit["bbox"])
                # Coordinates identify the starting cell; quotes may span multiple cells.
            else:
                page_span = quote_span(pages[unit["page"]], quote)
                if page_span is None:
                    flags.append("page_position_unresolved")
                    continue
                props.update(charStart=page_span[0], charEnd=page_span[1])
                quote = page_span[2]
            props.update(sourceQuote=quote, textSha256=digest(quote.encode()))
            pid = f"prov:{rid}:{eidx}"
            provs.append({"id": pid, "labels": ["Provenance"], "properties": props})
            pids.append(pid)
        row = {**raw, "identifier": rid, "ruleId": rid, "document_id": packet["document_id"],
               "sourceDocument": packet["document_id"], "model": MODEL, "extractionMethod": "llm",
               "provenanceIds": pids, "validation_flags": sorted(set(flags)), "kg_eligible": not flags}
        rules.append(row)
        audits.append({"identifier": rid, "flags": sorted(set(flags)), "kg_eligible": not flags})
    coverage_ids = [c["unit_id"] for c in value["coverage"]]
    coverage = {"missing_units": sorted(set(units) - set(coverage_ids)),
                "unknown_units": sorted(set(coverage_ids) - set(units)),
                "duplicate_units": sorted(k for k, n in Counter(coverage_ids).items() if n > 1),
                "dispositions": dict(Counter(c["disposition"] for c in value["coverage"]))}
    return rules, provs, {"rules": audits, "coverage": coverage}


def prepare(layout, out):
    packets = source_packets(layout)
    requests = {doc: request_for(packet) for doc, packet in packets.items()}
    manifest = {"version": VERSION, "requested_model": MODEL, "documents": sorted(packets),
                "prompt_sha256": digest((PROMPTS / "sol_v1.txt").read_bytes()),
                "example_sha256": digest((PROMPTS / "sol_example_v1.json").read_bytes()),
                "schema_sha256": digest(json_bytes(SCHEMA)),
                "request_sha256": {doc: digest(json_bytes(req)) for doc, req in requests.items()},
                "input_sha256": {p.name: digest(p.read_bytes()) for p in
                                 [layout.doc_manifest, layout.chunks_jsonl, layout.pages_jsonl, layout.tables_jsonl]},
                "answer_key_supplied": False, "seed_reference_supplied": False}
    freeze(out / "extraction_manifest.json", json_bytes(manifest))
    for doc, request in requests.items():
        freeze(out / "requests" / f"{doc}.json", json_bytes(request))
    return packets, requests, manifest


def run(preprocessed=None, out=None, dry_run=False, documents=None, client=None):
    layout = PreprocessedLayout.detect(preprocessed)
    out = Path(out or REPO_ROOT / "kg_build" / VERSION)
    packets, requests, manifest = prepare(layout, out)
    selected = sorted(packets) if documents is None else list(documents)
    if set(selected) - set(packets):
        raise ValueError("Unknown requested documents")
    if dry_run:
        return {"state": "prepared", "documents": selected,
                "request_bytes": sum(len(json_bytes(requests[d])) for d in selected),
                "api_calls": 0, "out": str(out)}
    if client is None:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / ".env", override=False)
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("Set OPENAI_API_KEY in the local .env file; no API request was made")
        from openai import OpenAI
        client = OpenAI(max_retries=0, timeout=180.0)
    for doc in selected:
        response_path = out / "responses" / f"{doc}.json"
        receipt_path = out / "responses" / f"{doc}.receipt.json"
        attempt = out / "responses" / f"{doc}.attempt.json"
        if not response_path.exists():
            if attempt.exists():
                raise RuntimeError(f"Unresolved previous API attempt for {doc}; inspect before retrying")
            freeze(attempt, json_bytes({"started_at": now(), "request_sha256": manifest["request_sha256"][doc]}))
            try:
                response = client.responses.create(**requests[doc])
            except Exception as exc:
                # Exception messages may contain request credentials; log only type and code.
                freeze(out / "responses" / f"{doc}.error.json", json_bytes({"type": type(exc).__name__,
                       "http_code": getattr(exc, "status_code", None), "ended_at": now()}))
                raise RuntimeError(f"API failed for {doc}: {type(exc).__name__}; inspect local error record") from None
            raw = response.model_dump(mode="json")
            freeze(response_path, json_bytes(raw))
            freeze(receipt_path, json_bytes({"response_sha256": digest(response_path.read_bytes()),
                   "request_sha256": manifest["request_sha256"][doc], "received_at": now()}))
        raw = json.loads(response_path.read_text())
        receipt = json.loads(receipt_path.read_text())
        if receipt["response_sha256"] != digest(response_path.read_bytes()) or receipt["request_sha256"] != manifest["request_sha256"][doc]:
            raise ValueError("Response receipt mismatch")
        parse_response(raw)
        print(f"{doc}: response saved and schema validated", flush=True)
    complete = all((out / "responses" / f"{d}.json").exists() for d in packets)
    if not complete:
        return {"state": "partial", "out": str(out), "note": "Resume in same directory; cached responses are not called again"}
    all_rules, all_provs, audit, usage = [], [], {}, {}
    for doc, packet in packets.items():
        raw = json.loads((out / "responses" / f"{doc}.json").read_text())
        receipt = json.loads((out / "responses" / f"{doc}.receipt.json").read_text())
        if receipt["response_sha256"] != digest(json_bytes(raw)) or receipt["request_sha256"] != manifest["request_sha256"][doc]:
            raise ValueError("Response receipt mismatch during finalization")
        rules, provs, report = normalize(parse_response(raw), packet)
        all_rules.extend(rules); all_provs.extend(provs); audit[doc] = report
        usage[doc] = raw.get("usage", {})
    def jsonl(rows):
        return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows).encode()
    freeze(out / "predictions.jsonl", jsonl(all_rules))
    freeze(out / "validation.json", json_bytes(audit))
    freeze(out / "rules_extracted.jsonl", jsonl([r for r in all_rules if r["kg_eligible"]]))
    stations, sensors, rels = build_station_sensor(layout)
    from imaks_kg.kg_build.structure_completion import document_flows
    flows, flow_provs = document_flows(layout, {n["id"] for n in stations})
    rels.extend(flows)
    all_provs.extend(flow_provs)
    freeze(out / "provenance.jsonl", jsonl(all_provs))
    freeze(out / "nodes.jsonl", jsonl(stations + sensors))
    freeze(out / "relationships.jsonl", jsonl(rels))
    freeze(out / "documents.jsonl", jsonl(build_documents(layout)))
    summary = {**manifest, "state": "complete", "actual_models": [MODEL], "usage": usage,
               "response_times_utc": {doc: json.loads((out / "responses" / f"{doc}.receipt.json").read_text())["received_at"] for doc in packets},
               "prediction_sha256": digest((out / "predictions.jsonl").read_bytes()),
               "by_document": dict(Counter(r["document_id"] for r in all_rules)),
               "by_class": dict(Counter(r["class"] for r in all_rules)),
               "prediction_count": len(all_rules), "kg_eligible_count": sum(r["kg_eligible"] for r in all_rules),
                "human_review": "pending", "answer_exposure_history": "Prior development evaluation and team report review; not an independent holdout"}
    freeze(out / "extraction_summary.json", json_bytes(summary))
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--preprocessed")
    p.add_argument("--out")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--documents", nargs="+")
    a = p.parse_args(argv)
    result = run(a.preprocessed, a.out, a.dry_run, a.documents)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
