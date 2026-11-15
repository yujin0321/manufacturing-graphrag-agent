# 별도 CSV 재분석·시계열 API 인계

최신 v2 계약: [비동기 분석·선행 구간·ZIP 내보내기/복원](ANALYSIS_WORKFLOW.md). HTTP 업로드는 아래와 같이 202 접수와 상태 조회를 사용한다. 입력 제한·기본 탐지·기존 결과는 유지한다.

작성 2026-11-15. 공유 브랜치 `예원12`. 구현 `sensor-analysis-v1-20261115`.

CSV 입력을 별도 분석으로 등록하고 기존 v3.1 규칙 엔진·KG 오버레이·근거 검사·주장 연결을 재사용한다. 시계열과 사건의 구조화된 설명은 로컬 코드로 생성하며 LLM·새 임베딩 호출이 없다. UI 화면은 변경하지 않았다. 일반 질문 Agent와 업로드 분석은 별도 경로다.

## 실행

기존 README대로 코드·의존성·런타임 ZIP을 준비한 뒤 실행한다.

```powershell
.\.venv\Scripts\python.exe scripts/run_xai_agent.py --serve --read-only --allow-local-analysis --port 8770
```

`--read-only`는 유료 답변 생성을 계속 금지한다. `--allow-local-analysis`는 CSV 저장·로컬 규칙 분석만 명시적으로 허용한다. 이 옵션을 생략하면 새 분석 API는 비활성화된다. `/api/session`의 `generation_enabled=false`, `analysis_enabled=true`를 구분한다. 외부 배포·다중 사용자 인증 서버는 아니며 기존 동일 출처·Host·CSRF 정책을 유지한다.

## 1. 입력 제한과 출처

UTF-8/BOM CSV, 다음 7개 열을 이 순서로 받는다. 정답·이상 라벨 열은 받지 않는다.

```csv
timestamp,zone,station_id,sensor_id,sensor_type,value,unit
```

- 최대 4 MiB, 20,000행. 관측값은 유한 숫자이며 절댓값 1e12 이하라는 수치 처리 상한을 둔다. 이 상한은 제조 안전 임계값이 아니다.
- 기존 KG와 규칙이 지원하는 센서만 사용한다. 공정·구역·유형·단위가 KG와 일치해야 한다. 새 센서를 임의로 매핑하지 않는다.
- 프로젝트의 현지시각 ISO 형식, 30초 격자(초 00/30), 시간대 표기 없음. 빈 셀·비유한 숫자·중복 센서/시각은 거절한다.
- 순서가 섞인 행은 센서·시간순으로 정규화한다. 원본 `upload.csv`와 정규화 `input.csv`의 해시를 모두 보존한다. 값을 보간하거나 공백을 정상으로 채우지 않는다.
- 관측 공백은 `quality.gaps`에 기록하고 연속 창을 초기화한다. 충분한 연속 표본이 없는 규칙은 `coverage.skipped_rules`에 표시한다.
- 기울기의 sigma는 기존 봉인된 정상 기준을 재사용하며 업로드로 학습하지 않는다. 선택 구간 시작보다 기준 학습 종료가 늦으면 그 센서의 기울기 규칙을 제외한다. 섞인 구간의 일부만 몰래 평가하지 않는다.
- 누락된 상대 센서가 필요한 공정 쌍은 제외하고 개수를 표시한다. 지원하지 않는 규칙·부분 관측 조건도 함께 공개한다. 후보 0건은 설비 정상 판정이 아니다.

분석마다 `ana-<32자리 hex>` ID와 별도 폴더를 만든다. 원본 입력·설정·실행 규칙·결과·오버레이·파일 해시를 봉인한다. 같은 CSV를 다시 넣어도 별도 분석이며, 사건 URI와 관측 출처는 분석별 namespace를 사용한다. 기존 사건 ID는 반드시 분석 ID와 함께 사용한다. `kg_build/sensor_analyses/`는 로컬 전용이며 Git·기존 런타임 ZIP에 자동 포함하지 않는다.

## 2. API

| 메서드 | 경로 | 반환 |
|---|---|---|
| GET | `/api/analyses` | 최근 분석 상태 최대 50개 |
| POST | `/api/analyses` | HTTP 202로 분석 ID 접수. status_url을 조회해 완료 결과 확인 |
| GET | `/api/analyses/{analysis_id}` | 상태·요약·사건 목록·관련 후보 |
| GET | `/api/analyses/{analysis_id}/series?sensor_id=...` | 페이지 단위 원시 관측값·기준선·알람/사건·공백 |
| GET | `/api/analyses/{analysis_id}/incidents/{incident_id}` | 해당 분석 사건의 원문·관계·XAI·코드 요약 |

분석은 백그라운드 작업자 1개에서 처리하고 실행+대기는 최대 3개다. 접수 후에는 같은 ID의 상태를 조회한다. 완료/실패/중단을 구분하고 자동 재업로드하지 않는다. 초기 SHACL 검사 등으로 시간이 걸릴 수 있다. CLI analyze와 Python create는 동기식을 유지한다.

POST는 세션 토큰 헤더가 필요하다. 파일 경로·파일 이름을 서버 저장 경로로 받지 않는다.

```javascript
const session = await (await fetch('/api/session')).json();
if (!session.analysis_enabled) throw new Error('로컬 분석 기능을 켜 주세요.');
const response = await fetch('/api/analyses', {
  method: 'POST',
  headers: {
    'Content-Type': 'text/csv; charset=utf-8',
    'X-Demo-Token': session.csrf_token,
    'X-Input-Kind': 'historical_replay'
  },
  body: selectedFile // 파일 선택창의 UTF-8 CSV File 객체
});
let result = await response.json();
if (!response.ok) throw new Error(result.error);
const analysisId = result.analysis_id;
while (['queued', 'processing'].includes(result.status)) {
  await new Promise(resolve => setTimeout(resolve, 1000));
  const statusResponse = await fetch(`/api/analyses/${analysisId}`);
  result = await statusResponse.json();
  if (!statusResponse.ok) throw new Error(result.error);
}
if (result.status !== 'complete') throw new Error(result.error?.message ?? result.status);
```

일반 CSV는 `X-Input-Kind: uploaded_sensor_csv`를 사용한다. 이 종류 표시는 호출자 선언이며 파일이 실제 미노출 데이터라는 증명은 아니다. JSON 방식은 `Content-Type: application/json`, 본문 `{"csv":"...","input_kind":"historical_replay"}`로도 지원한다. multipart/form-data는 구현하지 않았으므로 File 객체를 위처럼 본문에 직접 보낸다.

### 시계열

필수 `sensor_id`, 선택 `start`, `end`, `offset=0`, `limit=2000`(최대 10,000), `include_warmup=false`를 받는다. start/end는 양 끝 포함이다. 기본은 지정한 분석 대상 구간이며 선행 계산 구간 조회는 include_warmup=true가 필요하다. 같은 인자의 중복·거꾸로 된 구간·등록되지 않은 센서를 거절한다.

| 필드 | UI 사용 |
|---|---|
| `points` | `{timestamp,value}` 배열. value는 정확한 저장 표현을 위한 decimal string. 차트를 그릴 때 숫자로 변환 |
| `total`, `offset`, `next_offset` | 페이지 누락 없이 이어 받기. `next_offset=null`이면 끝 |
| `unit` | 축 단위. m/s와 mm/s 등을 임의 통합하지 않음 |
| `thresholds` | `nominal`, `warnLo`, `warnHi`, `critLo`, `critHi` 기준선 |
| `threshold_source` | 기준선 KG 노드·고정 KG 해시 |
| `gaps` | 관측 공백의 앞/뒤 시각·빠진 표본 수. 차트 선을 끊고 보간하지 않음 |
| `alarms` | 조건 시작·최초 발동·마지막 충족 시각을 각각 표시 |
| `incident_intervals` | 탐지기의 사건 구간·추정 유형 |
| `input_sha256` | 차트가 가리키는 정규화 업로드의 해시 |

알람·사건·공백은 **요청 전체 구간** 기준이며 points 한 페이지에 한정하지 않는다. `returned_interval`과 `markers_scope`를 확인하고 전체 페이지를 모으거나 현재 뷰에 맞춰 자른다. 다운샘플링·보간은 하지 않는다. 마지막 조건 충족 시각을 실제 설비 회복 시각으로 표시하지 않는다.

### 사건 XAI

`answer`는 질문에 대한 새 LLM 응답이 아니라 검증된 주장 ID를 코드가 골라 조립한 요약이다. `explanation_mode=deterministic_evidence_summary_no_LLM`, `answer_complete=false`다. 종류별 최대 4개 주장과 필수 한계를 선택하며 전체 규칙은 구조화된 근거에서 확인한다. `[CLM-...]`를 모델 내부 사고 설명으로 표시하지 않는다.

`sources`, `edges`, `claims[*].evidence_paths`, `xai.decision_evidence`, `xai.rule_explanations`, `xai.claim_binding`은 기존 XAI 규약을 따른다. 관측 출처는 업로드한 input.csv를 가리킨다. `correlation_candidates`는 규칙 패턴의 관련 후보이며 고장 원인 확정·인과 점수가 아니다. 부분 조건만 확인하거나 근거가 부족하면 요약 게시가 보류될 수 있으며, HTTP 200 안의 `agent_status`를 확인한다.

새 분석 사건은 이 전용 경로로 조회한다. 일반 `/api/agent`에 `analysis_id`를 전달해 새로운 데이터의 자유 질문을 처리하는 기능은 이번 범위에 없다. 일반 Agent와 과거 실행 기록은 보존한다.

### 오류

400은 요청 형식/참조/무결성/조회 인자 문제, 403은 Host/Origin/토큰, 404는 없는 분석 또는 비활성화 API, 408은 본문 전송 시간 초과, 409는 대기열 초과·결과 미준비·복원 충돌, 413은 본문 크기 초과, 415는 지원하지 않는 MIME다. 접수 후 CSV 상세 검증·계산 실패는 status=failed와 error에 남는다. 유료 답변 생성은 이 모드에서 여전히 503이다.

Windows에서 SHACL/SPARQL 파싱의 작업 스레드 스택 고갈을 피하도록, 로컬 분석 기능을 켠 서버는 이후 스레드에 최소 8 MiB 스택을 설정한다. [Python threading.stack_size 문서](https://docs.python.org/3/library/threading.html#threading.stack_size). 검사 규칙을 생략하는 방식은 사용하지 않았다.

## 3. 과거 자료의 무작위 재입력

```powershell
.\.venv\Scripts\python.exe scripts/run_sensor_analysis.py replay --seed 20261115 --minutes 120
.\.venv\Scripts\python.exe scripts/check_sensor_analysis_api.py --port 8770
```

첫 명령은 정상 기준이 사용 가능한 시점 이후의 공통 시간 범위에서 시작점을 균등 선택해 모든 센서의 연속 구간을 CSV로 만든다. seed·선택 구간·원본 해시·CSV 해시를 JSON에 기록하며 정답 파일이나 기존 탐지 결과를 보고 구간을 고르지 않는다. 원래 시각을 유지하고 재추출한다. 결과가 0건이어도 정상적인 시연 결과다.

둘째 명령은 실제 로컬 API 업로드→시계열 값 대조→사건 XAI→기존 입력·기본 엔진·KG 보존을 검사한다. 무작위 구간에 사건이 없어도 다시 뽑지 않고, 별도의 명시적 합성 이상 CSV(`synthetic_positive_ST02_TMP.csv`)로 양성 XAI도 확인한다. 전체 응답은 원문을 포함해 `kg_build/sensor_analysis_api_audit/`에만 저장하며, 공유 집계는 [실제 API 검사](sensor_analysis_api_audit.json)에 둔다. 전체 회귀 175개와 실제 API 결과는 [검증 보고서](../../reports/sensor_analysis_20261115_verify.md)에 기록했다.

서버 없이 분석만 실행할 수도 있다.

```powershell
.\.venv\Scripts\python.exe scripts/run_sensor_analysis.py analyze --input kg_build/sensor_replay_inputs/replay_seed20261115_120m.csv --input-kind historical_replay
```

과거 데이터를 다시 넣은 기능 시연이며 미노출 성능 평가가 아니다. 기존 3종 비교 점수나 탐지 정확도를 갱신하지 않는다. UI 담당자는 이 API로 업로드 버튼·사건 목록·시계열·근거 패널을 연결한다.
