import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from rdflib import Graph, RDF, Literal
from imaks_kg.rag import seed_event_demo as d, agent_tools, event_explain


class SeedDemoTests(unittest.TestCase):
    def test_all_source_fields_sensor_links_and_queries(self):
        d.verify()
        base = d.c.load_graph()
        overlay = Graph().parse(d.OUT / 'events.ttl')
        mapping = d.v.read(d.OUT / 'mapping.json')
        self.assertEqual(len(mapping), 14)
        self.assertEqual(len(list(overlay.subjects(RDF.type, d.EX.ProvidedAnomalyEvent))), 14)
        _, nodes = d.raw_csv_rows(d.IMAKS_DATA / 'kg_seed/nodes.csv')
        originals = {n['gtId']: {k: v for k, v in n.items() if v} for n in nodes if n['label']=='AnomalyEvent'}
        for m in mapping:
            self.assertEqual(m['source_fields'], originals[m['gt_id']])
            q = d.query_event(base, overlay, m['gt_id'])
            self.assertEqual(len(q['sensors']), 1)
            self.assertTrue(q['gold_loaded'])
            self.assertFalse(q['evaluation_run'])
            self.assertTrue(q['paths'])
            self.assertEqual(list(base.subjects(d.EX.gtId, Literal(m['gt_id']))), [])
        self.assertEqual(len(base), 2806)
        with self.assertRaises(ValueError):
            d.query_event(base, overlay, 'GT-9999')

    def test_seal_detects_changes_and_overwrite_is_refused(self):
        root = d.v.REPO_ROOT / 'kg_build/seed_demo_tests'
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as tmp:
            out = Path(tmp) / 'demo'
            d.build(out)
            d.verify(out)
            with self.assertRaises(FileExistsError):
                d.build(out)
            (out / 'events.ttl').write_text('changed', encoding='utf-8')
            with self.assertRaises(ValueError):
                d.verify(out)

    def test_normal_tools_do_not_read_gold_demo_or_seed(self):
        original = Path.open
        reads = []
        def guarded(path, *args, **kwargs):
            normalized = path.as_posix()
            if 'gold_event_demo' in normalized or '/kg_seed/' in normalized:
                raise AssertionError('Normal tool attempted gold source read')
            reads.append(normalized)
            return original(path, *args, **kwargs)
        root = d.v.REPO_ROOT / 'kg_build/seed_demo_tests'
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as tmp, patch.object(Path, 'open', guarded):
            session = agent_tools.ToolSession(Path(tmp) / 'normal', explicit_event_ids=['det-4220832c6ffd0c103c6e'])
            self.assertEqual(session.execute('list_candidates', {})['data']['total_matches'], 93)
            self.assertEqual(session.execute('get_candidate_evidence', {'event_id':'det-4220832c6ffd0c103c6e'})['status'], 'ok')
            request = d.v.read(next((d.v.DEFAULT_INDEX / 'query_cache').glob('*.request.json')))
            question = request.get('payload', request)['input'][0]
            result = agent_tools.search_documents({'question':question})
            self.assertTrue(result['sources'])
        self.assertTrue(reads)
