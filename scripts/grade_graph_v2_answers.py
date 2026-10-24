"""Aggregate explicit AI source-review decisions; no automatic semantic scoring."""
import csv
import io
from collections import defaultdict
from imaks_kg.rag import vector as v

ROOT=v.REPO_ROOT
RUN=ROOT/'kg_build/graphrag_v2_answers_20261024'
OUT=ROOT/'evaluation/graphrag_v2_answers_20261024'


def main():
    assert all(v.digest((ROOT/p).read_bytes())==h for p,h in v.read(v.LOCK)['hashes'].items())
    assert all(v.digest((ROOT/p).read_bytes())==h for p,h in v.read(RUN/'run_lock.json')['hashes'].items())
    keys={k['id']:k for k in v.read(ROOT/'evaluation/benchmark_yewon_v2_20261023/answer_key_PRIVATE.json')}
    old={(r['split'],r['id']):r for r in v.read(ROOT/'evaluation/comparison_20261024/decisions_PRIVATE.json') if r['system']=='GraphRAG'}
    decisions=v.read(OUT/'decisions_PRIVATE.json')
    assert len(decisions)==30 and {d['id'] for d in decisions}==set(keys)
    rows=[]
    for d in decisions:
        k=keys[d['id']];p=RUN/k['split']/d['id']/'answer.json';a=v.read(p)
        assert a['returned_model']=='gpt-6.1-sol' and a['question']==k['question']
        assert d['answer_sha256']==v.digest(p.read_bytes())
        assert len(d['atoms'])==3 and all(x in [0,1] for x in d['atoms'])
        assert d['faithfulness'] in [0,1] and d['reason'] and 0<=d['evidence']<=1
        total=sum(d['atoms'])+d['evidence']+d['faithfulness']
        prior=old[k['split'],d['id']]
        prior_total=sum(prior['atoms'])+prior['evidence']+prior['faithfulness']
        rows.append(dict(d,split=k['split'],category=k['category'],total=total,strict_correct=int(total==5),
                         old_graph_total=prior_total,delta=total-prior_total,answer=a['answer'],
                         prompt_tokens=a['usage']['prompt_tokens'],completion_tokens=a['usage']['completion_tokens']))
    summary={}
    for split,n in [('dev',6),('eval',24)]:
        rs=[r for r in rows if r['split']==split];assert len(rs)==n
        cats=defaultdict(list)
        for r in rs:cats[r['category']].append(r['total'])
        summary[split]={'n':n,'points':sum(r['total'] for r in rs),'mean':sum(r['total'] for r in rs)/n,
          'strict_correct':sum(r['strict_correct'] for r in rs),'strict_pct':100*sum(r['strict_correct'] for r in rs)/n,
          'content_pct':100*sum(sum(r['atoms']) for r in rs)/(3*n),'evidence_pct':100*sum(r['evidence'] for r in rs)/n,
          'faithfulness_pct':100*sum(r['faithfulness'] for r in rs)/n,
          'prompt_tokens':sum(r['prompt_tokens'] for r in rs),'completion_tokens':sum(r['completion_tokens'] for r in rs),
          'category_means':{k:sum(x)/len(x) for k,x in cats.items()},
          'gains':[r['id'] for r in rs if r['delta']>0],'regressions':[r['id'] for r in rs if r['delta']<0]}
    v.write(OUT/'scores_PRIVATE.json',rows);v.write(OUT/'summary.json',summary)
    f=io.StringIO(newline='');w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    (OUT/'scores_PRIVATE.csv').write_text(f.getvalue(),encoding='utf-8-sig')
    v.write(RUN/'complete.json',{'answers':30,'hashes':{str(p.relative_to(RUN)):v.digest(p.read_bytes()) for p in sorted(RUN.glob('*/*/answer.json'))}})
    print(__import__('json').dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
