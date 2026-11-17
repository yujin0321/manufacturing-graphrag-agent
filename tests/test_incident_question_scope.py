"""업로드 분석 사건 질문(/api/agent + analysis_id·incident_id)이 그 분석의 store로 Agent에 전달되는지 검사한다.

Agent는 가짜 함수로 바꿔 모델 호출 없이 실행한다.
"""
import http.client
import json
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from imaks_kg.rag import demo
from imaks_kg.rag.sensor_analysis import InputError

ANALYSIS = 'ana-' + 'a' * 32
INCIDENT = 'inc3-' + 'b' * 20
OTHER = 'inc3-' + 'c' * 20


class IncidentQuestionScopeTests(unittest.TestCase):
    def setUp(self):
        self.store = SimpleNamespace(by_id={INCIDENT: {'id': INCIDENT, 'sensor_id': 'ST01_FILLING_FLW'}})
        self.service = Mock()
        self.service.store.return_value = self.store
        self.start_server(analysis_service=self.service)

    def start_server(self, generation_enabled=True, analysis_service=None):
        self.calls = []

        def answer(question, run, **options):
            self.calls.append((question, options))

        self.server = demo.make_server(
            0, agent_answer=answer,
            agent_options={'detector_profile': {'main_v3_1'}, 'document_mode': {'auto'}, 'repair_incident': {True, False}},
            page=Path(demo.__file__).with_name('xai_demo.html'), generation_enabled=generation_enabled,
            analysis_service=analysis_service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, json.loads(data)

    def ask(self, payload):
        _, session = self.request('GET', '/api/session')
        headers = {'X-Demo-Token': session['csrf_token'], 'Content-Type': 'application/json'}
        with patch.object(demo, 'presentation', return_value={'agent_status': 'complete'}):
            return self.request('POST', '/api/agent', json.dumps(payload), headers)

    def test_selected_incident_is_answered_from_its_analysis_store(self):
        status, _ = self.ask({'question': '왜 이 경보가 났나요?', 'analysis_id': ANALYSIS, 'incident_id': INCIDENT})
        self.assertEqual(status, 200)
        self.service.store.assert_called_once_with(ANALYSIS)
        question, options = self.calls[0]
        self.assertEqual(question, f'사건 {INCIDENT}: 왜 이 경보가 났나요?')
        self.assertIs(options['store'], self.store)

    def test_question_that_already_names_the_incident_is_kept(self):
        status, _ = self.ask({'question': f'{INCIDENT} 근거 설명', 'analysis_id': ANALYSIS, 'incident_id': INCIDENT})
        self.assertEqual(status, 200)
        self.assertEqual(self.calls[0][0], f'{INCIDENT} 근거 설명')

    def test_options_still_pass_through_with_scope(self):
        status, _ = self.ask({'question': '설명', 'analysis_id': ANALYSIS, 'incident_id': INCIDENT, 'document_mode': 'auto'})
        self.assertEqual(status, 200)
        self.assertEqual(self.calls[0][1]['document_mode'], 'auto')

    def test_incident_outside_the_analysis_is_rejected_before_the_agent(self):
        status, body = self.ask({'question': '설명', 'analysis_id': ANALYSIS, 'incident_id': OTHER})
        self.assertEqual((status, body['code']), (400, 'incident_not_in_analysis'))
        self.assertEqual(self.calls, [])

    def test_conflicting_incident_in_question_is_rejected(self):
        status, body = self.ask({'question': f'{OTHER} 설명', 'analysis_id': ANALYSIS, 'incident_id': INCIDENT})
        self.assertEqual((status, body['code']), (400, 'conflicting_incident_id'))
        self.assertEqual(self.calls, [])

    def test_missing_incident_id_is_rejected(self):
        status, body = self.ask({'question': '설명', 'analysis_id': ANALYSIS})
        self.assertEqual((status, body['code']), (400, 'invalid_incident_scope'))
        self.assertEqual(self.calls, [])

    def test_unfinished_analysis_returns_409(self):
        self.service.store.side_effect = InputError('analysis_not_ready', '아직 완료되지 않은 분석입니다.')
        status, body = self.ask({'question': '설명', 'analysis_id': ANALYSIS, 'incident_id': INCIDENT})
        self.assertEqual((status, body['code']), (409, 'analysis_not_ready'))
        self.assertEqual(self.calls, [])

    def test_unknown_analysis_returns_404(self):
        self.service.store.side_effect = FileNotFoundError()
        status, _ = self.ask({'question': '설명', 'analysis_id': ANALYSIS, 'incident_id': INCIDENT})
        self.assertEqual(status, 404)
        self.assertEqual(self.calls, [])

    def test_scope_requires_local_analysis(self):
        self.tearDown()
        self.start_server(analysis_service=None)
        status, body = self.ask({'question': '설명', 'analysis_id': ANALYSIS, 'incident_id': INCIDENT})
        self.assertEqual((status, body['code']), (400, 'analysis_disabled'))
        self.assertEqual(self.calls, [])

    def test_read_only_server_still_refuses_generation(self):
        self.tearDown()
        self.start_server(generation_enabled=False, analysis_service=self.service)
        status, body = self.ask({'question': '설명', 'analysis_id': ANALYSIS, 'incident_id': INCIDENT})
        self.assertEqual((status, body['code']), (503, 'read_only'))
        self.service.store.assert_not_called()

    def test_plain_question_without_scope_is_unchanged(self):
        status, _ = self.ask({'question': '문서 질문'})
        self.assertEqual(status, 200)
        self.assertEqual(self.calls, [('문서 질문', {})])
        self.service.store.assert_not_called()


if __name__ == '__main__':
    unittest.main()
