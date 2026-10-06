"""Reexecute frozen joint settings, sequences and features in a separate bundle."""
import argparse
from datetime import date
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd

from build_normalized_windows import make_windows
from common_detection_data import KEYS, THRESHOLDS, align_by_keys, load_common_detection_data
from imaks_pipeline import detector_flags, rule_threshold_flags
from joint_causal_features import add_features, feature_schema, numeric_fields
from joint_window_core import EvaluationContext, stride_flags
from sweep_joint_windows import ROOT, protected_hashes, make_base, scored_features, sha256, dump

OUT = ROOT / 'experiments/joint_preprocessing_rerun_v1'
SELECTION = ROOT / 'experiments/joint_window_sweep_v1'


def save_csv(path,frame):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    compression={'method':'gzip','compresslevel':1} if path.suffix=='.gz' else None
    frame.to_csv(path,index=False,encoding='utf-8-sig',compression=compression)


def protected_snapshot():
    result = protected_hashes()
    result.update({path.relative_to(ROOT).as_posix(): sha256(path)
                   for path in SELECTION.rglob('*') if path.is_file()})
    return result


def load_frozen(provenance):
    manifest = json.loads((SELECTION/'manifest.json').read_text(encoding='utf-8'))
    for name in ['selected_model.json', 'protocol.json', 'validation_ranking.csv']:
        if sha256(SELECTION/name) != manifest['output_files_sha256'][name]:
            raise ValueError(f'Joint selection artifact changed: {name}')
    frozen = json.loads((SELECTION/'selected_model.json').read_text(encoding='utf-8'))
    if frozen['input_provenance'] != provenance or frozen['test_used_for_selection']:
        raise ValueError('Input provenance differs from validation selection')
    if sha256(SELECTION/'validation_ranking.csv') != frozen['validation_csv_sha256']:
        raise ValueError('Validation selection hash mismatch')
    config = frozen['config']
    if config['sampling_seconds'] != 30 or config['model'] != 'robust_causal':
        raise ValueError('Unsupported frozen detector')
    return config, {'selected_model_sha256': sha256(SELECTION/'selected_model.json'),
                    'validation_csv_sha256': frozen['validation_csv_sha256'], 'retuned': False}


def run_sensors(out=OUT, record_date='2026-10-06', comparison_baseline10=False):
    date.fromisoformat(record_date)
    out = Path(out)
    before = protected_snapshot()
    dump(out/'audit/protected_hashes_before.json', before)
    data = load_common_detection_data()
    config, selection_source = load_frozen(data.provenance)
    reference_name = 'selected'
    if comparison_baseline10:
        config = {**config,'mean_window_samples':10,'stuck_window_samples':11,'stride_samples':1}
        reference_name = 'previous_mean10_stuck11_stride1'
        selection_source = {**selection_source,'configuration_source':reference_name,
              'is_validation_selected':False,'status':'Previously observed evaluation comparison; not a new blind test or validation reselection'}
    mean, stuck, stride = (config[key] for key in ['mean_window_samples', 'stuck_window_samples', 'stride_samples'])
    sensor_out = out/'sensors'
    base, parameters = make_base(data.ml)
    scored = scored_features(base, mean, stuck)
    enriched = add_features(base, mean, stuck)
    np.testing.assert_allclose(enriched[f'mean_z_{mean}'].abs(), scored.rolling_z, rtol=1e-12, atol=1e-12, equal_nan=True)
    np.testing.assert_allclose(enriched[f'std_z_{stuck}'], scored.std_z, rtol=1e-12, atol=1e-12, equal_nan=True)
    point_fields, window_fields = numeric_fields(mean, stuck)
    meta = ['sensor_id','timestamp','zone','station_id','sensor_type','unit','value','split','segment_id','segment_position','normalized_row']
    readiness = ['ready_1step',f'ready_{mean}',f'ready_{stuck}','ready_all']
    points = enriched[meta+point_fields+readiness].copy()
    raw = detector_flags(scored, config)
    flags, decisions = stride_flags(raw, base.segment_position.to_numpy(), stride)
    normalized = base.drop(columns=['median','robust_scale'])
    save_csv(sensor_out/'normalized_observations.csv.gz', normalized)
    save_csv(sensor_out/'normalization_parameters.csv', parameters)
    save_csv(sensor_out/'point_features.csv.gz', points)
    save_csv(sensor_out/'combined_features_ready.csv.gz', points[points.ready_all])
    safe_scores = ['sensor_id','timestamp','station_id','unit','value','split','segment_id','segment_position','normalized_row',
                   'value_z','z_abs','mean_z','rolling_z','std_z','stuck_flag','mean_ready','stuck_ready']
    rows = scored[safe_scores].assign(is_decision=decisions,raw_flag_at_current_observation=raw,predicted_anomaly=flags)
    save_csv(sensor_out/'row_predictions.csv.gz', rows)
    schema = feature_schema(mean, stuck, stride)
    dump(sensor_out/'feature_schema.json', schema)
    # Complete original-cadence sequences, exported at scheduled decision endpoints.
    x_all, index_all, _ = make_windows(normalized, mean)
    all_ends = index_all.end_normalized_row.to_numpy(dtype=np.int64)
    keep = decisions[all_ends]
    index = index_all.loc[keep].reset_index(drop=True)
    x = x_all[keep]
    starts = index.start_normalized_row.to_numpy(dtype=np.int64)
    ends = index.end_normalized_row.to_numpy(dtype=np.int64)
    offsets = starts[:,None]+np.arange(mean)
    raw_x = base.value.to_numpy()[offsets]
    directory = sensor_out/f'window_{mean}_stride_{stride}'
    directory.mkdir(parents=True,exist_ok=True)
    index['window_id'] = [f'JW{mean}-S{stride}-{i:07d}' for i in range(len(index))]
    index['unit'] = base.iloc[ends].unit.to_numpy()
    np.savez_compressed(directory/'windows.npz',X=x,X_value=raw_x,start_row=starts,end_row=ends)
    save_csv(directory/'index.csv.gz', index)
    window_features = index[['window_id','sensor_id','timestamp','split','unit']].copy()
    for name in window_fields:
        window_features[name] = points.iloc[ends][name].to_numpy()
    save_csv(directory/'features.csv.gz', window_features)
    warmup = []
    for name in readiness[:-1]:
        missing = points.loc[~points[name],KEYS+['split','segment_id','normalized_row']].copy()
        missing['feature_branch'] = name
        missing['reason'] = 'Insufficient past observations; values retained and features left NaN'
        warmup.append(missing)
    save_csv(sensor_out/'audit/warmup_rows.csv.gz', pd.concat(warmup,ignore_index=True))
    # Targets and raw thresholds are accessed only after the feature export is complete.
    labels = align_by_keys(base,data.labels,['anomaly_label','dataset_severity'])
    point_labels = base[KEYS+['split','normalized_row']].assign(anomaly_label=labels.anomaly_label,dataset_severity=labels.dataset_severity)
    save_csv(out/'evaluation/point_labels.csv.gz',point_labels)
    window_labels = index[['window_id','sensor_id','timestamp','split']].copy()
    window_labels['end_anomaly_label'] = labels.iloc[ends].anomaly_label.to_numpy()
    window_labels['end_dataset_severity'] = labels.iloc[ends].dataset_severity.to_numpy()
    anomaly = labels.anomaly_label.ne('NORMAL').to_numpy()
    window_labels['anomaly_rows_in_window'] = anomaly[offsets].sum(axis=1)
    window_labels['contains_anomaly'] = window_labels.anomaly_rows_in_window.gt(0)
    save_csv(out/'evaluation/window_labels.csv.gz',window_labels)
    save_csv(out/'evaluation/anomaly_events.csv',data.events)
    rule = align_by_keys(base,data.rule,['value']+THRESHOLDS)
    np.testing.assert_array_equal(rule.value,base.value)
    rule_raw = rule_threshold_flags(rule)
    rule_held, _ = stride_flags(rule_raw,base.segment_position.to_numpy(),stride)
    metrics = []
    for name, prediction, interval in [('robust_causal',flags,stride),('sop_threshold_stride1',rule_raw,1),
                                       (f'sop_threshold_stride{stride}',rule_held,stride)]:
        for split in ['train','validation','test']:
            mask = base['split'].eq(split).to_numpy()
            frame = base.loc[mask].reset_index(drop=True)
            context = EvaluationContext(frame,data.events[data.events['split'].eq(split)],anomaly[mask])
            measured = context.measure(prediction[mask])
            metrics.append({'model':name,'split':split,'evaluated_rows':len(frame),'stride_samples':interval,
                            'uses_raw_threshold_metadata':name.startswith('sop_threshold'),**measured})
            save_csv(out/'evaluation'/f'{name}_{split}_predicted_events.csv',context.events(prediction[mask]))
            save_csv(out/'evaluation'/f'{name}_{split}_event_matches.csv',context.matches(prediction[mask]))
    metrics = pd.DataFrame(metrics).drop_duplicates(['model','split']).reset_index(drop=True)
    save_csv(out/'evaluation/detection_metrics.csv',metrics)
    reference_path = ROOT/'experiments/common_v1_detection/row_predictions.csv.gz' if comparison_baseline10 else SELECTION/'selected_scores.csv.gz'
    reference = pd.read_csv(reference_path,parse_dates=['timestamp'],float_precision='round_trip')
    if comparison_baseline10:
        reference['is_decision'] = True
    reference = align_by_keys(base,reference,['predicted_anomaly','is_decision','value'])
    np.testing.assert_array_equal(reference.predicted_anomaly,flags)
    np.testing.assert_array_equal(reference.is_decision,decisions)
    np.testing.assert_array_equal(reference.value,base.value)
    expected = pd.read_csv(SELECTION/'comparison_metrics.csv')
    for split in ['train','validation','test']:
        actual = metrics[metrics.model.eq('robust_causal') & metrics['split'].eq(split)].iloc[0]
        old = expected[expected.model_name.eq(reference_name) & expected['split'].eq(split)].iloc[0]
        fields = ['event_f1','row_f1','row_tp','row_fp','row_fn','predicted_events','detected_events','mean_delay_min']
        np.testing.assert_allclose(actual[fields].astype(float),old[fields].astype(float),rtol=1e-12,atol=1e-12)
    restored = pd.read_csv(sensor_out/'point_features.csv.gz',parse_dates=['timestamp'],float_precision='round_trip')
    np.testing.assert_array_equal(restored.value,base.value)
    np.testing.assert_allclose(restored[point_fields],points[point_fields],rtol=0,atol=0,equal_nan=True)
    restored_index = pd.read_csv(directory/'index.csv.gz',parse_dates=['timestamp','window_start'])
    pd.testing.assert_frame_equal(restored_index,index)
    arrays = np.load(directory/'windows.npz')
    np.testing.assert_array_equal(arrays['X'],base.value_z.to_numpy()[offsets])
    np.testing.assert_array_equal(arrays['X_value'],base.value.to_numpy()[offsets])
    assert np.array_equal(base.segment_id.to_numpy()[starts],base.segment_id.to_numpy()[ends])
    assert decisions[ends].all()
    assert (restored_index.timestamp-restored_index.window_start).dt.total_seconds().eq((mean-1)*30).all()
    restored_targets = pd.read_csv(out/'evaluation/window_labels.csv.gz',parse_dates=['timestamp'])
    np.testing.assert_array_equal(restored_targets.end_anomaly_label,labels.iloc[ends].anomaly_label)
    numeric_example = points.loc[base.sensor_id.eq('ST02_SEALING_TMP') & base.segment_position.eq(10)].iloc[0]
    example = json.loads(numeric_example[['timestamp','sensor_id','unit','value']+point_fields].to_json(date_format='iso'))
    dump(sensor_out/'worked_example.json',example)
    summary = {'record_date':record_date,'config':config,'input_provenance':data.provenance,'selection_source':selection_source,
               'observations':len(base),'sensors':int(base.sensor_id.nunique()),'segments':int(base.segment_id.nunique()),
               'point_rows_by_split':base['split'].value_counts().to_dict(),'normalization_fit_rows':int(parameters.fit_rows.sum()),
               'point_numeric_features':len(point_fields),'window_numeric_features':len(window_fields),
               'full_mean_window_endpoints_at_stride1':len(index_all),'exported_decision_mean_windows':len(index),
               'window_rows_by_split':index['split'].value_counts().to_dict(),'decision_rows':int(decisions.sum()),
               'ready_all_point_rows':int(points.ready_all.sum()),'ready_all_decision_rows':int((points.ready_all & decisions).sum()),
               'warmup_point_rows':int((~points.ready_all).sum()),'mean_warmup_rows':int((~points[f'ready_{mean}']).sum()),
               'raw_values_changed':0,'smoothing_imputation_padding':False,'default_detector_changed':False,
               'additional_features_used_by_detector':False,'llm_extraction_evaluation_86_performed':False,
               'configuration_reference':reference_name,'is_validation_selected':not comparison_baseline10}
    dump(sensor_out/'summary.json',summary)
    dump(sensor_out/'verification.json',{'all_flags_and_decisions_match_recorded_reference':True,
         'reference_model':reference_name,'reference_predictions_path':str(reference_path),'all_split_metrics_match':True,
         'raw_values_and_feature_serialization_preserved':True,'sequence_values_and_indices_verified':True,
         'end_labels_aligned_by_keys':True,'evaluated_rows_not_dropped':True})
    after = protected_snapshot()
    changed = [name for name in before.keys() | after.keys() if before.get(name)!=after.get(name)]
    if changed:
        raise ValueError(f'Protected files changed: {changed}')
    dump(out/'audit/preservation_check.json',{'protected_files':len(before),'changed_files':changed})
    dump(out/'run_config.json',{'record_date':record_date,'config':config,'selection_source':selection_source,
         'normalization_fit':'train only; no label filtering','no_retuning':True,'default_detector_changed':False,
         'raw_threshold_policy':f'Rule baseline only; report stride1 and matched-stride{stride} rule conditions (deduplicated if identical)'})
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)
    print(metrics[metrics['split'].eq('test')][['model','event_f1','row_f1','detected_events','predicted_events']].to_string(index=False),flush=True)
    return summary


def finalize(out=OUT,record_date='2026-10-06',report_comparison_baseline10=False):
    out = Path(out)
    sections={'sensors':out/'comparison_mean10_stuck11_stride1/sensors' if report_comparison_baseline10 else out/'sensors',
              'documents':out/'documents','graph':out/'graph'}
    for part,location in sections.items():
        if not (location/'summary.json').is_file():
            raise ValueError(f'Unfinished rerun section: {part}')
    before = json.loads((out/'audit/protected_hashes_before.json').read_text(encoding='utf-8'))
    after = protected_snapshot()
    changed = [name for name in before.keys()|after.keys() if before.get(name)!=after.get(name)]
    if changed:
        raise ValueError(f'Protected files changed during document/graph rerun: {changed}')
    references = {}
    for name in ['rules_ground_truth_original.csv','rules_ground_truth_spd_corrected.csv','evaluation_policy.json']:
        source = ROOT/'preprocessed/common_v1/evaluation'/name
        target = out/'evaluation'/name
        shutil.copyfile(source,target)
        if sha256(source)!=sha256(target):
            raise ValueError(f'Evaluation reference copy differs: {name}')
        references[name] = {'source_sha256':sha256(source),'copy_sha256':sha256(target)}
        if name.endswith('.csv'):
            count = len(pd.read_csv(target))
            if count!=86:
                raise ValueError(f'Expected 86 extraction references: {name}')
            references[name]['rows'] = count
    dump(out/'evaluation/reference_policy.json',{'rules':references,
          'rule_extraction_accuracy_evaluated':False,'rule_reference_used_as_input':False,
          'anomaly_events':14,'row_labels':'sensor_id + timestamp one-to-one',
          'qa_llm_vector_graph_rag_comparison_rerun':False})
    dump(out/'audit/preservation_check.json',{'protected_files':len(before),'changed_files':changed})
    summaries = {part:json.loads((location/'summary.json').read_text(encoding='utf-8')) for part,location in sections.items()}
    dump(out/'summary.json',{'record_date':record_date,'sections':summaries,'default_detector_changed':False,
         'section_directories':{part:str(path.relative_to(out)).replace('\\','/') for part,path in sections.items()},
         'reporting_basis':'User chose prior observed evaluation event F1 highest 10/11/1; not a new blind optimum' if report_comparison_baseline10 else 'Frozen validation-selected 2/10/2'})
    hashes = {path.relative_to(out).as_posix():sha256(path) for path in out.rglob('*') if path.is_file() and path!=out/'manifest.json'}
    sources = ['rerun_joint_preprocessing.py','joint_causal_features.py','rerun_joint_documents.py','rerun_joint_graph.py']
    dump(out/'manifest.json',{'record_date':record_date,'output_files_sha256':hashes,
          'implementation_sha256':{name:sha256(ROOT/name) for name in sources}})
    print(f'Finalized {len(hashes)} output files; {len(before)} previous files preserved',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record-date',default='2026-10-06')
    parser.add_argument('--finalize-only',action='store_true')
    parser.add_argument('--comparison-baseline10',action='store_true',help='Rerun prior mean10/STUCK11/stride1 in a separate comparison folder; never reselect on test')
    args=parser.parse_args()
    if args.finalize_only:
        finalize(record_date=args.record_date,report_comparison_baseline10=args.comparison_baseline10)
    else:
        sensor_out = OUT/'comparison_mean10_stuck11_stride1' if args.comparison_baseline10 else OUT
        run_sensors(out=sensor_out,record_date=args.record_date,comparison_baseline10=args.comparison_baseline10)
