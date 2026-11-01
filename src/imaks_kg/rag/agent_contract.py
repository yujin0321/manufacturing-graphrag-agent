"""Offline input/selection contract only; no model, retrieval or live UI wiring."""
import re

VERSION = 'agent-contract-v1-20261028'
LIMITS = {'tool_calls': 3, 'planning_calls': 2, 'answer_calls': 1,
          'embedding_calls': 1, 'evidence_tokens': 4000,
          'planning_completion_tokens': 512, 'answer_completion_tokens': 4096}
TOOLS = {
    'search_documents': {'required': {'question'}, 'optional': set()},
    'list_candidates': {'required': set(), 'optional': {'sensor_id', 'rule_id', 'kind', 'offset', 'limit'}},
    'get_candidate_evidence': {'required': {'event_id'}, 'optional': set()},
}


class ContractError(ValueError):
    pass


def validate_call(name, arguments):
    """Reject extra fields before any future tool can read files or call an API."""
    if not isinstance(name, str) or name not in TOOLS:
        raise ContractError('unknown_tool')
    if not isinstance(arguments, dict):
        raise ContractError('invalid_arguments')
    spec = TOOLS[name]
    if not spec['required'] <= arguments.keys() or arguments.keys() - spec['required'] - spec['optional']:
        raise ContractError('invalid_fields')
    args = dict(arguments)
    if name == 'search_documents':
        question = args['question']
        if not isinstance(question, str) or not question.strip() or len(question.encode('utf-8')) > 8000:
            raise ContractError('invalid_question')
    elif name == 'get_candidate_evidence':
        if not isinstance(args['event_id'], str) or not re.fullmatch(r'det-[0-9a-f]{20}', args['event_id']):
            raise ContractError('invalid_event_id')
    else:
        for key in ('sensor_id', 'rule_id'):
            if key in args and (not isinstance(args[key], str) or not re.fullmatch(r'[A-Za-z0-9_:-]{1,128}', args[key])):
                raise ContractError('invalid_filter')
        if 'kind' in args and args['kind'] not in ('document_rule', 'metadata_threshold'):
            raise ContractError('invalid_kind')
        for key, default, low, high in [('offset', 0, 0, 10000), ('limit', 10, 1, 20)]:
            value = args.get(key, default)
            if type(value) is not int or not low <= value <= high:
                raise ContractError('invalid_pagination')
            args[key] = value
    return args


def candidate_disposition(total_matches, returned_ids, intent):
    """Use the full filtered count, never just the first page, to allow selection."""
    if intent not in ('list', 'explain'):
        raise ContractError('invalid_intent')
    if type(total_matches) is not int or total_matches < 0 or not isinstance(returned_ids, list):
        raise ContractError('invalid_candidate_result')
    for event_id in returned_ids:
        validate_call('get_candidate_evidence', {'event_id': event_id})
    if len(set(returned_ids)) != len(returned_ids) or len(returned_ids) > total_matches:
        raise ContractError('invalid_candidate_result')
    if total_matches == 0:
        return {'status': 'insufficient_evidence', 'reason': 'no_matching_candidate'}
    if intent == 'list':
        return {'status': 'complete', 'reason': 'candidate_list_only'}
    if total_matches > 1:
        return {'status': 'needs_clarification', 'reason': 'multiple_candidates'}
    if len(returned_ids) != 1:
        raise ContractError('single_candidate_not_returned')
    return {'status': 'ready', 'event_id': returned_ids[0]}
