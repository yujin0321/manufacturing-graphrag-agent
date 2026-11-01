# Agent v4.1

현재 개선 경로는 agent_v4_1.py다. v3 및 중간 v4 실행/평가 기록은 보존한다.
이 버전은 기존 15문항의 실패 분석을 반영한 개발 버전이며 새 미노출 성능으로 표시하지 않는다.

## 변경 순서

1. 질문 분류: 사용자 제공 수치에 문서 규칙을 적용하는 질문과 실제 센서 조회/제어 요청을 구분한다. 명확한 경우 결정적 분류, 나머지는 제한된 모델 분류를 사용한다.
2. 답변 지침: 문서 QA와 과거 이벤트 설명 지침을 분리한다. 문서 질문에 후보 ID/최초 판정 시각을 만들어내지 않는다.
3. dense: 기존 행 청크를 1회 임베딩하고 원 질문의 dense 순위를 BM25와 RRF 결합한다. 같은 데이터에서 dense 유무만 바꿔 검색 효과를 측정했다.
4. 유형별 검색: 정비 우선순위는 실제 KG priority 필터와 문서 행으로, 이상 유형 정의와 역할별 확인 시간은 원문의 열 구조로 조회한다. 질문 ID/정답표/하드코딩 임계값은 사용하지 않는다. 자연어→Cypher 구현이라고 주장하지 않는다(RDF/원문 구조 조회다).
5. 근거 점검: 초안 인용 ID를 결정적으로 확인하고 별도 모델이 원문과 대조한다. 최대 1회 추가 검색, 초안 2회, 검증 2회다.
6. 검증 보완: 전체 코퍼스 완전성 미확인(null)과 근거 충실성 오류를 구분한다. 근거가 맞는 부분 답변은 범위·한계를 밝히고 반환하며 answer_complete=false로 기록할 수 있다. 전체 검색을 입증하지 못한 것을 원문이 거짓이라는 뜻으로 취급하지 않는다.

## 실행

저장소 .env의 OPENAI_API_KEY 또는 환경변수를 사용한다. 키 값은 출력하지 않는다.

```powershell
# 무료: 기본 BM25 + 그래프 + 유형별 검색만 확인
.\.venv\Scripts\python.exe scripts\run_agent_v4.py --question 'CRITICAL 예측 정비 규칙을 모두 정리해줘' --run-dir kg_build\agent_v4_search1 --retrieve-only

# 최초 1회 유료: 정답/벤치마크 파일 없이 행 인덱스 준비. 기존 인덱스가 맞으면 무료 재사용.
.\.venv\Scripts\python.exe scripts\prepare_retrieval_v4.py

# 유료: 문서 답변 + 근거 검증, 준비된 dense 행 인덱스 사용
.\.venv\Scripts\python.exe scripts\run_agent_v4.py --question '연구실 습도가 70%예요. 문서상 실험 기준과 조치는?' --run-dir kg_build\agent_v4_answer1 --dense
```

출력 폴더는 매번 새 경로를 사용한다. --dense가 없으면 인덱스가 있어도 BM25만 사용한다.
--dense에서 인덱스가 없으면 자동 구축/대체 없이 중단한다. 인덱스 최초 구축은 별도 유료 작업이다.

## 재현

```powershell
$env:PYTHONPATH='src'
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m unittest tests.test_agent_v4_1 tests.test_agent_v4 tests.test_agent_v3 tests.test_retrieval_v3 tests.test_detector_kg tests.test_agent_contract -q

# 각 명령은 새 출력 폴더를 지정한다.
.\.venv\Scripts\python.exe scripts\evaluate_retrieval_v4.py retrieve --out kg_build\retrieval_v4_new
.\.venv\Scripts\python.exe scripts\evaluate_retrieval_v4.py grade --out kg_build\retrieval_v4_new
.\.venv\Scripts\python.exe scripts\evaluate_agent_v4_1_quality.py --out kg_build\agent_v4_1_new --repeat 3
.\.venv\Scripts\python.exe scripts\grade_agent_v3_quality.py --run kg_build\agent_v4_1_new --out kg_build\agent_v4_1_review_new
.\.venv\Scripts\python.exe scripts\audit_agent_v4_faithfulness.py --run kg_build\agent_v4_1_new --review kg_build\agent_v4_1_review_new --out kg_build\agent_v4_1_audit_new
```

내용/근거 채점은 기존 v3 방법을 재사용한다. 충실성 검토에는 v4의 실제 앱 조회 메타데이터까지 포함한다. 완료 결과를 봉인한 뒤에만 PRIVATE 정답을 읽는다.
불완전한 수집은 최종 점수를 만들지 않으며, 실패/유보 답변을 유리하게 제외하지 않는다.

## 한도와 범위

- 문서 근거: 각 생성/검증 입력의 원문 4000토큰 이내. 반복 검색의 누적 읽기량과는 구분한다.
- 문서 검색 최대2회, 신규 질의 임베딩 최대2회, 초안 최대2회, 검증 최대2회. 전송 실패 자동 재시도 없음.
- 기존 후보 목록/설명은 원래 봉인된 과거 탐지 저장소와 선택 계약을 재사용한다. KG 탐지기 v2 결과 연결은 이번 범위가 아니다.
- 실제 센서/제어 연결이 없고, 설치 모델/원인/운전 허가/조치 완료를 문서만으로 확정하지 않는다.
- LLM 검증과 AI 채점은 오류가 있을 수 있다. 사람 검토를 수행했다고 표시하지 않는다.
