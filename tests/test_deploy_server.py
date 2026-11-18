"""Public-deployment settings of the demo server: hosts, origins, access code and request budgets."""
import http.client
import json
import threading
import unittest
from pathlib import Path

from imaks_kg.rag import demo


class DeployConfigTests(unittest.TestCase):
    def test_defaults_stay_loopback_only(self):
        config = demo.DeployConfig.from_env({})
        self.assertEqual(config.bind_host, '127.0.0.1')
        self.assertEqual(config.allowed_hosts(8770), {'127.0.0.1:8770'})
        self.assertEqual(config.allowed_origins(8770), {'http://127.0.0.1:8770'})
        self.assertEqual((config.access_code, config.daily_limit, config.hourly_per_ip), ('', 0, 0))

    def test_public_hosts_add_https_origins(self):
        config = demo.DeployConfig.from_env({'IMAKS_PUBLIC_HOSTS': 'Imaks.example.com, ,demo.example.org'})
        self.assertIn('imaks.example.com', config.allowed_hosts(8770))
        self.assertIn('https://demo.example.org', config.allowed_origins(8770))
        self.assertNotIn('http://imaks.example.com', config.allowed_origins(8770))

    def test_rejects_urls_and_negative_limits(self):
        with self.assertRaises(ValueError):
            demo.DeployConfig.from_env({'IMAKS_PUBLIC_HOSTS': 'https://imaks.example.com'})
        with self.assertRaises(ValueError):
            demo.DeployConfig.from_env({'IMAKS_GENERATION_DAILY_LIMIT': '-1'})


class LimiterTests(unittest.TestCase):
    def test_hourly_window_and_daily_cap(self):
        now = [1_800_000_000.0]
        limiter = demo.Limiter(daily_limit=3, hourly_per_ip=2, clock=lambda: now[0])
        self.assertIsNone(limiter.take('a'))
        self.assertIsNone(limiter.take('a'))
        self.assertEqual(limiter.take('a'), 'hourly')
        self.assertIsNone(limiter.take('b'))
        self.assertEqual(limiter.take('c'), 'daily')
        self.assertEqual(limiter.remaining_today(), 0)
        now[0] += 86400
        self.assertIsNone(limiter.take('a'))
        self.assertEqual(limiter.remaining_today(), 2)


class PublicServerTests(unittest.TestCase):
    HOST = 'imaks.example.com'

    def start(self, **settings):
        self.calls = []
        def answer(question, run, **options):
            self.calls.append(question)
        deploy = demo.DeployConfig(public_hosts=[self.HOST], trust_proxy=True, **settings)
        self.server = demo.make_server(0, agent_answer=answer, page=Path(demo.__file__).with_name('xai_demo.html'),
                                       agent_options={'document_mode': {'auto'}}, deploy=deploy)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        connection.request(method, path, body, {'Host': self.HOST, **(headers or {})})
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, json.loads(data) if data[:1] in (b'{', b'[') else data

    def ask(self, extra=None, ip='203.0.113.7'):
        _, session = self.request('GET', '/api/session')
        headers = {'Content-Type': 'application/json', 'X-Demo-Token': session['csrf_token'],
                   'Origin': 'https://' + self.HOST, 'X-Forwarded-For': ip, **(extra or {})}
        # demo.presentation() needs saved artifacts; the stub writes none, so success surfaces as 500 after the call.
        return self.request('POST', '/api/agent', json.dumps({'question': '테스트'}), headers)

    def test_public_host_is_served_and_unknown_host_is_rejected(self):
        self.start()
        status, _ = self.request('GET', '/api/session')
        self.assertEqual(status, 200)
        status, _ = self.request('GET', '/api/session', headers={'Host': 'evil.example.net'})
        self.assertEqual(status, 403)

    def test_http_origin_for_public_host_is_rejected(self):
        self.start()
        _, session = self.request('GET', '/api/session')
        status, _ = self.request('POST', '/api/agent', json.dumps({'question': 'q'}),
                                 {'Content-Type': 'application/json', 'X-Demo-Token': session['csrf_token'],
                                  'Origin': 'http://' + self.HOST})
        self.assertEqual(status, 403)
        self.assertEqual(self.calls, [])

    def test_access_code_is_required_before_any_model_call(self):
        self.start(access_code='s3cret')
        _, session = self.request('GET', '/api/session')
        self.assertTrue(session['access_code_required'])
        self.assertNotIn('s3cret', json.dumps(session))
        status, body = self.ask()
        self.assertEqual((status, body['code']), (401, 'access_code_required'))
        status, _ = self.ask({'X-Access-Code': 'wrong'})
        self.assertEqual(status, 401)
        self.assertEqual(self.calls, [])
        self.ask({'X-Access-Code': 's3cret'})
        self.assertEqual(self.calls, ['테스트'])

    def test_per_ip_and_daily_budgets_block_model_calls(self):
        self.start(daily_limit=3, hourly_per_ip=2)
        _, session = self.request('GET', '/api/session')
        self.assertEqual(session['generation_remaining_today'], 3)
        self.ask(ip='198.51.100.1')
        self.ask(ip='198.51.100.1')
        status, body = self.ask(ip='198.51.100.1')
        self.assertEqual((status, body['code']), (429, 'rate_limited_hourly'))
        self.ask(ip='198.51.100.2')
        status, body = self.ask(ip='198.51.100.3')
        self.assertEqual((status, body['code']), (429, 'rate_limited_daily'))
        self.assertEqual(len(self.calls), 3)

    def test_spoofed_forwarded_prefix_does_not_bypass_ip_limit(self):
        self.start(hourly_per_ip=1)
        self.ask(ip='10.0.0.1, 198.51.100.9')
        status, _ = self.ask(ip='10.0.0.2, 198.51.100.9')
        self.assertEqual(status, 429)
        self.assertEqual(len(self.calls), 1)


if __name__ == '__main__':
    unittest.main()
