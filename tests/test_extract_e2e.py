"""C: 가짜 응답 끝까지(fake → validate → merge → 검토 양식 → 전부 수락 → apply → to_rdf) + 합본 SHACL,
결정성, 실행 기록(재현 정보), 데이터시트 충돌 후보, 소스 정적 검사.

실행: PYTHONPATH=src .venv/Scripts/python.exe -m unittest tests.test_extract_e2e -v
"""
import json
import re
import sys
import unittest
from pathlib import Path

from rdflib import RDF, Graph

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_support as S  # noqa: E402
from imaks_kg import settings  # noqa: E402
from imaks_kg.common.provenance import sha256_file, sha256_text  # noqa: E402
from imaks_kg.extract import conflicts, review, to_rdf  # noqa: E402
from imaks_kg.extract.common import read_jsonl, safe_name  # noqa: E402
from imaks_kg.kg.naming import IM  # noqa: E402

DET_FILES = ("calls.jsonl", "candidates_premerge.jsonl", "rejected.csv", "merged.jsonl", "merge_conflicts.csv",
             "review_round1.csv", "final.jsonl")
RULE_CLASSES = ("OperationalRule", "ThresholdRule", "MaintenanceRule", "AccessRule")


def full_run(base, run_id):
    from imaks_kg.extract import ledger
    ledger.LEDGER_OVERRIDE = Path(base) / "ledger.jsonl"  # 같은 run_id로 두 번 돌리므로 실행마다 장부를 따로 둔다
    run_dir = S.fake_run(base, run_id)
    S.fill_round1(run_dir)
    review.make_round2(run_dir)
    review.apply_review(run_dir)
    res = to_rdf.run(run_dir, Path(base) / "kg")
    ledger.LEDGER_OVERRIDE = S.PROCESS_LEDGER
    return run_dir, res


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        why = S.needs_inputs()
        if why:
            raise unittest.SkipTest(why)
        cls.ctx = S.ctx()
        cls._a, cls._b = S.tmpdir(), S.tmpdir()
        cls.run_a, cls.res_a = full_run(cls._a.name, "t-e2e")
        cls.run_b, cls.res_b = full_run(cls._b.name, "t-e2e")

    @classmethod
    def tearDownClass(cls):
        cls._a.cleanup()
        cls._b.cleanup()

    def test_combined_shacl_pass(self):
        g = Graph().parse(str(self.res_a["outs"]["merged"]))
        ok, text = S.shacl(g)
        self.assertTrue(ok, text)
        # 검토 전 결과도 seed + B와 합치면 적합
        pre = Graph().parse(str(self.res_a["outs"]["prereview"]))
        for t in self.ctx["seed"]["graph"]:
            pre.add(t)
        for t in self.ctx["b"]["graph"]:
            pre.add(t)
        ok, text = S.shacl(pre)
        self.assertTrue(ok, text)

    def test_deterministic(self):
        for name in DET_FILES:
            self.assertEqual(sha256_file(self.run_a / name), sha256_file(self.run_b / name), name)
        for key in ("final", "prereview", "merged"):
            self.assertEqual(sha256_file(self.res_a["outs"][key]), sha256_file(self.res_b["outs"][key]), key)

    def test_reproducibility_record(self):
        meta = json.loads((self.run_a / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["model"], "claude-opus-5-5")
        self.assertEqual(meta["effort"], "high")
        self.assertEqual(meta["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(meta["fallbacks"], "default")
        self.assertIn("temperature", meta["params_not_sent"])
        self.assertTrue(meta["anthropic_sdk_version"])
        self.assertEqual(meta["prompt_sha256"], self.ctx["prompt"]["prompt_sha256"])
        self.assertEqual(meta["preprocess_lock_sha256"], sha256_file(settings.PREPROCESS_LOCK))
        self.assertEqual([c["chunk_id"] for c in meta["input_chunks"]], [c["chunk_id"] for c in self.ctx["selected"]])
        for c in meta["input_chunks"]:
            self.assertEqual(c["text_sha256"], self.ctx["chunks_by_id"][c["chunk_id"]]["text_sha256"])
        self.assertEqual(len(meta["excluded_chunks"]), len(self.ctx["excluded"]))
        self.assertTrue(meta["started_at"] and meta["finished_at"])
        for c in self.ctx["selected"]:
            name = safe_name(c["chunk_id"])
            req = json.loads((self.run_a / "raw" / "request" / f"{name}.json").read_text(encoding="utf-8"))
            self.assertNotIn("api_key", json.dumps(req).lower())
            self.assertTrue((self.run_a / "raw" / "response" / f"{name}.json").exists())

    def test_rejections_recorded(self):
        _, rows = S.read_rows(self.run_a / "rejected.csv")
        codes = {(r["chunk_id"], r["reason_code"]) for r in rows}
        for exp in [("SOP-001:p2:RULE-CAF01-01", "sensor_not_in_list"), ("SOP-001:p2:RULE-CAF01-01", "quote_not_in_chunk"),
                    ("SOP-001:p2:RULE-RND01-01", "schema"), ("SOP-001:p2:RULE-CHM01-01", "rule_id_not_in_chunk"),
                    ("SOP-001:p2:RULE-CHM01-02", "station_not_in_list"), ("SOP-001:p2:RULE-SRV01-02", "call_failed"),
                    ("SOP-001:p2:RULE-CAF01-02", "call_failed")]:
            self.assertIn(exp, codes)
        for r in rows:
            self.assertTrue(r["reason"])

    def test_rdf_provenance_complete(self):
        g = self.res_a["final_graph"]
        provs = set(g.subjects(RDF.type, IM.Provenance))
        self.assertTrue(provs)
        final = {to_rdf.prov_iri("t-e2e", r["candidate_id"]): r for r in read_jsonl(self.run_a / "final.jsonl")}
        self.assertEqual(provs, set(final))
        for pv in provs:
            r = final[pv]
            quote = str(next(g.objects(pv, IM.sourceQuote)))
            self.assertEqual(str(next(g.objects(pv, IM.textSha256))), sha256_text(quote))
            self.assertEqual(str(next(g.objects(pv, IM.extractionMethod))), "llm")
            self.assertEqual(int(next(g.objects(pv, IM.page))), r["page"])
            chunk = self.ctx["chunks_by_id"][r["chunk_id"]]
            self.assertIn(quote, chunk["text"])
            if chunk["kind"] == "table":
                self.assertTrue(list(g.objects(pv, IM.tableId)) and list(g.objects(pv, IM.colIndex)))
            else:
                cs, ce = int(next(g.objects(pv, IM.charStart))), int(next(g.objects(pv, IM.charEnd)))
                page = self.ctx["docs"]["pages"][(chunk["doc_id"], chunk["page"])]["text_normalized"]
                self.assertEqual(page[cs:ce].replace("\n", " "), quote)
        for cls in RULE_CLASSES:
            for s in g.subjects(RDF.type, IM[cls]):
                self.assertEqual(str(next(g.objects(s, IM.extractionMethod))), "llm")
                self.assertEqual(len(list(g.objects(s, IM.sourceDocument))), 1)

    def test_fallback_flag_in_outputs(self):
        recs = {r["candidate_id"]: r for r in read_jsonl(self.run_a / "final.jsonl")}
        self.assertTrue(recs["SOP-001:p2:RULE-SRV01-01:r1"]["fallback_used"])
        meta = json.loads((self.run_a / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["counts"]["fallback_served"], 1)


class Conflicts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        why = S.needs_inputs()
        if why:
            raise unittest.SkipTest(why)
        cls.rows, cls.specs = conflicts.collect()
        cls.ctx = S.ctx()

    def test_known_candidates_present(self):
        got = {(r["sensor_id"], r["sop_field"], r["ds_doc"]) for r in self.rows}
        self.assertIn(("ST02_SEALING_TMP", "critHi", "DS-THERM-2200"), got)
        self.assertIn(("ST02_SEALING_CUR", "critHi", "DS-ELEC-3300"), got)
        self.assertIn(("ST01_FILLING_PRS", "warnHi", "DS-MECH-4400"), got)
        self.assertEqual({r["sensor_id"] for r in self.rows},
                         {"ST02_SEALING_TMP", "ST02_SEALING_CUR", "ST01_FILLING_PRS"})

    def test_both_sources_recorded(self):
        tables = self.ctx["docs"]["tables"]
        pages = self.ctx["docs"]["pages"]
        for r in self.rows:
            t = tables[r["sop_table_id"]]
            cell = next(c for c in t["cells"] if c["row"] + 1 == r["sop_row"] and c["col"] + 1 == r["sop_col"])
            self.assertEqual(cell["text_normalized"], r["sop_quote"])
            self.assertEqual(r["sop_sha256"], sha256_text(r["sop_quote"]))
            self.assertEqual(r["ds_sha256"], sha256_text(r["ds_quote"]))
            self.assertTrue(r["sop_label"] and r["ds_label"])
            m = re.match(r"page (\d+) char (\d+)-(\d+)$", r["ds_location"])
            if m:
                text = pages[(r["ds_doc"], int(m.group(1)))]["text_normalized"]
                self.assertEqual(text[int(m.group(2)):int(m.group(3))], r["ds_quote"])
            else:
                tid = r["ds_location"].split(" ")[0]
                self.assertTrue(any(c["text_normalized"] == r["ds_quote"] for c in tables[tid]["cells"]))

    def test_values_not_unified(self):
        tmp = {r["sop_value"] for r in self.rows if r["sensor_id"] == "ST02_SEALING_TMP"}
        self.assertEqual(tmp, {"210.0"})
        self.assertEqual({r["ds_value"] for r in self.rows if r["sensor_id"] == "ST02_SEALING_TMP"},
                         {"-40 to 200", "200"})


class StaticSource(unittest.TestCase):
    FILES = sorted(list(settings.EXTRACT_CODE_DIR.rglob("*.py")) + list(settings.EXTRACT_PROMPTS_DIR.rglob("*.*")))

    def test_no_answer_or_eval_references(self):
        pats = [re.compile(r"ground_truth", re.I), re.compile(r"(?<![\w])data/"), re.compile(r"evaluation", re.I),
                re.compile(r"EVALUATION_DIR"), re.compile(r"imaks_data/human")]
        for f in self.FILES:
            text = f.read_text(encoding="utf-8")
            for p in pats:
                self.assertIsNone(p.search(text), f"{f.name}: {p.pattern}")

    def test_no_hardcoded_key_or_absolute_path(self):
        # 키 값 모양(sk-ant- 뒤 영숫자 8자 이상)을 찾는다. llm.py의 가림용 정규식(sk-ant-[...]+)은 키 값이 아니다.
        pats = [re.compile(r"sk-ant-[A-Za-z0-9]{8,}"), re.compile(r"api_key\s*=\s*[\"']"), re.compile(r"environ\[[^\]]+\]\s*="),
                re.compile(r"[A-Za-z]:\\\\"), re.compile(r"/Users/"), re.compile(r"/home/")]
        for f in self.FILES:
            text = f.read_text(encoding="utf-8")
            for p in pats:
                self.assertIsNone(p.search(text), f"{f.name}: {p.pattern}")

    def test_no_sampling_params_sent(self):
        text = (settings.EXTRACT_CODE_DIR / "llm.py").read_text(encoding="utf-8")
        body = text[text.index("def build_request"):text.index("class AnthropicClient")]
        for k in ("temperature", "top_p", "top_k", "thinking"):
            self.assertNotIn(k, body)


if __name__ == "__main__":
    unittest.main()
