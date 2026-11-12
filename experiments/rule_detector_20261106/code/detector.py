"""Causal-in-time rule scanner. No labels, trained model, network, or control actions."""
from __future__ import annotations
import argparse, csv, hashlib, json, math
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

FIELDS = ['timestamp','zone','station_id','sensor_id','sensor_type','value','unit']
POLICY = {'sample_seconds':30, 'confirm_observations':2, 'clear_observations':2,
          'duration':'strict elapsed > document limit; two consecutive fully qualifying observations',
          'gap':'report; reset pending state; truncate active event as unconfirmed, never recovered',
          'drift':'signed current minus exact historical observation; complete contiguous fixed window',
          'drift_direction':'positive increase only; no absolute-value conversion',
          'drift_maint02':'30+ min operationalized as fixed 30-minute lookback, NOT >1A held 30min',
          'unknown':'external candidate only; no automatic discovery; expert review required',
          'recovery':'document-recommended response only; no execution or confirmed cause'}

def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p, data):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def read(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def stamp(t): return t.isoformat()

def read_observations(path):
    groups=defaultdict(list);seen=set();problems=[]
    with Path(path).open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        if reader.fieldnames != FIELDS: raise ValueError('Only seven observation fields permitted')
        for row in reader:
            ts=datetime.fromisoformat(row['timestamp']); key=(row['sensor_id'],ts)
            if key in seen: raise ValueError('Duplicate sensor/timestamp')
            seen.add(key)
            try:
                number=Decimal(row['value']);valid=number.is_finite()
            except InvalidOperation: valid=False
            row={**row,'_time':ts,'_number':number if valid else None}
            if not valid: problems.append({'sensor_id':key[0],'timestamp':stamp(ts),'status':'missing_value','message':'결측 또는 비유한 값: 연속성 확인 불가'})
            groups[key[0]].append(row)
    for sid,rows in groups.items():
        rows.sort(key=lambda x:x['_time'])
        for a,b in zip(rows,rows[1:]):
            seconds=(b['_time']-a['_time']).total_seconds()
            if seconds != 30:
                problems.append({'sensor_id':sid,'after':stamp(a['_time']),'before':stamp(b['_time']),
                                 'status':'timestamp_gap','elapsed_seconds':seconds,
                                 'missing_slots':int(seconds/30)-1 if seconds>30 and seconds%30==0 else None,
                                 'message':'관측 공백: 해당 구간 상태·연속성 확인 불가'})
    return dict(groups),problems

def scan(rows,rule,*,confirm=2,clear=2):
    if confirm<1 or clear<1: raise ValueError('confirmation counts must be positive')
    events=[];active=None;last=None;lastvalue=None;same=0;start=None;hits=0;normal=0
    history={};segment_start=None
    limit=Decimal(str(rule['value'])); upper=Decimal(str(rule['second'])) if rule.get('second') is not None else None
    window=int(rule.get('window_seconds',0)); duration=int(rule.get('duration_seconds',0))
    def emit(status,at=None):
        nonlocal active
        if active:
            active['status']=status; active['closed_at']=stamp(at) if at else None
            active['normal_confirmed_at']=stamp(at) if status=='recovered' else None
            active['elapsed_to_last_positive_seconds']=(datetime.fromisoformat(active['last_positive_at'])-datetime.fromisoformat(active['condition_start'])).total_seconds()
            active['continuous_violation_claim']=False
            active['bridging_policy']='one observed nonqualifying point may be retained inside event; two clear; gaps never bridged'
            active['id']='det3-'+hashlib.sha256(json.dumps(active,sort_keys=True).encode()).hexdigest()[:20]
            events.append(active);active=None
    for row in rows:
        ts=row.get('_time') or datetime.fromisoformat(row['timestamp'])
        value=row.get('_number') if '_number' in row else Decimal(row['value'])
        if row['unit']!=rule['unit']: raise ValueError('Unit mismatch '+rule['rule_id'])
        contiguous=last is not None and (ts-last).total_seconds()==30
        if not contiguous or value is None or not value.is_finite():
            emit('data_gap_unconfirmed',last)
            same=0;start=None;hits=0;normal=0;lastvalue=None;history={};segment_start=ts
        if value is None or not value.is_finite():
            last=None;continue
        if segment_start is None:segment_start=ts
        same=same+1 if contiguous and value==lastvalue else 1
        history[ts]=value
        feature=value; baseline=None; ready=True
        op=rule['op']
        if op=='gt': condition=value>limit
        elif op=='lt': condition=value<limit
        elif op=='outside': condition=value<limit or value>upper
        elif op=='stuck_exact': condition=same>=int(limit)
        elif op=='delta_gt':
            earlier=ts-timedelta(seconds=window);baseline=history.get(earlier)
            ready=baseline is not None and (ts-segment_start).total_seconds()>=window
            feature=value-baseline if ready else None
            condition=bool(ready and feature>limit)
            # Keep only the required trailing history. No future data.
            history.pop(ts-timedelta(seconds=window+30),None)
        else: raise ValueError('Unknown operation '+op)
        if condition:
            if start is None:start=ts
            qualifies=not duration or (ts-start).total_seconds()>duration
        else:
            start=None;qualifies=False
        hits=hits+1 if qualifies else 0
        if active:
            if condition:
                normal=0
                active['last_positive_at']=stamp(ts);active['last_value']=str(value)
                active['positive_observations']+=1
                if qualifies:active['qualified_observations']+=1
            elif ready:
                normal+=1;active['nonqualifying_observations']+=1
                if normal==1:active['clear_started_at']=stamp(ts)
                if normal>=clear:emit('recovered',ts);normal=0
        elif hits>=confirm:
            condition_start=ts-timedelta(seconds=(same-1)*30) if op=='stuck_exact' else start
            active={'sensor_id':row['sensor_id'],'station_id':row.get('station_id'),
                    'rule_id':rule['rule_id'],'kind':rule['kind'],'op':op,
                    'condition_start':stamp(condition_start),'trigger_at':stamp(ts),
                    'last_positive_at':stamp(ts),'trigger_value':str(value),'last_value':str(value),
                    'unit':rule['unit'],'feature_value':str(feature),'baseline_value':str(baseline) if baseline is not None else None,
                    'baseline_at':stamp(ts-timedelta(seconds=window)) if window else None,
                    'threshold':str(limit),'second_threshold':str(upper) if upper is not None else None,
                    'window_seconds':window,'duration_seconds':duration,
                    'positive_observations':confirm,'qualified_observations':confirm,'nonqualifying_observations':0,
                    'source_evidence':rule.get('source_evidence',[]),'source_kg_node':rule.get('kg_node'),
                    'document_recommended_response':rule.get('document_recommended_response'),
                    'response_label':'문서가 권고하는 대응','action_executed':False,
                    'cause_status':'규칙 조건 일치; 실제 고장 원인 미확정','expert_review_required':False,
                    'operational_assumptions':rule.get('operational_assumptions',[])}
            normal=0
        last,lastvalue=ts,value
        if not window:history.clear()
    emit('open_at_data_end',None)
    return events

def external_candidates(path, rules):
    if path is None:return []
    candidates=read(path)
    if not isinstance(candidates,list):raise ValueError('External candidates must be a JSON list')
    pairs={(r['sensor_id'],r['rule_id']) for r in rules};result=[]
    for item in candidates:
        for key in ['sensor_id','start','end','origin','evidence']:
            if not item.get(key):raise ValueError('External candidate missing '+key)
        if datetime.fromisoformat(item['end'])<datetime.fromisoformat(item['start']):raise ValueError('Reversed interval')
        mapped=(item['sensor_id'],item.get('rule_id')) in pairs
        result.append({**item,'status':'문서 규칙 연결 후보' if mapped else '문서 미정의 이상 후보·유형 미확정',
                       'expert_review_required':True,'notice':'전문가의 확인이 필요합니다.',
                       'automatically_discovered':False,'cause_confirmed':False})
    return result

def run(input_path, rules_path, out, external=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    groups,problems=read_observations(input_path);rules=read(rules_path)['rules']
    events=[]
    for r in rules:
        if r['sensor_id'] not in groups:raise ValueError('Missing required sensor')
        events.extend(scan(groups[r['sensor_id']],r))
    write(out/'events.json',sorted(events,key=lambda x:(x['trigger_at'],x['sensor_id'],x['rule_id'])))
    write(out/'missing_data.json',problems)
    write(out/'external_candidates.json',external_candidates(external,rules))
    write(out/'summary.json',{'events':len(events),'rules':len(rules),'sensors':len(groups),
          'observations':sum(map(len,groups.values())),'missing_reports':len(problems),
          'gold_loaded':False,'api_calls':0,'policy':POLICY,
          'input_sha256':digest(input_path),'rules_sha256':digest(rules_path),
          'detector_sha256':digest(__file__),
          'external_candidates_sha256':digest(external) if external else None,
          'drift_warmup':'full contiguous window required; warm-up is unassessable, not confirmed normal'})
    write(out/'seal.json',{p.name:digest(p) for p in sorted(out.glob('*.json'))})
    return read(out/'summary.json')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--rules',required=True)
    p.add_argument('--out',required=True);p.add_argument('--external-candidates')
    a=p.parse_args();print(json.dumps(run(a.input,a.rules,a.out,a.external_candidates),ensure_ascii=False))
