"""Offline protocol audit of incident claim catalogs; no model quality grading."""
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import tiktoken
from imaks_kg.detection import rules
from imaks_kg.rag import claim_binding as cb, decision_evidence as d, team_runtime as rt, incident_tools, vector as v


def main():
    groups, _, profile = rules.read_inputs()
    encoding = tiktoken.get_encoding(v.read(v.CONFIG)['context_encoding'])
    budget = v.read(v.CONFIG)['context_token_budget']
    output = {'version': cb.VERSION, 'new_api_calls': 0, 'gold_loaded': False,
              'scope': 'catalog integrity and minimal selector protocol; no real LLM selection quality measurement', 'profiles': []}
    example_written = False
    for name in rt.PROFILES:
        store = rt.store(name)
        counts, maxima, issues = Counter(), {'catalog_claims': 0, 'selector_tokens': 0}, []
        for incident in store.incidents:
            evidence = incident_tools.get_incident_evidence(store, {'incident_id': incident['id']})
            if name.startswith('seongho_'):
                evidence['incident']['severity_origin'] = incident.get('severity_origin',
                    '표시용 ADVISORY 기본값. 성호 원본은 심각도를 분류하지 않음')
            d.add_dependencies(evidence, store)
            proof = d.build(evidence, store, rows=groups[incident['sensor_id']], input_sha256=profile['output_sha256'][rules.INPUT])
            catalog = cb.build_catalog(evidence, proof, store)
            view = cb.selector_view(catalog)
            tokens = len(encoding.encode(json.dumps(view, ensure_ascii=False)))
            ids = [next((claim['claim_id'] for claim in view if claim['claim_type'] == kind), None)
                   for kind in ('observation', 'condition', 'recommendation')]
            binding = cb.bind(json.dumps({'claim_ids': [cid for cid in ids if cid]}), catalog, '관측과 조건 및 조치를 설명')
            ok = binding['status'] == 'bound' and tokens <= budget and not cb.check_rendered(cb.render(binding), binding)
            if not ok:
                issues.append({'incident_id': incident['id'], 'issues': binding['issues'], 'selector_tokens': tokens})
            counts['incidents'] += 1
            counts['catalogs_valid'] += ok
            counts.update(claim['claim_type'] for claim in catalog['claims'])
            maxima['catalog_claims'] = max(maxima['catalog_claims'], len(catalog['claims']))
            maxima['selector_tokens'] = max(maxima['selector_tokens'], tokens)
            if not example_written and ok:
                v.write(ROOT / 'kg_build/claim_binding_20261114/example.json',
                        {'example_kind': 'offline_code_selection_not_a_model_run', 'catalog': catalog,
                         'binding': binding, 'answer': cb.render(binding)})
                example_written = True
        row = {'profile': name, 'counts': dict(counts), 'maxima': maxima, 'issues': issues}
        output['profiles'].append(row)
        print({'profile': name, 'counts': dict(counts), 'maxima': maxima}, flush=True)
    output['passed'] = all(not row['issues'] for row in output['profiles'])
    output['total_incidents'] = sum(row['counts']['incidents'] for row in output['profiles'])
    v.write(ROOT / 'kg_build/claim_binding_20261114/catalog_audit.json', output)
    if not output['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
