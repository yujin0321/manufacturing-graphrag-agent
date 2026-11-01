"""Local baseline archive with per-file SHA256; no API or extraction needed."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'evaluation/baselines/yewon_v2_comparison_20261024'
DIRECTORIES=[
    'src/imaks_kg/rag','docs/vector_rag_v1','docs/comparison_v1',
    'docs/benchmark_yewon_v2_20261023','evaluation/benchmark_yewon_v2_20261023',
    'evaluation/comparison_20261024','evaluation/vector_rag_dev_20261024',
    'kg_build/comparison_benchmark_20261024','kg_build/vector_rag_dev_20261024',
    'kg_build/vector_rag_v1','kg_build/comparison_v1',
]
FILES=[
    'artifacts/stage6_final_20261016/inputs/kg_build/openai_sol_v2_20261016/graph/candidate.ttl',
    'artifacts/stage6_final_20261016/inputs/kg_build/openai_sol_v2_20261016/llm_predictions.jsonl',
    'preprocessed/documents/chunks.jsonl','src/imaks_kg/__init__.py','src/imaks_kg/settings.py',
    'requirements-rag.txt','tests/test_vector_rag.py','tests/test_rag_comparison.py',
    'scripts/run_comparison_benchmark.py','scripts/preserve_comparison_baseline.py',
    'reports/comparison_eval_20261024_verify.md','reports/comparison_v1_20261024_verify.md',
    'reports/vector_rag_dev_20261024_verify.md','reports/vector_rag_v1_20261024_verify.md',
]
SUFFIXES={'.py','.json','.jsonl','.md','.csv','.txt','.ttl','.npy'}


def sha(b):return hashlib.sha256(b).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def encode(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8')


def verify(compare_working=False):
    seal=read(DEST/'seal.json');archive=DEST/'baseline_PRIVATE.zip'
    assert sha(archive.read_bytes())==seal['archive_sha256'],'Archive hash mismatch'
    assert sha((DEST/'manifest.json').read_bytes())==seal['manifest_sha256'],'Manifest hash mismatch'
    manifest=read(DEST/'manifest.json');changes=[]
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None,'ZIP CRC failure'
        assert set(z.namelist())==set(manifest['files'])|{'BASELINE_MANIFEST.json'}
        assert len(z.namelist())==len(set(z.namelist())),'Duplicate archive paths'
        assert z.read('BASELINE_MANIFEST.json')==(DEST/'manifest.json').read_bytes()
        for name,meta in manifest['files'].items():
            raw=z.read(name)
            assert len(raw)==meta['bytes'] and sha(raw)==meta['sha256'],name
            if compare_working and (not (ROOT/name).is_file() or sha((ROOT/name).read_bytes())!=meta['sha256']):changes.append(name)
    return {'archive_verified':True,'files':len(manifest['files']),'archive_bytes':archive.stat().st_size,'working_tree_changes':changes,'working_tree_compared':compare_working}


def build():
    if DEST.exists():raise FileExistsError('Baseline already exists; use verify, never overwrite')
    lock=read(ROOT/'docs/benchmark_yewon_v2_20261023/scoring_lock_v1.json')
    assert all(sha((ROOT/p).read_bytes())==h for p,h in lock['hashes'].items())
    audit=read(ROOT/'evaluation/comparison_20261024/execution_audit.json')
    assert all(sha((ROOT/p).read_bytes())==h for p,h in audit['answer_hashes'].items())
    old=read(ROOT/'evaluation/vector_rag_dev_20261024/summary.json')
    assert all(sha((ROOT/'kg_build/vector_rag_dev_20261024'/q/'answer.json').read_bytes())==h for q,h in old['answer_sha256'].items())
    paths={ROOT/p for p in FILES}
    for directory in DIRECTORIES:
        base=ROOT/directory
        assert base.is_dir(),directory
        paths.update(p for p in base.rglob('*') if p.is_file() and p.suffix in SUFFIXES and '__pycache__' not in p.parts)
    assert all(p.is_file() for p in paths)
    assert sum(p.name=='answer.json' for p in paths)==90
    manifest={'version':'yewon-v2-comparison-baseline-20261024','date_kst':'2026-10-24',
              'purpose':'Preserved pre-improvement baseline; private local archive',
              'python':platform.python_version(),'packages':{n:importlib.metadata.version(n) for n in ['numpy','tiktoken','rdflib']},
              'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'git_head_is_not_complete_snapshot':True,
              'answer_count':90,'scores':read(ROOT/'evaluation/comparison_20261024/summary.json'),
              'exclusions':['API keys/environment files','venv/model weights','original PDF ZIP','tokenizer cache','unrelated experiments'],
              'files':{p.relative_to(ROOT).as_posix():{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in sorted(paths)}}
    DEST.mkdir(parents=True,exist_ok=False)
    raw_manifest=encode(manifest);(DEST/'manifest.json').write_bytes(raw_manifest)
    archive=DEST/'baseline_PRIVATE.zip'
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,meta in manifest['files'].items():
            raw=(ROOT/name).read_bytes();assert sha(raw)==meta['sha256'],'File changed during snapshot'
            z.writestr(name,raw)
        z.writestr('BASELINE_MANIFEST.json',raw_manifest)
    (DEST/'seal.json').write_bytes(encode({'archive_sha256':sha(archive.read_bytes()),'manifest_sha256':sha(raw_manifest)}))
    return verify(compare_working=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['build','verify']);p.add_argument('--compare-working',action='store_true');a=p.parse_args()
    print(json.dumps(build() if a.action=='build' else verify(a.compare_working),ensure_ascii=False,indent=2))
