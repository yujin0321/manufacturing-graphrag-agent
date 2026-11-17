"""Audit boundaries and retrospective closure for every prepared profile, offline."""
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from imaks_kg.detection import rules
from imaks_kg.rag import rule_explanations as x, team_runtime as rt, vector as v, window_evidence


def main():
    groups, _, profile = rules.read_inputs()
    output = {'version': x.VERSION, 'new_api_calls': 0, 'gold_loaded': False, 'profiles': [],
              'code_sha256': {module.__name__: v.digest(Path(module.__file__).read_bytes()) for module in (x, window_evidence)},
              'input_sha256': profile['output_sha256'][rules.INPUT],
              'scope': 'development rule policy consistency; not anomaly accuracy or machine recovery'}
    for name in rt.PROFILES:
        store, cache, counts, failures = rt.store(name), {}, Counter(), []
        for incident in store.incidents:
            report = x.build(store, incident['id'], rows=groups[incident['sensor_id']],
                             input_sha256=profile['output_sha256'][rules.INPUT], trace_cache=cache)
            counts['incidents'] += 1
            if report['incident_end_aggregation']['state'] != 'consistent':
                failures.append({'incident_id': incident['id'], 'end_aggregation': report['incident_end_aggregation']})
            for item in report['items']:
                counts['alarms'] += 1
                counts['boundary_' + item['boundary']['state']] += 1
                counts['closure_' + item['closure']['state']] += 1
                counts[item['closure'].get('closure_kind', 'closure_unassessed')] += 1
                if item['closure']['state'] == 'inconsistent':
                    failures.append({'incident_id': incident['id'], **item})
        row = {'profile': name, 'counts': dict(counts), 'failures': failures,
               'engine_seal_sha256': v.digest(v.encoded(store.seal))}
        output['profiles'].append(row)
        print({'profile': name, 'counts': dict(counts), 'failures': len(failures)}, flush=True)
    keys = set().union(*(row['counts'] for row in output['profiles']))
    output['totals'] = {key: sum(row['counts'].get(key, 0) for row in output['profiles']) for key in sorted(keys)}
    output['passed'] = all(not row['failures'] for row in output['profiles'])
    v.write(ROOT / 'kg_build/xai_extensions_20261115/rule_audit.json', output)
    if not output['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
