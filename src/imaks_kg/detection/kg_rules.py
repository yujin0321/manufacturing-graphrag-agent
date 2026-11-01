"""Rule detector v2: executable conditions are compiled *from the KG*.

v1 (rules.py) hard-codes 30 thresholds that a person transcribed from the
SOPs. They are correct (all 30 match the source), but the KG is then only
used for provenance links. v2 reads each rule's ``conditionText``,
``appliesToSensor`` and the sensor's ``nominal`` from the KG, compiles it with
a small deterministic grammar, and *uses v1's reviewed table as a test oracle*
(tests/test_detector_kg.py): any disagreement fails the build.

Other changes vs v1
* No train/validation/test reset. Nothing is learned, so the split only
  broke persistence windows that cross midnight. Splits are a reporting
  label only.
* SOP-002 warning/critical bands are executed from the KG ThresholdRule nodes
  (not from the sensor-metadata CSV), and the two are cross-checked.

No gold labels, no API calls. Rules the grammar cannot express (DRIFT slopes,
operator-command preconditions, correlation instructions) are listed as
unsupported with a reason - never guessed.
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from rdflib import RDF, URIRef

from imaks_kg.rag import comparison as c
from imaks_kg.rag import vector as v
from imaks_kg.rag.linking import canonical_id

from . import rules as v1

OUT = v.REPO_ROOT / "kg_build/rule_detector_v2"
SAMPLE_SECONDS = 30
_NUM = r"(-?\d+(?:\.\d+)?)"


# ------------------------------------------------------------------ grammar
def parse_condition(text: str) -> dict:
    """Return {'op','value','second','duration_seconds','relative_to_nominal'}
    or {'unsupported': reason}. Deliberately small and strict."""
    t = " ".join(text.split())
    low = t.lower()

    if "without an operator command" in low:
        return {"unsupported": "precondition 'no operator command' is not observable in sensor data"}
    if "triggers a warning" in low or "correlat" in low or "increases with" in low:
        return {"unsupported": "monitoring/correlation instruction, not a threshold condition"}
    drift_absolute = re.search(rf"drifts above {_NUM}", low)
    if "drift" in low and not drift_absolute:
        return {"unsupported": "DRIFT slope/baseline is not specified operationally"}

    duration = 0
    m = re.search(r"(?:sustained|for) >\s*(\d+) min", low)
    if m:
        duration = int(m.group(1)) * 60
        # Remove the duration phrase so ">15 min" is never read as a threshold.
        low = low[: m.start()] + low[m.end():]

    m = re.search(r"stuck(?: for)? >\s*(\d+) (?:consecutive )?samples", low)
    if m:
        return {"op": "stuck_exact", "value": str(int(m.group(1)) + 1), "second": None,
                "duration_seconds": 0, "relative_to_nominal": False}

    m = re.search(rf"increases? >\s*{_NUM} a above nominal", low)
    if m:
        return {"op": "gt", "value": m.group(1), "second": None, "duration_seconds": duration,
                "relative_to_nominal": True}

    m = re.search(rf"between {_NUM}\s*(?:°c|l/min|n|%rh)? and {_NUM}", low)
    if m:
        return {"op": "outside", "value": m.group(1), "second": m.group(2), "duration_seconds": duration,
                "relative_to_nominal": False}

    if drift_absolute:  # "HUM drifts above 65%RH": v1 reviewed decision = absolute threshold
        return {"op": "gt", "value": drift_absolute.group(1), "second": None, "duration_seconds": duration,
                "relative_to_nominal": False, "note": "drift wording executed as absolute threshold (v1 decision)"}

    for pattern in (rf"must not exceed {_NUM}", rf"exceeds {_NUM}", rf"is above {_NUM}", rf"> ?{_NUM}"):
        m = re.search(pattern, low)
        if m:
            return {"op": "gt", "value": m.group(1), "second": None, "duration_seconds": duration,
                    "relative_to_nominal": False}
    for pattern in (rf"drops below {_NUM}", rf"is below {_NUM}", rf"< ?{_NUM}"):
        m = re.search(pattern, low)
        if m:
            return {"op": "lt", "value": m.group(1), "second": None, "duration_seconds": duration,
                    "relative_to_nominal": False}
    return {"unsupported": "condition text not covered by the grammar"}


def _sensor_info(graph, sensor) -> dict:
    """Nominal is not on the sensor node; it lives on the SOP-002 ThresholdRule
    that ``appliesToSensor`` the same sensor. This is a KG join, not a lookup
    table: operational rule -> sensor <- threshold rule."""
    nominal = None
    for rule in graph.subjects(c.IM.appliesToSensor, sensor):
        if (rule, RDF.type, c.IM.ThresholdRule) in graph and graph.value(rule, c.IM.nominal) is not None:
            nominal = graph.value(rule, c.IM.nominal)
    return {"sensor_id": str(graph.value(sensor, c.IM.identifier)),
            "unit": str(graph.value(sensor, c.IM.unit)),
            "nominal": nominal}


def compile_rules(graph) -> tuple[list[dict], list[dict]]:
    """Operational + maintenance rules from conditionText; SOP-002 bands from
    structured ThresholdRule properties."""
    executable, unsupported = [], []
    for cls in (c.IM.OperationalRule, c.IM.MaintenanceRule):
        for node in sorted(graph.subjects(RDF.type, cls), key=str):
            sensor = graph.value(node, c.IM.appliesToSensor)
            condition = graph.value(node, c.IM.conditionText)
            identifier = str(graph.value(node, c.IM.identifier))
            if sensor is None or condition is None:
                continue  # datasheet notes / seed duplicates without conditionText
            parsed = parse_condition(str(condition))
            base = {"kg_node": str(node), "rule_id": canonical_id(identifier),
                    "condition_text": str(condition), **_sensor_info(graph, sensor)}
            if "unsupported" in parsed:
                unsupported.append({**base, "reason": parsed["unsupported"]})
                continue
            value = Decimal(parsed["value"])
            if parsed["relative_to_nominal"]:
                if base["nominal"] is None:
                    unsupported.append({**base, "reason": "sensor nominal missing in KG"})
                    continue
                value += Decimal(str(base["nominal"]))
            rule = {**base, "kind": "kg_document_rule", "op": parsed["op"], "value": str(value),
                    "second": parsed["second"], "duration_seconds": parsed["duration_seconds"]}
            if parsed.get("note"):
                rule["note"] = parsed["note"]
            rule.pop("nominal")
            executable.append(rule)

    for node in sorted(graph.subjects(RDF.type, c.IM.ThresholdRule), key=str):
        sensor = graph.value(node, c.IM.appliesToSensor)
        if sensor is None:
            continue  # anomaly-type definitions
        info = _sensor_info(graph, sensor)
        info.pop("nominal")
        values = {k: graph.value(node, c.IM[k]) for k in ("warnLo", "warnHi", "critLo", "critHi")}
        identifier = canonical_id(str(graph.value(node, c.IM.identifier)))
        for level, lo, hi in (("warning", "warnLo", "warnHi"), ("critical", "critLo", "critHi")):
            executable.append({"kg_node": str(node), "rule_id": f"{identifier}:{level}", **info,
                               "kind": f"kg_threshold_{level}", "op": "outside", "value": str(values[lo]),
                               "second": str(values[hi]), "duration_seconds": 0,
                               "condition_text": f"value < {lo} or value > {hi} (SOP-002 via KG)"})
    return executable, unsupported


# ------------------------------------------------------------------ execution
def scan(rows: list[dict], rule: dict) -> list[dict]:
    """Forward-only. A gap between samples resets persistence; day/split
    boundaries do not. Boundaries follow the source wording (">" is strict)."""
    events: list[dict] = []
    current = None
    start = None
    last_ts = None
    last_value = None
    same = 0
    limit = Decimal(rule["value"])
    second = Decimal(rule["second"]) if rule.get("second") not in (None, "None") else None
    for row in rows:
        ts = datetime.fromisoformat(row["timestamp"])
        value = Decimal(row["value"])
        if row["unit"] != rule["unit"] or not value.is_finite():
            raise ValueError("Unit mismatch or non-finite observation")
        contiguous = last_ts is not None and (ts - last_ts).total_seconds() == SAMPLE_SECONDS
        if not contiguous:
            start, same = None, 0
            if current:
                events.append(current)
                current = None
        same = same + 1 if contiguous and value == last_value else 1

        op = rule["op"]
        if op == "gt":
            condition = value > limit
        elif op == "lt":
            condition = value < limit
        elif op == "outside":
            condition = value < limit or value > second
        elif op == "stuck_exact":
            condition = same >= int(limit)
        else:
            raise ValueError(f"Unknown op {op}")

        start = (start or ts) if condition else None
        hit = condition and (rule["duration_seconds"] == 0
                             or (ts - start).total_seconds() > rule["duration_seconds"])
        if hit:
            if current is None:
                condition_start = start if rule["duration_seconds"] else (
                    ts - timedelta(seconds=(same - 1) * SAMPLE_SECONDS) if op == "stuck_exact" else ts)
                current = {"sensor_id": row["sensor_id"], "rule_id": rule["rule_id"], "kind": rule["kind"],
                           "trigger_at": row["timestamp"], "condition_start": condition_start.isoformat(),
                           "trigger_value": str(value), "unit": row["unit"], "positive_samples": 0,
                           "report_split": v1.split(row["timestamp"])}
            current["last_positive_at"] = row["timestamp"]
            current["positive_samples"] += 1
        elif current:
            events.append(current)
            current = None
        last_ts, last_value = ts, value
    if current:
        events.append(current)
    return events


def threshold_consistency(graph, thresholds: dict) -> list[dict]:
    """KG (SOP-002 extraction) vs sensor metadata CSV. Differences are
    reported, never silently reconciled."""
    diffs = []
    pairs = {"warnLo": "warnLo", "warnHi": "warnHi", "critLo": "critLo", "critHi": "critHi"}
    for node in graph.subjects(RDF.type, c.IM.ThresholdRule):
        sensor = graph.value(node, c.IM.appliesToSensor)
        if sensor is None:
            continue
        sid = str(graph.value(sensor, c.IM.identifier))
        for kg_key, csv_key in pairs.items():
            kg = Decimal(str(graph.value(node, c.IM[kg_key])))
            meta = Decimal(thresholds[sid][csv_key])
            if kg != meta:
                diffs.append({"sensor_id": sid, "field": kg_key, "kg_sop002": str(kg), "metadata_csv": str(meta)})
    return diffs


def run(out: Path = OUT) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    groups, thresholds, _ = v1.read_inputs()
    graph = c.load_graph()
    rules, unsupported = compile_rules(graph)
    v.write(out / "rules.json", {"rules": rules, "unsupported": unsupported,
                                 "policy": {"split_reset": False, "gap_reset": True,
                                            "duration": "strict elapsed seconds > limit"}})
    events = []
    for rule in rules:
        events.extend(scan(groups[rule["sensor_id"]], rule))
    events.sort(key=lambda e: (e["trigger_at"], e["sensor_id"], e["rule_id"]))
    for e in events:
        e["id"] = "det2-" + v.digest(v.encoded(e))[:20]
    v.write(out / "events.json", events)
    summary = {"executable_rules": len(rules), "unsupported_rules": len(unsupported), "events": len(events),
               "events_by_kind": {k: sum(e["kind"] == k for e in events) for k in sorted({r["kind"] for r in rules})},
               "kg_vs_metadata_threshold_diffs": threshold_consistency(graph, thresholds),
               "kg_sha256": v.digest((v.REPO_ROOT / c.KG_REL).read_bytes()),
               "detector_sha256": v.digest(Path(__file__).read_bytes()), "gold_loaded": False, "api_calls": 0}
    v.write(out / "summary.json", summary)
    v.write(out / "complete.json", {p.name: v.digest(p.read_bytes()) for p in sorted(out.iterdir()) if p.is_file()})
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT)
    import json
    print(json.dumps(run(parser.parse_args().out), ensure_ascii=False, indent=2))
