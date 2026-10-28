import json
from pathlib import Path
import tempfile
import unittest
from imaks_kg.rag import agent_v4_1 as a,retrieval_v4_1 as r,vector as v

class CoverageTests(unittest.TestCase):
    def test_unknown_global_coverage_is_not_a_false_guarantee(self):
        result=r.retrieve('서버실 온도 기준과 자동 조치')
        self.assertIsNone(result['coverage_complete'])
        self.assertIn('not established',result['coverage_scope'])
    def test_typed_coverage_keeps_explicit_scope(self):
        result=r.retrieve('CRITICAL 예측 정비 규칙 모두')
        self.assertTrue(result['coverage_complete']);self.assertEqual(len(result['coverage_required_ids']),3)
    def test_grounded_partial_answer_is_returned_with_completeness_flag(self):
        root=v.REPO_ROOT/'kg_build/agent_v4_1_tests';root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as tmp:
            stages=[]
            def fake(resource,payload,cache):
                stage=Path(cache).name;stages.append(stage)
                if stage.startswith('verify'):
                    text=json.dumps({'approved':True,'answer_complete':False,'issues':[],'missing_queries':[]})
                else:
                    data=json.loads(payload['messages'][-1]['content'])
                    import re
                    cid=re.search(r'\[([^\]\n]+)\]',data['untrusted_reference_data']).group(1)
                    text='검색된 발췌에서 확인되는 기준입니다. 전체 자료의 완전성을 확인한 것은 아닙니다. ['+cid+']'
                return {'model':payload['model'],'choices':[{'finish_reason':'stop','message':{'content':text}}]},{}
            result=a.answer('서버실 온도 문서 기준',Path(tmp)/'run',fake)
            self.assertEqual(result['status'],'complete');self.assertFalse(result['answer_complete'])
            self.assertEqual(stages,['draft1','verify1'])

if __name__=='__main__':unittest.main()
