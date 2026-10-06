"""Actual generation and blinded per-question AI review; no simulated answer rows."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse,json,random,hashlib
from pathlib import Path
import run_llm_evaluation as backend
from prepare_benchmark_v2 import ROOT,OUT,source_record,support_keys,dump

JUDGE_SYSTEM='''당신은 문서 기반 답변의 평가자다. 아래 평가 기준과 기대 사실을 사용하라. answer_id는 익명이며 방법이나 반복을 추측하지 말라.
각 답변은 자신에게 제공된 context만 사용해야 한다. 답변에 없는 사실을 보충해서 점수를 주지 말라.
grounding: 2=주요 주장이 해당 context로 뒷받침됨(올바른 보류 포함), 1=일부 불명확, 0=핵심 근거 없는/모순 주장.
condition_handling: 2=가정/관측/지속시간/명령여부/적용성 한계를 정확히 구분, 1=일부 빠짐, 0=불확실 조건을 확정하거나 인과/해결을 보장.
completeness: 2=기대 핵심 사실 모두 답변, 1=일부 답변 또는 근거부족에 따른 부분 보류, 0=핵심 질문에 답하지 못함.
지원하지 않은 사실을 맞혔더라도 grounding은 감점하라. 간결함과 긴 답변 자체는 점수 기준이 아니다.
각 답변의 점수, 구체적 한국어 이유, unsupported_claims 목록을 반환하라. 도구나 외부 지식을 사용하지 말라.'''
JUDGE_SCHEMA={'type':'object','properties':{'reviews':{'type':'array','items':{'type':'object','properties':{
    'answer_id':{'type':'string'},'grounding':{'type':'integer','minimum':0,'maximum':2},
    'condition_handling':{'type':'integer','minimum':0,'maximum':2},'completeness':{'type':'integer','minimum':0,'maximum':2},
    'rationale':{'type':'string'},'unsupported_claims':{'type':'array','items':{'type':'string'}}},
    'required':['answer_id','grounding','condition_handling','completeness','rationale','unsupported_claims'],'additionalProperties':False}}},
    'required':['reviews'],'additionalProperties':False}

def run_phase(requests,phase,schema,workers):
    directory=OUT/phase
    for folder in ['answers','logs','isolated']:(directory/folder).mkdir(parents=True,exist_ok=True)
    dump(directory/'answer_schema.json',schema)
    cfg=json.loads((ROOT/'benchmark_v2.json').read_text(encoding='utf-8'))['config']
    backend.OUT=directory;backend.MODEL=cfg['model'];backend.SCHEMA=schema
    random.Random(cfg['seed']).shuffle(requests)
    results=[];failures=[]
    # Submit bounded batches. Stop after a failed batch rather than hammering a limit.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for offset in range(0,len(requests),workers):
            jobs={pool.submit(backend.generate,r):r for r in requests[offset:offset+workers]}
            for future in as_completed(jobs):
                request=jobs[future]
                try:
                    a=future.result();results.append(a)
                    print(f"{phase}: {len(results)}/{len(requests)} {a['id']} {a['mode']}",flush=True)
                except Exception as exc:
                    failures.append({'id':request['id'],'mode':request['mode'],'error':str(exc)})
                    print(str(exc),flush=True)
            if failures:break
    # Preserve all completed cache files, including results from earlier interrupted runs.
    all_answers=[json.loads(p.read_text(encoding='utf-8')) for p in sorted((directory/'answers').glob('*.json'))]
    with (directory/'all_answers.jsonl').open('w',encoding='utf-8') as f:
        for a in all_answers:f.write(json.dumps(a,ensure_ascii=False)+'\n')
    dump(directory/'status.json',{'phase':phase,'expected_this_call':len(requests),'completed_this_call':len(results),
        'total_cached':len(all_answers),'failures':failures,'model':cfg['model'],'reasoning_effort':cfg['reasoning_effort'],
        'temperature':None,'temperature_control':'not_exposed_by_codex_cli','tool_use_audit':'reject non-reasoning/non-message items'})
    if failures:raise SystemExit(1)
    return all_answers

def generation(limit,workers):
    requests=[json.loads(s) for s in (OUT/'generation_requests.jsonl').read_text(encoding='utf-8').splitlines()]
    for r in requests:r['id']=r['id']+'_r'+str(r['repeat'])
    if limit:requests=requests[:limit]
    return run_phase(requests,'generation',backend.SCHEMA,workers)

def judging(workers):
    definition=json.loads((ROOT/'benchmark_v2.json').read_text(encoding='utf-8'))
    cfg=definition['config'];cases=definition['cases']
    answers=[json.loads(s) for s in (OUT/'generation/all_answers.jsonl').read_text(encoding='utf-8').splitlines()]
    if len(answers)!=len(cases)*3*cfg['repeats']:raise ValueError('Complete all generation pairs before judging')
    contexts={(p['id'],p['mode']):p for p in json.loads((OUT/'prepared_contexts.json').read_text(encoding='utf-8'))}
    corpus=json.loads((OUT/'shared_corpus.json').read_text(encoding='utf-8'))
    requests=[];mapping=[]
    for case in cases:
        chosen=[a for a in answers if a['id'].split('_r')[0]==case['id']]
        random.Random(cfg['seed']+sum(map(ord,case['id']))).shuffle(chosen)
        blind=[]
        for i,a in enumerate(chosen):
            anonymous=f'A{i+1}'
            context=contexts[(case['id'],a['mode'])]['context']
            generated={k:a[k] for k in ['answer','citations','proposed_actions','uncertainties']}
            blind.append({'answer_id':anonymous,'response':generated,'provided_context':context})
            mapping.append({'case_id':case['id'],'answer_id':anonymous,'generation_id':a['id'],'mode':a['mode'],
                'input_sha256':a['input_sha256'],'answer_sha256':hashlib.sha256(a['answer'].encode()).hexdigest()})
        gold_flat=set(x for g in case['gold'] for x in g)
        reference=[source_record(d) for d in corpus if support_keys(d)&gold_flat]
        payload={'question':case['question'],'expected_facts':case['expected'],'condition_requirement':case['condition'],
                 'reference_for_expected_facts':reference,'responses':blind}
        requests.append({'id':case['id'],'mode':'blinded_judge','temperature':None,
            'prompt_sha256':hashlib.sha256(JUDGE_SYSTEM.encode()).hexdigest(),
            'messages':[{'role':'system','content':JUDGE_SYSTEM},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]})
    dump(OUT/'judge_private_mapping.json',mapping)
    with (OUT/'judge_requests.jsonl').open('w',encoding='utf-8') as f:
        for r in requests:f.write(json.dumps(r,ensure_ascii=False)+'\n')
    return run_phase(requests,'judge',JUDGE_SCHEMA,workers)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['generate','judge']);p.add_argument('--limit',type=int);p.add_argument('--workers',type=int,default=3)
    args=p.parse_args()
    if args.phase=='generate':generation(args.limit,args.workers)
    else:judging(args.workers)
