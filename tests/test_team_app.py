import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rdflib import Literal, RDF

from imaks_kg.rag import comparison as c, incident_agent, team_retrieval as retrieval, team_runtime as runtime, vector as v


class CompleteQueryTests(unittest.TestCase):
    def test_sensor_units_preserve_literal_slashes(self):
        result, sources, _ = retrieval.query_kg({'operation': 'sensors', 'station_id': 'ST04_PACKAGING'})
        speed = next(item for item in result['items'] if item['identifier'] == ['ST04_PACKAGING_SPD'])
        self.assertEqual(speed['unit'], ['m/s'])
        self.assertEqual(result['count'], len(sources))

    def test_rule_count_is_the_full_filtered_KG_set(self):
        result, sources, _ = retrieval.query_kg({'operation': 'rules', 'sensor_id': 'ST02_SEALING_CUR'})
        graph = c.load_graph()
        sensor = next(graph.subjects(c.IM.identifier, Literal('ST02_SEALING_CUR')))
        expected = set(graph.subjects(c.IM.appliesToSensor, sensor))
        self.assertEqual(result['count'], len(expected))
        self.assertEqual(len(sources), len(expected))
        self.assertTrue(any('candidate-' in item['identifier'][0] for item in result['items']))

    def test_path_query_preserves_direction(self):
        forward, _, _ = retrieval.query_kg({'operation': 'paths', 'start_station': 'ST01_FILLING', 'end_station': 'ST04_PACKAGING'})
        reverse, _, _ = retrieval.query_kg({'operation': 'paths', 'start_station': 'ST04_PACKAGING', 'end_station': 'ST01_FILLING'})
        self.assertGreater(forward['count'], 0)
        self.assertEqual(reverse['count'], 0)

    def test_unknown_identifier_and_unbounded_query_are_rejected(self):
        for arguments in ({'operation': 'cypher', 'query': 'anything'},
                          {'operation': 'rules', 'sensor_id': 'ST99_UNKNOWN'},
                          {'operation': 'sensors'}, {'operation': 'rules', 'rule_type': 'Anything'}):
            with self.assertRaises(ValueError):
                retrieval.query_kg(arguments)


@unittest.skipUnless((retrieval.INDEX / 'manifest.json').exists(), 'reuse the document index first')
class DocumentModeTests(unittest.TestCase):
    def embed(self, resource, payload, cache):
        self.assertEqual(resource, 'embeddings')
        self.assertEqual(len(payload['input']), 1)
        manifest = v.read(retrieval.INDEX / 'manifest.json')
        import numpy as np
        vector = np.load(retrieval.INDEX / 'vectors.npy', allow_pickle=False)[0].tolist()
        return {'model': manifest['embedding_model'], 'data': [{'index': 0, 'embedding': vector}],
                'usage': {'total_tokens': 0}}, {'mock': True}

    def test_all_document_modes_share_the_same_frozen_rows(self):
        row_sets = []
        for mode in ('auto', 'vector', 'graph', 'full'):
            retriever = retrieval.Retriever(mode)
            packet = retriever.retrieve('MAINT-05의 조건과 조치는?', self.embed)
            row_sets.append([row['chunk_id'] for row in retriever.rows])
            self.assertTrue(packet['sources'])
            self.assertLessEqual(packet['context_tokens'], retriever.max_tokens)
            self.assertEqual(packet['retrieval_backend'], 'team-v5-' + mode)
        self.assertTrue(all(rows == row_sets[0] for rows in row_sets))

    def test_full_document_mode_does_not_call_embeddings(self):
        retriever = retrieval.Retriever('full')
        def forbidden(*args):
            raise AssertionError('Full-document mode must not embed')
        result = retriever.retrieve('문서 기준', forbidden)
        self.assertEqual(len(result['selected_ids']), len(retriever.rows))
        self.assertTrue(result['coverage_complete'])


@unittest.skipUnless((runtime.directories('seongho_two_point')[1] / 'complete.json').exists(), 'prepare team profiles first')
class DetectorAdapterTests(unittest.TestCase):
    def test_every_selectable_profile_has_a_valid_store_and_report(self):
        seals = []
        for profile in runtime.PROFILES:
            store = runtime.store(profile)
            report = v.read(store.overlay_dir / 'overlay_report.json')
            self.assertFalse(report['shacl_blocking'])
            self.assertFalse(report['loader_errors'])
            self.assertFalse(report['guards_L4'])
            if profile.startswith('seongho_'):
                self.assertTrue(report['candidate_shapes_conform'])
                self.assertEqual(report['events'], len(store.incidents))
                self.assertTrue(all(store.event_node(item['id']) for item in store.incidents))
            seals.append(store.seal)
        self.assertEqual(len({v.digest(v.encoded(seal)) for seal in seals}), len(runtime.PROFILES))

    def test_original_seongho_events_are_not_regrouped_or_retyped(self):
        store = runtime.store('seongho_two_point')
        original = v.read(store.run_dir.parent / 'original_detector/events.json')
        self.assertEqual(len(original), len(store.incidents))
        self.assertEqual({event['id'] for event in original}, {event['original_event_id'] for event in store.alarms.values()})
        self.assertTrue(all(incident['anomaly_type'] == 'UNCLASSIFIED' for incident in store.incidents))
        for incident in store.incidents:
            from imaks_kg.detection.engine.overlay import DET
            node = store.event_node(incident['id'])
            self.assertIn((node, RDF.type, DET.RuleMatchCandidate), store.overlay)
            self.assertNotIn((node, RDF.type, c.IM.AnomalyEvent), store.overlay)

    def test_profile_ids_and_run_locks_are_distinct(self):
        first = runtime.store('main_v3_1')
        second = runtime.store('seongho_two_point')
        self.assertFalse(set(first.by_id) & set(second.by_id))
        self.assertNotEqual(first.seal, second.seal)

    def test_seongho_event_can_use_the_same_agent_contract(self):
        store = runtime.store('seongho_two_point')
        incident_id = store.incidents[0]['id']
        stages = []
        def call(resource, payload, cache):
            stage = Path(cache).name
            stages.append(stage)
            if stage == 'plan':
                text = json.dumps({'intent': 'explain', 'tool': 'get_incident_evidence', 'arguments': {'incident_id': incident_id}})
            elif stage == 'draft':
                evidence = json.loads(payload['messages'][-1]['content'])['evidence']
                self.assertEqual(evidence['incident']['anomaly_type'], 'UNCLASSIFIED')
                self.assertIn('표시용', evidence['incident']['severity_origin'])
                self.assertTrue(all(rule['params']['confirm_observations'] == 2 for rule in evidence['execution_parameters']))
                text = '원본의 규칙별 과거 후보이며 유형은 미분류입니다. [' + evidence['untrusted_reference_documents'][0]['chunk_id'] + ']'
            else:
                text = json.dumps({'approved': True, 'issues': []})
            return {'model': payload['model'], 'choices': [{'finish_reason': 'stop', 'message': {'content': text}}]}, {'mock': True}
        scratch = v.REPO_ROOT / 'kg_build/team_tests'
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            result = incident_agent.answer('사건 ' + incident_id + ' 설명', Path(folder) / 'run', call,
                                           detector_profile='seongho_two_point', store=store)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(stages, ['plan', 'draft', 'verify'])
        self.assertEqual(result['integration']['detector_profile'], 'seongho_two_point')


if __name__ == '__main__':
    unittest.main()
