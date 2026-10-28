# Agent 도구 연결 — 로컬 실행기

후속: [모델 선택·답변 생성 연결](AGENT_MODEL_CONNECTION_20261028.md)을 추가했다. 이 문서의 캐시 전용 설명은 독립 도구 실행기 기본 동작이며, 통합 Agent는 별도 검색 어댑터를 사용한다.

2026-10-28. 기존 검색·후보 조회를 재사용하는 도구 어댑터와 실행기를 구현했다. 기본 v2, 기존 검색 코드, 기존 시연 화면은 수정하지 않았다.

## 구현 범위

`src/imaks_kg/rag/agent_tools.py`의 `ToolSession`은 다음 도구를 실행하고 공통 형식으로 결과와 실행 추적을 저장한다.

| 도구 | 연결한 기존 기능 |
|---|---|
| search_documents | `graph_v2.retrieve`: 기존 벡터·KG 검색, 원문·그래프 경로 반환 |
| list_candidates | 봉인된 후보·규칙 파일 검증 후 필터·정렬·페이지 조회 |
| get_candidate_evidence | `event_explain.prepare`: 후보·실행 규칙·원문·그래프 경로 반환 |

최대 도구 시도 3회, 누적 근거 4,000토큰을 강제한다. 오류 후 세션은 중단되며 자동 재시도하지 않는다. 후보 근거 조회는 호출자가 명시한 ID 또는 전체 필터 결과가 정확히 한 건인 ID만 허용한다. 페이지에 한 건만 보인다는 이유로 선택을 허용하지 않는다.

`explicit_event_ids`는 UI나 상위 실행기가 사용자 입력에서 확인한 값만 전달해야 한다. 모델이 호출 인자로 이 목록을 수정할 수 없다. 현재 이 신뢰 경계를 담당하는 모델 라우터·UI는 아직 연결하지 않았다.

실행 폴더에는 `run_lock.json`, 순서별 `tool_01.json` 등과 `trace.json`을 저장한다. KG·인덱스·검색 정책·탐지 봉인·계약·실행기 해시, 도구 입력·결과 해시·상태·소요 시간·누적 근거량을 기록한다. 실행 폴더가 이미 있으면 덮어쓰지 않는다.

## 비용과 제한

이번 실행기는 **네트워크 호출과 답변 생성이 없다.** 문서 검색은 기존 질문 임베딩 캐시에 있는 질문을 처리한다. 캐시가 없는 새로운 질문은 `local_resource_or_embedding_cache_missing`으로 중단한다. 기존 별도 시연의 새 질문 기능은 그대로지만 이번 통합 도구에는 아직 유료 임베딩 경로를 연결하지 않았다.

모델의 도구 선택, 새로운 질문 임베딩, 최종 한국어 답변, 사용자 명확화 화면은 다음 연결 작업이다. 따라서 ‘Agent 전체 완성’ 또는 ‘새 질문까지 통합 E2E 완료’라고 보고하지 않는다. 계획·답변 생성 횟수 상수는 계약에 있지만 이번 실행기에는 해당 호출 자체가 없다.

최종 사용자 상태(`complete`, `needs_clarification` 등) 결정은 상위 실행기의 책임이다. 현재 도구는 `ok/error`와 조회 결과를 반환하며 후보 모호성 정책은 기존 `agent_contract.candidate_disposition`으로 판단할 수 있다. 독립 사실성·충돌 판정기는 추가하지 않았다.

## 로컬 사용 예

저장소 루트에서 기존 가상환경과 `PYTHONPATH=src`를 사용한다. 아래는 Python 예시이며, 실행마다 새 폴더명을 사용한다.

```python
from pathlib import Path
from imaks_kg.rag.agent_tools import ToolSession
from imaks_kg.rag.agent_contract import candidate_disposition

session = ToolSession(Path('kg_build/graphrag_agent_v1/example_001'))
result = session.execute('list_candidates', {'rule_id': 'MAINT-05'})
if result['status'] == 'ok':
    data = result['data']
    decision = candidate_disposition(
        data['total_matches'], [e['id'] for e in data['items']], 'explain')
    if decision['status'] == 'ready':
        evidence = session.execute('get_candidate_evidence',
                                   {'event_id': decision['event_id']})
    else:
        print(decision)  # 선택 요청 또는 근거 부족으로 종료
```

## 검증 결과

기존 계약 테스트 7개와 신규 연결 테스트 8개, 총 **15개 통과**.

- 실제 봉인 자료에서 93건 전체 수, 페이지 처리, 문서 규칙 ID 필터 확인.
- 실제 MAINT-05 후보에서 최초 판정 값 `26.9452`, SOP-003 원문, 그래프 경로와 추적 파일 확인.
- 실제 캐시 질문의 기존 GraphRAG 검색과 캐시 적중 확인.
- 복수 후보의 임의 선택, 잘못된 필터, 4번째 호출, 오류 후 재호출 차단 확인.
- 누적 근거 예산 초과 시 결과를 반환하지 않고 중단하는 것 확인.
- 캐시 없는 질문에 네트워크 대체 호출이 없는 것 확인.

최초 테스트는 운영체제 임시 폴더 권한 때문에 실패했다. 테스트 임시 결과 위치를 저장소의 `kg_build/agent_tool_tests/`로 바꾼 뒤 모두 통과했다. 테스트 생성 폴더는 종료 시 정리된다. 실제 모델의 도구 선택이나 답변 정확도 시험은 아니다.

재현 명령:

```powershell
$env:PYTHONPATH='src'
$env:PYTHONUTF8='1'
..\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_agent*.py' -v
```

다음 작업은 이 도구 실행기 위에 제한된 모델 선택·최종 답변 생성을 연결하는 것이다. 정답 이벤트 14건 시연 모드는 아직 추가하지 않았다. 이번 작업은 커밋·푸시하지 않았다.
