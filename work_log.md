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
