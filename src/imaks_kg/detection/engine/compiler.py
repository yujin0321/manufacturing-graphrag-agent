"""Compiler: KG -> executable rule IR.

The only module that reads the KG or parses SOP wording. Every IR record
keeps the KG node, the original ``conditionText``, how it was interpreted,
and where each parameter came from (KG text, KG property, or a value the
team fixed in config/code). Legacy parsers are reused unchanged so the IR
encodes exactly what v2/v3/v3.1 execute.
"""
from __future__ import annotations

import re

from rdflib import RDF, URIRef

from imaks_kg.rag import comparison as c
from imaks_kg.rag import vector as v
from imaks_kg.rag.linking import canonical_id

from .. import kg_rules as k2
from .. import kg_rules_v3 as k3
from .. import kg_rules_v3_1 as k31

IR_VERSION = "detector-ir-v1"
TYPE_NAMES = ("SPIKE", "DRIFT", "STUCK", "OUT_OF_RANGE", "CORRELATED")
SEVERITY_TAG = re.compile(r"\((CRITICAL|WARNING)\)")


class CompileError(ValueError):
    """A required KG rule could not be compiled (reported with its KG node)."""


def _type_definitions(graph) -> dict:
    """SOP-002 anomaly-type definitions. The legacy parser raises a bare
    AttributeError when a regex does not match; surface the failing node."""
    try:
        return k3.type_definitions(graph)
    except AttributeError as exc:
        bad = []
        for node in graph.subjects(RDF.type, c.IM.ThresholdRule):
            if graph.value(node, c.IM.appliesToSensor) is None:
                bad.append({"kg_node": str(node), "type": str(graph.value(node, c.IM.responseText) or ""),
                            "condition_text": str(graph.value(node, c.IM.conditionText) or "")})
        raise CompileError(f"SOP-002 type definition text no longer matches the grammar: {bad}") from exc


def _record(**kw) -> dict:
    kw["ir_id"] = f"{kw['rule_id']}@{kw['sensor_id']}"
    return kw


def _v2_records(graph, v2_rules: list[dict]) -> list[dict]:
    out = []
    for r in v2_rules:
        node = URIRef(r["kg_node"])
        kg_rule_id = canonical_id(str(graph.value(node, c.IM.identifier)))
        params = {"op": r["op"], "value": r["value"], "second": r["second"],
                  "duration_seconds": r["duration_seconds"]}
        if r["kind"] == "kg_document_rule":
            parsed = k2.parse_condition(r["condition_text"])
            value_src = ("kg:conditionText + kg:ThresholdRule.nominal" if parsed.get("relative_to_nominal")
                         else "kg:conditionText")
            sources = {"op": "kg:conditionText", "value": value_src,
                       "second": "kg:conditionText" if r["second"] is not None else "none",
                       "duration_seconds": "kg:conditionText" if r["duration_seconds"] else "default:0"}
            interp = r.get("note") or f"grammar v2: {parsed.get('op')}"
            tag = SEVERITY_TAG.search(r["condition_text"])
            if tag:
                params["severity_tag"] = tag.group(1)
                sources["severity_tag"] = "kg:conditionText (severity label in the SOP sentence)"
        else:
            lo, hi = ("warnLo", "warnHi") if r["kind"] == "kg_threshold_warning" else ("critLo", "critHi")
            sources = {"op": "engine:band", "value": f"kg:ThresholdRule.{lo}", "second": f"kg:ThresholdRule.{hi}",
                       "duration_seconds": "default:0"}
            interp = "SOP-002 band from structured ThresholdRule properties"
        out.append(_record(rule_id=r["rule_id"], kg_rule_id=kg_rule_id, kg_node=r["kg_node"], kind=r["kind"],
                           executor="threshold_scan", sensor_id=r["sensor_id"], unit=r["unit"],
                           condition_text=r["condition_text"], interpretation=interp,
                           params=params, param_sources=sources, alarm_extra={}))
    return out


def _sop002_records(defs: dict, sensors: dict) -> list[dict]:
    """SOP-002 type criteria applied to every sensor bound by a ThresholdRule."""
    out = []
    d, s, o = defs["DRIFT"], defs["STUCK"], defs["OUT_OF_RANGE"]
    for sid, info in sensors.items():
        common = {"sensor_id": sid, "unit": info["unit"]}
        out.append(_record(rule_id=d["rule_id"] + ":DRIFT", kg_rule_id=d["rule_id"], kg_node=d["kg_node"],
                           kind="sop002_drift_slope", executor="slope", condition_text=d["condition_text"],
                           interpretation="OLS slope over window, |slope| > k*sigma/min, moving away from nominal, "
                                          "N consecutive readings; skipped when sigma == 0",
                           params={"k_sigma_per_min": d["sigma_per_min"], "readings": d["readings"],
                                   "window_min": d["window_min"], "nominal": info["nominal"]},
                           param_sources={"k_sigma_per_min": "kg:conditionText", "readings": "kg:conditionText",
                                          "window_min": "kg:conditionText",
                                          "nominal": f"kg:ThresholdRule.nominal ({info['threshold_node']})",
                                          "sigma": "calibration:1.4826*MAD of train-period values (config.train_end)"},
                           alarm_extra={}, **common))
        out.append(_record(rule_id=s["rule_id"] + ":STUCK", kg_rule_id=s["rule_id"], kg_node=s["kg_node"],
                           kind="sop002_stuck_std", executor="stuck_std", condition_text=s["condition_text"],
                           interpretation="std(last N) < fraction*|nominal|; condition start = first sample of window",
                           params={"window": s["window"], "limit": s["nominal_fraction"] * abs(info["nominal"])},
                           param_sources={"window": "kg:conditionText",
                                          "limit": "kg:conditionText x kg:ThresholdRule.nominal"},
                           alarm_extra={}, **common))
        out.append(_record(rule_id=o["rule_id"] + ":OUT_OF_RANGE", kg_rule_id=o["rule_id"], kg_node=o["kg_node"],
                           kind="sop002_out_of_range", executor="outside_run", condition_text=o["condition_text"],
                           interpretation="outside WARN band for N consecutive readings",
                           params={"lo": info["warnLo"], "hi": info["warnHi"], "readings": o["readings"]},
                           param_sources={"lo": "kg:ThresholdRule.warnLo", "hi": "kg:ThresholdRule.warnHi",
                                          "readings": "kg:conditionText"},
                           alarm_extra={}, **common))
    return out


def _v3_records(compiled: dict) -> list[dict]:
    out = []
    sensors = compiled["sensors"]
    for m in compiled["maint_drift"]:
        common = {"rule_id": m["rule_id"], "kg_rule_id": m["rule_id"], "kg_node": m["kg_node"], "kind": m["kind"],
                  "sensor_id": m["sensor_id"], "unit": m["unit"], "condition_text": m["condition_text"],
                  "alarm_extra": {}}
        if m["mode"] == "window_change":
            out.append(_record(executor="window_change",
                               interpretation="|mean(last S) - mean(S ending W earlier)| > delta "
                                              "(direction per config.maint_direction)",
                               params={"delta": m["delta"], "window_min": m["window_min"],
                                       "nominal": sensors[m["sensor_id"]]["nominal"]},
                               param_sources={"delta": "kg:conditionText", "window_min": "kg:conditionText",
                                              "nominal": "kg:ThresholdRule.nominal (used only when direction=away)",
                                              "smooth_samples": "config.smooth_samples"}, **common))
        else:
            out.append(_record(executor="sustained_from_nominal",
                               interpretation="|value - nominal| > delta for W+ minutes (inclusive: W/30s + 1 readings)",
                               params={"delta": m["delta"], "min_minutes": m["min_minutes"],
                                       "nominal": sensors[m["sensor_id"]]["nominal"]},
                               param_sources={"delta": "kg:conditionText", "min_minutes": "kg:conditionText",
                                              "nominal": "kg:ThresholdRule.nominal"}, **common))
    for p in compiled["partial"]:
        out.append(_record(rule_id=p["rule_id"], kg_rule_id=p["rule_id"], kg_node=p["kg_node"], kind=p["kind"],
                           executor="partial_threshold", sensor_id=p["sensor_id"], unit=p["unit"],
                           condition_text=p["condition_text"],
                           interpretation="observable part only; unobservable precondition flagged",
                           params={"op": p["op"], "value": p["value"]},
                           param_sources={"op": "kg:conditionText", "value": "kg:conditionText"},
                           alarm_extra={"flag": p["flag"]}))
    return out


def compile_ir(graph) -> dict:
    """Return the IR bundle. Raises CompileError for required SOP-002 types."""
    defs = _type_definitions(graph)
    compiled = k3.compile_v3(graph)  # v2 grammar + v3 MAINT/partial/correlation parsers (unchanged)
    sensors = compiled["sensors"]
    rules = _v2_records(graph, compiled["v2_rules"]) + _sop002_records(defs, sensors) + _v3_records(compiled)
    ids = [r["ir_id"] for r in rules]
    if len(ids) != len(set(ids)):
        raise CompileError("duplicate IR ids")
    pairs = []
    for p in k31.pair_directions(graph, compiled["correlation_pairs"]):
        pairs.append({**p, "param_sources": {"pair": "kg:conditionText (parse_correlation)",
                                             "window_min": "kg:conditionText of " + p["window_rule_id"],
                                             "effect_direction": "kg:conditionText wording of the pair rules"}})
    severity_tags = {r["rule_id"]: r["params"]["severity_tag"] for r in rules if "severity_tag" in r["params"]}
    return {"ir_version": IR_VERSION, "rules": rules, "type_definitions": defs, "sensors": sensors,
            "severity_tags": severity_tags,
            "correlation_pairs": pairs, "unsupported": compiled["unsupported"],
            "kg_sha256": v.digest((v.REPO_ROOT / c.KG_REL).read_bytes())}
