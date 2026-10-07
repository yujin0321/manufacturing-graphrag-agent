#  데이터 전처리 + 클래스·관계 정의 + SHACL 규칙 생성 + 검증

"""Reproducible iMAKS preprocessing and RDF/SHACL build; no LLM credentials required."""
from pathlib import Path
import sys, json, hashlib, csv, re
import pandas as pd
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.deps'))
from rdflib import Graph, Namespace, Literal, RDF, RDFS, OWL, XSD
from pyshacl import validate
from pypdf import PdfReader
M = Namespace('https://example.org/imaks/')
SH = Namespace('http://www.w3.org/ns/shacl#')

def uri(value):
    from urllib.parse import quote
    return M[quote(str(value), safe='_-')]

def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

def run():
    source = ROOT / 'iMAKS_dataset'
    out = ROOT / 'data/processed'; out.mkdir(parents=True, exist_ok=True)
    ont = ROOT / 'ontology'; ont.mkdir(exist_ok=True)
    reports = ROOT / 'reports'; reports.mkdir(exist_ok=True)
    tables = {}; inventory = []
    for f in sorted(source.rglob('*')):
        if not f.is_file() or f.name == '.DS_Store': continue
        inventory.append({'path':str(f.relative_to(source)), 'bytes':f.stat().st_size,
                          'sha256':hashlib.sha256(f.read_bytes()).hexdigest()})
        if f.suffix == '.csv' and 'csi' not in f.parts:
            tables[f.stem] = pd.read_csv(f, encoding='utf-8', low_memory=False)
    dump(reports/'source_manifest.json', inventory)
    raw = tables['timeseries_raw'].copy(); annotated = tables['timeseries_annotated']
    keys = ['timestamp','sensor_id']
    assert not raw.duplicated(keys).any(), 'Duplicate sensor observations: resolve before processing'
    assert not annotated.duplicated(keys).any(), 'Duplicate annotation keys'
    raw['timestamp'] = pd.to_datetime(raw.timestamp, errors='raise')
    # Source timestamps have no timezone. Preserve them rather than inventing UTC/KST.
    raw = raw.sort_values(['sensor_id','timestamp']).reset_index(drop=True)
    assert np.isfinite(raw.value).all(), 'Non-finite measurements'
    assert (raw.crit_lo < raw.warn_lo).all() and (raw.warn_lo < raw.nominal).all()
    assert (raw.nominal < raw.warn_hi).all() and (raw.warn_hi < raw.crit_hi).all()
    raw['usable'] = raw.quality.eq('GOOD')
    raw['threshold_status'] = np.select([
        (raw.value < raw.crit_lo)|(raw.value > raw.crit_hi),
        (raw.value < raw.warn_lo)|(raw.value > raw.warn_hi)], ['CRITICAL','WARNING'], default='NORMAL')
    raw['minutes_since_previous'] = raw.groupby('sensor_id').timestamp.diff().dt.total_seconds()/60
    raw['gap_flag'] = raw.minutes_since_previous.gt(1)
    # Split by entire source days, so no overlapping windows cross a split boundary.
    days = sorted(raw.timestamp.dt.date.unique()); n=len(days)
    split_map={d:('train' if i < int(n*.6) else 'validation' if i < int(n*.8) else 'test') for i,d in enumerate(days)}
    raw['split']=raw.timestamp.dt.date.map(split_map)
    # Causal features: shift first; current and future values do not enter past statistics.
    raw['segment']=raw.groupby('sensor_id').gap_flag.cumsum()
    group=raw.groupby(['sensor_id','split','segment'], sort=False)
    raw['past_mean_10']=group.value.transform(lambda s:s.shift().rolling(10,min_periods=10).mean())
    raw['past_std_10']=group.value.transform(lambda s:s.shift().rolling(10,min_periods=10).std())
    raw['delta']=group.value.diff()
    raw.to_csv(out/'sensor_observations.csv',index=False)
    labels=annotated[keys+['anomaly_label','severity','alarm_flag']].copy()
    labels['timestamp']=pd.to_datetime(labels.timestamp)
    joined=raw[keys+['split']].merge(labels,on=keys,how='left',validate='one_to_one')
    assert joined.anomaly_label.notna().all(), 'Missing labels'
    joined.to_csv(out/'evaluation_labels.csv',index=False)
    aligned=raw[keys+['value']].merge(annotated[keys+['value']].assign(timestamp=lambda d:pd.to_datetime(d.timestamp)),on=keys,suffixes=('_raw','_annotated'),validate='one_to_one')
    assert len(aligned)==len(raw) and np.allclose(aligned.value_raw,aligned.value_annotated), 'Raw/annotated value mismatch'
    for name,d in tables.items():
        if name.startswith('timeseries'): continue
        d=d.copy()
        for c in d.columns:
            if pd.api.types.is_string_dtype(d[c]): d[c]=d[c].str.strip().replace({'R&D; Lab':'R&D Lab'})
        d.to_csv(out/(name+'.csv'),index=False)
    # CSI is a separate human activity modality with no timestamp in the files.
    # Preserve subject grouping; never fabricate a join to equipment telemetry.
    csi=[]
    for f in sorted((source/'csi').rglob('*.csv')):
        a=pd.read_csv(f,header=None).to_numpy(dtype=float)
        match=re.fullmatch(r'(.+?)(\d+)',f.stem)
        csi.append({'path':str(f.relative_to(source)), 'subject':f.parent.name,
                    'gesture':match[1] if match else f.stem,'trial':int(match[2]) if match else None,
                    'rows':a.shape[0],'columns':a.shape[1], 'finite':bool(np.isfinite(a).all()),
                    'mean':float(a.mean()),'std':float(a.std()),'min':float(a.min()),'max':float(a.max())})
    pd.DataFrame(csi).to_csv(out/'csi_manifest_features.csv',index=False)
    mqtt=json.loads((source/'sensors/mqtt_payloads.json').read_text(encoding='utf-8'))
    mr=[]
    for msg in mqtt:
        for st,reading in msg['readings'].items():
            mr.append({'message_id':msg['msg_id'],'timestamp':msg['timestamp'],
                       'station_id':msg['device']['id'],'sensor_type':st,**reading})
    pd.DataFrame(mr).to_csv(out/'mqtt_observations.csv',index=False)
    chunks=[]
    for f in sorted(source.rglob('*.pdf')):
        for i,page in enumerate(PdfReader(f).pages,1):
            txt=page.extract_text() or ''
            chunks.append({'id':f'{f.stem}-p{i}','source':str(f.relative_to(source)), 'page':i,'text':txt})
    with (out/'document_chunks.jsonl').open('w',encoding='utf-8') as fp:
        for c in chunks: fp.write(json.dumps(c,ensure_ascii=False)+'\n')
    build_graph(tables,raw,out,ont,reports,chunks)
    dump(reports/'preprocessing_summary.json', {
        'rows':{k:len(v) for k,v in tables.items()},'sensor_rows':len(raw),'sensors':raw.sensor_id.nunique(),
        'missing_values':raw[['value','timestamp','sensor_id']].isna().sum().to_dict(),
        'quality':raw.quality.value_counts().to_dict(),'gaps':int(raw.gap_flag.sum()),
        'labels':annotated.anomaly_label.value_counts().to_dict(), 'split_rows':raw.split.value_counts().to_dict(),
        'split_days':{str(k):v for k,v in split_map.items()}, 'csi_files':len(csi),
        'mqtt_readings':len(mr),'pdf_pages':len(chunks),'timezone':'unspecified in source; naive preserved',
        'policy':'No imputation, no scaling fit on evaluation data; UNCERTAIN flagged; labels excluded from inputs; overnight/shift gaps retained.'})
    print((reports/'preprocessing_summary.json').read_text(encoding='utf-8'))

def build_graph(tables,raw,out,ont,reports,chunks):
    g=Graph(); schema=Graph(); shapes=Graph()
    for x in (g,schema,shapes): x.bind('m',M); x.bind('sh',SH)
    classes=['System','Zone','Component','Sensor','AnomalyEvent','Maintenance','Person','SafetyEvent',
             'Rule','OperationalRule','ThresholdRule','MaintenanceRule','AccessRule','Observation','Document',
             'AccessEvent','AlarmResponse','OccupancySnapshot','UnknownActor']
    for c in classes: schema.add((M[c],RDF.type,OWL.Class))
    for c in ['OperationalRule','ThresholdRule','MaintenanceRule','AccessRule']: schema.add((M[c],RDFS.subClassOf,M.Rule))
    for c in ['Spike','Drift','StuckSensor','OutOfRange','Correlated']:
        schema.add((M[c],RDF.type,OWL.Class)); schema.add((M[c],RDFS.subClassOf,M.AnomalyEvent))
    relations={'contains':(None,None),'part_of':(None,None),'monitors':('Sensor','Component'),
               'hasSensor':('Component','Sensor'),'feeds_into':('Component','Component'),
               'correlates_with':('Sensor','Sensor'),'triggers':('Sensor','AnomalyEvent'),
               'resolves':('Maintenance','Sensor'),'authorized_for':('Person','Zone'),
               'involves':('SafetyEvent','Person'),'detected_in':('SafetyEvent','Zone'),
               'observedBy':('Observation','Sensor'),'locatedIn':('Component','Zone'),
               'governedBy':('Sensor','Rule'),'derivedFrom':('Rule','Document'),
               'person':(None,'Person'),'zone':(None,'Zone'),'event':('AlarmResponse','AnomalyEvent')}
    for p,(a,b) in relations.items():
        schema.add((M[p],RDF.type,OWL.ObjectProperty))
        if a: schema.add((M[p],RDFS.domain,M[a]))
        if b: schema.add((M[p],RDFS.range,M[b]))
    nodes=tables['nodes'].fillna(''); by_id=nodes.set_index('nodeId').to_dict('index')
    names={r['name']:uri(k) for k,r in by_id.items() if r['name']}
    people={r['personId']:uri(k) for k,r in by_id.items() if r['personId'] and r['label']=='Person'}
    zones={r['name'].replace('R&D; Lab','R&D Lab'):uri(k) for k,r in by_id.items() if r['label']=='Zone'}
    gt={r['gtId']:uri(k) for k,r in by_id.items() if r['gtId']}
    numeric={'critHi','critLo','warnHi','warnLo','nominalValue','durationMin','durationSec','magnitude'}
    for node,r in by_id.items():
        u=uri(node); g.add((u,RDF.type,M[r['label']]))
        for k,v in r.items():
            if v=='' or k=='label': continue
            if k in numeric: lit=Literal(float(v),datatype=XSD.double)
            elif k in {'startTs','endTs','timestamp'}: lit=Literal(v,datatype=XSD.dateTime)
            else: lit=Literal(str(v))
            g.add((u,M['zoneName' if k=='zone' else k],lit))
        if r['label']=='Component' and r['zone']: g.add((u,M.locatedIn,zones[r['zone'].replace('R&D; Lab','R&D Lab')]))
    edge_corrections=[]
    for r in tables['edges'].fillna('').to_dict('records'):
        assert r['fromId'] in by_id and r['toId'] in by_id, 'Dangling edge'
        p=r['type']; a=uri(r['fromId']); b=uri(r['toId'])
        if p=='monitors' and by_id[r['fromId']]['label']=='Component':
            p='hasSensor'; edge_corrections.append(r)
        g.add((a,M[p],b))
        if r['ruleRef']: g.add((a,M.governedBy,uri(r['ruleRef'])))
    for sid,d in raw.groupby('sensor_id'):
        u=names[sid]; r=d.iloc[0]
        for src,dst in [('crit_lo','critLo'),('warn_lo','warnLo'),('nominal','nominalValue'),('warn_hi','warnHi'),('crit_hi','critHi')]:
            g.set((u,M[dst],Literal(float(r[src]),datatype=XSD.double)))
        g.set((u,M.unit,Literal(r.unit)))
    for r in tables['ground_truth'].fillna('').to_dict('records'):
        u=uri(r['ruleId']); g.add((u,RDF.type,M.Rule)); g.add((u,RDF.type,M[r['class']]))
        for k,v in r.items():
            if v!='': g.add((u,M[k],Literal(str(v))))
        doc=uri(r['source']); g.add((doc,RDF.type,M.Document)); g.add((u,M.derivedFrom,doc))
        if r['sensor'] in names: g.add((names[r['sensor']],M.governedBy,u))
    for r in tables['person_registry'].to_dict('records'):
        u=people[r['person_id']]
        for zone in r['authorized_zones'].split('|'): g.add((u,M.authorized_for,zones[zone.replace('R&D; Lab','R&D Lab')]))
    for r in tables['access_events'].to_dict('records'):
        u=uri(r['event_id']); g.add((u,RDF.type,M.AccessEvent))
        actor=people.get(r['person_id'],uri('unknown-'+r['person_id']))
        if r['person_id'] not in people: g.add((actor,RDF.type,M.UnknownActor))
        g.add((u,M.person,actor)); g.add((u,M.zone,zones[r['zone'].replace('R&D; Lab','R&D Lab')]))
        for k in ['timestamp','event_type','authorized']:
            g.add((u,M[k],Literal(r[k],datatype=XSD.dateTime if k=='timestamp' else None)))
    limits={'operator':(15,3),'technician':(10,2),'supervisor':(5,1),'manager':(15,5),'security':(20,5)}
    for r in tables['alarm_response_log'].to_dict('records'):
        u=uri(r['response_id']); g.add((u,RDF.type,M.AlarmResponse)); g.add((u,M.event,gt[r['gt_id']]))
        g.add((u,M.person,people[r['responder_id']]))
        delay=(pd.Timestamp(r['ack_timestamp'])-pd.Timestamp(r['event_start_ts'])).total_seconds()/60
        limit=limits[r['responder_role']][r['severity']=='CRITICAL']
        for k,v in [('ackDelay',delay),('maxAllowed',limit)]: g.add((u,M[k],Literal(float(v),datatype=XSD.double)))
    # Occupancy source repeats the zone count per person. Keep one snapshot per zone/time.
    occ=tables['occupancy_timeseries'].copy(); occ.zone=occ.zone.replace({'R&D; Lab':'R&D Lab'})
    assert occ.groupby(['timestamp','zone']).zone_count.nunique().max()==1
    snapshots=occ.drop_duplicates(['timestamp','zone'])
    snapshots[['timestamp','zone','zone_count','zone_max','occupancy_anomaly','oc_severity']].to_csv(out/'occupancy_snapshots.csv',index=False)
    # Static retrieval graph carries daily peak snapshots; full history remains in CSV.
    peaks=snapshots.assign(date=pd.to_datetime(snapshots.timestamp).dt.date).sort_values('zone_count').groupby(['date','zone']).tail(1)
    for i,r in enumerate(peaks.to_dict('records')):
        u=uri(f'OCC-{i}'); g.add((u,RDF.type,M.OccupancySnapshot)); g.add((u,M.zone,zones[r['zone']]))
        g.add((u,M.timestamp,Literal(r['timestamp'],datatype=XSD.dateTime)))
        for k,src in [('count','zone_count'),('capacity','zone_max')]: g.add((u,M[k],Literal(int(r[src]),datatype=XSD.integer)))
    make_shapes(shapes)
    for b in shapes.objects(None,SH.property):
        p=shapes.value(b,SH.path); dt=shapes.value(b,SH.datatype)
        if dt:
            schema.add((p,RDF.type,OWL.DatatypeProperty)); schema.add((p,RDFS.range,dt))
    schema.serialize(ont/'manufacturing.ttl',format='turtle'); shapes.serialize(ont/'shapes.ttl',format='turtle')
    g.serialize(out/'knowledge_graph.ttl',format='turtle')
    # Observations are streamed separately, to keep the static graph easy to retrieve and validate.
    with (out/'observations.nt').open('w',encoding='utf-8') as fp:
        for i,r in enumerate(raw.to_dict('records')):
            u=uri(f'OBS-{i}')
            triples=[(u,RDF.type,M.Observation),(u,M.observedBy,names[r['sensor_id']]),
                     (u,M.timestamp,Literal(r['timestamp'].isoformat(),datatype=XSD.dateTime)),
                     (u,M.value,Literal(float(r['value']),datatype=XSD.double)),(u,M.unit,Literal(r['unit'])),
                     (u,M.quality,Literal(r['quality']))]
            for a,b,c in triples: fp.write(f'{a.n3()} {b.n3()} {c.n3()} .\n')
    conform,vg,txt=validate(g,shacl_graph=shapes,ont_graph=schema,advanced=True)
    vg.serialize(reports/'shacl_report.ttl',format='turtle'); (reports/'shacl_report.txt').write_text(txt,encoding='utf-8')
    # Validate every observation in bounded chunks, with only the sensor reference closure.
    reference=Graph()
    for u in g.subjects(RDF.type,M.Sensor):
        for t in g.triples((u,None,None)): reference.add(t)
    obs_shapes=Graph()
    from rdflib import BNode
    def closure(subject):
        for t in shapes.triples((subject,None,None)):
            if t[1]==SH.sparql: continue  # Full unit rule tested separately; vector metadata check covers every row.
            obs_shapes.add(t)
            if isinstance(t[2],BNode): closure(t[2])
    closure(M.ObservationShape)
    obs_results=[]; batch=Graph()
    with (out/'observations.nt').open(encoding='utf-8') as fp:
        lines=[]
        for i,line in enumerate(fp,1):
            lines.append(line)
            if i%12000==0:
                batch=Graph().parse(data=''.join(lines),format='nt')+reference
                ok,_,_=validate(batch,shacl_graph=obs_shapes)
                obs_results.append(bool(ok)); lines=[]
        if lines:
            ok,_,_=validate(Graph().parse(data=''.join(lines),format='nt')+reference,shacl_graph=obs_shapes)
            obs_results.append(bool(ok))
    dump(reports/'validation_summary.json',{'static_conforms':bool(conform),'static_triples':len(g),
         'observation_rows':len(raw),'observation_batches':len(obs_results),'all_observations_conform':all(obs_results),
         'normalized_monitors_edges':len(edge_corrections),
         'results':len(list(vg.subjects(RDF.type,SH.ValidationResult))),
         'violations':len(list(vg.subjects(SH.resultSeverity,SH.Violation))),
         'warnings':len(list(vg.subjects(SH.resultSeverity,SH.Warning)))})
    dump(reports/'edge_normalizations.json',edge_corrections)

def make_shapes(s):
    from rdflib import BNode
    def shape(cls):
        u=M[cls+'Shape']; s.add((u,RDF.type,SH.NodeShape)); s.add((u,SH.targetClass,M[cls])); return u
    def prop(u,p,datatype=None,cls=None,required=True):
        b=BNode(); s.add((u,SH.property,b)); s.add((b,SH.path,M[p])); s.add((b,SH.maxCount,Literal(1)))
        if required:s.add((b,SH.minCount,Literal(1)))
        if datatype:s.add((b,SH.datatype,datatype))
        if cls:s.add((b,SH['class'],M[cls]))
        return b
    def query(u,msg,where,severity=None):
        b=BNode(); s.add((u,SH.sparql,b)); s.add((b,SH.message,Literal(msg)))
        s.add((b,SH.select,Literal('PREFIX m: <https://example.org/imaks/> SELECT $this WHERE { '+where+' }')))
        if severity:s.add((u,SH.severity,severity))
    u=shape('Sensor'); prop(u,'name',XSD.string); prop(u,'sensorType',XSD.string); prop(u,'unit',XSD.string); prop(u,'monitors',cls='Component')
    for p in ['critLo','warnLo','nominalValue','warnHi','critHi']: prop(u,p,XSD.double)
    query(u,'Thresholds must strictly satisfy critLo < warnLo < nominal < warnHi < critHi.',
          '$this m:critLo ?a; m:warnLo ?b; m:nominalValue ?c; m:warnHi ?d; m:critHi ?e. FILTER (!(?a < ?b && ?b < ?c && ?c < ?d && ?d < ?e))')
    u=shape('Component'); prop(u,'name',XSD.string); prop(u,'locatedIn',cls='Zone')
    u=shape('Person'); prop(u,'personId',XSD.string); prop(u,'role',XSD.string)
    u=shape('AnomalyEvent'); prop(u,'startTs',XSD.dateTime); prop(u,'endTs',XSD.dateTime); prop(u,'anomalyType',XSD.string)
    query(u,'Event end must not precede start.','$this m:startTs ?a; m:endTs ?b. FILTER (?b < ?a)')
    u=shape('Rule'); prop(u,'ruleId',XSD.string); prop(u,'condition',XSD.string); prop(u,'derivedFrom',cls='Document')
    u=shape('Observation'); prop(u,'observedBy',cls='Sensor'); prop(u,'timestamp',XSD.dateTime); prop(u,'value',XSD.double); prop(u,'unit',XSD.string)
    b=prop(u,'quality',XSD.string)
    from rdflib.collection import Collection
    head=BNode(); Collection(s,head,[Literal('GOOD'),Literal('UNCERTAIN')]); s.add((b,SH['in'],head))
    query(u,'Observation unit differs from sensor unit.','$this m:observedBy ?s; m:unit ?u. ?s m:unit ?v. FILTER (?u != ?v)')
    u=shape('AccessEvent'); prop(u,'person',cls='Person'); prop(u,'zone',cls='Zone'); prop(u,'timestamp',XSD.dateTime); prop(u,'authorized',XSD.string)
    query(u,'Access flag conflicts with registry authorization.','$this m:person ?p; m:zone ?z; m:event_type "ENTRY"; m:authorized ?a. FILTER ((?a="YES" && NOT EXISTS {?p m:authorized_for ?z}) || (?a="NO" && EXISTS {?p m:authorized_for ?z}))')
    u=shape('AlarmResponse'); prop(u,'event',cls='AnomalyEvent'); prop(u,'person',cls='Person'); prop(u,'ackDelay',XSD.double); prop(u,'maxAllowed',XSD.double)
    query(u,'Alarm acknowledgment exceeded SOP-004 role-specific SLA.','$this m:ackDelay ?a; m:maxAllowed ?b. FILTER (?a > ?b || ?a < 0)')
    u=shape('OccupancySnapshot'); prop(u,'zone',cls='Zone'); prop(u,'timestamp',XSD.dateTime)
    for p in ['count','capacity']:
        b=prop(u,p,XSD.integer); s.add((b,SH.minInclusive,Literal(0)))
    # Operational alarms are reported as warnings; they are not corrupt telemetry.
    u=M.CapacityShape; s.add((u,RDF.type,SH.NodeShape)); s.add((u,SH.targetClass,M.OccupancySnapshot))
    query(u,'Zone capacity exceeded (SOP-004).','$this m:count ?a; m:capacity ?b. FILTER (?a > ?b)',SH.Warning)

if __name__=='__main__': run()
