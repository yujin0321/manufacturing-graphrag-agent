"""Gold is read only here, after pre-evaluation hash lock. Never print rule text."""
import pathlib,json,csv,hashlib,re,sys,collections,math
import numpy as np
from scipy.optimize import linear_sum_assignment
from sentence_transformers import SentenceTransformer
O=pathlib.Path(__file__).resolve().parents[3];B=O.parent;R=B/'run_20261016_01'
GOLD=pathlib.Path('C:/Users/ysh/Desktop/대학교/동아리/비타민/프로젝트/26-2/지훈코드/imaks_data/kg_seed/ground_truth.csv')
def h(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def j(p):return json.loads(p.read_text(encoding='utf-8'))
def save(n,v):
    with (O/n).open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2);f.write('\n')
def allocate(sim,threshold):
    if not sim.size:return []
    valid=sim>=threshold;constant=min(sim.shape)+1
    reward=np.where(valid,constant+sim,0.0)
    a,b=linear_sum_assignment(-reward)
    return [(int(i),int(k),float(sim[i,k])) for i,k in zip(a,b) if valid[i,k]]
def metrics(tp,p,g):
    pr=tp/p if p else 0.0;rc=tp/g if g else 0.0
    return dict(predictions=p,gold=g,TP=tp,FP=p-tp,FN=g-tp,precision=pr,recall=rc,F1_content=2*tp/(p+g) if p+g else 0.0,coverage=rc,granularity_ratio=p/g if g else None,theoretical_F1_upper_bound=2*min(p,g)/(p+g) if p+g else 0.0)
def algorithm_test():
    # Raw maximum sum would choose one valid edge; cardinality-first must choose two.
    x=np.array([[1.0,.60],[.60,.59]])
    assert {(i,k) for i,k,_ in allocate(x,.6)}=={(0,1),(1,0)}
    # Invalid similarities cannot break ties between equally valid objectives.
    x=np.array([[.9,.8],[.59,-.9]])
    assert [(i,k) for i,k,_ in allocate(x,.6)]==[(0,0)]
    assert len(allocate(np.array([[.6]]),.6))==1
    assert allocate(np.zeros((0,2)),.6)==[]
    return dict(cardinality_first=True,invalid_pair_sum_excluded=True,inclusive_threshold=True,empty_document=True)
def main():
    L=j(O/'pre_evaluation_lock.json');assert h(O/'pre_evaluation_lock.json')==(O/'pre_evaluation_lock.sha256').read_text().split()[0]
    assert h(pathlib.Path(L['prediction_file']))==L['prediction_sha256'];assert h(pathlib.Path(__file__))==L['evaluator_sha256'];assert h(O/'evaluation_policy.json')==L['policy_sha256']
    for meta in L['definition_files'].values():assert h(pathlib.Path(meta['path']))==meta['sha256']
    for n,v in L['embedding_model']['files'].items():assert h(O/'embedding_model'/n)==v
    tests=algorithm_test()
    predictions=[json.loads(x) for x in pathlib.Path(L['prediction_file']).read_text(encoding='utf-8').splitlines()]
    manifest=list(csv.DictReader((B/'input/doc_manifest.csv').read_text(encoding='utf-8').splitlines()))
    docmap={}
    for row in manifest:
        for val in [row['doc_id'],row['file'],pathlib.PurePosixPath(row['file']).name]:docmap[val.replace('\\','/').lower()]=row['doc_id']
    # First access to gold, only after lock validation and algorithm tests.
    gold_bytes=GOLD.read_bytes();gold_hash=hashlib.sha256(gold_bytes).hexdigest()
    reader=csv.DictReader(gold_bytes.decode('utf-8-sig').splitlines());gold=list(reader);headers=reader.fieldnames
    def field(aliases,required=True):
        found=[x for x in aliases if x in headers]
        if not found:
            if required:raise ValueError('Missing required gold field; columns='+str(headers)+' aliases='+str(aliases))
            return None
        return found[0]
    source=field(['source']);cond=field(['condition','Condition']);action=field(['action','Action']);cl=field(['class','ruleClass','rule_class','type']);ident=field(['identifier','ruleId','rule_id','id'],False);sensor=field(['sensors','sensor_ids','sensorIds','appliesToSensor','sensor_id','sensor'],False)
    assert len(gold)==L['evaluation_policy']['expected_gold_rows_from_definitions'],('unexpected gold row count',len(gold))
    unknown=[]
    for i,g in enumerate(gold):
        s=g[source].strip().replace('\\','/').lower();doc=docmap.get(s) or docmap.get(s.rsplit('/',1)[-1])
        if not doc:unknown.append(dict(row=i+2,source=g[source]))
        g['_document']=doc;g['_id']=g[ident] if ident else f'row-{i+2}'
    if unknown:
        save('evaluation_error.json',{'reason':'unknown gold source; stopped without guessing','rows':unknown,'gold_sha256':gold_hash,'columns':headers});raise ValueError('Unknown gold documents; stopped without guessing. See evaluation_error.json.')
    sop=[r for r in predictions if r['document_id'].startswith('SOP-')];outside=[r for r in predictions if not r['document_id'].startswith('SOP-')]
    documents=sorted({g['_document'] for g in gold}|{r['document_id'] for r in sop});processed={r['document_id'] for r in sop}
    model=SentenceTransformer(str(O/'embedding_model'),device='cpu',local_files_only=True,token=False)
    all_scores={};all_pairs=[];matrices={}
    for style in ['plain','labeled']:
        def text(c,a):
            c='' if c is None else c;a='' if a is None else a
            return c+' '+a if style=='plain' else 'Condition: '+c+'\nAction: '+a
        pt=[text(p['condition'],p['action']) for p in sop];gt=[text(g[cond],g[action]) for g in gold]
        embeds=model.encode(pt+gt,normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False,batch_size=32)
        ep=embeds[:len(pt)];eg=embeds[len(pt):]
        sim=np.asarray(ep@eg.T,dtype=np.float64)
        assert np.isfinite(sim).all();matrices[style]=sim
        runs={}
        for threshold in [.5,.6,.7]:
            pairs=[];perdoc={}
            for doc in documents:
                pi=[i for i,p in enumerate(sop) if p['document_id']==doc];gi=[i for i,g in enumerate(gold) if g['_document']==doc]
                matched=allocate(sim[np.ix_(pi,gi)],threshold)
                perdoc[doc]=metrics(len(matched),len(pi),len(gi))
                for i,k,v in matched:pairs.append((pi[i],gi[k],v))
            tp=len(pairs);main=metrics(tp,len(sop),len(gold));scope_gold=sum(g['_document'] in processed for g in gold);scope_tp=sum(gold[k]['_document'] in processed for _,k,_ in pairs)
            same=sum(sop[i]['class']==gold[k][cl] for i,k,_ in pairs)
            confusion=collections.Counter((gold[k][cl],sop[i]['class']) for i,k,_ in pairs)
            main.update(threshold=threshold,per_document=perdoc,processed_scope=metrics(scope_tp,len(sop),scope_gold),class_matched=dict(TP=same,FP=len(sop)-same,FN=len(gold)-same,precision=same/len(sop) if sop else 0,recall=same/len(gold) if gold else 0,F1=2*same/(len(sop)+len(gold)) if sop or gold else 0),class_confusion=[dict(gold_class=g,prediction_class=p,count=n) for (g,p),n in sorted(confusion.items())])
            if sensor:
                def sensor_set(v):
                    if isinstance(v,list):items=v
                    elif not v:return set()
                    else:
                        try:items=json.loads(v)
                        except (ValueError,TypeError):items=re.split(r'[,;|]',v)
                        if isinstance(items,str):items=[items]
                    return {re.sub(r'-(TMP|PRS|FLW|CUR|SPD|TEN|CNT|VIB|HUM)$',r'_\1',str(x).strip()) for x in items if str(x).strip()}
                equal=sum(sensor_set(sop[i].get('sensors',[]))==sensor_set(gold[k][sensor]) for i,k,_ in pairs)
                main['sensor_set_exact_match']=dict(equal=equal,matched_pairs=len(pairs),ratio=equal/len(pairs) if pairs else None,gold_field=sensor,normalization='split comma/semicolon/pipe or JSON array; terminal -TYPE -> _TYPE')
            else:main['sensor_set_exact_match']=dict(status='N/A',reason='No supported gold sensor column',available_columns=headers)
            runs[str(threshold)]=main
            for i,k,v in pairs:all_pairs.append(dict(style=style,threshold=threshold,document_id=sop[i]['document_id'],prediction_identifier=sop[i]['identifier'],gold_identifier=gold[k]['_id'],similarity=v,class_equal=sop[i]['class']==gold[k][cl]))
        all_scores[style]=runs
    np.savez_compressed(O/'similarity_matrices.local.npz',**matrices)
    with (O/'matches.local.jsonl').open('x',encoding='utf-8') as f:
        for pair in all_pairs:f.write(json.dumps(pair,ensure_ascii=False)+'\n')
    # Diagnose numeric disagreement only; never rewrite either prediction or gold.
    def numeric_tokens(v):return re.findall(r'[<>≤≥]?\s*[-+]?\d+(?:\.\d+)?\s*(?:°C|%RH|L/min|mm/s|pcs/min|m/s|bar|A|N|minutes?|min|hours?|h|seconds?|s)?',v)
    diagnostic=[]
    for p in all_pairs:
        if p['style']!='plain' or p['threshold']!=.6:continue
        pred=next(x for x in sop if x['identifier']==p['prediction_identifier']);g=next(x for x in gold if x['_id']==p['gold_identifier'])
        pn=numeric_tokens((pred['condition'] or '')+' '+(pred['action'] or ''));gn=numeric_tokens(g[cond]+' '+g[action])
        if pn!=gn:diagnostic.append(dict(document_id=p['document_id'],prediction_identifier=p['prediction_identifier'],gold_identifier=p['gold_identifier'],predicted_numeric_tokens=pn,gold_numeric_tokens=gn,status='diagnostic_only_not_field_accuracy'))
    save('numeric_diagnostics.local.json',diagnostic)
    assert h(pathlib.Path(L['prediction_file']))==L['prediction_sha256']
    result={'definition':'two user-supplied Markdown definitions; full definition plus pinned revision from team summary','primary_style':'plain','primary_threshold':.6,'gold_sha256':gold_hash,'gold_path':str(GOLD),'gold_rows':len(gold),'gold_documents':dict(collections.Counter(g['_document'] for g in gold)),'gold_columns':headers,'gold_field_mapping':dict(source=source,condition=cond,action=action,rule_class=cl,identifier=ident,sensors=sensor),'prediction_sha256':L['prediction_sha256'],'predictions_total':len(predictions),'sop_predictions':len(sop),'out_of_scope_datasheet_predictions':len(outside),'out_of_scope_by_document':dict(collections.Counter(p['document_id'] for p in outside)),'scores':all_scores,'algorithm_tests':tests,'pre_evaluation_lock_sha256':h(O/'pre_evaluation_lock.json'),'embedding_model':{'name':L['embedding_model']['name'],'revision':L['embedding_model']['revision']},'versions':L['versions'],'model_label':'모델(요청 설정): GPT-6.1 Sol','GT0009_binary':'N/A: subsequent event stage','leakage':'historical project gold exposure; allowed schema and attached definitions disclose metadata. Individual gold rules consumed only by this local evaluator after lock. Not an independent blind test.','prediction_changes_after_gold':False,'local_match_results_published':False,'numeric_disagreement_pairs':len(diagnostic),'gold_sensor_missing_note':None if sensor else 'Sensor set comparison N/A; no supported source field.'}
    save('evaluation_results.json',result)
    print(json.dumps({'status':'complete','primary':all_scores['plain']['0.6'],'gold_rows':len(gold),'gold_columns':headers,'sop_predictions':len(sop),'datasheet_predictions':len(outside),'gold_sha256':gold_hash},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
