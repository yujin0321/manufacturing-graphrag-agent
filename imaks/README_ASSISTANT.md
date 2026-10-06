# 한국어 검색과 조치 조건 검증

확장된 세 방식·유형별·반복 LLM 비교는 `notebooks/04_graphrag_fair_benchmark.ipynb`와 `README_BENCHMARK_V2.md`에 있습니다.

`notebooks/03_korean_conditions_evaluation.ipynb`를 VS Code에서 열면 실행 결과와 직접 질문할 수 있는 셀이 있습니다. 커널은 프로젝트 `.venv`입니다.

## 이번 구현

- 한국어 설비 별칭·센서 종류 식별과 기술 용어 보강. 모호하거나 데이터에 없는 센서는 조치를 제시하지 않습니다.
- 기존 8개와 분리된 후속 질문 20개: 근거 검색 14개, 모호성·지원 범위 6개. 일부 규칙·의도는 기존과 겹치며, 같은 개발자가 작성해 외부 독립 평가가 아닙니다.
- SOP 원문에 연결된 실행 규칙 12개. 부등호 경계·단위·지속 시간·작업자 명령·시계열 연속성 검증.
- LLM 비교 요청 28개 준비. 동일 모델·프롬프트 비교용이며 실제 LLM 호출은 하지 않았습니다.

## 고정 질문셋 결과

| 방법 | 근거 하나 이상 회수 Hit@3 | 필수 근거 회수율 Recall@3 | MRR@3 |
|---|---:|---:|---:|
| 한국어 원문을 기존 검색에 입력 | 85.7% | 82.1% | 65.5% |
| 한국어 용어 보강 + 일반 검색 | 100% | 92.9% | 90.5% |
| 한국어 용어 보강 + 그래프 검색 | 92.9% | 85.7% | 81.0% |

이 질문셋에서는 일반 검색이 더 좋았습니다. 그래프 확장이 관련 없는 주변 설비를 추가해 검색 순위를 떨어뜨릴 수 있습니다. 결과를 보고 가중치를 재조정하지 않았습니다. 센서 식별/질문 보류 상태는 고정된 20개에서 예상과 모두 일치했지만, 일반 한국어 성능을 입증하는 수치는 아닙니다.

센서 데이터시트 비교 질문은 문서 회수 여부만 평가합니다. 특정 모델이 실제 설비에 장착됐다는 증거까지 검증한 것은 아닙니다.

## 조건 검증 방식

`met`, `not_met`, `insufficient_data`를 구분합니다. 지원 규칙이 없으면 `unsupported_rule_subset`으로 표시합니다. 지원되지 않는 센서를 정상으로 간주하지 않습니다.

질문 속 '212도'를 실제 측정값으로 자동 채택하지 않습니다. 측정값·단위·시각이 있는 구조화 입력으로 조건을 확인합니다. 입력 데이터의 진실성을 외부 센서와 대조한 것은 아닙니다.

현재 구현 정책은 30초 수집 간격과 최대 30초 최신성입니다. 이는 데이터에 맞춘 구현 가정이며 SOP 문구 자체가 아닙니다. 단위 변환을 자동 수행하지 않고 불일치 시 보류합니다. 같은 센서에서 여러 규칙이 충족되면 높은 우선순위 조치를 선택하며, 낮은 우선순위 검사 결과도 보존합니다.

실제 ST02 raw 관측(2026-01-06 08:30, 212.8202°C)은 SOP-001 p.1 RULE-ST02-02의 210°C 초과 조건을 충족했습니다. 문서상 조치와 근거는 `assistant_outputs/first_verified_action.json`에 있습니다. 과거 기록 재현이며 실시간 설비 제어는 하지 않습니다.

## 직접 질문

```powershell
.\.venv\Scripts\python.exe imaks_assistant.py --question "포장기 속도가 떨어졌어. 관련 전류 규칙은?" --sensor ST04_PACKAGING_SPD --mode text
```

관측 데이터 없이 실행하면 문서 후보만 제시합니다. 검증하려면 JSON 파일을 `--observation`으로, 그 기록에 맞는 기준 시각을 `--as-of`로 지정합니다. 예시 형식:

```json
{
  "sensor_id": "ST04_PACKAGING_SPD",
  "timestamp": "2026-01-08T09:00:00",
  "value": 0.9,
  "unit": "m/s",
  "operator_command": false
}
```

지속 시간·정체 규칙에는 동일 센서/단위의 `history` 배열(각 원소: sensor_id, timestamp, value, unit)이 필요합니다. 배열은 과거부터 정렬하고 현재 관측까지 포함해야 합니다. 공칭 대비 전류 규칙에는 `nominal`도 필요합니다.

## LLM 비교 준비

`assistant_outputs/llm_requests.jsonl`에는 일반/그래프 검색별 14개 요청이 있습니다. `model=null`, `status=not_run`입니다. 모델 선택 전에는 답변 품질 결과가 없습니다.

모델을 선택한 후 같은 모델·temperature=0으로 실행하고, JSONL 답변에 요청의 `id`, `mode`, `prompt_sha256`와 실제 `model`, `temperature`, `answer`, `citations`(chunk_id 배열)를 기록합니다. `proposed_actions`, `uncertainties`도 프롬프트가 요청합니다. 질문에 없는 검증된 관측값을 생성해 넣지 마세요.

```powershell
.\.venv\Scripts\python.exe evaluate_llm_answers.py your_answers.jsonl
```

검사기는 모든 쌍의 동일 모델·온도·시스템 프롬프트 해시와 인용 ID를 확인합니다. 인용 ID가 유효해도 주장 내용이 문서에 뒷받침된다는 뜻은 아닙니다. 결과 CSV의 의미상 근거·조건 정확성·조치 일치 칸은 사람이 채워야 합니다. 답변 파일의 실제 API 실행 여부와 모델 출처는 독립적으로 인증하지 않습니다.

## 재현

기존 02 단계 출력이 있어야 합니다. 프로젝트 루트에서:

```powershell
.\.venv\Scripts\python.exe imaks_assistant.py
.\.venv\Scripts\python.exe -m unittest test_assistant test_answer_review test_pipeline -v
.\.venv\Scripts\python.exe -c "from test_assistant import save_condition_report; save_condition_report()"
.\.venv\Scripts\python.exe build_assistant_notebook.py
```

규칙 등록부와 질문·근거·검사 결과는 `assistant_outputs`에 저장됩니다. API 키나 추가 외부 패키지는 필요하지 않습니다.
