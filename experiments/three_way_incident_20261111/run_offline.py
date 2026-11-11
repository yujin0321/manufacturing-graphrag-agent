"""LLM-only vs text-retrieval RAG vs GraphRAG on rule-engine incident questions.

Offline, label-free, no API. Fills part of the GraphRAG v5 "pending_event_fixture"
questions (CQ02/03/05/11/15/16/22/24) with fixtures taken from the sealed
rule-engine run (v3.1 correlation candidates), plus two set questions.

* Fixtures and required evidence are computed deterministically from the sealed
  engine output, the overlay and the frozen KG. Dataset labels are never read.
* All systems get the same question text and the same evidence universe:
  86 document chunks + text records of incidents, correlation candidates,
  timeseries provenance windows, KG rule facts and station facts.
* LLM-only: no retrieval (empty context).
* Text RAG: BM25 over the whole universe (stands in for VectorRAG: new question
  embeddings need a paid API or the PC-only local model; see README).
* GraphRAG: generic entity linking (incident = sensor + start minute, sensor,
  station, severity word, rule id) and typed expansion over KG + overlay.
* Same budget for both RAGs: 4,000 o200k tokens. Metric: required-evidence
  recall (not answer accuracy).

  python experiments/three_way_incident_20261111/run_offline.py --run kg_build/rule_engine_v3_1 \
      --overlay kg_build/rule_engine_v3_1_overlay --out experiments/three_way_incident_20261111/results
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import tiktoken  # noqa: E402
from rdflib import RDF  # noqa: E402

from imaks_kg.rag import comparison as c  # noqa: E402
from imaks_kg.rag import incident_tools as it  # noqa: E402
from imaks_kg.rag import vector as v  # noqa: E402
from imaks_kg.rag.lexical import BM25  # noqa: E402

BUDGET = 4000
ENC = tiktoken.get_encoding("o200k_base")
RULE_CLASSES = ("OperationalRule", "ThresholdRule", "MaintenanceRule", "AccessRule")


def tokens(text: str) -> int:
    return len(ENC.encode(text))


def minute(ts: str) -> str:
    return ts[:16].replace("T", " ")


# ------------------------------------------------------------------ evidence universe
def build_units(store: it.IncidentStore) -> dict:
    g, units = store.base, {}
    links, chunks = store.source_links()
    for cid, row in chunks.items():
        units[f"chunk:{cid}"] = {"text": f"[문서 {cid}] {row['text']}", "kind": "chunk"}
    windows = {}
    for p in store.overlay.subjects(c.IM.sourceKind, None):
        wid = str(store.overlay.value(p, c.IM.windowId))
        windows[wid] = p
        units[f"win:{wid}"] = {"kind": "window", "text": (
            f"[시계열 출처 {wid}] 파일 {store.overlay.value(p, c.IM.fileName)} "
            f"sha256 {store.overlay.value(p, c.IM.fileSha256)} 센서 {store.overlay.value(p, c.IM.sensorId)} "
            f"구간 {store.overlay.value(p, c.IM.intervalStart)} ~ {store.overlay.value(p, c.IM.intervalEnd)}")}
    for inc in store.incidents:
        alarms = [store.alarms[a] for a in inc["alarm_ids"]]
        units[f"inc:{inc['id']}"] = {"kind": "incident", "text": (
            f"[탐지 사건 {inc['id']}] 센서 {inc['sensor_id']} 공정 {inc['station_id']} 시작 {minute(inc['start'])} "
            f"종료 {minute(inc['end'])} 추정 시작 {minute(inc['onset_estimate'])} 유형 {inc['anomaly_type']} "
            f"({inc['type_reason']}) 심각도 {inc['severity']} 규칙 {', '.join(inc['rule_ids'])} "
            f"알람 {'; '.join(a['kind'] + ' ' + a['rule_id'] + ' ' + minute(a['trigger_at']) + ' 값 ' + a['trigger_value'] for a in alarms)}")}
    for link in store.correlations:
        key = v.digest(v.encoded(link))[:20]
        units[f"corr:{key}"] = {"kind": "correlation", "text": (
            f"[상관 후보 {key}] 원인 사건 {link['cause_incident']} ({link['cause_sensor']}) → 결과 사건 "
            f"{link['effect_incident']} ({link['effect_sensor']}) 시차 {link['lag_min']}분(사건 시작 기준) "
            f"근거 종류 {link['hasEvidence']} 근거 규칙 {', '.join(link['evidence_rule_ids'])} 상태 {link['status']}; "
            "likelihoodScore 정의 없음, causallyAffects 미적재")}
    facts = {}
    for cls in RULE_CLASSES:
        for n in g.subjects(RDF.type, c.IM[cls]):
            text = g.value(n, c.IM.conditionText)
            if text is None:
                continue  # seed duplicates without text
            rid = str(g.value(n, c.IM.identifier)).rsplit("::", 1)[-1]
            sensors = sorted(str(g.value(s, c.IM.identifier)) for s in g.objects(n, c.IM.appliesToSensor))
            targets = sorted(str(g.value(s, c.IM.identifier)) for s in g.objects(n, c.IM.actionTarget))
            doc = g.value(n, c.IM.sourceDocument)
            facts[rid] = n
            units[f"fact:{rid}"] = {"kind": "rule_fact", "text": (
                f"[KG 규칙 {rid}] 클래스 {cls} 조건 {' '.join(str(text).split())} 조치 "
                f"{' '.join(str(g.value(n, c.IM.responseText) or '').split())} 적용 센서 {', '.join(sensors) or '-'} "
                f"조치 대상 {', '.join(targets) or '-'} 출처 문서 {g.value(doc, c.IM.identifier) if doc else '-'} "
                f"원문 청크 {', '.join(links.get(str(n), [])) or '-'}")}
    stations = {str(g.value(s, c.IM.identifier)): s for s in g.subjects(RDF.type, c.IM.Station)}
    for sid, s in stations.items():
        sensors = sorted(str(g.value(x, c.IM.identifier)) for x in g.objects(s, c.IM.hasSensor))
        units[f"fact:hasSensor:{sid}"] = {"kind": "station_fact",
                                          "text": f"[KG 공정 {sid}] hasSensor {', '.join(sensors)}"}
        for o in g.objects(s, c.IM.feedsInto):
            oid = str(g.value(o, c.IM.identifier))
            units[f"fact:feeds:{sid}->{oid}"] = {"kind": "station_fact",
                                                 "text": f"[KG 공정 흐름] {sid} feedsInto {oid} (물리적 공정 순서, 인과 아님)"}
    for u in units.values():
        u["tokens"] = tokens(u["text"])
    return {"units": units, "facts": facts, "stations": stations, "windows": windows}


# ------------------------------------------------------------------ fixtures, questions, required evidence
def window_of(inc):
    return f"W-{inc['sensor_id']}-{inc['start'].replace('-', '').replace(':', '')}"


def chunk_of(store, rid):
    links, _ = store.source_links()
    for cls in RULE_CLASSES:
        for n in store.base.subjects(RDF.type, c.IM[cls]):
            if str(store.base.value(n, c.IM.identifier)).rsplit("::", 1)[-1] == rid and links.get(str(n)):
                return [f"chunk:{x}" for x in links[str(n)]]
    raise KeyError(rid)


def questions(store: it.IncidentStore) -> list[dict]:
    by_id = store.by_id
    fixtures = sorted(store.correlations, key=lambda l: by_id[l["effect_incident"]]["start"])
    qs = []
    for k, link in enumerate(fixtures, 1):
        e, cz = by_id[link["effect_incident"]], by_id[link["cause_incident"]]
        corr = f"corr:{v.digest(v.encoded(link))[:20]}"
        ed = f"{e['sensor_id']} {minute(e['start'])} 사건"
        cd = f"{cz['sensor_id']} {minute(cz['start'])} 사건"
        r_0204, r_ex01, r_ex27 = chunk_of(store, "RULE-ST02-04"), chunk_of(store, "SOP-003-EX-01"), chunk_of(store, "SOP-002-EX-27")
        qs += [
            {"id": f"F{k}-CQ02", "source": "CQ02", "question": f"{ed}과 {cd}의 연결 후보는 SOP 규칙 근거인가, 시계열에서만 관측된 것인가? 저장된 시차는?",
             "required": [corr, f"inc:{e['id']}", f"inc:{cz['id']}", *r_0204, *r_ex01]},
            {"id": f"F{k}-CQ03", "source": "CQ03", "question": f"{ed}과 {cd} 연결 후보의 문서 근거는 어느 문서·위치이며, 시계열 근거는 어느 파일·센서·시간 구간인가?",
             "required": [*r_0204, *r_ex01, *r_ex27, f"win:{window_of(e)}", f"win:{window_of(cz)}"]},
            {"id": f"F{k}-CQ16", "source": "CQ16", "question": f"{ed}과 {cd} 연결 후보가 참조하는 ruleIds와 windowId가 실제 저장소에 존재하는가?",
             "required": [corr, "fact:RULE-ST02-04", "fact:SOP-003-EX-01", "fact:SOP-002-EX-27",
                          f"win:{window_of(e)}", f"win:{window_of(cz)}"]},
            {"id": f"F{k}-CQ22", "source": "CQ22", "question": f"{ed}의 ST04 속도 변화가 원인 후보인 {cd}보다 먼저 시작됐는가? 관측 순서만으로 인과를 확정할 수 있는가?",
             "required": [f"inc:{e['id']}", f"inc:{cz['id']}"]},
            {"id": f"F{k}-CQ15", "source": "CQ15", "question": f"{ed}의 원인 후보 공정에서 공정 → 센서 → 적용 정비 규칙 → 원문 근거로 이어지는 경로를 제시하라.",
             "required": [corr, f"fact:hasSensor:{cz['station_id']}", "fact:MAINT-02", *chunk_of(store, "MAINT-02")]},
            {"id": f"F{k}-CQ24", "source": "CQ24", "question": f"{ed}에서 점수 0.6 이상인 원인 후보가 있는가? 없다면 근거 부족과 기준 미달을 구별해 답하라.",
             "required": [corr]},
        ]
    cur = [i for i in store.incidents if i["sensor_id"] == "ST02_SEALING_CUR"]
    crit = [i for i in store.incidents if i["severity"] == "CRITICAL"]
    qs += [
        {"id": "G-CQ05", "source": "CQ05", "question": "원인 후보 공정 ST02_SEALING의 전류 센서 ST02_SEALING_CUR가 이상일 때 적용되는 정비 규칙(조치·우선순위)과 SOP-003의 해소 절차는?",
         "required": ["fact:MAINT-02", *chunk_of(store, "MAINT-02"), *chunk_of(store, "SOP-003-EX-01")]},
        {"id": "G-CQ11", "source": "CQ11", "question": "ST02_SEALING에서 ST04_PACKAGING까지 물리적 공정 연결 경로가 있는가? 중간 공정과 방향을 순서대로 제시하라.",
         "required": ["fact:feeds:ST02_SEALING->ST03_LABELLING", "fact:feeds:ST03_LABELLING->ST04_PACKAGING"]},
        {"id": "G-SET1", "source": "new_set", "question": "ST02_SEALING_CUR 센서에서 탐지된 사건을 모두 시작 시각·유형·심각도와 함께 나열하라.",
         "required": [f"inc:{i['id']}" for i in cur]},
        {"id": "G-SET2", "source": "new_set", "question": "심각도 CRITICAL인 탐지 사건을 모두 센서·시작 시각과 함께 나열하라.",
         "required": [f"inc:{i['id']}" for i in crit]},
    ]
    return qs


# ------------------------------------------------------------------ retrievers
def fill(order: list[str], units: dict) -> tuple[list[str], int]:
    chosen, used = [], 0
    for key in dict.fromkeys(order):
        t = units[key]["tokens"]
        if used + t <= BUDGET:
            chosen.append(key)
            used += t
    return chosen, used


def text_rag(q: str, universe: dict, bm25: BM25, keys: list[str]):
    scores = bm25.scores(q)
    order = [k for _, k in sorted(zip(scores, keys), key=lambda x: -x[0]) if _ > 0]
    return fill(order, universe["units"])


def graph_rag(q: str, store: it.IncidentStore, universe: dict):
    g, units, facts = store.base, universe["units"], universe["facts"]
    links, _ = store.source_links()
    order: list[str] = []
    sensor_ids = {str(g.value(s, c.IM.identifier)) for s in g.subjects(RDF.type, c.IM.Sensor)}
    sensors = [s for s in sorted(sensor_ids, key=len, reverse=True) if s in q]
    stations = [s for s in universe["stations"] if re.search(rf"{s}(?!_[A-Z]{{3}})", q)]
    stamps = re.findall(r"([A-Z0-9_]+) (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) 사건", q)
    linked = [i for i in store.incidents for s, t in stamps if i["sensor_id"] == s and minute(i["start"]) == t]

    def rule_units(rule_ids):
        for rid in rule_ids:
            rid = rid.split(":")[0]
            if rid in facts:
                order.append(f"fact:{rid}")
                order.extend(f"chunk:{x}" for x in links.get(str(facts[rid]), []))

    def incident_units(inc, depth=0):
        order.append(f"inc:{inc['id']}")
        order.append(f"win:{window_of(inc)}")
        if depth == 0:
            for link in store.correlations:
                if inc["id"] in (link["cause_incident"], link["effect_incident"]):
                    order.append(f"corr:{v.digest(v.encoded(link))[:20]}")
                    other = store.by_id[link["cause_incident"] if link["effect_incident"] == inc["id"] else link["effect_incident"]]
                    incident_units(other, 1)
                    rule_units(link["evidence_rule_ids"])
                    cause = store.by_id[link["cause_incident"]]
                    order.append(f"fact:hasSensor:{cause['station_id']}")
                    sensor_rules(cause["sensor_id"])
        rule_units(inc["rule_ids"])

    def sensor_rules(sid):
        node = next(s for s in g.subjects(RDF.type, c.IM.Sensor) if str(g.value(s, c.IM.identifier)) == sid)
        for r in g.subjects(c.IM.appliesToSensor, node):
            rid = str(g.value(r, c.IM.identifier)).rsplit("::", 1)[-1]
            if rid in facts:
                rule_units([rid])

    for inc in linked:
        incident_units(inc)
    for sid in sensors:
        if not linked:
            for inc in (i for i in store.incidents if i["sensor_id"] == sid):
                order.append(f"inc:{inc['id']}")
        station = next(st for st, n in universe["stations"].items()
                       if sid in {str(g.value(x, c.IM.identifier)) for x in g.objects(n, c.IM.hasSensor)})
        order.append(f"fact:hasSensor:{station}")
        sensor_rules(sid)
    for sev in ("CRITICAL", "WARNING", "ADVISORY"):
        if sev in q and not linked and not sensors:
            order.extend(f"inc:{i['id']}" for i in store.incidents if i["severity"] == sev)
    if len(stations) >= 2:  # feedsInto paths between mentioned stations (BFS, stored direction only)
        nodes = universe["stations"]
        for a in stations:
            for b in stations:
                if a == b:
                    continue
                prev, seen, dq = {}, {a}, deque([a])
                while dq:
                    cur = dq.popleft()
                    for o in g.objects(nodes[cur], c.IM.feedsInto):
                        oid = str(g.value(o, c.IM.identifier))
                        if oid not in seen:
                            seen.add(oid)
                            prev[oid] = cur
                            dq.append(oid)
                if b in prev:
                    path, x = [], b
                    while x != a:
                        path.append(f"fact:feeds:{prev[x]}->{x}")
                        x = prev[x]
                    order.extend(reversed(path))
    for st in stations:
        order.append(f"fact:hasSensor:{st}")
    order = [k for k in order if k in units]
    return fill(order, units)


def run(run_dir: Path, overlay_dir: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=False)
    store = it.IncidentStore(run_dir, overlay_dir)
    universe = build_units(store)
    keys = sorted(universe["units"])
    bm25 = BM25([universe["units"][k]["text"] for k in keys])
    qs = questions(store)
    rows = []
    for q in qs:
        missing = [r for r in q["required"] if r not in universe["units"]]
        if missing:
            raise ValueError(f"required evidence missing from universe: {q['id']} {missing}")
        req = list(dict.fromkeys(q["required"]))
        systems = {"LLM": ([], 0), "TextRAG": text_rag(q["question"], universe, bm25, keys),
                   "GraphRAG": graph_rag(q["question"], store, universe)}
        row = {"id": q["id"], "source": q["source"], "question": q["question"], "required": req}
        for name, (ctx, used) in systems.items():
            hit = [r for r in req if r in ctx]
            row[name] = {"recall": len(hit) / len(req), "all": len(hit) == len(req), "tokens": used,
                         "missing": [r for r in req if r not in ctx], "context": ctx}
        rows.append(row)
    summary = {}
    for name in ("LLM", "TextRAG", "GraphRAG"):
        summary[name] = {"questions": len(rows),
                         "macro_recall": round(sum(r[name]["recall"] for r in rows) / len(rows), 4),
                         "all_recalled": sum(r[name]["all"] for r in rows),
                         "mean_tokens": round(sum(r[name]["tokens"] for r in rows) / len(rows), 1)}
    meta = {"engine_seal_sha256": v.digest(v.encoded(store.seal)), "overlay_seal": store.overlay_seal,
            "kg_sha256": v.digest((v.REPO_ROOT / c.KG_REL).read_bytes()), "budget_tokens": BUDGET,
            "units": {k: sum(u["kind"] == k for u in universe["units"].values())
                      for k in sorted({u["kind"] for u in universe["units"].values()})},
            "labels_read": False, "api_calls": 0,
            "code_sha256": v.digest(Path(__file__).read_bytes())}
    v.write(out / "questions.json", qs)
    v.write(out / "results.json", {"meta": meta, "summary": summary, "rows": rows})
    v.write(out / "complete.json", {p.name: v.digest(p.read_bytes()) for p in sorted(out.iterdir()) if p.is_file()})
    return {"meta": meta, "summary": summary, "rows": rows}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run", type=Path, default=it.ENGINE_RUN)
    p.add_argument("--overlay", type=Path, default=it.ENGINE_OVERLAY)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    res = run(a.run, a.overlay, a.out)
    print(json.dumps(res["summary"], ensure_ascii=False, indent=2))
    for r in res["rows"]:
        print(f"{r['id']:10} LLM {r['LLM']['recall']:.2f}  Text {r['TextRAG']['recall']:.2f}  Graph {r['GraphRAG']['recall']:.2f}"
              f"  text-miss {r['TextRAG']['missing']}  graph-miss {r['GraphRAG']['missing']}")


if __name__ == "__main__":
    main()
