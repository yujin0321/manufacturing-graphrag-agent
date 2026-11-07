"""Read saved artifacts back and check their source/array/label correspondence."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from common_detection_data import FORBIDDEN, THRESHOLDS, align_by_keys, load_common_detection_data

ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = ROOT/'experiments'/'robust_windows_v1'


def verify_artifacts(out=DEFAULT_OUT, data=None, update_manifest=True):
    out = Path(out)
    data = data if data is not None else load_common_detection_data()
    points = pd.read_csv(out/'normalized_observations.csv.gz')
    points['timestamp'] = pd.to_datetime(points.timestamp)
    params = pd.read_csv(out/'normalization_parameters.csv').set_index('sensor_id')
    reference = align_by_keys(points, data.ml, ['value','unit'])
    assert np.array_equal(reference.value.to_numpy(), points.value.to_numpy())
    assert reference.unit.equals(points.unit)
    centers = points.sensor_id.map(params['median'])
    scales = points.sensor_id.map(params.robust_scale)
    np.testing.assert_allclose(points.value_z*scales+centers,points.value,rtol=1e-12,atol=1e-12)
    np.testing.assert_allclose(points.z_abs,points.value_z.abs(),rtol=1e-12,atol=1e-12)
    assert not (FORBIDDEN|set(THRESHOLDS)) & set(points)
    labels = align_by_keys(points,data.labels,['anomaly_label','dataset_severity'])
    summary = []
    for size in (10,11):
        directory = out/f'window_{size}'
        index = pd.read_csv(directory/'index.csv.gz')
        features = pd.read_csv(directory/'features.csv.gz')
        targets = pd.read_csv(out/'evaluation'/f'window_{size}_labels.csv.gz')
        assert index[['window_id','sensor_id','timestamp','split']].equals(features[['window_id','sensor_id','timestamp','split']])
        assert index[['window_id','sensor_id','timestamp','split']].equals(targets[['window_id','sensor_id','timestamp','split']])
        assert not (FORBIDDEN|set(THRESHOLDS)) & set(features)
        with np.load(directory/'windows.npz',allow_pickle=False) as stored:
            x = stored['X']; starts=stored['start_row']; ends=stored['end_row']
            np.testing.assert_array_equal(starts,index.start_normalized_row)
            np.testing.assert_array_equal(ends,index.end_normalized_row)
            np.testing.assert_allclose(x,points.value_z.to_numpy()[starts[:,None]+np.arange(size)],rtol=1e-12,atol=1e-12)
            np.testing.assert_allclose(features.z_current,x[:,-1],rtol=1e-12,atol=1e-12)
            np.testing.assert_allclose(features.z_mean,x.mean(axis=1),rtol=1e-12,atol=1e-12)
            np.testing.assert_allclose(features.z_std,x.std(axis=1,ddof=0),rtol=1e-12,atol=1e-12)
            np.testing.assert_allclose(features.z_min,x.min(axis=1),rtol=1e-12,atol=1e-12)
            np.testing.assert_allclose(features.z_max,x.max(axis=1),rtol=1e-12,atol=1e-12)
            np.testing.assert_allclose(features.z_change,x[:,-1]-x[:,0],rtol=1e-12,atol=1e-12)
            np.testing.assert_allclose(features.z_rate_per_min,(x[:,-1]-x[:,0])/((size-1)/2),rtol=1e-12,atol=1e-12)
        endpoint = labels.iloc[ends].reset_index(drop=True)
        assert targets.end_anomaly_label.equals(endpoint.anomaly_label)
        assert targets.end_dataset_severity.fillna('').equals(endpoint.dataset_severity.fillna(''))
        summary.append({'samples':size,'csv_features_and_labels_verified':len(index)})
    point_features=pd.read_csv(out/'point_features.csv.gz')
    combined=pd.read_csv(out/'combined_features_ready.csv.gz')
    assert len(point_features)==len(points)
    assert int(point_features.ready_both.sum())==len(combined)
    assert not (FORBIDDEN|set(THRESHOLDS)) & set(point_features)
    feature_columns=['value_z','z_abs','mean_z_10','mean_abs_z_10','std_z_11']
    assert combined[feature_columns].notna().all().all()
    baseline_path=ROOT/'experiments'/'common_v1_detection'/'row_predictions.csv.gz'
    baseline_comparison=None
    if baseline_path.exists():
        baseline=pd.read_csv(baseline_path)
        baseline['timestamp']=pd.to_datetime(baseline.timestamp)
        aligned=align_by_keys(points,baseline,['z_abs','rolling_z'])
        np.testing.assert_allclose(point_features.z_abs,aligned.z_abs,rtol=1e-10,atol=1e-10)
        np.testing.assert_allclose(point_features.mean_abs_z_10,aligned.rolling_z,rtol=1e-10,atol=1e-10,equal_nan=True)
        baseline_comparison='z_abs and 10-sample absolute rolling z match existing detector.'
    report={'original_observations_preserved':True,'inverse_normalization_verified':True,
            'csv_array_feature_correspondence_verified':summary,
            'endpoint_labels_match_source':True,'combined_rows':len(combined),
            'existing_detector_comparison':baseline_comparison,
            'numeric_csv_tolerance':{'rtol':1e-12,'atol':1e-12},
            'baseline_comparison_tolerance':{'rtol':1e-10,'atol':1e-10}}
    target=out/'verification.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if update_manifest:
        manifest_path=out/'manifest.json'
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['output_files_sha256']['verification.json']=hashlib.sha256(target.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    print(json.dumps(verify_artifacts(),ensure_ascii=True,indent=2))
