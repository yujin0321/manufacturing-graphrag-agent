import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rdflib import Graph, RDF
from imaks_kg.stage3 import supplement, build


class SupplementTests(unittest.TestCase):
    def test_actual_source_mapping_and_continuation(self):
        with tempfile.TemporaryDirectory() as d, patch.object(supplement,'OUT',Path(d)):
            supplement.supplement()
            summary=json.loads((Path(d)/'sop002_source_supplement_summary.json').read_text(encoding='utf8'))
            self.assertEqual(summary['threshold_sensor_rows'],22)
            self.assertEqual(summary['anomaly_definition_rows'],5)
            self.assertFalse(summary['ground_truth_read'])
            row=next(r for r in summary['mapping'] if r['sensor']=='SRV01_SERVERROOM_HUM')
            self.assertEqual(row['table_id'],'SOP-002:p2:table1')
            self.assertEqual(row['continued_from'],'SOP-002:p1:table5')

    def test_missing_continuation_context_rejected(self):
        original=supplement.read_jsonl
        def changed(path):
            rows=original(path)
            if path.name=='tables.jsonl':
                rows=[{**r,'continued_from':'UNKNOWN'} if r['table_id']=='SOP-002:p2:table1' else r for r in rows]
            return rows
        with patch.object(supplement,'read_jsonl',side_effect=changed):
            with self.assertRaises(ValueError): supplement.supplement()

    def test_numeric_properties_and_method_separation(self):
        with tempfile.TemporaryDirectory() as d, patch.object(supplement,'OUT',Path(d)), patch.object(build,'OUT',Path(d)):
            supplement.supplement()
            build.build(supplement=Path(d)/'sop002_source_supplement.jsonl')
            g=Graph().parse(Path(d)/'enriched_with_supplement.ttl')
            self.assertEqual(len(list(g.subjects(RDF.type,build.IM.ThresholdRule))),27)
            self.assertEqual(len(list(g.triples((None,build.IM.critHi,None)))),22)
            methods=set(str(v) for v in g.objects(None,build.IM.extractionMethod))
            self.assertIn('deterministic_source_table',methods)
            self.assertNotIn('LLM',methods)
            ledger=[json.loads(line) for line in (Path(d)/'enriched_with_supplement_triple_sources.jsonl').read_text(encoding='utf8').splitlines()]
            covered={(r['subject'],r['predicate'],r['object']) for r in ledger}
            self.assertTrue(all((str(s),str(p),o.n3()) in covered for s,p,o in g))


if __name__=='__main__': unittest.main()
