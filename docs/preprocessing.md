# Preprocessing 작업 설명

이 문서는 `preprocessing-sumin` 브랜치에서 구현한 전처리 작업만 설명한다. 프로젝트 전체 README를 대체하지 않는다.

## 목적

이번 전처리는 최종 ML 모델, Ontology, Knowledge Graph, Graph RAG, Agent를 구현하기 전 단계다. 목표는 원본 제조 데이터셋의 구조와 품질을 검증하고, 탐지 입력과 평가 정답을 분리하며, 이후 Ontology/KG 구축에 필요한 ID 대응 관계와 문서 출처 정보를 재현 가능하게 정리하는 것이다.

원본 데이터의 이상값은 삭제하거나 보정하지 않는다. ground truth에서 오류 후보가 발견되어도 원본을 수정하지 않고 issue log에 기록한다.

## 입력 데이터

스크립트는 iMAKS 제조 합성 데이터셋 디렉터리를 입력으로 받는다. 기본 경로는 repository의 부모 디렉터리에 있는 `../iMAKS_dataset`이다.

사용하는 주요 입력은 다음과 같다.

- `sensors/timeseries_raw.csv`
- `sensors/timeseries_annotated.csv`
- `sensors/mqtt_payloads.json`
- `rules/*.pdf`
- `datasheets/*.pdf`
- `kg_seed/nodes.csv`
- `kg_seed/edges.csv`
- `kg_seed/ground_truth.csv`
- `kg_seed/nodes_factory.csv`
- `human/*.csv`
- `csi/*/*.csv`

데이터셋을 repository 안으로 복사하지 않는다.

## 수행한 전처리

### Sensor

`timeseries_raw.csv`에 대해 timestamp parsing, timestamp ordering, sensor별 30초 sampling interval, `(timestamp, sensor_id)` 중복, 결측, numeric dtype, sensor type별 unit 일관성, `sensor_id` 구조를 검증한다.

탐지 입력용 clean 데이터에서는 다음 컬럼을 제외한다.

- `quality`
- `nominal`
- `warn_hi`
- `crit_hi`
- `warn_lo`
- `crit_lo`
- `anomaly_label`
- `severity`
- `alarm_flag`

`timeseries_annotated.csv`는 모델 입력으로 사용하지 않고 평가 라벨 파일로 분리한다. threshold 컬럼은 정답 라벨 자체가 아니라 실제 운영 사전 지식이지만, pattern 기반 탐지와 rule-based 탐지를 분리 평가하기 위해 clean 입력에서는 제외하고 rule reference 파일에 보존한다.

### MQTT

탐지 입력용 MQTT JSONL에서는 `status`, `alarms`, alarm message를 제거한다. nested reading의 `quality`도 clean stream에서는 제거한다. 원본 `mqtt_payloads.json`은 수정하지 않는다.

### SOP / Datasheet

이번 단계에서는 최종 RAG chunking을 하지 않는다. PDF별로 `document_id`, `source_file`, `page`, `section_title`, `text`, table-like rows, extraction order를 보존한 중간 JSONL을 만든다.

추출 결과는 나중에 Ontology v1 설계와 문서 기반 triple extraction을 준비하기 위한 preview다. embedding, Vector DB 적재, LLM extraction은 수행하지 않는다.

### KG Reference

기존 `nodes.csv`, `edges.csv`는 최종 KG가 아니라 reference/evaluation 자료로만 검증한다.

검증 항목은 nodeId 중복, node label 분포, edge relation type, dangling edge, duplicate edge, bidirectional relation, Sensor node와 raw timeseries sensor_id 대응이다.

`nodes_factory.csv`는 설비·센서 카탈로그로 신뢰할 수 없어 import 대상에서 제외한다. 확인된 문제는 issue log에 기록한다.

기존 KG의 `AnomalyEvent` 14건은 탐지 평가 입력에서 제외한다. 단, 최종 GraphRAG/Agent 단계에서 사후 설명이나 데모 목적으로 의도적으로 삽입할 수 있는 데이터이므로 삭제하지 않는다.

### Ground Truth

다음 정답 데이터를 분리 관리한다.

- `timeseries_annotated.csv`의 anomaly labels: 이상 탐지 평가용
- 기존 KG의 `AnomalyEvent` 14건: event-level 평가 및 후속 데모용
- `kg_seed/ground_truth.csv` 86건: 향후 LLM rule/triple extraction 평가용

이번 단계에서는 `ground_truth.csv` 86건과 LLM 추출 결과를 대조하지 않는다.

### Human / Access / CSI

이번 단계에서는 최소 검증만 수행한다.

- 파일 구조
- access event 시간 범위
- `UNKNOWN` person
- occupancy label 성격 컬럼
- CSI file count와 subject count

Human/Access/CSI feature engineering, SafetyEvent 탐지, CSI 행동 인식 분석은 수행하지 않는다.

## 데이터 누수 방지 정책

- `quality`: `UNCERTAIN`이 STUCK 라벨과 일치하므로 clean 탐지 입력에서 제외한다. 원본과 issue log에는 보존한다.
- threshold 5개: 실제 운영 사전 지식이지만 clean ML/pattern 입력에서는 제외한다. rule baseline과 Graph RAG reference용 파일에 보존한다.
- annotated labels: `anomaly_label`, `severity`, `alarm_flag`는 평가용으로만 사용한다.
- MQTT `status`, `alarms`: alarm state/type/severity를 직접 포함하므로 clean stream에서 제거한다.
- KG `AnomalyEvent` 14건: 탐지 평가 입력에서 제외한다. 최종 Agent 설명/데모 단계에서는 의도적으로 사용할 수 있다.

## 생성되는 파일

기본 출력 위치는 `processed/`이며, 이 디렉터리는 git 추적에서 제외한다.

| 파일 | 역할 |
| --- | --- |
| `processed/sensors/timeseries_input_clean.csv` | 탐지 입력용 clean 시계열. 라벨과 누수 컬럼 제거 |
| `processed/sensors/timeseries_eval_labels.csv` | `(timestamp, sensor_id)` 기준 평가 라벨 |
| `processed/sensors/timeseries_rule_reference.csv` | threshold/rule baseline 및 Graph RAG reference용 |
| `processed/sensors/mqtt_input_stream.jsonl` | alarm/status 정보를 제거한 MQTT 입력용 stream |
| `processed/documents/document_index.csv` | 문서 ID, source file, page count, checksum |
| `processed/documents/document_extraction_preview.jsonl` | source/page/text/table-like rows를 보존한 문서 중간 표현 |
| `processed/kg/kg_reference_audit.csv` | KG seed 구조 검증 결과 |
| `processed/issues/preprocessing_issues.csv` | 데이터 결함, 누수, 미결정 사항 |
| `processed/preprocessing_log.json` | 실행 정보, checksum, 정책, 요약 통계 |

## 실행 방법

기본 데이터셋 경로가 `../iMAKS_dataset`일 때:

```bash
python3 scripts/validate_preprocessing.py
```

데이터셋 경로를 직접 지정할 때:

```bash
python3 scripts/validate_preprocessing.py --dataset-root /path/to/iMAKS_dataset --output-root processed
```

PDF 추출에는 `pdftotext`와 `pdfinfo`가 있으면 이를 사용한다. 없으면 `pypdf` fallback을 시도한다.

## 검증 방법

전처리를 재실행하면 생성과 검증이 함께 수행된다.

이미 생성된 산출물만 검증하려면:

```bash
python3 scripts/validate_preprocessing.py --validate-only --output-root processed
```

검증은 다음을 확인한다.

- 필수 output 존재 여부
- clean input에 forbidden leakage column이 없는지
- MQTT stream에 `status`, `alarms`, nested `quality`가 남아 있지 않은지
- document preview에 `document_id`, `source_file`, `page`, `text`가 있는지

## 현재 단계에서 하지 않은 것

다음은 누락이 아니라 후속 단계에서 각자 실험하기 위해 의도적으로 제외했다.

- normalization
- z-score
- delta / rolling feature engineering
- smoothing / interpolation
- sliding window 생성
- 최종 document chunking
- embedding
- Vector DB 적재
- LLM triple extraction
- Ontology/KG 구축
- RDF/TTL 변환
- Neo4j 적재
- relation expansion
- GraphRAG 구현
- Agent 구현

## 발견된 데이터 이슈

실행 결과로 확인된 issue는 `processed/issues/preprocessing_issues.csv`에 기록된다. 대표적으로 다음 이슈를 기록한다.

- `quality=UNCERTAIN`과 STUCK 라벨 일치
- threshold 컬럼의 rule-based 탐지 가능성
- MQTT `status`, `alarms` 누수
- `nodes_factory.csv`의 phantom sensor, 누락 sensor/component, nodeId 충돌
- `monitors` 양방향 관계
- 기존 KG의 `AnomalyEvent` 14건
- SPD ground truth 불일치 후보
- GT-0007 severity 검토 필요
- access event 시간 범위 차이
- `UNKNOWN` person
- `alarm_response_log.action_taken`을 조치 정답으로 쓰면 안 되는 문제
