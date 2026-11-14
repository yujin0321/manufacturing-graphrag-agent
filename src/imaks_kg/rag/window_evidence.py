"""Independent window metrics and confirmation checks; never calls the detector."""
from datetime import datetime, timedelta
from decimal import Decimal
import math
import statistics
from rdflib import URIRef

from . import comparison as c, vector as v
from .decision_evidence import number


class Frame:
    def __init__(self, rows, trigger_at, step=30):
        self.step = step
        if type(step) is not int or step <= 0:
            raise ValueError('Invalid sample interval')
        trigger = datetime.fromisoformat(trigger_at)
        self.rows = [row for row in rows if datetime.fromisoformat(row['timestamp']) <= trigger]
        self.times = [datetime.fromisoformat(row['timestamp']) for row in self.rows]
        if not self.times or self.times[-1] != trigger:
            raise ValueError('Trigger observation missing')
        if any(b <= a for a, b in zip(self.times, self.times[1:])):
            raise ValueError('Duplicate or unordered observations')
        if len({row['unit'] for row in self.rows}) != 1 or len({row['sensor_id'] for row in self.rows}) != 1:
            raise ValueError('Mixed sensors or units')
        self.values = [number(row['value']) for row in self.rows]
        self.segments = [0]
        for a, b in zip(self.times, self.times[1:]):
            self.segments.append(self.segments[-1] + ((b - a).total_seconds() != step))

    def window(self, i, n):
        if type(n) is not int or n < 1:
            raise ValueError('Invalid window length')
        first = i - n + 1
        return None if first < 0 or self.segments[first] != self.segments[i] else self.values[first:i + 1]

    def samples(self, seconds):
        value = number(seconds) / self.step
        if value < 1 or value != int(value):
            raise ValueError('Window must be a positive multiple of sample interval')
        return int(value)


def calibration(rows, cfg, recorded, trigger_at):
    """Check the sealed calibration against raw training observations."""
    if datetime.fromisoformat(cfg['train_end']) > datetime.fromisoformat(trigger_at):
        return {'state': 'unassessed', 'reason': 'calibration includes a period after trigger time'}
    values = [float(number(row['value'])) for row in rows if row['timestamp'] < cfg['train_end']]
    if not values:
        return {'state': 'inconsistent', 'reason': 'empty calibration period'}
    median = statistics.median(values)
    mad = statistics.median(abs(value - median) for value in values)
    sigma = 1.4826 * mad if mad else statistics.pstdev(values)
    method = '1.4826*MAD' if mad else 'std (MAD=0)'
    ok = (math.isclose(sigma, float(recorded['sigma']), rel_tol=1e-12, abs_tol=1e-15)
          and recorded['train_samples'] == len(values) and recorded['method'] == method)
    return {'state': 'consistent' if ok else 'inconsistent', 'sigma': str(sigma),
            'train_samples': len(values), 'method': method, 'train_end': cfg['train_end']}


def rule_proof(rows, trigger_at, rule, cfg, *, sigma=None):
    p = rule['params']
    kind = rule.get('executor') or p.get('op')
    if p.get('op') == 'stuck_exact':
        kind = 'stuck_exact'
    kinds = {'outside_run', 'window_change', 'stuck_std', 'stuck_exact', 'sustained_from_nominal', 'delta_gt', 'slope'}
    if kind not in kinds:
        return {'state': 'unassessed', 'operator': kind, 'reason': 'unsupported operator or partial precondition'}
    frame = Frame(rows, trigger_at, cfg['sample_seconds'])
    required, offset = int(p.get('confirm_observations', 1)), 0
    if kind in ('outside_run', 'slope'):
        required = int(p['readings'])
    elif kind == 'sustained_from_nominal':
        required = frame.samples(number(p['min_minutes']) * 60) + 1
    elif kind in ('stuck_std', 'stuck_exact'):
        width = int(p['window'] if kind == 'stuck_std' else p['value'])
        if width < 1 or number(width) != number(p['window'] if kind == 'stuck_std' else p['value']):
            raise ValueError('Invalid stuck window')
        if kind == 'stuck_std' or 'confirm_observations' in p or not p.get('duration_seconds'):
            offset = (width - 1) * frame.step
    if required < 1:
        raise ValueError('Invalid confirmation count')
    duration = number(p.get('duration_seconds', 0))
    if duration < 0:
        raise ValueError('Negative duration')
    if kind == 'slope' and (sigma is None or number(sigma) <= 0):
        return {'state': 'unassessed', 'operator': kind, 'reason': 'positive verified sigma required'}
    cache = {}

    def condition(i):
        if i in cache:
            return cache[i]
        value, metrics = frame.values[i], {}
        ready, ok = True, False
        if kind == 'outside_run':
            lo, hi = number(p['lo']), number(p['hi'])
            if lo > hi:
                raise ValueError('Reversed band')
            ok = value < lo or value > hi
            metrics = {'value': str(value), 'lo': str(lo), 'hi': str(hi)}
        elif kind == 'sustained_from_nominal':
            deviation = abs(value - number(p['nominal']))
            ok = deviation > number(p['delta'])
            metrics = {'absolute_deviation': str(deviation), 'delta': str(p['delta'])}
        elif kind == 'stuck_exact':
            sample = frame.window(i, width)
            ready = sample is not None
            ok = ready and all(x == value for x in sample)
            metrics = {'exact_equal_samples': width, 'value': str(value)}
        elif kind == 'delta_gt':
            n = frame.samples(p['window_seconds'])
            ready = frame.window(i, n + 1) is not None
            if ready:
                baseline = frame.values[i - n]
                delta = value - baseline
                ok = delta > number(p['value'])
                metrics = {'signed_delta': str(delta), 'baseline': str(baseline),
                           'baseline_at': frame.times[i - n].isoformat(), 'threshold': str(p['value'])}
        elif kind == 'window_change':
            n, smooth = frame.samples(number(p['window_min']) * 60), cfg['smooth_samples']
            if type(smooth) is not int or smooth < 1:
                raise ValueError('Invalid smoothing width')
            ready = frame.window(i, n + smooth) is not None
            direction = cfg['maint_direction']
            if direction not in ('away', 'any', 'absolute', 'either'):
                raise ValueError('Unknown window change direction')
            if ready:
                now = sum(frame.values[i - smooth + 1:i + 1]) / smooth
                before = sum(frame.values[i - n - smooth + 1:i - n + 1]) / smooth
                nominal = number(p['nominal'])
                away = abs(now - nominal) > abs(before - nominal)
                ok = abs(now - before) > number(p['delta']) and (direction != 'away' or away)
                metrics = {'now_mean': str(now), 'before_mean': str(before), 'absolute_delta': str(abs(now - before)),
                           'delta': str(p['delta']), 'direction': direction, 'away_from_nominal': away,
                           'smooth_samples': smooth, 'lookback_samples': n}
        elif kind == 'stuck_std':
            sample = frame.window(i, width)
            ready = sample is not None
            if ready:
                mean = sum(sample) / width
                std = (sum((x - mean) ** 2 for x in sample) / width).sqrt()
                ok = std < number(p['limit'])
                metrics = {'population_std': str(std), 'limit': str(p['limit']), 'window_samples': width}
        elif kind == 'slope':
            n = frame.samples(number(p['window_min']) * 60)
            if n < 2:
                raise ValueError('Slope requires two samples')
            sample = frame.window(i, n)
            ready = sample is not None
            if ready:
                mean = sum(sample) / n
                centered = [(number(j) - number(n - 1) / 2) * frame.step / 60 for j in range(n)]
                slope = sum(t * (x - mean) for t, x in zip(centered, sample)) / sum(t * t for t in centered)
                fitted_end = mean + slope * centered[-1]
                limit = number(p['k_sigma_per_min']) * number(sigma)
                away = (fitted_end - number(p['nominal'])) * slope > 0
                ok = abs(slope) > limit and away
                metrics = {'slope_per_minute': str(slope), 'limit': str(limit), 'sigma': str(sigma),
                           'fitted_end': str(fitted_end), 'away_from_nominal': away, 'window_samples': n}
        cache[i] = (bool(ok), ready, metrics)
        return cache[i]

    last = len(frame.values) - 1
    ok, ready, metrics = condition(last)
    if not ready:
        return {'state': 'inconsistent', 'operator': kind, 'reason': 'incomplete contiguous feature window'}
    if not ok:
        return {'state': 'inconsistent', 'operator': kind, 'reason': 'feature condition not satisfied', 'metrics': metrics}
    first = last
    while first > 0 and frame.segments[first] == frame.segments[first - 1] and condition(first - 1)[0]:
        first -= 1
    qualified = sum(duration == 0 or number((at - frame.times[first]).total_seconds()) > duration
                    for at in frame.times[first:last + 1])
    start = frame.times[first] - timedelta(seconds=offset)
    return {'state': 'consistent' if qualified == required else 'inconsistent', 'operator': kind,
            'metrics': metrics, 'condition_start': start.isoformat(), 'qualified_observations': qualified,
            'required_confirmation_observations': required, 'strict_duration_seconds': str(duration),
            'trigger_is_first_qualifying_confirmation': qualified == required,
            'elapsed_seconds': str((frame.times[last] - start).total_seconds()),
            'scope': 'feature, contiguous window, confirmation and first trigger; not anomaly truth or recovery'}


def checked_file(store, name):
    path = store.run_dir / name
    if name not in store.seal or v.digest(path.read_bytes()) != store.seal[name]:
        raise ValueError('Unsealed or changed runtime dependency: ' + name)
    return v.read(path)


def add_monitor_sources(evidence, store):
    """Explicit extra retrieval for source-slope/window definitions, not a repair of inputs."""
    monitor_alarms = [store.alarms.get(alarm['id'], {}) for alarm in evidence['alarms']]
    monitor_alarms = [alarm for alarm in monitor_alarms if alarm.get('kind') == 'kg_correlation_monitor']
    if not monitor_alarms:
        return {'added_source_ids': [], 'dependency_rule_nodes': []}
    bundle = checked_file(store, 'ir.json')
    nodes = set()
    for alarm in monitor_alarms:
        for rule in bundle['rules']:
            if rule.get('executor') == 'slope' and rule['sensor_id'] == alarm['sensor_id']:
                nodes.add(rule['kg_node'])
        for pair in bundle['correlation_pairs']:
            if pair['rule_ids'][0] + ':monitor' == alarm['rule_id'] and pair['effect_sensor'] == alarm['sensor_id']:
                nodes.update(pair['kg_nodes'])
                nodes.add(bundle['type_definitions']['CORRELATED']['kg_node'])
    links, records = store.source_links()
    selected = {source['chunk_id'] for source in evidence['untrusted_reference_documents']}
    added = []
    edge_keys = {tuple(edge[key] for key in ('s', 'p', 'o')) for edge in evidence['graph_paths']}
    for node in sorted(nodes):
        for cid in links.get(node, []):
            if cid not in selected:
                evidence['untrusted_reference_documents'].append({'chunk_id': cid, 'text': records[cid]['text']})
                added.append(cid)
                selected.add(cid)
        for predicate in (c.IM.sourceDocument, c.IM.hasProvenance):
            for target in store.base.objects(URIRef(node), predicate):
                edge = (node, str(predicate), str(target))
                if edge not in edge_keys:
                    evidence['graph_paths'].append(dict(zip(('s', 'p', 'o'), edge), depth=2))
                    edge_keys.add(edge)
    return {'added_source_ids': sorted(added), 'dependency_rule_nodes': sorted(nodes),
            'basis': 'sealed monitor pair, source slope IR and window definition; not a causal assertion'}


def monitor_proof(rows, alarm, store, bundle, params):
    """Validate configured promotion, never claim that the upstream event caused it."""
    if alarm.get('kind') != 'kg_correlation_monitor':
        return {'state': 'unassessed', 'reason': 'no executable rule for derived alarm'}
    signals = checked_file(store, 'signals.json')
    signal = next((s for s in signals if s['id'] == alarm.get('source_signal')), None)
    cfg = params['config']
    copy_fields = ('sensor_id', 'trigger_at', 'condition_start', 'trigger_value', 'unit',
                   'positive_samples', 'last_positive_at', 'report_split')
    reference_status = 'retained_signal'
    if signal is None:
        # postprocess removes promoted signals from signals.json by design.
        # Reconstruct their exact original content and require the recorded hash ID.
        candidates = [r for r in bundle['rules'] if r.get('executor') == 'slope' and r['sensor_id'] == alarm['sensor_id']]
        if len(candidates) != 1:
            return {'state': 'inconsistent', 'reason': 'source slope IR ambiguous or absent'}
        slope_ir = candidates[0]
        reconstructed = {key: alarm[key] for key in copy_fields}
        reconstructed.update(rule_id=slope_ir['rule_id'], kind=slope_ir['kind'],
                             sigma=params['sigma_by_sensor'][alarm['sensor_id']]['sigma'])
        expected_id = cfg['id_prefix']['alarm'] + v.digest(v.encoded(reconstructed))[:20]
        if expected_id != alarm.get('source_signal'):
            return {'state': 'inconsistent', 'reason': 'removed source signal cannot be reconstructed with exact hash'}
        signal = {**reconstructed, 'id': expected_id}
        reference_status = 'removed_after_promotion_reconstructed_with_exact_hash'
    if any(signal.get(k) != alarm.get(k) for k in copy_fields):
        return {'state': 'inconsistent', 'reason': 'promoted alarm differs from source signal'}
    cause = store.by_id.get(alarm.get('monitored_by'))
    pairs = [p for p in bundle['correlation_pairs'] if p['rule_ids'][0] + ':monitor' == alarm['rule_id']
             and p['effect_sensor'] == alarm['sensor_id'] and cause and p['cause_sensor'] == cause['sensor_id']]
    if len(pairs) != 1:
        return {'state': 'inconsistent', 'reason': 'monitor pair or source incident does not resolve'}
    pair = pairs[0]
    warnings = [store.alarms[aid] for aid in cause['alarm_ids']
                if store.alarms[aid]['kind'] == 'kg_threshold_warning']
    if not warnings or 'kg_threshold_warning' not in cause['kinds']:
        return {'state': 'inconsistent', 'reason': 'required warning gate absent'}
    if cfg['monitor_anchor'] == 'warning_trigger':
        warning = min(warnings, key=lambda a: (a['trigger_at'], a['id']))
        start = warning['trigger_at']
        if alarm.get('monitor_cause_alarm') != warning['id']:
            return {'state': 'inconsistent', 'reason': 'wrong warning anchor'}
    elif cfg['monitor_anchor'] == 'incident_start':
        start = cause['start']
    else:
        return {'state': 'unassessed', 'reason': 'unknown monitor anchor policy'}
    end = (datetime.fromisoformat(start) + timedelta(minutes=pair['window_min'])).isoformat()
    windows = checked_file(store, 'monitor_windows.json')
    if not any(w['cause_incident'] == cause['id'] and w['effect_sensor'] == alarm['sensor_id']
               and w['from'] == start and w['to'] == end for w in windows):
        return {'state': 'inconsistent', 'reason': 'configured monitor window absent'}
    value = number(alarm['trigger_value'])
    nominal = number(bundle['sensors'][alarm['sensor_id']]['nominal'])
    direction = pair['effect_direction']
    direction_ok = ((direction == 'below_nominal' and value < nominal) or
                    (direction == 'above_nominal' and value > nominal))
    if not (start <= alarm['trigger_at'] <= end and direction_ok):
        return {'state': 'inconsistent', 'reason': 'signal outside monitor window or direction'}
    ir = next((r for r in bundle['rules'] if r['rule_id'] == signal['rule_id'] and r['sensor_id'] == signal['sensor_id']), None)
    if ir is None or ir.get('executor') != 'slope':
        return {'state': 'inconsistent', 'reason': 'slope IR missing'}
    cal = calibration(rows, cfg, params['sigma_by_sensor'][alarm['sensor_id']], signal['trigger_at'])
    if cal['state'] != 'consistent':
        return {**cal, 'operator': 'derived_monitor', 'calibration': cal}
    source_proof = rule_proof(rows, signal['trigger_at'], ir, cfg, sigma=cal['sigma'])
    if source_proof.get('condition_start') != signal['condition_start']:
        source_proof = {**source_proof, 'state': 'inconsistent', 'reason': 'source slope condition start mismatch'}
    return {'state': source_proof['state'], 'operator': 'derived_monitor', 'condition_start': signal['condition_start'],
            'source_signal_id': signal['id'], 'source_trigger_check': source_proof, 'calibration': cal,
            'source_signal_reference_status': reference_status,
            'monitor_from': start, 'monitor_to': end, 'cause_incident': cause['id'], 'direction': direction,
            'evidence_rule_nodes': list(pair['kg_nodes']) + [bundle['type_definitions']['CORRELATED']['kg_node']],
            'source_rule_node': ir['kg_node'], 'scope': 'source slope and configured promotion; no causal confirmation'}
