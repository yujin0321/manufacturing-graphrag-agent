# 분석 작업 v2 검증 — 2026-11-15

브랜치 `예원12`. 요청한 세 기능을 순서대로 구현했다. main, 기존 평가 입력·KG·기본 탐지 결과, 과거 모델 답변·점수는 보존한다. UI 구현·새 모델 학습·유료 LLM/임베딩 호출은 0회다.

## 1. 비동기 분석·진행 상태

HTTP 업로드는 202와 분석 ID를 먼저 반환한다. 작업자 1개, 실행+대기 최대 3개다. 상태 조회는 실제 queued→validating→preparing_rules→detecting→validating_graph→sealing→complete를 기록한다. 오류·서버 중단을 별도로 보존하며 가짜 퍼센트나 자동 재업로드/재실행은 없다. 미완료 결과 조회는 409다. Python create와 CLI analyze는 기존 동기식을 유지한다.

통제 gate를 이용해 작업이 아직 실행 중일 때 이미 접수 ID를 받는 것을 검증했다. 대기열 초과·빈 입력 후 슬롯 반환·종료 중 접수 거절·worker 실패 1회 기록·현재 실행을 제외한 중단 상태 표시를 검사했다. 실제 로컬 서버에서도 202 접수와 단계 기록을 확인했다. 작은 합성 CSV의 접수 응답은 약 0.015초였으며 일반적인 성능 보장이나 대용량 처리 벤치마크는 아니다.

## 2. 계산 이력과 분석 대상 분리

입력 앞부분을 선행 계산 이력으로 유지하고, 지정 분석 끝 이후는 정규화 계산 입력·탐지·종료 검사에서 제외한다. 원본은 보존한다. 표본 수·공백·규칙별 선행 표본 가용성을 표시한다. 가용성 검사는 실제 조건 충족·관측되지 않은 이력·설비 정상 여부를 증명하지 않는다.

실제 합성 대조는 다음과 같다. 정답 파일이나 기존 탐지 결과를 이용한 무작위 선별 실험이 아니라, 경계 동작을 확인하기 위해 명시적으로 만든 테스트다.

| 항목 | 결과 |
|---|---|
| 원본 업로드 | ST02 온도 90개 표본 |
| 지정 대상 | 2026-01-08 12:26:00~12:35:00 |
| 계산 입력 | 71개: 선행 52개 + 대상 19개 |
| 분석 끝 이후 제외 | 19개. 12:40의 극단값 999도 탐지에 미사용 |
| 대상 차트 | 19개 |
| 선행 구간 포함 차트 | 71개 |
| 대상과 겹친 사건 | 1개·알람 4개 |
| 사건 구분 | started_before_analysis. 이전에 발동해 대상 구간까지 이어짐 |

미래 값을 바꿔도 정규화 계산 입력이 같음을 검사했다. 관측 공백이 선행 연속 표본 수를 초기화하는 것, 대상 전용 조회에서 이력을 몰래 섞지 않는 것, 분석 이전에 끝난 사건을 기본 목록에서 제외하되 근거로 조회하는 것도 확인했다. 잘린 입력 앞부분의 완전성·새로운 인과·미노출 이상 탐지 정확도를 주장하지 않는다.

## 3. 결과 ZIP 내보내기·복원

완료된 입력·규칙/설정·결과·오버레이·해시·상태·요청 구간을 허용 목록으로 묶는다. API 키·모델 가중치·다른 실행 캐시를 포함하지 않는다. 이번 묶음은 14,739바이트였다. 원시 데이터가 포함된 팀 내부 전달용이며 Git에는 넣지 않는다.

실제 API로 다운로드하고 같은 저장소에 다시 넣었을 때 already_present를 확인했다. 별도 빈 저장 위치에 복원한 뒤 XAI 관측·출처 검사가 consistent이고 코드 요약이 complete인 것도 확인했다. 원래 그래프·파일 바이트는 유지하고, 같은 해시의 로컬 입력으로 참조를 해석했다. 복원은 재탐지나 새 모델 실행이 아니다.

변조 해시, 다른 문서/KG/기준 의존성, 중복/허용되지 않은 경로, 링크, 크기 상한을 검사한다. 같은 ID의 다른 내용은 덮어쓰지 않으며 검사 실패 시 임시 복원 폴더를 제거한다. 검사는 봉인·의존성·정형 참조·정규화 입력 일치 범위이며 생성자 인증·정답·인과를 증명하는 서명이 아니다.

## 검증 결과와 보존

- 기존 입력/API·Agent·XAI·탐지 엔진을 포함한 **193개 회귀 검사 통과**. 이전 175개에 새 작업/구간/복원 및 HTTP 계약 검사 18개를 추가했다.
- 실제 로컬 서버의 202 접수·상태 조회·구간별 시계열·ZIP 다운로드/중복 복원·다른 위치 복원·XAI를 모두 통과했다.
- 원본 센서 입력, 고정 v2 KG, 기본 엔진 봉인의 해시가 실행 전후 일치했다. 새 유료 API 호출 0회, 실제 모델 선택 성능 미측정이다.
- [실제 API 집계](../docs/agent_handoff/analysis_workflow_api_audit.json)는 Git에 포함한다. 원본 CSV·ZIP·전체 응답은 로컬 `kg_build/analysis_workflow_audit/`에 둔다.

## 재현·인계

[UI/API 연결 명세](../docs/agent_handoff/ANALYSIS_WORKFLOW.md)를 따른다. 기존 런타임 ZIP을 복원한 예원12 코드에서 실행한다.

```powershell
.\.venv\Scripts\python.exe scripts/run_xai_agent.py --serve --read-only --allow-local-analysis --port 8770
```

다른 터미널:

```powershell
.\.venv\Scripts\python.exe scripts/check_analysis_workflow.py --port 8770
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m unittest tests.test_analysis_workflow tests.test_sensor_analysis tests.test_evidence_paths tests.test_claim_binding tests.test_window_evidence tests.test_decision_evidence tests.test_incident_repair tests.test_agent_handoff tests.test_incident_agent tests.test_team_app tests.test_agent_v4_1 tests.test_agent_contract tests.test_retrieval_v5 tests.test_team_app_server tests.test_rule_explanations tests.test_document_claims tests.test_detector_engine tests.test_detector_engine_stages -v
```
