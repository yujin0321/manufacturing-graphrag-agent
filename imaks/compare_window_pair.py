"""Reevaluate two frozen window configurations on the same existing splits.

No synthetic data, split changes, retuning, or changes to the default detector.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from common_detection_data import FORBIDDEN, THRESHOLDS, align_by_keys, load_common_detection_data
from imaks_pipeline import detector_flags
from joint_window_core import stride_flags
from sweep_joint_windows import CONFIG, context_for, make_base, scored_features

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "experiments" / "window_pair_comparison_v1"
PAIRS = {
    "mean2_stuck10_stride2": dict(mean_window_samples=2, stuck_window_samples=10, stride_samples=2),
    "mean10_stuck11_stride1": dict(mean_window_samples=10, stuck_window_samples=11, stride_samples=1),
}
REFERENCES = {
    "mean2_stuck10_stride2": ("selected", "experiments/joint_window_sweep_v1/selected_scores.csv.gz"),
    "mean10_stuck11_stride1": ("previous_mean10_stuck11_stride1", "experiments/common_v1_detection/row_predictions.csv.gz"),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def csv(path, frame):
    path.parent.mkdir(parents=True, exist_ok=True)
    compression = {"method": "gzip", "compresslevel": 1, "mtime": 0} if path.suffix == ".gz" else None
    frame.to_csv(path, index=False, encoding="utf-8-sig", compression=compression)


def write_report(metrics, events, provenance, output):
    split_names = {"train": "학습", "validation": "검증", "test": "평가"}
    names = {name: f"{c['mean_window_samples']}/{c['stuck_window_samples']}/{c['stride_samples']}" for name, c in PAIRS.items()}
    lines = ["# 같은 학습·검증·평가 데이터에서 두 설정 재비교", "",
             "숫자 순서는 평균 / STUCK / stride다. 원본 관측은 30초 간격이며, 2/10/2는 60초마다, 10/11/1은 30초마다 판정한다.", "",
             "## 동일하게 고정한 조건", "",
             "- 공통 입력 211,200행, 센서 22개와 기존 시간 분할을 그대로 사용했다.",
             "- 학습 2026-01-06 06:00~23:59:30: 47,520행·이벤트 2건.",
             "- 검증 2026-01-07 00:00~23:59:30: 63,360행·이벤트 4건.",
             "- 평가 2026-01-08 00:00~01-09 13:59:30: 100,320행·이벤트 8건.",
             "- 정규화는 같은 학습 구간의 센서별 median/MAD. 학습 라벨로 정상 행을 선별하지 않았다.",
             "- 순간/평균 임계값 6/4, STUCK 허용 오차 0.001×abs(학습 중앙값), 판정 시작 위치 phase0 유지.",
             "- 센서·공백·split 경계에서 초기화하고 준비 전 행도 평가에 포함했다.",
             "- quality·정답 라벨·raw 임계값은 통계 탐지에 미사용. 원본값 삭제/보정/보간/평활화 미적용.",
             "- 새 조합을 탐색하거나 기존 기본 설정·기존 산출물을 덮어쓰지 않았다.", "",
             "## 분할별 결과", "",
             "| 구간 | 설정 | 이벤트 F1 | 행 F1 | 탐지/정답 | 경보 수 | 추가 조각 | 정상 행 경보 | 평균 지연(분) |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for split in split_names:
        for row in metrics[metrics['split'].eq(split)].to_dict('records'):
            lines.append(f"| {split_names[split]} | {names[row['config_name']]} | {row['event_f1']:.2%} | {row['row_f1']:.2%} | {row['detected_events']}/{row['true_events']} | {row['predicted_events']} | {row['fragment_alarm_events']} | {row['row_fp']} | {row['mean_delay_min']:.2f} |")
    a = metrics[metrics.config_name.eq('mean2_stuck10_stride2') & metrics['split'].eq('test')].iloc[0]
    b = metrics[metrics.config_name.eq('mean10_stuck11_stride1') & metrics['split'].eq('test')].iloc[0]
    lines += ["", "## 해석", "",
              f"같은 평가 데이터의 이벤트 F1은 10/11/1이 {b.event_f1:.2%}, 2/10/2가 {a.event_f1:.2%}로, 10/11/1이 {(b.event_f1-a.event_f1)*100:.2f}%p 높다. 두 설정 모두 사건 8건을 전부 탐지했다. 차이는 같은 이상 구간에 겹치는 추가 경보 조각이 9개에서 3개로 줄어든 데서 발생한다. 순수 오경보 이벤트는 두 설정 모두 0건이다.", "",
              "행 F1, 정상 행 경보 수, 평균·최대 탐지 지연은 2/10/2가 더 좋다. 따라서 10/11/1은 이 데이터에서 이벤트 단위 경보 연속성과 중복 억제에 유리하지만, 모든 지표에서 우수한 설정은 아니다.", "",
              "경보 이벤트는 한 센서에서 판정이 연속 True인 구간이다. 정답과 겹치는 경보 하나만 일대일 매칭하고 남은 경보는 추가 경보로 센다. 이상 구간에 겹친 추가 조각과 이상 사건에 전혀 겹치지 않는 순수 오경보를 구분해야 한다. 정상 행 경보(row FP)는 그와 별개의 행 단위 지표다.", "",
              "지연은 매칭된 경보의 시작 시각 기준이고, 이상 시작 전부터 유지된 경보의 지연은 0이다. 전체 원인 파악 또는 조치 완료 시간을 뜻하지 않는다.", "",
              "## 평가 이벤트별 탐지 지연", "",
              "| 이벤트 | 유형 | 2/10/2(분) | 10/11/1(분) |", "|---|---|---:|---:|"]
    test_events = events[events['split'].eq('test')]
    for event_id, group in test_events.groupby('event_id', sort=True):
        indexed = group.set_index('config_name')
        lines.append(f"| {event_id} | {group.iloc[0].anomaly_type} | {indexed.loc['mean2_stuck10_stride2', 'delay_min']:.2f} | {indexed.loc['mean10_stuck11_stride1', 'delay_min']:.2f} |")
    lines += ["", "## 보고 범위와 재현", "",
              "이 결과는 이미 사용한 데이터의 재비교다. 학습 지표는 적합에 사용한 데이터의 결과이며, 신규 독립 평가나 일반화 우위의 증거가 아니다. 검증에서 정해진 기준의 선택값 2/10/2와 기존 평가 이벤트 F1이 높은 비교 설정 10/11/1의 이력을 함께 보존한다.", "",
              "검증은 4건뿐이고 SPIKE·CORRELATED가 없으며, 평가에는 STUCK이 없다. 평가 결과만으로 STUCK 길이 10과 11의 우열을 확정할 수 없다. 2/10/2의 판정 시작 위치 민감도는 기존 README_JOINT_WINDOW_SWEEP.md에도 기록돼 있다.", "",
              "재실행한 모든 행의 예측과 두 설정의 학습·검증·평가 지표를 기존 결과와 대조했다. 설정·입력·기존 결과의 보존 및 코드/산출물 해시는 verification.json과 manifest.json에 있다.", "",
              "```powershell", "$env:PYTHONIOENCODING='utf-8'", "$env:MPLCONFIGDIR=Join-Path (Get-Location) 'tmp/matplotlib-policy'",
              ".\\.venv\\Scripts\\python.exe compare_window_pair.py --record-date 2026-10-06", "```", ""]
    (output / "report_ko.md").write_text("\n".join(lines), encoding="utf-8")


def run(record_date):
    OUT.mkdir(parents=True, exist_ok=True)
    old_metrics_path = ROOT / 'experiments/joint_window_sweep_v1/comparison_metrics.csv'
    selected_path = ROOT / 'experiments/joint_window_sweep_v1/selected_model.json'
    parameter_path = ROOT / 'experiments/joint_window_sweep_v1/normalization_parameters.csv'
    protected = [ROOT / 'iMAKS_dataset.zip', selected_path, old_metrics_path, parameter_path]
    protected += [ROOT / p for _, p in REFERENCES.values()]
    protected += [p for p in (ROOT / 'preprocessed/common_v1').rglob('*') if p.is_file()]
    before = {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in protected}
    selected = json.loads(selected_path.read_text(encoding='utf-8'))['config']
    if any(selected[k] != v for k, v in PAIRS['mean2_stuck10_stride2'].items()):
        raise ValueError('Prior validation-selected configuration changed')
    if selected['instant_k'] != CONFIG['instant_k'] or selected['rolling_k'] != CONFIG['rolling_k']:
        raise ValueError('Thresholds differ from frozen selection')
    protocol = {'record_date': record_date, 'experiment_kind': 'existing_data_fixed_pair_reevaluation',
                'new_independent_test': False, 'synthetic_data_generated': False, 'retuned': False,
                'default_detector_changed': False, 'configs': PAIRS, 'detector': CONFIG,
                'sampling_seconds': 30, 'phase_samples': 0,
                'stride_policy': 'causal forward hold; reset at sensor/gap/split',
                'evaluation': 'all original rows including warmup; legacy one-to-one event overlap',
                'normalization': 'same train-only median/MAD, including contaminated training',
                'leakage_policy': 'no quality, labels, raw thresholds or derived threshold features'}
    dump(OUT / 'protocol.json', protocol)
    data = load_common_detection_data()
    base, parameters = make_base(data.ml)
    pd.testing.assert_frame_equal(base[data.ml.columns], data.ml, check_exact=True)
    prior_parameters = pd.read_csv(parameter_path).sort_values('sensor_id').reset_index(drop=True)
    fitted = parameters.sort_values('sensor_id').reset_index(drop=True)
    np.testing.assert_array_equal(fitted.sensor_id, prior_parameters.sensor_id)
    np.testing.assert_allclose(fitted[['median', 'mad', 'robust_scale']], prior_parameters[['median', 'mad', 'robust_scale']], rtol=1e-12, atol=1e-12)
    if len(base) != 211200 or int(parameters.fit_rows.sum()) != 47520:
        raise ValueError('Original observation/train counts changed')
    csv(OUT / 'normalization_parameters.csv', parameters)
    predictions = {}
    prediction_file = base[['sensor_id', 'timestamp', 'split', 'segment_id']].copy()
    for name, config in PAIRS.items():
        scored = scored_features(base, config['mean_window_samples'], config['stuck_window_samples'])
        if (FORBIDDEN | set(THRESHOLDS)) & set(scored):
            raise ValueError('Leaking fields in detector features')
        raw_flags = detector_flags(scored, CONFIG)
        flags, decisions = stride_flags(raw_flags, base.segment_position.to_numpy(), config['stride_samples'])
        predictions[name] = (flags, decisions)
        prediction_file[name + '_predicted'] = flags
        prediction_file[name + '_decision'] = decisions
        reference = pd.read_csv(ROOT / REFERENCES[name][1], usecols=['sensor_id', 'timestamp', 'predicted_anomaly'], parse_dates=['timestamp'])
        aligned = align_by_keys(base, reference, ['predicted_anomaly'])
        np.testing.assert_array_equal(flags, aligned.predicted_anomaly.to_numpy())
    # References and labels enter scoring only after both feature/prediction arrays exist.
    prior_metrics = pd.read_csv(old_metrics_path)
    metrics, event_details, predicted_events, row_types = [], [], [], []
    for split in ('train', 'validation', 'test'):
        context, mask, frame = context_for(base, data.labels, data.events, split)
        truth = data.events[data.events['split'].eq(split)][['event_id', 'anomalyType', 'start', 'end']].rename(columns={'anomalyType': 'anomaly_type'})
        types = data.labels.loc[mask, 'anomaly_label'].to_numpy()
        for name, config in PAIRS.items():
            flags, decisions = predictions[name]
            score = context.measure(flags[mask])
            prior = prior_metrics[prior_metrics.model_name.eq(REFERENCES[name][0]) & prior_metrics['split'].eq(split)].iloc[0]
            fields = list(score)
            np.testing.assert_allclose([score[k] for k in fields], prior[fields].astype(float).to_numpy(), rtol=1e-12, atol=1e-12)
            metrics.append(dict(config_name=name, split=split, evaluated_rows=len(frame), decision_count=int(decisions[mask].sum()), **config, **score))
            events = context.events(flags[mask])
            events.insert(0, 'config_name', name)
            events.insert(1, 'split', split)
            predicted_events.append(events)
            matches = context.matches(flags[mask]).merge(truth, on='event_id', how='left', validate='one_to_one')
            matches.insert(0, 'config_name', name)
            matches.insert(1, 'split', split)
            event_details.append(matches)
            for kind in sorted(set(types)):
                kind_mask = types == kind
                rows = int(kind_mask.sum())
                flagged = int(np.count_nonzero(flags[mask] & kind_mask))
                row_types.append(dict(config_name=name, split=split, anomaly_type=kind, rows=rows,
                                      flagged_rows=flagged, unflagged_rows=rows-flagged,
                                      anomaly_row_recall=flagged/rows if kind != 'NORMAL' else np.nan,
                                      normal_false_positive_rate=flagged/rows if kind == 'NORMAL' else np.nan))
    metrics = pd.DataFrame(metrics)
    details = pd.concat(event_details, ignore_index=True)
    csv(OUT / 'comparison_metrics.csv', metrics)
    csv(OUT / 'evaluation/event_matches.csv', details)
    csv(OUT / 'evaluation/predicted_events.csv', pd.concat(predicted_events, ignore_index=True))
    csv(OUT / 'evaluation/row_counts_by_label.csv', pd.DataFrame(row_types))
    csv(OUT / 'row_predictions.csv.gz', prediction_file)
    # Verify prediction serialization independently by keyed original prediction references above.
    serialized = pd.read_csv(OUT / 'row_predictions.csv.gz', parse_dates=['timestamp'])
    pd.testing.assert_frame_equal(serialized, prediction_file, check_exact=True)
    after = {path: sha(ROOT / path) for path in before}
    if before != after:
        raise ValueError('Protected original inputs/results changed')
    dump(OUT / 'input_provenance.json', data.provenance)
    dump(OUT / 'verification.json', {'same_original_rows_and_raw_values': True, 'same_train_normalization': True,
         'row_predictions_match_prior_for_both_configs': True, 'all_six_metrics_match_prior': True,
         'prediction_serialization_exact': True, 'labels_not_in_feature_inputs': True,
         'protected_files_unchanged': True, 'protected_file_count': len(before), 'protected_sha256': before})
    write_report(metrics, details, data.provenance, OUT)
    sources = ['compare_window_pair.py', 'sweep_joint_windows.py', 'joint_window_core.py', 'common_detection_data.py', 'build_normalized_windows.py', 'imaks_pipeline.py']
    outputs = {str(p.relative_to(OUT)).replace('\\', '/'): sha(p) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
    dump(OUT / 'manifest.json', {'record_date': record_date, 'source_archive_sha256': data.provenance['source_archive_sha256'],
         'output_files_sha256': outputs, 'implementation_sha256': {name: sha(ROOT / name) for name in sources}})
    print(metrics[['config_name', 'split', 'event_f1', 'row_f1', 'row_fp', 'mean_delay_min']].to_string(index=False), flush=True)
    print(f'Completed: {OUT}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--record-date', default='2026-10-06')
    run(parser.parse_args().record_date)
