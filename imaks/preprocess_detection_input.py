"""Create separate rule and ML inputs while preserving source cell values."""
import csv
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
THRESHOLD_COLUMNS = ("nominal", "warn_hi", "crit_hi", "warn_lo", "crit_lo")


def write_view(source, target, removed):
    with source.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        assert set(removed) <= set(reader.fieldnames)
        fields = [c for c in reader.fieldnames if c not in removed]
        rows = 0
        with target.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in reader:
                writer.writerow(row)
                rows += 1
    with source.open(encoding="utf-8", newline="") as f, target.open(encoding="utf-8", newline="") as output:
        original = csv.DictReader(f)
        cleaned = csv.DictReader(output)
        assert cleaned.fieldnames == fields
        for row in original:
            assert next(cleaned) == {c: row[c] for c in fields}
        assert next(cleaned, None) is None
    return {"file": str(target.relative_to(ROOT)), "rows": rows, "columns": fields,
            "verification": "All retained cells and row order match the source."}


def main():
    archive = ROOT / "iMAKS_dataset.zip"
    out = ROOT / "preprocessed" / "sensors"
    out.mkdir(parents=True, exist_ok=True)
    target = out / "timeseries_detection_input.csv"
    with ZipFile(archive) as z:
        source = "sensors/timeseries_raw.csv"
        with io.TextIOWrapper(z.open(source), encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            assert "quality" in reader.fieldnames
            fields = [c for c in reader.fieldnames if c != "quality"]
            count = 0
            with target.open("w", encoding="utf-8", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                for row in reader:
                    writer.writerow(row)
                    count += 1
        # Verify every remaining cell and row order against the original.
        with io.TextIOWrapper(z.open(source), encoding="utf-8-sig", newline="") as f, target.open(encoding="utf-8", newline="") as output:
            original = csv.DictReader(f)
            cleaned = csv.DictReader(output)
            assert cleaned.fieldnames == fields
            verified = 0
            for row in original:
                assert next(cleaned) == {c: row[c] for c in fields}
                verified += 1
            assert next(cleaned, None) is None
            assert verified == count
    report = {
        "source": "iMAKS_dataset.zip:sensors/timeseries_raw.csv",
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "output": str(target.relative_to(ROOT)),
        "removed_columns": ["quality"],
        "rows": count,
        "remaining_columns": fields,
        "verification": "All remaining cells and row order match the source.",
        "scope": "Only quality removal; other potential leakage fields not audited.",
    }
    (out / "quality_removal_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    views = {
        "rule_baseline": write_view(target, out / "timeseries_rule_input.csv", ()),
        "ml_detector": write_view(target, out / "timeseries_ml_input.csv", THRESHOLD_COLUMNS),
    }
    policy_report = {"threshold_columns": THRESHOLD_COLUMNS, "quality_allowed": False,
                     "rule_thresholds_allowed": True, "ml_thresholds_allowed": False,
                     "views": views, "archive_sha256": report["archive_sha256"]}
    (out / "input_policy_report.json").write_text(json.dumps(policy_report, indent=2), encoding="utf-8")
    print(json.dumps(policy_report, indent=2))


if __name__ == "__main__":
    main()
