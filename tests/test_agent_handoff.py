import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from scripts import agent_handoff as handoff


class RestoreTests(unittest.TestCase):
    def setUp(self):
        scratch = handoff.ROOT / 'kg_build/handoff_tests'
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.temp.name).resolve()
        assert self.root.is_relative_to(scratch.resolve())
        self.target = self.root / 'restored'
        self.bundle = self.root / 'bundle.zip'

    def tearDown(self):
        self.temp.cleanup()

    def make_bundle(self, files, checksums=None):
        manifest = {'version': 'agent-runtime-handoff-v1', 'files': {
            name: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)} for name, data in files.items()}}
        if checksums:
            manifest['files'].update(checksums)
        with ZipFile(self.bundle, 'x') as archive:
            for name, data in files.items():
                archive.writestr(name, data)
            archive.writestr('HANDOFF_MANIFEST.json', json.dumps(manifest))

    def test_verified_restore_is_idempotent(self):
        name = 'kg_build/team_app/document_index/manifest.json'
        self.make_bundle({name: b'{}'})
        handoff.restore(self.bundle, self.target)
        handoff.restore(self.bundle, self.target)
        self.assertEqual((self.target / name).read_bytes(), b'{}')

    def test_checksum_error_causes_no_partial_write(self):
        first = 'kg_build/team_app/document_index/manifest.json'
        second = 'kg_build/team_app/document_index/vectors.npy'
        self.make_bundle({first: b'{}', second: b'vector'},
                         {second: {'sha256': '0' * 64, 'bytes': 6}})
        with self.assertRaises(ValueError):
            handoff.restore(self.bundle, self.target)
        self.assertFalse((self.target / first).exists())

    def test_existing_conflict_is_preserved_without_partial_write(self):
        first = 'kg_build/team_app/document_index/manifest.json'
        second = 'kg_build/team_app/document_index/vectors.npy'
        self.make_bundle({first: b'{}', second: b'new'})
        existing = self.target / second
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b'old')
        with self.assertRaises(FileExistsError):
            handoff.restore(self.bundle, self.target)
        self.assertEqual(existing.read_bytes(), b'old')
        self.assertFalse((self.target / first).exists())

    def test_path_traversal_cannot_escape_target(self):
        self.make_bundle({'../outside.txt': b'bad'})
        with self.assertRaises(ValueError):
            handoff.restore(self.bundle, self.target)
        self.assertFalse((self.root / 'outside.txt').exists())


if __name__ == '__main__':
    unittest.main()
