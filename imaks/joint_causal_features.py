"""Configurable trailing features for the separately frozen joint experiment."""
import numpy as np

from common_detection_data import FORBIDDEN, THRESHOLDS, checked_keys


def numeric_fields(mean_window, stuck_window):
    one = ['delta_value_1', 'rate_value_1_per_min', 'delta_z_1', 'rate_z_1_per_min']
    trailing = [f'{stat}_{suffix}_{mean_window}' for suffix in ['value', 'z']
                for stat in ['mean', 'std', 'min', 'max', 'range', 'change', 'rate']]
    trailing = [name + '_per_min' if name.startswith('rate_') else name for name in trailing]
    window = ['value_z', 'z_abs'] + one + trailing
    return window + [f'std_z_{stuck_window}'], window


def add_features(base, mean_window, stuck_window):
    for size in [mean_window, stuck_window]:
        if isinstance(size, bool) or not isinstance(size, (int, np.integer)) or size < 2:
            raise ValueError('Window sizes must be integers >=2')
    if mean_window == stuck_window:
        raise ValueError('This exporter requires distinct mean and STUCK window sizes')
    blocked = (FORBIDDEN | set(THRESHOLDS) | {'status', 'alarms'}) & set(base)
    if blocked:
        raise ValueError(f'Forbidden feature input fields: {sorted(blocked)}')
    required = {'sensor_id', 'timestamp', 'split', 'segment_id', 'value', 'median', 'robust_scale'}
    if not required <= set(base):
        raise ValueError(f'Missing feature input fields: {sorted(required - set(base))}')
    checked_keys(base, 'joint causal features')
    if base.segment_id.isna().any() or not base.robust_scale.gt(0).all():
        raise ValueError('Missing segment or invalid normalization scale')
    for column in ['value', 'median', 'robust_scale']:
        if not np.isfinite(base[column].to_numpy(dtype=float)).all():
            raise ValueError('Nonfinite feature source')
    for _, segment in base.groupby('segment_id', sort=False):
        if segment.sensor_id.nunique() != 1 or segment['split'].nunique() != 1:
            raise ValueError('Segment crosses sensor or split')
        if not segment.timestamp.diff().dropna().dt.total_seconds().eq(30).all():
            raise ValueError('Segment crosses time gap or is unsorted')
        if segment['median'].nunique() != 1 or segment.robust_scale.nunique() != 1:
            raise ValueError('Segment changes normalization parameters')
    result = base.copy()
    signed = (base.value - base['median']) / base.robust_scale
    result['value_z'] = signed
    result['z_abs'] = signed.abs()
    grouped = base.groupby('segment_id', sort=False)['value']
    delta = grouped.diff()
    result['delta_value_1'] = delta
    result['rate_value_1_per_min'] = delta / .5
    result['delta_z_1'] = delta / base.robust_scale
    result['rate_z_1_per_min'] = result.delta_z_1 / .5
    roll = lambda method: grouped.transform(lambda x: getattr(x.rolling(mean_window, min_periods=mean_window), method)())
    mean, minimum, maximum = roll('mean'), roll('min'), roll('max')
    std = grouped.transform(lambda x: x.rolling(mean_window, min_periods=mean_window).std(ddof=0))
    first = grouped.shift(mean_window - 1)
    change = base.value - first
    elapsed_min = (mean_window - 1) * .5
    raw_fields = {'mean': mean, 'std': std, 'min': minimum, 'max': maximum,
                  'range': maximum - minimum, 'change': change, 'rate': change / elapsed_min}
    for stat, values in raw_fields.items():
        end = '_per_min' if stat == 'rate' else ''
        result[f'{stat}_value_{mean_window}{end}'] = values
        normalized = (values - base['median']) / base.robust_scale if stat in ['mean', 'min', 'max'] else values / base.robust_scale
        result[f'{stat}_z_{mean_window}{end}'] = normalized
    stuck_std = grouped.transform(lambda x: x.rolling(stuck_window, min_periods=stuck_window).std(ddof=0))
    result[f'std_z_{stuck_window}'] = stuck_std / base.robust_scale
    result['ready_1step'] = delta.notna()
    result[f'ready_{mean_window}'] = mean.notna()
    result[f'ready_{stuck_window}'] = stuck_std.notna()
    result['ready_all'] = result['ready_1step'] & mean.notna() & stuck_std.notna()
    return result


def feature_schema(mean_window, stuck_window, stride):
    point, window = numeric_fields(mean_window, stuck_window)
    return {'mean_window_samples': mean_window, 'stuck_window_samples': stuck_window,
            'sampling_seconds': 30, 'decision_stride_samples': stride, 'decision_interval_seconds': 30 * stride,
            'feature_computation_stride_samples': 1, 'sequence_export_stride_samples': stride,
            'mean_first_to_last_seconds': (mean_window - 1) * 30,
            'stuck_first_to_last_seconds': (stuck_window - 1) * 30,
            'point_numeric_features': point, 'window_numeric_features': window, 'standard_deviation_ddof': 0,
            'normalization': 'Per-sensor train median / max(1.4826*MAD, 1e-8)',
            'delta': 'Current minus previous 30-second observation, signed; divide by 0.5 min for rate',
            'window_change': f'Current minus {mean_window - 1} observations ago; rate divides by {(mean_window - 1)*.5} min',
            'stuck_std': 'Separate trailing raw population std divided by train scale; not derived from the mean sequence',
            'window_tensor': f'Raw and signed-z float64 [windows,{mean_window}], oldest to current, using ALL 30-second observations',
            'decision_policy': 'First observation then position%stride==0; causal hold to next decision; phase0',
            'resets': ['sensor', 'gap!=30seconds', 'split boundary'], 'warmup': 'NaN preserved; no padding or imputation',
            'labels': 'Separate evaluation files; endpoint is primary target; contains_anomaly is separate and never a feature',
            'detector_features_used': ['z_abs', 'abs(mean_z)', 'stuck_flag'],
            'additional_features': 'Delta/rate/min/max/range are generated for later models, not consumed by the current statistical detector'}
