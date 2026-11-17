import http.client
import json
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from imaks_kg.rag import demo


class TeamServerTests(unittest.TestCase):
    def setUp(self):
        self.start_server()

    def start_server(self, generation_enabled=True, team_config=None, analysis_service=None):
        self.calls = []
        self.profiles = []
        def answer(question, run, **options):
            self.calls.append((question, options))
        def factory(profile):
            self.profiles.append(profile)
            return object()
        self.server = demo.make_server(0, agent_answer=answer, incident_store_factory=factory,
            agent_options={'detector_profile': {'main_v3_1', 'seongho_two_point'},
                           'document_mode': {'auto', 'vector'}, 'repair_incident': {True, False}},
            team_config=team_config or (lambda: {'detectors': ['main_v3_1', 'seongho_two_point']}),
            page=Path(demo.__file__).with_name('xai_demo.html'), generation_enabled=generation_enabled,analysis_service=analysis_service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, data

    def test_session_bootstrap_does_not_expose_an_api_key(self):
        status, body = self.request('GET', '/api/session')
        self.assertEqual(status, 200)
        session = json.loads(body)
        self.assertEqual(set(session), {'csrf_token', 'generation_enabled'})
        self.assertTrue(session['csrf_token'])
        self.assertTrue(session['generation_enabled'])
        self.assertEqual(self.calls, [])

    def test_async_submission_passes_interval_and_returns_202_without_generation(self):
        from unittest.mock import Mock
        service=Mock();service.submit.return_value={'analysis_id':'ana-'+'a'*32,'status':'queued'}
        self.tearDown();self.start_server(generation_enabled=False,analysis_service=service)
        _,body=self.request('GET','/api/session');token=json.loads(body)['csrf_token']
        request={'csv':'controlled','input_kind':'historical_replay','analysis_start':'2026-01-08T12:26:00','analysis_end':'2026-01-08T12:35:00'}
        status,body=self.request('POST','/api/analyses',json.dumps(request),{'Content-Type':'application/json','X-Demo-Token':token})
        self.assertEqual(status,202);self.assertEqual(json.loads(body)['status'],'queued')
        service.submit.assert_called_once_with(b'controlled','historical_replay',analysis_start=request['analysis_start'],analysis_end=request['analysis_end'])
        self.assertFalse(self.calls)

    def test_export_download_and_import_use_binary_body_without_generation(self):
        from unittest.mock import Mock
        service=Mock();service.export_bundle.return_value=b'controlled zip'
        service.import_bundle.return_value={'status':'restored','new_api_calls':0}
        self.tearDown();self.start_server(generation_enabled=False,analysis_service=service)
        _,body=self.request('GET','/api/session');token=json.loads(body)['csrf_token']
        aid='ana-'+'a'*32
        status,body=self.request('GET',f'/api/analyses/{aid}/export')
        self.assertEqual(status,200);self.assertEqual(body,b'controlled zip')
        status,body=self.request('POST','/api/analyses/import',b'controlled zip',{'Content-Type':'application/zip','X-Demo-Token':token})
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['status'],'restored')
        service.import_bundle.assert_called_once_with(b'controlled zip');self.assertFalse(self.calls)

    def test_warmup_flag_and_not_ready_status_are_not_silently_accepted(self):
        from unittest.mock import Mock
        from imaks_kg.rag.sensor_analysis import InputError
        service=Mock();service.series.side_effect=InputError('analysis_not_ready','running')
        self.tearDown();self.start_server(generation_enabled=False,analysis_service=service)
        path='/api/analyses/ana-'+('a'*32)+'/series?sensor_id=S'
        self.assertEqual(self.request('GET',path+'&include_warmup=yes')[0],400)
        self.assertEqual(self.request('GET',path+'&include_warmup=true')[0],409)

    def test_real_registry_defaults_are_exposed_as_valid_json(self):
        from imaks_kg.rag import team_runtime
        self.tearDown()
        self.start_server(team_config=team_runtime.application_config)
        status, body = self.request('GET', '/api/team-config')
        self.assertEqual(status, 200)
        config = json.loads(body)
        self.assertEqual(config['defaults']['detector_profile'], 'main_v3_1')
        self.assertEqual(config['defaults']['document_mode'], 'auto')
        self.assertEqual(len(config['detectors']), 4)
        self.assertEqual(len(config['members']), 4)
        self.assertEqual(self.calls, [])

    def test_read_only_server_rejects_generation_before_calling_agent(self):
        self.tearDown()
        self.start_server(generation_enabled=False)
        _, body = self.request('GET', '/api/session')
        session = json.loads(body)
        self.assertFalse(session['generation_enabled'])
        status, body = self.request('POST', '/api/agent', json.dumps({'question': 'test'}),
                                    {'X-Demo-Token': session['csrf_token']})
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)['code'], 'read_only')
        self.assertEqual(self.calls, [])

    def test_repair_boolean_is_forwarded_and_integer_is_rejected(self):
        _, body = self.request('GET', '/api/session')
        headers = {'X-Demo-Token': json.loads(body)['csrf_token']}
        with patch.object(demo, 'presentation', return_value={'agent_status': 'complete'}):
            status, _ = self.request('POST', '/api/agent', json.dumps({'question': 'test', 'repair_incident': True}), headers)
        self.assertEqual(status, 200)
        self.assertTrue(self.calls[-1][1]['repair_incident'])
        status, _ = self.request('POST', '/api/agent', '{"question":"test","repair_incident":1}', headers)
        self.assertEqual(status, 400)
        self.assertEqual(len(self.calls), 1)

    def test_saved_decision_recheck_uses_no_generation_callback(self):
        from imaks_kg.rag import decision_evidence
        with patch.object(decision_evidence, 'for_saved_run', return_value={'new_api_calls': 0, 'decision_evidence': {'status': 'consistent'}}):
            status, body = self.request('GET', '/api/decision-evidence/safe_example')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['new_api_calls'], 0)
        status, _ = self.request('GET', '/api/decision-evidence/..%2Foutside')
        self.assertEqual(status, 400)
        self.assertFalse(self.calls)

    def test_saved_claim_catalog_does_not_call_generation_or_relabel_old_answers(self):
        from imaks_kg.rag import claim_binding
        with patch.object(claim_binding, 'catalog_for_saved_run', return_value={'new_api_calls': 0, 'past_answer_claim_binding': 'not_performed'}):
            status, body = self.request('GET', '/api/claim-catalog/safe_example')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['past_answer_claim_binding'], 'not_performed')
        status, _ = self.request('GET', '/api/claim-catalog/..%2Foutside')
        self.assertEqual(status, 400)
        self.assertFalse(self.calls)

    def test_saved_path_endpoint_is_read_only_and_keeps_scope_explicit(self):
        from imaks_kg.rag import evidence_paths
        with patch.object(evidence_paths, 'for_saved_run', return_value={'new_api_calls': 0, 'past_answer_prose_revalidated': False}):
            status, body = self.request('GET', '/api/claim-paths/safe_example')
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)['past_answer_prose_revalidated'])
        status, _ = self.request('GET', '/api/claim-paths/..%2Foutside')
        self.assertEqual(status, 400)
        self.assertFalse(self.calls)

    def test_free_config_and_selected_incident_store(self):
        status, body = self.request('GET', '/api/team-config')
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)['detectors']), 2)
        with patch.object(demo, 'incident_presentation', return_value={'incidents': []}):
            status, _ = self.request('GET', '/api/incidents?profile=seongho_two_point')
        self.assertEqual(status, 200)
        self.assertEqual(self.profiles, ['seongho_two_point'])
        self.assertEqual(self.calls, [])

    def test_rule_and_document_audits_are_read_only_and_reject_path_traversal(self):
        from imaks_kg.rag import rule_explanations, document_claims
        for route, module in [('rule-explanations',rule_explanations), ('document-claims',document_claims)]:
            with patch.object(module,'for_saved_run',return_value={'new_api_calls':0,'past_answer_prose_revalidated':False}):
                status,body=self.request('GET','/api/'+route+'/safe_example')
            self.assertEqual(status,200)
            self.assertEqual(json.loads(body)['new_api_calls'],0)
            status,_=self.request('GET','/api/'+route+'/..%2Foutside')
            self.assertEqual(status,400)
        self.assertFalse(self.calls)

    def test_selected_modes_are_forwarded_and_invalid_modes_do_not_call_agent(self):
        status, _ = self.request('GET', '/')
        self.assertEqual(status, 200)
        # The sensor UI reads the CSRF token from /api/session instead of an inline page constant.
        status, body = self.request('GET', '/api/session')
        self.assertEqual(status, 200)
        token = json.loads(body)['csrf_token']
        headers = {'X-Demo-Token': token, 'Content-Type': 'application/json'}
        payload = {'question': '후보 설명', 'detector_profile': 'seongho_two_point', 'document_mode': 'vector'}
        with patch.object(demo, 'presentation', return_value={'agent_status': 'complete'}):
            status, _ = self.request('POST', '/api/agent', json.dumps(payload), headers)
        self.assertEqual(status, 200)
        self.assertEqual(self.calls, [('후보 설명', {'detector_profile': 'seongho_two_point', 'document_mode': 'vector'})])
        payload['detector_profile'] = 'not_published'
        status, _ = self.request('POST', '/api/agent', json.dumps(payload), headers)
        self.assertEqual(status, 400)
        self.assertEqual(len(self.calls), 1)


if __name__ == '__main__':
    unittest.main()
