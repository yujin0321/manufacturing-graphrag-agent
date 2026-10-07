# Final Preprocessing Candidate

이 문서는 `preprocessing-final-candidate` 브랜치의 최종 후보 전처리 방식을 설명한다. 프로젝트 전체 README를 대체하지 않으며, 팀이 최종 전처리안을 고를 때 비교 기준으로 쓰기 위한 작업 문서다.

## 방향

이번 후보안은 두 브랜치의 장점을 합친다.

- `codex/imaks-preprocessing`: 데이터 누수 분리, KG seed 정적 입력/evaluation 분리, MQTT masking, known defect audit, evaluation policy.
- `지훈`: 센서 입력 allowlist 방식, 원본 관측값 보존 검증, PDF page/table/chunk/glyph 보존 방식.

목표는 모델, Ontology, RDF, Neo4j, GraphRAG를 완성하는 것이 아니라, 후속 단계가 안전하게 사용할 수 있는 전처리 입력과 평가 기준을 만드는 것이다.

## 실행

데이터셋이 repository 부모 디렉터리의 `../iMAKS_dataset`에 있을 때:

```bash
python3 scripts/preprocess_final_candidate.py
```

경로를 직접 지정할 때:

```bash
python3 scripts/preprocess_final_candidate.py \
  --dataset-root /path/to/iMAKS_dataset \
  --output-root preprocessed/final_v1
```

이미 생성된 산출물 검증:

```bash
python3 scripts/preprocess_final_candidate.py --validate-only --output-root preprocessed/final_v1
```

## 생성 위치

기본 출력은 `preprocessed/final_v1/`이다. 이 디렉터리는 재생성 가능한 산출물이므로 Git 추적 대상에서 제외한다.

## 핵심 산출물

| 경로 | 역할 |
| --- | --- |
| `inputs/sensors/timeseries_ml_input.csv` | 탐지 입력. `timestamp, zone, station_id, sensor_id, sensor_type, value, unit` 7개 allowlist 컬럼만 포함 |
| `inputs/sensors/timeseries_rule_input.csv` | rule baseline 및 GraphRAG reference용. ML 입력 7컬럼에 threshold 5개 추가 |
| `inputs/sensors/mqtt_stream_input.jsonl` | MQTT 입력 stream. `status`, `alarms`, nested `quality` 제거 |
| `inputs/kg/nodes_static.csv` | 탐지 입력용 정적 KG reference node. `AnomalyEvent`, `SafetyEvent`, `Maintenance` 제외 |
| `inputs/kg/edges_static.csv` | 탐지 입력용 정적 KG reference edge. `monitors`는 canonical `has_sensor` 방향으로 정규화 |
| `documents/pages.jsonl` | 문서별 page text와 source metadata |
| `documents/tables.jsonl` | PDF table 구조, row/cell, bbox 보존 |
| `documents/chunks.jsonl` | 후속 LLM extraction/RAG 후보 입력. 최종 chunking은 아님 |
| `documents/glyph_fixes.csv` | PDF glyph/table cell 보정 로그 |
| `evaluation/row_labels.csv` | `(sensor_id, timestamp)` 기준 row-level evaluation labels |
| `evaluation/anomaly_events.csv` | 기존 KG의 AnomalyEvent 14건. 탐지 입력에서는 제외 |
| `evaluation/rules_ground_truth_original.csv` | ground_truth.csv 86건 원본 보존 |
| `evaluation/kg/*` | 원본 KG 및 dynamic node 분리본 |
| `audit/preprocessing_issues.csv` | 누수, 결함, 미결정 사항 issue log |
| `audit/preprocessing_audit.csv` | 검증 항목별 audit 결과 |
| `summary.json` | 실행 요약 |
| `manifest.json` | raw/source/output checksum |

## 데이터 누수 방지

### Sensor

`timeseries_ml_input.csv`는 allowlist 7개 컬럼만 쓴다. 따라서 다음은 ML/pattern 탐지 입력에 들어가지 않는다.

- `quality`
- `nominal`, `warn_hi`, `crit_hi`, `warn_lo`, `crit_lo`
- `anomaly_label`, `severity`, `alarm_flag`
- `day`, `shift`, `batch_id`

Threshold는 정답 라벨은 아니지만 rule-based 탐지와 pattern-based 탐지를 분리 평가하기 위해 ML 입력에서 제외한다. 대신 `timeseries_rule_input.csv`에 보존한다.

### MQTT

MQTT 원본의 `status`, `alarms`, nested reading `quality`는 label-like field라서 sanitized JSONL에서는 제거한다. 원본 파일은 수정하지 않는다.

### KG

기존 KG의 `AnomalyEvent` 14건은 탐지 평가 입력에서 제외한다. 단, 최종 GraphRAG/Agent 단계에서 사후 설명이나 데모 목적으로 의도적으로 삽입할 수 있으므로 삭제하지 않고 `evaluation/` 아래에 분리 보존한다.

`SafetyEvent`, `Maintenance`도 static input KG에서 분리한다. 기존 KG는 최종 KG가 아니라 reference/evaluation seed로만 다룬다.

## 문서 전처리

SOP/Datasheet는 최종 RAG chunking, embedding, LLM triple extraction을 하지 않는다. 이번 단계에서는 다음 정보를 보존한다.

- `document_id`
- source file
- page
- raw/normalized text
- table rows/cells/bbox
- rule/table/text preview chunk
- glyph/table cell 보정 로그
- file/text checksum

`RULE-ST02-04`처럼 여러 줄로 추출되는 규칙은 한 rule chunk에 보존한다.

## 확인된 주요 이슈

실행 결과 대표 이슈:

- `quality=UNCERTAIN` 25행이 STUCK 25행과 일치한다.
- threshold 비교만으로 일부 anomaly type을 강하게 잡을 수 있으므로 rule/pattern 입력을 분리한다.
- MQTT 21,600건 중 373건이 `status=ALARM`이며 `alarms`에 label-like 정보가 있다.
- `nodes_factory.csv`에는 phantom sensor 4건, 실제 sensor 14건 누락, component 5건 누락, nodeId 충돌이 있어 import 대상에서 제외한다.
- 기존 KG에 AnomalyEvent 14건이 있으므로 탐지 입력에서 제외한다.
- event severity를 threshold 기준으로 다시 계산하면 6건 충돌한다. 원본 label은 수정하지 않고 `rule_severity`를 별도 기록한다.
- access event 156건은 sensor time range 밖에 있고, UNKNOWN person 2건이 있다.
- `alarm_response_log.action_taken`은 corrective action ground truth로 쓰지 않는다.

상세 내용은 `audit/preprocessing_issues.csv`와 `audit/preprocessing_audit.csv`를 확인한다.

## 이번 단계에서 하지 않은 것

다음은 누락이 아니라 후속 단계에서 실험/설계하기 위해 제외했다.

- normalization / z-score
- delta / rolling feature
- smoothing / interpolation
- sliding window
- final RAG chunking
- embedding / Vector DB
- LLM triple extraction
- Ontology mapping
- RDF / TTL 변환
- Neo4j 적재
- relation expansion
- ground_truth 86건 정량 평가
- GraphRAG 구현
- Agent 구현

## 현재 실행 결과

로컬 데이터 기준 검증 결과:

- sensor rows: 211,200
- sensors: 22
- sampling gaps: 0
- MQTT messages: 21,600
- MQTT alarm payloads: 373
- documents/pages/tables: 7 / 10 / 24
- KG nodes/edges: 115 / 341
- static KG nodes/edges: 83 / 269
- dynamic nodes/edges separated: 32 / 50
- AnomalyEvent: 14
- ground_truth rules: 86
- validation: PASS
