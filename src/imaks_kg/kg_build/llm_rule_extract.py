"""LLM-based rule extraction from preprocessed document chunks."""
import argparse
import json
import os
import re
from pathlib import Path

from imaks_kg.common.io_utils import write_json, write_jsonl
from imaks_kg.kg_build.document_nodes import load_chunks
from imaks_kg.kg_build.preprocessed_abox import PreprocessedLayout
from imaks_kg.kg_build.rule_schema import RuleRecord, validate_rule
from imaks_kg.settings import REPO_ROOT, rel


SYSTEM_PROMPT = """You extract manufacturing KG rules from preprocessed source chunks.
Return only a JSON array. Use this exact object shape:
{
  "ruleId": "RULE-...",
  "class": "OperationalRule|ThresholdRule|MaintenanceRule|AccessRule",
  "station": "",
  "sensor": "",
  "sensorType": "",
  "condition": "",
  "action": "",
  "ruleSeverity": "",
  "critHi": "",
  "warnHi": "",
  "critLo": "",
  "warnLo": "",
  "unit": "",
  "source": "SOP-...",
  "sourceDocument": "SOP-...",
  "provenanceId": "prov:<chunk_id>",
  "extractionMethod": "llm"
}
Use only the provided chunks. Do not use evaluation labels or seed KG files."""


def chunk_payload(layout: PreprocessedLayout, max_chars_per_chunk=1800):
    items = []
    for c in load_chunks(layout):
        text = c.get("text", "")
        if not text.strip():
            continue
        items.append({
            "sourceDocument": c.get("document_id") or c.get("doc_id", ""),
            "provenanceId": f"prov:{c['chunk_id']}",
            "page": c.get("page", ""),
            "kind": c.get("kind", ""),
            "section": c.get("section", ""),
            "text": text[:max_chars_per_chunk],
        })
    return items


def prompt_for(items):
    return json.dumps({"chunks": items}, ensure_ascii=False)


def extract_json_array(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", text, flags=re.S)
        if not m:
            raise
        value = json.loads(m.group(0))
    if not isinstance(value, list):
        raise ValueError("LLM response must be a JSON array")
    return value


def call_openai(model, user_prompt):
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install dependencies first: python3 -m pip install -r requirements.txt") from exc
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for LLM extraction")

    client = OpenAI()
    if hasattr(client, "responses"):
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.output_text

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
    )
    return response.choices[0].message.content


def normalize_records(records):
    out = []
    seen = set()
    for row in records:
        row = dict(row)
        row["extractionMethod"] = "llm"
        rule = validate_rule(RuleRecord.from_dict(row))
        if rule.ruleId in seen:
            continue
        seen.add(rule.ruleId)
        out.append(rule.to_dict())
    return out


def extract(preprocessed_root=None, model=None, response_text=None):
    layout = PreprocessedLayout.detect(preprocessed_root)
    if response_text is None:
        chosen = model or os.environ.get("OPENAI_MODEL")
        if not chosen:
            raise RuntimeError("Set --model or OPENAI_MODEL before running LLM extraction")
        response_text = call_openai(chosen, prompt_for(chunk_payload(layout)))
    return normalize_records(extract_json_array(response_text))


def build(preprocessed_root=None, out_dir=None, model=None, response_text=None):
    layout = PreprocessedLayout.detect(preprocessed_root)
    out = Path(out_dir or (REPO_ROOT / "kg_build" / "latest"))
    records = extract(layout.root, model=model, response_text=response_text)
    write_jsonl(out / "rules_llm_extracted.jsonl", records)
    by_class = {}
    for r in records:
        by_class[r["class"]] = by_class.get(r["class"], 0) + 1
    write_json(out / "llm_rule_extract_summary.json", {
        "rule_count": len(records),
        "by_class": by_class,
        "preprocessed_root": rel(layout.root) if layout.root.is_relative_to(REPO_ROOT) else str(layout.root),
        "extraction_method": "llm",
        "evaluation_labels_used_for_extraction": False,
        "seed_reference_used_for_extraction": False,
    })
    return {"rules": records, "out_dir": out}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--preprocessed", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--response-json", default=None, help="Optional saved LLM response for repeatable local runs.")
    args = parser.parse_args(argv)
    response_text = Path(args.response_json).read_text(encoding="utf-8") if args.response_json else None
    result = build(args.preprocessed, args.out, args.model, response_text)
    print(f"extracted {len(result['rules'])} LLM rules")
    print(f"output: {result['out_dir']}")


if __name__ == "__main__":
    main()
