"""48 paired generations from sealed contexts; no gold access or automatic retries."""
import argparse
import json
from imaks_kg.rag import vector as v

ROOT = v.REPO_ROOT
SOURCE = ROOT / 'kg_build/stored_edge_ablation_20261028'
RUN = ROOT / 'kg_build/stored_edge_answers_20261028'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--execute', action='store_true')
    args = p.parse_args()
    assert all(v.digest((SOURCE / f).read_bytes()) == h for f, h in v.read(SOURCE / 'complete.json')['files'].items())
    assert all(v.digest((ROOT / f).read_bytes()) == h for f, h in v.read(SOURCE / 'audit.json')['hashes'].items())
    cfg = v.read(v.CONFIG)
    common = (ROOT / 'docs/vector_rag_v1/answer_instructions.txt').read_text(encoding='utf-8')
    qs = [json.loads(x) for x in (ROOT / 'docs/benchmark_yewon_v2_20261023/questions_eval.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
    assert len(qs) == 24
    paths = ['scripts/run_stored_edge_answers.py', 'src/imaks_kg/rag/vector.py',
             'docs/vector_rag_v1/config.json', 'docs/vector_rag_v1/answer_instructions.txt',
             'docs/benchmark_yewon_v2_20261023/채점기준_확정_v1.md',
             'kg_build/stored_edge_ablation_20261028/complete.json']
    lock = {'hashes': {f: v.digest((ROOT / f).read_bytes()) for f in paths},
            'config': cfg, 'max_generations': 48, 'gold_loaded': False, 'new_embeddings': 0,
            'automatic_retries': False, 'evaluation': 'development retest'}
    if (RUN / 'run_lock.json').exists():
        assert v.read(RUN / 'run_lock.json') == lock
    else:
        v.write(RUN / 'run_lock.json', lock)
    jobs = []
    for i, q in enumerate(qs):
        arms = ['stored_edges_off', 'stored_edges_on']
        if i % 2: arms.reverse()
        for arm in arms:
            r = v.read(SOURCE / arm / q['id'] / 'input.json')
            assert r['question'] == q['question'] and r['context_tokens'] <= 4000
            payload = {'model': cfg['generation_model'], 'store': False,
                       'max_completion_tokens': cfg['max_completion_tokens'],
                       'messages': [{'role': 'system', 'content': common}, {'role': 'user', 'content': json.dumps({'question': q['question'], 'untrusted_reference_documents': r['context']}, ensure_ascii=False)}]}
            jobs.append((q, arm, payload))
    if not args.execute:
        print('Verified 48 requests; dry run; API calls=0')
        return
    for q, arm, payload in jobs:
        run = RUN / arm / q['id']
        if (run / 'answer.json').exists():
            assert v.read(run / 'answer.json')['request_sha256'] == v.digest(v.encoded(payload))
            continue
        try:
            raw, api = v.api_call('chat/completions', payload, run / 'api')
            choice = raw['choices'][0]
            assert choice['finish_reason'] == 'stop' and choice['message'].get('content') and not choice['message'].get('refusal')
            assert raw['model'] == cfg['generation_model'], 'Returned model changed'
            v.write(run / 'answer.json', {'id': q['id'], 'question': q['question'], 'arm': arm,
                     'answer': choice['message']['content'], 'returned_model': raw['model'],
                     'usage': raw['usage'], 'api': api, 'request_sha256': v.digest(v.encoded(payload))})
            print(q['id'] + ' ' + arm + ' complete', flush=True)
        except Exception as exc:
            v.write(run / 'failure.json', {'type': type(exc).__name__, 'retry': False})
            raise
    answers = sorted(RUN.glob('*/*/answer.json'))
    assert len(answers) == 48
    v.write(RUN / 'complete.json', {'files': {p.relative_to(RUN).as_posix(): v.digest(p.read_bytes()) for p in answers}, 'answers': 48})
    print('COMPLETE 48', flush=True)


if __name__ == '__main__':
    main()
