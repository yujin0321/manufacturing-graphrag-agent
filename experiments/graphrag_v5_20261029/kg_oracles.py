"""Independent evaluation queries. Not imported by any inference component."""
from collections import defaultdict
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent
REPO=ROOT.parent.parent
sys.path.insert(0,str(REPO/'src'))
from rdflib import RDF,URIRef
from imaks_kg.rag import comparison as c,vector as v
from imaks_kg.rag.kg_query_v5 import short


def oracle(engine,qid):
    g=engine.graph;refs=engine.refs
    def objects(n,p):return sorted(short(o) for o in g.objects(n,c.IM[p]))
    def subjects(p,n):return set(g.subjects(c.IM[p],n))
    def rule(n):
        return {'node':short(n),'identifier':objects(n,'identifier'),
                'types':sorted(short(o) for o in g.objects(n,RDF.type)),
                **{p:objects(n,p) for p in ['appliesToSensor','actionTarget','sourceDocument','conditionText','responseText','priority']}}
    rules={n for typ in ['OperationalRule','ThresholdRule','MaintenanceRule','AccessRule'] for n in g.subjects(RDF.type,c.IM[typ])}
    s2=refs['ST02_SEALING'];s4=refs['ST04_PACKAGING'];cur=refs['ST02_SEALING_CUR'];doc1=refs['SOP-001'];doc3=refs['SOP-003']
    sensors2=set(g.objects(s2,c.IM.hasSensor));sensors4=set(g.objects(s4,c.IM.hasSensor))
    a={n for s in sensors4 for n in subjects('appliesToSensor',s)};b=subjects('actionTarget',s4)
    needed=set();result={}
    if qid=='REL-K01':
        result={key:sorted(short(n) for n in nodes) for key,nodes in [('A',a),('B',b),('intersection',a&b),('A_minus_B',a-b),('B_minus_A',b-a)]};needed=a|b
    elif qid in ['REL-K02','ADD-01']:
        tuples=[]
        for s in sensors2:
            for n in subjects('appliesToSensor',s):
                for target in g.objects(n,c.IM.actionTarget):
                    if qid=='REL-K02' and target!=s2 and (target,RDF.type,c.IM.Station) in g or qid=='ADD-01' and target==s4 and (n,c.IM.sourceDocument,doc1) in g:
                        tuples.append({'sensor':short(s),'rule':short(n),'target':short(target),'documents':objects(n,'sourceDocument')});needed.add(n)
        result={'tuples':sorted(tuples,key=lambda x:json.dumps(x,sort_keys=True))}
    elif qid=='REL-K03':
        needed=subjects('sourceDocument',doc3);result={'rules':[rule(n) for n in sorted(needed,key=str)]}
    elif qid in ['REL-K04','YB-03']:
        def paths(start,end=None):
            found=[]
            def dfs(path):
                for n in sorted(g.objects(path[-1],c.IM.feedsInto),key=str):
                    if n in path:continue
                    p=path+[n]
                    if end is None or n==end:found.append(p)
                    if n!=end:dfs(p)
            dfs([start]);return found
        start=refs['ST01_FILLING'];forward=paths(start,s4 if qid=='REL-K04' else None)
        reverse=paths(s4,start) if qid=='REL-K04' else []
        needed={n for p in forward+reverse for n in p};result={'forward':[[short(n) for n in p] for p in forward],
            'reverse':[[short(n) for n in p] for p in reverse],'limit':'No stored path does not imply physical absence or absence of causation.'}
    elif qid in ['REL-K05','YB-11']:
        names=['candidate-SOP-001::RULE-ST02-02','candidate-SOP-003::MAINT-05'] if qid=='REL-K05' else ['MAINT-02']
        entries=[]
        for name in names:
            n=refs[name];needed.add(n)
            for p in g.objects(n,c.IM.hasProvenance):
                needed.add(p)
                entries.append({'node':short(n),'documents':objects(n,'sourceDocument'),
                    'provenance':short(p),'fields':{short(k):str(o) for k,o in g.predicate_objects(p)}})
        result={'entries':entries,'limit':'Hash agreement checks representation identity, not domain validity; normalized table row is not a contiguous PDF sentence.'}
    elif qid=='REL-K06':
        sensor=refs['SRV01_SERVERROOM_TMP'];needed=subjects('appliesToSensor',sensor)
        result={'rules':[rule(n) for n in sorted(needed,key=str)],'missing_condition':[short(n) for n in sorted(needed,key=str) if not list(g.objects(n,c.IM.conditionText))],
                'limit':'A missing stored conditionText does not mean the source has no condition.'}
    elif qid=='ADD-02':
        only={n for n in b if set(g.objects(n,c.IM.actionTarget))=={s4}}
        multiple=b-only;missing={n for n in rules if not list(g.objects(n,c.IM.actionTarget))}
        needed=b|missing;result={'only_ST04':sorted(map(short,only)),'other_targets_also':sorted(map(short,multiple)),
                                'no_actionTarget_in_entire_rule_population':sorted(map(short,missing)),
                                'scope_note':'No-actionTarget nodes cannot be claimed to target ST04; reported separately over all rules.'}
    elif qid=='ADD-03':
        entries=[]
        for s in g.subjects(RDF.type,c.IM.Sensor):
            rs=subjects('appliesToSensor',s);left={n for n in rs if (n,c.IM.sourceDocument,doc1) in g};right={n for n in rs if (n,c.IM.sourceDocument,doc3) in g}
            if left and right:
                entries.append({'sensor':short(s),'SOP-001':sorted(map(short,left)),'SOP-003':sorted(map(short,right))});needed.update(left|right);needed.add(s)
        result={'shared':entries,'limit':'Shared sensor does not imply equal conditions/actions.'}
    elif qid=='ADD-04':
        paths=[(cur,n,s4) for n in subjects('appliesToSensor',cur) if (n,c.IM.actionTarget,s4) in g]
        needed={n for p in paths for n in p};result={'paths':[[short(n) for n in p] for p in paths],
            'stored_direction':'Rule -> appliesToSensor -> Sensor, Rule -> actionTarget -> Station',
            'search_direction':'Sensor <- appliesToSensor <- Rule -> actionTarget -> Station',
            'feedsInto_only_from_sensor':[]}
    elif qid=='ADD-05':
        needed=subjects('appliesToSensor',cur);groups=defaultdict(list)
        for n in sorted(needed,key=str):
            for d in g.objects(n,c.IM.sourceDocument):groups[short(d)].append(rule(n))
        result={'groups':dict(groups),'counts':{key:len(rows) for key,rows in groups.items()},'limit':'Node count is not independent knowledge count.'}
    elif qid=='ADD-06':
        needed={n for n in rules if list(g.objects(n,c.IM.sourceDocument)) and not list(g.objects(n,c.IM.appliesToSensor))}
        result={'rules':[rule(n) for n in sorted(needed,key=str)],'limit':'Source review needed: station/role/procedure rules may not require a sensor link; missing connection is not physical absence.'}
    elif qid=='YB-01':
        needed={s2}|sensors2;result={'sensors':[{'id':short(s),'units':objects(s,'unit')} for s in sorted(sensors2,key=str)]}
    elif qid=='YB-02':
        s=refs['ST04_PACKAGING_SPD'];needed={s}|subjects('hasSensor',s)
        result={'station':sorted(map(short,subjects('hasSensor',s))),'sensorType':objects(s,'sensorType'),'unit':objects(s,'unit')}
    elif qid=='YB-04':
        n=refs['CHM01_CHEMICALSTORAGE'];needed={n};result={'stationType':objects(n,'stationType'),'zone':objects(n,'zone')}
    elif qid=='YB-12':
        n=doc3;needed={n};result={'fields':{short(p):str(o) for p,o in g.predicate_objects(n)}}
    elif qid=='YB-13':
        needed={n for n in subjects('appliesToSensor',cur) if (n,RDF.type,c.IM.MaintenanceRule) in g}
        result={'rules':[rule(n) for n in sorted(needed,key=str)],'limit':'Seed and candidate nodes distinct; missing stored condition fields must be marked, not silently filled.'}
    elif qid in ['YB-16','YB-17']:
        result={'snapshot_identifier_present': 'ST99_UNKNOWN' in refs,
                'causallyAffects_triples':sum(1 for t in g.triples((None,c.IM.causallyAffects,None))),
                'limit':'No empirical scored causal candidates/lags are stored; no fabricated top three or unknown station sensor.'}
    else:return None
    evidence=sorted(engine.node_ids[n] for n in needed if n in engine.node_ids)
    if not evidence:evidence=['KG:MANIFEST']
    # Evidence rows are minimal node records, not the query's answer text itself.
    return {'id':qid,'oracle_result':result,'evidence':evidence,
            'atoms':['Return the complete matching identifiers/tuples/values in oracle_result, preserving seed and candidate identities.',
                     'Preserve requested field values, relation direction, conditions, missing fields, and any set/path partition in oracle_result.',
                     'Give traceable supporting stored facts and the question-specific limits; do not infer real-world causation, absence, installed model, or operational completion.'],
            'reviewer':'Deterministic RDF queries independent of the retrieval planner; interpretation still needs human domain review.'}
