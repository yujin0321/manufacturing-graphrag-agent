"""Verify saved window3 values, differences, boundary resets, labels and pipeline exports."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from causal_features import ONE_STEP_FEATURES, POINT_FEATURES, THREE_SAMPLE_FEATURES, WINDOW_FEATURES
from common_detection_data import FORBIDDEN, KEYS, THRESHOLDS, align_by_keys, load_common_detection_data

ROOT = Path(__file__).resolve().parent
OUT = ROOT/'experiments'/'window3_features_v1'


def verify_artifacts(out=OUT,data=None):
    out = Path(out)
    data = data if data is not None else load_common_detection_data()
    normalized = pd.read_csv(out/'normalized_observations.csv.gz',parse_dates=['timestamp'])
    points = pd.read_csv(out/'point_features.csv.gz',parse_dates=['timestamp'])
    combined = pd.read_csv(out/'combined_features_ready.csv.gz',parse_dates=['timestamp'])
    params = pd.read_csv(out/'normalization_parameters.csv').set_index('sensor_id')
    source = align_by_keys(points,data.ml,['value','unit'])
    np.testing.assert_array_equal(points.value,source.value)
    pd.testing.assert_series_equal(points.unit,source.unit,check_names=False)
    np.testing.assert_allclose(points.value_z*points.sensor_id.map(params.robust_scale)+points.sensor_id.map(params['median']),
                               points.value,rtol=1e-12,atol=1e-12)
    assert not (FORBIDDEN|set(THRESHOLDS)|{'status','alarms','predicted_anomaly','contains_anomaly'}) & set(points)
    expected_one = points.groupby('segment_id').cumcount().ge(1)
    expected_three = points.groupby('segment_id').cumcount().ge(2)
    expected_eleven = points.groupby('segment_id').cumcount().ge(10)
    np.testing.assert_array_equal(points.ready_1step,expected_one)
    np.testing.assert_array_equal(points.ready_3,expected_three)
    np.testing.assert_array_equal(points.ready_11,expected_eleven)
    np.testing.assert_array_equal(points.ready_all,expected_eleven)
    assert points.loc[~expected_one,ONE_STEP_FEATURES].isna().all().all()
    assert points.loc[~expected_three,THREE_SAMPLE_FEATURES].isna().all().all()
    assert points.loc[~expected_eleven,'std_z_11'].isna().all()
    assert points.loc[expected_three,WINDOW_FEATURES].notna().all().all()
    assert combined[POINT_FEATURES].notna().all().all()
    pd.testing.assert_frame_equal(combined.reset_index(drop=True),points.loc[points.ready_all].reset_index(drop=True))
    index = pd.read_csv(out/'window_3'/'index.csv.gz',parse_dates=['timestamp','window_start'])
    windows = pd.read_csv(out/'window_3'/'features.csv.gz',parse_dates=['timestamp'])
    targets = pd.read_csv(out/'evaluation'/'window_3_labels.csv.gz',parse_dates=['timestamp'])
    np.testing.assert_array_equal(index[['window_id','sensor_id','timestamp','split']],windows[['window_id','sensor_id','timestamp','split']])
    np.testing.assert_array_equal(index[['window_id','sensor_id','timestamp','split']],targets[['window_id','sensor_id','timestamp','split']])
    with np.load(out/'window_3'/'windows.npz',allow_pickle=False) as stored:
        x, raw = stored['X'],stored['X_value']
        starts,ends = stored['start_row'],stored['end_row']
        assert x.shape==raw.shape==(len(index),3)
        np.testing.assert_array_equal(starts,index.start_normalized_row)
        np.testing.assert_array_equal(ends,index.end_normalized_row)
        offsets = starts[:,None]+np.arange(3)
        np.testing.assert_allclose(x,normalized.value_z.to_numpy()[offsets],rtol=1e-12,atol=1e-12)
        np.testing.assert_array_equal(raw,normalized.value.to_numpy()[offsets])
        np.testing.assert_array_equal(ends-starts,2)
        np.testing.assert_array_equal(normalized.iloc[starts].segment_id,normalized.iloc[ends].segment_id)
        np.testing.assert_array_equal(normalized.iloc[starts].sensor_id,normalized.iloc[ends].sensor_id)
        np.testing.assert_array_equal(normalized.iloc[starts]['split'],normalized.iloc[ends]['split'])
        assert (index.timestamp-index.window_start).dt.total_seconds().eq(60).all()
        for suffix,matrix in [('value',raw),('z',x)]:
            expected = {'mean':matrix.mean(axis=1),'std':matrix.std(axis=1,ddof=0),
                        'min':matrix.min(axis=1),'max':matrix.max(axis=1),
                        'range':matrix.max(axis=1)-matrix.min(axis=1),
                        'change':matrix[:,-1]-matrix[:,0]}
            for prefix,values in expected.items():
                np.testing.assert_allclose(windows[f'{prefix}_{suffix}_3'],values,rtol=1e-10,atol=1e-10)
            np.testing.assert_allclose(windows[f'rate_{suffix}_3_per_min'],expected['change']/1.,rtol=1e-10,atol=1e-10)
            difference = matrix[:,-1]-matrix[:,-2]
            np.testing.assert_allclose(windows[f'delta_{suffix}_1'],difference,rtol=1e-10,atol=1e-10)
            np.testing.assert_allclose(windows[f'rate_{suffix}_1_per_min'],difference/.5,rtol=1e-10,atol=1e-10)
        np.testing.assert_allclose(windows[WINDOW_FEATURES],points.iloc[ends][WINDOW_FEATURES],rtol=1e-10,atol=1e-10)
        labels = align_by_keys(normalized,data.labels,['anomaly_label','dataset_severity'])
        pd.testing.assert_series_equal(targets.end_anomaly_label,labels.iloc[ends].anomaly_label.reset_index(drop=True),check_names=False)
        pd.testing.assert_series_equal(targets.end_dataset_severity.fillna(''),labels.iloc[ends].dataset_severity.fillna('').reset_index(drop=True),check_names=False)
        anomaly = labels.anomaly_label.ne('NORMAL').to_numpy()
        np.testing.assert_array_equal(targets.anomaly_rows_in_window,anomaly[offsets].sum(axis=1))
        np.testing.assert_array_equal(targets.contains_anomaly,anomaly[offsets].any(axis=1))
    point_labels = pd.read_csv(out/'evaluation'/'point_labels.csv.gz',parse_dates=['timestamp'])
    np.testing.assert_array_equal(point_labels[KEYS],points[KEYS])
    pd.testing.assert_series_equal(point_labels.anomaly_label,labels.anomaly_label,check_names=False)
    pipeline_checks = []
    for directory in [ROOT/'experiments'/'common_v1_detection_window3',ROOT/'pipeline_outputs_window3']:
        reference = pd.read_csv(directory/'row_predictions.csv.gz',parse_dates=['timestamp'])
        aligned = align_by_keys(points,reference,['z_abs','rolling_z'])
        np.testing.assert_allclose(points.z_abs,aligned.z_abs,rtol=1e-10,atol=1e-10)
        np.testing.assert_allclose(points.mean_z_3.abs(),aligned.rolling_z,rtol=1e-10,atol=1e-10,equal_nan=True)
        exported = pd.read_csv(directory/'causal_features.csv.gz',parse_dates=['timestamp'])
        aligned_features = align_by_keys(points,exported,POINT_FEATURES)
        np.testing.assert_allclose(points[POINT_FEATURES],aligned_features[POINT_FEATURES],rtol=1e-10,atol=1e-10,equal_nan=True)
        pipeline_checks.append(directory.relative_to(ROOT).as_posix())
    report = {'source_observations_preserved':True,'inverse_normalization_verified':True,
              'all_point_rows_retained':len(points),'complete_window3_rows':len(index),'combined_ready_rows':len(combined),
              'saved_raw_and_normalized_arrays_match':True,'statistics_delta_and_actual_time_rate_verified':True,
              'sensor_gap_split_boundaries_verified':True,'warmup_nan_no_padding_verified':True,
              'endpoint_and_optional_window_labels_verified':True,'labels_excluded_from_features':True,
              'default_pipeline_feature_exports_match':pipeline_checks,
              'default_detector_scores_unchanged':True}
    (out/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    print(json.dumps(verify_artifacts(),ensure_ascii=False,indent=2))
