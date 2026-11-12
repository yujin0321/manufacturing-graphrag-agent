"""Evaluator only: labels are opened after sealed, label-free inference."""
import argparse,csv,json,statistics
from collections import defaultdict,Counter
from datetime import datetime
from pathlib import Path
import detector as d

def gold_events(path):
    groups=defaultdict(list)
    with Path(path).open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            groups[r['sensor_id']].append({k:r[k] for k in ['timestamp','sensor_id','anomaly_label','severity']})
    result=[]
    for sid,rows in groups.items():
        rows.sort(key=lambda r:r['timestamp']);current=None;last=None
        for r in rows:
            ts=datetime.fromisoformat(r['timestamp']);label=r['anomaly_label']
            continuing=current and label==current['label'] and last is not None and (ts-last).total_seconds()==30
            if not continuing:
                if current:result.append(current)
                current=None
                if label!='NORMAL':current={'sensor_id':sid,'label':label,'start':r['timestamp'],'end':r['timestamp'],'samples':0}
            if current:current['end']=r['timestamp'];current['samples']+=1
            last=ts
        if current:result.append(current)
    return sorted(result,key=lambda r:(r['start'],r['sensor_id']))

def overlap(x,y):
    return x['sensor_id']==y['sensor_id'] and x['trigger_at']<=y['end'] and x['last_positive_at']>=y['start']

def episodes(events):
    out=[]
    for e in sorted(events,key=lambda x:(x['sensor_id'],x['trigger_at'],x['last_positive_at'])):
        if out and out[-1]['sensor_id']==e['sensor_id'] and e['trigger_at']<=out[-1]['last_positive_at']:
            out[-1]['last_positive_at']=max(out[-1]['last_positive_at'],e['last_positive_at'])
            out[-1]['rules']=sorted(set(out[-1]['rules']+[e['rule_id']]))
        else:out.append({**{k:e[k] for k in ['sensor_id','trigger_at','last_positive_at']},'rules':[e['rule_id']]})
    return out

def maximum_match(ep,gold):
    # Independent event one-to-one scoring. Any compatible maximum matching is
    # sufficient for counts; no claim this pairing optimizes alarm latency.
    matched={}
    def visit(i,seen):
        for j,g in enumerate(gold):
            if j in seen or not overlap(ep[i],g):continue
            seen.add(j)
            if j not in matched or visit(matched[j],seen):matched[j]=i;return True
        return False
    for i in range(len(ep)):visit(i,set())
    return matched

def metrics(events,gold):
    per=[]
    for g in gold:
        hits=[e for e in events if overlap(e,g)]
        onset=[e for e in hits if g['start']<=e['trigger_at']<=g['end']]
        first=min((e['trigger_at'] for e in hits),default=None)
        latency=(datetime.fromisoformat(first)-datetime.fromisoformat(g['start'])).total_seconds()/60 if first else None
        per.append({**g,'covered':bool(hits),'new_alarm_in_gold_window':bool(onset),
                    'first_alarm':first,'latency_minutes_signed':latency,
                    'preexisting_alarm':bool(first and first<g['start']),
                    'rules':sorted({e['rule_id'] for e in hits})})
    alarms_without_overlap=[e for e in events if not any(overlap(e,g) for g in gold)]
    ep=episodes(events);match=maximum_match(ep,gold);tp=len(match);fp=len(ep)-tp;fn=len(gold)-tp
    lat=[p['latency_minutes_signed'] for p in per if p['covered'] and not p['preexisting_alarm']]
    return {'rule_alarm_count':len(events),'gold_events':len(gold),
            'events_covered':sum(p['covered'] for p in per),'events_with_new_alarm':sum(p['new_alarm_in_gold_window'] for p in per),
            'coverage_recall':sum(p['covered'] for p in per)/len(gold),
            'rule_alarms_without_gold_overlap':len(alarms_without_overlap),
            'rule_alarm_overlap_precision':1-len(alarms_without_overlap)/len(events) if events else 0,
            'median_latency_minutes_non_preexisting':statistics.median(lat) if lat else None,
            'preexisting_alarm_events':sum(p['preexisting_alarm'] for p in per),
            'merged_episode_count':len(ep),'one_to_one_TP':tp,'one_to_one_FP':fp,'one_to_one_FN':fn,
            'one_to_one_precision':tp/len(ep) if ep else 0,'one_to_one_recall':tp/len(gold),
            'one_to_one_F1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0,
            'by_type':{t:{'caught':sum(p['covered'] for p in per if p['label']==t),'total':sum(p['label']==t for p in per)} for t in sorted({g['label'] for g in gold})},
            'events':per,'unmatched_rule_alarms':alarms_without_overlap}

def run(root,labels):
    root=Path(root);done=d.read(root/'generation_complete.json')
    lock=d.read(root/'protocol_lock.json')
    for name,h in lock['code'].items():assert d.digest(root/'code'/name)==h,'Code changed after protocol lock'
    for name,h in done['runs'].items():
        folder=root/'runs'/name;assert d.digest(folder/'seal.json')==h
        for f,v in d.read(folder/'seal.json').items():assert d.digest(folder/f)==v
    # The only label access in the runtime is below this barrier.
    gold=gold_events(labels);assert len(gold)==14
    result={}
    for name in done['runs']:
        events=d.read(root/'runs'/name/'events.json')
        result[name]={'ALL':metrics(events,gold),
                      'by_family':{k:metrics([e for e in events if e['kind']==k],gold) for k in sorted({e['kind'] for e in events})}}
    out=root/'evaluation';out.mkdir(exist_ok=False)
    d.write(out/'event_metrics.json',result)
    d.write(out/'gold_events_evaluator_only.json',gold)
    d.write(out/'evaluation_manifest.json',{'labels_sha256':d.digest(labels),'gold_events':14,
          'labels_opened_after_all_runs_sealed':True,'grace_seconds':0,
          'matching':'same sensor; alarm-confirmation to last-positive interval overlap; no type agreement required',
          'limits':['Interval coverage is not correct anomaly-type or root-cause identification',
                    'Persistent early alarms can overlap gold; separately report new alarms and negative latency',
                    'One-to-one precision uses merged same-sensor overlapping alarm episodes, not raw rule counts',
                    'No independent holdout: team has previously inspected these 14 events',
                    'Unmatched alarms are relative to provided labels, not expert-certified false physical events']})
    with (out/'event_comparison.csv').open('w',encoding='utf-8-sig',newline='') as f:
        fields=['sensor_id','label','start','end']+[name+'_'+key for name in result for key in ['covered','new_alarm_in_gold_window','latency_minutes_signed']]
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for i,g in enumerate(gold):
            row={k:g[k] for k in fields[:4]}
            for name in result:
                for key in ['covered','new_alarm_in_gold_window','latency_minutes_signed']:row[name+'_'+key]=result[name]['ALL']['events'][i][key]
            w.writerow(row)
    print(json.dumps({n:{k:v for k,v in x['ALL'].items() if k not in ['events','unmatched_rule_alarms','by_type']} for n,x in result.items()},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--labels',required=True)
    a=p.parse_args();run(a.root,a.labels)
