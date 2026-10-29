"""Zero-API retrieval comparison. This runtime blocks every network connection.

Inference only reads public questions/corpus; grading loads private keys after
the result files have been sealed. Historical API embeddings and local encoder
results are always separate tracks.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import csv
import json
import os
from pathlib import Path
import socket
import statistics
import sys

os.environ.pop('OPENAI_API_KEY',None)
network_attempts=[]
def denied(*args,**kwargs):
    network_attempts.append('blocked');raise RuntimeError('API/network prohibited by offline protocol')
socket.create_connection=denied;socket.socket.connect=denied

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parent.parent
sys.path.insert(0,str(REPO/'src'))
from imaks_kg.rag import vector as v,comparison as c,retrieval_v3 as r3,retrieval_v5 as r5
from imaks_kg.rag.kg_query_v5 import KGEngine
from benchmark_catalog import BENCHMARKS
v.api_call=denied
OUT=ROOT/'runs/offline_budget_v1'
REPORT=ROOT/'reports/offline_budget_v1'


def questions():return [q for q in BENCHMARKS if q['status']=='executable' and q['track']!='fault_injection']


def public_code():
    paths=[Path(__file__),ROOT/'offline_local_encode.py',ROOT/'benchmark_catalog.py',
        REPO/'src/imaks_kg/rag/retrieval_v5.py',REPO/'src/imaks_kg/rag/kg_query_v5.py',
        REPO/'docs/graphrag_v3/lexicon.json',v.SOURCE,ROOT/c.KG_REL]
    return {str(p.relative_to(REPO)):v.digest(p.read_bytes()) for p in paths}


def cache_inventory(qs):
    import numpy as np
    locations=[ROOT/'runs/retrieval_v2/query_embeddings',REPO/'kg_build/retrieval_v3_rows',
        REPO/'kg_build']
    wanted={q['question'] for q in qs};matches={};rejected=[];read_count=0
    for folder in locations:
        for request in sorted(folder.rglob('*.request.json')):
            payload=v.read(request)
            if payload.get('model')!='text-embedding-3-small' or payload.get('dimensions')!=1536:continue
            inputs=payload.get('input',[])
            if not isinstance(inputs,list) or not wanted.intersection(x for x in inputs if isinstance(x,str)):continue
            response=request.with_name(request.name.replace('.request.json','.response.json'))
            if not response.exists():continue
            raw=v.read(response);read_count+=1
            if raw.get('model')!='text-embedding-3-small':rejected.append(str(response));continue
            data={item['index']:item['embedding'] for item in raw['data']}
            for i,text in enumerate(inputs):
                if text not in wanted or i not in data:continue
                vector=np.asarray(data[i],dtype=np.float32)
                if vector.shape!=(1536,) or not np.isfinite(vector).all() or np.linalg.norm(vector)==0:
                    rejected.append(str(response));continue
                if text not in matches:matches[text]={'vector':vector/np.linalg.norm(vector),'request':str(request),
                    'response':str(response),'request_sha256':v.digest(request.read_bytes()),'response_sha256':v.digest(response.read_bytes())}
    return matches,{'matching_cache_response_files':read_count,'invalid_files':rejected,
        'covered_ids':[q['id'] for q in qs if q['question'] in matches],
        'missing_ids':[q['id'] for q in qs if q['question'] not in matches],
        'scanned_locations':list(map(str,locations)),'network_calls':0}


def embedding_text(record,engine):
    text=v.embedding_text(record);stations,types=engine.names(text)
    aliases=[a for station in stations for a in engine.lexicon['stations'][station]]
    aliases += [a for typ in types for a in engine.lexicon['sensor_types'][typ]]
    return text+'\nPublic entity aliases: '+' '.join(dict.fromkeys(aliases))


def prepare():
    OUT.mkdir(parents=True,exist_ok=False);qs=questions();kg=KGEngine()
    snapshots=Path(os.environ.get('V5_LOCAL_MODEL_DIR', str(Path.home()/'.cache/huggingface/hub/models--jhgan--ko-sroberta-multitask/snapshots')))
    model=snapshots if (snapshots/'modules.json').is_file() else next(p for p in sorted(snapshots.iterdir()) if (p/'modules.json').is_file())
    records=[{'id':row['chunk_id'],'embedding_text':embedding_text(row,kg.doc_engine)} for row in kg.rows]
    records += [{'id':'QUESTION:'+q['id'],'embedding_text':kg.doc_engine.expanded(q['question'])} for q in qs]
    caches,inventory=cache_inventory(qs)
    v.write(OUT/'cache_inventory.json',inventory)
    v.write(OUT/'public_inputs.json',{'questions':qs,'corpus':kg.rows,'embedding_records':records,
        'local_model_path':str(model),'code':public_code(),
        'protocol':{'new_api_calls':0,'automatic_download':False,'local_full_suite_questions':len(qs),
            'historical_api_encoder':'text-embedding-3-small','local_encoder':'jhgan/ko-sroberta-multitask',
            'budgets_document':[1000,2000,4000],'budgets_kg':[2000,4000,8000],
            'general_LLM_retrieval_score':'not applicable: no retriever',
            'fairness':'Same corpus, alias dictionary and context caps within each track; graph-off controls included.'}})
    v.write(OUT/'cached_query_provenance.json',{q['id']:{k:value for k,value in caches[q['question']].items() if k!='vector'}
        for q in qs if q['question'] in caches})
    import numpy as np
    ids=[q['id'] for q in qs if q['question'] in caches]
    np.save(OUT/'cached_query_embeddings.npy',np.stack([caches[q['question']]['vector'] for q in qs if q['question'] in caches]),allow_pickle=False)
    v.write(OUT/'cached_query_ids.json',ids)
    print(json.dumps({'suite_questions':len(qs),'cached_api_queries':len(ids),'missing_api_queries':len(qs)-len(ids),
                      'local_model':str(model),'local_embedding_records':len(records),'new_api_calls':0},ensure_ascii=False))


def retrieve():
    import numpy as np
    setup=v.read(OUT/'public_inputs.json');qs=setup['questions'];kg=KGEngine();doc=r5.Engine(c.load_graph());base=r5.Engine(rows=doc.rows)
    doc_off=r5.Engine(c.Graph(),rows=doc.rows);kg_off=KGEngine()
    # Same serializer, public dictionary, packing and fallback, but no RDF facts
    # available to its planner. This isolates stored topology/attributes.
    kg_off.graph=c.Graph();kg_off.refs={};kg_off.doc_engine=r5.Engine(c.Graph(),rows=kg.documents)
    manifest=v.read(OUT/'local_embedding_manifest.json')
    if manifest['public_inputs_sha256']!=v.digest((OUT/'public_inputs.json').read_bytes()):raise ValueError('Local embedding input changed')
    if manifest['embedding_sha256']!=v.digest((OUT/'local_embeddings.npy').read_bytes()):raise ValueError('Local embedding hash mismatch')
    vectors=np.load(OUT/'local_embeddings.npy',allow_pickle=False)
    lookup={key:i for i,key in enumerate(manifest['record_ids'])}
    doc_vectors=vectors[[lookup[row['chunk_id']] for row in doc.rows]]
    kg_vectors=vectors[[lookup[row['chunk_id']] for row in kg.rows]]
    covered=[]
    for i,q in enumerate(qs,1):
        is_kg=q['track'] in ['kg_structure','kg_and_documents'];rows=kg.rows if is_kg else doc.rows
        matrix=kg_vectors if is_kg else doc_vectors;query=vectors[lookup['QUESTION:'+q['id']]]
        order=[hit['chunk_id'] for hit in v.retrieve(rows,matrix,query,len(rows))]
        budgets=setup['protocol']['budgets_kg' if is_kg else 'budgets_document']
        systems=['VectorRAG','GraphNoTopology','GraphRAG'] if is_kg else ['VectorRAG','HybridRAG','GraphNoTopology','GraphRAG']
        for budget in budgets:
            for system in systems:
                if is_kg:
                    engine=kg_off if system=='GraphNoTopology' else kg
                    result=engine.retrieve(q['question'],order,'GraphRAG' if system=='GraphNoTopology' else system,budget)
                else:
                    engine=doc if system=='GraphRAG' else doc_off if system=='GraphNoTopology' else base
                    result=engine.retrieve(q['question'],order,'GraphRAG' if system=='GraphNoTopology' else system,budget)
                result.update(system=system,encoder_track='local_offline',question_id=q['id'])
                if system=='GraphNoTopology':result['trace'].update(graph_used=False,topology_disabled=True)
                v.write(OUT/'retrieval/local_offline'/str(budget)/system/f"{q['id']}.json",result)
        covered.append(q['id'])
        if i%10==0:print(json.dumps({'stage':'offline_retrieval','done':i,'total':len(qs)},ensure_ascii=False),flush=True)
    # Historical OpenAI vectors are used only with their own index and cached
    # query vectors; never mix 1536-d API and 768-d local vector spaces.
    saved=v.read(r3.ROW_INDEX/'manifest.json');path=r3.ROW_INDEX/'vectors.npy'
    if saved['row_ids']!=[row['chunk_id'] for row in doc.rows] or saved['vectors_sha256']!=v.digest(path.read_bytes()):raise ValueError('Historical index changed')
    matrix=v.normalized(np.load(path,allow_pickle=False),len(doc.rows),1536)
    qids=v.read(OUT/'cached_query_ids.json');queries=np.load(OUT/'cached_query_embeddings.npy',allow_pickle=False)
    queries={qid:vector for qid,vector in zip(qids,queries)}
    cached_scored=[]
    for q in qs:
        if q['track']!='document_qa' or q['id'] not in queries:continue
        order=[hit['chunk_id'] for hit in v.retrieve(doc.rows,matrix,queries[q['id']],len(doc.rows))]
        for budget in [1000,2000,4000]:
            for system in ['VectorRAG','HybridRAG','GraphNoTopology','GraphRAG']:
                engine=doc if system=='GraphRAG' else doc_off if system=='GraphNoTopology' else base
                result=engine.retrieve(q['question'],order,'GraphRAG' if system=='GraphNoTopology' else system,budget)
                result.update(system=system,encoder_track='cached_api',question_id=q['id'])
                v.write(OUT/'retrieval/cached_api'/str(budget)/system/f"{q['id']}.json",result)
        cached_scored.append(q['id'])
    v.write(OUT/'retrieval_coverage.json',{'local_offline':covered,'cached_api_document_only':cached_scored,
        'new_api_calls':0,'network_attempts':len(network_attempts),'unscored':[q for q in BENCHMARKS if q['status']=='pending_input'],
        'fault_injection_report':'reports/fault_injection/results.json'})
    files={str(p.relative_to(OUT)):v.digest(p.read_bytes()) for p in sorted(OUT.rglob('*.json')) if p.name!='retrieval_seal.json'}
    v.write(OUT/'retrieval_seal.json',{'files':files,'code':public_code(),'gold_read':False,
        'embedding_files':{str(p.relative_to(OUT)):v.digest(p.read_bytes()) for p in OUT.glob('*.npy')},
        'new_api_calls':0,'network_attempts':len(network_attempts)})
    print(json.dumps({'local_questions':len(covered),'cached_api_document_questions':len(cached_scored),'new_api_calls':0},ensure_ascii=False))


def grade():
    seal=v.read(OUT/'retrieval_seal.json')
    for rel,sha in {**seal['files'],**seal['embedding_files']}.items():
        if v.digest((OUT/rel).read_bytes())!=sha:raise ValueError('Sealed inference output changed')
    if seal['code']!=public_code():raise ValueError('Source changed after retrieval freeze')
    # Private answers are first opened here, after retrieval has been sealed.
    lock=v.read(ROOT/'experiment/expanded/suite_lock.json');private=ROOT/'evaluation/expanded/answer_key.json'
    if v.digest(private.read_bytes())!=lock['private_key_sha256']:raise ValueError('Private key changed')
    keys={q['id']:q for q in v.read(private)['questions']};qs={q['id']:q for q in questions()}
    if (REPORT/'retrieval_summary.json').exists():raise ValueError('Preserve existing offline grades; use a new version')
    REPORT.mkdir(parents=True,exist_ok=True);details=[];groups=defaultdict(list)
    for path in sorted((OUT/'retrieval').rglob('*.json')):
        data=v.read(path);qid=data['question_id'];q=qs[qid];needed=keys[qid]['evidence'];selected=set(data['selected_ids'])
        found=sorted(set(needed)&selected)
        row={'id':qid,'encoder_track':data['encoder_track'],'track':q['track'],'category':q['category'],
            'split':q.get('split'),'system':data['system'],'budget':data['budget'],
            'required':len(needed),'found':len(found),'recall':len(found)/len(needed),
            'complete':len(found)==len(needed),'tokens':data['context_tokens'],'missing':' | '.join(sorted(set(needed)-set(found)))}
        details.append(row)
        for scope in ['all',q['track']]:groups[(row['encoder_track'],scope,row['budget'],row['system'])].append(row)
    summary=[]
    for (encoder,track,budget,system),rows in sorted(groups.items()):
        summary.append({'encoder_track':encoder,'track':track,'budget':budget,'system':system,'questions':len(rows),
            'micro_evidence_recall':sum(r['found'] for r in rows)/sum(r['required'] for r in rows),
            'macro_evidence_recall':statistics.mean(r['recall'] for r in rows),
            'complete_questions':sum(r['complete'] for r in rows),'mean_context_tokens':statistics.mean(r['tokens'] for r in rows)})
    v.write(REPORT/'retrieval_summary.json',summary);v.write(REPORT/'retrieval_details.json',details)
    for name,rows in [('문항별_검색비교.csv',details),('검색성능_요약.csv',summary)]:
        with (REPORT/name).open('w',encoding='utf-8-sig',newline='') as handle:
            writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    v.write(REPORT/'evaluation_protocol.json',{'new_api_calls':0,'network_attempts':len(network_attempts),
        'retrieval_seal_sha256':v.digest((OUT/'retrieval_seal.json').read_bytes()),
        'private_key_sha256':v.digest(private.read_bytes()),'grading':'Exact required evidence ID coverage only, not answer accuracy',
        'answer_key_status':'AI source-based drafts and deterministic KG queries, no independent human review',
        'LLM_retrieval_score':'N/A: the no-retrieval baseline has no retrieval metric'})
    print(json.dumps([r for r in summary if r['encoder_track']=='local_offline' and
        (r['track']=='document_qa' and r['budget']==4000 or r['track'] in ['kg_structure','kg_and_documents'] and r['budget']==8000)],ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','retrieve','grade']);a=p.parse_args()
    {'prepare':prepare,'retrieve':retrieve,'grade':grade}[a.action]()
