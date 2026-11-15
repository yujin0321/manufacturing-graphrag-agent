# iMAKS UI 전달 안내

- demo/index.html: 더블클릭 후 예제 데이터 불러오기 → 탐지 실행 → 경보 선택 → 설명. 밀봉 온도 한 규칙과 예시 설명으로 화면을 확인합니다.
- 연결용 (integration/): main 탐지기와 Agent를 붙이기 위한 UI 소스입니다. 아래 인터페이스는 제안 규격입니다. 팀 서버 형식이 다르면 api.js에서 맞추면 됩니다. index.html과 api.js를 백엔드와 같은 HTTP 출처에서 제공하세요.
- 26-2 폴더에 있는 timeseries_raw.csv는 탐지 입력, anomaly_events.csv는 탐지 이후 비교에 사용하는 정답입니다.

## 연결용 인터페이스

POST /api/detect — multipart/form-data의 file 필드. 응답 예시:

```json
{"run_id":"run-001","start":"2026-01-06T08:00:00+09:00","end":"2026-01-06T09:00:00+09:00","events":[{"event_id":"inc-example","id":"ST02_SEALING_TMP","time":"2026-01-06T08:30:00+09:00","value":212.82,"unit":"°C","kind":"상한 초과"}]}
```

event_id는 이 실행에서 사건을 다시 찾을 수 있는 안정된 ID입니다. id는 센서 ID, time은 판정 시각입니다. events가 비어도 실행 시간 범위를 반환하세요.

GET /api/runs/{run_id}/events/{event_id}/series — 경보 전후 시계열 조회. 범위 조건이 없으면 low/high를 null로 반환하세요.

```json
{"low":175,"high":195,"points":[{"time":"2026-01-06T08:30:00+09:00","value":212.82}]}
```

POST /api/runs/{run_id}/events/{event_id}/explain — 같은 사건의 설명 요청. 응답 예시:

```json
{"status":"complete","answer":"관측값이 적용 규칙의 상한을 넘었습니다.","sources":[{"id":"SOP-001","text":"관련 원문 발췌"}],"limitations":["온도 상승의 물리적 원인은 추가 점검이 필요합니다."]}
```

오류는 HTTP 4xx/5xx에 {"message":"사용자에게 표시할 이유"}를 반환하세요. 설명 상태와 출처는 실제 Agent 결과에 맞춥니다. 화면에서 14건 정답 평가를 표시하려면 별도 평가 연동이 필요합니다.

## 결과 및 근거 표시용 선택 필드

- 탐지 응답: alarm_count(개별 경보 수), evaluation({caught,total,type_matches,unmatched_alarms}). evaluation은 정답을 탐지 이후 별도로 비교한 결과가 있을 때만 반환합니다.
- 사건: start/end(사건 시작·종료), rule_id/condition(실제 실행 규칙과 조건). time은 최초 판정 시각입니다.
- 설명: verification, recommendation, action_record, expert_check(각각 문자열 또는 null). 출처 원문은 sources[].text에 전달합니다.

화면 확인용은 세 센서의 시연 데이터와 정답 비교를 제공합니다. 실제 센서 CSV는 화면 확인용에서 밀봉 온도만 검사합니다. 연결용 상세 화면은 사건의 선택 필드 source_id를 표시할 수 있습니다.
출처 위치는 sources[].location에 페이지·절·표 행 등 사람이 찾아볼 수 있는 문자열로 전달할 수 있습니다.
