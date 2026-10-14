# seed → RDF 개수 대조표 (③)

생성: `imaks_kg.kg.seed_to_rdf` (직접 고치지 말 것). 원본 개수는 CSV에서 센 값이다.

## 입력

| 파일 | 데이터 행 | SHA-256 |
|---|---|---|
| `imaks_data/kg_seed/nodes.csv` | 115 | `3b78a37ff96c39cd5ef2b1b9bf6019d9c951c7926ca4e708e8cb365b9581964e` |
| `imaks_data/kg_seed/edges.csv` | 341 | `18f6556db405f22091a7c5f2bd5d15e2cebe51597ecd33c8da54c84113b46bd3` |

## 노드 (nodes.csv `label`)

| 종류 | 원본 | 변환 | 이월(B) | 이월(⑦) | 제외 | 결과(seed.ttl) | 사유 |
|---|---|---|---|---|---|---|---|
| Component | 9 | 9 | 0 | 0 | 0 | Station 9 | Station으로 1:1 매핑(CLAUDE.md §3) |
| Sensor | 22 | 22 | 0 | 0 | 0 | Sensor 22 | Sensor. 임계값 컬럼은 넣지 않음(B의 ThresholdRule 몫) |
| Maintenance | 8 | 0 | 8 | 0 | 0 | - | MaintenanceRule은 Rule·Document와 함께 B에서 변환 |
| AnomalyEvent | 14 | 0 | 0 | 14 | 0 | - | ⑦ 이후 경로(seed_events_post7.py). ⑥ 입력에 넣지 않음 |
| System | 1 | 0 | 0 | 0 | 1 | - | 질문 5개에 불필요. 처리 미결정(schema_tables 6·9장) |
| Zone | 7 | 0 | 0 | 0 | 7 | - | Zone 클래스 없음. Station.zone 속성으로 흡수 |
| Person | 44 | 0 | 0 | 0 | 44 | - | 범위 밖(CLAUDE.md §3: Person 만들지 않음) |
| SafetyEvent | 10 | 0 | 0 | 0 | 10 | - | 범위 밖(Layer 2 성격, schema_tables 6장) |
| **합계** | **115** | 31 | 8 | 14 | 62 | | |

## 엣지 (edges.csv `type`, 양 끝 노드 종류)

| 종류 | 원본 | 변환 | 이월(B) | 이월(⑦) | 제외 | 대상 관계 | 사유 |
|---|---|---|---|---|---|---|---|
| monitors (Component→Sensor) | 22 | 22 | 0 | 0 | 0 | hasSensor | 정방향 줄. 역방향 줄과 한 관계로 합침 |
| monitors (Sensor→Component) | 22 | 22 | 0 | 0 | 0 | hasSensor | 역방향 줄. 정방향 줄과 한 관계로 합침 |
| feeds_into (Component→Component) | 3 | 3 | 0 | 0 | 0 | feedsInto | 그대로 |
| triggers (Sensor→Maintenance) | 8 | 0 | 8 | 0 | 0 | appliesToSensor | resolves와 합쳐 B에서 변환 |
| resolves (Maintenance→Sensor) | 8 | 0 | 8 | 0 | 0 | appliesToSensor | triggers(Sensor→Maintenance)와 합쳐 B에서 변환 |
| triggers (Sensor→AnomalyEvent) | 14 | 0 | 0 | 14 | 0 | triggers | ⑦ 이후 경로 |
| correlates_with (Sensor→Sensor) | 1 | 0 | 0 | 1 | 0 | correlatesWith | ⑦ 이후 경로 |
| contains (System→Zone) | 7 | 0 | 0 | 0 | 7 | - | System·Zone 적재 안 함 |
| contains (Zone→Component) | 9 | 0 | 0 | 0 | 9 | - | Zone 적재 안 함(Station.zone으로 흡수) |
| part_of (Component→System) | 9 | 0 | 0 | 0 | 9 | - | System 적재 안 함 |
| authorized_for (Person→Zone) | 218 | 0 | 0 | 0 | 218 | - | Person·권한 범위 밖 |
| involves (SafetyEvent→Person) | 10 | 0 | 0 | 0 | 10 | - | SafetyEvent·Person 범위 밖 |
| detected_in (SafetyEvent→Zone) | 10 | 0 | 0 | 0 | 10 | - | SafetyEvent·Zone 범위 밖 |
| **합계** | **341** | 47 | 16 | 15 | 263 | | |

## 결과 관계 수 (변환 줄 → 생성 관계)

| 관계 | 원본 줄 | 생성(변환 코드) | seed.ttl 실제 트리플 |
|---|---|---|---|
| hasSensor | monitors 44줄(양방향) | 22 | 22 |
| feedsInto | feeds_into 3줄 | 3 | 3 |

## seed.ttl 실제 트리플 기준 개수

| 항목 | 개수 | 기대 |
|---|---|---|
| Station | 9 | 9 |
| Sensor | 22 | 22 |
| hasSensor | 22 | 22 |
| feedsInto | 3 | 3 |
| Provenance | 56 | - |
| hasProvenance | 56 | - |
| triples | 482 | - |

## 옮기지 않은 컬럼 (비어 있지 않은 원본 컬럼 중)

| 노드 종류 | 컬럼 | 처리 |
|---|---|---|
| Component | description | 미반영: 온톨로지에 대응 속성 없음 |
| Sensor | critHi | 이월(B): ThresholdRule 몫 |
| Sensor | critLo | 이월(B): ThresholdRule 몫 |
| Sensor | nominalValue | 이월(B): ThresholdRule 몫 |
| Sensor | warnHi | 이월(B): ThresholdRule 몫 |
| Sensor | warnLo | 이월(B): ThresholdRule 몫 |
