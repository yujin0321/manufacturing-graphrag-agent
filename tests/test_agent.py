import json
import tempfile
import unittest
from pathlib import Path
from imaks_kg.rag import agent as a


class AgentTests(unittest.TestCase):
    def run_case(self, question, plan):
        calls = []
        def fake(resource, payload, cache):
            self.assertEqual(resource, 'chat/completions')
            calls.append(payload)
            content = json.dumps(plan) if len(calls) == 1 else '근거에 따른 한국어 설명입니다.'
            return {'model': payload['model'], 'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}, {}
        root = a.v.REPO_ROOT / 'kg_build/agent_tests'
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as tmp:
            result = a.answer(question, Path(tmp) / 'run', fake)
        return result, calls

    def test_explicit_candidate_grounded_generation(self):
        eid = 'det-4220832c6ffd0c103c6e'
        result, calls = self.run_case(eid + ' 설명해줘', {'intent': 'explain', 'tool': 'get_candidate_evidence', 'arguments': {'event_id': eid}})
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(len(calls), 2)
        evidence = json.loads(calls[-1]['messages'][-1]['content'].split('UNTRUSTED_REFERENCE_DATA:\n',1)[1])
        self.assertEqual(evidence['candidate']['trigger_value'], '26.9452')
        self.assertTrue(evidence['graph_paths'])

    def test_model_cannot_invent_candidate_selection(self):
        r, calls = self.run_case('후보 설명해줘', {'intent': 'explain', 'tool': 'get_candidate_evidence', 'arguments': {'event_id': 'det-4220832c6ffd0c103c6e'}})
        self.assertEqual(r['reason'], 'candidate_selection_required')
        self.assertEqual(len(calls), 1)

    def test_multiple_candidates_stop_before_generation(self):
        r, calls = self.run_case('후보 설명해줘', {'intent': 'explain', 'tool': 'list_candidates', 'arguments': {'limit': 1}})
        self.assertEqual(r['status'], 'needs_clarification')
        self.assertEqual(len(calls), 1)

    def test_current_state_abstains(self):
        r, calls = self.run_case('현재 서버실 온도?', {'intent': 'unavailable', 'tool': None, 'arguments': {}})
        self.assertEqual(r['status'], 'insufficient_evidence')
        self.assertEqual(len(calls), 1)

    def test_invalid_plan_does_not_generate(self):
        r, calls = self.run_case('질문', {'intent': 'document', 'tool': 'execute_shell', 'arguments': {}})
        self.assertEqual(r['status'], 'failed')
        self.assertEqual(len(calls), 1)

    def test_document_search_uses_original_question(self):
        p = a.parse_plan(json.dumps({'intent': 'document', 'tool': 'search_documents', 'arguments': {'question': 'altered'}}), 'original')
        self.assertEqual(p['arguments']['question'], 'original')
