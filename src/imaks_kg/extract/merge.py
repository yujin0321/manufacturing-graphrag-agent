"""C 결과와 B 규칙(kg_build/rules_deterministic.ttl) 병합. work_log 2026-10-12 "MAINT 병합 기준"을 그대로 구현한다.

같은 규칙의 기준(둘 중 하나)
 (a) ruleIdInText를 정규화한 값(대문자, 공백 제거)이 B identifier와 같다
 (b) ruleIdInText가 없고, sourceQuote가 B 셀 Provenance와 같은 표(tableId)의 같은 행(rowIndex)을 인용한다
병합하면
- 새 Rule을 만들지 않는다. B 값(class, appliesToSensor, conditionText, responseText, priority)은 덮어쓰지 않는다.
- LLM 출처는 B 규칙에 "재확인" Provenance로 덧붙인다(to_rdf.py).
- 값이 다르면(class, 센서 집합, 공정, 조건·조치 문구) merge_conflicts.csv에 두 값과 출처를 남긴다.
ID가 다른 규칙은 수치·문구가 비슷해도 합치지 않는다. ruleIdInText가 있는데 B에 없는 ID면 (b)도 적용하지 않는다.

병합하지 않은 후보의 identifier
- ruleIdInText(원문 표기 그대로)가 있고 다른 후보·B와 겹치지 않으면 그 값
- 여러 후보가 같은 ruleIdInText를 내면: 그 ID가 자기 청크의 rule_id인(rule 청크) 후보 하나만 그 ID를 쓰고, 나머지는
  위치 기반 ID. 그런 후보가 정확히 하나가 아니면 모두 위치 기반 ID(결정적).
- 그 밖에는 위치 기반 ID <chunk_id>:r<n>(= candidate_id)
마지막에 B + C의 identifier 중복이 0인지 확인하고, 있으면 ExtractError로 멈춘다.
"""
from rdflib import RDF, Graph

from imaks_kg.extract.common import ExtractError
from imaks_kg.extract.schema import RULE_CLASSES
from imaks_kg.kg.naming import IM

CONFLICT_FIELDS = ("conflict_id", "candidate_id", "chunk_id", "b_identifier", "merge_basis", "field",
                   "llm_value", "b_value", "llm_source", "b_source")


def norm_id(s):
    return "".join(str(s).split()).upper()


def _one(g, s, p, default=""):
    vals = sorted(str(o) for o in g.objects(s, p))
    if len(vals) > 1:
        raise ExtractError(f"B 규칙 {s}의 {p}가 여러 개: {vals}")
    return vals[0] if vals else default


def load_b_rules(rules_ttl, seed):
    """B 규칙 색인. seed: common.seed_ids 결과(센서 IRI → identifier, 센서 → 공정)."""
    g = Graph().parse(str(rules_ttl), format="turtle")
    sensor_by_iri = {iri: sid for sid, iri in _sensor_iris(seed).items()}
    rules, by_norm, by_row = {}, {}, {}
    for cls in RULE_CLASSES:
        for s in sorted(g.subjects(RDF.type, IM[cls])):
            ident = _one(g, s, IM.identifier)
            if not ident or ident in rules:
                raise ExtractError(f"B identifier가 없거나 중복: {s} {ident!r}")
            sensors = sorted(sensor_by_iri[o] for o in g.objects(s, IM.appliesToSensor))
            targets = sorted(str(_one(g, o, IM.identifier)) for o in g.objects(s, IM.actionTarget))
            if targets:
                stations, st_src = targets, "actionTarget"
            else:
                stations = sorted({seed["sensor_station"][x] for x in sensors})
                st_src = "appliesToSensor 센서의 소속 공정(hasSensor)"
            rows = set()
            for p in g.objects(s, IM.hasProvenance):
                t, r = _one(g, p, IM.tableId), _one(g, p, IM.rowIndex)
                if t and r:
                    rows.add((t, int(r)))
            rules[ident] = {"identifier": ident, "iri": str(s), "class": cls, "sensors": sensors,
                            "stations": stations, "stations_source": st_src,
                            "conditionText": _one(g, s, IM.conditionText),
                            "responseText": _one(g, s, IM.responseText), "priority": _one(g, s, IM.priority),
                            "rows": sorted(rows)}
            if norm_id(ident) in by_norm:
                raise ExtractError(f"B identifier 정규화 값이 겹침: {ident}")
            by_norm[norm_id(ident)] = ident
            for row in rows:
                if row in by_row and by_row[row] != ident:
                    raise ExtractError(f"B 두 규칙이 같은 표 행을 출처로 가짐: {row}")
                by_row[row] = ident
    return {"rules": rules, "by_norm": by_norm, "by_row": by_row, "graph": g}


def _sensor_iris(seed):
    g = seed["graph"]
    out = {}
    for s in g.subjects(RDF.type, IM.Sensor):
        out[str(next(g.objects(s, IM.identifier)))] = s
    return out


def _llm_source(c):
    p = c["provenance"]
    loc = (f"{p['tableId']} row {p['rowIndex']} col {','.join(str(x) for x in p['colIndex'])}"
           if "tableId" in p else f"char {p['charStart']}-{p['charEnd']}")
    return f"{p['doc_id']} p{p['page']} {loc}; chunk {p['chunk_id']}; textSha256 {p['textSha256']}"


def _b_source(b):
    rows = "; ".join(f"{t} row {r}" for t, r in b["rows"]) or "(표 행 출처 없음)"
    return f"kg_build/rules_deterministic.ttl {b['iri']}; {rows}"


def _row_key(c):
    p = c["provenance"]
    return (p["tableId"], p["rowIndex"]) if "tableId" in p else None


def compare(c, b):
    """병합 건의 값 차이 [(field, llm 값, B 값)]. 문구는 문자열 그대로 비교한다(통일하지 않음)."""
    diffs = []
    if c["class"] != b["class"]:
        diffs.append(("class", c["class"], b["class"]))
    if sorted(c["sensors"]) != b["sensors"]:
        diffs.append(("sensors", "|".join(sorted(c["sensors"])), "|".join(b["sensors"])))
    if sorted(c["targetStations"]) != b["stations"]:
        diffs.append(("stations", "|".join(sorted(c["targetStations"])),
                      "|".join(b["stations"]) + f" ({b['stations_source']})"))
    if c["conditionText"] != b["conditionText"]:
        diffs.append(("conditionText", c["conditionText"], b["conditionText"]))
    if c["responseText"] != b["responseText"]:
        diffs.append(("responseText", c["responseText"], b["responseText"]))
    return diffs


def merge(candidates, b, chunks_by_id):
    """후보 목록 → (병합 후 레코드 목록, 충돌 행 목록). 입력 후보는 바꾸지 않는다."""
    records, conflicts = [], []
    for c in candidates:
        r = dict(c)
        r["notes"] = []
        rid = c["ruleIdInText"]
        row = _row_key(c)
        basis, b_ident = "", ""
        if rid is not None and norm_id(rid) in b["by_norm"]:
            basis, b_ident = "id", b["by_norm"][norm_id(rid)]
            if row is not None and row in b["by_row"] and b["by_row"][row] != b_ident:
                r["notes"].append(f"인용한 표 행은 B {b['by_row'][row]}의 행")
                conflicts.append(_conflict(c, b["rules"][b_ident], basis, "tableRow",
                                           f"{row[0]} row {row[1]}", f"{b['by_row'][row]}의 행"))
        elif rid is None and row is not None and row in b["by_row"]:
            basis, b_ident = "table_row", b["by_row"][row]
        if basis:
            br = b["rules"][b_ident]
            r["merge"] = {"merged": True, "basis": basis, "b_identifier": b_ident, "b_iri": br["iri"]}
            r["identifier"], r["identifier_source"] = b_ident, "b_rule"
            for field, lv, bv in compare(c, br):
                conflicts.append(_conflict(c, br, basis, field, lv, bv))
        else:
            r["merge"] = {"merged": False, "basis": "", "b_identifier": "", "b_iri": ""}
        records.append(r)
    _assign_identifiers(records, b, chunks_by_id)
    check_unique(records, b)
    conflicts.sort(key=lambda x: x["conflict_id"])
    return records, conflicts


def _conflict(c, br, basis, field, lv, bv):
    return {"conflict_id": f"{c['candidate_id']}#{field}", "candidate_id": c["candidate_id"],
            "chunk_id": c["chunk_id"], "b_identifier": br["identifier"], "merge_basis": basis, "field": field,
            "llm_value": lv, "b_value": bv, "llm_source": _llm_source(c), "b_source": _b_source(br)}


def _assign_identifiers(records, b, chunks_by_id):
    free = [r for r in records if not r["merge"]["merged"]]
    by_id = {}
    for r in free:
        if r["ruleIdInText"] is not None:
            by_id.setdefault(r["ruleIdInText"], []).append(r)
    for r in free:
        rid = r["ruleIdInText"]
        if rid is None:
            r["identifier"], r["identifier_source"] = r["candidate_id"], "position"
            continue
        group = by_id[rid]
        if len(group) == 1:
            r["identifier"], r["identifier_source"] = rid, "ruleIdInText"
            continue
        owners = [x for x in group if chunks_by_id[x["chunk_id"]].get("rule_id") == rid]
        if len(owners) == 1 and owners[0] is r:
            r["identifier"], r["identifier_source"] = rid, "ruleIdInText"
        else:
            r["identifier"], r["identifier_source"] = r["candidate_id"], "position"
            r["notes"].append(f"ruleIdInText {rid}를 여러 후보가 내서 위치 기반 ID를 씀")


def check_unique(records, b):
    """병합 후 identifier 중복 0 확인: C 단독 규칙끼리, C 단독 규칙과 B 규칙."""
    seen = {}
    for r in records:
        if r["merge"]["merged"]:
            continue
        ident = r["identifier"]
        if ident in seen:
            raise ExtractError(f"병합 후 identifier 중복: {ident} ({seen[ident]}, {r['candidate_id']})")
        if ident in b["rules"] or norm_id(ident) in b["by_norm"]:
            raise ExtractError(f"C 규칙 identifier가 B와 겹침: {ident}")
        seen[ident] = r["candidate_id"]
