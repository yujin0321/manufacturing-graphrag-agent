"""Prepare allowlisted observations and rules; never reads event labels."""
import ast,csv,json,re,sys,shutil,hashlib
from pathlib import Path
from types import SimpleNamespace
from decimal import Decimal
from datetime import datetime,timedelta
from collections import Counter
import detector as d

IM_URI='https://example.org/imaks/v1#'

def upstream(source):
    from rdflib import RDF,URIRef,Namespace
    tree=ast.parse(Path(source).read_text(encoding='utf-8'))
    names={'parse_condition','_sensor_info','compile_rules','scan'}
    selected=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    scope={'RDF':RDF,'URIRef':URIRef,'c':SimpleNamespace(IM=Namespace(IM_URI)),
           'canonical_id':lambda x:x.rsplit('::',1)[-1], 're':re,'Decimal':Decimal,
           'datetime':datetime,'timedelta':timedelta,'SAMPLE_SECONDS':30,'_NUM':r'(-?\d+(?:\.\d+)?)',
           'v1':SimpleNamespace(split=lambda t:'train' if t<'2026-01-07' else 'validation' if t<'2026-01-08' else 'test')}
    exec(compile(ast.Module(body=selected,type_ignores=[]),str(source),'exec'),scope)
    assert names.issubset(scope)
    return scope

def prepare(raw,kg,chunks,upstream_file,v1_file,root):
    from rdflib import Graph,URIRef,Namespace
    root=Path(root)
    if (root/'protocol_lock.json').exists():raise ValueError('Preserve frozen preparation; choose a new root')
    inputs=root/'inputs';inputs.mkdir(exist_ok=True)
    for name,path in [('candidate.ttl',kg),('chunks.jsonl',chunks),('upstream_kg_rules.py',upstream_file),('upstream_rules.py',v1_file)]:
        shutil.copy2(path,inputs/name)
    records=[json.loads(l) for l in Path(chunks).read_text(encoding='utf-8').splitlines()]
    assert len(records)==86
    with (inputs/'observations.csv').open('w',encoding='utf-8',newline='') as target,Path(raw).open(encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(target,fieldnames=d.FIELDS);w.writeheader();thresholds={}
        for row in csv.DictReader(f):
            w.writerow({k:row[k] for k in d.FIELDS})
            values={out:row[src] for out,src in [('nominalValue','nominal'),('warnLo','warn_lo'),('warnHi','warn_hi'),('critLo','crit_lo'),('critHi','crit_hi')]}
            if row['sensor_id'] in thresholds:assert values==thresholds[row['sensor_id']]
            thresholds[row['sensor_id']]=values
    scope=upstream(upstream_file);g=Graph().parse(kg,format='turtle');assert len(g)==2806
    rules,unsupported=scope['compile_rules'](g);assert len(rules)==74
    # Cross-check against v1's independently source-reviewed thirty conditions.
    tree=ast.parse(Path(v1_file).read_text(encoding='utf-8'));fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='definitions')
    ns={'Decimal':Decimal};exec(compile(ast.Module(body=[fn],type_ignores=[]),str(v1_file),'exec'),ns)
    oracle,_=ns['definitions']({r['chunk_id']:r for r in records},thresholds)
    def signature(r):
        return (r['sensor_id'],r['op'],Decimal(str(r['value'])),Decimal(str(r['second'])) if r.get('second') is not None else None,int(r.get('duration_seconds',r.get('duration',0))))
    expected=Counter(signature(r) for r in oracle);actual=Counter(signature(r) for r in rules if r['kind']=='kg_document_rule')
    assert expected==actual and len(oracle)==30
    im=Namespace(IM_URI)
    threshold_diffs=[]
    for r in rules:
        if r['kind']!='kg_document_rule':
            level='crit' if r['kind']=='kg_threshold_critical' else 'warn'
            if Decimal(r['value'])!=Decimal(thresholds[r['sensor_id']][level+'Lo']) or Decimal(r['second'])!=Decimal(thresholds[r['sensor_id']][level+'Hi']):threshold_diffs.append(r['rule_id'])
        node=URIRef(r['kg_node']);evidence=[]
        for prov in g.objects(node,im.hasProvenance):
            quote=str(g.value(prov,im.sourceQuote) or '');qhash=str(g.value(prov,im.textSha256) or '')
            if quote:
                assert hashlib.sha256(quote.encode()).hexdigest()==qhash
                matches=[x['chunk_id'] for x in records if ' '.join(quote.split()) in ' '.join(x['text'].split()) and x['source_file_sha256']==str(g.value(prov,im.fileSha256))]
                assert matches
                evidence.append({'chunk_ids':matches,'quote':quote,'quote_sha256':qhash})
        assert evidence
        r.update(source_evidence=evidence,document_recommended_response=str(g.value(node,im.responseText) or ''),operational_assumptions=[])
    assert not threshold_diffs
    d.write(root/'rules_baseline.json',{'rules':rules,'unsupported':unsupported})
    improved=json.loads(json.dumps(rules));added=[]
    table=next(x for x in records if x['chunk_id']=='SOP-003:p1:table1:chunk')
    for row in table['text'].splitlines():
        if not row.startswith('Rule ID: '):continue
        fields=dict(part.split(': ',1) for part in re.split(r'; (?=(?:Rule ID|Sensor|Station|Trigger|Action|Priority): )',row))
        trigger=fields['Trigger'];match=re.fullmatch(r'\w+ DRIFT >([\d.]+)(.*?) (?:over|for) (\d+)(\+)? (min|h)',trigger)
        if not match:continue
        value,unit,period,plus,scale=match.groups();rid=fields['Rule ID'];sid=fields['Station']+'_'+fields['Sensor']
        matching=[r for r in unsupported if r['rule_id']==rid and r['sensor_id']==sid];assert len(matching)==1
        base=matching[0];assert Decimal(value)>0 and unit.strip()==base['unit']
        added.append({**{k:base[k] for k in ['kg_node','rule_id','sensor_id','unit','condition_text']},
                     'kind':'kg_document_drift','op':'delta_gt','value':value,'second':None,'duration_seconds':0,
                     'window_seconds':int(period)*(3600 if scale=='h' else 60),
                     'document_recommended_response':fields['Action'],'priority':fields['Priority'],
                     'source_evidence':[{'chunk_ids':[table['chunk_id']],'quote':row,'quote_sha256':hashlib.sha256(row.encode()).hexdigest()}],
                     'operational_assumptions':['signed endpoint increase; exact fixed lookback; all intervening samples required',
                       'not equivalent to SOP-002 sigma-based monotonic slope definition',
                       '30+ min interpreted as fixed 30-minute change, subject to team review' if plus else 'fixed document lookback']})
    assert len(added)==4
    improved+=added
    d.write(root/'rules_improved.json',{'rules':improved,'unsupported':[r for r in unsupported if r['rule_id'] not in {x['rule_id'] for x in added}],
             'out_of_scope':['SOP-004 access/occupancy/acknowledgment: no corresponding telemetry input',
             'SOP-002 statistical SPIKE/DRIFT/STUCK tolerance and causal association definitions not all implemented',
             'work-command-dependent speed rule; cross-sensor correlation; installed-product mapping'],
             'policy':d.POLICY})
    d.write(root/'source_audit.json',{'baseline_conditions_match_v1':30,'threshold_conditions_match_metadata':44,
             'threshold_mismatches':threshold_diffs,'added_delta_rules':4,'triples':len(g),'chunks':len(records),
             'quotes_validated':True,'rules_baseline':74,'rules_improved':78,'unsupported_numeric_candidates':5,
             'note':'v1 reviewed table and KG are checked against one another, not independent domain expert certification'})
    d.write(root/'protocol_lock.json',{'fixed_before_label_evaluation':True,'policy':d.POLICY,
              'evaluation':'same-sensor zero-grace overlap; coverage + confirmed-alarm-in-gold-window; merged alarm episodes one-to-one maximum matching',
              'label_access':'only evaluator after all output seals; previous team result exposure disclosed',
              'inputs':{p.name:d.digest(p) for p in inputs.iterdir()},
              'rules':{p.name:d.digest(p) for p in root.glob('rules_*.json')},
              'code':{p.name:d.digest(p) for p in (root/'code').glob('*.py')},
              'raw_source_sha256':d.digest(raw),'upstream_commit':'2b19fc6a05be86485282266925b94b96ae0dd230'})

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser()
    for name in ['raw','kg','chunks','upstream','v1','root']:p.add_argument('--'+name,required=True)
    a=p.parse_args();prepare(a.raw,a.kg,a.chunks,a.upstream,a.v1,a.root)
