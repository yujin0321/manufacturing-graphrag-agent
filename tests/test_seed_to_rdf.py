"""seed → RDF 변환(③) 검사. 변환은 메모리에서 다시 돌려 확인한다(파일 출력 없음).

실행: .\\.venv\\Scripts\\python.exe -m unittest tests.test_seed_to_rdf -v   (저장소 루트에서)
"""
import copy
import sys
import unittest
from pathlib import Path

from pyshacl import validate
from rdflib import OWL, RDF, Graph

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from imaks_kg.kg import seed_events_post7, seed_to_rdf  # noqa: E402
from imaks_kg.kg.naming import IM  # noqa: E402

ONT = ROOT / "ontology_v1" / "ontology.ttl"
SHAPES = ROOT / "ontology_v1" / "shapes.ttl"
GUARDS = ROOT / "guards" / "leakage_shapes.ttl"
THRESHOLD_PROPS = ["nominal", "nominalValue", "warnLo", "warnHi", "critLo", "critHi"]
EVENT_CLASSES = ["AnomalyEvent", "Spike", "Drift", "StuckSensor", "OutOfRange", "Correlated", "CausalLink"]


def shacl(dg, shapes_path, ont=True):
    og = Graph().parse(str(ONT)) if ont else None
    conforms, _, text = validate(dg, shacl_graph=Graph().parse(str(shapes_path)), ont_graph=og, inference="none")
    return conforms, text


class SeedToRdf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nodes, cls.edges = seed_to_rdf.load_inputs()
        g, cls.stats = seed_to_rdf.build_graph(cls.nodes, cls.edges)
        cls.text = seed_to_rdf.serialize(g)
        cls.g = Graph().parse(data=cls.text, format="turtle")
        cls.ttl = seed_to_rdf.ttl_counts(cls.text)
        cls.by_id = {r["nodeId"]: r for r in cls.nodes}

    # ---- 개수
    def test_counts(self):
        self.assertEqual(len(self.nodes), 115)
        self.assertEqual(len(self.edges), 341)
        for k, v in {"Station": 9, "Sensor": 22, "hasSensor": 22, "feedsInto": 3}.items():
            self.assertEqual(self.ttl[k], v, k)

    def test_counts_table_totals(self):
        hashes = {"nodes.csv": (115, "x"), "edges.csv": (341, "y")}
        _, tot = seed_to_rdf.counts_table(self.stats, self.ttl, hashes)
        self.assertEqual(tot["nodes"]["원본"], 115)
        self.assertEqual(tot["edges"]["원본"], 341)
        cats = seed_to_rdf.CATEGORIES
        self.assertEqual(sum(tot["nodes"].get(c, 0) for c in cats), 115)
        self.assertEqual(sum(tot["edges"].get(c, 0) for c in cats), 341)

    # ---- 속성
    def test_no_threshold_properties(self):
        preds = {p for _, p, _ in self.g}
        for name in THRESHOLD_PROPS:
            self.assertNotIn(IM[name], preds, name)

    def test_only_ontology_terms(self):
        ont = Graph().parse(str(ONT))
        declared = set(ont.subjects(RDF.type, OWL.ObjectProperty)) | set(ont.subjects(RDF.type, OWL.DatatypeProperty))
        classes = set(ont.subjects(RDF.type, OWL.Class))
        for _, p, o in self.g:
            if p == RDF.type:
                self.assertIn(o, classes)
            else:
                self.assertIn(p, declared, p)

    def test_station_sensor_values_match_csv(self):
        for s in self.g.subjects(RDF.type, IM.Station):
            r = self.by_id[str(self.g.value(s, IM.sourceNodeId))]
            self.assertEqual(r["label"], "Component")
            self.assertEqual(str(self.g.value(s, IM.identifier)), r["name"])
            self.assertEqual(str(self.g.value(s, IM.stationType)), r["stationType"])
            self.assertEqual(str(self.g.value(s, IM.zone)), r["zone"])
        for s in self.g.subjects(RDF.type, IM.Sensor):
            r = self.by_id[str(self.g.value(s, IM.sourceNodeId))]
            self.assertEqual(r["label"], "Sensor")
            self.assertEqual(str(self.g.value(s, IM.identifier)), r["name"])
            self.assertEqual(str(self.g.value(s, IM.sensorType)), r["sensorType"])
            self.assertEqual(str(self.g.value(s, IM.unit)), r["unit"])

    # ---- 출처와 역추적
    def _provs(self, s):
        out = []
        for p in self.g.objects(s, IM.hasProvenance):
            self.assertIn((p, RDF.type, IM.Provenance), self.g)
            self.assertEqual(str(self.g.value(p, IM.sourceKind)), "seedCsv")
            out.append((str(self.g.value(p, IM.fileName)), sorted(str(x) for x in self.g.objects(p, IM.sourceRowId))))
        return out

    def _edge(self, rid):
        self.assertTrue(rid.startswith("row:"))
        return self.edges[int(rid[4:]) - 1]

    def test_every_node_has_node_provenance(self):
        for cls in (IM.Station, IM.Sensor):
            subjects = list(self.g.subjects(RDF.type, cls))
            self.assertTrue(subjects)
            for s in subjects:
                provs = self._provs(s)
                node_provs = [rows for f, rows in provs if f == "imaks_data/kg_seed/nodes.csv"]
                self.assertEqual(node_provs, [[str(self.g.value(s, IM.sourceNodeId))]], s)

    def test_has_sensor_traces_to_both_monitors_rows(self):
        for st, _, se in self.g.triples((None, IM.hasSensor, None)):
            st_id, se_id = str(self.g.value(st, IM.sourceNodeId)), str(self.g.value(se, IM.sourceNodeId))
            edge_provs = [rows for f, rows in self._provs(se) if f == "imaks_data/kg_seed/edges.csv"]
            self.assertEqual(len(edge_provs), 1, se)
            rows = edge_provs[0]
            self.assertEqual(len(rows), 2)
            pairs = {(self._edge(r)["type"], self._edge(r)["fromId"], self._edge(r)["toId"]) for r in rows}
            self.assertEqual(pairs, {("monitors", st_id, se_id), ("monitors", se_id, st_id)})

    def test_feeds_into_traces_to_row(self):
        for a, _, b in self.g.triples((None, IM.feedsInto, None)):
            a_id, b_id = str(self.g.value(a, IM.sourceNodeId)), str(self.g.value(b, IM.sourceNodeId))
            found = []
            for f, rows in self._provs(a):
                if f == "imaks_data/kg_seed/edges.csv":
                    for r in rows:
                        e = self._edge(r)
                        if e["type"] == "feeds_into":
                            found.append((e["fromId"], e["toId"]))
            self.assertIn((a_id, b_id), found)

    def test_all_seed_rows_used_are_monitors_or_feeds(self):
        used = set()
        for p in self.g.subjects(IM.fileName, None):
            if str(self.g.value(p, IM.fileName)).endswith("edges.csv"):
                used |= {str(x) for x in self.g.objects(p, IM.sourceRowId)}
        self.assertEqual(len(used), 47)
        self.assertEqual({self._edge(r)["type"] for r in used}, {"monitors", "feeds_into"})

    # ---- 금지 대상
    def test_no_events_rules_or_post7_relations(self):
        for c in EVENT_CLASSES + ["Rule", "OperationalRule", "ThresholdRule", "MaintenanceRule", "AccessRule", "Document"]:
            self.assertEqual(list(self.g.subjects(RDF.type, IM[c])), [], c)
        for p in ("triggers", "correlatesWith", "causallyAffects", "appliesToSensor"):
            self.assertEqual(list(self.g.triples((None, IM[p], None))), [], p)
        self.assertNotRegex(self.text, r"GT-\d{4}")

    def test_main_does_not_use_post7_or_eval_files(self):
        src = Path(seed_to_rdf.__file__).read_text(encoding="utf-8")
        self.assertNotIn("build_post7_graph", src)
        self.assertNotIn("import seed_events_post7", src)
        self.assertNotIn("from imaks_kg.kg.seed_events_post7", src)
        for name in ("ground_truth", "nodes_factory"):
            for f in Path(seed_to_rdf.__file__).parent.glob("*.py"):
                self.assertNotIn(name, f.read_text(encoding="utf-8"), f.name)
        self.assertEqual(seed_to_rdf.NODES_FILE.name, "nodes.csv")
        self.assertEqual(seed_to_rdf.EDGES_FILE.name, "edges.csv")

    # ---- SHACL
    def test_shacl_conforms(self):
        conforms, text = shacl(self.g, SHAPES)
        self.assertTrue(conforms, text)

    def test_leakage_guard_conforms(self):
        conforms, text = shacl(self.g, GUARDS, ont=False)
        self.assertTrue(conforms, text)

    # ---- 결정성
    def test_deterministic(self):
        g2, _ = seed_to_rdf.build_graph(copy.deepcopy(self.nodes), copy.deepcopy(self.edges))
        self.assertEqual(seed_to_rdf.serialize(g2).encode("utf-8"), self.text.encode("utf-8"))

    def test_written_file_matches_if_present(self):
        if not seed_to_rdf.OUT_TTL.exists():
            self.skipTest("kg_build/seed.ttl 없음(먼저 seed_to_rdf 실행)")
        self.assertEqual(seed_to_rdf.OUT_TTL.read_bytes(), self.text.encode("utf-8"))

    # ---- 오류 처리
    def test_unknown_node_label_rejected(self):
        nodes = copy.deepcopy(self.nodes)
        nodes[0]["label"] = "Unknown"
        with self.assertRaises(ValueError):
            seed_to_rdf.build_graph(nodes, self.edges)

    def test_incomplete_monitors_pair_rejected(self):
        edges = [e for e in self.edges if not (e["type"] == "monitors" and e["fromId"] == "N0010")]
        with self.assertRaises(ValueError):
            seed_to_rdf.build_graph(self.nodes, edges)


class SeedEventsPost7(unittest.TestCase):
    """⑦ 이후 경로 함수: 메모리에서만 확인(파일 출력 없음)."""

    @classmethod
    def setUpClass(cls):
        cls.nodes, cls.edges = seed_to_rdf.load_inputs()
        cls.g, cls.notes = seed_events_post7.build_post7_graph(cls.nodes, cls.edges)

    def test_counts(self):
        ev = {s for c in EVENT_CLASSES[1:6] for s in self.g.subjects(RDF.type, IM[c])}
        self.assertEqual(len(ev), 14)
        self.assertEqual(len(list(self.g.triples((None, IM.triggers, None)))), 14)
        self.assertEqual(len(list(self.g.triples((None, IM.correlatesWith, None)))), 1)
        self.assertEqual(len(self.notes), 1)
        self.assertEqual(self.notes[0]["ruleRef"], "RULE-ST02-04")

    def test_no_eval_columns(self):
        preds = {p for _, p, _ in self.g}
        for name in ("gtId", "causedBy", "sourceRule", "durationMin", "anomalyType"):
            self.assertNotIn(IM[name], preds)
        text = self.g.serialize(format="turtle")
        self.assertNotRegex(text, r"GT-\d{4}")
        self.assertNotIn("_DRIFT", text)  # causedBy 값(예: ..._CUR_DRIFT)이 들어가지 않음

    def test_merged_with_seed_conforms(self):
        seed, _ = seed_to_rdf.build_graph(self.nodes, self.edges)
        conforms, text = shacl(seed + self.g, SHAPES)
        self.assertTrue(conforms, text)

    def test_post7_fails_leakage_guard(self):
        # 이 그래프는 ⑥ 입력이 아니다: 누수 가드에 걸려야 정상
        conforms, _ = shacl(self.g, GUARDS, ont=False)
        self.assertFalse(conforms)


if __name__ == "__main__":
    unittest.main()
