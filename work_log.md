# work_log.md

선택과 이유, 미결정 사항을 단계가 끝날 때마다 적는다. 기준 문서는 `CLAUDE.md`이며, 다르면 `CLAUDE.md`가 우선한다. 커밋은 작업 완료 후 한꺼번에 한다(사용자 결정).

> **로컬 전용 안내:** 이 문서와 `docs/`, `ontology_v1/schema_tables.md`가 언급하는 `reports/`의 초안(`own_*`), 팀원 비교(`comparison_rubric.md`, `teammate_comparison.md`), CLAUDE.md 백업(`*.bak`)은 git에 올리지 않는 **로컬 전용** 파일이다(`.gitignore`로 제외, 2026-10-07 결정). 결정과 이유는 이 문서에 모두 요약돼 있다. git에 추적하는 것은 구현·검증 보고서(`reports/*_impl.md`, `reports/*_verify.md`)뿐이다.

## 2026-10-07

### 진행한 것
| 단계 | 내용 | 산출물 |
|---|---|---|
| 탐색(①) | `imaks_data` 읽기 전용 파악. `csi/`는 개수만 세고 열지 않음. PDF 7개는 `pdfplumber`로 표까지 추출 | Notion "iMAKS 데이터셋 배경지식 정리" 1~12장, `reports/own_facts_for_design.md` |
| 독립 초안 | 서브에이전트(Read/Write/Bash만, 웹·Notion 접근 불가)가 `CLAUDE.md`와 사실 자료만으로 구조·온톨로지·SHACL·CQ 초안 작성 | `reports/own_structure_draft.md`, `reports/own_design_draft.md` |
| 비교 | 루브릭 14항목을 고정한 뒤 팀원 브랜치 `origin/codex/imaks-preprocessing`(`638ce3c`)를 `git show`로만 읽어 비교 | `reports/comparison_rubric.md`, `reports/teammate_comparison.md` (6장이 최종) |
| 목표 기준 재도출 | 3~13번 항목을 G1(LLM으로 KG 구축 학습), G2(`causallyAffects` 발굴), G3(GraphRAG·Agent 조치 제안)로 다시 걸러냄 | `reports/teammate_comparison.md` 6장 |

### 가이드라인 1단계: Competency Questions (완료 2026-10-07)
- 산출물: `docs/competency_questions.md` (질문 5개, 질문별 필요 노드·관계·속성, Cypher 스케치, 온톨로지 필수 항목 역산표, 열린 쟁점). 가이드라인은 `ontology_v1/competency_questions.md`를 예로 들었으나 사용자 지시에 따라 `docs/`에 둠. 3단계에서 `ontology_v1/`로 옮길지 정한다.
- 질문 구성: CQ1 원인 후보 상위 3개(G2·G3), CQ2 근거 종류·시차(G2), CQ3 출처(G1·G3), CQ4 SOP 조치(G3), CQ5 정비 규칙·해소 절차(G3). 팀원 CQ 중 조치 시나리오(CQ3)와 상관 센서(CQ2)의 아이디어를 채택하고 출입 권한 질문은 제외.
- 열린 쟁점(3단계에서 결정): (1) `causallyAffects` 관계가 근거(규칙·시계열 구간)를 가리키는 방법(D2 후속), (2) 이벤트(후보 창) 단위 점수 식별 속성(GT id 사용 금지), (3) Rule/Maintenance/Document/Provenance 클래스 이름, (4) 센서→정비 규칙 관계 이름(`triggers`와 구분), (5) Cypher↔SPARQL 이름 대응표.
- 확인 사항: CQ4의 위험 기준(210℃)은 SOP-002 임계값 행과 SOP-001 §2.2 `RULE-ST02-02` 두 곳에 같은 내용으로 있어 둘 다 답해야 한다.

### 열린 쟁점 5개 결정 (3단계 전, 2026-10-07)
| # | 쟁점 | 결정 | 이유 |
|---|---|---|---|
| 1 | `causallyAffects` 선이 근거를 가리키는 방법 | **확정: A + 적재 검증.** 선에 근거 번호표(`ruleIds`, `windowId`)를 값으로 붙이고, 적재 스크립트가 번호의 존재와 `hasEvidence`와의 일치를 검사해 틀리면 적재를 거부한다. 적재 후 감사 질의("`ruleIds`가 가리키는 Rule이 없는 선 = 0개")를 `stage-check`에 추가하고 `Rule.identifier`에 UNIQUE 제약을 둔다 | D2(관계 속성)와 일관. 번호 오류는 점수가 아니라 출처 표시 오류(Traceability)에 영향이라 막아야 함. 근거 카드 노드(B)는 Neo4j가 선을 가리킬 수 없어 (스테이션 쌍, `windowId`) 값 일치로 옮겨 갈 뿐이라 이점이 작음 |
| 2 | 이벤트(후보 창) 단위 점수 식별 | **확정: A.** 선에 `windowId`(⑥이 정한 후보 구간 ID, 센서+시각 기반, GT id 아님)를 붙이고 구간마다 선을 따로 둔다. ⑦에서 AnomalyEvent를 만들 때 `windowId`로 맞춘다 | 누수 없음, ⑥/⑦ 경로 분리 원칙(§4) 유지, "이벤트당 상위 3개" 규칙을 지킴 |
| 3 | 클래스 이름 확정 | **확정: A.** `Rule` 아래 4분류(`OperationalRule`, `ThresholdRule`, `MaintenanceRule`, `AccessRule`, ground_truth와 같은 이름), `Document`, `Provenance`. 원본 `Maintenance` 8행 = `MaintenanceRule`. **Task 클래스는 지금 만들지 않고** 조치는 `responseText` 속성으로 둔다. `AccessRule`은 Person 연결 없이 텍스트 규칙으로 추출(SOP-004 규칙 20개가 평가 86개에 포함되므로) | ⑤ F1_content가 4분류로 채점하므로 이름 정렬. 가장 단순하고 오늘 마감에 맞음. **미충족 표시:** `CLAUDE.md` ②의 "Task 클래스" 요구는 ④ 시작 전에 재검토한다 |
| 4 | 센서→정비 규칙 관계 이름 | **확정: C.** 새 관계 없이 `appliesToSensor`(MaintenanceRule→Sensor)를 재사용한다. 설계 #3의 방향 표현(센서→규칙)은 규칙→센서로 바뀌었지만 의미는 같다 | `Rule` 계층에 이미 `appliesToSensor`가 있어 새 관계를 만들면 설계 #3에서 없앤 중복이 다시 생김. "해소한다" 과대 표현도 피함 |
| 5 | Cypher↔SPARQL 이름 대응 | **확정: A.** camelCase 이름을 두 곳에서 그대로 쓴다. 대응표 없음 | 표가 늘지 않음. Neo4j 대문자 관례는 필수가 아님 |

### 가이드라인 3단계: 온톨로지 산출물 (초안 완료 2026-10-07)
- 산출물: `ontology_v1/ontology.ttl`(클래스 16, 객체 관계 11, 데이터 속성 45), `ontology_v1/schema_tables.md`(이름·의미·원본 대응·예시·근거, seed→새 스키마 대응표, CQ 커버리지).
- 검증(이 환경에서 실행): `rdflib`로 파싱 성공(432 트리플), 모든 항목에 라벨·설명·근거(`decisionRef`) 있음, domain/range 참조 오류 0, 표와 TTL의 이름이 72개 모두 1:1 일치, 두 Disjoint 그룹(AnomalyEvent 5유형, Rule 4분류) 선언 확인, `stage-check`의 `check_leakage.py`로 `ontology_v1/` PASS. **OWL 추론(예: `owlrl`)과 SHACL 실행은 아직 안 했다**(4단계).
- 설계 중 정리한 것: (1) 출처 위치 정보(쪽·인용)가 Rule과 Provenance 두 곳에 있으면 같은 사실이 두 곳이 되므로 **Provenance 한 곳으로 모음**(Rule은 `sourceDocument`로 문서만 가리킴). 그에 맞춰 `docs/competency_questions.md`의 CQ3·CQ4·CQ5 질의를 수정. (2) 식별자는 `identifier`로 통일(질의의 `id` → `identifier`). (3) 금지어와 겹치지 않도록 `ruleSeverity`, `datasetSeverity`로 이름을 붙이고, 설명 문장에도 금지어를 쓰지 않음(점검 통과를 위해). (4) 열린 쟁점 #1의 UNIQUE 제약은 `Rule.identifier`에 건다(앞의 `Rule.id` 표기를 정정).
- 새로 확인된 점: SOP-004 AccessRule 20개는 평가 86개에 포함되므로 Person 없이 텍스트 규칙으로 추출한다(열린 쟁점 #3에 반영).
- 제안 상태로 남은 것(4단계·④에서 쓰면서 확정): `actionTarget`, `sourceDocument`, `conditionText`, `extractionMethod`, `sourceQuote`.
- 미결: Task 클래스(④ 시작 전 재검토, `CLAUDE.md` ② 요구), System 노드 1개 처리.
- **`CLAUDE.md` 반영 완료(2026-10-07):** Rule 4분류·Document·Provenance, Task 보류(② 행), AccessRule 텍스트 추출, `appliesToSensor` 통합(정비 규칙 포함), `ruleIds`/`windowId`와 적재 검증, SHACL 추론 끔, camelCase 이름, 출처 위치를 Provenance 한 곳에 저장(이 항목은 3단계에서 제가 정리한 설계였고 반영 때 사용자가 확정), 7장 산출물 위치 안내. 백업: `reports/CLAUDE.md.before_3단계반영전.bak`.

### 가이드라인 4단계: SHACL (초안 완료 2026-10-07)
- 산출물: `ontology_v1/shapes.ttl`(S1~S8), `ontology_v1/examples/`(통과 5, 실패 5), `guards/leakage_shapes.ttl`(L1~L4)과 `guards/examples/`(통과 1, 실패 3), `tests/test_shacl.py`.
- 규칙: S1 센서 소속(Sensor는 `hasSensor`로 정확히 1개 Station), S2 AnomalyEvent는 `triggers`로 Sensor 1개 이상 + 하위 유형 정확히 1개, S3 `causallyAffects`(CausalLink)의 원인·결과는 Station이고 서로 다름, S4 `hasEvidence`, S5 점수 0.0~1.0·`hasLag` 0 이상, S6 근거 번호표 일치(`ruleIds`가 실제 Rule을 가리킴, `windowId`가 등록된 구간, 근거 종류와 번호표 일치), S7 Provenance 필수 필드(종류별), S8 Rule·Document 출처. 0.6 미만 제외와 이벤트당 상위 3개는 적재 스크립트 몫이며 P5 예제(점수 0.4 통과)로 SHACL이 걸러내지 않음을 보였다.
- 누수 검사(`guards/`): L1 AnomalyEvent 금지, L2 `triggers`/`correlatesWith`/`causallyAffects`/CausalLink 금지, L3 금지된 이름의 속성(정규화 비교), L4 GT-#### 식별자. 금지어를 담아 `ontology_v1/` 밖에 둠.
- **검증(이 환경에서 실행, pyshacl 0.40.1·rdflib 7.6.0):** `tests/test_shacl.py` 15개 모두 통과(통과 예제 5 적합, 실패 예제 5는 의도한 규칙 하나만 위반, 누수 가드 4, 보조 반례 12). `check_leakage.py`로 `ontology_v1`·`tests` PASS.
- **검증 중 발견한 문제와 처리:**
  1. `hasLag`·`likelihoodScore`가 정수(예: 90)로 쓰이면 `xsd:decimal` 요구에 걸림 → decimal 또는 integer 허용으로 수정.
  2. **RDFS 추론을 켜면 range 선언 때문에 Sensor가 Station으로 간주돼 S3가 무력화됨** → 검증은 `ont_graph`만 주고 `inference="none"`으로 실행(하위 클래스 관계는 ont_graph로 충분). shapes.ttl 주석과 테스트에 반영.
  3. SHACL-SPARQL 제약 안에는 `VALUES` 절을 쓸 수 없음 → `FILTER ... IN (...)`로 수정.
  4. SPARQL은 추론 없이는 하위 유형을 상위로 보지 않음 → `rdfs:subClassOf*`로 수정.
  5. `ontology.ttl`의 4개 속성(`hasProvenance`, `identifier`, `sourceNodeId`, `windowId`)에 domain이 없어서 `owl:unionOf`로 선언(체크리스트 "모든 관계에 Domain/Range").
- **해결(사용자 확정 2026-10-07): `run_shacl.py` 한 줄 수정(A).** `.claude/skills/stage-check/scripts/run_shacl.py`가 `--ont` 지정 시 `inference="rdfs"`를 써서 우리 shapes를 정확히 검증하지 못했다(Sensor가 Station으로 간주돼 S3가 무력화). `inference="none"`으로 바꾸고 `--ont`는 하위 클래스 관계만 섞는 용도로 설명을 고쳤다. 확인: 예제 10개 모두 의도대로(통과 5 PASS, 실패 5 FAIL), `fail_03`은 S3 위반으로 나옴. **주의:** 하위 유형을 쓰는 데이터(`pass_02`처럼 Rule 하위 클래스, AnomalyEvent 하위 유형)는 `--ont ontology_v1/ontology.ttl`을 꼭 줘야 한다(없으면 S6이 하위 유형을 못 봄). `--ont` 기본값을 온톨로지로 두는 개선은 아직 하지 않았다(승인 범위 밖).
- **결정(2026-10-07): `forbidden_columns.txt` 확장은 전처리 시작 때(A).** 금지어를 일반 목록(모든 파일에서 검사)과 컬럼 전용 목록(CSV 헤더·JSON 키에서만 검사: `day`, `status`, `quality` 등 흔한 단어)으로 나누는 방식으로 그때 만든다. 지금은 검사할 데이터 파일이 없고 흔한 단어는 문서에서 오탐이 많다.
- 아직 안 한 것: `CausalLink` 변환 코드와 적재 스크립트의 검증 로직(⑥ 이후), `check_raw_unchanged.py`는 `--init`이 필요한 상태라 실행하지 않음.

### 환경 마무리 (완료 2026-10-07)
- `.gitignore`: PowerShell `echo >>`가 만든 UTF-16 줄(NUL 바이트 13개)을 제거했다. 이 줄 때문에 git이 `.gitignore`를 바이너리로 취급하고 있었다(`Bin 4628 -> 4893 bytes`). 이제 변경은 `.venv/`, `imaks_data/` 두 줄이고 두 폴더 모두 실제로 무시되는 것을 `git check-ignore`로 확인했다.
- 원본 지문 기준선: `check_raw_unchanged.py --init`으로 `harness/raw_manifest.json`을 만들었다(`imaks_data/` 1,121개 파일). 바로 비교해 PASS(원본 불변). **전처리 코드를 쓰기 전의 기준선**이며, 파일 크기가 작아(약 163KB) git 추적 대상이다. 전처리 후 `check_raw_unchanged.py`로 재확인한다.
- 임시 스크립트(scratchpad)는 전처리 안에서 필요한 것만 저장소로 옮긴다(PDF 표 추출은 문서 전처리 코드로 다시 작성). 옮길 때 절대 경로는 저장소 기준 상대 경로로 바꾼다.

### 가이드라인 2단계: 전처리 (구현 + 독립 검증 PASS, 2026-10-07)
- 구현: `implementer` 서브에이전트(보고서 `reports/preprocess_impl.md`). 코드 `src/imaks_kg/{settings.py, common/, preprocess/sensors.py, preprocess/documents.py}`, 테스트 3종, 금지어 컬럼 전용 목록 `harness/forbidden_columns_header_only.txt`, `check_leakage.py` 최소 수정, `.gitignore`에 `/preprocessed/`, `/evaluation/` 추가.
- 산출물: `preprocessed/sensors/{input/ts_input.csv, metadata/original_time_labels.csv, rules/sensor_thresholds.csv, profile.json}`, `evaluation/row_labels.csv`(평가 전용), `preprocessed/documents/{doc_manifest.csv, pages.jsonl, tables.jsonl, chunks.jsonl, glyph_fixes.csv, doc_profile.json}`. 모두 git 제외 대상.
- **내가 직접 확인한 것(구현 코드를 쓰지 않고 별도 스크립트로 원본과 대조):** `ts_input` 헤더가 허용목록 7개, 211,200행 모두 원본과 문자열로 동일(불일치 0), (sensor_id, timestamp) 정렬·중복 0, 센서 22·타임스탬프 9,600, `original_time_labels`와 원본 불일치 0, 정답 컬럼은 `evaluation/row_labels.csv`로 분리(비정상 라벨 행 1,460), 임계값 파일 22행이 SOP-002 표와 일치(차이 0), 문서 7개·10쪽·표 24개(SOP-002는 센서 행 21 + 쪽에 걸친 연속 1 = 22), 청크 86개(rule 28, table 24, text 34), 청크 위치가 쪽 본문과 일치(불일치 0), 청크 해시 불일치 0, 화살표 글리프 복원 확인(SOP-001 §1 표 "thermal fault → ST04"), `RULE-ST02-04`가 한 청크에 온전히 들어 있음. 테스트 47개 통과, `check_raw_unchanged.py` PASS, `src/`의 절대 경로 0건, 정답 규칙 파일 언급 0건.
- **점검 FAIL 1건(오탐, 사람 결정 필요):** `check_leakage.py` 기본 폴더에서 `preprocessed/documents/*.jsonl` 4건이 걸린다. SOP-004 §3의 실제 제목 "Maximum Acknowledgment Times by Role and Severity"에 일반 금지어가 글자 그대로 있어서다. 원문은 고치지 않는다.
- **승인 필요 1건:** 구현자가 `check_leakage.py`에 `preprocessed/sensors/rules/` 폴더의 헤더 검사 예외를 넣었다(임계값 CSV의 헤더가 컬럼 전용 금지어와 같아서). 예외 대신 컬럼 이름을 바꾸는 방법도 있다.
- 알려진 한계: 쪽 본문(`text_normalized`)의 표 영역에는 쪼개진 셀 병합이 적용되지 않음(표 행·table 청크에만 반영). text 청크 중 30자 미만 제목 청크 15개. 연속 표 판정은 휴리스틱(이 PDF 묶음에서는 1건).

- **위 미결 2건 해결(사용자 확정 2026-10-07):** (1) 문서 폴더(`preprocessed/documents/`)는 JSON 본문 값 검사에서 제외하고 키만 검사(`TEXT_EXEMPT_PREFIXES`, 점검기의 유일한 예외). 문서는 ④ 추출용 원문이라 ⑥ 입력이 아니며 원문에 금지어 단어가 자연스럽게 나온다. (2) 임계값 CSV 컬럼명을 `nominalValue, warnLo, warnHi, critLo, critHi`로 바꾸고(온톨로지 속성과 일치) `rules/` 폴더 예외는 제거. 수정 후 `check_leakage.py` 기본 폴더 PASS, 단위 테스트 50개 통과.
- **독립 검증(`verifier`, `reports/preprocess_verify.md`): PASS.** 공통 5 + 전처리 16항목 모두 직접 계산해 확인, FAIL·미확인 없음. 이를 위해 `harness/checklist.md`에 "전처리 (센서·문서)" 절 16항목을 추가했다.
- **verifier 추가 관찰(판정 제외, 후속 개선 후보):**
  1. 금지 목록이 camelCase 임계값 이름(`nominalValue` 등)을 못 잡는다. 이름 블랙리스트는 끝이 없으므로, `preprocessed/sensors/input/`의 CSV 헤더가 허용목록 7개와 정확히 같은지 검사하는 **허용목록 검사**를 점검 도구에 추가하는 것이 낫다(현재는 `tests/test_preprocess_sensors.py`가 헤더를 검사).
  2. `evaluation/`은 기본 점검 폴더가 아니다(의도). "정답이 `evaluation/`에만 있다"는 것은 스크립트가 아니라 수동 대조로 확인했다.
  3. 문서 폴더 JSON은 본문·`ground_truth` 경고 검사를 건너뛴다(의도한 범위). `grep`으로 `preprocessed/`에 `ground_truth` 언급 없음을 확인.
  4. `original_time_labels.csv`(day/shift/batch_id 보존본)는 ⑥ 입력 목록에서 제외해야 한다(`CLAUDE.md` §4에 이미 명시). 모든 산출물이 git 무시 대상이라 `src` 재실행으로만 복원되며 `profile.json`의 해시로 대조한다.
- **남은 것:** ③ KG 변환(seed → 새 스키마, 매핑표, AnomalyEvent·`correlates_with` 분리)은 일정상 10/8 이후. 문서 쪽 쪼개진 셀 병합이 쪽 본문 표 영역에는 적용되지 않는 한계, text 청크 중 30자 미만 제목 청크 15개는 ④·⑧ 단계에서 처리.

### 정정한 사실 (내 쪽 오류)
- `day` 라벨은 1~5(각 1,920행)이고 실제 timestamp는 4일(80시간)이다. `shift`도 시계 시각과 60% 불일치. Zenodo의 "five days"는 이 라벨에서 온 것으로 보인다. 이전의 "day 1~4"는 틀렸다.
- `nodes_factory.csv`는 별도 ID 체계가 아니라 `nodes.csv`와 같은 ID에 서로 다른 이름이 붙은 6건(N0018, N0019, N0020, N0022, N0023, N0024) 충돌이다.
- Notion 배경지식 페이지 1장·4-4에도 위 오류가 남아 있음 → 수정 대기.

### 확정된 선택 (이유)
| 선택 | 이유 |
|---|---|
| 팀원 자료는 폴더로 꺼내지 않고 `git show`로만 읽음 | 읽기 전용을 구조적으로 보장, 정리할 것 없음 |
| 0~1단계 독립 초안은 서브에이전트에 맡김 | 이 세션이 이미 팀원 문서를 읽어 편향될 수 있어서 |
| 비교 루브릭을 읽기 전에 고정 | 팀원 자료에 끌려가지 않도록 |
| 채택 판단 기준을 `CLAUDE.md` 충돌 여부가 아니라 목표 G1~G3 적합성으로 | 팀원과 목표 중점이 다름(팀원: 탐지 성능·최소 제출물, 우리: `causallyAffects`·KG 구축 학습) |
| `day/shift/batch_id`는 ⑥ 입력에서 제외하고 원본은 `original_*`로 보존, `calendar_date`/`clock_shift` 파생 | B02 결함 확인됨(로컬 검증) |
| `quality`, MQTT `status/alarms`는 ⑥ 입력 제외 | 정답 파생(UNCERTAIN = STUCK 구간) |

### 결정 대기 (D1~D6). 초보자 눈높이로 하나씩 함께 결정할 것
| ID | 질문 | 수정 추천 | 상태 |
|---|---|---|---|
| D1 | ⑥ 발굴 입력에 `nominal/warn/crit` 컬럼을 쓸 수 있나 | ⑥ 입력에서는 제외, 룰·⑧⑨ 경로에서만 사용 | **확정(2026-10-07): 제외.** 이유: GT-0009(ST04 속도 1.2→약 1.05 m/s, 최저 1.006으로 경고 하한 1.0을 넘지 않음)는 임계값으로 잡히지 않고, GT-0008처럼 기준을 넘는 이상은 정답 구간과 거의 같아 간접 누수 위험. 제외는 되돌리기 쉽다(컬럼 추가). 라벨이 임계값으로 만들어졌는지는 미확정(GT-0007은 불일치) |
| D2 | `causallyAffects` 속성(`hasLag`, `hasEvidence`, `likelihoodScore`)을 어떻게 표현할지 | Neo4j에서는 관계 속성, RDF는 SHACL 검증용 변환에서만 `CausalLink` | **확정(2026-10-07): A.** Neo4j에서는 관계에 `hasLag/hasEvidence/likelihoodScore`를 직접 붙이고, SHACL 검증 때만 `CausalLink` 형태로 변환. 이유: ⑧⑨ Agent가 쓰는 Cypher 질의가 짧고, `CLAUDE.md` §3의 "관계의 속성" 문구와 맞음. 직접 관계와 CausalLink를 동시에 두는 방식은 값이 어긋날 위험이 있어 불채택. 변환 코드의 난이도는 아직 확인 못 함(만들 때 검증 필요) |
| D3 | "모든 트리플에 출처"의 범위 | 의미 트리플(CausalLink, Rule)은 전체 필드, 구조 트리플은 `origId`+seed 수준 | **확정(2026-10-07): 구분 적용(3종류로 보정).** 문서(SOP·데이터시트) 유래 규칙·근거는 전체 필드(문서ID, 쪽, 문자 위치/표 좌표, 원문 해시), seed CSV 유래 구조 정보는 파일명+원본 ID, **시계열 CSV 유래 인과 후보는 파일명+센서 ID+시간 구간+파일 해시**(처음 문구에는 이 세 번째가 빠져 있어 보정). `CLAUDE.md` §4의 "모든 트리플"을 "출처가 있으면 그 출처를 정확히"로 해석한 것이므로 팀 합의가 더 엄격하면 조정 필요 |
| D4 | `hasSensor`(Station→Sensor) vs `monitors`(Sensor→Station) | 우선순위 낮음(목표 무관). 팀 호환성만 고려 | **확정(2026-10-07): `hasSensor`(Station→Sensor).** 처음에는 선호 없음으로 답했고, 쉬운 설명(같은 사실의 두 표현, 그래프에서는 거꾸로도 탐색 가능해 영향 거의 없음)을 본 뒤 선택. 이유: 팀원 코드와 맞고 SHACL 검사("센서는 정확히 한 스테이션에 속함")를 그대로 씀. 이름 변경은 매우 쉬움 |
| D5 | Maintenance 8행, Person의 정적 취급 | Maintenance 유지, Person 제외 | **확정(2026-10-07): Maintenance 유지, Person 제외.** 처음에는 선호 없음으로 답했고, 쉬운 설명(MAINT-02 예시, Person은 출입 관리 정보라 검색 잡음 증가) 후 선택. 이유: 정비 규칙(SOP-003)은 ⑨ 조치 제안에 필요(이상 이벤트와의 연결은 ⑦ 이후), 작업자 권한 218개는 Layer 2 성격으로 설비 이상 원인과 무관 |
| D6 | (a) 정답 14건 선투입 해석 (b) 팀원 탐지 트랙을 ⑥ 베이스라인으로 쓸지 | (a) `CLAUDE.md` §4가 이미 답함(두 경로 분리), (b) 쓰지 않음 | **확정(2026-10-07): 참고만, 선투입은 `CLAUDE.md`대로.** (a) 정답 14건은 ⑦ 이후 별도 경로로 투입(⑥ 입력과 코드에서 분리), 팀 확인 불필요. (b) 팀원 탐지 트랙은 ⑥ 베이스라인으로 쓰지 않음(윈도우 설정을 검증 정답으로 골라 정답 의존). 필요하면 비교 참고용으로만 |

### 온톨로지 설계 결정 6건 (탐색에서 나온 것) - 모두 확정(2026-10-07)
서브에이전트 초안의 추천안을 쉬운 설명 후 하나씩 확인했다. 3번과 6번은 초안 추천과 다르게 정했다.
| # | 결정 | 이유 |
|---|---|---|
| 1 | 이상 유형 클래스 이름은 **SOP-002 이름**(`Spike`, `Drift`, `StuckSensor`, `OutOfRange`, `Correlated`)으로 `AnomalyEvent`의 하위 클래스, 서로 Disjoint | SOP-002 표의 "Ontology Class" 열과 같아 ④ 추출·출처 추적이 쉽고 Disjoint 검사(`CLAUDE.md` ②)를 쓸 수 있음. 이름은 일괄 치환으로 변경 가능 |
| 2 | 이상↔센서 방향은 **원본 그대로** `Sensor triggers AnomalyEvent` | 원본과 1:1 대응으로 매핑표가 단순. 의미는 주석으로 설명. ⑦ 이후에만 사용 |
| 3 | 정비 규칙-센서 중복 선(`triggers` Sensor→Maintenance 8개와 `resolves` Maintenance→Sensor 8개가 **같은 8쌍**)은 **센서→정비 규칙(조건 방향) 한 줄만** 유지. 관계 이름은 설계 단계에서 확정 | SOP-003 표의 `Sensor/Trigger/Action` 열과 1:1이고 `resolves`는 해소를 보장하는 것처럼 읽힘. **초안 추천(`resolves` 유지)에서 변경**. 이 관계 이름이 `Sensor→AnomalyEvent`의 `triggers`와 겹치지 않게 별도 이름을 쓴다 |
| 4 | `monitors` 양방향은 단방향으로 정리 → D4(`hasSensor` Station→Sensor)로 **해결** | 같은 사실이 22쌍 중복 |
| 5 | SOP-003 §2의 도착점이 공정이 아닌 2패턴(서버실 온도→SCADA 지연, 창고 온도→QC HOLD)은 **`causallyAffects`로 만들지 않고 규칙 텍스트(SOPRule)로만 보관**. 단 ④ 추출·⑤ 평가에는 포함(`ground_truth`에 `RULE-CORR-02/03` 있음) | `causallyAffects`는 Station→Station만(§3), 품질 연결은 제외(§3). Agent는 이 두 패턴을 규칙 텍스트로만 답함 |
| 6 | **Zone 클래스를 두지 않고 Station의 `zone` 속성으로 흡수** (Zone 노드 7개와 `contains` 제거, Main Entrance 불필요) | **초안 추천(분리 유지)에서 변경.** D5로 Person(출입 권한)을 제외하면서 Zone의 주 용도가 사라졌고, 생산 순서는 `feedsInto`가 이미 표현 |

참고 확인 사실: Station(Component) 9개는 Production Area(ST01~ST04) 1곳과 보조 구역 5곳(각자 1개)에 속한다. Main Entrance는 스테이션·센서가 없는 구역이다.

### 미확인 (추정하지 않음)
- 팀원 `generated/`, `validation/` 본문(실행 결과 수치), 팀원 탐지·윈도우·벤치마크·LLM 평가·assistant 계열 코드. 팀원의 "검증 통과"는 이 환경에서 재실행하지 않았다(팀원 pyshacl 0.30.1, 우리 `.venv` 0.40.1).
- 데이터시트 vs SOP-002 수치 충돌은 후보 3건(ST02 TMP 200 vs 210℃, ST02 CUR 14 vs 15.0 A, ST01 PRS 마진)이다. 어느 것이 공식 충돌인지는 원문에 명시가 없다. 임의로 통일하지 않고 출처와 함께 둘 다 기록한다.
- `sh:sparql`·`sh:inversePath`가 우리 환경에서 동작하는지 실행해서 확인하지 않았다.

### 다음 할 일
1. (완료) D1~D6와 온톨로지 설계 6건 결정.
2. Notion 배경지식 페이지의 오류 수정과 결함 B02·B05~B07 추가.
3. (완료 2026-10-07) 확정 내용을 `CLAUDE.md` 2·3·4장에 반영. 수정 전 백업: `reports/CLAUDE.md.before_2026-10-07.bak`. handoff 문서 반영은 아직.
4. 가이드라인 단계: 1단계 Competency Questions → 2단계 전처리 → 3단계 온톨로지 → 4단계 SHACL.
5. 0단계 마무리: `.gitignore`의 UTF-16 깨진 줄 정리, `CLAUDE.md` 커밋(작업 완료 후 한꺼번에).

## 2026-10-12

### 2번째 작업 시작 전 환경 정리 (브랜치 `유진-2번째작업`)
- 원본 폴더 `iMAKS_dataset/` → `imaks_data/`: 사용자가 직접 이름을 바꿈(원본 보호 훅이 이 폴더에 대한 이동 명령을 막으므로). 바꾼 뒤 `check_raw_unchanged.py` PASS(1,121개 파일, 기준선 그대로).
- `.gitignore`에 `/.deps/`(예전 `pip --target` 설치본, 참조 없음, 삭제하지 않음)와 `/data/`(팀원 산출물로 보이며 정답 파일 포함, 내용은 열지 않음)를 추가.
- `.venv` 생성(Python 3.12.10): pdfplumber 0.11.10, pdfminer.six 20260107, rdflib 7.6.0, pyshacl 0.40.1.
- 전처리 재실행: 센서(211,200행, 센서 22, timestamp 9,600, 임계값 22행), 문서(문서 7, 10쪽, 표 24, 청크 86 = rule 28·table 24·text 34, SOP-002 센서 행 22가 임계값 파일과 일치, 경고 0).
- 확인: `unittest discover -s tests` 50개 통과, `check_raw_unchanged.py` PASS, `check_leakage.py` 기본 폴더 PASS.
- B 전에 확인할 것: 예전 기록에는 CSV 컬럼 이름을 온톨로지에 맞췄다고 돼 있지만 `ontology.ttl`에는 `nominal`이 남아 있다(결정 필요 #2).

### [A] 기존 KG 변환 ③ (구현 + 독립 검증 PASS, 2026-10-12)
- 구현: `implementer`(`reports/seed_to_rdf_impl.md`). 코드 `src/imaks_kg/kg/{naming.py, seed_to_rdf.py, seed_events_post7.py}`, 테스트 `tests/test_seed_to_rdf.py`(21개), `settings.py` 경로 상수 추가, `.gitignore`에 `/kg_build/`.
- 산출물: `kg_build/seed.ttl`(Station 9, Sensor 22, hasSensor 22, feedsInto 3, Provenance 56, 482 트리플, 결정적), `reports/seed_to_rdf_counts.md`(코드 생성).
- 대조: 노드 115 = 변환 31 + 이월(B) 8(Maintenance) + 이월(⑦) 14(AnomalyEvent) + 제외 62(System 1, Zone 7, Person 44, SafetyEvent 10). 엣지 341 = 변환 47(monitors 44→hasSensor 22, feeds_into 3) + 이월(B) 16(triggers Sensor→Maintenance 8, resolves 8) + 이월(⑦) 15(triggers Sensor→AnomalyEvent 14, correlates_with 1) + 제외 263.
- 설계 선택(구현자): 인스턴스 IRI는 원본 name(`inst:ST02_SEALING`). 관계 출처는 온톨로지에 관계 트리플용 수단이 없어 노드에 붙임(hasSensor 출처→Sensor, feedsInto 출처→주어 Station). monitors 2줄은 Provenance 하나에 `sourceRowId` 두 개(`row:<n>`). 임계값 컬럼은 허용목록 방식으로 Sensor에 들어갈 수 없게 함. ⑦ 경로 모듈은 gtId·causedBy·sourceRule을 KG 속성으로 올리지 않고, seed_to_rdf에서 부르지 않음. System 노드는 제외로 처리.
- 검증: `verifier`(`reports/seed_to_rdf_verify.md`) PASS(공통 5 + ③ 3, FAIL·미확인 0). stage-check(원본 불변, 누수 `preprocessed ontology_v1 kg_build src`, SHACL) 모두 PASS. 단위 테스트 71개 통과.
- 후속 후보(판정 제외): (1) shapes.ttl이 Sensor의 임계값 속성을 잡지 못함(코드·테스트로만 보장). (2) 관계 단위 출처 표현(reification / `hasProvenance` domain 확장 / Provenance에 관계 종류 속성) 미결. (3) `row:<n>`이 edges.csv 행 순서에 의존하는데 Provenance에 파일 해시가 없음(대조표에만). (4) counts.md가 `/reports/*` 규칙으로 git 제외. (5) Component `description` 미반영. (6) correlatesWith의 `ruleRef` 보존 방법은 ⑦ 전에 결정.

### [B] 시작 전 결정 (사용자 확정 2026-10-12)
| # | 결정 | 이유 |
|---|---|---|
| 1 | ThresholdRule은 **센서당 1개(22개)**. 한 규칙에 nominalValue·warnLo·warnHi·critLo·critHi와 CRITICAL Response 조치(`responseText`)를 담는다 | SOP-002 표는 센서마다 한 행이고 조치 열은 "CRITICAL Response" 하나뿐이다. 경고 등급 조치 문구가 원문에 없어 등급별로 나누면 문구를 만들어 넣어야 한다. 정답 파일은 보지 않고 정함 |
| 2 | 온톨로지 `nominal` → **`nominalValue`**로 변경(`ontology.ttl`, `schema_tables.md`). 누수 가드 L3 목록에 `nominalvalue` 추가(기존 `nominal` 유지) | 전처리 CSV·seed가 `nominalValue`를 쓰고, `nominal`은 컬럼 전용 금지어라 CSV 쪽을 바꾸면 점검기 예외가 필요하다. L3는 이름이 정확히 같을 때만 잡으므로 새 이름도 넣어야 ⑥ 입력 검사가 유지된다 |
- `harness/checklist.md`에 "Rule·Document 승격 (B)" 8항목 추가(사용자 승인).
- nominal 옆 허용오차(± 0.4 등)는 온톨로지에 속성이 없다. 원문은 표 Provenance로 남는다.

### [A] 수용과 B에 반영할 요청 (사용자 2026-10-12)
- A는 완료로 받아들임. 관계 출처를 노드에 붙인 방식도 A에서는 수용.
- `.gitignore`에 `!/reports/seed_to_rdf_counts.md` 예외를 추가해 상세 대조표를 git에 남길 수 있게 함(커밋은 아직 안 함).
- B에서 반영: Sensor에 임계값 속성(nominalValue, warnLo, warnHi, critLo, critHi)이 붙으면 SHACL이 실패하는 **명시적 금지 shape**를 추가하고 실패 예제로 확인한다(domain 선언에 기대지 않음).
- **후속 과제(온톨로지 변경안은 구현 전에 사용자에게 먼저 보여 줌):** (1) 관계 단위 출처 표현(현재는 노드에 붙임). (2) 원본 파일 해시를 Provenance에 보존(현재 `row:<n>`은 행 순서에 의존하고 해시는 대조표에만 있음).

### [B] Rule·Document 승격 (구현 + 독립 검증 PASS, 2026-10-12)
- 구현: `implementer`(`reports/promote_rules_impl.md`). 코드 `src/imaks_kg/kg/promote_rules.py`, `naming.py`(IRI 함수 추가), `settings.py`(경로 상수), 테스트 `tests/test_promote_rules.py`(17개). LLM 호출 없음.
- 산출물: `kg_build/rules_deterministic.ttl`(Document 7, MaintenanceRule 8, ThresholdRule 22, Provenance 240 = 문서 표 셀 224 + seed CSV 16, 2,676 트리플, 결정적), `kg_build/seed_plus_rules.ttl`(SHACL용 합본), `reports/maint_mapping.md`, `reports/threshold_mapping.md`(코드 생성).
- **S9 추가(사용자 요청):** `shapes.ttl`에 `im:SensorNoThresholdShape`(Sensor에 nominalValue·warnLo·warnHi·critLo·critHi가 있으면 `sh:maxCount 0`으로 실패). domain 선언에 기대지 않는 명시적 금지다. 실패 예제 `ontology_v1/examples/fail_06_sensor_threshold.ttl`은 S9만 위반하고, 기존 예제 10개의 판정은 그대로다.
- 대조 결과: MAINT 8행 중 seed와 SOP-003 문구가 같은 것 3(05·06·08), 다른 것 5(01·02·03·04·07). 다른 것은 모두 조치 문구이고 센서·우선순위 차이는 0이다. 임계값 22행 × 5값 + 단위는 KG·seed·`sensor_thresholds.csv`·SOP-002 본문 네 곳에서 불일치 0.
- 설계 선택(구현자): ThresholdRule identifier는 `SOP-002:THR:<센서 identifier>`. 문서 Provenance는 셀 하나당 하나(page, tableId, rowIndex, colIndex, bbox, sourceQuote, textSha256). MaintenanceRule의 responseText는 seed action이다(SOP-003 문구는 Provenance 인용과 대조표에 있음). ThresholdRule에는 `unit`을 붙이지 않았다(온톨로지에서 `unit`의 domain이 Sensor라서). 원문에 없는 값(ruleSeverity, conditionText, ± 허용오차)은 만들지 않았다.
- 검증: `verifier`(`reports/promote_rules_verify.md`) PASS(공통 5 + B 8, FAIL·미확인 0). 사용자 중점 3건(MAINT 문구 차이 8행, 임계값 22행 수치, 문서 Provenance 224개 전수를 셀·해시·PDF 해시까지)을 독립 스크립트로 확인해 불일치 0. stage-check(원본 불변, 누수, 합본 SHACL) PASS, 단위 테스트 90개 통과.
- 후속·미결(판정 제외): (1) Provenance에 문서 ID 전용 속성이 없다. 지금은 Rule의 `sourceDocument`와 tableId 접두어로만 알 수 있다(§4 "위치는 Provenance 한 곳" 원칙과는 맞음). 관계 단위 출처·파일 해시 후속 과제와 함께 온톨로지 변경안으로 다룬다. (2) MaintenanceRule 대표 문구를 seed로 둘지 SOP-003으로 둘지, SOP-003 Trigger를 conditionText로 넣을지. (3) ThresholdRule 단위 속성. (4) extractionMethod 어휘 고정. (5) sourceQuote·해시는 정규화 텍스트 기준(셀 18개가 text_raw와 줄바꿈이 다름). (6) `maint_mapping.md`·`threshold_mapping.md`는 `/reports/*` 규칙으로 git에서 제외됨.
- verifier 관찰 O5(`ontology.ttl`·`.gitignore`·`work_log.md` 수정자)는 내가 한 변경이다(결정 #2 이름 변경, gitignore 예외, 기록).

### B 보완 요청과 MAINT 병합 기준 (사용자 확정 2026-10-12)
- B 보완(사용자 요청):
  - (1) 해시 사슬 검사: PDF → 고정 전처리 기록(`harness/preprocess_lock.json`) → pages/tables/manifest → rules. 어긋나거나 오래된 전처리 결과이면 산출물을 쓰기 전에 멈춘다.
  - (2) 임계값을 바꾼 반례 테스트를 추가한다.
  - (3) `maint_mapping.md`, `threshold_mapping.md`를 `.gitignore` 예외로 보존한다(적용 완료, 커밋 안 함).
  - 해시 사슬 구현은 첫 시도 때 세션이 끊겨 반영되지 않아 다시 진행 중이다.
- **MAINT 병합 기준(정답 파일을 보지 않고 문서 구조로 정함):**
  1. 조건 보완은 B에서 결정적으로 한다. SOP-003 Trigger 셀을 MaintenanceRule `conditionText`로 넣고 셀 Provenance를 붙인다.
  2. C 결과가 B 규칙과 같은 규칙이면 새 규칙을 만들지 않고 합친다. 같은 규칙의 기준은 (a) `ruleIdInText`를 정규화한 값이 B identifier와 같거나, (b) ID는 없지만 sourceQuote가 B 셀 출처와 같은 표의 같은 행인 경우다. B의 값은 덮어쓰지 않고 LLM 출처는 "재확인" 출처로 덧붙인다. 값이 다르면 `extraction/merge_conflicts.csv`에 기록해 1차 사람 검토로 넘긴다.
  3. D 예측 집합은 병합 후 고유 identifier이고, 합친 규칙은 한 번만 센다("B 유래(C 재확인)"). LLM 단독 결과는 병합 전으로 따로 보고하고 주 F1에는 넣지 않는다.
  4. ID가 다른 규칙은 수치가 같아도 합치지 않는다(예: SOP-001 `RULE-ST02-02` vs SOP-002 ST02 TMP 임계값). SOP-003 표 2의 패턴 3개는 C에서만 위치 기반 ID로 만든다.
- **MaintenanceRule `responseText` = SOP-003 Action 셀 원문**으로 바꾼다(기존 seed action). 이유: `sourceDocument`·출처 인용과 문구를 일치시키기 위해서다. seed 문구 차이는 `maint_mapping.md`와 seed Provenance에 남는다. (1)·이 변경은 해시 사슬 보완 뒤 B에 반영한다.

### [B] 보완 반영과 2차 독립 검증 PASS (2026-10-12)
- **해시 사슬:** `src/imaks_kg/kg/preprocess_lock.py`, `harness/preprocess_lock.json`(git 추적, SHA-256 `c7998ba8…14d8`).
  - lock에 담은 것: PDF 7개, 문서 산출물 5개, `sensor_thresholds.csv`, 전처리 코드 2개의 해시와 근거 보고서.
  - 갱신은 `--init --force`로만 한다.
  - promote_rules는 산출물을 쓰기 전에 다음을 모두 확인하고, 하나라도 틀리면 멈춘다(새 파일 0, 기존 출력 불변): PDF 해시 == lock == doc_manifest, 산출물 == lock, doc_profile 기록 == 현재 파일, 코드 == lock, SOP-002 22행 수치 == `sensor_thresholds.csv`(의미 검사).
  - lock을 만들기 전에 전처리를 임시 폴더에서 다시 돌려 현재 `preprocessed/`와 해시가 같음을 확인했다(구현자 보고).
  - 반례 테스트 10개를 추가했다(임계값 변경, lock까지 맞춘 변경, pages, PDF 해시, doc_profile, 코드, 정상, mtime 불변 등).
- **MAINT 문구 출처(결정 반영):** `conditionText`는 SOP-003 Trigger 셀, `responseText`는 Action 셀 원문이며 둘 다 셀 Provenance가 있다. seed action은 KG에서 빼고 대조표와 seed Provenance에만 남긴다. priority·센서가 seed와 SOP-003에서 다르면 멈춘다(현재 8행 일치).
  - 구현자가 지시 없이 MaintenanceRule의 `extractionMethod`를 "seedCsv"에서 "table"로 바꿨다. 사용자 확인 대기.
- **2차 검증:** `verifier`(`reports/promote_rules_verify.md`, "2차 검증(보완 후)") PASS. 공통 5 + B 8 항목, 독립 점검 104건 PASS, FAIL 0.
  - 멈춤 5경우를 사본으로 직접 재현했다.
  - MAINT 8개 조건·조치가 셀과 일치하고 Provenance 224개 전수 불일치 0, 임계값 110개 값 불일치 0.
  - 단위 테스트 101개 통과. stage-check(원본 불변, 누수 + lock 파일, 합본 SHACL)와 `preprocess_lock` 검사 PASS.
- **남은 한계(후속):**
  1. 표·lock·doc_profile을 함께 고치면 SOP-002 수치 밖의 변조(예: MAINT Action 셀)는 막지 못한다. 남는 방어선은 lock 변경의 git diff 리뷰다.
  2. 코드 해시는 documents.py·sensors.py만 본다(공용 모듈, pdfplumber 버전 제외).
  3. lock 기준선은 10-12 재생성본이다. 10-07 출력 해시는 기록이 없어 직접 비교할 수 없다.
  4. `check_leakage.py harness` 폴더 전체 검사는 금지어 목록 파일 자체 때문에 FAIL(알려진 오탐)이다. lock 파일만 지정하면 PASS다.

### [B] 완료 수용 (사용자 2026-10-12)
- B를 완료로 받아들임(해시 연결 검사, 변조 시 중단, 기존 출력 보존, B 테스트 28개 통과 확인).
- MaintenanceRule의 `extractionMethod`는 **"table"로 유지**(사용자 확정). 조건·조치 문구의 실제 추출 방식에 맞춘다. priority·센서·원본 ID는 seed 값이며, 표와 일치하는지 검사한 뒤 쓴다.
- C 준비 점검: `ANTHROPIC_API_KEY` 등 LLM 키 환경변수는 모두 설정되지 않았고, `ant` CLI도 없다. `.venv`에 `anthropic` SDK는 아직 설치하지 않았다.

### [C] 시작 전 결정 (사용자 확정 2026-10-12)
| # | 결정 | 이유 |
|---|---|---|
| 3 | **Task 클래스는 만들지 않는다. `responseText`를 유지**하고, LLM 출력 JSON에 선택 항목 `actionSteps`(조치 단계 목록)를 받아 원본 응답에만 보존한다(KG에는 넣지 않음). Task 노드는 ⑨에서 필요할 때 다시 검토한다 | ⑤는 4분류 규칙 단위로 채점하므로 Task가 점수에 영향을 주지 않는다. 단계 정보가 원본 응답에 남아 있어, 나중에 LLM을 다시 돌리지 않고 Task를 만들 수 있다. `CLAUDE.md` ②의 "④ 전 재검토" 요구를 이것으로 처리한다 |
| 4 | **LLM은 Claude Opus 5.5(`claude-opus-5-5`)**, Anthropic 공식 Python SDK를 쓴다. 출력은 구조화 출력(JSON 스키마)으로 받고, effort는 고정해서 기록한다 | 현재 기본 모델이다. **작업 요청서의 "temperature 0"에서 벗어난다:** 현재 세대 모델은 temperature를 바꾸면 400 오류가 난다. 재현성은 모델 ID, effort, 프롬프트 버전·해시, 입력 청크 해시, 원본 응답 저장으로 확보한다(temperature 0이어도 완전한 결정성은 보장되지 않는다) |
| 4 | **API 키는 Windows 사용자 환경변수 `ANTHROPIC_API_KEY`**로 사용자가 직접 설정한다. 코드는 SDK 기본 방식으로만 읽고 키를 로그·실행 기록에 남기지 않는다 | 저장소에 키 파일이 생기지 않는다. Claude는 키를 입력하거나 보지 않는다 |
- `harness/checklist.md` ④ 절에 10항목 추가(사용자 승인): MAINT 병합 5 + 인용문·ID·해시 사슬·재현 정보·검토 결과 보존 5.
- "병합 규칙은 D에서 한 번만 센다"는 D 체크리스트에 넣는다.
- LLM 실제 호출은 비용이 들므로, 실행 전에 예상 토큰·비용을 보여 주고 승인받는다.

### [C] 구현 시작 (2026-10-12)
- `.venv`에 anthropic 1.13.0(httpx2 기반), pydantic 2.14.1을 설치했다.
- `.gitignore`에 `/extraction/`(실행 로그·원본 응답·검토 CSV)을 추가했다.
- 호출 설정: `client.beta.messages.create`, model `claude-opus-5-5`, effort `high`(고정), 구조화 출력(JSON 스키마), `fallbacks: "default"`(beta `server-side-fallback-2026-07-01`, 거부 시 서버가 다른 모델로 다시 실행). 실제로 답한 모델과 폴백 여부를 기록하고, 폴백으로 나온 결과는 검토 CSV에 표시한다. temperature·thinking 파라미터는 보내지 않는다.
- 이번 구현은 가짜 응답으로만 테스트한다. 실제 호출은 Example 확정, API 키 설정, 비용 승인 뒤에 한다.

### [C] 보완 요청: 검토 완료·입력 동일성 검증 (사용자 2026-10-12)
- 사용자 확인: 가짜 응답 테스트 55개 통과. 다만 RDF 출력 단계가 사람 검토 완료를 검증하지 않음.
- 반영 요청:
  - (1) `to_rdf.run`은 `review_applied.json`이 있어야만 동작한다. 기록된 해시와 현재 `final.jsonl`·`merged.jsonl`·1차·2차 검토 파일이 다르면 출력 전에 멈춘다.
  - (2) 실행 기록(meta.json)에 seed.ttl·rules_deterministic.ttl 해시를 저장한다. 검토·출력 때 이것을 preprocess_lock·청크 해시와 함께 추출 당시 값과 비교하고, 다르면 멈춘다.
  - (3) 반례 테스트: 검토 기록 없음, 검토 후 조치 변경, 검토 CSV 변경, B 산출물 변경 외에 seed·청크·lock 변경, 멈춘 경우 기존 출력 불변.
- 구현은 C 구현 에이전트에게 맡김(진행 중).

### [C] 구현 + 1차 독립 검증 PARTIAL (2026-10-13)
- 구현: `src/imaks_kg/extract/`(inputs, prompt, schema, llm, run, validate, merge, conflicts, review, to_rdf, guard), `prompts/v1/{system.md, examples.json}`, 테스트 6개 파일. 실제 LLM 호출은 하지 않았고 가짜 응답으로만 실행했다. 전체 단위 테스트 171개 통과. leakage·raw 점검 PASS.
- dry-run: 호출 60회(SOP-001 35, SOP-004 11, SOP-002 본문 10, SOP-003 4). 제외 26개(SOP-002 표 11, 데이터시트 15). 입력 약 13만 토큰(글자 수 추정).
- 가짜 응답 전체 경로(fake → validate → merge → review → apply → to_rdf): 합본 SHACL PASS, 병합 후 identifier 중복 0, B 규칙 값 불변. conflicts.csv 후보 5건(ST02 TMP 210 vs 200, ST02 CUR 15.0 vs 14, ST01 PRS 여유)은 통일하지 않고 양쪽 출처를 기록했다.
- 지시와 다르게 구현한 것(구현자):
  - (1) 표 청크 인용은 charStart가 아니라 표 좌표(tableId/rowIndex/colIndex/bbox). CLAUDE.md §4 "표는 좌표"와 B 방식에 맞춘 것이다.
  - (2) merge_conflicts.csv를 실행 폴더 안에 둔다.
  - (3) 예시 상태 키를 `confirmationStatus`로 했다(`status`가 금지어라서).
  - (4) 폴백 응답은 마지막 fallback 블록 뒤의 text를 쓴다.
- 독립 검증(`reports/extract_verify.md`) PARTIAL: 19항목 중 17 PASS, 2 FAIL.
  - FAIL 2건은 체크리스트 문구와 맞지 않는 것이다. 위의 (1)·(2)로, 내용은 맞고 편차도 합리적이라는 판정이다.
  - 체크리스트 밖에서 검토 기록 위조가 1건 통과했다: 1차 결정 변경 + final 삭제 + review_applied 재계산. manifest의 1차 확정 해시를 대조하지 않은 탓이다. 구현자에게 수정과 반례 테스트를 요청했고, `--execute` 경로 테스트의 실제 네트워크 위험도 mock으로 바꾸도록 했다.
- 판정 외 관찰:
  - 예시 3개의 출처 청크가 추출 입력과 겹친다. ⑤에서 이 청크를 따로 표시하거나 빼고 본 수치를 함께 보고한다.
  - Provenance에 청크·실행·모델·문서 ID 속성이 없다.
  - extractionMethod가 domain 밖인 Provenance에 붙어 있다.
  - 다른 ID로 B 표 행을 인용한 후보는 표시 없이 새 규칙이 된다.
  - `--execute`에 비용 승인 장치가 없다.
- **사용자 확정(2026-10-13):**
  - (1) 체크리스트 ④ 두 항목의 문구를 구현에 맞게 고쳤다. merge_conflicts는 실행 폴더 안에 두고, 인용 위치는 본문이면 charStart·charEnd, 표면 표 좌표로 쓴다.
  - (2) 제목·머리말 청크도 LLM에 보낸다(60회 그대로). 사람이 입력을 골라 빼는 선택 편향을 피하고, 오탐도 확인하기 위해서다.
  - (3) `--execute`에 비용 승인 장치를 넣는다. dry-run이 추정 ID와 호출 상한을 남기고, `--approve <ID>`가 있어야만 실행된다. 입력이 바뀌면 승인은 무효가 된다.
  - Example 초안 3개는 사용자 확정 대기 중이다(예시 2의 conditionText, 예시 3의 분류).

### [C] 방향 변경: Gemini 무료 API (사용자 2026-10-13)
- **LLM 제공자를 Anthropic에서 Gemini API Free Tier로 바꾼다**(결제가 연결되지 않은 Google 프로젝트). OpenAI 어댑터 준비는 중단했다. **유료 API로 자동 전환하지 않는다.**
- 키: 사용자가 프로젝트 루트 `.env`에 `GEMINI_API_KEY`를 설정했다(`.gitignore`의 `.env` 규칙으로 무시됨을 확인, 값은 열지 않음). 코드는 이 한 줄만 읽어 `genai.Client(api_key=...)`에 명시적으로 넘긴다. `GOOGLE_API_KEY`도 함께 있으면 멈춘다(SDK가 GOOGLE_API_KEY를 먼저 쓰기 때문).
- 이미 구현된 것 확인(코드 기준):
  - 오류 분류(FATAL_AUTH/BILLING/REQUEST, TRANSIENT_RATE, AMBIGUOUS)
  - Anthropic SDK 내부 재시도 끔(`max_retries=0`)
  - 승인 상태(unused → reserved → used / released / usage_check_required, resolve 명령)
  - `--chunk`
  - 이것들은 다시 만들지 않고 Gemini에도 적용한다. 제공자에 따라 다른 부분만 어댑터로 분리한다.
- google-genai 2.30.0 확인:
  - `HttpOptions.retry_options`가 None이면 재시도하지 않는다(1회 시도). 지정하면 기본 5회, 408/429/5xx를 재시도한다. 그래서 retry_options를 지정하지 않는다.
  - timeout 단위는 ms다.
  - 오류는 `errors.APIError`(ClientError 4xx / ServerError 5xx)이며 code, status, message, details를 가진다.
- Gemini 오류 분류:
  - 키 오류는 401이 아니라 400 INVALID_ARGUMENT + `API_KEY_INVALID`로 올 수 있다.
  - 429 RESOURCE_EXHAUSTED는 QuotaFailure로 나눈다. 분당 한도면 TRANSIENT, 일일 한도나 무료 배정 0이면 FATAL_QUOTA.
  - 400 FAILED_PRECONDITION(지역·결제 필요)은 FATAL.
  - 500/504와 전송 타임아웃은 AMBIGUOUS.
- temperature: Gemini는 지정할 수 있으므로 **0으로 둔다**(원래 작업 요청서 문구와 일치). 모델 ID는 사용자가 정한다(무료 사용 가능 여부를 추측하지 않음).
- 무료 등급은 분당 요청 한도가 낮다. 호출 간격 옵션을 두어 429를 미리 피한다. 비용은 0으로 기록하고, 대신 호출 수·토큰·간격을 기록한다.
- 진행 순서(사용자 지시): Gemini 연결·테스트 → C 2차 독립 검증 → 예시를 사용자에게 보여 주고 확정 → 대표 청크 1개 → 3~5개 시험 → 소규모 결과 보고 후 확인받아 전체 추출.

### [C] Gemini 보완 요청과 모델 확인 (사용자 2026-10-13)
- 사용자 확인: Gemini 테스트 22개 통과.
- 보완 요청:
  - (1) 승인 청크 수와 재시도 상한 충돌을 고친다. 지금은 청크 1개에서 첫 429 뒤 재시도가 막힌다. 처리 청크 수(`max_chunks`)와 API 시도 상한(`max_attempts`)을 나누고 각각 기록한다.
  - (2) 이어하기(`--resume-from`): 무료 한도로 멈춘 뒤 성공 응답만 재사용한다. 모델·생성 설정·프롬프트·예시·입력 해시가 다르면 재사용을 거부한다. 여러 실행을 합쳐도 같은 청크·규칙이 중복되지 않는지 검사한다.
  - (3) 전송 대상을 이번 합성 데이터셋의 SOP(SOP-001~004, `imaks_data/rules/`)로 제한한다. 사용자가 무료 등급 데이터 정책을 이해했음을 확인했다.
- 모델:
  - 사용자 우선 후보는 `gemini-3.8-flash`다. 프로젝트 모델 목록(`models.list`, 생성 없음)에 있고 generateContent를 지원한다.
  - 무료 사용 가능 여부는 목록으로 알 수 없어 첫 호출에서 확인한다. 쓸 수 없으면 자동으로 바꾸지 않고, 목록에 있는 다른 후보(gemini-3.7-flash, gemini-3.5-flash, gemini-2.5-flash, flash-lite 계열)를 사용자에게 제안한다.
- 진행 순서: 보완 → C 2차 독립 검증 + 최신 보고서 → Example 확인(사용자) → 대표 청크 1개 → 3~5개 → 소규모 결과 보고 후 전체 추출.

### [C] Gemini 보완 + 2차 독립 검증 PARTIAL (2026-10-13)
- 구현 완료(구현자 보고):
  - 어댑터 분리(기본 gemini, Anthropic은 `--provider anthropic`으로만), `GEMINI_MODEL="gemini-3.8-flash"`.
  - 요청 설정: temperature 0, seed 20261012, JSON 스키마, max_output_tokens 8192. SDK 재시도 없음(retry_options 미지정, timeout 600000ms).
  - Gemini 오류 분류: QuotaFailure 근거를 문구보다 먼저 본다.
  - 청크 수와 시도 상한 분리: `approved_attempts = min(N×3, N+10)`.
  - `--resume-from`, SOP 전송 허용 목록, 호출 간격 6초, 자동 전환 없음.
  - 테스트 239개 통과.
- 대표 청크 dry-run(SOP-001:p1:RULE-ST02-04): gemini-3.8-flash, 청크 1, 시도 상한 3, 입력 약 2,173~2,897 토큰(글자 수 추정), 출력 상한 8,192, 무료(비용 0).
- 모델 목록: 사용자 지시로 `models.list`를 실행했다(생성 없음). gemini-3.8-flash가 있고 generateContent를 지원한다.
- **2차 독립 검증(`reports/extract_verify.md`): PARTIAL.** 체크리스트 19항목은 모두 PASS. 추가 확인 10개 중 8개 PASS, 2개에서 FAIL 하나씩.
  1. applied와 manifest를 함께 맞춰 위조하면 to_rdf가 막지 못한다. 실행 폴더 안의 기록끼리만 대조하는 구조적 한계로, 구현 보고서도 이미 인정한 부분이다. 실행 폴더 밖 신뢰 기준점이 필요하다 → 사용자 결정 대기.
  2. 이어하기의 served model 비교가 앞부분 일치라서 `gemini-3.8-flash-lite`도 허용했다 → 구현자에게 수정 요청(정확히 같거나 숫자 버전 접미사만 허용).
- 판정 밖 관찰:
  - 실제 Gemini 응답·오류 형식은 아직 확인하지 않았다.
  - 6초 간격은 분당 10회 경계와 정확히 같아 여유가 없다.
  - 승인 기록의 state 필드가 내용 해시 밖에 있다. 손으로 고치면 승인을 다시 쓸 수 있다(1번과 같은 종류).
  - Provenance 속성 미비, extractionMethod가 domain 밖에 쓰임.
  - 예시 청크 3개가 입력과 겹친다.
- **사용자 확정(2026-10-13):**
  - (1) 서로 맞춘 위조를 막기 위해 **git이 추적하는 해시 장부** `harness/extraction_ledger.jsonl`을 둔다. 추가만 하고, 앞 항목 해시를 이어 가는 체인이며, run_id·이벤트·파일명·해시·시각만 담는다.
    - 검토·출력·승인 검사가 모두 이 장부와 대조한다. 승인 state도 장부의 이벤트로 다시 계산해 파일과 비교한다.
    - 한계: 장부까지 고쳐 커밋하면 git 이력 검토 말고는 잡을 수 없다.
  - (2) Gemini 호출 간격 기본값을 **7.5초**로 한다(분당 약 8회). 실제 한도는 첫 시험 호출에서 확인해 조정한다.
  - Example 3개는 사용자 확인 대기 중이다(예시 2의 conditionText, 예시 3의 MaintenanceRule 분류).

### [C] 2차 검증 보완 확인 PASS (2026-10-14)
- 구현 에이전트는 사용 한도로 최종 보고 직전에 멈췄지만, 코드·테스트·보고서(extract_impl 15·16장)는 모두 반영돼 있었다. 직접 확인한 결과: 전체 단위 테스트 251개 통과, leakage(기본 + 장부 포함 폴더)·원본 불변 PASS, 실제 장부 0줄.
- 보완 확인(`verifier`, `reports/extract_verify.md` 끝의 "2차 검증 보완 확인" 절): **PASS**. 원래 2차 판정 PARTIAL은 문구 그대로 두었다.
  - served model: 정확히 같거나 3자리 숫자 접미사만 허용한다.
  - 서로 맞춘 위조(j): 장부 검사로 출력 전에 멈춘다(대조군: 장부를 끄면 통과).
  - 장부 사슬: 중간 삭제·수정·순서 바꾸기, 장부 없음을 모두 잡는다. 승인 상태를 손으로 되돌리면 거부한다. 장부에 내용·키 0건.
  - 호출 간격 7.5초. 대표 청크 dry-run은 네트워크 0회.
- 내가 직접 고친 것: `run.py`의 `--model` 도움말을 현재 동작(기본 gemini-3.8-flash, 자동 전환 없음)에 맞게 수정.
- 남은 한계·권고:
  - 위조 뒤에 장부에 정상 형식의 줄을 덧붙이면 통과한다(git 이력 검토가 방어선). **첫 실제 실행 전에 빈 장부를 커밋해 두기를 권한다.** 커밋은 사용자 요청 시에만 한다.
  - 실제 Gemini의 `model_version` 형식이 3자리 숫자 접미사가 아니면 정상 응답도 재사용이 거부된다(안전한 쪽으로 실패). 첫 실제 호출에서 확인한다.

### [C] 실행 전 보완 3건 요청 (사용자 코드 검토, 2026-10-14)
- 기존 PASS 판정은 그대로 두고, 보완과 검증 결과는 따로 덧붙인다. 실제 Gemini 생성 호출 금지, 예시 2·3 확정 상태 변경 금지.
- [P1] 호출 중 KeyboardInterrupt가 나면 finally가 outcome보다 먼저 돌아 승인이 unused로 복원된다(재현됨).
  - 수정 방향: 시도 단계(prepared/sending/http_error_response/http_200_received/interpreted)를 저널에 남긴다. 미사용이 확인될 때만 unused로 되돌리고, 그 밖은 usage_check_required로 둔다. 200 이후 해석 예외가 나도 200이 났다는 사실은 보존한다.
- [P1] 같은 승인을 동시에 예약하는 경우와 장부 동시 기록에 프로세스 간 잠금이 없다.
  - 수정 방향: Windows에서 동작하는 파일 잠금(msvcrt/fcntl), 잠금 순서는 승인 → 장부로 고정한다. 장부에 먼저 기록한 뒤 파일을 원자적으로 바꿔, 중간에 실패하면 막힌 쪽(closed)으로 끝나게 한다. 실제 프로세스로 테스트한다.
- [P2] 같은 청크 재시도에는 최소 호출 간격이 적용되지 않는다(대기 [2.0] 재현).
  - 수정 방향: 실행 하나에 페이서 하나를 두고, 대기는 max(최소 간격 남은 시간, backoff, retry_after)로 한 번만 한다.
- 구현은 C 구현 에이전트가 진행 중이고, 이어서 verifier가 독립 검증한다.
- 구현 결과(구현자): 3건 모두 반영. `locks.py`(msvcrt/fcntl)를 새로 만들고, 시도 단계 저널 `attempts.jsonl`, `approval.decide`, 실행 잠금, `llm.Pacer`를 넣었다. 테스트 269개 통과, 실제 API 0회, 실제 장부 0줄. 잠금 폴더 `extraction/.locks/`는 기존 `/extraction/` 규칙으로 이미 무시되므로 `.gitignore`를 바꿀 필요가 없다.
- 독립 검증(`reports/extract_verify.md` "실행 전 보완 3건 검증"): **PARTIAL**.
  - 인터럽트(a~h, 실제 프로세스 kill 포함), 동시성(2·4 프로세스 동시 예약 각 5회 → 매번 1개만 성공, 장부 동시 기록 사슬 유효, 잠금 쥔 채 kill 뒤 복구, os.replace 실패 시 막힌 쪽으로 끝남), 호출 간격(재시도 7.5초, retry_after 20 → 20, 이중 대기 없음): 모두 PASS.
  - FAIL 1: 대기 중에 끊기면 partial_run의 미완료 목록이 비어 있다. 비용과는 무관하다.
  - FAIL 2: journal 없이 finalize를 부르거나 journal 파일이 없으면 AMBIGUOUS도 unused로 돌아간다. 지금 CLI 경로에서는 닿지 않지만, "미사용이 확인될 때만 unused" 원칙에 어긋난다.
  - 두 건과 관찰 2건(해석 실패한 200의 원본 본문 저장, 어긋남 오류 메시지가 원인을 오해하게 함)을 구현자에게 수정 요청했다.


### Codex C completion and first evaluation work (2026-10-14, ongoing)
- User confirmed example 2 unchanged and example 3 MaintenanceRule; confirmationStatus CONFIRMED.
- Direct local verification: 281 tests OK (455.186s), raw unchanged 1121 files PASS, leakage PASS, A+B SHACL PASS. Prompt tests 12 OK after confirmation.
- Real Gemini smoke and pilot completed: 4 unique chunks, 11 candidates, 8 merged into B, 3 new rules, no rejects. 503 exhausted pilot preserved results; retry reused prior successes.
- Full extraction real-20261014-full remains running (56 new chunks, 4 reused, maximum 66 attempts, minimum interval 30s). Do not launch a duplicate job.
- Evaluation-only code in eval/, encoder downloaded and offline tested, core matching tests 4 PASS. Reference schema inspected only; first quantitative results and human review remain pending.
- User explicitly requested current completed code be pushed now to 2nd-yujin, then work continue. Original restriction on commit/push is superseded for this upload. No keys or large output files to be committed.
- Final report is still a draft. Current snapshot is reports/progress_abc_evaluation_impl.md.
