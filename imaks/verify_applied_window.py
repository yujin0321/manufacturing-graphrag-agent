"""Run the selected detector and full pipeline; verify window3 and preserve baseline files."""
import hashlib
import json
from unittest.mock import patch

import numpy as np
import pandas as pd

import imaks_pipeline as pipeline
from common_detection_data import align_by_keys, load_common_detection_data

ROOT = pipeline.ROOT
PROTECTED = ['pipeline_outputs', 'experiments/common_v1_detection', 'experiments/robust_windows_v1',
             'experiments/window_sweep_v1', 'preprocessed/common_v1']


def snapshot():
    records = {}
    for directory in PROTECTED:
        records[directory] = {path.relative_to(ROOT/directory).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in sorted((ROOT/directory).rglob('*')) if path.is_file()}
        if not records[directory]:
            raise ValueError(f'Missing reference directory: {directory}')
    return records


def run():
    before = snapshot()
    chosen, metrics, _ = pipeline.run_common_detection()
    pipeline.main()
    data = load_common_detection_data()
    sweep = ROOT/'experiments/window_sweep_v1'
    reference_features = pd.read_csv(sweep/'selected_features.csv.gz',parse_dates=['timestamp'])
    reference_flags = pd.read_csv(sweep/'selected_row_predictions.csv.gz',parse_dates=['timestamp'])
    expected_metrics = pd.read_csv(sweep/'all_metrics.csv')
    expected_metrics = expected_metrics[expected_metrics.window_samples.eq(3)].set_index('split')
    fields = ['event_f1','event_precision','event_recall','detected_events','predicted_events',
              'unmatched_alarm_events','pure_false_alarm_events','row_tp','row_fp','row_fn','row_f1']
    for directory in [pipeline.COMMON_DETECTION_OUT, pipeline.SELECTED_PIPELINE_OUT]:
        rows = pd.read_csv(directory/'row_predictions.csv.gz',parse_dates=['timestamp'])
        values = align_by_keys(rows, reference_features, ['value','z_abs','rolling_z'])
        np.testing.assert_array_equal(rows.value, values.value)
        for name in ['z_abs','rolling_z']:
            np.testing.assert_allclose(rows[name],values[name],rtol=1e-10,atol=1e-10,equal_nan=True)
        flags = align_by_keys(rows,reference_flags,['predicted_anomaly'])
        np.testing.assert_array_equal(rows.predicted_anomaly, flags.predicted_anomaly)
        actual = pd.read_csv(directory/'detection_metrics.csv')
        actual = actual[actual.model.eq('robust_causal')].set_index('split')
        np.testing.assert_allclose(actual.loc[expected_metrics.index,fields].to_numpy(dtype=float),
                                   expected_metrics[fields].to_numpy(dtype=float),rtol=1e-12,atol=1e-12)
        saved_config = json.loads((directory/'selected_model.json').read_text(encoding='utf-8'))
        if saved_config['config'] != chosen:
            raise ValueError('Recorded and applied model differ')
    # A caller can still explicitly reproduce the old baseline without rewriting its files.
    with patch('imaks_pipeline.csv'):
        old = pipeline.fit_scores(data.ml,mean_window_samples=10)
    old_reference = pd.read_csv(ROOT/'experiments/common_v1_detection/row_predictions.csv.gz',parse_dates=['timestamp'])
    values = align_by_keys(old,old_reference,['z_abs','rolling_z','predicted_anomaly'])
    for name in ['z_abs','rolling_z']:
        np.testing.assert_allclose(old[name],values[name],rtol=1e-10,atol=1e-10,equal_nan=True)
    np.testing.assert_array_equal(pipeline.detector_flags(old,chosen),values.predicted_anomaly)
    after = snapshot()
    if before != after:
        raise ValueError('An existing input or experiment artifact changed')
    verification = {'applied_config':chosen, 'rows':len(reference_features),
        'detector_and_full_pipeline_match_sweep_window3':True,
        'scores_predictions_metrics_match':True,'explicit_window10_reproduces_baseline':True,
        'protected_artifacts_unchanged':True,
        'protected_directories':{name:{'files':len(files),'combined_sha256':hashlib.sha256(
            json.dumps(files,sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest()} for name,files in before.items()},
        'test_status':'Existing test reevaluation; no selection or retuning',
        'full_pipeline_output':str(pipeline.SELECTED_PIPELINE_OUT)}
    pipeline.write_json(pipeline.COMMON_DETECTION_OUT/'application_verification.json',verification)
    print(json.dumps(verification,ensure_ascii=False,indent=2))
    return verification


if __name__ == '__main__':
    run()
