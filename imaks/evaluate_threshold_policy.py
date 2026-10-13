"""Compare rule thresholds and threshold-free statistics in an isolated output directory."""
import imaks_pipeline as pipeline


def main():
    chosen, metrics, _ = pipeline.run_common_detection()
    pipeline.write_json(pipeline.OUT / 'input_policy.json', {
        'quality_allowed': False,
        'threshold_metadata': ['nominal', 'warn_hi', 'crit_hi', 'warn_lo', 'crit_lo'],
        'sop_threshold': 'Raw threshold metadata allowed; uses warn_hi/warn_lo.',
        'robust_causal': 'No raw nominal/threshold metadata or derivatives.',
        'comparison': 'Different detectors, not a same-model feature ablation.',
        'chosen': chosen,
    })
    print(metrics[['model', 'split', 'uses_raw_threshold_metadata', 'row_precision', 'row_recall',
                   'event_precision', 'event_recall', 'event_f1', 'detected_events',
                   'predicted_events']].to_string(index=False))


if __name__ == '__main__':
    main()
