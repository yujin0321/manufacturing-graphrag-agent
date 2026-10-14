import json
from pathlib import Path
import tempfile
import unittest
import types
from unittest.mock import patch

import numpy as np
from rdflib import Graph, RDF

from imaks_kg.stage3 import build, extract
from imaks_kg.stage3.common import OUT, DOCS, read_jsonl
from imaks_kg.stage3.evaluate import match, metrics
from imaks_kg.stage3 import evaluate
from imaks_kg.stage3.common import digest


class MatchingTests(unittest.TestCase):
    def test_threshold_and_unmatched(self):
        self.assertEqual(match([[.59]], [[True]]), [])
        self.assertEqual(len(match([[.6]], [[True]])), 1)
        self.assertEqual(match([[.99]], [[False]]), [])

    def test_one_to_one(self):
        self.assertEqual(len(match([[.9], [.8]], [[True], [True]])), 1)

    def test_maximize_valid_matches(self):
        pairs = match([[1, .61], [.61, .59]], [[True, True], [True, True]])
        self.assertEqual({(i, j) for i, j, _ in pairs}, {(0, 1), (1, 0)})

    def test_empty_and_nonfinite(self):
        self.assertEqual(match(np.empty((0, 3)), np.empty((0, 3), dtype=bool)), [])
        with self.assertRaises(ValueError):
            match([[float('nan')]], [[True]])
        self.assertEqual(metrics(0, 0, 86)["fn"], 86)

    def test_evaluation_pipeline_with_synthetic_embeddings(self):
        # Integration fixture only: never written to project result directories.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'imaks_data/kg_seed').mkdir(parents=True)
            (root / 'imaks_data/kg_seed/ground_truth.csv').write_text('fixture', encoding='utf8')
            pred = {"prediction_id": "fixture", "doc_id": "SOP-001", "class": "OperationalRule",
                    "condition": "temperature > 80", "action": "stop", "sensors": [], "severity": ""}
            predictions = root / 'predictions.jsonl'
            predictions.write_text(json.dumps(pred) + '\n', encoding='utf8')
            (root / 'manifest.json').write_text(json.dumps({'predictions_sha256': digest(predictions.read_bytes()),
                                                           'human_corrected': False, 'partial': True,
                                                           'completed_documents': ['SOP-001']}), encoding='utf8')
            gt = [{'ruleId': 'fixture-' + str(i), 'source': 'SOP-001' if i < 59 else 'SOP-002', 'class': 'OperationalRule',
                   'condition': 'temperature > 80', 'action': 'stop', 'sensor': '', 'severity': ''} for i in range(86)]
            embeddings = np.eye(87)
            embeddings[1] = embeddings[0]
            fake_model = types.SimpleNamespace(encode=lambda *a, **kw: embeddings)
            modules = {'sentence_transformers': types.SimpleNamespace(SentenceTransformer=lambda *a, **kw: fake_model),
                       'huggingface_hub': types.SimpleNamespace(snapshot_download=lambda *a, **kw: 'fixture-revision')}
            with patch.dict('sys.modules', modules), patch.object(evaluate, 'REPO_ROOT', root), patch.object(evaluate, 'read_csv', return_value=gt):
                evaluate.evaluate(predictions, root / 'result.json')
            result = json.loads((root / 'result.json').read_text(encoding='utf8'))
            self.assertEqual(result['content']['tp'], 1)
            self.assertEqual(result['content']['fn'], 85)
            self.assertEqual(len(result['unmatched_references']), 85)
            self.assertEqual(result['processed_document_scope']['reference'], 59)
            self.assertEqual(result['unprocessed_reference_count'], 27)
            self.assertTrue(result['partial_extraction'])


class EvidenceTests(unittest.TestCase):
    def sample(self):
        c = next(c for c in read_jsonl(DOCS / "chunks.jsonl") if c["kind"] == "rule")
        return {"prediction_id": "test", "class": "OperationalRule", "doc_id": c["doc_id"],
                "condition": "TEST ONLY", "action": "", "severity": "", "sensors": [],
                "action_targets": [], "chunk_id": c["chunk_id"], "source_quote": c["text"],
                "table_row": None, "table_col": None}

    def test_real_quote_and_reject_fabrication(self):
        r = self.sample()
        self.assertEqual(extract.validate_rules([r]), [r])
        with self.assertRaises(ValueError):
            extract.validate_rules([{**r, "source_quote": "FABRICATED QUOTE"}])

    def test_reject_wrong_document_and_unknown_sensor(self):
        r = self.sample()
        for extra in ({"doc_id": "SOP-999"}, {"sensors": ["MADE_UP"]}):
            with self.assertRaises(ValueError):
                extract.validate_rules([{**r, **extra}])

    def test_table_coordinates_required(self):
        c = next(c for c in read_jsonl(DOCS / "chunks.jsonl") if c["kind"] == "table")
        r = {**self.sample(), "chunk_id": c["chunk_id"], "doc_id": c["doc_id"]}
        with self.assertRaises(ValueError):
            extract.validate_rules([r])

    def test_multiple_evidence_and_bad_secondary_quote(self):
        r = self.sample()
        ev = {"chunk_id": r.pop("chunk_id"), "source_quote": r.pop("source_quote"),
              "supports": ["condition"], "table_id": None, "table_row": None, "table_col": None}
        r["evidence"] = [ev, {**ev, "supports": ["action"]}]
        extract.validate_rules([r])
        r["evidence"][1]["source_quote"] = "NOT A DOCUMENT QUOTE"
        with self.assertRaises(ValueError):
            extract.validate_rules([r])

    def test_empty_evidence_is_rejected(self):
        with self.assertRaises(ValueError):
            extract.validate_rules([{**self.sample(), "evidence": []}])


class GraphTests(unittest.TestCase):
    def test_actual_graph_counts_sources_and_no_events(self):
        with tempfile.TemporaryDirectory() as d, patch.object(build, "OUT", Path(d)):
            build.build()
            graph = Graph().parse(Path(d) / "seed.ttl")
            self.assertEqual(len(list(graph.subjects(RDF.type, build.IM.Station))), 9)
            self.assertEqual(len(list(graph.subjects(RDF.type, build.IM.Sensor))), 22)
            self.assertEqual(len(list(graph.subjects(RDF.type, build.IM.MaintenanceRule))), 8)
            self.assertFalse(list(graph.subjects(RDF.type, build.IM.AnomalyEvent)))
            ledger = read_jsonl(Path(d) / "seed_triple_sources.jsonl")
            covered = {(r["subject"], r["predicate"], r["object"]) for r in ledger}
            self.assertTrue(all((str(s), str(p), o.n3()) in covered for s, p, o in graph))
            self.assertTrue(all(r["sources"] for r in ledger))

    def test_enriched_graph(self):
        r = EvidenceTests().sample()
        with tempfile.TemporaryDirectory() as d, patch.object(build, "OUT", Path(d)):
            pred = Path(d) / "fixture.jsonl"
            pred.write_text(json.dumps(r) + '\n', encoding="utf-8")
            build.build(pred)
            graph = Graph().parse(Path(d) / "enriched.ttl")
            self.assertEqual(len(list(graph.subjects(RDF.type, build.IM.OperationalRule))), 1)


if __name__ == "__main__":
    unittest.main()
