"""Two separate offline phases: retrieve first, then compare reference evidence."""
import argparse
import json
import statistics
from unittest.mock import patch
from imaks_kg.rag import vector as v, graph_v2 as g

ROOT=v.REPO_ROOT
RUN=ROOT/'kg_build/graphrag_v2_retrieval_20261024'
OUT=ROOT/'evaluation/graphrag_v2_retrieval_20261024'


def questions():
    result=[];lock=v.read(v.LOCK)
    for split in ['dev','eval']:
        rel=f'docs/benchmark_yewon_v2_20261023/questions_{split}.jsonl'
        p=ROOT/rel;assert v.digest(p.read_bytes())==lock['hashes'][rel]
        qs=[json.loads(line) for line in p.read_text(encoding='utf-8').splitlines() if line.strip()]
        assert len(qs)==(6 if split=='dev' else 24)
        assert all(q['split']==split for q in qs);result.extend(qs)
    return result


def generate():
    implementation=v.read(ROOT/'kg_build/graphrag_v2_implementation_20261024/implementation_manifest.json')
    assert all(v.digest((ROOT/p).read_bytes())==h for p,h in implementation['hashes'].items())
    RUN.mkdir(parents=True,exist_ok=False)
    v.write(RUN/'lock.json',{'implementation_hashes':implementation['hashes'],'policy':v.read(g.POLICY_PATH),'answer_generation':False,'api_calls':0})
    # Even accidental use of the existing HTTP helper fails before a request.
    with patch.object(v,'urlopen',side_effect=AssertionError('Network forbidden')):
        for q in questions():
            result=g.retrieve(q['question'])
            assert result['embedding_api']['cache_hit'] and result['context_tokens']<=4000
            v.write(RUN/q['id']/'retrieval.json',result)
            print(q['id']+' retrieved',flush=True)
    v.write(RUN/'complete.json',{'questions':30,'files':{q['id']:v.digest((RUN/q['id']/'retrieval.json').read_bytes()) for q in questions()},'gold_loaded_during_generation':False})


def measure(required,selected):
    required=set(required);selected=set(selected)
    if not required:raise ValueError('Empty reference evidence')
    found=required & selected
    return {'required':len(required),'found':len(found),'recall':len(found)/len(required),'complete':required<=selected,'missing':sorted(required-selected)}


def grade():
    complete=v.read(RUN/'complete.json');assert complete['questions']==30
    assert all(v.digest((RUN/q/'retrieval.json').read_bytes())==h for q,h in complete['files'].items())
    lock=v.read(v.LOCK)
    assert all(v.digest((ROOT/p).read_bytes())==h for p,h in lock['hashes'].items())
    # Answer key is loaded only in this separate post-retrieval process.
    keys={k['id']:k for k in v.read(ROOT/'evaluation/benchmark_yewon_v2_20261023/answer_key_PRIVATE.json')}
    corpus,_=v.source_records();by_id={c['chunk_id']:c for c in corpus};rows=[]
    for q in questions():
        qid=q['id'];split=q['split'];required=[e['chunk_id'] for e in keys[qid]['evidence']]
        paths={'GraphRAG_v2':RUN/qid/'retrieval.json',
               'GraphRAG_v1':ROOT/'kg_build/comparison_benchmark_20261024'/split/'GraphRAG'/qid/'retrieval.json',
               'VectorRAG':ROOT/'kg_build/comparison_benchmark_20261024'/split/'VectorRAG'/qid/'retrieval.json'}
        if split=='dev':paths['VectorRAG']=ROOT/'kg_build/vector_rag_dev_20261024'/qid/'retrieval.json'
        for system,p in paths.items():
            r=v.read(p);selected=r['selected_ids']
            assert len(selected)==len(set(selected))
            assert all(cid in by_id and by_id[cid]['text'] in r['context'] for cid in selected)
            row={'id':qid,'split':split,'system':system,**measure(required,selected),'context_tokens':r['context_tokens'],
                 'selected_chunks':len(selected),'graph_cards':len(r.get('graph_nodes',[])),
                 'uncovered_explicit_documents':r.get('uncovered_explicit_documents',[]),'skipped_for_budget':r['skipped_for_budget']}
            rows.append(row)
    summary={};changes=[]
    for split in ['dev','eval']:
        summary[split]={}
        for system in ['VectorRAG','GraphRAG_v1','GraphRAG_v2']:
            rs=[r for r in rows if r['split']==split and r['system']==system]
            summary[split][system]={'questions':len(rs),'found_units':sum(r['found'] for r in rs),'required_units':sum(r['required'] for r in rs),
              'micro_recall':sum(r['found'] for r in rs)/sum(r['required'] for r in rs),'macro_recall':statistics.mean(r['recall'] for r in rs),
              'complete_questions':sum(r['complete'] for r in rs),'mean_context_tokens':statistics.mean(r['context_tokens'] for r in rs),
              'max_context_tokens':max(r['context_tokens'] for r in rs),'mean_selected_chunks':statistics.mean(r['selected_chunks'] for r in rs),
              'zero_graph_card_questions':sum(r['graph_cards']==0 for r in rs)}
        for q in [q for q in questions() if q['split']==split]:
            old=next(r for r in rows if r['id']==q['id'] and r['system']=='GraphRAG_v1');new=next(r for r in rows if r['id']==q['id'] and r['system']=='GraphRAG_v2')
            changes.append({'id':q['id'],'split':split,'gained':sorted(set(old['missing'])-set(new['missing'])),'lost':sorted(set(new['missing'])-set(old['missing'])),'remaining_missing':new['missing']})
    OUT.mkdir(parents=True,exist_ok=False)
    v.write(OUT/'per_question_PRIVATE.json',rows);v.write(OUT/'changes_PRIVATE.json',changes);v.write(OUT/'summary.json',summary)
    print(json.dumps({'summary':summary,'changed_or_missing':[r for r in changes if r['gained'] or r['lost'] or r['remaining_missing']]},ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['generate','grade']);a=p.parse_args()
    generate() if a.action=='generate' else grade()
