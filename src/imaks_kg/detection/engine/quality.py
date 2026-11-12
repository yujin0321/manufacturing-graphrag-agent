"""KG quality report produced while compiling. Report only: nothing here
changes detection, severity or the KG."""
from __future__ import annotations

import re

from rdflib import RDF

from imaks_kg.rag import comparison as c
from imaks_kg.rag.linking import canonical_id

SEVERITY_TAG = re.compile(r"\((CRITICAL|WARNING)\)")
RULE_CLASSES = ("OperationalRule", "MaintenanceRule", "ThresholdRule")


def kg_quality(graph, bundle: dict) -> dict:
    by_node = {}
    for r in bundle["rules"]:
        by_node.setdefault(r["kg_node"], set()).add(r["kind"])
    rows, missing_condition = [], []
    for cls in RULE_CLASSES:
        for node in sorted(graph.subjects(RDF.type, c.IM[cls]), key=str):
            if graph.value(node, c.IM.appliesToSensor) is None:
                continue
            text = graph.value(node, c.IM.conditionText)
            rid = canonical_id(str(graph.value(node, c.IM.identifier)))
            if text is None:
                missing_condition.append({"rule_id": rid, "kg_node": str(node), "class": cls})
                continue
            tag = SEVERITY_TAG.search(str(text))
            severity = graph.value(node, c.IM.ruleSeverity)
            rows.append({"rule_id": rid, "kg_node": str(node), "class": cls,
                         "ruleSeverity": str(severity) if severity is not None else None,
                         "text_severity_tag": tag.group(1) if tag else None,
                         "executed_kinds": sorted(by_node.get(str(node), []))})
    tagged = [r for r in rows if r["text_severity_tag"]]
    return {
        "sensor_bound_rules": len(rows),
        "ruleSeverity_missing": sum(r["ruleSeverity"] is None for r in rows),
        "text_tag_without_ruleSeverity": [r for r in tagged if r["ruleSeverity"] is None],
        "conditionText_missing": missing_condition,
        "unsupported": [{"rule_id": u["rule_id"], "kg_node": u["kg_node"], "reason": u["reason"]}
                        for u in bundle["unsupported"]],
        "correlation_pairs_without_direction": [p["rule_ids"] for p in bundle["correlation_pairs"]
                                                if p.get("effect_direction") is None],
        "incident_severity_note": ("incident severity uses only SOP-002 band kinds "
                                   "(kg_threshold_critical / kg_threshold_warning / sop002_out_of_range); "
                                   "document-rule severity tags are not used. Unchanged in stage 1."),
        "rules": rows,
    }


def markdown(report: dict, kg_sha: str) -> str:
    lines = ["# 룰 탐지 엔진 KG 품질 보고서 (2026-11-11, 1단계)", "",
             "탐지 엔진 컴파일 중 확인한 KG 상태다. 보고만 하며 탐지 결과·심각도·KG는 바꾸지 않았다.", "",
             f"- KG: `{c.KG_REL}` (sha256 `{kg_sha[:12]}…`)",
             f"- 센서에 연결된 규칙(Operational/Maintenance/Threshold): {report['sensor_bound_rules']}개",
             f"- `ruleSeverity` 값이 없는 규칙: {report['ruleSeverity_missing']}개 (전체)",
             f"- `conditionText`가 없어 컴파일에서 건너뛴 센서 연결 규칙: {len(report['conditionText_missing'])}개",
             "", "## 1. 원문에 등급 표기가 있지만 `ruleSeverity`가 비어 있는 규칙", "",
             "| 규칙 ID | 클래스 | 원문 표기 | 실행 종류 | KG 노드 |", "|---|---|---|---|---|"]
    for r in report["text_tag_without_ruleSeverity"]:
        lines.append(f"| {r['rule_id']} | {r['class']} | {r['text_severity_tag']} | "
                     f"{', '.join(r['executed_kinds']) or '-'} | `{r['kg_node']}` |")
    lines += ["", report["incident_severity_note"], "",
              "## 2. 미지원 규칙", "", "| 규칙 ID | 사유 | KG 노드 |", "|---|---|---|"]
    for u in report["unsupported"]:
        lines.append(f"| {u['rule_id']} | {u['reason']} | `{u['kg_node']}` |")
    lines += ["", "## 3. `conditionText`가 없는 센서 연결 규칙", ""]
    if report["conditionText_missing"]:
        with_text = {r["rule_id"] for r in report["rules"]}
        lines += ["| 규칙 ID | 클래스 | 같은 ID의 원문 노드 존재 | KG 노드 |", "|---|---|---|---|"]
        lines += [f"| {r['rule_id']} | {r['class']} | {'예' if r['rule_id'] in with_text else '아니오'} | "
                  f"`{r['kg_node']}` |" for r in report["conditionText_missing"]]
    else:
        lines.append("없음")
    lines += ["", "## 4. 상관 쌍 방향", "",
              ("방향을 정하지 못한 상관 쌍: " + str(report["correlation_pairs_without_direction"]))
              if report["correlation_pairs_without_direction"] else "모든 상관 쌍의 결과 방향이 원문에서 정해졌다.",
              "", "## 5. 후속 후보 (이번 단계에서 하지 않음)", "",
              "- `ruleSeverity`를 KG에 채우거나 원문 등급 표기를 사건 심각도에 반영할지 결정(탐지 결과가 바뀌므로 새 평가 체계 이후).",
              "- 원문 노드가 따로 있는 seed 노드(`conditionText` 없음)를 KG에서 하나로 합칠지 결정"
              "(현재 컴파일러는 건너뛰므로 탐지에는 영향 없음).", ""]
    return "\n".join(lines)
