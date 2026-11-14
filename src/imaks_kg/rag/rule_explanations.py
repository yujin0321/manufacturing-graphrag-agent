"""Read-only rule boundaries and retrospective closure; no control or model calls."""
from datetime import datetime
from decimal import ROUND_FLOOR

from . import decision_evidence as d, vector as v, window_evidence as w

VERSION = 'rule-explanations-v1-20261115'
LIMITATIONS = [
    '경계 비교는 다른 조건을 고정한 수학적 가정이며 실제 센서 조작·최소 변경량·고장 해결책이 아닙니다.',
    '종료 검사는 사후 관측을 사용합니다. 발동 당시 알 수 있었던 정보와 구분해야 합니다.',
    '규칙 조건 해제와 설비 정상·조치 수행·인과적 회복은 서로 다릅니다.']


def boundary(rule, cfg, *, sigma=None):
    """Symbolic sides/equality, without an invented sensor resolution/epsilon."""
    p = rule['params']
    kind = rule.get('executor') or p.get('op')
    op = p.get('op')
    axes, gates = [], []

    def axis(name, limit, comparator):
        n = d.number(limit)
        axes.append({'feature': name, 'boundary': str(n), 'comparator': comparator,
                     'below': comparator == '<', 'equal': False, 'above': comparator == '>',
                     'meaning': 'this scalar predicate only, with other gates fixed'})

    if op in ('gt', 'lt'):
        axis('sensor_value', p['value'], '>' if op == 'gt' else '<')
    elif op == 'outside' or kind == 'outside_run':
        lo, hi = (p['value'], p['second']) if op == 'outside' else (p['lo'], p['hi'])
        if d.number(lo) > d.number(hi):
            raise ValueError('Reversed boundaries')
        axes.append({'feature': 'sensor_value', 'interval': [str(lo), str(hi)],
                     'comparator': 'x < lo or x > hi', 'at_lower': False, 'at_upper': False,
                     'degenerate_interval': d.number(lo) == d.number(hi),
                     'meaning': 'both interval endpoints do not satisfy this predicate'})
    elif op == 'delta_gt':
        axis('signed_current_minus_fixed_lookback', p['value'], '>')
        gates.append('complete contiguous lookback; signed increase, not absolute change')
    elif op == 'stuck_exact':
        width = int(p['value'])
        if width < 1 or d.number(width) != d.number(p['value']):
            raise ValueError('Invalid equal count')
        axes.append({'feature': 'consecutive_identical_samples', 'boundary': width,
                     'comparator': '>=', 'below': False, 'equal': True, 'above': True})
    elif kind == 'stuck_std':
        axis('population_standard_deviation', p['limit'], '<')
        gates.append('complete contiguous fixed window; a negative standard deviation is unreachable')
    elif kind in ('window_change', 'sustained_from_nominal'):
        axis('absolute_smoothed_change' if kind == 'window_change' else 'absolute_deviation_from_nominal', p['delta'], '>')
        if kind == 'window_change':
            gates.append('complete contiguous smoothing/lookback window')
            if cfg['maint_direction'] == 'away':
                gates.append('current mean must also be farther from nominal')
    elif kind == 'slope':
        if sigma is None or d.number(sigma) <= 0:
            return {'state': 'unassessed', 'reason': 'verified positive calibration sigma required'}
        axis('absolute_slope_per_minute', d.number(p['k_sigma_per_min']) * d.number(sigma), '>')
        gates += ['complete contiguous OLS window', '(fitted_end - nominal) * signed_slope > 0']
    else:
        return {'state': 'unassessed', 'reason': 'no supported direct executable rule boundary'}
    step = int(cfg['sample_seconds'])
    duration = d.number(p.get('duration_seconds', 0))
    confirm = int(p.get('confirm_observations', p.get('readings', 1)))
    if kind == 'sustained_from_nominal':
        count = d.number(p['min_minutes']) * 60 / step
        if count != int(count):
            raise ValueError('Nonintegral persistence window')
        confirm = int(count) + 1
    if step < 1 or duration < 0 or confirm < 1:
        raise ValueError('Invalid temporal boundary')
    first_qualified = (int((duration / step).to_integral_value(rounding=ROUND_FLOOR)) + 1) * step if duration else 0
    elapsed = first_qualified + (confirm - 1) * step
    return {'state': 'explained', 'operator': kind, 'axes': axes, 'other_required_gates': gates,
            'time_policy': {'sample_seconds': step, 'strict_duration_seconds': str(duration),
                            'at_duration_boundary_qualifies': False if duration else None,
                            'required_confirmations': confirm,
                            'earliest_trigger_elapsed_from_feature_streak_seconds': elapsed,
                            'feature_warmup_excluded': True},
            'hypothetical': True, 'minimal_physical_intervention': False,
            'explanation': '경계의 같음·미만·초과와 시간 조건을 각각 확인했습니다. 다른 조건까지 만족해야 발동합니다.'}


def feature_states(rows, rule, cfg, *, sigma=None):
    """Independent predicate series; no detector implementation is called."""
    frame = w.Frame(rows, rows[-1]['timestamp'], cfg['sample_seconds'])
    if rule['params'].get('op') in ('gt', 'lt', 'outside'):
        return [d.predicate(value, rule['params']) for value in frame.values]
    traced = w.rule_proof(rows, rows[-1]['timestamp'], rule, cfg, sigma=sigma, feature_trace=True)
    if 'states' not in traced:
        raise ValueError('Unsupported closure feature: ' + traced.get('reason', 'unknown'))
    return traced['states']


def closure(rows, alarm, states, *, sample_seconds=30, clear=1):
    """Last positive + observed clearing, gap or data end, starting at the trigger.

    With clear=2 one nonqualifying point may be bridged, as the adapter declares.
    Does not certify machine recovery or causal effects.
    """
    if type(clear) is not int or clear < 1 or len(rows) != len(states):
        raise ValueError('Invalid closure inputs')
    frame = w.Frame(rows, rows[-1]['timestamp'], sample_seconds)
    indices = [i for i, row in enumerate(rows) if row['timestamp'] == alarm['trigger_at']]
    if len(indices) != 1 or states[indices[0]] is not True:
        return {'state': 'inconsistent', 'reason': 'trigger predicate absent'}
    start = indices[0]
    last, normals, first_clear, decision, at = start, 0, None, 'open_at_data_end', None
    for i in range(start + 1, len(rows)):
        if frame.segments[i] != frame.segments[i - 1]:
            decision, at = 'data_gap_unconfirmed', rows[i - 1]['timestamp']
            break
        if states[i] is True:
            last, normals, first_clear = i, 0, None
        elif states[i] is False:
            normals += 1
            first_clear = first_clear or rows[i]['timestamp']
            if normals >= clear:
                decision, at = 'rule_condition_cleared', rows[i]['timestamp']
                break
        else:
            decision, at = 'feature_unavailable', rows[i]['timestamp']
            break
    expected_end = rows[last]['timestamp']
    checks = {'last_positive_at': alarm['last_positive_at'] == expected_end}
    if 'status' in alarm:
        status = {'rule_condition_cleared': 'recovered'}.get(decision, decision)
        checks['status'] = alarm['status'] == status
        checks['normal_confirmed_at'] = alarm.get('normal_confirmed_at') == (at if decision == 'rule_condition_cleared' else None)
        checks['closed_at'] = alarm.get('closed_at') == (at if decision != 'open_at_data_end' else None)
        if decision == 'rule_condition_cleared':
            checks['clear_started_at'] = alarm.get('clear_started_at') == first_clear
    return {'state': 'consistent' if all(checks.values()) else 'inconsistent', 'checks': checks,
            'closure_kind': decision, 'last_positive_at': expected_end,
            'first_clearing_observation_at': first_clear, 'normal_confirmed_at': at if decision == 'rule_condition_cleared' else None,
            'closed_at': at, 'required_clear_observations': clear,
            'machine_recovery_verified': False, 'retrospective': True,
            'explanation': {'rule_condition_cleared': '규칙 조건 해제를 관측했습니다. 설비 회복이나 조치 효과 확인은 아닙니다.',
                            'open_at_data_end': '자료 종료까지 해제를 확인하지 못했습니다. 회복으로 표시하지 않습니다.',
                            'data_gap_unconfirmed': '관측 공백으로 연속 상태를 확인할 수 없습니다. 회복으로 표시하지 않습니다.',
                            'feature_unavailable': '필요한 특징값을 계산할 수 없어 종료 판단을 보류합니다.'}[decision]}


def build(store, incident_id, *, rows=None, input_sha256=None, trace_cache=None):
    incidents = {i['id']: i for i in w.checked_file(store, 'incidents.json')}
    incident = incidents[incident_id]
    alarms = {a['id']: a for a in w.checked_file(store, 'events.json')}
    bundle = w.checked_file(store, 'ir.json')
    params = w.checked_file(store, 'params.json')
    cfg = params['config']
    if rows is None:
        rows, input_sha256 = d.observations(incident['sensor_id'])
    if any(row['sensor_id'] != incident['sensor_id'] for row in rows):
        raise ValueError('Mixed observation sensors')
    cache = trace_cache if trace_cache is not None else {}
    results = []
    for aid in incident['alarm_ids']:
        alarm = alarms[aid]
        rules = [r for r in bundle['rules'] if r['rule_id'] == alarm['rule_id'] and r['sensor_id'] == alarm['sensor_id']]
        derived = alarm.get('kind') == 'kg_correlation_monitor'
        if derived:
            monitor = w.monitor_proof(rows, alarm, store, bundle, params)
            rules = [r for r in bundle['rules'] if r['kg_node'] == monitor.get('source_rule_node')
                     and r['sensor_id'] == alarm['sensor_id']] if monitor['state'] == 'consistent' else []
        if len(rules) != 1:
            results.append({'alarm_id': aid, 'boundary': {'state': 'unassessed', 'reason': 'rule binding unavailable'},
                            'closure': {'state': 'unassessed', 'reason': 'rule binding unavailable'}})
            continue
        rule = rules[0]
        sigma = None
        if rule.get('executor') == 'slope':
            cal = w.calibration(rows, cfg, params['sigma_by_sensor'][alarm['sensor_id']], alarm['trigger_at'])
            if cal['state'] != 'consistent':
                results.append({'alarm_id': aid, 'boundary': {'state': 'unassessed', 'reason': 'calibration unavailable'},
                                'closure': {'state': 'unassessed', 'reason': 'calibration unavailable'}})
                continue
            sigma = cal['sigma']
        bounds = boundary(rule, cfg, sigma=sigma)
        bounds['observed_trigger'] = {'at': alarm['trigger_at'], 'sensor_value': alarm['trigger_value'], 'unit': alarm['unit']}
        bounds['rule_reference'] = {'ir_id': rule['ir_id'], 'kg_node': rule['kg_node'],
                                    'params_file_sha256': store.seal['params.json'], 'ir_file_sha256': store.seal['ir.json']}
        key = v.digest(v.encoded({'rule': rule, 'cfg': cfg, 'sigma': sigma, 'input': input_sha256}))
        if key not in cache:
            cache[key] = feature_states(rows, rule, cfg, sigma=sigma)
        checked = closure(rows, alarm, cache[key], sample_seconds=cfg['sample_seconds'],
                          clear=rule['params'].get('clear_observations', 1))
        if derived:
            bounds['other_required_gates'].append('sealed monitor promotion gate, window and direction; source slope boundary only')
            checked['scope'] = 'source slope alarm closure; monitor promotion checked separately, not causal recovery'
        results.append({'alarm_id': aid, 'rule_id': alarm['rule_id'], 'ir_id': rule['ir_id'],
                        'boundary': bounds, 'closure': checked})
    expected_end = max(alarms[aid]['last_positive_at'] for aid in incident['alarm_ids'])
    return {'version': VERSION, 'incident_id': incident_id, 'items': results,
            'incident_end_aggregation': {'state': 'consistent' if incident['end'] == expected_end else 'inconsistent',
                                         'stored_end': incident['end'], 'max_alarm_last_positive': expected_end,
                                         'scope': 'end aggregation only; does not verify cluster membership'},
            'counts': {state: sum(item['closure']['state'] == state for item in results)
                       for state in ('consistent', 'inconsistent', 'unassessed')},
            'input_sha256': input_sha256, 'engine_seal_sha256': v.digest(v.encoded(store.seal)),
            'new_api_calls': 0, 'limitations': LIMITATIONS}


def for_saved_run(run):
    from . import team_runtime
    checked = d.for_saved_run(run)
    answer = v.read(run / 'answer.json')
    if checked['decision_evidence']['status'] != 'consistent':
        raise ValueError('Saved trigger evidence is inconsistent')
    store = team_runtime.store(answer['integration']['detector_profile'])
    report = build(store, answer['xai']['incident']['id'])
    return {'run_id': run.name, 'rule_explanations': report, 'new_api_calls': 0,
            'answer_unchanged_sha256': checked['answer_unchanged_sha256'],
            'scope': 'current retrospective rule checks; old answer not regenerated or regraded'}
