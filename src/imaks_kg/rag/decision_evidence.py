"""Independent, scoped checks for incident evidence. No labels or model calls."""
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation

from rdflib import Literal, URIRef

from . import comparison as c, vector as v
from ..detection import rules

VERSION = 'decision-evidence-v1-20261114'


def number(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('Invalid numeric evidence') from None
    if not result.is_finite():
        raise ValueError('Non-finite numeric evidence')
    return result


def predicate(value, params):
    op = params.get('op')
    if op not in ('gt', 'lt', 'outside'):
        return None
    value, limit = number(value), number(params['value'])
    if op == 'outside':
        upper = number(params['second'])
        if limit > upper:
            raise ValueError('Reversed threshold bounds')
        return value < limit or value > upper
    return value > limit if op == 'gt' else value < limit


def threshold_proof(rows, trigger_at, params, *, confirm=1, sample_seconds=30):
    """Check strict > duration and consecutive fully-qualified points.

    Only simple point predicates are supported. Does not validate recovery,
    event grouping, classification, partial preconditions or causal effects.
    """
    if params.get('op') not in ('gt', 'lt', 'outside'):
        return {'state': 'unassessed', 'reason': 'operator requires an unimplemented feature/window check'}
    if type(confirm) is not int or confirm < 1 or type(sample_seconds) is not int or sample_seconds < 1:
        raise ValueError('Invalid confirmation policy')
    duration = number(params.get('duration_seconds', 0))
    if duration < 0:
        raise ValueError('Negative duration')
    times = [datetime.fromisoformat(row['timestamp']) for row in rows]
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('Duplicate or nonmonotonic observations')
    trigger = datetime.fromisoformat(trigger_at)
    indices = [index for index, at in enumerate(times) if at == trigger]
    if len(indices) != 1:
        return {'state': 'inconsistent', 'reason': 'trigger observation missing or duplicated'}
    last = indices[0]
    first = last
    if not predicate(rows[last]['value'], params):
        return {'state': 'inconsistent', 'point_satisfied': False, 'reason': 'point predicate not satisfied'}
    while first > 0:
        if (times[first] - times[first - 1]).total_seconds() != sample_seconds:
            break
        if not predicate(rows[first - 1]['value'], params):
            break
        if rows[first - 1]['unit'] != rows[last]['unit']:
            raise ValueError('Mixed units in condition window')
        first -= 1
    elapsed = number((trigger - times[first]).total_seconds())
    qualifying = sum(duration == 0 or number((at - times[first]).total_seconds()) > duration
                     for at in times[first:last + 1])
    return {'state': 'consistent' if qualifying == confirm else 'inconsistent', 'point_satisfied': True,
            'strict_duration_seconds': str(duration), 'elapsed_seconds': str(elapsed),
            'consecutive_observations': last - first + 1, 'qualified_observations': qualifying,
            'required_confirmation_observations': confirm, 'condition_start': times[first].isoformat(),
            'trigger_is_first_qualifying_confirmation': qualifying == confirm,
            'scope': 'simple predicate, contiguous persistence, and first confirmation only'}


def observations(sensor_id):
    path = v.REPO_ROOT / rules.INPUT
    expected = v.read(v.REPO_ROOT / 'preprocessed/sensors/profile.json')['output_sha256'][rules.INPUT]
    if v.digest(path.read_bytes()) != expected:
        raise ValueError('Frozen observations changed')
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != rules.FIELDS:
            raise ValueError('Observation field allowlist changed')
        rows = [row for row in reader if row['sensor_id'] == sensor_id]
    return rows, expected


def build(evidence, store, *, rows=None, input_sha256=None):
    """Bind provided evidence to sealed alarms, raw samples, IR and real sources."""
    incident = evidence['incident']
    original = store.by_id.get(incident['id'])
    issues, items = [], []
    if original is None or any(original.get(key) != value for key, value in incident.items() if key in original):
        issues.append('incident differs from authorized sealed incident')
    sensor_id = original['sensor_id'] if original else incident['sensor_id']
    if rows is None:
        rows, input_sha256 = observations(sensor_id)
    by_time = {}
    for row in rows:
        by_time.setdefault(row['timestamp'], []).append(row)
    sensor = next(store.base.subjects(c.IM.identifier, Literal(sensor_id)), None)
    unit = str(store.base.value(sensor, c.IM.unit)) if sensor else None
    ir = v.read(store.run_dir / 'ir.json')['rules']
    supplied = {source['chunk_id']: source for source in evidence['untrusted_reference_documents']}
    canonical, _ = v.source_records()
    canonical = {source['chunk_id']: source for source in canonical}
    links, _ = store.source_links()
    if len(supplied) != len(evidence['untrusted_reference_documents']):
        issues.append('duplicate source identifiers')
    for cid, source in supplied.items():
        if cid not in canonical or source['text'] != canonical[cid]['text']:
            issues.append('supplied source unknown or altered: ' + cid)
    for item in evidence.get('execution_parameters', []):
        expected = next((rule for rule in ir if rule['ir_id'] == item['ir_id']), {})
        if any(expected.get(key) != value for key, value in item.items()):
            issues.append('execution parameters differ from sealed IR')
    required_alarm_ids = set(original['alarm_ids']) if original else set()
    if {alarm['id'] for alarm in evidence['alarms']} != required_alarm_ids or len(evidence['alarms']) != len(required_alarm_ids):
        issues.append('alarm set differs from authorized incident')
    expected_rule_nodes = {str(node) for node in store.overlay.objects(store.event_node(incident['id']), URIRef('https://example.org/imaks/detection/engine#matchedRule'))}
    if {rule['kg_node'] for rule in evidence['matched_rules']} != expected_rule_nodes:
        issues.append('matched rule set differs from sealed overlay')
    for matched in evidence['matched_rules']:
        node = URIRef(matched['kg_node'])
        for field, prop in (('condition_text', c.IM.conditionText), ('response_text', c.IM.responseText)):
            if matched[field] != str(store.base.value(node, prop) or ''):
                issues.append('KG rule text mismatch: ' + matched['rule_id'])
        if set(matched['source_chunks']) != set(links.get(matched['kg_node'], [])):
            issues.append('rule source links differ from canonical provenance')
        if any(cid not in supplied for cid in links.get(matched['kg_node'], [])):
            issues.append('matched rule source missing from evidence')
    for alarm in evidence['alarms']:
        errors = []
        sealed = store.alarms.get(alarm['id'], {})
        if alarm['id'] not in required_alarm_ids or any(sealed.get(k) != val for k, val in alarm.items()):
            errors.append('alarm differs from authorized sealed alarm')
        matches = by_time.get(alarm['trigger_at'], [])
        if len(matches) != 1:
            errors.append('raw trigger observation missing or duplicated')
        else:
            row = matches[0]
            if row['sensor_id'] != sensor_id or number(row['value']) != number(alarm['trigger_value']):
                errors.append('trigger value or sensor differs from raw observation')
            if row['unit'] != alarm['unit'] or alarm['unit'] != unit:
                errors.append('observation, alarm and KG units disagree')
        candidates = [rule for rule in ir if rule['rule_id'] == alarm['rule_id'] and rule['sensor_id'] == sensor_id]
        rule = candidates[0] if len(candidates) == 1 else None
        source_ids = links.get(rule['kg_node'], []) if rule else []
        for cid in source_ids:
            if cid not in supplied or cid not in canonical or supplied[cid]['text'] != canonical[cid]['text']:
                errors.append('required source missing or altered: ' + cid)
        if rule and not source_ids:
            errors.append('executable rule has no canonical source')
        proof = {'state': 'unassessed', 'reason': 'derived alarm or complex window operator'}
        if rule:
            params = rule['params']
            supported = rule.get('executor') == 'threshold_scan' or 'confirm_observations' in params
            if supported:
                proof = threshold_proof(rows, alarm['trigger_at'], params,
                    confirm=params.get('confirm_observations', 1))
                if proof['state'] == 'inconsistent':
                    errors.append('trigger predicate, persistence or first confirmation inconsistent')
                if proof.get('state') == 'consistent':
                    # Legacy immediate rules record trigger time, two-point rules record streak start.
                    expected_start = proof['condition_start'] if params.get('duration_seconds') or 'confirm_observations' in params else alarm['trigger_at']
                    if alarm['condition_start'] != expected_start:
                        errors.append('recorded condition start differs from contiguous raw observations')
        items.append({'evidence_id': 'DEC-' + v.digest(alarm['id'].encode())[:12],
            'alarm_id': alarm['id'], 'observation': {'sensor_id': sensor_id, 'at': alarm['trigger_at'],
                'value': alarm['trigger_value'], 'unit': alarm['unit']},
            'rule': {'rule_id': alarm['rule_id'], 'ir_id': rule['ir_id'] if rule else None,
                'kg_node': rule['kg_node'] if rule else None, 'params': rule['params'] if rule else None,
                'source_chunks': source_ids}, 'trigger_check': proof, 'issues': errors,
            'grounding_status': 'consistent' if not errors else 'inconsistent'})
        issues.extend(errors)
    return {'version': VERSION, 'status': 'inconsistent' if issues else 'consistent',
            'input_file': rules.INPUT, 'input_sha256': input_sha256, 'items': items, 'issues': issues,
            'scope': 'evidence grounding and supported simple trigger checks only',
            'not_verified': ['complex window/slope/stuck operators', 'event classification and recovery',
                             'all natural-language claims', 'causality or action execution']}


def summary(report):
    return {'status': report['status'], 'grounded_alarm_count': len(report['items']),
            'simple_trigger_checks': sum(item['trigger_check']['state'] == 'consistent' for item in report['items']),
            'unassessed_trigger_count': sum(item['trigger_check']['state'] == 'unassessed' for item in report['items']),
            'scope': report['scope'], 'not_verified': report['not_verified']}


def for_saved_run(run):
    """Recheck an old incident run without modifying it or regenerating its answer."""
    from . import team_runtime
    answer = v.read(run / 'answer.json')
    if not answer.get('xai', {}).get('incident'):
        raise ValueError('Saved run has no incident evidence')
    store = team_runtime.store(answer['integration']['detector_profile'])
    if v.read(run / 'store_lock.json') != store.lock():
        raise ValueError('Saved run belongs to a different sealed store')
    evidence = v.read(run / 'retrieval.json')['context']
    if evidence['incident']['id'] != answer['xai']['incident']['id']:
        raise ValueError('Saved answer and retrieved incident disagree')
    return {'run_id': run.name, 'audit_version': VERSION, 'new_api_calls': 0,
            'answer_unchanged_sha256': v.digest((run / 'answer.json').read_bytes()),
            'decision_evidence': build(evidence, store)}
