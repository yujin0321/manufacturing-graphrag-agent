"""Event-level evaluation of a *sealed* detector output (v1 or v2).

v1 reported row-level P/R for the metadata-threshold check only, which says
nothing about the 43 document-rule detections or about how early an anomaly
is caught. This script answers the questions a plant engineer asks:

* Of the labelled anomaly events, how many did each rule family catch?
* How many minutes after the anomaly began was the first alarm?
* How many alarms fired outside any labelled anomaly (false alarms)?
* Which anomaly types (SPIKE/DRIFT/STUCK/OUT_OF_RANGE/CORRELATED) are missed?

Gold events = maximal runs of consecutive non-NORMAL labels per sensor in
``evaluation/row_labels.csv``. Labels are read only here, after the detector
output hash is verified.

  python scripts/evaluate_detector_events.py --run kg_build/rule_detector_v2
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from imaks_kg.rag import vector as v  # noqa: E402

LABELS = "evaluation/row_labels.csv"


def gold_events(path: Path) -> list[dict]:
    by_sensor = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            by_sensor[row["sensor_id"]].append(row)
    events = []
    for sensor, rows in by_sensor.items():
        rows.sort(key=lambda r: r["timestamp"])
        current = None
        for row in rows:
            ts = datetime.fromisoformat(row["timestamp"])
            positive = row["anomaly_label"] != "NORMAL"
            continues = current and positive and row["anomaly_label"] == current["label"] and \
                (ts - current["_last"]).total_seconds() == 30
            if continues:
                current["_last"] = ts
                current["rows"] += 1
                continue
            if current:
                events.append(current)
                current = None
            if positive:
                current = {"sensor_id": sensor, "label": row["anomaly_label"], "severity": row["severity"],
                           "_start": ts, "_last": ts, "rows": 1}
        if current:
            events.append(current)
    for e in events:
        e["start"], e["end"] = e.pop("_start").isoformat(), e.pop("_last").isoformat()
    return sorted(events, key=lambda e: (e["start"], e["sensor_id"]))


def overlaps(det: dict, gold: dict, grace: timedelta) -> bool:
    if det["sensor_id"] != gold["sensor_id"]:
        return False
    d0 = datetime.fromisoformat(det["trigger_at"])
    d1 = datetime.fromisoformat(det["last_positive_at"])
    g0 = datetime.fromisoformat(gold["start"])
    g1 = datetime.fromisoformat(gold["end"]) + grace
    return d0 <= g1 and d1 >= g0


def evaluate(detections: list[dict], gold: list[dict], grace_minutes: int) -> dict:
    grace = timedelta(minutes=grace_minutes)
    families = sorted({d["kind"] for d in detections})
    report = {}
    for family in families + ["ALL"]:
        dets = [d for d in detections if family == "ALL" or d["kind"] == family]
        caught, latencies, by_type = 0, [], defaultdict(lambda: [0, 0])
        per_event = []
        for g in gold:
            hits = [d for d in dets if overlaps(d, g, grace)]
            by_type[g["label"]][1] += 1
            if hits:
                caught += 1
                by_type[g["label"]][0] += 1
                first = min(datetime.fromisoformat(d["trigger_at"]) for d in hits)
                latency = (first - datetime.fromisoformat(g["start"])).total_seconds() / 60
                latencies.append(latency)
                per_event.append({**g, "caught": True, "first_alarm": first.isoformat(),
                                  "latency_min": latency, "rules": sorted({d["rule_id"] for d in hits})})
            else:
                per_event.append({**g, "caught": False})
        false_alarms = [d for d in dets if not any(overlaps(d, g, grace) for g in gold)]
        report[family] = {
            "detections": len(dets), "gold_events": len(gold), "events_caught": caught,
            "event_recall": caught / len(gold) if gold else 0.0,
            "alarm_precision": (len(dets) - len(false_alarms)) / len(dets) if dets else 0.0,
            "false_alarms": len(false_alarms),
            "median_latency_min": sorted(latencies)[len(latencies) // 2] if latencies else None,
            "recall_by_type": {k: f"{a}/{b}" for k, (a, b) in sorted(by_type.items())},
            "events": per_event}
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--grace-minutes", type=int, default=0,
                   help="alarms up to N minutes after the labelled end still count (default 0)")
    a = p.parse_args()
    seal = v.read(a.run / "complete.json")
    for name, digest in seal.items():
        if v.digest((a.run / name).read_bytes()) != digest:
            raise ValueError(f"Detector output changed after sealing: {name}")
    profile = v.read(v.REPO_ROOT / "preprocessed/sensors/profile.json")
    labels = v.REPO_ROOT / LABELS
    if v.digest(labels.read_bytes()) != profile["output_sha256"][LABELS]:
        raise ValueError("Labels changed")
    gold = gold_events(labels)
    report = evaluate(v.read(a.run / "events.json"), gold, a.grace_minutes)
    out = v.REPO_ROOT / "evaluation" / f"detector_events_{a.run.name}"
    out.mkdir(parents=True, exist_ok=True)
    v.write(out / "event_metrics.json", {"run": str(a.run), "grace_minutes": a.grace_minutes,
                                         "detector_seal_sha256": v.digest((a.run / "complete.json").read_bytes()),
                                         "report": report})
    for family, r in report.items():
        print(f"{family:24} caught {r['events_caught']}/{r['gold_events']}  precision {r['alarm_precision']:.2f} "
              f"false_alarms {r['false_alarms']}  median_latency {r['median_latency_min']}  {r['recall_by_type']}")
    print(json.dumps([{k: e[k] for k in ("sensor_id", "label", "start", "end", "caught")} |
                      ({"latency_min": e["latency_min"], "rules": e["rules"]} if e["caught"] else {})
                      for e in report["ALL"]["events"]], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
