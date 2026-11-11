"""Engine entry point: one pipeline, behaviour selected by a config file.

  python -m imaks_kg.detection.engine.run --config v3   --out kg_build/rule_engine_v3
  python -m imaks_kg.detection.engine.run --config v3_literal --out kg_build/rule_engine_v3_literal
  python -m imaks_kg.detection.engine.run --config v3_1 --out kg_build/rule_engine_v3_1

Inputs: frozen sensor input (preprocessed/sensors, hash-checked) and the
frozen KG. No labels, no API calls. The output directory must not exist.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from imaks_kg.rag import comparison as c
from imaks_kg.rag import vector as v

from .. import kg_rules as k2
from .. import rules as v1
from . import compiler, config, executor, postprocess, quality

OUTPUT_FILES = {"events": "events.json", "signals": "signals.json", "monitor_windows": "monitor_windows.json",
                "incidents": "incidents.json", "correlations": "correlations.json"}


def pipeline(groups: dict, bundle: dict, cfg: dict, sigmas: dict | None = None) -> tuple[dict, dict]:
    """In-memory run (used by run() and by the synthetic benchmark).
    ``sigmas`` can be fixed from the unmodified input so injected test
    anomalies do not change the calibration."""
    sigmas = sigmas if sigmas is not None else executor.calibrate(groups, cfg)
    alarms = executor.execute(groups, bundle["rules"], sigmas, cfg)
    return postprocess.run_postprocess(alarms, bundle, cfg), sigmas


def run(cfg_name: str | Path, out: str | Path) -> dict:
    cfg = config.load(cfg_name)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    groups, thresholds, _ = v1.read_inputs()
    graph = c.load_graph()
    bundle = compiler.compile_ir(graph)
    report = quality.kg_quality(graph, bundle)
    result, sigmas = pipeline(groups, bundle, cfg)

    v.write(out / "params.json", {"config": {k: val for k, val in cfg.items() if k != "_path"},
                                  "config_file": Path(cfg["_path"]).name, "sigma_by_sensor": sigmas})
    v.write(out / "ir.json", {k: bundle[k] for k in ("ir_version", "rules", "type_definitions", "sensors",
                                                     "severity_tags", "correlation_pairs", "unsupported", "kg_sha256")})
    v.write(out / "kg_quality.json", report)
    for key in cfg["outputs"]:
        v.write(out / OUTPUT_FILES[key], result[key])
    incidents, alarms_out = result["incidents"], result["events"]
    engine_dir = Path(__file__).resolve().parent
    summary = {"config": cfg["name"], "alarms": len(alarms_out), "slope_signals": len(result["signals"]),
               "monitor_windows": len(result["monitor_windows"]), "monitor_alarms": result["monitor_alarm_count"],
               "incidents": len(incidents), "correlation_links": len(result["correlations"]),
               "alarms_by_kind": {kd: sum(a["kind"] == kd for a in alarms_out)
                                  for kd in sorted({a["kind"] for a in alarms_out})},
               "incidents_by_type": {t: sum(i["anomaly_type"] == t for i in incidents)
                                     for t in sorted({i["anomaly_type"] for i in incidents})},
               "ir_rules": len(bundle["rules"]), "unsupported": [u["rule_id"] for u in bundle["unsupported"]],
               "kg_vs_metadata_threshold_diffs": k2.threshold_consistency(graph, thresholds),
               "kg_sha256": bundle["kg_sha256"],
               "engine_sha256": {p.name: v.digest(p.read_bytes()) for p in sorted(engine_dir.glob("*.py"))},
               "config_sha256": v.digest(Path(cfg["_path"]).read_bytes()),
               "gold_loaded": False, "api_calls": 0, "post_hoc": bool(cfg.get("post_hoc"))}
    v.write(out / "summary.json", summary)
    v.write(out / "complete.json", {p.name: v.digest(p.read_bytes()) for p in sorted(out.iterdir()) if p.is_file()})
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="config name in engine/configs (v3, v3_literal, v3_1) or path")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--quality-md", type=Path, help="also write the KG quality report as markdown")
    a = parser.parse_args()
    summary = run(a.config, a.out)
    if a.quality_md:
        a.quality_md.write_text(quality.markdown(v.read(a.out / "kg_quality.json"), summary["kg_sha256"]),
                                encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
