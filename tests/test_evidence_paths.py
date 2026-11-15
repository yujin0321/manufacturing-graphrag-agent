from copy import deepcopy, copy
import json
from pathlib import Path
from shutil import copyfile
import tempfile
import unittest
from rdflib import Graph, Literal, URIRef

from imaks_kg.rag import comparison as c, claim_binding as cb, decision_evidence as d, evidence_paths as ep
from imaks_kg.rag import incident_tools, team_runtime as rt, vector as v
from tests.claim_fixtures import selected_claims


@unittest.skipUnless((incident_tools.ENGINE_OVERLAY / 'complete.json').exists(), 'restore runtime first')
class EvidencePathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = rt.store()
        cls.evidence = incident_tools.get_incident_evidence(cls.store, {'incident_id': cls.store.incidents[0]['id']})
        cls.proof = d.build(cls.evidence, cls.store)
        cls.catalog = cb.build_catalog(cls.evidence, cls.proof, cls.store)
        cls.observation = next(claim for claim in cls.catalog['claims'] if claim['claim_type'] == 'observation')
        cls.condition = next(claim for claim in cls.catalog['claims'] if claim['claim_type'] == 'condition')
        cls.recommendation = next(claim for claim in cls.catalog['claims'] if claim['claim_type'] == 'recommendation')

    def altered_store(self):
        store = copy(self.store)
        store.base = Graph()
        store.overlay = Graph()
        for triple in self.store.base:
            store.base.add(triple)
        for triple in self.store.overlay:
            store.overlay.add(triple)
        return store

    def paths(self, claim, store=None, proof=None):
        return ep.build([claim], self.evidence, proof or self.proof, store or self.store)['claims'][0]

    def retag(self, claim):
        fields = ('incident_id', 'claim_type', 'text', 'evidence_refs', 'values', 'validation')
        claim['claim_id'] = 'CLM-' + v.digest(v.encoded({key: claim[key] for key in fields}))[:16]
        return claim

    def test_paths_are_contiguous_and_rdf_steps_preserve_the_actual_triple(self):
        graph = self.store.base + self.store.overlay
        for claim in (self.observation, self.condition, self.recommendation):
            result = self.paths(claim)
            self.assertEqual(result['status'], 'complete')
            for path in result['paths']:
                self.assertTrue(all(a['to'] == b['from'] for a, b in zip(path['steps'], path['steps'][1:])))
                for step in path['steps'] + [step for branch in path['branches'] for step in branch['steps']]:
                    if step['kind'] == 'rdf':
                        stored = step['stored']
                        self.assertIn(tuple(URIRef(stored[key]) for key in ('s', 'p', 'o')), graph)
                    else:
                        self.assertNotIn('stored', step)

    def test_native_sensor_edge_is_an_inverse_traversal_not_a_fabricated_forward_edge(self):
        steps = self.paths(self.observation)['paths'][0]['steps']
        trigger = next(step for step in steps if step['kind'] == 'rdf')
        self.assertEqual(trigger['traversal'], 'inverse')
        self.assertEqual(trigger['relation'], str(c.IM.triggers))
        self.assertEqual(trigger['from'], trigger['stored']['o'])

    def test_reversed_sensor_edge_is_broken(self):
        store = self.altered_store()
        event = store.event_node(self.evidence['incident']['id'])
        sensor = next(store.overlay.subjects(c.IM.triggers, event))
        store.overlay.remove((sensor, c.IM.triggers, event))
        store.overlay.add((event, c.IM.triggers, sensor))
        result = self.paths(self.observation, store)
        self.assertEqual(result['status'], 'broken')
        self.assertEqual(result['breaks'][0]['code'], 'missing_stored_relation')
        self.assertTrue(result['breaks'][0]['message'])

    def test_rule_document_and_provenance_are_branches_from_rule(self):
        paths = self.paths(self.recommendation)['paths']
        document = next(path for path in paths if path['kind'] == 'document_source')
        prov = next(step for step in document['steps'] if step.get('relation') == str(c.IM.hasProvenance))
        branch = document['branches'][0]
        self.assertEqual(branch['starts_at'], prov['from'])
        self.assertEqual(branch['steps'][0]['relation'], str(c.IM.sourceDocument))
        self.assertFalse(any(step['from'] == branch['steps'][0]['to'] for step in document['steps']))

    def test_missing_event_rule_link_reports_break_location(self):
        store = self.altered_store()
        event = store.event_node(self.evidence['incident']['id'])
        item = next(item for item in self.proof['items'] if item['evidence_id'] == self.condition['values']['evidence_id'])
        store.overlay.remove((event, URIRef(ep.DET + 'matchedRule'), URIRef(item['rule']['kg_node'])))
        result = self.paths(self.condition, store)
        self.assertEqual(result['status'], 'broken')
        self.assertEqual(result['breaks'][0]['at_node'], str(event))

    def test_missing_document_or_provenance_link_does_not_pass_on_quote_match_alone(self):
        node = URIRef(self.recommendation['evidence_refs'][0]['node'])
        for predicate in (c.IM.sourceDocument, c.IM.hasProvenance):
            store = self.altered_store()
            store.base.remove((node, predicate, None))
            self.assertEqual(self.paths(self.recommendation, store)['status'], 'broken')

    def test_wrong_page_metadata_is_rejected_even_with_a_valid_chunk_id(self):
        claim = deepcopy(self.recommendation)
        ref = next(ref for ref in claim['evidence_refs'] if ref['kind'] == 'document_chunk')
        ref['page'] += 1
        result = self.paths(self.retag(claim))
        self.assertEqual(result['status'], 'broken')
        self.assertEqual(result['breaks'][0]['code'], 'claim_source_metadata_mismatch')

    def test_wrong_quote_hash_or_row_is_rejected(self):
        condition = next(claim for claim in self.catalog['claims'] if claim['claim_type'] == 'condition'
                         and claim['values']['rule_id'].startswith('SOP-002-EX-04'))
        item = next(item for item in self.proof['items'] if item['evidence_id'] == condition['values']['evidence_id'])
        node = URIRef(item['rule']['kg_node'])
        prov = next(self.store.base.objects(node, c.IM.hasProvenance))
        for predicate, value in ((c.IM.rowIndex, Literal(3)), (c.IM.textSha256, Literal('0' * 64))):
            store = self.altered_store()
            store.base.set((prov, predicate, value))
            self.assertEqual(self.paths(condition, store)['status'], 'broken')

    def test_wrong_runtime_IR_join_is_rejected(self):
        proof = deepcopy(self.proof)
        item = next(item for item in proof['items'] if item['evidence_id'] == self.condition['values']['evidence_id'])
        item['rule']['ir_id'] = 'another-rule@another-sensor'
        result = self.paths(self.condition, proof=proof)
        self.assertEqual(result['status'], 'broken')
        self.assertEqual(result['breaks'][0]['code'], 'IR_rule_binding_mismatch')

    def test_scope_statements_do_not_claim_a_factual_graph_path(self):
        scope = next(claim for claim in self.catalog['claims'] if claim['claim_id'] in self.catalog['mandatory_claim_ids'])
        result = self.paths(scope)
        self.assertEqual(result['status'], 'scope_only')
        self.assertFalse(result['paths'])

    def test_broken_paths_are_excluded_and_cannot_be_selected_with_a_valid_id(self):
        catalog = deepcopy(self.catalog)
        condition = next(claim for claim in catalog['claims'] if claim['claim_type'] == 'condition')
        condition['evidence_paths']['status'] = 'broken'
        catalog['catalog_sha256'] = v.digest(v.encoded(cb._payload(catalog)))
        self.assertNotIn(condition['claim_id'], {claim['claim_id'] for claim in cb.selector_view(catalog)})
        ids = json.loads(selected_claims({'claim_catalog': cb.selector_view(self.catalog)}))
        result = cb.bind(json.dumps(ids), catalog, '관측·조건·조치')
        self.assertEqual(result['status'], 'withheld')
        self.assertIn('broken evidence path', result['issues'][0])

    def test_table_row_and_recorded_column_precision_are_exposed(self):
        condition = next(claim for claim in self.catalog['claims'] if claim['claim_type'] == 'condition'
                         and claim['values']['rule_id'].startswith('SOP-002-EX-04'))
        document = next(path for path in self.paths(condition)['paths'] if path['kind'] == 'document_source')
        locator = document['steps'][-1]['validation']['locator']
        self.assertEqual(locator['data_row_number'], 1)
        self.assertEqual(locator['row_index'], 2)
        self.assertEqual(locator['column_check'], 'recorded_metadata_only')

    def test_unclassified_candidate_sensor_direction_is_forward(self):
        store = rt.store('seongho_two_point')
        evidence = incident_tools.get_incident_evidence(store, {'incident_id': store.incidents[0]['id']})
        proof = d.build(evidence, store)
        catalog = cb.build_catalog(evidence, proof, store)
        claim = next(c for c in catalog['claims'] if c['claim_type'] == 'observation')
        steps = claim['evidence_paths']['paths'][0]['steps']
        edge = next(step for step in steps if step['kind'] == 'rdf')
        self.assertEqual(edge['traversal'], 'forward')
        self.assertEqual(edge['relation'], ep.DET + 'observedOnSensor')

    def test_monitor_dependencies_are_runtime_refs_not_invented_rdf_edges(self):
        store = self.store
        incident = next(inc for inc in store.incidents if any(store.alarms[a]['kind'] == 'kg_correlation_monitor' for a in inc['alarm_ids']))
        evidence = incident_tools.get_incident_evidence(store, {'incident_id': incident['id']})
        d.add_dependencies(evidence, store)
        proof = d.build(evidence, store)
        catalog = cb.build_catalog(evidence, proof, store)
        claim = next(c for c in catalog['claims'] if c['claim_type'] == 'condition' and c['values']['trigger_check'].get('operator') == 'derived_monitor')
        self.assertEqual(claim['evidence_paths']['status'], 'complete')
        steps = [step for path in claim['evidence_paths']['paths'] for step in path['steps']]
        signal = next(step for step in steps if step['relation'] == 'checked_source_signal')
        self.assertEqual(signal['kind'], 'runtime_reference')
        self.assertNotIn('stored', signal)

    @unittest.skipUnless((v.REPO_ROOT / 'kg_build/graphrag_live/team_main_20261113_01/answer.json').exists(), 'restore saved sample')
    def test_old_prose_is_not_marked_as_revalidated_by_free_path_endpoint(self):
        run = v.REPO_ROOT / 'kg_build/graphrag_live/team_main_20261113_01'
        before = (run / 'answer.json').read_bytes()
        result = ep.for_saved_run(run)
        self.assertFalse(result['past_answer_prose_revalidated'])
        self.assertIn('not_a_validation_of_old_prose', result['path_scope'])
        self.assertEqual(before, (run / 'answer.json').read_bytes())

    @unittest.skipUnless((v.REPO_ROOT / 'kg_build/graphrag_live/team_main_20261113_01/answer.json').exists(), 'restore saved sample')
    def test_saved_published_claims_are_checked_instead_of_a_new_candidate_catalog(self):
        source = v.REPO_ROOT / 'kg_build/graphrag_live/team_main_20261113_01'
        scratch = v.REPO_ROOT / 'kg_build/path_saved_tests'
        scratch.mkdir(exist_ok=True)
        binding = cb.bind(selected_claims({'claim_catalog': cb.selector_view(self.catalog)}), self.catalog, '관측·조건·조치')
        binding['published'] = True
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            run = Path(folder).resolve()
            self.assertTrue(run.is_relative_to(scratch.resolve()))
            for name in ('answer.json', 'store_lock.json', 'retrieval.json'):
                copyfile(source / name, run / name)
            answer = v.read(run / 'answer.json')
            answer.update(claims=binding['claims'])
            answer['xai']['claim_binding'] = binding
            v.write(run / 'answer.json', answer)
            before = (run / 'answer.json').read_bytes()
            result = ep.for_saved_run(run)
            self.assertEqual(result['path_scope'], 'stored_published_claims_reference_paths')
            self.assertEqual(len(result['evidence_paths']['claims']), len(binding['claims']))
            self.assertEqual(result['evidence_paths']['status'], 'complete')
            self.assertEqual(before, (run / 'answer.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
