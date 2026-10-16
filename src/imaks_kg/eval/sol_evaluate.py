"""Evaluate frozen Sol predictions under the two user-supplied definitions."""
import argparse
import hashlib
import json
import platform
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np

from imaks_kg.common.io_utils import write_json, write_text
from imaks_kg.eval.team_protocol.embed import SbertEmbedder, MODEL_NAME, DEFAULT_REVISION
from imaks_kg.eval.team_protocol.gold import load_gold, known_doc_ids, file_sha256
from imaks_kg.eval.team_protocol.metrics import evaluate
from imaks_kg.eval.team_protocol.predictions import load_predictions
from imaks_kg.kg_build.preprocessed_abox import PreprocessedLayout
from imaks_kg.settings import REPO_ROOT

DEFINITIONS = [REPO_ROOT / "docs" / n for n in
               ["eval_definition_F1_content.md", "eval_definition_team_summary.md"]]


def versions():
    return {"python": platform.python_version(), **{n: version(n) for n in
            ["openai", "numpy", "scipy", "sentence-transformers", "transformers", "torch", "jsonschema"]}}


class RecordingEmbedder:
    def __init__(self, base, out):
        self.base, self.out, self.count = base, out, 0

    def encode(self, texts):
        values = self.base.encode(texts)
        self.count += 1
        np.save(self.out / f"embeddings_{self.count}.npy", values, allow_pickle=False)
        write_json(self.out / f"embedding_inputs_{self.count}.json", {
            "text_count": len(texts),
            "texts_sha256": hashlib.sha256(json.dumps(texts, ensure_ascii=False).encode()).hexdigest(),
            "vectors_sha256": file_sha256(self.out / f"embeddings_{self.count}.npy"),
        })
        return values


def report_markdown(metrics, docs, meta):
    main = metrics["main_report"]
    lines = ["# 수민 GPT-6.1 Sol 자동 추출·평가 결과", "",
             "고정된 자동 추출 결과의 개발 평가다. 사람 검토와 인과 추론 성능 평가는 포함하지 않는다.", "",
             "## 실행", "",
             f"- 요청 모델: {meta['requested_model']}; 실제 모델: {', '.join(meta['actual_models'])}",
             f"- 프롬프트·Example·스키마 버전: {meta['version']}",
             f"- 처리 문서: {', '.join(meta['documents'])}",
             f"- 문서별 응답 수신 시각(UTC): {json.dumps(meta['response_times_utc'], ensure_ascii=False)}",
             f"- 정답 노출 이력: {meta['answer_exposure_history']}",
             f"- 자동 예측 전체 {meta['prediction_count']}건; 근거 검증 통과 후보 KG {meta['kg_eligible_count']}건",
             "- 검증 플래그가 있는 규칙도 자동 예측 평가에 포함한다. 조건·조치·분류·건수를 평가 후 수정하지 않았다.",
             "", "## 주 결과", "", "| 항목 | 값 |", "|---|---:|"]
    for label, value in [("SOP 예측", main["n_pred"]), ("정답", main["n_gold"]),
                         ("TP / FP / FN", f"{main['tp']} / {main['fp']} / {main['fn']}"),
                         ("Precision", f"{main['precision']:.6f}"), ("Recall / Coverage", f"{main['recall']:.6f}"),
                         ("F1_content", f"{main['f1']:.6f}"),
                         ("처리 범위 F1", f"{metrics['processed_scope_report']['f1']:.6f}"),
                         ("분류까지 일치 F1", f"{main['class_aware']['f1']:.6f}"),
                         ("데이터시트 예측(점수 밖)", metrics["out_of_scope_predictions"]["datasheet_prediction_count"]),
                         ("예측/정답 비율", f"{main['pred_gold_ratio']:.6f}"),
                         ("건수 기반 이론적 F1 상한", f"{main['f1_upper_bound']:.6f}"),
                         ("GT-0009 binary", "N/A — 이후 이벤트 단계")]:
        lines.append(f"| {label} | {value} |")
    lines += ["", "## 문서별", "", "| 문서 | 예측 | 정답 | TP | FP | FN | F1 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for r in docs:
        lines.append(f"| {r['document_id']} | {r['n_pred']} | {r['n_gold']} | {r['tp']} | {r['fp']} | {r['fn']} | {r['f1']:.6f} |")
    lines += ["", "## 보조 지표", "", "| 임계값 | TP | FP | FN | F1 |", "|---|---:|---:|---:|---:|"]
    for t, r in metrics["threshold_sensitivity"].items():
        lines.append(f"| {t} | {r['tp']} | {r['fp']} | {r['fn']} | {r['f1']:.6f} |")
    lines += ["", f"문장 형식 민감도: 단순 연결 F1 {main['f1']:.6f}, Condition/Action 형식 F1 {metrics['text_format_sensitivity']['labeled_f1']:.6f}.",
              "주 점수는 임계 0.6, 단순 연결 형식으로 고정한다.", "",
              "매칭된 쌍의 센서 집합 일치 (빈 집합끼리도 일치, 표기 정규화 없음):", "",
              "```json", json.dumps(metrics["agreement_on_matched_pairs"], ensure_ascii=False, indent=2), "```", "",
              "매칭된 쌍의 클래스 혼동표 (행 정답, 열 예측):", "", "```json",
              json.dumps(metrics["class_confusion_matched_pairs"], ensure_ascii=False, indent=2), "```", "",
              "## 구현과 재현성", "",
              "전처리 문서 → 문서별 단일 모델 구조화 응답 → 원문 근거 검증 → 자동 예측 고정 → 사전 평가 잠금 → 원본 정답 읽기 → SBERT/Hungarian 평가 순서다.",
              "두 정의서·예측·프롬프트·Example·스키마·요청·응답·평가 코드·실행 라이브러리 정보를 잠금과 메타데이터에 저장했다.",
              f"임베딩: {MODEL_NAME}, revision {DEFAULT_REVISION}, CPU. 정규화 코사인, 문서 내 유효 쌍 수 우선, 유효 유사도 합 차순위, 클래스 제한 없음.",
              "예측과 정답의 비교 문장은 condition + 공백 + action이다. 데이터시트는 FP로 세지 않는다. 분할 예측을 임의 병합하지 않는다.",
              f"예측 SHA-256: `{metrics['inputs']['prediction_sha256']}`",
              f"정답 SHA-256: `{metrics['inputs']['gold_sha256']}`", "",
              "## 사용량", "", "```json", json.dumps(meta["usage"], ensure_ascii=False, indent=2), "```", "",
              "## 해석의 한계와 남은 작업", "",
              "F1_content는 의미 유사도 기반이다. 수치·단위·부등호 정확도나 새 인과관계 발견을 보증하지 않는다. 원문에 있지만 정답에 없는 규칙도 FP가 될 수 있다.",
              "SOP와 데이터시트 충돌 수치는 출처별 예측에 보존한다. 개별 수치 대조 및 MAINT 매핑 감사는 별도 검토 대상이며 이 자동 점수만으로 완료를 주장하지 않는다.",
              "사람의 1·2차 검토는 대기 상태다. 후보 KG의 SHACL 적합 여부는 별도 shacl_report.txt로 확인한다. 자동 추출 점수와 사람 수정 결과를 혼합하지 않는다.",
              "팀원 보고서의 점수는 재현하지 않았으며 이 결과로 팀원 간 우열을 주장하지 않는다. 개별 매칭·임베딩·정답은 로컬 전용이다.", ""]
    return "\n".join(lines)


def run(build_dir, gold_path, out, preprocessed=None, embedder=None):
    build_dir, out, gold_path = Path(build_dir), Path(out), Path(gold_path)
    layout = PreprocessedLayout.detect(preprocessed)
    meta_path = build_dir / "extraction_summary.json"
    meta = json.loads(meta_path.read_text())
    if meta.get("state") != "complete" or meta.get("actual_models") != ["gpt-6.1-sol"]:
        raise ValueError("Only a completed single-model Sol experiment is accepted")
    pred_path = build_dir / "predictions.jsonl"
    if file_sha256(pred_path) != meta["prediction_sha256"]:
        raise ValueError("Predictions changed after extraction freeze")
    known = known_doc_ids(layout.doc_manifest)
    preds = load_predictions(pred_path, known)
    if len(preds) != meta["prediction_count"] or any(p.model != "gpt-6.1-sol" for p in preds):
        raise ValueError("Prediction count or model provenance mismatch")
    if not set(meta["documents"]) <= known:
        raise ValueError("Unknown processed document")
    base = embedder or SbertEmbedder()
    # Loading the fixed embedding model does not read any reference answers.
    if embedder is None:
        base._load()
        if base.loaded_revision() != DEFAULT_REVISION:
            raise ValueError("Embedding revision cannot be verified")
    out.mkdir(parents=True, exist_ok=True)
    lock_path = out / "pre_evaluation_lock.json"
    if any(out.iterdir()):
        raise ValueError("Evaluation directory must be empty; use a new directory")
    lock = {"written_at_utc": datetime.now(timezone.utc).isoformat(), "threshold": 0.6,
            "prediction_sha256": file_sha256(pred_path),
            "definition_sha256": {p.name: file_sha256(p) for p in DEFINITIONS},
            "metadata_sha256": file_sha256(meta_path), "extraction_metadata": meta,
            "embedding_model": base.model_name, "embedding_revision": base.revision,
            "libraries": versions(), "processed_documents": meta["documents"],
            "evaluation_code_sha256": {str(p.relative_to(Path(__file__).parent)): file_sha256(p)
                                      for p in Path(__file__).parent.rglob("*.py")}}
    with lock_path.open("x", encoding="utf-8") as f:
        json.dump(lock, f, ensure_ascii=False, indent=2)
    # First reference-answer file read occurs strictly after lock creation.
    gold = load_gold(gold_path, known)
    if len(gold) != 86 or any(not g.doc.startswith("SOP-") for g in gold):
        raise ValueError("Protocol requires 86 original SOP reference rows")
    gold_hash = file_sha256(gold_path)
    recorder = RecordingEmbedder(base, out)
    processed = {d for d in meta["documents"] if d.startswith("SOP-")}
    metrics, docs, matches = evaluate(preds, gold, recorder, 0.6, processed)
    alt, _, _ = evaluate(preds, gold, recorder, 0.6, processed,
                         formatter=lambda c, a: f"Condition: {c}\nAction: {a}")
    metrics["text_format_sensitivity"] = {"labeled_f1": alt["main_report"]["f1"],
                                          "delta_from_main": alt["main_report"]["f1"] - metrics["main_report"]["f1"]}
    metrics["inputs"] = {"prediction_sha256": lock["prediction_sha256"], "gold_sha256": gold_hash,
                         "gold_by_document": dict(Counter(g.doc for g in gold))}
    if file_sha256(pred_path) != lock["prediction_sha256"] or file_sha256(gold_path) != gold_hash:
        raise ValueError("Inputs changed during evaluation")
    write_json(out / "metrics.json", metrics)
    write_json(out / "matches.local.json", matches)
    write_json(out / "document_scores.json", docs)
    write_text(out / "report.md", report_markdown(metrics, docs, meta))
    return metrics


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--build-dir", required=True)
    p.add_argument("--gold", required=True, help="Original reference CSV, read only after pre-evaluation lock")
    p.add_argument("--out", required=True)
    p.add_argument("--preprocessed")
    a = p.parse_args(argv)
    result = run(a.build_dir, a.gold, a.out, a.preprocessed)
    print(json.dumps(result["main_report"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
