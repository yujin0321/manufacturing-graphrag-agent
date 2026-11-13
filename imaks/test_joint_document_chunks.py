"""Synthetic chunk provenance checks without model files or source PDFs."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

import numpy as np

from rerun_joint_documents import make_chunks, verify_chunks


class FakeTokenizer:
    def encode(self, text):
        return SimpleNamespace(ids=range(len(text) + 2))


class JointDocumentChunkTests(unittest.TestCase):
    def documents(self):
        return [{'doc_id': 'DOC-A', 'source_header': ['Example source'],
                 'sha256': 'a' * 64, 'pages': 2, 'source': 'rules/example.pdf'}]

    def page(self, number, text):
        lines, offset = [], 0
        for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
            lines.append({'line': line_number, 'start': offset, 'end': offset + len(line)})
            offset += len(line)
        return {'doc_id': 'DOC-A', 'page_id': f'DOC-A-p{number}', 'page': number,
                'source': 'rules/example.pdf', 'text': text, 'lines': lines}

    def table_case(self):
        pages = [self.page(1, 'First page source.\n'), self.page(2, 'Continued page source.\n')]
        header = ['Sensor', 'Condition']
        rows = [[f'TMP{i}', f'>= {i + 10} AND stable for 15 consecutive samples'] for i in range(5)]
        continued_rows = [['HUM', '< 30 for 10 consecutive readings'],
                          ['PRS', '> 4 AND operator confirmation required']]
        tables = [{'table_id': 'T1', 'doc_id': 'DOC-A', 'page': 1, 'page_id': pages[0]['page_id'],
                   'cells': [header] + rows, 'bbox': [10, 20, 100, 200]},
                  {'table_id': 'T2', 'doc_id': 'DOC-A', 'page': 2, 'page_id': pages[1]['page_id'],
                   'cells': continued_rows, 'bbox': [11, 21, 101, 201],
                   'continues_table': 'T1'}]
        chunks = make_chunks(pages, tables, self.documents(), FakeTokenizer(), max_tokens=150)
        return pages, tables, chunks

    def test_all_characters_exact_offsets_and_whole_rule_block_are_preserved(self):
        rule = 'RULE-TEST-01: TMP > 90 AND PRS < 1 for 5 min.\nAction: inspect sensor.\n'
        text = 'Introduction.\n' + 'A' * 450 + '\n' + rule + '2.1 Notes\n' + 'B' * 800 + '\n'
        pages = [self.page(1, text)]
        documents = self.documents()
        chunks = make_chunks(pages, [], documents, FakeTokenizer(), max_tokens=480)
        report = verify_chunks(chunks, pages, [], documents)
        self.assertTrue(report['all_page_characters_covered'])
        covered = np.zeros(len(text), dtype=bool)
        text_chunks = [chunk for chunk in chunks if chunk['kind'] == 'page_text']
        self.assertGreater(len(text_chunks), 1)
        for chunk in text_chunks:
            self.assertEqual(text[chunk['char_start']:chunk['char_end']], chunk['text'])
            covered[chunk['char_start']:chunk['char_end']] = True
            self.assertLessEqual(chunk['embedding_tokens'], 480)
            self.assertIn(chunk['text'], chunk['embedding_text'])
        self.assertTrue(covered.all())
        rule_chunks = [chunk for chunk in chunks if chunk['kind'] == 'rule_block']
        self.assertEqual(len(rule_chunks), 1)
        self.assertEqual(rule_chunks[0]['rule_id'], 'RULE-TEST-01')
        self.assertEqual(rule_chunks[0]['text'], rule)
        self.assertTrue(rule_chunks[0]['whole_rule_block'])

    def test_rows_split_without_loss_and_continued_header_uses_next_page_source(self):
        pages, tables, chunks = self.table_case()
        verify_chunks(chunks, pages, tables, self.documents())
        table_chunks = [chunk for chunk in chunks if chunk['kind'] == 'table_rows']
        self.assertGreater(len([chunk for chunk in table_chunks if chunk['table_id'] == 'T1']), 1)
        for table in tables:
            relevant = [chunk for chunk in table_chunks if chunk['table_id'] == table['table_id']]
            observed = [row for chunk in relevant for row in chunk['source_row_indices']]
            expected = list(range(1, len(table['cells']))) if table['table_id'] == 'T1' else list(range(len(table['cells'])))
            self.assertEqual(observed, expected)
            for chunk in relevant:
                self.assertEqual(chunk['text'].splitlines()[0], 'Sensor | Condition')
                self.assertEqual(chunk['original_header_table_id'], 'T1')
                self.assertEqual(chunk['source_bbox'], table['bbox'])
                self.assertEqual(chunk['page_id'], table['page_id'])
                self.assertEqual(chunk['page'], 1 if table['table_id'] == 'T1' else 2)
                self.assertEqual(chunk['corrected_cells'], [table['cells'][i] for i in chunk['source_row_indices']])
                self.assertLessEqual(chunk['embedding_tokens'], 150)
        continued = [chunk for chunk in table_chunks if chunk['table_id'] == 'T2']
        self.assertTrue(all(chunk['continues_table'] == 'T1' for chunk in continued))
        self.assertEqual(continued[0]['source_row_indices'][0], 0)

    def test_one_oversized_table_row_is_rejected_not_truncated(self):
        pages = [self.page(1, 'Short source.\n')]
        tables = [{'table_id': 'T1', 'doc_id': 'DOC-A', 'page': 1, 'page_id': 'DOC-A-p1',
                   'cells': [['Condition'], ['X' * 300]], 'bbox': [1, 2, 3, 4]}]
        with self.assertRaisesRegex(ValueError, 'One table row cannot fit'):
            make_chunks(pages, tables, self.documents(), FakeTokenizer(), max_tokens=100)

    def test_title_prefix_exceeding_budget_is_rejected_without_looping(self):
        documents = self.documents()
        documents[0]['source_header'][0] = 'X' * 200
        with self.assertRaisesRegex(ValueError, 'metadata leaves no embedding token budget'):
            make_chunks([self.page(1, 'One source character.')], [], documents,
                        FakeTokenizer(), max_tokens=100)

    def test_offset_and_original_row_tampering_are_rejected(self):
        pages, tables, chunks = self.table_case()
        altered = deepcopy(chunks)
        text_chunk = next(chunk for chunk in altered if chunk['kind'] == 'page_text')
        text_chunk['char_start'] += 1
        with self.assertRaises((AssertionError, ValueError)):
            verify_chunks(altered, pages, tables, self.documents())
        altered = deepcopy(chunks)
        row_chunk = next(chunk for chunk in altered if chunk.get('table_id') == 'T1')
        row_chunk['source_row_indices'][0] += 1
        with self.assertRaises((AssertionError, ValueError)):
            verify_chunks(altered, pages, tables, self.documents())

    def test_pdf_hash_and_continued_page_tampering_are_rejected(self):
        pages, tables, chunks = self.table_case()
        altered = deepcopy(chunks)
        altered[0]['source_pdf_sha256'] = 'b' * 64
        with self.assertRaises((AssertionError, ValueError)):
            verify_chunks(altered, pages, tables, self.documents())
        altered = deepcopy(chunks)
        continued_chunk = next(chunk for chunk in altered if chunk.get('table_id') == 'T2')
        continued_chunk['page_id'] = 'DOC-A-p1'
        continued_chunk['page'] = 1
        with self.assertRaises((AssertionError, ValueError)):
            verify_chunks(altered, pages, tables, self.documents())


if __name__ == '__main__':
    unittest.main()
