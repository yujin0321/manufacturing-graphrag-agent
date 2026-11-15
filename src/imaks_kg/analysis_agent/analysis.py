"""정규화된 센서 입력 → 룰 엔진 실행(봉인) → KG 오버레이(봉인).

룰 엔진(`detection/engine`)과 오버레이 검증 코드는 수정하지 않고 그대로 호출한다.
업로드 입력에 맞춰 바꾸는 것은 세 가지뿐이다.

1. σ(기울기 보조 신호의 척도)는 업로드 파일이 아니라 고정 기준 입력의 학습 구간에서 계산한 값을 쓴다.
   업로드 데이터에 학습 구간이 없거나 이상 구간만 있어도 척도가 흔들리지 않게 하기 위해서다.
   기준 입력을 그대로 올리면 엔진 단독 실행과 결과가 같다(테스트로 확인).
2. 업로드에 없는 센서의 규칙은 실행 목록에서 뺀다(누락 센서는 보고서에 남긴다).
3. 오버레이 Provenance의 파일명·해시는 업로드 파일 기준으로 기록한다.
"""
from __future__ import annotations

from pathlib import Path

from rdflib import Graph, Literal

from imaks_kg.detection import rules as v1
from imaks_kg.detection.engine import compiler, config, executor, overlay as ov
from imaks_kg.detection.engine import run as engine_run
from imaks_kg.rag import comparison as c
from imaks_kg.rag import vector as v

DEFAULT_CONFIG = "v3_1"
SIGMA_CACHE = v.REPO_ROOT / "kg_build/analysis_agent/reference_sigma_{name}.json"
_GRAPH: Graph | None = None
_BUNDLE: dict | None = None


def base_graph() -> Graph:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = c.load_graph()
    return _GRAPH


def ir_bundle() -> dict:
    global _BUNDLE
    if _BUNDLE is None:
        _BUNDLE = compiler.compile_ir(base_graph())
    return _BUNDLE


def reference_sigmas(cfg: dict) -> dict:
    """기준 입력의 학습 구간(timestamp < train_end) σ. 라벨을 쓰지 않는다."""
    profile = v.read(v.REPO_ROOT / "preprocessed/sensors/profile.json")
    key = {"input_sha256": profile["output_sha256"][v1.INPUT], "train_end": cfg["train_end"]}
    path = Path(str(SIGMA_CACHE).format(name=cfg["name"]))
    if path.exists():
        cached = v.read(path)
        if cached.get("key") == key:
            return cached["sigma_by_sensor"]
    groups, _, _ = v1.read_inputs()
    sigmas = executor.calibrate(groups, cfg)
    v.write(path, {"key": key, "sigma_by_sensor": sigmas})
    return sigmas


def run_engine(groups: dict, out: Path, input_ref: dict, cfg_name: str = DEFAULT_CONFIG) -> dict:
    """엔진 실행 결과를 run.py와 같은 파일 구성으로 봉인 저장한다."""
    cfg = config.load(cfg_name)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    full = ir_bundle()
    present = set(groups)
    bundle = {**full, "rules": [r for r in full["rules"] if r["sensor_id"] in present]}
    skipped_rules = sorted({r["rule_id"] for r in full["rules"] if r["sensor_id"] not in present})
    ref = reference_sigmas(cfg)
    sigmas = {sid: ref[sid] for sid in groups}
    result, _ = engine_run.pipeline(groups, bundle, cfg, sigmas)

    v.write(out / "params.json", {"config": {k: val for k, val in cfg.items() if k != "_path"},
                                  "config_file": Path(cfg["_path"]).name, "sigma_by_sensor": sigmas,
                                  "sigma_source": "reference input train period (fixed)", "input": input_ref})
    v.write(out / "ir.json", {k: bundle[k] for k in ("ir_version", "rules", "type_definitions", "sensors",
                                                     "severity_tags", "correlation_pairs", "unsupported", "kg_sha256")})
    for key in cfg["outputs"]:
        v.write(out / engine_run.OUTPUT_FILES[key], result[key])
    incidents, alarms = result["incidents"], result["events"]
    summary = {"config": cfg["name"], "alarms": len(alarms), "slope_signals": len(result["signals"]),
               "monitor_windows": len(result["monitor_windows"]), "incidents": len(incidents),
               "correlation_links": len(result["correlations"]),
               "incidents_by_type": _count(incidents, "anomaly_type"),
               "incidents_by_severity": _count(incidents, "severity"),
               "incidents_by_station": _count(incidents, "station_id"),
               "rules_executed": len(bundle["rules"]), "rules_skipped_missing_sensor": skipped_rules,
               "unsupported_rules": [u["rule_id"] for u in bundle["unsupported"]],
               "kg_sha256": bundle["kg_sha256"], "input": input_ref,
               "gold_loaded": False, "api_calls": 0}
    v.write(out / "summary.json", summary)
    v.write(out / "complete.json", {p.name: v.digest(p.read_bytes()) for p in sorted(out.iterdir()) if p.is_file()})
    return summary


def _count(items: list[dict], key: str) -> dict:
    return {k: sum(i[key] == k for i in items) for k in sorted({i[key] for i in items})}


def build_overlay(run_dir: Path, out: Path, input_ref: dict) -> dict:
    """overlay.load()와 같은 검증·봉인. Provenance만 업로드 파일로 바꾼다."""
    run_dir, out = Path(run_dir), Path(out)
    if out.exists():
        raise FileExistsError(f"overlay output exists: {out}")
    seal = ov.verify_seal(run_dir)
    base = base_graph()
    graph, summary = ov.build_overlay(run_dir, base)
    for prov in set(graph.subjects(c.IM.sourceKind, Literal("timeseries"))):
        graph.set((prov, c.IM.fileName, Literal(input_ref["file_name"])))
        graph.set((prov, c.IM.fileSha256, Literal(input_ref["file_sha256"])))
    report = {"engine_run": run_dir.name, "engine_seal_sha256": v.digest(v.encoded(seal)), **summary,
              "input": input_ref, "loader_errors": ov.loader_checks(graph, base), **ov.shacl_checks(graph, base)}
    if report["loader_errors"] or report["shacl_blocking"] or report["guards_L4"]:
        raise ov.OverlayRejected("overlay rejected: validation failed", report)
    out.mkdir(parents=True, exist_ok=False)
    graph.serialize(out / "overlay.ttl", format="turtle")
    v.write(out / "overlay_report.json", report)
    v.write(out / "complete.json", {p.name: v.digest(p.read_bytes()) for p in sorted(out.iterdir()) if p.is_file()})
    return report
