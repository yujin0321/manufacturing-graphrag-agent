"""Explicit source-reviewed rules. No learned model, gold labels or API calls."""
import argparse
import csv
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote
from rdflib import Graph, Namespace, URIRef, Literal, RDF
from imaks_kg.rag import vector as v, comparison as c

OUT=v.REPO_ROOT/'kg_build/rule_detector_20261026'
INPUT='preprocessed/sensors/input/ts_input.csv'
THRESHOLDS='preprocessed/sensors/rules/sensor_thresholds.csv'
FIELDS=['timestamp','zone','station_id','sensor_id','sensor_type','value','unit']
EX=Namespace('https://example.org/imaks/detection/v1#')


def split(ts):
    return 'train' if ts<'2026-01-07' else 'validation' if ts<'2026-01-08' else 'test'


def definitions(corpus, thresholds):
    rules=[]
    def add(rule, sensor, unit, op, value, source, duration=0, branch='main', second=None):
        chunk=corpus[source]
        text=chunk['text']
        if rule.startswith('MAINT-'):
            text=next(line for line in text.splitlines() if line.startswith('Rule ID: '+rule+';'))
        rules.append({'id':rule+':'+branch,'document_rule':rule,'sensor_id':sensor,'unit':unit,
            'op':op,'value':str(value),'second':str(second) if second is not None else None,
            'duration_seconds':duration,'source_chunk':source,'source_quote':text,
            'source_text_sha256':chunk['text_sha256'],'kind':'document_rule'})
    def sop(rule,sensor,unit,op,value,**kw):
        source=next(k for k in corpus if k.startswith('SOP-001:') and k.endswith(':'+rule))
        add(rule,sensor,unit,op,value,source,**kw)
    sop('RULE-ST01-01','ST01_FILLING_FLW','L/min','outside',112,second=128)
    sop('RULE-ST01-02','ST01_FILLING_TMP','°C','gt',26)
    sop('RULE-ST01-03','ST01_FILLING_PRS','bar','lt','3.3')
    sop('RULE-ST02-01','ST02_SEALING_TMP','°C','outside',175,second=195)
    sop('RULE-ST02-02','ST02_SEALING_TMP','°C','gt',210)
    nominal=Decimal(thresholds['ST02_SEALING_CUR']['nominalValue'])
    sop('RULE-ST02-03','ST02_SEALING_CUR','A','gt',nominal+Decimal('1.5'),duration=300)
    sop('RULE-ST03-01','ST03_LABELLING_TEN','N','outside','1.8',second='2.6')
    sop('RULE-ST03-02','ST03_LABELLING_CNT','pcs/min','lt',110,branch='below110')
    sop('RULE-ST03-02','ST03_LABELLING_CNT','pcs/min','lt',100,branch='below100')
    sop('RULE-ST03-03','ST03_LABELLING_TEN','N','stuck_exact',11)
    sop('RULE-ST04-01','ST04_PACKAGING_VIB','mm/s','gt','0.20')
    sop('RULE-ST04-02','ST04_PACKAGING_VIB','mm/s','gt','0.35')
    sop('RULE-SRV01-01','SRV01_SERVERROOM_TMP','°C','gt',25)
    sop('RULE-SRV01-02','SRV01_SERVERROOM_TMP','°C','gt',28)
    sop('RULE-WRH01-01','WRH01_WAREHOUSE_TMP','°C','outside','0.5',second=8)
    sop('RULE-WRH01-01','WRH01_WAREHOUSE_TMP','°C','gt',12,branch='critical')
    sop('RULE-WRH01-02','WRH01_WAREHOUSE_HUM','%RH','gt',85)
    sop('RULE-CHM01-01','CHM01_CHEMICALSTORAGE_TMP','°C','outside',10,second=20)
    sop('RULE-CHM01-01','CHM01_CHEMICALSTORAGE_TMP','°C','gt',25,branch='critical')
    sop('RULE-CHM01-02','CHM01_CHEMICALSTORAGE_HUM','%RH','gt',50,branch='limit')
    sop('RULE-CHM01-02','CHM01_CHEMICALSTORAGE_HUM','%RH','gt',45,branch='action')
    sop('RULE-RND01-01','RND01_RDLAB_TMP','°C','outside',18,second=26)
    sop('RULE-RND01-02','RND01_RDLAB_HUM','%RH','gt',65)
    sop('RULE-RND01-02','RND01_RDLAB_HUM','%RH','gt',75,branch='critical')
    sop('RULE-CAF01-01','CAF01_CAFETERIA_TMP','°C','gt',26)
    sop('RULE-CAF01-02','CAF01_CAFETERIA_HUM','%RH','gt',70)
    source='SOP-003:p1:table1:chunk'
    add('MAINT-03','ST03_LABELLING_TEN','N','stuck_exact',11,source)
    add('MAINT-04','ST01_FILLING_PRS','bar','lt','3.3',source,duration=900)
    add('MAINT-05','SRV01_SERVERROOM_TMP','°C','gt',25,source,duration=300)
    add('MAINT-07','CHM01_CHEMICALSTORAGE_TMP','°C','gt',20,source,duration=600)
    unsupported=[
        {'rule':'RULE-ST04-03','reason':'Operator-command history absent; speed alone cannot establish the full condition.'},
        {'rule':'RULE-ST02-04','reason':'Correlation/monitoring instruction, not proof of a new causal anomaly; no numeric drift definition.'},
        {'rule':'RULE-CHM01-03','reason':'No person-role, hazmat training and access observations in sensor input.'},
        *[{'rule':x,'reason':'DRIFT definition/baseline and window aggregation require a separate agreed operational specification; not guessed.'} for x in ['MAINT-01','MAINT-02','MAINT-06','MAINT-08']],
        {'rule':'SOP-004 access/occupancy/acknowledgment','reason':'Required access, occupancy and response records are outside this 7-column sensor input.'},
        {'rule':'Datasheet installed-product limits','reason':'No verified sensor-to-installed-product mapping; not imposed as plant limits.'},
        {'rule':'SOP-002 SPIKE/DRIFT/CORRELATED statistical definitions','reason':'Sigma/baseline, trend criteria and causal-event association are not specified by this baseline.'}]
    return rules,unsupported


def evaluate_rule(rows, rule):
    """Forward-only decision; contiguous 30-second samples, reset at split/gap.

    STUCK exact is a declared conservative implementation, not a tolerance fit.
    Event ends are retrospective last-positive times, not known at trigger time.
    """
    events=[];current=None;last=None;lastvalue=None;start=None;same=0
    for row in rows:
        ts=datetime.fromisoformat(row['timestamp']);value=Decimal(row['value'])
        if row['unit']!=rule['unit'] or not value.is_finite():raise ValueError('Unit/nonfinite observation')
        contiguous=last is not None and (ts-last).total_seconds()==30 and split(row['timestamp'])==split(last.isoformat())
        if not contiguous:
            start=None;same=0
            if current:events.append(current);current=None
        same=same+1 if contiguous and value==lastvalue else 1
        limit=Decimal(rule['value']);op=rule['op']
        if op=='gt':condition=value>limit
        elif op=='lt':condition=value<limit
        elif op=='outside':condition=value<limit or value>Decimal(rule['second'])
        elif op=='stuck_exact':condition=same>=int(limit)
        else:raise ValueError('Unknown operation')
        if condition:
            if start is None:start=ts
        else:start=None
        duration=rule['duration_seconds']
        hit=condition and (duration==0 or (ts-start).total_seconds()>duration)
        if hit:
            if current is None:
                witness_start=ts if op!='stuck_exact' else ts-__import__('datetime').timedelta(seconds=(same-1)*30)
                current={'sensor_id':row['sensor_id'],'rule_id':rule['id'],'kind':rule['kind'],
                    'split':split(row['timestamp']),'trigger_at':row['timestamp'],
                    'condition_start':(start if duration else witness_start).isoformat(),
                    'trigger_value':str(value),'unit':row['unit'],'positive_samples':0,
                    'min_value':str(value),'max_value':str(value)}
            current['last_positive_at']=row['timestamp'];current['positive_samples']+=1
            current['min_value']=str(min(Decimal(current['min_value']),value));current['max_value']=str(max(Decimal(current['max_value']),value))
        elif current:events.append(current);current=None
        last=ts;lastvalue=value
    if current:events.append(current)
    return events


def read_inputs():
    profile=v.read(v.REPO_ROOT/'preprocessed/sensors/profile.json')
    for path in [INPUT,THRESHOLDS]:
        if v.digest((v.REPO_ROOT/path).read_bytes())!=profile['output_sha256'][path]:raise ValueError('Frozen sensor input changed')
    def csvrows(path):
        with (v.REPO_ROOT/path).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
    raw=csvrows(INPUT);thresholds={r['sensor_id']:r for r in csvrows(THRESHOLDS)}
    if not raw or list(raw[0])!=FIELDS:raise ValueError('Observation allowlist mismatch')
    grouped=defaultdict(list);seen=set()
    for row in raw:
        key=(row['sensor_id'],row['timestamp'])
        if key in seen:raise ValueError('Duplicate sensor/time')
        seen.add(key);grouped[row['sensor_id']].append(row)
    for rows in grouped.values():rows.sort(key=lambda r:r['timestamp'])
    if set(grouped)!=set(thresholds):raise ValueError('Sensor threshold mismatch')
    return grouped,thresholds,profile


def run(out=OUT):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    groups,thresholds,profile=read_inputs();sources,_=v.source_records();corpus={r['chunk_id']:r for r in sources}
    rules,unsupported=definitions(corpus,thresholds)
    for sensor,t in thresholds.items():
        rules.append({'id':'METADATA_WARN:'+sensor,'sensor_id':sensor,'unit':t['unit'],'op':'outside',
                      'value':t['warnLo'],'second':t['warnHi'],'duration_seconds':0,'kind':'metadata_threshold',
                      'source_chunk':None,'source_quote':'value < warnLo OR value > warnHi; raw sensor threshold metadata',
                      'source_file':THRESHOLDS})
    v.write(out/'rules.json',{'rules':rules,'unsupported':unsupported,
        'policy':{'sample_seconds':30,'gap_reset':True,'split_reset':True,'duration':'strict elapsed seconds > limit',
                  'stuck':'11 consecutive exactly equal sampled values; tolerance-based STUCK not implemented',
                  'maintenance_deadlines':'Action deadlines are not condition persistence times',
                  'range':'outside inclusive maintained range; endpoints themselves not violations',
                  'drift_humidity':'RULE-RND01-02 treated as stated absolute HUM threshold, not a fitted slope'}})
    v.write(out/'input_lock.json',{'input_hashes':{p:profile['output_sha256'][p] for p in [INPUT,THRESHOLDS]},
        'source_chunks_sha256':v.digest(v.SOURCE.read_bytes()),'detector_sha256':v.digest(Path(__file__).read_bytes()),
        'rules_sha256':v.digest((out/'rules.json').read_bytes()),'gold_loaded':False,'training':False})
    events=[]
    for rule in rules:events.extend(evaluate_rule(groups[rule['sensor_id']],rule))
    events.sort(key=lambda e:(e['trigger_at'],e['sensor_id'],e['rule_id']))
    for e in events:e['id']='det-'+v.digest(v.encoded(e))[:20]
    v.write(out/'events.json',events)
    # A separate overlay links candidates to immutable KG nodes; base KG is never mutated.
    base=c.load_graph();links=c.source_links(base,sources);overlay=Graph();overlay.bind('det',EX)
    index={r['id']:r for r in rules}
    for e in events:
        n=URIRef('https://example.org/imaks/detection/'+e['id']);rule=index[e['rule_id']]
        rn=URIRef('https://example.org/imaks/detection/rule/'+quote(rule['id'],safe=''))
        overlay.add((n,RDF.type,EX.RuleEvaluationCandidate));overlay.add((n,EX.evaluatedRule,rn))
        overlay.add((rn,RDF.type,EX.ExecutableRuleConfiguration));overlay.add((rn,EX.definition,Literal(__import__('json').dumps(rule,ensure_ascii=False))))
        for k in ['sensor_id','trigger_at','condition_start','trigger_value','last_positive_at','unit','kind']:
            overlay.add((n,EX[k],Literal(e[k])))
        overlay.add((n,EX.status,Literal('offline_observed_rule_match_not_confirmed_anomaly')))
        for node,identifier in base.subject_objects(c.IM.identifier):
            if str(identifier)==e['sensor_id']:overlay.add((n,EX.observedSensor,node))
        if rule.get('source_chunk'):
            overlay.add((rn,EX.sourceChunk,Literal(rule['source_chunk'])))
            for node,cs in links.items():
                ids=list(map(str,base.objects(node,c.IM.identifier)))
                if rule['source_chunk'] in cs and any(i==rule['document_rule'] or i.endswith('::'+rule['document_rule']) for i in ids):
                    overlay.add((rn,EX.existingRule,node))
    overlay.serialize(out/'candidate_events.ttl',format='turtle')
    summary={'rows':sum(map(len,groups.values())),'sensors':len(groups),'document_branches':sum(r['kind']=='document_rule' for r in rules),
        'distinct_document_rules':len({r['document_rule'] for r in rules if r['kind']=='document_rule'}),
        'metadata_thresholds':len(thresholds),'events':len(events),'unsupported':unsupported,
        'event_counts':{kind:{s:sum(e['kind']==kind and e['split']==s for e in events) for s in ['train','validation','test']} for kind in ['document_rule','metadata_threshold']},
        'api_calls':0,'gold_loaded':False,'base_kg_sha256':v.digest((v.REPO_ROOT/c.KG_REL).read_bytes()),'overlay_triples':len(overlay)}
    v.write(out/'summary.json',summary)
    v.write(out/'complete.json',{p.name:v.digest(p.read_bytes()) for p in out.iterdir() if p.is_file()})
    print(__import__('json').dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=OUT);a=p.parse_args();run(a.out)
