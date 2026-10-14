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

## 2026-10-14 이번 주 목표와 결정

### 이번 주 목표 (일정 무시, 사용자 지시)
기존 KG 변환(③) + Rule·Document 노드 승격 + LLM 추출(④) → `ground_truth.csv` 86건 대조(⑤)로 첫 정량 결과를 낸다.

### 결정 (사용자 확정)
| 항목 | 결정 | 이유 |
|---|---|---|
| LLM 호출 | Gemini API, OpenAI API를 사용한다. 모델과 키는 코드가 아니라 설정·환경변수로 바꾸게 하고, 실패 시 fallback(다른 모델·공급자)을 구현한다 | API 요청 실패나 토큰 문제에 대비 |
| Task 클래스 | 보류 유지. 조치는 `responseText` | F1_content가 규칙 4분류로 채점되어 가장 단순. ④ 시작 전 재검토 항목은 이번 결정으로 이번 주에는 보류로 확정(CLAUDE.md ②의 Task 요구는 여전히 미충족) |
| 적재 범위 | CSV/TTL까지만. Neo4j 적재는 다음 주 | 이번 주 목표에 불필요 |
| 프롬프트 튜닝 | 첫 실행 점수를 기준선으로 고정, 수정은 최대 2회, 정답 내용을 보지 않고 오류 유형만 근거로 하며 고친 이유를 기록 | 정답에 맞춘 튜닝 방지(누수 방지 규칙) |

### 주의
- API 키는 환경변수로만 사용한다(`.env`는 `.gitignore`에 있음). 코드·로그·보고서에 키를 남기지 않는다.
- LLM 호출은 요청·응답·모델명·시각을 파일로 저장해 재현할 수 있게 한다.
- `ground_truth.csv`는 평가 스크립트만 읽는다. 프롬프트·예시·청킹·KG 구축에 쓰지 않는다.

### 추가 결정 (2026-10-14, LLM 공급자)
- 1순위 Gemini, 2순위 OpenAI. 환경변수 이름은 `GEMINI_API_KEY`, `OPENAI_API_KEY`.
- 모델명은 미정(보류). 설정 파일에서 바꾸게 하고 코드에 기본값을 박지 않는다. 모델명이 정해지기 전에는 ④ 실행 불가, 구현과 mock 테스트까지만 한다.
- 첫 점수 기준선은 같은 공급자·모델로 전체를 돌린 결과로 고정한다. fallback이 섞이면 모델별로 분리해 보고한다.

### 체크리스트 보강 (2026-10-14, 사용자 확정)
- `harness/checklist.md`의 공통 절(키 검색, 보고 분량), ③(제외 대상·문구 보존·엣지 출처·③ 한정 재현성), ④(공급자 설정·fallback mock·호출 기록·캐시·스모크 테스트·Task 없음·S7/S8·사람 검토·모델별 구분), ⑤(모델 기록·eval 폴더·보조 지표·튜닝 2회·보고 명시)를 추가했다. 백업은 `reports/checklist.md.before_2026-10-14_③④⑤보강전.bak`(로컬 전용).
- 토큰 절약 원칙: 검증은 LLM을 다시 호출하지 않고 호출 기록을 근거로 한다. 키 검색과 정답 문구 겹침은 스크립트가 건수만 출력한다.
- 미반영(별도 승인 필요): `.claude/agents/verifier.md`에 정답 파일 읽기 범위 명시, 키 검색·겹침 비교 스크립트 추가, `CLAUDE.md` 7장에 평가 코드 위치(`src/imaks_kg/eval/`) 기재.

### 추가 결정 (2026-10-14, 사용자 확정)
- ③ 엣지(`hasSensor`, `feedsInto`, `appliesToSensor`)의 출처는 CSV(`sourceEdgeRow`)에 두는 것으로 충분하다. TTL로 올리는 것은 필요해질 때 같은 값을 옮긴다. 보고서에 "선 출처는 CSV에 있다"고 명시한다(CLAUDE.md 4장의 "모든 트리플에 출처"와의 차이를 알고 선택).
- ④ 체크리스트의 "fallback 결과 모델별 구분" 항목은 빼지 않고 유지한다(첫 점수 기준선을 같은 모델로 고정하기 위해 처음부터 필요).
- 평가 코드 위치 `src/imaks_kg/eval/`를 `CLAUDE.md` 7장에 한 줄 추가하는 안은 문구 확인 후 반영한다(승인 대기).
- `CLAUDE.md` 7장에 평가 코드 위치 한 줄 반영 완료(백업: `reports/CLAUDE.md.before_2026-10-14_평가코드위치.bak`).

### 점검 스크립트 2종 (2026-10-14)
- `check_secrets.py`, `check_gt_overlap.py`와 테스트를 추가했다. 독립 검증: 핵심 기준 모두 PASS, 검증자가 지적한 "테스트 파일 줄이 키 대입 패턴에 걸려 커밋 후 자기 오탐" 문제는 테스트의 소스 줄을 나눠 쓰는 방식으로 고쳤다. 같은 이유로 `reports/check_scripts_verify.md`의 인용 문구 한 곳을 서술형으로 바꿨다(판정·근거는 그대로).
- 판정 중 C4(`harness/checklist.md` 수정 상태)는 사용자가 승인한 체크리스트 보강이라 의도된 변경이다.
- 측정 한계: 정답 규칙 86개 중 41개는 6단어 기준 고유 n-gram이 없어 복사 여부를 잴 수 없다. 단어가 그대로 같을 때만 잡는다.
- 미반영(승인 대기): SKILL.md 등록, 체크리스트 2곳 문구, verifier.md 한 줄.
- 반영 완료(사용자 승인): `SKILL.md`(스크립트 2개 등록, 설명 2줄, 못 보는 것 1줄), `harness/checklist.md`(공통 12행, ④ 54행), `.claude/agents/verifier.md`(정답 파일 읽기 범위와 키 검색 방식 2줄). 백업: `reports/*.before_2026-10-14_점검스크립트반영전.bak`(로컬 전용). 반영 후 `check_secrets` PASS, `check_leakage` PASS.

### ③ 개선 4건 (2026-10-14, 세 브랜치 비교 후 사용자 지시로 적용)
- 계기: 성호·2nd-yewon·kg-val-sumin의 ③ 변환을 읽고 내 변환에 가져올 부분을 정했다(요약은 로컬 `reports/branch_comparison_2026-10-14.md`).
- 개선: (1) 트리플 단위 출처 장부 `triple_sources.jsonl`(모든 트리플의 원본 파일·줄·해시, 이중 근거 보존, 완결성 검사), (2) MaintenanceRule 8개에 SOP-003 문서 Provenance 추가(쪽·표·행·열·원문·해시), `extractionMethod="seedCsv"`, (3) ⑦ 이후 전용 타입·관계(AnomalyEvent 5유형, Person, CausalLink, triggers, correlatesWith, causallyAffects)가 ③ 그래프에 없음을 검사, (4) PDF 해시를 파일에서 다시 계산해 manifest와 대조.
- **이 결정이 대체하는 것:** 같은 날 앞서 정한 "③ 엣지 출처는 CSV(`sourceEdgeRow`)에 두는 것으로 충분하다"를 장부 도입으로 대체한다. 엣지 출처는 장부와 CSV 양쪽에 남는다. 장부는 TTL과 별도 파일이며 해시로 묶인다(`CLAUDE.md` 4장의 "트리플과 함께 저장"을 이렇게 해석).
- **CLAUDE.md와의 충돌 점검:** 없음. 4장 "모든 트리플에 출처", "문서 안 위치는 Provenance 한 곳", 3장 MaintenanceRule 정의, ⑦ 이후 경로 분리와 모두 맞는다.
- **문서 정리 대기(승인 필요):** `schema_tables.md`에 `rowIndex`·`colIndex`는 1부터 센다는 규약과 `extractionMethod`의 `seedCsv` 값 추가. ④ LLM 출력도 같은 1부터 규약을 쓴다.
- 보류: seed 정비 규칙과 LLM 정비 규칙의 병합 여부(⑤ 대조에서 정답의 MaintenanceRule 개수와 비교한 뒤 결정, 지금은 별도 노드), Neo4j용 Cypher 생성(다음 주 적재와 함께).

### 번호 규약 통일과 문서 반영 (2026-10-14, 사용자 승인)
- 표 위치(`rowIndex`, `colIndex`)는 **1부터 센다**(헤더 행 = 1, 첫 열 = 1). 온톨로지가 positiveInteger라 0을 쓸 수 없다. ④ LLM 출력도 같은 규약.
- 매핑표 `maint_seed_vs_sop003.csv`의 `sop003RowIndex`(원래 0부터)를 1부터로 바꿔 문서 Provenance와 통일(MAINT-01 = 2, MAINT-08 = 9). 코드에 어긋남 검사와 테스트 추가. 독립 검증 PASS(`reports/kg_convert_v3_verify.md`).
- Document `title`은 넣지 않았다: manifest에 제목 열이 없고 청크 첫 줄이 서식이라 결정적으로 얻을 수 없다(추정 금지).
- 깨진 글자 점검: 전처리 산출물과 `kg_build`에 U+FFFD가 0건. SOP-003의 비ASCII 글자는 `°` `↑` `→` `↓` 뿐이며, `��`는 윈도우 콘솔 표시 문제였다. 터미널 확인 시 `PYTHONIOENCODING=utf-8`을 쓴다.
- 반영한 문서: `ontology_v1/schema_tables.md`(4-5장 규약과 MaintenanceRule 이중 Provenance, 7장 extractionMethod와 출처 장부), `ontology_v1/ontology.ttl`(rowIndex·colIndex 주석), `harness/checklist.md` ③(장부 완결성, PDF 해시 재계산). 백업: `reports/*.before_2026-10-14_번호규약반영전.bak`(로컬 전용).

### ④ 설계 수정본 확정 (2026-10-14, 사용자 확정)
- 세 브랜치(성호, 2nd-yewon, kg-val-sumin) 비교에서 가져온 변경 7개를 반영한 ④ 설계를 확정했다: (1) 요청 단위 문서, (2) 인용마다 `supports` 필드와 1부터 센 표 위치, (3) KG의 Station·Sensor 목록 안에서만 ID 선택, (4) 가벼운 coverage, (5) 요청 메타 플래그·응답 해시 고정·평가 전 정책 고정, (6) SOP-002 결정적 변환은 비교 기준선으로 별도 유지, (7) 평가 정의서 선행.
- 확정 6건: ①표도 LLM으로 추출하고 결정적 변환은 비교 기준선 ②데이터시트 3개도 추출하되 채점 범위에서 분리 ③Example은 가상 문장(누수 방지 생성 절차 필수, 아래) ④사람 검토는 표시 항목 + 승인 규칙의 약 20% 표본 ⑤평가 정의서를 팀에 먼저 제안 ⑥스모크 테스트 문구를 "작은 문서 1개 또는 청크 3~5개 분량"으로 수정(체크리스트 수정은 전후 확인 후 반영 대기).
- Example 누수 방지 절차(사용자 요구): 가상 이름·수치·문장 작성 규칙, 정답·SOP 문구와 5단어 겹침 0건 확인, 데이터셋의 ID·수치 미사용, 해시 고정, 수정 시 재검증. 세부는 설계 문서에 명시.
- 체크리스트 ④ 반영 완료(사용자 승인): 스모크 테스트 문구를 "작은 문서 1개 또는 청크 3~5개 분량"으로 수정, Example 누수 방지 항목 추가. 백업: `reports/checklist.md.before_2026-10-14_스모크Example반영전.bak`(로컬 전용).
- 문서 작성(2026-10-14): `docs/extraction_design.md`(④ 설계 v1), `docs/eval_definition_F1_content.md`(평가 정의서 제안 v1). 구현 전, 팀 합의 대기.

### 모델 예선 계획 검토와 확정 (2026-10-14, 조사 세션의 예선 프롬프트를 검토)
- 큰 방향은 채택: 프롬프트·스키마 고정 후 모델만 교체, 예선 점수로 프롬프트 수정 금지, 예선 문서와 최종 보고 문서 분리, 3회 실행, 1차 관문(JSON 파싱 95%, 인용 일치 95%) 후 F1_content, 동률이면 일관성과 비용 순.
- 충돌해서 조정한 것: (1) Example은 "SOP 원문을 보고 직접 작성"이 아니라 확정안대로 **가상 문장**(설계 §8). (2) 프롬프트는 청크 단위가 아니라 **설계 v1(문서 단위, supports, 허용 ID, coverage)**. (3) 필드명은 설계 §4. (4) 예선 문서는 정답에 노출된 문서로 표시하고 최종 보고 점수는 예선에 쓰지 않은 문서에서만 낸다.
- 사용자 확정: **예선 문서 SOP-003 + SOP-004, 최종 보고 SOP-001 + SOP-002**(정답 건수는 팀원 보고 기준 11+19 / 29+27). 예선 후보는 **Gemini 3.8 Flash, Gemini 3.1 Flash-Lite, gpt-6.1-sol**(오픈 모델 HF는 시간이 남을 때). 모델 이름·가격은 조사 세션의 결과이며 이 환경에서 미확인 -> 키 설정 후 각 공급자의 **모델 목록 조회로 실제 호출 가능한 이름만** 남긴다. 구조화 출력·temperature 0 지원도 실제 호출로 확인해 기록.
- 키는 `.env`(git 제외)에 지훈이 직접 넣는다. 채팅·코드·로그에 쓰지 않는다. 무료 구간 입력은 제품 개선에 쓰일 수 있으므로 합성 SOP 외 자료와 `ground_truth.csv`는 절대 보내지 않는다.
- 선정 기록은 표로 이 파일에 남긴다(F1_content, 파싱 성공률, 인용 일치율, 3회 일관성, 토큰, 비용, 지연, 모델 이름·버전·날짜·온도·프롬프트 버전). 예선 문서 점수는 "정답 노출 문서"로 표기.

### API 연결 확인 결과 (2026-10-14, 실제 호출, 내용은 "OK라고 답하라" 한 문장뿐)
| 모델 | 목록에 있음 | 일반 호출 | JSON 모드 | 온도 0 | 비고 |
|---|---|---|---|---|---|
| gemini-3.8-flash | 있음 | 1회 성공(3.4초), 이후 2회 503(수요 과다) | 3회 시도 모두 실패(타임아웃 2, 503 1) | 일반 호출에서는 허용 | **현재 불안정**. 재시도 필요 |
| gemini-3.1-flash-lite | 있음 | 성공(9.8초, 첫 호출 지연) | 성공(1.3초, JSON 파싱 가능) | 허용 | 안정적 |
| gpt-6.1-sol | 있음 | 성공(1.6초) **온도 지정 없이만** | 성공(3.2초, JSON 파싱 가능) 온도 지정 없이 | **온도 0 거부(HTTP 400, 기본값 1만 허용)** | 설계의 "온도 0"은 이 모델에서 불가 -> 온도 미지정으로 기록 |
- 세 후보 이름이 모두 실제 모델 목록에 있음을 확인했다(조사 세션의 이름은 맞았다). 가격은 여전히 미확인.
- `connectivity.py`에 `--no-temperature` 옵션을 추가했다(구현자 코드의 작은 수정, 테스트 13개 통과).
- 알게 된 것: `--contains`를 여러 번 주면 마지막 값만 적용된다(미수정). 호출 로그는 `llm_logs/`(git 제외)에 26건.
- 시사점: 본선에서 **가용성**(503, 타임아웃)이 실제 변수다. fallback과 재시도 설계(§6)가 필요하고, 모델별 실패율도 선정 기록에 넣는다.

### 공식 문서 조사: gemini-3.8-flash와 gpt-6.1-sol (2026-10-14, 공식 문서를 직접 열어 확인)
출처: ai.google.dev/gemini-api/docs/{models, models/gemini-3.8-flash, pricing, rate-limits, troubleshooting, thinking}(2026-10-14 기준 최종 갱신 표시), openai.com/ko-KR/api, developers.openai.com/api/docs/{models/gpt-6.1-sol, guides/latest-model}.
| 항목 | gemini-3.8-flash | gpt-6.1-sol |
|---|---|---|
| 설명 | Google의 가장 지능적인 Flash 모델, 안정(stable) 버전 | Astra에 근접한 성능을 낮은 비용으로 |
| 컨텍스트 / 최대 출력 | 입력 1,048,576 / 출력 65,536 | 1,050,000 / 128,000 |
| 가격(100만 토큰, 표준) | 입력 $0.75 / 출력 $3.75 (2026-12-31까지), 2027-01-01부터 $1.50 / $7.50. 출력에 사고 토큰 포함 | 입력 $2 / 출력 $10 (입력 27.2만 토큰 초과 시 입력 2배, 출력 1.5배). 캐시 입력 $0.10 |
| 절감 옵션 | Batch·Flex 50% 절감, Priority는 약 1.8배(표준 대비 $1.35 / $6.75) | Batch·Flex 50% 절감, Fast 2배, Ultrafast 6배 |
| 구조화 출력 | 지원 | 지원 |
| 사고(추론) | 항상 켜짐(low/medium/high, minimal 불가, 기본 medium) | 항상 켜짐(low/medium/high/xhigh/max, none·minimal 불가, 기본 medium) |
| temperature 등 | **3.6 이상 모델은 temperature·top_p·top_k의 맞춤값을 무시**하고 경고 헤더를 반환(향후 400 오류) -> 보내지 않는다 | **추론이 켜져 있으면 temperature·top_p 제거**(실제 호출에서 400 확인) |
| 요율 제한 | 프로젝트별 RPM/TPM/RPD, 값은 AI Studio에서 확인. 지정 한도는 보장되지 않고 실제 용량은 다를 수 있음 | Free 미지원, Build 5,000 RPM / 100만 TPM, Launch 1만 / 400만, Grow 1.5만 / 4천만 |
| 무료 구간 | 있음(입력이 제품 개선에 사용될 수 있음), 유료는 아님 | 없음 |
| 오류 처리 지침 | 429·408·5xx만 지수 백오프+지터로 재시도, 400·402·403은 재시도하지 않음. SDK 기본: 초기 약 1초, 최대 60초, 최대 4회 | (이 환경에서 해당 문서 미확인) |
| 사고 토큰과 출력 한도 | `max_output_tokens`는 사고 토큰 포함. 한도에 닿으면 잘리거나 빈 출력(사고 토큰은 계속 청구). 지연·비용은 한도를 줄이지 말고 사고 수준을 낮춰 줄이라고 안내 | 추론 토큰도 출력으로 계산(문서의 "Reasoning token support") |
- 확인하지 못한 것: 지훈 계정의 실제 요율 제한과 사용 등급(AI Studio, OpenAI 대시보드에서 확인 필요), Gemini 키가 무료/유료 어느 쪽인지, 구조화 출력의 스키마 제한, REST 필드 이름(`thinkingLevel` 등)과 OpenAI `reasoning_effort`의 정확한 사용법, Flex의 지연 특성.
- 설계 영향: 우리 설계의 "온도 0 고정"은 두 모델 모두에서 불가능하다 -> 샘플링 매개변수를 보내지 않고 재현성은 응답 고정·캐시로 보장, 3회 일관성은 그대로 측정. 사고 수준(Gemini `low`, GPT `low`)을 낮춰 지연·비용·잘림을 줄이는 것을 예선 기본값으로 비교. 타임아웃은 넉넉히(사고 때문에 느림). 503은 용량 문제라 지수 백오프+지터로 재시도.

### 공식 문서 조사 후 설계 반영 (2026-10-14, 사용자 승인)
- `docs/extraction_design.md`: 온도·top_p·top_k를 보내지 않음(재현성은 응답 고정·캐시, 일관성은 3회 실행으로 측정), 생각 수준 기본 `low`(예선에서 `medium`과 비교), 타임아웃 120초 이상, 429·408·5xx만 지수 백오프+지터 최대 4회로 재시도하고 400·402·403은 재시도 금지. §0 결정 표와 §6에 반영.
- `connectivity.py`의 `ping` 기본값을 "온도 없음"으로 변경(`--temperature X`로 지정 가능), 테스트 14개 통과. 이전 연결 확인에서 온도 0이 거부된 것은 GPT-6.1 Sol의 추론 규칙 때문이었다.
- **예선 기록 항목 추가:** 생각 수준, 출력이 잘린 비율(incomplete), 503·타임아웃 횟수, 재시도 횟수. 실패율과 지연도 점수와 함께 표에 남긴다.

### 평가기 라이브러리 설치와 동작 확인 (2026-10-14, 사용자 승인)
- `.venv`에 설치: torch 2.14.1+cpu(CPU 전용 인덱스 `https://download.pytorch.org/whl/cpu`), sentence-transformers 6.1.0, transformers 5.19.0, scipy 1.18.1(numpy 2.5.3은 기존). 파이썬 3.12.9.
- 모델 `sentence-transformers/all-MiniLM-L6-v2`를 내려받았고(캐시: 사용자 홈의 `.cache/huggingface`), Hub 조회 revision은 `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`(2nd-yewon의 SBERT 보고서 revision과 같음). 임베딩 384차원, 최대 입력 256토큰.
- 동작 확인: 말바꿈 문장 쌍 코사인 0.827, 무관한 문장 쌍 0.207(가상 문장으로 한 확인이며 점수 의미 없음). 임베딩 계산은 로컬이라 API 호출 없음.
- 디스크 여유가 설치로 7.0GB에서 5.7GB로 줄었다(전체 226GB 중 98% 사용).
- `requirements.txt`는 아직 만들지 않음(승인 대기). Docker는 Neo4j 적재 때 논의.
- `requirements.txt` 생성(사용자 승인): 버전 고정, CPU 전용 torch 인덱스 지정, ASCII 전용(Windows pip이 한글 주석을 cp949로 읽어 오류가 나는 것을 확인), `pip install -r --dry-run`로 현재 환경과 일치 확인. Docker는 Neo4j 적재 때 논의.

### 보류 항목 재검토 메모 (2026-10-14, 첫 정량 결과가 나온 뒤 함께 정할 것)
| 항목 | 현재 결정 | 아직 정하지 않은 것 | 재검토 시점 |
|---|---|---|---|
| Task 클래스 | **이번 주 보류 유지**(조치는 `responseText`). 이유: F1_content가 규칙 4분류로 채점되어 가장 단순 | 첫 정량 결과 뒤에도 보류할지, 도입한다면 범위(조치만 Task로 분리? 온톨로지·SHACL·추출 프롬프트 변경 범위) | **첫 정량 결과 직후**(결과 해석과 함께). `CLAUDE.md` ② 행의 "④ 시작 전 재검토" 문구는 이때 "재검토 시점"을 확정해 고친다(수정 시 전후 확인·백업) |
| Neo4j 적재 | **CSV/TTL까지만, 적재는 다음 주** | Docker 사용 여부(디스크 여유 약 5.7GB 주의), 계정·접속 설정, 적재 스크립트 방식(`LOAD CSV` vs 드라이버), Cypher 생성 시점, 감사 질의, `causallyAffects` 적재 검증과의 연결 | 첫 정량 결과 이후, ⑥ 설계 전 |
| 정비 규칙 병합 | seed 8개와 LLM 정비 규칙은 별도 노드 | 병합 여부 | ⑤ 대조에서 정답의 MaintenanceRule 개수와 비교한 뒤 |
| System 노드 1개 | 적재 안 함 | 처리 방식 | ⑥ 설계 때 |
| Docker | 필수 아님 | 앱 전체 컨테이너화 여부 | Neo4j 적재 방식을 정할 때 |
- 이 항목들은 이번 주 목표(변환·승격·추출·첫 정량 결과)의 구현에는 영향을 주지 않는다.

### 평가기 구현과 누수 가드 충돌 (2026-10-14, 사용자 결정)
- 평가기 구현 보고: `check_leakage.py`가 평가 코드의 `severity` 단어 9건으로 FAIL. 구현자가 단어를 쪼개 쓰는 우회를 만들지 않고 결정을 요청했다.
- **결정: 등급 일치 지표를 제거하고 단어를 코드에서 뺀다.** 점검 도구는 고치지 않는다(예외 1개 원칙 유지). 추출 출력 키는 `severity` 대신 온톨로지 속성과 같은 `ruleSeverity`로 통일(설계서 §4 반영), 평가 정의서 §5도 수정.
- `describe-gold`로 실제 정답 구조를 확인(규칙 문장은 보지 않음): 14열, 86행, 문서 SOP-001 29 / SOP-002 27 / SOP-003 11 / SOP-004 19 / 데이터시트 0, 클래스 Operational 28 / Threshold 27 / Access 20 / Maintenance 11. 팀원(2nd-yewon) 보고와 일치. "정답에 데이터시트 행이 없다"가 직접 확인됨.
- 모델 revision은 가중치에서 직접 읽지 못했고 로컬 캐시 폴더 이름(`1110a243…`)으로 간접 확인.

### 평가기 검증 PASS와 매칭 정의 확정 (2026-10-14)
- 평가기 독립 검증 PASS(`reports/eval_verify.md`): 매칭 규칙·분모·보조 지표·정답 노출 통제(lock이 정답 읽기 전)·재현성(metrics.json 바이트 동일)·정답 읽기 경로 `eval/gold.py` 단일. 테스트 115개.
- 판정 외 관찰: 2순위 "유사도 합"이 무효한 쌍까지 포함 -> **사용자 결정: 유효한 쌍의 합만**. 1순위(유효 매칭 수 최대화)는 그대로. 반례(P1=[0.99,0.61], P2=[0.61,0.59])는 유효 2개 조합을 고르고, 3x3 예시([0.70,0.75,0.05],[0.05,0.62,0.10],[0.63,0.05,0.59])는 {P1-G2, P3-G1}(합 1.38)을 고른다. 정의서 §3-4 반영, 구현자에게 비용식 수정 요청(재검증 필요).
- 남은 관찰: 문장 구성 민감도(`Condition: … Action: …`) 미구현, `--meta`를 주지 않으면 lock의 프롬프트·모델 정보가 비어 있음(추출 쪽에서 반드시 전달).
- 추출 구현 방식 확정: 2단계 순차(1단계 호출 계층 -> 2단계 요청 빌더·검증기·TTL 변환·사람 검토 기록). 1단계 시작.
- 설계 보정(2026-10-14): 요청 메타 플래그 `ground_truth_supplied`가 누수 가드(평가 폴더 밖의 `ground_truth` 단어 경고)에 걸려 **`answer_key_supplied`**로 이름을 바꿨다(설계서 §6, 추출 코드). 체크리스트 ⑤의 "경고 0건" 요구와 맞춘 것이며 뜻은 같다.
- 평가기 v3(유효 쌍 합) 구현 완료: 테스트 120개, 반례 2개와 완전 탐색 60개 일치 보고. 독립 재검증 대기.

### 설정 파일 형식 확정: TOML (2026-10-14, 사용자 확정)
- 호출 계층 설정은 **TOML**(`config/extract.example.toml`)로 확정. 이유: 파이썬 3.11+ 표준 라이브러리 `tomllib`로 읽어 PyYAML 설치가 필요 없고, 파일을 UTF-8로 고정해 읽어 한글 주석이 안전하며(requirements.txt에서 겪은 cp949 문제 회피), 값의 종류가 명확하다.
- 영향: 읽는 코드(`config.py`) 한 곳뿐. ⑥ 파라미터와 ⑧~⑨ Agent 설정도 같은 형식을 쓸 수 있다. `docker-compose.yml`(YAML)은 별개 파일이라 충돌 없음. 되돌리기 쉬움(설정이 작고 로더가 한 곳).
- 한계: `tomllib`은 읽기 전용(우리는 사람이 고치는 설정이라 무관), 파이썬 3.11+ 필요 -> `requirements.txt` 머리말에 명시, 설계서 §10 경로를 `.toml`로 수정. 팀원의 설정 형식과 파이썬 버전(sumin 미확인)은 확인하지 못함.

### 추출 1단계 검증 PASS와 정책 확정 (2026-10-14, 사용자 확정)
- 추출 1단계(호출 계층) 독립 검증 PASS(`reports/extract_a_verify.md`), 평가기 v3 재검증 PASS(`reports/eval_v3_verify.md`). 조용한 상태에서 전체 테스트 173개를 3회 연속 실행해 모두 통과(검증자의 첫 실행 오류는 동시 실행 탓으로 추정, 미확정).
- 확정 4건: (1) 점수 실행은 모델 하나만 둔 체인(`run_mode="scoring"`)만 허용하고 fallback은 운영 실행에만 사용, (2) 재시도 4회(총 5회, 대기 1·2·4·8초), (3) 400은 같은 공급자의 다음 모델로 넘기고 전부 400이면 실패 기록·요청 형식 의심, (4) 크레딧·인증 오류는 해당 공급자만 중단하고 다음 공급자 시도(기본값). 설계서 §6에 반영. `config/extract.toml`은 `.gitignore` 대상으로 추가.
- 기록만 하는 관찰: 캐시의 응답 텍스트는 마스킹되지 않음(우리는 모델에 키를 보내지 않으므로 위험 낮음), `assert_no_sampling`이 JSON 스키마 속성 이름에 `temperature`·`top_k`가 있으면 요청을 막음.

### 추출 2단계 검증 PASS와 Example 등록 (2026-10-14)
- 추출 2단계 독립 검증 PASS(`reports/extract_b_verify.md`): 요청 빌더(7개 문서, 표 24개의 행·열 1부터), 검증기(산문 인용 83개·표 셀 30개의 위치·해시 독립 재계산 일치), 산출물(재검증 바이트 동일), 사람 검토, TTL(SHACL 적합, 출처 장부), Example 게이트. 전체 테스트 256개 215초(구현자의 6,707초는 환경 탓으로 추정, 파일별 합계 247초).
- 사용자 확정: (1) SOP-003의 MAINT-01~08 ID 충돌은 **TTL에서 제외하고 기록만**(중단·병합하지 않음), (2) 누수 점검은 `kg_build/extraction/` 본문 값을 문서 폴더처럼 제외(점검 도구 수정은 전후 확인 후 반영 — 대기).
- Example 정식 등록: 요청 빌더의 실제 표시 형식에 맞춰 영어 Example(`example_v1.txt`)을 쓰고 `example_check` 검증 4종(정답 고유 문구, 원문 5단어, 데이터셋 어휘, 해시)을 모두 통과해 등록. SHA-256 `edbf73a72c071cccf019094cfb96069ae8075aec2e6263b519bae8b5d16d34b8`.
- 설계서 §4 coverage 키 `coverage_status`, §5 재시도 문구 정리, §13 구현 반영 사항 추가.
- 스모크 테스트는 사용자 요청에 따라 시작하지 않음(정할 것이 있음).

### 누수 점검 예외 반영 (2026-10-14, 사용자 승인)
- `check_leakage.py`: `TEXT_EXEMPT_PREFIXES`에 `kg_build/extraction/` 추가, 예외 적용 대상을 JSON·JSONL에서 **TTL까지** 확장(`text_exempt = (is_json or .ttl) and 접두 일치`). 두 폴더의 JSON 본문 값은 검사하지 않고 키는 계속 검사, `kg_build/extraction/`의 TTL은 본문 전체를 검사하지 않음(키 구조가 없어서). 다른 폴더의 TTL은 그대로 검사. 이유: SOP 원문 인용문(예: SOP-004의 "Severity")이 들어가는 추출 결과는 ⑥ 입력이 아니고 정답 컬럼도 아님.
- 새 시험 2개 추가(`tests/test_check_leakage.py`, 16개 통과). 기본 폴더 `check_leakage` PASS. 백업: `reports/*.before_2026-10-14_extraction예외반영전.bak`(로컬 전용).
- `harness/checklist.md`: 예외 문구를 "TEXT_EXEMPT_PREFIXES 1개뿐이고 폴더는 preprocessed/documents/ 와 kg_build/extraction/ 둘뿐", ④ Rule 클래스를 4분류(MaintenanceRule 포함)로 수정.
- MAINT ID 충돌 처리(제외+기록)는 구현자가 `to_rdf.py`를 수정 중.

### 스모크·예선 문서 확정과 공급자 API 형식 조사 (2026-10-14, 사용자 확정)
- 사용자 확정: **스모크 테스트는 DS-ELEC-3300**(가장 작은 데이터시트, 정답 없음, 채점 안 됨 — 결과를 보고 고쳐도 정답 편향 여지가 없음), **모델 예선은 SOP-003 + SOP-004 유지**(정답 30건 노출, 최종은 SOP-001 + SOP-002). 오늘은 예선까지만, 최종 실행은 이후. 스모크는 공급자마다 최소 1회(필드 이름 미확인 사항이 처음 부딪히는 곳). 스모크 모델: gemini-3.1-flash-lite와 gpt-6.1-sol 우선, 성공 후 gemini-3.8-flash 1회.
- 스모크와 예선의 차이: 스모크는 파이프라인이 끝까지 도는지(키·모델 이름·요청 형식·파싱·검증·기록) 확인하는 배관 점검이고 점수를 내지 않으며, 예선은 후보 모델을 같은 조건으로 점수 비교해 하나를 선정한다(문서 2 x 모델 3 x 3회 = 약 18회).
- MAINT ID 충돌 처리 변경 완료(구현자 보고, 독립 검증은 아직): 충돌 규칙만 TTL에서 제외하고 `identifier_conflicts.json`에 기록, 중단·병합 안 함. 전체 테스트 261개 통과 보고.
- **공식 문서 확인(2026-10-14)**: Gemini는 Interactions API(`POST /v1beta/interactions`, `response_format {type:"text", mime_type:"application/json", schema}`, `generation_config.thinking_level`, `store`)가 신규 프로젝트 권장 표준이고 generateContent는 레거시이나 계속 지원. **Interactions는 기본으로 요청·응답을 서버에 저장(`store=false`로 끔)** -> 우리는 `store=false`로 보낸다. 응답은 `status`(completed/failed/incomplete…), `steps[]`(`model_output`의 `content[].text`), `usage`(`total_*_tokens`, 사고 토큰 포함). OpenAI(gpt-6.1-sol)는 Chat Completions(도구 없이)에서 `reasoning_effort`, `response_format` json_schema strict(모든 필드 required, additionalProperties false), 거부는 `message.refusal`, 잘림은 `finish_reason == "length"`.
- 미확인(스모크에서 확인): 두 공급자가 우리 스키마(enum 안 null 등)를 그대로 받는지, Gemini 최대 출력 토큰 필드 이름(`generation_config.max_output_tokens`로 추정).
- 공급자 어댑터를 위 형식으로 수정하는 작업을 구현자에게 맡김(보고서 `reports/provider_update_impl.md` 예정). 실제 설정 `config/extract.toml`(git 제외)은 이후 사용자가 모델 id를 넣어 만든다.

### 공급자 어댑터 수정 검증 PASS와 모델별 설정 생성 (2026-10-14)
- 공급자 어댑터 수정과 MAINT ID 충돌 처리 변경 독립 검증 PASS(`reports/provider_update_verify.md`): 가짜 transport로 요청 본문을 캡처해 Gemini Interactions 기본·레거시 선택, 키는 헤더에만, `store:false` 항상, 샘플링 매개변수 없음, 응답 파싱·오류 분류, OpenAI 본문, 설정 검증을 확인. OpenAI strict 린트 4건(`minItems` 1곳, `minimum` 3곳)을 검증자가 독립적으로 같은 목록으로 확인했고 로컬 검증기는 원본 스키마로 같은 제약을 계속 검사(`table_row=0`, 빈 evidence, 음수 규칙 번호가 걸림). MAINT-01·05를 가진 가짜 응답으로 충돌 규칙 2개만 TTL에서 빠지고 중단 없음, 고아 Provenance 없음, 출처 장부와 트리플 일치, 예측 파일 해시 불변. 전체 테스트 275개 통과.
- 설계서 §6의 "필드 이름 미확인" 문구를 공급자 API 형식(Interactions, `store:false`, 스키마 변환 정책 = 공급자용 스키마는 원본보다 약함, 스모크에서 확인할 항목 목록)으로 갱신.
- **모델별 로컬 설정 3개 생성**(git 제외, 키 값 없음, `run_mode = "scoring"`, 생각 수준 low, 타임아웃 120초, Example `example_v1.txt`): `config/extract.gemini-3-1-flash-lite.toml`, `config/extract.gemini-3-8-flash.toml`, `config/extract.gpt-6-1-sol.toml`. 점수 실행은 체인에 모델이 하나여야 하는 규칙 때문에 모델마다 설정 파일을 분리. `.gitignore`에 `/config/extract.*.toml`(예시 파일은 예외) 추가. 설정 로더로 3개 모두 로드 확인(네트워크 호출 없음). `check_secrets` PASS.
- 다음: 스모크(`DS-ELEC-3300`) — 실제 API를 처음 호출하므로 실행 직전에 사용자에게 알림. 스모크에서 가장 먼저 볼 항목: Gemini 사고 단계 type 이름(`model_output` 오분류 위험).

### 스모크 테스트 결과 (2026-10-14, 실제 API 첫 호출, DS-ELEC-3300 = 채점되지 않는 데이터시트, 정답 파일은 보내지 않음)
| 모델 | 결과 | 시도 | 지연 | 토큰(입력/출력/사고) | 규칙 | 플래그 |
|---|---|---|---|---|---|---|
| gemini-3.1-flash-lite | 성공 | 1 | 14.7초 | 4,008 / 1,580 / **3,885** | 8 | evidence_not_found 2, duplicate_identifier 3 |
| gpt-6.1-sol | 성공 | 1 | 21.6초 | 3,948 / 1,457 / 79 | 8 | 없음 |
| gemini-3.8-flash | 성공 | **5** (429 1회, 503 3회 후 성공) | 46.3초 | 4,008 / 750 / 0 (캐시 입력 2,299) | 4 | 없음 |
- 확인된 것: Gemini Interactions 요청·응답 파싱(`model_output` 단계 text 이음)이 정상 동작(빈 출력 오분류 없음), `store:false`·`generation_config.thinking_level`·`max_output_tokens`·`response_format` 스키마가 오류 없이 수용됨, OpenAI strict json_schema(키워드 4곳 제거본)가 수용됨(제거가 필요했는지는 미확인), `gemini-3.8-flash`의 503/429를 재시도 로직(지수 백오프)이 복구, 호출 기록에 `retry_reasons`·토큰·지연 기록, 호출 기록·산출물·설정에 키 없음(`check_secrets` PASS), 비용은 세 호출 합쳐 몇 센트.
- 아직 확인 못한 것: `incomplete` 응답 형태(발생하지 않음), `max_output_tokens`가 실제로 적용되는지, Interactions의 system 문구 전용 필드.
- 관찰 1 **인용 불일치는 줄바꿈 때문**: gemini-3.1-flash-lite의 evidence_not_found 2건은 인용이 실제 문장과 같은데 청크 원문에는 줄바꿈이 있어(`Operation between\n14 A ...`) 정확한 부분 문자열이 아니라서 걸림(공백 정규화하면 일치). 모델이 줄바꿈을 공백으로 바꿔 인용하는 것이 원인. 1차 관문 "인용 일치율 95%"의 정의에 직접 영향 -> 예선 전에 정의를 정해야 함.
- 관찰 2 **같은 printed_rule_id 중복**: 한 각주(Note 2)에서 규칙 3개가 나와 모두 "Note 2" -> duplicate_identifier. 분할 규칙의 식별자 접미사 정책 필요.
- 관찰 3 모델별 추출 세분화가 다름(8/8/4개). 사고 토큰: gemini-3.1-flash-lite가 출력의 2.5배(비용·지연), gpt-6.1-sol 79개, gemini-3.8-flash 보고 0.
- 관찰 4 데이터시트 표 행을 모델이 condition=항목명, action=값으로 나눔(gemini-3.1) 또는 condition에 합침(gpt). 프롬프트 품질 이슈이며 스모크 문서는 채점 대상이 아니므로 조정하지 않음(프롬프트 수정은 예선 기준선 이후 최대 2회).
- 구현 보정: `run.py`의 `main()`이 시작할 때 `.env`를 읽도록 한 줄 추가(실행 CLI가 키를 찾지 못하던 문제, 값은 출력하지 않음).
- 설계서 갱신(2026-10-14): §5 2·5·6번에 공백 정규화 인용 일치(`quote_whitespace_adjusted`, `quote_match_rate`), 원문 구간 기준 위치·해시·`model_quote` 보존, 중복 인쇄 ID 접미사(`-2`, `-3`, `split_from_printed_id`)를 반영하고 §14에 스모크 결과를 추가. 검증기 수정은 구현자가 진행 중(독립 검증 대기).

### 마무리 정리 (2026-10-14)
- 검증기 수정(공백 정규화 인용, 중복 인쇄 ID 접미사) 독립 검증 PASS(`reports/validator_update_verify.md`): 줄바꿈 인용 8개 일치, 단어·숫자·대소문자·구두점 변경은 `evidence_not_found`, 위치·해시·`model_quote` 독립 재계산 일치, 접미사 `-2`·`-3` 결정적, 비차단 플래그가 KG 적재 제외를 일으키지 않음, 스모크 재검증 값이 보고와 일치, TTL SHACL 적합. 전체 테스트 301개, 점검 3종 PASS(경고 0건).
- 판정 외 관찰(미결): (1) 서로 다른 문서의 같은 인쇄 ID는 `duplicate_identifier`로 둘 다 `rules_valid`에서 빠짐(점수 영향 없음, 접미사/문서 접두 결정 필요), (2) 표 행 인용 끝의 ` | ` 때문에 붙는 `quote_whitespace_adjusted`는 정보 가치가 낮음, (3) 표 셀에 줄바꿈이 든 실제 데이터가 없어 해당 경로는 합성 데이터로만 시험.
- **예선 전 발견한 문제:** 같은 설정으로 반복 실행하면 캐시(검증된 응답 재사용)가 같은 응답을 돌려줘 "3회 실행 일관성" 측정이 무의미해진다. 캐시 우회 옵션이 아직 없다(`--no-cache` 등). 예선 전에 구현·검증 필요(인수인계 문서 §6-1).
- 인수인계 문서 `docs/handoff_2026-10-14.md` 작성. 커밋 전 점검: `check_secrets`(미추적 포함 146개) PASS, `check_leakage` PASS(125개), `check_raw_unchanged` PASS, `.env`·모델별 설정·호출 기록·산출물·백업이 추적 후보에 없음, `requirements.txt` ASCII.
