"""Real local async -> target window -> private export/restore -> XAI check."""
import argparse
import csv
from datetime import datetime,timedelta
import io
import json
from pathlib import Path
import sys
import tempfile
import time
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from imaks_kg.rag import sensor_analysis as a, comparison as c, vector as v


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8770)
    args=parser.parse_args();base=f'http://127.0.0.1:{args.port}'
    def request(path,body=None,headers=None,binary=False):
        with urlopen(Request(base+path,data=body,headers=headers or {}),timeout=180) as response:
            raw=response.read();return response.status,raw if binary else json.loads(raw)
    _,session=request('/api/session')
    if session['generation_enabled'] or not session.get('analysis_enabled'):raise ValueError('Use generation-disabled local analysis server')
    sid='ST02_SEALING_TMP';meta=a.schema(c.load_graph())[sid]
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=a.rules.FIELDS,lineterminator='\n');writer.writeheader()
    for i in range(90):
        value=212 if 50<=i<55 else 999 if i==80 else [184,186,185,187,183][i%5]
        writer.writerow({'timestamp':(datetime(2026,1,8,12)+timedelta(seconds=30*i)).isoformat(),
                         'sensor_id':sid,'value':str(value),**meta})
    raw=stream.getvalue().encode()
    originals={str(path.relative_to(ROOT)):v.digest(path.read_bytes()) for path in
               (ROOT/a.rules.INPUT,ROOT/c.KG_REL,a.team_runtime.store().run_dir/'complete.json')}
    headers={'X-Demo-Token':session['csrf_token'],'Content-Type':'text/csv','X-Input-Kind':'uploaded_sensor_csv',
             'X-Analysis-Start':'2026-01-08T12:26:00','X-Analysis-End':'2026-01-08T12:35:00'}
    begin=time.monotonic();status,accepted=request('/api/analyses',raw,headers);elapsed=time.monotonic()-begin
    if status!=202 or accepted['status']!='queued':raise ValueError('Expected asynchronous 202 response')
    aid=accepted['analysis_id'];deadline=time.monotonic()+180;states=[]
    while True:
        _,result=request('/api/analyses/'+aid);states.append(result.get('phase',result.get('status')))
        if result['status']=='complete':break
        if result['status'] not in ('queued','processing'):raise ValueError('Job failed: '+str(result.get('error')))
        if time.monotonic()>deadline:raise TimeoutError('Inspect the accepted ID; do not automatically upload again')
        time.sleep(.25)
    _,series=request(f'/api/analyses/{aid}/series?sensor_id={sid}')
    _,context=request(f'/api/analyses/{aid}/series?sensor_id={sid}&include_warmup=true')
    if len(series['points'])!=19 or len(context['points'])!=71:raise ValueError('Target/history split mismatch')
    if any(point['timestamp']>'2026-01-08T12:35:00' for point in context['points']):raise ValueError('Future observation leaked into context')
    if result['incident_items'][0]['window_scope']!='started_before_analysis':raise ValueError('Ongoing event lost its scope')
    _,bundle=request(f'/api/analyses/{aid}/export',binary=True)
    _,again=request('/api/analyses/import',bundle,{'X-Demo-Token':session['csrf_token'],'Content-Type':'application/zip'})
    if again['status']!='already_present':raise ValueError('Duplicate restore was not idempotent')
    out=ROOT/'kg_build/analysis_workflow_audit';out.mkdir(parents=True,exist_ok=True)
    (out/'synthetic_context.csv').write_bytes(raw);(out/'analysis_export.zip').write_bytes(bundle)
    v.write(out/'summary.json',result);v.write(out/'target_series.json',series);v.write(out/'context_series.json',context)
    with tempfile.TemporaryDirectory(prefix='restore_',dir=out) as temp:
        restored=a.AnalysisService(Path(temp));receipt=restored.import_bundle(bundle)
        detail=restored.detail(aid,result['incident_items'][0]['id'])
        if receipt['status']!='restored' or detail['agent_status']!='complete':raise ValueError('Fresh restore failed')
        if detail['xai']['decision_evidence']['status']!='consistent':raise ValueError('Restored input XAI mismatch')
        remapped=detail['input_source']['file']!=detail['origin_input_source']['file']
        if not remapped or detail['input_source']['sha256']!=detail['origin_input_source']['sha256']:raise ValueError('Local reference resolution mismatch')
        v.write(out/'restored_detail.json',detail);restored.close()
    if any(v.digest((ROOT/name).read_bytes())!=sha for name,sha in originals.items()):raise ValueError('Original inputs changed')
    audit={'version':'analysis-workflow-audit-v1-20261115','analysis_id':aid,'passed':True,
           'data_kind':'explicit_synthetic_control_not_accuracy_evaluation','http_accept_status':status,'submit_seconds':elapsed,
           'phases':[item['phase'] for item in result['job']['phase_history']], 'polled_states':list(dict.fromkeys(states)),
           'upload_rows':90,'processing_rows':result['rows'],'target_points':len(series['points']),
           'context_points':len(context['points']),'excluded_future_rows':result['intervals']['excluded_after_analysis_end_rows'],
           'incidents':result['incidents'],'alarms':result['alarms'],'incident_scope':result['incident_items'][0]['window_scope'],
           'bundle_bytes':len(bundle),'bundle_sha256':v.digest(bundle),'idempotent_import':again['status'],
           'fresh_restore_XAI':'consistent','local_reference_remapped':remapped,'original_hashes_preserved':originals,
           'new_api_calls':0,'model_selection_tested':False,
           'code_sha256':{name:v.digest((ROOT/name).read_bytes()) for name in
                ('src/imaks_kg/rag/sensor_analysis.py','src/imaks_kg/rag/analysis_archive.py','src/imaks_kg/rag/demo.py')},
           'scope':'async API, temporal input boundary and stored-artifact integrity; not field accuracy, authentic origin or causality'}
    v.write(out/'audit.json',audit)
    print(json.dumps({key:audit[key] for key in ('analysis_id','passed','http_accept_status','processing_rows','target_points',
                      'context_points','excluded_future_rows','incident_scope','bundle_bytes','fresh_restore_XAI','new_api_calls')},ensure_ascii=False))


if __name__=='__main__':main()
