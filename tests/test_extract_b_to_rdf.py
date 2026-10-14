"""TTL 변환 시험: SHACL S7·S8 적합, 위반 사례 부적합, ID 충돌 중단, 출처 장부. 실제 ③ 산출물(kg_build/instances)이 필요하다."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from rdflib import RDF, Graph, Literal, URIRef

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_b_helpers as h  # noqa: E402
from test_extract_b_outputs import do_run  # noqa: E402

from imaks_kg.extract import to_rdf  # noqa: E402
from imaks_kg.extract.artifacts import file_sha256  # noqa: E402
from imaks_kg.kg.convert_seed import IM, INST  # noqa: E402


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


class ToRdf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._t = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._t.name)
        cls.cfg, cls.rr, _, _ = do_run(cls.tmp)
        cls.d = cls.rr.out_dir
        cls.root = cls.tmp / "out"
        cls.report = to_rdf.convert("mock-t1", out_root=cls.root)
        cls.g = Graph().parse(str(cls.d / "kg_with_rules.ttl"))

    @classmethod
    def tearDownClass(cls):
        cls._t.cleanup()

    def test_shacl_s7_s8_conform(self):
        self.assertTrue(self.report["shacl"]["conforms"], self.report["shacl"]["messages"])
        self.assertEqual(self.report["shacl"]["inference"], "none")
        self.assertTrue(self.report["base_instances_conform"])

    def test_rule_nodes_and_properties(self):
        self.assertEqual(self.report["rules_in_ttl"], 3)
        s = INST["RULE-ST02-01"]
        self.assertIn((s, RDF.type, IM.OperationalRule), self.g)
        self.assertIn((s, IM.identifier, Literal("RULE-ST02-01")), self.g)
        self.assertIn((s, IM.extractionMethod, Literal("LLM")), self.g)
        self.assertIn((s, IM.appliesToSensor, INST["ST02_SEALING_TMP"]), self.g)
        self.assertIn((s, IM.sourceDocument, INST["SOP-001"]), self.g)
        self.assertEqual(len(list(self.g.objects(s, IM.conditionText))), 1)
        m = INST[to_rdf.iri_local("SOP-003:p1:table1:chunk:1")]
        self.assertIn((m, RDF.type, IM.MaintenanceRule), self.g)
        self.assertIn((m, IM.actionTarget, INST["ST02_SEALING"]), self.g)
        self.assertIn((m, IM.ruleSeverity, Literal("HIGH")), self.g)
        provs = list(self.g.objects(m, IM.hasProvenance))
        self.assertEqual(len(provs), 2)
        p = provs[0]
        self.assertEqual(str(self.g.value(p, IM.tableId)), "SOP-003:p1:table1")
        self.assertIsNotNone(self.g.value(p, IM.bbox))
        self.assertEqual(str(self.g.value(p, IM.sourceKind)), "document")
        self.assertEqual(len(str(self.g.value(p, IM.textSha256))), 64)

    def test_prose_provenance_has_char_range(self):
        s = INST["RULE-SRV01-01"]
        p = self.g.value(s, IM.hasProvenance)
        self.assertIsNotNone(self.g.value(p, IM.charStart))
        self.assertGreater(int(self.g.value(p, IM.charEnd)), int(self.g.value(p, IM.charStart)))

    def test_seed_maintenance_rules_untouched_and_not_merged(self):
        base = Graph().parse(str(h.ROOT / "kg_build/instances/instances.ttl"))
        for t in base:
            self.assertIn(t, self.g)
        self.assertEqual(len(list(self.g.subjects(RDF.type, IM.MaintenanceRule))), 9)   # 8 seed + LLM 1, 별도 노드

    def test_flagged_rules_are_not_in_ttl(self):
        idents = {str(o) for o in self.g.objects(None, IM.identifier)}
        self.assertNotIn("SOP-001:p1:RULE-ST02-01:1", idents)
        self.assertNotIn("SOP-001:p1:RULE-ST02-01:2", idents)

    def test_ledger_complete_and_has_sources(self):
        led = jl(self.d / "triple_sources.jsonl")
        rules_only = Graph().parse(str(self.d / "rules_only.ttl"))
        self.assertEqual(len(led), len(rules_only))
        pred_sha = self.report["predictions_sha256"]
        for rec in led:
            self.assertEqual(len(rec["triple"]), 3)
            self.assertTrue(rec["sources"])
            for src in rec["sources"]:
                self.assertEqual(src["predictionsSha256"], pred_sha)
                self.assertTrue(src["documentId"] and src["chunkId"] and src["textSha256"])
                self.assertTrue("charStart" in src or "tableId" in src)

    def test_rules_final_is_preferred_when_present(self):
        from imaks_kg.extract import review
        with tempfile.TemporaryDirectory() as t:
            cfg, rr, _, _ = do_run(t)
            review.init_review("mock-t1", 1, out_root=Path(t) / "out")
            review.apply_review("mock-t1", out_root=Path(t) / "out")
            rep = to_rdf.convert("mock-t1", out_root=Path(t) / "out")
            self.assertEqual(rep["source"], "rules_final.jsonl")
            self.assertTrue(rep["shacl"]["conforms"])


class Violations(unittest.TestCase):
    def test_missing_provenance_or_document_is_non_conforming(self):
        base = Graph().parse(str(h.ROOT / "kg_build/instances/instances.ttl"))
        full = Graph()
        for t in base:
            full.add(t)
        r = INST["BAD-RULE-1"]
        full.add((r, RDF.type, IM.OperationalRule))
        full.add((r, IM.identifier, Literal("BAD-RULE-1")))
        ok, msgs = to_rdf.shacl_check(full)
        self.assertFalse(ok)
        self.assertTrue(any("S8" in m for m in msgs))
        # 출처 해시 형식 위반(S7)
        pv = INST["prov_bad"]
        full.add((r, IM.sourceDocument, INST["SOP-001"]))
        full.add((r, IM.hasProvenance, pv))
        full.add((pv, RDF.type, IM.Provenance))
        full.add((pv, IM.sourceKind, Literal("document")))
        full.add((pv, IM.page, Literal(1, datatype=URIRef("http://www.w3.org/2001/XMLSchema#positiveInteger"))))
        full.add((pv, IM.textSha256, Literal("not-a-hash")))
        ok, msgs = to_rdf.shacl_check(full)
        self.assertFalse(ok)
        self.assertTrue(any("S7" in m for m in msgs))

    def test_unresolved_provenance_rule_is_excluded_from_ttl(self):
        with tempfile.TemporaryDirectory() as t:
            cfg, rr, _, _ = do_run(t)
            d = rr.out_dir
            rules = jl(d / "rules_valid.jsonl")
            rules[0]["evidence"][0]["provenance"]["resolved"] = False
            (d / "rules_valid.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rules), encoding="utf-8")
            rep = to_rdf.convert("mock-t1", out_root=Path(t) / "out")
            self.assertEqual(len(rep["excluded"]), 1)
            self.assertEqual(rep["rules_in_ttl"], 2)
            self.assertTrue(rep["shacl"]["conforms"])


class Collisions(unittest.TestCase):
    def run_with_maint(self, t, extra_ids=("MAINT-02",)):
        store = h.real_store()
        resp = h.sop003_response(store)
        resp["rules"][0]["printed_rule_id"] = extra_ids[0]
        sop1 = h.sop001_response(store)
        cfg, rr, _, _ = do_run(t, {"SOP-003": json.dumps(resp), "SOP-001": json.dumps(sop1)})
        return rr

    def test_seed_collision_excludes_only_that_rule_and_records(self):
        with tempfile.TemporaryDirectory() as t:
            rr = self.run_with_maint(t)
            d = rr.out_dir
            before = {n: file_sha256(d / n) for n in ("predictions.jsonl", "rules_all.jsonl", "rules_valid.jsonl")}
            rep = to_rdf.convert("mock-t1", out_root=Path(t) / "out")
            after = {n: file_sha256(d / n) for n in before}
            self.assertEqual(before, after)                                  # 점수·규칙 파일 불변
            self.assertEqual(rep["identifier_conflicts"], 1)
            self.assertEqual(rep["rules_in_ttl"], 2)                          # 나머지(SOP-001 정상 2개)는 변환
            self.assertTrue(rep["shacl"]["conforms"], rep["shacl"]["messages"])
            rec = json.loads((d / "identifier_conflicts.json").read_text(encoding="utf-8"))
            self.assertEqual(rec["count"], 1)
            c = rec["conflicts"][0]
            self.assertEqual(c["identifier"], "MAINT-02")
            self.assertEqual(c["seed_node_iris"], [str(INST["MAINT-02"])])
            self.assertEqual((c["document_id"], c["chunk_id"]), ("SOP-003", "SOP-003:p1:table1:chunk"))
            self.assertTrue(c["reason"])
            g = Graph().parse(str(d / "kg_with_rules.ttl"))
            # seed 노드는 그대로(별도 노드, 병합·접두 없음)
            self.assertEqual(len(list(g.objects(INST["MAINT-02"], IM.hasProvenance))), 2)
            self.assertEqual(len(list(g.subjects(IM.identifier, Literal("MAINT-02")))), 1)
            self.assertEqual(len(list(g.subjects(RDF.type, IM.MaintenanceRule))), 8)
            self.assertFalse(any("MAINT-02" in str(o) for s_, o in g.subject_objects(IM.identifier) if str(s_) != str(INST["MAINT-02"])))

    def test_no_orphans_and_ledger_covers_all_triples(self):
        with tempfile.TemporaryDirectory() as t:
            rr = self.run_with_maint(t)
            to_rdf.convert("mock-t1", out_root=Path(t) / "out")
            only = Graph().parse(str(rr.out_dir / "rules_only.ttl"))
            led = jl(rr.out_dir / "triple_sources.jsonl")
            self.assertEqual(len(led), len(only))
            provs = set(only.subjects(RDF.type, IM.Provenance))
            used = set(only.objects(None, IM.hasProvenance))
            self.assertEqual(provs, used)                                     # 고아 Provenance 없음
            self.assertEqual(len(set(only.subjects(RDF.type, IM.MaintenanceRule))), 0)
            ledger_subjects = {r["triple"][0] for r in led}
            self.assertTrue({s_.n3() for s_ in only.subjects()} <= ledger_subjects)

    def test_zero_conflicts_records_count_zero(self):
        with tempfile.TemporaryDirectory() as t:
            do_run(t)
            rep = to_rdf.convert("mock-t1", out_root=Path(t) / "out")
            rec = json.loads((Path(t) / "out" / "mock-t1" / "identifier_conflicts.json").read_text(encoding="utf-8"))
            self.assertEqual((rec["count"], rec["conflicts"], rep["identifier_conflicts"]), (0, [], 0))

    def test_duplicates_inside_input_still_stop(self):
        with tempfile.TemporaryDirectory() as t:
            rr = self.run_with_maint(t, ("MAINT-02",))
            rules = jl(rr.out_dir / "rules_valid.jsonl")
            rules.append(dict(rules[0]))
            (rr.out_dir / "rules_valid.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + chr(10) for x in rules), encoding="utf-8")
            with self.assertRaises(to_rdf.IdCollisionError):
                to_rdf.convert("mock-t1", out_root=Path(t) / "out")


if __name__ == "__main__":
    unittest.main()
