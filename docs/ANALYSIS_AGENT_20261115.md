# 센서 분석 결과 설명 Agent

2026-11-15, `agent-sumin`. 사용자가 센서 데이터를 올리면 룰 엔진으로 이상 사건 후보를 찾고, 질문하면 그 결과를 KG 규칙과 SOP 원문 근거로 설명한다. UI 시작 화면은 "센서 데이터를 넣어 결과를 도출"하는 방식으로 정해졌고, 이 문서의 `AnalysisService`가 그 화면이 호출할 백엔드다.

기존 탐지 엔진(`detection/engine/`), 사건 도구(`rag/incident_tools.py`), 문서 검색(`rag/retrieval_v4_1.py`) 코드는 수정하지 않고 호출만 한다.

## 1. 흐름

```
센서 CSV 업로드
  └ ingest      필수 컬럼 확인, 라벨·임계값 컬럼 제거, 30초 간격·중복·단위 검사 → 7개 컬럼 정규화
  └ analysis    룰 엔진 v3.1 실행(봉인) → KG 오버레이(SHACL·적재 검사 후 봉인)        ← 약 25초, API 0회
질문
  └ planner     코드 규칙으로 질문 분류(대부분). 애매할 때만 모델이 JSON 계획 선택 → 코드가 검사
  └ tools       결과 요약 · 사건 목록 · 사건 근거 · 상관 후보 · 센서 구간 값 · SOP 검색   ← 로컬 조회, API 0회
  └ agent       답변 생성 → 결정적 인용 검사 + 검증 모델 대조 → 실패 시 지적 반영해 1회 재생성
```

| 모듈 | 역할 |
|---|---|
| `src/imaks_kg/analysis_agent/ingest.py` | 업로드 CSV 검증·정규화. 정답 라벨(`anomaly_label`, `severity`, `alarm_flag`)과 `quality`, 임계값 컬럼, `day`/`shift`/`batch_id`는 읽지 않고 버린 뒤 이름만 보고한다. 임계값은 저장소의 고정 메타데이터와 KG에서만 가져온다. |
| `analysis.py` | 엔진 `pipeline()`과 오버레이 `build_overlay()`·`loader_checks()`·`shacl_checks()`를 그대로 호출한다. 업로드에 맞춰 바꾸는 것은 σ 고정, 없는 센서의 규칙 제외, Provenance 파일명·해시 세 가지다. |
| `tools.py` | Agent 도구 6개와 호출 한도. 사건 근거·상관 후보는 `incident_tools`의 함수를 세션 결과에 적용한다. |
| `planner.py` | 결정적 분류 규칙과 모델 계획 검사. |
| `agent.py` | 계획 실행, 답변 생성·검증, UI 응답 구성. |
| `service.py` | UI 연결용 진입점. 세션 생성·조회·질문·대화 이력. |
| `providers.py` | 모델 제공자 선택(OpenAI 기본, Gemini 선택). 5.1절 |
| `scripts/run_analysis_agent.py` | CLI. |
| `tests/test_analysis_agent.py` | 가짜 모델 응답으로 시험(유료 API 0회). |

### 1.1 업로드 데이터에 엔진을 적용하는 방식

- **σ 고정:** DRIFT 보조 신호의 척도 σ는 업로드 파일이 아니라 기준 입력(`preprocessed/sensors/input/ts_input.csv`)의 학습 구간(2026-01-07 이전)에서 계산한 값을 쓴다. 업로드 데이터가 짧거나 이상 구간만 있어도 척도가 흔들리지 않게 하기 위해서다. 기준 입력을 그대로 올리면 엔진 단독 실행과 결과가 같다.
- **일부 센서만 있는 파일:** 없는 센서의 규칙은 실행하지 않고 `rules_skipped_missing_sensor`에 남긴다. 상관 규칙(ST02 전류 → ST04 속도)은 두 센서가 모두 있어야 후보가 나온다.
- **Provenance:** 오버레이의 시계열 출처는 업로드 파일 이름과 SHA-256으로 기록한다.

## 2. 입력 형식

| 컬럼 | 필수 | 설명 |
|---|---|---|
| `timestamp` | O | `2026-01-06T06:00:00` 또는 `2026-01-06 06:00:00`. 시간대 표기 없음 |
| `sensor_id` | O | 기준 센서 22개 중 하나(예: `ST02_SEALING_TMP`). 그 밖의 센서 행은 건너뛰고 개수를 보고 |
| `value` | O | 숫자. 비거나 숫자가 아닌 행만 평가 불가로 제외하고 개수를 보고. 이상값은 지우거나 보정하지 않음 |
| `zone`, `station_id`, `sensor_type`, `unit` | - | 있으면 기준 메타데이터와 같아야 함, 없으면 기준값으로 채움 |
| 그 밖의 컬럼 | - | 읽지 않음(`dropped_columns`에 이름만 기록) |

센서별 표본 간격 중앙값이 30초가 아니면 거부한다. 룰의 지속 시간을 표본 수로 계산하기 때문이다. 같은 센서·시각 중복도 거부한다. 원본 `imaks_data/sensors/timeseries_raw.csv`와 `timeseries_annotated.csv`는 그대로 올릴 수 있다.

## 3. UI 연결

```python
from imaks_kg.analysis_agent.service import AnalysisService
from imaks_kg.analysis_agent.ingest import IngestError

svc = AnalysisService()                                   # 세션 폴더: kg_build/analysis_sessions/
overview = svc.create_session(file_bytes, "line.csv")     # 업로드 → 분석. 입력 오류는 IngestError(메시지·details)
reply = svc.ask(overview["session_id"], "가장 심각한 사건 설명해줘",
                focus_incident_id=None,                   # 화면에서 사건 카드를 선택했다면 그 ID
                offline=False)                            # True면 모델 호출 없이 근거 템플릿 답변
svc.get_session(session_id)    # 시작 화면 재조회
svc.conversation(session_id)   # 대화 이력
svc.list_sessions()
```

세션당 질문은 한 번에 하나만 처리한다(처리 중이면 `SessionError`). 직전 답변의 사건은 다음 질문의 "이 사건", "그거" 같은 지시어로 이어진다.

### 3.1 `create_session` / `get_session` 응답 (시작 화면)

| 필드 | 내용 |
|---|---|
| `session_id`, `status`, `file_name`, `created_at` | `status`: `ready` / `failed` |
| `ingest` | 기간, 사용 행 수, 센서 목록, 누락 센서, 버린 컬럼, 제외 행 수 |
| `summary` | 알람 수, 사건 수, 유형별·심각도별·공정별 집계, 실행하지 않은 규칙 |
| `incidents[]` | 사건 카드(심각도 → 시작 시각 순): `id`, `sensor_id`, `station_id`, `start`, `end`, `onset_estimate`, `anomaly_type`, `severity`, `type_reason`, `rule_ids`, `flags` |
| `correlations[]` | 상관 후보: 원인·결과 사건, 시차(분), 근거 규칙, `status`(인과 확정 아님) |
| `suggested_questions[]` | 결과에 맞춘 추천 질문 |
| `warnings[]` | 화면에 항상 표시할 한계 문구 |

### 3.2 `ask` 응답 (질문 화면)

| 필드 | 내용 |
|---|---|
| `status` | `verified`(검증 통과), `unverified`(2회 생성 뒤에도 지적 남음 — 화면에 경고 표시), `generated`(검증 생략), `offline`, `unavailable`(실시간 조회·제어 요청), `clarify`(대상 불분명), `error`(모델 응답 실패, 자동 재시도 없음) |
| `answer` | 마크다운 답변. 요약 → 관측 → 판정 근거 → 권고 조치(문서 기준) → 한계. 근거 ID는 `[inc3-…]`, `[SOP-001:p1:RULE-ST02-01]` 형태 |
| `focus_incident_id` | 답변의 중심 사건. 화면에서 해당 카드 강조에 사용 |
| `incidents[]` | 이번 답변의 근거에 등장한 사건 카드. `cited`: 답변에서 인용했는지 |
| `sensor_windows[]` | 사건 전후 센서 값 차트용: `points[{t,v}]`(최대 약 40점), `reference_thresholds`(nominal·warn·crit), `unit`, `window` |
| `sources[]` | 원문 근거: `chunk_id`, `text`, `cited` |
| `graph_paths[]` | KG 경로(센서 → 사건 → 규칙 → 센서). 그래프 시각화용 |
| `verification` | `passed`, `attempts`, `issues` |
| `intent`, `routing` | 질문 분류 결과와 방식(`deterministic` / `model` / `fallback`) |
| `tool_trace`, `usage`, `run_id`, `seconds` | 실행 기록. `usage.model_calls`, `usage.total_tokens` |

실행마다 `kg_build/analysis_sessions/<session>/questions/<run_id>/`에 계획, 도구 결과, 근거, 모델 원응답, 검증, `answer.json`, 코드·프롬프트 해시를 남긴다. API 키는 저장하지 않는다.

## 4. 질문 처리

| 분류 | 예시 | 도구 |
|---|---|---|
| summary | "어떤 이상이 탐지됐는지 요약해줘" | 결과 요약 |
| summary + 순위 선택 | "가장 심각한 사건 설명해줘", "첫 번째/마지막 사건" | 결과 요약 → 코드가 선택한 사건의 근거·상관·센서 값 |
| list | "실링 전류 이상", "포장 공정 CRITICAL 사건", "창고 온도 드리프트 조치는?" | 조건 목록. 1건이면 그 사건 설명까지 |
| incident | 사건 ID 포함, UI 선택 사건, "이 사건 센서 값은?" | 사건 근거 → 상관 후보 → 센서 구간 값 |
| correlation | "공정 간 상관 후보 설명해줘" | 결과 요약 → 결과 사건별 상관 후보 |
| document | "SOP-002의 DRIFT 정의가 뭐야?" | SOP·데이터시트 검색(BM25 + KG 구조 조회) |
| unavailable | "지금 서버실 온도 실시간 조회해줘" | 없음(연결 없음 안내) |
| 모델 계획 | 규칙으로 정할 수 없는 질문 | 모델이 JSON으로 도구 선택(최대 4개), 코드가 도구·인자·사건 ID 검사 |

공정 이름(충전, 실링, 라벨, 포장, 서버실, 창고, 화학약품 보관소, 연구실, 식당), 센서 종류(온도, 습도, 전류, 압력, 진동, 장력, 속도, 유량, 생산량), 유형, 심각도를 한국어·영어로 인식한다. "가장 심각한 것" 같은 선택은 모델이 아니라 코드가 심각도 → 시작 시각 순으로 한다.

## 5. 답변 규칙과 검증

- 근거는 도구 결과뿐이다. 원문 조치는 KG 규칙의 `responseText`와 SOP 청크에 있는 것만 쓴다.
- 사건은 "규칙 일치 사건 후보", 상관은 "SOP 규칙 패턴이 일치한 후보"로만 표현한다. 원인 후보는 근거 규칙과 시차를 함께 쓴다. `likelihoodScore`가 아직 정의되지 않아 점수는 만들지 않는다.
- 확정 이상·확정 원인·입증된 인과·실시간 상태·조치 실행 완료를 단정하지 않는다. 사건 종료 시각과 구간 통계가 사후 집계임을 밝힌다.
- **결정적 검사:** 답변의 대괄호 인용 ID와 `YYYY-MM-DDTHH:MM` 시각이 모두 근거 안에 있어야 하고, 근거가 있으면 인용이 1개 이상이어야 한다.
- **검증 모델:** 같은 모델에 별도 지침으로 수치·시각·조치의 근거 일치, 인용 적합성, 단정 표현, 질문 충족을 검사시킨다.
- 둘 중 하나라도 지적이 있으면 지적 사항을 넣어 1회 재생성한다. 초안 최대 2회, 검증 최대 2회다. 2회 뒤에도 남으면 `unverified`로 답변과 지적을 함께 돌려준다. 이 경로는 1회 통과로 끝나므로 "2회 연속 통과 수렴 하네스"로 표현하지 않는다.

| 한도 | 값 |
|---|---|
| 도구 호출 | 질문당 6회 |
| 근거 토큰 | 질문당 9,000(실측 최대 약 4,000: 사건 설명) |
| 모델 호출 | 계획 0~1 + 초안 1~2 + 검증 1~2 |
| 대화 이력 | 직전 3턴(답변 800자까지)만 생성 입력에 포함 |
| 전송 실패 | 자동 재시도 없음(`vector.api_call` 정책 그대로) |

### 5.1 모델 제공자

| 제공자 | 선택 | 키(`.env` 또는 환경변수) | 기본 모델 | 비용 |
|---|---|---|---|---|
| OpenAI | 기본값 | `OPENAI_API_KEY` | 기존 설정(`docs/vector_rag_v1/config.json`의 `generation_model`) | 키 소유 계정에 과금 |
| Gemini | `provider="gemini"` / `--provider gemini` | `GEMINI_API_KEY` | `GEMINI_MODEL` 또는 `gemini-3.8-flash` | 결제를 연결하지 않은 Google AI Studio 프로젝트의 키면 무료 등급(호출 수 제한) |

- Gemini는 OpenAI 호환 엔드포인트(`generativelanguage.googleapis.com/v1beta/openai/chat/completions`)로 호출한다(`analysis_agent/providers.py`). 계획·생성·검증 프롬프트와 검사 규칙은 같다. `store`는 빼고 `max_completion_tokens`는 `max_tokens`로 바꿔 보낸다.
- 다른 규칙도 OpenAI 경로와 같다. 자동 재시도는 없고, 원응답을 저장하며, 같은 요청은 저장된 응답을 재사용한다(API 0회). 키는 기록하지 않는다. 응답 모델명이 `models/<id>`나 버전 접미사로 와도 같은 모델이면 요청한 이름으로 맞추고, 원래 값은 `returned_model_raw`에 남긴다. 다른 모델이면 `error`다.
- 무료 등급의 호출 수 한도는 Google이 예고 없이 바꿀 수 있다. 한도를 넘으면 HTTP 429 → `error` 상태로 끝나며 재시도하지 않는다. 결제가 연결된 프로젝트의 키는 무료 한도와 관계없이 과금될 수 있다. 무료 등급 입력의 데이터 처리 조건은 Google 가격 페이지에서 확인한다.
- Gemini는 `reasoning_effort="none"`을 기본으로 보낸다(`GEMINI_REASONING_EFFORT`로 변경). 내부 추론 토큰이 `max_tokens`에 포함되어, 기본값에서는 짧은 답이 잘리는 것을 확인했다. 대기 한도는 300초다.
- 실측(2026-11-15, 무료 등급, `gemini-3.8-flash`): 한 문장 요청도 47~152초가 걸렸다. "가장 심각한 사건 설명하고 조치 알려줘" 1건은 초안 3분 33초, 검증 2분 46초(출력 10토큰)로 총 약 6분 20초, `verified`, 13,544토큰이었다. 출력 길이와 무관하게 오래 걸려 무료 등급의 대기 시간으로 보인다. 시연·UI에는 오프라인 모드나 유료 등급을 쓴다.
- 응답과 실행 기록에 `provider`, `model`을 남긴다. 기존 팀 평가는 OpenAI 모델 기준이므로, Gemini 결과는 따로 표시하고 합산하지 않는다.

## 6. 실행

```powershell
$env:PYTHONPATH="src"; $env:PYTHONUTF8="1"
.\.venv\Scripts\python.exe -m unittest tests.test_analysis_agent

# 분석 세션 (API 0회)
.\.venv\Scripts\python.exe scripts\run_analysis_agent.py analyze --csv imaks_data\sensors\timeseries_raw.csv
.\.venv\Scripts\python.exe scripts\run_analysis_agent.py analyze --reference

# 질문: --offline은 API 0회, 없으면 모델 호출
.\.venv\Scripts\python.exe scripts\run_analysis_agent.py ask --session <session_id> --question "요약해줘" --offline
# OpenAI(.env의 OPENAI_API_KEY, 유료)
.\.venv\Scripts\python.exe scripts\run_analysis_agent.py ask --session <session_id> --question "가장 심각한 사건 설명하고 조치 알려줘"
# Gemini(.env의 GEMINI_API_KEY). --model로 모델 지정 가능
.\.venv\Scripts\python.exe scripts\run_analysis_agent.py ask --session <session_id> --question "가장 심각한 사건 설명하고 조치 알려줘" --provider gemini
```

macOS·Linux는 `.venv/bin/python`과 `export PYTHONPATH=src`로 같다.

## 7. 확인한 것

- 테스트 21개 통과(API 0회).
  - 기준 입력 업로드 결과의 사건·상관 후보가 엔진 단독 실행과 같다.
  - 라벨 컬럼을 붙인 파일과 뗀 파일의 정규화 결과가 같고, 라벨은 읽지 않는다.
  - 최소 3개 컬럼, 일부 센서 파일을 처리한다.
  - 입력 오류 5종(필수 컬럼, 미지원 센서, 중복, 간격, 단위)을 거부한다.
  - 세션 ID 경로 조작을 거부한다.
  - 질문 분류 10종과 후속·UI 선택 사건 연결을 확인했다.
  - 모델 계획 검사(모르는 ID 제거, 잘못된 도구·형식 거부)를 확인했다.
  - 생성 → 검증 통과, 꾸며낸 인용 → 재생성, 2회 미승인 → `unverified`, 다른 모델 응답 → `error`(재시도 없음), 오프라인·실시간 요청 → 모델 호출 0회를 확인했다.
  - Gemini 호출 함수(가짜 HTTP)를 확인했다: 요청 주소·인증 헤더·필드 변환, 모델명 정규화, 다른 모델명 유지, 같은 요청 재사용, 429·키 누락 오류, 서비스 경로의 제공자·모델 기록.
- `timeseries_annotated.csv`(정답 라벨 포함 원본)를 올리면 라벨·임계값 등 12개 컬럼이 버려지고, 엔진 출력 5개 파일이 `kg_build/rule_engine_v3_1`과 바이트 단위로 같다. 오버레이 SHACL 차단 0건, 적재 오류 0건이다.
- 소요 시간(macOS 로컬): 업로드·정규화 약 3초, 엔진 약 5초, 오버레이 검증 약 15초. 도구 실행은 질문당 0.1초 미만이다.

**확인하지 않은 것:** 실제 모델(OpenAI·Gemini)로 생성·검증한 답변 품질과 실제 Gemini 엔드포인트 응답 형식. 아직 실행하지 않았다. 질문당 약 1만~2만 토큰(초안·검증, 재생성 시 두 배)으로 예상한다.

## 8. 한계와 다음 단계

- 업로드 데이터에 대한 과거 기록 분석이다. 실시간 스트림이나 설비 제어는 연결하지 않는다.
- 질문 분류 규칙은 이 데이터셋의 공정·센서 이름에 맞춰져 있다. 규칙에 걸리지 않는 질문은 모델 계획으로 넘어가며, 오프라인 모드에서는 전체 요약으로 답한다.
- σ는 기준 입력에서 고정한 값이다. 다른 라인이나 기간의 데이터라면 σ를 다시 정해야 한다.
- 다음 단계:
  1. 실제 모델로 대표 질문 몇 개를 실행해 답변을 원문과 대조한다(유료, 승인 후).
  2. UI를 연결한다. 업로드 화면 → `create_session`, 사건 카드·차트 → `incidents`·`sensor_windows`, 채팅 → `ask`.
  3. `likelihoodScore`가 정의되면 상관 후보를 점수와 함께 설명한다.
