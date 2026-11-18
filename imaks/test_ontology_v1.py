"""Meaningful acceptance tests for isolation, malformed data, and provenance."""
import json
import unittest

from rdflib import Graph, Literal, RDF, RDFS, XSD

from build_ontology_v1 import COMMON, IM, INST, ROOT, OUT, VerifiedSources, new_graph, resource
from verify_ontology_v1 import BASE, base_example, check, fixtures


class OntologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Graph().parse(OUT / "rule_context.ttl", format="turtle")
        cls.shapes = Graph().parse(BASE / "shapes.ttl", format="turtle")
        cls.examples = {key: (passing, failing) for key, passing, failing, *_ in fixtures(cls.source)}

    def clone(self, source):
        graph = new_graph()
        for triple in source:
            graph.add(triple)
        return graph

    def assert_conforms(self, graph, expected):
        conforms, _, details, _ = check(graph, self.shapes)
        self.assertEqual(conforms, expected, details)

    def test_each_required_pass_and_fail_example(self):
        for key, (passing, failing) in self.examples.items():
            with self.subTest(constraint=key, kind="pass"):
                self.assert_conforms(passing, True)
            with self.subTest(constraint=key, kind="fail"):
                self.assert_conforms(failing, False)

    def test_finite_extreme_observation_is_preserved_but_nonfinite_rejected(self):
        graph = self.clone(self.examples["C2"][0])
        obs = resource("example", "observation")
        self.assert_conforms(graph, True)
        for value in [float("nan"), float("inf"), -float("inf")]:
            with self.subTest(value=value):
                graph.set((obs, IM.value, Literal(value, datatype=XSD.double)))
                self.assert_conforms(graph, False)

    def test_observation_timestamp_and_sensor_link_are_required(self):
        graph = self.clone(self.examples["C2"][0])
        obs = resource("example", "observation")
        graph.set((obs, IM.timestamp, Literal("2026-01-06T06:00:00")))
        self.assert_conforms(graph, False)
        graph.set((obs, IM.timestamp, Literal("2026-01-06T06:00:00", datatype=XSD.dateTime)))
        graph.set((obs, IM.observedBy, INST.missing_sensor))
        self.assert_conforms(graph, False)

    def test_sensor_cannot_have_two_stations_or_wrong_unit(self):
        graph = base_example(self.source)
        graph.add((INST.N0017, RDF.type, IM.Station))
        graph.add((INST.N0017, IM.hasSensor, INST.N0014))
        self.assert_conforms(graph, False)
        graph = base_example(self.source)
        graph.set((INST.N0014, IM.unit, Literal("A")))
        self.assert_conforms(graph, False)

    def test_rule_needs_real_document_and_nonempty_quote(self):
        graph = self.clone(self.examples["C3"][0])
        rule = resource("rule", "RULE-ST02-02")
        graph.set((rule, IM.sourceQuote, Literal(" ")))
        self.assert_conforms(graph, False)
        graph = self.clone(self.examples["C3"][0])
        graph.set((rule, IM.sourceDocument, INST.missing_document))
        self.assert_conforms(graph, False)

    def test_document_sha_and_positive_page_count(self):
        graph = self.clone(self.examples["C3"][0])
        document = resource("document", "SOP-001")
        graph.set((document, IM.sourceSha256, Literal("not-a-sha256")))
        self.assert_conforms(graph, False)
        graph = self.clone(self.examples["C3"][0])
        graph.set((document, IM.pageCount, Literal(0, datatype=XSD.positiveInteger)))
        self.assert_conforms(graph, False)

    def test_nonfinite_threshold_and_wrong_rule_unit_are_rejected(self):
        rule = resource("rule", "SOP002-THRESHOLD-ST02_SEALING_TMP")
        for value in [float("nan"), float("inf"), -float("inf")]:
            with self.subTest(value=value):
                graph = self.clone(self.examples["C4"][0])
                graph.set((rule, IM.critHi, Literal(value, datatype=XSD.double)))
                self.assert_conforms(graph, False)
        graph = self.clone(self.examples["C4"][0])
        graph.set((rule, IM.unit, Literal("A")))
        self.assert_conforms(graph, False)

    def test_control_node_cannot_be_removed_to_bypass_leakage_checks(self):
        graph = self.clone(self.examples["C5"][0])
        graph.remove((IM.InputData, None, None))
        self.assert_conforms(graph, False)

    def test_duplicate_profile_control_node_is_rejected(self):
        graph = self.clone(self.examples["C5"][0])
        graph.add((INST.extra_control, RDF.type, IM.InputGraph))
        graph.add((INST.extra_control, IM.inputProfile, Literal("ml_metadata")))
        self.assert_conforms(graph, False)

    def test_hidden_label_predicate_and_seeded_event_are_rejected(self):
        for predicate in [IM.quality, IM.status, IM.alarms, IM.anomaly_label, IM.dataset_severity]:
            with self.subTest(predicate=predicate):
                graph = self.clone(self.examples["C5"][0])
                graph.add((INST.unrelated_subject, predicate, Literal("NORMAL")))
                self.assert_conforms(graph, False)
        graph = self.clone(self.examples["C5"][0])
        graph.add((INST.event, RDF.type, IM.AnomalyEvent))
        self.assert_conforms(graph, False)
        graph = self.clone(self.examples["C5"][0])
        graph.add((INST.event, IM.identifier, Literal("GT-0001")))
        self.assert_conforms(graph, False)

    def test_natural_name_label_is_allowed(self):
        graph = self.clone(self.examples["C5"][0])
        graph.add((INST.N0014, RDFS.label, Literal("ST02 temperature sensor")))
        self.assert_conforms(graph, True)

    def test_ml_cannot_receive_rule_or_document_text_indirectly(self):
        graph = self.clone(self.examples["C3"][0])
        graph.set((IM.InputData, IM.inputProfile, Literal("ml_metadata")))
        self.assert_conforms(graph, False)
        graph = self.clone(self.examples["C5"][0])
        graph.add((INST.untyped_resource, IM.documentText, Literal("CRIT_HI=210")))
        self.assert_conforms(graph, False)

    def test_evaluation_sources_are_rejected_and_lineage_is_source_grounded(self):
        source = VerifiedSources(COMMON)
        for relative in ["evaluation/rules_ground_truth.csv", "evaluation/anomaly_events.csv", "kg_seed/nodes_factory.csv"]:
            with self.subTest(relative=relative):
                with self.assertRaises(ValueError):
                    source.file(relative)
        summary = json.loads((OUT / "build_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["evaluation_files_read"], [])
        self.assertFalse(summary["llm_extraction_run"])
        tables = {t["table_id"]: t for t in source.json("documents/tables.json")}
        pages = {p["page_id"]: p for p in source.json("documents/pages.json")}
        lineage = json.loads((OUT / "rule_lineage.json").read_text(encoding="utf-8"))
        self.assertEqual(len(lineage["threshold_rules"]), 22)
        for row in lineage["threshold_rules"]:
            self.assertEqual(row["source_cells"], tables[row["source_table"]]["cells"][row["source_row"] - 1])
        self.assertEqual(tables["SOP-002:p2:table1"]["continues_table"], "SOP-002:p1:table5")
        for row in lineage["manual_source_examples"]:
            text = pages[f"{row['doc_id']}:p{row['source_page']}"]["text"]
            self.assertEqual(text[row["text_start"]:row["text_end"]], row["source_quote"])


if __name__ == "__main__":
    unittest.main()
