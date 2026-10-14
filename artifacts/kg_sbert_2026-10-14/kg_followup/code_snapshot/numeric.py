"""Supplementary source-vs-gold numeric audit, not a semantic F1 metric."""
import argparse
import csv
import json
from pathlib import Path


def compare(predictions, gold):
    rows = []
    for p in predictions:
        if not p.get("numeric"):
            continue
        candidates = [g for g in gold if g["source"] == p["unit_id"].split(":")[0]
                      and p["sensorIds"] and g["sensor"] == p["sensorIds"][0]
                      and g["class"] == "ThresholdRule"]
        if len(candidates) != 1:
            raise ValueError("Ambiguous threshold comparison")
        g = candidates[0]
        differences = {k: {"prediction": p["numeric"][k], "gold": float(g[k])}
                       for k in ("critLo", "warnLo", "warnHi", "critHi")
                       if p["numeric"][k] != float(g[k])}
        rows.append({"prediction_id": p["identifier"], "gold_id": g["ruleId"],
                     "sensor": p["sensorIds"][0], "unit_id": p["unit_id"],
                     "sourceQuote": p["sourceQuote"],
                     "all_four_limits_match": not differences, "differences": differences})
    return {"status": "supplementary_posthoc_diagnostic", "not_primary_metric": True,
            "policy": "Align source document and first threshold-bearing sensor; compare four limits exactly; no prediction edits",
            "rows": rows, "sensors_compared": len(rows),
            "all_four_match": sum(r["all_four_limits_match"] for r in rows),
            "numeric_fields_compared": 4 * len(rows),
            "numeric_fields_match": 4 * len(rows) - sum(len(r["differences"]) for r in rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("predictions", "gold", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    a = parser.parse_args()
    predictions = [json.loads(x) for x in a.predictions.read_text(encoding="utf-8-sig").splitlines() if x.strip()]
    with a.gold.open(encoding="utf-8-sig", newline="") as f:
        gold = list(csv.DictReader(f))
    with a.output.open("x", encoding="utf-8") as f:
        json.dump(compare(predictions, gold), f, ensure_ascii=False, indent=2, allow_nan=False)


if __name__ == "__main__":
    main()
