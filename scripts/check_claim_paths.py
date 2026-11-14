"""Free path continuity audit for every prepared incident claim catalog."""
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from imaks_kg.detection import rules
from imaks_kg.rag import claim_binding as cb, decision_evidence as d, team_runtime as rt, incident_tools, vector as v, evidence_paths


def main():
    groups, _, profile = rules.read_inputs()
    output = {'version': evidence_paths.VERSION, 'new_api_calls': 0, 'gold_loaded': False,
              'scope': 'declared path continuity, direction and frozen text metadata; not semantic accuracy', 'profiles': []}
    example_written = False
    for name in rt.PROFILES:
        store, counts, failures = rt.store(name), Counter(), []
        for incident in store.incidents:
            evidence = incident_tools.get_incident_evidence(store, {'incident_id': incident['id']})
            d.add_dependencies(evidence, store)
            proof = d.build(evidence, store, rows=groups[incident['sensor_id']], input_sha256=profile['output_sha256'][rules.INPUT])
            catalog = cb.build_catalog(evidence, proof, store)
            counts['incidents'] += 1
            for claim in catalog['claims']:
                checked = claim['evidence_paths']
                counts['claims'] += 1
                counts[checked['status']] += 1
                if checked['status'] == 'broken':
                    failures.append({'incident_id': incident['id'], 'claim_id': claim['claim_id'], 'breaks': checked['breaks']})
                for path in checked['paths']:
                    counts['paths'] += 1
                    counts.update('step_' + step['kind'] for step in path['steps'])
                    for branch in path['branches']:
                        counts['document_branches'] += 1
                        counts.update('step_' + step['kind'] for step in branch['steps'])
            if not example_written:
                v.write(ROOT / 'kg_build/claim_paths_20261115/example.json',
                        {'example_kind': 'offline_path_catalog_not_a_model_run', 'catalog': catalog})
                example_written = True
        row = {'profile': name, 'counts': dict(counts), 'failures': failures,
               'engine_seal_sha256': v.digest(v.encoded(store.seal))}
        output['profiles'].append(row)
        print({'profile': name, 'counts': dict(counts)}, flush=True)
    keys = ('incidents', 'claims', 'complete', 'scope_only', 'broken', 'paths',
            'step_rdf', 'step_runtime_reference', 'step_file_lookup', 'document_branches')
    output['totals'] = {key: sum(row['counts'].get(key, 0) for row in output['profiles']) for key in keys}
    output['passed'] = all(not row['failures'] for row in output['profiles'])
    v.write(ROOT / 'kg_build/claim_paths_20261115/path_audit.json', output)
    if not output['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
