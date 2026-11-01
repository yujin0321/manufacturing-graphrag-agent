import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from imaks_kg.rag import agent_tools as t

EVENT = 'det-4220832c6ffd0c103c6e'


class ToolTests(unittest.TestCase):
    def setUp(self):
        root = t.v.REPO_ROOT / 'kg_build/agent_tool_tests'
        root.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.tmp.cleanup)
        # Network is forbidden even if a future implementation accidentally uses it.
        self.net = patch.object(t.v, 'api_call', side_effect=AssertionError('No API allowed'))
        self.net.start()
        self.addCleanup(self.net.stop)

    def session(self, **kwargs):
        return t.ToolSession(Path(self.tmp.name) / 'run', **kwargs)

    def test_real_store_pagination_and_reference_filter(self):
        session = self.session()
        result = session.execute('list_candidates', {'limit': 1})['data']
        self.assertEqual(result['total_matches'], 93)
        self.assertEqual(result['next_offset'], 1)
        self.assertEqual(len(result['items']), 1)
        result = session.execute('list_candidates', {'rule_id': 'MAINT-05'})['data']
        self.assertTrue(all(e['rule_id'] == 'MAINT-05:main' for e in result['items']))
        self.assertGreater(result['total_matches'], 0)

    def test_real_evidence_and_trace(self):
        session = self.session(explicit_event_ids=[EVENT])
        r = session.execute('get_candidate_evidence', {'event_id': EVENT})
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(r['data']['candidate']['trigger_value'], '26.9452')
        self.assertEqual(r['data']['untrusted_reference_documents'][0]['chunk_id'], 'SOP-003:p1:table1:chunk')
        self.assertTrue(r['data']['graph_paths'])
        self.assertTrue((session.run / 'trace.json').is_file())

    def test_ambiguous_page_cannot_authorize_model_pick(self):
        session = self.session()
        page = session.execute('list_candidates', {'limit': 1})['data']
        result = session.execute('get_candidate_evidence', {'event_id': page['items'][0]['id']})
        self.assertEqual(result['error']['code'], 'candidate_selection_required')

    def test_limits_and_failure_stop(self):
        session = self.session()
        for _ in range(3):
            self.assertEqual(session.execute('list_candidates', {})['status'], 'ok')
        self.assertEqual(session.execute('list_candidates', {})['error']['code'], 'tool_limit_exceeded')
        self.assertEqual(session.execute('list_candidates', {})['error']['code'], 'session_stopped')

    def test_unknown_filter_and_injection_fail_closed(self):
        session = self.session()
        self.assertEqual(session.execute('list_candidates', {'sensor_id': 'UNKNOWN'})['error']['code'], 'unknown_filter_id')
        with patch.object(t, 'list_candidates') as tool:
            self.assertEqual(session.execute('list_candidates', {})['error']['code'], 'session_stopped')
            tool.assert_not_called()

    def test_real_cached_document_search(self):
        request = t.v.read(next((t.v.DEFAULT_INDEX / 'query_cache').glob('*.request.json')))
        payload = request.get('payload', request)
        question = payload['input'][0]
        session = self.session()
        result = session.execute('search_documents', {'question': question})
        self.assertEqual(result['status'], 'ok', result['error'])
        self.assertTrue(result['data']['selected_ids'])
        self.assertTrue(result['data']['embedding_api']['cache_hit'])

    def test_missing_cache_has_no_network_fallback(self):
        session = self.session()
        r = session.execute('search_documents', {'question': 'agent-tools-never-cached-20261028-unit-test'})
        self.assertEqual(r['error']['code'], 'local_resource_or_embedding_cache_missing')

    def test_cumulative_context_budget(self):
        session = self.session()
        with patch.object(session, 'document_search', return_value={'context_tokens': 2500}):
            self.assertEqual(session.execute('search_documents', {'question': 'one'})['status'], 'ok')
            r = session.execute('search_documents', {'question': 'two'})
            self.assertEqual(r['error']['code'], 'context_budget_exceeded')
            self.assertIsNone(r['data'])


if __name__ == '__main__':
    unittest.main()
