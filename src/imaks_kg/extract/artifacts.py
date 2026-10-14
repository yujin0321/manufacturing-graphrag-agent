"""④ 2단계 산출물 쓰기: kg_build/extraction/<run_id>/ 아래 predictions, rules_all, rules_valid, flags, run_summary, eval_meta.

- predictions.jsonl: 평가기(imaks_kg.eval)가 읽는 형식. 점검 플래그가 붙은 규칙도 숨기지 않고 모두 넣는다.
  (condition과 action이 모두 빈 규칙만 평가기가 읽을 수 없어 뺀다. rules_all에는 남고 flags.csv에 표시한다.)
- rules_all.jsonl: 플래그·위치·해시 포함 전체. rules_valid.jsonl: KG 적재용(제외 플래그가 없는 규칙).
- 사람이 고친 결과는 이 파일들을 바꾸지 않고 review.py가 rules_final.jsonl로 따로 만든다.
- JSON 키에는 누수 점검 가드의 금지 키 이름(state를 뜻하는 흔한 단어 등)을 쓰지 않는다: 'outcome' 같은 이름을 쓴다.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from imaks_kg.common.io_utils import write_csv, write_json, write_jsonl
from imaks_kg.extract.validator import (ALL_FLAGS, EXCLUDING_FLAGS, FLAG_EMPTY, FLAG_EVIDENCE, FLAG_WS, ValidationResult,
                                        apply_duplicate_flags, apply_identifier_suffixes, rule_is_valid_for_kg)
from imaks_kg.settings import KG_BUILD

EXTRACTION_ROOT = KG_BUILD / "extraction"
FLAG_COLUMNS = ["run_id", "document_id", "rule_identifier", "rule_index", "flag", "scope", "chunk_id", "detail",
                "source_quote", "excluded_from_kg"]


@dataclass
class DocOutcome:
    document_id: str
    part: int = 1
    n_parts: int = 1
    outcome: str = ""                 # validated | schema_failed | call_failed
    request_meta: dict = field(default_factory=dict)
    provider: str = ""
    model_id: str = ""
    call_id: str = ""
    cache_hit: bool = False
    response_file: str = ""
    response_sha256: str = ""
    failure_reason: str = ""
    validation_attempts: int = 0
    validation: ValidationResult | None = None


def run_dir(run_id: str, root: Path | None = None) -> Path:
    return Path(root or EXTRACTION_ROOT) / run_id


def file_sha256(path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def prediction_record(rule: dict, run_id: str) -> dict:
    """평가기 형식(document_id, class, condition, action, identifier, sensors, model) + 추가 필드(평가기는 무시).
    run_id는 넣지 않는다: 같은 응답을 다시 검증하면 바이트까지 같아야 한다(실행 이름은 폴더가 가진다)."""
    return {"document_id": rule["document_id"], "class": rule["class"], "condition": rule["condition"],
            "action": rule["action"], "identifier": rule["identifier"], "sensors": list(rule["sensors"]),
            "model": rule["model"], "provider": rule["provider"], "ruleSeverity": rule["ruleSeverity"],
            "printed_rule_id": rule["printed_rule_id"], "action_targets": list(rule["action_targets"]),
            "flags": list(rule["flags"])}


def collect_rules(outcomes: list, reserved=()) -> list:
    rules = []
    for o in outcomes:
        if o.validation is not None and o.validation.accepted:
            rules += o.validation.rules
    apply_identifier_suffixes(rules, reserved)   # 같은 문서의 중복 인쇄 ID -> <ID>-2, -3 (먼저)
    apply_duplicate_flags(rules)                  # 그래도 남은 충돌(예: 다른 문서의 같은 ID)만 표시
    return rules


def flag_rows(run_id: str, outcomes: list, rules: list) -> list:
    rows = []
    for r in rules:
        quote = next((e["source_quote"] for e in r["evidence"]), "")
        chunk = next((e["chunk_id"] for e in r["evidence"]), "")
        excl = "yes" if not rule_is_valid_for_kg(r) else "no"
        for f in r["flags"]:
            details = [d["detail"] for d in r["flag_details"] if d["flag"] == f]
            rows.append([run_id, r["document_id"], r["identifier"], r["rule_index"], f, "rule", chunk,
                         " / ".join(details)[:300], quote[:300], excl if f in EXCLUDING_FLAGS else "no"])
    for o in outcomes:
        if o.validation is None:
            continue
        for d in o.validation.doc_flags:
            rows.append([run_id, o.document_id, "", "", d["flag"], "chunk", d.get("chunkId", ""), d["detail"], "", "no"])
        for e in o.validation.blocking_errors[:5]:
            rows.append([run_id, o.document_id, "", "", e.split(":", 1)[0], "response", "", e[:300], "", "yes"])
    for o in outcomes:
        if o.validation is None and o.outcome == "call_failed":
            rows.append([run_id, o.document_id, "", "", "call_failed", "response", "", o.failure_reason[:300], "", "yes"])
    return rows


def quote_stats(rules: list) -> dict:
    """인용 일치 집계. quote_match_rate = 인용이 일치한 evidence 수 / 전체 evidence 수(예선 1차 관문의 '인용 일치율').
    일치하지 않은 evidence = evidence_not_found 플래그가 붙은 evidence. 공백 조정(quote_whitespace_adjusted)은 일치로 센다."""
    total = not_found = adjusted = 0
    for r in rules:
        total += len(r["evidence"])
        nf = {d["evidenceIndex"] for d in r["flag_details"] if d["flag"] == FLAG_EVIDENCE}
        ws = {d["evidenceIndex"] for d in r["flag_details"] if d["flag"] == FLAG_WS}
        not_found += len(nf)
        adjusted += len(ws - nf)
    return {"evidence_total": total, "evidence_matched": total - not_found, "evidence_not_found": not_found,
            "quote_whitespace_adjusted": adjusted,
            "quote_match_rate": (round((total - not_found) / total, 6) if total else None)}


def summarize(run_id: str, outcomes: list, rules: list, preds: list, valid: list, *, run_mode: str, mock: bool,
              meta: dict, validation_retries: int) -> dict:
    by_flag = Counter(f for r in rules for f in r["flags"])
    models = sorted({o.model_id for o in outcomes if o.model_id})
    qs = quote_stats(rules)
    docs = []
    for o in outcomes:
        docs.append({"document_id": o.document_id, "part": o.part, "n_parts": o.n_parts, "outcome": o.outcome,
                     "provider": o.provider, "model": o.model_id, "cache_hit": o.cache_hit,
                     "response_sha256": o.response_sha256, "validation_attempts": o.validation_attempts,
                     "failure_reason": o.failure_reason,
                     "blocking_errors": (o.validation.blocking_errors[:5] if o.validation else []),
                     "n_rules": (len(o.validation.rules) if o.validation and o.validation.accepted else 0)})
    return {"run_id": run_id, "mock": mock, "run_mode": run_mode,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "prompt_version": meta.get("prompt_version"), "prompt_sha256": meta.get("prompt_sha256"),
            "schema_sha256": meta.get("schema_sha256"), "example_sha256": meta.get("example_sha256"),
            "requested_model": meta.get("requested_model"), "models_used": models,
            "validation_retries_allowed": validation_retries,
            "counts": {"requests": len(outcomes),
                       "responses_accepted": sum(1 for o in outcomes if o.validation and o.validation.accepted),
                       "rules_all": len(rules), "predictions": len(preds), "rules_valid": len(valid),
                       "rules_excluded_from_kg": len(rules) - len(valid),
                       "rules_with_any_flag": sum(1 for r in rules if r["flags"])},
            "by_flag": {f: by_flag.get(f, 0) for f in ALL_FLAGS},
            "quote_stats": qs, "quote_match_rate": qs["quote_match_rate"],
            "quote_whitespace_adjusted": qs["quote_whitespace_adjusted"],
            "by_class": dict(sorted(Counter(r["class"] for r in rules).items())),
            "by_document": dict(sorted(Counter(r["document_id"] for r in rules).items())),
            "by_model": dict(sorted(Counter(r["model"] for r in rules).items())),
            "documents": docs}


def write_outputs(out_dir: Path, run_id: str, outcomes: list, *, run_mode: str, mock: bool, meta: dict,
                  validation_retries: int = 0, allow_overwrite_predictions: bool = False,
                  reserved_identifiers=()) -> dict:
    """산출물 6종을 쓴다. predictions.jsonl이 이미 있고 내용이 다르면 덮어쓰지 않고 오류(고정된 자동 추출 결과 보호)."""
    out_dir = Path(out_dir)
    rules = collect_rules(outcomes, reserved_identifiers)
    preds = [prediction_record(r, run_id) for r in rules if FLAG_EMPTY not in r["flags"]]
    valid = [r for r in rules if rule_is_valid_for_kg(r)]
    pred_path = out_dir / "predictions.jsonl"
    new_pred_bytes = "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in preds).encode("utf-8")
    if pred_path.is_file() and pred_path.read_bytes() != new_pred_bytes and not allow_overwrite_predictions:
        raise FileExistsError(f"{pred_path.name}이 이미 있고 내용이 다릅니다. 자동 추출 결과는 덮어쓰지 않습니다. "
                              "다른 run_id(--out-run-id)로 쓰세요.")
    write_jsonl(pred_path, preds)
    write_jsonl(out_dir / "rules_all.jsonl", rules)
    write_jsonl(out_dir / "rules_valid.jsonl", valid)
    write_csv(out_dir / "flags.csv", FLAG_COLUMNS, flag_rows(run_id, outcomes, rules))
    summary = summarize(run_id, outcomes, rules, preds, valid, run_mode=run_mode, mock=mock, meta=meta,
                        validation_retries=validation_retries)
    write_json(out_dir / "run_summary.json", summary)
    requested = sorted({o.request_meta.get("requested_model", "") for o in outcomes if o.request_meta} - {""})
    eval_meta = {"run_id": run_id, "mock": mock, "run_mode": run_mode, "prompt_version": meta.get("prompt_version"),
                 "prompt_sha256": meta.get("prompt_sha256"), "example_sha256": meta.get("example_sha256"),
                 "schema_sha256": meta.get("schema_sha256"), "requested_models": requested,
                 "actual_models": sorted({f"{o.provider}/{o.model_id}" for o in outcomes if o.model_id}),
                 "predictions_file": "predictions.jsonl"}
    write_json(out_dir / "eval_meta.json", eval_meta)
    return summary
