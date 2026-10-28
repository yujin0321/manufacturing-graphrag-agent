"""Aggregate sealed Agent v3 quality runs; no model calls."""
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


def aggregate(rows):
 return {'samples':len(rows),'mean':statistics.mean(r['total'] for r in rows),
  'strict_correct':sum(bool(r['strict_correct']) for r in rows),
  'content_points':sum(sum(r['content']) for r in rows),
  'evidence_points':sum(r.get('evidence_score',0) for r in rows),
  'faithful':sum(r['faithfulness'] for r in rows),
  'statuses':dict(Counter(r['status'] for r in rows))}


def summarize(run,review,audit,out):
 run,review,audit,out = (p.resolve() for p in (run,review,audit,out))
 verify(run)
 for folder,sealname in [(review,'review_seal.json'),(audit,'seal.json')]:
  for name,digest in v.read(folder/sealname)['files'].items():
   if v.digest((folder/name).read_bytes())!=digest: raise ValueError('Seal mismatch: '+name)
 initial=v.read(review/'grades.json');final=v.read(audit/'final_grades.json');audits=v.read(audit/'audits.json')
 if len(final)!=45 or any(r['pending'] for r in final): raise ValueError('Incomplete or pending final grades')
 observations=v.read(run/'observations.json')
 data={'version':'agent-v3-quality-20261028-report-v1','initial':aggregate(initial),'final':aggregate(final),
  'per_repeat':{str(k):aggregate([r for r in final if r['repeat']==k]) for k in (1,2,3)},
  'per_category':{name:aggregate([r for r in final if r['category']==name]) for name in sorted({r['category'] for r in final})},
  'per_question':{qid:{'scores':[r['total'] for r in sorted(final,key=lambda r:r['repeat']) if r['qid']==qid],
    'routes':[r['route'] for r in sorted(final,key=lambda r:r['repeat']) if r['qid']==qid],
    **aggregate([r for r in final if r['qid']==qid])} for qid in sorted({r['qid'] for r in final})},
  'audit_changes':[{'qid':r['qid'],'repeat':r['repeat'],'before':r['initial_faithfulness'],'after':r['faithfulness'],'reason':r['reason']} for r in audits if r['faithfulness']!=r['initial_faithfulness']],
  'latency_seconds':{'all_median':statistics.median(o['seconds'] for o in observations),
   'complete_median':statistics.median(o['seconds'] for o in observations if o['status']=='complete'),
   'min':min(o['seconds'] for o in observations),'max':max(o['seconds'] for o in observations)}}
 phases={'generation':[],'initial_review':[],'faithfulness_audit':[]}
 for obs in observations:
  phases['generation'].extend(v.read(run/obs['path']/'answer.json')['usage'])
 for r in initial:
  if r.get('review_usage'):phases['initial_review'].append(r['review_usage'])
 phases['faithfulness_audit']=[{'usage':r['usage'],'transport':r['transport']} for r in audits]
 data['token_usage']={}
 for name,items in phases.items():
  data['token_usage'][name]={'requests':len(items),'prompt_tokens':sum(i.get('usage',{}).get('prompt_tokens',0) for i in items),
   'completion_tokens':sum(i.get('usage',{}).get('completion_tokens',0) for i in items),
   'cached_prompt_tokens':sum(i.get('usage',{}).get('prompt_tokens_details',{}).get('cached_tokens',0) for i in items)}
 out.mkdir(parents=True,exist_ok=False)
 v.write(out/'summary.json',data)
 lines=['# Agent v3 실제 품질 평가 — 2026-10-28','',
 '새 15문항을 각 3회 실행한 45개 표본이다. 현재 기본 BM25+graph_v3 Agent를 실제 모델 gpt-6.1-sol로 평가했다. dense 인덱스는 사용하지 않았다.',
 '생성 결과 전체를 봉인한 뒤 별도 프로세스에서 PRIVATE 정답을 읽었다. 평가 도중 검색·Agent·질문·정답·배점은 바꾸지 않았다.','',
 '## 결과','',
 '| 항목 | 결과 |','|---|---:|',
 f"| 최종 AI 평가 평균 | {data['final']['mean']:.3f}/5 |",
 f"| 최초 AI 평가 평균 | {data['initial']['mean']:.3f}/5 |",
 f"| 최종 완전 정답 | {data['final']['strict_correct']}/45 |",
 '| 답변 생성 완료 | 39/45 (86.7%) |','| 추가 설명 요청 | 3/45 |','| 답변 유보 | 3/45 |','| 기술적 실행 실패 | 0/45 |','| 판정보류 | 0/45 |','',
 '완료/유보는 실행 상태이고 정답 여부가 아니다. 45개는 15개 고유 질문의 반복이므로 독립 질문 45개로 해석하지 않는다.','',
 '## 문항별 점수와 라우팅','', '| 문항 | 1회 | 2회 | 3회 | 평균 | 라우팅 1/2/3회 |','|---|---:|---:|---:|---:|---|']
 for qid,r in data['per_question'].items():
  lines.append(f"| {qid} | {r['scores'][0]:.2f} | {r['scores'][1]:.2f} | {r['scores'][2]:.2f} | {r['mean']:.2f} | {' / '.join(r['routes'])} |")
 lines+=['','## 반복과 유형','', '| 반복 | 평균 /5 | 완전 정답 |','|---|---:|---:|']
 for k,r in data['per_repeat'].items():lines.append(f"| {k} | {r['mean']:.3f} | {r['strict_correct']}/{r['samples']} |")
 lines+=['','| 유형 | 평균 /5 | 완전 정답 |','|---|---:|---:|']
 for k,r in data['per_category'].items():lines.append(f"| {k} | {r['mean']:.3f} | {r['strict_correct']}/{r['samples']} |")
 lines+=['','## 채점 재검토 이력','',
 '기존 내용3+근거1+충실성1 기준을 유지했다. 최초 AI 채점에는 실제 검색 컨텍스트가 없어서 발췌 범위의 한계 설명과 전체 문서 부재 단정을 구분하기 어려웠다.',
 '점수 결과를 본 뒤 이 입력 부족을 발견했다. 최초 판정은 보존하고 모든 완료 답변 39개(최초 충실성 0과 1 모두)에 실제 생성 컨텍스트를 추가하여 충실성만 대칭적으로 재검토했다.',
 '필수 내용/근거 점수는 변경하지 않았다. 이 재검토는 사후 절차이므로 최초 점수도 함께 공개한다. 독립 인간 검토나 완전한 맹검이 아니다.','',
 f"변경된 충실성 판정: {len(data['audit_changes'])}건. 아래 변경은 최초→재검토 값이다.",'']
 for r in data['audit_changes']:lines.append(f"- {r['qid']} {r['repeat']}회: {r['before']}→{r['after']}. {r['reason']}")
 lines+=['','## 주요 문제와 다음 수정 방향','',
 '- 라우팅: G09는 document/clarify/document, G10은 clarify/document/clarify, G11은 unavailable 3회다. 사용자가 제공한 상황값에 문서 규칙을 적용하는 질문과 실제 실시간 조회를 구분하는 라우팅 개선이 우선이다.',
 '- 집계 검색: G01은 전체 CRITICAL 정비 규칙을 묻는다. 엔티티 시작 탐색만으로 전체 목록을 보장할 수 없으므로 속성 필터/구조 질의가 필요하다.',
 '- 정의표 회수: G14의 이상 유형 정의와 G08의 STUCK 정의 근거가 검색에서 빠지는 문제가 있다. 검색 누락과 생성 해석 오류를 분리해 보아야 한다.',
 '- G12에서는 센서 데이터시트의 사양과 실제 설치 모델의 확인을 구분해야 한다. 센서 정격 이내라는 설명을 실제 장착 모델 확인 없이 단정하는지 검토해야 한다.',
 '- 기존 이벤트 설명용 답변 지침을 문서 질문에도 공유하여 후보 ID/최초 판정 등 불필요한 내용을 덧붙이는 경향이 있다. 후속 버전에서 문서 QA 지침과 후보 설명 지침을 분리할 가치가 있다.',
 '이번 평가 결과를 본 뒤 기존 평가를 덮어쓰거나 Agent를 튜닝하지 않았다. 후속 수정은 새 버전과 별도 평가로 남겨야 한다.','',
 '## 토큰 및 시간','', '| 단계 | 요청 | 입력 토큰 | 출력 토큰 | 캐시 입력 토큰 |','|---|---:|---:|---:|---:|']
 for k,r in data['token_usage'].items():lines.append(f"| {k} | {r['requests']} | {r['prompt_tokens']:,} | {r['completion_tokens']:,} | {r['cached_prompt_tokens']:,} |")
 lines += ['',f"답변 완료 건의 Agent 실행 중앙값: {data['latency_seconds']['complete_median']:.2f}초. 전체 시도 범위: {data['latency_seconds']['min']:.2f}~{data['latency_seconds']['max']:.2f}초.",
 '토큰은 해당 평가 API 응답의 usage 합계다. 앞선 인증 실패·별도 진단 요청은 이 표에서 제외한다. 실제 달러 청구액으로 환산하지 않았다. 다른 방식과 속도/비용 우열을 비교한 실험이 아니다.','',
 '## 한계','',
 '- 생성과 두 채점 단계가 같은 모델 계열의 AI 평가다. 사람 교차 채점은 수행하지 않았다.',
 '- 문서/별칭 사전/문항의 개발 노출이 있는 15문항이다. 독립 미노출 일반화 성능이 아니다.',
 '- 최초 충실성 판정과 재검토에 차이가 있다. 총점뿐 아니라 최초 점수와 판정 이유를 함께 검토해야 한다.',
 '- 유진/예원, dense/비dense, Vector/Graph의 직접 성능 우열을 증명하는 비교가 아니다.',
 '- 과거 후보 목록/설명 경로 및 실제 탐지 성능을 평가한 결과가 아니다. 실제 설비 운전 허가·안전성 인증도 아니다.','',
 '## 산출물','',
 f'- 생성/봉인: `{run.relative_to(ROOT)}`',f'- 최초 채점/봉인: `{review.relative_to(ROOT)}`',f'- 충실성 재검토/최종 판정: `{audit.relative_to(ROOT)}`',
 '원본 답변·요청·응답·샘플별 채점 사유와 해시를 보존했다. PRIVATE 정답과 비밀 키는 보고서에 복사하지 않았다.']
 (out/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print(json.dumps({'initial':data['initial'],'final':data['final'],'audit_changes':len(data['audit_changes']),'token_usage':data['token_usage']},ensure_ascii=False))

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('run','review','audit','out'):p.add_argument('--'+name,type=Path,required=True)
 a=p.parse_args();summarize(a.run,a.review,a.audit,a.out)
