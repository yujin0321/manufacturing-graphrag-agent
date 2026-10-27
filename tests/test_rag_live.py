import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from imaks_kg.rag import live,vector as v


class LiveTests(unittest.TestCase):
    def temporary(self):
        root=v.REPO_ROOT/"kg_build/live_tests"
        root.mkdir(parents=True,exist_ok=True)
        return tempfile.TemporaryDirectory(dir=root)

    def test_new_question_uses_embedding_then_exact_context(self):
        calls=[]
        def fake(resource,payload,cache):
            calls.append((resource,payload))
            if resource=='embeddings':
                return {'model':payload['model'],'data':[{'index':0,'embedding':[1.0]*payload['dimensions']}],'usage':{}},{'cache_hit':False}
            return {'model':payload['model'],'choices':[{'finish_reason':'stop','message':{'content':'테스트 답변'}}],'usage':{}},{'cache_hit':False}
        with self.temporary() as tmp, patch.object(live.g,'cached_embeddings',side_effect=FileNotFoundError):
            run=Path(tmp)/'run';r=live.answer('SOP-003의 MAINT-03을 설명해 주세요. live test',run,fake)
            self.assertEqual([c[0] for c in calls],['embeddings','chat/completions'])
            payload=json.loads(calls[1][1]['messages'][1]['content'])
            self.assertEqual(payload['untrusted_reference_documents'],v.read(run/'retrieval.json')['context'])
            self.assertLessEqual(r['context_tokens'],4000)
            self.assertEqual(r['selected_ids'],[s['chunk_id'] for s in r['retrieved_sources']])
            with self.assertRaises(FileExistsError):live.answer('different',run,fake)
            self.assertEqual(len(calls),2)

    def test_invalid_question_never_calls_api(self):
        with self.temporary() as tmp:
            for q in ['', ' ', '가'*3000, None]:
                with self.assertRaises(ValueError):live.answer(q,Path(tmp)/'run',lambda *a:self.fail('API called'))
            self.assertFalse((Path(tmp)/'run').exists())

    def test_embedding_failure_stops_generation_and_is_redacted(self):
        calls=[]
        def fail(*args):
            calls.append(args[0]);raise RuntimeError('secret diagnostic must not be saved')
        with self.temporary() as tmp, patch.object(live.g,'cached_embeddings',side_effect=FileNotFoundError):
            run=Path(tmp)/'run'
            with self.assertRaises(RuntimeError):live.answer('new live failure question',run,fail)
            self.assertEqual(calls,['embeddings'])
            self.assertNotIn('secret', (run/'failure.json').read_text())
            self.assertFalse((run/'answer.json').exists())


if __name__=='__main__':unittest.main()
