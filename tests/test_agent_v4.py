"""V4 behavior tests: real source retrieval and bounded mocked verification."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from imaks_kg.rag import agent_v4 as agent, routing_v4 as routing, retrieval_v4 as retrieval
from imaks_kg.rag import vector as v


class RoutingTests(unittest.TestCase):
    def test_scenarios_are_documents_even_with_now(self):
        for question in ['연구실 습도가 70%예요. 실험 계속해도 되나요?', '포장기 진동이 0.28 mm/s입니다. 지금 해야 할 조치는?',
                         '충전 압력 3.1 bar일 때 점검 대상은?', '실험실 온도가 31도라고 가정하면 어떻게 해야 하나요?']:
            with self.subTest(question=question):self.assertEqual(routing.deterministic_plan(question)['intent'],'document')
    def test_actual_queries_and_execution_stay_unavailable(self):
        for question in ['지금 서버실 온도 몇 도야?', '현재 센서 측정값을 조회해줘', '라인을 실제로 정지시켜줘', '밸브를 꺼줘']:
            with self.subTest(question=question):self.assertEqual(routing.deterministic_plan(question)['intent'],'unavailable')
    def test_unclear_question_needs_planner(self):
        self.assertIsNone(routing.deterministic_plan('어떻게 해야 하지?'))
    def test_candidate_is_not_forced_to_document(self):
        self.assertIsNone(routing.deterministic_plan('탐지 후보 det-4220832c6ffd0c103c6e 설명해줘'))


class RetrievalTests(unittest.TestCase):
    def test_priority_query_covers_all_matching_document_rows(self):
        r=retrieval.retrieve('예측 정비 규칙 중 CRITICAL 우선순위를 모두 정리해줘')
        ids=r['coverage_required_ids']
        self.assertEqual(len(ids),3)
        self.assertTrue(r['coverage_complete'])
        self.assertTrue(set(ids)<=set(r['selected_ids']))
        self.assertEqual(r['typed_queries'][0]['priority'],'CRITICAL')
    def test_priority_filter_is_station_scoped(self):
        r=retrieval.retrieve('ST02 실링 정비 규칙 중 HIGH 우선순위 목록')
        texts={row['chunk_id']:row['text'] for row in retrieval.base.row_corpus()}
        self.assertTrue(r['coverage_required_ids'])
        self.assertTrue(all('ST02_SEALING' in texts[cid] for cid in r['coverage_required_ids']))
    def test_definition_query_recovers_definition_columns(self):
        r=retrieval.retrieve('경고 기준 위반 지속으로 정의되는 이상 유형과 탐지 기준은?')
        sources=retrieval.source_packet(r)['sources']
        self.assertTrue(any('Type: OUT_OF_RANGE;' in row['text'] for row in sources))
        self.assertTrue(r['coverage_complete'])
    def test_stuck_definition_is_targeted(self):
        r=retrieval.retrieve('장력 값이 12회 연속으로 같으면 이상 유형 정의는?')
        self.assertEqual(len(r['coverage_required_ids']),1)
        self.assertIn('Type: STUCK;',next(row['text'] for row in retrieval.base.row_corpus() if row['chunk_id']==r['coverage_required_ids'][0]))
    def test_role_table_retains_ties(self):
        r=retrieval.retrieve('CRITICAL 경보 확인 시간이 가장 긴 역할은?')
        self.assertEqual(len(r['coverage_required_ids']),5)
        self.assertTrue(r['coverage_complete'])
    def test_budget_never_grows_for_typed_retrieval(self):
        for question in ['CRITICAL 정비 규칙 모두', '이상 유형 정의와 모든 탐지 기준', '경보 확인 시간 역할']:
            self.assertLessEqual(retrieval.retrieve(question)['context_tokens'],4000)
    def test_dense_is_never_enabled_by_index_presence(self):
        with patch.object(retrieval.base,'dense_ranking',side_effect=AssertionError('No API')):
            self.assertFalse(retrieval.retrieve('서버실 온도 규칙')['dense_used'])


class AgentTests(unittest.TestCase):
    def setUp(self):
        root=v.REPO_ROOT/'kg_build/agent_v4_tests';root.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=root);self.addCleanup(self.tmp.cleanup)
        self.run=Path(self.tmp.name)/'run';self.calls=[]
    def fake(self,resource,payload,cache):
        self.assertEqual(resource,'chat/completions')
        stage=Path(cache).name;self.calls.append(stage)
        if stage.startswith('verify'):
            result={'approved':True,'issues':[],'missing_queries':[]}
            text=json.dumps(result)
        elif stage.startswith('draft'):
            packet=json.loads(payload['messages'][-1]['content'])
            import re
            cid=re.search(r'\[((?:SOP|DS)-[^\]\n]+:chunk#r\d+)\]',packet['untrusted_reference_data'])
            if not cid:cid=re.search(r'\[([^\]\n]+)\]',packet['untrusted_reference_data'])
            text='문서 규칙에 따른 조건부 설명입니다. ['+cid.group(1)+']'
        else:raise AssertionError('No planner needed for explicit documents')
        return {'model':payload['model'],'choices':[{'finish_reason':'stop','message':{'content':text}}]}, {'mock':True}
    def test_document_route_draft_and_verifier(self):
        result=agent.answer('서버실 온도 규칙과 조치',self.run,self.fake)
        self.assertEqual(result['status'],'complete');self.assertEqual(self.calls,['draft1','verify1'])
        request=v.read(self.run/'draft1_request.json')
        self.assertNotIn('후보 ID, 센서, 최초 판정',request['messages'][0]['content'])
        self.assertTrue((self.run/'verification_1.json').is_file())
    def test_real_lookup_abstains_without_any_model_call(self):
        result=agent.answer('현재 서버실 온도 몇 도야?',self.run,self.fake)
        self.assertEqual(result['status'],'insufficient_evidence');self.assertEqual(self.calls,[])
    def test_rejected_draft_searches_only_once_and_stops(self):
        def reject(resource,payload,cache):
            if Path(cache).name.startswith('verify'):
                self.calls.append(Path(cache).name)
                text=json.dumps({'approved':False,'issues':['Missing definition'],'missing_queries':['anomaly definition']})
                return {'model':payload['model'],'choices':[{'finish_reason':'stop','message':{'content':text}}]},{}
            return self.fake(resource,payload,cache)
        result=agent.answer('이상 유형 정의',self.run,reject)
        self.assertEqual(result['status'],'insufficient_evidence');self.assertEqual(result['search_count'],2)
        self.assertEqual(self.calls,['draft1','verify1','draft2','verify2'])
    def test_unknown_citation_cannot_pass_model_approval(self):
        def wrong(resource,payload,cache):
            if Path(cache).name.startswith('draft'):
                return {'model':payload['model'],'choices':[{'finish_reason':'stop','message':{'content':'틀린 인용 [SOP-999:p1:fake]'}}]},{}
            return self.fake(resource,payload,cache)
        result=agent.answer('서버실 문서 규칙',self.run,wrong)
        self.assertEqual(result['status'],'insufficient_evidence')
        self.assertTrue(any('Citations outside' in issue for check in result['verification'] for issue in check['issues']))
    def test_model_approval_has_consistent_fields(self):
        def inconsistent(resource,payload,cache):
            if Path(cache).name.startswith('verify'):
                text=json.dumps({'approved':True,'issues':['Problem'],'missing_queries':[]})
                return {'model':payload['model'],'choices':[{'finish_reason':'stop','message':{'content':text}}]},{}
            return self.fake(resource,payload,cache)
        self.assertEqual(agent.answer('서버실 문서 규칙',self.run,inconsistent)['status'],'failed')
    def test_runtime_never_reads_private_answers(self):
        original_bytes,original_text=Path.read_bytes,Path.read_text
        def read_bytes(path,*a,**kw):
            self.assertNotIn('evaluation',path.parts);self.assertNotIn('PRIVATE',path.name)
            return original_bytes(path,*a,**kw)
        def read_text(path,*a,**kw):
            self.assertNotIn('evaluation',path.parts);self.assertNotIn('PRIVATE',path.name)
            return original_text(path,*a,**kw)
        with patch.object(Path,'read_bytes',read_bytes),patch.object(Path,'read_text',read_text):
            self.assertEqual(agent.answer('연구실 습도 70%일 때 실험 기준?',self.run,self.fake)['status'],'complete')

if __name__=='__main__':unittest.main()
