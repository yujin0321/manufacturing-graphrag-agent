import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from imaks_kg.stage3 import gemini


class GeminiAdapterTests(unittest.TestCase):
    def setup_request(self, directory):
        root = Path(directory)
        request = {"request_id": "SOP-003", "request_sha256": "fixture-hash", "system": "fixture", "input": {}}
        (root / 'requests.jsonl').write_text(json.dumps(request) + '\n', encoding='utf8')
        return root

    def test_request_schema_settings_and_resume(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.setup_request(d)
            payload = {"modelVersion": "fixture-version", "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": '{"rules": []}'}]}}]}
            response = io.BytesIO(json.dumps(payload).encode())
            with patch.object(gemini, 'OUT', root), patch.object(gemini, 'read_gemini_key', return_value='dummy-key'), patch.object(gemini.urllib.request, 'urlopen', return_value=response) as network:
                gemini.run('fixture', only='SOP-003', thinking='low')
                body = json.loads(network.call_args.args[0].data)
                self.assertEqual(body['generationConfig']['thinkingConfig']['thinkingLevel'], 'low')
                self.assertEqual(body['generationConfig']['responseJsonSchema'], gemini.SCHEMA)
                gemini.run('fixture', only='SOP-003', thinking='low')
                self.assertEqual(network.call_count, 1)

    def test_api_error_does_not_write_key(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.setup_request(d)
            error = urllib.error.HTTPError('https://generativelanguage.googleapis.com', 403, 'Forbidden', {}, io.BytesIO(b'error reflected dummy-key'))
            with patch.object(gemini, 'OUT', root), patch.object(gemini, 'read_gemini_key', return_value='dummy-key'), patch.object(gemini.urllib.request, 'urlopen', side_effect=error):
                with self.assertRaises(RuntimeError):
                    gemini.run('fixture', only='SOP-003')
            for path in root.rglob('*'):
                if path.is_file():
                    self.assertNotIn('dummy-key', path.read_text(encoding='utf8'))


if __name__ == '__main__':
    unittest.main()
