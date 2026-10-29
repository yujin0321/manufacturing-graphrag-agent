"""Publish compact, auditable results without model calls or price estimates."""
from collections import Counter,defaultdict
from pathlib import Path
import csv
import json
import statistics
import sys
ROOT=Path(__file__).resolve().parent
REPO=ROOT.parent.parent
sys.path.insert(0,str(REPO/'src'))
from imaks_kg.rag import vector as v
from benchmark_catalog import BENCHMARKS

OUT=ROOT/'reports/offline_budget_v1'

def link(path,label=None):return f'[{label or path.name}](<{path.as_posix()}>)'

def main():
    rows=v.read(OUT/'retrieval_details.json');summary=v.read(OUT/'retrieval_summary.json')
    coverage=v.read(ROOT/'runs/offline_budget_v1/retrieval_coverage.json')
    model=v.read(ROOT/'runs/offline_budget_v1/local_embedding_manifest.json')
    review=v.read(OUT/'representative_review.json');questions={q['id']:q for q in BENCHMARKS}
    api_counts={name:len(list((ROOT/folder).rglob('*.response.json'))) for name,folder in [
        ('answer_generation','runs/answers_final'),('question_embeddings','runs/retrieval_v2/query_embeddings'),
        ('additional_key_authoring','evaluation/expanded/authoring_api')]}
    before=v.read(ROOT/'reports/API사용량_중단시점.json')['stages']
    unchanged=all(api_counts[name]==before[name]['saved_responses'] for name in api_counts)
    assert unchanged,'Unexpected paid response appeared during offline evaluation'
    assert model['network_attempts']==0 and coverage['network_attempts']==0
    lines=['# 전체 문항 검색 비교와 대표 답변 검토','',
        '**이번 실행의 추가 API 호출·답변 생성·모델 채점 호출은 모두 0회다.** 저장된 API 임베딩과 PC에 있던 로컬 모델을 사용했다.',
        '전체 130문항을 코드에 보존했다. 입력이 고정된 102문항의 검색을 비교했고, 오류 주입 2문항은 별도 검증 결과로 연결했다. 사건·후보·시간 구간 등이 없는 26문항은 미실행 사유를 남겼다.','',
        '검색 평가는 정답에 필요한 원문/노드 기록을 문맥에 얼마나 포함했는지 측정한다. 답변 정확도와 다르다. 일반 LLM은 검색기가 없으므로 검색 점수는 N/A이며, 대표 답변에서만 함께 검토한다.','',
        '## 1. 기존 API 임베딩 재사용 — 35문항','',
        '이 트랙은 기존 text-embedding-3-small 문서 인덱스와 정확히 일치하는 저장 질문 벡터만 사용했다. 질문 캐시가 없는 67문항에 새 API 임베딩을 요청하지 않았다.','',
        '| 방식 | 문항 수 | 필수 근거 회수율 | 필수 근거를 모두 회수한 문항 | 평균 문맥 토큰 |',
        '|---|---:|---:|---:|---:|']
    for system in ['VectorRAG','HybridRAG','GraphNoTopology','GraphRAG']:
        item=next(r for r in summary if r['encoder_track']=='cached_api' and r['track']=='all' and r['budget']==4000 and r['system']==system)
        lines.append(f"| {system} | {item['questions']} | {item['micro_evidence_recall']:.1%} | {item['complete_questions']}/{item['questions']} | {item['mean_context_tokens']:.0f} |")
    lines += ['','근거 예산은 동일하게 최대 4,000토큰이다. HybridRAG는 같은 별칭 사전과 BM25+벡터 검색을 사용한다. GraphNoTopology는 같은 자료·전처리·문맥 구성에서 구조화 KG 조회를 끈 대조군이다.',
        '**35개 문서 질문에서 GraphRAG와 그래프를 끈 대조군의 회수율은 같다. 따라서 VectorRAG 대비 개선분 전체를 그래프 자체의 효과로 주장할 수 없다.**','',
        '## 2. 로컬 모델 — 전체 실행 가능 102문항','',
        '로컬에 이미 있던 jhgan/ko-sroberta-multitask 가중치로 문서·KG 기록과 질문을 계산해 저장했다. 다른 모델의 벡터 공간을 섞지 않았다. 한국어·영어 정렬 성능은 별도 검증하지 않았으므로 기존 API 트랙과 절대 성능을 직접 비교하지 않는다.',
        '같은 질문 안에서는 두 RAG에 동일 원문·동일 KG 사실을 제공한다. VectorRAG에는 KG 노드를 텍스트 기록으로, GraphRAG에는 같은 텍스트 기록과 구조화 탐색을 제공한다. 원문 QA는 최대 4,000토큰, KG 질문은 최대 8,000토큰이다.','',
        '| 문항군 | 방식 | 문항 수 | 필수 근거 회수율 | 전부 회수 | 평균 문맥 토큰 |',
        '|---|---|---:|---:|---:|---:|']
    track_names={'document_qa':'문서 QA','kg_structure':'KG 관계·집합·경로','kg_and_documents':'YB 구조·메타데이터·문서'}
    for track,budget in [('document_qa',4000),('kg_structure',8000),('kg_and_documents',8000)]:
        for system in ['VectorRAG','GraphNoTopology','GraphRAG']:
            item=next(r for r in summary if r['encoder_track']=='local_offline' and r['track']==track and r['budget']==budget and r['system']==system)
            lines.append(f"| {track_names[track]} | {system} | {item['questions']} | {item['micro_evidence_recall']:.1%} | {item['complete_questions']}/{item['questions']} | {item['mean_context_tokens']:.0f} |")
    lines+=['','KG 조회의 정답은 저장된 RDF에 대한 별도 계산 결과다. 구조화 조회를 끈 대조군도 같은 텍스트 사실에 접근한다. 조회 표현·필터·경로 구성의 이득을 평가하며 신규 인과관계나 실제 설비 안전성을 증명하지 않는다.','',
        '### GraphRAG와 VectorRAG의 문항별 차이','',
        '| 문항 | 문항군 | VectorRAG 회수율 | GraphRAG 회수율 | 차이 |','|---|---|---:|---:|---:|']
    pairs=[]
    for qid,q in questions.items():
        budget=4000 if q['track']=='document_qa' else 8000
        vrow=next((r for r in rows if r['id']==qid and r['encoder_track']=='local_offline' and r['budget']==budget and r['system']=='VectorRAG'),None)
        grow=next((r for r in rows if r['id']==qid and r['encoder_track']=='local_offline' and r['budget']==budget and r['system']=='GraphRAG'),None)
        if vrow and grow:pairs.append({'id':qid,'track':q['track'],'vector':vrow['recall'],'graph':grow['recall'],'delta':grow['recall']-vrow['recall']})
    positives=sorted([r for r in pairs if r['delta']>0],key=lambda r:(-r['delta'],r['id']))[:4]
    negatives=sorted([r for r in pairs if r['delta']<0],key=lambda r:(r['delta'],r['id']))[:4]
    for row in positives+negatives:
        lines.append(f"| {row['id']} | {track_names.get(row['track'],row['track'])} | {row['vector']:.0%} | {row['graph']:.0%} | {row['delta']:+.0%}p |")
    lines += ['',f"102문항에서 GraphRAG의 회수율이 높은 문항 {sum(r['delta']>0 for r in pairs)}개, 같은 문항 {sum(r['delta']==0 for r in pairs)}개, 낮은 문항 {sum(r['delta']<0 for r in pairs)}개다. 같은 원문을 공유하는 문항이 있어 독립 표본의 통계적 우월성으로 해석하지 않는다.",'',
        '## 3. 대표 6문항의 저장 답변 검토','',
        '유형별로 미리 지정한 6문항의 기존 답변 18개를 원문과 대조했다. 새 생성과 별도 AI 채점 API를 사용하지 않았다. 과거 API 임베딩 검색으로 만든 답변이므로 이번 로컬 검색의 생성 정확도 점수로 합산하지 않는다.',
        '아래는 현재 AI 작성 에이전트의 정성 검토이며 독립 인간·전문가 검토 또는 전체 102문항 답변 정확도가 아니다.','',
        '| 문항 | 일반 LLM | VectorRAG | GraphRAG |','|---|---|---|---|']
    for item in review['questions']:
        verdicts=[item['observations'][s].replace('|','/') for s in ['LLM','VectorRAG','GraphRAG']]
        lines.append('| '+item['id']+' | '+' | '.join(verdicts)+' |')
    lines += ['',
        'G10에서는 GraphRAG가 SOP-003의 복구·QC·ERP HOLD 및 정비 조건을 더 완전하게 모았다. G13과 NEW-03에서는 두 RAG가 모두 요청을 충족했다. G06의 GraphRAG 추가 설명은 원문의 단순 나열을 실행 순서처럼 보이게 할 수 있어 주의사항으로 기록했다.',
        '일반 LLM의 적절한 유보를 허위 답변으로 취급하지 않는다. 다만 프로젝트 문서의 고유 규칙·수치·절차를 회수하지 못했다는 점과 일반적인 권고를 구분한다.','',
        '## 4. 범위·한계와 남은 입력','',
        '- 문항·정답은 AI 작성 및 원문 대조 초안이다. KG 문항 일부는 별도 결정적 조회 정답을 사용한다. 독립 전문가 정답 검증은 없다.',
        '- 개발에 이미 노출된 문항이다. 신규 공장·미공개 데이터에 대한 일반화 성능은 입증하지 않는다.',
        '- 필수 근거 ID 회수율은 정답표가 지정한 근거에 대한 지표다. 동등한 다른 근거를 모두 의미적으로 채점한 결과가 아니다.',
        '- 로컬 임베딩과 API 임베딩의 결과를 섞지 않는다. KG 8,000토큰과 문서 QA 4,000토큰을 같은 조건의 단일 평균으로 합치지 않는다.',
        '- 일반 LLM·VectorRAG·GraphRAG의 전체 답변 정확도 전수 비교는 실행하지 않았다. 저장 답변 검토 범위를 넘는 성능은 주장하지 않는다.',
        '- 사건·후보·시간 구간이 없는 26문항은 지표에서 제외하고 필요한 입력을 기록했다. 임의의 원인 점수·시차·구간을 만들지 않았다.',
        '- 12개 관련 기능 테스트가 통과했다. 오류 주입 2문항은 원본 KG를 보존한 복사본에서 기존 검증을 재현한 결과이며 새로운 발견이 아니다.','',
        '## 5. 결과 파일','',
        '- '+link(ROOT/'benchmark_catalog.py','전체 130문항 코드'),
        '- '+link(OUT/'문항별_검색비교.csv','문항별 검색 비교 CSV'),
        '- '+link(OUT/'검색성능_요약.csv','검색 성능 요약 CSV'),
        '- '+link(OUT/'대표6문항_답변검토.md','대표 문항의 답변·원문·검토'),
        '- '+link(ROOT/'runs/offline_budget_v1/retrieval_seal.json','검색 산출물 무결성 기록'),
        '- '+link(ROOT/'reports/fault_injection/results.json','오류 주입 검증 결과'),
        '- '+link(OUT/'전체문항_실행현황.csv','전체 문항 실행·대기 상태'),'',
        f"추가 API 응답 파일 수: 0개. 이전 저장 응답 수와 비교해 변화 없음({sum(api_counts.values())}개 유지). 로컬 모델·검색 실행의 네트워크 시도도 0회다. 과거 중단 요청의 실제 청구 여부는 이 결과로 확인할 수 없다."]
    (OUT/'검색성능_전체문항_비교보고서.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    status=[]
    for q in BENCHMARKS:
        status.append({'id':q['id'],'track':q['track'],'question':q['question'],
            'retrieval_status':'completed_local' if q['id'] in coverage['local_offline'] else
                'completed_fault_injection' if q['track']=='fault_injection' else 'pending_input',
            'cached_api_query':q['id'] in coverage['cached_api_document_only'],
            'representative_answer_review':q['id'] in {x['id'] for x in review['questions']},
            'pending_reason':q.get('pending_reason') or ''})
    with (OUT/'전체문항_실행현황.csv').open('w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(status[0]));writer.writeheader();writer.writerows(status)
    v.write(OUT/'completion.json',{'catalog_questions':len(BENCHMARKS),'retrieval_compared':len(coverage['local_offline']),
        'cached_api_compared':len(coverage['cached_api_document_only']),'fault_injection_questions':2,'pending_input':26,
        'representative_questions':6,'representative_saved_answers':18,'new_api_calls':0,'new_generation_calls':0,
        'new_judge_calls':0,'new_network_attempts':0,'api_response_counts_unchanged':unchanged,
        'graph_vs_vector_local':{'wins':sum(r['delta']>0 for r in pairs),'ties':sum(r['delta']==0 for r in pairs),'losses':sum(r['delta']<0 for r in pairs)},
        'scope_completed':'All executable retrieval questions plus cached representative review; no full-suite answer accuracy claim'})
    print(json.dumps(v.read(OUT/'completion.json'),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
