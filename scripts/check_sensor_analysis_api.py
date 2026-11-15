"""One labelled historical replay through the actual local CSV/series/XAI APIs."""
import argparse
import csv
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from imaks_kg.rag import comparison as c, team_runtime, vector as v, sensor_analysis
from run_sensor_analysis import make_replay


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8770)
    args=parser.parse_args()
    base=f'http://127.0.0.1:{args.port}'
    def request(path,body=None,headers=None):
        with urlopen(Request(base+path,data=body,headers=headers or {}),timeout=180) as response:return json.load(response)
    session=request('/api/session')
    if session['generation_enabled'] or not session.get('analysis_enabled'):
        raise ValueError('Run --serve --read-only --allow-local-analysis first')
    recipe=make_replay(20261115,120)
    raw=(ROOT/recipe['csv_file']).read_bytes()
    baseline=team_runtime.store()
    originals={str(path.relative_to(ROOT)):v.digest(path.read_bytes()) for path in
               (ROOT/'preprocessed/sensors/input/ts_input.csv',ROOT/c.KG_REL,baseline.run_dir/'complete.json')}
    summary=request('/api/analyses',raw,{'Content-Type':'text/csv','X-Demo-Token':session['csrf_token'],'X-Input-Kind':'historical_replay'})
    aid=summary['analysis_id']
    sensor=summary['incident_items'][0]['sensor_id'] if summary['incident_items'] else summary['sensors'][0]
    series=request(f'/api/analyses/{aid}/series?sensor_id={sensor}&limit=1000')
    points=list(series['points'])
    while series['next_offset'] is not None:
        series=request(f'/api/analyses/{aid}/series?sensor_id={sensor}&limit=1000&offset={series["next_offset"]}')
        points+=series['points']
    expected=[{'timestamp':datetime.fromisoformat(row['timestamp']).isoformat(),'value':row['value'].strip()}
              for row in csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))) if row['sensor_id']==sensor]
    expected.sort(key=lambda row:row['timestamp'])
    if points!=expected:raise ValueError('Chart data differs from uploaded observations')
    detail=None
    if summary['incident_items']:
        detail=request(f'/api/analyses/{aid}/incidents/{summary["incident_items"][0]["id"]}')
        if detail['xai']['decision_evidence']['status']!='consistent':raise ValueError('Uploaded XAI reference mismatch')
        if aid not in detail['xai']['decision_evidence']['input_file']:raise ValueError('XAI points to baseline rather than upload')
        if detail['xai']['rule_explanations']['counts']['inconsistent']:raise ValueError('Closure mismatch')
    # A separate, explicitly synthetic control exercises positive XAI. Never
    # resample the random historical window until a desired detection appears.
    sid='ST02_SEALING_TMP';metadata=sensor_analysis.schema(c.load_graph())[sid]
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=sensor_analysis.rules.FIELDS,lineterminator='\n');writer.writeheader()
    for i in range(90):
        value=212 if 50<=i<55 else [184,186,185,187,183][i%5]
        writer.writerow({'timestamp':(datetime(2026,1,8,12)+timedelta(seconds=i*30)).isoformat(),
                         'sensor_id':sid,'value':str(value),**metadata})
    control_raw=stream.getvalue().encode()
    control_file=ROOT/'kg_build/sensor_replay_inputs/synthetic_positive_ST02_TMP.csv'
    control_file.write_bytes(control_raw)
    control=request('/api/analyses',control_raw,{'Content-Type':'text/csv','X-Demo-Token':session['csrf_token'],
                    'X-Input-Kind':'uploaded_sensor_csv'})
    if not control['incident_items']:raise ValueError('Positive synthetic control did not fire')
    control_detail=request(f'/api/analyses/{control["analysis_id"]}/incidents/{control["incident_items"][0]["id"]}')
    if control_detail['agent_status']!='complete' or control_detail['xai']['decision_evidence']['status']!='consistent':
        raise ValueError('Positive synthetic control XAI failed')
    if control['analysis_id'] not in control_detail['xai']['decision_evidence']['input_file']:
        raise ValueError('Positive XAI points to wrong input')
    if any(v.digest((ROOT/name).read_bytes())!=sha for name,sha in originals.items()):raise ValueError('Frozen input or baseline changed')
    out=ROOT/'kg_build/sensor_analysis_api_audit';out.mkdir(parents=True,exist_ok=True)
    v.write(out/'summary.json',summary);v.write(out/'series.json',{'sensor_id':sensor,'points':points})
    if detail:v.write(out/'detail.json',detail)
    v.write(out/'synthetic_control_detail.json',control_detail)
    audit={'version':'sensor-analysis-api-audit-v1-20261115','analysis_id':aid,'passed':True,
           'input_kind':'historical_replay','recipe':recipe,'uploaded_rows':summary['rows'],
           'incidents':summary['incidents'],'alarms':summary['alarms'],'chart_sensor':sensor,'chart_points':len(points),
           'chart_matches_uploaded_values':True,'detail_status':detail['agent_status'] if detail else 'not_applicable_no_incidents',
           'XAI_input_is_upload':True if detail else None,'original_hashes_preserved':originals,
           'positive_control':{'data_kind':'explicit_synthetic_control','analysis_id':control['analysis_id'],
                'csv_file':control_file.relative_to(ROOT).as_posix(),'rows':control['rows'],
                'incidents':control['incidents'],'alarms':control['alarms'],'detail_status':control_detail['agent_status'],
                'XAI_input_is_upload':True,'source_checks':'consistent','new_api_calls':0},
           'generation_enabled':False,'new_api_calls':0,'model_selection_tested':False,
           'code_sha256':v.digest((ROOT/'src/imaks_kg/rag/sensor_analysis.py').read_bytes()),
           'scope':'local API integration on labelled historical replay; not new anomaly accuracy or causal validation'}
    v.write(out/'audit.json',audit)
    print(json.dumps({key:audit[key] for key in ('analysis_id','passed','uploaded_rows','incidents','alarms','chart_sensor','chart_points','detail_status','new_api_calls')},ensure_ascii=False))


if __name__=='__main__':main()
