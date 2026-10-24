import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from imaks_kg.rag import vector as v


class VectorRAGTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_tempdir = tempfile.tempdir
        cls.temp_root = v.REPO_ROOT / 'kg_build/vector_rag_test_tmp'
        cls.temp_root.mkdir(parents=True, exist_ok=True)
        tempfile.tempdir = str(cls.temp_root)

    @classmethod
    def tearDownClass(cls):
        tempfile.tempdir = cls.original_tempdir

    def test_known_cosine_ranking_and_ties(self):
        corpus=[{'chunk_id':'b'},{'chunk_id':'a'},{'chunk_id':'c'}]
        matrix=v.normalized([[1,0],[1,0],[0,1]],3,2)
        hits=v.retrieve(corpus,matrix,[10,0],2)
        self.assertEqual([h['chunk_id'] for h in hits],['a','b'])

    def test_rejects_invalid_vectors(self):
        for data in [[[0,0]],[[float('nan'),1]],[[1]]]:
            with self.assertRaises(ValueError):v.normalized(data,1,2)

    def test_response_index_reordering(self):
        def call(resource,payload,cache):
            return {'model':'test','data':[{'index':1,'embedding':[0,2]},{'index':0,'embedding':[3,0]}]},{}
        matrix,_=v.embed(['first','second'],{'embedding_model':'test','dimensions':2},None,call)
        np.testing.assert_allclose(matrix,np.eye(2))

    def test_missing_or_duplicate_api_indices(self):
        def call(*args):
            return {'model':'test','data':[{'index':0,'embedding':[1,0]},{'index':0,'embedding':[1,0]}]},{}
        with self.assertRaises(ValueError):v.embed(['a','b'],{'embedding_model':'test','dimensions':2},None,call)

    def test_model_fallback_rejected(self):
        def call(*args):return {'model':'other','data':[{'index':0,'embedding':[1,0]}]},{}
        with self.assertRaises(ValueError):v.embed(['a'],{'embedding_model':'test','dimensions':2},None,call)

    def test_budget_skips_whole_chunks(self):
        hits=[{'chunk_id':'long','doc_id':'d','page':1,'text':'large '*1000},
              {'chunk_id':'short','doc_id':'d','page':1,'text':'short evidence'}]
        text,chosen,skipped,n=v.context(hits,{'context_encoding':'o200k_base','context_token_budget':40})
        self.assertEqual([x['chunk_id'] for x in chosen],['short'])
        self.assertEqual(skipped,['long']);self.assertLessEqual(n,40)
        self.assertNotIn('large',text)

    def test_prepare_uses_only_fixed_source_and_no_api(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(v,'api_call',side_effect=AssertionError('No API')):
            plan=v.prepare(Path(tmp))
            self.assertEqual(plan['documents'],sorted(v.DOCS))
            corpus=v.read(Path(tmp)/'corpus.json')
            self.assertTrue(all(c['doc_id'] in v.DOCS for c in corpus))
            self.assertFalse(plan['evaluation_answers_loaded'])

    def test_tampered_source_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'chunks.jsonl';p.write_text('{}',encoding='utf-8')
            with patch.object(v,'SOURCE',p):
                with self.assertRaises(ValueError):v.source_records()

    def test_index_corruption_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);plan=v.prepare(p)
            corpus=v.read(p/'corpus.json')
            np.save(p/'vectors.npy',np.ones((len(corpus),plan['config']['dimensions']),dtype=np.float32))
            v.write(p/'index_manifest.json',{**plan,'vectors_sha256':v.digest((p/'vectors.npy').read_bytes())})
            v.load_index(p)
            corpus[0]['text']='modified'
            v.write(p/'corpus.json',corpus)
            with self.assertRaises(ValueError):v.load_index(p)

    def test_cached_api_response_needs_no_secret(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{},clear=True):
            p=Path(tmp);payload={'model':'example'}
            key=v.digest(v.encoded({'resource':'embeddings','payload':payload}))
            v.write(p/(key+'.response.json'),{'data':[]})
            with patch.object(v,'urlopen',side_effect=AssertionError('network')):
                _,meta=v.api_call('embeddings',payload,p)
            self.assertTrue(meta['cache_hit'])

    def test_unresolved_attempt_never_resends(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'OPENAI_API_KEY':'test-only'}):
            p=Path(tmp);payload={'model':'example'}
            key=v.digest(v.encoded({'resource':'embeddings','payload':payload}))
            (p/(key+'.attempt.json')).write_text('{}')
            with patch.object(v,'urlopen',side_effect=AssertionError('network')):
                with self.assertRaises(FileExistsError):v.api_call('embeddings',payload,p)

    def test_incomplete_generation_logged_not_scored(self):
        cfg=v.read(v.CONFIG);cfg['dimensions']=2
        corpus=[{'chunk_id':'synthetic:p1','doc_id':'synthetic','page':1,'text':'Synthetic component description'}]
        def call(resource,payload,cache):
            if resource=='embeddings':
                return {'model':cfg['embedding_model'],'data':[{'index':0,'embedding':[1,0]}]},{}
            return {'choices':[{'finish_reason':'length','message':{'content':'unfinished'}}]},{}
        with tempfile.TemporaryDirectory() as tmp, patch.object(v,'load_index',return_value=(corpus,np.array([[1.,0.]]),{'config':cfg})):
            run=Path(tmp)/'run'
            with self.assertRaises(ValueError):v.answer('Describe a synthetic component',Path(tmp),run,call)
            self.assertTrue((run/'failure.json').exists())
            self.assertFalse((run/'answer.json').exists())
            self.assertFalse(v.read(run/'failure.json')['grading_performed'])


if __name__=='__main__':unittest.main()
