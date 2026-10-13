import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from evaluate_llm_answers import evaluate

class AnswerReviewTests(unittest.TestCase):
    def setup_files(self,root,invalid_model=False,invalid_citation=False):
        requests=[]; answers=[]
        for mode in ['normalized_text','normalized_graph']:
            requests.append({'id':'Q','mode':mode,'prompt_sha256':'same',
                'messages':[{}, {'content':json.dumps({'context':[{'chunk_id':'C1'}]})}]})
            answers.append({'id':'Q','mode':mode,'prompt_sha256':'same',
                'model':'other' if invalid_model and mode=='normalized_graph' else 'test-model',
                'temperature':0,'answer':'test fixture only','citations':['UNKNOWN' if invalid_citation else 'C1']})
        (root/'llm_requests.jsonl').write_text('\n'.join(map(json.dumps,requests)),encoding='utf-8')
        path=root/'answers.jsonl'; path.write_text('\n'.join(map(json.dumps,answers)),encoding='utf-8')
        return path

    def test_different_models_rejected(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); path=self.setup_files(root,invalid_model=True)
            with patch('evaluate_llm_answers.OUT',root),self.assertRaises(ValueError): evaluate(path)

    def test_missing_pair_rejected(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); path=self.setup_files(root)
            path.write_text(path.read_text(encoding='utf-8').splitlines()[0],encoding='utf-8')
            with patch('evaluate_llm_answers.OUT',root),self.assertRaises(ValueError): evaluate(path)

    def test_citation_id_check_does_not_claim_semantic_correctness(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); path=self.setup_files(root,invalid_citation=True)
            with patch('evaluate_llm_answers.OUT',root): result=evaluate(path)
            self.assertTrue(result.citation_id_validity.eq(0).all())
            self.assertTrue(result.semantic_grounding_manual.isna().all())

if __name__=='__main__': unittest.main()
