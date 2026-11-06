"""Rule detector v3.1: post-hoc fixes on top of v3 (v3 file and output untouched).

Written *after* v3 was evaluated, so results are not a blind evaluation.
Both changes follow SOP wording; no new numeric parameter is introduced.

1. MAINT "drift >X over W": the change must also move *away from nominal*
   (|now - nominal| > |before - nominal|). v3 counted recoveries as drift.
2. RULE-ST02-04 "Monitor ST04 SPD whenever ST02 CUR triggers a WARNING":
   a cause incident containing an SOP-002 warning alarm opens a monitoring
   window of the SOP-002 CORRELATED length (90 min). Effect-sensor slope
   signals that start inside it, in the direction the rule names
   ("reduction" = below nominal), are raised to alarms. Outside the window,
   slope hits stay supporting signals as in v3.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from rdflib import URIRef

from imaks_kg.rag import comparison as c
from imaks_kg.rag import vector as v

from . import kg_rules as k2
from . import kg_rules_v3 as k3
from . import rules as v1

OUT = v.REPO_ROOT / "kg_build/rule_detector_v3_1"


def window_change_away_condition(x, seg, window_samples, delta, nominal):
    """|now - before| > delta and now is farther from nominal than before."""
    cond = np.zeros(len(x), dtype=bool)
    need = window_samples + k3.SMOOTH_SAMPLES
    for i in range(need - 1, len(x)):
        if not k3._window_ok(seg, i, need):
            continue
        now = x[i - k3.SMOOTH_SAMPLES + 1:i + 1].mean()
        j = i - window_samples
        before = x[j - k3.SMOOTH_SAMPLES + 1:j + 1].mean()
        cond[i] = abs(now - before) > delta and abs(now - nominal) > abs(before - nominal)
    return cond


def effect_direction(text: str) -> str | None:
    low = text.lower()
    if re.search(r"reduction|decreas|drop", low):
        return "below_nominal"
    if re.search(r"increas|rise|rising", low):
        return "above_nominal"
    return None


def pair_directions(graph, pairs: list[dict]) -> list[dict]:
    """Effect direction from the pair's own KG rule texts; all must agree."""
    out = []
    for p in pairs:
        dirs = {effect_direction(str(graph.value(URIRef(n), c.IM.conditionText) or "")) for n in p["kg_nodes"]}
        dirs.discard(None)
        out.append({**p, "effect_direction": dirs.pop() if len(dirs) == 1 else None})
    return out


def detect_new_v31(groups, compiled, sigmas):
    """v3 new alarms, with MAINT window-change rules replaced by the
    away-from-nominal version."""
    window_rules = [m for m in compiled["maint_drift"] if m["mode"] == "window_change"]
    rest = {**compiled, "maint_drift": [m for m in compiled["maint_drift"] if m["mode"] != "window_change"]}
    alarms = k3.detect_new(groups, rest, sigmas)
    for m in window_rules:
        sid = m["sensor_id"]
        ts, x, seg = k3._arrays(groups[sid])
        cond = window_change_away_condition(x, seg, m["window_min"] * 60 // k3.SAMPLE_SECONDS, m["delta"],
                                            compiled["sensors"][sid]["nominal"])
        found = k3.runs({"_arrays": (ts, x, seg)}, cond, 1, m, {"direction": "away_from_nominal"})
        for a in found:
            for key in ("mode", "delta", "window_min", "condition_text", "kg_node"):
                a.pop(key, None)
        alarms += found
    return alarms


def monitor_alarms(incidents, signals, pairs, sensors):
    """Promote effect-sensor slope signals that start inside a monitoring
    window opened by a cause incident with an SOP-002 warning alarm."""
    promoted, windows = [], []
    for p in pairs:
        window = timedelta(minutes=p["window_min"])
        nominal = sensors[p["effect_sensor"]]["nominal"]
        for cause in (i for i in incidents if i["sensor_id"] == p["cause_sensor"]):
            if "kg_threshold_warning" not in cause["kinds"]:
                continue
            t0 = datetime.fromisoformat(cause["start"])
            windows.append({"cause_incident": cause["id"], "effect_sensor": p["effect_sensor"],
                            "from": t0.isoformat(), "to": (t0 + window).isoformat()})
            for s in signals:
                if s["sensor_id"] != p["effect_sensor"]:
                    continue
                ts = datetime.fromisoformat(s["trigger_at"])
                value_ok = (p["effect_direction"] == "below_nominal" and float(s["trigger_value"]) < nominal) or \
                           (p["effect_direction"] == "above_nominal" and float(s["trigger_value"]) > nominal)
                if t0 <= ts <= t0 + window and value_ok:
                    a = {**{k: s[k] for k in ("sensor_id", "trigger_at", "condition_start", "trigger_value", "unit",
                                               "positive_samples", "last_positive_at", "report_split")},
                         "rule_id": p["rule_ids"][0] + ":monitor", "kind": "kg_correlation_monitor",
                         "monitored_by": cause["id"], "source_signal": s["id"]}
                    a["id"] = "det31-" + v.digest(v.encoded(a))[:20]
                    promoted.append(a)
    unique = {a["source_signal"]: a for a in promoted}  # one alarm per signal even if windows overlap
    return sorted(unique.values(), key=lambda a: a["trigger_at"]), windows


def run(out: Path = OUT) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    groups, thresholds, _ = v1.read_inputs()
    graph = c.load_graph()
    compiled = k3.compile_v3(graph)
    pairs = pair_directions(graph, compiled["correlation_pairs"])
    sigmas = {sid: k3.train_sigma(rows) for sid, rows in groups.items()}
    defs = compiled["type_definitions"]
    v.write(out / "params.json", {"sigma_by_sensor": sigmas, "smooth_samples": k3.SMOOTH_SAMPLES,
                                  "incident_gap_min": k3.INCIDENT_GAP_MIN, "slope_as_alarm": False,
                                  "maint_window_change": "away_from_nominal", "correlation_monitor": pairs,
                                  "post_hoc": "designed after v3 evaluation; not a blind evaluation"})
    alarms = []
    for rule in compiled["v2_rules"]:
        alarms.extend(k2.scan(groups[rule["sensor_id"]], rule))
    alarms.extend(detect_new_v31(groups, compiled, sigmas))
    alarms.sort(key=lambda e: (e["trigger_at"], e["sensor_id"], e["rule_id"]))
    for a in alarms:
        a["id"] = "det31-" + v.digest(v.encoded(a))[:20]
    signals = [a for a in alarms if a["kind"] == "sop002_drift_slope"]
    alarms = [a for a in alarms if a["kind"] != "sop002_drift_slope"]
    # Pass 1: incidents without monitoring, to find cause incidents.
    first = k3.group_incidents(alarms, defs, signals=signals)
    monitored, windows = monitor_alarms(first, signals, pairs, compiled["sensors"])
    used = {a["source_signal"] for a in monitored}
    alarms = sorted(alarms + monitored, key=lambda e: (e["trigger_at"], e["sensor_id"], e["rule_id"]))
    remaining = [s for s in signals if s["id"] not in used]
    # Pass 2: final incidents and correlation links.
    incidents = k3.group_incidents(alarms, defs, signals=remaining)
    links = k3.link_correlations(incidents, pairs)
    v.write(out / "events.json", alarms)
    v.write(out / "signals.json", remaining)
    v.write(out / "monitor_windows.json", windows)
    v.write(out / "incidents.json", incidents)
    v.write(out / "correlations.json", links)
    summary = {"alarms": len(alarms), "slope_signals": len(remaining), "monitor_windows": len(windows),
               "monitor_alarms": len(monitored), "incidents": len(incidents), "correlation_links": len(links),
               "alarms_by_kind": {kd: sum(a["kind"] == kd for a in alarms) for kd in sorted({a["kind"] for a in alarms})},
               "incidents_by_type": {t: sum(i["anomaly_type"] == t for i in incidents)
                                     for t in sorted({i["anomaly_type"] for i in incidents})},
               "kg_vs_metadata_threshold_diffs": k2.threshold_consistency(graph, thresholds),
               "kg_sha256": v.digest((v.REPO_ROOT / c.KG_REL).read_bytes()),
               "detector_sha256": v.digest(Path(__file__).read_bytes()),
               "v3_detector_sha256": v.digest(Path(k3.__file__).read_bytes()),
               "gold_loaded": False, "api_calls": 0, "post_hoc": True}
    v.write(out / "summary.json", summary)
    v.write(out / "complete.json", {p.name: v.digest(p.read_bytes()) for p in sorted(out.iterdir()) if p.is_file()})
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT)
    print(json.dumps(run(parser.parse_args().out), ensure_ascii=False, indent=2))
