"""Build arm-masked review packets after generation, then aggregate explicit decisions."""
import argparse
import random
from collections import Counter
import numpy as np
from imaks_kg.rag import vector as v

ROOT = v.REPO_ROOT
RUN = ROOT / 'kg_build/stored_edge_answers_20261028'
OUT = ROOT / 'evaluation/stored_edge_answers_20261028'


def verify():
    seal = v.read(RUN / 'complete.json')
    assert len(seal['files']) == 48
    assert all(v.digest((RUN / p).read_bytes()) == h for p, h in seal['files'].items())
    assert all(v.digest((ROOT / p).read_bytes()) == h for p, h in v.read(RUN / 'run_lock.json')['hashes'].items())
    assert all(v.digest((ROOT / p).read_bytes()) == h for p, h in v.read(v.LOCK)['hashes'].items())
    return seal


def prepare():
    seal = verify()
    OUT.mkdir(parents=True, exist_ok=False)
    keys = {k['id']: k for k in v.read(ROOT / 'evaluation/benchmark_yewon_v2_20261023/answer_key_PRIVATE.json')}
    paths = sorted(seal['files'])
    random.Random(20261028).shuffle(paths)
    mapping = {}; packets = []
    for i, path in enumerate(paths, 1):
        a = v.read(RUN / path); k = keys[a['id']]; label = f'R{i:02}'
        mapping[label] = {'path': path, 'sha256': seal['files'][path], 'id': a['id'], 'arm': a['arm']}
        packets.append({'review_id': label, 'id': a['id'], 'question': k['question'],
                        'atoms': k['answer_atoms'], 'evidence': [{'chunk_id': e['chunk_id'], 'text': e['text']} for e in k['evidence']],
                        'prohibited_claim': k['prohibited_claim'], 'answer': a['answer']})
    v.write(OUT / 'mapping_PRIVATE.json', mapping)
    v.write(OUT / 'packets_PRIVATE.json', packets)
    print('Prepared 48 arm-masked packets')


def aggregate():
    verify()
    decisions = v.read(OUT / 'decisions_PRIVATE.json')
    mapping = v.read(OUT / 'mapping_PRIVATE.json')
    assert len(decisions) == 48 and {d['review_id'] for d in decisions} == set(mapping)
    rows = []
    for d in decisions:
        m = mapping[d['review_id']]; a = v.read(RUN / m['path'])
        assert len(d['atoms']) == 3 and all(x in [0, 1] for x in d['atoms'])
        assert d['faithfulness'] in [0, 1] and 0 <= d['evidence'] <= 1 and d['reason']
        rows.append({**d, **m, 'total': sum(d['atoms']) + d['evidence'] + d['faithfulness'], 'usage': a['usage'], 'reviewer': 'Codex AI; arm labels masked; prior benchmark exposure; not independent human review'})
    summary = {}
    for arm in ['stored_edges_off', 'stored_edges_on']:
        rs = [r for r in rows if r['arm'] == arm]; assert len(rs) == 24
        summary[arm] = {'n': 24, 'points': sum(r['total'] for r in rs), 'mean': sum(r['total'] for r in rs)/24,
                        'strict_correct': sum(r['total'] == 5 for r in rs),
                        'content_pct': sum(sum(r['atoms']) for r in rs)/72*100,
                        'evidence_pct': sum(r['evidence'] for r in rs)/24*100,
                        'faithfulness_pct': sum(r['faithfulness'] for r in rs)/24*100,
                        'usage': {f: sum(r['usage'].get(f, 0) for r in rs) for f in ['prompt_tokens', 'completion_tokens', 'total_tokens']}}
    pairs = []
    for q in sorted({r['id'] for r in rows}):
        off = next(r for r in rows if r['id'] == q and r['arm'].endswith('off'))
        on = next(r for r in rows if r['id'] == q and r['arm'].endswith('on'))
        pairs.append({'id': q, 'off': off['total'], 'on': on['total'], 'delta': on['total']-off['total']})
    diffs = np.array([p['delta'] for p in pairs])
    means = np.random.default_rng(20261028).choice(diffs, size=(10000, 24), replace=True).mean(axis=1)
    summary['paired'] = {'mean_delta': float(diffs.mean()), 'wins': int(sum(diffs > 0)), 'ties': int(sum(diffs == 0)), 'losses': int(sum(diffs < 0)), 'bootstrap_95_percentile': np.quantile(means, [.025, .975]).tolist(), 'repeat_count': 1}
    summary['api_failures'] = len(list(RUN.glob('*/*/failure.json')))
    v.write(OUT / 'scores_PRIVATE.json', rows)
    v.write(OUT / 'paired.json', pairs)
    v.write(OUT / 'summary.json', summary)
    print(__import__('json').dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('action', choices=['prepare', 'aggregate']); args = p.parse_args()
    prepare() if args.action == 'prepare' else aggregate()
