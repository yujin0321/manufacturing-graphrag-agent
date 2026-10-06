"""Offline, reproducible iMAKS detection + graph-assisted retrieval prototype."""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import argparse
import hashlib
import json
import math
import re
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from common_detection_data import COMMON, THRESHOLDS, align_by_keys, load_common_detection_data, read_verified
from causal_features import add_three_sample_features, feature_schema, feature_table

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'pipeline_outputs'
COMMON_DETECTION_OUT = ROOT / 'experiments' / 'common_v1_detection_window3'
SELECTED_PIPELINE_OUT = ROOT / 'pipeline_outputs_window3'
WINDOW_SELECTION = ROOT / 'experiments' / 'window_sweep_v1'
DEFAULT_MEAN_WINDOW = 3
STUCK_WINDOW = 11
TRAIN_END = pd.Timestamp('2026-01-07')
VAL_END = pd.Timestamp('2026-01-08')

def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

def csv(df, name):
    df.to_csv(OUT/name, index=False, encoding='utf-8-sig')

def split_name(ts):
    return np.where(ts < TRAIN_END, 'train', np.where(ts < VAL_END, 'validation', 'test'))

def load_applied_config(input_provenance=None):
    """Use the already frozen validation choice; never retune against new scores."""
    manifest = json.loads((WINDOW_SELECTION/'manifest.json').read_text(encoding='utf-8'))
    paths = {entry['path']:entry['sha256'] for entry in manifest['files']}
    hashes = {}
    for name in ['selected_model.json', 'validation_selection.csv', 'protocol.json']:
        hashes[name] = hashlib.sha256((WINDOW_SELECTION/name).read_bytes()).hexdigest()
        if hashes[name] != paths.get(name):
            raise ValueError(f'Window selection artifact hash mismatch: {name}')
    selection = json.loads((WINDOW_SELECTION/'selected_model.json').read_text(encoding='utf-8'))
    protocol = json.loads((WINDOW_SELECTION/'protocol.json').read_text(encoding='utf-8'))
    if selection.get('test_used_for_selection') is not False or selection.get('frozen_before_test_evaluation') is not True:
        raise ValueError('Window configuration is not frozen from validation')
    if selection['validation_csv_sha256'] != hashes['validation_selection.csv']:
        raise ValueError('Selected window does not match its validation record')
    config = dict(selection['config'])
    expected = {'model':'robust_causal', 'instant_k':6., 'rolling_k':4.,
                'mean_window_samples':DEFAULT_MEAN_WINDOW, 'stuck_window_samples':STUCK_WINDOW,
                'sampling_seconds':30, 'stride_samples':1}
    if config != expected:
        raise ValueError('Frozen selection differs from the applied 3/11 configuration')
    if input_provenance is not None and protocol['input_provenance'] != input_provenance:
        raise ValueError('Current input differs from the data used for window selection')
    source = {'directory':str(WINDOW_SELECTION), 'artifact_sha256':hashes,
              'selected_using':selection['selected_using'], 'selection_order':selection['selection_order'],
              'retuned_on_application':False, 'test_used_for_selection':False}
    return config, source

def load_data():
    """Legacy five-frame interface, now reading common_v1 instead of the ZIP.

    First frame is rule input, not ML input. Fit ML from load_common_detection_data().ml.
    """
    data = load_common_detection_data()
    manifest = json.loads((COMMON/'manifest.json').read_text(encoding='utf-8'))
    nodes = read_verified(COMMON, 'evaluation/kg/nodes_original.csv', manifest)
    edges = read_verified(COMMON, 'evaluation/kg/edges_original.csv', manifest)
    responses = read_verified(COMMON, 'evaluation/human/alarm_response_log_reviewed.csv', manifest)
    responses['ack_timestamp'] = pd.to_datetime(responses.ack_timestamp)
    return data.rule, data.labels, nodes, edges, responses

def truth_events(nodes, edges):
    """For evaluation only; never added to retrieval graph or detector input."""
    ev = nodes[nodes.label.eq('AnomalyEvent')][['nodeId','gtId','startTs','endTs','anomalyType']].copy()
    links = edges[edges.type.eq('triggers') & edges.toId.isin(ev.nodeId)]
    ev = ev.merge(links[['fromId','toId']], left_on='nodeId', right_on='toId', validate='one_to_one')
    ev = ev.merge(nodes[['nodeId','name']], left_on='fromId',right_on='nodeId',validate='many_to_one')
    ev = ev.rename(columns={'name':'sensor_id','startTs':'start','endTs':'end','gtId':'event_id'})
    ev['start'], ev['end'] = pd.to_datetime(ev.start), pd.to_datetime(ev.end)
    # Inclusive event endpoints. Refuse to silently divide any known event.
    for boundary in [TRAIN_END, VAL_END]:
        if ((ev.start < boundary) & (ev.end >= boundary)).any():
            raise ValueError('Split boundary intersects an event; choose another boundary.')
    ev['split'] = split_name(ev.start)
    return ev[['event_id','sensor_id','start','end','anomalyType','split']].sort_values('start').reset_index(drop=True)

def build_static_graph():
    catalog = pd.read_csv(ROOT/'eda_outputs/equipment_sensor_catalog.csv').fillna('')
    original = pd.read_csv(ROOT/'eda_outputs/edges_readable.csv').fillna('')
    records = [{'id': r.nodeId, 'name': r['name'], 'label': r.label,
                'source':'kg_seed/nodes.csv'} for _,r in catalog.iterrows()]
    lookup = {r['id']: r for r in records}
    normalized = []
    for _, r in original.iterrows():
        if r.fromId not in lookup or r.toId not in lookup:
            continue
        kind = r.type
        if kind == 'monitors':
            # Retain one canonical equipment -> sensor edge, with explicit provenance.
            if lookup[r.fromId]['label'] != 'Component':
                continue
            kind = 'has_sensor'
        if kind not in ['has_sensor','feeds_into','correlates_with']:
            continue
        normalized.append({'source':r.fromId,'target':r.toId,'relation':kind,
            'original_relation':r.type,'rule_ref':r.ruleRef,'provenance':'kg_seed/edges.csv'})
    assert len({(e['source'],e['target'],e['relation']) for e in normalized}) == len(normalized)
    graph = {'nodes': records, 'edges':normalized,
             'policy':'Static only; no ground-truth anomaly, future response or causedBy fields.'}
    write_json(OUT/'static_graph.json',graph)
    return graph

def chunks_from_pages(pages, graph):
    chunks = []
    station_names = [n['name'] for n in graph['nodes'] if n['label']=='Component']
    def append(page,text,rule_id=''):
        text = text.strip()
        if not text: return
        entities = [name for name in station_names if name in text or
                    re.search(r'\b'+re.escape(name.split('_')[0])+r'\b',text)]
        chunks.append({'chunk_id':f'C{len(chunks)+1:04d}', 'document':page['document'],
            'page':page['page'],'rule_id':rule_id,'text':text,'entities':entities})
    for p in pages:
        text=p['text']
        # Explicit rule blocks preserve multiline clauses and exact text provenance.
        pattern=r'(?m)^(RULE-[A-Z0-9-]+):.*?(?=^RULE-[A-Z0-9-]+:|^\d+\.\d+\s|\Z)'
        for m in re.finditer(pattern,text,re.S|re.M): append(p,m.group(),m.group(1))
        if 'SOP_003' in p['document']:
            pattern=r'(?m)^(MAINT-\d+)\n.*?(?=^MAINT-\d+\n|^2\. Correlated|\Z)'
            for m in re.finditer(pattern,text,re.S|re.M): append(p,m.group(),m.group(1))
            pos=text.find('2. Correlated Fault Resolution')
            if pos>=0: append(p,text[pos:],'CORRELATED-RESOLUTION')
        if 'SOP_002' in p['document']:
            pattern=r'(?m)^([A-Z0-9_]+) Thresholds\n.*?(?=^[A-Z0-9_]+ Thresholds|^Anomaly Type|\Z)'
            for m in re.finditer(pattern,text,re.S|re.M): append(p,m.group(),'THRESHOLDS-'+m.group(1))
        # Generic chunks keep datasheets, dependency tables and other text searchable.
        for start in range(0,len(text),1000): append(p,text[start:start+1200])
    for c in chunks:
        source = next(p['text'] for p in pages if p['document']==c['document'] and p['page']==c['page'])
        assert c['text'] in source, 'Citation text must exist verbatim on referenced page'
    write_json(OUT/'document_chunks.json',chunks)
    return chunks

def fit_scores(raw, mean_window_samples=DEFAULT_MEAN_WINDOW, stuck_window_samples=STUCK_WINDOW, *, save_parameters=False):
    """Unsupervised robust location/scale fitted only on training values (including contamination)."""
    assert not ({'quality','anomaly_label','severity','dataset_severity','alarm_flag','gt_id','day','shift','batch_id'} | set(THRESHOLDS)) & set(raw.columns), 'Use threshold-free common ML input, not rule or labeled data.'
    for size in [mean_window_samples, stuck_window_samples]:
        if isinstance(size, bool) or not isinstance(size, (int, np.integer)) or size < 2:
            raise ValueError('Window samples must be integers >=2')
    train = raw[raw.timestamp < TRAIN_END]
    params=[]
    for sid, d in train.groupby('sensor_id'):
        med = d.value.median()
        scale = max(float(1.4826*(d.value-med).abs().median()),1e-8)
        params.append({'sensor_id':sid,'median':med,'robust_scale':scale,'fit_rows':len(d)})
    params=pd.DataFrame(params)
    scored=raw.merge(params,on='sensor_id',how='left',validate='many_to_one')
    assert scored.robust_scale.notna().all()
    scored['z_abs'] = ((scored.value-scored['median'])/scored.robust_scale).abs()
    scored['split'] = split_name(scored.timestamp)
    # Past-and-current rolling windows. Restart at gaps AND split boundaries.
    gaps = scored.groupby('sensor_id').timestamp.diff().dt.total_seconds().ne(30)
    boundary = scored['split'].ne(scored['split'].shift()) | scored.sensor_id.ne(scored.sensor_id.shift())
    scored['_segment'] = (gaps | boundary).cumsum()
    groups = scored.groupby('_segment').value
    roll_mean = groups.transform(lambda x:x.rolling(mean_window_samples,min_periods=mean_window_samples).mean())
    roll_std = groups.transform(lambda x:x.rolling(stuck_window_samples,min_periods=stuck_window_samples).std(ddof=0))
    scored['rolling_z'] = ((roll_mean-scored['median'])/scored.robust_scale).abs()
    # >10 samples unchanged: 11-sample window. Domain rule, not learned class label.
    scored['stuck_flag'] = (roll_std < .001*scored['median'].abs().clip(lower=1e-8)).fillna(False)
    if mean_window_samples == DEFAULT_MEAN_WINDOW and stuck_window_samples == STUCK_WINDOW:
        scored = add_three_sample_features(scored)
    scored.attrs['window_config'] = {'mean_window_samples':int(mean_window_samples),
                                    'stuck_window_samples':int(stuck_window_samples),
                                    'sampling_seconds':30, 'stride_samples':1}
    # Direct feature calculation is side-effect free; entrypoints opt into their new output directory.
    if save_parameters:
        csv(params,'trained_parameters.csv')
    return scored

def predictions_to_events(frame, flags):
    frame=frame[['sensor_id','timestamp']].copy()
    frame['flag']=np.asarray(flags,dtype=bool)
    frame=frame.sort_values(['sensor_id','timestamp'])
    changes=(frame.sensor_id.ne(frame.sensor_id.shift()) | frame.flag.ne(frame.flag.shift()) |
             frame.timestamp.diff().dt.total_seconds().ne(30))
    frame['group']=changes.cumsum()
    result=frame[frame.flag].groupby(['sensor_id','group']).agg(start=('timestamp','min'),end=('timestamp','max'),rows=('timestamp','size')).reset_index().drop(columns='group')
    result['prediction_id']=[f'P{i:05d}' for i in range(len(result))]
    return result

def evaluate_events(pred, truth):
    """Strict one-to-one temporal-overlap match; fragments beyond first are unmatched alarms."""
    used=set(); matches=[]
    for _, t in truth.sort_values('start').iterrows():
        candidates=pred[(pred.sensor_id==t.sensor_id)&(pred.start<=t.end)&(pred.end>=t.start)&~pred.prediction_id.isin(used)].sort_values('start')
        if len(candidates):
            p=candidates.iloc[0]; used.add(p.prediction_id)
            matches.append({'event_id':t.event_id,'prediction_id':p.prediction_id,'sensor_id':t.sensor_id,
                            'detected':True,'delay_min':max(0,(p.start-t.start).total_seconds()/60),
                            'onset_offset_min':(p.start-t.start).total_seconds()/60})
        else:
            matches.append({'event_id':t.event_id,'prediction_id':None,'sensor_id':t.sensor_id,
                            'detected':False,'delay_min':None,'onset_offset_min':None})
    tp=len(used); fp=len(pred)-tp; fn=len(truth)-tp
    precision=tp/len(pred) if len(pred) else 0.
    recall=tp/len(truth) if len(truth) else 0.
    delays=[m['delay_min'] for m in matches if m['detected']]
    # Pure false alarms are separate from fragments that overlap an already matched event.
    pure_false=0
    for _,p in pred.iterrows():
        if not ((truth.sensor_id.eq(p.sensor_id)) & (truth.start<=p.end) & (truth.end>=p.start)).any(): pure_false+=1
    return {'true_events':len(truth),'predicted_events':len(pred),'detected_events':tp,
            'unmatched_alarm_events':fp,'pure_false_alarm_events':pure_false,'missed_events':fn,
            'event_precision':precision,'event_recall':recall,
            'event_f1':2*precision*recall/(precision+recall) if precision+recall else 0.,
            'median_delay_min':float(np.median(delays)) if delays else None}, pd.DataFrame(matches)

def detector_flags(scored, config):
    if config['model']=='sop_threshold': return rule_threshold_flags(scored)
    assert not set(THRESHOLDS) & set(scored), 'Rule thresholds reached statistical detector'
    return ((scored.z_abs>config['instant_k']) | (scored.rolling_z>config['rolling_k']) | scored.stuck_flag).to_numpy()

def rule_threshold_flags(rule_input):
    return ((rule_input.value > rule_input.warn_hi) | (rule_input.value < rule_input.warn_lo)).to_numpy()

def run_detection(scored,labeled,truth,rule_input,config=None,selection_source=None):
    if config is None:
        config, selection_source = load_applied_config()
    chosen = dict(config)
    window_config = {key:chosen[key] for key in ['mean_window_samples','stuck_window_samples','sampling_seconds','stride_samples']}
    if scored.attrs.get('window_config') != window_config:
        raise ValueError('Scored windows differ from the selected configuration')
    # Join once by keys; both results follow scored order, regardless of file order.
    aligned_labels = align_by_keys(scored, labeled, ['anomaly_label'])
    if aligned_labels.anomaly_label.isna().any():
        raise ValueError('Missing evaluation label')
    aligned_rule = align_by_keys(scored, rule_input, ['value'] + THRESHOLDS)
    if not np.array_equal(scored.value.to_numpy(), aligned_rule.value.to_numpy()):
        raise ValueError('Rule and ML observations differ')
    val=scored[scored.split.eq('validation')]
    validation_metrics,_=evaluate_events(predictions_to_events(val,detector_flags(val,chosen)),truth[truth.split.eq('validation')])
    csv(pd.DataFrame([{**chosen,**validation_metrics}]),'fixed_config_validation_metrics.csv')
    write_json(OUT/'selected_model.json',{'config':chosen,'selected_using':'Previously frozen validation window selection; no retuning on application',
        'selection_source':selection_source,'fit':'Jan 6 robust median/MAD; no anomaly labels or raw nominal/thresholds',
        'window':f'{chosen["mean_window_samples"]}-sample mean, {chosen["stuck_window_samples"]}-sample std; trailing only, reset at split and gaps; stuck tolerance from training median'})
    metrics=[]; test_pred=None
    for config in [{'model':'sop_threshold'},chosen]:
        for split in ['train','validation','test']:
            d=scored[scored.split.eq(split)]
            flags=rule_threshold_flags(aligned_rule.loc[d.index]) if config['model']=='sop_threshold' else detector_flags(d,config)
            pred=predictions_to_events(d,flags)
            m, matches=evaluate_events(pred,truth[truth.split.eq(split)])
            y=aligned_labels.loc[d.index,'anomaly_label'].ne('NORMAL').to_numpy()
            row_tp=int((flags&y).sum()); row_fp=int((flags&~y).sum()); row_fn=int((~flags&y).sum())
            m.update(model=config['model'],split=split,uses_raw_threshold_metadata=config['model']=='sop_threshold',row_tp=row_tp,row_fp=row_fp,row_fn=row_fn,
                     mean_window_samples=chosen['mean_window_samples'] if config['model']=='robust_causal' else None,
                     stuck_window_samples=chosen['stuck_window_samples'] if config['model']=='robust_causal' else None,
                     row_precision=row_tp/(row_tp+row_fp) if row_tp+row_fp else 0.,
                     row_recall=row_tp/(row_tp+row_fn) if row_tp+row_fn else 0.,
                     row_f1=2*row_tp/(2*row_tp+row_fp+row_fn) if 2*row_tp+row_fp+row_fn else 0.,
                     sensor_days=len(d)*30/86400)
            m['pure_false_alarms_per_sensor_day']=m['pure_false_alarm_events']/m['sensor_days']
            metrics.append(m)
            csv(pred,f'{config["model"]}_{split}_predicted_events.csv')
            csv(matches,f'{config["model"]}_{split}_event_matches.csv')
            if split=='test' and config['model']=='robust_causal': test_pred=pred
    result=pd.DataFrame(metrics); csv(result,'detection_metrics.csv')
    minimal=scored[['timestamp','sensor_id','station_id','value','split','z_abs','rolling_z']].copy()
    minimal['predicted_anomaly']=detector_flags(scored,chosen)
    minimal.to_csv(OUT/'row_predictions.csv.gz',index=False,compression='gzip')
    features = feature_table(scored)
    csv(features, 'causal_features.csv.gz')
    csv(features[features.ready_all], 'causal_features_ready.csv.gz')
    write_json(OUT/'feature_schema.json', feature_schema())
    fig,axes=plt.subplots(1,2,figsize=(11,4))
    test=result[result.split.eq('test')].set_index('model')
    test[['event_precision','event_recall']].plot.bar(ax=axes[0],ylim=(0,1.05),rot=10,title='Existing test reevaluation: event metrics')
    test[['unmatched_alarm_events','pure_false_alarm_events','missed_events']].plot.bar(ax=axes[1],rot=10,title='Existing test: extra alarms / missed events')
    fig.tight_layout(); fig.savefig(OUT/'detection_comparison.png',dpi=150); plt.close(fig)
    return chosen,result,test_pred

def tokenize(text):
    return re.findall(r'[a-z]+|\d+(?:\.\d+)?',text.lower())

class Retriever:
    def __init__(self,chunks,graph):
        self.chunks=chunks; self.graph=graph
        self.docs=[Counter(tokenize(c['text']+' '+' '.join(c['entities']))) for c in chunks]
        self.lengths=[sum(d.values()) for d in self.docs]
        self.avg=np.mean(self.lengths)
        df=Counter(t for d in self.docs for t in d)
        self.idf={t:math.log(1+(len(chunks)-n+.5)/(n+.5)) for t,n in df.items()}
        self.by_id={n['id']:n for n in graph['nodes']}
        self.by_name={n['name']:n['id'] for n in graph['nodes']}

    def context(self,sensor_id):
        sid=self.by_name[sensor_id]
        owners=[e['source'] for e in self.graph['edges'] if e['relation']=='has_sensor' and e['target']==sid]
        station=owners[0]
        # Direct process neighbours and explicit correlation links, not arbitrary graph flooding.
        linked=[]
        for e in self.graph['edges']:
            if e['relation']=='feeds_into' and station in [e['source'],e['target']]: linked.append(e)
            if e['relation']=='correlates_with' and sid in [e['source'],e['target']]: linked.append(e)
        names={self.by_id[station]['name'],sensor_id}
        for e in linked:
            names.update([self.by_id[e['source']]['name'],self.by_id[e['target']]['name']])
        return {'station':self.by_id[station]['name'],'entities':sorted(names),'relations':linked}

    def search(self,query,sensor_id,mode='text',k=3):
        ctx=self.context(sensor_id)
        # Identical event context for both methods; graph variant adds only static neighbours.
        base=query+' '+sensor_id+' '+ctx['station']
        terms=Counter(tokenize(base))
        if mode=='graph':
            for token in tokenize(' '.join(ctx['entities'])): terms[token]+=.35
            for rel in ctx['relations']:
                for token in tokenize(rel['rule_ref']): terms[token]+=.75
        scores=[]
        for i,d in enumerate(self.docs):
            score=0.
            for term,weight in terms.items():
                tf=d.get(term,0)
                score+=weight*self.idf.get(term,0)*tf*2.5/(tf+1.5*(.25+.75*self.lengths[i]/self.avg))
            scores.append(score)
        top=sorted(range(len(scores)),key=lambda i:(-scores[i],self.chunks[i]['chunk_id']))[:k]
        return [{**self.chunks[i],'score':scores[i]} for i in top]

def benchmark(retriever):
    # Manually grounded development questions; NOT a blind generalization benchmark.
    cases=[
      ('Q01','ST02_SEALING_TMP','Temperature exceeds 210 C critical. Which stations must stop?',['RULE-ST02-02'],['emergency stop ST02, ST03, ST04']),
      ('Q02','ST04_PACKAGING_VIB','Vibration above 0.35 critical. What action is required?',['RULE-ST04-02'],['inspect bearings']),
      ('Q03','ST04_PACKAGING_SPD','Speed drops below 1.00 without operator command. Which other station current should be checked?',['RULE-ST04-03','RULE-ST02-04'],['shared electrical coupling']),
      ('Q04','ST02_SEALING_CUR','Current drift greater than 1.0 A for 30 minutes. Maintenance action?',['MAINT-02'],['Inspect sealing jaw']),
      ('Q05','WRH01_WAREHOUSE_TMP','Temperature drift greater than 2 C over 2 hours. Maintenance action?',['MAINT-06'],['Inspect compressor']),
      ('Q06','ST03_LABELLING_TEN','Tension sensor unchanged for more than 10 samples. Maintenance action?',['MAINT-03'],['Replace sensor']),
      ('Q07','SRV01_SERVERROOM_TMP','Temperature above 28 C critical. What response?',['RULE-SRV01-02'],['controlled shutdown']),
      ('Q08','CHM01_CHEMICALSTORAGE_TMP','Temperature above 25 C critical. What response?',['RULE-CHM01-01'],['emergency ventilation','safety officer']),
    ]
    results=[]; details=[]
    for qid,sensor,query,gold,actions in cases:
        for mode in ['text','graph']:
            hits=retriever.search(query,sensor,mode,k=3)
            got={h['rule_id'] for h in hits}
            ranks=[i+1 for i,h in enumerate(hits) if h['rule_id'] in gold]
            context=' '.join(' '.join(h['text'].split()).lower() for h in hits)
            results.append({'question_id':qid,'mode':mode,'hit_at_3':int(bool(ranks)),
                'gold_rule_recall_at_3':len(got&set(gold))/len(gold),
                'mrr_at_3':1/min(ranks) if ranks else 0.,
                'action_evidence_coverage':sum(a.lower() in context for a in actions)/len(actions)})
            details.append({'question_id':qid,'sensor_id':sensor,'query':query,'mode':mode,
                'gold_rule_ids':gold,'expected_action_phrases':actions,'hits':hits})
    result=pd.DataFrame(results)
    csv(result,'retrieval_per_question.csv')
    summary=result.groupby('mode')[['hit_at_3','gold_rule_recall_at_3','mrr_at_3','action_evidence_coverage']].mean().reset_index()
    csv(summary,'retrieval_comparison.csv'); write_json(OUT/'retrieval_details.json',details)
    write_json(OUT/'retrieval_protocol.json',{'type':'8 manually authored development questions, English queries',
        'same_corpus':True,'top_k':3,'method':'BM25 vs BM25 with weighted static graph expansion',
        'llm_used':False,'action_metric':'exact normalized phrase availability in retrieved context; not generated answer correctness',
        'limitations':['No Korean semantic retrieval','Not a blind benchmark','No LLM answer or action consistency score','Do not infer improvement from graph presence']})
    return summary

def available_history(events,as_of,sensors):
    # Online event records have observed_at, never oracle start/end/severity.
    return [e for e in events if e['sensor_id'] in sensors and pd.Timestamp(e['observed_at']) < pd.Timestamp(as_of)]

def make_evidence(retriever,raw,responses,pred):
    first_time=pd.Timestamp('2026-01-06 08:30:00')
    obs=raw[raw.sensor_id.eq('ST02_SEALING_TMP') & raw.timestamp.eq(first_time)].iloc[0]
    rule=next(c for c in retriever.chunks if c['rule_id']=='RULE-ST02-02')
    assert obs.value > obs.crit_hi
    package={'mode':'label-event integration demo (retrospective event selection)',
        'as_of':str(first_time),'sensor_id':obs.sensor_id,'station_id':obs.station_id,
        'observation':{'value':obs.value,'unit':obs.unit,'critical_high':obs.crit_hi},
        'source_evidence':rule,'graph_context':retriever.context(obs.sensor_id),
        'logged_responses_available_as_of':responses[responses.sensor_id.eq(obs.sensor_id)&responses.ack_timestamp.le(first_time)].to_dict('records'),
        'interpretation':'SOP-001 RULE-ST02-02 requires emergency stop ST02/ST03/ST04. No equipment commands are executed.',
        'retrospective_only':{'recorded_action':responses.iloc[0].action_taken,
            'note':'Recorded action differs from this SOP clause; do not treat the log as the prescribed response.'}}
    write_json(OUT/'first_event_evidence.json',package)
    # Turn predicted alert onsets into causal records without ground-truth labels or future ends.
    registry=[]; packages=[]
    for _,p in pred.sort_values('start').iterrows():
        d=raw[(raw.sensor_id==p.sensor_id)&(raw.timestamp==p.start)].iloc[0]
        ctx=retriever.context(p.sensor_id)
        history=available_history(registry,p.start,ctx['entities'])
        query=f'{d.sensor_type} sensor anomaly value {d.value} {d.unit}; warning limits {d.warn_lo} {d.warn_hi}; inspect maintenance response'
        hits=retriever.search(query,p.sensor_id,'graph')
        packages.append({'prediction_id':p.prediction_id,'observed_at':str(p.start),
            'sensor_id':p.sensor_id,'value':d.value,'unit':d.unit,'graph_context':ctx,
            'past_predicted_alerts':history,'source_candidates':hits,
            'status':'Evidence candidates only; no LLM recommendation or inferred root cause.'})
        registry.append({'prediction_id':p.prediction_id,'sensor_id':p.sensor_id,'observed_at':str(p.start)})
    write_json(OUT/'predicted_event_evidence.json',packages)
    return package,packages

def graph_plot(graph):
    byid={n['id']:n for n in graph['nodes']}
    stations=[n for n in graph['nodes'] if n['label']=='Component']
    positions={}; fig,ax=plt.subplots(figsize=(15,9))
    for i,n in enumerate(stations):
        row=0 if i<4 else 1
        col=i if i<4 else i-4
        x=col*3.; y=-row*5.
        positions[n['id']]=(x,y)
        ax.text(x,y,n['name'].replace('_','\n',1),ha='center',va='center',fontsize=8,bbox=dict(boxstyle='round,pad=.5',fc='#dbeafe',ec='#2563eb'))
        children=[e['target'] for e in graph['edges'] if e['source']==n['id'] and e['relation']=='has_sensor']
        for j,sid in enumerate(children):
            sx=x+(j-(len(children)-1)/2)*.8; sy=y-1.6
            positions[sid]=(sx,sy)
            ax.text(sx,sy,byid[sid]['name'].split('_')[-1],ha='center',va='center',fontsize=8,bbox=dict(boxstyle='round',fc='#dcfce7',ec='#16a34a'))
            ax.annotate('',xy=(sx,sy+.2),xytext=(x,y-.5),arrowprops=dict(arrowstyle='->',color='#94a3b8'))
    for e in graph['edges']:
        if e['relation'] not in ['feeds_into','correlates_with']: continue
        a,b=positions[e['source']],positions[e['target']]
        color='#e11d48' if e['relation']=='correlates_with' else '#2563eb'
        if e['relation']=='correlates_with':
            ax.annotate('',xy=(b[0],b[1]-.17),xytext=(a[0],a[1]-.17),
                        arrowprops=dict(arrowstyle='->',color=color,connectionstyle='arc3,rad=.3'))
        else:
            ax.annotate('',xy=(b[0]-.6,b[1]),xytext=(a[0]+.6,a[1]),arrowprops=dict(arrowstyle='->',color=color))
    ax.set(xlim=(-1.5,13.5),ylim=(-8,1.5),title='iMAKS static graph | blue: process flow, red: documented correlation')
    ax.axis('off'); fig.tight_layout(); fig.savefig(OUT/'equipment_graph.png',dpi=150); plt.close(fig)

def main():
    global OUT
    OUT = SELECTED_PIPELINE_OUT
    OUT.mkdir(exist_ok=True)
    raw,labeled,nodes,edges,responses=load_data()
    common_data=load_common_detection_data()
    applied_config, selection_source = load_applied_config(common_data.provenance)
    write_json(OUT/'input_provenance.json',common_data.provenance)
    truth=truth_events(nodes,edges); csv(truth,'evaluation_truth_events.csv')
    graph=build_static_graph(); graph_plot(graph)
    pages=json.loads((ROOT/'pipeline_outputs/sources/pages.json').read_text(encoding='utf-8'))
    chunks=chunks_from_pages(pages,graph)
    # Add provenance-bearing document links; keep detector/temporal records out of static graph.
    links=[{'source':n['id'],'target':c['chunk_id'],'relation':'mentioned_in','document':c['document'],'page':c['page']}
           for c in chunks for n in graph['nodes'] if n['label']=='Component' and n['name'] in c['entities']]
    write_json(OUT/'graph_document_links.json',links)
    scored=fit_scores(common_data.ml, applied_config['mean_window_samples'], applied_config['stuck_window_samples'], save_parameters=True)
    splits=scored.groupby('split').agg(start=('timestamp','min'),end=('timestamp','max'),rows=('value','size')).reset_index()
    splits['truth_events']=splits['split'].map(truth['split'].value_counts())
    csv(splits,'temporal_splits.csv')
    chosen,metrics,pred=run_detection(scored,labeled,truth,common_data.rule,applied_config,selection_source)
    retriever=Retriever(chunks,graph)
    retrieval=benchmark(retriever)
    first,packages=make_evidence(retriever,raw,responses,pred)
    manifest={'source_zip_sha256':hashlib.file_digest(open(ROOT/'iMAKS_dataset.zip','rb'),'sha256').hexdigest(),
        'static_nodes':len(graph['nodes']),'static_edges':len(graph['edges']),'pdf_pages':len(pages),
        'document_chunks':len(chunks),'predicted_test_evidence_packages':len(packages),
        'selected_model':chosen,'selection_source':selection_source,'llm_used':False}
    write_json(OUT/'manifest.json',manifest)
    print(metrics.to_string(index=False)); print(retrieval.to_string(index=False)); print(json.dumps(manifest,indent=2))

def run_common_detection():
    """Verify the new input connection without rewriting legacy retrieval outputs."""
    global OUT
    OUT = COMMON_DETECTION_OUT
    OUT.mkdir(parents=True, exist_ok=True)
    data = load_common_detection_data()
    applied_config, selection_source = load_applied_config(data.provenance)
    write_json(OUT/'input_provenance.json',data.provenance)
    csv(data.events,'evaluation_truth_events.csv')
    scored = fit_scores(data.ml, applied_config['mean_window_samples'], applied_config['stuck_window_samples'], save_parameters=True)
    chosen, metrics, pred = run_detection(scored,data.labels,data.events,data.rule,applied_config,selection_source)
    split_rows = scored.groupby('split').agg(start=('timestamp','min'),end=('timestamp','max'),rows=('value','size')).reset_index()
    split_rows['truth_events'] = split_rows['split'].map(data.events['split'].value_counts())
    csv(split_rows,'temporal_splits.csv')
    write_json(OUT/'experiment_config.json',{
        'input_provenance':data.provenance, 'normalization':'Train-only median/MAD per sensor; contaminated training retained',
        'windows':[{'feature':'rolling_mean','samples':chosen['mean_window_samples'],
                    'nominal_window_seconds':chosen['mean_window_samples']*30,
                    'first_to_last_seconds':(chosen['mean_window_samples']-1)*30,'min_periods':chosen['mean_window_samples']},
                   {'feature':'rolling_std','samples':chosen['stuck_window_samples'],
                    'nominal_window_seconds':chosen['stuck_window_samples']*30,
                    'first_to_last_seconds':(chosen['stuck_window_samples']-1)*30,'min_periods':chosen['stuck_window_samples'],'ddof':0}],
        'stride_samples':1,'sampling_seconds':30,'trailing_only':True,'reset_at':['sensor','time gap','split boundary'],
        'selected_model':chosen,'selection_source':selection_source,'rule_thresholds_used_only_by':'sop_threshold',
        'label_use':'Validation selection and evaluation only; not fitting/features',
        'comparison':'Different detectors; not a same-model threshold feature ablation',
        'purpose':'Apply frozen validation-selected mean3/STUCK11 with fixed 6/4 thresholds; no new tuning',
        'test_status':'Previously evaluated test split; reevaluation, not a new blind test'})
    print(metrics[['model','split','event_precision','event_recall','event_f1','detected_events','predicted_events']].to_string(index=False))
    return chosen,metrics,pred

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--detection-only',action='store_true',help='Apply selected mean3/STUCK11 in experiments/common_v1_detection_window3; preserve window10 outputs.')
    args=parser.parse_args()
    if args.detection_only: run_common_detection()
    else: main()
