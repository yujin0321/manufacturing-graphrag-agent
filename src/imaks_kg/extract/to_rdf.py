"""④ 추출 규칙 -> 온톨로지에 맞는 TTL 변환 + SHACL(S7·S8 포함) 확인.

입력: kg_build/extraction/<run_id>/rules_final.jsonl(사람 검토 반영; 없으면 rules_valid.jsonl)과 ③ 산출물 instances.ttl.
출력(같은 폴더): kg_with_rules.ttl(③ 인스턴스 + 규칙), rules_only.ttl, triple_sources.jsonl(③ 장부와 같은 형식),
                to_rdf_report.json, (충돌 시) id_collisions.json.
- IRI 방식은 ③과 같다: inst:<identifier>(Station·Sensor·Document·MAINT 규칙). 규칙 identifier는 퍼센트 인코딩.
- seed 정비 규칙 8개와 LLM이 뽑은 정비 규칙은 병합하지 않는다. ③ 노드와 identifier가 충돌한 규칙은 접두 없이 TTL에서만
  제외하고 identifier_conflicts.json에 기록한다(나머지는 정상 변환). 입력 규칙끼리의 중복은 여전히 중단한다.
- 위치를 확정하지 못한 근거(position_unresolved 등)는 Provenance로 올리지 않는다. 확정 근거가 하나도 없는 규칙은
  S8(Provenance 1개 이상)을 깨므로 TTL에서 빼고 보고서에 이유를 적는다.
- SHACL: run_shacl.py와 같은 설정(ont_graph=ontology.ttl, shapes.ttl, 추론 없음).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import quote

from rdflib import RDF, XSD, Graph, Literal, URIRef

from imaks_kg.common.io_utils import write_json, write_jsonl, write_text
from imaks_kg.extract.artifacts import file_sha256, run_dir
from imaks_kg.kg.convert_seed import IM, INST, Ledger, check_ledger_complete, ledger_records
from imaks_kg.settings import KG_BUILD, REPO_ROOT, rel

ONTOLOGY = REPO_ROOT / "ontology_v1" / "ontology.ttl"
SHAPES = REPO_ROOT / "ontology_v1" / "shapes.ttl"
CLASS_IRI = {c: IM[c] for c in ("OperationalRule", "ThresholdRule", "MaintenanceRule", "AccessRule")}


class IdCollisionError(RuntimeError):
    """LLM 규칙 identifier가 ③ 인스턴스(또는 서로)와 충돌."""


def iri_local(identifier: str) -> str:
    return quote(identifier, safe="-._~")


def load_rules(d: Path, source: str = "auto") -> tuple:
    final, valid = d / "rules_final.jsonl", d / "rules_valid.jsonl"
    if source == "final" or (source == "auto" and final.is_file()):
        path = final
    else:
        path = valid
    if not path.is_file():
        raise FileNotFoundError(f"{path.name}이 없습니다: {d.name}")
    rules = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return rules, path


def find_collisions(rules: list, base: Graph) -> list:
    out = []
    base_ids = {}
    for s, o in base.subject_objects(IM.identifier):
        base_ids.setdefault(str(o), []).append(s)
    seen: dict = {}
    for r in rules:
        ident = r["identifier"]
        iri = INST[iri_local(ident)]
        existing_types = sorted({str(t).rsplit("#", 1)[-1] for t in base.objects(iri, RDF.type)})
        if existing_types or (iri, None, None) in base:
            out.append({"identifier": ident, "document_id": r["document_id"], "kind": "iri_exists_in_instances",
                        "existing_types": existing_types})
        elif ident in base_ids:
            out.append({"identifier": ident, "document_id": r["document_id"], "kind": "identifier_exists_in_instances",
                        "existing_nodes": [str(x) for x in base_ids[ident]]})
        if ident in seen:
            out.append({"identifier": ident, "document_id": r["document_id"], "kind": "duplicate_in_input",
                        "first_document_id": seen[ident]})
        seen.setdefault(ident, r["document_id"])
    return out


def _evidence_source(r: dict, p: dict, pred_rel: str, pred_sha: str, src_rel: str, src_sha: str, run_id: str) -> dict:
    ev = {"documentId": r["document_id"], "chunkId": p["chunkId"], "page": p["page"], "textSha256": p["textSha256"],
          "runId": run_id, "predictionsFile": pred_rel, "predictionsSha256": pred_sha,
          "rulesFile": src_rel, "rulesSha256": src_sha}
    if "charStart" in p:
        ev.update({"charStart": p["charStart"], "charEnd": p["charEnd"]})
    else:
        ev.update({"tableId": p["tableId"], "rowIndex": p["rowIndex"], "colIndex": p["colIndex"]})
    return ev


def _prov_iri(identifier: str, p: dict) -> URIRef:
    key = json.dumps([identifier, p["chunkId"], p["textSha256"], p.get("charStart"), p.get("tableId"),
                      p.get("rowIndex"), p.get("colIndex")], ensure_ascii=False)
    return INST["prov_llm_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]]


def build_rules_graph(rules: list, base: Graph, *, pred_rel: str, pred_sha: str, src_rel: str, src_sha: str,
                      run_id: str) -> tuple:
    """(규칙 트리플만 담은 Graph, Ledger, 제외 목록, 버려진 ID 목록)"""
    new = Graph()
    L = Ledger(new)
    excluded, dropped = [], []
    for r in rules:
        resolved = [e["provenance"] for e in r["evidence"] if e.get("provenance") and e["provenance"].get("resolved")]
        if not resolved:
            excluded.append({"identifier": r["identifier"], "reason": "확정된 출처 위치가 없어 S8(Provenance 1개 이상)을 만족할 수 없음"})
            continue
        doc_iri = INST[r["document_id"]]
        if (doc_iri, RDF.type, IM.Document) not in base:
            raise ValueError(f"③ 인스턴스에 Document가 없습니다: {r['document_id']}")
        s = INST[iri_local(r["identifier"])]
        evs = [_evidence_source(r, p, pred_rel, pred_sha, src_rel, src_sha, run_id) for p in resolved]
        L.add(s, RDF.type, CLASS_IRI[r["class"]], evs)
        L.add(s, IM.identifier, Literal(r["identifier"]), evs)
        if r["condition"].strip():
            L.add(s, IM.conditionText, Literal(r["condition"]), evs)
        if r["action"].strip():
            L.add(s, IM.responseText, Literal(r["action"]), evs)
        if r["ruleSeverity"].strip():
            L.add(s, IM.ruleSeverity, Literal(r["ruleSeverity"]), evs)
        L.add(s, IM.extractionMethod, Literal("LLM"), evs)
        L.add(s, IM.sourceDocument, doc_iri, evs)
        bad = []
        for sid in dict.fromkeys(r["sensors"]):
            n = INST[sid]
            if (n, RDF.type, IM.Sensor) in base:
                L.add(s, IM.appliesToSensor, n, evs)
            else:
                bad.append(sid)
        for tid in dict.fromkeys(r["action_targets"]):
            n = INST[tid]
            if (n, RDF.type, IM.Station) in base:
                L.add(s, IM.actionTarget, n, evs)
            else:
                bad.append(tid)
        if bad:
            dropped.append({"identifier": r["identifier"], "ids_not_linked": bad})
        for p in dict.fromkeys(json.dumps(x, sort_keys=True) for x in resolved):
            p = json.loads(p)
            pi = _prov_iri(r["identifier"], p)
            pe = [_evidence_source(r, p, pred_rel, pred_sha, src_rel, src_sha, run_id)]
            L.add(pi, RDF.type, IM.Provenance, pe)
            L.add(pi, IM.sourceKind, Literal("document"), pe)
            L.add(pi, IM.page, Literal(p["page"], datatype=XSD.positiveInteger), pe)
            if "charStart" in p:
                L.add(pi, IM.charStart, Literal(p["charStart"], datatype=XSD.nonNegativeInteger), pe)
                L.add(pi, IM.charEnd, Literal(p["charEnd"], datatype=XSD.nonNegativeInteger), pe)
            else:
                L.add(pi, IM.tableId, Literal(p["tableId"]), pe)
                L.add(pi, IM.rowIndex, Literal(p["rowIndex"], datatype=XSD.positiveInteger), pe)
                L.add(pi, IM.colIndex, Literal(p["colIndex"], datatype=XSD.positiveInteger), pe)
                if p.get("bbox"):
                    L.add(pi, IM.bbox, Literal(p["bbox"]), pe)
            L.add(pi, IM.sourceQuote, Literal(p["sourceQuote"]), pe)
            L.add(pi, IM.textSha256, Literal(p["textSha256"]), pe)
            L.add(s, IM.hasProvenance, pi, pe)
    return new, L, excluded, dropped


def shacl_check(data: Graph, ontology: Path = ONTOLOGY, shapes: Path = SHAPES) -> tuple:
    """(적합 여부, 위반 메시지 목록). run_shacl.py와 같은 설정: ont_graph=ontology, 추론 없음."""
    from pyshacl import validate
    sg = Graph().parse(str(shapes))
    og = Graph().parse(str(ontology))
    conforms, rg, _ = validate(data, shacl_graph=sg, ont_graph=og, inference="none")
    SH = "http://www.w3.org/ns/shacl#"
    msgs = sorted({str(o) for o in rg.objects(None, URIRef(SH + "resultMessage"))})
    return bool(conforms), msgs


def convert(run_id: str, *, source: str = "auto", instances_dir: Path | None = None, out_root: Path | None = None,
            ontology: Path = ONTOLOGY, shapes: Path = SHAPES) -> dict:
    d = run_dir(run_id, out_root)
    inst = Path(instances_dir) if instances_dir else KG_BUILD / "instances"
    rules, src_path = load_rules(d, source)
    base = Graph().parse(str(inst / "instances.ttl"))
    col = find_collisions(rules, base)
    dup = [c for c in col if c["kind"] == "duplicate_in_input"]
    if dup:   # 입력 안의 중복은 예전처럼 중단(검토 단계에서 edited_identifier로 해결)
        write_json(d / "id_collisions.json", {"run_id": run_id, "collisions": dup,
                                              "note": "입력 규칙끼리 identifier가 겹쳐 중단했습니다."})
        raise IdCollisionError(f"입력 안의 identifier 중복 {len(dup)}건: "
                               + ", ".join(sorted({c['identifier'] for c in dup})[:8]))
    # ③ seed 노드와 겹치는 규칙은 병합·접두 없이 TTL에서만 제외하고 기록한다(rules_*와 predictions에는 영향 없음).
    seed_hits = {c["identifier"]: c for c in col}
    conflicts, kept = [], []
    for r in rules:
        c = seed_hits.get(r["identifier"])
        if c is None:
            kept.append(r)
            continue
        ev = next((e for e in r["evidence"]), {"chunk_id": ""})
        nodes = ([str(INST[iri_local(r["identifier"])])] if c["kind"] == "iri_exists_in_instances"
                 else c.get("existing_nodes", []))
        conflicts.append({"identifier": r["identifier"], "seed_node_iris": nodes, "document_id": r["document_id"],
                          "chunk_id": ev["chunk_id"], "kind": c["kind"],
                          "reason": "③ seed 노드와 identifier가 겹쳐 병합·접두 없이 TTL에서 제외(별도 노드 정책)"})
    write_json(d / "identifier_conflicts.json", {"run_id": run_id, "count": len(conflicts), "conflicts": conflicts})
    rules_all_input = len(rules)
    rules = kept
    pred = d / "predictions.jsonl"
    pred_sha, src_sha = file_sha256(pred), file_sha256(src_path)
    pred_rel = rel(pred) if pred.resolve().is_relative_to(REPO_ROOT) else pred.name
    src_rel = rel(src_path) if src_path.resolve().is_relative_to(REPO_ROOT) else src_path.name
    new, L, excluded, dropped = build_rules_graph(rules, base, pred_rel=pred_rel, pred_sha=pred_sha,
                                                  src_rel=src_rel, src_sha=src_sha, run_id=run_id)
    check_ledger_complete(new, L.sources)
    full = Graph()
    for t in base:
        full.add(t)
    for t in new:
        full.add(t)
    for g in (full, new):
        g.bind("im", IM)
        g.bind("inst", INST)
        g.bind("xsd", XSD)
    write_text(d / "kg_with_rules.ttl", full.serialize(format="turtle"))
    write_text(d / "rules_only.ttl", new.serialize(format="turtle"))
    write_jsonl(d / "triple_sources.jsonl", ledger_records(L.sources))
    base_conforms, _ = shacl_check(base, ontology, shapes)
    conforms, msgs = shacl_check(full, ontology, shapes)
    report = {"run_id": run_id, "source": src_path.name, "source_sha256": src_sha, "predictions_sha256": pred_sha,
              "input_rules": rules_all_input, "identifier_conflicts": len(conflicts), "rules_in_ttl": len(rules) - len(excluded), "excluded": excluded,
              "ids_not_linked": dropped, "triples_added": len(new), "triples_total": len(full),
              "base_instances_conform": base_conforms,
              "shacl": {"conforms": conforms, "messages": msgs[:20], "ont_graph": "ontology_v1/ontology.ttl",
                        "shapes": "ontology_v1/shapes.ttl", "inference": "none"}}
    write_json(d / "to_rdf_report.json", report)
    return report


def cli(run_id: str, source: str, instances: str | None) -> int:
    try:
        rep = convert(run_id, source=source, instances_dir=Path(instances) if instances else None)
    except IdCollisionError as e:
        print(f"중단(입력 안의 ID 중복): {e}", file=sys.stderr)
        return 2
    s = rep["shacl"]
    print(f"TTL: 규칙 {rep['rules_in_ttl']}/{rep['input_rules']}개, 추가 트리플 {rep['triples_added']}개 "
          f"(제외 {len(rep['excluded'])}개, ID 충돌 제외 {rep['identifier_conflicts']}개)")
    print("SHACL(S7·S8 포함, 추론 없음): " + ("적합" if s["conforms"] else "위반"))
    for m in s["messages"][:5]:
        print("  -", m)
    return 0 if s["conforms"] else 1
