"""Aggregate final v4.1 regression and one-factor retrieval ablation, no API calls."""
import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'scripts'))
from imaks_kg.rag import vector as v
from grade_agent_v3_quality import verify
from summarize_agent_v3_quality import aggregate


def report(run,review,audit,ablation,out):
 run,review,audit,ablation,out=(p.resolve() for p in (run,review,audit,ablation,out))
 verify(run)
 for directory,filename in [(review,'review_seal.json'),(audit,'seal.json'),(ablation,'seal.json')]:
  for name,digest in v.read(directory/filename)['files'].items():
   if v.digest((directory/name).read_bytes())!=digest:raise ValueError('Artifact changed after sealing: '+name)
 initial=v.read(review/'grades.json');final=v.read(audit/'final_grades.json');audits=v.read(audit/'audits.json')
 prior_audit=run.parent/(run.name+'_audit')
 prior_audits=v.read(prior_audit/'audits.json') if (prior_audit/'audits.json').exists() and prior_audit!=audit else []
 prior_grades=v.read(prior_audit/'final_grades.json') if prior_audits else []
 if len(final)!=45 or any(r['pending'] for r in final):raise ValueError('Incomplete or unresolved evaluation')
 baseline=v.read(ROOT/'docs/graphrag_v3/agent_v3_quality_summary_20261028.json')
 search=v.read(ablation/'grade_summary.json')
 observations=v.read(run/'observations.json')
 answers=[v.read(run/o['path']/'answer.json') for o in observations]
 result={'version':'agent-v4.1-regression-report-20261028','initial':aggregate(initial),'final':aggregate(final),
  'baseline_v3':baseline['final'],'baseline_v3_initial':baseline['initial'],
  'per_repeat':{str(k):aggregate([r for r in final if r['repeat']==k]) for k in (1,2,3)},
  'per_question':{qid:{'scores':[r['total'] for r in sorted(final,key=lambda r:r['repeat']) if r['qid']==qid],
    **aggregate([r for r in final if r['qid']==qid])} for qid in sorted({r['qid'] for r in final})},
  'per_category':{cat:aggregate([r for r in final if r['category']==cat]) for cat in sorted({r['category'] for r in final})},
  'document_routes':sum(o['route']=='document' for o in observations),
  'declared_answer_complete':dict(Counter(str(a.get('answer_complete')) for a in answers)),
  'search_count':dict(Counter(str(a.get('search_count',0)) for a in answers)),
  'verification_count':dict(Counter(str(len(a.get('verification',[]))) for a in answers)),
  'audit_changes':[{'qid':a['qid'],'repeat':a['repeat'],'before':a['initial_faithfulness'],'after':a['faithfulness'],'reason':a['reason']} for a in audits if a['faithfulness']!=a['initial_faithfulness']],
  'retrieval_ablation':search,
  'latency_seconds':{'median':statistics.median(o['seconds'] for o in observations),'min':min(o['seconds'] for o in observations),'max':max(o['seconds'] for o in observations)}}
 phases={'generation':[u for answer in answers for u in answer['usage']],
  'grading':[r['review_usage'] for r in initial if r.get('review_usage')],
  'audit':[{'usage':r['usage'],'transport':r['transport']} for r in audits]}
 if prior_audits:
  phases['context_only_audit']=[{'usage':r['usage'],'transport':r['transport']} for r in prior_audits]
  result['context_only_audit']=aggregate(prior_grades)
 result['api_usage']={}
 for name,items in phases.items():
  live=[u for u in items if not u.get('transport',{}).get('cache_hit',False) or u.get('transport',{}).get('original_request_counted',False)]
  result['api_usage'][name]={'new_requests':len(live),'local_cache_reuses':len(items)-len(live),
   'prompt_tokens':sum(u.get('usage',{}).get('prompt_tokens',0) for u in live),
   'completion_tokens':sum(u.get('usage',{}).get('completion_tokens',0) for u in live),
   'provider_cached_prompt_tokens':sum(u.get('usage',{}).get('prompt_tokens_details',{}).get('cached_tokens',0) for u in live)}
 out.mkdir(parents=True,exist_ok=False);v.write(out/'summary.json',result)
 f=result['final'];b=result['baseline_v3'];i=result['initial']
 lines=['# Agent v4.1 개선·개발 회귀 평가 — 2026-10-28','',
 '기존 실패 분석을 반영한 개선판이다. 질문·정답·채점 기준과 이전 v3 결과를 보존했다. 이번 15문항은 이미 본 개발 회귀 집합이며 미노출 일반화 평가가 아니다.',
 '15문항을 각 3회, 총45회 실제 실행했다. 기본 비교 대상은 이전 v3(BM25) 결과이고 최종판은 dense+유형별 검색+새 라우팅/지침/검증을 사용한다.',
 '여러 요소가 함께 바뀐 QA 점수 차이를 그래프 고유 효과나 특정 한 요소의 효과라고 해석하지 않는다.','',
 '## 최종 결과','', '| 항목 | 이전 v3 | 개선 v4.1 |','|---|---:|---:|',
 f"| 최초 AI 평균 /5 | {result['baseline_v3_initial']['mean']:.3f} | {i['mean']:.3f} |",
 f"| 충실성 재검토 후 AI 평균 /5 | {b['mean']:.3f} | {f['mean']:.3f} |",
 f"| 완전 정답 | {b['strict_correct']}/45 | {f['strict_correct']}/45 |",
 f"| 실행 상태 | {b['statuses']} | {f['statuses']} |",
 f"| 문서 질문 라우팅 | 39/45 | {result['document_routes']}/45 |",'',
 '완료는 실행 상태이며 모든 질문 요구의 충족을 뜻하지 않는다. answer_complete는 별도 모델 검증 플래그이며 공식 QA 점수를 대체하지 않는다.',
 f"검증기의 answer_complete 분포: {result['declared_answer_complete']}.",
 '동일 모델 gpt-6.1-sol로 실제 생성 및 별도 AI 채점을 수행했다. 사람 교차 채점은 수행하지 않았다.','',
 '## 문항별 점수','', '| 문항 | 이전 평균 | 개선 1회 | 2회 | 3회 | 개선 평균 |','|---|---:|---:|---:|---:|---:|']
 for qid,row in result['per_question'].items():
  old=baseline['per_question'][qid]['mean'];scores=row['scores']
  lines.append(f"| {qid} | {old:.2f} | {scores[0]:.2f} | {scores[1]:.2f} | {scores[2]:.2f} | {row['mean']:.2f} |")
 lines+=['','| 반복 | 평균 /5 | 완전 정답 |','|---|---:|---:|']
 for k,row in result['per_repeat'].items():lines.append(f"| {k} | {row['mean']:.3f} | {row['strict_correct']}/{row['samples']} |")
 lines+=['','## 남은 내용 누락','']
 for qid in sorted({row['qid'] for row in final if row['total']<5}):
  misses=[row for row in final if row['qid']==qid and row['total']<5]
  reason=next((reason for row in misses for score,reason in zip(row['content'],row.get('content_reasons',[])) if score==0),'상세 판정 참조')
  lines.append(f"- {qid}: {len(misses)}/3회 감점. {reason}")
 lines+=['','## 한 요소씩 분리한 검색 비교','', '| 설정 | 필수 행 근거 | 근거 완비 문항 | 평균 원문+카드 토큰 |','|---|---:|---:|---:|']
 for name,row in search.items():lines.append(f"| {name} | {row['found']}/{row['needed']} | {row['complete_questions']}/15 | {row['mean_context_tokens']:.1f} |")
 lines += ['',
 '- bm25_v3 → hybrid_v3는 dense 추가만 다르다. hybrid_v3 → hybrid_typed_v4는 유형별 후보 우선순위만 다르다. 같은 문항·KG·행 청크·후보 상한·토큰 예산을 사용했다.',
 '- 최초 행 임베딩은 실제 9345토큰이었다. 기존 원문과 KG는 변경하지 않았다. 질의 캐시는 재사용했다.',
 '- 검색 결과를 봉인한 뒤 별도 채점 단계에서 PRIVATE 정답과 대조했다. 근거 회수율은 답변 정확도가 아니다.','',
 '## 구현한 변경','',
 '1. 값이 주어진 상황 질문과 실제 조회/제어 요청을 구분. 명확한 문서/상황은 결정적 분류, 모호한 경우 모델 분류.',
 '2. 문서 답변 지침과 과거 후보 설명 지침 분리. 숫자·단위·부등호·시간·조치의 행 인용을 명시.',
 '3. 원 질문 dense + BM25 RRF를 사용. dense 활성화는 명시 선택이며 인덱스를 자동으로 다시 구축하지 않음.',
 '4. KG priority 필터와 원문 정의표/역할 시간 열 조회. 엔티티 범위를 제한하고 전체 동률을 보존.',
 '5. 인용 ID 결정적 검사와 별도 모델 검증, 최대1회 재검색·초안2회·검증2회. 불명확한 입력은 무제한 재시도하지 않음.',
 '6. 전체 검색 완전성 미확인과 원문 왜곡을 구분. 지원되는 부분 답변에는 범위를 밝히고 answer_complete=false를 기록할 수 있음.','',
 '## 중간 버전 및 채점 이력','',
 '중간 v4는 45회 중42회 답변을 반환하고 서버실 전체 문서 질문을3회 과잉 보류했다. 검증기가 전체 검색의 완전성 미확인을 근거 오류로 취급한 것이 원인이었다.',
 '이 실행을 덮어쓰지 않고 v4.1에서 unknown coverage를 null로 표시하고 근거 충실성/답변 완전성을 분리했다. v4.1은45회를 새로 실행했으며 중간 버전 답변 중 좋은 것만 선택하지 않았다.',
 '최초 채점과 실제 생성 컨텍스트를 포함한 충실성 재검토를 이전 v3와 같은 방법으로 수행했다. 내용·근거 배점은 고정했고 재검토는 완료 답변 전체에 대칭 적용했다.',
 f"앱 조회 메타데이터가 빠졌던 1차 충실성 검토 평균은 {result.get('context_only_audit',result['initial'])['mean']:.3f}/5다. 해당 누락을 확인한 뒤 실제 초안의 조회 메타데이터까지 포함해 완료 답변 전체45개를 동일 기준으로 다시 검토했고 앞선 판정도 보존했다. 점수 기준이나 내용/근거 배점은 바꾸지 않았다.\n이번 충실성 변경 {len(result['audit_changes'])}건. 최초/재검토 점수를 모두 보존했다. AI 채점의 주관성과 동일 모델 편향이 남아 있다.",'',
 '## 실행량과 한도','',f"검색 횟수 분포: {result['search_count']}; 검증 횟수 분포: {result['verification_count']}.",
 f"Agent 실행 시간 중앙값 {result['latency_seconds']['median']:.2f}초, 범위 {result['latency_seconds']['min']:.2f}~{result['latency_seconds']['max']:.2f}초.",
 '다른 날짜·캐시·구성이므로 이전 버전 대비 속도 우위를 주장하지 않는다.','',
 '| 단계 | 신규 API 요청 | 로컬 응답 캐시 재사용 | 입력 토큰 | 출력 토큰 |','|---|---:|---:|---:|---:|']
 for name,row in result['api_usage'].items():lines.append(f"| {name} | {row['new_requests']} | {row['local_cache_reuses']} | {row['prompt_tokens']:,} | {row['completion_tokens']:,} |")
 lines += ['',
 '이 표는 최종 v4.1 실행/채점/재검토만 포함한다. 중간 v4, 최초 인덱스/검색 대조 실험 및 과거 인증 진단은 별도 기록이다. 캐시의 과거 사용량은 신규 청구량에 중복 합산하지 않았다. 실제 달러 청구액으로 환산하지 않았다.','',
 '## 한계와 후속 검증','',
 '- 기존15문항을 본 뒤 개선한 결과다. 새 문항과 독립 사람 검토 없이 일반화 성능이나 현장 안정성을 확정할 수 없다.',
 '- 답변 전 검증 모델도 오류가 있을 수 있다. 검증기 승인과 QA 채점은 서로 다른 관찰이다.',
 '- KG priority 구조 조회는 RDF/문서 구조 기반이다. 자연어→Cypher 전체 기능을 구현했다고 주장하지 않는다.',
 '- 과거 후보 도구는 기존 탐지 저장소를 재사용한다. 실제 센서·제어 연결이나 KG 탐지기 v2 후보 통합은 이번 범위가 아니다.',
 '- 기존 v1/v2/v3·정책·문항·정답·점수 파일을 변경하지 않았다.','',
 '## 원본 기록','',f'- 최종 생성: `{run.relative_to(ROOT)}`',f'- 최초 채점: `{review.relative_to(ROOT)}`',f'- 충실성 재검토: `{audit.relative_to(ROOT)}`',
 f'- 검색 대조: `{ablation.relative_to(ROOT)}`','각 원본은 해시 봉인되어 있다. PRIVATE 정답과 API 키는 보고서/커밋에 복사하지 않았다.']
 (out/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print(json.dumps({'baseline':b,'initial':i,'final':f,'document_routes':result['document_routes'],'audited_changes':len(result['audit_changes'])},ensure_ascii=False))

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('run','review','audit','ablation','out'):p.add_argument('--'+n,type=Path,required=True)
 a=p.parse_args();report(a.run,a.review,a.audit,a.ablation,a.out)
