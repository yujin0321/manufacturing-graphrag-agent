import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rdflib import Graph, Namespace, RDF, XSD
from imaks_kg.kg_build.structure_completion import document_flows
from imaks_kg.kg_build.rdf_export import export_ttl
from imaks_kg.kg_build.sol_extract import normalize


class StructureTests(unittest.TestCase):
    def test_flow_uses_explicit_feeds_not_fault_arrow(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            manifest = p / 'manifest.csv'
            manifest.write_text('document_id,file_sha256\nSOP-001,' + 'a'*64 + '\n')
            table = {'document_id': 'SOP-001', 'table_id': 't', 'page': 1,
                     'rows': [['Station ID', 'Downstream Effect'], ['X_A', 'Feeds Y; fault -> Z'],
                              ['Y_B', 'Fault -> Z']]}
            tables = p / 'tables.jsonl'; tables.write_text(json.dumps(table) + '\n')
            layout = SimpleNamespace(doc_manifest=manifest, tables_jsonl=tables)
            flows, prov = document_flows(layout, {'X_A', 'Y_B', 'Z_C'})
            self.assertEqual([(r['source'], r['target']) for r in flows], [('X_A', 'Y_B')])
            self.assertEqual(prov[0]['properties']['rowIndex'], 2)

    def test_decimal_domain_zero_and_multi_target_export(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            rows = {'nodes': [{'id': 'S', 'labels': ['Sensor'], 'properties': {'nominal': '99'}},
                              {'id': 'A', 'labels': ['Station'], 'properties': {}},
                              {'id': 'B', 'labels': ['Station'], 'properties': {}}],
                    'rules_extracted': [{'ruleId': 'r', 'class': 'ThresholdRule',
                                         'numeric': {'warnLo': '0', 'critHi': '12.50'},
                                         'sensors': ['S'], 'action_targets': ['A', 'B'],
                                         'provenanceIds': ['p1', 'p2']}]}
            for name, data in rows.items():
                (p / (name + '.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in data))
            g = Graph().parse(export_ttl(p))
            im = Namespace('https://example.org/imaks/v1#')
            self.assertEqual(len(list(g.triples((None, im.actionTarget, None)))), 2)
            self.assertEqual(len(list(g.triples((None, im.hasProvenance, None)))), 2)
            self.assertEqual(len(list(g.triples((None, im.nominal, None)))), 0)
            self.assertEqual(next(g.objects(None, im.warnLo)).datatype, XSD.decimal)
            self.assertEqual(float(next(g.objects(None, im.warnLo))), 0)

    def test_unsupported_numeric_is_flagged_without_dropping_rule(self):
        unit = {'unit_id':'u', 'kind':'text', 'page':1, 'text':'Upper warning limit is 12.'}
        packet = {'document_id':'SOP-TEST', 'source_sha256':'a'*64, 'units':[unit],
                  'page_context':[{'page':1,'text':unit['text']}], 'allowed_sensors':[], 'allowed_stations':[]}
        raw = {'class':'ThresholdRule', 'condition':'Upper limit 99', 'action':'', 'printed_rule_id':'',
               'sensors':[], 'action_targets':[], 'numeric':{'warnHi':'99'}, 'priority':'',
               'evidence':[{'unit_id':'u','quote':unit['text']}]}
        rules, _, _ = normalize({'rules':[raw], 'coverage':[]}, packet)
        self.assertEqual(len(rules), 1)
        self.assertFalse(rules[0]['kg_eligible'])
        self.assertIn('unsupported_numeric_warnHi', rules[0]['validation_flags'])


if __name__ == '__main__':
    unittest.main()
