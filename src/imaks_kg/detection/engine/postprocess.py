"""Post-processing: alarms -> incidents, SOP-002 type, severity, correlation.

Steps are separate functions (id assignment, signal split, grouping, signal
attachment, typing/severity, monitoring, correlation links) so later stages
can change one interpretation without copying the pipeline. Stage 1
reproduces legacy semantics exactly, including when IDs are computed and how
records are ordered. Typing (k3.classify) and correlation linking
(k3.link_correlations) are the legacy functions.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from imaks_kg.rag import vector as v

from .. import kg_rules_v3 as k3
from .. import rules as v1

SLOPE_KIND = "sop002_drift_slope"
SIGNAL_COPY_KEYS = ("sensor_id", "trigger_at", "condition_start", "trigger_value", "unit",
                    "positive_samples", "last_positive_at", "report_split")


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def assign_alarm_ids(alarms: list[dict], prefix: str) -> None:
    for a in alarms:
        a["id"] = prefix + v.digest(v.encoded(a))[:20]


def split_signals(alarms: list[dict], slope_mode: str) -> tuple[list[dict], list[dict]]:
    """slope_mode='signal': slope hits never raise alarms; they only support
    incident type and onset. 'alarm': literal SOP-002 design."""
    if slope_mode == "alarm":
        return alarms, []
    return ([a for a in alarms if a["kind"] != SLOPE_KIND], [a for a in alarms if a["kind"] == SLOPE_KIND])


def cluster(alarms: list[dict], gap: timedelta) -> list[dict]:
    """Same-sensor alarms whose trigger is <= gap after the running end form one cluster."""
    by_sensor: dict[str, list[dict]] = {}
    for a in sorted(alarms, key=lambda a: (a["sensor_id"], a["trigger_at"])):
        by_sensor.setdefault(a["sensor_id"], []).append(a)
    clusters = []
    for sid, items in by_sensor.items():
        current = None
        for a in items:
            if current and _dt(a["trigger_at"]) <= current["end"] + gap:
                current["alarms"].append(a)
                current["end"] = max(current["end"], _dt(a["last_positive_at"]))
                continue
            if current:
                clusters.append(current)
            current = {"sensor_id": sid, "alarms": [a], "end": _dt(a["last_positive_at"])}
        if current:
            clusters.append(current)
    return clusters


def attached_signals(c: dict, signals_by_sensor: dict, gap: timedelta) -> list[dict]:
    """A slope signal supports a cluster if active from (gap before) its start until its end."""
    t_start = _dt(min(a["trigger_at"] for a in c["alarms"]))
    return [s for s in signals_by_sensor.get(c["sensor_id"], [])
            if _dt(s["trigger_at"]) <= c["end"] and _dt(s["last_positive_at"]) >= t_start - gap]


SEVERITY_RANK = {"ADVISORY": 0, "WARNING": 1, "CRITICAL": 2}


def severity(kinds: set[str]) -> str:
    return ("CRITICAL" if "kg_threshold_critical" in kinds else
            "WARNING" if kinds & {"kg_threshold_warning", "sop002_out_of_range"} else "ADVISORY")


def incident_severity(alarms: list[dict], cfg: dict, tags: dict) -> str:
    """'sop002_bands' (legacy): SOP-002 band kinds only. 'with_document_tags':
    a matched document rule whose SOP sentence says (CRITICAL)/(WARNING) can
    raise the level; it never lowers it."""
    level = severity({a["kind"] for a in alarms})
    if cfg.get("severity_policy", "sop002_bands") == "with_document_tags":
        for a in alarms:
            tag = tags.get(a["rule_id"])
            if tag and SEVERITY_RANK[tag] > SEVERITY_RANK[level]:
                level = tag
    return level


def describe(c: dict, attached: list[dict], defs: dict, prefix: str, cfg: dict | None = None,
             tags: dict | None = None) -> dict:
    alarms = c["alarms"]
    kinds = {a["kind"] for a in alarms}
    start = min(a["trigger_at"] for a in alarms)
    anomaly_type, reason = k3.classify(alarms + attached, defs)
    record = {"sensor_id": c["sensor_id"], "station_id": c["sensor_id"].rsplit("_", 1)[0],
              "start": start, "end": c["end"].isoformat(),
              "onset_estimate": min(a["condition_start"] for a in alarms + attached),
              "supporting_signal_ids": sorted(s["id"] for s in attached),
              "anomaly_type": anomaly_type, "type_reason": reason,
              "severity": incident_severity(alarms, cfg or {}, tags or {}),
              "alarm_ids": sorted(a["id"] for a in alarms), "rule_ids": sorted({a["rule_id"] for a in alarms}),
              "kinds": sorted(kinds), "report_split": v1.split(start),
              "flags": sorted({a["flag"] for a in alarms if a.get("flag")})}
    record["id"] = prefix + v.digest(v.encoded(record))[:20]
    return record


def build_incidents(alarms: list[dict], signals: list[dict], defs: dict, cfg: dict,
                    tags: dict | None = None) -> list[dict]:
    gap = timedelta(minutes=cfg["incident_gap_min"])
    by_sensor: dict[str, list[dict]] = {}
    for s in signals:
        by_sensor.setdefault(s["sensor_id"], []).append(s)
    out = [describe(c, attached_signals(c, by_sensor, gap), defs, cfg["id_prefix"]["incident"], cfg, tags)
           for c in cluster(alarms, gap)]
    return sorted(out, key=lambda r: (r["start"], r["sensor_id"]))


def warning_anchor(cause: dict, alarms_by_id: dict) -> dict | None:
    """First SOP-002 warning alarm of a cause incident (RULE-ST02-04 trigger)."""
    warnings = [alarms_by_id[a] for a in cause["alarm_ids"]
                if a in alarms_by_id and alarms_by_id[a]["kind"] == "kg_threshold_warning"]
    return min(warnings, key=lambda a: (a["trigger_at"], a["id"])) if warnings else None


def monitor(incidents: list[dict], signals: list[dict], pairs: list[dict], sensors: dict,
            cfg: dict, alarms_by_id: dict | None = None) -> tuple[list[dict], list[dict]]:
    """RULE-ST02-04 monitoring (v3.1). Gate 'warning_any': a cause incident
    containing an SOP-002 warning alarm opens a window of the CORRELATED length
    anchored at the incident start (stage 1 keeps this legacy anchor). Effect
    slope signals inside it, in the rule's direction, become alarms."""
    promoted, windows = [], []
    for p in pairs:
        window = timedelta(minutes=p["window_min"])
        nominal = sensors[p["effect_sensor"]]["nominal"]
        for cause in (i for i in incidents if i["sensor_id"] == p["cause_sensor"]):
            if "kg_threshold_warning" not in cause["kinds"]:
                continue
            anchor_alarm = None
            if cfg.get("monitor_anchor", "incident_start") == "warning_trigger":
                anchor_alarm = warning_anchor(cause, alarms_by_id or {})
                t0 = _dt(anchor_alarm["trigger_at"])
            else:
                t0 = _dt(cause["start"])  # legacy v3.1 anchor
            win = {"cause_incident": cause["id"], "effect_sensor": p["effect_sensor"],
                   "from": t0.isoformat(), "to": (t0 + window).isoformat()}
            if anchor_alarm:
                win["cause_alarm"] = anchor_alarm["id"]
            windows.append(win)
            for s in signals:
                if s["sensor_id"] != p["effect_sensor"]:
                    continue
                value = float(s["trigger_value"])
                direction_ok = ((p["effect_direction"] == "below_nominal" and value < nominal) or
                                (p["effect_direction"] == "above_nominal" and value > nominal))
                if t0 <= _dt(s["trigger_at"]) <= t0 + window and direction_ok:
                    a = {**{k: s[k] for k in SIGNAL_COPY_KEYS},
                         "rule_id": p["rule_ids"][0] + ":monitor", "kind": "kg_correlation_monitor",
                         "monitored_by": cause["id"], "source_signal": s["id"]}
                    if anchor_alarm:
                        a["monitor_cause_alarm"] = anchor_alarm["id"]
                    a["id"] = cfg["id_prefix"]["alarm"] + v.digest(v.encoded(a))[:20]
                    promoted.append(a)
    unique = {a["source_signal"]: a for a in promoted}  # one alarm per signal even if windows overlap
    return sorted(unique.values(), key=lambda a: a["trigger_at"]), windows


def verified_links(incidents: list[dict], pairs: list[dict], alarms_by_id: dict, sensors: dict,
                   cfg: dict) -> list[dict]:
    """link_policy='verified': link an effect incident only when
    (1) the cause incident has an SOP-002 WARNING alarm (RULE-ST02-04 trigger),
    (2) the effect starts within the CORRELATED window after the anchor
        (WARNING alarm time, or incident start for the legacy anchor),
    (3) an effect alarm lies in the rule's direction from nominal, and
    (4) if the effect contains monitor alarms, the cause is the incident that
        opened that monitoring (same cause for promotion and link)."""
    links = []
    for pair in pairs:
        window = timedelta(minutes=pair["window_min"])
        nominal = sensors[pair["effect_sensor"]]["nominal"]
        causes = []
        for ci in (i for i in incidents if i["sensor_id"] == pair["cause_sensor"]):
            anchor_alarm = warning_anchor(ci, alarms_by_id)
            if anchor_alarm is None:
                continue
            anchor = (_dt(anchor_alarm["trigger_at"]) if cfg.get("monitor_anchor") == "warning_trigger"
                      else _dt(ci["start"]))
            causes.append((anchor, ci, anchor_alarm))
        for effect in (i for i in incidents if i["sensor_id"] == pair["effect_sensor"]):
            t = _dt(effect["start"])
            effect_alarms = [alarms_by_id[a] for a in effect["alarm_ids"] if a in alarms_by_id]
            values = [float(a["trigger_value"]) for a in effect_alarms]
            direction_ok = any((pair["effect_direction"] == "below_nominal" and x < nominal) or
                               (pair["effect_direction"] == "above_nominal" and x > nominal) for x in values)
            monitored_by = {a["monitored_by"] for a in effect_alarms if a["kind"] == "kg_correlation_monitor"}
            cands = [(anchor, ci, aa) for anchor, ci, aa in causes if anchor <= t <= anchor + window
                     and (not monitored_by or ci["id"] in monitored_by)]
            if not cands or not direction_ok:
                continue
            anchor, cause, anchor_alarm = max(cands, key=lambda x: (x[0], x[1]["id"]))
            lag = (t - anchor).total_seconds() / 60
            effect["pre_correlation_type"] = effect["anomaly_type"]
            effect["anomaly_type"] = "CORRELATED"
            effect["type_reason"] = (f"onset {lag:.1f} min after {cause['sensor_id']} WARNING alarm "
                                     f"({', '.join(pair['rule_ids'])}); direction {pair['effect_direction']}")
            effect["correlated_with"] = cause["id"]
            links.append({"cause_incident": cause["id"], "effect_incident": effect["id"],
                          "cause_alarm": anchor_alarm["id"], "cause_sensor": pair["cause_sensor"],
                          "effect_sensor": pair["effect_sensor"], "lag_min": lag,
                          "lag_anchor": cfg.get("monitor_anchor"), "effect_direction": pair["effect_direction"],
                          "evidence_rule_ids": pair["rule_ids"] + [pair["window_rule_id"]],
                          "evidence_kg_nodes": pair["kg_nodes"], "hasEvidence": "SOPRule",
                          "status": "rule_pattern_match_not_confirmed_causality", "link_policy": "verified"})
    return links


def run_postprocess(alarms: list[dict], bundle: dict, cfg: dict) -> dict:
    """alarms: executor output (sorted, without ids). Returns every output list."""
    defs, pairs = bundle["type_definitions"], bundle["correlation_pairs"]
    tags = bundle.get("severity_tags", {})
    assign_alarm_ids(alarms, cfg["id_prefix"]["alarm"])
    alarms, signals = split_signals(alarms, cfg["slope_mode"])
    windows = []
    if cfg["monitor_gate"] == "warning_any":
        first = build_incidents(alarms, signals, defs, cfg, tags)  # pass 1: find cause incidents
        monitored, windows = monitor(first, signals, pairs, bundle["sensors"], cfg, {a["id"]: a for a in alarms})
        used = {a["source_signal"] for a in monitored}
        alarms = sorted(alarms + monitored, key=lambda e: (e["trigger_at"], e["sensor_id"], e["rule_id"]))
        signals = [s for s in signals if s["id"] not in used]
    incidents = build_incidents(alarms, signals, defs, cfg, tags)
    if cfg.get("link_policy", "legacy") == "verified":
        links = verified_links(incidents, pairs, {a["id"]: a for a in alarms}, bundle["sensors"], cfg)
    else:
        links = k3.link_correlations(incidents, pairs)  # mutates effect incidents after their ids (legacy order)
    return {"events": alarms, "signals": signals, "monitor_windows": windows,
            "incidents": incidents, "correlations": links,
            "monitor_alarm_count": sum(a["kind"] == "kg_correlation_monitor" for a in alarms)}
