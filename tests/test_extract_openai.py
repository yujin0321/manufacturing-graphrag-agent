import io
import json
import unittest
import urllib.error
from unittest.mock import patch
from imaks_kg.extract import llm, llm_openai as o, run, approval
from imaks_kg.extract.schema import build_schema
from imaks_kg.extract.common import ExtractError

def response(status='completed', model=o.MODEL_ID, content=None):
    return {'id':'resp_fixture','model':model,'status':status,
            'usage':{'input_tokens':10,'output_tokens':20,'output_tokens_details':{'reasoning_tokens':5}},
            'output':[{'type':'message','role':'assistant','content': content if content is not None else
                       [{'type':'output_text','text':'{"rules":[]}'}]}]}

class OpenAIExtraction(unittest.TestCase):
    def test_default_and_gemini_disabled(self):
        self.assertEqual(run.get_adapter().name,'openai')
        self.assertEqual(run.get_adapter().model_id,o.MODEL_ID)
        with self.assertRaises(ExtractError): run.get_adapter('gemini')
        with self.assertRaises(ExtractError): o.OpenAIAdapter('gpt-other')

    def test_request_and_schema_immutable(self):
        schema=build_schema(['S'],['ST'])
        original=json.dumps(schema,sort_keys=True)
        req=o.OpenAIAdapter().build_request('system','user',schema)
        self.assertEqual(req['reasoning'],{'effort':'low'})
        self.assertTrue(req['text']['format']['strict'])
        self.assertFalse(req['store'])
        self.assertEqual(req['service_tier'],'default')
        for name in ('temperature','top_p','seed'): self.assertNotIn(name,req)
        self.assertEqual(original,json.dumps(schema,sort_keys=True))

    def test_success_usage_and_raw(self):
        raw=response()
        result=o.interpret('chunk',raw)
        self.assertTrue(result.ok)
        self.assertEqual(result.parsed,{'rules':[]})
        self.assertEqual(result.usage['output_tokens_details']['reasoning_tokens'],5)
        self.assertEqual(result.raw,raw)

    def test_incomplete_refusal_invalid_output_not_retried(self):
        for raw in (response('incomplete'),response(content=[{'type':'refusal','refusal':'no'}]),
                    response(content=[{'type':'output_text','text':'broken'}])):
            class Client:
                calls=0
                def create(self,request,key): self.calls+=1; return raw
            client=Client()
            result=llm.call_with_policy(client,{},'c',llm.RetryBudget(),adapter=o.OpenAIAdapter())
            self.assertFalse(result.ok)
            self.assertEqual(client.calls,1)

    def test_model_mismatch_aborts(self):
        self.assertTrue(o.interpret('c',response(model='gpt-6.1-sol-lite')).abort)
        self.assertTrue(o.interpret('c',response(model='gpt-6.1-sol-001')).ok)

    def test_error_policy(self):
        for status,code,expected in [(401,'',llm.FATAL_AUTH),(429,'insufficient_quota',llm.FATAL_BILLING),
                  (429,'rate_limit_exceeded',llm.TRANSIENT_RATE),(503,'',llm.TRANSIENT_RATE),
                  (400,'',llm.FATAL_REQUEST),(500,'',llm.AMBIGUOUS),(None,'',llm.AMBIGUOUS)]:
            self.assertEqual(o.classify(o.OpenAIError('error',status,{'error':{'code':code}})).error_class,expected)

    def test_transport_authorization_once(self):
        calls=[]
        class Body(io.BytesIO):
            headers={'x-request-id':'req-test'}
        def transport(req,timeout):
            calls.append(req)
            self.assertEqual(req.get_header('Authorization'),'Bearer sk-fixture')
            self.assertEqual(req.full_url,o.ENDPOINT)
            return Body(json.dumps(response()).encode())
        with patch.object(o,'api_key',return_value='sk-fixture'):
            result=o.OpenAIClient(transport).create({'model':o.MODEL_ID},'chunk')
        self.assertEqual(len(calls),1)
        self.assertEqual(result['_request_id'],'req-test')

    def test_timeout_never_retried(self):
        calls=[]
        def transport(req,timeout): calls.append(req); raise TimeoutError()
        with patch.object(o,'api_key',return_value='sk-fixture'):
            result=llm.call_with_policy(o.OpenAIClient(transport),{},'c',llm.RetryBudget(),adapter=o.OpenAIAdapter())
        self.assertEqual(len(calls),1)
        self.assertTrue(result.abort)
        self.assertEqual(result.error_class,llm.AMBIGUOUS)

    def test_rate_retries_budgeted(self):
        class Client:
            calls=0
            def create(self,request,key):
                self.calls+=1
                if self.calls==1: raise o.OpenAIError('rate',429)
                return response()
        client=Client()
        budget=llm.RetryBudget()
        result=llm.call_with_policy(client,{},'c',budget,sleep=lambda _:None,adapter=o.OpenAIAdapter())
        self.assertTrue(result.ok)
        self.assertEqual(client.calls,2)
        self.assertEqual(budget.used,1)

    def test_outbound_and_prices(self):
        adapter=o.OpenAIAdapter()
        docs={'manifest':{'SOP-001':{'file':'imaks_data/rules/a.pdf'}}}
        self.assertEqual(adapter.outbound_problem({'doc_id':'SOP-001'},docs),'')
        self.assertTrue(adapter.outbound_problem({'doc_id':'DS-ELEC-3300'},docs))
        self.assertEqual(approval.price_for('openai',o.MODEL_ID)['output_per_mtok'],10)

    def test_redaction(self):
        with patch.object(o,'api_key',return_value='secret_fixture'):
            self.assertNotIn('secret_fixture',str(o.OpenAIError('secret_fixture sk-testkey')))
            self.assertNotIn('sk-testkey',str(o.OpenAIError('secret_fixture sk-testkey')))

    def test_settings_hash_captures_reasoning_not_chunk(self):
        a=o.OpenAIAdapter()
        req=a.build_request('s','u',build_schema(['S'],['ST']))
        sha=a.settings_sha(req)
        req['input']='different chunk'
        self.assertEqual(sha,a.settings_sha(req))
        req['reasoning']['effort']='high'
        self.assertNotEqual(sha,a.settings_sha(req))
