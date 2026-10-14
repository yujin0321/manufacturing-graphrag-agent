"""Local rule evaluation. Reference data is never imported by extraction code."""
import argparse
import csv
import hashlib
import importlib.metadata
import json
from datetime import datetime, timezone
from pathlib import Path

from rule_matching import content_text, match_matrix

CLASSES = ("OperationalRule", "ThresholdRule", "MaintenanceRule", "AccessRule")
MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_b(path):
    from rdflib import Graph, Namespace, RDF
    g = Graph().parse(str(path))
    seed = Graph().parse(str(Path(path).with_name("seed.ttl")))
    im = Namespace("https://example.org/imaks/v1#")
    def one(s, name):
        vals = list(g.objects(s, im[name]))
        if len(vals) > 1:
            raise ValueError(f"Multiple values: {s} {name}")
        return str(vals[0]) if vals else ""
    out = []
    for cls in CLASSES:
        for s in sorted(g.subjects(RDF.type, im[cls])):
            condition = one(s, "conditionText")
            sensors = sorted(str(x).rsplit("/", 1)[-1] for x in g.objects(s, im.appliesToSensor))
            if cls == "ThresholdRule" and not condition:
                props = [(k, one(s, k)) for k in ("nominalValue", "warnLo", "warnHi", "critLo", "critHi", "unit")]
                if not one(s, "unit"):
                    units = sorted({str(u) for sensor in g.objects(s, im.appliesToSensor) for u in seed.objects(sensor, im.unit)})
                    props[-1] = ("unit", "|".join(units))
                condition = "; ".join(["Sensor " + "|".join(sensors)] + [f"{k} {v}" for k, v in props if v])
            docs = [one(d, "identifier") for d in g.objects(s, im.sourceDocument)]
            out.append({"identifier": one(s, "identifier"), "class": cls,
                        "condition": condition, "response": one(s, "responseText"),
                        "doc_id": docs[0] if len(docs) == 1 else "|".join(docs),
                        "numeric_limits": {k: one(s, k) for k in ("warnLo", "warnHi", "critLo", "critHi") if one(s, k)},
                        "sensors": sensors, "origin": "B", "example_chunk": False})
    return out


def c_rule(r, examples):
    return {"identifier": r["identifier"], "class": r["class"], "condition": r["conditionText"],
            "response": r["responseText"], "doc_id": r["doc_id"], "sensors": r["sensors"],
            "chunk_id": r["chunk_id"], "candidate_id": r["candidate_id"],
            "origin": "C", "example_chunk": r["chunk_id"] in examples}


def load_reference(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows, fields = list(reader), reader.fieldnames
    # Field mappings are schema adapters, never reference-specific matching rules.
    aliases = {"identifier": ("ruleId", "gt_id", "rule_id", "id", "identifier"),
               "class": ("class", "rule_class", "rule_type"),
               "condition": ("conditionText", "condition_text", "condition", "trigger"),
               "response": ("responseText", "response_text", "response", "action"),
               "doc_id": ("doc_id", "source_document", "document_id", "document", "sourceDoc", "source")}
    chosen = {}
    for dst, names in aliases.items():
        chosen[dst] = next((x for x in names if x in fields), None)
    required = ("identifier", "class", "condition", "response")
    if any(chosen[k] is None for k in required):
        raise ValueError(f"Unmapped reference schema: {fields}; adapter={chosen}")
    result = [{k: r.get(src, "") if src else "" for k, src in chosen.items()} for r in rows]
    for item, raw in zip(result, rows):
        item["numeric_limits"] = {k: raw[k] for k in ("warnLo", "warnHi", "critLo", "critHi") if raw.get(k)}
    if len(result) != 86 or len({r["identifier"] for r in result}) != 86:
        raise ValueError("Expected exactly 86 unique reference rules")
    if any(r["class"] not in CLASSES or not content_text(r) for r in result):
        raise ValueError("Invalid reference class/content")
    return result, chosen


def evaluate(name, predictions, reference, model, output):
    import numpy as np
    ptexts, rtexts = [content_text(p) for p in predictions], [content_text(r) for r in reference]
    emb = model.encode(ptexts + rtexts, normalize_embeddings=True, show_progress_bar=False,
                       convert_to_numpy=True, batch_size=32)
    sim = emb[:len(predictions)] @ emb[len(predictions):].T
    for i, text in enumerate(ptexts):
        if not text:
            sim[i, :] = -1
    pairs, result = match_matrix(sim.tolist(), len(reference))
    matched = [p for p in pairs if p["matched"]]
    result["class_correct_among_content_matches"] = sum(
        predictions[p["prediction_index"]]["class"] == reference[p["reference_index"]]["class"] for p in matched)
    result["class_accuracy_among_content_matches"] = result["class_correct_among_content_matches"] / len(matched) if matched else 0.0
    result["by_class"] = {}
    for cls in CLASSES:
        pi = [i for i, p in enumerate(predictions) if p["class"] == cls]
        ri = [i for i, r in enumerate(reference) if r["class"] == cls]
        sub = sim[np.ix_(pi, ri)]
        result["by_class"][cls] = match_matrix(sub.tolist(), len(ri))[1]
    used_p = {p["prediction_index"] for p in matched}
    used_r = {p["reference_index"] for p in matched}
    audit = [{**p, "prediction": predictions[p["prediction_index"]], "reference": reference[p["reference_index"]]} for p in pairs]
    save_json(output / f"{name}_pairs.json", audit)
    save_json(output / f"{name}_unmatched.json", {
        "predictions": [p for i, p in enumerate(predictions) if i not in used_p],
        "reference": [r for i, r in enumerate(reference) if i not in used_r]})
    save_json(output / f"{name}_predictions.json", predictions)
    np.save(output / f"{name}_cosine.npy", sim)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--stage", choices=("prereview", "reviewed"), default="prereview")
    ap.add_argument("--model-path", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    args.out_dir.mkdir(parents=True, exist_ok=False)
    cpath = args.run_dir / ("final.jsonl" if args.stage == "reviewed" else "merged.jsonl")
    meta = json.loads((args.run_dir / "meta.json").read_text(encoding="utf-8"))
    if meta["mode"] != "execute" or meta["status"] != "completed":
        raise ValueError("Only completed real extraction can be scored")
    paths = [root / "kg_build/rules_deterministic.ttl", root / "kg_build/seed.ttl", cpath, args.run_dir / "meta.json",
             args.run_dir / "calls.jsonl", root / "src/imaks_kg/extract/prompts/v1/examples.json",
             Path(__file__), Path(__file__).with_name("rule_matching.py"),
             root / "eval/evaluation_protocol.md"]
    paths.extend(sorted((args.run_dir / "raw/response").glob("*.json")))
    paths.extend(sorted((root / "src/imaks_kg/extract").rglob("*.py")))
    paths.extend(root / p for p in ("ontology_v1/ontology.ttl", "ontology_v1/shapes.ttl", "harness/preprocess_lock.json"))
    paths.append(root / "evaluation/model_info.json")
    paths.extend(p for p in sorted(args.model_path.rglob("*")) if p.is_file())
    if args.stage == "reviewed":
        paths.extend(args.run_dir / n for n in ("review_applied.json", "review_round1.csv", "review_round2.csv"))
    hashes = {str(p.resolve().relative_to(root)): sha(p) for p in paths}
    freeze = {"frozen_at_utc": datetime.now(timezone.utc).isoformat(), "inputs": hashes,
              "stage": args.stage, "reference_not_yet_opened": True}
    save_json(args.out_dir / "freeze.json", freeze)
    b = load_b(root / "kg_build/rules_deterministic.ttl")
    examples = set(meta["example_chunk_ids"])
    cs = jsonl(cpath)
    new = [c_rule(r, examples) for r in cs if not r["merge"]["merged"]]
    all_predictions = b + new
    if len({r["identifier"] for r in all_predictions}) != len(all_predictions):
        raise ValueError("Duplicate prediction identifiers")
    # This is the first reference read. Extraction inputs are already frozen.
    reference_path = root / "imaks_data/kg_seed/ground_truth.csv"
    reference, adapter = load_reference(reference_path)
    save_json(args.out_dir / "reference.json", reference)
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(str(args.model_path), device="cpu", local_files_only=True)
    results = {"B_only": evaluate("B_only", b, reference, model, args.out_dir),
               "B_plus_C": evaluate("B_plus_C", all_predictions, reference, model, args.out_dir),
               "B_plus_C_without_example_predictions": evaluate("B_plus_C_without_example_predictions",
                   [r for r in all_predictions if not r["example_chunk"]], reference, model, args.out_dir)}
    if any(sha(root / p) != h for p, h in hashes.items()):
        raise ValueError("Input mutated during evaluation")
    summary = {"stage": args.stage, "model": MODEL, "model_snapshot": args.model_path.name,
               "embedding_max_sequence_length": model.max_seq_length,
               "threshold": 0.6, "assignment": "Hungarian maximum total cosine, then threshold",
               "reference_sha256": sha(reference_path), "reference_adapter": adapter,
               "versions": {n: importlib.metadata.version(n) for n in ("sentence-transformers", "scipy", "numpy", "torch", "transformers", "rdflib")},
               "counts": {"B": len(b), "C_records": len(cs), "C_confirmations_of_B": len(cs)-len(new),
                          "C_new": len(new), "example_predictions": sum(r["example_chunk"] for r in new)},
               "metrics": results, "inputs_unchanged": True}
    save_json(args.out_dir / "summary.json", summary)
    report = ["# First quantitative rule evaluation", "", f"Stage: {args.stage} (human review pending if prereview).",
              "", "| System | Predictions | TP | FP | FN | Precision | Recall/Coverage | F1_content |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, m in results.items():
        report.append(f"| {name} | {m['predictions']} | {m['tp']} | {m['fp']} | {m['fn']} | {m['precision']:.4f} | {m['recall']:.4f} | {m['f1_content']:.4f} |")
    report += ["", "Model: " + MODEL + "; revision: " + args.model_path.name + "; cosine threshold: 0.6.",
               "Assignment maximizes total content cosine, then applies the threshold. IDs and class labels are excluded from embeddings.",
               "B confirmations are counted once. No extraction or review was tuned against reference results.",
               "Coverage here equals matched reference rules / 86. Class metrics are in summary.json.",
               "Example-excluded score keeps the same 86 references; it is a sensitivity check, not a disjoint holdout.",
               "Semantic similarity does not establish exact numeric, timing or action correctness. Audit pairs and unmatched rows before interpreting F1.",
               "All evaluated inputs were hashed before opening reference data and rechecked after scoring."]
    (args.out_dir / "report.md").write_text("\n".join(report)+"\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
