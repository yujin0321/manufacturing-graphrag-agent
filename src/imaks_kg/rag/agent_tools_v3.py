"""V3 document adapter; reuse bounded historical tools without eager v2 inputs."""
from pathlib import Path
from . import agent_tools as legacy, agent_contract as contract
from . import retrieval_v3 as r3, vector as v, comparison as c, linking


def retrieval_lock(use_dense=False):
    files = [Path(__file__), Path(r3.__file__), Path(linking.__file__),
             r3.POLICY_PATH, linking.LEXICON_PATH, v.REPO_ROOT / c.KG_REL]
    lock = {'backend': 'graph_v3', 'dense_requested': use_dense,
            'files': {str(p.relative_to(v.REPO_ROOT)): v.digest(p.read_bytes()) for p in files}}
    manifest = r3.ROW_INDEX / 'manifest.json'
    if use_dense and manifest.exists():
        lock['row_index_manifest_sha256'] = v.digest(manifest.read_bytes())
    return lock


def search_documents(args, *, use_dense=False, call=v.api_call):
    args = contract.validate_call('search_documents', args)
    rows = r3.row_corpus()
    # No index autodetection: dense is an explicit caller choice.
    dense = r3.dense_ranking(args['question'], rows, call=call) if use_dense else None
    result = r3.build_context('graph_v3', args['question'], rows, dense, c.load_graph())
    by_id = {row['chunk_id']: row for row in rows}
    selected = result['selected_ids']
    docs = {row['doc_id'] for row in rows}
    named = [doc for doc in sorted(docs) if linking.find_spans(doc, args['question'])]
    return {'context': result['context'], 'context_tokens': result['context_tokens'],
            'sources': [by_id[cid] for cid in selected], 'selected_ids': selected,
            'graph_paths': result.get('traversed_edges', []),
            'uncovered_explicit_documents': [doc for doc in named if not any(by_id[cid]['doc_id'] == doc for cid in selected)],
            'retrieval_backend': 'graph_v3', 'dense_used': use_dense, 'retrieval_trace': result}


class ToolSession(legacy.ToolSession):
    """Keep the existing selection and call limits; load candidate data only on use."""
    def __init__(self, run_dir, *, explicit_event_ids=(), document_search=None, use_dense=False):
        for eid in explicit_event_ids:
            contract.validate_call('get_candidate_evidence', {'event_id': eid})
        self.allowed = set(explicit_event_ids)
        self.document_search = document_search or (lambda args: search_documents(args, use_dense=use_dense))
        self.attempts = 0
        self.evidence_tokens = 0
        self.stopped = False
        self.trace = []
        self.run = Path(run_dir)
        self.run.mkdir(parents=True, exist_ok=False)
        v.write(self.run / 'run_lock.json', {
            'contract_version': contract.VERSION, 'limits': contract.LIMITS,
            'retrieval': retrieval_lock(use_dense), 'explicit_event_ids': sorted(self.allowed),
            'contract_sha256': v.digest(Path(contract.__file__).read_bytes()),
            'legacy_tools_sha256': v.digest(Path(legacy.__file__).read_bytes()),
            'candidate_backend': 'legacy sealed historical detector store; not KG detector v2',
            'evaluation_run': False, 'gold_loaded': False, 'generation_calls': 0})
