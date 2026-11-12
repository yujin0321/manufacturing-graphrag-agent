"""Executor: sensor samples + rule IR -> alarms.

Never reads the KG or SOP text: everything it needs is in the IR. Firing
decisions use only samples up to the firing time (forward-only), and a gap
between samples resets persistence. ``last_positive_at`` is the batch
end-of-run timestamp, as in the legacy outputs. Per-sample calculations are
the legacy functions (k2.scan, k3.runs, k3.slope_condition,
k3.stuck_condition) so the alarms are identical.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np

from .. import kg_rules as k2
from .. import kg_rules_v3 as k3

EXECUTORS = {"threshold_scan", "slope", "stuck_std", "outside_run", "window_change",
             "sustained_from_nominal", "partial_threshold"}


def train_sigma(rows: list[dict], train_end: str) -> dict:
    """sigma = 1.4826*MAD of values before ``train_end``; std if MAD == 0. No labels."""
    x = np.array([float(r["value"]) for r in rows if r["timestamp"] < train_end])
    mad = float(np.median(np.abs(x - np.median(x))))
    sigma, method = 1.4826 * mad, "1.4826*MAD"
    if sigma == 0:
        sigma, method = float(np.std(x)), "std (MAD=0)"
    return {"sigma": sigma, "method": method, "train_samples": int(x.size)}


def calibrate(groups: dict, cfg: dict) -> dict:
    return {sid: train_sigma(rows, cfg["train_end"]) for sid, rows in groups.items()}


def window_change_condition(x, seg, window_samples: int, delta: float, smooth: int,
                            direction: str, nominal: float):
    """|now - before| > delta, means over ``smooth`` samples. direction='away'
    also requires now to be farther from nominal than before (v3.1)."""
    cond = np.zeros(len(x), dtype=bool)
    need = window_samples + smooth
    for i in range(need - 1, len(x)):
        if not k3._window_ok(seg, i, need):
            continue
        now = x[i - smooth + 1:i + 1].mean()
        j = i - window_samples
        before = x[j - smooth + 1:j + 1].mean()
        ok = abs(now - before) > delta
        if direction == "away":
            ok = ok and abs(now - nominal) > abs(before - nominal)
        cond[i] = ok
    return cond


def _alarm_rule(ir: dict) -> dict:
    return {"sensor_id": ir["sensor_id"], "rule_id": ir["rule_id"], "kind": ir["kind"], "unit": ir["unit"]}


def execute_rule(ir: dict, rows: list[dict], arrays, sigma: dict, cfg: dict) -> list[dict]:
    """Alarms of one IR record on one sensor's ordered samples."""
    kind, p = ir["executor"], ir["params"]
    if kind == "threshold_scan":
        rule = {**_alarm_rule(ir), "op": p["op"], "value": p["value"], "second": p["second"],
                "duration_seconds": p["duration_seconds"]}
        return k2.scan(rows, rule)
    ts, x, seg = arrays
    wrapped = {"_arrays": arrays}
    rule, extra = _alarm_rule(ir), dict(ir["alarm_extra"])
    step = cfg["sample_seconds"]
    if kind == "slope":
        if not sigma["sigma"] > 0:
            return []
        window = p["window_min"] * 60 // step
        cond = k3.slope_condition(x, seg, window, sigma["sigma"], p["nominal"], p["k_sigma_per_min"])
        return k3.runs(wrapped, cond, p["readings"], rule, {**extra, "sigma": sigma["sigma"]})
    if kind == "stuck_std":
        cond = k3.stuck_condition(x, seg, p["window"], p["limit"])
        offset = [timedelta(seconds=(p["window"] - 1) * step)] * len(x)
        return k3.runs(wrapped, cond, 1, rule, extra or None, start_offset=offset)
    if kind == "outside_run":
        cond = (x < p["lo"]) | (x > p["hi"])
        return k3.runs(wrapped, cond, p["readings"], rule, extra or None)
    if kind == "window_change":
        direction = cfg["maint_direction"]
        cond = window_change_condition(x, seg, p["window_min"] * 60 // step, p["delta"], cfg["smooth_samples"],
                                       direction, p["nominal"])
        if direction == "away":
            extra["direction"] = "away_from_nominal"
        return k3.runs(wrapped, cond, 1, rule, extra or None)
    if kind == "sustained_from_nominal":
        cond = np.abs(x - p["nominal"]) > p["delta"]
        return k3.runs(wrapped, cond, p["min_minutes"] * 60 // step + 1, rule, extra or None)
    if kind == "partial_threshold":
        cond = x < p["value"] if p["op"] == "lt" else x > p["value"]
        return k3.runs(wrapped, cond, 1, rule, extra or None)
    raise ValueError(f"unknown executor {kind}")


def execute(groups: dict, ir_rules: list[dict], sigmas: dict, cfg: dict) -> list[dict]:
    """All alarms, sorted by (trigger_at, sensor_id, rule_id). IDs are assigned
    later by post-processing (same point in the pipeline as legacy)."""
    arrays = {sid: k3._arrays(rows) for sid, rows in groups.items()}
    alarms = []
    for ir in ir_rules:
        if ir["executor"] not in EXECUTORS:
            raise ValueError(f"unknown executor {ir['executor']}")
        sid = ir["sensor_id"]
        alarms.extend(execute_rule(ir, groups[sid], arrays[sid], sigmas[sid], cfg))
    alarms.sort(key=lambda e: (e["trigger_at"], e["sensor_id"], e["rule_id"]))
    return alarms
