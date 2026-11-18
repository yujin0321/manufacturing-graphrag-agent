"""Exhaustive bounded search of mean/STUCK windows and causal decision stride."""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from build_normalized_windows import normalize_observations
from common_detection_data import FORBIDDEN, THRESHOLDS, KEYS, align_by_keys, load_common_detection_data
from imaks_pipeline import detector_flags, fit_scores, evaluate_events, predictions_to_events
from joint_window_core import EvaluationContext, stride_flags

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "experiments" / "joint_window_sweep_v1"
MEANS = tuple(range(2, 121))
STUCKS = tuple(range(2, 121))
STRIDES = tuple(range(1, 11))
CONFIG = {"model": "robust_causal", "instant_k": 6.0, "rolling_k": 4.0}
PARAMS = ["mean_window_samples", "stuck_window_samples", "stride_samples"]
ORDER = ["event_f1", "unmatched_alarm_events", "row_f1", "mean_delay_min", "stride_samples", "mean_window_samples", "stuck_window_samples"]
ASCENDING = [False, True, False, True, True, True, True]
PROTECTED = ["preprocessed/common_v1", "experiments/common_v1_detection", "experiments/common_v1_detection_window3",
             "experiments/robust_windows_v1", "experiments/window3_features_v1", "experiments/window_sweep_v1",
             "pipeline_outputs", "pipeline_outputs_window3", "ontology_v1"]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def save_csv(path, frame):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig", compression="infer")


def protected_hashes():
    paths = [ROOT / "iMAKS_dataset.zip", ROOT / "imaks_pipeline.py"]
    paths += [p for name in PROTECTED for p in (ROOT / name).rglob("*") if p.is_file()]
    return {str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p) for p in sorted(paths)}


def make_base(observations):
    normalized, parameters = normalize_observations(observations)
    base = normalized.merge(parameters[["sensor_id", "median", "robust_scale"]],
                            on="sensor_id", validate="many_to_one", sort=False)
    base["segment_position"] = base.groupby("segment_id", sort=False).cumcount()
    if (FORBIDDEN | set(THRESHOLDS)) & set(base):
        raise ValueError("Leaking fields entered feature preparation")
    return base, parameters


def calculate_windows(base, mean_sizes=MEANS, stuck_sizes=STUCKS):
    """Compute past/current features once. No labels or oracle thresholds."""
    if (FORBIDDEN | set(THRESHOLDS)) & set(base):
        raise ValueError("Leaking fields entered rolling calculation")
    grouped = base.groupby("segment_id", sort=False)["value"]
    instant = base.z_abs.to_numpy() > CONFIG["instant_k"]
    means, stucks = {}, {}
    median = base["median"].to_numpy()
    scale = base.robust_scale.to_numpy()
    tolerance = .001 * np.maximum(np.abs(median), 1e-8)
    for size in mean_sizes:
        values = grouped.transform(lambda x: x.rolling(size, min_periods=size).mean()).to_numpy()
        means[size] = np.abs((values - median) / scale) > CONFIG["rolling_k"]
    for size in stuck_sizes:
        values = grouped.transform(lambda x: x.rolling(size, min_periods=size).std(ddof=0)).to_numpy()
        stucks[size] = values < tolerance
    return instant, means, stucks


def scored_features(base, mean_size, stuck_size):
    scored = base.copy()
    grouped = scored.groupby("segment_id", sort=False)["value"]
    mean = grouped.transform(lambda x: x.rolling(mean_size, min_periods=mean_size).mean())
    std = grouped.transform(lambda x: x.rolling(stuck_size, min_periods=stuck_size).std(ddof=0))
    scored["mean_z"] = (mean - scored["median"]) / scored.robust_scale
    scored["rolling_z"] = scored.mean_z.abs()
    scored["std_z"] = std / scored.robust_scale
    scored["stuck_flag"] = (std < .001 * scored["median"].abs().clip(lower=1e-8)).fillna(False)
    scored["mean_ready"] = mean.notna()
    scored["stuck_ready"] = std.notna()
    return scored


def phase_stride_flags(raw_flags, positions, stride, phase=0):
    """Hold from the first observation, then decide on a shifted stride grid."""
    default_flags, default_decisions = stride_flags(raw_flags, positions, stride)
    if isinstance(phase, (bool, np.bool_)) or not isinstance(phase, (int, np.integer)) or not 0 <= phase < stride:
        raise ValueError("phase must be an integer in [0, stride)")
    if phase == 0:
        return default_flags, default_decisions
    positions = np.asarray(positions)
    remainder = (positions - phase) % stride
    source_position = np.where(positions >= phase, positions - remainder, 0)
    sources = np.arange(len(positions)) - positions + source_position
    decisions = (positions == 0) | ((positions >= phase) & (remainder == 0))
    return np.asarray(raw_flags, dtype=bool)[sources], decisions


def select_combination(validation):
    if validation.empty or not validation["split"].eq("validation").all():
        raise ValueError("Only validation metrics may select a joint configuration")
    if validation.duplicated(PARAMS).any():
        raise ValueError("Duplicate joint candidate")
    ranking = validation.sort_values(ORDER, ascending=ASCENDING, na_position="last", kind="stable").reset_index(drop=True)
    selected = {key: int(ranking.iloc[0][key]) for key in PARAMS}
    return selected, ranking


def context_for(base, labels, truth, split):
    mask = base["split"].eq(split).to_numpy()
    frame = base.loc[mask].reset_index(drop=True)
    target = labels.loc[mask, "anomaly_label"].ne("NORMAL").to_numpy()
    events = truth[truth["split"].eq(split)].copy()
    return EvaluationContext(frame, events, target), mask, frame


def measure_config(base, aligned_labels, truth, config, split, *, tables=False):
    scored = scored_features(base, config["mean_window_samples"], config["stuck_window_samples"])
    context, mask, frame = context_for(base, aligned_labels, truth, split)
    raw = detector_flags(scored.loc[mask], CONFIG)
    flags, decision = stride_flags(raw, frame.segment_position.to_numpy(), config["stride_samples"])
    metrics = context.measure(flags)
    metrics.update(config, split=split, evaluated_rows=len(frame), decision_count=int(decision.sum()),
                   sampling_seconds=30, decision_interval_seconds=30 * config["stride_samples"],
                   mean_first_to_last_seconds=(config["mean_window_samples"] - 1) * 30,
                   stuck_first_to_last_seconds=(config["stuck_window_samples"] - 1) * 30)
    if tables:
        return metrics, context.events(flags), context.matches(flags), flags, decision, scored.loc[mask].reset_index(drop=True)
    return metrics


def validate_reference(base, aligned_labels, truth):
    results = []
    for mean, folder in [(3, "common_v1_detection_window3"), (10, "common_v1_detection")]:
        config = dict(mean_window_samples=mean, stuck_window_samples=11, stride_samples=1)
        scored = scored_features(base, mean, 11)
        reference = fit_scores(base[["timestamp", "zone", "station_id", "sensor_id", "sensor_type", "value", "unit"]], mean, 11)
        np.testing.assert_allclose(scored.z_abs, reference.z_abs, rtol=1e-10, atol=1e-10)
        np.testing.assert_allclose(scored.rolling_z, reference.rolling_z, rtol=1e-10, atol=1e-10, equal_nan=True)
        np.testing.assert_array_equal(scored.stuck_flag, reference.stuck_flag)
        saved = pd.read_csv(ROOT / "experiments" / folder / "row_predictions.csv.gz", parse_dates=["timestamp"])
        old = align_by_keys(base, saved, ["predicted_anomaly"])
        np.testing.assert_array_equal(detector_flags(scored, CONFIG), old.predicted_anomaly.to_numpy())
        old_metrics = pd.read_csv(ROOT / "experiments" / folder / "detection_metrics.csv")
        for split in ["train", "validation", "test"]:
            measured, pred, matches, flags, _, frame = measure_config(base, aligned_labels, truth, config, split, tables=True)
            existing = old_metrics[old_metrics.model.eq("robust_causal") & old_metrics["split"].eq(split)].iloc[0]
            fields = ["event_f1", "event_precision", "event_recall", "detected_events", "predicted_events",
                      "unmatched_alarm_events", "pure_false_alarm_events", "row_tp", "row_fp", "row_fn"]
            np.testing.assert_allclose([measured[k] for k in fields], existing[fields].astype(float).to_numpy(), rtol=1e-12, atol=1e-12)
            pandas_pred = predictions_to_events(frame, flags)
            pandas_metrics, _ = evaluate_events(pandas_pred, truth[truth["split"].eq(split)])
            event_fields = fields[:7]
            np.testing.assert_allclose([measured[k] for k in event_fields], [pandas_metrics[k] for k in event_fields], rtol=1e-12, atol=1e-12)
        results.append({"config": config, "all_row_flags_match_saved_results": True,
                        "all_split_metrics_match": True, "numpy_event_scoring_matches_pandas": True})
    return results


def plot_validation(ranking, selected, output):
    best_stride = ranking.drop_duplicates(["mean_window_samples", "stuck_window_samples"])
    for metric in ["event_f1", "row_f1"]:
        table = best_stride.pivot(index="stuck_window_samples", columns="mean_window_samples", values=metric).sort_index().sort_index(axis=1)
        fig, ax = plt.subplots(figsize=(10, 7))
        im = ax.imshow(table.to_numpy(), origin="lower", extent=[1.5, 120.5, 1.5, 120.5], vmin=0, vmax=1, aspect="auto", cmap="viridis")
        ax.scatter(selected["mean_window_samples"], selected["stuck_window_samples"], s=120, marker="*", color="red", label="Validation-selected")
        ax.set(xlabel="Mean window samples", ylabel="STUCK statistic window samples", title=f"Validation {metric}; best ranked stride at each pair")
        ax.legend(loc="upper right")
        fig.colorbar(im, ax=ax, label=metric)
        fig.tight_layout()
        fig.savefig(output / f"validation_{metric}_heatmap.png", dpi=160)
        plt.close(fig)


def write_report(selected, ranking, compared, protocol, output):
    def line(row):
        return f"| {row['model_name']} | {int(row['mean_window_samples'])} | {int(row['stuck_window_samples'])} | {int(row['stride_samples'])} | {row['event_f1']:.1%} | {row['row_f1']:.1%} | {int(row['detected_events'])}/{int(row['true_events'])} | {int(row['predicted_events'])} |"
    validation_rows = compared[compared["split"].eq("validation") & compared.model_name.isin(["selected", "current_mean3_stuck11_stride1", "previous_mean10_stuck11_stride1"])]
    test_rows = compared[compared["split"].eq("test") & compared.model_name.isin(["selected", "current_mean3_stuck11_stride1", "previous_mean10_stuck11_stride1"])]
    table_head = "| 설정 | 평균 | STUCK | stride | 이벤트 F1 | 행 F1 | 탐지/정답 이벤트 | 경보 수 |\n|---|---:|---:|---:|---:|---:|---:|---:|"
    best = ranking.iloc[0]
    phases = pd.read_csv(output / "phase_sensitivity.csv")
    phase_lines = [f"| {row['split']} | {int(row['phase_samples'])} | {row['event_f1']:.1%} | {row['row_f1']:.1%} | {int(row['detected_events'])}/{int(row['true_events'])} | {int(row['predicted_events'])} |"
                   for row in phases.to_dict('records')]
    report = f'''# 평균·STUCK·stride 공동 탐색 결과

검증에서 선택한 조합은 **평균 {selected['mean_window_samples']}개 / STUCK {selected['stuck_window_samples']}개 / stride {selected['stride_samples']}개**다. 원본 관측 간격은 **30초**이며 판정 간격은 **{selected['stride_samples'] * 30}초**다.

## 탐색 범위와 선택

평균 2~120개, STUCK 통계 윈도우 2~120개, stride 1~10개를 모두 조합해 **{len(ranking):,}개**를 검증했다. 최대 윈도우는 120개 관측(첫 관측~마지막 관측 59.5분), 최대 판정 간격은 5분이다. 이 유한 범위의 전수 탐색이며 모든 가능한 모델·임계값·관측 주기의 전역 최적을 증명한 것은 아니다. 순간/평균 임계값은 6/4, STUCK 허용 오차는 학습 중앙값의 0.001배로 고정했다. 6/4는 앞선 같은 검증 구간에서 선택한 값이며 이번 탐색으로 임계값까지 새로 최적화하지 않았다. 따라서 같은 작은 검증 집합을 반복 사용한 개발 실험이다.

학습 구간은 1/6, 검증은 1/7, 기존 평가는 1/8~1/9다. 정규화는 학습 구간 센서별 median/MAD만 사용한다. quality·정답·raw 임계값을 피처 계산에 사용하지 않는다. 검증 정답으로 조합을 선택하고 selected_model.json을 저장한 뒤 평가했다.

정렬 기준은 이벤트 F1 내림차순 → 추가 경보 수 오름차순 → 행 F1 내림차순 → 평균 탐지 지연 오름차순 → stride·평균·STUCK 크기 오름차순이다. 반올림하지 않은 원래 수치를 사용한다. 같은 지표에서는 더 자주 판정하는 stride를 우선한다.

검증 이벤트는 4건이며 DRIFT·STUCK·OUT_OF_RANGE만 있고 SPIKE·CORRELATED는 없다. 넓은 탐색 범위에 비해 작은 검증 집합이므로 다른 이상 유형이나 공장으로 일반화할 수 없다. 평가 8건에는 STUCK이 없어서 선택한 STUCK 길이의 별도 평가 성능은 확인할 수 없다. 선택된 STUCK 길이는 통계 특징 길이이며 SOP의 '>10 consecutive samples' 조건이 최적화됐다는 뜻은 아니다.

## stride의 의미

윈도우는 stride와 무관하게 최근 30초 간격 원본 W개를 사용한다. segment의 첫 관측에서 판정하고 stride마다 다시 판정한다. 중간 행에서는 직전 판정을 앞으로 유지하며 미래 판정을 과거에 채우지 않는다. 센서·시간 공백·split 경계에서 다시 시작한다. 판정 시작 위치(phase)는 segment_position=0으로 고정했으며, 다른 시작 위치에서의 최적 조합까지 탐색한 것은 아니다.

모든 후보를 같은 검증 **63,360행**에서 평가한다. 준비 전 평균/STUCK 분기는 비활성이고 순간 분기는 처음부터 동작한다. 미판정 행을 제거하거나 정상으로 간주하지 않는다. 큰 stride는 판정 지연과 짧은 이상 누락을 유발할 수 있으며 원래 관측값은 버리지 않는다.

## 검증 비교

{table_head}
{chr(10).join(line(row) for row in validation_rows.to_dict('records'))}

검증 이벤트 F1 최고 동률 조합은 {int(ranking.event_f1.eq(best.event_f1).sum()):,}개다. 전체 순위는 validation_ranking.csv, 상위 20개는 validation_top20.csv다.

## 기존 평가 구간의 재평가

{table_head}
{chr(10).join(line(row) for row in test_rows.to_dict('records'))}

평가값은 선택에 사용하지 않았다. 이 평가 구간은 이전에 결과를 확인했던 데이터이며 새 맹검 시험이 아니다. 최종 선택과 검증 상위 5개를 평가해 참고로 저장했고, 평가 결과로 선택을 다시 바꾸지 않았다.

## 판정 시작 시점 민감도

선택값을 고정한 뒤 같은 설정으로 가능한 phase 0~stride−1을 평가했다. segment의 첫 행에서 반드시 초기 판정을 하고 이후 판정 위치만 옮긴다. phase는 후보 선택에 사용하지 않았다. phase가 바뀌어도 원본 관측과 특징은 그대로다.

| 구간 | phase(관측 개수) | 이벤트 F1 | 행 F1 | 탐지/정답 이벤트 | 경보 수 |
|---|---:|---:|---:|---:|---:|
{chr(10).join(phase_lines)}

## 저장·재현

- protocol.json: 사전 탐색 범위·정렬·stride 정책·입력 해시.
- validation_ranking.csv, validation_top20.csv: 모든 후보 검증 결과.
- selected_model.json: 평가 이전에 고정한 선택값.
- comparison_metrics.csv: 선택값·검증 상위 후보·현재 3/11/1·이전 10/11/1의 split별 지표.
- phase_sensitivity.csv: 선택 후 판정 시작 위치에 대한 민감도 확인. 재선택에 사용하지 않음.
- selected_scores.csv.gz: 전체 211,200행의 선택된 raw 점수·판정 시점·유지된 예측. 입력 라벨과 raw 임계값은 없음.
- evaluation/: 키로 연결된 정답과 split별 예측 이벤트·매칭·유형별 탐지·추가 조각 분석.
- verification.json, preservation_check.json, manifest.json: 기존 탐지기 재현·저장값 대조·원본/기존 파일 보존·해시.

이 검색은 별도 실험이며 현재 기본 평균3/STUCK11/stride1 코드와 기존 특징 파일을 변경하지 않았다. 선택값을 기본 탐지/특징 생성에 적용하는 작업은 별도 연결 단계다.
'''
    (output / "report_ko.md").write_text(report, encoding="utf-8")


def run(output=OUT, *, record_date=None):
    if record_date is not None:
        date.fromisoformat(record_date)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()
    dump(output / "audit/protected_hashes_before.json", before)
    protocol = {"record_date": record_date, "mean_window_candidates": list(MEANS), "stuck_window_candidates": list(STUCKS),
                "stride_candidates": list(STRIDES), "candidate_count": len(MEANS) * len(STUCKS) * len(STRIDES),
                "sampling_seconds": 30, "sampling_interval_optimized": False, "fixed_detector_thresholds": CONFIG,
                "stuck_tolerance": "0.001 * max(abs(train median), 1e-8)", "normalization_fit": "train only median/MAD",
                "selection_split": "validation", "selection_order": [{"metric": key, "ascending": ascending} for key, ascending in zip(ORDER, ASCENDING)],
                "stride_policy": "Decide at segment_position % stride == 0; carry previous prediction forward to next decision; no backfill; all original rows evaluated",
                "stride_phase": "segment_position 0; never optimized against event boundaries",
                "phase_sensitivity": "After freezing selection, report all phases of selected stride on validation and test; never reselect",
                "resets": ["sensor", "gap !=30 seconds", "split boundary"], "future_values_used": False,
                "validation_events": 4, "test_status": "Previously observed existing test; reevaluation, not new blind test",
                "test_used_for_selection": False, "default_detector_changed": False,
                "runtime_versions": {"numpy": np.__version__, "pandas": pd.__version__, "matplotlib": matplotlib.__version__},
                "implementation_sha256": sha256(__file__), "core_sha256": sha256(ROOT / "joint_window_core.py")}
    dump(output / "protocol.json", protocol)
    data = load_common_detection_data()
    protocol["input_provenance"] = data.provenance
    dump(output / "protocol.json", protocol)
    base, parameters = make_base(data.ml)
    save_csv(output / "normalization_parameters.csv", parameters)
    labels = align_by_keys(base, data.labels, ["anomaly_label", "dataset_severity"])
    print("Precomputing causal mean/STUCK features", flush=True)
    instant, means, stucks = calculate_windows(base)
    context, mask, validation_frame = context_for(base, labels, data.events, "validation")
    instant = instant[mask]
    means = {key: values[mask] for key, values in means.items()}
    stucks = {key: values[mask] for key, values in stucks.items()}
    position = validation_frame.segment_position.to_numpy()
    row_index = np.arange(len(validation_frame))
    sources, decision_counts = {}, {}
    for stride in STRIDES:
        _, decision = stride_flags(np.zeros(len(position), dtype=bool), position, stride)
        sources[stride] = row_index - position % stride
        decision_counts[stride] = int(decision.sum())
    metrics = []
    start = time.perf_counter()
    for mean_size in MEANS:
        for stuck_size in STUCKS:
            raw = instant | means[mean_size] | stucks[stuck_size]
            for stride in STRIDES:
                held = raw[sources[stride]]
                measured = context.measure(held)
                measured.update(mean_window_samples=mean_size, stuck_window_samples=stuck_size, stride_samples=stride,
                                split="validation", evaluated_rows=len(position), decision_count=decision_counts[stride])
                metrics.append(measured)
        if mean_size == 2 or mean_size % 10 == 0 or mean_size == 120:
            elapsed = time.perf_counter() - start
            print(f"Validation {len(metrics):,}/{protocol['candidate_count']:,} combinations; {elapsed:.1f}s", flush=True)
    raw_metrics = pd.DataFrame(metrics)
    selection_runtime = time.perf_counter() - start
    selected, ranking = select_combination(raw_metrics)
    save_csv(output / "validation_ranking.csv", ranking)
    save_csv(output / "validation_top20.csv", ranking.head(20))
    saved_validation = pd.read_csv(output / "validation_ranking.csv", float_precision="round_trip")
    saved_selected, _ = select_combination(saved_validation)
    if selected != saved_selected:
        raise ValueError("Saved validation ranking does not reproduce selected configuration")
    selection = {"config": {**CONFIG, **selected, "sampling_seconds": 30}, "selected_using": "Validation only; exhaustive bounded grid",
                 "candidate_count": len(ranking), "selection_order": protocol["selection_order"],
                 "selected_validation_metrics": json.loads(ranking.iloc[0].to_json()), "frozen_before_test_evaluation": True,
                 "test_used_for_selection": False, "validation_csv_sha256": sha256(output / "validation_ranking.csv"),
                 "input_provenance": data.provenance, "default_detector_changed": False}
    dump(output / "selected_model.json", selection)
    frozen_selection = (output / "selected_model.json").read_bytes()
    print("Frozen validation selection: " + json.dumps(selected), flush=True)
    references = validate_reference(base, labels, data.events)
    print("Reference 3/11/1 and 10/11/1 scores, flags and metrics reproduced", flush=True)
    # Test is never passed to select_combination. The shortlist is validation-defined.
    shortlist = [("selected", selected), ("current_mean3_stuck11_stride1", dict(mean_window_samples=3, stuck_window_samples=11, stride_samples=1)),
                 ("previous_mean10_stuck11_stride1", dict(mean_window_samples=10, stuck_window_samples=11, stride_samples=1))]
    for i, row in ranking.head(5).iterrows():
        shortlist.append((f"validation_rank_{i+1}", {key: int(row[key]) for key in PARAMS}))
    comparison = []
    for name, config in shortlist:
        for split in ["train", "validation", "test"]:
            measured, pred, matches, flags, decision, scored = measure_config(base, labels, data.events, config, split, tables=True)
            comparison.append({"model_name": name, **measured})
            if name == "selected":
                save_csv(output / "evaluation" / f"{split}_predicted_events.csv", pred)
                save_csv(output / "evaluation" / f"{split}_event_matches.csv", matches)
    compared = pd.DataFrame(comparison)
    save_csv(output / "comparison_metrics.csv", compared)
    phase_results = []
    phase_scored = scored_features(base, selected["mean_window_samples"], selected["stuck_window_samples"])
    for split in ["validation", "test"]:
        phase_context, phase_mask, phase_frame = context_for(base, labels, data.events, split)
        phase_raw = detector_flags(phase_scored.loc[phase_mask], CONFIG)
        for phase in range(selected["stride_samples"]):
            held, decision = phase_stride_flags(phase_raw, phase_frame.segment_position.to_numpy(), selected["stride_samples"], phase)
            phase_results.append({**selected, "split": split, "phase_samples": phase, "evaluated_rows": len(phase_frame),
                                  "decision_count": int(decision.sum()), **phase_context.measure(held)})
    save_csv(output / "phase_sensitivity.csv", pd.DataFrame(phase_results))
    scores = scored_features(base, selected["mean_window_samples"], selected["stuck_window_samples"])
    raw_flags = detector_flags(scores, CONFIG)
    flags, decision = stride_flags(raw_flags, scores.segment_position.to_numpy(), selected["stride_samples"])
    safe = ["sensor_id", "timestamp", "station_id", "zone", "sensor_type", "unit", "value", "value_z", "z_abs", "mean_z",
            "rolling_z", "std_z", "mean_ready", "stuck_ready", "stuck_flag", "split", "segment_id", "segment_position", "normalized_row"]
    score_export = scores[safe].assign(is_decision=decision, raw_flag_at_current_observation=raw_flags,
                                       predicted_anomaly=flags)
    save_csv(output / "selected_scores.csv.gz", score_export)
    eval_rows = base[KEYS + ["split"]].assign(anomaly_label=labels.anomaly_label, dataset_severity=labels.dataset_severity)
    save_csv(output / "evaluation/row_labels.csv.gz", eval_rows)
    save_csv(output / "evaluation/anomaly_events.csv", data.events)
    diagnostics = []
    for split in ["train", "validation", "test"]:
        events = pd.read_csv(output / "evaluation" / f"{split}_predicted_events.csv", parse_dates=["start", "end"])
        matched = pd.read_csv(output / "evaluation" / f"{split}_event_matches.csv")
        for _, event in data.events[data.events["split"].eq(split)].iterrows():
            matches = events.sensor_id.eq(event.sensor_id) & events.start.le(event.end) & events.end.ge(event.start)
            hit = matched[matched.event_id.eq(event.event_id)].iloc[0]
            diagnostics.append({"event_id": event.event_id, "sensor_id": event.sensor_id, "split": split,
                                "anomaly_type": event.anomalyType, "detected": bool(hit.detected),
                                "overlapping_alarm_fragments": int(matches.sum()), "delay_min": hit.delay_min})
    save_csv(output / "evaluation/event_diagnostics.csv", pd.DataFrame(diagnostics))
    restored = pd.read_csv(output / "selected_scores.csv.gz", parse_dates=["timestamp"], float_precision="round_trip")
    aligned_values = align_by_keys(restored, data.ml, ["value"])
    np.testing.assert_array_equal(restored.value, aligned_values.value)
    np.testing.assert_array_equal(restored.predicted_anomaly, flags)
    np.testing.assert_array_equal(restored.is_decision, decision)
    if (output / "selected_model.json").read_bytes() != frozen_selection:
        raise ValueError("Selection changed after test reporting")
    after = protected_hashes()
    changed = [name for name in before.keys() | after.keys() if before.get(name) != after.get(name)]
    if changed:
        raise ValueError(f"Protected files changed: {changed}")
    dump(output / "preservation_check.json", {"protected_files": len(before), "changed_files": changed, "protected_directories": PROTECTED})
    verification = {"candidate_count": len(ranking), "expected_candidate_count": protocol["candidate_count"],
                    "all_validation_rows_evaluated": bool(ranking.evaluated_rows.eq(63360).all()),
                    "all_combinations_unique": not bool(ranking.duplicated(PARAMS).any()), "frozen_selection_unchanged_after_test": True,
                    "validation_ranking_reproduced": True, "references": references, "source_values_preserved": True,
                    "selected_serialized_predictions_match": True, "selected_serialized_decisions_match": True,
                    "observations": len(base), "sensors": int(base.sensor_id.nunique()), "segments": int(base.segment_id.nunique()),
                    "selection_runtime_seconds": selection_runtime,
                    "search_and_reporting_runtime_seconds": time.perf_counter() - start, "test_used_for_selection": False}
    if len(ranking) != protocol["candidate_count"] or not verification["all_validation_rows_evaluated"]:
        raise ValueError("Incomplete or incomparable search")
    dump(output / "verification.json", verification)
    plot_validation(ranking, selected, output)
    write_report(selected, ranking, compared, protocol, output)
    entries = {str(path.relative_to(output)).replace("\\", "/"): sha256(path) for path in sorted(output.rglob("*")) if path.is_file() and path.name != "manifest.json"}
    dump(output / "manifest.json", {"record_date": record_date, "implementation_sha256": sha256(__file__),
                                    "core_sha256": sha256(ROOT / "joint_window_core.py"), "output_files_sha256": entries})
    print(compared[compared.model_name.eq("selected")][["split", "event_f1", "row_f1", "detected_events", "predicted_events"]].to_string(index=False), flush=True)
    return selection, compared


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-date", help="Client date YYYY-MM-DD; no host timezone inferred")
    args = parser.parse_args()
    run(record_date=args.record_date)
