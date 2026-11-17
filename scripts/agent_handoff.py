"""Offline audit, private runtime package and safe restore for the XAI handoff."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
OUT = ROOT / 'kg_build/agent_handoff_20261114'
RUNS = ('team_main_20261113_01', 'team_seongho_20261113_01',
        'team_document_20261113_01', 'team_kg_20261113_01', 'team_unavailable_20261114_01')
INPUTS = ('preprocessed/documents/chunks.jsonl', 'preprocessed/sensors/profile.json',
          'preprocessed/sensors/input/ts_input.csv', 'preprocessed/sensors/rules/sensor_thresholds.csv')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def audit():
    from rdflib import URIRef
    from imaks_kg.rag import comparison as c, demo, incident_agent, agent_v4_1, retrieval_v3 as r3
    from imaks_kg.rag import team_runtime as runtime, team_retrieval, vector as v
    sources, _ = v.source_records()
    by_source = {item['chunk_id']: item for item in sources + r3.row_corpus()}
    base = c.load_graph()
    # The unavailable example is deterministic and must never call a model.
    unavailable = ROOT / 'kg_build/graphrag_live' / RUNS[-1]
    if not unavailable.exists():
        def forbidden(*args, **kwargs):
            raise AssertionError('Offline audit attempted a model call')
        incident_agent.answer('현재 센서 측정값을 조회해줘.', unavailable, forbidden)
    checks = []
    for run_id in RUNS:
        folder = ROOT / 'kg_build/graphrag_live' / run_id
        answer = read(folder / 'answer.json')
        presented = demo.presentation(folder)
        issues = []
        def check(ok, description):
            if not ok:
                issues.append(description)
        check(presented['answer'] == answer['answer'], 'presentation changed the answer')
        check(presented['sources'] == answer['sources'], 'presentation changed sources')
        check(presented['edges'] == answer['graph_paths'], 'presentation changed graph paths')
        graph = base
        route = answer['integration'].get('route')
        if route == 'explain':
            store = runtime.store(answer['integration']['detector_profile'])
            graph = base + store.overlay
            incident = answer['xai']['incident']
            original = store.by_id[incident['id']]
            check(all(original.get(k) == val for k, val in incident.items() if k in original), 'incident differs from sealed run')
            for alarm in answer['xai']['alarms']:
                check(all(store.alarms[alarm['id']].get(k) == val for k, val in alarm.items()), 'alarm differs from sealed run')
            ir = read(store.run_dir / 'ir.json')['rules']
            for rule in answer['xai']['execution_parameters']:
                expected = next((item for item in ir if item['ir_id'] == rule['ir_id']), {})
                check(all(expected.get(k) == val for k, val in rule.items()), 'execution rule differs from sealed IR')
            check(presented['context_tokens'] == answer['xai']['context_tokens'], 'final evidence token count mismatch')
        if route == 'kg':
            computed, kg_sources, _ = team_retrieval.query_kg(answer['xai']['kg_query']['query'])
            check(computed == answer['xai']['kg_query'], 'KG computation differs from frozen graph')
            by_source.update({item['chunk_id']: item for item in kg_sources})
        for source in answer['sources']:
            expected = by_source.get(source['chunk_id'], {})
            check(source.get('text') == expected.get('text'), 'source text mismatch: ' + source['chunk_id'])
            check(digest(source['text'].encode()) == source['text_sha256'], 'source text hash mismatch')
            check(source['source_file_sha256'] == expected.get('source_file_sha256'), 'source file hash mismatch')
        for edge in answer['graph_paths']:
            triple = tuple(URIRef(edge[key]) for key in ('s', 'p', 'o'))
            check(triple in graph, 'displayed edge not stored: ' + edge['p'])
        if route in ('document', 'explain'):
            check(not agent_v4_1.citation_check(answer['answer'], [s['chunk_id'] for s in answer['sources']]), 'invalid document citations')
            check(bool(answer['verification']) and all(item['approved'] for item in answer['verification']), 'recorded verifier not approved')
        if route == 'unavailable':
            check(answer['status'] == 'insufficient_evidence', 'unsupported request was not withheld')
            check(not answer['usage'] and not answer['sources'] and not answer['graph_paths'], 'unsupported request called a model or claimed evidence')
        else:
            check(answer['status'] == 'complete', 'saved run was not complete')
        checks.append({'run_id': run_id, 'route': route, 'status': answer['status'],
            'source_count': len(answer['sources']), 'edge_count': len(answer['graph_paths']),
            'answer_sha256': digest((folder / 'answer.json').read_bytes()), 'issues': issues})
        if not issues:
            write(OUT / 'examples' / (run_id + '.json'), presented)
    result = {'date': '2026-11-14', 'scope': 'backend response and stored-evidence audit; no visual inspection',
              'new_api_calls': 0, 'passed': all(not item['issues'] for item in checks), 'runs': checks,
              'limits': ['Does not independently validate every natural-language claim.',
                         'Recorded AI approval is not a domain expert sign-off or benchmark score.']}
    write(OUT / 'response_audit.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result['passed']:
        raise SystemExit(1)
    return result


def approved_path(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
        return False
    if name in INPUTS:
        return True
    roots = ('kg_build/rule_engine_v3_1/', 'kg_build/rule_engine_v3_1_overlay/',
             'kg_build/team_app/', 'kg_build/tokenizer_cache/')
    if name.startswith(roots):
        return not any(part in ('query_cache', '.env', '__pycache__') for part in path.parts)
    return any(name.startswith('kg_build/graphrag_live/' + run + '/') for run in RUNS)


def package(output):
    from imaks_kg.rag import team_runtime as runtime
    audit_result = audit()
    paths = {ROOT / name for name in INPUTS}
    for profile in runtime.PROFILES:
        run, overlay = runtime.directories(profile)
        for root in (run, overlay):
            paths.update(path for path in root.rglob('*') if path.is_file())
        if profile.startswith('seongho_'):
            paths.update(path for path in (run.parent / 'original_detector').glob('*.json'))
    index = runtime.TEAM_ROOT / 'document_index'
    paths.update(index / name for name in ('manifest.json', 'vectors.npy'))
    paths.update(path for path in (ROOT / 'kg_build/tokenizer_cache').iterdir() if path.is_file())
    for run in RUNS:
        paths.update(path for path in (ROOT / 'kg_build/graphrag_live' / run).rglob('*.json'))
    # A local private package is distinct from the public Git commit.
    secrets = [os.environ.get('OPENAI_API_KEY', '').encode()]
    env = ROOT / '.env'
    if env.exists():
        secrets += [line.split('=', 1)[1].strip().strip('"\'').encode()
                    for line in env.read_text(encoding='utf-8-sig').splitlines()
                    if line.startswith('OPENAI_API_KEY=')]
    files = {}
    for path in sorted(paths):
        name = path.relative_to(ROOT).as_posix()
        if not approved_path(name):
            raise ValueError('File outside handoff allowlist: ' + name)
        data = path.read_bytes()
        if any(secret and secret in data for secret in secrets) or re.search(rb'sk-(?:proj-)?[A-Za-z0-9_-]{24,}', data):
            raise ValueError('Credential detected; nothing published')
        files[name] = data
    manifest = {'version': 'agent-runtime-handoff-v1', 'private_local_package': True,
                'new_api_calls': 0, 'defaults': runtime.DEFAULTS, 'runs': list(RUNS),
                'audit': audit_result, 'files': {name: {'sha256': digest(data), 'bytes': len(data)} for name, data in files.items()}}
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'x', ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr('HANDOFF_MANIFEST.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        assert all(digest(archive.read(name)) == item['sha256'] for name, item in manifest['files'].items())
    receipt = {'file': output.name, 'bytes': output.stat().st_size, 'sha256': digest(output.read_bytes()),
               'files': len(files), 'uncompressed_bytes': sum(len(data) for data in files.values()),
               'private_local_package': True, 'contains_api_key': False, 'publish_to_git': False}
    write(OUT / 'package_receipt.json', receipt)
    print(json.dumps(receipt, indent=2))


def restore(bundle, target):
    target = target.resolve()
    pending = []
    with ZipFile(bundle) as archive:
        manifest = json.loads(archive.read('HANDOFF_MANIFEST.json'))
        if manifest.get('version') != 'agent-runtime-handoff-v1':
            raise ValueError('Unknown handoff version')
        if set(archive.namelist()) != set(manifest['files']) | {'HANDOFF_MANIFEST.json'}:
            raise ValueError('Unexpected or missing archive entries')
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError('Duplicate archive entries')
        for name, item in manifest['files'].items():
            if not approved_path(name):
                raise ValueError('Unsafe or unexpected archive path')
            destination = (target / name).resolve()
            if not destination.is_relative_to(target):
                raise ValueError('Archive path escapes workspace')
            data = archive.read(name)
            if digest(data) != item['sha256'] or len(data) != item['bytes']:
                raise ValueError('Archive content checksum mismatch')
            if destination.exists() and digest(destination.read_bytes()) != item['sha256']:
                raise FileExistsError('Existing different file left untouched: ' + name)
            if not destination.exists():
                pending.append((destination, data))
        # Validate every entry and conflict before the first mutation.
        for destination, data in pending:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as stream:
                stream.write(data)
    print(json.dumps({'verified_files': len(manifest['files']), 'restored_files': len(pending),
                      'new_api_calls': 0, 'target': str(target)}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    commands.add_parser('audit')
    pack = commands.add_parser('package')
    pack.add_argument('--output', type=Path, default=OUT / 'imaks_agent_runtime_20261114.zip')
    unpack = commands.add_parser('restore')
    unpack.add_argument('bundle', type=Path)
    unpack.add_argument('--target', type=Path, default=ROOT)
    args = parser.parse_args()
    if args.action == 'audit':
        audit()
    elif args.action == 'package':
        package(args.output)
    else:
        restore(args.bundle, args.target)
