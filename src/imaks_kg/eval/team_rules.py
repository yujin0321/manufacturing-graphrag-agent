"""Re-score archived cosine matrices under the team's cardinality-first definition."""
import json
import hashlib
import platform
import re
from pathlib import Path
import numpy as np
from imaks_kg.common.raw_io import raw_csv_rows,raw_bytes
from imaks_kg.common.provenance import sha256_file
from imaks_kg.common.io_utils import write_json
from imaks_kg.kg.documents import read_jsonl,units
from imaks_kg.settings import REPO_ROOT

def assign(cost):
    """Rectangular Hungarian minimum-cost assignment, rows <= columns."""
    n,m=cost.shape
    u=[0.]*(n+1);v=[0.]*(m+1);p=[0]*(m+1);way=[0]*(m+1)
    for i in range(1,n+1):
        p[0]=i;j0=0;mins=[float('inf')]*(m+1);used=[False]*(m+1)
        while True:
            used[j0]=True;i0=p[j0];delta=float('inf');j1=0
            for j in range(1,m+1):
                if not used[j]:
                    cur=float(cost[i0-1,j-1])-u[i0]-v[j]
                    if cur<mins[j]:mins[j]=cur;way[j]=j0
                    if mins[j]<delta:delta=mins[j];j1=j
            for j in range(m+1):
                if used[j]:u[p[j]]+=delta;v[j]-=delta
                else:mins[j]-=delta
            j0=j1
            if p[j0]==0:break
        while True:
            j1=way[j0];p[j0]=p[j1];j0=j1
            if j0==0:break
    return [(p[j]-1,j-1) for j in range(1,m+1) if p[j]]

def match(scores,eligible,threshold):
    n,m=scores.shape
    if not n or not m:return []
    valid=eligible & (scores>=threshold)
    weights=np.zeros((n,m+n))
    weights[:,:m]=np.where(valid,min(n,m)+1+scores,0.)
    return [(i,j,float(scores[i,j])) for i,j in assign(-weights) if j<m and valid[i,j]]

def counts(tp,p,g):
    return dict(tp=tp,fp=p-tp,fn=g-tp,precision=tp/p if p else 0,
                recall=tp/g if g else 0,f1=2*tp/(p+g) if p+g else 0)

def evaluate(run,definition):
    folder=REPO_ROOT/'evaluation'/run/'colab_results'
    predpath=REPO_ROOT/'kg_build'/run/'llm_predictions.jsonl'
    old=json.loads((folder/'metrics.json').read_text(encoding='utf-8'))
    output=REPO_ROOT/'evaluation'/run/'team_definition'
    reqroot=REPO_ROOT/'kg_build'/run/'responses/requests'
    request_files={p.name:sha256_file(p) for p in sorted(reqroot.glob('*.json'))}
    write_json(output/'pre_evaluation_lock.json',dict(
        status='retrospective_lock_before_team_rescoring_NOT_before_initial_gold_exposure',
        predictions_sha256=sha256_file(predpath),definition_sha256=sha256_file(definition),
        api_requests_sha256=request_files,requested_model='gpt-6.1-sol',
        actual_models=sorted({json.loads(p.read_text(encoding='utf-8'))['model'] for p in (reqroot.parent/'raw').glob('*.json')}),
        encoder_revision=old['encoder_revision'],
        embedding_versions='Notebook pins sentence-transformers 3.4.1, scipy 1.15.2; actual runtime versions not archived',
        rescoring_versions=dict(python=platform.python_version(),numpy=np.__version__),
        scores_sha256=sha256_file(folder/'similarities.npy'),independent_test=False))
    assert sha256_file(predpath)==old['predictions_sha256']
    gp=REPO_ROOT/'imaks_data/kg_seed/ground_truth.csv'
    _,gold=raw_csv_rows(gp,evaluation=True)
    assert hashlib.sha256(raw_bytes(gp,evaluation=True)).hexdigest()==old['reference_sha256']
    sop={'SOP-001','SOP-002','SOP-003','SOP-004'}
    if len(gold)!=86 or any(g['source'] not in sop for g in gold):raise ValueError('Unknown reference document/count')
    docs={u['unit_id']:u['doc_id'] for u in units()}
    allpred=read_jsonl(predpath)
    if any(docs[p['unit_id']] not in sop|{'DS-ELEC-3300','DS-MECH-4400','DS-THERM-2200'} for p in allpred):raise ValueError('Unknown prediction document')
    pred=[p for p in allpred if docs[p['unit_id']] in sop]
    scores=np.load(folder/'similarities.npy',allow_pickle=False)
    assert scores.shape==(len(pred),len(gold)) and np.isfinite(scores).all()
    eligible=np.array([[docs[p['unit_id']]==g['source'] for g in gold] for p in pred])
    pairs=match(scores,eligible,.6)
    micro=counts(len(pairs),len(pred),len(gold))
    correct=sum(pred[i]['ruleClass']==gold[j]['class'] for i,j,s in pairs)
    confusion={c:{d:0 for d in sorted({p['ruleClass'] for p in pred})} for c in sorted({g['class'] for g in gold})}
    for i,j,s in pairs:confusion[gold[j]['class']][pred[i]['ruleClass']]+=1
    norm=lambda x:re.sub('[^A-Z0-9]','',x.upper())
    sensor_equal=sum({norm(x) for x in pred[i].get('sensorIds',[])}==({norm(gold[j]['sensor'])} if gold[j]['sensor'].strip() else set()) for i,j,s in pairs)
    result=dict(run=run,F1_content=micro['f1'],micro=micro,processed_scope_F1=micro['f1'],
        SOP_predictions=len(pred),datasheet_predictions=len(allpred)-len(pred),reference_count=86,
        class_agreement=counts(correct,len(pred),86),confusion_gold_rows_pred_columns=confusion,
        per_document={d:counts(sum(gold[j]['source']==d for i,j,s in pairs),sum(docs[p['unit_id']]==d for p in pred),sum(g['source']==d for g in gold)) for d in sorted(sop)},
        sensitivity={str(t):counts(len(match(scores,eligible,t)),len(pred),86) for t in [.5,.6,.7]},
        granularity_ratio=len(pred)/86,theoretical_F1_ceiling=2*min(len(pred),86)/(len(pred)+86),
        sensor_set_agreement=dict(equal=sensor_equal,denominator=len(pairs),ratio=sensor_equal/len(pairs),
            normalization='uppercase alphanumeric; underscores/hyphens removed; empty-empty included'),
        format_sensitivity='NOT MEASURED: alternative prefixed embeddings unavailable',
        GT_0009='N/A',definition_sha256=sha256_file(definition),
        predictions_sha256=sha256_file(predpath),reference_sha256=old['reference_sha256'],
        archived_matrix_reused=True,embedding_regenerated=False,
        matching='same document; no class constraint; maximize valid pair count then valid cosine sum',
        lock_limitation='Retrospective; original definition-specific pre-evaluation lock did not exist')
    write_json(output/'summary.json',result)
    write_json(output/'matches_private.json',[dict(prediction_id=pred[i]['identifier'],reference_id=gold[j]['ruleId'],similarity=s) for i,j,s in pairs])
    assert sha256_file(predpath)==old['predictions_sha256']
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--definition',type=Path,required=True)
    p.add_argument('--run',default='openai_sol_v2_20261016')
    a=p.parse_args()
    evaluate(a.run,a.definition)
