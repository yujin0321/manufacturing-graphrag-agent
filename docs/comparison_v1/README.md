# 세 방식 비교 실행 준비 v1

2026-10-24. LLM 단독 및 예원 v2 GraphRAG 실행 경로를 추가했다. 이번 작업은 구현·오프라인 검증이며 새 두 방식의 실시간 API 답변 생성이나 정식 eval 평가를 실행한 결과가 아니다.

| 조건 | LLM | Vector RAG v1 | GraphRAG v1 |
|---|---|---|---|
| 생성 모델 | gpt-6.1-sol | 동일 | 동일 |
| 공통 지시문 | docs/vector_rag_v1/answer_instructions.txt | 동일 | 동일 |
| 최대 출력 토큰 | 4,096 | 동일 | 동일 |
| temperature·seed | 생략 | 동일 | 동일 |
| 자료 접근 | 없음, 질문만 | SOP·데이터시트 7개 | 동일 문서 + 원래 예원 v2 KG |
| 컨텍스트 상한 | 0 | 4,000 기준 토큰 | 그래프와 문서 합계 4,000 기준 토큰 |
| 검색 | 없음 | 코사인 top8 | 코사인 top8 + 식별자 연결 + 그래프 탐색 |

토큰 예산 기준은 o200k_base이며 실제 생성 모델 토크나이저와 같다고 가정하지 않는다. 동일 예산은 입력 내용이나 실제 길이가 같다는 뜻이 아니다. LLM 단독은 원문에 접근할 수 없어 출처 점수가 불리하며 총점 차이를 순수 모델 능력 차이로 해석하지 않는다.

## GraphRAG 설계

기준 KG는 `artifacts/stage6_final_20261016/inputs/kg_build/openai_sol_v2_20261016/graph/candidate.ttl`의 2,806개 트리플이다. 원래 v2의 seed 구조와 추출 규칙을 함께 사용하며 이후 priority 레이어·확장 관계·다른 팀 산출물은 추가하지 않았다.

1. 기존 임베딩 인덱스에서 코사인 상위 8개 원문 청크를 찾는다. 질문 벡터 캐시도 재사용한다.
2. 질문에 완전하게 쓰인 KG identifier와 해당 청크에 원문 출처가 연결된 노드를 탐색 시작점으로 삼는다. Document 노드는 식별자 시작점에서 제외해 문서 전체로 무제한 확장하지 않는다. 별도 한국어 개체명 번역 사전·질문별 예외는 없다.
3. 시작 노드 최대 6개, 방문 노드 최대 24개, 최대 2홉. appliesToSensor/actionTarget/hasSensor/feedsInto를 양방향으로 탐색한다. sourceDocument와 hasProvenance를 통과하는 무제한 탐색은 하지 않는다. 탐색 방향은 원래 트리플에 기록해 역방향 탐색을 역방향 사실로 바꾸지 않는다.
4. 방문 노드의 기존 속성·출처를 카드로 직렬화한다. 문서 출처는 파일 해시를 확인하고 table ID 또는 원문 인용 일치로 청크와 연결한다. 그래프 카드 최대 1,500 기준 토큰이며 카드 전체가 들어가지 않으면 건너뛴다.
5. 포함된 카드에 연결된 원문, 기존 top8 원문 순으로 중복을 제거해 남은 예산에 넣는다. 표·문장 청크를 중간에 자르지 않는다. 그래프와 원문 합계는 4,000 기준 토큰을 넘지 않는다.
6. 노드·탐색 간선·제외 항목·실제 컨텍스트를 기록하고 공통 생성 지시문으로 답변을 요청한다.

따라서 이 방식의 정확한 이름은 **문서 벡터 검색을 보조로 사용하는 로컬 예원 v2 GraphRAG**다. 그래프만 검색하는 방식이나 Microsoft GraphRAG 구현은 아니다. seed CSV 구조까지 활용하므로 Vector RAG와의 비교는 자료 표현·접근 경로 차이를 포함한다. 원문과 seed/추출 속성이 다르면 임의로 수정하지 않고 출처를 보존한다. KG 주장을 현재 상태나 검증된 신규 인과관계로 표현하지 않는다.

## 실행

저장소 루트 PowerShell. 기존 환경의 rdflib를 사용하며 이번에 설치한 패키지나 모델은 없다. 최소 의존성은 requirements-rag.txt에 기록했다.

```powershell
$env:PYTHONPATH='src'
$env:PYTHONUTF8='1'
..\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*rag*.py' -v
```

다음은 실제 유료 API 호출 명령 형식이다. 환경변수 OPENAI_API_KEY가 필요하고 실행 폴더는 새 폴더여야 한다. 벤치마크에서는 해당 질문 파일의 문장을 수정 없이 전달한다.

```powershell
..\.venv\Scripts\python.exe -m imaks_kg.rag.comparison LLM --question '질문' --run-dir kg_build/comparison_runs/LLM/run001
..\.venv\Scripts\python.exe -m imaks_kg.rag.comparison GraphRAG --question '질문' --run-dir kg_build/comparison_runs/GraphRAG/run001
```

모든 실행은 독립 messages 배열을 사용한다. LLM 경로는 KG·원문·벡터 인덱스를 읽지 않는다. 입력, 검색, 원시 API 응답, 답변 또는 실패 기록을 저장하며 API 키는 저장하지 않는다. 정답과 채점 파일은 두 실행 경로 모두 읽지 않는다. 생성 모델 반환 ID가 다르면 기록되므로 후속 비교 집계 전에 확인한다. 자동 모델 대체·자동 API 재시도는 없다.

## 비교 순서와 한계

먼저 새 두 방식으로 dev 6문항의 실시간 답변 생성과 같은 기준 채점을 점검한다. 그 뒤 세 방식의 실행 코드·정책·지시문·KG·문서를 고정하고 eval24를 실행한다. 이번 구현은 Vector RAG dev 실패를 이미 본 이후 설계했으므로 dev를 독립 평가라고 보고하지 않는다. GraphRAG 점수를 예상하거나 보장하지 않는다. 설정을 수정한다면 이유와 버전을 기록하며 기존 Vector RAG 3.9167/5를 새 설정의 성능으로 대체하지 않는다.

현재 코드·입력 해시 및 오프라인 확인 결과: `kg_build/comparison_v1/manifest.json`. 이 파일은 준비 시점의 스냅샷이며 실행 시 모든 구현 파일의 변경을 자동 차단하는 장치는 아니다. 정식 평가 전에 스냅샷과 실행 코드를 다시 대조해야 한다.

## 실행 결과 추가 (2026-10-24)
이후 dev 점검 및 eval24 세 방식 실행·AI 채점을 완료했다. 결과는 ../../reports/comparison_eval_20261024_verify.md에 있다. 위 준비 단계 설명의 미실행 상태는 당시 기록이다. 현재 결과는 LLM0.7917/5, VectorRAG4.4375/5, GraphRAG4.4375/5이며 GraphRAG 점수 개선은 확인되지 않았다.
