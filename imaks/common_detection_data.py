"""Validated common_v1 detector inputs and evaluation-only references."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
COMMON = ROOT / 'preprocessed' / 'common_v1'
KEYS = ['sensor_id', 'timestamp']
OBSERVATIONS = ['timestamp', 'zone', 'station_id', 'sensor_id', 'sensor_type', 'value', 'unit']
THRESHOLDS = ['nominal', 'warn_hi', 'crit_hi', 'warn_lo', 'crit_lo']
FORBIDDEN = {'quality', 'anomaly_label', 'severity', 'dataset_severity', 'alarm_flag', 'gt_id', 'day', 'shift', 'batch_id'}


def checked_keys(frame, name):
    if not set(KEYS) <= set(frame):
        raise ValueError(f'{name}: missing sensor/time key')
    if frame[KEYS].isna().any().any() or frame.duplicated(KEYS).any():
        raise ValueError(f'{name}: missing or duplicate sensor/time key')


def align_by_keys(observations, reference, fields):
    """Require an exact key match and retain observation order and index."""
    checked_keys(observations, 'observations')
    checked_keys(reference, 'reference')
    if not set(fields) <= set(reference):
        raise ValueError('Reference fields missing')
    left = observations[KEYS].copy()
    left['_input_order'] = np.arange(len(left))
    joined = left.merge(reference[KEYS + fields], on=KEYS, how='outer',
                        validate='one_to_one', indicator=True, sort=False)
    if not joined['_merge'].eq('both').all():
        counts = joined['_merge'].value_counts().to_dict()
        raise ValueError(f'Sensor/time keys do not match: {counts}')
    joined = joined.sort_values('_input_order', kind='stable').drop(columns=['_input_order', '_merge'])
    joined.index = observations.index
    return joined


def read_verified(base, relative, manifest):
    target = base / relative
    expected = manifest['output_files_sha256'].get(relative)
    # Windows preprocessing manifests contain Windows path separators.
    if expected is None:
        expected = manifest['output_files_sha256'].get(relative.replace('/', '\\'))
    if not target.is_file() or expected is None:
        raise FileNotFoundError(f'Missing common input or manifest entry: {target}. Run prepare_common_data.py.')
    if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
        raise ValueError(f'Common input hash mismatch: {target}. Regenerate common preprocessing rather than silently using altered data.')
    frame = pd.read_csv(target, low_memory=False)
    if 'timestamp' in frame:
        frame['timestamp'] = pd.to_datetime(frame['timestamp'], errors='raise')
    return frame


@dataclass
class DetectionData:
    ml: pd.DataFrame
    rule: pd.DataFrame
    labels: pd.DataFrame
    events: pd.DataFrame
    provenance: dict


def load_common_detection_data(base=COMMON):
    base = Path(base)
    manifest_path = base / 'manifest.json'
    if not manifest_path.exists():
        raise FileNotFoundError(f'{manifest_path} missing; run prepare_common_data.py first. No raw ZIP fallback.')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    paths = {
        'ml': 'inputs/sensors/timeseries_ml_input.csv',
        'rule': 'inputs/sensors/timeseries_rule_input.csv',
        'labels': 'evaluation/row_labels.csv',
        'events': 'evaluation/anomaly_events.csv',
        'metadata': 'metadata/sensor_time_metadata.csv',
    }
    frames = {name: read_verified(base, path, manifest) for name, path in paths.items()}
    ml, rule = frames['ml'], frames['rule']
    if list(ml) != OBSERVATIONS or list(rule) != OBSERVATIONS + THRESHOLDS:
        raise ValueError('Common detector schema differs from the ML/rule policy')
    for frame in [ml, rule]:
        if FORBIDDEN & set(frame):
            raise ValueError('Forbidden detector fields')
        checked_keys(frame, 'common detector input')
        if not np.isfinite(pd.to_numeric(frame.value, errors='raise')).all():
            raise ValueError('Nonfinite observation')
    ml = ml.sort_values(KEYS, kind='stable').reset_index(drop=True)
    rule = rule.sort_values(KEYS, kind='stable').reset_index(drop=True)
    pd.testing.assert_frame_equal(ml, rule[OBSERVATIONS], check_exact=True)
    labels = align_by_keys(ml, frames['labels'], ['anomaly_label', 'dataset_severity', 'alarm_flag', 'split'])
    if labels.anomaly_label.isna().any():
        raise ValueError('Missing anomaly label')
    time_metadata = align_by_keys(ml, frames['metadata'], ['split'])
    expected_split = np.where(ml.timestamp < pd.Timestamp('2026-01-07'), 'train',
                             np.where(ml.timestamp < pd.Timestamp('2026-01-08'), 'validation', 'test'))
    if not (labels['split'].eq(expected_split).all() and time_metadata['split'].eq(expected_split).all()):
        raise ValueError('Common preprocessing split differs from the detection protocol')
    events = frames['events'].rename(columns={'anomaly_type': 'anomalyType'})
    events['start'] = pd.to_datetime(events['start'], errors='raise')
    events['end'] = pd.to_datetime(events['end'], errors='raise')
    if len(events) != 14 or events.event_id.duplicated().any() or events['start'].gt(events['end']).any():
        raise ValueError('Invalid common event reference')
    if not set(events.sensor_id) <= set(ml.sensor_id):
        raise ValueError('Unknown event sensor')
    for boundary in [pd.Timestamp('2026-01-07'), pd.Timestamp('2026-01-08')]:
        if ((events['start'] < boundary) & (events['end'] >= boundary)).any():
            raise ValueError('Split boundary intersects an event')
    event_split = np.where(events['start'] < pd.Timestamp('2026-01-07'), 'train',
                          np.where(events['start'] < pd.Timestamp('2026-01-08'), 'validation', 'test'))
    if not events['split'].eq(event_split).all():
        raise ValueError('Event split mismatch')
    provenance = {'common_directory': str(base), 'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                  'source_archive_sha256': manifest['source_archive_sha256'],
                  'files': {name: {'path': path, 'sha256': hashlib.sha256((base/path).read_bytes()).hexdigest()}
                            for name, path in paths.items()},
                  'rows': len(ml), 'events': len(events), 'label_alignment': 'sensor_id + timestamp, one-to-one; no positional label lookup',
                  'ml_features': ['value'], 'ml_metadata': [c for c in OBSERVATIONS if c != 'value'],
                  'rule_thresholds_allowed': THRESHOLDS, 'raw_zip_fallback': False}
    return DetectionData(ml, rule, labels, events, provenance)
