# 제조 데이터 전처리 · 온톨로지 · SHACL

현재 작업 범위는 Graph RAG 및 이상 탐지 Agent의 **데이터·지식 모델 기반 구축**입니다. LLM 호출, Graph RAG 검색 엔진 및 Agent 실행은 아직 포함하지 않습니다. `유진` 브랜치에서 진행합니다.

## 실행

Python 3.11 이상 환경에서:

```powershell
python -m pip install -r requirements.txt
python src/pipeline.py
python src/finalize.py
```

로컬 `.deps`가 있으면 해당 패키지를 우선 사용합니다. 원본 `iMAKS_dataset`은 수정하지 않습니다. 생성 결과는 `data/processed`, 검증 및 출처 보고서는 `reports`에 저장됩니다.

## 전처리 계약

- 센서 관측 키는 `(timestamp, sensor_id)`입니다. 중복, 비정상 숫자, 임계값 순서 오류 및 원시값/주석값 불일치는 실행 실패로 처리합니다.
- 날짜 전체를 시간순 60/20/20 비율로 train/validation/test에 배정합니다. 평가 라벨과 alarm_flag는 `evaluation_labels.csv`에 분리합니다. `sensor_observations.csv`에는 이상 라벨이 없습니다.
- 과거 10개 관측의 평균/표준편차는 shift 후 계산합니다. 분할 경계와 1분을 넘는 시간 공백에서 통계를 초기화합니다. 야간/교대 간 공백은 기록하되 보간하지 않습니다.
- GOOD/UNCERTAIN 품질을 보존하고 `usable` 플래그를 제공합니다. 결측치 임의 대체와 정규화는 수행하지 않습니다. 표준화는 후속 모델의 train 데이터로만 학습해야 합니다.
- 시간대 정보가 원본에 없으므로 UTC나 한국 시간을 임의 부여하지 않습니다.
- 인원별 점유 행의 zone_count를 합산하지 않습니다. 시간/구역당 하나의 스냅샷으로 정리합니다. 정적 KG에는 날짜/구역의 최대 점유 스냅샷을 넣고 전체 이력은 CSV에 보존합니다.
- CSI CSV는 헤더 없는 숫자 행렬로 읽고 모든 파일의 subject/gesture/trial, 차원과 기술 통계를 제공합니다. CSI timestamp와 열 의미가 없어 설비 시계열에 시간 정렬하지 않습니다. CSI 모델 학습 시 subject 단위 분할이 필요합니다.
- MQTT는 별도 관측으로 정규화합니다. 원시 CSV와 같은 시각의 수치가 다르므로 덮어쓰거나 병합하지 않습니다.
- PDF는 페이지와 출처를 유지하는 JSONL로 추출합니다. SHA256 원본 manifest를 제공합니다.

## 클래스와 관계

`ontology/manufacturing.ttl`은 OWL/RDFS 클래스와 객체 관계를 정의합니다. System, Zone, Component, Sensor, Observation, Person, AnomalyEvent, SafetyEvent, Maintenance, Rule 및 하위 규칙, Document, AccessEvent, AlarmResponse, OccupancySnapshot을 포함합니다. 이상 하위 클래스는 Spike, Drift, StuckSensor, OutOfRange, Correlated입니다. 원본 이벤트는 anomalyType 속성으로 분류를 보존합니다.

| 관계 | 방향/의미 |
|---|---|
| monitors / hasSensor | Sensor → Component / Component → Sensor |
| locatedIn | Component → Zone |
| feeds_into | Component → downstream Component |
| correlates_with | Sensor → Sensor (상관; 인과 확정 아님) |
| triggers | Sensor → 원본 AnomalyEvent |
| resolves | Maintenance → Sensor |
| authorized_for | Person → Zone |
| governedBy / derivedFrom | Sensor → Rule / Rule → Document |
| observedBy | Observation → Sensor |
| person / zone / event | 출입·대응·점유 기록의 참조 |

seed에서 `monitors`가 양방향으로 쓰여 Component→Sensor 방향은 `hasSensor`로 변환하고 변환 기록을 남깁니다. `contains`, `part_of`는 여러 클래스에 쓰여 강제 domain/range를 두지 않습니다. 원본 ground_truth.csv는 **규칙 목록**이며 관측 정답은 주석 CSV와 AnomalyEvent입니다. 이벤트 정답은 정적 KG에 포함되므로 학습/온라인 검색 시 AnomalyEvent 및 triggers 경로를 제외해야 합니다.

`finalize.py`는 정답 이벤트·대응 결과·출입/점유 이력을 제외한 `retrieval_graph.ttl`도 생성합니다. 후속 Graph RAG의 기본 컨텍스트는 이 그래프를 사용하고, 센서 관측과 인원 이력은 질의 시점 이전의 기록만 검색해야 합니다.

명부에 없는 UNKNOWN 출입 주체는 UnknownActor로 보존합니다. 이름·역할을 임의로 만들어 등록하지 않습니다. SHACL의 Person 참조/필수 속성 제약이 이를 보고합니다.

## SHACL 제약

`ontology/shapes.ttl`은 필수 속성, 개수, datatype, 클래스 참조, 센서 소속, 임계값 순서, 관측 단위/품질, 이벤트 시간 순서, 규칙 출처, 출입 권한 정합성, 역할별 알람 응답 SLA, 점유 한계를 검증합니다. 임계값 초과 관측 자체는 유효한 데이터이며 데이터 오류로 거부하지 않습니다. 점유 한계는 SHACL Warning, SLA 및 정합성 오류는 Violation입니다.

전체 관측 RDF는 `observations.nt`, 정적 KG는 `knowledge_graph.ttl`입니다. 관측 RDF의 구조 제약은 전 행을 배치 검증합니다. 단위 정합성은 원시 센서 그룹으로 생성하고 mutation test로 SHACL 규칙 동작을 검증합니다. 검증 보고서가 non-conformant여도 실제 원본 운영 위반일 수 있습니다. 위반을 삭제해서 통과시키지 않습니다.

## 근거 충돌 및 후속 구현 경계

`reports/source_conflicts.json`에 SOP/사양서/기록의 충돌을 보존합니다. 센서 사용 한계, hazmat 역할, DRIFT와 OUT_OF_RANGE의 지속 시간 정의는 별도 검토가 필요합니다. `ground_truth.csv`의 자연어 조건은 원문 규칙으로 보존하며 모든 시간 규칙을 SHACL 추론 규칙으로 자동 변환했다고 주장하지 않습니다. 5개 이상 유형의 실제 탐지기는 후속 Agent 단계에서 시간 창·기준 σ·우선순위·명령 이력을 명시하고 구현해야 합니다.

LLM 온톨로지 확장을 위한 입력은 document_chunks.jsonl과 현재 클래스/관계/규칙입니다. LLM 출력은 출처 페이지, 대상 센서, 관계, 단위, 조건, confidence를 포함하는 후보로 생성하고 SHACL 및 충돌 검토 후 승인된 후보만 KG에 반영해야 합니다. 현재 구현은 외부 LLM을 호출하지 않고 데이터에 근거한 결정적 기반 모델을 생성합니다.

`reports/preprocessing_summary.json`, `validation_summary.json`, `shacl_report.txt`, `mutation_tests.json`을 확인하면 실행 결과와 한계를 검토할 수 있습니다.
