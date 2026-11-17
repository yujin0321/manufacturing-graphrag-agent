# 분석 작업 v2: 비동기 상태·선행 구간·내보내기/복원

작성 2026-11-15. 구현 `sensor-analysis-v2-20261115`. 2026-11-17 사용자 승인으로 `예원12` 구현을 main에 통합하며, 현재 공유·실행 기준은 main이다.

기존 CSV·시계열 API에 세 기능을 추가했다. UI 화면·새 모델 학습·유료 답변 생성은 범위 밖이다. 기존 분석은 계속 조회할 수 있다.

## 1. 비동기 분석

`POST /api/analyses`는 입력을 저장·접수한 뒤 **HTTP 202**로 분석 ID를 먼저 반환한다. CSV 상세 검증과 계산은 백그라운드 작업에서 수행한다. 202는 검증 성공이나 분석 완료가 아니다.

```json
{
  "analysis_id": "ana-<32자리 hex>",
  "status": "queued",
  "phase": "queued",
  "status_url": "/api/analyses/ana-<32자리 hex>",
  "new_api_calls": 0
}
```

UI는 `status_url`을 약 1초 간격으로 조회한다. 재업로드로 진행 여부를 확인하지 않는다.

| status | phase | 표시 |
|---|---|---|
| queued | queued | 대기 |
| processing | validating | 입력 검증 |
| processing | preparing_rules | 규칙·기준 준비 |
| processing | detecting | 탐지 |
| processing | validating_graph | KG·SHACL 검사 |
| processing | sealing | 결과 봉인 |
| complete | complete | 결과 표시 |
| failed | failed | error.code/message 표시, 조회 반복 중단 |
| interrupted | interrupted | 이전 서버 실행 중단. 자동 재실행 없음 |

실제 단계와 UTC 시각은 `phase_history`에 남긴다. 계산한 적 없는 진행률 숫자를 만들지 않는다. 완료 응답의 `job`에는 상태 이력이 포함된다. worker에서 발견한 CSV 열/값 오류도 `failed.error`에 남는다. 결과가 준비되기 전 series/detail/export는 HTTP 409 `analysis_not_ready`다.

과거 완료 기록에는 phase_history가 없을 수 있다. 당시 진행률을 만들어 소급 적용하지 않고 기존 결과로 표시한다.

기본은 작업자 1개, 실행+대기 합계 최대 3개이며 초과 접수는 409 `analysis_queue_full`이다. 전송 중 중복 버튼을 막는다. 프로세스가 정상 종료되면 예약된 작업을 마칠 때까지 기다린다. 강제 종료 후 서버를 다시 켜면 이전 queued/processing을 interrupted로 표시하며 임의 재실행하지 않는다. 저장 폴더 하나에는 서버 하나만 사용한다.

Python 함수 `AnalysisService.create()`와 CLI analyze는 동기식을 유지한다. 테스트·명령행에서 완료 결과를 즉시 다룰 수 있으며, HTTP API만 새 접수 계약을 사용한다.

## 2. 선행 계산 구간과 분석 대상

업로드 CSV에 분석 대상보다 앞선 관측도 함께 넣는다. JSON 본문의 `analysis_start`, `analysis_end` 또는 원시 CSV 요청의 `X-Analysis-Start`, `X-Analysis-End`로 대상 구간을 지정한다. 둘을 함께 지정하거나 모두 생략한다. 생략 시 기존처럼 업로드 전체 범위를 분석한다.

```json
{
  "csv": "timestamp,zone,station_id,sensor_id,sensor_type,value,unit\n...",
  "input_kind": "historical_replay",
  "analysis_start": "2026-01-08T12:26:00",
  "analysis_end": "2026-01-08T12:35:00"
}
```

- 구간은 업로드의 실제 시간 범위 안이어야 하며 분석 구간에 관측값이 있어야 한다. 센서마다 실제 포함된 표본 수를 별도 보고한다.
- 분석 시작보다 앞선 값은 계산 이력이다. 정상 기준을 새로 학습하는 자료로 사용하지 않는다.
- 분석 끝보다 뒤의 값은 원본 upload.csv에 보존하되 **정규화 계산 입력·탐지·종료 검사에서 제외**한다. 업로드 전체의 형식·값 검사는 먼저 수행한다.
- 기존 기울기 기준 가용성 제한을 유지한다. 계산 이력 시작보다 기준 학습 종료가 늦으면 해당 센서의 기울기 규칙을 제외한다.
- `coverage.start_boundary_checks`는 규칙별 필요한 선행 표본 수·실제 연속 선행 표본 수·`sample_history_ready`를 반환한다. 이는 표본 가용성 검사이며 선행 조건의 충족·전체 관계 검색 완전성·실제 정상 상태를 증명하지 않는다.
- 입력 시작 이전 이력은 알 수 없고 관측 공백은 연속성을 끊는다. 선행 구간을 넣었다는 이유로 잘린 이력을 완전한 관측이라고 표현하지 않는다.

summary의 `incident_items`, `incidents`, `alarms`는 대상 구간과 겹치는 결과다. 전체 계산 결과는 봉인 파일에 그대로 보존하고 `processing_incidents`, `processing_alarms`, `history_incident_ids`로 구분한다. 분석 이전에 끝난 사건은 기본 목록에서 제외하지만 관련 근거로 상세 조회할 수 있다.

| window_scope | 의미 |
|---|---|
| started_in_analysis | 최초 발동이 분석 대상 안에 있음 |
| started_before_analysis | 이전에 발동했고 대상 구간까지 이어짐 |
| warmup_only | 분석 이전에 끝난 이력. 새 대상 사건으로 세지 않음 |

series는 기본적으로 대상 구간만 반환한다. 계산 이력도 그리려면 `include_warmup=true`를 사용한다. 두 경우 모두 분석 끝 이후의 값은 반환하지 않는다. `intervals.analysis/context/upload`와 센서별 표본 수를 함께 전달한다. 과거 발동선이 차트 왼쪽에 있으면 이전에 시작된 사건이라는 표시를 사용한다.

선행 구간이 포함된 과거 CSV를 만들 수 있다. 아래 30분은 시연 선택값이며 모든 규칙·관계에 충분한 이력을 보장하지 않는다.

```powershell
.\.venv\Scripts\python.exe scripts/run_sensor_analysis.py replay --seed 20261115 --minutes 120 --warmup-minutes 30
```

출력 JSON의 analysis_start/end를 요청에 함께 사용한다. 원래 시각과 seed·원본/CSV 해시를 유지하며 기존 정답이나 탐지 결과로 구간을 고르지 않는다.

## 3. 내보내기와 복원

| 메서드·경로 | 기능 |
|---|---|
| GET `/api/analyses/{ID}/export` | 완료 분석 ZIP 다운로드. `Content-Type: application/zip` |
| POST `/api/analyses/import` | ZIP 바이너리 본문으로 복원. 세션 토큰과 `Content-Type: application/zip` 필요 |

내보내기는 입력 원본·계산 입력·규칙/설정·결과·오버레이·파일 해시·완료 상태와 요청 구간을 담는다. 허용된 분석 파일만 포함하며 API 키·모델 가중치·다른 실행 캐시는 넣지 않는다. **원시 데이터가 포함된 팀 내부 전달용 ZIP**이며 Git에 올리지 않는다.

복원은 분석 ID와 파일 바이트를 그대로 유지하고 재탐지·LLM 호출을 하지 않는다. 같은 내용은 `already_present`, 새 복원은 `restored`다. 같은 ID에 다른 내용이 있으면 409 `analysis_conflict`로 거절하고 기존 파일을 덮어쓰지 않는다.

압축 32 MiB·해제 합계 64 MiB·항목/manifest 크기를 제한한다. 허용 목록 밖 경로, 중복, 링크, 암호화, 해시/크기 불일치, 문서·KG·기준 버전 차이는 거절한다. 모든 검사가 끝난 임시 폴더만 게시한다. ZIP 내용을 실행하지 않는다.

원래 그래프의 파일 이름과 봉인 바이트는 수정하지 않는다. 다른 저장 위치에서는 SHA-256이 같은 로컬 입력으로 참조를 해석하며 `input_source`와 `origin_input_source`를 함께 반환한다. 봉인·의존성·정형 참조·원본/정규화 입력 일치 검사는 생성자의 신원, 결과의 도메인 정답, 원인이나 새 성능을 인증하는 서명 검사가 아니다.

필요한 구성은 **main 코드(예원12 구현 통합) + 기존 런타임 ZIP + 전달받은 개별 분석 ZIP**이다. 개별 ZIP은 독립 실행 프로그램이 아니다. 기존 문서·KG·센서 기준의 해시가 다르면 먼저 같은 런타임을 복원한다.

```powershell
.\.venv\Scripts\python.exe scripts/run_sensor_analysis.py export --analysis-id ana-... --output kg_build/my_analysis.zip
.\.venv\Scripts\python.exe scripts/run_sensor_analysis.py restore --input kg_build/my_analysis.zip
```

CLI export는 이미 있는 출력 파일을 덮어쓰지 않는다. 복원된 사건은 새 독립 표본이나 새 분석 실행으로 집계하지 않는다.

## 실행·검증

```powershell
.\.venv\Scripts\python.exe scripts/run_xai_agent.py --serve --read-only --allow-local-analysis --port 8770
```

다른 터미널에서 실제 로컬 경로를 확인한다.

```powershell
.\.venv\Scripts\python.exe scripts/check_analysis_workflow.py --port 8770
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m unittest tests.test_analysis_workflow tests.test_sensor_analysis tests.test_team_app_server -v
```

[검증 보고서](../../reports/analysis_workflow_20261115_verify.md) · [실제 API 집계](analysis_workflow_api_audit.json). 합성 대조의 기능 검사이며 새 모델 정확도나 미노출 이상 탐지 성능 평가가 아니다. UI 담당자는 접수/상태 폴링, 구간 구분, 다운로드/복원 버튼을 연결한다.
