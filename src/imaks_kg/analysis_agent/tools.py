"""분석 세션 위에서 동작하는 Agent 도구.

도구는 모두 로컬 조회이며 API를 호출하지 않는다. 사건 관련 3개 도구는 `rag/incident_tools.py`의
함수를 세션의 봉인 결과에 그대로 적용한다.

* summarize_results()                    업로드 데이터 전체 결과 요약
* list_incidents(sensor_id?, anomaly_type?, severity?, offset?, limit?)
* get_incident_evidence(incident_id)     사건·알람·일치 KG 규칙·원문 근거·그래프 경로
* get_correlated_incidents(incident_id)  규칙 패턴 상관 후보(인과 아님)
* get_sensor_window(incident_id)         사건 전후 센서 값(업로드 데이터)과 기준 임계값
* search_documents(query)                SOP·데이터시트 검색(BM25 + KG 구조 조회, 임베딩 없음)
"""
from __future__ import annotations

import csv
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import tiktoken

from imaks_kg.rag import agent_contract as contract
from imaks_kg.rag import incident_tools as it
from imaks_kg.rag import retrieval_v4_1 as retrieval
from imaks_kg.rag import vector as v

from . import ingest

VERSION = "analysis-agent-tools-v1-20261115"
LIMITS = {"tool_calls": 6, "evidence_tokens": 9000, "document_searches": 1}
INCIDENT_ID = re.compile(r"inc3[0-9]?-[0-9a-f]{20}")
SEVERITY_RANK = {"CRITICAL": 0, "WARNING": 1, "ADVISORY": 2}
TOOLS = {
    "summarize_results": {"required": set(), "optional": set()},
    "list_incidents": {"required": set(), "optional": {"sensor_id", "station_id", "sensor_type", "anomaly_type",
                                                       "severity", "offset", "limit"}},
    "get_incident_evidence": {"required": {"incident_id"}, "optional": set()},
    "get_correlated_incidents": {"required": {"incident_id"}, "optional": set()},
    "get_sensor_window": {"required": {"incident_id"}, "optional": set()},
    "search_documents": {"required": {"query"}, "optional": set()},
}
WARNINGS = it.WARNINGS
_ENCODER = None


def tokens(obj) -> int:
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = tiktoken.get_encoding("o200k_base")
    return len(_ENCODER.encode(json.dumps(obj, ensure_ascii=False)))


def validate_call(name, arguments) -> dict:
    if not isinstance(name, str) or name not in TOOLS:
        raise contract.ContractError("unknown_tool")
    if not isinstance(arguments, dict):
        raise contract.ContractError("invalid_arguments")
    spec = TOOLS[name]
    if not spec["required"] <= arguments.keys() or arguments.keys() - spec["required"] - spec["optional"]:
        raise contract.ContractError("invalid_fields")
    if name == "list_incidents":
        extra = {k: arguments[k] for k in ("station_id", "sensor_type") if k in arguments}
        for val in extra.values():
            if not isinstance(val, str) or not re.fullmatch(r"[A-Z0-9_]{1,64}", val):
                raise contract.ContractError("invalid_filter")
        args = it.validate_call(name, {k: val for k, val in arguments.items() if k not in extra})
        return {**args, **extra}
    if name in ("get_incident_evidence", "get_correlated_incidents"):
        return it.validate_call(name, arguments)
    if name == "get_sensor_window":
        return it.validate_call("get_incident_evidence", arguments)
    if name == "search_documents":
        q = arguments["query"]
        if not isinstance(q, str) or not q.strip() or len(q.encode()) > 2000:
            raise contract.ContractError("invalid_query")
    return dict(arguments)


def rank_key(inc: dict):
    return (SEVERITY_RANK.get(inc["severity"], 9), inc["start"], inc["id"])


class Workspace:
    """한 분석 세션의 봉인 결과(엔진·오버레이)와 정규화 입력. 질문마다 재사용한다."""

    def __init__(self, session_dir: Path, base=None):
        self.dir = Path(session_dir)
        self.store = it.IncidentStore(self.dir / "engine", self.dir / "overlay", base=base)
        self.summary = v.read(self.dir / "engine/summary.json")
        self.ingest = v.read(self.dir / "input/ingest_report.json")
        self.meta = ingest.reference_metadata()["sensors"]
        self._series: dict[str, list[tuple[str, float]]] | None = None

    def series(self, sensor_id: str) -> list[tuple[str, float]]:
        if self._series is None:
            data: dict[str, list[tuple[str, float]]] = {}
            with (self.dir / "input/sensor_input.csv").open(encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    data.setdefault(row["sensor_id"], []).append((row["timestamp"], float(row["value"])))
            self._series = data
        return self._series.get(sensor_id, [])

    def lock(self) -> dict:
        return {**self.store.lock(), "input_sha256": self.ingest["file_sha256"]}


# ---------------------------------------------------------------- handlers
def summarize_results(ws: Workspace, args: dict) -> dict:
    incs = sorted(ws.store.incidents, key=rank_key)
    keys = ("id", "sensor_id", "station_id", "start", "end", "anomaly_type", "severity")
    data = {"input": {k: ws.ingest[k] for k in ("file_name", "period", "rows_used", "sensors_missing",
                                                 "dropped_label_like_columns", "invalid_value_rows")},
            "sensor_count": len(ws.ingest["sensors"]),
            "totals": {k: ws.summary[k] for k in ("alarms", "incidents", "correlation_links")},
            "by_type": ws.summary["incidents_by_type"], "by_severity": ws.summary["incidents_by_severity"],
            "by_station": ws.summary["incidents_by_station"],
            "incidents_ranked": [{k: i[k] for k in keys} for i in incs[:12]],
            "incidents_not_shown": max(0, len(incs) - 12),
            "correlation_candidates": [{k: c[k] for k in ("cause_incident", "effect_incident", "lag_min",
                                                          "evidence_rule_ids", "status")}
                                       for c in ws.store.correlations],
            "rules_not_executed": {"missing_sensor": ws.summary["rules_skipped_missing_sensor"],
                                   "unsupported": ws.summary["unsupported_rules"]},
            "ranking": "심각도(CRITICAL>WARNING>ADVISORY) 다음 시작 시각 순"}
    return {**data, "context_tokens": tokens(data)}


def list_incidents(ws: Workspace, args: dict) -> dict:
    """incident_tools.list_incidents와 같은 출력 형태 + station_id 필터, 심각도 순 정렬."""
    for key, known in (("sensor_id", ws.meta), ("station_id", {m["station_id"] for m in ws.meta.values()}),
                       ("sensor_type", {m["sensor_type"] for m in ws.meta.values()})):
        if key in args and args[key] not in known:
            raise contract.ContractError("unknown_filter_id")
    fields = ("sensor_id", "station_id", "anomaly_type", "severity")
    matches = sorted((i for i in ws.store.incidents
                      if all(i[k] == args[k] for k in fields if k in args)
                      and ("sensor_type" not in args or ws.meta[i["sensor_id"]]["sensor_type"] == args["sensor_type"])),
                     key=rank_key)
    start, end = args["offset"], args["offset"] + args["limit"]
    keys = ("id", "sensor_id", "station_id", "start", "end", "anomaly_type", "severity", "rule_ids")
    data = {"filters": {k: args[k] for k in (*fields, "sensor_type") if k in args},
            "total_matches": len(matches), "items": [{k: i[k] for k in keys} for i in matches[start:end]],
            "next_offset": end if end < len(matches) else None, "ranking": "심각도 다음 시작 시각 순"}
    return {**data, "context_tokens": tokens(data)}


def get_sensor_window(ws: Workspace, args: dict) -> dict:
    inc = ws.store.by_id.get(args["incident_id"])
    if inc is None:
        raise contract.ContractError("unknown_incident_id")
    meta = ws.meta[inc["sensor_id"]]
    lo = datetime.fromisoformat(inc["onset_estimate"]) - timedelta(minutes=15)
    hi = datetime.fromisoformat(inc["end"]) + timedelta(minutes=15)
    start, end = inc["start"], inc["end"]
    pts = [(t, x) for t, x in ws.series(inc["sensor_id"]) if lo.isoformat() <= t <= hi.isoformat()]
    before = [x for t, x in pts if t < inc["onset_estimate"]]
    during = [x for t, x in pts if start <= t <= end]
    step = max(1, len(pts) // 40)
    stat = lambda xs: ({"n": len(xs), "min": round(min(xs), 4), "max": round(max(xs), 4),
                        "mean": round(sum(xs) / len(xs), 4)} if xs else None)
    peak = max(during, key=lambda x: abs(x - meta["nominal"])) if during else None
    data = {"incident_id": inc["id"], "sensor_id": inc["sensor_id"], "unit": meta["unit"],
            "reference_thresholds": {k: meta[k] for k in ("nominal", "warn_lo", "warn_hi", "crit_lo", "crit_hi")},
            "threshold_source": "preprocessed/sensors/rules/sensor_thresholds.csv (고정 메타데이터, 업로드 파일 아님)",
            "window": {"from": lo.isoformat(), "to": hi.isoformat()},
            "before_onset": stat(before), "during_incident": stat(during),
            "farthest_from_nominal_during": peak,
            "points": [{"t": t, "v": x} for t, x in pts[::step]],
            "note": "업로드된 과거 값의 구간 요약이다. 실시간 값이 아니다. 사건 구간 통계는 사후 집계다."}
    return {**data, "context_tokens": tokens({k: val for k, val in data.items() if k != "points"})}


def search_documents(ws: Workspace, args: dict) -> dict:
    packet = retrieval.source_packet(retrieval.retrieve(args["query"], use_dense=False, typed=True))
    data = {"query": args["query"], "context": packet["context"], "selected_ids": packet["selected_ids"],
            "sources": [{"chunk_id": s["chunk_id"], "text": s["text"]} for s in packet["sources"]],
            "graph_paths": packet["graph_paths"], "coverage_complete": packet["coverage_complete"]}
    return {**data, "context_tokens": packet["context_tokens"]}


def _incident_tool(fn):
    return lambda ws, args: fn(ws.store, args)


HANDLERS = {"summarize_results": summarize_results,
            "list_incidents": list_incidents,
            "get_incident_evidence": _incident_tool(it.get_incident_evidence),
            "get_correlated_incidents": _incident_tool(it.get_correlated_incidents),
            "get_sensor_window": get_sensor_window,
            "search_documents": search_documents}


class ToolSession:
    """질문 하나의 도구 실행. 한도 초과·계약 위반은 그 도구만 실패로 기록하고 이어간다."""

    def __init__(self, ws: Workspace, run_dir: Path, explicit_ids=()):
        self.ws, self.run = ws, Path(run_dir)
        self.allowed = {i for i in explicit_ids if i in ws.store.by_id}
        self.calls, self.evidence_tokens, self.searches, self.trace, self.results = 0, 0, 0, [], []

    def known_ids(self, data) -> set[str]:
        return set(INCIDENT_ID.findall(json.dumps(data))) & set(self.ws.store.by_id)

    def execute(self, name: str, arguments: dict) -> dict:
        started = time.perf_counter()
        self.calls += 1
        args, data, code = None, None, None
        try:
            if self.calls > LIMITS["tool_calls"]:
                raise contract.ContractError("tool_limit_exceeded")
            args = validate_call(name, arguments)
            if "incident_id" in args and args["incident_id"] not in self.allowed:
                raise contract.ContractError("incident_selection_required")
            if name == "search_documents":
                self.searches += 1
                if self.searches > LIMITS["document_searches"]:
                    raise contract.ContractError("document_search_limit")
            data = HANDLERS[name](self.ws, args)
            count = data.get("context_tokens", 0)
            if self.evidence_tokens + count > LIMITS["evidence_tokens"]:
                raise contract.ContractError("context_budget_exceeded")
            self.evidence_tokens += count
            if name in ("summarize_results", "list_incidents", "get_correlated_incidents"):
                self.allowed |= self.known_ids(data)
        except contract.ContractError as exc:
            code, data = str(exc), None
        except Exception as exc:  # 도구 내부 오류는 원문 메시지 대신 유형만 남긴다
            code, data = f"tool_execution_failed:{type(exc).__name__}", None
        result = {"tool": name, "arguments": args if args is not None else arguments,
                  "status": "error" if code else "ok", "error_code": code, "data": data}
        self.results.append(result)
        self.trace.append({"step": self.calls, "tool": name, "arguments": result["arguments"],
                           "status": result["status"], "error_code": code,
                           "seconds": round(time.perf_counter() - started, 3)})
        v.write(self.run / f"tool_{self.calls:02d}.json", result)
        return result
