"""Stage 3: Agent tools over the rule-engine incidents and their KG overlay.

Reads a sealed engine run (``detection/engine/run.py``) and the overlay built
from it (``detection/engine/overlay.py``); both seals and their link are
verified before any data is returned. The frozen KG and the overlay are
queried together. No generation, network or label access.

Tools (same session limits as agent_contract.LIMITS):
* list_incidents(sensor_id?, anomaly_type?, severity?, offset, limit)
* get_incident_evidence(incident_id): incident, alarms, matched KG rules with
  condition/response text and source chunks, graph paths, monitoring windows.
* get_correlated_incidents(incident_id): rule-pattern correlation candidates.

Outputs describe historical rule-match candidates. They are not confirmed
anomalies and correlation candidates are not confirmed causality.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import tiktoken
from rdflib import Graph, Literal, RDF, URIRef

from . import agent_contract as contract
from . import comparison as c
from . import vector as v

ENGINE_RUN = v.REPO_ROOT / "kg_build/rule_engine_v3_1"
ENGINE_OVERLAY = v.REPO_ROOT / "kg_build/rule_engine_v3_1_overlay"
VERSION = "incident-tools-v1-20261111"
TYPES = ("SPIKE", "DRIFT", "STUCK", "OUT_OF_RANGE", "CORRELATED", "UNCLASSIFIED")
SEVERITIES = ("CRITICAL", "WARNING", "ADVISORY")
TOOLS = {
    "list_incidents": {"required": set(), "optional": {"sensor_id", "anomaly_type", "severity", "offset", "limit"}},
    "get_incident_evidence": {"required": {"incident_id"}, "optional": set()},
    "get_correlated_incidents": {"required": {"incident_id"}, "optional": set()},
}
WARNINGS = ["과거 센서 데이터의 규칙 일치 후보입니다. 확정 이상이나 실시간 설비 상태가 아닙니다.",
            "상관 후보는 SOP 규칙 패턴 일치이며 입증된 인과가 아닙니다.",
            "사건 종료 시각과 구간 집계는 사후 정보입니다."]
DET = "https://example.org/imaks/detection/engine#"


def validate_call(name, arguments):
    if not isinstance(name, str) or name not in TOOLS:
        raise contract.ContractError("unknown_tool")
    if not isinstance(arguments, dict):
        raise contract.ContractError("invalid_arguments")
    spec = TOOLS[name]
    if not spec["required"] <= arguments.keys() or arguments.keys() - spec["required"] - spec["optional"]:
        raise contract.ContractError("invalid_fields")
    args = dict(arguments)
    if "incident_id" in spec["required"]:
        if not isinstance(args["incident_id"], str) or not re.fullmatch(r"inc3[0-9]?-[0-9a-f]{20}", args["incident_id"]):
            raise contract.ContractError("invalid_incident_id")
        return args
    if "sensor_id" in args and (not isinstance(args["sensor_id"], str)
                                or not re.fullmatch(r"[A-Z0-9_]{1,64}", args["sensor_id"])):
        raise contract.ContractError("invalid_filter")
    if "anomaly_type" in args and args["anomaly_type"] not in TYPES:
        raise contract.ContractError("invalid_filter")
    if "severity" in args and args["severity"] not in SEVERITIES:
        raise contract.ContractError("invalid_filter")
    for key, default, low, high in (("offset", 0, 0, 10000), ("limit", 10, 1, 20)):
        value = args.get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise contract.ContractError("invalid_pagination")
        args[key] = value
    return args


def _verify(root: Path, required: set[str]) -> dict:
    seal = v.read(root / "complete.json")
    if not required <= set(seal):
        raise ValueError("Incomplete seal")
    for name, checksum in seal.items():
        if Path(name).name != name or v.digest((root / name).read_bytes()) != checksum:
            raise ValueError("Invalid seal")
    return seal


class IncidentStore:
    """Sealed engine output + sealed overlay, with the KG loaded once."""

    def __init__(self, run_dir: Path = ENGINE_RUN, overlay_dir: Path = ENGINE_OVERLAY, base: Graph | None = None):
        self.run_dir, self.overlay_dir = Path(run_dir), Path(overlay_dir)
        self.seal = _verify(self.run_dir, {"incidents.json", "events.json", "correlations.json", "ir.json"})
        self.overlay_seal = _verify(self.overlay_dir, {"overlay.ttl", "overlay_report.json"})
        report = v.read(self.overlay_dir / "overlay_report.json")
        if report["engine_seal_sha256"] != v.digest(v.encoded(self.seal)):
            raise ValueError("Overlay was built from a different engine run")
        self.incidents = v.read(self.run_dir / "incidents.json")
        self.by_id = {i["id"]: i for i in self.incidents}
        self.alarms = {a["id"]: a for a in v.read(self.run_dir / "events.json")}
        self.correlations = v.read(self.run_dir / "correlations.json")
        windows = self.run_dir / "monitor_windows.json"
        self.windows = v.read(windows) if windows.exists() else []
        self.base = base if base is not None else c.load_graph()
        self.overlay = Graph().parse(self.overlay_dir / "overlay.ttl", format="turtle")
        self._links = None

    def source_links(self):
        if self._links is None:
            corpus, _ = v.source_records()
            self._links = ({str(k): vs for k, vs in c.source_links(self.base, corpus).items()},
                           {r["chunk_id"]: r for r in corpus})
        return self._links

    def event_node(self, incident_id: str) -> URIRef:
        node = next(self.overlay.subjects(URIRef(DET + "engineIncidentId"), Literal(incident_id)), None)
        if node is None:
            raise contract.ContractError("unknown_incident_id")
        return node

    def lock(self) -> dict:
        return {"engine_seal": self.seal, "overlay_seal": self.overlay_seal,
                "kg_sha256": v.digest((v.REPO_ROOT / c.KG_REL).read_bytes())}


def list_incidents(store: IncidentStore, args: dict) -> dict:
    if "sensor_id" in args and args["sensor_id"] not in {i["sensor_id"] for i in store.incidents} | \
            {str(store.base.value(s, c.IM.identifier)) for s in store.base.subjects(RDF.type, c.IM.Sensor)}:
        raise contract.ContractError("unknown_filter_id")
    matches = [i for i in store.incidents
               if ("sensor_id" not in args or i["sensor_id"] == args["sensor_id"])
               and ("anomaly_type" not in args or i["anomaly_type"] == args["anomaly_type"])
               and ("severity" not in args or i["severity"] == args["severity"])]
    matches.sort(key=lambda i: (i["start"], i["id"]))
    start, end = args["offset"], args["offset"] + args["limit"]
    keys = ("id", "sensor_id", "station_id", "start", "anomaly_type", "severity", "rule_ids")
    return {"total_matches": len(matches), "items": [{k: i[k] for k in keys} for i in matches[start:end]],
            "next_offset": end if end < len(matches) else None}


def _count(obj) -> int:
    cfg = v.read(v.REPO_ROOT / "docs/vector_rag_v1/config.json")
    return len(tiktoken.get_encoding(cfg["context_encoding"]).encode(json.dumps(obj, ensure_ascii=False)))


def get_incident_evidence(store: IncidentStore, args: dict) -> dict:
    inc = store.by_id.get(args["incident_id"])
    if inc is None:
        raise contract.ContractError("unknown_incident_id")
    node = store.event_node(inc["id"])
    links, chunks_by_id = store.source_links()
    edges, rules, chunk_ids = [], [], set()
    for sensor in store.overlay.subjects(c.IM.triggers, node):
        edges.append({"s": str(sensor), "p": str(c.IM.triggers), "o": str(node), "depth": 1})
    for rule in sorted(store.overlay.objects(node, URIRef(DET + "matchedRule")), key=str):
        edges.append({"s": str(node), "p": DET + "matchedRule", "o": str(rule), "depth": 1})
        rid = str(store.base.value(rule, c.IM.identifier)).rsplit("::", 1)[-1]
        cids = links.get(str(rule), [])
        chunk_ids.update(cids)
        rules.append({"kg_node": str(rule), "rule_id": rid,
                      "condition_text": str(store.base.value(rule, c.IM.conditionText) or ""),
                      "response_text": str(store.base.value(rule, c.IM.responseText) or ""),
                      "source_chunks": cids})
        for sensor in store.base.objects(rule, c.IM.appliesToSensor):
            edges.append({"s": str(rule), "p": str(c.IM.appliesToSensor), "o": str(sensor), "depth": 2})
    alarms = [{k: store.alarms[a][k] for k in ("id", "rule_id", "kind", "trigger_at", "trigger_value", "unit",
                                               "condition_start") if k in store.alarms[a]}
              for a in inc["alarm_ids"]]
    windows = [w for w in store.windows if w["cause_incident"] == inc["id"]]
    context = {"incident": {k: inc[k] for k in ("id", "sensor_id", "station_id", "start", "end", "onset_estimate",
                                                 "anomaly_type", "type_reason", "severity", "flags")
                            if k in inc},
               "sensor_level_type": inc.get("pre_correlation_type"),
               "alarms": alarms, "matched_rules": rules, "monitor_windows_opened": windows,
               "graph_paths": edges,
               "untrusted_reference_documents": [{"chunk_id": cid, "text": chunks_by_id[cid]["text"]}
                                                 for cid in sorted(chunk_ids) if cid in chunks_by_id]}
    tokens = _count(context)
    return {**context, "context_tokens": tokens}


def get_correlated_incidents(store: IncidentStore, args: dict) -> dict:
    inc = store.by_id.get(args["incident_id"])
    if inc is None:
        raise contract.ContractError("unknown_incident_id")
    items = []
    for link in store.correlations:
        if inc["id"] not in (link["cause_incident"], link["effect_incident"]):
            continue
        role = "cause" if link["cause_incident"] == inc["id"] else "effect"
        other = store.by_id[link["effect_incident"] if role == "cause" else link["cause_incident"]]
        items.append({"role_of_queried_incident": role, "other_incident": other["id"],
                      "other_sensor": other["sensor_id"], "other_start": other["start"],
                      "lag_min": link["lag_min"], "evidence_rule_ids": link["evidence_rule_ids"],
                      "evidence_kind": link["hasEvidence"], "status": link["status"]})
    data = {"incident_id": inc["id"], "correlation_candidates": items,
            "note": "SOP 규칙 패턴 일치 후보이며 likelihoodScore가 정의되지 않아 causallyAffects로 적재하지 않았습니다."}
    return {**data, "context_tokens": _count(data)}


HANDLERS = {"list_incidents": list_incidents, "get_incident_evidence": get_incident_evidence,
            "get_correlated_incidents": get_correlated_incidents}


class IncidentToolSession:
    """One request. Evidence for an incident needs an explicit caller ID or a
    unique filtered match (same selection rule as the legacy tools)."""

    def __init__(self, run_dir, *, store: IncidentStore | None = None, explicit_incident_ids=()):
        for iid in explicit_incident_ids:
            validate_call("get_incident_evidence", {"incident_id": iid})
        self.store = store or IncidentStore()
        self.allowed = set(explicit_incident_ids)
        self.attempts, self.evidence_tokens, self.stopped, self.trace = 0, 0, False, []
        self.run = Path(run_dir)
        self.run.mkdir(parents=True, exist_ok=False)
        v.write(self.run / "run_lock.json", {"version": VERSION, "limits": contract.LIMITS, **self.store.lock(),
                                             "explicit_incident_ids": sorted(self.allowed),
                                             "code_sha256": v.digest(Path(__file__).read_bytes()),
                                             "evaluation_run": False, "gold_loaded": False, "generation_calls": 0})

    def execute(self, name, arguments):
        started = time.perf_counter()
        self.attempts += 1
        args, data, code = None, None, None
        try:
            if self.stopped:
                raise contract.ContractError("session_stopped")
            if self.attempts > contract.LIMITS["tool_calls"]:
                raise contract.ContractError("tool_limit_exceeded")
            args = validate_call(name, arguments)
            if name != "list_incidents" and args["incident_id"] not in self.allowed:
                raise contract.ContractError("incident_selection_required")
            data = HANDLERS[name](self.store, args)
            if name == "list_incidents" and data["total_matches"] == 1 and len(data["items"]) == 1:
                self.allowed.add(data["items"][0]["id"])
            count = data.get("context_tokens", 0)
            if self.evidence_tokens + count > contract.LIMITS["evidence_tokens"]:
                raise contract.ContractError("context_budget_exceeded")
            self.evidence_tokens += count
        except contract.ContractError as exc:
            code = str(exc)
        except Exception:
            code = "tool_execution_failed"
        if code:
            self.stopped, data = True, None
        result = {"version": VERSION, "tool": name if name in TOOLS else None,
                  "status": "error" if code else "ok", "data": data,
                  "error": {"code": code, "message": "도구 실행을 중단했습니다. 자동 재시도하지 않습니다."} if code else None,
                  "warnings": WARNINGS}
        self.trace.append({"attempt": self.attempts, "tool": result["tool"], "arguments": args,
                           "status": result["status"], "error_code": code,
                           "result_sha256": v.digest(v.encoded(result)), "seconds": time.perf_counter() - started})
        v.write(self.run / f"tool_{self.attempts:02d}.json", result)
        v.write(self.run / "trace.json", {"steps": self.trace, "stopped": self.stopped,
                                         "evidence_tokens": self.evidence_tokens})
        return result
