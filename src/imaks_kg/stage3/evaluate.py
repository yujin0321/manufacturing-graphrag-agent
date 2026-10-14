"""Post-extraction evaluation only. Only evaluation/diagnostic modules read GT; build and extraction do not."""
import argparse
from collections import Counter
from pathlib import Path
import re

import numpy as np
from scipy.optimize import linear_sum_assignment

from .common import CLASSES, REPO_ROOT, digest, read_csv, read_jsonl, write_json


def match(similarities, eligible, threshold=0.6):
    """Maximize valid match count, then similarity; allow both sides to remain unmatched."""
    similarities = np.asarray(similarities, dtype=float)
    eligible = np.asarray(eligible, dtype=bool)
    if similarities.ndim != 2 or similarities.shape != eligible.shape:
        raise ValueError("Invalid similarity/eligibility shapes")
    if not np.isfinite(similarities).all() or not 0 <= threshold <= 1:
        raise ValueError("Invalid similarity/threshold")
    n, m = similarities.shape
    if not n or not m:
        return []
    # Dummy rows/columns enable unmatched predictions/references. Invalid pairs gain zero.
    benefit = np.zeros((n + m, n + m))
    valid = eligible & (similarities >= threshold)
    benefit[:n, :m] = np.where(valid, min(n, m) + 1 + similarities, 0)
    rr, cc = linear_sum_assignment(-benefit)
    return [(int(i), int(j), float(similarities[i, j])) for i, j in zip(rr, cc)
            if i < n and j < m and valid[i, j]]


def metrics(tp, predicted, actual):
    precision = tp / predicted if predicted else 0.0
    recall = tp / actual if actual else 0.0
    return {"tp": tp, "fp": predicted - tp, "fn": actual - tp, "predicted": predicted,
            "reference": actual, "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0}


def numeric_signature(text):
    # An audit signal only, not an exact numeric correctness metric.
    return sorted(re.findall(r"(?<![A-Za-z_])(?:>=|<=|>|<|≥|≤)?\s*-?\d+(?:\.\d+)?", text))


def evaluate(predictions, output, threshold=0.6, revision=None):
    from sentence_transformers import SentenceTransformer
    from huggingface_hub import snapshot_download
    if output.exists():
        raise ValueError("Evaluation output already exists; use a new run path")
    manifest_path = predictions.parent / "manifest.json"
    import json
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["predictions_sha256"] != digest(predictions.read_bytes()):
        raise ValueError("Frozen predictions were modified")
    raw = read_jsonl(predictions)
    sop_ids = {"SOP-001", "SOP-002", "SOP-003", "SOP-004"}
    pred = [r for r in raw if r["doc_id"] in sop_ids]
    gt_path = REPO_ROOT / "imaks_data/kg_seed/ground_truth.csv"
    gt = read_csv(gt_path)
    if len(gt) != 86 or any(r["class"] not in CLASSES for r in gt):
        raise ValueError("Unexpected reference version")
    model_id = "sentence-transformers/all-MiniLM-L6-v2"
    snapshot = snapshot_download(model_id, revision=revision,
                                 allow_patterns=["*.json", "*.safetensors", "vocab.txt", "tokenizer.*", "*.txt"])
    model = SentenceTransformer(snapshot, device="cpu", trust_remote_code=False)
    def text(r):
        return "Condition: " + r["condition"] + "\nAction: " + r["action"]
    texts = [text(r) for r in pred + gt]
    embeddings = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    sim = embeddings[:len(pred)] @ embeddings[len(pred):].T
    eligible = np.array([[p["doc_id"] == g["source"] for g in gt] for p in pred], dtype=bool).reshape(len(pred), len(gt))
    pairs = match(sim, eligible, threshold)
    paired_p, paired_g = {p for p, _, _ in pairs}, {g for _, g, _ in pairs}
    details = []
    for p, g, score in pairs:
        a, b = pred[p], gt[g]
        details.append({"prediction_id": a["prediction_id"], "reference_id": b["ruleId"], "similarity": score,
                        "class_correct": a["class"] == b["class"],
                        "sensor_correct": set(a["sensors"]) == ({b["sensor"]} if b["sensor"] else set()),
                        "severity_correct": a["severity"].casefold() == b["severity"].casefold(),
                        "numeric_review_needed": numeric_signature(text(a)) != numeric_signature(text(b)),
                        "prediction": a, "reference": b})
    by_class = {}
    for cls in CLASSES:
        tp = sum(pred[p]["class"] == gt[g]["class"] == cls for p, g, _ in pairs)
        by_class[cls] = metrics(tp, sum(r["class"] == cls for r in pred), sum(r["class"] == cls for r in gt))
    completed_sop = sorted(set(manifest.get("completed_documents", {r["doc_id"] for r in pred})) & sop_ids)
    scoped_gt = [g for g in gt if g["source"] in completed_sop]
    scope_by_class = {}
    for cls in CLASSES:
        tp = sum(pred[p]["class"] == gt[g]["class"] == cls for p, g, _ in pairs)
        scope_by_class[cls] = metrics(tp, sum(r["class"] == cls for r in pred), sum(r["class"] == cls for r in scoped_gt))
    result = {"status": "evaluated", "protocol": {"embedding_model": model_id,
        "resolved_revision": Path(snapshot).name, "threshold": threshold, "matching": "Hungarian; max valid count then similarity",
        "eligibility": "same source document; class scored separately", "text": "Condition + Action",
        "human_corrected": manifest["human_corrected"], "interpretation": "development result, not held-out generalization"},
        "prediction_sha256": digest(predictions.read_bytes()), "reference_sha256": digest(gt_path.read_bytes()),
        "content": metrics(len(pairs), len(pred), len(gt)), "by_class": by_class,
        "partial_extraction": manifest.get("partial", False),
        "completed_sop_documents": completed_sop,
        "unprocessed_sop_documents": sorted(sop_ids - set(completed_sop)),
        "processed_document_scope": metrics(len(pairs), len(pred), len(scoped_gt)),
        "processed_scope_by_class": scope_by_class,
        "class_aware_content": metrics(sum(m["class_correct"] for m in details), len(pred), len(gt)),
        "class_aware_processed_scope": metrics(sum(m["class_correct"] for m in details), len(pred), len(scoped_gt)),
        "unprocessed_reference_count": len(gt) - len(scoped_gt),
        "interpretation_full_reference": "Missing-document references count as FN in pipeline coverage; do not attribute them to extraction errors on processed documents",
        "class_confusion": dict(Counter(pred[p]["class"] + " -> " + gt[g]["class"] for p, g, _ in pairs)),
        "datasheet_predictions_excluded": len(raw) - len(pred), "matches": details,
        "unmatched_predictions": [r for i, r in enumerate(pred) if i not in paired_p],
        "unmatched_references": [r for i, r in enumerate(gt) if i not in paired_g]}
    write_json(output, result)
    print(result["content"])


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--predictions", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--threshold", type=float, default=0.6)
    p.add_argument("--revision")
    a = p.parse_args()
    evaluate(a.predictions, a.output, a.threshold, a.revision)
