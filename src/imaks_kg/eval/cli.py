"""평가 실행과 describe-gold.

PYTHONPATH=src python -m imaks_kg.eval --predictions P.jsonl --out-dir evaluation/run1
PYTHONPATH=src python -m imaks_kg.eval describe-gold [--gold CSV]
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from imaks_kg.common.io_utils import write_csv, write_json
from imaks_kg.eval import gold as gold_mod
from imaks_kg.eval.embed import DEFAULT_REVISION, MODEL_NAME, SbertEmbedder
from imaks_kg.eval.lock import LOCK_NAME, write_lock
from imaks_kg.eval.metrics import evaluate
from imaks_kg.eval.predictions import load_predictions
from imaks_kg.settings import EVALUATION_DIR, REPO_ROOT

DEFINITION_PATH = REPO_ROOT / "docs" / "eval_definition_F1_content.md"
DOC_COLUMNS = ["document_id", "processed", "n_pred", "n_gold", "tp", "fp", "fn", "precision", "recall", "f1",
               "class_aware_f1"]
ASSIGN_COLUMNS = ["row_type", "document_id", "prediction_key", "prediction_identifier", "gold_rule_id", "cosine",
                  "valid", "class_match", "pred_class", "gold_class"]


def run_evaluation(predictions: Path, out_dir: Path, gold_path: Path = gold_mod.GOLD_PATH, threshold: float = 0.6,
                   meta_path: Path | None = None, revision: str = DEFAULT_REVISION, embedder=None,
                   gold_loader=gold_mod.load_gold, manifest: Path = gold_mod.MANIFEST_PATH,
                   definition: Path = DEFINITION_PATH, processed_docs: set | None = None) -> dict:
    predictions, out_dir = Path(predictions), Path(out_dir)
    known = gold_mod.known_doc_ids(manifest)
    preds = load_predictions(predictions, known)  # 정답은 아직 읽지 않는다
    meta = json.loads(Path(meta_path).read_text(encoding="utf-8")) if meta_path else None
    if embedder is None:
        embedder = SbertEmbedder(MODEL_NAME, revision)

    # 1) lock을 먼저 쓴다  2) 그 다음에만 정답을 읽는다
    lock = write_lock(out_dir, predictions, definition, embedder.model_name, embedder.revision, threshold, meta)
    gold = gold_loader(Path(gold_path), known)
    gold_sha = gold_mod.file_sha256(Path(gold_path))

    metrics, doc_rows, assign_rows = evaluate(preds, gold, embedder, threshold, processed_docs)
    loaded = embedder.loaded_revision()
    metrics["inputs"] = {
        "predictions_sha256": lock["predictions_sha256"],
        "gold_file": Path(gold_path).name,
        "gold_sha256": gold_sha,
        "gold_rows": len(gold),
        "prediction_rows": len(preds),
        "definition_sha256": lock["definition_sha256"],
    }
    metrics["embedding"] = {
        "model": embedder.model_name,
        "revision_requested": embedder.revision,
        "revision_loaded": loaded if loaded else "unverified (확인 불가)",
        "revision_loaded_matches_requested": (loaded == embedder.revision) if loaded else None,
        "libraries": lock["libraries"],
    }
    write_json(out_dir / "metrics.json", metrics)
    write_csv(out_dir / "document_scores.csv", DOC_COLUMNS, [[r[c] for c in DOC_COLUMNS] for r in doc_rows])
    write_csv(out_dir / "assignments.csv", ASSIGN_COLUMNS, [[r[c] for c in ASSIGN_COLUMNS] for r in assign_rows])
    return metrics


def _summary(m: dict) -> str:
    a, p = m["main_report"], m["processed_scope_report"]
    return (f"주 보고: TP {a['tp']} FP {a['fp']} FN {a['fn']}  P {a['precision']:.3f} R {a['recall']:.3f} "
            f"F1_content {a['f1']:.3f}\n"
            f"처리 범위: TP {p['tp']} FP {p['fp']} FN {p['fn']}  F1_content {p['f1']:.3f}\n"
            f"분류까지 일치 F1 {a['class_aware']['f1']:.3f}; 범위 밖(데이터시트) 예측 "
            f"{m['out_of_scope_predictions']['datasheet_prediction_count']}건")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "describe-gold":
        ap = argparse.ArgumentParser(prog="imaks_kg.eval describe-gold")
        ap.add_argument("--gold", default=str(gold_mod.GOLD_PATH))
        args = ap.parse_args(argv[1:])
        print(json.dumps(gold_mod.describe_gold(Path(args.gold)), ensure_ascii=False, indent=2))
        return 0
    ap = argparse.ArgumentParser(prog="imaks_kg.eval", description="F1_content 평가")
    ap.add_argument("--predictions", required=True)
    ap.add_argument("--out-dir", default=None, help="새 폴더 (기본: evaluation/f1_content_<UTC 시각>)")
    ap.add_argument("--gold", default=str(gold_mod.GOLD_PATH))
    ap.add_argument("--threshold", type=float, default=0.6)
    ap.add_argument("--meta", default=None, help="프롬프트·Example·스키마 해시, 모델 목록 JSON")
    ap.add_argument("--model-revision", default=DEFAULT_REVISION)
    ap.add_argument("--processed-docs", default=None, help="쉼표 구분. 기본: 예측이 있는 SOP 문서")
    args = ap.parse_args(argv)
    out = Path(args.out_dir) if args.out_dir else EVALUATION_DIR / datetime.now(timezone.utc).strftime("f1_content_%Y%m%dT%H%M%SZ")
    processed = {d.strip() for d in args.processed_docs.split(",") if d.strip()} if args.processed_docs else None
    try:
        m = run_evaluation(Path(args.predictions), out, Path(args.gold), args.threshold,
                           Path(args.meta) if args.meta else None, args.model_revision, processed_docs=processed)
    except Exception as e:  # lock 불일치, 형식 오류, 알 수 없는 문서 등은 메시지와 함께 중단
        print(f"중단: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    print(_summary(m))
    print(f"결과: {out}  ({LOCK_NAME} 포함)")
    return 0
