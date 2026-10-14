"""요청 빌더 시험(가짜 문서 묶음 + 실제 문서). API 호출 없음."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_b_helpers as h  # noqa: E402

from imaks_kg.extract.docdata import DocumentStore, load_allowlist  # noqa: E402
from imaks_kg.extract.request_builder import (ExampleError, SplitError, build_all, build_doc_requests,  # noqa: E402
                                              load_prompt_files, make_units, require_registered_example)
from imaks_kg.extract.run import build_requests, run_extraction  # noqa: E402


def fake(tmp, specs):
    d, i = h.write_fake_docs(tmp, specs)
    return DocumentStore(d), load_allowlist(i)


TABLE = {"rows": [["Rule ID", "Trigger", "Action"], ["R1", "TRQ >70 kNm", "Check gearbox"]], "caption": "Cap"}


class Build(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.ex, self.reg = h.make_registered_example(self.tmp)
        self.cfg = h.make_cfg(self.tmp, self.ex)
        self.rt, self.schema = load_prompt_files()

    def tearDown(self):
        self._t.cleanup()

    def build(self, store, allow, doc, cfg=None):
        return build_doc_requests(doc, store, allow, role_task=self.rt, schema=self.schema, example_text="EX",
                                  example_sha256="e" * 64, config=cfg or self.cfg, requested_model="gemini/m1")

    def test_one_request_per_document_title_merge_and_markers(self):
        store, allow = fake(self.tmp, {"T-1": [("text", "Header line one\nsecond line of header text", None),
                                               ("text", "3. Mixer Rules", None),
                                               ("text", "RULE-X: do the thing carefully now.", "3. Mixer Rules"),
                                               ("table", TABLE, "3. Mixer Rules")],
                                       "T-2": [("text", "Only one long enough chunk of plain text here.", None)]})
        reqs = self.build(store, allow, "T-1")
        self.assertEqual(len(reqs), 1)
        b = reqs[0]
        self.assertEqual(b.merged_title_ids, ["T-1:p1:text2"])
        self.assertNotIn("T-1:p1:text2", b.sent_chunk_ids)
        self.assertNotIn("<<chunk T-1:p1:text2", b.request.prompt)
        self.assertIn("<<chunk T-1:p1:text3 | page 1>>\nSection: 3. Mixer Rules", b.request.prompt)
        self.assertEqual(len(self.build(store, allow, "T-2")), 1)

    def test_title_threshold_is_under_30_chars(self):
        store, _ = fake(self.tmp, {"T-1": [("text", "x" * 29, None), ("text", "y" * 30, None), ("text", "tail text long enough here", None)]})
        units = make_units(store.chunks_by_doc["T-1"])
        self.assertEqual([u.chunk.chunk_id for u in units], ["T-1:p1:text2", "T-1:p1:text3"])
        self.assertEqual([t.chunk_id for t in units[0].titles], ["T-1:p1:text1"])

    def test_table_rows_and_cols_are_one_based(self):
        store, allow = fake(self.tmp, {"T-1": [("table", TABLE, None)]})
        p = self.build(store, allow, "T-1")[0].request.prompt
        self.assertIn("[행 1] [열1] Rule ID [열2] Trigger [열3] Action", p)
        self.assertIn("[행 2] [열1] R1 [열2] TRQ >70 kNm [열3] Check gearbox", p)
        self.assertNotIn("[행 0]", p)
        self.assertNotIn("[열0]", p)

    def test_allowlist_and_meta_flags(self):
        store, allow = fake(self.tmp, {"T-1": [("text", "Only one long enough chunk of plain text here.", None)]})
        b = self.build(store, allow, "T-1")[0]
        self.assertIn("QX01_MIXER", b.request.prompt)
        self.assertIn("QX02_PUMP_FLW", b.request.prompt)
        m = b.meta
        self.assertIs(m["answer_key_supplied"], False)
        self.assertIs(m["seed_maintenance_text_supplied"], False)
        for k in ("prompt_sha256", "schema_sha256", "example_sha256", "input_sha256", "document_input_sha256",
                  "document_pdf_sha256", "document_id", "requested_model"):
            self.assertTrue(m[k], k)
        self.assertEqual(m["example_sha256"], "e" * 64)
        self.assertIs(b.request.answer_key_supplied, False)

    def test_split_at_section_boundary_keeps_continued_table_together(self):
        big = "w" * 2500
        cont_a = dict(TABLE, continues_in="T-1:p1:table2")
        cont_b = {"rows": [["R2", "TRQ >80", "Stop"]], "continued_from": "T-1:p1:table1"}
        specs = {"T-1": [("text", big, "S1"), ("table", cont_a, "S1"), ("table", cont_b, "S1"),
                         ("text", big, "S2"), ("text", big, "S3")]}
        store, allow = fake(self.tmp, specs)
        cfg = h.make_cfg(self.tmp, self.ex, max_input_tokens_est=10000, chars_per_token=1.0)
        # 한도 안: 분할 없음
        self.assertEqual(len(self.build(store, allow, "T-1")), 1)
        # 한도를 넘기면 section 경계로 분할
        reqs = self.build(store, allow, "T-1", cfg)
        self.assertGreater(len(reqs), 1)
        allc = [c for r in reqs for c in r.sent_chunk_ids]
        self.assertEqual(allc, [c.chunk_id for c in store.chunks_by_doc["T-1"]])  # 빠짐·중복·순서 변경 없음
        part_of = {c: r.part for r in reqs for c in r.sent_chunk_ids}
        self.assertEqual(part_of["T-1:p1:table1:chunk"], part_of["T-1:p1:table2:chunk"])  # 연속 표는 같은 요청
        self.assertTrue(all(r.meta["n_parts"] == len(reqs) for r in reqs))

    def test_unsplittable_stops_without_cutting(self):
        store, allow = fake(self.tmp, {"T-1": [("text", "w" * 4000, "S1"), ("text", "v" * 4000, "S1")]})
        cfg = h.make_cfg(self.tmp, self.ex, max_input_tokens_est=3000, chars_per_token=1.0)
        with self.assertRaises(SplitError):
            self.build(store, allow, "T-1", cfg)

    def test_unsplittable_run_records_and_makes_no_call(self):
        d, i = h.write_fake_docs(self.tmp / "fx", {"T-1": [("text", "w" * 4000, "S1"), ("text", "v" * 4000, "S1")]})
        cfg = h.make_cfg(self.tmp, self.ex, max_input_tokens_est=3000, chars_per_token=1.0)
        from imaks_kg.extract.providers.mock import ScriptedByDocMock
        prov = {"gemini": ScriptedByDocMock("gemini", {})}
        with self.assertRaises(SplitError):
            run_extraction(cfg, run_id="r1", providers=prov, registry_path=self.reg, documents_dir=d, instances_dir=i,
                           out_root=self.tmp / "out")
        self.assertEqual(prov["gemini"].calls, [])
        self.assertTrue((Path(cfg.log_dir) / "requests" / "r1" / "split_error.json").is_file())

    def test_seed_maintenance_text_not_read(self):
        # 빌더 코드는 nodes.csv와 maintenance_rules.csv를 열지 않는다(소스에 이름이 없다).
        src = (Path(h.ROOT) / "src/imaks_kg/extract/request_builder.py").read_text(encoding="utf-8")
        src += (Path(h.ROOT) / "src/imaks_kg/extract/docdata.py").read_text(encoding="utf-8")
        self.assertNotIn("nodes.csv", src)
        self.assertNotIn("maintenance_rules", src)
        self.assertNotIn("kg_seed", src)

    def test_build_requests_writes_files_only(self):
        d, i = h.write_fake_docs(self.tmp / "fx", {"T-1": [("text", "Only one long enough chunk of plain text here.", None)]})
        rr = build_requests(self.cfg, run_id="rq", registry_path=self.reg, documents_dir=d, instances_dir=i)
        f = Path(self.cfg.log_dir) / "requests" / "rq" / "T-1.request.json"
        self.assertTrue(f.is_file())
        self.assertEqual(json.loads(f.read_text(encoding="utf-8"))["meta"]["document_id"], "T-1")
        self.assertFalse((Path(self.cfg.log_dir) / "calls_rq.jsonl").exists())


class ExampleGate(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)

    def tearDown(self):
        self._t.cleanup()

    def test_empty_path_missing_file_and_unregistered_are_refused(self):
        reg = self.tmp / "reg.json"
        reg.write_text('{"version":1,"entries":[]}', encoding="utf-8")
        with self.assertRaises(ExampleError):
            require_registered_example("", reg)
        with self.assertRaises(ExampleError):
            require_registered_example(self.tmp / "nope.txt", reg)
        f = self.tmp / "e.txt"
        f.write_text("hello", encoding="utf-8")
        with self.assertRaises(ExampleError) as cm:
            require_registered_example(f, reg)
        self.assertIn("example_check", str(cm.exception))

    def test_registered_passes_and_edit_after_registration_is_refused(self):
        ex, reg = h.make_registered_example(self.tmp)
        text, sha = require_registered_example(ex, reg)
        self.assertEqual(len(sha), 64)
        ex.write_bytes(ex.read_bytes() + b"x")
        with self.assertRaises(ExampleError):
            require_registered_example(ex, reg)

    def test_run_refuses_without_registry_entry(self):
        d, i = h.write_fake_docs(self.tmp / "fx", {"T-1": [("text", "Only one long enough chunk of plain text here.", None)]})
        ex = self.tmp / "e.txt"
        ex.write_text("x", encoding="utf-8")
        reg = self.tmp / "reg.json"
        reg.write_text('{"version":1,"entries":[]}', encoding="utf-8")
        cfg = h.make_cfg(self.tmp, ex)
        with self.assertRaises(ExampleError):
            run_extraction(cfg, registry_path=reg, documents_dir=d, instances_dir=i, out_root=self.tmp / "o")

    def test_shipped_registry_is_wellformed_and_code_never_writes_example(self):
        # 사용자가 Example을 등록하면 항목이 생긴다: 비어 있다고 가정하지 않는다.
        reg = json.loads((Path(h.ROOT) / "src/imaks_kg/extract/prompts/example_registry.json").read_text(encoding="utf-8"))
        self.assertIsInstance(reg["entries"], list)
        for e in reg["entries"]:
            self.assertEqual(len(e["sha256"]), 64)
        code = "".join(p.read_text(encoding="utf-8") for p in (Path(h.ROOT) / "src/imaks_kg/extract").glob("*.py"))
        self.assertNotIn("example_v1", code)   # 코드가 Example 파일을 만들거나 이름을 박지 않는다


class RealDocs(unittest.TestCase):
    def test_real_documents_build(self):
        store, allow = h.real_store(), h.real_allow()
        self.assertEqual((len(allow.stations), len(allow.sensors)), (9, 22))
        with tempfile.TemporaryDirectory() as t:
            ex, _ = h.make_registered_example(Path(t))
            cfg = h.make_cfg(Path(t), ex)
            reqs = build_all(store.doc_ids(), store, allow, cfg, example_text="EX", example_sha256="e" * 64)
        self.assertEqual(len(reqs), 7)
        sop2 = [r for r in reqs if r.doc_id == "SOP-002"][0]
        self.assertIn("continued from SOP-002:p1:table5", sop2.request.prompt)
        sop3 = [r for r in reqs if r.doc_id == "SOP-003"][0]
        self.assertIn("[행 9] [열1] MAINT-08", sop3.request.prompt)


if __name__ == "__main__":
    unittest.main()
