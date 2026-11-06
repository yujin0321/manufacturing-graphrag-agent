"""Rule detector v3: SOP-002 anomaly-type criteria, MAINT drift rules,
cross-station correlation and incident grouping. Everything is compiled from
KG text; v1/v2 code and outputs are untouched.

Detection layer (adds alarms on top of the unchanged v2 alarms)
* SOP-002 type definitions (ThresholdRule nodes without ``appliesToSensor``)
  are applied to every sensor:
    DRIFT        slope > k*sigma/min for N+ readings (OLS over the stated window)
    STUCK        std(last N) < f * |nominal|
    OUT_OF_RANGE outside the WARN band for N+ readings
  SPIKE's detection criterion ("single reading > CRIT") is the v2 critical
  band, so it adds no new alarm; its "<5 min" bound is used for typing only.
* MAINT drift rules: "drift >X over W" = change of the 10-sample mean over W;
  "drift >X for W+" = |value - nominal| > X sustained for at least W.
* RULE-ST04-03 is run on its observable part (SPD < 1.00) and flagged
  ``precondition_unobserved`` because operator commands are not in the data.

Revision before evaluation (unlabeled evidence): the literal slope criterion
fired ~3,000 times on normal autocorrelated noise, so by default slope hits are
*supporting signals* that inform incident type and onset but never raise an
alarm. ``--slope-as-alarm`` reproduces the literal design.

Post-processing layer (no new alarms)
* Alarms of one sensor whose times overlap or are <= GAP apart form one incident.
* Each incident gets one SOP-002 type by a fixed priority, and a severity.
* CORRELATED: KG rules that name a cause sensor and an effect sensor
  (RULE-ST02-04, SOP-003 pattern) link an effect incident whose onset is within
  the SOP-002 CORRELATED window (90 min) after a cause incident.

sigma is not defined in the SOPs. It is fixed per sensor as a robust spread
(1.4826 * MAD) of *train-period values only*. No labels are read.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from rdflib import RDF

from imaks_kg.rag import comparison as c
from imaks_kg.rag import vector as v
from imaks_kg.rag.linking import canonical_id

from . import kg_rules as k2
from . import rules as v1

OUT = v.REPO_ROOT / "kg_build/rule_detector_v3"
SAMPLE_SECONDS = 30
TRAIN_END = "2026-01-07"          # v1.split: train = timestamps before this date
SMOOTH_SAMPLES = 10               # mean width for MAINT "over W" change (= SOP-002 STUCK window)
INCIDENT_GAP_MIN = 10             # same-sensor alarms <= 10 min apart are one incident
TYPE_PRIORITY = ["STUCK", "SPIKE", "DRIFT", "OUT_OF_RANGE"]
QUANTITY = {"speed": "SPD", "current": "CUR", "temperature": "TMP", "humidity": "HUM", "pressure": "PRS",
            "vibration": "VIB", "tension": "TEN", "flow": "FLW", "count": "CNT"}
_NUM = r"(-?\d+(?:\.\d+)?)"
THRESHOLD_KINDS = {"kg_document_rule", "kg_document_rule_partial", "kg_threshold_warning",
                   "kg_threshold_critical", "sop002_out_of_range"}
DRIFT_KINDS = {"sop002_drift_slope", "kg_maint_drift"}


# ------------------------------------------------------------------ KG compile
def type_definitions(graph) -> dict:
    """Parse the five SOP-002 anomaly-type definitions into parameters."""
    defs = {}
    for node in graph.subjects(RDF.type, c.IM.ThresholdRule):
        if graph.value(node, c.IM.appliesToSensor) is not None:
            continue
        name = str(graph.value(node, c.IM.responseText) or "")
        text = " ".join(str(graph.value(node, c.IM.conditionText) or "").split())
        base = {"kg_node": str(node), "rule_id": canonical_id(str(graph.value(node, c.IM.identifier))),
                "condition_text": text}
        if name == "DRIFT":
            m = re.search(rf"slope >{_NUM}σ/min for (\d+)\+ readings", text)
            w = re.search(r"deviation >(\d+) min", text)
            defs[name] = {**base, "sigma_per_min": float(m.group(1)), "readings": int(m.group(2)),
                          "window_min": int(w.group(1))}
        elif name == "STUCK":
            m = re.search(rf"std\(last (\d+)\)<{_NUM}×nominal", text)
            defs[name] = {**base, "window": int(m.group(1)), "nominal_fraction": float(m.group(2))}
        elif name == "OUT_OF_RANGE":
            m = re.search(r">WARN for (\d+)\+ readings", text)
            defs[name] = {**base, "readings": int(m.group(1))}
        elif name == "SPIKE":
            m = re.search(r"<(\d+) min", text)
            defs[name] = {**base, "max_minutes": int(m.group(1))}
        elif name == "CORRELATED":
            m = re.search(r"within (\d+) min of cause", text)
            defs[name] = {**base, "window_min": int(m.group(1))}
    missing = {"DRIFT", "STUCK", "OUT_OF_RANGE", "SPIKE", "CORRELATED"} - set(defs)
    if missing:
        raise ValueError(f"SOP-002 type definitions missing in KG: {sorted(missing)}")
    return defs


def sensor_table(graph) -> dict:
    """sensor_id -> unit, nominal, warn/crit band (SOP-002 ThresholdRule via KG)."""
    table = {}
    for node in graph.subjects(RDF.type, c.IM.ThresholdRule):
        sensor = graph.value(node, c.IM.appliesToSensor)
        if sensor is None:
            continue
        sid = str(graph.value(sensor, c.IM.identifier))
        table[sid] = {"unit": str(graph.value(sensor, c.IM.unit)), "threshold_node": str(node),
                      **{key: float(graph.value(node, c.IM[key]))
                         for key in ("nominal", "warnLo", "warnHi", "critLo", "critHi")}}
    return table


def parse_maint_drift(text: str) -> dict | None:
    low = " ".join(text.split()).lower()
    m = re.search(rf"drift >{_NUM}\s*[^\s\d]*\s+over (\d+) (min|h)\b", low)
    if m:
        minutes = int(m.group(2)) * (60 if m.group(3) == "h" else 1)
        return {"mode": "window_change", "delta": float(m.group(1)), "window_min": minutes}
    m = re.search(rf"drift >{_NUM}\s*[^\s\d]*\s+for (\d+)\+ min", low)
    if m:
        return {"mode": "sustained_from_nominal", "delta": float(m.group(1)), "min_minutes": int(m.group(2))}
    return None


def parse_partial(text: str) -> dict | None:
    low = " ".join(text.split()).lower()
    m = re.search(rf"drops below {_NUM} \S+ without an operator command", low)
    if m:
        return {"op": "lt", "value": float(m.group(1)),
                "flag": "precondition_unobserved: operator command history is not in sensor data"}
    return None


def parse_correlation(text: str, cause_sensor: str, sensors: set[str]) -> str | None:
    """Return the effect sensor named in a correlation rule, or None."""
    low = " ".join(text.split())
    if not re.search(r"correlat|increases with", low, re.I):
        return None
    cause_station = cause_sensor.rsplit("_", 1)[0]
    for station, word in re.findall(r"\b([A-Z]{2,3}\d{2}_[A-Z]+) (\w+)", low):
        code = QUANTITY.get(word.lower())
        sid = f"{station}_{code}" if code else None
        if station != cause_station and sid in sensors:
            return sid
    return None


def compile_v3(graph) -> dict:
    """Additional executable items, plus what stays unsupported (with reason)."""
    v2_rules, v2_unsupported = k2.compile_rules(graph)
    defs = type_definitions(graph)
    sensors = sensor_table(graph)
    maint, partial, pairs, unsupported = [], [], {}, []
    for item in v2_unsupported:
        sid, text = item["sensor_id"], item["condition_text"]
        base = {"kg_node": item["kg_node"], "rule_id": item["rule_id"], "sensor_id": sid,
                "unit": item["unit"], "condition_text": text}
        drift = parse_maint_drift(text)
        part = parse_partial(text)
        effect = parse_correlation(text, sid, set(sensors))
        if drift:
            maint.append({**base, **drift, "kind": "kg_maint_drift"})
        elif part:
            partial.append({**base, **part, "kind": "kg_document_rule_partial"})
        elif effect:
            pair = pairs.setdefault((sid, effect), {"cause_sensor": sid, "effect_sensor": effect,
                                                    "rule_ids": [], "kg_nodes": []})
            pair["rule_ids"].append(item["rule_id"])
            pair["kg_nodes"].append(item["kg_node"])
        else:
            unsupported.append({**base, "reason": item["reason"] + "; v3: no observable sensor pair/condition"})
    for pair in pairs.values():
        pair["window_min"] = defs["CORRELATED"]["window_min"]
        pair["window_rule_id"] = defs["CORRELATED"]["rule_id"]
    return {"v2_rules": v2_rules, "type_definitions": defs, "sensors": sensors, "maint_drift": maint,
            "partial": partial, "correlation_pairs": sorted(pairs.values(), key=lambda p: p["cause_sensor"]),
            "unsupported": unsupported}


# ------------------------------------------------------------------ sigma (train values only)
def train_sigma(rows: list[dict]) -> dict:
    x = np.array([float(r["value"]) for r in rows if r["timestamp"] < TRAIN_END])
    mad = float(np.median(np.abs(x - np.median(x))))
    sigma, method = 1.4826 * mad, "1.4826*MAD"
    if sigma == 0:
        sigma, method = float(np.std(x)), "std (MAD=0)"
    return {"sigma": sigma, "method": method, "train_samples": int(x.size)}


# ------------------------------------------------------------------ execution helpers
def _arrays(rows):
    ts = [datetime.fromisoformat(r["timestamp"]) for r in rows]
    x = np.array([float(r["value"]) for r in rows])
    seg = np.zeros(len(rows), dtype=int)  # contiguous segment id (gap resets)
    for i in range(1, len(rows)):
        seg[i] = seg[i - 1] + ((ts[i] - ts[i - 1]).total_seconds() != SAMPLE_SECONDS)
    return ts, x, seg


def _window_ok(seg, i, n):
    """True if samples i-n+1..i exist and belong to one contiguous segment."""
    return i - n + 1 >= 0 and seg[i - n + 1] == seg[i]


def runs(rows, cond, min_count, rule, extra=None, start_offset=None):
    """Alarm segments where ``cond`` is true for >= min_count consecutive
    contiguous readings. Trigger = the min_count-th reading (forward-only)."""
    ts, x, seg = rows["_arrays"]
    events, current, count = [], None, 0
    for i in range(len(ts)):
        if i and seg[i] != seg[i - 1]:
            count = 0
            if current:
                events.append(current)
                current = None
        count = count + 1 if cond[i] else 0
        if count >= min_count:
            if current is None:
                first = i - count + 1
                cstart = ts[first] - (start_offset[first] if start_offset is not None else timedelta(0))
                current = {"sensor_id": rule["sensor_id"], "rule_id": rule["rule_id"], "kind": rule["kind"],
                           "trigger_at": ts[i].isoformat(), "condition_start": cstart.isoformat(),
                           "trigger_value": repr(float(x[i])), "unit": rule["unit"], "positive_samples": 0,
                           "report_split": v1.split(ts[i].isoformat()), **(extra or {})}
            current["last_positive_at"] = ts[i].isoformat()
            current["positive_samples"] += 1
        elif current:
            events.append(current)
            current = None
    if current:
        events.append(current)
    return events


def slope_condition(x, seg, window, sigma, nominal, k):
    """OLS slope (units/min) over the last ``window`` samples, deviating away
    from nominal: |slope| > k*sigma and sign(fitted_end - nominal) == sign(slope)."""
    n = len(x)
    cond = np.zeros(n, dtype=bool)
    t = np.arange(window) * SAMPLE_SECONDS / 60.0
    tc = t - t.mean()
    denom = float((tc ** 2).sum())
    for i in range(window - 1, n):
        if not _window_ok(seg, i, window):
            continue
        y = x[i - window + 1:i + 1]
        slope = float((tc * (y - y.mean())).sum() / denom)
        fitted_end = y.mean() + slope * tc[-1]
        cond[i] = abs(slope) > k * sigma and np.sign(fitted_end - nominal) == np.sign(slope)
    return cond


def stuck_condition(x, seg, window, limit):
    cond = np.zeros(len(x), dtype=bool)
    for i in range(window - 1, len(x)):
        if _window_ok(seg, i, window):
            cond[i] = float(np.std(x[i - window + 1:i + 1])) < limit
    return cond


def window_change_condition(x, seg, window_samples, delta):
    """|mean(last SMOOTH) - mean(SMOOTH ending window_samples earlier)| > delta."""
    cond = np.zeros(len(x), dtype=bool)
    need = window_samples + SMOOTH_SAMPLES
    for i in range(need - 1, len(x)):
        if not _window_ok(seg, i, need):
            continue
        now = x[i - SMOOTH_SAMPLES + 1:i + 1].mean()
        j = i - window_samples
        before = x[j - SMOOTH_SAMPLES + 1:j + 1].mean()
        cond[i] = abs(now - before) > delta
    return cond


def detect_new(groups: dict, compiled: dict, sigmas: dict) -> list[dict]:
    defs, sensors = compiled["type_definitions"], compiled["sensors"]
    alarms = []
    for sid, raw_rows in groups.items():
        ts, x, seg = _arrays(raw_rows)
        rows = {"_arrays": (ts, x, seg)}
        info, sigma = sensors[sid], sigmas[sid]["sigma"]
        unit = info["unit"]
        d = defs["DRIFT"]
        window = d["window_min"] * 60 // SAMPLE_SECONDS
        if sigma > 0:
            cond = slope_condition(x, seg, window, sigma, info["nominal"], d["sigma_per_min"])
            alarms += runs(rows, cond, d["readings"],
                           {"sensor_id": sid, "rule_id": d["rule_id"] + ":DRIFT", "kind": "sop002_drift_slope",
                            "unit": unit}, {"sigma": sigma})
        s = defs["STUCK"]
        cond = stuck_condition(x, seg, s["window"], s["nominal_fraction"] * abs(info["nominal"]))
        offset = [timedelta(seconds=(s["window"] - 1) * SAMPLE_SECONDS)] * len(x)
        alarms += runs(rows, cond, 1, {"sensor_id": sid, "rule_id": s["rule_id"] + ":STUCK",
                                       "kind": "sop002_stuck_std", "unit": unit}, start_offset=offset)
        o = defs["OUT_OF_RANGE"]
        cond = (x < info["warnLo"]) | (x > info["warnHi"])
        alarms += runs(rows, cond, o["readings"], {"sensor_id": sid, "rule_id": o["rule_id"] + ":OUT_OF_RANGE",
                                                   "kind": "sop002_out_of_range", "unit": unit})
        for m in (r for r in compiled["maint_drift"] if r["sensor_id"] == sid):
            if m["mode"] == "window_change":
                cond = window_change_condition(x, seg, m["window_min"] * 60 // SAMPLE_SECONDS, m["delta"])
                alarms += runs(rows, cond, 1, m)
            else:  # "for W+ min": inclusive, so W/30s + 1 readings span W minutes
                cond = np.abs(x - info["nominal"]) > m["delta"]
                alarms += runs(rows, cond, m["min_minutes"] * 60 // SAMPLE_SECONDS + 1, m)
        for p in (r for r in compiled["partial"] if r["sensor_id"] == sid):
            cond = x < p["value"] if p["op"] == "lt" else x > p["value"]
            alarms += runs(rows, cond, 1, p, {"flag": p["flag"]})
    for a in alarms:
        for key in ("mode", "delta", "window_min", "min_minutes", "op", "value", "condition_text", "kg_node"):
            a.pop(key, None)
    return alarms


# ------------------------------------------------------------------ post-processing
def group_incidents(alarms: list[dict], defs: dict, gap_min: int = INCIDENT_GAP_MIN,
                    signals: list[dict] = ()) -> list[dict]:
    """Group alarms into incidents. ``signals`` (slope hits when not used as
    alarms) never create an incident; they only inform type and onset."""
    gap = timedelta(minutes=gap_min)
    by_sensor = {}
    for a in sorted(alarms, key=lambda a: (a["sensor_id"], a["trigger_at"])):
        by_sensor.setdefault(a["sensor_id"], []).append(a)
    incidents = []
    for sid, items in by_sensor.items():
        current = None
        for a in items:
            t0 = datetime.fromisoformat(a["trigger_at"])
            if current and t0 <= current["_end"] + gap:
                current["alarms"].append(a)
                current["_end"] = max(current["_end"], datetime.fromisoformat(a["last_positive_at"]))
                continue
            if current:
                incidents.append(current)
            current = {"sensor_id": sid, "alarms": [a], "_end": datetime.fromisoformat(a["last_positive_at"])}
        if current:
            incidents.append(current)
    signals_by_sensor = {}
    for s in signals:
        signals_by_sensor.setdefault(s["sensor_id"], []).append(s)
    out = []
    for inc in incidents:
        alarms_ = inc["alarms"]
        kinds = {a["kind"] for a in alarms_}
        start = min(a["trigger_at"] for a in alarms_)
        # A slope signal supports this incident if it is active up to (gap before) its start or during it.
        t_start = datetime.fromisoformat(start)
        attached = [s for s in signals_by_sensor.get(inc["sensor_id"], [])
                    if datetime.fromisoformat(s["trigger_at"]) <= inc["_end"]
                    and datetime.fromisoformat(s["last_positive_at"]) >= t_start - gap]
        anomaly_type, reason = classify(alarms_ + attached, defs)
        severity = ("CRITICAL" if "kg_threshold_critical" in kinds else
                    "WARNING" if kinds & {"kg_threshold_warning", "sop002_out_of_range"} else "ADVISORY")
        record = {"sensor_id": inc["sensor_id"], "station_id": inc["sensor_id"].rsplit("_", 1)[0],
                  "start": start, "end": inc["_end"].isoformat(),
                  "onset_estimate": min(a["condition_start"] for a in alarms_ + attached),
                  "supporting_signal_ids": sorted(s["id"] for s in attached),
                  "anomaly_type": anomaly_type, "type_reason": reason, "severity": severity,
                  "alarm_ids": sorted(a["id"] for a in alarms_), "rule_ids": sorted({a["rule_id"] for a in alarms_}),
                  "kinds": sorted(kinds), "report_split": v1.split(start),
                  "flags": sorted({a["flag"] for a in alarms_ if a.get("flag")})}
        record["id"] = "inc3-" + v.digest(v.encoded(record))[:20]
        out.append(record)
    return sorted(out, key=lambda r: (r["start"], r["sensor_id"]))


def classify(alarms: list[dict], defs: dict) -> tuple[str, str]:
    """Fixed priority STUCK > SPIKE > DRIFT > OUT_OF_RANGE > UNCLASSIFIED."""
    kinds = {a["kind"] for a in alarms}
    if "sop002_stuck_std" in kinds or any(a["rule_id"].startswith(("RULE-ST03-03", "MAINT-03")) for a in alarms):
        return "STUCK", "stuck criterion alarm in incident"
    value_alarms = [a for a in alarms if a["kind"] in THRESHOLD_KINDS]
    if "kg_threshold_critical" in kinds and value_alarms:
        span = (max(datetime.fromisoformat(a["last_positive_at"]) for a in value_alarms)
                - min(datetime.fromisoformat(a["trigger_at"]) for a in value_alarms))
        if span < timedelta(minutes=defs["SPIKE"]["max_minutes"]):
            return "SPIKE", f"critical band crossed; threshold span {span} < {defs['SPIKE']['max_minutes']} min"
    drift = [a for a in alarms if a["kind"] in DRIFT_KINDS]
    if drift:
        first_drift = min(a["trigger_at"] for a in drift)
        first_value = min((a["trigger_at"] for a in value_alarms), default=None)
        if first_value is None or first_drift < first_value or "sop002_out_of_range" not in kinds:
            return "DRIFT", "drift alarm precedes threshold alarms" if first_value else "drift alarm only"
    if "sop002_out_of_range" in kinds:
        return "OUT_OF_RANGE", "WARN band violated for the SOP-002 reading count"
    return "UNCLASSIFIED", "threshold rule match without an SOP-002 type criterion"


def link_correlations(incidents: list[dict], pairs: list[dict]) -> list[dict]:
    links = []
    for pair in pairs:
        window = timedelta(minutes=pair["window_min"])
        causes = [i for i in incidents if i["sensor_id"] == pair["cause_sensor"]]
        for effect in (i for i in incidents if i["sensor_id"] == pair["effect_sensor"]):
            t = datetime.fromisoformat(effect["start"])
            cands = [ci for ci in causes if t - window <= datetime.fromisoformat(ci["start"]) <= t]
            if not cands:
                continue
            cause = max(cands, key=lambda ci: ci["start"])  # most recent preceding cause
            lag = (t - datetime.fromisoformat(cause["start"])).total_seconds() / 60
            effect["pre_correlation_type"] = effect["anomaly_type"]
            effect["anomaly_type"] = "CORRELATED"
            effect["type_reason"] = f"onset {lag:.1f} min after {cause['sensor_id']} incident ({', '.join(pair['rule_ids'])})"
            effect["correlated_with"] = cause["id"]
            links.append({"cause_incident": cause["id"], "effect_incident": effect["id"],
                          "cause_sensor": pair["cause_sensor"], "effect_sensor": pair["effect_sensor"],
                          "lag_min": lag, "evidence_rule_ids": pair["rule_ids"] + [pair["window_rule_id"]],
                          "evidence_kg_nodes": pair["kg_nodes"], "hasEvidence": "SOPRule",
                          "status": "rule_pattern_match_not_confirmed_causality"})
    return links


# ------------------------------------------------------------------ run
def run(out: Path = OUT, slope_as_alarm: bool = False) -> dict:
    """slope_as_alarm=True reproduces the literal pre-registered design
    (SOP-002 slope hits as alarms); default treats them as supporting signals."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    groups, thresholds, _ = v1.read_inputs()
    graph = c.load_graph()
    compiled = compile_v3(graph)
    sigmas = {sid: train_sigma(rows) for sid, rows in groups.items()}
    params = {"sigma_by_sensor": sigmas, "sigma_source": f"sensor values with timestamp < {TRAIN_END}; no labels",
              "smooth_samples": SMOOTH_SAMPLES, "incident_gap_min": INCIDENT_GAP_MIN,
              "type_priority": TYPE_PRIORITY + ["UNCLASSIFIED"], "correlation_overrides_type": True,
              "slope_as_alarm": slope_as_alarm}
    v.write(out / "params.json", params)
    v.write(out / "rules.json", {k: compiled[k] for k in ("v2_rules", "type_definitions", "maint_drift", "partial",
                                                            "correlation_pairs", "unsupported")})
    alarms = []
    for rule in compiled["v2_rules"]:
        alarms.extend(k2.scan(groups[rule["sensor_id"]], rule))
    alarms.extend(detect_new(groups, compiled, sigmas))
    alarms.sort(key=lambda e: (e["trigger_at"], e["sensor_id"], e["rule_id"]))
    for a in alarms:
        a["id"] = "det3-" + v.digest(v.encoded(a))[:20]
    signals = []
    if not slope_as_alarm:
        signals = [a for a in alarms if a["kind"] == "sop002_drift_slope"]
        alarms = [a for a in alarms if a["kind"] != "sop002_drift_slope"]
    incidents = group_incidents(alarms, compiled["type_definitions"], signals=signals)
    links = link_correlations(incidents, compiled["correlation_pairs"])
    v.write(out / "events.json", alarms)          # alarm-level, same schema family as v2
    v.write(out / "signals.json", signals)
    v.write(out / "incidents.json", incidents)
    v.write(out / "correlations.json", links)
    summary = {"alarms": len(alarms), "slope_signals": len(signals), "slope_as_alarm": slope_as_alarm,
               "incidents": len(incidents), "correlation_links": len(links),
               "alarms_by_kind": {kd: sum(a["kind"] == kd for a in alarms) for kd in sorted({a["kind"] for a in alarms})},
               "incidents_by_type": {t: sum(i["anomaly_type"] == t for i in incidents)
                                     for t in sorted({i["anomaly_type"] for i in incidents})},
               "unsupported": [u["rule_id"] for u in compiled["unsupported"]],
               "kg_vs_metadata_threshold_diffs": k2.threshold_consistency(graph, thresholds),
               "kg_sha256": v.digest((v.REPO_ROOT / c.KG_REL).read_bytes()),
               "detector_sha256": v.digest(Path(__file__).read_bytes()),
               "gold_loaded": False, "api_calls": 0, "training": "none; sigma from train-period values only"}
    v.write(out / "summary.json", summary)
    v.write(out / "complete.json", {p.name: v.digest(p.read_bytes()) for p in sorted(out.iterdir()) if p.is_file()})
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--slope-as-alarm", action="store_true",
                        help="literal SOP-002 slope criterion as alarms (pre-registered v3 design)")
    a = parser.parse_args()
    print(json.dumps(run(a.out, a.slope_as_alarm), ensure_ascii=False, indent=2))
