"""Offline qualitative review of six predeclared cases; no new model calls."""
from pathlib import Path
from collections import Counter
import json
import re
import sys
ROOT=Path(__file__).resolve().parent
REPO=ROOT.parent.parent
sys.path.insert(0,str(REPO/'src'))
from imaks_kg.rag import vector as v,retrieval_v3 as r3
from benchmark_catalog import BENCHMARKS

# These are authoring-agent judgments after reading the saved answers and source
# rows, not automatic scores or independent human/domain-expert certification.
JUDGMENTS={
 'G02':{'LLM':'미충족: 원문이 없어 규칙·수치를 제시하지 못함',
         'VectorRAG':'핵심 충족: 운영·임계값·정비의 세 문서 내용을 모두 연결',
         'GraphRAG':'핵심 충족: 세 문서와 관련 역방향 확인 규칙·해소 절차까지 제시',
         'finding':'이 사례는 두 RAG 모두 필수 내용을 회수했다. 추가 설명이 많다는 이유만으로 그래프의 우월성을 채점하지 않는다.'},
 'G06':{'LLM':'미충족: 규칙 참조와 해소 절차를 특정하지 못함',
         'VectorRAG':'핵심 충족: ST04 규칙→ST02 규칙→전류 센서 및 해소 3단계',
         'GraphRAG':'핵심 충족, 추가 표현 점검 필요: 같은 참조·절차를 답했으나 별도 CRITICAL 대응을 화살표로 나열',
         'finding':'GraphRAG의 추가 E-STOP→부하 점검→SPD 확인 표현은 원문 세미콜론 나열을 실행 순서로 오해시킬 수 있다. 원문에 순서가 명시된 해소 3단계와 구분해 수정할 여지가 있다. 생성 결과는 덮어쓰지 않는다.'},
 'G10':{'LLM':'문서 고유 요구 미충족: 일반적인 대응과 품질평가 안내를 제공',
         'VectorRAG':'일부 충족: 온도 범위·경고/위험 구분은 맞지만 SOP-003의 <8°C 복구·ERP HOLD와 MAINT-06 누락',
         'GraphRAG':'핵심 충족: 운영 기준, SOP-003 복구·QC·ERP HOLD, 조건부 정비를 구분',
         'finding':'여러 문서의 절차를 모아야 하는 현장 질문에서 저장된 GraphRAG 답변이 더 완전했다. 실제 제품 품질·운전 허가를 입증한 결과는 아니다.'},
 'G13':{'LLM':'미충족: 역할별 값을 알 수 없다고 답함',
         'VectorRAG':'요청 충족: supervisor 1분, manager/security 공동 5분과 정확한 표 행 인용',
         'GraphRAG':'요청 충족: 동일한 최소·공동 최댓값과 표 행 인용',
         'finding':'한 표 안의 비교에서는 두 RAG가 같은 답을 냈다. 질문에 명시되지 않은 추가 설명을 임의의 필수 조건으로 만들어 감점하지 않는다.'},
 'NEW-03':{'LLM':'일부 충족: 206~212°C는 계산했지만 규칙의 임계값을 몰라 조건 판정 유보',
            'VectorRAG':'핵심 충족: >210°C, 구간이 경계를 걸침, 명목 209°C의 판정을 구분',
            'GraphRAG':'핵심 충족: 동일한 구간·부등호·조건부 판정',
            'finding':'외부 규칙이 필요한 계산 문항에서는 두 RAG가 모두 성공했다. 단순 계산만으로 그래프가 필수라고 주장하지 않는다.'},
 'NEW-10':{'LLM':'일부 충족: 결측을 임의로 연결하면 안 된다고 설명했지만 MAINT-03 원문 조건은 확인 불가',
            'VectorRAG':'핵심 충족: MAINT-03과 다른 문서의 consecutive 정의를 분리하고 결측 정책을 가정으로 표시',
            'GraphRAG':'핵심 충족: MAINT-03에 없는 연속·결측 정책을 만들지 않음; SOP-001의 별도 연속 조건 인용',
            'finding':'두 답변 모두 원문과 추가 결측 정책을 구분한다. GraphRAG가 SOP-002 행 대신 SOP-001의 동등한 연속 조건을 인용한 점은 대체 근거로 기록한다.'}
}

def main():
    selection=v.read(ROOT/'experiment/representative_offline_selection.json')
    questions={q['id']:q for q in BENCHMARKS}
    keys={q['id']:q for q in v.read(ROOT/'evaluation/v5/answer_key.json')['questions']}
    originals={r['chunk_id']:r for r in v.source_records()[0]+r3.row_corpus()}
    out=ROOT/'reports/offline_budget_v1';out.mkdir(parents=True,exist_ok=True)
    review=[];appendix=['# 대표 문항의 저장 답변·원문 검토','',
        '검토자: 현재 AI 작성 에이전트. 별도 모델 채점 API와 독립 인간·도메인 전문가 검토는 사용하지 않았다.',
        '6문항은 답변 본문을 열기 전 유형별로 지정했다. 과거 API 임베딩 검색으로 생성한 저장 답변이며, 이번 로컬 임베딩 검색의 생성 성능으로 해석하지 않는다.',
        '전수 정확도나 5점 총점을 산출하지 않고 원문 대조 관찰만 기록한다. 새 생성 0회, 새 채점 호출 0회.','']
    for selected in selection['questions']:
        qid=selected['id'];entry={'id':qid,'question':questions[qid]['question'],'reason':selected['reason'],
            'observations':JUDGMENTS[qid],'systems':{}}
        appendix += [f'## {qid}', '',questions[qid]['question'],'']
        for system,meta in selected['answers'].items():
            path=Path(meta['path'])
            if not path.is_absolute():path=ROOT.parent/path
            if v.digest(path.read_bytes())!=meta['sha256']:raise ValueError('Saved selected answer changed')
            answer=v.read(path)
            cited=re.findall(r'\[([^\]\n]+)\]',answer['answer'])
            source_ids=[cid for cid in cited if cid in originals]
            fabricated=[cid for cid in cited if re.match(r'(?:SOP-\d+|DS-[A-Z]+-\d+):',cid) and cid not in originals]
            missing=sorted(set(keys[qid]['evidence'])-set(source_ids))
            entry['systems'][system]={'verdict':JUDGMENTS[qid][system],'answer_path':str(path),
                'answer_sha256':meta['sha256'],'cited_source_ids':source_ids,'nonexistent_citations':fabricated,
                'uncited_required_ids_before_semantic_alternatives':missing,
                'caveat':'Citation ID existence is checked automatically; substantive support and alternative evidence are reviewed qualitatively.'}
            appendix += [f'### {system}','','검토: '+JUDGMENTS[qid][system],'',answer['answer'],'']
        appendix += ['관찰: '+JUDGMENTS[qid]['finding'],'','### 필수 원문 근거','']
        for cid in keys[qid]['evidence']:
            appendix += [f'**{cid}**','',originals[cid]['text'],'']
        review.append(entry)
    v.write(out/'representative_review.json',{'questions':review,'new_generation_calls':0,'new_judge_calls':0,
        'reviewer':'Current authoring AI; qualitative source comparison, not independent evaluation',
        'not_full_suite_answer_accuracy':True,'historical_generation_encoder':'text-embedding-3-small'})
    (out/'대표6문항_답변검토.md').write_text('\n'.join(appendix)+'\n',encoding='utf-8')
    print(json.dumps({'reviewed_questions':len(review),'reviewed_saved_answers':sum(len(q['systems']) for q in review),
                      'new_api_calls':0,'nonexistent_citations':sum(len(x['nonexistent_citations']) for q in review for x in q['systems'].values())},ensure_ascii=False))

if __name__=='__main__':main()
