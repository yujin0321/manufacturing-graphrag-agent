"""Conversation-authored extraction plan, deterministic rendering; no model API."""
import pathlib,json,hashlib,re,csv,sys
O=pathlib.Path(__file__).resolve().parent
I=O.parent/'input'
def h(b): return hashlib.sha256(b).hexdigest()
def load(n): return [json.loads(x) for x in (I/n).read_text(encoding='utf-8').splitlines()]
P=load('pages.jsonl'); C=load('chunks.jsonl'); T=load('tables.jsonl')
PM={(x['doc_id'],x['page']):x for x in P}; CM={x['chunk_id']:x for x in C}; TM={x['table_id']:x for x in T}
def save(n,v):
    with (O/n).open('x',encoding='utf-8',newline='\n') as f: f.write(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def jl(n,rs):
    with (O/n).open('x',encoding='utf-8',newline='\n') as f:
        for r in rs: f.write(json.dumps(r,ensure_ascii=False)+'\n')
def ce(c):
    q=PM[c['doc_id'],c['page']]['text_normalized'][c['char_start']:c['char_end']]
    return dict(document_id=c['doc_id'],page=c['page'],chunk_id=c['chunk_id'],table_id=None,row_index=None,col_index=None,bbox=None,char_start=c['char_start'],char_end=c['char_end'],quote=q,text_sha256=h(q.encode()),representation='page.text_normalized')
def te(t,r,col):
    cell=next(c for c in t['cells'] if c['row']==r and c['col']==col); q=cell['text_normalized']
    return dict(document_id=t['doc_id'],page=t['page'],chunk_id=t['table_id']+':chunk',table_id=t['table_id'],row_index=r+1,col_index=col+1,bbox=cell['bbox'],char_start=None,char_end=None,quote=q,text_sha256=h(q.encode()),representation='table.cell.text_normalized')
def rowev(t,r): return [te(t,r,j) for j in range(len(t['rows_normalized'][r]))]
R=[]; entities=[]; relations=[]; outside=[]
def add(doc,cl,ident,cond,action,ev,sensors=(),eq=(),targets=(),notes=(),**extra):
    x=dict(document_id=doc,**{'class':cl},identifier=ident,condition=cond,action=action,sensors=list(sensors),equipment=list(eq),action_targets=list(targets),evidence=ev,notes=list(notes),extraction_method='Codex conversation AI source interpretation + deterministic serialization')
    x.update(extra);R.append(x);return x
ST=TM['SOP-001:p1:table1']
stations=[r[0] for r in ST['rows_normalized'][1:]]
short={s.split('_')[0]:s for s in stations}
units={}; sensor_evidence={}
# Source station inventory, no seed files.
for i,row in enumerate(ST['rows_normalized'][1:],1):
    entities.append(dict(identifier=row[0],type='Station',stationType=row[0].split('_',1)[1],zone=row[1],evidence=rowev(ST,i)))
# Table/station correspondence comes from headings and explicit continuation metadata.
table_station={f'SOP-002:p1:table{i}':stations[i-1] for i in range(1,6)}
table_station.update({'SOP-002:p2:table1':short['SRV01'],**{f'SOP-002:p2:table{i}':stations[i+3] for i in range(2,6)}})
for tid,station in table_station.items():
    t=TM[tid]
    for i,row in enumerate(t['rows_normalized']):
        if row[0]=='Sensor':continue
        sid=station+'_'+row[0];units[sid]=row[1];sensor_evidence[sid]=rowev(t,i)
        entities.append(dict(identifier=sid,type='Sensor',sensorType=row[0],unit=row[1],station=station,evidence=rowev(t,i),resolution='station heading; continued_from for page 2 table 1'))
        relations.append(dict(subject=station,predicate='hasSensor',object=sid,evidence=rowev(t,i),resolution='sensor row under explicit station heading; continuation resolved'))
# AI-authored spans for numbered prose. null conditions preserve unconditional mandates.
spec={
'RULE-ST01-01':(None,'FLW MUST be maintained between 112 and 128 L/min.'),
'RULE-ST01-02':('If TMP exceeds 26°C','reduce speed by 10% and notify QC.'),
'RULE-ST01-03':('PRS drop below 3.3 bar','inspect inlet valve within 5 min.'),
'RULE-ST02-01':(None,'TMP MUST remain between 175°C and 195°C.'),
'RULE-ST02-02':('TMP > 210°C (CRITICAL)','emergency stop ST02, ST03, ST04.'),
'RULE-ST02-03':('CUR increase >1.5 A above nominal sustained >5 min','schedule maintenance.'),
'RULE-ST02-04':('ST02_SEALING-CUR triggers a WARNING.','Monitor ST04_PACKAGING-SPD'),
'RULE-ST03-01':(None,'TEN MUST be between 1.8 and 2.6 N.'),
'RULE-ST03-02':('CNT below 110 pcs/min; Below 100 (CRITICAL)','check for label jam.; halt.'),
'RULE-ST03-03':('TEN STUCK >10 consecutive samples',None),
'RULE-ST04-01':('VIB > 0.20 mm/s (WARNING)','schedule maintenance within 24 h.'),
'RULE-ST04-02':('VIB > 0.35 mm/s (CRITICAL)','emergency stop; inspect bearings.'),
'RULE-ST04-03':('SPD drops below 1.00 m/s without operator command','verify RULE-ST02-04.'),
'RULE-SRV01-01':(None,'TMP MUST NOT exceed 25°C.'),
'RULE-SRV01-02':('TMP > 28°C (CRITICAL)','automatic controlled shutdown of all PLC nodes.'),
'RULE-WRH01-01':('CRITICAL above 12°C','TMP MUST remain between 0.5°C and 8°C.; notify QC and quarantine batch.'),
'RULE-WRH01-02':('HUM above 85%RH','inspect door seals and activate dehumidifier.'),
'RULE-CHM01-01':('CRITICAL above 25°C','TMP MUST remain between 10°C and 20°C.; activate emergency ventilation and notify safety officer immediately.'),
'RULE-CHM01-02':('HUM >45%RH.','HUM MUST NOT exceed 50%RH.; Activate desiccant system'),
'RULE-CHM01-03':('UNAUTHORIZED_ACCESS','Only personnel with hazmat training (technician/supervisor/manager role) are authorised to enter Chemical Storage.; UNAUTHORIZED_ACCESS must be escalated within 2 minutes.'),
'RULE-RND01-01':(None,'TMP MUST remain between 18°C and 26°C for experimental validity.'),
'RULE-RND01-02':('HUM drift above 65%RH; Above 75%RH (CRITICAL)','activate dehumidifier.; suspend sensitive experiments and inspect HVAC system.'),
'RULE-CAF01-01':('TMP above 26°C','check ventilation system.'),
'RULE-CAF01-02':('HUM above 70%RH','inspect drainage and activate ventilation.'),
'RULE-ACCESS-01':('Any entry by an unauthorised role','MUST be logged as OccupancyEvent::UnauthorisedAccess with person_id, zone, and timestamp.'),
'RULE-ACCESS-02':('detection','Security personnel MUST be notified within 2 minutes of detection.'),
'RULE-ACCESS-03':(None,'The KG node MUST include authorized=NO and a reference to this rule.'),
'RULE-ACCESS-04':('Any UNAUTHORIZED_ACCESS','immediate escalation to the Safety Officer regardless of role.')}
# Keep branch associations explicitly; full original quote remains authoritative.
branches={
'RULE-ST03-02':[('CNT below 110 pcs/min','check for label jam.'),('Below 100 (CRITICAL)','halt.')],
'RULE-WRH01-01':[(None,'TMP MUST remain between 0.5°C and 8°C.'),('CRITICAL above 12°C','notify QC and quarantine batch.')],
'RULE-CHM01-01':[(None,'TMP MUST remain between 10°C and 20°C.'),('CRITICAL above 25°C','activate emergency ventilation and notify safety officer immediately.')],
'RULE-CHM01-02':[(None,'HUM MUST NOT exceed 50%RH.'),('HUM >45%RH.','Activate desiccant system')],
'RULE-CHM01-03':[(None,'Only personnel with hazmat training (technician/supervisor/manager role) are authorised to enter Chemical Storage.'),('UNAUTHORIZED_ACCESS','must be escalated within 2 minutes.')],
'RULE-RND01-02':[('HUM drift above 65%RH','activate dehumidifier.'),('Above 75%RH (CRITICAL)','suspend sensitive experiments and inspect HVAC system.')]}
for doc in ['SOP-001','SOP-002','SOP-003','SOP-004','DS-ELEC-3300','DS-MECH-4400','DS-THERM-2200']:
    for c in [x for x in C if x['doc_id']==doc and x['kind']=='rule']:
        ident=c['rule_id']; body=c['text'].split(': ',1)[1];cond,act=spec[ident];eq=[];sens=[];targets=[];ev=[ce(c)]
        if doc=='SOP-001':
            st=short[ident.split('-')[1]];eq=[st]
            ev+=rowev(ST,stations.index(st)+1)
            for typ in ['TMP','PRS','FLW','CUR','SPD','TEN','CNT','VIB','HUM']:
                if re.search(r'\b'+typ+r'\b',body) and st+'_'+typ in units:sens.append(st+'_'+typ)
            if ident=='RULE-ST02-04':sens=[short['ST02']+'_CUR',short['ST04']+'_SPD'];eq.append(short['ST04'])
            if ident=='RULE-ST02-02':targets=[short[x] for x in ['ST02','ST03','ST04']]
            elif act and (act.startswith(('inspect','check','activate','emergency','schedule','reduce','TMP MUST','TEN MUST','FLW MUST','HUM MUST','suspend'))): targets=[st]
        cl='AccessRule' if doc=='SOP-004' or ident=='RULE-CHM01-03' else 'OperationalRule'
        x=add(doc,cl,ident,cond,act,ev,sens,eq,targets,notes=['Composite identifier retained; clauses preserve condition/action pairing.'] if ident in branches else [])
        if ident in branches:x['clauses']=[dict(condition=a,action=b) for a,b in branches[ident]]
        if ident=='RULE-ST03-03':x['notes'].append('Diagnostic conclusion: sensor failure. No physical intervention specified.')
        for s in sens:x['evidence']+=sensor_evidence[s][:2]
    for t in [x for x in T if x['doc_id']==doc]:
        tid=t['table_id'];rows=t['rows_normalized']
        if tid in table_station:
            st=table_station[tid]
            for i,row in enumerate(rows):
                if row[0]=='Sensor':continue
                sid=st+'_'+row[0]; header=TM[t['continued_from']]['rows_normalized'][0] if t['continued_from'] else rows[0]
                ev=rowev(t,i)+rowev(TM[t['continued_from']],0) if t['continued_from'] else rowev(t,i)+rowev(t,0)
                # The heading chunk is the nearest preceding text chunk (previous page for continued table).
                ht=TM[t['continued_from']] if t['continued_from'] else t
                preceding=[c for c in C if c['doc_id']==doc and c['page']==ht['page'] and c['kind']=='text' and c['char_start']<CM[ht['table_id']+':chunk']['char_start']]
                if preceding:ev.append(ce(preceding[-1]))
                cond='; '.join(header[j]+'='+row[j] for j in range(2,7))
                targets=[short[x] for x in ['ST02','ST03','ST04']] if 'E-STOP ST02/ST03/ST04' in row[7] else ([st] if 'E-STOP' in row[7] else [])
                add(doc,'ThresholdRule','THR-'+sid,cond,row[7],ev,[sid],[st],targets,notes=['CRITICAL Response column applies to critical state; threshold equality comparator not specified. Nominal tolerance preserved in condition.'],thresholds=dict(zip(['critLo','warnLo','nominal','warnHi','critHi'],[float(row[j].split(' ±')[0]) for j in range(2,7)])),response_scope='CRITICAL')
        elif tid=='SOP-002:p2:table6':
            for i,row in enumerate(rows[1:],1):add(doc,'ThresholdRule','ANOMALY-'+row[0],row[1]+'; '+row[2],None,rowev(t,i)+rowev(t,0),notes=['Definition/detection criterion; no response stated. Ontology class mapping: '+row[3]])
        elif tid=='SOP-003:p1:table1':
            for i,row in enumerate(rows[1:],1):add(doc,'MaintenanceRule',row[0],row[3],row[4],rowev(t,i)+rowev(t,0),[row[2]+'_'+row[1]],[row[2]],[row[2]],priority=row[5])
        elif tid=='SOP-003:p1:table2':
            links=[([short['ST02']+'_CUR',short['ST04']+'_SPD'],[short['ST02'],short['ST04']]),([short['SRV01']+'_TMP'],[short['SRV01']]),([short['WRH01']+'_TMP'],[short['WRH01']])]
            for i,row in enumerate(rows[1:],1):add(doc,'MaintenanceRule',f'SOP-003-p1-RESOLUTION-{i}',row[0],row[3],rowev(t,i)+rowev(t,0),*links[i-1],targets=links[i-1][1],notes=['Primary fault: '+row[1], 'Secondary effect: '+row[2]])
        elif tid=='SOP-004:p1:table1':
            for i,row in enumerate(rows[1:],1):add(doc,'AccessRule',f'SOP-004-p1-AUTH-{row[0]}',rows[0][0]+'='+row[0],'; '.join(rows[0][j]+'='+row[j] for j in range(1,len(row))),rowev(t,i)+rowev(t,0),notes=['Role-zone matrix row retained as one compound authorization rule; no Person/Zone class instantiated.'])
        elif tid=='SOP-004:p1:table2':
            for i,row in enumerate(rows[1:],1):add(doc,'AccessRule',f'SOP-004-p1-OCCUPANCY-{i}',row[0],rows[0][1]+'='+row[1]+'; '+row[2],rowev(t,i)+rowev(t,0),notes=['Maximum occupancy and enforcement retained; no unstated response inferred.'])
        elif tid=='SOP-004:p1:table3':
            for i,row in enumerate(rows[1:],1):add(doc,'AccessRule',f'SOP-004-p1-ACK-{row[0]}','Role='+row[0],'; '.join(rows[0][j]+'='+row[j] for j in [1,2]),rowev(t,i)+rowev(t,0),notes=['Role-specific WARNING/CRITICAL acknowledgement limits, not causal claims.'])
    if doc.startswith('DS'):
        c=CM[doc+':p1:text2'];txt=c['text'];ev=[ce(c)]
        if doc=='DS-ELEC-3300':
            add(doc,'OperationalRule',doc+'-p1-OVERLOAD', 'Operation between\n14 A and 20 A','permissible for short durations (< 60 seconds).',ev,eq=['Series 3300'],notes=['Product family, no evidence of installation on any station.'])
            add(doc,'ThresholdRule',doc+'-p1-ALARM',None,'ElectroMeasure recommends that process alarm thresholds triggering corrective action be\nset no higher than the continuous overload rating.',ev,eq=['Series 3300'],notes=['Continuous overload rating explicitly 14 A in same note; no installed sensor assignment.'])
        elif doc=='DS-MECH-4400':
            add(doc,'ThresholdRule',doc+'-p1-ALARM',None,txt.split('\n2. Electromagnetic')[0],ev,eq=['PRS-4410'],notes=['Both 5× accuracy recommended margin and <3× not recommended retained. No installed sensor assignment.'])
        else:
            start=txt.index('applications requiring');end=txt.index('\n2. Humidity')
            add(doc,'OperationalRule',doc+'-p1-SUSTAINED','applications requiring sustained operation above 200°C','ThermoSense recommends the Series 2400 (Pt100 RTD,\nrated to 250°C continuous).',ev,eq=['TMP-2210','Series 2400'],notes=['Recommendation only; no inferred shutdown or station installation.'])
# Additional physical links: only explicit process sequence, not inferred causality.
seq=ce(CM['SOP-001:p1:text1'])
for a,b in zip(stations[:3],stations[1:4]):relations.append(dict(subject=a,predicate='feedsInto',object=b,evidence=[seq]))
outside += [dict(subject='ST02_SEALING_CUR',predicate='correlatesWith',object='ST04_PACKAGING_SPD',status='deferred_schema_load_stage',evidence=[ce(CM['SOP-001:p1:RULE-ST02-04'])],reason='Ontology limits correlatesWith to later event stage; no event data in this experiment.'),dict(subject='ST02_SEALING',predicate='causallyAffects',object='ST04_PACKAGING',status='deferred_missing_required_likelihoodScore',evidence=rowev(TM['SOP-003:p1:table2'],1),reason='Explicit fault/effect text but no numeric likelihood; never fabricate SHACL-required score.')]
outside += [dict(subject='AccessRule',predicate='authorizedForZone',object='role/zone matrix',status='outside_ontology',evidence=rowev(TM['SOP-004:p1:table1'],0),reason='No Person/Zone/authorizedForZone in supplied ontology; matrix preserved as Rule text.'),dict(subject='RULE-ACCESS-01',predicate='createsEvent',object='OccupancyEvent::UnauthorisedAccess',status='outside_ontology',evidence=[ce(CM['SOP-004:p1:RULE-ACCESS-01'])],reason='No OccupancyEvent class or createsEvent relation in supplied ontology.')]
jl('predictions.raw.jsonl',R);jl('entities.raw.jsonl',entities);jl('relations.raw.jsonl',relations);jl('relations.deferred.jsonl',outside)
save('reading_coverage.json',{doc:dict(pages=[x['page'] for x in P if x['doc_id']==doc],chunks=[x['chunk_id'] for x in C if x['doc_id']==doc],tables=[x['table_id'] for x in T if x['doc_id']==doc],read_status='all supplied page/chunk/table records processed document by document',rules=sum(r['document_id']==doc for r in R)) for doc in dict.fromkeys(x['doc_id'] for x in P)})
tracked=['extraction_policy.txt','output_schema.json','configuration.json','prompt.txt','extract.py','predictions.raw.jsonl','entities.raw.jsonl','relations.raw.jsonl','relations.deferred.jsonl','reading_coverage.json','input_inventory.json']
freeze={'format':'v1','stage':'original predictions frozen before validation/filter/review','inputs':{n:h((I/n).read_bytes()) for n in ['chunks.jsonl','pages.jsonl','tables.jsonl','doc_manifest.csv','ontology.ttl','shapes.ttl']},'artifacts':{n:h((O/n).read_bytes()) for n in tracked},'model':{'requested':'GPT-6.1 Sol','actual':'미확인','actual_model_evidence':None},'api_used':False,'evaluation':'고정 후 별도 평가 대기','prompt_scope':'prompt.txt is task execution prompt record; not a full transcript of system/developer instructions','exposure':'Input-isolated chat; project has historical gold exposure; allowed ontology/shapes disclose design references and counts. Not an independent blind test.'}
save('freeze.json',freeze)
(O/'freeze.sha256').write_text(h((O/'freeze.json').read_bytes())+'  freeze.json\n',encoding='ascii')
print(json.dumps({'raw_rules':len(R),'documents':len(set(x['document_id'] for x in R)),'freeze_sha256':h((O/'freeze.json').read_bytes())}))
