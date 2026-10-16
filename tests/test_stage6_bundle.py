import hashlib
import json
import unittest
from rdflib import Graph
from rdflib.compare import isomorphic
from pyshacl import validate
from imaks_kg.settings import REPO_ROOT

BUNDLE = REPO_ROOT / 'artifacts/stage6_final_20261016'


class BundleTests(unittest.TestCase):
    def test_bundle_integrity(self):
        manifest = json.loads((BUNDLE / 'bundle_manifest.json').read_text(encoding='utf-8'))
        for name, expected in manifest['files'].items():
            self.assertEqual(hashlib.sha256((BUNDLE / name).read_bytes()).hexdigest(), expected, name)

    def test_packaged_graph_shacl(self):
        g = Graph().parse(BUNDLE / 'final/document_kg.ttl')
        for shapes, ontology in [(BUNDLE / 'final/shapes.ttl', BUNDLE / 'final/ontology.ttl'),
                                 (REPO_ROOT / 'ontology_v1/shapes.ttl', REPO_ROOT / 'ontology_v1/ontology.ttl')]:
            self.assertTrue(validate(g, shacl_graph=Graph().parse(shapes), ont_graph=Graph().parse(ontology), inference='none')[0])

    def test_rebuilt_graph_isomorphic(self):
        from imaks_kg.kg.finalize_stage6 import run, OUT
        run(BUNDLE)
        self.assertTrue(isomorphic(Graph().parse(OUT / 'document_kg.ttl'), Graph().parse(BUNDLE / 'final/document_kg.ttl')))


if __name__ == '__main__':
    unittest.main()
