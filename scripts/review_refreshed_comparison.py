"""Arm-masked AI review records and deterministic aggregation after 72 generations."""
import argparse
import random
from collections import defaultdict
from imaks_kg.rag import vector as v
from run_refreshed_comparison import RUN, ROOT, ARMS, verify

OUT = ROOT / 'evaluation/refreshed_comparison_20261028'


def verify_answers():
    verify()
    seal = v.read(RUN / 'complete.json')
    assert len(seal['files']) == 72
    assert all(v.digest((RUN / p).read_bytes()) == h for p, h in seal['files'].items())
    assert all(v.digest((ROOT / p).read_bytes()) == h for p, h in v.read(v.LOCK)['hashes'].items())
    return seal


def prepare():
    seal = verify_answers()
    OUT.mkdir(parents=True, exist_ok=False)
    keys = {k['id']: k for k in v.read(ROOT / 'evaluation/benchmark_yewon_v2_20261023/answer_key_PRIVATE.json')}
    paths = sorted(seal['files']); random.Random(28102026).shuffle(paths)
    mapping = {}; packets = defaultdict(list)
    for i, path in enumerate(paths, 1):
        a = v.read(RUN / path); label = f'T{i:02}'
        mapping[label] = {'path': path, 'sha256': seal['files'][path], 'id': a['id'], 'arm': a['arm']}
        packets[a['id']].append({'review_id': label, 'answer': a['answer']})
    grouped = []
    for q, answers in sorted(packets.items()):
        k = keys[q]
        grouped.append({'id': q, 'question': k['question'], 'atoms': k['answer_atoms'],
                        'evidence': [{'chunk_id': e['chunk_id'], 'text': e['text']} for e in k['evidence']], 'answers': answers})
    v.write(OUT / 'mapping_PRIVATE.json', mapping)
    v.write(OUT / 'packets_PRIVATE.json', grouped)
    print('Prepared 72 arm-masked responses across 24 questions')


def aggregate():
    verify_answers()
    mapping = v.read(OUT / 'mapping_PRIVATE.json'); ds = v.read(OUT / 'decisions_PRIVATE.json')
    assert len(ds) == 72 and {d['review_id'] for d in ds} == set(mapping)
    keys = {k['id']: k for k in v.read(ROOT / 'evaluation/benchmark_yewon_v2_20261023/answer_key_PRIVATE.json')}
    rows = []
    for d in ds:
        m = mapping[d['review_id']]; path = RUN / m['path']; answer = v.read(path)
        assert v.digest(path.read_bytes()) == m['sha256']
        assert len(d['atoms']) == 3 and all(x in [0, 1] for x in d['atoms'])
        assert d['faithfulness'] in [0, 1] and 0 <= d['evidence'] <= 1 and d['reason']
        total = sum(d['atoms']) + d['evidence'] + d['faithfulness']
        rows.append({**d, **m, 'category': keys[m['id']]['category'], 'total': total, 'strict_correct': total == 5,
                     'usage': answer['usage'], 'reviewer': 'Codex AI; system names masked; prior benchmark exposure'})
    summary = {}
    for arm in ARMS:
        rs = [r for r in rows if r['arm'] == arm]; assert len(rs) == 24
        summary[arm] = {'n': 24, 'points': sum(r['total'] for r in rs), 'mean': sum(r['total'] for r in rs)/24,
            'strict_correct': sum(r['strict_correct'] for r in rs),
            'content_pct': sum(sum(r['atoms']) for r in rs)/72*100,
            'evidence_pct': sum(r['evidence'] for r in rs)/24*100,
            'faithfulness_pct': sum(r['faithfulness'] for r in rs)/24*100,
            'usage': {f: sum(r['usage'][f] for r in rs) for f in ['prompt_tokens', 'completion_tokens', 'total_tokens']},
            'category_means': {cat: sum(r['total'] for r in rs if r['category'] == cat)/4 for cat in sorted({r['category'] for r in rs})},
            'not_full_score': [{'id': r['id'], 'total': r['total'], 'reason': r['reason']} for r in rs if r['total'] != 5]}
    paired = []
    for q in sorted({r['id'] for r in rows}):
        scores = {r['arm']: r['total'] for r in rows if r['id'] == q}
        paired.append({'id': q, **scores, 'graph_minus_vector': scores['GraphRAG']-scores['VectorHybrid']})
    summary['paired_graph_vector'] = {'wins': sum(p['graph_minus_vector'] > 0 for p in paired),
        'ties': sum(p['graph_minus_vector'] == 0 for p in paired), 'losses': sum(p['graph_minus_vector'] < 0 for p in paired)}
    summary['failures'] = len(list(RUN.glob('answers/*/*/failure.json')))
    v.write(OUT / 'scores_PRIVATE.json', rows); v.write(OUT / 'summary.json', summary); v.write(OUT / 'paired.json', paired)
    print(__import__('json').dumps({k: {a: b for a,b in val.items() if a!='not_full_score'} if isinstance(val,dict) else val for k,val in summary.items()}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('action', choices=['prepare', 'aggregate']); args = p.parse_args()
    prepare() if args.action == 'prepare' else aggregate()
