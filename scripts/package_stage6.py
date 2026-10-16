"""Package only allowlisted stage-6 results and frozen reconstruction inputs."""
import json
import shutil
import hashlib
from pathlib import Path
from imaks_kg.kg.finalize_stage6 import run, OUT, INPUT, BASE, REPO_ROOT
from imaks_kg.kg.documents import units

DEST = REPO_ROOT / 'artifacts/stage6_final_20261016'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    run()
    review = json.loads((INPUT / 'ai_review.json').read_text(encoding='utf-8'))
    files = [REPO_ROOT / p for p in review['protected_artifact_sha256']]
    files += [BASE, INPUT / 'ai_review.json', INPUT / 'relation_candidates.ttl']
    for path in files:
        target = DEST / 'inputs' / path.relative_to(REPO_ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    (DEST / 'final').mkdir(parents=True, exist_ok=True)
    for name in ['document_kg.ttl', 'reviewed_relations.ttl', 'ontology.ttl', 'shapes.ttl',
                 'human_approved_relations.ttl', 'relations.json', 'triple_evidence.json',
                 'summary.json', 'release_manifest.json', 'base_shacl.txt', 'relation_shacl.txt']:
        shutil.copyfile(OUT / name, DEST / 'final' / name)
    needed = {e['unit_id'] for r in json.loads((INPUT / 'candidates.json').read_text(encoding='utf-8')) for e in r['evidence']}
    selected = [u for u in units() if u['unit_id'] in needed]
    assert len(selected) == len(needed)
    (DEST / 'source_units.json').write_text(json.dumps(selected, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    paths = [p for root in ['inputs', 'final'] for p in (DEST / root).rglob('*') if p.is_file()]
    paths.append(DEST / 'source_units.json')
    manifest = {'scope': 'Frozen source snapshot and v2 predictions; no API secrets, raw dataset, model or ground-truth answers',
                'source_snapshot_validation': 'Verified against local source units at packaging; snapshot rebuild does not re-verify original PDFs',
                'files': {p.relative_to(DEST).as_posix(): sha(p) for p in sorted(paths)}}
    (DEST / 'bundle_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Packaged {len(paths)} files; {sum(p.stat().st_size for p in paths):,} bytes')


if __name__ == '__main__':
    main()
