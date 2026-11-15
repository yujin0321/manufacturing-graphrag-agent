# 통합 Agent 연결 검증 결과 (2026-11-13)

기준 main: `020c863`. 로컬 개발 브랜치: `codex/agent-e2e-xai-20261113`. [사용·적용 범위](TEAM_AGENT_APP_20261113.md).

## 자동 검사

37개 Agent·검색·원본 매핑·전수 질의 회귀 검사와 2개 HTTP 선택 전달 검사가 모두 통과했다. 건너뛴 검사는 없다. JavaScript 구문 검사도 통과했다. 실제 서버의 네 탐지 목록 조회와 저장 결과 조회를 확인했다. 브라우저 제어 도구 초기화 실패로 시각적 배치는 직접 확인하지 못했다.

## 탐지 산출물

| 선택 | 후보/사건 수 | 알람 수 | 검증 |
|---|---:|---:|---|
| main_v3_1 | 17 | 120 | SHACL·참조·봉인 통과 |
| yujin_v3_2 | 17 | 120 | SHACL·참조·봉인 통과 |
| seongho_two_point | 55 | 55 | SHACL·참조·봉인 통과 |
| seongho_drift | 89 | 89 | SHACL·참조·봉인 통과 |

성호의 수치는 원본 규칙별 이벤트 수다. 기본 엔진의 묶음 사건 수와 단위가 달라 성능 비교에 사용하지 않는다. S2의 유형 제약 때문에 미분류를 AnomalyEvent로 표현한 초기 시도를 중단했고, 별도 RuleMatchCandidate와 전용 SHACL로 바로잡았다. 원본 탐지기와 기본 온톨로지는 수정하지 않았다. 봉인된 중간 출력은 재실행하지 않고 복구해 사용했다.

## 실제 API 연결 확인

| 실행 ID | 경로 | 상태 | 새 API 호출 | 모델 토큰 |
|---|---|---|---:|---:|
| team_document_20261113_01 | document | complete | 5 | 6,915 |
| team_kg_20261113_01 | kg | complete | 1 | 519 |
| team_main_20261113_01 | explain | complete | 3 | 11,073 |
| team_seongho_20261113_01 | explain | complete | 3 | 6,009 |

네 사례 모두 검토 통과 또는 코드 전수 질의 결과를 반환했다. 이 확인 사례는 이미 알려진 입력을 포함하는 개발 점검이며 정확도·모델 우열·새 미노출 평가 결과가 아니다. 전체 4×4 조합의 생성 품질을 측정한 결과도 아니다.

157개 문서 행의 기존 임베딩을 재사용했다. 새 원문 임베딩 호출은 0회다. 위 문서 질문의 질의 임베딩 1회는 API 호출 수에 포함하고 모델 토큰 열에서는 제외했다. 요청·응답·도구·초안·검토 원본은 각 `kg_build/graphrag_live/<실행 ID>/`에 있다. 실행 집계와 해시는 `kg_build/team_app/validation_20261113.json`, 무료 테스트 로그는 `kg_build/team_tests_final.log`에 있다.

기존 실험 점수는 그대로 보존한다. 이번 작업은 네 사람의 자료를 읽고 선택 가능한 앱으로 연결한 새 구성이다. 수민 보고서의 미공개 실행 코드나 성호 11/9 정정 실험을 그대로 재현했다고 주장하지 않는다. 제외 요청한 17건 연속 실험을 불러오지 않았다.

## 재검사 명령

```powershell
$env:PYTHONPATH='src'
..\.venv\Scripts\python.exe -m unittest tests.test_incident_agent tests.test_team_app tests.test_agent_v4_1 tests.test_agent_contract tests.test_retrieval_v5 tests.test_team_app_server -v
```

서버는 `http://127.0.0.1:8770/`에서 실행한다. 화면을 열고 저장된 기록을 읽는 데는 새 API 비용이 없다. Git 커밋·푸시는 이번 통합 단계에서 실행하지 않았다.
