"""Free development audit of every prepared profile's stored incident evidence."""
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from imaks_kg.detection import rules
from imaks_kg.rag import decision_evidence as d, incident_tools as tools, team_runtime as runtime, vector as v


def main():
    groups, _, profile = rules.read_inputs()
    report = {'new_api_calls': 0, 'gold_loaded': False,
              'scope': 'development grounding and supported trigger audit; not anomaly accuracy',
              'audit_version': d.VERSION, 'profiles': []}
    for name in runtime.PROFILES:
        store = runtime.store(name)
        counts, operators, problems = Counter(), Counter(), []
        for incident in store.incidents:
            evidence = tools.get_incident_evidence(store, {'incident_id': incident['id']})
            added = d.add_dependencies(evidence, store)
            checked = d.build(evidence, store, rows=groups[incident['sensor_id']],
                              input_sha256=profile['output_sha256'][rules.INPUT])
            counts['incidents'] += 1
            counts['alarms'] += len(checked['items'])
            counts['added_dependency_sources'] += len(added['added_source_ids'])
            counts['grounding_inconsistent'] += checked['status'] != 'consistent'
            counts.update(item['trigger_check']['state'] for item in checked['items'])
            operators.update(item['trigger_check'].get('operator', 'unknown') for item in checked['items'])
            if checked['issues']:
                problems.append({'incident_id': incident['id'], 'issues': checked['issues']})
        item = {'profile': name, 'counts': dict(counts), 'operators': dict(operators), 'problems': problems,
                'engine_seal_sha256': v.digest(v.encoded(store.seal))}
        report['profiles'].append(item)
        print({key: item[key] for key in ('profile', 'counts')}, flush=True)
    report['passed'] = all(not item['problems'] for item in report['profiles'])
    report['totals'] = {key: sum(item['counts'].get(key, 0) for item in report['profiles'])
                        for key in ('incidents', 'alarms', 'consistent', 'unassessed', 'inconsistent', 'grounding_inconsistent')}
    v.write(ROOT / 'kg_build/window_evidence_20261114/after.json', report)
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
