"""Compare causal mean-window lengths; select on validation before test reporting."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from build_normalized_windows import CADENCE, normalize_observations, write_csv, write_json
from common_detection_data import FORBIDDEN, KEYS, THRESHOLDS, align_by_keys, load_common_detection_data
from imaks_pipeline import detector_flags, evaluate_events, predictions_to_events

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'experiments' / 'window_sweep_v1'
WINDOW_SIZES = (3, 5, 10, 15, 20, 30, 60, 120)
STUCK_WINDOW = 11
CONFIG = {'model': 'robust_causal', 'instant_k': 6.0, 'rolling_k': 4.0}
ORDER = ['event_f1', 'unmatched_alarm_events', 'row_f1', 'mean_delay_min', 'window_samples']
ASCENDING = [False, True, False, True, True]


def make_base(observations):
    """Fit on train without labels; keep every observation, including warmup."""
    normalized, parameters = normalize_observations(observations)
    base = normalized.merge(parameters[['sensor_id', 'median', 'robust_scale']],
                            on='sensor_id', validate='many_to_one', sort=False)
    std = base.groupby('segment_id', sort=False).value.transform(
        lambda values: values.rolling(STUCK_WINDOW, min_periods=STUCK_WINDOW).std(ddof=0))
    base['stuck_ready'] = std.notna()
    base['stuck_flag'] = (std < .001 * base['median'].abs().clip(lower=1e-8)).fillna(False)
    base['std_z_11'] = std / base.robust_scale
    return base, parameters


def score_window(base, size):
    if not isinstance(size, (int, np.integer)) or size < 2:
        raise ValueError('Window must be an integer >=2')
    leaking = (FORBIDDEN | set(THRESHOLDS)) & set(base)
    if leaking:
        raise ValueError(f'Forbidden scoring fields: {sorted(leaking)}')
    scored = base.copy()
    # Match the existing detector exactly: raw trailing mean, then train-fitted z.
    mean = scored.groupby('segment_id', sort=False).value.transform(
        lambda values: values.rolling(size, min_periods=size).mean())
    scored['mean_z'] = (mean - scored['median']) / scored.robust_scale
    scored['rolling_z'] = scored.mean_z.abs()
    scored['mean_ready'] = mean.notna()
    return scored


def measure_split(scored, aligned_labels, truth, split, size):
    frame = scored[scored['split'].eq(split)]
    flags = detector_flags(frame, CONFIG)
    pred = predictions_to_events(frame, flags)
    metrics, matches = evaluate_events(pred, truth[truth['split'].eq(split)])
    target = aligned_labels.loc[frame.index, 'anomaly_label'].ne('NORMAL').to_numpy()
    tp = int((flags & target).sum())
    fp = int((flags & ~target).sum())
    fn = int((~flags & target).sum())
    tn = int((~flags & ~target).sum())
    delays = matches.loc[matches.detected, 'delay_min'].dropna()
    metrics.update(
        window_samples=int(size), nominal_window_min=size * CADENCE / 60,
        first_to_last_min=(size - 1) * CADENCE / 60, stride_samples=1,
        stuck_window_samples=STUCK_WINDOW, instant_k=CONFIG['instant_k'], rolling_k=CONFIG['rolling_k'],
        split=split, evaluated_rows=len(frame), anomalous_rows=int(target.sum()),
        mean_ready_rows=int(frame.mean_ready.sum()), mean_warmup_rows=int((~frame.mean_ready).sum()),
        stuck_warmup_rows=int((~frame.stuck_ready).sum()),
        row_tp=tp, row_fp=fp, row_fn=fn, row_tn=tn,
        row_precision=tp/(tp+fp) if tp+fp else 0.,
        row_recall=tp/(tp+fn) if tp+fn else 0.,
        row_f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.,
        mean_delay_min=float(delays.mean()) if len(delays) else None,
        max_delay_min=float(delays.max()) if len(delays) else None,
        fragment_alarm_events=metrics['unmatched_alarm_events']-metrics['pure_false_alarm_events'])
    if tp+fp+fn+tn != len(frame):
        raise ValueError('Evaluation row coverage changed')
    return metrics, pred, matches


def select_window(validation):
    """Only accept validation rows; criteria are declared before experiments."""
    if validation.empty or not validation['split'].eq('validation').all():
        raise ValueError('Selection accepts validation only, never train/test')
    if validation.window_samples.duplicated().any():
        raise ValueError('Duplicate window candidate')
    ranking = validation.sort_values(ORDER, ascending=ASCENDING, na_position='last', kind='stable')
    return int(ranking.iloc[0].window_samples), ranking.reset_index(drop=True)


def check_existing_baseline(scored, measurements):
    """Read-only equivalence to the previous 10/11 detector, not a selection step."""
    baseline = ROOT / 'experiments' / 'common_v1_detection'
    old_rows = pd.read_csv(baseline / 'row_predictions.csv.gz', parse_dates=['timestamp'])
    aligned = align_by_keys(scored, old_rows, ['z_abs', 'rolling_z', 'predicted_anomaly'])
    np.testing.assert_allclose(scored.z_abs, aligned.z_abs, rtol=1e-10, atol=1e-10)
    np.testing.assert_allclose(scored.rolling_z, aligned.rolling_z, rtol=1e-10, atol=1e-10, equal_nan=True)
    np.testing.assert_array_equal(detector_flags(scored, CONFIG), aligned.predicted_anomaly)
    old_metrics = pd.read_csv(baseline / 'detection_metrics.csv')
    old_metrics = old_metrics[old_metrics.model.eq('robust_causal')].set_index('split')
    fields = ['detected_events', 'predicted_events', 'unmatched_alarm_events', 'pure_false_alarm_events',
              'event_f1', 'event_precision', 'event_recall', 'row_tp', 'row_fp', 'row_fn']
    current = measurements[measurements.window_samples.eq(10)].set_index('split')
    np.testing.assert_allclose(current.loc[old_metrics.index, fields].to_numpy(dtype=float),
                               old_metrics[fields].to_numpy(dtype=float), rtol=1e-12, atol=1e-12)
    return {'old_window_10_scores_match': True, 'old_window_10_predictions_match': True,
            'old_window_10_metrics_match': True, 'existing_artifacts_read_only': True}


def plot_results(metrics, selected, out):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    for split, marker in [('validation', 'o'), ('test', 's')]:
        values = metrics[metrics['split'].eq(split)].sort_values('window_samples')
        name = 'Validation (selection)' if split == 'validation' else 'Existing test (report only)'
        axes[0].plot(values.window_samples, values.event_f1, marker=marker, label=name)
        axes[1].plot(values.window_samples, values.row_f1, marker=marker, label=name)
    for ax, title in zip(axes, ['Event F1', 'Point F1']):
        ax.axvline(selected, color='#777777', linestyle='--', label=f'Selected: {selected} samples')
        ax.set_xscale('log')
        ax.set_xticks(WINDOW_SIZES, [str(size) for size in WINDOW_SIZES])
        ax.set(xlabel='Mean window samples (30 s/sample)', ylabel=title, ylim=(0, 1.05), title=title)
        ax.grid(alpha=.25)
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out / 'window_comparison.png', dpi=170)
    plt.close(fig)


def format_table(validation, test):
    rows = ['| 관측 수 | 명목 길이 | 검증 이벤트 F1 | 검증 행 F1 | 평가 이벤트 F1 | 평가 행 F1 | 평가 추가 경보 |',
            '|---:|---:|---:|---:|---:|---:|---:|']
    for size in WINDOW_SIZES:
        val = validation.set_index('window_samples').loc[size]
        held = test.set_index('window_samples').loc[size]
        rows.append(f'| {size} | {size/2:g}분 | {val.event_f1:.1%} | {val.row_f1:.1%} | '
                    f'{held.event_f1:.1%} | {held.row_f1:.1%} | {int(held.unmatched_alarm_events)} |')
    return '\n'.join(rows)


def write_report(metrics, selected, selection, out):
    val = metrics[metrics['split'].eq('validation')]
    test = metrics[metrics['split'].eq('test')]
    best_val = val.set_index('window_samples').loc[selected]
    best_test = test.set_index('window_samples').loc[selected]
    baseline_test = test.set_index('window_samples').loc[10]
    tied = selection['primary_event_f1_ties']
    test_best = int(test.sort_values(['event_f1', 'window_samples'], ascending=[False, True]).iloc[0].window_samples)
    fragments = fragment_diagnostics(selected, out)
    changed_fragments = fragments[fragments.selected_overlap_alarms.ne(fragments.baseline_10_overlap_alarms)]
    diagnostic_rows = ['| 사건 | 선택 윈도우 경보 조각 | 기존 10개 경보 조각 |', '|---|---:|---:|']
    for _, event in changed_fragments.iterrows():
        diagnostic_rows.append(f'| {event.event_id} · {event.sensor_id} | {int(event.selected_overlap_alarms)} | {int(event.baseline_10_overlap_alarms)} |')
    diagnostic_text = '\n'.join(diagnostic_rows) if len(changed_fragments) else '사건별로 겹치는 경보 조각 수가 기존 10개와 같다.'
    report = f'''# 슬라이딩 윈도우 길이 비교 결과

검증 기준으로 선택한 평균 윈도우는 **{selected}개**다. 관측 간격 30초, stride 1개(30초), 명목 길이 {selected/2:g}분, 실제 첫~끝 관측 시간차 {(selected-1)/2:g}분이다. STUCK 판정의 표준편차 윈도우는 11개로 고정했다.

{format_table(val, test)}

## 선택 기준과 해석

학습 구간에서만 센서별 median/MAD를 구했다. 기존 검증에서 선택했던 순간 임계값 6과 평균 임계값 4를 모든 후보에 동일하게 적용했다. 평균 윈도우만 변경했으므로 새 ML 알고리즘 또는 임계값 격자를 비교한 실험은 아니다.

검증 이벤트 F1이 높은 순 → 미매칭 추가 경보가 적은 순 → 검증 행 F1이 높은 순 → 평균 탐지 지연이 짧은 순 → 작은 윈도우 순으로 선택했다. 이 순서는 실험 코드와 protocol.json에 사전 정의했다. 평가 결과를 계산하기 전에 selected_model.json을 저장했다. **평가 수치로 선택을 다시 바꾸지 않았다.**

검증 정답 이벤트는 4건이며 이벤트 F1 최고점 동률 후보는 {', '.join(map(str, tied))}개 관측이다. 따라서 선택은 보조 지표까지 포함한 이 데이터의 검증 기준에 따른 권고이며, 보편적으로 최적인 윈도우라는 뜻은 아니다. 선택값의 검증 행 F1은 {best_val.row_f1:.2%}, 평균 지연은 {best_val.mean_delay_min:g}분이다. 지연은 탐지한 이벤트만 대상으로 정답 사건과 겹치는 첫 경보의 시작 시각에서 사건 시작 시각을 뺀 값이며, 최소 0분으로 계산한다.

기존 평가 구간의 정답 8건 중 선택값은 {int(best_test.detected_events)}건을 탐지했고 경보 {int(best_test.predicted_events)}개를 생성했다. 이벤트 정밀도 {best_test.event_precision:.2%}, 재현율 {best_test.event_recall:.2%}, F1 {best_test.event_f1:.2%}; 행 정밀도 {best_test.row_precision:.2%}, 재현율 {best_test.row_recall:.2%}, F1 {best_test.row_f1:.2%}다. 미매칭 추가 경보 {int(best_test.unmatched_alarm_events)}개 중 실제 이벤트와 전혀 겹치지 않는 경보는 {int(best_test.pure_false_alarm_events)}개, 같은 이벤트에 대한 추가 조각은 {int(best_test.fragment_alarm_events)}개다. 기존 10개 평균의 평가 이벤트 F1은 {baseline_test.event_f1:.2%}였다.

**검증 선택 {selected}개와 평가 이벤트 F1 최고 {test_best}개를 구분해야 한다.** 선택값의 평가 행 F1은 {best_test.row_f1:.2%}, 기존 10개는 {baseline_test.row_f1:.2%}다. 평균 지연은 각각 {best_test.mean_delay_min:g}분과 {baseline_test.mean_delay_min:g}분이다. 사건별 경보 조각 차이는 다음과 같다.

{diagnostic_text}

경보 조각은 정답 사건과 겹치는 경보 구간 수다. 이 값은 현재 데이터의 사건을 설명하기 위한 사후 분석이고 윈도우 선택에는 사용하지 않았다. 선택값으로 바꾸면 모든 지표가 개선된다고 주장할 수 없다. 기존 탐지 코드의 평균10/STUCK11 기본값은 유지했고, 검증에서 선택한 평균{selected}/STUCK11은 별도 실험 설정과 특징 파일로 저장했다.

평가 구간은 이전 단계에서 이미 성능을 확인한 구간의 **재평가**다. 이번 길이 선택에는 쓰지 않았지만 새로운 맹검 시험으로 해석할 수 없다. 다른 후보의 평가값도 선택 후 참고 비교로 기록했다. 추후 새 시간 구간/설비의 데이터에서 일반화 성능을 추가 확인해야 한다.

## 동일한 평가 범위

전체 211,200행(학습 47,520 / 검증 63,360 / 평가 100,320)을 모든 후보에서 평가했다. 평균 윈도우가 차기 전에는 평균 분기만 비활성이고 순간 점수 분기는 작동한다. STUCK 분기도 11개가 준비되기 전에는 비활성이다. NaN을 0으로 채우거나 긴 윈도우의 초기 행을 평가에서 삭제하지 않았다. 각 후보/분할의 mean_warmup_rows와 stuck_warmup_rows를 기록했다.

윈도우는 현재와 과거만 사용하고 센서·30초 시간 공백·학습/검증/평가 경계에서 초기화했다. 원본 관측값·이상값은 보존했다. 정답과 quality/status/alarms 및 raw 임계값 5개는 정규화·피처·통계 탐지 입력에 없다. 라벨은 검증 선택과 결과 채점에만 사용한다. 행 정답은 끝 시점 라벨이며 윈도우 내 어느 시점이든 이상이라는 라벨로 바꾸지 않았다.

이벤트 평가는 기존과 동일하게 같은 센서의 시간 겹침에 대한 1:1 매칭이다. 한 사건에서 생긴 추가 경보 조각은 미매칭으로 계산한다. 일반적인 accuracy는 정상행의 비율이 높아 길이 선택 지표로 쓰지 않았다.

## 산출물과 재현

- validation_selection.csv: 평가값을 섞지 않은 검증 순위표.
- selected_model.json: 선택한 관측 수·고정 임계값·선택 정책·선택 전 검증 기록 해시.
- all_metrics.csv / comparison.csv: 분할별 전체 지표 / 길이별 검증·평가 비교.
- details/: 모든 후보/분할의 이벤트 경보와 정답 매칭.
- event_fragment_comparison.csv: 선택값과 기존 평균10의 사건별 경보 조각·탐지 지연 비교.
- selected_features.csv.gz: 선택한 평균 윈도우의 시점별 정규화 특징·준비 상태, 211,200행. 라벨·예측 포함 안 함.
- selected_row_predictions.csv.gz: 선택 설정의 시점별 경보 결과.
- evaluation/selected_row_labels.csv.gz: sensor_id+timestamp로 대응하는 분리된 채점 정답.
- normalization_parameters.csv / protocol.json: 학습 기준과 입력 해시·분할·윈도우·비교·선택 규칙.
- verification.json / manifest.json: 기존 10개 결과 재현, 모든 후보 행 범위, 저장 후 검증 및 산출물 해시.
- window_comparison.png: 이벤트·행 F1 비교 그림.

실행: `.\\.venv\\Scripts\\python.exe sweep_window_sizes.py`

선택한 특징 파일의 숫자 피처는 value_z, z_abs, mean_z, rolling_z, std_z_11이다. sensor_id/timestamp/zone/station_id/sensor_type/unit/split/segment_id/normalized_row와 ready 상태는 식별·준비 메타데이터다. 현재 비교 탐지기는 z_abs/rolling_z와 별도 STUCK 판정을 사용한다. ready를 새 모델의 숫자 피처로 자동 넣지 않는다. 정규화·윈도우 생성의 기존 10/11 산출물과 탐지 결과는 별도로 보존했다.
'''
    (out / 'report_ko.md').write_text(report, encoding='utf-8')


def fragment_diagnostics(selected, out):
    """Post-selection explanation of fragmentation; never a selection metric."""
    frames = {}
    for size in {selected, 10}:
        frames[size] = (
            pd.read_csv(out / 'details' / f'window_{size}_test_predicted_events.csv', parse_dates=['start', 'end']),
            pd.read_csv(out / 'details' / f'window_{size}_test_event_matches.csv').set_index('event_id'))
    truth = load_common_detection_data().events
    records = []
    for _, event in truth[truth['split'].eq('test')].iterrows():
        record = {'event_id': event.event_id, 'sensor_id': event.sensor_id, 'anomaly_type': event.anomalyType}
        for name, size in [('selected', selected), ('baseline_10', 10)]:
            pred, matches = frames[size]
            record[f'{name}_overlap_alarms'] = int((pred.sensor_id.eq(event.sensor_id) & pred.start.le(event.end) & pred.end.ge(event.start)).sum())
            record[f'{name}_delay_min'] = matches.loc[event.event_id, 'delay_min']
        records.append(record)
    result = pd.DataFrame(records)
    write_csv(result, out / 'event_fragment_comparison.csv')
    return result


def run(out=OUT):
    out.mkdir(parents=True, exist_ok=True)
    protocol = {
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'implementation_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'runtime_versions': {'numpy': np.__version__, 'pandas': pd.__version__, 'matplotlib': matplotlib.__version__},
        'mean_window_candidates': list(WINDOW_SIZES), 'sampling_seconds': CADENCE,
        'stride_samples': 1, 'stuck_std_window_samples': STUCK_WINDOW, 'stuck_std_ddof': 0,
        'stuck_tolerance': '0.001 * abs(train median), with median denominator floor 1e-8',
        'detector_config_fixed': CONFIG,
        'fixed_threshold_source': 'Previously selected on the same validation split; not retuned in this sweep',
        'selection_order': [{'metric': name, 'ascending': direction} for name, direction in zip(ORDER, ASCENDING)],
        'selection_split': 'validation', 'normalization_fit_split': 'train',
        'split_boundaries': {'train_end_exclusive': '2026-01-07 00:00:00', 'validation_end_exclusive': '2026-01-08 00:00:00'},
        'causal_trailing_only': True, 'reset_at': ['sensor', 'gap !=30s', 'split'],
        'evaluation_coverage': 'All original rows in every candidate; unavailable rolling branches stay inactive',
        'row_target': 'Current/endpoint anomaly label, not any anomaly within window',
        'event_matching': 'Same-sensor temporal overlap, one to one; fragments count as unmatched alarms',
        'raw_thresholds_used': False, 'label_use': 'Validation selection and evaluation only',
        'test_status': 'Previously evaluated test split; reevaluation, not a new blind test',
        'test_candidate_comparison': 'Report all candidates after validation selection is frozen; never use for selection'}
    # Persist the rules before computing candidate metrics.
    write_json(protocol, out / 'protocol.json')
    data = load_common_detection_data()
    protocol['input_provenance'] = data.provenance
    write_json(protocol, out / 'protocol.json')
    base, parameters = make_base(data.ml)
    write_csv(parameters, out / 'normalization_parameters.csv')
    aligned_labels = align_by_keys(base, data.labels, ['anomaly_label', 'dataset_severity'])
    write_csv(base[KEYS+['split']].assign(anomaly_label=aligned_labels.anomaly_label,
                                       dataset_severity=aligned_labels.dataset_severity),
              out / 'evaluation' / 'selected_row_labels.csv.gz')
    validation_metrics = []
    for size in WINDOW_SIZES:
        scored = score_window(base, size)
        metrics, pred, matches = measure_split(scored, aligned_labels, data.events, 'validation', size)
        validation_metrics.append(metrics)
        write_csv(pred, out / 'details' / f'window_{size}_validation_predicted_events.csv')
        write_csv(matches, out / 'details' / f'window_{size}_validation_event_matches.csv')
    selected, ranking = select_window(pd.DataFrame(validation_metrics))
    write_csv(ranking, out / 'validation_selection.csv')
    selection = {
        'config': {**CONFIG, 'mean_window_samples': selected, 'stuck_window_samples': STUCK_WINDOW,
                   'sampling_seconds': CADENCE, 'stride_samples': 1},
        'selected_using': 'Validation only, before test metrics', 'selection_order': protocol['selection_order'],
        'primary_event_f1_ties': sorted(ranking.loc[ranking.event_f1.eq(ranking.iloc[0].event_f1), 'window_samples'].astype(int).tolist()),
        'selected_validation_metrics': json.loads(ranking.iloc[0].to_json()),
        'validation_csv_sha256': hashlib.sha256((out / 'validation_selection.csv').read_bytes()).hexdigest(),
        'frozen_before_test_evaluation': True,
        'fit': 'Train-only median/MAD; no label or raw threshold fitting', 'test_used_for_selection': False}
    write_json(selection, out / 'selected_model.json')
    frozen_selection = (out / 'selected_model.json').read_bytes()
    # Only now evaluate training/test. These numbers never enter select_window.
    all_metrics = list(validation_metrics)
    for size in WINDOW_SIZES:
        scored = score_window(base, size)
        for split in ['train', 'test']:
            metrics, pred, matches = measure_split(scored, aligned_labels, data.events, split, size)
            all_metrics.append(metrics)
            write_csv(pred, out / 'details' / f'window_{size}_{split}_predicted_events.csv')
            write_csv(matches, out / 'details' / f'window_{size}_{split}_event_matches.csv')
        if size == selected:
            metadata = ['timestamp', 'zone', 'station_id', 'sensor_id', 'sensor_type', 'value', 'unit',
                        'split', 'segment_id', 'normalized_row']
            features = ['value_z', 'z_abs', 'mean_z', 'rolling_z', 'std_z_11', 'mean_ready', 'stuck_ready']
            write_csv(scored[metadata+features], out / 'selected_features.csv.gz')
            predictions = scored[KEYS+['split']].copy()
            predictions['predicted_anomaly'] = detector_flags(scored, CONFIG)
            write_csv(predictions, out / 'selected_row_predictions.csv.gz')
    metrics = pd.DataFrame(all_metrics).sort_values(['window_samples', 'split']).reset_index(drop=True)
    write_csv(metrics, out / 'all_metrics.csv')
    fields = ['event_f1', 'event_precision', 'event_recall', 'row_f1', 'row_precision', 'row_recall',
              'predicted_events', 'detected_events', 'unmatched_alarm_events', 'pure_false_alarm_events', 'mean_delay_min']
    comparison = metrics[metrics['split'].isin(['validation', 'test'])].pivot(index='window_samples', columns='split', values=fields)
    comparison.columns = [f'{split}_{metric}' for metric, split in comparison.columns]
    comparison = comparison.reset_index()
    comparison['selected_using_validation'] = comparison.window_samples.eq(selected)
    write_csv(comparison, out / 'comparison.csv')
    verified = check_existing_baseline(score_window(base, 10), metrics)
    if not metrics.groupby('split').evaluated_rows.nunique().eq(1).all():
        raise ValueError('Candidate evaluation coverage differs')
    saved_val = pd.read_csv(out / 'validation_selection.csv')
    saved_selected, _ = select_window(saved_val)
    if saved_selected != selected or (out / 'selected_model.json').read_bytes() != frozen_selection:
        raise ValueError('Frozen validation selection changed')
    saved_features = pd.read_csv(out / 'selected_features.csv.gz', parse_dates=['timestamp'])
    saved_predictions = pd.read_csv(out / 'selected_row_predictions.csv.gz', parse_dates=['timestamp'])
    keyed_values = align_by_keys(saved_features, data.ml, ['value'])
    np.testing.assert_array_equal(saved_features.value, keyed_values.value)
    restored_scores = score_window(base, selected)
    np.testing.assert_allclose(saved_features.rolling_z, restored_scores.rolling_z, rtol=1e-10, atol=1e-10, equal_nan=True)
    keyed_predictions = align_by_keys(restored_scores, saved_predictions, ['predicted_anomaly'])
    np.testing.assert_array_equal(keyed_predictions.predicted_anomaly, detector_flags(restored_scores, CONFIG))
    verified.update(all_candidates_identical_evaluation_rows=True, selected_validation_csv_reproduced=True,
                    selection_unchanged_after_test=True, source_values_preserved=True,
                    serialized_selected_features_match=True, serialized_selected_predictions_match=True,
                    observations=len(base), sensors=int(base.sensor_id.nunique()), segments=int(base.segment_id.nunique()))
    write_json(verified, out / 'verification.json')
    plot_results(metrics, selected, out)
    write_report(metrics, selected, selection, out)
    entries = []
    for path in sorted(out.rglob('*')):
        if path.is_file() and path.name != 'manifest.json':
            entries.append({'path': path.relative_to(out).as_posix(), 'bytes': path.stat().st_size,
                            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    write_json({'files': entries, 'selected_mean_window_samples': selected, 'source': data.provenance}, out / 'manifest.json')
    print(format_table(metrics[metrics['split'].eq('validation')], metrics[metrics['split'].eq('test')]))
    print(json.dumps({'selected_mean_window_samples': selected, 'primary_event_f1_ties': selection['primary_event_f1_ties'],
                      'verification': verified}, ensure_ascii=False, indent=2))
    return selected, metrics


if __name__ == '__main__':
    run()
