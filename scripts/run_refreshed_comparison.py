"""Fresh three-arm QA comparison. Prepare without gold; 72 generations at most."""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from imaks_kg.rag import vector as v, graph_v2 as g, comparison as c, ablation as a

ROOT = v.REPO_ROOT
RUN = ROOT / 'kg_build/refreshed_comparison_20261028'
ARMS = ['LLM', 'VectorHybrid', 'GraphRAG']


def questions():
    p = ROOT / 'docs/benchmark_yewon_v2_20261023/questions_eval.jsonl'
    assert v.digest(p.read_bytes()) == v.read(v.LOCK)['hashes'][p.relative_to(ROOT).as_posix()]
    qs = [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]
    assert len(qs) == 24
    return qs


def prepare():
    qs = questions()
    old = ROOT / 'kg_build/graph_ablation_20261024'
    full = ROOT / 'kg_build/graphrag_v2_retrieval_20261024'
    assert all(v.digest((old / p).read_bytes()) == h for p, h in v.read(old / 'complete.json')['files'].items())
    assert all(v.digest((full / q / 'retrieval.json').read_bytes()) == h for q, h in v.read(full / 'complete.json')['files'].items())
    assert all(v.digest((ROOT / p).read_bytes()) == h for p, h in v.read(full / 'lock.json')['implementation_hashes'].items())
    RUN.mkdir(parents=True, exist_ok=False)
    with patch.object(v, 'urlopen', side_effect=AssertionError('Offline preparation')):
        corpus, matrix, meta = v.load_index(v.DEFAULT_INDEX)
        with patch.object(c, 'load_graph', side_effect=AssertionError('Vector arm must not load KG')):
            for q in qs:
                query, _ = v.embed([q['question']], meta['config'], v.DEFAULT_INDEX / 'query_cache', g.cached_embeddings)
                dense = v.retrieve(corpus, matrix, query[0], len(corpus))
                result = a.select(q['question'], corpus, dense)
                assert result['context'] == v.read(old / 'B' / q['id'] / 'retrieval.json')['context']
                v.write(RUN / 'inputs/VectorHybrid' / (q['id'] + '.json'), {**result, 'question': q['question'], 'variant': 'VectorHybrid', 'kg_loaded': False})
    for q in qs:
        r = v.read(full / q['id'] / 'retrieval.json')
        assert r['context_tokens'] <= 4000
        v.write(RUN / 'inputs/GraphRAG' / (q['id'] + '.json'), {**r, 'question': q['question'], 'variant': 'GraphRAG'})
        v.write(RUN / 'inputs/LLM' / (q['id'] + '.json'), {'question': q['question'], 'context': '', 'selected_ids': [], 'context_tokens': 0, 'variant': 'LLM'})
    paths = ['scripts/run_refreshed_comparison.py', 'src/imaks_kg/rag/vector.py',
             'src/imaks_kg/rag/ablation.py', 'src/imaks_kg/rag/graph_v2.py',
             'docs/vector_rag_v1/config.json', 'docs/vector_rag_v1/answer_instructions.txt',
             'docs/graphrag_v2/retrieval_policy.json', 'docs/benchmark_yewon_v2_20261023/채점기준_확정_v1.md',
             'docs/benchmark_yewon_v2_20261023/questions_eval.jsonl', c.KG_REL]
    v.write(RUN / 'run_lock.json', {'hashes': {p: v.digest((ROOT / p).read_bytes()) for p in paths},
            'inputs': {p.relative_to(RUN).as_posix(): v.digest(p.read_bytes()) for p in RUN.glob('inputs/*/*.json')},
            'arms': ARMS, 'max_generations': 72, 'new_embeddings': 0, 'gold_loaded_for_generation': False,
            'vector_policy': 'dense+lexical RRF, literal ID, explicit document coverage, max24 chunks/4000tokens, no KG',
            'graph_policy': 'sealed full graph_v2 contexts including cards; not stored-edge-only ablation',
            'generation_config': v.read(v.CONFIG), 'evaluation': 'development retest', 'retries': False})
    print('PREPARED 72 inputs; no API calls')


def verify():
    lock = v.read(RUN / 'run_lock.json')
    assert all(v.digest((ROOT / p).read_bytes()) == h for p, h in lock['hashes'].items())
    assert len(lock['inputs']) == 72
    assert all(v.digest((RUN / p).read_bytes()) == h for p, h in lock['inputs'].items())
    return lock


def execute():
    lock = verify(); cfg = lock['generation_config']
    common = (ROOT / 'docs/vector_rag_v1/answer_instructions.txt').read_text(encoding='utf-8')
    def generate(q, arm):
        r = v.read(RUN / 'inputs' / arm / (q['id'] + '.json'))
        payload = {'model': cfg['generation_model'], 'store': False, 'max_completion_tokens': cfg['max_completion_tokens'],
                   'messages': [{'role': 'system', 'content': common}, {'role': 'user', 'content': json.dumps({'question': q['question'], 'untrusted_reference_documents': r['context']}, ensure_ascii=False)}]}
        run = RUN / 'answers' / arm / q['id']
        h = v.digest(v.encoded(payload))
        if (run / 'answer.json').exists():
            assert v.read(run / 'answer.json')['request_sha256'] == h
            return
        try:
            raw, api = v.api_call('chat/completions', payload, run / 'api')
            choice = raw['choices'][0]; msg = choice['message']
            assert choice['finish_reason'] == 'stop' and msg.get('content') and not msg.get('refusal')
            assert raw['model'] == cfg['generation_model'], 'Actual model differs'
            v.write(run / 'answer.json', {'id': q['id'], 'arm': arm, 'question': q['question'], 'answer': msg['content'],
                    'returned_model': raw['model'], 'usage': raw['usage'], 'api': api, 'request_sha256': h})
            print(q['id'] + ' ' + arm + ' complete', flush=True)
        except Exception as exc:
            v.write(run / 'failure.json', {'type': type(exc).__name__, 'retry': False})
            raise
    with ThreadPoolExecutor(max_workers=3) as pool:
        for i, q in enumerate(questions()):
            arms = ARMS[i % 3:] + ARMS[:i % 3]
            futures = [pool.submit(generate, q, arm) for arm in arms]
            for f in futures: f.result()
    paths = sorted(RUN.glob('answers/*/*/answer.json')); assert len(paths) == 72
    v.write(RUN / 'complete.json', {'files': {p.relative_to(RUN).as_posix(): v.digest(p.read_bytes()) for p in paths}, 'answers': 72})
    print('COMPLETE 72', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('action', choices=['prepare', 'verify', 'execute']); args = p.parse_args()
    {'prepare': prepare, 'verify': verify, 'execute': execute}[args.action]()
