"""Evaluate extracted rules against ground_truth.csv."""
import argparse
import csv
import json
from pathlib import Path

from imaks_kg.common.io_utils import write_csv, write_json
from imaks_kg.eval.ground_truth import load_ground_truth
from imaks_kg.eval.match_rules import max_match


def load_jsonl(path):
    with Path(path).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def summarize(predictions, truths, pairs):
    tp = len(pairs)
    precision = tp / len(predictions) if predictions else 0.0
    recall = tp / len(truths) if truths else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
    by_class = {}
    classes = sorted({r.get("class", "") for r in predictions + truths})
    pair_classes = [truths[j].get("class", "") for _, j, _ in pairs]
    for klass in classes:
        p_count = sum(1 for r in predictions if r.get("class") == klass)
        t_count = sum(1 for r in truths if r.get("class") == klass)
        c_tp = sum(1 for c in pair_classes if c == klass)
        c_p = c_tp / p_count if p_count else 0.0
        c_r = c_tp / t_count if t_count else 0.0
        by_class[klass] = {
            "predicted": p_count, "ground_truth": t_count, "matched": c_tp,
            "precision": c_p, "recall": c_r,
            "f1_content": (2 * c_p * c_r / (c_p + c_r)) if c_p + c_r else 0.0,
        }
    return {
        "predicted_count": len(predictions),
        "ground_truth_count": len(truths),
        "matched_count": tp,
        "precision": precision,
        "recall": recall,
        "f1_content": f1,
        "by_class": by_class,
    }


def evaluate(predictions, truths, threshold=0.6):
    pairs = max_match(predictions, truths, threshold)
    summary = summarize(predictions, truths, pairs)
    summary["threshold"] = threshold
    summary["matcher"] = "thresholded maximum bipartite content match"
    return summary, pairs


def write_matches(path, predictions, truths, pairs):
    rows = []
    matched_pred = {i for i, _, _ in pairs}
    matched_truth = {j for _, j, _ in pairs}
    for i, j, score in pairs:
        rows.append(["matched", f"{score:.4f}", predictions[i].get("ruleId", ""), truths[j].get("ruleId", ""),
                     predictions[i].get("class", ""), truths[j].get("class", "")])
    for i, p in enumerate(predictions):
        if i not in matched_pred:
            rows.append(["false_positive", "", p.get("ruleId", ""), "", p.get("class", ""), ""])
    for j, t in enumerate(truths):
        if j not in matched_truth:
            rows.append(["missed_ground_truth", "", "", t.get("ruleId", ""), "", t.get("class", "")])
    write_csv(path, ["status", "score", "pred_ruleId", "gt_ruleId", "pred_class", "gt_class"], rows)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--pred", required=True)
    parser.add_argument("--ground-truth", required=True)
    parser.add_argument("--out-dir", default="evaluation")
    parser.add_argument("--threshold", type=float, default=0.6)
    args = parser.parse_args(argv)

    predictions = load_jsonl(args.pred)
    truths = load_ground_truth(Path(args.ground_truth))
    summary, pairs = evaluate(predictions, truths, args.threshold)
    out_dir = Path(args.out_dir)
    write_json(out_dir / "kg_val_metrics.json", summary)
    write_matches(out_dir / "kg_val_matches.csv", predictions, truths, pairs)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
