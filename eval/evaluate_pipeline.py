"""Export unchanged automatic predictions, then use the user-approved team protocol."""
import os, sys, json, hashlib, importlib.util, argparse
from pathlib import Path
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'src'),str(root/'eval')]
sys.path.append(str(root/'.venv/Lib/site-packages'))
from imaks_kg.eval.cli import run_evaluation
from imaks_kg.eval.embed import SbertEmbedder,DEFAULT_REVISION
from imaks_kg.extract import llm_openai,ledger
from imaks_kg.extract.common import safe_name
from sentence_transformers import SentenceTransformer

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def lines(path): return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]
parser=argparse.ArgumentParser(description='Team-protocol automatic rule evaluation')
parser.add_argument('--run-dir',type=Path,required=True)
parser.add_argument('--out-dir',type=Path,required=True)
args=parser.parse_args()
run=args.run_dir.resolve()
meta=json.loads((run/'meta.json').read_text(encoding='utf-8'))
if meta['mode']!='execute' or meta['status']!='completed': raise ValueError('Real extraction is not complete')
ledger.verify_run(run,'run_finished')
out=args.out_dir.resolve()
out.mkdir(parents=True,exist_ok=False)
calls=lines(run/'calls.jsonl')
served={c['served_model'] for c in calls if c['http_200']}
if served!={'gpt-6.1-sol'}: raise ValueError('Actual models differ; split models before scoring')
requests={p.stem:json.loads(p.read_text(encoding='utf-8')) for p in (run/'raw/request').glob('*.json')}
schema_hashes={hashlib.sha256(json.dumps(r['text']['format']['schema'],sort_keys=True).encode()).hexdigest() for r in requests.values()}
chunks={c['chunk_id']:c for c in lines(root/'preprocessed/documents/chunks.jsonl')}
raw_predictions=[]
for call in calls:
    cid=call['key']
    raw=json.loads((run/'raw/response'/(safe_name(cid)+'.json')).read_text(encoding='utf-8'))
    result=llm_openai.interpret(cid,raw)
    if not result.ok: continue
    for index,r in enumerate(result.parsed['rules'],1):
        raw_predictions.append({'document_id':chunks[cid]['doc_id'],'class':r['class'],
              'condition':r['conditionText'],'action':r['responseText'],
              'identifier':r['ruleIdInText'] or f'{cid}:prediction{index}',
              'sensors':r['sensors'],'model':result.served_model,'chunk_id':cid,
              'sourceQuote':r['sourceQuote'],'origin':'C_automatic_raw'})
def save_predictions(name,rows):
    p=out/(name+'.jsonl')
    p.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
    return p
primary=save_predictions('C_automatic_raw',raw_predictions)
# B is a deterministic, separately reported baseline, not LLM output.
spec=importlib.util.spec_from_file_location('legacy_reader',root/'eval/evaluate_rules.py')
reader=importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)
b=[dict(document_id=r['doc_id'],**{'class':r['class']},condition=r['condition'],action=r['response'],
        identifier=r['identifier'],sensors=r['sensors'],origin='B_deterministic') for r in reader.load_b(root/'kg_build/rules_deterministic.ttl')]
baseline=save_predictions('B_deterministic',b)
# No recombination of split predictions. B+C is a declared supplementary union, not a replacement for the raw primary.
union=save_predictions('B_plus_C_union',b+raw_predictions)
merged=[r for r in lines(run/'merged.jsonl') if r['merge']['merged']]
confirmation_keys={(r['doc_id'],r['ruleIdInText']) for r in merged}
pipeline_rows=b+[r for r in raw_predictions if (r['document_id'],r['identifier']) not in confirmation_keys]
pipeline=save_predictions('B_plus_C_pipeline',pipeline_rows)
definitions=[root/'docs/eval_definition_F1_content.md',root/'docs/eval_definition_team_summary.md']
inputs=[run/'meta.json',run/'calls.jsonl',run/'candidates_premerge.jsonl',run/'merged.jsonl',run/'rejected.csv',
        root/'kg_build/rules_deterministic.ttl',root/'kg_build/seed.ttl',root/'evaluation/model_info.json',*definitions]
inputs+=list((run/'raw/request').glob('*.json'))+list((run/'raw/response').glob('*.json'))
hashes={str(p.relative_to(root)):digest(p) for p in inputs}
metadata={'requested_model':meta['model'],'actual_models':sorted(served),'prompt_sha256':meta['prompt_sha256'],
          'prompt_version':meta['prompt_version'],'example_sha256':digest(root/'src/imaks_kg/extract/prompts/v1/examples.json'),
          'schema_sha256':sorted(schema_hashes),'source_files_sha256':hashes,
          'prior_gold_exposure':True,'gold_exposure_note':'Earlier branch comparison used this reference. Development evaluation, not independent holdout.',
          'human_corrected':False,'primary':'raw automatic C predictions; validation rejects are not removed',
          'secondary':'B baseline; B+C pipeline preserves source-identity B confirmations once; B+C union includes duplicates',
          'processed_documents':sorted({chunks[c['key']]['doc_id'] for c in calls if c['http_200']})}
(out/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
snapshot=root/'evaluation/models/models--sentence-transformers--all-MiniLM-L6-v2/snapshots'/DEFAULT_REVISION
info=json.loads((root/'evaluation/model_info.json').read_text(encoding='utf-8'))
if info['revision']!=DEFAULT_REVISION: raise ValueError('Embedding revision mismatch')
for filename,expected in info['files'].items():
    if digest(snapshot/filename)!=expected: raise ValueError('Embedding weights changed')
embedder=SbertEmbedder()
embedder._model=SentenceTransformer(str(snapshot),device='cpu',local_files_only=True)
embedder.loaded_revision=lambda:DEFAULT_REVISION
scores={}
for name,p in [('C_automatic_raw',primary),('B_deterministic',baseline),('B_plus_C_pipeline',pipeline),('B_plus_C_union',union)]:
    score=run_evaluation(p,out/name,meta_path=out/'metadata.json',embedder=embedder,
           definition=definitions[0],processed_docs=set(metadata['processed_documents']))
    if score['inputs']['gold_rows']!=86: raise ValueError('Expected exactly 86 original reference rows')
    scores[name]=score
if any(digest(root/p)!=h for p,h in hashes.items()): raise ValueError('Input changed during evaluation')
result={'protocol':'user-provided two MD files','extraction_model':sorted(served),'human_review':'pending; automatic baseline only',
        'metrics':scores,'source_files_unchanged':True}
(out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
usage=[c.get('usage',{}) for c in calls]
input_tokens=sum(u.get('input_tokens',0) for u in usage)
output_tokens=sum(u.get('output_tokens',0) for u in usage)
report=['# GPT-6.1 Sol C 추출 및 86규칙 첫 정량 결과','',
        '자동 결과를 먼저 고정해 평가했다. 사람 검토는 대기 상태이며 정답 노출 이력이 있는 개발 평가다.',
        '', '| 결과 | 예측 | TP | FP | FN | Precision | Recall | F1_content | 분류 일치 F1 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
for name,score in scores.items():
    m=score['main_report']
    report.append(f"| {name} | {m['n_pred']} | {m['tp']} | {m['fp']} | {m['fn']} | {m['precision']:.4f} | {m['recall']:.4f} | {m['f1']:.4f} | {m['class_aware']['f1']:.4f} |")
report+=['','C_automatic_raw는 LLM 자동 추출, B+C pipeline은 전체 규칙 구축 결과다. B는 코드 변환 기준선, B+C union은 중복을 포함한 보조 결과다. Pipeline은 추출 시 기록된 같은 문서·같은 인쇄 ID의 B 재확인 8건만 한 번 집계하며 분할 예측은 합치지 않는다.',
         '문장 condition+공백+action, 같은 문서 안 매칭, 유효 수 우선 Hungarian, 임계 0.6, 정답 86건 전체 분모. 데이터시트는 범위 밖으로 별도 집계.',
         f'전체 사용량: 입력 {input_tokens:,}, 출력·추론 {output_tokens:,} 토큰. 표준 단가 계산 ${input_tokens*2/1e6+output_tokens*10/1e6:.4f} (대시보드 청구액 별도 확인).',
         '임베딩 all-MiniLM-L6-v2 revision '+DEFAULT_REVISION+'. 모델 파일 해시 검증, 로컬 CPU 실행.',
         '문서별 결과·분류 혼동표·센서 일치·세분화 비율·이론 F1 상한·0.5/0.6/0.7 민감도는 summary.json에 기록.',
         '정답은 src/imaks_kg/eval/gold.py만 읽으며 pre_evaluation_lock.json을 먼저 기록했다. 개별 매칭·예측 파일은 extraction/evaluation 아래 로컬 보존한다.',
         '남은 작업: 1차·2차 사람 검토, 승인 후 RDF 최종 출력. 자동 첫 정량 결과 완료와 사람 검토 완료를 구분한다.']
(root/'reports/gpt61_sol_first_evaluation.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
print(json.dumps({k:v['main_report'] for k,v in scores.items()},ensure_ascii=False))
