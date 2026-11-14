import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from imaks_kg.rag import agent_contract, demo, incident_agent as agent, incident_tools, vector as v
from tests.claim_fixtures import selected_claims


class PlanTests(unittest.TestCase):
    def test_unknown_tool_and_observation_arguments_are_rejected(self):
        for tool, arguments in [('run_shell', {}), ('list_incidents', {'value': 212}),
                                ('get_incident_evidence', {'incident_id': '../x'})]:
            with self.assertRaises(agent_contract.ContractError):
                agent.parse_plan(json.dumps({'intent': 'explain', 'tool': tool, 'arguments': arguments}))

    def test_document_plan_cannot_smuggle_arguments(self):
        with self.assertRaises(agent_contract.ContractError):
            agent.parse_plan(json.dumps({'intent': 'document', 'tool': None, 'arguments': {'question': 'changed'}}))


@unittest.skipUnless((incident_tools.ENGINE_OVERLAY / 'complete.json').exists(), 'prepare the sealed incident demo first')
class IncidentAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = incident_tools.IncidentStore()
        cls.incident_id = cls.store.incidents[0]['id']

    def setUp(self):
        scratch = v.REPO_ROOT / 'kg_build/xai_tests'
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.assertTrue(Path(self.temp.name).resolve().is_relative_to(scratch.resolve()))
        self.run = Path(self.temp.name) / 'run'
        self.stages = []
        self.plan = {'intent': 'explain', 'tool': 'get_incident_evidence',
                     'arguments': {'incident_id': self.incident_id}}
        self.bad_citation = False
        self.reject = False
        self.extra_prose = False

    def tearDown(self):
        self.temp.cleanup()

    def call(self, resource, payload, cache):
        self.assertEqual(resource, 'chat/completions')
        stage = Path(cache).name
        self.stages.append(stage)
        if stage == 'plan':
            text = json.dumps(self.plan)
        elif stage == 'draft':
            content = json.loads(payload['messages'][-1]['content'])
            self.assertTrue(content['claim_catalog'])
            text = selected_claims(content, unknown=self.bad_citation)
            if self.extra_prose:
                selected = json.loads(text)
                selected['answer'] = '관측값은 99999도이며 실제 비상정지를 완료했습니다.'
                text = json.dumps(selected)
        elif stage == 'verify':
            content = json.loads(payload['messages'][-1]['content'])
            evidence = content['evidence']
            self.assertTrue(all(cid in content['answer'] for cid in content['claim_binding_summary']['claim_ids']))
            self.assertEqual(evidence['incident']['id'], self.incident_id)
            self.assertIn('execution_parameters', evidence)
            self.assertIn('implementation_policy', evidence)
            self.assertTrue(evidence['type_definitions'])
            self.assertTrue(any(row['chunk_id'] == 'SOP-002:p2:table6:chunk'
                                for row in evidence['untrusted_reference_documents']))
            text = json.dumps({'approved': not self.reject, 'issues': ['원문 조건 오류'] if self.reject else []})
        else:
            raise AssertionError(stage)
        return {'model': payload['model'], 'choices': [{'finish_reason': 'stop', 'message': {'content': text}}],
                'usage': {'total_tokens': 10}}, {'mock': True}

    def test_selected_incident_flows_through_tools_generation_and_verification(self):
        result = agent.answer('과거 사건 ' + self.incident_id + '를 설명해 주세요.', self.run, self.call, store=self.store)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(self.stages, ['plan', 'draft', 'verify'])
        self.assertEqual(result['candidate_ids'], [self.incident_id])
        self.assertTrue(result['sources'])
        self.assertTrue(result['graph_paths'])
        self.assertTrue(result['verification'][0]['approved'])
        self.assertLessEqual(result['xai']['context_tokens'], 4000)
        trace = v.read(self.run / 'tools/trace.json')
        self.assertEqual([step['tool'] for step in trace['steps']], ['get_incident_evidence', 'get_correlated_incidents'])
        shown = demo.presentation(self.run)
        self.assertEqual(shown['xai']['incident']['id'], self.incident_id)
        self.assertTrue(shown['verification'][0]['approved'])
        self.assertNotIn('plan_request', shown)
        self.assertTrue(result['claims'])
        self.assertTrue(result['xai']['claim_binding']['published'])
        self.assertEqual(shown['claims'], result['claims'])

    def test_model_cannot_choose_an_unmentioned_incident(self):
        result = agent.answer('온도 사건을 설명해 주세요.', self.run, self.call, store=self.store)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.stages, ['plan'])
        self.assertEqual(v.read(self.run / 'tools/trace.json')['steps'][0]['error_code'], 'incident_selection_required')

    def test_multiple_matches_require_selection_without_a_draft(self):
        self.plan = {'intent': 'explain', 'tool': 'list_incidents', 'arguments': {}}
        result = agent.answer('과거 사건을 설명해 주세요.', self.run, self.call, store=self.store)
        self.assertEqual(result['status'], 'needs_clarification')
        self.assertEqual(self.stages, ['plan'])
        self.assertIn('선택', result['answer'])

    def test_unique_filtered_match_can_be_explained(self):
        from collections import Counter
        counts = Counter(row['sensor_id'] for row in self.store.incidents)
        target = next(row for row in self.store.incidents if counts[row['sensor_id']] == 1)
        self.incident_id = target['id']
        self.plan = {'intent': 'explain', 'tool': 'list_incidents', 'arguments': {'sensor_id': target['sensor_id']}}
        result = agent.answer(target['sensor_id'] + '의 과거 사건을 설명해 주세요.', self.run, self.call, store=self.store)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['candidate_ids'], [target['id']])
        self.assertEqual(len(v.read(self.run / 'tools/trace.json')['steps']), 3)

    def test_unknown_claim_blocks_the_answer(self):
        self.bad_citation = True
        result = agent.answer('사건 ' + self.incident_id + ' 설명', self.run, self.call, store=self.store)
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertFalse(result['verification'][0]['approved'])

    def test_valid_ids_with_extra_model_prose_are_withheld_before_ai_verification(self):
        self.extra_prose = True
        result = agent.answer('사건 ' + self.incident_id + ' 설명', self.run, self.call, store=self.store)
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertEqual(result['reason'], 'claim_binding_failed')
        self.assertEqual(self.stages, ['plan', 'draft'])
        self.assertFalse(result['claims'])
        self.assertNotIn('99999', result['answer'])

    def test_negative_model_verification_is_preserved(self):
        self.reject = True
        result = agent.answer('사건 ' + self.incident_id + ' 설명', self.run, self.call, store=self.store)
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertIn('원문 조건 오류', result['verification'][0]['issues'])

    def test_live_query_stops_before_model_or_tools(self):
        result = agent.answer('현재 센서 측정값을 조회해줘.', self.run, self.call, store=self.store)
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertEqual(self.stages, [])
        self.assertFalse((self.run / 'tools').exists())

    def test_document_route_preserves_original_question(self):
        self.plan = {'intent': 'document', 'tool': None, 'arguments': {}}
        forwarded = {'status': 'complete', 'answer': '문서 답변', 'sources': [], 'graph_paths': [], 'usage': [], 'verification': []}
        with patch.object(agent.team_retrieval, 'Retriever'), patch.object(agent.documents, 'answer', return_value=forwarded) as answer:
            result = agent.answer('MAINT-05의 조건은?', self.run, self.call, store=self.store)
        self.assertEqual(answer.call_args.args[0], 'MAINT-05의 조건은?')
        self.assertEqual(result['answer'], '문서 답변')
        self.assertEqual(result['xai']['claim_binding']['status'], 'not_applied')
        self.assertFalse(result['claims'])


if __name__ == '__main__':
    unittest.main()
