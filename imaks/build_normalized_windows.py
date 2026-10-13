"""Create train-fitted normalization and causal single-sensor windows."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from common_detection_data import COMMON, FORBIDDEN, KEYS, THRESHOLDS, align_by_keys, checked_keys, load_common_detection_data

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'experiments' / 'robust_windows_v1'
TRAIN_END = pd.Timestamp('2026-01-07')
VAL_END = pd.Timestamp('2026-01-08')
CADENCE = 30
WINDOWS = (10, 11)
WINDOW_FEATURES = ['z_current', 'z_mean', 'z_std', 'z_min', 'z_max', 'z_change', 'z_rate_per_min']
POINT_FEATURES = ['value_z', 'z_abs', 'mean_z_10', 'mean_abs_z_10', 'std_z_11']


def assign_split(times):
    return np.where(times < TRAIN_END, 'train', np.where(times < VAL_END, 'validation', 'test'))


def normalize_observations(observations):
    """Fit without labels on train only, then retain signed normalized values."""
    forbidden = (FORBIDDEN | set(THRESHOLDS)) & set(observations)
    if forbidden:
        raise ValueError(f'Forbidden normalization input fields: {sorted(forbidden)}')
    frame = observations.copy()
    frame['timestamp'] = pd.to_datetime(frame.timestamp, errors='raise')
    checked_keys(frame, 'normalization input')
    frame['value'] = pd.to_numeric(frame.value, errors='raise')
    if not np.isfinite(frame.value).all():
        raise ValueError('Invalid value; no silent imputation')
    frame = frame.sort_values(KEYS, kind='stable').reset_index(drop=True)
    train = frame[frame.timestamp < TRAIN_END]
    records = []
    for sid, group in train.groupby('sensor_id', sort=True):
        median = float(group.value.median())
        mad = float((group.value - median).abs().median())
        raw_scale = 1.4826 * mad
        records.append({'sensor_id': sid, 'median': median, 'mad': mad,
                        'robust_scale': max(raw_scale, 1e-8), 'scale_floor_used': raw_scale < 1e-8,
                        'fit_rows': len(group), 'fit_start': group.timestamp.min(), 'fit_end': group.timestamp.max()})
    if not records:
        raise ValueError('No training observations')
    parameters = pd.DataFrame(records)
    if set(frame.sensor_id) != set(parameters.sensor_id):
        raise ValueError('A sensor has no training observations; do not fit on validation/test')
    fitted = frame.merge(parameters[['sensor_id','median','robust_scale']], on='sensor_id', validate='many_to_one', sort=False)
    frame['value_z'] = (fitted.value - fitted['median']) / fitted.robust_scale
    frame['z_abs'] = frame.value_z.abs()
    frame['split'] = assign_split(frame.timestamp)
    gap = frame.groupby('sensor_id').timestamp.diff().dt.total_seconds()
    starts = frame.sensor_id.ne(frame.sensor_id.shift()) | gap.ne(CADENCE) | frame['split'].ne(frame['split'].shift())
    frame['segment_id'] = starts.cumsum().astype('int64')
    frame['normalized_row'] = np.arange(len(frame), dtype=np.int64)
    restored = frame.value_z * fitted.robust_scale + fitted['median']
    if not np.allclose(restored, frame.value, rtol=1e-12, atol=1e-12):
        raise ValueError('Normalization inverse check failed')
    return frame, parameters


def make_windows(normalized, size):
    """One window per valid endpoint, never crossing a segment boundary."""
    if size < 2:
        raise ValueError('Window size must be >=2')
    matrices, starts, ends = [], [], []
    for _, segment in normalized.groupby('segment_id', sort=False):
        if len(segment) < size:
            continue
        if segment.sensor_id.nunique() != 1 or segment['split'].nunique() != 1:
            raise ValueError('Segment crosses a sensor or split')
        if not segment.timestamp.diff().dropna().dt.total_seconds().eq(CADENCE).all():
            raise ValueError('Segment has a time gap')
        matrix = np.lib.stride_tricks.sliding_window_view(segment.value_z.to_numpy(dtype=np.float64), size)
        end = segment.normalized_row.to_numpy()[size-1:]
        matrices.append(matrix)
        ends.append(end)
        starts.append(end - (size-1))
    x = np.concatenate(matrices) if matrices else np.empty((0, size), dtype=np.float64)
    end_rows = np.concatenate(ends) if ends else np.empty(0, dtype=np.int64)
    start_rows = np.concatenate(starts) if starts else np.empty(0, dtype=np.int64)
    endpoint = normalized.iloc[end_rows]
    beginning = normalized.iloc[start_rows]
    index = endpoint[['sensor_id', 'timestamp', 'split', 'segment_id']].reset_index(drop=True)
    index.insert(0, 'window_id', [f'W{size}-{i:07d}' for i in range(len(index))])
    index['window_start'] = beginning.timestamp.to_numpy()
    index['start_normalized_row'] = start_rows
    index['end_normalized_row'] = end_rows
    if len(index):
        assert np.array_equal(endpoint.segment_id.to_numpy(), beginning.segment_id.to_numpy())
        assert (index.timestamp - index.window_start).dt.total_seconds().eq((size-1)*CADENCE).all()
    features = index[['window_id', 'sensor_id', 'timestamp', 'split']].copy()
    features['z_current'] = x[:, -1]
    features['z_mean'] = x.mean(axis=1)
    features['z_std'] = x.std(axis=1, ddof=0)
    features['z_min'] = x.min(axis=1) if len(x) else np.empty(0)
    features['z_max'] = x.max(axis=1) if len(x) else np.empty(0)
    features['z_change'] = x[:, -1] - x[:, 0]
    features['z_rate_per_min'] = features.z_change / ((size-1)*CADENCE/60)
    return x, index, features


def write_csv(frame, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding='utf-8-sig', compression='gzip' if path.suffix == '.gz' else None)


def write_json(value, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str) + '\n', encoding='utf-8')


def build():
    data = load_common_detection_data()
    normalized, parameters = normalize_observations(data.ml)
    OUT.mkdir(parents=True, exist_ok=True)
    write_csv(normalized, OUT/'normalized_observations.csv.gz')
    write_csv(parameters, OUT/'normalization_parameters.csv')
    # Labels are consulted only after normalization, solely to write evaluation artifacts.
    labels = align_by_keys(normalized, data.labels, ['anomaly_label', 'dataset_severity'])
    anomaly = labels.anomaly_label.ne('NORMAL').astype('int64')
    point = normalized[['sensor_id','timestamp','split','segment_id','normalized_row','value_z','z_abs']].copy()
    summary, excluded = [], []
    for size in WINDOWS:
        print(f'Building {size}-observation windows', flush=True)
        x, index, features = make_windows(normalized, size)
        directory = OUT/f'window_{size}'
        directory.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(directory/'windows.npz', X=x,
                            start_row=index.start_normalized_row.to_numpy(dtype=np.int64),
                            end_row=index.end_normalized_row.to_numpy(dtype=np.int64))
        write_csv(index, directory/'index.csv.gz')
        write_csv(features, directory/'features.csv.gz')
        ready = np.zeros(len(normalized), dtype=bool)
        ready[index.end_normalized_row.to_numpy(dtype=np.int64)] = True
        point[f'ready_{size}'] = ready
        if size == 10:
            point['mean_z_10'] = np.nan
            point.loc[ready, 'mean_z_10'] = features.z_mean.to_numpy()
            point['mean_abs_z_10'] = point.mean_z_10.abs()
        else:
            point['std_z_11'] = np.nan
            point.loc[ready, 'std_z_11'] = features.z_std.to_numpy()
        warmup = normalized.loc[~ready, ['sensor_id','timestamp','split','segment_id','normalized_row']].copy()
        warmup['window_size'] = size
        warmup['reason'] = 'insufficient past observations in this sensor/gap/split segment'
        excluded.append(warmup)
        # Full-window inputs and endpoint targets share the same window_id/order.
        end_rows = index.end_normalized_row.to_numpy(dtype=np.int64)
        evaluation = index[['window_id','sensor_id','timestamp','split']].copy()
        evaluation['end_anomaly_label'] = labels.iloc[end_rows].anomaly_label.to_numpy()
        evaluation['end_dataset_severity'] = labels.iloc[end_rows].dataset_severity.to_numpy()
        in_window = anomaly.groupby(normalized.segment_id).transform(lambda group:group.rolling(size,min_periods=size).sum())
        evaluation['anomaly_rows_in_window'] = in_window.iloc[end_rows].astype('int64').to_numpy()
        evaluation['contains_anomaly'] = evaluation.anomaly_rows_in_window.gt(0)
        write_csv(evaluation, OUT/'evaluation'/f'window_{size}_labels.csv.gz')
        # Read saved tensors/CSV back and verify their order, values and key linkage.
        with np.load(directory/'windows.npz', allow_pickle=False) as saved:
            assert np.array_equal(saved['X'], x)
            assert np.array_equal(saved['end_row'], end_rows)
            offsets = saved['start_row'][:,None] + np.arange(size)
            assert np.array_equal(saved['X'], normalized.value_z.to_numpy()[offsets])
        reindex = pd.read_csv(directory/'index.csv.gz')
        relabel = pd.read_csv(OUT/'evaluation'/f'window_{size}_labels.csv.gz')
        assert reindex[['window_id','sensor_id','timestamp']].equals(relabel[['window_id','sensor_id','timestamp']])
        counts = index['split'].value_counts().to_dict()
        summary.append({'samples':size,'windows':len(index),'warmup_rows':len(warmup),
                        'per_split':counts,'nominal_coverage_seconds':size*CADENCE,
                        'first_to_last_seconds':(size-1)*CADENCE})
    point['ready_both'] = point.ready_10 & point.ready_11
    write_csv(point, OUT/'point_features.csv.gz')
    write_csv(point[point.ready_both], OUT/'combined_features_ready.csv.gz')
    write_csv(pd.concat(excluded,ignore_index=True), OUT/'audit'/'warmup_rows.csv.gz')
    feature_eval = labels[['sensor_id','timestamp','anomaly_label','dataset_severity']].copy()
    feature_eval['split'] = normalized['split']
    feature_eval['ready_both'] = point.ready_both
    write_csv(feature_eval, OUT/'evaluation'/'point_feature_labels.csv.gz')
    # Verify the statistics are consistent with the existing detector's training fit.
    old_params_path = ROOT/'experiments'/'common_v1_detection'/'trained_parameters.csv'
    detector_check = None
    if old_params_path.exists():
        old_params = pd.read_csv(old_params_path).sort_values('sensor_id').reset_index(drop=True)
        new_params = parameters.sort_values('sensor_id').reset_index(drop=True)
        assert old_params.sensor_id.equals(new_params.sensor_id)
        assert np.allclose(old_params[['median','robust_scale']],new_params[['median','robust_scale']],rtol=1e-12,atol=1e-12)
        detector_check = 'Train median/scale match existing detector parameters.'
    assert np.isfinite(normalized.value_z).all()
    assert len(point) == len(data.ml)
    assert not (FORBIDDEN | set(THRESHOLDS)) & set(point)
    report = {'normalized_rows':len(normalized),'sensors':len(parameters),'segments':int(normalized.segment_id.nunique()),
              'full_windows':summary,'combined_ready_rows':int(point.ready_both.sum()),
              'combined_warmup_rows':int((~point.ready_both).sum()),
              'scale_floor_sensors':int(parameters.scale_floor_used.sum()),
              'inverse_transform_verified':True,'saved_tensors_verified':True,
              'window_endpoint_labels_verified':True,'existing_detector_comparison':detector_check,
              'observations_removed_or_modified':0}
    write_json(report, OUT/'summary.json')
    config = {'input_provenance':data.provenance,
              'normalization':{'formula':'z=(value-median)/max(1.4826*MAD,1e-8)','fit':'train only, per sensor; no label filtering',
                               'signed_values':True,'clipping':False,'imputation':False,'smoothing':False},
              'sampling_seconds':CADENCE,'window_sizes_samples':list(WINDOWS),'stride_samples':1,
              'trailing_only':True,'includes_current':True,'ddof':0,'reset_at':['sensor','time gap','split boundary'],
              'warmup':'Retain original rows and NaN point features; tensors contain full windows only. Never zero-pad.',
              'window_feature_columns':WINDOW_FEATURES,'point_feature_columns':POINT_FEATURES,
              'tensor_schema':'X float64 [windows,samples], oldest to newest, one sensor only; no labels or IDs in X.',
              'labels':'evaluation/ only. Primary point task uses endpoint labels. contains_anomaly is a different optional window-level target; never a feature.',
              'z_rate_per_min':'Last-minus-first signed z divided by actual first-to-last minutes, not linear regression slope.',
              'purpose':'Reusable version of existing 10/11 windows; no new model fit, hyperparameter selection, or test tuning.'}
    write_json(config, OUT/'experiment_config.json')
    from verify_normalized_windows import verify_artifacts
    verify_artifacts(OUT, data=data, update_manifest=False)
    hashes = {str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest()
              for p in OUT.rglob('*') if p.is_file() and p.name != 'manifest.json'}
    write_json({'generated_at_utc':datetime.now(timezone.utc).isoformat(), 'output_files_sha256':hashes,
                'input_manifest_sha256':data.provenance['manifest_sha256']}, OUT/'manifest.json')
    print(json.dumps(report,ensure_ascii=True,indent=2),flush=True)


if __name__ == '__main__':
    build()
