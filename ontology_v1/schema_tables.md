# iMAKS 온톨로지 v1: 클래스·관계·속성 표 (초안)

작성 2026-10-07. `ontology.ttl`과 1:1로 대응한다(클래스 16, 객체 관계 11, 데이터 속성 45). 근거 표기: **확정**은 `CLAUDE.md` 또는 `work_log.md`(D1~D6, 설계 #1~#6, 열린 쟁점 #1~#5)에서 확정한 것, **제안**은 재도출(`reports/teammate_comparison.md` 6장)에서 채택했지만 개별로 확정하지는 않은 것이다.

## 1. 표기 규칙
- 이름공간: 어휘 `https://example.org/imaks/v1#`(prefix `im:`), 임시 IRI이다. 인스턴스 IRI는 원본 이름을 그대로 쓴다(예: `ST02_SEALING`).
- Neo4j에서는 **노드 라벨 = 클래스 이름, 관계 타입 = 객체 관계 이름, 노드·관계 속성 = 데이터 속성 이름**을 그대로 쓴다. camelCase 대응표는 필요 없다(열린 쟁점 #5).
- OWL의 domain·range는 의미 선언이며, 필수값·개수·누수 검사는 `shapes.ttl`(4단계)이 맡는다.
- 속성 이름은 ⑥ 입력 금지 목록(`harness/forbidden_columns.txt`)의 단어를 단독으로 쓰지 않는다. 그래서 심각도 계열은 `ruleSeverity`, `datasetSeverity`처럼 접두어를 붙였다.

## 2. 클래스 (16개)
| 이름 | 의미 | 원본 대응 | 예시 | 근거 |
|---|---|---|---|---|
| `Station` | 공정(스테이션). 생산 4 + 보조구역 5 | Component 9개 (이름이 같아 1:1) | ST02_SEALING (N0013) | 확정 (CLAUDE.md §3, 설계 #6) |
| `Sensor` | 센서 22개 | Sensor 22개 | ST02_SEALING_CUR | 확정 (CLAUDE.md §3) |
| `Rule` | SOP에서 뽑은 조건-조치 규칙(상위 클래스) | 없음(새로 추출) | RULE-ST02-02 | 확정 (열린 쟁점 #3) |
| `OperationalRule` | SOP-001 운전 규칙 | 정답 규칙 파일(평가용)의 OperationalRule | RULE-ST02-02 | 확정 (열린 쟁점 #3) |
| `ThresholdRule` | SOP-002 임계값 규칙과 이상 유형 정의 | 정답 규칙 파일(평가용)의 ThresholdRule | RULE-THR-ST02-TMP-CRIT | 확정 (열린 쟁점 #3) |
| `MaintenanceRule` | SOP-003 정비 규칙 | Maintenance 8개 (MAINT-01~08) | MAINT-02 | 확정 (D5, 열린 쟁점 #3) |
| `AccessRule` | SOP-004 접근·인원·확인시간 규칙. Person과 연결하지 않음 | 정답 규칙 파일(평가용)의 AccessRule | RULE-ACCESS-01 | 확정 (D5, 열린 쟁점 #3) |
| `Document` | 출처 PDF 7개 | 없음 | SOP-001 | 확정 (열린 쟁점 #3) |
| `Provenance` | 출처 기록(문서 위치 / seed CSV 행 / 시계열 구간) | 없음 | SOP-002 1쪽 표 2의 TMP 행 | 확정 (D3, CLAUDE.md §4) |
| `AnomalyEvent` | 이상 이벤트(⑦ 이후만 인스턴스화) | AnomalyEvent 14개 | (⑦ 이후) | 확정 (CLAUDE.md §4, 설계 #1) |
| `Spike` | 5분 미만의 순간 변화 | anomalyType SPIKE | | 확정 (설계 #1) |
| `Drift` | 한 방향으로 서서히 계속되는 변화 | anomalyType DRIFT | | 확정 (설계 #1) |
| `StuckSensor` | 값이 고정된 상태 | anomalyType STUCK | | 확정 (설계 #1) |
| `OutOfRange` | 경고 한계 밖에 한동안 머묾 | anomalyType OUT_OF_RANGE | | 확정 (설계 #1) |
| `Correlated` | 다른 센서 이상의 영향으로 시차를 두고 따라 변함 | anomalyType CORRELATED | | 확정 (설계 #1) |
| `CausalLink` | **SHACL 검증 전용.** Neo4j에는 만들지 않음 | 없음 | | 확정 (D2) |

- `Spike`~`Correlated`는 서로 **Disjoint**(한 이벤트는 한 유형), `OperationalRule`~`AccessRule`도 서로 Disjoint이다(`CLAUDE.md` ②).

## 3. 객체 관계 (11개)
| 이름 | 방향 | 의미 | 원본 대응 | 근거 |
|---|---|---|---|---|
| `hasSensor` | Station → Sensor | 스테이션이 센서를 가짐 | monitors 양방향 44줄(22쌍)을 이 방향 하나로 정리 | 확정 (D4, 설계 #4) |
| `feedsInto` | Station → Station | 물리적 공정 순서(인과 아님) | feeds_into 3개 | 확정 (CLAUDE.md §3) |
| `correlatesWith` | Sensor → Sensor | 문서 근거 센서 상관 1건. 신규 발견 아님, ⑦ 이후 경로에서만 적재 | correlates_with 1개 | 확정 (설계 #2, §4) |
| `triggers` | Sensor → AnomalyEvent | 센서가 이상 이벤트를 발생시킴(원본 방향) | triggers 중 Sensor→AnomalyEvent 14개 | 확정 (설계 #2) |
| `causallyAffects` | Station → Station | 원인 공정 → 결과 공정 인과 후보. 속성은 5장 | 없음(⑥이 생성) | 확정 (CLAUDE.md §3, D2) |
| `appliesToSensor` | Rule → Sensor | 규칙이 적용되는 센서. 정비 규칙도 이 관계 사용 | triggers(Sensor→Maintenance)와 resolves(Maintenance→Sensor)를 합침 | 확정 (설계 #3, 열린 쟁점 #4) |
| `actionTarget` | Rule → Station | 규칙의 조치 대상 스테이션 | 없음(④가 생성) | 제안 (CQ4) |
| `sourceDocument` | Rule → Document | 규칙이 나온 문서 | 없음 | 제안 (CQ3·CQ4) |
| `hasProvenance` | (주로 Rule) → Provenance | 출처 기록 연결 | 없음 | 확정 (D3) |
| `hasCause` | CausalLink → Station | 검증 변환 전용: 원인 공정 | 없음 | 확정 (D2) |
| `hasEffect` | CausalLink → Station | 검증 변환 전용: 결과 공정 | 없음 | 확정 (D2) |

## 4. 데이터 속성 (45개)

### 4-1. 공통
| 이름 | 대상 | 자료형 | 의미 | 예시 | 근거 |
|---|---|---|---|---|---|
| `identifier` | Station, Sensor, Rule, Document | string | 외부 식별자(원본 name, ruleId, 문서 ID) | ST02_SEALING_CUR | 확정 |
| `sourceNodeId` | Station, Sensor, MaintenanceRule | string | 원본 nodeId (역추적용) | N0013 | 확정 (D3) |

### 4-2. Station·Sensor
| 이름 | 대상 | 자료형 | 의미 | 예시 | 근거 |
|---|---|---|---|---|---|
| `stationType` | Station | string | 9개 값 중 하나 | SEALING | 확정 |
| `zone` | Station | string | 속한 구역 이름. Zone 클래스 대신 속성 | Production Area | 확정 (설계 #6) |
| `sensorType` | Sensor | string | 9개 값 중 하나 | CUR | 확정 |
| `unit` | Sensor | string | 원문 단위 그대로 | A | 확정 |

### 4-3. Rule
| 이름 | 대상 | 자료형 | 의미 | 예시 | 근거 |
|---|---|---|---|---|---|
| `conditionText` | Rule | string | 조건 문장 | TMP > 210°C (CRITICAL) | 제안 |
| `responseText` | Rule | string | 조치 문장. Task 클래스 대신 이 속성 | emergency stop ST02, ST03, ST04 | 확정 (열린 쟁점 #3) |
| `ruleSeverity` | Rule | string | 문서가 정한 등급 | CRITICAL | 확정 |
| `extractionMethod` | Rule | string | 규칙 생성 방법 | LLM 추출 / 표 결정적 변환 | 제안 (재도출 6장) |
| `priority` | MaintenanceRule | string | 정비 우선순위 | HIGH | 확정 (D5) |
| `nominal` | ThresholdRule | decimal | 평상값 | 185.0 | 확정 |
| `warnHi` | ThresholdRule | decimal | 경고 상한 | 195.0 | 확정 |
| `warnLo` | ThresholdRule | decimal | 경고 하한 | 175.0 | 확정 |
| `critHi` | ThresholdRule | decimal | 위험 상한(룰·⑧⑨ 경로에서만 사용, ⑥ 입력 아님) | 210.0 | 확정 (D1) |
| `critLo` | ThresholdRule | decimal | 위험 하한 | 165.0 | 확정 (D1) |

### 4-4. Document
| 이름 | 대상 | 자료형 | 의미 | 예시 | 근거 |
|---|---|---|---|---|---|
| `title` | Document | string | 문서 제목 | Standard Operating Procedures — Production Line A | 확정 |
| `sourcePath` | Document | string | 저장소 기준 상대 경로 | imaks_data/rules/SOP_001_OperatingProcedures.pdf | 확정 (CLAUDE.md §7) |
| `sourceSha256` | Document | string | PDF 바이너리 SHA-256(64자 16진수) | | 확정 (§4) |
| `pageCount` | Document | positiveInteger | 쪽수 | 2 | 확정 |

### 4-5. Provenance
출처 종류(`sourceKind`)에 따라 쓰는 필드가 다르다(`CLAUDE.md` §4, D3).
| 이름 | 대상 | 자료형 | 의미 | 쓰는 종류 | 근거 |
|---|---|---|---|---|---|
| `sourceKind` | Provenance | string | `document`, `seedCsv`, `timeseries` | 공통 | 확정 (D3) |
| `page` | Provenance | positiveInteger | 쪽 번호 | document | 확정 (D3) |
| `charStart` | Provenance | nonNegativeInteger | 쪽 텍스트 안 시작 위치 | document | 확정 (§4) |
| `charEnd` | Provenance | nonNegativeInteger | 끝 위치 | document | 확정 (§4) |
| `tableId` | Provenance | string | 표 ID | document(표) | 확정 (§4) |
| `rowIndex` | Provenance | positiveInteger | 표 행 번호 | document(표) | 확정 (§4) |
| `colIndex` | Provenance | positiveInteger | 표 열 번호 | document(표) | 확정 (§4) |
| `bbox` | Provenance | string | 좌표 x0,y0,x1,y1 | document(표) | 확정 (§4) |
| `sourceQuote` | Provenance | string | 근거 원문 인용 | document | 제안 (재도출 6장) |
| `textSha256` | Provenance | string | 인용 원문 SHA-256 | document | 확정 (§4) |
| `fileName` | Provenance | string | 원본 파일 경로 | seedCsv, timeseries | 확정 (D3) |
| `sourceRowId` | Provenance | string | 원본 행 식별자 | seedCsv | 확정 (D3) |
| `sensorId` | Provenance | string | 센서 ID | timeseries | 확정 (D3) |
| `intervalStart` | Provenance | dateTime | 구간 시작 | timeseries | 확정 (D3) |
| `intervalEnd` | Provenance | dateTime | 구간 끝 | timeseries | 확정 (D3) |
| `fileSha256` | Provenance | string | 시계열 파일 SHA-256 | timeseries | 확정 (D3) |

### 4-6. 구간 ID와 AnomalyEvent
| 이름 | 대상 | 자료형 | 의미 | 예시 | 근거 |
|---|---|---|---|---|---|
| `windowId` | Provenance(timeseries), AnomalyEvent, `causallyAffects` 관계 | string | ⑥이 정한 후보 구간 ID. 센서+시각 기반이고 GT id가 아님 | ST04_PACKAGING_SPD@2026-01-08T09:45:00/2026-01-08T10:15:00 | 확정 (열린 쟁점 #2) |
| `startTime` | AnomalyEvent | dateTime | 시작(⑦ 이후) | | 확정 (설계 #2) |
| `endTime` | AnomalyEvent | dateTime | 끝(⑦ 이후) | | 확정 (설계 #2) |
| `magnitude` | AnomalyEvent | decimal | 변화 크기(⑦ 이후) | | 확정 (설계 #2) |
| `datasetSeverity` | AnomalyEvent | string | 데이터셋이 붙인 심각도. 규칙 판정과 분리 보존 | WARNING | 확정 (결함 B07) |

### 4-7. causallyAffects의 속성
| 이름 | 자료형 | 의미 | 근거 |
|---|---|---|---|
| `hasLag` | decimal | 시차(분, 0 이상) | 확정 (CLAUDE.md §3) |
| `hasEvidence` | string | `TimeseriesCorrelation`, `SOPRule`, `Both` 중 하나 | 확정 (§3) |
| `likelihoodScore` | decimal | 0.0~1.0. 0.6 이상·이벤트당 상위 3개 필터는 적재 스크립트가 처리 | 확정 (§3) |
| `ruleIds` | string(여러 개 가능) | SOP 규칙 근거 번호표(Rule의 identifier) | 확정 (열린 쟁점 #1) |

(`windowId`는 4-6의 같은 속성을 `causallyAffects`도 쓴다.)

## 5. causallyAffects 표현: Neo4j와 RDF 검증 변환 (D2, 열린 쟁점 #1·#2)
| 개념 | Neo4j (KG 본체) | RDF 검증 변환 (SHACL용) |
|---|---|---|
| 인과 연결 | `(Station)-[:causallyAffects {…}]->(Station)` | `CausalLink` 노드가 `hasCause`, `hasEffect`로 두 Station을 가리킴 |
| 속성 5개 | 관계 속성으로 직접 | `CausalLink`의 데이터 속성 |
| 근거 연결 | `ruleIds`(규칙 번호), `windowId`(구간 번호)를 값으로 | 같은 값을 `CausalLink`에 |
| 구간별 점수 | 같은 스테이션 쌍도 `windowId`마다 관계를 따로 둠 | `CausalLink`도 구간마다 따로 |

**적재 검증(열린 쟁점 #1):** 적재 스크립트가 아래를 검사하고 하나라도 틀리면 그 관계의 적재를 거부한다.
1. `ruleIds`의 모든 번호가 실제 `Rule`의 `identifier`로 존재하는가
2. `windowId`가 ⑥이 만든 후보 구간 목록(timeseries 유래 `Provenance`의 `windowId`)에 있는가
3. `hasEvidence`가 `SOPRule`/`Both`면 `ruleIds` 1개 이상, `TimeseriesCorrelation`/`Both`면 `windowId` 필수인가
4. `likelihoodScore`가 0.0~1.0이고 `hasLag`가 0 이상인가
5. 적재 후 감사 질의: "`ruleIds`가 가리키는 `Rule`이 없는 관계 = 0개"(`stage-check`에 추가), `Rule.identifier`에 UNIQUE 제약

## 6. 만들지 않은 것과 이유
| 대상 | 이유 |
|---|---|
| Component(부품 계층) | Station 수준까지만 다룬다(CLAUDE.md §3). 원본 Component는 Station으로 매핑 |
| Person, authorized_for | 설비 이상 원인과 무관, Layer 2 성격(D5) |
| Zone | Station의 `zone` 속성으로 흡수(설계 #6) |
| Task 클래스 | 보류. 조치는 `responseText` 속성으로 둠(열린 쟁점 #3). **`CLAUDE.md` ②의 요구라 ④ 시작 전에 재검토** |
| System | 질문 5개에 필요 없음. 원본 노드 1개의 처리는 미결정으로 기록 |
| QualityDefect, SafetyEvent | 품질불량 제외(CLAUDE.md §3), SafetyEvent는 Layer 2 성격 |
| Observation(시계열 표본 노드) | 시계열은 CSV로 두고 KG에 올리지 않음 |
| SWRL 보완 규칙 | 선택 사항(CLAUDE.md §3). 이번 스프린트에서 제외 |

## 7. 원본 KG → 새 스키마 대응 (seed → ③ 변환)
| 원본 | → 새 스키마 | 비고 |
|---|---|---|
| Component 노드 9개 | `Station` | `sourceNodeId`에 nodeId, `stationType`, `zone`은 원본 `zone` 값 |
| Sensor 노드 22개 | `Sensor` | `identifier`=name, `sensorType`, `unit` |
| Maintenance 노드 8개 | `MaintenanceRule` | `identifier`=ruleId(MAINT-01~08), `responseText`=action, `priority`. action 문구가 SOP-003과 조금 다르므로 매핑표를 둔다(CLAUDE.md §4) |
| AnomalyEvent 노드 14개 | `AnomalyEvent` 하위 유형 | ⑦ 이후만. `startTs`→`startTime`, `endTs`→`endTime`, 원본 심각도 컬럼→`datasetSeverity`. `gtId`, `causedBy`는 평가용이라 KG에 올리지 않음 |
| Zone 7개, System 1개 | 적재 안 함 | `zone`은 Station 속성으로 흡수. System은 미결정 |
| Person 44개, SafetyEvent 10개 | 적재 안 함 | 범위 밖 |
| 엣지 monitors(44줄, 양방향) | `hasSensor` 22개 | 원본 두 줄을 같은 관계에 연결해 보존 |
| 엣지 feeds_into(3) | `feedsInto` | 그대로 |
| 엣지 correlates_with(1) | `correlatesWith` | ⑦ 이후 경로에서만 적재. `ruleRef`는 규칙 번호 근거로 보존 |
| 엣지 triggers(22) | Sensor→AnomalyEvent 14개는 `triggers`(⑦ 이후), Sensor→Maintenance 8개는 `appliesToSensor`로 합침 | 설계 #2, #3 |
| 엣지 resolves(8) | `appliesToSensor`로 합침 | triggers(Sensor→Maintenance)와 같은 8쌍 |
| 엣지 contains(16), part_of(9) | 적재 안 함 | Zone·System 없음 |
| 엣지 authorized_for(218), involves(10), detected_in(10) | 적재 안 함 | 범위 밖 |

## 8. 질문 5개 커버리지 확인 (docs/competency_questions.md)
| 질문 | 필요한 것 | 이 스키마에서 |
|---|---|---|
| CQ1 원인 후보 상위 3개 | Station, Sensor, `hasSensor`, `causallyAffects` + 속성 | 모두 있음 |
| CQ2 근거 종류와 시차 | `causallyAffects` 속성, `feedsInto`, `correlatesWith`, `ruleIds` | 모두 있음 |
| CQ3 출처 | Rule, Document, `Provenance`, `hasProvenance`, `ruleIds`, `windowId` | 모두 있음 |
| CQ4 SOP 조치 | Rule, `appliesToSensor`, `actionTarget`, `sourceDocument`, `responseText`, `critHi` | 모두 있음 |
| CQ5 정비 규칙 | `MaintenanceRule`, `appliesToSensor`, `hasSensor`, `priority`, `responseText` | 모두 있음 |

## 9. 미결·후속
- **Task 클래스 보류**: ④ 시작 전에 재검토(`CLAUDE.md` ② 요구).
- **System 노드 1개**의 처리는 정하지 않았다(질문에 필요 없어 제외).
- `actionTarget`, `sourceDocument`, `conditionText`, `extractionMethod`, `sourceQuote`는 **제안** 상태다. 4단계 SHACL과 ④ 추출 설계에서 쓰면서 확정한다.
- 이름 충돌 점검: 위 표의 이름은 ⑥ 입력 금지 목록(`harness/forbidden_columns.txt`)의 단어와 겹치지 않는다. `stage-check`의 `check_leakage.py`로 확인했다.
- `CLAUDE.md` 3장에는 아직 Rule 4분류, `appliesToSensor` 통합, `ruleIds`/`windowId` 결정이 반영되지 않았다(3단계 결과와 함께 한 번에 반영 예정).
