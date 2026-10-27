import http.client
import json
import re
import threading
import unittest
from unittest.mock import patch
from imaks_kg.rag import demo


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.calls=[]
        self.server=demo.make_server(0,answer=lambda q,p:self.calls.append((q,p)),explain=lambda q,p:self.calls.append((q,p)))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.port=self.server.server_port
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
    def request(self,method,path,body=None,headers=None):
        c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
        c.request(method,path,body,headers or {});r=c.getresponse();result=(r.status,r.read());c.close();return result
    def token(self):
        status,b=self.request('GET','/');self.assertEqual(status,200)
        return re.search("const token='([^']+)'",b.decode()).group(1)
    def test_read_only_history_and_source_display(self):
        status,b=self.request('GET','/api/run/smoke_20261024_01')
        self.assertEqual(status,200);d=json.loads(b)
        self.assertTrue(d['sources']);self.assertIn('edges',d)
        self.assertNotIn('api',d);self.assertEqual(self.calls,[])
    def test_detection_read_only_without_gold(self):
        status,b=self.request('GET','/api/detections')
        self.assertEqual(status,200);d=json.loads(b)
        self.assertEqual(len(d['events']),93)
        self.assertFalse(d['summary']['gold_loaded'])
        self.assertNotIn('anomaly_label',b.decode())
        self.assertEqual(self.calls,[])
    def test_cross_origin_and_path_rejection(self):
        token=self.token()
        status,_=self.request('POST','/api/ask',json.dumps({'question':'test'}),{'X-Demo-Token':token,'Origin':'https://evil.example'})
        self.assertEqual(status,403)
        status,_=self.request('GET','/api/run/..%2F..')
        self.assertEqual(status,404);self.assertEqual(self.calls,[])
    def test_submit_and_validation(self):
        token=self.token();h={'X-Demo-Token':token}
        status,_=self.request('POST','/api/ask','{"question":" "}',h)
        self.assertEqual(status,400);self.assertEqual(self.calls,[])
        with patch.object(demo,'presentation',return_value={'answer':'mock result'}):
            status,b=self.request('POST','/api/ask','{"question":"synthetic"}',h)
        self.assertEqual(status,200);self.assertEqual(json.loads(b)['answer'],'mock result')
        self.assertEqual(len(self.calls),1);self.assertEqual(self.calls[0][0],'synthetic')
    def test_event_endpoint_rejects_forged_id_and_uses_server_record(self):
        h={'X-Demo-Token':self.token()}
        status,_=self.request('POST','/api/explain-event',json.dumps({'event_id':'fake'}),h)
        self.assertEqual(status,400);self.assertEqual(self.calls,[])
        with patch.object(demo,'presentation',return_value={'answer':'event mock'}):
            status,_=self.request('POST','/api/explain-event',json.dumps({'event_id':'det-4220832c6ffd0c103c6e','value':999}),h)
        self.assertEqual(status,200);self.assertEqual(self.calls[0][0],'det-4220832c6ffd0c103c6e')


if __name__=='__main__':unittest.main()
