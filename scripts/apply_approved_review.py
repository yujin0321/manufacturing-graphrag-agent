"""Apply a user-approved, immutable proposal through the existing review API.

This helper does not choose decisions, read reference rules, or approve itself.
The operator must first obtain explicit approval for the proposal hash.
"""
import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
from imaks_kg.extract import review, to_rdf


def write_rows(path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--approved-sha256", required=True)
    parser.add_argument("--approval-note", required=True)
    args = parser.parse_args()
    digest = hashlib.sha256(args.proposal.read_bytes()).hexdigest()
    if digest != args.approved_sha256:
        raise ValueError("Proposal differs from the user-approved hash")
    proposal = json.loads(args.proposal.read_text(encoding="utf-8"))
    rows = review.read_round1(args.run_dir)
    decisions = proposal["decisions"]
    if {r["item_id"] for r in rows} != set(decisions):
        raise ValueError("Proposal must cover every candidate and conflict")
    for row in rows:
        item = decisions[row["item_id"]]
        row["decision"] = item["decision"]
        row["edited_fields"] = json.dumps(item.get("edited_fields", {}), ensure_ascii=False) if item.get("edited_fields") else ""
        row["comment"] = item["reason"] + "; " + args.approval_note
    write_rows(args.run_dir / "review_round1.csv", review.ROUND1_FIELDS, rows)
    rows2 = review.make_round2(args.run_dir)
    for row in rows2:
        item = decisions[row["item_id"]]
        row["final_decision"] = item.get("final_decision", "accept")
        row["final_edited_fields"] = ""
        row["final_comment"] = "Final state included in the same approved proposal. " + args.approval_note
    write_rows(args.run_dir / "review_round2.csv", review.ROUND2_FIELDS, rows2)
    result = review.apply_review(args.run_dir)
    rdf = to_rdf.run(args.run_dir)
    print(json.dumps({"proposal_sha256": digest, "review_result": result,
                      "outputs": {k: str(v) for k, v in rdf["outs"].items()}}, default=str, ensure_ascii=False))


if __name__ == "__main__":
    main()
