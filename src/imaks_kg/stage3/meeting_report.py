"""Generate a meeting brief from saved actual results; never invent missing metrics."""
import argparse
from collections import Counter
import json
from pathlib import Path

from .common import OUT, REPO_ROOT, read_jsonl


def make_report(run, evaluation):
    result = json.loads(evaluation.read_text(encoding="utf8"))
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf8"))
    predictions = read_jsonl(run / "predictions.jsonl")
    responses = read_jsonl(run / "responses.jsonl")
    issues = read_jsonl(run / "validation_issues.jsonl")
    graph = json.loads((OUT / "enriched_summary.json").read_text(encoding="utf8"))
    score = result["content"]
    def percent(v):
        return f"{100*v:.2f}%"
    lines = ["# 10월 14일 회의 — KG 구축 및 첫 LLM 추출 평가", "",
        "## 발표할 핵심", "",
        f"지훈 안의 온톨로지에 맞춰 기존 KG를 변환하고, LLM으로 완료된 문서 {len(responses)}개에서 규칙 {len(predictions)}개를 자동 추출했다.",
        f"SOP 예측 {score['predicted']}개를 원본 정답 86건과 비교한 첫 내용 F1은 {percent(score['f1'])}이다.",
        "이 수치는 SBERT 의미 유사도 기반 개발 평가이며, 숫자·부등호의 완전한 정확도나 인과 발견 성능을 뜻하지 않는다.", "",
        "**부분 실행 결과**: 미완료 문서가 있으면 전체 추출 완료라고 주장하지 않는다.",
        "완료 문서: " + ", ".join(manifest.get('completed_documents', [])),
        "미완료 문서: " + ", ".join(manifest.get('missing_documents', [])), "",
        "## 실행 조건", "",
        "- 실제 모델: " + ", ".join(sorted({r["model"] for r in responses})),
        "- 입력: 전처리 문서 청크/표 + Station/Sensor 식별자 목록. 정답 파일과 seed 정비 문구는 미제공.",
        "- 프롬프트: 온톨로지 기반 Rule 분류 및 적용 센서/조치 대상/다중 근거 추출.",
        "- 사람에 의한 추출 내용 수정 없음. 정확 중복 제거 후 전체 예측으로 채점.",
        "- 채점: 같은 문서, Condition+Action, all-MiniLM-L6-v2, cosine >= 0.6, Hungarian 일대일 매칭.",
        "- 이전 대화에서 정답 일부를 확인했으므로 완전히 독립된 비공개 시험은 아니다.",
        f"- 추출 결과 해시: `{manifest['predictions_sha256']}`", "",
        "## 첫 정량 결과 — 전체 정답 86건 기준", "", "| 지표 | 값 |", "|---|---:|",
        f"| Precision | {percent(score['precision'])} |", f"| Recall | {percent(score['recall'])} |",
        f"| F1_content | {percent(score['f1'])} |", f"| TP / FP / FN | {score['tp']} / {score['fp']} / {score['fn']} |", "",
        f"미처리 SOP의 정답 {result.get('unprocessed_reference_count',0)}건도 전체 기준에서는 FN으로 포함한다. 이는 문서 처리 범위가 제한된 영향이다.", "",
        "## 처리 완료한 SOP 범위만의 점수", ""]
    scope = result.get('processed_document_scope', score)
    lines += [f"- 대상 정답: {scope['reference']}건", f"- Precision / Recall / F1: {percent(scope['precision'])} / {percent(scope['recall'])} / {percent(scope['f1'])}", "",
        f"- 규칙 분류까지 맞아야 하는 전체 F1: {percent(result.get('class_aware_content', score)['f1'])}",
        "내용만 매칭된 경우를 분류까지 정확하다고 해석하면 안 된다.", "",
        "아래 클래스별 표는 전체 86건 기준이다.", "",
        "| 규칙 분류 | 예측 | 정답 | 분류까지 일치한 TP | Precision | Recall | F1 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for cls, m in result["by_class"].items():
        lines.append(f"| {cls} | {m['predicted']} | {m['reference']} | {m['tp']} | {percent(m['precision'])} | {percent(m['recall'])} | {percent(m['f1'])} |")
    lines += ["", "클래스별 점수는 내용이 매칭돼도 분류가 다르면 정답으로 세지 않는다.", "",
              "## 문서별 자동 추출 수", "", "| 문서 | 규칙 |", "|---|---:|"]
    for doc, count in sorted(Counter(p["doc_id"] for p in predictions).items()):
        lines.append(f"| {doc} | {count} |")
    lines += ["", "데이터시트 예측은 SOP 정답 86건 평가에서 제외하고 KG 후보에 포함한다.", "",
              "## KG 및 출처 검증", "",
              f"- seed KG: 639트리플. LLM 결과 반영 후: {graph['triples']}트리플.",
              f"- SHACL 적합: {graph['shacl_conforms']} (추론 없음).",
              f"- 근거/형식 검증에서 제외된 기록: {len(issues)}개. 첫 내용 점수에는 숨기지 않고 포함.",
              f"- KG 적재 가능한 자동 규칙: {manifest['kg_eligible_predictions']}개.",
              "- seed 정비 규칙 8개와 LLM 규칙은 출처가 다른 별도 노드로 보존. 아직 의미상 병합하지 않음.",
              "- RDF 생성 완료. Neo4j용 Cypher 생성 완료, Neo4j 서버 적재는 미실행.", "",
              "## 검토할 실패 사례", ""]
    for r in result["unmatched_references"][:5]:
        lines.append(f"- 미매칭 정답 `{r['ruleId']}` ({r['source']}): {r['condition']} / {r['action']}")
    for r in result["unmatched_predictions"][:5]:
        lines.append(f"- 미매칭 예측 `{r['prediction_id']}`: {r['condition']} / {r['action']}")
    lines += ["", "미매칭은 유사도·규칙 분할 단위·정답 범위 차이에서도 발생하므로 모두 환각/누락으로 단정하지 않는다.",
              f"숫자 표현 차이 검토 신호: {sum(m['numeric_review_needed'] for m in result['matches'])}개 매칭.",
              "이 신호는 센서 이름의 숫자나 문장 표현에도 반응할 수 있어 사람이 확인해야 한다.", "",
              "## 분류 오류", ""]
    for key, count in result['class_confusion'].items():
        left, right = key.split(' -> ')
        if left != right:
            lines.append(f"- {left}로 추출했지만 정답 분류는 {right}: {count}건")
    lines += ["", "SOP-001의 수치 조건을 ThresholdRule로 분류하는 등 분류 기준 혼동이 관찰됐다. 첫 결과는 수정하지 않았다.", "",
              "## 다음 작업", "",
              "1. 실제 원문을 보며 숫자·부등호·단위·대상 연결 및 정답 오류 의심을 검토.",
              "2. SOP/데이터시트 충돌과 seed/LLM 정비 규칙 중복을 출처별로 정리.",
              "3. 이번 자동 추출 점수를 보존하고, 사람 검토본과 이후 개선 실험을 별도 기록.",
              "4. 공용/로컬 Neo4j를 정해 적재 및 조회 검증.", ""]
    destination = REPO_ROOT / "reports/stage3_meeting_impl.md"
    destination.write_text("\n".join(lines), encoding="utf8")
    print(destination)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--evaluation", type=Path, required=True)
    args = p.parse_args()
    make_report(args.run, args.evaluation)
