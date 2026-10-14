"""④ 2단계 실행 CLI.

  PYTHONPATH=src python -m imaks_kg.extract build-requests [--docs SOP-001,SOP-003 | --smoke]
  PYTHONPATH=src python -m imaks_kg.extract run [--docs ... | --smoke] [--config PATH]
  PYTHONPATH=src python -m imaks_kg.extract validate --run-id RUN [--out-run-id NEW]
  PYTHONPATH=src python -m imaks_kg.extract review-init --run-id RUN --stage 1|2 [--seed N]
  PYTHONPATH=src python -m imaks_kg.extract review-apply --run-id RUN
  PYTHONPATH=src python -m imaks_kg.extract to-rdf --run-id RUN

실제 호출은 설정 파일(config/extract.toml: 모델 id, 키 환경변수)이 있을 때만 일어난다.
`--mock-responses FILE`을 주면 mock 공급자만 쓰고 네트워크를 쓰지 않는다(시험용; 실행 이름이 mock-로 시작).
`run`은 (1) Example 검증 통과 기록, (2) scoring 모드의 모델 1개 조건, (3) 모델 id 채움을 모두 통과해야 시작한다.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from imaks_kg.common.io_utils import write_json
from imaks_kg.extract import artifacts
from imaks_kg.extract.artifacts import DocOutcome, run_dir
from imaks_kg.extract.callog import CallLogger, new_run_id
from imaks_kg.extract.cache import ResponseCache
from imaks_kg.extract.client import extract_call
from imaks_kg.extract.config import (DEFAULT_CONFIG_PATH, EXAMPLE_CONFIG_PATH, ConfigError, ExtractConfig, config_from_dict, load_config)
from imaks_kg.extract.docdata import DocumentStore, load_allowlist, sha256_text
from imaks_kg.extract.reserved_ids import load_reserved_identifiers
from imaks_kg.extract.request_builder import (ExampleError, SplitError, build_all, load_prompt_files,
                                              require_registered_example, smallest_doc)
from imaks_kg.extract.validator import VALIDATOR_NAME, validate_response
from imaks_kg.settings import REPO_ROOT


@dataclass
class RunResult:
    run_id: str
    out_dir: Path | None = None
    log_run_dir: Path | None = None
    outcomes: list = field(default_factory=list)
    built: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    build_only: bool = False


def _write_new(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as f:   # 응답 원문은 변경 불가: 같은 이름이 있으면 FileExistsError
        f.write(text.encode("utf-8"))


def _check_models_filled(config: ExtractConfig) -> None:
    chain = config.chain()
    if not chain:
        raise ConfigError("시도할 모델이 없습니다. config/extract.toml에 공급자와 모델 id를 채우세요.")
    empty = [f"{p.name}" for p, m in chain if not m.id.strip()]
    if empty:
        raise ConfigError("설정의 모델 id가 비어 있습니다(" + ", ".join(empty) + "). 모델 id를 채우기 전에는 실행하지 않습니다.")


def select_docs(store: DocumentStore, docs: list | None, smoke: bool) -> list:
    ids = list(docs) if docs else store.doc_ids()
    unknown = [d for d in ids if d not in store.chunks_by_doc]
    if unknown:
        raise ValueError("알 수 없는 문서 ID: " + ", ".join(unknown))
    return [smallest_doc(store, ids)] if smoke else ids


def _req_file_name(doc_id: str, part: int, n_parts: int) -> str:
    return f"{doc_id}.request.json" if n_parts == 1 else f"{doc_id}.part{part}of{n_parts}.request.json"


def _prepare(config: ExtractConfig, *, docs, smoke, registry_path, example_file, documents_dir, instances_dir,
             require_models: bool) -> tuple:
    if require_models:
        _check_models_filled(config)
        config.assert_run_mode()
    example_text, ex_sha = require_registered_example(example_file or config.example_file, registry_path)
    store = DocumentStore(documents_dir) if documents_dir else DocumentStore()
    allow = load_allowlist(instances_dir)
    ids = select_docs(store, docs, smoke)
    return store, allow, ids, example_text, ex_sha


def build_requests(config: ExtractConfig, *, docs=None, smoke=False, run_id=None, registry_path=None,
                   example_file=None, documents_dir=None, instances_dir=None) -> RunResult:
    """요청 파일만 쓴다(API 호출 없음). 파일은 config.log_dir/requests/<run_id>/ 아래(git 제외 폴더)."""
    run_id = run_id or new_run_id()
    store, allow, ids, ex_text, ex_sha = _prepare(config, docs=docs, smoke=smoke, registry_path=registry_path,
                                                  example_file=example_file, documents_dir=documents_dir,
                                                  instances_dir=instances_dir, require_models=False)
    req_dir = Path(config.log_dir) / "requests" / run_id
    try:
        built = build_all(ids, store, allow, config, example_text=ex_text, example_sha256=ex_sha)
    except SplitError as e:
        req_dir.mkdir(parents=True, exist_ok=True)
        write_json(req_dir / "split_error.json", {"run_id": run_id, "message": str(e)})
        raise
    for b in built:
        write_json(req_dir / _req_file_name(b.doc_id, b.part, b.n_parts),
                   {"meta": b.meta, "system": b.request.system, "prompt": b.request.prompt})
    return RunResult(run_id, None, req_dir, [], built, {}, True)


def run_extraction(config: ExtractConfig, *, docs=None, smoke=False, run_id=None, mock=False, providers=None,
                   registry_path=None, example_file=None, out_root=None, documents_dir=None, instances_dir=None,
                   validation_retries=1, sleep=time.sleep, rng=random.random, clock=time.monotonic) -> RunResult:
    store, allow, ids, ex_text, ex_sha = _prepare(config, docs=docs, smoke=smoke, registry_path=registry_path,
                                                  example_file=example_file, documents_dir=documents_dir,
                                                  instances_dir=instances_dir, require_models=True)
    run_id = run_id or (("mock-" if mock else "") + new_run_id())
    req_dir = Path(config.log_dir) / "requests" / run_id
    try:
        built = build_all(ids, store, allow, config, example_text=ex_text, example_sha256=ex_sha)
    except SplitError as e:   # 아무 호출도 하기 전에 중단하고 기록
        req_dir.mkdir(parents=True, exist_ok=True)
        write_json(req_dir / "split_error.json", {"run_id": run_id, "message": str(e)})
        raise
    for b in built:
        write_json(req_dir / _req_file_name(b.doc_id, b.part, b.n_parts),
                   {"meta": b.meta, "system": b.request.system, "prompt": b.request.prompt})
    _, schema = load_prompt_files()
    logger = CallLogger(config.log_dir, run_id, config.key_env_names())
    cache = ResponseCache(config.cache_dir)
    resp_dir = Path(config.log_dir) / "extract_runs" / run_id / "responses"
    outcomes = []
    for b in built:
        o = DocOutcome(b.doc_id, b.part, b.n_parts, request_meta=b.meta)
        attempt = 0
        while True:
            attempt += 1
            res = extract_call(config, b.request, providers=providers, logger=logger, cache=cache, run_id=run_id,
                               sleep=sleep, rng=rng, clock=clock)
            o.provider, o.model_id, o.call_id, o.cache_hit = res.provider, res.model_id, res.call_id, res.cache_hit
            if res.status != "success":
                o.outcome, o.failure_reason = "call_failed", res.failure_reason
                break
            fname = f"{b.doc_id}.part{b.part}.attempt{attempt}.response.txt"
            _write_new(resp_dir / fname, res.text)
            o.response_file = f"extract_runs/{run_id}/responses/{fname}"
            o.response_sha256 = sha256_text(res.text)
            info = {"model": res.model_id, "provider": res.provider, "response_sha256": o.response_sha256,
                    "call_id": res.call_id}
            v = validate_response(res.text, doc_id=b.doc_id, store=store, allowlist=allow,
                                  sent_chunk_ids=b.sent_chunk_ids, merged_title_ids=b.merged_title_ids,
                                  schema=schema, part=b.part, model_info=info)
            o.validation, o.validation_attempts = v, attempt
            if v.accepted:
                if not res.validated:
                    res.mark_validated(VALIDATOR_NAME)
                o.outcome = "validated"
                break
            o.outcome = "schema_failed"
            o.failure_reason = "; ".join(v.blocking_errors[:3])
            if attempt > validation_retries:
                break
        outcomes.append(o)
    return _finish(run_id, outcomes, built, config, mock, validation_retries, logger, out_root,
                   load_reserved_identifiers(instances_dir))


def _meta_from(outcomes_or_built) -> dict:
    for x in outcomes_or_built:
        m = x.meta if hasattr(x, "meta") else x.request_meta
        if m:
            return m
    return {}


def _finish(run_id, outcomes, built, config, mock, validation_retries, logger, out_root, reserved=()) -> RunResult:
    out_dir = run_dir(run_id, out_root)
    meta = _meta_from(built)
    summary = artifacts.write_outputs(out_dir, run_id, outcomes, run_mode=config.run_mode, mock=mock, meta=meta,
                                      validation_retries=validation_retries, reserved_identifiers=reserved)
    manifest = {"run_id": run_id, "mock": mock, "run_mode": config.run_mode,
                "entries": [{"document_id": o.document_id, "part": o.part, "n_parts": o.n_parts,
                             "outcome": o.outcome, "provider": o.provider, "model_id": o.model_id,
                             "call_id": o.call_id, "cache_hit": o.cache_hit, "response_file": o.response_file,
                             "response_sha256": o.response_sha256, "failure_reason": o.failure_reason,
                             "validation_attempts": o.validation_attempts, "request_meta": o.request_meta}
                            for o in outcomes]}
    mdir = Path(config.log_dir) / "extract_runs" / run_id
    write_json(mdir / "run_manifest.json", manifest)
    return RunResult(run_id, out_dir, mdir, outcomes, built, summary, False)


def revalidate(run_id: str, config: ExtractConfig, *, out_run_id=None, out_root=None, documents_dir=None,
               instances_dir=None) -> RunResult:
    """저장된 응답만 다시 검증한다. LLM을 부르지 않고 캐시도 건드리지 않는다."""
    mdir = Path(config.log_dir) / "extract_runs" / run_id
    mp = mdir / "run_manifest.json"
    if not mp.is_file():
        raise FileNotFoundError(f"실행 기록이 없습니다: {run_id} (llm_logs/extract_runs/{run_id}/run_manifest.json)")
    manifest = json.loads(mp.read_text(encoding="utf-8"))
    store = DocumentStore(documents_dir) if documents_dir else DocumentStore()
    allow = load_allowlist(instances_dir)
    _, schema = load_prompt_files()
    outcomes = []
    for e in manifest["entries"]:
        meta = e["request_meta"]
        o = DocOutcome(e["document_id"], e["part"], e["n_parts"], outcome=e["outcome"], request_meta=meta,
                       provider=e["provider"], model_id=e["model_id"], call_id=e["call_id"],
                       cache_hit=e["cache_hit"], response_file=e["response_file"],
                       response_sha256=e["response_sha256"], failure_reason=e["failure_reason"],
                       validation_attempts=e["validation_attempts"])
        if e["response_file"]:
            text = (Path(config.log_dir) / e["response_file"]).read_bytes().decode("utf-8")
            if sha256_text(text) != e["response_sha256"]:
                raise ValueError(f"저장된 응답의 해시가 기록과 다릅니다(변조 의심): {e['response_file']}")
            info = {"model": e["model_id"], "provider": e["provider"], "response_sha256": e["response_sha256"],
                    "call_id": e["call_id"]}
            v = validate_response(text, doc_id=e["document_id"], store=store, allowlist=allow,
                                  sent_chunk_ids=meta["chunk_ids"], merged_title_ids=meta["merged_title_chunk_ids"],
                                  schema=schema, part=e["part"], model_info=info)
            o.validation = v
            o.outcome = "validated" if v.accepted else "schema_failed"
        outcomes.append(o)
    new_id = out_run_id or run_id
    out_dir = run_dir(new_id, out_root)
    summary = artifacts.write_outputs(out_dir, new_id, outcomes, run_mode=manifest["run_mode"],
                                      mock=manifest["mock"], meta=_meta_from(outcomes), validation_retries=0,
                                      reserved_identifiers=load_reserved_identifiers(instances_dir))
    return RunResult(new_id, out_dir, mdir, outcomes, [], summary, False)


# ---------------------------------------------------------------- CLI
def _mock_config(example_file: str) -> ExtractConfig:
    return config_from_dict({"run": {"provider_order": ["gemini"], "run_mode": "scoring"},
                             "providers": {"gemini": {"models": [{"id": "mock-model"}]}},
                             "extract": {"example_file": example_file or ""}})


def _load_cfg(args, require_models: bool) -> ExtractConfig:
    if getattr(args, "mock_responses", None) and not args.config:
        return _mock_config(args.example or "")
    path = Path(args.config) if args.config else DEFAULT_CONFIG_PATH
    if not args.config and not path.is_file() and args.cmd in ("build-requests", "validate"):
        print("설정 파일(config/extract.toml)이 없어 견본 설정의 폴더 위치만 씁니다(모델 id 없음, API 호출 없음).")
        path = EXAMPLE_CONFIG_PATH
    return load_config(path, require_models=require_models)


def _docs_arg(s):
    return [x.strip() for x in s.split(",") if x.strip()] if s else None


def _print_summary(rr: RunResult) -> None:
    s = rr.summary
    c = s["counts"]
    print(f"실행 {rr.run_id}{' (mock)' if s['mock'] else ''}: 요청 {c['requests']}개, 응답 통과 {c['responses_accepted']}개, "
          f"규칙 {c['rules_all']}개 -> 예측 {c['predictions']}, KG 적재 대상 {c['rules_valid']}")
    fl = ", ".join(f"{k} {v}" for k, v in s["by_flag"].items() if v)
    print("  플래그: " + (fl or "없음"))
    print(f"  산출물: {rr.out_dir}")


def main(argv=None) -> int:
    from imaks_kg.extract.connectivity import load_env
    load_env()  # .env(git 제외)의 키 이름만 환경변수로 읽는다. 이미 설정된 값은 덮어쓰지 않고 값은 출력하지 않는다
    ap = argparse.ArgumentParser(prog="imaks_kg.extract", description="④ LLM 규칙 추출 2단계")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, run=False):
        p.add_argument("--config", default=None, help="기본: config/extract.toml")
        p.add_argument("--docs", default=None, help="쉼표 구분 문서 ID (기본: 7개 전부)")
        p.add_argument("--smoke", action="store_true", help="가장 작은 문서 하나만")
        p.add_argument("--run-id", default=None)
        p.add_argument("--example", default=None, help="Example 파일 경로(기본: 설정 extract.example_file)")
        p.add_argument("--registry", default=None, help="(시험용) Example 레지스트리 경로")
        if run:
            p.add_argument("--mock-responses", default=None, help="mock 응답 JSON({문서ID: 응답 텍스트}); 네트워크 미사용")
            p.add_argument("--validation-retries", type=int, default=1)

    p = sub.add_parser("build-requests", help="요청 파일만 만든다(API 호출 없음)")
    common(p)
    p = sub.add_parser("run", help="요청 생성 -> 호출 -> 응답 저장 -> 검증")
    common(p, run=True)
    p = sub.add_parser("validate", help="저장된 응답만 다시 검증(LLM 재호출 없음)")
    p.add_argument("--config", default=None)
    p.add_argument("--run-id", required=True)
    p.add_argument("--out-run-id", default=None, help="새 폴더 이름(기본: 같은 run_id; 예측이 달라지면 거부)")
    p = sub.add_parser("review-init", help="사람 검토 파일 만들기")
    p.add_argument("--run-id", required=True)
    p.add_argument("--stage", type=int, choices=(1, 2), required=True)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--fraction", type=float, default=0.2)
    p = sub.add_parser("review-apply", help="검토 결과를 rules_final.jsonl로 적용(predictions는 바꾸지 않음)")
    p.add_argument("--run-id", required=True)
    p = sub.add_parser("to-rdf", help="규칙을 TTL로 변환하고 SHACL S7·S8 확인")
    p.add_argument("--run-id", required=True)
    p.add_argument("--source", choices=("auto", "final", "valid"), default="auto")
    p.add_argument("--instances", default=None)
    args = ap.parse_args(argv)

    try:
        if args.cmd == "build-requests":
            cfg = _load_cfg(args, require_models=False)
            rr = build_requests(cfg, docs=_docs_arg(args.docs), smoke=args.smoke, run_id=args.run_id,
                                registry_path=args.registry, example_file=args.example)
            for b in rr.built:
                print(f"{b.doc_id} part {b.part}/{b.n_parts}: 입력 추정 {b.est_input_tokens} 토큰, 청크 {len(b.sent_chunk_ids)}개")
            print(f"요청 파일: {rr.log_run_dir} (API 호출 없음)")
            return 0
        if args.cmd == "run":
            cfg = _load_cfg(args, require_models=True)
            providers = None
            if args.mock_responses:
                from imaks_kg.extract.providers.mock import ScriptedByDocMock
                resp = json.loads(Path(args.mock_responses).read_text(encoding="utf-8"))
                providers = {n: ScriptedByDocMock(n, resp) for n in cfg.provider_order}
            rr = run_extraction(cfg, docs=_docs_arg(args.docs), smoke=args.smoke, run_id=args.run_id,
                                mock=bool(args.mock_responses), providers=providers, registry_path=args.registry,
                                example_file=args.example, validation_retries=args.validation_retries)
            _print_summary(rr)
            return 0
        if args.cmd == "validate":
            cfg = _load_cfg(args, require_models=False)
            rr = revalidate(args.run_id, cfg, out_run_id=args.out_run_id)
            _print_summary(rr)
            return 0
        if args.cmd == "review-init":
            from imaks_kg.extract import review
            msg = review.init_review(args.run_id, args.stage, seed=args.seed, fraction=args.fraction)
            print(review.NOTICE)
            print(msg)
            return 0
        if args.cmd == "review-apply":
            from imaks_kg.extract import review
            print(review.NOTICE)
            print(review.apply_review(args.run_id))
            return 0
        if args.cmd == "to-rdf":
            from imaks_kg.extract import to_rdf
            return to_rdf.cli(args.run_id, args.source, args.instances)
    except (ConfigError, ExampleError, SplitError, FileNotFoundError, FileExistsError, ValueError, KeyError) as e:
        print(f"중단: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
