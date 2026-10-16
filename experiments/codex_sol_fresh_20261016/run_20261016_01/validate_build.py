import pathlib,json,hashlib,csv,re,sys,collections,importlib.metadata
O=pathlib.Path(__file__).resolve().parent;I=O.parent/'input';sys.path.insert(0,str(O/'vendor'))
from rdflib import Graph,Namespace,Literal,RDF,RDFS,OWL,XSD,URIRef
from pyshacl import validate
import jsonschema
def h(b):return hashlib.sha256(b).hexdigest()
def read(n,base=O):return json.loads((base/n).read_text(encoding='utf-8'))
def jl(n,base=O):return [json.loads(x) for x in (base/n).read_text(encoding='utf-8').splitlines()]
def save(n,v):
    with (O/n).open('x',encoding='utf-8',newline='\n') as f:f.write(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def lines(n,vs):
    with (O/n).open('x',encoding='utf-8',newline='\n') as f:
        for v in vs:f.write(json.dumps(v,ensure_ascii=False)+'\n')
def norm(s):return re.sub(r'\s+',' ',s).strip()
F=read('freeze.json');errors=[]
for n,s in F['inputs'].items():assert h((I/n).read_bytes())==s,('input changed',n)
for n,s in F['artifacts'].items():assert h((O/n).read_bytes())==s,('frozen artifact changed',n)
assert (O/'freeze.sha256').read_text().split()[0]==h((O/'freeze.json').read_bytes())
P=jl('pages.jsonl',I);C=jl('chunks.jsonl',I);T=jl('tables.jsonl',I)
PM={(x['doc_id'],x['page']):x for x in P};CM={x['chunk_id']:x for x in C};TM={x['table_id']:x for x in T}
manifest=list(csv.DictReader((I/'doc_manifest.csv').read_text(encoding='utf-8').splitlines()));DM={x['doc_id']:x for x in manifest}
input_checks=[]
for p in P:
    ok=len(p['text_normalized'])==p['char_count'] and len(p['text_raw'])==p['char_count_raw'];input_checks.append(dict(kind='page_counts',document=p['doc_id'],page=p['page'],passed=ok))
for c in C:
    ok=h(c['text'].encode())==c['text_sha256'] and c['source_file_sha256']==DM[c['doc_id']]['file_sha256']
    slice_=PM[c['doc_id'],c['page']]['text_normalized'][c['char_start']:c['char_end']]
    input_checks.append(dict(kind='chunk_hash_manifest',chunk=c['chunk_id'],passed=ok))
    input_checks.append(dict(kind='chunk_page_span_whitespace_normalized',chunk=c['chunk_id'],passed=norm(slice_)==norm(c['text']),note='Table layout may differ between flattened page and normalized table/chunk; cell validation used for table evidence.'))
for doc,m in DM.items():
    assert sorted(p['page'] for p in P if p['doc_id']==doc)==list(range(1,int(m['pages'])+1)),doc
def evcheck(e):
    assert e['document_id'] in DM
    assert (e['document_id'],e['page']) in PM
    assert e['chunk_id'] in CM
    c=CM[e['chunk_id']];assert c['doc_id']==e['document_id'] and c['page']==e['page']
    assert h(e['quote'].encode())==e['text_sha256']
    if e['table_id']:
        t=TM[e['table_id']];assert c['table_id']==e['table_id'];r=e['row_index']-1;col=e['col_index']-1
        cell=next(x for x in t['cells'] if x['row']==r and x['col']==col)
        assert cell['text_normalized']==e['quote']==t['rows_normalized'][r][col]
        assert cell['bbox']==e['bbox'];assert len(e['bbox'])==4
        assert t['bbox'][0]<=e['bbox'][0]<=e['bbox'][2]<=t['bbox'][2]+0.01
        assert t['bbox'][1]<=e['bbox'][1]<=e['bbox'][3]<=t['bbox'][3]+0.01
    else:
        assert 0<=e['char_start']<e['char_end']<=len(PM[e['document_id'],e['page']]['text_normalized'])
        assert PM[e['document_id'],e['page']]['text_normalized'][e['char_start']:e['char_end']]==e['quote']
        assert c['char_start']<=e['char_start'] and e['char_end']<=c['char_end']
        assert norm(e['quote']) in norm(c['text'])
    return True
E=jl('entities.raw.jsonl');ER={e['identifier']:e for e in E};rels=jl('relations.raw.jsonl');R=jl('predictions.raw.jsonl');schema=read('output_schema.json')
decisions=[];valid=[]
for r in R:
    errs=[]
    try:
        jsonschema.validate(r,schema)
        assert len([x for x in R if x['identifier']==r['identifier']])==1
        assert r['document_id'] in DM
        for e in r['evidence']:evcheck(e)
        for s in r['sensors']:assert s in ER and ER[s]['type']=='Sensor'
        for s in r['action_targets']:assert s in ER and ER[s]['type']=='Station'
        # English source fragments; synthesized table key=value strings are checked below by source cells.
        if r['identifier'].startswith('RULE-') or r['document_id'].startswith('DS'):
            quote=norm(r['evidence'][0]['quote'])
            for field in ['condition','action']:
                v=r[field]
                if v:
                    fragments=v.split('; ') if r['identifier'] in ['RULE-ST03-02','RULE-WRH01-01','RULE-CHM01-01','RULE-CHM01-02','RULE-CHM01-03','RULE-RND01-02'] else [v]
                    for frag in fragments:assert norm(frag) in quote,('unsupported text',field,frag)
            for cl in r.get('clauses',[]):
                for v in cl.values():
                    if v:assert norm(v) in quote
    except Exception as ex:errs.append(str(ex))
    decisions.append(dict(identifier=r['identifier'],passed=not errs,checks=['schema','quote and coordinates','evidence SHA-256','unique identifier','sensor/target referential integrity','source fragment check where prose'],errors=errs,semantic_approval=False))
    if not errs:valid.append(r)
for e in E:
    for evidence in e['evidence']:evcheck(evidence)
for rel in rels:
    assert rel['subject'] in ER and rel['object'] in ER
    for evidence in rel['evidence']:evcheck(evidence)
for rel in jl('relations.deferred.jsonl'):
    for evidence in rel['evidence']:evcheck(evidence)
lines('validation.decisions.jsonl',decisions);lines('predictions.validated.jsonl',valid)
save('input_integrity_checks.json',input_checks)
# AI review is explicit source-based analysis, separate from the original predictions.
review=[dict(identifier=r['identifier'],reviewer='source-based AI review in this Codex conversation',human_approval=False,decision='retain_with_limitations' if r.get('clauses') or r['action'] is None or r['document_id'].startswith('DS') else 'retain',notes=r['notes'],changes_to_original=False) for r in valid]
lines('ai_review.jsonl',review)
issues=[
dict(id='ISSUE-01',kind='source_conflict',detail='SOP-001 RULE-CHM01-03 lists hazmat-trained technician/supervisor/manager roles; SOP-004 role-zone matrix also marks security YES. Preserve both, do not resolve authorization policy.',evidence=[next(r for r in R if r['identifier']=='RULE-CHM01-03')['evidence'][0],*[e for r in R if r['identifier']=='SOP-004-p1-AUTH-security' for e in r['evidence']]]),
dict(id='ISSUE-02',kind='cross_document_limit',detail='Thermal datasheet continuous rating 200°C versus ST02 critical high 210°C. Actual installed model unknown; this is a compatibility review candidate, not a proved equipment violation.',evidence=[next(r for r in R if r['identifier']=='DS-THERM-2200-p1-SUSTAINED')['evidence'][0],next(r for r in R if r['identifier']=='THR-ST02_SEALING_TMP')['evidence'][6]]),
dict(id='ISSUE-03',kind='cross_document_limit',detail='Current datasheet recommends corrective-action alarm threshold no higher than 14 A; ST02 current critical high is 15 A. Actual installed sensor unknown; retain source values without automatic correction.',evidence=[next(r for r in R if r['identifier']=='DS-ELEC-3300-p1-ALARM')['evidence'][0],next(r for r in R if r['identifier']=='THR-ST02_SEALING_CUR')['evidence'][6]]),
dict(id='ISSUE-04',kind='scope_limit',detail='SOP-002 anomaly definitions are schema/detection rules, not observed AnomalyEvents. No timeseries/event/likelihood data loaded.',evidence=row if False else next(r for r in R if r['identifier']=='ANOMALY-CORRELATED')['evidence']),
dict(id='ISSUE-05',kind='representation_limit',detail='Compound identifier records require clauses and full evidence to interpret paired responses; top-level compound condition/action alone is insufficient for executable rules.',evidence=next(r for r in R if r['identifier']=='RULE-ST03-02')['evidence'][:1])]
for issue in issues:
    for e in issue['evidence']:evcheck(e)
save('review_issues.json',issues)
# KG source validated subset only. No unsupported data sheet product-as-Station conversion.
IM=Namespace('https://example.org/imaks/v1#');N=Namespace('https://example.org/imaks/experiment/codex-sol-fresh-20261016/')
g=Graph();g.bind('im',IM);g.bind('ex',N)
ont=Graph().parse(I/'ontology.ttl',format='turtle');sh=Graph().parse(I/'shapes.ttl',format='turtle')
allowed=set(ont.subjects(RDF.type,OWL.ObjectProperty))|set(ont.subjects(RDF.type,OWL.DatatypeProperty))
links=[];prov_count=0
def lit(s,p,v,dt=None):g.add((s,IM[p],Literal(v,datatype=dt)))
def provenance(node,e):
    global prov_count
    prov_count+=1;p=N['provenance/'+str(prov_count)]
    g.add((p,RDF.type,IM.Provenance));g.add((node,IM.hasProvenance,p))
    for k,v in [('sourceKind','document'),('page',e['page']),('sourceQuote',e['quote']),('textSha256',e['text_sha256'])]:lit(p,k,v,XSD.positiveInteger if k=='page' else XSD.string)
    if e['table_id']:
        for k,v in [('tableId',e['table_id']),('rowIndex',e['row_index']),('colIndex',e['col_index']),('bbox',','.join(map(str,e['bbox'])))]:lit(p,k,v,XSD.positiveInteger if k in ['rowIndex','colIndex'] else XSD.string)
    else:
        for k in ['charStart','charEnd']:lit(p,k,e['char_start' if k=='charStart' else 'char_end'],XSD.nonNegativeInteger)
    links.append(dict(provenance=str(p),document_id=e['document_id'],chunk_id=e['chunk_id'],evidence=e))
for doc,m in DM.items():
    n=N['document/'+doc];g.add((n,RDF.type,IM.Document));lit(n,'identifier',doc,XSD.string);lit(n,'sourcePath',m['file'],XSD.string);lit(n,'sourceSha256',m['file_sha256'],XSD.string);lit(n,'pageCount',int(m['pages']),XSD.positiveInteger)
    lit(n,'title',PM[doc,1]['text_normalized'].split('\nDocument:')[0],XSD.string)
for e in E:
    n=N['entity/'+e['identifier']];g.add((n,RDF.type,IM[e['type']]));lit(n,'identifier',e['identifier'],XSD.string)
    for k in ['stationType','zone','sensorType','unit']:
        if k in e:lit(n,k,e[k],XSD.string)
    for evidence in e['evidence']:provenance(n,evidence)
for rel in rels:g.add((N['entity/'+rel['subject']],IM[rel['predicate']],N['entity/'+rel['object']]))
kg_relations=[]
for r in valid:
    n=N['rule/'+r['identifier']];g.add((n,RDF.type,IM[r['class']]));g.add((n,RDF.type,IM.Rule));lit(n,'identifier',r['identifier'],XSD.string)
    for key,p in [('condition','conditionText'),('action','responseText'),('priority','priority'),('extraction_method','extractionMethod')]:
        if r.get(key) is not None:lit(n,p,r[key],XSD.string)
    for k,v in r.get('thresholds',{}).items():lit(n,k,str(v),XSD.decimal)
    g.add((n,IM.sourceDocument,N['document/'+r['document_id']]))
    for s in r['sensors']:g.add((n,IM.appliesToSensor,N['entity/'+s]))
    for s in r['action_targets']:g.add((n,IM.actionTarget,N['entity/'+s]))
    for e in r['evidence']:provenance(n,e)
    kg_relations.append(dict(rule=r['identifier'],sourceDocument=r['document_id'],appliesToSensor=r['sensors'],actionTarget=r['action_targets'],unmapped_equipment=[s for s in r['equipment'] if s not in ER]))
assert all(p in allowed or p==RDF.type for _,p,_ in g)
assert not list(g.subjects(RDF.type,IM.AnomalyEvent));assert not list(g.triples((None,IM.causallyAffects,None)))
conforms,report_graph,report_text=validate(g,shacl_graph=sh,ont_graph=ont,inference='none',advanced=True,abort_on_first=False,allow_infos=False,allow_warnings=False)
# Serialize once; reparse confirms syntactic validity.
g.serialize(O/'kg.candidate.ttl',format='turtle');Graph().parse(O/'kg.candidate.ttl',format='turtle')
report_graph.serialize(O/'shacl.report.ttl',format='turtle')
(O/'shacl.report.txt').write_text(report_text,encoding='utf-8')
lines('provenance.index.jsonl',links);lines('kg.rule_links.jsonl',kg_relations)
counts={doc:dict(pages=int(m['pages']),chunks=sum(x['doc_id']==doc for x in C),tables=sum(x['doc_id']==doc for x in T),raw=sum(r['document_id']==doc for r in R),validated=sum(r['document_id']==doc for r in valid),rejected=sum(d['identifier'] in [r['identifier'] for r in R if r['document_id']==doc] and not d['passed'] for d in decisions)) for doc,m in DM.items()}
stats=dict(documents=len(DM),pages=len(P),chunks=len(C),tables=len(T),raw_rules=len(R),validated_rules=len(valid),rejected_rules=len(R)-len(valid),class_counts=dict(collections.Counter(r['class'] for r in R)),documents_detail=counts,freeze_hash_verified=True,input_checks_passed=sum(x['passed'] for x in input_checks),input_checks_failed=[x for x in input_checks if not x['passed']],evidence_occurrences=sum(len(r['evidence']) for r in R),entities=len(E),stations=sum(e['type']=='Station' for e in E),sensors=sum(e['type']=='Sensor' for e in E),kg_triples=len(g),provenance_nodes=prov_count,shacl_conforms=bool(conforms),shacl_inference='none',shacl_result_count=len(list(report_graph.subjects(RDF.type,URIRef('http://www.w3.org/ns/shacl#ValidationResult')))),out_of_ontology_predicates_in_kg=0,source_validation_is_not_semantic_accuracy=True,evaluation='고정 후 별도 평가 대기',pdf_binary_hash_recomputation='not performed: PDFs outside allowlist',versions={n:importlib.metadata.version(n) for n in ['rdflib','pyshacl','jsonschema']})
save('validation_summary.json',stats)
print(json.dumps(stats,ensure_ascii=False,indent=2))
