"""Offline Agent v3 integration tests; actual retrieval, mocked model transport."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from imaks_kg.rag import agent_v3 as a, agent_tools_v3 as t

EVENT = 'det-4220832c6ffd0c103c6e'


class AgentV3Tests(unittest.TestCase):
    def setUp(self):
        root = a.v.REPO_ROOT / 'kg_build/agent_v3_tests'
        root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name) / 'run'
        self.calls = []

    def fake(self, resource, payload, cache):
        self.assertEqual(resource, 'chat/completions', 'No embeddings in default BM25 mode')
        self.calls.append(payload)
        content = json.dumps(self.plan) if len(self.calls) == 1 else '문서 근거에 따른 설명입니다.'
        return {'model': payload['model'], 'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}, {'mock': True}

    def document_plan(self):
        self.plan = {'intent': 'document', 'tool': 'search_documents', 'arguments': {'question': 'altered'}}

    def test_real_document_route_has_rows_paths_and_no_v2_resources(self):
        self.document_plan()
        with patch.object(t.legacy, 'candidate_store', side_effect=AssertionError('No candidate dependency')), \
             patch.object(a.v, 'load_index', side_effect=AssertionError('No v2 index')), \
             patch.object(t.r3, 'dense_ranking', side_effect=AssertionError('No dense autodetection')):
            result = a.answer('서버실 온도 관련 규칙과 조치는?', self.run, self.fake)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(result['graph_paths'])
        ids = [row['chunk_id'] for row in result['sources']]
        self.assertIn('SOP-003:p1:table1:chunk#r5', ids)
        final_input = self.calls[-1]['messages'][-1]['content']
        self.assertIn('[SOP-003:p1:table1:chunk#r5]', final_input)
        self.assertNotIn('altered', final_input)
        retrieval = a.v.read(self.run / 'retrieval.json')
        self.assertEqual(retrieval['retrieval_backend'], 'graph_v3')
        self.assertFalse(retrieval['dense_used'])
        self.assertLessEqual(retrieval['context_tokens'], 4000)

    def test_document_route_never_reads_private_answers(self):
        self.document_plan()
        read_bytes, read_text = Path.read_bytes, Path.read_text
        def safe_bytes(path, *args, **kwargs):
            self.assertNotIn('evaluation', path.parts)
            self.assertNotIn('PRIVATE', path.name)
            return read_bytes(path, *args, **kwargs)
        def safe_text(path, *args, **kwargs):
            self.assertNotIn('evaluation', path.parts)
            self.assertNotIn('PRIVATE', path.name)
            return read_text(path, *args, **kwargs)
        with patch.object(Path, 'read_bytes', safe_bytes), patch.object(Path, 'read_text', safe_text):
            result = a.answer('실러 전류 관련 규칙은?', self.run, self.fake)
        self.assertEqual(result['status'], 'complete')

    def test_current_measurement_stops_without_tools(self):
        self.plan = {'intent': 'unavailable', 'tool': None, 'arguments': {}}
        with patch.object(t, 'ToolSession', side_effect=AssertionError('No tool needed')):
            result = a.answer('현재 서버실 온도는?', self.run, self.fake)
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertEqual(len(self.calls), 1)

    def test_model_cannot_select_unmentioned_candidate(self):
        self.plan = {'intent': 'explain', 'tool': 'get_candidate_evidence', 'arguments': {'event_id': EVENT}}
        result = a.answer('후보를 설명해줘', self.run, self.fake)
        self.assertEqual(result['reason'], 'candidate_selection_required')
        self.assertEqual(len(self.calls), 1)

    def test_multiple_candidates_require_user_selection(self):
        self.plan = {'intent': 'explain', 'tool': 'list_candidates', 'arguments': {'limit': 1}}
        data = {'total_matches': 2, 'items': [{'id': EVENT, 'sensor_id': 'S', 'rule_id': 'R', 'trigger_at': 'T'}], 'next_offset': 1}
        with patch.object(t.legacy, 'list_candidates', return_value=data):
            result = a.answer('과거 후보 설명해줘', self.run, self.fake)
        self.assertEqual(result['status'], 'needs_clarification')
        self.assertEqual(len(self.calls), 1)

    def test_missing_dense_index_stops_before_final_answer(self):
        self.document_plan()
        with patch.object(t.r3, 'ROW_INDEX', Path(self.tmp.name) / 'missing'), \
             patch.object(t.r3, 'dense_ranking', side_effect=FileNotFoundError('No row index')):
            result = a.answer('서버실 온도 규칙?', self.run, self.fake, use_dense=True)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['reason'], 'local_resource_or_embedding_cache_missing')
        self.assertEqual(len(self.calls), 1)

    def test_explicit_dense_reaches_v3_retriever(self):
        self.document_plan()
        rows = t.r3.row_corpus()
        with patch.object(t.r3, 'dense_ranking', return_value=[row['chunk_id'] for row in rows]) as dense:
            result = a.answer('포장기 진동 규칙?', self.run, self.fake, use_dense=True)
        self.assertEqual(result['status'], 'complete')
        dense.assert_called_once()
        self.assertEqual(dense.call_args.args[0], '포장기 진동 규칙?')
        self.assertTrue(a.v.read(self.run / 'retrieval.json')['dense_used'])

    def test_oversized_evidence_stops_before_generation(self):
        self.document_plan()
        data = {'sources': [{'chunk_id': 'test'}], 'context': 'large', 'graph_paths': [], 'context_tokens': 4001}
        with patch.object(t, 'search_documents', return_value=data):
            result = a.answer('문서 질문', self.run, self.fake)
        self.assertEqual(result['reason'], 'context_budget_exceeded')
        self.assertEqual(len(self.calls), 1)

    def test_invalid_tool_plan_does_not_execute(self):
        self.plan = {'intent': 'document', 'tool': 'execute_shell', 'arguments': {}}
        result = a.answer('문서 질문', self.run, self.fake)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(len(self.calls), 1)


if __name__ == '__main__':
    unittest.main()
