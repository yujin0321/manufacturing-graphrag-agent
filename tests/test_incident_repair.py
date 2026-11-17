from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from imaks_kg.rag import incident_agent as agent, incident_tools, vector as v
from tests.claim_fixtures import selected_claims


@unittest.skipUnless((incident_tools.ENGINE_OVERLAY / 'complete.json').exists(), 'restore runtime first')
class RepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = incident_tools.IncidentStore()
        cls.incident_id = cls.store.incidents[0]['id']

    def setUp(self):
        scratch = v.REPO_ROOT / 'kg_build/repair_tests'
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.run = Path(self.temp.name) / 'run'
        self.stages = []
        self.reject_forever = False
        self.bad_citation = False
        self.transport_failure = False
        self.invalid_verifier = False
        self.repair_feedback = None

    def tearDown(self):
        self.temp.cleanup()

    def call(self, resource, payload, cache):
        stage = Path(cache).name
        self.stages.append(stage)
        content = json.loads(payload['messages'][-1]['content'])
        if stage == 'plan':
            text = json.dumps({'intent': 'explain', 'tool': 'get_incident_evidence',
                               'arguments': {'incident_id': self.incident_id}})
        elif stage.startswith('draft'):
            if self.transport_failure:
                raise RuntimeError('synthetic transport failure')
            if stage == 'draft2':
                self.repair_feedback = content['previous_verification_issues']
            text = selected_claims(content, all_conditions=stage == 'draft2', unknown=stage == 'draft' and self.bad_citation)
        else:
            if self.invalid_verifier:
                text = 'invalid JSON'
            else:
                approved = not self.reject_forever and (stage == 'verify2' or self.bad_citation)
                text = json.dumps({'approved': approved, 'issues': [] if approved else ['조건 설명을 보완하세요.']})
        return {'model': payload['model'], 'choices': [{'finish_reason': 'stop', 'message': {'content': text}}]}, {'mock': True}

    def answer(self):
        return agent.answer('과거 사건 ' + self.incident_id + ' 설명', self.run, self.call,
                            store=self.store, repair_incident=True)

    def test_one_repair_passes_with_both_attempts_preserved(self):
        result = self.answer()
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(self.stages, ['plan', 'draft', 'verify', 'draft2', 'verify2'])
        self.assertEqual([item['approved'] for item in result['verification']], [False, True])
        self.assertEqual(self.repair_feedback, ['조건 설명을 보완하세요.'])
        self.assertEqual(result['xai']['claim_binding']['attempt'], 2)
        self.assertNotEqual(v.read(self.run / 'draft.json')['answer'], v.read(self.run / 'draft2.json')['answer'])
        self.assertTrue((self.run / 'draft.json').exists())
        self.assertTrue((self.run / 'draft2.json').exists())
        self.assertEqual(len(v.read(self.run / 'tools/trace.json')['steps']), 2)
        self.assertEqual(v.read(self.run / 'agent_lock.json')['limits']['drafts'], 2)

    def test_repeated_rejection_stops_after_two_attempts(self):
        self.reject_forever = True
        result = self.answer()
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertEqual(self.stages, ['plan', 'draft', 'verify', 'draft2', 'verify2'])
        self.assertFalse((self.run / 'draft3.json').exists())

    def test_invented_claim_cannot_be_overruled_by_ai_approval(self):
        self.bad_citation = True
        result = self.answer()
        self.assertEqual(result['status'], 'complete')
        self.assertFalse(result['verification'][0]['approved'])
        self.assertTrue(any('Unknown' in issue for issue in self.repair_feedback))
        self.assertNotIn('CLM-' + '0' * 16, result['answer'])
        self.assertEqual(self.stages, ['plan', 'draft', 'draft2', 'verify2'])

    def test_transport_failure_is_not_retried(self):
        self.transport_failure = True
        result = self.answer()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.stages, ['plan', 'draft'])
        self.assertFalse(v.read(self.run / 'failure.json')['automatic_retry'])

    def test_invalid_verifier_is_not_a_repair_signal(self):
        self.invalid_verifier = True
        result = self.answer()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.stages, ['plan', 'draft', 'verify'])

    def test_corrupted_evidence_is_blocked_before_drafting(self):
        original = incident_tools.HANDLERS['get_incident_evidence']
        def tampered(store, args):
            data = deepcopy(original(store, args))
            data['alarms'][0]['unit'] = 'F'
            return data
        with patch.dict(incident_tools.HANDLERS, {'get_incident_evidence': tampered}):
            result = self.answer()
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertEqual(result['reason'], 'decision_evidence_inconsistent')
        self.assertEqual(self.stages, ['plan'])
        self.assertEqual(result['xai']['decision_evidence']['status'], 'inconsistent')

    def test_repair_flag_requires_a_boolean_before_any_model_call(self):
        with self.assertRaises(ValueError):
            agent.answer('question', self.run, self.call, repair_incident=1)
        self.assertFalse(self.stages)
        self.assertFalse(self.run.exists())


if __name__ == '__main__':
    unittest.main()
