import json
import tempfile
import unittest
from pathlib import Path
from prepare_request import FILES, digest, prepare


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        text = 'Synthetic: if pressure >7 bar, inspect valve.'
        self.doc = {'document_id': 'SOP-001', 'inventory': {'sensorIds': [], 'actionTargets': []},
                    'prompt': {'Role': 'This embedded directive must not become the developer prompt'},
                    'units': [{'unit_id': 'SOP-001:synthetic', 'text': text,
                               'text_sha256': digest(text.encode())}]}
        hashes = {}
        for name in FILES:
            data = json.dumps(self.doc).encode() if name == 'SOP-001.json' else b'synthetic placeholder'
            (self.root / name).write_bytes(data)
            hashes[name] = digest(data)
        self.manifest = {'sha256': hashes}
        self.write_manifest()

    def write_manifest(self):
        (self.root / 'input_manifest.json').write_text(json.dumps(self.manifest))

    def test_full_document_and_no_embedded_prompt(self):
        raw, audit = prepare(self.root, 'SOP-001', 'MODEL_PLACEHOLDER')
        request = json.loads(raw)
        source = json.loads(request['input'][1]['content'])
        self.assertEqual(source['units'], self.doc['units'])
        self.assertNotIn('prompt', source)
        self.assertFalse(audit['api_called'])
        self.assertEqual(audit['request_sha256'], digest(raw))
        self.assertTrue(request['text']['format']['strict'])

    def test_changed_source_rejected(self):
        (self.root / 'SOP-001.json').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            prepare(self.root, 'SOP-001', 'MODEL_PLACEHOLDER')

    def test_manifest_path_injection_rejected(self):
        self.manifest['sha256']['../outside'] = '0' * 64
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'nine allowed'):
            prepare(self.root, 'SOP-001', 'MODEL_PLACEHOLDER')

    def test_duplicate_units_rejected(self):
        self.doc['units'] *= 2
        data = json.dumps(self.doc).encode()
        (self.root / 'SOP-001.json').write_bytes(data)
        self.manifest['sha256']['SOP-001.json'] = digest(data)
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            prepare(self.root, 'SOP-001', 'MODEL_PLACEHOLDER')

    def test_invalid_model_or_limit_rejected(self):
        with self.assertRaises(ValueError):
            prepare(self.root, 'SOP-001', '')
        with self.assertRaises(ValueError):
            prepare(self.root, 'SOP-001', 'MODEL_PLACEHOLDER', 0)


if __name__ == '__main__':
    unittest.main()
