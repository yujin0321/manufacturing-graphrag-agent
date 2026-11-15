from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from imaks_kg.rag import document_claims as dc, agent_v4_1 as agent, incident_agent, vector as v


def packet(records):
    return {'selected_ids': [row['chunk_id'] for row in records], 'sources': records,
            'context': '\n\n'.join('['+row['chunk_id']+']\n'+row['text'] for row in records),
            'context_tokens': 100, 'graph_paths': [], 'retrieval_trace': {'typed_queries': []},
            'coverage_complete': None, 'coverage_required_ids': [], 'retrieval_backend': 'test', 'dense_used': False}


class DocumentClaimTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = list(dc.canonical_rows().values())
        cls.packet = packet([row for row in cls.records if 'MAINT-02' in row['text']][:1])
        cls.catalog = dc.build(cls.packet)

    def test_code_rendered_claims_are_exact_and_locations_are_not_pdf_coordinates(self):
        cid = self.catalog['claims'][0]['claim_id']
        result = dc.bind(json.dumps({'claim_ids': [cid]}), self.catalog)
        self.assertEqual(result['status'], 'bound')
        claim = result['claims'][0]
        self.assertIn(claim['text'], self.packet['sources'][0]['text'])
        self.assertIn('원문 발췌:', result['answer'])
        self.assertIn('현재 측정', result['answer'])
        self.assertFalse(claim['validation']['domain_truth_certified'])
        steps=claim['evidence_paths']['paths'][0]['steps']
        self.assertFalse(steps[-1]['validation']['PDF_visual_verification'])
        self.assertTrue(all(a['to']==b['from'] for a,b in zip(steps,steps[1:])))

    def test_unknown_duplicate_cross_retrieval_and_free_prose_are_withheld(self):
        cid = self.catalog['claims'][0]['claim_id']
        other = dc.build(packet([self.records[-1]]))['claims'][0]['claim_id']
        for selection in ({'claim_ids': ['DCL-no-such-id']}, {'claim_ids': [cid, cid]},
                          {'claim_ids': [other]}, {'claim_ids': [cid], 'answer': '실제 정비 완료'},
                          {'claim_ids': []}, {'claim_ids': [3]}):
            with self.subTest(selection=selection):
                self.assertEqual(dc.bind(json.dumps(selection), self.catalog)['status'], 'withheld')

    def test_retrieved_text_page_hash_and_parent_are_checked(self):
        for field, value in [('text', '조작된 원문'), ('page', -1), ('text_sha256', '0'*64), ('source_file_sha256', '0'*64)]:
            data = deepcopy(self.packet)
            data['sources'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                dc.build(data)
        catalog = deepcopy(self.catalog)
        catalog['claims'][0]['source']['parent_chunk_id'] = 'wrong-parent'
        catalog['catalog_sha256'] = v.digest(v.encoded(dc.payload(catalog)))
        self.assertEqual(dc.bind(json.dumps({'claim_ids': [catalog['claims'][0]['claim_id']]}), catalog)['status'], 'withheld')

    def test_rehashed_fabricated_quote_still_fails_against_canonical_text(self):
        catalog = deepcopy(self.catalog)
        claim = catalog['claims'][0]
        claim['text'] = '실제 비상 정지를 완료했다.'
        claim['claim_id'] = 'DCL-' + v.digest(v.encoded(dc.body(claim)))[:16]
        catalog['catalog_sha256'] = v.digest(v.encoded(dc.payload(catalog)))
        self.assertEqual(dc.bind(json.dumps({'claim_ids': [claim['claim_id']]}), catalog)['status'], 'withheld')

    def test_truncation_is_explicit_and_never_bypasses_the_selector_budget(self):
        catalog = dc.build(packet(self.records[:6]), token_budget=1)
        self.assertTrue(catalog['truncated'])
        self.assertEqual(catalog['claims'], [])

    def test_duplicate_json_keys_are_rejected(self):
        cid=self.catalog['claims'][0]['claim_id']
        self.assertEqual(dc.bind('{"claim_ids":[],"claim_ids":["'+cid+'"]}',self.catalog)['status'],'withheld')

    def test_document_agent_selects_claims_and_verifies_without_free_prose(self):
        scratch = v.REPO_ROOT / 'kg_build/xai_document_tests'
        scratch.mkdir(parents=True, exist_ok=True)
        calls = []
        class Retriever:
            max_tokens = 4000
            def lock(self): return {'backend': 'offline_fixture'}
            def retrieve(inner, question, call): return deepcopy(self.packet)
        def fake(resource, payload, cache):
            stage = Path(cache).name
            calls.append(stage)
            if stage.startswith('draft'):
                content = json.loads(payload['messages'][-1]['content'])
                self.assertNotIn('untrusted_reference_data', content)
                text = json.dumps({'claim_ids': [content['claim_catalog'][0]['claim_id']]})
            elif stage.startswith('verify'):
                content = json.loads(payload['messages'][-1]['content'])
                self.assertIn('DCL-', content['answer'])
                text = json.dumps({'approved': True, 'answer_complete': False, 'issues': [], 'missing_queries': []})
            else:
                raise AssertionError(stage)
            return {'model': payload['model'], 'choices': [{'finish_reason': 'stop', 'message': {'content': text}}]}, {'mock': True}
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            result = agent.answer('MAINT-02 문서 기준', Path(folder)/'run', fake, retriever=Retriever(), claim_mode=True)
            self.assertEqual(result['status'], 'complete')
            self.assertTrue(result['claim_binding']['published'])
            self.assertTrue(result['claims'])
            self.assertFalse(result['answer_complete'])
        self.assertEqual(calls, ['draft1', 'verify1'])

    def test_invalid_selection_skips_ai_verifier_and_is_not_published(self):
        scratch = v.REPO_ROOT / 'kg_build/xai_document_tests'
        scratch.mkdir(parents=True, exist_ok=True)
        class Retriever:
            max_tokens = 4000
            def lock(self): return {}
            def retrieve(inner, question, call): return deepcopy(self.packet)
        calls=[]
        def fake(resource,payload,cache):
            calls.append(Path(cache).name)
            return {'model': payload['model'], 'choices': [{'finish_reason':'stop','message':{'content':'{"claim_ids":[],"answer":"허위"}'}}]},{}
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            result=agent.answer('MAINT-02 문서 기준',Path(folder)/'run',fake,retriever=Retriever(),claim_mode=True)
            self.assertEqual(result['status'],'insufficient_evidence')
            self.assertFalse(result['claim_binding']['published'])
            self.assertEqual(result['claims'],[])
        self.assertEqual(calls,['draft1','draft2'])

    def test_integrated_document_route_enables_claim_mode_and_forwards_claims(self):
        scratch = v.REPO_ROOT / 'kg_build/xai_document_tests'
        scratch.mkdir(parents=True, exist_ok=True)
        binding = dc.bind(json.dumps({'claim_ids':[self.catalog['claims'][0]['claim_id']]}),self.catalog)
        binding['published']=True
        result={'status':'complete','answer':binding['answer'],'sources':self.packet['sources'],
                'graph_paths':[],'usage':[],'verification':[],'claim_binding':binding,'answer_complete':False}
        def fake(resource,payload,cache):
            plan={'intent':'document','tool':None,'arguments':{}}
            return {'model':payload['model'],'choices':[{'finish_reason':'stop','message':{'content':json.dumps(plan)}}]},{}
        with tempfile.TemporaryDirectory(dir=scratch) as folder, patch.object(incident_agent.team_retrieval,'Retriever'), patch.object(incident_agent.documents,'answer',return_value=result) as forwarded:
            answer=incident_agent.answer('MAINT-02 기준',Path(folder)/'run',fake)
            self.assertTrue(forwarded.call_args.kwargs['claim_mode'])
            self.assertTrue(answer['claims'])
            self.assertEqual(answer['xai']['claim_binding']['scope'],'document_excerpts')
            self.assertFalse(answer['xai']['document_answer_complete'])

    def test_real_bm25_retrieval_works_with_claim_mode_without_embeddings(self):
        scratch=v.REPO_ROOT/'kg_build/xai_document_tests';scratch.mkdir(parents=True,exist_ok=True)
        calls=[]
        def fake(resource,payload,cache):
            self.assertEqual(resource,'chat/completions')
            stage=Path(cache).name;calls.append(stage)
            if stage.startswith('draft'):
                content=json.loads(payload['messages'][-1]['content'])
                text=json.dumps({'claim_ids':[content['claim_catalog'][0]['claim_id']]})
            elif stage.startswith('verify'):
                text=json.dumps({'approved':True,'answer_complete':False,'issues':[],'missing_queries':[]})
            else:raise AssertionError(stage)
            return {'model':payload['model'],'choices':[{'finish_reason':'stop','message':{'content':text}}]},{}
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            result=agent.answer('MAINT-02 문서 기준',Path(folder)/'run',fake,claim_mode=True)
            self.assertEqual(result['status'],'complete')
            self.assertTrue(result['claims'])
        self.assertEqual(calls,['draft1','verify1'])


if __name__ == '__main__':
    unittest.main()
