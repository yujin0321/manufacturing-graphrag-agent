"""C 결과 → RDF.

  PYTHONPATH=src .venv/Scripts/python.exe -m imaks_kg.extract.to_rdf --run-dir extraction/runs/<run_id> [--out-dir kg_build]

출력(기본 kg_build/)
- rules_llm.ttl: 검토를 마친 결과(final.jsonl)
- rules_llm_prereview.ttl: 검토 전 결과(merged.jsonl, 비교용)
- seed_plus_rules_llm.ttl: seed.ttl + rules_deterministic.ttl + rules_llm.ttl 합본(SHACL 확인용)

표현
- B에 병합하지 않은 규칙: inst:rule_llm_<identifier 토큰>, 클래스(4분류), identifier, conditionText, responseText,
  ruleSeverity(원문에 있을 때만), extractionMethod "llm", appliesToSensor, actionTarget, sourceDocument, hasProvenance.
- B에 병합된 규칙: 새 Rule을 만들지 않고 B 규칙 IRI에 hasProvenance로 "재확인" Provenance만 덧붙인다(같은 파일).
  B의 다른 트리플은 이 파일에 쓰지 않는다(덮어쓰기 없음).
- Provenance: inst:prov_llm_<run_id 토큰>_<candidate_id 토큰>. sourceKind "document", page, sourceQuote,
  textSha256, extractionMethod "llm", 그리고 text·rule 청크는 charStart·charEnd(쪽 좌표), table 청크는 tableId·rowIndex·
  colIndex(인용이 걸친 열마다)·bbox.
  청크 ID·실행 ID·모델 ID 전용 속성은 ontology.ttl에 없어 IRI(실행 ID·후보 ID=청크 ID+번호)에만 담고,
  모델 ID는 실행 폴더 meta.json과 final.jsonl(served_model)에 있다(보고서의 온톨로지 미비 사항).
"""
import argparse
import re
import sys
from pathlib import Path

from rdflib import RDF, XSD, Graph, Literal, URIRef

from imaks_kg.common.io_utils import write_text
from imaks_kg.extract import guard, ledger
from imaks_kg.extract.common import ExtractError, disp, read_jsonl
from imaks_kg.kg.naming import IM, INST, SOURCE_KIND_DOCUMENT, document_iri, entity_iri
from imaks_kg.settings import KG_BUILD, RULES_LLM_PREREVIEW_TTL, RULES_LLM_TTL, SEED_RULES_LLM_TTL

EXTRACTION_LLM = "llm"


def _tok(text):
    return re.sub(r"[^A-Za-z0-9_]", "_", str(text))


def prov_iri(run_id, candidate_id):
    return INST[f"prov_llm_{_tok(run_id)}_{_tok(candidate_id)}"]


def llm_rule_iri(identifier):
    return INST[f"rule_llm_{_tok(identifier)}"]


def build_graph(records, run_id, b, seed):
    """레코드 목록(final 또는 merged) → Graph. b: merge.load_b_rules 결과, seed: common.seed_ids 결과."""
    g = Graph()
    g.bind("im", IM)
    g.bind("inst", INST)
    g.bind("xsd", XSD)
    used_rule_iris, used_prov = {}, set()
    for r in records:
        p = r["provenance"]
        pv = prov_iri(run_id, r["candidate_id"])
        if pv in used_prov:
            raise ExtractError(f"Provenance IRI 중복: {pv}")
        used_prov.add(pv)
        g.add((pv, RDF.type, IM.Provenance))
        g.add((pv, IM.sourceKind, Literal(SOURCE_KIND_DOCUMENT)))
        g.add((pv, IM.page, Literal(int(p["page"]), datatype=XSD.positiveInteger)))
        if "tableId" in p:
            g.add((pv, IM.tableId, Literal(p["tableId"])))
            g.add((pv, IM.rowIndex, Literal(int(p["rowIndex"]), datatype=XSD.positiveInteger)))
            for c in p["colIndex"]:
                g.add((pv, IM.colIndex, Literal(int(c), datatype=XSD.positiveInteger)))
            g.add((pv, IM.bbox, Literal(p["bbox"])))
        else:
            g.add((pv, IM.charStart, Literal(int(p["charStart"]), datatype=XSD.nonNegativeInteger)))
            g.add((pv, IM.charEnd, Literal(int(p["charEnd"]), datatype=XSD.nonNegativeInteger)))
        g.add((pv, IM.sourceQuote, Literal(p["sourceQuote"])))
        g.add((pv, IM.textSha256, Literal(p["textSha256"])))
        g.add((pv, IM.extractionMethod, Literal(EXTRACTION_LLM)))
        if r["merge"]["merged"]:
            br = b["rules"].get(r["merge"]["b_identifier"])
            if br is None or br["iri"] != r["merge"]["b_iri"]:
                raise ExtractError(f"{r['candidate_id']}: 병합 대상 B 규칙을 찾을 수 없음")
            g.add((URIRef(br["iri"]), IM.hasProvenance, pv))
            continue
        ident = r["identifier"]
        s = llm_rule_iri(ident)
        if s in used_rule_iris or str(s) in {x["iri"] for x in b["rules"].values()}:
            raise ExtractError(f"규칙 IRI 중복: {s} ({ident}, {used_rule_iris.get(s)})")
        used_rule_iris[s] = ident
        g.add((s, RDF.type, IM[r["class"]]))
        g.add((s, IM.identifier, Literal(ident)))
        if r["conditionText"]:
            g.add((s, IM.conditionText, Literal(r["conditionText"])))
        if r["responseText"]:
            g.add((s, IM.responseText, Literal(r["responseText"])))
        if r["ruleSeverity"]:
            g.add((s, IM.ruleSeverity, Literal(r["ruleSeverity"])))
        g.add((s, IM.extractionMethod, Literal(EXTRACTION_LLM)))
        for sid in sorted(r["sensors"]):
            if sid not in seed["sensors"]:
                raise ExtractError(f"{r['candidate_id']}: seed에 없는 센서 {sid}")
            g.add((s, IM.appliesToSensor, entity_iri(sid)))
        for st in sorted(r["targetStations"]):
            if st not in seed["stations"]:
                raise ExtractError(f"{r['candidate_id']}: seed에 없는 공정 {st}")
            g.add((s, IM.actionTarget, entity_iri(st)))
        g.add((s, IM.sourceDocument, document_iri(r["doc_id"])))
        g.add((s, IM.hasProvenance, pv))
    return g


def header(kind, run_id, meta):
    return (f"# 생성 파일: imaks_kg.extract.to_rdf (직접 고치지 말 것). {kind}\n"
            f"# run_id={run_id} model={meta.get('model')} prompt={meta.get('prompt_version')} "
            f"prompt_sha256={meta.get('prompt_sha256')}\n"
            "# 재확인 출처(B에 병합된 C 결과)는 B 규칙 IRI에 hasProvenance로만 붙인다. 스키마: ontology_v1/ontology.ttl\n\n")


def run(run_dir, out_dir=None, paths=None):
    """검사(입력이 추출 때와 같음 + 검토 기록 일치)를 모두 통과한 뒤에만 현재 seed·B를 새로 읽어 출력 3개를 쓴다.
    하나라도 틀리면 ExtractError, 출력 파일을 하나도 쓰지 않는다(기존 출력도 그대로)."""
    run_dir = Path(run_dir)
    out_dir = Path(out_dir) if out_dir else KG_BUILD
    meta = guard.check_inputs(run_dir, paths, "RDF 출력")
    guard.verify_review_record(run_dir)
    ledger.verify_run(run_dir, "RDF 출력")
    ctx = guard.load_current(paths)
    run_id = meta["run_id"]
    final_path = run_dir / "final.jsonl"
    g_final = build_graph(read_jsonl(final_path), run_id, ctx["b"], ctx["seed"])
    g_pre = build_graph(read_jsonl(run_dir / "merged.jsonl"), run_id, ctx["b"], ctx["seed"])
    final_txt = header("검토 후(final.jsonl)", run_id, meta) + g_final.serialize(format="turtle")
    pre_txt = header("검토 전(merged.jsonl, 비교용)", run_id, meta) + g_pre.serialize(format="turtle")
    merged = Graph()
    for prefix, ns in (("im", IM), ("inst", INST), ("xsd", XSD)):
        merged.bind(prefix, ns)
    for src in (ctx["seed"]["graph"], ctx["b"]["graph"], g_final):
        for t in src:
            merged.add(t)
    merged_txt = ("# 생성 파일: imaks_kg.extract.to_rdf (SHACL 확인용 합본, 직접 고치지 말 것)\n"
                  "# = kg_build/seed.ttl + kg_build/rules_deterministic.ttl + rules_llm.ttl\n\n"
                  + merged.serialize(format="turtle"))
    outs = {"final": out_dir / RULES_LLM_TTL.name, "prereview": out_dir / RULES_LLM_PREREVIEW_TTL.name,
            "merged": out_dir / SEED_RULES_LLM_TTL.name}
    # 읽은 뒤에도 입력·검토 기록이 그대로인지 한 번 더 확인하고 나서 쓴다
    guard.check_inputs(run_dir, paths, "RDF 출력")
    guard.verify_review_record(run_dir)
    ledger.verify_run(run_dir, "RDF 출력")
    for key, text in (("final", final_txt), ("prereview", pre_txt), ("merged", merged_txt)):
        write_text(outs[key], text)
    ledger.record_outputs(run_id, list(outs.values()))
    return {"outs": outs, "final_graph": g_final, "merged_graph": merged}


def main(argv=None):
    ap = argparse.ArgumentParser(description="C 결과 → kg_build/rules_llm.ttl")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out-dir", default=None, help=f"출력 폴더(기본 {disp(KG_BUILD)})")
    args = ap.parse_args(argv)
    try:
        res = run(args.run_dir, args.out_dir)
    except ExtractError as e:
        print(f"멈춤: {e}")
        return 1
    print("산출물:", *(disp(p) for p in res["outs"].values()))
    print(f"rules_llm 트리플 {len(res['final_graph'])}, 합본 트리플 {len(res['merged_graph'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
