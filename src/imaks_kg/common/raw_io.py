"""Read verified small source files without extracting the dataset to disk."""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
from zipfile import ZipFile

from imaks_kg.settings import IMAKS_DATA, REPO_ROOT


def raw_bytes(path, *, evaluation=False):
    path = Path(path).resolve()
    relative = path.relative_to(IMAKS_DATA.resolve()).as_posix()
    allowed = relative in {'kg_seed/nodes.csv', 'kg_seed/edges.csv'} or (
        relative.startswith(('rules/', 'datasheets/')) and relative.endswith('.pdf'))
    if evaluation and relative == 'kg_seed/ground_truth.csv':
        allowed = True
    if not allowed:
        raise ValueError('Source is outside the KG source allowlist: ' + relative)
    manifest = json.loads((REPO_ROOT / 'harness/raw_manifest.json').read_text(encoding='utf-8'))
    expected = manifest[relative]
    if expected['size'] > 5_000_000:
        raise ValueError('Small-source reader size limit exceeded')
    if path.is_file():
        data = path.read_bytes()
    else:
        archive = Path(os.environ.get('IMAKS_DATA_ZIP', REPO_ROOT.parent / 'iMAKS_dataset.zip'))
        with ZipFile(archive) as z:
            if z.getinfo(relative).file_size != expected['size']:
                raise ValueError('Archive member size mismatch: ' + relative)
            data = z.read(relative)
    if len(data) != expected['size'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
        raise ValueError('Source integrity mismatch: ' + relative)
    return data


def raw_sha256(path):
    return hashlib.sha256(raw_bytes(path)).hexdigest()


def raw_csv_rows(path, *, evaluation=False):
    reader = csv.DictReader(io.StringIO(raw_bytes(path, evaluation=evaluation).decode('utf-8-sig')))
    return list(reader.fieldnames or []), list(reader)
