# iMAKS Ontology v1 스키마

어휘 URI는 `https://example.org/imaks/v1#`, 인스턴스 URI는 `https://example.org/imaks/id/`를 사용한다. `ontology.ttl`은 OWL TBox, 변환 RDF는 ABox, `shapes.ttl`은 입력 검증 규칙이다. OWL domain/range는 의미 선언이며 필수값·개수·자료형 검증을 대신하지 않는다. 검증은 추론 없이 실행하며 ThresholdRule 인스턴스에 Rule과 ThresholdRule 두 타입을 명시한다.

## 클래스와 원본 대응

| 클래스 | 의미·원본 대응 | v1 범위 | 예시 |
|---|---|---|---|
| System | 원본 System | 1개 | iMAKS, N0001 |
| Zone | 원본 Zone | 7개 | Production Area, N0002 |
| Station | 원본 Component의 스테이션 수준 의미 | 9개, 원본 ID·sourceLabel 유지 | ST02_SEALING, N0013 |
| Sensor | 원본 Sensor | 22개, identifier는 CSV sensor_id | ST02_SEALING_TMP, N0014 |
| Person | 원본 Person | 44개, 빈 name을 추정하지 않음 | P043/security, N0104 |
| Document | 원본 SOP·데이터시트 PDF | 7개, PDF 해시·경로·페이지 수·원문 | SOP-001 |
| Rule | 문서 근거의 조건·조치 규칙 | 24개: 임계값 표 22개 + 원문 문장 2개 | RULE-ST02-02 |
| ThresholdRule | Rule의 하위 클래스 | Rule 24개 중 22개, 이중 rdf:type 명시 | SOP002-THRESHOLD-ST02_SEALING_TMP |
| Observation | 센서·시각·값·단위 | 센서별 첫 관측 표본 22개 | ST02 TMP의 2026-01-06 06:00 관측 |
| InputGraph | 검증 프로필 제어 노드 | RDF 파일마다 1개 | im:InputData |
| InternalComponent | 미래 확장용 내부 부품 | 인스턴스 없음 | 향후 BOM으로 확인할 베어링; 현재 설치 사실 없음 |
| QualityDefect | 미래 확장용 관측 품질불량 | 인스턴스 없음 | 향후 실제 검사로 확인할 밀봉불량; 현재 불량 사실 없음 |

정적 83개 노드와 269개 원본 정규 엣지는 유지한다. Station의 원본 zone 문자열을 Zone에 연결한 locatedIn 9개는 명시적인 파생 관계다. Observation 표본은 형식 확인용이며 공식 시계열 입력은 전체 211,200행 CSV이다. 표본을 전체 시계열이나 전체 이상 이벤트 평가로 해석하지 않는다.

Rule 22개는 SOP-002 원문 표에서 변환한다. 추가 2개 `RULE-ST02-02`·`RULE-ST02-04`는 SOP-001 p.1의 실제 조건·조치 문장에서 수동 추출한다. 정답 규칙 86건이나 정답 이벤트 14건을 읽어 Rule을 생성하지 않는다. LLM 추출 성능을 평가한 결과도 아니다.

## 객체 관계

| 속성 | 방향·domain → range | 의미·원본 대응 | 예시 |
|---|---|---|---|
| contains | System 또는 Zone → Zone 또는 Station | 원본 System→Zone, Zone→Station 유지 | Production Area → ST02_SEALING |
| partOf | Station → System | 원본 part_of. contains의 inverse로 선언하지 않음 | ST02_SEALING → iMAKS |
| hasSensor | Station → Sensor | 전처리 has_sensor; 원본 monitors의 양방향 중복 정규화 | ST02_SEALING → ST02_SEALING_TMP |
| feedsInto | Station → Station | 원본 feeds_into의 방향 유지 | ST02_SEALING → ST03_LABELLING |
| correlatesWith | Sensor → Sensor | 원본 ST02_CUR→ST04_SPD 한 건. 문서 근거 관계이며 인과·자동 대칭을 주장하지 않음 | ST02_SEALING_CUR → ST04_PACKAGING_SPD |
| authorizedFor | Person → Zone | 원본 authorized_for 218개 유지 | P043 → Chemical Storage; 교육 이수는 미확정 |
| locatedIn | Station → Zone | 원본 Station zone 이름과 Zone name 대응 | ST02_SEALING → Production Area |
| appliesToSensor | Rule → Sensor | 일반 Rule에는 선택적, ThresholdRule에는 정확히 1개 | RULE-ST02-02 → ST02_SEALING_TMP |
| monitorsSensor | Rule → Sensor | 상관 규칙에서 추가로 관찰할 센서 | RULE-ST02-04 → ST04_PACKAGING_SPD |
| actionTarget | Rule → Station | 원문 조치의 대상, 조치가 실제 수행됐다는 뜻이 아님 | RULE-ST02-02 → ST03_LABELLING |
| sourceDocument | Rule → Document | 규칙 근거 문서 정확히 1개 | RULE-ST02-02 → SOP-001 |
| observedBy | Observation → Sensor | 관측 센서 정확히 1개 | ST02 TMP 첫 관측 → ST02_SEALING_TMP |

관계에 대칭성·전이성·역관계를 자동 부여하지 않는다. 특히 correlatesWith는 센서 연결의 원본 방향을 보존하며, feedsInto는 원인 관계로 바꾸지 않는다.

## 데이터 속성

| 속성 | 자료형 | 기록 정책 | 예시 |
|---|---|---|---|
| identifier | xsd:string | 외부 ID. Sensor는 시계열 sensor_id와 대응 | ST02_SEALING_CUR |
| name | xsd:string | 원본 이름; Person의 빈값을 만들어 채우지 않음 | ST02_SEALING |
| sourceLabel | xsd:string | 원본 KG 타입. Station의 원본 Component 표기 보존 | Component (Station의 원본 타입) |
| stationType | xsd:string | FILLING·SEALING·LABELLING·PACKAGING·SERVERROOM·WAREHOUSE·CHEMICALSTORAGE·RDLAB·CAFETERIA | SEALING |
| sensorType | xsd:string | TMP·PRS·FLW·CUR·SPD·TEN·CNT·VIB·HUM | CUR |
| unit | xsd:string | 원문 단위를 그대로 보존 | A |
| personId | xsd:string | 원본 personId | P001 |
| role | xsd:string | 원본 role | operator |
| department | xsd:string | 원본 dept | Production |
| csiSubject | xsd:string | 원본 csiSubject | soggetto 1 |
| line | xsd:string | 원본 line | LineaA |
| sourcePath | xsd:string | Document는 원본 ZIP 내부 PDF 경로, Observation은 CSV 경로, 관계 RDF.Statement는 엣지 CSV 경로. Document domain으로 한정하지 않음 | rules/SOP_001_OperatingProcedures.pdf |
| sourceSha256 | xsd:string | 원본 PDF 바이너리 SHA-256, 64자리 16진수 | 0e209d7e484691a7ee90849b7754c44c1145e8b6f4751e3ce8e5a940556fbe89 |
| pageCount | xsd:positiveInteger | 원본 PDF 페이지 수 | 2 (SOP-001) |
| title | xsd:string | 원문 문서 제목 | Standard Operating Procedures — Production Line A |
| documentText | xsd:string | 전처리에서 보존한 문서 원문, rule_context만 허용 | SOP-001 p.1의 원문 및 [page 1] 표기 |
| sourcePage | xsd:positiveInteger | minInclusive 1, 1-based 원문 페이지, pageCount 이하 | 1 |
| sourceTable | xsd:string | 전처리 tables.json table ID. 문장 규칙에는 생략 가능 | SOP-002:p1:table2 |
| sourceRow | xsd:positiveInteger | minInclusive 1, 해당 tables.cells의 실제 1-based 행. 연속표도 해당 표의 행 위치를 사용 | 2 (해당 표의 TMP 행) |
| sourceQuote | xsd:string | 표 규칙은 원문 셀 행 JSON, 문장 규칙은 원문 인용 | RULE-ST02-02: TMP > 210°C (CRITICAL) — emergency stop ST02, ST03, ST04. |
| conditionText | xsd:string | 규칙 조건, 공백만 있는 문자열 금지 | TMP > 210°C (CRITICAL) |
| responseText | xsd:string | 문서 근거 조치, 공백만 있는 문자열 금지 | emergency stop ST02, ST03, ST04. |
| extractionMethod | xsd:string | 표 변환·수동 문장 추출 등 실제 방법 | manual source-grounded example; not LLM extraction |
| nominal | xsd:double | nominal 원문 표기의 중앙값 | 12.4 (ST02 CUR) |
| nominalTolerance | xsd:double | 원문 nominal의 ± 수치, 0 이상 | 0.3 (ST02 CUR) |
| nominalText | xsd:string | 원문 nominal 표기를 보존하여 중앙값으로만 덮어쓰지 않음 | 12.4 ± 0.3 |
| warnHi | xsd:double | 경고 상한 | 13.5 A (ST02 CUR) |
| critHi | xsd:double | 심각 상한 | 15.0 A (ST02 CUR) |
| warnLo | xsd:double | 경고 하한 | 11.0 A (ST02 CUR) |
| critLo | xsd:double | 심각 하한 | 9.5 A (ST02 CUR) |
| timestamp | xsd:dateTime | 원본 시간대 미지정 시각 보존. UTC/KST 추정 변환 없음 | 2026-01-06T06:00:00 (시간대 미지정) |
| value | xsd:double | 원본 관측값, 이상값도 보존 | 1000000.0 (C2 합성 검증 예제; 공식 원본을 바꾸지 않음) |
| inputProfile | xsd:string | ml_metadata 또는 rule_context | ml_metadata / rule_context |
| ruleReference | xsd:string | 원본 엣지 ruleRef. 실제 Rule 인스턴스와 자동 동일시하지 않음 | RULE-ST02-04 (공통 E0051 참조) |


## SHACL 핵심 5개 그룹

| 그룹·타겟 shape | 검사 범위 | 주요 규칙 |
|---|---|---|
| C1 SensorShape | Sensor | identifier·sensorType·unit 각각 정확히 1개. 역 hasSensor를 통해 Station 정확히 1개. 9개 센서 타입–단위 대응 |
| C2 ObservationShape | Observation | observedBy Sensor 1개, timestamp xsd:dateTime 1개, 유한한 value xsd:double 1개, unit 1개. 관측 단위와 센서 단위 일치 |
| C3 RuleShape | Rule 및 Document | 타입별로 무타겟 RuleHelper·DocumentHelper에 분기. Rule 출처·페이지·근거·조건·조치·추출 방법 필수. 모든 Document의 ID·제목·경로·PDF 해시·페이지 수 필수 |
| C4 ThresholdRuleShape | ThresholdRule | 명시적 Rule 타입과 C3 요건. 적용 센서 1개. 임계값 5개 각각 유한한 xsd:double 1개, 단위 일치, critLo < warnLo < nominal < warnHi < critHi. 선택적 nominalTolerance도 유한값 |
| C5 InputGraphShape | InputGraph 및 고정 노드 im:InputData | 고정 제어 노드의 InputGraph 타입·프로필 허용값·정확히 1개. 해당 입력 그래프 전체의 금지 predicate·GT 식별자·평가 사건 인스턴스 검사. ml_metadata의 규칙·문서·임계값 차단 |

타겟이 있는 NodeShape는 정확히 5개다. StationHelper·ZoneHelper·SystemHelper·RuleHelper·DocumentHelper는 타겟이 없고 core shape에서 호출한다. C3가 Rule과 Document를 모두 타겟으로 하므로 규칙에 아직 연결되지 않은 문서도 검사한다. Person은 이름이 없는 원본을 그대로 유지하며 name 필수 검사를 적용하지 않는다.

Station helper는 locatedIn Zone 1개·partOf System 1개와 타입을 검사한다. 센서 타입–단위 대응은 다음과 같다.

| 타입 | 단위 |
|---|---|
| TMP | °C |
| PRS | bar |
| FLW | L/min |
| CUR | A |
| SPD | m/s |
| TEN | N |
| CNT | pcs/min |
| VIB | mm/s |
| HUM | %RH |

**Observation에는 임계값 범위 검사를 하지 않는다.** 이상 탐지 대상인 값을 정상 범위 밖이라는 이유로 적재 거부하면 안 된다. NaN·양/음의 무한값은 수치 결함으로 차단하지만, 유한한 이상 크기는 보존한다. C4는 규칙 정의의 내부 순서와 수치 유효성을 검사한다. sourcePage·sourceRow·pageCount는 positiveInteger 자료형과 별도로 minInclusive 1도 적용한다.

## 입력 프로필과 누출 방지

| 프로필 | 허용 입력 | 차단 대상 |
|---|---|---|
| ml_metadata | 정적 System·Zone·Station·Sensor·Person과 정적 관계·식별 메타데이터 | Rule·ThresholdRule·Document 인스턴스, 임계값·nominal 원문·문서 원문 |
| rule_context | 정적 KG + Document + 출처 기반 Rule + 확인용 Observation | 정답 라벨·정답 사건·사후 알람·정비 사건 |

두 파일은 별도로 검증한다. 프로필을 합쳐 union graph로 만들면 ml_metadata 정책과 충돌한다. `ml_metadata` 그래프는 ML 수치 피처 파일이 아니다. CSV 탐지 입력의 feature whitelist와 기존 quality·임계값 정책은 그대로 적용한다.

C5는 namespace와 대소문자·underscore·hyphen 표기에 관계없이 predicate local name을 정규화하여 `label`, `quality`, `status`, `alarms`, `gtId`/`gt_id`, `anomaly_label`, `dataset_severity`, `severity`, `alarm_flag`, `shift`, `day`, `batch_id`를 차단한다. 자연어 리소스 이름을 표현하는 정확한 `rdfs:label` URI는 label 차단에서 제외한다. 이를 정답 저장 수단으로 이용해서는 안 된다. `sourceLabel`은 원본 스키마 대응 메타데이터이므로 허용한다. `GT-####` 외부 식별자·인스턴스 URI와 AnomalyEvent·SafetyEvent·MaintenanceEvent(원본 Maintenance 포함) 인스턴스도 차단한다.

TBox에서 클래스나 속성을 선언한 것만으로 인스턴스 누출로 판단하지 않는다. 예를 들어 `AnomalyEvent rdf:type owl:Class`는 사건 인스턴스가 아니다. 모든 C5 SPARQL constraint가 실제 데이터 그래프에서 `$this` InputGraph를 focus로 전역 검색한다. `sh:targetNode im:InputData`와 `sh:class im:InputGraph`를 함께 사용하여 고정 제어 노드나 그 타입을 삭제해 검사를 우회하지 못하게 한다. 검증 실행기도 파일의 InputGraph 제어 노드가 정확히 1개이고 im:InputData인지 확인한다.

이 검사는 **명시적인 누출 패턴 검사**다. 다른 이름의 속성, 자유 텍스트 속의 답, 센서 ID·관계 구조 같은 의미적 프록시 누출이 전혀 없다는 증명이 아니다. 정답·audit·사후 대응 파일을 입력 생성 코드에서 읽지 않는 정책과 변환 기록을 함께 확인한다. SHACL 통과도 문서 주장의 사실 정확성이나 규칙의 완전성을 보증하지 않는다.
