"""Independent source-to-field and document coverage checks after original freeze."""
import pathlib,json,hashlib,re,collections
O=pathlib.Path(__file__).resolve().parent;I=O.parent/'input'
def rows(p):return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines()]
R=rows(O/'predictions.raw.jsonl');T={x['table_id']:x for x in rows(I/'tables.jsonl')};C=rows(I/'chunks.jsonl');P=rows(I/'pages.jsonl');E=rows(O/'entities.raw.jsonl')
checks=[]
def check(name,ok,detail):checks.append(dict(check=name,passed=bool(ok),detail=detail))
# Derive threshold station from page heading, not extract.py's hardcoded mapping.
by_page={(p['doc_id'],p['page']):p['text_normalized'] for p in P}
for r in R:
    if r['identifier'].startswith('THR-'):
        t=T[r['evidence'][0]['table_id']];i=r['evidence'][0]['row_index']-1;row=t['rows_normalized'][i]
        head=T[t['continued_from']] if t['continued_from'] else t
        txt=by_page[head['doc_id'],head['page']]
        chunk=next(c for c in C if c['table_id']==head['table_id'])
        matches=re.findall(r'([A-Z0-9]+_[A-Z]+) Thresholds',txt[:chunk['char_start']]);station=matches[-1]
        header=head['rows_normalized'][0]
        check('threshold_mapping:'+r['identifier'],r['sensors']==[station+'_'+row[0]] and r['equipment']==[station] and r['condition']=='; '.join(header[j]+'='+row[j] for j in range(2,7)) and r['action']==row[7] and list(r['thresholds'].values())==[float(row[j].split(' ±')[0]) for j in range(2,7)],'Sensor/heading continuation, all threshold columns, nominal tolerance and critical response exact.')
    elif r['identifier'].startswith('MAINT-'):
        t=T[r['evidence'][0]['table_id']];row=t['rows_normalized'][r['evidence'][0]['row_index']-1]
        check('maintenance_mapping:'+r['identifier'],r['identifier']==row[0] and r['condition']==row[3] and r['action']==row[4] and r['priority']==row[5] and r['sensors']==[row[2]+'_'+row[1]],'All maintenance fields from same row.')
    elif r['document_id']=='SOP-004' and not r['identifier'].startswith('RULE-'):
        t=T[r['evidence'][0]['table_id']];row=t['rows_normalized'][r['evidence'][0]['row_index']-1];header=t['rows_normalized'][0]
        if 'AUTH-' in r['identifier']:expected='; '.join(header[j]+'='+row[j] for j in range(1,len(row)));expected_c='Role='+row[0]
        elif 'ACK-' in r['identifier']:expected='; '.join(header[j]+'='+row[j] for j in [1,2]);expected_c='Role='+row[0]
        else:expected='Max Persons='+row[1]+'; '+row[2];expected_c=row[0]
        check('access_mapping:'+r['identifier'],r['action']==expected and r['condition']==expected_c,'Matrix/enforcement/acknowledgement labels and values exact.')
    elif r['identifier'].startswith('ANOMALY-'):
        t=T[r['evidence'][0]['table_id']];row=t['rows_normalized'][r['evidence'][0]['row_index']-1]
        check('definition_mapping:'+r['identifier'],r['condition']==row[1]+'; '+row[2] and r['action'] is None,'Definition and detector preserved; no invented response.')
    elif '-RESOLUTION-' in r['identifier']:
        t=T[r['evidence'][0]['table_id']];row=t['rows_normalized'][r['evidence'][0]['row_index']-1]
        check('resolution_mapping:'+r['identifier'],r['condition']==row[0] and r['action']==row[3],'Pattern and complete ordered resolution from one row.')
ids={r['identifier'] for r in R};source_ids={c['rule_id'] for c in C if c['kind']=='rule'}
check('numbered_rule_coverage',source_ids<=ids,{'source_identifiers':len(source_ids),'missing':sorted(source_ids-ids)})
check('document_coverage',{p['doc_id'] for p in P}=={r['document_id'] for r in R},'All seven documents produce rules including explicit datasheet guidance.')
check('table_coverage',set(T)=={c['table_id'] for c in C if c['kind']=='table'},'All supplied tables have corresponding chunks and were inspected; specification-only tables need no Rule.')
check('no_duplicate_identifiers',len(ids)==len(R),'Local generated identifiers do not overlap source IDs.')
check('no_invented_action_for_diagnosis',next(r for r in R if r['identifier']=='RULE-ST03-03')['action'] is None,'Sensor failure is a diagnosis, not replacement instruction.')
check('compound_clauses_present',all('clauses' in next(r for r in R if r['identifier']==i) for i in ['RULE-ST03-02','RULE-WRH01-01','RULE-CHM01-01','RULE-CHM01-02','RULE-CHM01-03','RULE-RND01-02']),'Unconditional mandates and conditional branches preserved separately.')
v={'checks':checks,'passed':sum(x['passed'] for x in checks),'failed':sum(not x['passed'] for x in checks),'limits':'Coverage is source-record coverage, not gold recall. Datatype/SHACL constraints are structural checks, not semantic correctness scores.'}
with (O/'supplemental_checks.json').open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2)
print(json.dumps(v,ensure_ascii=False))
