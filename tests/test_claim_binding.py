from copy import deepcopy
import json
import unittest

from imaks_kg.rag import claim_binding as cb, decision_evidence as d, incident_tools, vector as v
from tests.claim_fixtures import selected_claims


@unittest.skipUnless((incident_tools.ENGINE_OVERLAY / 'complete.json').exists(), 'restore runtime first')
class ClaimBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = incident_tools.IncidentStore()
        cls.evidence = incident_tools.get_incident_evidence(cls.store, {'incident_id': cls.store.incidents[0]['id']})
        cls.proof = d.build(cls.evidence, cls.store)
        cls.catalog = cb.build_catalog(cls.evidence, cls.proof, cls.store)
        cls.selection = selected_claims({'claim_catalog': cb.selector_view(cls.catalog)})

    def test_claim_types_have_distinct_methods_and_real_references(self):
        claims = self.catalog['claims']
        self.assertEqual({c['claim_type'] for c in claims}, set(cb.TYPES))
        for claim in claims:
            self.assertTrue(claim['evidence_refs'])
            self.assertFalse(claim['validation']['domain_truth_certified'])
        observation = next(c for c in claims if c['claim_type'] == 'observation')
        self.assertEqual(observation['evidence_refs'][0]['file_sha256'], self.proof['input_sha256'])
        condition = next(c for c in claims if c['claim_type'] == 'condition')
        self.assertEqual(condition['evidence_refs'][0]['kind'], 'decision_check')
        recommendation = next(c for c in claims if c['claim_type'] == 'recommendation')
        self.assertEqual(recommendation['validation']['method'], 'frozen_kg_fields_and_provenance')
        self.assertEqual(recommendation['values']['action_executed'], 'not_verified')

    def test_bound_output_contains_only_canonical_claim_text_and_mandatory_limits(self):
        result = cb.bind(self.selection, self.catalog, '관측·조건·조치 설명')
        self.assertEqual(result['status'], 'bound')
        self.assertFalse(result['published'])
        self.assertEqual(len(result['automatically_added_claim_ids']), 2)
        rendered = cb.render(result)
        self.assertFalse(cb.check_rendered(rendered, result))
        self.assertTrue(all(claim['text'] in rendered and claim['claim_id'] in rendered for claim in result['claims']))
        self.assertTrue(any(claim['claim_type'] == 'interpretation' for claim in result['claims']))

    def test_wrong_number_and_unbound_sentence_cannot_be_smuggled_into_rendered_answer(self):
        result = cb.bind(self.selection, self.catalog, '설명')
        text = cb.render(result)
        changed = text.replace(self.proof['items'][0]['observation']['value'], '99999')
        self.assertTrue(cb.check_rendered(changed, result))
        self.assertTrue(cb.check_rendered(text + '\n실제 비상정지를 완료했습니다.', result))

    def test_valid_ids_plus_arbitrary_model_prose_are_rejected(self):
        selection = json.loads(self.selection)
        selection['answer'] = '온도는 99999도이며 정비를 실행했습니다.'
        result = cb.bind(json.dumps(selection), self.catalog, '설명')
        self.assertEqual(result['status'], 'withheld')
        self.assertFalse(result['claims'])
        with self.assertRaises(ValueError):
            cb.render(result)

    def test_unknown_or_foreign_incident_ids_are_rejected(self):
        evidence = incident_tools.get_incident_evidence(self.store, {'incident_id': self.store.incidents[1]['id']})
        catalog = cb.build_catalog(evidence, d.build(evidence, self.store), self.store)
        foreign = catalog['claims'][0]['claim_id']
        selected = json.loads(self.selection)
        selected['claim_ids'].append(foreign)
        result = cb.bind(json.dumps(selected), self.catalog, '설명')
        self.assertEqual(result['status'], 'withheld')
        self.assertEqual(result['withheld_claims'][0]['claim_id'], foreign)

    def test_duplicate_oversized_malformed_and_duplicate_field_selections_are_rejected(self):
        cid = self.catalog['claims'][0]['claim_id']
        for raw in ('not JSON', json.dumps({'claim_ids': [cid, cid]}),
                    json.dumps({'claim_ids': [cid] * 17}), json.dumps({'claim_ids': [1]}),
                    '{"claim_ids":[],"claim_ids":["' + cid + '"]}'):
            self.assertEqual(cb.bind(raw, self.catalog, '설명')['status'], 'withheld')

    def test_catalog_text_tampering_is_detected(self):
        catalog = deepcopy(self.catalog)
        catalog['claims'][0]['text'] = 'invented statement'
        result = cb.bind(self.selection, catalog, '설명')
        self.assertEqual(result['status'], 'withheld')
        self.assertIn('integrity', result['issues'][0])

    def test_missing_observation_condition_or_requested_recommendation_is_withheld(self):
        by_type = {kind: next(c['claim_id'] for c in self.catalog['claims'] if c['claim_type'] == kind) for kind in cb.TYPES}
        for ids in ([by_type['observation']], [by_type['condition']],
                    [by_type['observation'], by_type['condition']]):
            self.assertEqual(cb.bind(json.dumps({'claim_ids': ids}), self.catalog, '관측·조건·조치 설명')['status'], 'withheld')

    def test_proof_from_a_different_incident_is_not_relabelled(self):
        proof = deepcopy(self.proof)
        proof['items'][0]['alarm_id'] = 'det31-' + '0' * 20
        with self.assertRaises(ValueError):
            cb.build_catalog(self.evidence, proof, self.store)

    @unittest.skipUnless((v.REPO_ROOT / 'kg_build/graphrag_live/team_main_20261113_01/answer.json').exists(), 'restore saved sample')
    def test_old_answer_is_not_retroactively_marked_as_bound(self):
        from imaks_kg.rag import demo
        run = v.REPO_ROOT / 'kg_build/graphrag_live/team_main_20261113_01'
        before = (run / 'answer.json').read_bytes()
        result = cb.catalog_for_saved_run(run)
        self.assertEqual(result['past_answer_claim_binding'], 'not_performed')
        self.assertEqual(result['new_api_calls'], 0)
        self.assertEqual(demo.presentation(run)['xai']['claim_binding']['status'], 'not_recorded')
        self.assertEqual(before, (run / 'answer.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
