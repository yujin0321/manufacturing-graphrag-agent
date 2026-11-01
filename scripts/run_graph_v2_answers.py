"""Generate once from sealed step-3 contexts; never read grading answers."""
import argparse
import json
import time
from imaks_kg.rag import vector as v
from verify_graph_v2_retrieval import questions

ROOT = v.REPO_ROOT
SOURCE = ROOT / 'kg_build/graphrag_v2_retrieval_20261024'
RUN = ROOT / 'kg_build/graphrag_v2_answers_20261024'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('split', choices=['dev', 'eval'])
    args = parser.parse_args()
    complete = v.read(SOURCE / 'complete.json')
    assert all(v.digest((SOURCE/q/'retrieval.json').read_bytes()) == h for q,h in complete['files'].items())
    cfg = v.read(v.CONFIG)
    common = (ROOT/'docs/vector_rag_v1/answer_instructions.txt').read_text(encoding='utf-8')
    paths = ['scripts/run_graph_v2_answers.py', 'src/imaks_kg/rag/vector.py',
             'docs/vector_rag_v1/config.json', 'docs/vector_rag_v1/answer_instructions.txt',
             'kg_build/graphrag_v2_retrieval_20261024/complete.json']
    lock = {'hashes': {p:v.digest((ROOT/p).read_bytes()) for p in paths},
            'generation_config':cfg, 'retrieval':'sealed graph_v2 step3, not config.top_k',
            'evaluation':'development retest; not unseen holdout', 'automatic_retries':False,
            'gold_loaded_for_generation':False, 'new_embeddings':False}
    if (RUN/'run_lock.json').exists():
        assert v.read(RUN/'run_lock.json') == lock
    else:
        v.write(RUN/'run_lock.json',lock)
    for q in [q for q in questions() if q['split'] == args.split]:
        run = RUN/args.split/q['id']
        if (run/'answer.json').exists():
            assert v.read(run/'answer.json')['question'] == q['question']
            print(q['id']+' preserved',flush=True)
            continue
        run.mkdir(parents=True,exist_ok=False)
        r = v.read(SOURCE/q['id']/'retrieval.json')
        assert r['context_tokens'] <= 4000
        v.write(run/'retrieval.json',r)
        v.write(run/'input.json',{'question':q['question'],'split':args.split,'system':'GraphRAG_v2'})
        payload = {'model':cfg['generation_model'],'store':False,
                   'max_completion_tokens':cfg['max_completion_tokens'],
                   'messages':[{'role':'system','content':common},
                               {'role':'user','content':json.dumps({'question':q['question'],
                                 'untrusted_reference_documents':r['context']},ensure_ascii=False)}]}
        started = time.perf_counter()
        try:
            raw,api = v.api_call('chat/completions',payload,run/'api')
            choice=raw['choices'][0];msg=choice['message']
            assert choice['finish_reason']=='stop' and msg.get('content') and not msg.get('refusal')
            assert raw['model']==cfg['generation_model'], 'Returned model differs; stop'
            answer={'status':'complete','system':'GraphRAG_v2','question':q['question'],
                    'answer':msg['content'],'requested_model':cfg['generation_model'],
                    'returned_model':raw['model'],'usage':raw['usage'],'generation_api':api,
                    'seconds':time.perf_counter()-started,'selected_ids':r['selected_ids'],
                    'context_tokens':r['context_tokens'],'instruction_sha256':v.digest(common.encode()),
                    'grading_performed':False}
            v.write(run/'answer.json',answer)
            print(json.dumps({'id':q['id'],'status':'complete','tokens':raw['usage']['total_tokens']}),flush=True)
        except Exception as exc:
            v.write(run/'failure.json',{'type':type(exc).__name__,'retry':False})
            raise
    print('COMPLETE '+args.split,flush=True)


if __name__=='__main__':
    main()
