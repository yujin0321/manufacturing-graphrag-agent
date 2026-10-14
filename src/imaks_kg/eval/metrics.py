"""F1_content 계산 (정의서 3~6장). 정답 파일은 읽지 않는다 - 이미 읽은 GoldRule 목록을 받는다."""
from collections import Counter, defaultdict
from typing import Sequence

import numpy as np

from imaks_kg.eval.gold import GoldRule
from imaks_kg.eval.match import assign, cosine_matrix
from imaks_kg.eval.predictions import Prediction
from imaks_kg.eval.text import similarity_text

# 문서 종류 판별 규칙은 이 한 곳에만 둔다.
SOP_PREFIX = "SOP-"
DATASHEET_PREFIX = "DS-"
SENSITIVITY_THRESHOLDS = (0.5, 0.6, 0.7)


def is_sop(doc_id: str) -> bool:
    return doc_id.startswith(SOP_PREFIX)


def is_datasheet(doc_id: str) -> bool:
    return doc_id.startswith(DATASHEET_PREFIX)


def prf(tp: int, n_pred: int, n_gold: int) -> dict:
    p = tp / n_pred if n_pred else 0.0
    r = tp / n_gold if n_gold else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return {"tp": tp, "fp": n_pred - tp, "fn": n_gold - tp, "n_pred": n_pred, "n_gold": n_gold,
            "precision": p, "recall": r, "f1": f1}


def f1_upper_bound(n_pred: int, n_gold: int) -> float:
    """예측 N건, 정답 G건에서 1:1 매칭으로 가능한 최대 F1 = 2*min/(N+G)."""
    return 2 * min(n_pred, n_gold) / (n_pred + n_gold) if (n_pred + n_gold) else 0.0


class _Context:
    def __init__(self, preds: Sequence[Prediction], gold: Sequence[GoldRule], embedder):
        self.preds, self.gold = list(preds), list(gold)
        texts = ([similarity_text(p.condition, p.action) for p in self.preds]
                 + [similarity_text(g.condition, g.action) for g in self.gold])
        emb = np.asarray(embedder.encode(texts), dtype=np.float64)
        if emb.shape[0] != len(texts):
            raise ValueError("임베더가 문장 수와 다른 행 수를 돌려줬습니다")
        pe, ge = emb[:len(self.preds)], emb[len(self.preds):]
        self.p_idx, self.g_idx = defaultdict(list), defaultdict(list)
        for i, p in enumerate(self.preds):
            self.p_idx[p.doc].append(i)
        for j, g in enumerate(self.gold):
            self.g_idx[g.doc].append(j)
        self.sims = {}
        for d in set(self.p_idx) | set(self.g_idx):
            self.sims[d] = cosine_matrix(pe[self.p_idx[d]], ge[self.g_idx[d]])

    def match(self, threshold: float, pred_docs: set, gold_docs: set):
        """문서별로 매칭. 반환: {doc: [(pred 전역 인덱스, gold 전역 인덱스, 유사도)]}"""
        out = {}
        for d in sorted(pred_docs | gold_docs):
            if d not in self.sims:
                out[d] = []
                continue
            sim = self.sims[d]
            if d not in pred_docs or d not in gold_docs:
                out[d] = []
                continue
            out[d] = [(self.p_idx[d][i], self.g_idx[d][j], s) for i, j, s in assign(sim, threshold)]
        return out


def _count(ctx: _Context, matches: dict, pred_docs: set, gold_docs: set) -> dict:
    n_pred = sum(len(ctx.p_idx[d]) for d in pred_docs)
    n_gold = sum(len(ctx.g_idx[d]) for d in gold_docs)
    tp = sum(len(v) for v in matches.values())
    res = prf(tp, n_pred, n_gold)
    tp_c = sum(1 for v in matches.values() for pi, gj, _ in v if ctx.preds[pi].cls == ctx.gold[gj].cls)
    c = prf(tp_c, n_pred, n_gold)
    res["class_aware"] = {k: c[k] for k in ("tp", "precision", "recall", "f1")}
    res["pred_gold_ratio"] = (n_pred / n_gold) if n_gold else None
    res["f1_upper_bound"] = f1_upper_bound(n_pred, n_gold)
    return res


def evaluate(preds: Sequence[Prediction], gold: Sequence[GoldRule], embedder, threshold: float = 0.6,
             processed_docs: set | None = None, sensitivity: Sequence[float] = SENSITIVITY_THRESHOLDS):
    """반환: (metrics dict, 문서별 행 목록, 매칭 행 목록). 정답 문장은 어떤 반환값에도 넣지 않는다."""
    ctx = _Context(preds, gold, embedder)
    sop_pred_docs = {p.doc for p in ctx.preds if is_sop(p.doc)}
    gold_docs = {g.doc for g in ctx.gold}
    if processed_docs is None:
        processed = set(sop_pred_docs)
    else:
        processed = {d for d in processed_docs}
    out_of_scope = [p for p in ctx.preds if not is_sop(p.doc)]

    # 주 보고: SOP 예측 전체 vs 정답 전체
    main_matches = ctx.match(threshold, sop_pred_docs, gold_docs)
    main = _count(ctx, main_matches, sop_pred_docs, gold_docs)

    # 처리 범위 보고
    proc_pred = sop_pred_docs & processed
    proc_gold = gold_docs & processed
    proc_matches = ctx.match(threshold, proc_pred, proc_gold)
    proc = _count(ctx, proc_matches, proc_pred, proc_gold)
    proc["documents"] = sorted(processed)

    # 문서별
    doc_rows = []
    for d in sorted((sop_pred_docs | gold_docs) | {x for x in processed}):
        pd_, gd_ = ({d} & sop_pred_docs), ({d} & gold_docs)
        m = {d: main_matches.get(d, [])}
        r = _count(ctx, m, pd_, gd_)
        doc_rows.append({"document_id": d, "processed": d in processed, "n_pred": r["n_pred"], "n_gold": r["n_gold"],
                         "tp": r["tp"], "fp": r["fp"], "fn": r["fn"], "precision": r["precision"],
                         "recall": r["recall"], "f1": r["f1"], "class_aware_f1": r["class_aware"]["f1"]})

    # 혼동표 (매칭된 쌍, 주 보고 기준)
    conf = defaultdict(Counter)
    for v in main_matches.values():
        for pi, gj, _ in v:
            conf[ctx.gold[gj].cls][ctx.preds[pi].cls] += 1
    confusion = {g: dict(sorted(c.items())) for g, c in sorted(conf.items())}

    # 임계값 민감도 (보고만)
    sens = {}
    for t in sensitivity:
        mm = ctx.match(t, sop_pred_docs, gold_docs)
        r = _count(ctx, mm, sop_pred_docs, gold_docs)
        sens[f"{t:g}"] = {k: r[k] for k in ("tp", "fp", "fn", "precision", "recall", "f1")}
        sens[f"{t:g}"]["class_aware_f1"] = r["class_aware"]["f1"]

    # 센서 집합 일치 (예측에 필드가 있을 때만)
    s_eval = s_ok = 0
    for v in main_matches.values():
        for pi, gj, _ in v:
            p, g = ctx.preds[pi], ctx.gold[gj]
            if p.sensors is not None:
                s_eval += 1
                s_ok += set(p.sensors) == ({g.sensor} if g.sensor else set())
    aux = {
        "sensor_set": ({"evaluable_pairs": s_eval, "agree": s_ok, "ratio": s_ok / s_eval}
                       if s_eval else "skipped: 예측에 sensors 필드 없음"),
    }

    # 매칭 행 (정답 문장 없음)
    rows = []
    matched_p, matched_g = set(), set()
    for d, v in main_matches.items():
        for pi, gj, s in v:
            p, g = ctx.preds[pi], ctx.gold[gj]
            matched_p.add(pi)
            matched_g.add(gj)
            rows.append({"row_type": "matched", "document_id": d, "prediction_key": p.key,
                         "prediction_identifier": p.identifier or "", "gold_rule_id": g.rule_id,
                         "cosine": s, "valid": True, "class_match": p.cls == g.cls,
                         "pred_class": p.cls, "gold_class": g.cls})
    for pi, p in enumerate(ctx.preds):
        if not is_sop(p.doc):
            rows.append({"row_type": "out_of_scope", "document_id": p.doc, "prediction_key": p.key,
                         "prediction_identifier": p.identifier or "", "gold_rule_id": "", "cosine": "",
                         "valid": False, "class_match": "", "pred_class": p.cls, "gold_class": ""})
        elif pi not in matched_p:
            rows.append({"row_type": "unmatched_prediction", "document_id": p.doc, "prediction_key": p.key,
                         "prediction_identifier": p.identifier or "", "gold_rule_id": "", "cosine": "",
                         "valid": False, "class_match": "", "pred_class": p.cls, "gold_class": ""})
    for gj, g in enumerate(ctx.gold):
        if gj not in matched_g:
            rows.append({"row_type": "unmatched_gold", "document_id": g.doc, "prediction_key": "",
                         "prediction_identifier": "", "gold_rule_id": g.rule_id, "cosine": "", "valid": False,
                         "class_match": "", "pred_class": "", "gold_class": g.cls})

    metrics = {
        "threshold": threshold,
        "main_report": {"scope": "SOP 예측 전체 vs 정답 전체", **main},
        "processed_scope_report": {"scope": "처리한 문서의 예측 vs 그 문서의 정답", **proc},
        "out_of_scope_predictions": {"datasheet_prediction_count": sum(1 for p in out_of_scope if is_datasheet(p.doc)),
                                     "other_non_sop_prediction_count": sum(1 for p in out_of_scope if not is_datasheet(p.doc)),
                                     "counted_as_fp_in_main": False},
        "gold_rows_in_datasheet_documents": sum(1 for g in ctx.gold if is_datasheet(g.doc)),
        "class_confusion_matched_pairs": {"rows_gold_class_cols_pred_class": confusion},
        "threshold_sensitivity": sens,
        "agreement_on_matched_pairs": aux,
        "gt0009_binary": "N/A (7단계 이후 정의)",
    }
    return metrics, doc_rows, rows
