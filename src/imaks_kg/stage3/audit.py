"""Audit input integrity, timestamp cadence and all LLM request paths."""
from collections import Counter, defaultdict
from datetime import datetime
import json
import math

from .common import DOCS, OUT, REPO_ROOT, digest, read_csv, read_jsonl, write_json


def audit():
    path = REPO_ROOT / "preprocessed/sensors/input/ts_input.csv"
    clean = read_csv(path)
    expected = ["timestamp", "zone", "station_id", "sensor_id", "sensor_type", "value", "unit"]
    if list(clean[0]) != expected:
        raise ValueError("Input header allowlist mismatch")
    raw = read_csv(REPO_ROOT / "imaks_data/sensors/timeseries_raw.csv")
    def key(r):
        return r["sensor_id"], r["timestamp"]
    raw_index = {key(r): r for r in raw}
    if len(raw_index) != len(raw) or len({key(r) for r in clean}) != len(clean):
        raise ValueError("Duplicate sensor/timestamp")
    if {key(r) for r in clean} != set(raw_index):
        raise ValueError("Raw/clean key mismatch")
    by_sensor = defaultdict(list)
    for r in clean:
        if any(r[k] != raw_index[key(r)][k] for k in expected):
            raise ValueError("Original input field changed")
        if not math.isfinite(float(r["value"])):
            raise ValueError("Nonfinite value")
        by_sensor[r["sensor_id"]].append(datetime.fromisoformat(r["timestamp"]))
    for sid, dates in by_sensor.items():
        if dates != sorted(dates) or any((z-a).total_seconds() != 30 for a, z in zip(dates, dates[1:])):
            raise ValueError("Cadence/order error: " + sid)
    requests = read_jsonl(OUT / "requests.jsonl")
    for r in requests:
        if set(r["input"]) != {"document", "catalog", "chunks", "tables"}:
            raise ValueError("Request payload allowlist mismatch")
        if set(r["input"]["catalog"]) != {"stations", "sensors"}:
            raise ValueError("Catalog allowlist mismatch")
        actual = digest(r["system"] + json.dumps(r["input"], sort_keys=True, ensure_ascii=False))
        if actual != r["request_sha256"]:
            raise ValueError("Request hash mismatch")
    inventory = {p.relative_to(REPO_ROOT / "imaks_data").as_posix(): digest(p.read_bytes())
                 for p in sorted((REPO_ROOT / "imaks_data").rglob("*")) if p.is_file()}
    baseline = json.loads((REPO_ROOT / "harness/raw_manifest.json").read_text(encoding="utf-8"))
    missing = sorted(set(baseline) - set(inventory))
    changed = [k for k in baseline.keys() & inventory.keys() if baseline[k]["sha256"] != inventory[k]]
    extra = sorted(set(inventory) - set(baseline))
    if changed or extra or any(not p.endswith("/.DS_Store") for p in missing):
        raise ValueError("Original baseline mismatch: " + str((missing, changed, extra)))
    write_json(OUT / "raw_manifest.json", inventory)
    summary = {"sensor_rows": len(clean), "sensors": len(by_sensor), "cadence_seconds": 30,
               "original_values_preserved": True, "finite_values": True, "header_allowlist": expected,
               "document_requests": len(requests), "raw_files": len(inventory),
               "original_baseline_changed": changed, "omitted_os_metadata_files": missing,
               "request_input_scope": "documents + station/sensor IDs only",
               "automatic_extraction_status": "not assessed by input audit; see frozen run manifest and evaluation"}
    write_json(OUT / "audit.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    audit()
