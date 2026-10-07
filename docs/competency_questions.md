# Competency Questions v1: KG가 답해야 할 질문 5개

작성 2026-10-07. 기준 문서는 `CLAUDE.md`이고, 확정된 결정은 `work_log.md`(D1~D6, 온톨로지 설계 6건)를 따른다.

이 질문들은 KG와 온톨로지가 **반드시 답할 수 있어야 하는 요구사항**이다. 학습·탐지 모델에 정답을 주는 입력이 아니다. 질문마다 필요한 노드·관계·속성을 적었고, 3장의 목록이 3단계 온톨로지에 꼭 들어가야 할 항목의 기준이다.

목표 표기: **G1** LLM으로 KG 구축 학습(④), **G2** `causallyAffects` 발굴(⑥), **G3** GraphRAG·Agent의 원인 분석·조치 제안(⑧⑨). 이름 표기: (확정)은 `work_log.md`에서 확정한 것, (제안)은 3단계에서 확정할 것이다.

## 0. 답변 형식 규칙 (`CLAUDE.md` §3)
- Agent는 "확정 원인은 X"가 아니라 **가능성 높은 원인 후보 상위 3개 이내를 점수와 함께** 답한다(점수 0.6 이상만).
- KG에 없는 사실은 만들지 않는다. 근거가 없으면 "근거 없음"이라고 답한다.
- 이 문서의 ST02→ST04 예시는 SOP가 이미 적고 있는 **사전 지식**(`correlates_with` 1개, GT-0009 쌍)이다. 회귀 테스트로 쓰고, 새 인과관계라고 주장하지 않는다.

## 1. 질문 5개 한눈에 보기
| ID | 질문 | 목표 | 답할 수 있는 시점 |
|---|---|---|---|
| CQ1 | ST04_PACKAGING의 속도(SPD) 저하가 관측될 때, 원인 후보 공정 상위 3개와 각 점수는? | G2·G3 | ⑥ 이후 |
| CQ2 | ST02_SEALING→ST04_PACKAGING 후보는 SOP 규칙 근거인가, 시계열에서만 관측된 것인가? 시차는? | G2 | ⑥ 이후 |
| CQ3 | 이 후보(또는 규칙)의 근거는 어느 문서·쪽·위치이며 원문 해시는? 시계열 근거는 어느 파일·센서·시간 구간인가? | G1·G3 | ④ 이후(규칙), ⑥ 이후(시계열) |
| CQ4 | ST02 온도가 SOP 위험 기준을 넘으면(212℃ 가정) SOP가 안내하는 조치·대상 스테이션·근거 문서는? | G3 | ③ + ④ 이후 |
| CQ5 | 원인 후보 공정의 센서가 이상일 때 적용되는 정비 규칙(조치·우선순위)과 SOP-003 §2의 해소 절차는? | G3 | ③ + ④ 이후 |

## 2. 질문별 상세

### CQ1. 원인 후보 공정 상위 3개 (G2·G3)
- **질문:** ST04_PACKAGING의 속도(SPD) 저하가 관측될 때, 원인 후보 공정 상위 3개와 각 점수는?
- **왜 필요한가:** 프로젝트의 핵심 질문이다. Agent 답변의 뼈대("가능성 높은 원인 후보 상위 N개를 점수와 함께")가 이 질문이다.
- **필요한 것**
  - 노드: Sensor(`ST04_PACKAGING_SPD`), Station
  - 관계: `hasSensor`(Station→Sensor, 확정), `causallyAffects`(Station→Station, 확정)
  - 속성: `likelihoodScore`, `hasLag`, `hasEvidence`(확정), 센서 ID
- **기대 답변 형태:** 후보 공정 이름, 점수(0.6 이상), 시차(분), 근거 종류. 값은 ⑥이 만든다.
- **Cypher 스케치**
```cypher
MATCH (s:Sensor {identifier:'ST04_PACKAGING_SPD'})<-[:hasSensor]-(e:Station)
      <-[r:causallyAffects]-(c:Station)
WHERE r.likelihoodScore >= 0.6
RETURN c.identifier, r.likelihoodScore, r.hasLag, r.hasEvidence
ORDER BY r.likelihoodScore DESC LIMIT 3
```
- **한계:** "이벤트당 상위 3개" 필터는 적재 스크립트가 처리한다. 질의의 `LIMIT 3`은 안전장치다. ⑦ 이후에는 입력이 센서가 아니라 AnomalyEvent가 되는 변형이 생긴다.

### CQ2. 근거 종류와 시차 (G2)
- **질문:** ST02_SEALING→ST04_PACKAGING 후보는 SOP 규칙 근거가 있는가, 시계열에서만 관측된 것인가? 시차는?
- **왜 필요한가:** "새로 발견한 관계"와 "문서에 이미 있는 관계"를 구분해서 보고해야 발굴 주장이 의미를 가진다(`CLAUDE.md` §1).
- **필요한 것**
  - 관계: `causallyAffects`, `correlatesWith`(Sensor→Sensor, seed 1개, 확정), `feedsInto`(Station→Station, 확정)
  - 속성: `hasEvidence`(TimeseriesCorrelation | SOPRule | Both), `hasLag`, `likelihoodScore`
  - 규칙 노드(제안): `RULE-ST02-04`와 그 규칙이 가리키는 센서
- **기대 답변 형태:** 근거 종류와 시차. `TimeseriesCorrelation`만 있고 SOP·seed에 같은 쌍이 없을 때만 "새로운 관계 후보"로 분류한다. 물리적 상류→하류(`feedsInto`) 방향이 맞는지도 함께 보여 준다.
- **Cypher 스케치**
```cypher
MATCH (a:Station {identifier:'ST02_SEALING'})-[r:causallyAffects]->(b:Station {identifier:'ST04_PACKAGING'})
RETURN r.hasEvidence, r.hasLag, r.likelihoodScore,
       EXISTS { (a)-[:feedsInto*1..3]->(b) } AS physicallyDownstream
```
- **한계:** 사전 지식이 이 쌍 하나뿐이어서, 이 쌍은 회귀 테스트이지 신규 발견 증거가 아니다.

### CQ3. 근거의 출처 (G1·G3)
- **질문:** 이 후보(또는 규칙)의 근거는 어느 문서·쪽·위치이며 원문 해시는? 시계열 근거는 어느 파일·센서·시간 구간인가?
- **왜 필요한가:** 모든 정보에 출처를 남긴다는 규칙(`CLAUDE.md` §4)을 검증하고, ⑩ Traceability 평가의 기초가 된다.
- **필요한 것**
  - 노드(제안): Rule, Document, Provenance
  - 속성(`CLAUDE.md` §4 출처 3종류): 문서 유래는 문서 ID, 쪽, 문자 위치(표는 좌표), 원문 해시. seed CSV 유래는 파일명과 원본 ID. 시계열 유래는 파일명, 센서 ID, 시간 구간, 파일 해시
- **기대 답변 형태(예):** `RULE-ST02-04` → SOP-001 §2.2, 1쪽, 해당 문장의 위치와 해시.
- **Cypher 스케치(개념)**
```cypher
MATCH (rule:Rule {identifier:'RULE-ST02-04'})-[:sourceDocument]->(d:Document),
      (rule)-[:hasProvenance]->(p:Provenance {sourceKind:'document'})
RETURN d.identifier, p.page, p.charStart, p.charEnd, p.sourceQuote, p.textSha256, d.sourceSha256
```
- **한계:** `causallyAffects` 관계가 어느 규칙·시계열 구간을 근거로 삼았는지 연결하는 방법은 3단계에서 정한다(5장의 열린 쟁점 1).

### CQ4. SOP가 안내하는 조치 (G3)
- **질문:** ST02 온도가 SOP 위험 기준(210℃)을 넘으면(212℃ 가정) SOP가 안내하는 조치, 대상 스테이션, 근거 문서는?
- **왜 필요한가:** Agent가 원인뿐 아니라 **조치를 문서 근거와 함께** 제안하려면 규칙→센서→조치 대상→문서의 경로가 필요하다. 임계값은 ⑥ 입력이 아니라 이 룰·⑧⑨ 경로에서 쓴다(D1).
- **필요한 것**
  - 노드: Sensor, Station, Rule, Document
  - 관계(제안): `appliesToSensor`(Rule→Sensor), `actionTarget`(Rule→Station), `sourceDocument`(Rule→Document)
  - 속성: 규칙의 조건 문장·조치 문장, 임계값(`critHi` 등), 쪽
- **기대 답변 형태:** 같은 내용이 두 곳에 있다. (1) SOP-002 ST02 TMP 행(위험 상한 210℃, 응답 "E-STOP ST02/ST03/ST04; inspect element"), (2) SOP-001 §2.2(1쪽)의 `RULE-ST02-02`("TMP > 210°C → ST02, ST03, ST04 비상 정지"). 대상 스테이션은 3개이며, 두 근거를 모두 출처와 함께 답한다. 아래 질의의 `critHi` 조건은 (1)의 임계값 규칙에 걸리고 (2)는 `actionTarget` 경로로 찾는다.
- **Cypher 스케치**
```cypher
MATCH (r:Rule)-[:appliesToSensor]->(s:Sensor {identifier:'ST02_SEALING_TMP'}),
      (r)-[:actionTarget]->(t:Station), (r)-[:sourceDocument]->(d:Document),
      (r)-[:hasProvenance]->(p:Provenance)
WHERE r.critHi < 212.0
RETURN r.identifier, r.responseText, collect(t.identifier) AS targets, d.identifier, p.page
```
- **한계:** 212℃는 가정한 수치이며 실제 경보 수신이나 제어 실행을 뜻하지 않는다. 운영 적용에는 최신성과 센서 상태 확인이 추가로 필요하다.

### CQ5. 정비 규칙과 해소 절차 (G3)
- **질문:** 원인 후보로 올라온 공정의 센서가 이상일 때 적용되는 정비 규칙(조치·우선순위)과 SOP-003 §2의 해소 절차는?
- **왜 필요한가:** 후보 원인(CQ1) 다음 단계인 "그래서 무엇을 하라"를 SOP-003 근거로 답한다. 정비 규칙 8행 유지(D5)와 센서→정비 규칙 한 줄 정리(설계 #3)의 용도다.
- **필요한 것**
  - 노드: Station, Sensor, MaintenanceRule(정비 규칙, 원본 Maintenance 8행), Document(SOP-003)
  - 관계: `hasSensor`(확정), `appliesToSensor`(MaintenanceRule→Sensor, 확정)
  - 속성: 정비 규칙의 ID(`MAINT-xx`), 조치, 우선순위, 조건
  - 규칙 텍스트(제안): SOP-003 §2 연관 장애 해소 절차(`RULE-CORR-01`)
- **기대 답변 형태(예):** ST02 → `ST02_SEALING_CUR` → `MAINT-02`(우선순위 HIGH, 실링 조 점검). 해소 절차: "1. ST02 전류 추세 확인, 2. 실링 조 점검, 3. ST04 속도 설정값 재설정"(SOP-003 §2).
- **Cypher 스케치**
```cypher
MATCH (st:Station {identifier:'ST02_SEALING'})-[:hasSensor]->(s:Sensor)<-[:appliesToSensor]-(m:MaintenanceRule)
RETURN s.identifier, m.identifier, m.responseText, m.priority
```
(`appliesToSensor`는 모든 규칙이 쓰는 관계라 정비 규칙도 같은 관계로 센서에 이어진다. 설계 #3의 "센서→정비 규칙" 표현은 규칙→센서로 바뀌었지만 의미는 같다.)
- **한계:** `Maintenance`의 조치 문구는 seed와 SOP-003 원문이 조금 달라서(예: "alignment" 추가) 근거 답변에는 **SOP-003 원문을 우선**한다. SOP-003 §2의 다른 두 패턴(SCADA 지연, QC HOLD)은 `causallyAffects`로 만들지 않고 규칙 텍스트로만 답한다(설계 #5).

## 3. 온톨로지가 반드시 포함해야 할 항목 (질문 역산)
| 구분 | 항목 | 필요한 질문 | 상태 |
|---|---|---|---|
| 클래스 | Station (속성: id, stationType, zone) | CQ1~CQ5 | 확정 |
| 클래스 | Sensor (속성: id, sensorType, unit) | CQ1, CQ4, CQ5 | 확정 |
| 클래스 | Rule (하위: OperationalRule, ThresholdRule, MaintenanceRule, AccessRule), Document | CQ2~CQ5 | 확정 |
| 클래스 | MaintenanceRule (원본 Maintenance 8행) | CQ5 | 확정 |
| 클래스 | Provenance | CQ3 | 확정 |
| 클래스 | AnomalyEvent + 하위 5유형(Disjoint) | 질문에 직접 쓰이지 않음. `CLAUDE.md` ② 요구, ⑦ 이후 CQ1의 입력 | 확정 |
| 관계 | `hasSensor` | CQ1, CQ5 | 확정 |
| 관계 | `causallyAffects`(속성 3개) | CQ1, CQ2 | 확정 |
| 관계 | `feedsInto`, `correlatesWith` | CQ2 | 확정 |
| 관계 | `appliesToSensor`(Rule→Sensor, MaintenanceRule 포함) | CQ2~CQ5 | 확정 |
| 관계 | `actionTarget`, `sourceDocument` | CQ2~CQ4 | 제안(3단계 표에서 확정) |
| 관계 | `causallyAffects` 선의 근거 번호표 속성 `ruleIds`, `windowId` | CQ1~CQ3 | 확정 |
| 관계 | `triggers`(Sensor→AnomalyEvent) | ⑦ 이후 | 확정 |
| 속성 | `likelihoodScore`, `hasLag`, `hasEvidence` | CQ1, CQ2 | 확정 |
| 속성 | 규칙의 조건 문장·조치 문장·임계값(쪽·인용은 Provenance가 가짐) | CQ3, CQ4 | 확정(`ontology_v1/schema_tables.md` 4장) |
| 속성 | 출처 필드 3종류(문서/seed CSV/시계열 CSV) | CQ3 | 확정(`CLAUDE.md` §4) |
| 속성 | 정비 규칙의 ID·조치·우선순위 | CQ5 | 확정 |

## 4. 검증 방법 (이번 스프린트)
- **정적 질문(CQ4, CQ5 일부):** ③ 변환 결과와 SOP 문서만으로 질의가 가능한지 확인한다.
- **⑥ 이후 질문(CQ1~CQ3):** 수기로 만든 예제 데이터 1~2건에 질의가 되는지로 **질의 가능성만** 확인한다. 실제 값은 ⑥ 이후다.
- 질의 형태는 이 문서의 Cypher 스케치(Agent 경로)를 기준으로 하고, 4단계 SHACL 검증은 `CausalLink` 변환형 RDF(D2)에 SPARQL로 한다.
- 이 질문 5개의 질의 성공은 Agent 답변 정확도를 입증하지 않는다.

## 5. 열린 쟁점과 결정 결과 (2026-10-07 모두 확정)
| # | 쟁점 | 결정 |
|---|---|---|
| 1 | `causallyAffects` → 근거 연결 | 선에 번호표(`ruleIds`, `windowId`)를 값으로 붙이고, 적재 스크립트가 번호의 존재와 `hasEvidence` 일치를 검사해 틀리면 거부. 적재 후 감사 질의 추가 |
| 2 | 이벤트(후보 창) 단위 점수 | 선에 `windowId`(⑥이 정한 후보 구간 ID, GT id 아님)를 붙이고 구간마다 선을 따로 둠 |
| 3 | 클래스 이름 | `Rule` 아래 4분류, `Document`, `Provenance`, 원본 Maintenance = `MaintenanceRule`. Task 클래스는 보류(④ 전 재검토), AccessRule은 텍스트 규칙으로 추출 |
| 4 | 센서→정비 규칙 관계 | 새 관계 없이 `appliesToSensor` 재사용 |
| 5 | Cypher↔SPARQL 이름 | camelCase 이름을 그대로 사용 |

아래는 쟁점이 열려 있던 때의 원래 문구다(기록용).
1. **`causallyAffects` 관계 → 근거 연결 방법.** D2에서 속성을 관계에 직접 붙이기로 했으므로, 관계가 어느 규칙(SOPRule)이나 시계열 구간을 근거로 했는지 가리키려면 관계 속성(규칙 ID, 근거 구간 ID)으로 두는 방법을 정해야 한다.
2. **이벤트(후보 창) 단위 점수 식별 속성.** 점수는 이벤트마다 다르다. ⑥은 정답 GT id를 쓸 수 없으므로 후보 창 ID 같은 별도 식별자가 필요하다(`CLAUDE.md` §4).
3. **클래스 이름 확정:** Rule, Maintenance(MaintenanceTask), Document, Provenance와 Task 상위 클래스 여부.
4. **센서→정비 규칙 관계 이름:** `triggers`(Sensor→AnomalyEvent)와 겹치지 않는 이름.
5. **질의 표기:** Cypher(Agent 경로)와 SPARQL(검증 경로) 사이의 이름 대응표.

## 부록. 참고 질문 (필수 아님)
- **A1 구조 확인(sanity):** ST02_SEALING에는 어떤 센서가 있고 단위는? (`hasSensor`, `sensorType`, `unit`, 스테이션의 `zone`)
- **A2 충돌 병기(G1):** ST02 전류의 SOP 임계값(경고 13.5 A, 위험 15.0 A)과 전류 데이터시트의 연속 운전 사양(14 A)은 어떻게 다른가? 문서 출처와 함께 둘 다 답한다. 실제 설치 모델 적합성은 자료가 없어 판정하지 않는다.
