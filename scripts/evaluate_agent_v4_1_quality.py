"""Agent v4 development regression evaluation: freeze, real generation, seal; grade separately."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from imaks_kg.rag import agent_v4_1 as agent, retrieval_v4_1 as tools, vector as v

BENCH = ROOT / 'docs/benchmark_graph_v3_20261028'
SCORING = ROOT / 'docs/benchmark_yewon_v2_20261023/채점기준_확정_v1.md'


def load_key_environment():
    if os.environ.get('OPENAI_API_KEY'):
        return
    path = ROOT / '.env'
    if path.is_file():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if line.strip().startswith('OPENAI_API_KEY='):
                os.environ['OPENAI_API_KEY'] = line.split('=', 1)[1].strip().strip('\"\'')
                break
    if not os.environ.get('OPENAI_API_KEY'):
        raise ValueError('OPENAI_API_KEY unavailable; no request sent')


def questions():
    path = BENCH / 'questions.jsonl'
    lock = v.read(BENCH / 'lock.json')
    if v.digest(path.read_bytes()) != lock['hashes'][str(path.relative_to(ROOT)).replace('\\', '/')]:
        raise ValueError('Frozen questions changed')
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def seal(run):
    files = {str(p.relative_to(run)).replace('\\', '/'): v.digest(p.read_bytes())
             for p in sorted(run.rglob('*.json')) if p.name != 'generation_seal.json'}
    v.write(run / 'generation_seal.json', {'files': files, 'stage': 'generation_complete_or_stopped',
                                         'created_at': datetime.now(timezone.utc).isoformat()})


def generate(run, repeat):
    if repeat < 1:
        raise ValueError('repeat must be positive')
    qs = questions()
    load_key_environment()
    run.mkdir(parents=True, exist_ok=False)
    sources = [Path(agent.__file__), Path(tools.__file__), Path(__file__), SCORING, BENCH / 'questions.jsonl']
    protocol = {
        'version': 'agent-v4.1-quality-20261028-v1', 'created_at': datetime.now(timezone.utc).isoformat(),
        'questions': len(qs), 'repeat': repeat, 'expected_answers': len(qs) * repeat,
        'dense_used': True, 'retrieval': tools.retrieval_lock(True),
        'config': v.read(v.CONFIG), 'hashes': {str(p.relative_to(ROOT)): v.digest(p.read_bytes()) for p in sources},
        'generation_private_key_loaded': False,
        'scope': 'Agent v4: scenario routing, document instructions, dense+BM25 graph retrieval, typed queries, bounded verification with separate groundedness/completeness flags',
        'grading': 'Separate post-seal AI reviewer; existing frozen 3 content + evidence + faithfulness rubric',
        'human_review': False, 'exposure': 'Development regression on the previously evaluated 15 questions; code changes were informed by prior errors, not an unseen test',
        'max_chat_requests': len(qs) * repeat * 5, 'automatic_retries': False,
        'failure_policy': 'Failed/abstained answerable samples count as zero; stop whole run on transport/account errors; no sample replacement',
    }
    v.write(run / 'protocol.json', protocol)
    observations = []
    stopped = None
    try:
        for iteration in range(1, repeat + 1):
            for q in qs:
                relative = Path('answers') / q['id'] / f'run{iteration}'
                before = time.perf_counter()
                result = agent.answer(q['question'], run / relative, use_dense=True)
                plan = v.read(run / relative / 'plan.json') if (run / relative / 'plan.json').exists() else {}
                row = {'qid': q['id'], 'repeat': iteration, 'category': q['category'],
                       'question': q['question'], 'path': relative.as_posix(), 'status': result['status'],
                       'route': plan.get('intent'), 'tool': plan.get('tool'), 'reason': result.get('reason'),
                       'seconds': time.perf_counter() - before}
                observations.append(row)
                v.write(run / 'observations.json', observations)
                print(json.dumps({k: row[k] for k in ('qid', 'repeat', 'status', 'route', 'seconds')}, ensure_ascii=False), flush=True)
                errors = list((run / relative).rglob('*.error.json'))
                if errors:
                    stopped = {'qid': q['id'], 'repeat': iteration, 'error_files': [str(p.relative_to(run)) for p in errors]}
                    raise RuntimeError('API transport/account failure; stopped without retry')
    finally:
        v.write(run / 'generation_summary.json', {'planned': len(qs) * repeat, 'attempted': len(observations),
                'complete': sum(o['status'] == 'complete' for o in observations), 'stopped': stopped})
        seal(run)
    print(f'Generation sealed: {run}', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--repeat', type=int, default=3)
    args = p.parse_args()
    generate(args.out, args.repeat)
