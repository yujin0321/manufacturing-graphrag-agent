"""Offline B/C ablation. Generate contexts before loading evaluation answers."""
import argparse
import json
import statistics
from unittest.mock import patch
from imaks_kg.rag import vector as v,graph_v2 as g,comparison as c,ablation as a

ROOT=v.REPO_ROOT;RUN=ROOT/'kg_build/graph_ablation_20261024';OUT=ROOT/'evaluation/graph_ablation_20261024'


def questions():
    qs=[]
    for split in ['dev','eval']:
        rel=f'docs/benchmark_yewon_v2_20261023/questions_{split}.jsonl';p=ROOT/rel
        assert v.digest(p.read_bytes())==v.read(v.LOCK)['hashes'][rel]
        qs.extend(json.loads(line) for line in p.read_text(encoding='utf-8').splitlines() if line.strip())
    assert len(qs)==30;return qs


def generate():
    RUN.mkdir(parents=True,exist_ok=False)
    files=['src/imaks_kg/rag/ablation.py','src/imaks_kg/rag/graph_v2.py','src/imaks_kg/rag/comparison.py','docs/graphrag_v2/retrieval_policy.json']
    v.write(RUN/'lock.json',{'hashes':{p:v.digest((ROOT/p).read_bytes()) for p in files},'graph_cards_in_B_and_C':0,'max_chunks':24,'max_tokens':4000,'api_calls':0})
    corpus,matrix,m=v.load_index(v.DEFAULT_INDEX)
    with patch.object(v,'urlopen',side_effect=AssertionError('Network forbidden')):
        # B is completed first with KG loading explicitly forbidden.
        with patch.object(c,'load_graph',side_effect=AssertionError('B must not read KG')):
            for q in questions():
                query,_=v.embed([q['question']],m['config'],v.DEFAULT_INDEX/'query_cache',g.cached_embeddings)
                dense=v.retrieve(corpus,matrix,query[0],len(corpus))
                v.write(RUN/'B'/q['id']/'retrieval.json',a.select(q['question'],corpus,dense))
        graph=c.load_graph()
        for q in questions():
            query,_=v.embed([q['question']],m['config'],v.DEFAULT_INDEX/'query_cache',g.cached_embeddings)
            dense=v.retrieve(corpus,matrix,query[0],len(corpus))
            trace=g.context(q['question'],corpus,dense,graph,{**v.read(g.POLICY_PATH),'max_graph_tokens':0})
            result=a.select(q['question'],corpus,dense,trace)
            b=v.read(RUN/'B'/q['id']/'retrieval.json')
            assert result['shared_prefix']==b['shared_prefix'] and result['shared_ranked_ids']==b['shared_ranked_ids']
            v.write(RUN/'C'/q['id']/'retrieval.json',result)
            v.write(RUN/'C'/q['id']/'graph_trace.json',trace)
            print(q['id']+' B/C completed',flush=True)
    v.write(RUN/'complete.json',{'files':{p.relative_to(RUN).as_posix():v.digest(p.read_bytes()) for p in RUN.glob('*/*/*.json')},'gold_loaded':False})


def grade():
    complete=v.read(RUN/'complete.json');assert len(complete['files'])==90
    assert all(v.digest((RUN/p).read_bytes())==h for p,h in complete['files'].items())
    keys={k['id']:k for k in v.read(ROOT/'evaluation/benchmark_yewon_v2_20261023/answer_key_PRIVATE.json')}
    corpus,_=v.source_records();texts={r['chunk_id']:r['text'] for r in corpus}
    rows=[];pairs=[];summary={}
    for q in questions():
        required={e['chunk_id'] for e in keys[q['id']]['evidence']};traces={}
        for variant in ['B','C']:
            r=v.read(RUN/variant/q['id']/'retrieval.json');traces[variant]=r;selected=set(r['selected_ids'])
            assert len(selected)==len(r['selected_ids'])<=24 and r['context_tokens']<=4000
            assert all(texts[cid] in r['context'] for cid in selected)
            rows.append({'id':q['id'],'split':q['split'],'variant':variant,'found':len(required&selected),'required':len(required),'recall':len(required&selected)/len(required),'complete':required<=selected,'missing':sorted(required-selected),'tokens':r['context_tokens'],'chunks':len(selected)})
        b=set(traces['B']['selected_ids']);cc=set(traces['C']['selected_ids'])
        pairs.append({'id':q['id'],'split':q['split'],'required_gained':sorted(required&(cc-b)),'required_lost':sorted(required&(b-cc)),'all_added':sorted(cc-b),'all_removed':sorted(b-cc),'same_order':traces['B']['selected_ids']==traces['C']['selected_ids']})
    for split in ['dev','eval']:
        summary[split]={}
        for variant in ['B','C']:
            rs=[r for r in rows if r['split']==split and r['variant']==variant]
            summary[split][variant]={'n':len(rs),'found':sum(r['found'] for r in rs),'required':sum(r['required'] for r in rs),'complete':sum(r['complete'] for r in rs),'mean_tokens':statistics.mean(r['tokens'] for r in rs),'max_tokens':max(r['tokens'] for r in rs),'mean_chunks':statistics.mean(r['chunks'] for r in rs)}
    OUT.mkdir(parents=True,exist_ok=False);v.write(OUT/'summary.json',summary);v.write(OUT/'paired_PRIVATE.json',pairs);v.write(OUT/'scores_PRIVATE.json',rows)
    print(json.dumps({'summary':summary,'required_changes':[p for p in pairs if p['required_gained'] or p['required_lost']],'changed_sets':sum(bool(p['all_added'] or p['all_removed']) for p in pairs)},ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['generate','grade']);args=p.parse_args()
    generate() if args.action=='generate' else grade()
