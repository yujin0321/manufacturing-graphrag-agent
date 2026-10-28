import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from imaks_kg.rag import chunking, comparison as c, lexical, linking, retrieval_v3 as r3
from imaks_kg.rag import vector as v

MAINT04 = "https://example.org/imaks/id/MAINT-04"
MAINT04_EXTRACTED = "https://example.org/imaks/id/candidate-SOP-003%3A%3AMAINT-04"


class ChunkingTests(unittest.TestCase):
    def test_rows_keep_title_and_parent(self):
        table = {"chunk_id": "T:chunk", "kind": "table", "text": "[T] Title\nrow one\nrow two", "doc_id": "D"}
        rows = chunking.split_table_rows([table, {"chunk_id": "x", "kind": "rule", "text": "rule"}])
        self.assertEqual([r["chunk_id"] for r in rows], ["T:chunk#r1", "T:chunk#r2", "x"])
        self.assertEqual(rows[1]["text"], "[T] Title\nrow two")
        self.assertEqual({r["parent_chunk_id"] for r in rows[:2]}, {"T:chunk"})
        self.assertEqual(chunking.parent_of("T:chunk#r2"), "T:chunk")

    def test_provenance_row_index_counts_header(self):
        self.assertIsNone(chunking.provenance_row_number("1"))
        self.assertEqual(chunking.provenance_row_number("5"), 4)

    def test_real_corpus_row_split_is_stable(self):
        rows = r3.row_corpus()
        self.assertEqual(len({r["parent_chunk_id"] for r in rows}), 86)
        maint = [r for r in rows if r["parent_chunk_id"] == "SOP-003:p1:table1:chunk"]
        self.assertEqual(len(maint), 8)
        self.assertIn("MAINT-04", maint[3]["text"])


class LexicalTests(unittest.TestCase):
    def test_compound_ids_and_korean_particles(self):
        tokens = lexical.tokenize("ST02_SEALING-CUR와 서버실의")
        for t in ["st02_sealing-cur", "st02", "sealing", "cur", "서버실"]:
            self.assertIn(t, tokens)

    def test_bm25_prefers_rare_matching_term(self):
        bm = lexical.BM25(["pump pump filter", "pump", "bearing"])
        s = bm.scores("filter")
        self.assertGreater(s[0], s[1])
        self.assertEqual(s[2], 0)

    def test_rrf_deterministic(self):
        self.assertEqual(lexical.rrf([["a", "b"], ["b", "a"]]), ["a", "b"])


class LinkingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = c.load_graph()
        cls.index = linking.EntityIndex.build(cls.g)

    def linked(self, question):
        return {m.node.rsplit("/", 1)[-1] for m in self.index.link(question)}

    def test_shorthand_and_korean_compose_sensor(self):
        self.assertIn("ST02_SEALING_CUR", self.linked("ST02 전류가 명목보다 높다"))
        self.assertIn("SRV01_SERVERROOM_TMP", self.linked("서버실 온도가 26°C"))
        self.assertIn("ST04_PACKAGING_VIB", self.linked("포장기 진동이 심하다"))

    def test_longest_station_alias_wins(self):
        linked = self.linked("화학 창고 습도")
        self.assertIn("CHM01_CHEMICALSTORAGE_HUM", linked)
        self.assertNotIn("WRH01_WAREHOUSE", linked)

    def test_type_far_from_station_is_not_composed(self):
        linked = self.linked("ST02 공정에서 작업자가 오랫동안 기다렸는데 결국 진동이 생겼다")
        self.assertNotIn("ST02_SEALING_VIB", linked)  # does not exist anyway
        self.assertFalse(any(x.endswith("_VIB") for x in linked))

    def test_rule_id_with_particle_and_prefix(self):
        linked = self.linked("MAINT-03의 조치")
        self.assertIn("MAINT-03", linked)
        self.assertIn("candidate-SOP-003%3A%3AMAINT-03", linked)
        self.assertNotIn("MAINT-03", self.linked("MAINT-030"))

    def test_duplicates_grouped_and_conflict_kept(self):
        group = self.index.group_of(MAINT04)
        self.assertEqual(group, sorted([MAINT04, MAINT04_EXTRACTED]))
        card = linking.merged_card(self.g, group, {})
        responses = {x["value"] for x in card["properties"]["responseText"]}
        self.assertEqual(responses, {"Inspect inlet filter and pump", "Inspect filter and pump. Priority: MEDIUM."})


class ContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = r3.row_corpus()
        cls.g = c.load_graph()

    def test_vector_never_touches_graph(self):
        with patch.object(c, "load_graph", side_effect=AssertionError("KG read")):
            out = r3.build_context("vector_v3", "ST01 압력", self.rows, None)
        self.assertFalse(out["graph_used"])

    def test_graph_only_adds_to_shared_candidates(self):
        q = "ST01 압력이 3.2 bar로 16분 지속되었다. 정비 규칙은?"
        vec = r3.build_context("vector_v3", q, self.rows, None)
        gra = r3.build_context("graph_v3", q, self.rows, None, self.g)
        self.assertEqual(vec["shared_prefix"], gra["shared_prefix"])
        self.assertIn("SOP-003:p1:table1:chunk#r4", gra["graph_rows"])  # MAINT-04 row via sensor
        self.assertLessEqual(gra["context_tokens"], r3.load_policy()["context_token_budget"])

    def test_graph_reaches_cross_document_rules_from_natural_language(self):
        out = r3.build_context("graph_v3", "서버실이 너무 더워요. 온도 관련 규칙 알려줘", self.rows, None, self.g)
        parents = set(out["selected_parent_ids"])
        self.assertIn("SOP-003:p1:table1:chunk", parents)  # MAINT-05
        self.assertIn("SOP-001:p2:RULE-SRV01-02", parents)
        self.assertIn("SOP-002:p1:table5:chunk", parents)

    def test_lexicon_control_expands_names_only(self):
        q = "서버실 온도가 높아요"
        expanded, names = r3.expand_query(q, self.g)
        self.assertEqual(names, ["SRV01_SERVERROOM", "SRV01_SERVERROOM_TMP"])
        out = r3.build_context("vector_v3_lex", q, self.rows, None, self.g)
        self.assertFalse(out["graph_used"])
        self.assertNotIn("graph_rows", out)  # no traversal, no provenance rows

    def test_budget_respected_with_tiny_budget(self):
        policy = r3.load_policy()
        policy["context_token_budget"] = 60
        out = r3.build_context("graph_v3", "ST02 전류", self.rows, None, self.g, policy)
        self.assertLessEqual(out["context_tokens"], 60 + 1)

    def test_full_context_contains_every_chunk(self):
        out = r3.full_context_text()
        self.assertEqual(len(out["selected_ids"]), 86)

    def test_answer_records_failure_and_never_reads_keys(self):
        def fake(resource, payload, cache):
            if resource == "embeddings":
                raise AssertionError("dense disabled in this test")
            text = payload["messages"][1]["content"]
            self.assertNotIn("PRIVATE", text)
            return {"model": "gpt-6.1-sol", "choices": [{"finish_reason": "length", "message": {"content": "x"}}]}, {}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                r3.answer("graph_v3", "ST02 전류", Path(tmp) / "run", call=fake, use_dense=False)
            self.assertEqual(json.loads((Path(tmp) / "run/failure.json").read_text())["status"], "failed")


if __name__ == "__main__":
    unittest.main()
