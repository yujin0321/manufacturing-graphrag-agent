"""Build reusable window3 sequences and causal statistics without changing the detector."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from build_normalized_windows import make_windows, normalize_observations, write_csv, write_json
from causal_features import POINT_FEATURES, READY_COLUMNS, WINDOW_FEATURES, add_three_sample_features, feature_schema, feature_table
from common_detection_data import KEYS, align_by_keys, load_common_detection_data
from imaks_pipeline import load_applied_config

ROOT = Path(__file__).resolve().parent
OUT = ROOT/'experiments'/'window3_features_v1'


def build(out=OUT):
    out = Path(out)
    data = load_common_detection_data()
    applied, selection = load_applied_config(data.provenance)
    normalized, parameters = normalize_observations(data.ml)
    fitted = normalized.merge(parameters[['sensor_id','median','robust_scale']],on='sensor_id',validate='many_to_one',sort=False)
    enriched = add_three_sample_features(fitted,segment_column='segment_id')
    points = feature_table(enriched,segment_column='segment_id')
    out.mkdir(parents=True,exist_ok=True)
    print('Writing all point features and fixed normalization parameters',flush=True)
    write_csv(normalized,out/'normalized_observations.csv.gz')
    write_csv(parameters,out/'normalization_parameters.csv')
    write_csv(points,out/'point_features.csv.gz')
    write_csv(points[points.ready_all],out/'combined_features_ready.csv.gz')
    x, index, _ = make_windows(normalized,3)
    ends = index.end_normalized_row.to_numpy(dtype=np.int64)
    starts = index.start_normalized_row.to_numpy(dtype=np.int64)
    offsets = starts[:,None]+np.arange(3)
    raw_x = normalized.value.to_numpy()[offsets]
    index['unit'] = normalized.iloc[ends].unit.to_numpy()
    directory = out/'window_3'
    directory.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(directory/'windows.npz',X=x,X_value=raw_x,start_row=starts,end_row=ends)
    write_csv(index,directory/'index.csv.gz')
    window_features = index[['window_id','sensor_id','timestamp','split','unit']].copy()
    for name in WINDOW_FEATURES:
        window_features[name] = points.iloc[ends][name].to_numpy()
    write_csv(window_features,directory/'features.csv.gz')
    warmup = []
    for branch, ready in [('one_step','ready_1step'),('window_3','ready_3'),('std_11','ready_11')]:
        missing = points.loc[~points[ready],KEYS+['split','segment_id','normalized_row']].copy()
        missing['feature_branch'] = branch
        missing['reason'] = 'insufficient past observations in this sensor/gap/split segment; retained as NaN'
        warmup.append(missing)
    write_csv(pd.concat(warmup,ignore_index=True),out/'audit'/'warmup_rows.csv.gz')
    # Feature generation is finished before any target values are joined.
    labels = align_by_keys(normalized,data.labels,['anomaly_label','dataset_severity'])
    point_labels = normalized[KEYS+['split','normalized_row']].copy()
    point_labels['anomaly_label'] = labels.anomaly_label
    point_labels['dataset_severity'] = labels.dataset_severity
    write_csv(point_labels,out/'evaluation'/'point_labels.csv.gz')
    target = index[['window_id','sensor_id','timestamp','split']].copy()
    target['end_anomaly_label'] = labels.iloc[ends].anomaly_label.to_numpy()
    target['end_dataset_severity'] = labels.iloc[ends].dataset_severity.to_numpy()
    anomaly = labels.anomaly_label.ne('NORMAL').to_numpy()
    target['anomaly_rows_in_window'] = anomaly[offsets].sum(axis=1)
    target['contains_anomaly'] = target.anomaly_rows_in_window.gt(0)
    write_csv(target,out/'evaluation'/'window_3_labels.csv.gz')
    write_csv(data.events,out/'evaluation'/'anomaly_events.csv')
    schema = feature_schema()
    write_json(schema,out/'feature_schema.json')
    write_json({'recorded_date_local':'2026-10-05','input_provenance':data.provenance,
                'applied_detector_config':applied,'selection_source':selection,'feature_schema':schema,
                'normalization':'Train-only per-sensor median/MAD; contaminated training kept; no clipping/imputation/smoothing',
                'tensor_schema':'X signed z and X_value raw units, float64 [windows,3], oldest to newest; start/end refer to normalized_observations',
                'window3_excludes_std11':'window_3/features contains current/one-step/three-sample features only. std_z_11 is separate point context.',
                'primary_target':'Endpoint anomaly label; contains_anomaly is a separate optional target and never a feature.',
                'pipeline_exports':'Both default detector and full pipeline export causal_features.csv.gz, causal_features_ready.csv.gz and feature_schema.json.',
                'detector_changed':False},out/'experiment_config.json')
    report = {'point_rows':len(points),'sensors':len(parameters),'segments':int(normalized.segment_id.nunique()),
              'window_samples':3,'sampling_seconds':30,'stride_samples':1,
              'nominal_window_seconds':90,'first_to_last_seconds':60,
              'full_window_rows':len(index),'window_rows_by_split':index['split'].value_counts().to_dict(),
              'point_rows_by_split':points['split'].value_counts().to_dict(),
              'point_numeric_features':len(POINT_FEATURES),'window_numeric_features':len(WINDOW_FEATURES),
              'ready_all_rows':int(points.ready_all.sum()),
              'warmup_rows':{name:int((~points[name]).sum()) for name in READY_COLUMNS},
              'source_values_changed':0,'imputed_or_zero_padded_rows':0,'detector_changed':False}
    write_json(report,out/'summary.json')
    print('Reading serialized features/tensors/labels back for verification',flush=True)
    from verify_window3_features import verify_artifacts
    verify_artifacts(out,data=data)
    hashes = {path.relative_to(out).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(out.rglob('*')) if path.is_file() and path.name!='manifest.json'}
    write_json({'recorded_date_local':'2026-10-05','output_files_sha256':hashes,
                'input_manifest_sha256':data.provenance['manifest_sha256'],
                'implementation_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                    for name in ['causal_features.py','build_selected_window_features.py','verify_window3_features.py']}},out/'manifest.json')
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
    return report


if __name__=='__main__':
    build()
