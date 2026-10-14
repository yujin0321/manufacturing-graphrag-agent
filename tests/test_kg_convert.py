"""③ seed 변환 산출물 검사 (먼저 python -m imaks_kg.kg.convert_seed 실행)."""
import csv
import json
import unittest
from pathlib import Path

import hashlib
import sys
import tempfile

from rdflib import RDF, Graph, Literal, Namespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from imaks_kg.kg import convert_seed as cs  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "kg_build" / "instances"
IM = Namespace("https://example.org/imaks/v1#")


def rows(name, base=OUT):
    with (base / name).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class KgConvert(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = Graph().parse(str(OUT / "instances.ttl"))
        cls.nodes = {r["nodeId"]: r for r in rows("nodes.csv", ROOT / "imaks_data" / "kg_seed")}
        cls.edges = rows("edges.csv", ROOT / "imaks_data" / "kg_seed")

    def count(self, cls):
        return len(set(self.g.subjects(RDF.type, cls)))

    def test_counts(self):
        self.assertEqual(self.count(IM.Station), 9)
        self.assertEqual(self.count(IM.Sensor), 22)
        self.assertEqual(self.count(IM.MaintenanceRule), 8)
        self.assertEqual(self.count(IM.Document), 7)
        self.assertEqual(len(list(self.g.triples((None, IM.hasSensor, None)))), 22)
        self.assertEqual(len(list(self.g.triples((None, IM.feedsInto, None)))), 3)
        self.assertEqual(len(list(self.g.triples((None, IM.appliesToSensor, None)))), 8)

    def test_each_sensor_one_station(self):
        for s in self.g.subjects(RDF.type, IM.Sensor):
            self.assertEqual(len(list(self.g.subjects(IM.hasSensor, s))), 1, s)

    def test_no_excluded_types(self):
        for cls in ("AnomalyEvent", "Spike", "Drift", "StuckSensor", "OutOfRange", "Correlated",
                    "OperationalRule", "ThresholdRule", "AccessRule", "CausalLink"):
            self.assertEqual(self.count(IM[cls]), 0, cls)
        for p in ("triggers", "correlatesWith", "causallyAffects"):
            self.assertEqual(len(list(self.g.triples((None, IM[p], None)))), 0, p)

    def test_traceback_to_source_rows(self):
        """sourceNodeId/sourceRowId로 원본 nodes.csv 행을 찾아 값이 같은지 대조한다."""
        for r in rows("stations.csv"):
            n = self.nodes[r["sourceNodeId"]]
            self.assertEqual((n["label"], n["name"], n["stationType"], n["zone"]),
                             ("Component", r["identifier"], r["stationType"], r["zone"]))
        for r in rows("sensors.csv"):
            n = self.nodes[r["sourceNodeId"]]
            self.assertEqual((n["label"], n["name"], n["sensorType"], n["unit"]),
                             ("Sensor", r["identifier"], r["sensorType"], r["unit"]))
        for r in rows("maintenance_rules.csv"):
            n = self.nodes[r["sourceNodeId"]]
            self.assertEqual((n["label"], n["ruleId"], n["action"], n["priority"]),
                             ("Maintenance", r["identifier"], r["responseText"], r["priority"]))
        for r in rows("provenance.csv"):
            self.assertIn(r["sourceRowId"], self.nodes)
            self.assertEqual(r["fileName"], "imaks_data/kg_seed/nodes.csv")

    def test_edge_rows_traceback(self):
        for r in rows("has_sensor.csv"):
            for ref in r["sourceEdgeRows"].split(";"):
                e = self.edges[int(ref.rsplit(":L", 1)[1]) - 2]
                self.assertEqual(e["type"], "monitors")
                self.assertEqual({e["fromId"], e["toId"]}, {r["stationNodeId"], r["sensorNodeId"]})
        for r in rows("feeds_into.csv"):
            e = self.edges[int(r["sourceEdgeRow"].rsplit(":L", 1)[1]) - 2]
            self.assertEqual((e["type"], e["fromId"], e["toId"]), ("feeds_into", r["fromNodeId"], r["toNodeId"]))
        for r in rows("applies_to_sensor.csv"):
            t = self.edges[int(r["sourceEdgeRowSensorToRule"].rsplit(":L", 1)[1]) - 2]
            s = self.edges[int(r["sourceEdgeRowRuleToSensor"].rsplit(":L", 1)[1]) - 2]
            self.assertEqual((t["type"], t["fromId"], t["toId"]), ("triggers", r["sensorNodeId"], r["ruleNodeId"]))
            self.assertEqual((s["type"], s["fromId"], s["toId"]), ("resolves", r["ruleNodeId"], r["sensorNodeId"]))

    def test_documents_match_manifest(self):
        man = {m["doc_id"]: m for m in rows("doc_manifest.csv", ROOT / "preprocessed" / "documents")}
        docs = rows("documents.csv")
        self.assertEqual({d["identifier"] for d in docs}, set(man))
        for d in docs:
            self.assertEqual(d["sourceSha256"], man[d["identifier"]]["file_sha256"])
            self.assertEqual(d["sourcePath"], man[d["identifier"]]["file"])

    def test_maintenance_source_document_and_mapping(self):
        for r in rows("maintenance_rules.csv"):
            self.assertEqual(r["sourceDocument"], "SOP-003")
        m = rows("maint_seed_vs_sop003.csv", ROOT / "kg_build" / "mapping")
        self.assertEqual(len(m), 8)
        self.assertTrue(all(r["sop003TableId"] for r in m))

    def test_summary_has_no_values(self):
        s = json.loads((ROOT / "kg_build" / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(s["counts"]["Station"], 9)
        self.assertTrue(s["sop003Verified"])


class KgConvertV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = Graph().parse(str(OUT / "instances.ttl"))
        with (OUT / "triple_sources.jsonl").open(encoding="utf-8") as f:
            cls.ledger = [json.loads(line) for line in f if line.strip()]

    def test_ledger_covers_every_triple(self):
        self.assertEqual(len(self.ledger), len(self.g))
        keys = set()
        for r in self.ledger:
            self.assertTrue(r["sources"], r["triple"])
            keys.add(tuple(r["triple"]))
        for t in self.g:
            self.assertIn(tuple(x.n3() for x in t), keys)
        s = json.loads((ROOT / "kg_build" / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(s["tripleCount"], len(self.g))
        self.assertTrue(s["ledgerComplete"])

    def test_double_evidence_preserved(self):
        for pred in ("hasSensor", "appliesToSensor"):
            recs = [r for r in self.ledger if r["triple"][1] == IM[pred].n3()]
            self.assertEqual(len(recs), 22 if pred == "hasSensor" else 8)
            for r in recs:
                lines = {x["line"] for x in r["sources"]}
                self.assertEqual(len(lines), 2, r)
                self.assertTrue(all(x["file"] == "imaks_data/kg_seed/edges.csv" for x in r["sources"]))

    def test_maintenance_two_provenance_and_s7(self):
        rules = set(self.g.subjects(RDF.type, IM.MaintenanceRule))
        self.assertEqual(len(rules), 8)
        for r in rules:
            kinds = sorted(str(self.g.value(p, IM.sourceKind)) for p in self.g.objects(r, IM.hasProvenance))
            self.assertEqual(kinds, ["document", "seedCsv"])
            self.assertEqual(str(self.g.value(r, IM.extractionMethod)), "seedCsv")
            doc = [p for p in self.g.objects(r, IM.hasProvenance)
                   if str(self.g.value(p, IM.sourceKind)) == "document"][0]
            for prop in ("page", "tableId", "rowIndex", "colIndex", "sourceQuote", "textSha256"):
                self.assertIsNotNone(self.g.value(doc, IM[prop]), prop)
            quote = str(self.g.value(doc, IM.sourceQuote))
            self.assertEqual(str(self.g.value(doc, IM.textSha256)), hashlib.sha256(quote.encode("utf-8")).hexdigest())
            self.assertTrue(quote.startswith(str(self.g.value(r, IM.identifier)) + " | "))
            self.assertGreaterEqual(int(self.g.value(doc, IM.rowIndex)), 1)
        self.assertEqual(self.count_type(IM.Provenance), 47)

    def count_type(self, cls):
        return len(set(self.g.subjects(RDF.type, cls)))

    def test_ledger_check_rejects_unsourced_triple(self):
        g = Graph()
        t = (IM.a, IM.identifier, Literal("x"))
        g.add(t)
        with self.assertRaises(ValueError):
            cs.check_ledger_complete(g, {})
        self.assertTrue(cs.check_ledger_complete(g, {t: [{"file": "f", "rowId": "1", "sha256": "0"}]}))
        with self.assertRaises(ValueError):
            cs.Ledger(Graph()).add(*t, [])

    def test_forbidden_types_and_predicates_raise(self):
        for cls in cs.FORBIDDEN_TYPES:
            g = Graph()
            g.add((IM.x, RDF.type, IM[cls]))
            with self.assertRaises(ValueError, msg=cls):
                cs.assert_no_later_stage_items(g)
        for p in cs.FORBIDDEN_PREDICATES:
            g = Graph()
            g.add((IM.x, IM[p], IM.y))
            with self.assertRaises(ValueError, msg=p):
                cs.assert_no_later_stage_items(g)
        cs.assert_no_later_stage_items(self.g)

    def test_pdf_hash_mismatch_raises(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.pdf").write_bytes(b"hello")
            good = hashlib.sha256(b"hello").hexdigest()
            ok = [{"doc_id": "X", "file": "a.pdf", "file_sha256": good}]
            self.assertEqual(cs.verify_manifest_hashes(ok, root), {"X": good})
            with self.assertRaises(ValueError):
                cs.verify_manifest_hashes([{"doc_id": "X", "file": "a.pdf", "file_sha256": "0" * 64}], root)
            with self.assertRaises(ValueError):
                cs.verify_manifest_hashes([{"doc_id": "X", "file": "missing.pdf", "file_sha256": good}], root)

    def test_locate_requires_exactly_one_hit(self):
        row = ["MAINT-01", "a"]
        mk = lambda tid, rows: {"doc_id": "SOP-003", "table_id": tid, "page": 1, "rows_normalized": rows}
        loc = cs.locate_in_tables([mk("t1", [["Rule ID", "x"], row])], "MAINT-01")
        self.assertEqual((loc["rowIndex"], loc["colIndex"]), (2, 1))
        with self.assertRaises(ValueError):
            cs.locate_in_tables([mk("t1", [["Rule ID", "x"]])], "MAINT-01")
        with self.assertRaises(ValueError):
            cs.locate_in_tables([mk("t1", [row]), mk("t2", [row])], "MAINT-01")

    def test_mapping_rowindex_matches_provenance(self):
        """매핑표 sop003RowIndex(1부터)와 provenance_document.csv rowIndex가 8행 모두 같다."""
        mp = {r["ruleId"]: r for r in rows("maint_seed_vs_sop003.csv", ROOT / "kg_build" / "mapping")}
        pv = {r["subject"]: r for r in rows("provenance_document.csv")}
        self.assertEqual(len(mp), 8)
        self.assertEqual(set(mp), set(pv))
        for rid, r in mp.items():
            self.assertEqual(int(r["sop003RowIndex"]), int(pv[rid]["rowIndex"]), rid)
        self.assertEqual(int(mp["MAINT-01"]["sop003RowIndex"]), 2)
        self.assertEqual(int(mp["MAINT-08"]["sop003RowIndex"]), 9)
        cs.check_row_index_consistent("X", 2, 2)
        with self.assertRaises(ValueError):
            cs.check_row_index_consistent("X", 1, 2)


if __name__ == "__main__":
    unittest.main()
