import unittest

import numpy as np
import pandas as pd

from imaks_pipeline import evaluate_events, predictions_to_events
from joint_window_core import EvaluationContext, stride_flags


class JointWindowCoreTests(unittest.TestCase):
    def frame(self, sensors=('a',), samples=12, gap=False):
        records = []
        for sensor in sensors:
            for position in range(samples):
                segment = position >= samples // 2 if gap else False
                seconds = position * 30 + (300 if segment else 0)
                records.append({'sensor_id': sensor,
                                'timestamp': pd.Timestamp('2026-01-07') + pd.Timedelta(seconds=seconds),
                                'segment_id': f'{sensor}-{int(segment)}'})
        return pd.DataFrame(records)

    def truth(self, frame, intervals):
        records = []
        for index, (sensor, start, end) in enumerate(intervals):
            sensor_frame = frame[frame.sensor_id.eq(sensor)].reset_index(drop=True)
            records.append({'event_id': f'GT-{index:04d}', 'sensor_id': sensor,
                            'start': sensor_frame.timestamp.iloc[start],
                            'end': sensor_frame.timestamp.iloc[end]})
        return pd.DataFrame(records, columns=['event_id', 'sensor_id', 'start', 'end'])

    def compare_reference(self, frame, truth, target, flags):
        context = EvaluationContext(frame, truth, target)
        expected_events = predictions_to_events(frame, flags)
        expected_metrics, expected_matches = evaluate_events(expected_events, truth)
        pd.testing.assert_frame_equal(context.events(flags), expected_events, check_dtype=False)
        pd.testing.assert_frame_equal(context.matches(flags), expected_matches, check_dtype=False)
        metrics = context.measure(flags)
        for key, expected in expected_metrics.items():
            if expected is None:
                self.assertIsNone(metrics[key], key)
            else:
                self.assertAlmostEqual(metrics[key], expected, msg=key)
        self.assertEqual(metrics['row_tp'], int(np.count_nonzero(flags & target)))
        self.assertEqual(metrics['row_fp'], int(np.count_nonzero(flags & ~target)))
        self.assertEqual(metrics['row_fn'], int(np.count_nonzero(~flags & target)))
        self.assertEqual(metrics['row_tn'], int(np.count_nonzero(~flags & ~target)))
        self.assertEqual(sum(metrics[key] for key in ['row_tp', 'row_fp', 'row_fn', 'row_tn']), len(frame))
        return metrics

    def test_hand_calculated_fragments_false_alarms_and_delay(self):
        frame = self.frame(('a', 'b'))
        truth = self.truth(frame, [('a', 1, 4), ('a', 6, 8), ('a', 9, 9)])
        flags = np.zeros(len(frame), dtype=bool)
        flags[[2, 4, 6, 7, 10, 13]] = True
        target = np.zeros(len(frame), dtype=bool)
        target[[1, 2, 3, 4, 6, 7, 8, 9]] = True
        metrics = self.compare_reference(frame, truth, target, flags)
        self.assertEqual(metrics['predicted_events'], 5)
        self.assertEqual(metrics['detected_events'], 2)
        self.assertEqual(metrics['missed_events'], 1)
        self.assertEqual(metrics['pure_false_alarm_events'], 2)
        self.assertEqual(metrics['fragment_alarm_events'], 1)
        self.assertEqual(metrics['row_tp'], 4)
        self.assertEqual(metrics['row_fp'], 2)
        self.assertEqual(metrics['row_fn'], 4)
        self.assertEqual(metrics['row_tn'], 14)
        self.assertEqual(metrics['mean_delay_min'], .25)
        self.assertEqual(metrics['max_delay_min'], .5)

    def test_greedy_one_to_one_and_sensor_isolation(self):
        frame = self.frame(('a', 'b'))
        truth = self.truth(frame, [('a', 2, 5), ('a', 0, 3)])
        flags = np.zeros(len(frame), dtype=bool)
        flags[[2, 3, 4, 14, 15, 16]] = True
        context = EvaluationContext(frame, truth, np.zeros(len(frame), dtype=bool))
        metrics = self.compare_reference(frame, truth, np.zeros(len(frame), dtype=bool), flags)
        self.assertEqual(metrics['detected_events'], 1)
        self.assertEqual(metrics['pure_false_alarm_events'], 1)
        self.assertEqual(context.matches(flags).detected.tolist(), [True, False])

    def test_actual_gap_separates_events(self):
        frame = self.frame(samples=12, gap=True)
        truth = self.truth(frame, [('a', 0, 11)])
        metrics = self.compare_reference(frame, truth, np.ones(len(frame), dtype=bool), np.ones(len(frame), dtype=bool))
        self.assertEqual(metrics['predicted_events'], 2)
        self.assertEqual(metrics['fragment_alarm_events'], 1)

    def test_start_time_ties_follow_legacy_pandas_truth_sort(self):
        frame = self.frame(samples=30)
        truth = self.truth(frame, [('a', 0, 29)] * 20).sample(frac=1, random_state=2).reset_index(drop=True)
        flags = np.arange(len(frame)) % 2 == 0
        self.compare_reference(frame, truth, flags, flags)

    def test_seeded_random_samples_match_pandas_reference(self):
        rng = np.random.default_rng(923)
        for iteration in range(30):
            frame = self.frame(('a', 'b', 'c'), samples=40, gap=bool(iteration % 2))
            intervals = []
            for _ in range(7):
                sensor = ('a', 'b', 'c')[rng.integers(3)]
                begin = int(rng.integers(32))
                intervals.append((sensor, begin, begin + int(rng.integers(1, 8))))
            truth = self.truth(frame, intervals).sample(frac=1, random_state=iteration).reset_index(drop=True)
            flags = rng.random(len(frame)) < .27
            target = rng.random(len(frame)) < .2
            with self.subTest(iteration=iteration):
                self.compare_reference(frame, truth, target, flags)

    def test_empty_flags_and_no_truth(self):
        frame = self.frame()
        truth = self.truth(frame, [('a', 2, 5)])
        self.compare_reference(frame, truth, np.zeros(len(frame), dtype=bool), np.zeros(len(frame), dtype=bool))
        no_truth = self.truth(frame, [])
        flags = np.arange(len(frame)) % 2 == 0
        metrics = self.compare_reference(frame, no_truth, np.zeros(len(frame), dtype=bool), flags)
        self.assertEqual(metrics['pure_false_alarm_events'], 6)
        self.assertIsNone(metrics['mean_delay_min'])

    def test_stride_is_causal_and_keeps_every_observation(self):
        raw = np.array([False, True, True, True, False, False, False, True])
        positions = np.arange(len(raw))
        held, decisions = stride_flags(raw, positions, 3)
        np.testing.assert_array_equal(held, [False, False, False, True, True, True, False, False])
        np.testing.assert_array_equal(decisions, [True, False, False, True, False, False, True, False])
        changed = raw.copy()
        changed[6:] = True
        changed_held, _ = stride_flags(changed, positions, 3)
        np.testing.assert_array_equal(held[:6], changed_held[:6])
        self.assertEqual(len(held), len(raw))

    def test_stride_gap_or_split_restart_does_not_carry_alarm(self):
        raw = np.array([True, False, False, False, True, True])
        positions = np.array([0, 1, 2, 0, 1, 2])
        held, decisions = stride_flags(raw, positions, 3)
        np.testing.assert_array_equal(held, [True, True, True, False, False, False])
        np.testing.assert_array_equal(decisions, [True, False, False, True, False, False])

    def test_short_anomaly_can_be_missed_between_decisions(self):
        raw = np.array([False, True, True, False, False])
        held, _ = stride_flags(raw, np.arange(len(raw)), 3)
        self.assertFalse(held.any())
        stride_one, decisions = stride_flags(raw, np.arange(len(raw)), 1)
        np.testing.assert_array_equal(stride_one, raw)
        self.assertTrue(decisions.all())

    def test_invalid_stride_positions_and_context_are_rejected(self):
        for stride in [0, -1, 1.5, True]:
            with self.subTest(stride=stride), self.assertRaises(ValueError):
                stride_flags([False, True], np.array([0, 1]), stride)
        for positions in [np.array([1, 2]), np.array([0, 2]), np.array([0, -1]), np.array([0., 1.])]:
            with self.subTest(positions=positions.tolist()), self.assertRaises(ValueError):
                stride_flags([False, True], positions, 1)
        with self.assertRaises(ValueError):
            stride_flags([False], np.array([0, 1]), 1)
        frame = self.frame()
        truth = self.truth(frame, [])
        with self.assertRaises(ValueError):
            EvaluationContext(frame.iloc[::-1].reset_index(drop=True), truth, np.zeros(len(frame), dtype=bool))
        with self.assertRaises(ValueError):
            EvaluationContext(frame.assign(split=['train'] * 6 + ['validation'] * 6), truth, np.zeros(len(frame), dtype=bool))
        context = EvaluationContext(frame, truth, np.zeros(len(frame), dtype=bool))
        with self.assertRaises(ValueError):
            context.measure([False])


if __name__ == '__main__':
    unittest.main()
