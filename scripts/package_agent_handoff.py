"""Explicit local allowlist packages; no publication, credentials or API requests."""
import hashlib
import json
import os
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'kg_build/team_handoff_20261028'
def sha(b): return hashlib.sha256(b).hexdigest()

def package(name, paths, gold):
    paths = sorted(set(paths))
    files = {}
    key = os.environ.get('OPENAI_API_KEY', '').encode()
    for rel in paths:
        p = ROOT / rel
        data = p.read_bytes()
        if key and key in data:
            raise ValueError('Credential detected; package aborted')
        if not gold and ('gold_event_demo' in rel or 'kg_seed/' in rel or 'ground_truth' in p.name):
            raise ValueError('Gold file in normal package')
        files[rel] = data
    manifest = {'gold_provided_demo': gold, 'files': {k: {'sha256': sha(b), 'bytes': len(b)} for k,b in files.items()}}
    with ZipFile(OUT / name, 'x', ZIP_DEFLATED) as z:
        for rel, data in files.items(): z.writestr(rel, data)
        z.writestr('BUNDLE_MANIFEST.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    with ZipFile(OUT / name) as z:
        assert z.testzip() is None
        for rel, item in manifest['files'].items(): assert sha(z.read(rel)) == item['sha256']
    return {'file':name,'bytes':(OUT/name).stat().st_size,'sha256':sha((OUT/name).read_bytes()),'files':len(files)}

def main():
    OUT.mkdir(parents=True, exist_ok=False)
    normal = ['requirements-rag.txt','src/imaks_kg/__init__.py','src/imaks_kg/settings.py',
              'src/imaks_kg/detection/__init__.py','src/imaks_kg/detection/rules.py',
              'docs/vector_rag_v1/config.json','docs/vector_rag_v1/answer_instructions.txt',
              'docs/graphrag_v2/retrieval_policy.json','docs/benchmark_yewon_v2_20261023/scoring_lock_v1.json',
              'preprocessed/documents/chunks.jsonl',
              'artifacts/stage6_final_20261016/inputs/kg_build/openai_sol_v2_20261016/graph/candidate.ttl',
              'docs/TEAM_HANDOFF_20261028.md','reports/agent_ui_validation_20261028_verify.md',
              'reports/e2e_handoff_20261028_verify.md']
    normal += [p.relative_to(ROOT).as_posix() for p in (ROOT/'src/imaks_kg/rag').glob('*') if p.suffix in {'.py','.html'} and p.name!='seed_event_demo.py']
    normal += ['kg_build/vector_rag_v1/'+n for n in ['corpus.json','vectors.npy','index_manifest.json']]
    normal += [p.relative_to(ROOT).as_posix() for p in (ROOT/'kg_build/tokenizer_cache').iterdir() if p.is_file()]
    seal=json.loads((ROOT/'kg_build/rule_detector_20261026/complete.json').read_text())
    normal += ['kg_build/rule_detector_20261026/'+n for n in list(seal)+['complete.json']]
    for name in ['agent_document_20261028','agent_document_fixed_20261028','agent_multiple_20261028','agent_current_20261028']:
        folder=ROOT/'kg_build/graphrag_live'/name
        for n in ['input.json','answer.json','agent_lock.json','tools/trace.json']:
            if (folder/n).exists(): normal.append((folder/n).relative_to(ROOT).as_posix())
    normal += ['kg_build/e2e_handoff_20261028/'+n for n in ['tests.json','tests.txt']]
    gold = [p.relative_to(ROOT).as_posix() for p in (ROOT/'kg_build/gold_event_demo_20261028').iterdir() if p.is_file()]
    gold += ['src/imaks_kg/rag/seed_event_demo.py','tests/test_seed_event_demo.py','reports/gold_event_demo_20261028_verify.md','docs/TEAM_HANDOFF_20261028.md']
    bundles=[package('imaks_agent_runtime.zip',normal,False),package('imaks_gold_demo_ONLY.zip',gold,True)]
    (OUT/'bundles.json').write_text(json.dumps(bundles,indent=2),encoding='utf-8')
    print(json.dumps(bundles,indent=2))

if __name__ == '__main__': main()
