"""Generate independent benchmark responses without loading reference answers."""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from imaks_kg.rag import vector as v, comparison as c


def main():
    parser=argparse.ArgumentParser();parser.add_argument('split',choices=['dev','eval'])
    args=parser.parse_args();split=args.split
    root=v.REPO_ROOT/'kg_build/comparison_benchmark_20261024'/split
    qpath=v.REPO_ROOT/f'docs/benchmark_yewon_v2_20261023/questions_{split}.jsonl'
    assert v.digest(qpath.read_bytes())==v.read(v.LOCK)['hashes'][qpath.relative_to(v.REPO_ROOT).as_posix()]
    questions=[json.loads(x) for x in qpath.read_text(encoding='utf-8').splitlines() if x.strip()]
    assert len(questions)==(6 if split=='dev' else 24)
    assert all(q['split']==split for q in questions)
    systems=['LLM','GraphRAG'] if split=='dev' else ['LLM','VectorRAG','GraphRAG']
    paths=['src/imaks_kg/rag/comparison.py','src/imaks_kg/rag/vector.py','docs/vector_rag_v1/config.json','docs/vector_rag_v1/answer_instructions.txt',c.KG_REL,qpath.relative_to(v.REPO_ROOT).as_posix()]
    lock={'split':split,'systems':systems,'policy':c.POLICY,'hashes':{p:v.digest((v.REPO_ROOT/p).read_bytes()) for p in paths},'question_count':len(questions),'max_parallel_questions':3,'automatic_retries':False}
    if (root/'run_lock.json').exists():assert v.read(root/'run_lock.json')==lock
    else:v.write(root/'run_lock.json',lock)
    def one(q):
        for system in systems:
            run=root/system/q['id']
            if (run/'answer.json').exists():
                r=v.read(run/'answer.json')
                assert r['question']==q['question'] and r['returned_model']=='gpt-6.1-sol'
                print(json.dumps({'system':system,'id':q['id'],'status':'preserved_existing'}),flush=True);continue
            if run.exists():raise RuntimeError('Unresolved run; no resend: '+str(run))
            r=v.answer(q['question'],run_dir=run) if system=='VectorRAG' else c.answer(system,q['question'],run)
            if r['returned_model']!='gpt-6.1-sol':raise RuntimeError('Model changed; inspect before continuing')
            print(json.dumps({'system':system,'id':q['id'],'status':r['status'],'tokens':r['usage']['total_tokens']},ensure_ascii=False),flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(one,questions))
    print('COMPLETE '+split,flush=True)


if __name__=='__main__':main()
