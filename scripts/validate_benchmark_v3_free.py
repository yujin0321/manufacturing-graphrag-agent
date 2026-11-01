"""Free v3 validation: dependencies, official tokenizer, tests, retrieval, grade."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str) -> None:
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    out = args.out or ROOT / 'kg_build/benchmark_v3' / datetime.now().strftime('retrieval_bm25_%Y%m%d_%H%M%S_%f')
    if not out.is_absolute():
        out = ROOT / out
    if out.exists():
        parser.error(f'Output already exists; choose a new directory: {out}')
    os.environ['PYTHONPATH'] = str(ROOT / 'src')
    os.environ['PYTHONUTF8'] = '1'
    os.environ.setdefault('TIKTOKEN_CACHE_DIR', str(ROOT / 'kg_build/tokenizer_cache'))
    packages = ('numpy', 'tiktoken', 'rdflib')
    missing = [name for name in packages if importlib.util.find_spec(name) is None]
    print('Missing packages:', missing, flush=True)
    if missing:
        run('-m', 'pip', 'install', '-r', str(ROOT / 'requirements-rag.txt'))
        importlib.invalidate_caches()
    from importlib.metadata import version
    versions = {name: version(name) for name in packages}
    print('Installed versions:', json.dumps(versions), flush=True)
    import tiktoken
    try:
        encoding = tiktoken.get_encoding('o200k_base')
        encoding.encode('Manufacturing validation')
    except Exception as exc:
        raise SystemExit(f'Official o200k_base preparation failed; no fallback used: {exc}') from exc
    print('Tokenizer: o200k_base (official tiktoken; first download allowed)', flush=True)
    run('-m', 'unittest', 'tests.test_retrieval_v3', 'tests.test_detector_kg', '-v')
    run('scripts/run_benchmark_v3.py', 'retrieve', '--bm25-only', '--out', str(out))
    # Only this separate process opens the private answer key after retrieval is sealed.
    run('scripts/run_benchmark_v3.py', 'grade', '--run', str(out))
    summary = json.loads((out / 'grade_summary.json').read_text(encoding='utf-8'))
    cloud = {'vector_v3': 13, 'vector_v3_lex': 44, 'graph_v3': 43}
    for name, previous in cloud.items():
        current = summary['systems'][name]
        print(f'{name}: o200k={current["found"]}/{current["needed"]}; cloud approximate={previous}/48')
    (out / 'environment.json').write_text(json.dumps({
        'python': sys.version, 'packages': versions, 'missing_before_install': missing,
        'tokenizer': 'o200k_base', 'dense_used': False,
    }, indent=2), encoding='utf-8')
    print(f'Free validation complete: {out}')


if __name__ == '__main__':
    main()
