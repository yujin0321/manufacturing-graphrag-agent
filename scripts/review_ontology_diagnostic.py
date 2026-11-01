"""Post-generation integrity checks and explicit AI review record, not auto-grading."""
import json
from imaks_kg.rag import vector as v

NOTES={
'OD-01':'명령 없는 SPD<1.00, ST04-03→ST02-04, CUR WARNING 시 SPD 모니터링을 구분. 추가 SOP-002 수치도 검색 원문과 대조함.',
'OD-02':'SOP-001 범위에서 역참조 규칙과 방향을 식별. 공동 출현과 SOP-002 별도 참조를 제외함.',
'OD-03':'25°C/300초 경계 미충족, 330초 충족. 문서상 냉각 조치와 실제 실행을 구분함.',
'OD-04':'I>N+1.5 A와 >5분을 보존. 실제 명목값을 임의 대입하지 않음.',
'OD-05':'10개 미충족/11개 충족, 10간격=300초. SOP-003에 수치 허용오차가 없다는 범위와 별도 SOP-002 표6의 표준편차 기준을 구분함.',
'OD-06':'TMP 조건과 세 대상 공정 actionTarget을 구분. 실제 정지 실행은 미확인으로 처리함.',
'OD-07':'45/47/50%에서 가동 조건과 상한 위반을 정확히 구분. 가동 미충족을 정지 명령으로 해석하지 않음.',
'OD-08':'현재 온도와 냉각 실가동은 확인 불가라는 내용은 적절함. 그러나 응답이 일본어여서 고정 system 지침의 한국어 요구를 위반함. 창고 KG 카드 혼입도 검색 관련성 관찰로 기록하되 원인으로 확정하지 않음.'}

def main():
 root=v.REPO_ROOT;out=root/'evaluation/ontology_diagnostic_20261027';runs=root/'kg_build/ontology_diagnostic_20261027'
 lock=v.read(out/'pre_run_lock.json');rubric_path=out/'rubric_PRIVATE.json'
 assert v.digest(rubric_path.read_bytes())==lock['rubric_sha256']
 rubric={r['id']:r for r in v.read(rubric_path)}
 questions=v.read(root/'docs/ontology_diagnostic_20261027/questions.json')
 complete=v.read(runs/'complete.json');assert complete['questions']==8
 sealed={r['id']:r for r in complete['runs']}
 common=(root/'docs/vector_rag_v1/answer_instructions.txt').read_text(encoding='utf-8')
 rows=[]
 for q in questions:
  ident=q['id'];p=runs/ident;a=v.read(p/'answer.json');r=v.read(p/'retrieval.json')
  assert v.digest((p/'answer.json').read_bytes())==sealed[ident]['answer_sha256']
  assert v.digest((p/'retrieval.json').read_bytes())==sealed[ident]['retrieval_sha256']
  requests=list((p/'api').glob('*.request.json'));assert len(requests)==1
  payload=v.read(requests[0]);messages=payload['messages']
  assert len(messages)==2 and messages[0]=={'role':'system','content':common}
  assert messages[1]['role']=='user'
  assert json.loads(messages[1]['content'])=={'question':q['question'],'untrusted_reference_documents':r['context']}
  expected=rubric[ident]['evidence'];missing=[e['chunk_id'] for e in expected if e['chunk_id'] not in r['selected_ids']]
  for e in expected:
   if e['chunk_id'] not in missing:
    source=next(s for s in a['retrieved_sources'] if s['chunk_id']==e['chunk_id'])
    assert source['text_sha256']==e['chunk_sha256'] and e['quote'] in source['text']
  rows.append({'id':ident,'expected_source_count':len(expected),'missing_sources':missing,
     'content_review':'no discrepancy found in required content','language_instruction':'fail' if ident=='OD-08' else 'pass',
     'primary_failure_cause':'generation_language_instruction' if ident=='OD-08' else 'none_observed',
     'ontology_failure_demonstrated':False,'review_note':NOTES[ident],
     'usage':a['usage'],'embedding_usage':a['embedding_api'].get('usage',{}),
     'context_tokens':r['context_tokens'],'traversed_edge_kinds':sorted({e['kind'] for e in r['traversed_edges']}),
     'answer_sha256':sealed[ident]['answer_sha256'],'retrieval_sha256':sealed[ident]['retrieval_sha256']})
 summary={'review_type':'AI single nonblind development source review; explicit judgments, not automatic semantic scoring',
    'questions':8,'source_units_expected':sum(r['expected_source_count'] for r in rows),
    'source_units_missing':sum(len(r['missing_sources']) for r in rows),
    'content_discrepancies_identified':0,'language_instruction_failures':1,'ontology_failure_demonstrated':False,
    'generation_tokens':sum(r['usage']['total_tokens'] for r in rows),
    'embedding_tokens':sum(r['embedding_usage'].get('total_tokens',0) for r in rows),
    'no_regeneration':True,'request_payload_verified':True,'original_rubric_unchanged':True,
    'language_review_basis':'pre-existing frozen system prompt; separate from original content rubric',
    'benchmark_accuracy_claim':False,'rows':rows}
 v.write(out/'review_PRIVATE.json',summary)
 print(json.dumps({k:x for k,x in summary.items() if k!='rows'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
