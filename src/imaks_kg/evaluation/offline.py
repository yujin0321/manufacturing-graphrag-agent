"""Diagnostic ID and lexical evaluation; NOT the SBERT F1_content metric."""
import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

TOKEN = re.compile(r"\d+(?:\.\d+)?|[^\W\d_]+", re.UNICODE)


def tokens(text):
    return Counter(TOKEN.findall(text.lower()))


def dice(a, b):
    a, b = tokens(a), tokens(b)
    total = sum(a.values()) + sum(b.values())
    return 2 * sum((a & b).values()) / total if total else 0.0


def hungarian_max(scores):
    """Maximum-weight full assignment, with zero dummy rows/columns.

    Returns real row/column pairs. Threshold filtering is applied afterwards.
    """
    nr = len(scores)
    nc = len(scores[0]) if nr else 0
    if not nr or not nc:
        return []
    if any(len(row) != nc for row in scores):
        raise ValueError("Ragged score matrix")
    n = max(nr, nc)
    cost = [[-scores[i][j] if i < nr and j < nc else 0.0 for j in range(n)] for i in range(n)]
    u, v, p, way = [0.0] * (n + 1), [0.0] * (n + 1), [0] * (n + 1), [0] * (n + 1)
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minv, used = [float("inf")] * (n + 1), [False] * (n + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], float("inf"), 0
            for j in range(1, n + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    return sorted((p[j] - 1, j - 1) for j in range(1, n + 1) if 0 < p[j] <= nr and j <= nc)


def prf(matches, npred, ngold):
    precision = matches / npred if npred else 0.0
    recall = matches / ngold if ngold else 0.0
    return {"matched": matches, "predictions": npred, "gold": ngold,
            "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0}


def evaluate(pred_path, gold_path, lineage_path, policy_path, output, threshold=0.6):
    output = Path(output)
    if output.exists():
        raise FileExistsError("Evaluation output must be new")
    if threshold != 0.6:
        raise ValueError("This frozen diagnostic protocol uses threshold 0.6")
    preds = [json.loads(x) for x in Path(pred_path).read_text(encoding="utf-8-sig").splitlines() if x.strip()]
    with Path(gold_path).open(encoding="utf-8-sig", newline="") as f:
        gold = list(csv.DictReader(f))
    lineage = {x["identifier"]: x for x in json.loads(Path(lineage_path).read_text(encoding="utf-8-sig"))}
    for values, key in ((preds, "identifier"), (gold, "ruleId")):
        if len({x[key] for x in values}) != len(values):
            raise ValueError("Duplicate evaluation identifiers")
    doc_ids = {p["unit_id"].split(":")[0] for p in preds}
    if any(g["source"] not in doc_ids for g in gold):
        raise ValueError("Gold source cannot be aligned to a document")
    assignments, accepted, by_doc = [], [], {}
    for doc in sorted(doc_ids):
        pp = [p for p in preds if p["unit_id"].split(":")[0] == doc]
        gg = [g for g in gold if g["source"] == doc]
        scores = [[dice(g["condition"] + " " + g["action"], p["conditionText"] + " " + p["responseText"]) for p in pp] for g in gg]
        pairs = hungarian_max(scores)
        for i, j in pairs:
            g, p = gg[i], pp[j]
            row = {"document_id": doc, "gold_id": g["ruleId"], "prediction_id": p["identifier"],
                   "score": scores[i][j], "accepted": scores[i][j] >= threshold,
                   "gold_class": g["class"], "prediction_class": p["ruleClass"],
                   "gold_text": g["condition"] + " " + g["action"],
                   "prediction_text": p["conditionText"] + " " + p["responseText"]}
            assignments.append(row)
            if row["accepted"]:
                accepted.append(row)
        by_doc[doc] = prf(sum(scores[i][j] >= threshold for i, j in pairs), len(pp), len(gg))
    matched_pred = {a["prediction_id"] for a in accepted}
    matched_gold = {a["gold_id"] for a in accepted}
    id_rows = []
    for g in gold:
        same_doc = [p for p in preds if p["unit_id"].split(":")[0] == g["source"]]
        exact = [p["identifier"] for p in same_doc if p["identifier"] == g["ruleId"]]
        original = [p["identifier"] for p in same_doc if lineage.get(p["identifier"], {}).get("source_rule_id") == g["ruleId"]]
        id_rows.append({"gold_id": g["ruleId"], "document_id": g["source"],
                        "exact_prediction_ids": exact, "source_lineage_prediction_ids": original})
    confusion = Counter((a["gold_class"], a["prediction_class"]) for a in accepted)
    per_class = {}
    for cls in sorted({g["class"] for g in gold} | {p["ruleClass"] for p in preds}):
        tp = sum(a["gold_class"] == cls and a["prediction_class"] == cls for a in accepted)
        per_class[cls] = prf(tp, sum(p["ruleClass"] == cls for p in preds), sum(g["class"] == cls for g in gold))
    hashes = {label: hashlib.sha256(Path(path).read_bytes()).hexdigest() for label, path in
              [("predictions", pred_path), ("ground_truth_original", gold_path), ("lineage", lineage_path), ("policy", policy_path)]}
    summary = {"status": "DIAGNOSTIC_COMPLETE_PRIMARY_METRIC_UNAVAILABLE",
               "F1_content": None,
               "primary_metric_unavailable_reason": "sentence_transformers and local all-MiniLM-L6-v2 model unavailable; no download permitted",
               "method": "F1_lexical_proxy: Unicode word/number multiset Dice + per-document Hungarian 1:1, then >=0.6",
               "F1_lexical_proxy": prf(len(accepted), len(preds), len(gold)),
               "threshold": threshold, "by_document": by_doc,
               "class_aware_diagnostic": per_class,
               "matched_class_confusion": [{"gold_class": k[0], "prediction_class": k[1], "count": v} for k, v in sorted(confusion.items())],
               "id_diagnostic": {"exact_gold_ids": sum(bool(r["exact_prediction_ids"]) for r in id_rows),
                                 "source_lineage_gold_ids": sum(bool(r["source_lineage_prediction_ids"]) for r in id_rows),
                                 "gold_total": len(gold), "is_content_score": False},
               "unmatched_predictions": len(preds) - len(matched_pred),
               "unmatched_gold": len(gold) - len(matched_gold), "hashes": hashes,
               "human_review_completed": False, "api_extraction_result": False,
               "limitations": ["Not SBERT F1_content or semantic correctness",
                               "1:1 assignment penalizes split atomic rules and extra source-supported rules",
                               "Korean/English mixed prediction text differs lexically from English gold",
                               "Token metric does not verify signs, inequalities, negation or numeric meaning",
                               "Gold may add actions not in the cited source; no prediction repair was performed"]}
    output.mkdir(parents=True)
    for name, value in [("metrics.json", summary), ("assignments.json", assignments),
                        ("id_diagnostic.json", id_rows),
                        ("unmatched_predictions.json", [p for p in preds if p["identifier"] not in matched_pred]),
                        ("unmatched_gold.json", [g for g in gold if g["ruleId"] not in matched_gold])]:
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("predictions", "gold", "lineage", "policy", "output"):
        parser.add_argument("--" + key, required=True, type=Path)
    a = parser.parse_args()
    print(json.dumps(evaluate(a.predictions, a.gold, a.lineage, a.policy, a.output), ensure_ascii=True))


if __name__ == "__main__":
    main()
