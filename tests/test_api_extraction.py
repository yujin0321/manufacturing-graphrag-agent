import unittest
from imaks_kg.kg.run_llm import normalize_identifiers


class ApiExtractionTests(unittest.TestCase):
    def test_atomic_rules_keep_content_and_original_ids_in_ledger(self):
        raw = [dict(identifier='R1',conditionText='hot',responseText='stop'),
               dict(identifier='R1',conditionText='hot',responseText='notify')]
        out, ledger = normalize_identifiers(raw,'SOP-001')
        self.assertEqual(len({r['identifier'] for r in out}),2)
        self.assertEqual(raw[0]['identifier'],'R1')
        for before,after,entry in zip(raw,out,ledger):
            self.assertEqual(before,{**after,'identifier':entry['original']})

    def test_ambiguous_suffix_collision_fails(self):
        with self.assertRaisesRegex(ValueError,'collision'):
            normalize_identifiers([{'identifier':x} for x in ['R','R','R::part-1']],'SOP-001')

    def test_namespaces_separate_document_ids(self):
        a,_=normalize_identifiers([{'identifier':'R'}],'SOP-001')
        b,_=normalize_identifiers([{'identifier':'R'}],'SOP-002')
        self.assertNotEqual(a,b)
