"""Bounded, retrieval-only tool session. No generation or network fallback."""
import time
from pathlib import Path
from . import agent_contract as contract, vector as v, graph_v2 as g, comparison as c
from . import event_explain


def candidate_store():
    root = event_explain.OUT
    seal = v.read(root / 'complete.json')
    required = {'events.json', 'rules.json', 'candidate_events.ttl', 'input_lock.json', 'summary.json'}
    if not required.issubset(seal):
        raise ValueError('Incomplete seal')
    for name, checksum in seal.items():
        if Path(name).name != name or v.digest((root / name).read_bytes()) != checksum:
            raise ValueError('Invalid seal')
    return v.read(root / 'events.json'), v.read(root / 'rules.json')['rules'], seal


def list_candidates(args):
    events, rules, _ = candidate_store()
    if 'sensor_id' in args and args['sensor_id'] not in {r['sensor_id'] for r in rules}:
        raise contract.ContractError('unknown_filter_id')
    if 'rule_id' in args and args['rule_id'] not in {s for r in rules for s in (r['id'], r.get('document_rule'))}:
        raise contract.ContractError('unknown_filter_id')
    registry = {r['id']: r for r in rules}
    matches = [e for e in events
               if ('sensor_id' not in args or e['sensor_id'] == args['sensor_id'])
               and ('kind' not in args or e['kind'] == args['kind'])
               and ('rule_id' not in args or args['rule_id'] in
                    (e['rule_id'], registry[e['rule_id']].get('document_rule')))]
    matches.sort(key=lambda e: (e['trigger_at'], e['id']))
    start, end = args['offset'], args['offset'] + args['limit']
    keys = ('id', 'sensor_id', 'rule_id', 'kind', 'trigger_at', 'trigger_value', 'unit')
    return {'total_matches': len(matches), 'items': [{k: e[k] for k in keys} for e in matches[start:end]],
            'next_offset': end if end < len(matches) else None}


def search_documents(args):
    # Reuse the existing retriever unchanged. Missing cached questions fail closed.
    result = g.retrieve(args['question'])
    corpus, _ = v.source_records()
    by_id = {r['chunk_id']: r for r in corpus}
    return {'selected_ids': result['selected_ids'],
            'sources': [by_id[cid] for cid in result['selected_ids']],
            'graph_paths': result['traversed_edges'], 'context': result['context'],
            'context_tokens': result['context_tokens'],
            'uncovered_explicit_documents': result['uncovered_explicit_documents'],
            'embedding_api': result['embedding_api']}


class ToolSession:
    """One request; explicit IDs are trusted caller input, never model arguments."""
    def __init__(self, run_dir, *, explicit_event_ids=(), document_search=None):
        for eid in explicit_event_ids:
            contract.validate_call('get_candidate_evidence', {'event_id': eid})
        self.allowed = set(explicit_event_ids)
        self.document_search = document_search or search_documents
        self.attempts = 0
        self.evidence_tokens = 0
        self.stopped = False
        self.trace = []
        self.run = Path(run_dir)
        self.run.mkdir(parents=True, exist_ok=False)
        c.load_graph()
        _, _, seal = candidate_store()
        v.write(self.run / 'run_lock.json', {
            'contract_version': contract.VERSION, 'limits': contract.LIMITS,
            'kg_sha256': v.digest((v.REPO_ROOT / c.KG_REL).read_bytes()),
            'detector_seal': seal, 'explicit_event_ids': sorted(self.allowed),
            'code_sha256': v.digest(Path(__file__).read_bytes()),
            'contract_sha256': v.digest(Path(contract.__file__).read_bytes()),
            'policy_sha256': v.digest(g.POLICY_PATH.read_bytes()),
            'index_manifest_sha256': v.digest(v.encoded(v.load_index(v.DEFAULT_INDEX)[2])),
            'evaluation_run': False, 'gold_loaded': False,
            'custom_document_search': document_search is not None, 'generation_calls': 0})

    def execute(self, name, arguments):
        started = time.perf_counter()
        args = None
        data = None
        code = None
        self.attempts += 1
        try:
            if self.stopped:
                raise contract.ContractError('session_stopped')
            if self.attempts > contract.LIMITS['tool_calls']:
                raise contract.ContractError('tool_limit_exceeded')
            args = contract.validate_call(name, arguments)
            if name == 'list_candidates':
                data = list_candidates(args)
                if data['total_matches'] == 1 and len(data['items']) == 1:
                    self.allowed.add(data['items'][0]['id'])
            elif name == 'get_candidate_evidence':
                if args['event_id'] not in self.allowed:
                    raise contract.ContractError('candidate_selection_required')
                events, _, _ = candidate_store()
                if args['event_id'] not in {e['id'] for e in events}:
                    raise contract.ContractError('unknown_event_id')
                _, _, retrieval, _, _ = event_explain.prepare(args['event_id'])
                data = dict(retrieval['context'], context_tokens=retrieval['context_tokens'])
            else:
                data = self.document_search(args)
            count = data.get('context_tokens', 0)
            if self.evidence_tokens + count > contract.LIMITS['evidence_tokens']:
                raise contract.ContractError('context_budget_exceeded')
            self.evidence_tokens += count
        except contract.ContractError as exc:
            code = str(exc)
        except FileNotFoundError:
            code = 'local_resource_or_embedding_cache_missing'
        except Exception:
            code = 'tool_execution_failed'
        if code:
            self.stopped = True
            data = None
        result = {'contract_version': contract.VERSION,
                  'tool': name if isinstance(name, str) and name in contract.TOOLS else None,
                  'status': 'error' if code else 'ok', 'data': data,
                  'error': {'code': code, 'message': '도구 실행을 중단했습니다. 자동 재시도하지 않습니다.'} if code else None,
                  'warnings': ['정적 문서·과거 후보 조회이며 실제 설비 상태나 확정 원인이 아닙니다.']}
        self.trace.append({'attempt': self.attempts, 'tool': result['tool'],
                           'arguments': args, 'status': result['status'], 'error_code': code,
                           'result_sha256': v.digest(v.encoded(result)),
                           'seconds': time.perf_counter() - started})
        v.write(self.run / f'tool_{self.attempts:02d}.json', result)
        v.write(self.run / 'trace.json', {'steps': self.trace, 'stopped': self.stopped,
                                         'evidence_tokens': self.evidence_tokens})
        return result
