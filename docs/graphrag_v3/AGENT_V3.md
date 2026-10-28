# Agent v3 연결

문서 질문 → 모델 라우팅 → graph_v3 검색 → 행 단위 원문/병합 카드 → 근거 기반 답변.
기존 agent.py와 v1/v2는 수정하지 않고 agent_v3.py 경로를 추가했다.

## 무료 검색 확인

저장소 폴더에서 실행한다. 필요 패키지는 requirements-rag.txt를 사용한다.

```powershell
$env:PYTHONPATH='src'
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m imaks_kg.rag.agent_v3 --question '서버실 온도가 높으면 어떤 규칙과 조치를 확인해야 하나요?' --run-dir kg_build\agent_v3_search_run1 --retrieve-only
```

새 출력 폴더를 사용한다. 기존 폴더가 있으면 덮어쓰지 않는다.
이 경로는 모델 라우팅/답변 생성을 수행하지 않는다. 공식 o200k 토크나이저 최초 다운로드는 가능하다.
기본 검색은 BM25이며, 행 임베딩 인덱스가 존재해도 자동으로 dense를 사용하지 않는다.

## 답변 생성 경로 (유료)

```powershell
.\.venv\Scripts\python.exe -m imaks_kg.rag.agent_v3 --question '실러 전류 관련 문서 규칙과 조치는?' --run-dir kg_build\agent_v3_answer_run1
```

OPENAI_API_KEY가 필요하다. 라우팅과 최종 답변에 모델 호출을 사용한다.
`--dense`를 추가하면 기존 v3 행 인덱스를 사용하고 질의 임베딩 캐시가 없을 때 최대 1회 임베딩 API를 호출한다.
인덱스가 없으면 중단하며 자동 구축이나 BM25 대체를 하지 않는다.
`--retrieve-only`와 `--dense`는 함께 사용할 수 없다.

## 보존한 동작

- 모델이 도구와 인자를 제안하고 코드가 허용 목록/선택/한도를 검사한다.
- 문서 질문의 검색 질의는 모델이 바꾼 문장이 아니라 사용자 원문이다.
- 특정 후보 ID는 사용자 명시 또는 단일 후보 결과로만 허용한다. 여러 후보면 선택을 요청한다.
- 과거 후보 조회/설명은 기존 봉인 탐지 저장소와 event_explain을 사용한다. KG 탐지기 v2 결과를 연결했다고 주장하지 않는다.
- 문서 질문은 해당 저장소와 v2 벡터 인덱스 없이 실행된다. 후보 질문에 필요한 저장소가 없으면 오류로 중단한다.
- 실제 현재 측정값을 묻는 경우 자료 부족을 알린다. 문서 지시를 실행하거나 설비를 제어하지 않는다.
- 최대 근거 4000토큰, 도구 3회, 신규 질의 임베딩 1회, 최종 답변 1회. 자동 재시도 없음.

## 출력과 검증 범위

`input.json`, `agent_lock.json`, `plan.json`, `retrieval.json`, `tools/trace.json`, 요청/응답, `answer.json`을 저장한다.
검색 기록에는 행 ID, parent_chunk_id를 포함한 출처, 그래프 경로, 실제 토큰 수가 남는다.
검색 전용 경로는 retrieval.json과 retrieval_lock.json만 만든다.
실패를 정답/완료 답변으로 바꾸지 않는다. 정답 PRIVATE 파일은 런타임 입력이 아니다.

테스트: `python -m unittest tests.test_agent_v3 tests.test_retrieval_v3 tests.test_detector_kg tests.test_agent_contract -v`
통합/회귀 47개 통과. 모델 전송은 모의 처리하고 실제 문서/KG 검색을 사용했다.
서버실 온도 질문의 실제 무료 검색은 2772토큰으로 근거와 경로를 반환했다.
실제 유료 모델의 라우팅 정확도, 최종 인용 정확성, dense 검색 품질은 이번 작업에서 측정하지 않았다.
별도 자기검증/재검색 루프도 추가하지 않았다. 현재 구현은 한 번 라우팅하고 한 번 답하는 제한형 Agent다.

## 실제 품질 평가 완료 (2026-10-28)

인증 권한 복구 후 15문항 x 3회 실제 생성/봉인/별도 채점을 완료했다.
현재 기본 BM25 Agent의 최초 AI 평균은 3.18/5, 충실성 재검토 후 3.51/5다.
재검토는 실제 생성 컨텍스트의 누락을 발견한 뒤 완료 답변 39개 전체에 적용했으며 최초 점수를 보존했다.
사람 검토/미노출 일반화 성능 또는 예원과의 직접 우열 비교가 아니다.
상세: [품질 평가](AGENT_V3_QUALITY_20261028.md), [예원/유진 비교](YEWON_VS_YUJIN_AGENT_20261028.md).
