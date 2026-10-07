# CLAUDE.md — 제조 공정 지식그래프 + GraphRAG 설비 이상 분석 Agent

이 파일은 Claude Code가 세션 시작 때마다 읽는 프로젝트 맥락이다. 결정이 바뀌면 이 파일부터 고친다.

## 1. 프로젝트 한 줄 정의

iMAKS(제조 공정 합성 데이터셋)로 지식그래프(KG)를 직접 구축하고, GraphRAG로 설비 이상의 원인을 분석·조치를 제안하는 AI Agent를 만든다.
진단 성능 자체보다 **LLM으로 KG를 만드는 과정**을 배우는 것이 목적이다.

핵심 목표는 데이터셋에 명시되지 않은 **새로운 공정 간 인과관계(`causallyAffects`)를 찾는 것**이다. ML 이상탐지 모델 비교가 아니다.

## 2. 파이프라인 (①~⑩)

| 단계 | 내용 |
| --- | --- |
| ① | iMAKS 구조 분석: 파일 구성, nodes/edges, 14개 이상 이벤트, 기존 KG 한계 |
| ② | 온톨로지 설계: Domain/Range, Disjoint 제약, SHACL, Task 클래스(현재 보류, ④ 시작 전 재검토), SWRL 보완규칙(선택). 확정된 설계 결정은 3장, 산출물은 `ontology_v1/` |
| ③ | CSV 기반 설비·센서 인스턴스 생성 (nodes.csv/edges.csv를 ②의 온톨로지에 맞춰 변환). Component 9개는 Station으로 1:1 매핑, 센서 연결은 hasSensor 단방향으로 정리, Person·authorized_for는 제외하고 Zone은 Station의 속성으로 흡수 |
| ④ | SOP·데이터시트에서 LLM 관계 추출: Role/Task/Example 3단 프롬프트 + 2단계 사람 검토 |
| ⑤ | 검증: ground_truth.csv 86규칙 대비 F1_content, MAINT-01~08 매핑표, 데이터시트 vs SOP-002 수치 충돌 |
| ⑥ | 센서 시계열 기반 공정 간 인과관계 추론: `causallyAffects` 후보 발굴 (likelihoodScore). 입력은 라벨 없는 raw 시계열이며 임계값 컬럼은 제외(4장) |
| ⑦ | 탐지 결과를 AnomalyEvent로 KG에 추가. 대표 테스트케이스는 GT-0009 |
| ⑧ | GraphRAG 검색: Sparse-Dense-Graph 하이브리드 + 자연어→Cypher + Graph-to-Text |
| ⑨ | Agent 답변: 2-에이전트(추론 생성 + 자기검증), Premise→Inference→Conclusion→Evidence 구조 |
| ⑩ | 평가: Baseline RAG vs GraphRAG ablation, RAGAS, 관계 유형별 Confusion Matrix |

일정 기준: 10/1~10/7 전처리·온톨로지·SHACL, 10/8~10/14 KG 구축, 10/15~10/31 베이스라인·탐지기, 11/1~11/10 GraphRAG+Agent, 11/12~11/16 평가.

## 3. 확정된 결정 (임의로 바꾸지 말 것)

- **Station(공정) 수준까지만 다룬다.** 내부 부품(Component) 계층은 만들지 않는다. 원본 Component 9개는 이름이 스테이션과 같으므로 Station으로 1:1 매핑한다.
- **센서–스테이션 연결은 `hasSensor`(Station→Sensor) 단방향이다.** 원본 monitors 양방향 44줄(22쌍)은 하나로 정리한다.
- **Person(작업자 44명)과 authorized_for(218개)는 만들지 않는다.** Zone 클래스도 만들지 않고 Station의 zone 속성으로 흡수한다(Main Entrance 불필요).
- **규칙 클래스는 `Rule` 아래 4분류(`OperationalRule`, `ThresholdRule`, `MaintenanceRule`, `AccessRule`)로 둔다.** 평가용 정답 규칙 파일의 class 이름과 같아서 ⑤ 클래스별 채점과 맞는다. 문서는 `Document`, 출처는 `Provenance` 클래스로 둔다. Task 클래스는 지금 만들지 않고 조치는 `responseText` 속성으로 둔다(④ 시작 전 재검토).
- **원본 Maintenance 8행(MAINT-01~08)은 `MaintenanceRule`이다.** 원본의 중복 선 두 줄(Sensor→Maintenance triggers, Maintenance→Sensor resolves)은 모든 규칙이 쓰는 `appliesToSensor`(Rule→Sensor) 하나로 합친다. 이상 이벤트와의 연결은 ⑦ 이후에 한다.
- **`AccessRule`(SOP-004 규칙 20개)은 Person과 연결하지 않고 텍스트 규칙으로 추출한다.** 정답 86규칙에 포함되므로 ④ 추출·⑤ 평가 대상이다.
- **AnomalyEvent는 SOP-002 이름의 하위 클래스 5개로 나누고 서로 Disjoint로 한다.** Spike, Drift, StuckSensor, OutOfRange, Correlated. 이상↔센서 방향은 원본 그대로 `Sensor triggers AnomalyEvent`이며 ⑦ 이후에만 인스턴스화한다.
- **핵심 관계는 `causallyAffects` (Station → Station).** 속성: `hasLag`(분), `hasEvidence`(TimeseriesCorrelation | SOPRule | Both), `likelihoodScore`(0.0~1.0). 근거 번호표 `ruleIds`(규칙 identifier)와 `windowId`(⑥이 정한 후보 구간 ID, GT id 아님)도 붙인다. 점수는 구간마다 달라서 같은 스테이션 쌍도 `windowId`마다 관계를 따로 둔다. Neo4j에서는 이 속성을 관계 속성으로 직접 붙이고, SHACL 검증 때만 CausalLink 형태로 변환한다.
- **`causallyAffects`의 근거 번호표는 적재 스크립트가 검증한다.** `ruleIds`가 실제 Rule을 가리키는지, `windowId`가 등록된 구간인지, `hasEvidence`와 일치하는지 검사해 틀리면 적재를 거부한다. 적재 후에도 감사 질의로 확인한다.
- **SOP-003 §2의 도착점이 공정이 아닌 2패턴(서버실→SCADA 지연, 창고→QC HOLD)은 `causallyAffects`로 만들지 않는다.** 규칙 텍스트로만 보관하되 ④ 추출·⑤ 평가에는 포함한다.
- **확정/추정 이진 구분을 쓰지 않는다.** 연속 점수 `likelihoodScore`로 매기고, **0.6 이상**만, **이벤트당 상위 3개**까지만 KG에 채택한다. 이 필터는 SHACL이 아니라 KG 적재 스크립트에서 처리한다.
- Agent 답변도 "확정 원인은 X"가 아니라 "가능성 높은 원인 후보 상위 N개를 점수와 함께" 제시한다.
- 품질불량 연결은 범위에서 제외한다 (원본 KG에 품질/불량 노드 타입이 없음).
- 범위 제외 데이터: Layer 2(작업자 presence), Layer 3(WiFi CSI), Person·권한 관계.
- 팀원(yujin)의 통계 탐지 결과는 ⑥의 입력·베이스라인으로 쓰지 않는다. 참고만 한다(검증 정답으로 설정을 맞춘 결과라 정답 의존이다).
- 온톨로지 기술: RDF(필수), OWL·SHACL(권장), RDFS·SWRL(선택). Graph DB는 Neo4j. 이름은 camelCase를 Neo4j와 RDF에서 그대로 쓴다.
- SHACL 검증은 `ontology.ttl`을 ont_graph로 주되 **추론은 끈다**(`inference="none"`). RDFS 추론은 range 선언으로 Sensor를 Station으로 간주해 `sh:class` 검사를 무력화한다.

## 4. 데이터 규칙

### 누수 방지
- **정답 라벨을 `causallyAffects` 발굴(⑥) 입력에 섞지 않는다.** 정답을 넣고 "새 관계를 찾았다"고 주장하면 의미가 없다.
  - 금지 대상: `anomaly_label`, `severity`, `alarm_flag`, GT id 등 annotated 정답 컬럼, AnomalyEvent 14건의 정답 속성.
  - 같은 이유로 ⑥ 입력에서 제외: raw의 `quality`(UNCERTAIN 25행이 STUCK 구간과 일치), MQTT의 `status`·`alarms`, 임계값 컬럼(`nominal`, `warn_*`, `crit_*`; 룰·⑧⑨ 경로에서는 사용).
  - `day`·`shift`·`batch_id`는 timestamp와 맞지 않는 라벨이므로(day는 1~5인데 실제는 4일) ⑥ 입력에서 제외하고 원본은 `original_*`로 보존한다. 시간 기준은 timestamp다.
- `ground_truth.csv`(86규칙)와 응답 로그는 **평가용**이다. 문서 청킹, 추출 프롬프트, KG 구축의 입력·정답으로 쓰지 않는다.
- ⑦ 이후 단계(11월 End-to-End)에서 AnomalyEvent 14건을 KG에 넣는 것은 일정상 계획된 동작이다. 발굴 입력과 구분해서 다룬다. 코드에서도 두 경로를 분리한다.
- 이상값을 오류로 삭제하거나 보간·평활화로 바꾸지 않는다. 원본 value는 보존하고 파생 값은 별도 컬럼으로 둔다.
- 원본 데이터 파일은 직접 수정하지 않는다. 복사본에서 작업한다.

### 평가
- **ruleId 기반 F1_strict를 주 지표로 쓰지 않는다.** 86개 중 31개만 SOP 원문에 ID가 있어서 F1_strict는 구조적으로 31/86(약 36%)을 넘을 수 없다.
- 주 지표는 **F1_content** (Hungarian assignment + SBERT all-MiniLM-L6-v2, 임계 0.6). 보조로 Coverage, GT-0009 binary(다중소스 융합 통과 여부)를 본다.
- `ground_truth.csv`(규칙 추출 정답)와 `nodes.csv/edges.csv`(KG 구조 정답)는 목적이 다른 별개 파일이다. MAINT-01~08은 양쪽에 같은 ID로 있지만 필드가 다르므로 매핑표를 만들어 대조한다.
- 데이터시트 3개에는 SOP-002와 의도적으로 충돌하는 수치가 있다. 임의로 통일하지 말고 출처와 함께 둘 다 기록한다.

### 모든 트리플에 출처를 남긴다
문서 ID, 페이지, 문자 위치(표는 좌표), 원문 해시를 provenance로 함께 저장한다. Traceability 평가에 쓴다.
출처 종류별로 남기는 필드는 다음과 같다.
- 문서(SOP·데이터시트) 유래 규칙·근거: 위 전체 필드.
- seed CSV 유래 구조 정보: 파일명과 원본 ID(행 식별자).
- 시계열 CSV 유래 인과 후보: 파일명, 센서 ID, 시간 구간, 파일 해시.

문서 안의 위치(쪽, 문자 위치, 표 좌표, 인용, 해시)는 Rule이 아니라 `Provenance` 한 곳에만 저장한다. Rule은 `sourceDocument`로 문서만 가리킨다.

## 5. 하네스 해당 지점

10단계 전체가 하네스는 아니다. **자율 에이전트 하네스는 ⑧~⑨(런타임 질의응답)뿐**이다.

- ⑧~⑨: Cypher 쿼리(plan/code) → 추론 체인 생성 → 자기검증 모델 검사(verify) → 틀리면 재검색·재생성(self-correct)을 사람 개입 없이 반복.
  - 구성: 에이전트 2개(추론 생성, 자기검증), 공용 스킬 1개(질의→Cypher 또는 Graph-to-Text), 중간 산출물 폴더, 프로젝트 규칙(SHACL 제약).
  - 수렴 조건: 일관성 검사를 2회 연속 통과하면 종료. 반복 횟수 상한을 반드시 둔다.
  - 도구 제한: Cypher 쿼리, SOP 문서 검색, 센서 시계열 조회만. KG에 없는 사실을 임의로 생성하지 않는다.
- ④(LLM 추출 + 사람 검토)는 자기수정 주체가 사람이라 "사람이 낀 미니 하네스"로 분류한다.
- ⑤, ⑩의 평가 스크립트는 하네스가 아니라 하네스를 바깥에서 재는 별도 계층이다.
- 나머지(①②③⑥⑦)는 일회성 데이터 엔지니어링·설계 작업이다.

## 6. 작업 규칙

- 각자 본인 브랜치에서 작업한다 (예: `지훈`). `main`에는 직접 push하지 않고 Pull Request로 합친다. 세부는 팀 합의에 따른다.
- 커밋 메시지는 무엇을 왜 바꿨는지 한 줄로 쓴다.
- 파이프라인 단계를 바꾸면 이 파일의 2·3장도 같이 고친다.
- 선택과 이유, 미결정 사항은 `work_log.md`에 기록한다.
- 코드 실행 환경은 Windows PowerShell + Python 가상환경(.venv). 큰 산출물과 원본 데이터는 git에 올리지 않는다.

## 7. 참고

- 노션 정리 페이지: "제조 Agent" — https://app.notion.com/p/3f1d169a5e3681bf9cd8e55dc167cadc (작성자 워크스페이스의 비공개 페이지라 팀원은 열 수 없을 수 있음)
- 참고논문 1: Miao et al., *Graph RAG-based fault diagnosis for train bogies using knowledge graphs and large language model*, Knowledge-Based Systems 331 (2025) 114855 — 추출·리트리벌·자기검증·평가의 근거
- 참고논문 2: Shim et al., *OmEGa: Ontology-based information extraction framework for constructing task-centric knowledge graph from manufacturing documents with large language model*, Advanced Engineering Informatics 64 (2025) 103001 — Task 중심 온톨로지·SWRL·Disjoint 제약의 근거
- 산출물 위치: 질문 `docs/competency_questions.md`, 온톨로지 `ontology_v1/`(`ontology.ttl`, `schema_tables.md`, `shapes.ttl`, `examples/`), 누수 검사 `guards/`, 테스트 `tests/test_shacl.py`, 결정 기록 `work_log.md`.
- 데이터셋: iMAKS v3 (Zenodo, https://zenodo.org/records/20075430)
  - 로컬 저장 위치: `C:\Users\LG\manufacturing-graphrag-agent\imaks_data` (저장소 기준 상대 경로: `imaks_data/`). 코드에서는 절대 경로를 하드코딩하지 말고 저장소 기준 상대 경로나 설정 파일로 참조한다.
