"""Label-free trailing three-sample features and a separate eleven-sample context."""
from __future__ import annotations

import numpy as np
import pandas as pd

from common_detection_data import FORBIDDEN, THRESHOLDS, checked_keys

CADENCE_SECONDS = 30
WINDOW_SAMPLES = 3
STUCK_SAMPLES = 11
ONE_STEP_FEATURES = ['delta_value_1', 'rate_value_1_per_min', 'delta_z_1', 'rate_z_1_per_min']
THREE_SAMPLE_FEATURES = [
    'mean_value_3', 'std_value_3', 'min_value_3', 'max_value_3', 'range_value_3',
    'change_value_3', 'rate_value_3_per_min',
    'mean_z_3', 'std_z_3', 'min_z_3', 'max_z_3', 'range_z_3', 'change_z_3', 'rate_z_3_per_min',
]
WINDOW_FEATURES = ['value_z', 'z_abs'] + ONE_STEP_FEATURES + THREE_SAMPLE_FEATURES
POINT_FEATURES = WINDOW_FEATURES + ['std_z_11']
READY_COLUMNS = ['ready_1step', 'ready_3', 'ready_11', 'ready_all']
META_COLUMNS = ['sensor_id', 'timestamp', 'zone', 'station_id', 'sensor_type', 'value', 'unit',
                'split', 'segment_id', 'normalized_row']


def add_three_sample_features(frame, segment_column='_segment'):
    """Use fixed train parameters already in frame; never fit or consult labels."""
    blocked = (FORBIDDEN | set(THRESHOLDS) | {'status', 'alarms'}) & set(frame)
    if blocked:
        raise ValueError(f'Forbidden feature input columns: {sorted(blocked)}')
    required = {'sensor_id', 'timestamp', 'value', 'median', 'robust_scale', 'split', segment_column}
    if not required <= set(frame):
        raise ValueError(f'Missing feature fields: {sorted(required-set(frame))}')
    checked_keys(frame, 'causal feature input')
    if frame[segment_column].isna().any():
        raise ValueError('Missing segment')
    for name in ['value', 'median', 'robust_scale']:
        if not np.isfinite(frame[name].to_numpy(dtype=float)).all():
            raise ValueError(f'Nonfinite feature source: {name}')
    if not frame.robust_scale.gt(0).all():
        raise ValueError('Nonpositive normalization scale')
    result = frame.copy()
    signed = (frame.value.to_numpy()-frame['median'].to_numpy()) / frame.robust_scale.to_numpy()
    if 'value_z' in frame:
        np.testing.assert_allclose(frame.value_z, signed, rtol=1e-12, atol=1e-12)
    result['value_z'] = signed
    if 'z_abs' not in result:
        result['z_abs'] = np.abs(signed)
    else:
        np.testing.assert_allclose(result.z_abs, np.abs(signed), rtol=1e-12, atol=1e-12)
    values = {name:np.full(len(frame), np.nan, dtype=np.float64)
              for name in ONE_STEP_FEATURES + THREE_SAMPLE_FEATURES + ['std_z_11']}
    ready_one = np.zeros(len(frame), dtype=bool)
    ready_three = np.zeros(len(frame), dtype=bool)
    ready_eleven = np.zeros(len(frame), dtype=bool)
    for positions in frame.groupby(segment_column, sort=False).indices.values():
        segment = frame.iloc[positions]
        if segment.sensor_id.nunique() != 1 or segment['split'].nunique() != 1:
            raise ValueError('Feature segment crosses a sensor or split')
        if not segment.timestamp.diff().dropna().dt.total_seconds().eq(CADENCE_SECONDS).all():
            raise ValueError('Feature segment crosses a time gap or is unsorted')
        if segment['median'].nunique() != 1 or segment.robust_scale.nunique() != 1:
            raise ValueError('Normalization parameters change within a segment')
        raw = segment.value.to_numpy(dtype=np.float64)
        z = signed[positions]
        delta_positions = positions[1:]
        ready_one[delta_positions] = True
        values['delta_value_1'][delta_positions] = np.diff(raw)
        values['rate_value_1_per_min'][delta_positions] = np.diff(raw)/(CADENCE_SECONDS/60)
        values['delta_z_1'][delta_positions] = np.diff(z)
        values['rate_z_1_per_min'][delta_positions] = np.diff(z)/(CADENCE_SECONDS/60)
        if len(segment) >= WINDOW_SAMPLES:
            ends = positions[WINDOW_SAMPLES-1:]
            ready_three[ends] = True
            for suffix, data in [('value', raw), ('z', z)]:
                matrix = np.lib.stride_tricks.sliding_window_view(data, WINDOW_SAMPLES)
                minimum = matrix.min(axis=1)
                maximum = matrix.max(axis=1)
                values[f'mean_{suffix}_3'][ends] = matrix.mean(axis=1)
                values[f'std_{suffix}_3'][ends] = matrix.std(axis=1, ddof=0)
                values[f'min_{suffix}_3'][ends] = minimum
                values[f'max_{suffix}_3'][ends] = maximum
                values[f'range_{suffix}_3'][ends] = maximum-minimum
                change = matrix[:, -1]-matrix[:, 0]
                values[f'change_{suffix}_3'][ends] = change
                values[f'rate_{suffix}_3_per_min'][ends] = change/((WINDOW_SAMPLES-1)*CADENCE_SECONDS/60)
        # This reproduces the existing detector's raw rolling std -> fitted scale.
        std = segment.value.rolling(STUCK_SAMPLES, min_periods=STUCK_SAMPLES).std(ddof=0)
        values['std_z_11'][positions] = std.to_numpy()/segment.robust_scale.to_numpy()
        ready_eleven[positions[STUCK_SAMPLES-1:]] = True
    for name, data in values.items():
        result[name] = data
    result['ready_1step'] = ready_one
    result['ready_3'] = ready_three
    result['ready_11'] = ready_eleven
    result['ready_all'] = ready_one & ready_three & ready_eleven
    return result


def feature_table(scored, segment_column='_segment'):
    """Export an explicit allowlist; target labels and detector flags are excluded."""
    required = set(POINT_FEATURES + READY_COLUMNS)
    if not required <= set(scored):
        raise ValueError('Three-sample features have not been calculated')
    frame = scored.copy()
    if segment_column != 'segment_id':
        frame['segment_id'] = frame[segment_column]
    if 'normalized_row' not in frame:
        frame['normalized_row'] = np.arange(len(frame), dtype=np.int64)
    metadata = [name for name in META_COLUMNS if name in frame]
    return frame[metadata + POINT_FEATURES + READY_COLUMNS].copy()


def feature_schema():
    return {
        'mean_window_samples':WINDOW_SAMPLES, 'stuck_std_window_samples':STUCK_SAMPLES,
        'sampling_seconds':CADENCE_SECONDS, 'stride_samples':1,
        'nominal_window_seconds':WINDOW_SAMPLES*CADENCE_SECONDS,
        'first_to_last_seconds':(WINDOW_SAMPLES-1)*CADENCE_SECONDS,
        'one_step_elapsed_seconds':CADENCE_SECONDS, 'standard_deviation_ddof':0,
        'point_numeric_features':POINT_FEATURES, 'window3_numeric_features':WINDOW_FEATURES,
        'metadata_columns':META_COLUMNS, 'readiness_metadata':READY_COLUMNS,
        'feature_definitions':{
            'delta_*_1':'Current minus immediately previous observation in the same segment.',
            'rate_*_1_per_min':'One-step difference divided by 0.5 min.',
            'change_*_3':'Last minus first of three trailing observations.',
            'rate_*_3_per_min':'Three-sample endpoint difference divided by 1 min; not a regression slope.',
            'mean/std/min/max/range_*_3':'Statistics of three past-and-current observations; range=max-min.',
            'std_z_11':'Separate eleven-sample raw population rolling std divided by train-fitted scale; not derived from X_3.'},
        'raw_feature_units':'Source value unit; rate_value_* uses that unit per minute.',
        'normalized_feature_units':'Signed train-fitted robust z; rate_z_* uses z per minute.',
        'warmup':'Preserve all observations and NaN features. No zero padding or imputation.',
        'causal':True, 'reset_at':['sensor','time gap','train/validation/test boundary'],
        'labels':'Separate evaluation files only; endpoint label is the primary target.',
        'feature_selection':'Use explicit numeric feature lists, not every numeric column.',
        'detector_use':'Existing z_abs/rolling_z/STUCK flags only; new delta/statistic features do not change flags.'}
