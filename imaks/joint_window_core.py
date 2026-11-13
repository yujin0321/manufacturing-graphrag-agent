"""NumPy evaluation for the joint window search; no fitting or label features.

Truth ordering intentionally uses pandas ``sort_values('start')`` with its
existing default algorithm, exactly as imaks_pipeline.evaluate_events does.
That legacy ordering is not promised to be stable for tied start timestamps.
The ordered truth is frozen once per context, rather than re-sorted per trial.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CADENCE_NS = 30_000_000_000
MINUTE_NS = 60_000_000_000


def _boolean_vector(values, length, name):
    vector = np.asarray(values, dtype=bool)
    if vector.ndim != 1 or len(vector) != length:
        raise ValueError(f'{name} must be a one-dimensional array of length {length}')
    return vector


def stride_flags(raw_flags, positions, stride):
    """Make decisions every stride rows and causally hold within each segment.

    All feature windows still use the original 30-second observations. This
    controls the decision cadence only. Position 0 starts each sensor/gap/split
    segment; no previous segment's decision can carry into that first row.
    """
    if isinstance(stride, (bool, np.bool_)) or not isinstance(stride, (int, np.integer)) or stride < 1:
        raise ValueError('stride must be a positive integer')
    positions = np.asarray(positions)
    if positions.ndim != 1 or positions.dtype.kind not in 'iu':
        raise ValueError('positions must be a one-dimensional integer array')
    flags = _boolean_vector(raw_flags, len(positions), 'raw_flags')
    if len(positions) == 0:
        return flags.copy(), np.empty(0, dtype=bool)
    if positions[0] != 0 or np.any(positions < 0):
        raise ValueError('Each position segment must start at zero and be nonnegative')
    if np.any((positions[1:] != 0) & (positions[1:] != positions[:-1] + 1)):
        raise ValueError('Segment positions must increase by one or restart at zero')
    remainder = positions % int(stride)
    sources = np.arange(len(positions), dtype=np.int64) - remainder.astype(np.int64)
    # Validated positions ensure sources never precede the current segment.
    return flags[sources], remainder == 0


class EvaluationContext:
    """Reusable one-split event and row scoring with the legacy greedy match.

    ``frame`` is sorted by sensor_id/timestamp with a reset index. ``target``
    contains endpoint anomaly labels solely for scoring. No warmup rows are
    dropped. ``measure`` uses no per-prediction pandas loops or DataFrames.
    """

    def __init__(self, frame, truth, target):
        needed = {'sensor_id', 'timestamp', 'segment_id'}
        if not needed <= set(frame):
            raise ValueError(f'frame missing fields: {sorted(needed - set(frame))}')
        if not frame.index.equals(pd.RangeIndex(len(frame))):
            raise ValueError('frame must have a reset index')
        if frame[['sensor_id', 'timestamp', 'segment_id']].isna().any().any():
            raise ValueError('frame has missing sensor/time/segment values')
        if frame.duplicated(['sensor_id', 'timestamp']).any():
            raise ValueError('frame has duplicate sensor/time keys')
        if 'split' in frame and frame['split'].nunique() > 1:
            raise ValueError('EvaluationContext accepts one split at a time')
        self.frame = frame[['sensor_id', 'timestamp', 'segment_id']].copy()
        self.frame['timestamp'] = pd.to_datetime(self.frame.timestamp, errors='raise')
        if not self.frame.equals(self.frame.sort_values(['sensor_id', 'timestamp'], kind='stable')):
            raise ValueError('frame must be sorted by sensor_id and timestamp')
        self._n = len(self.frame)
        self._target = _boolean_vector(target, self._n, 'target').copy()
        self._target_count = int(np.count_nonzero(self._target))
        self._sensors = self.frame.sensor_id.to_numpy()
        self._time = self.frame.timestamp.to_numpy(dtype='datetime64[ns]').view(np.int64)
        self._codes, sensor_names = pd.factorize(self.frame.sensor_id, sort=False)
        self._lookup = {name: code for code, name in enumerate(sensor_names)}
        self._boundary = np.ones(self._n, dtype=bool)
        if self._n > 1:
            segments = self.frame.segment_id.to_numpy()
            self._boundary[1:] = ((self._codes[1:] != self._codes[:-1]) |
                                  (self._time[1:] - self._time[:-1] != CADENCE_NS) |
                                  (segments[1:] != segments[:-1]))

        columns = {'event_id', 'sensor_id', 'start', 'end'}
        if not columns <= set(truth):
            raise ValueError(f'truth missing fields: {sorted(columns - set(truth))}')
        ordered = truth[['event_id', 'sensor_id', 'start', 'end']].copy()
        ordered['start'] = pd.to_datetime(ordered.start, errors='raise')
        ordered['end'] = pd.to_datetime(ordered.end, errors='raise')
        if ordered.isna().any().any() or ordered.start.gt(ordered.end).any():
            raise ValueError('truth has missing values or a reversed interval')
        # Same pandas default sort as the reference, including start-time ties.
        self.truth = ordered.sort_values('start').reset_index(drop=True)
        self._truth_count = len(self.truth)
        self._truth_codes = np.asarray([self._lookup.get(name, -1) for name in self.truth.sensor_id], dtype=np.int64)
        self._truth_start = self.truth.start.to_numpy(dtype='datetime64[ns]').view(np.int64)
        self._truth_end = self.truth.end.to_numpy(dtype='datetime64[ns]').view(np.int64)

    def _runs(self, flags):
        positives = np.flatnonzero(flags)
        if not len(positives):
            empty = np.empty(0, dtype=np.int64)
            return empty, empty
        breaks = ((positives[1:] - positives[:-1] != 1) |
                  self._boundary[positives[1:]])
        return positives[np.r_[True, breaks]], positives[np.r_[breaks, True]]

    def _match(self, starts, ends):
        """Vectorize all overlaps, then greedily consume one prediction per GT."""
        count = len(starts)
        chosen = np.full(self._truth_count, -1, dtype=np.int64)
        delays = np.full(self._truth_count, np.nan, dtype=np.float64)
        offsets = np.full(self._truth_count, np.nan, dtype=np.float64)
        if not count:
            return chosen, delays, offsets, 0
        if not self._truth_count:
            return chosen, delays, offsets, count
        overlaps = ((self._codes[starts, None] == self._truth_codes[None, :]) &
                    (self._time[starts, None] <= self._truth_end[None, :]) &
                    (self._time[ends, None] >= self._truth_start[None, :]))
        pure_false = int(np.count_nonzero(~overlaps.any(axis=1)))
        used = np.zeros(count, dtype=bool)
        for gt_index in range(self._truth_count):
            candidates = np.flatnonzero(overlaps[:, gt_index] & ~used)
            if not len(candidates):
                continue
            prediction = int(candidates[0])
            chosen[gt_index] = prediction
            used[prediction] = True
            offset = float((self._time[starts[prediction]] - self._truth_start[gt_index]) / MINUTE_NS)
            offsets[gt_index] = offset
            delays[gt_index] = max(0., offset)
        return chosen, delays, offsets, pure_false

    def measure(self, flags):
        flags = _boolean_vector(flags, self._n, 'flags')
        starts, ends = self._runs(flags)
        chosen, delays, _, pure_false = self._match(starts, ends)
        detected = int(np.count_nonzero(chosen >= 0))
        predicted = len(starts)
        unmatched = predicted - detected
        event_precision = detected / predicted if predicted else 0.
        event_recall = detected / self._truth_count if self._truth_count else 0.
        finite_delays = delays[chosen >= 0]
        row_tp = int(np.count_nonzero(flags & self._target))
        positive_rows = int(np.count_nonzero(flags))
        row_fp = positive_rows - row_tp
        row_fn = self._target_count - row_tp
        row_tn = self._n - row_tp - row_fp - row_fn
        row_denominator = 2 * row_tp + row_fp + row_fn
        return {
            'true_events': self._truth_count, 'predicted_events': predicted,
            'detected_events': detected, 'unmatched_alarm_events': unmatched,
            'pure_false_alarm_events': pure_false, 'missed_events': self._truth_count - detected,
            'event_precision': event_precision, 'event_recall': event_recall,
            'event_f1': 2 * event_precision * event_recall / (event_precision + event_recall)
                        if event_precision + event_recall else 0.,
            'median_delay_min': float(np.median(finite_delays)) if len(finite_delays) else None,
            'mean_delay_min': float(finite_delays.mean()) if len(finite_delays) else None,
            'max_delay_min': float(finite_delays.max()) if len(finite_delays) else None,
            'fragment_alarm_events': unmatched - pure_false,
            'row_tp': row_tp, 'row_fp': row_fp, 'row_fn': row_fn, 'row_tn': row_tn,
            'row_precision': row_tp / positive_rows if positive_rows else 0.,
            'row_recall': row_tp / self._target_count if self._target_count else 0.,
            'row_f1': 2 * row_tp / row_denominator if row_denominator else 0.,
        }

    def events(self, flags):
        flags = _boolean_vector(flags, self._n, 'flags')
        starts, ends = self._runs(flags)
        return pd.DataFrame({
            'sensor_id': self._sensors[starts],
            'start': pd.to_datetime(self._time[starts]),
            'end': pd.to_datetime(self._time[ends]),
            'rows': ends - starts + 1,
            'prediction_id': [f'P{i:05d}' for i in range(len(starts))],
        })

    def matches(self, flags):
        flags = _boolean_vector(flags, self._n, 'flags')
        starts, ends = self._runs(flags)
        chosen, delays, offsets, _ = self._match(starts, ends)
        records = []
        for index, row in enumerate(self.truth.itertuples(index=False)):
            found = chosen[index] >= 0
            records.append({
                'event_id': row.event_id,
                'prediction_id': f'P{chosen[index]:05d}' if found else None,
                'sensor_id': row.sensor_id, 'detected': bool(found),
                'delay_min': float(delays[index]) if found else None,
                'onset_offset_min': float(offsets[index]) if found else None,
            })
        return pd.DataFrame(records)
