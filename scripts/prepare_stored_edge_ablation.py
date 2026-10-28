"""Freeze offline paired contexts; never load answer keys or call an API."""
import json
from unittest.mock import patch
from imaks_kg.rag import vector as v, graph_v2 as g, comparison as c, ablation as a
from run_graph_ablation import questions

ROOT = v.REPO_ROOT
OUT = ROOT / 'kg_build/stored_edge_ablation_20261028'


def main():
    old = ROOT / 'kg_build/graph_ablation_20261024'
    seal = v.read(old / 'complete.json')
    assert len(seal['files']) == 90
    assert all(v.digest((old / p).read_bytes()) == h for p, h in seal['files'].items())
    assert all(v.digest((ROOT / p).read_bytes()) == h for p, h in v.read(old / 'lock.json')['hashes'].items())
    qs = questions()
    OUT.mkdir(parents=True, exist_ok=False)
    rows = []
    with patch.object(v, 'urlopen', side_effect=AssertionError('Offline only')):
        corpus, matrix, metadata = v.load_index(v.DEFAULT_INDEX)
        graph = c.load_graph()
        policy = {**v.read(g.POLICY_PATH), 'max_graph_tokens': 0}
        for q in qs:
            query, _ = v.embed([q['question']], metadata['config'], v.DEFAULT_INDEX / 'query_cache', g.cached_embeddings)
            dense = v.retrieve(corpus, matrix, query[0], len(corpus))
            pair = {}
            for arm in ['stored_edges_off', 'stored_edges_on']:
                active = {**policy, 'traverse_predicates': []} if arm.endswith('off') else policy
                trace = g.context(q['question'], corpus, dense, graph, active)
                result = a.select(q['question'], corpus, dense, trace)
                result['variant'] = arm
                result['traversal_policy'] = active
                assert result['graph_cards'] == 0 and result['context_tokens'] <= 4000
                if arm.endswith('off'):
                    assert not any(e['kind'] == 'stored_edge' for e in trace['traversed_edges'])
                else:
                    assert result['context'] == v.read(old / 'C' / q['id'] / 'retrieval.json')['context']
                v.write(OUT / arm / q['id'] / 'input.json', {'id': q['id'], 'split': q['split'], 'question': q['question'], **result})
                v.write(OUT / arm / q['id'] / 'trace.json', trace)
                pair[arm] = result
            off, on = pair.values()
            assert off['shared_prefix'] == on['shared_prefix']
            assert off['shared_ranked_ids'] == on['shared_ranked_ids']
            rows.append({'id': q['id'], 'split': q['split'], 'same_context': off['context'] == on['context'],
                         'same_chunk_set': set(off['selected_ids']) == set(on['selected_ids']),
                         'off_tokens': off['context_tokens'], 'on_tokens': on['context_tokens']})
    files = ['scripts/prepare_stored_edge_ablation.py', 'scripts/run_graph_ablation.py',
             'src/imaks_kg/rag/vector.py', 'src/imaks_kg/rag/ablation.py',
             'src/imaks_kg/rag/graph_v2.py', 'src/imaks_kg/rag/comparison.py',
             'docs/graphrag_v2/retrieval_policy.json', 'docs/vector_rag_v1/config.json', c.KG_REL]
    files += [f'docs/benchmark_yewon_v2_20261023/questions_{s}.jsonl' for s in ['dev', 'eval']]
    summary = {s: {'n': len(rs := [r for r in rows if r['split'] == s]),
                   'changed_contexts': sum(not r['same_context'] for r in rs),
                   'changed_chunk_sets': sum(not r['same_chunk_set'] for r in rs)} for s in ['dev', 'eval']}
    v.write(OUT / 'audit.json', {'api_calls': 0, 'gold_loaded': False, 'old_files_verified': 90,
             'summary': summary, 'pairs': rows, 'hashes': {str(p): v.digest((ROOT / p).read_bytes()) for p in files}})
    v.write(OUT / 'complete.json', {'files': {p.relative_to(OUT).as_posix(): v.digest(p.read_bytes()) for p in OUT.rglob('*.json')}})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
