"""Read saved usage only. This program never imports or calls an API client."""
from collections import Counter
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parent.parent

def main():
    stages=[('answer_generation',ROOT/'runs/answers_final'),
            ('question_embeddings',ROOT/'runs/retrieval_v2/query_embeddings'),
            ('additional_key_authoring',ROOT/'evaluation/expanded/authoring_api')]
    report={};total=Counter();unresolved=[]
    for label,folder in stages:
        files=sorted(folder.rglob('*.response.json'));usage=Counter();models=Counter()
        for path in files:
            raw=json.loads(path.read_text(encoding='utf-8'));u=raw.get('usage',{})
            models[raw.get('model','unknown')]+=1
            for field in ['prompt_tokens','completion_tokens','total_tokens']:usage[field]+=u.get(field,0)
            usage['cached_prompt_tokens']+=u.get('prompt_tokens_details',{}).get('cached_tokens',0)
        for path in folder.rglob('*.attempt.json'):
            if not path.with_name(path.name.replace('.attempt.json','.response.json')).exists():
                unresolved.append(str(path.relative_to(ROOT)))
        report[label]={'saved_responses':len(files),'models':dict(models),'usage':dict(usage)}
        total.update(usage)
    answers=list((ROOT/'runs/answers_final').glob('*/*/answer.json'))
    by_system=Counter();by_status=Counter()
    for path in answers:
        item=json.loads(path.read_text(encoding='utf-8'));by_system[item['system']]+=1;by_status[item['status']]+=1
    result={'status':'API execution stopped after user cost concern; no automatic continuation authorized',
        'recorded_at_kst':datetime.now(timezone(timedelta(hours=9))).isoformat(),
        'stages':report,'recorded_total':dict(total),'saved_answers':len(answers),'by_system':dict(by_system),
        'by_status':dict(by_status),'unresolved_attempts':unresolved,
        'billing_limit':'Saved response usage is not an invoice. In-flight/interrupted requests may incur additional usage not saved locally.',
        'final_comparison_ready':False,'no_new_api_calls_in_this_audit':True}
    out=ROOT/'reports';out.mkdir(exist_ok=True)
    (out/'API사용량_중단시점.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# API 실행 중단 시점의 저장 기록','',
        '사용자의 비용 우려에 따라 추가 API 실행을 중단했다. 전체 문항 비교·최종 채점은 완료되지 않았다.','',
        f'저장된 답변: {len(answers)}개. 모델별: '+', '.join(f'{s} {n}개' for s,n in by_system.items()),'',
        '| 단계 | 저장된 API 응답 수 | 입력 토큰 | 출력 토큰 | 합계 토큰 |','|---|---:|---:|---:|---:|']
    for stage,item in report.items():
        u=item['usage'];lines.append(f"| {stage} | {item['saved_responses']} | {u.get('prompt_tokens',0):,} | {u.get('completion_tokens',0):,} | {u.get('total_tokens',0):,} |")
    lines+=['','이 수치는 로컬에 응답이 저장된 요청의 사용량이다. 실제 청구액은 확인하지 않았으며, 중단 당시 처리 중이던 요청은 별도 과금될 수 있다.',
            f'응답 미저장 시도: {len(unresolved)}건. 자동 재전송하지 않는다.','',
            '문항집: `benchmark_catalog.py` (130개). 답변 비교 대상 102개, 별도 오류 주입 검증 2개, 입력 미지정 대기 26개.',
            '1차 검색 평가: `reports/retrieval/retrieval_summary.json`. 검색 근거 회수율이며 답변 정확도와 다르다.',
            '답변: `runs/answers_final/<방식>/<문항ID>/answer.json`. 현재 일반 LLM도 유료 API이며 무료 서비스 비교가 아니다.']
    (out/'진행현황_및_API사용량.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
