# Rule·Document 승격 구현 보고서 [B, 결정적 변환]

작성 2026-10-12 (같은 날 보완 2회: 10장 해시 사슬 검사, 11장 MAINT 조건·조치 문구 출처 변경). 범위: Document 7, MaintenanceRule 8, ThresholdRule 22와 그 출처(Provenance), S9 shape, 전처리 고정 검증 기록과 사전 검사. C·D는 구현하지 않았다. 모델 호출·네트워크 접근 없음.

## 1. 만든·고친 파일
| 파일 | 구분 | 내용 |
|---|---|---|
| `src/imaks_kg/kg/promote_rules.py` | 새로 만듦 | 승격 본체. `load_inputs(paths)`, `build_graph`(순수 함수), `semantic_threshold_errors`, `run(paths)`(사전 검사 → 변환 → 의미 검사 → 쓰기), `main(paths)`, 대조표 생성. 결정할 수 없는 입력은 `PromoteError`로 멈춤 |
| `src/imaks_kg/kg/preprocess_lock.py` | 새로 만듦(보완 1) | 경로 묶음 `BPaths`(기본값 settings 상수), lock 생성(`--init`, 기존 파일은 `--force` 필요), `check_chain(paths)`(쓰기 없음) |
| `harness/preprocess_lock.json` | 새로 만듦(보완 1) | 고정 검증 기록. git 추적 대상(`git check-ignore` 결과 무시 안 됨). SHA-256 `c7998ba8fdc40a3dae42edba54ea960731f3d25aba842d22ff711cc3a56714d8` |
| `src/imaks_kg/kg/naming.py` | 함수 추가 | `document_iri`, `maintenance_rule_iri`, `threshold_rule_iri`, `table_cell_prov_iri`, `SOURCE_KIND_DOCUMENT`. A의 기존 함수는 그대로 |
| `src/imaks_kg/settings.py` | 상수 추가 | `DOC_MANIFEST`, `DOC_PAGES`, `DOC_TABLES`, `SENSOR_THRESHOLDS_CSV`, `SEED_TTL`, `RULES_TTL`, `SEED_PLUS_RULES_TTL`, `PREPROCESS_LOCK`, `PREPROCESS_CODE_DIR`, `PREPROCESS_VERIFY_REPORT` |
| `ontology_v1/shapes.ttl` | S9 추가 | `im:SensorNoThresholdShape`: `sh:targetClass im:Sensor`와 nominalValue·warnLo·warnHi·critLo·critHi 각각 `sh:maxCount 0`, 한국어 메시지. 머리 주석에 S9 한 줄 추가. 그 밖은 그대로 |
| `ontology_v1/examples/fail_06_sensor_threshold.ttl` | 새로 만듦 | S1을 만족하는 Station·Sensor에 `im:critHi` 하나만 붙인 실패 예제 |
| `tests/test_shacl.py` | 수정 | EXPECTED에 fail_06→{S9} 추가, 실패 예제 수 5→6, 보조 반례 2개(속성 5개 각각 S9만 위반 / ThresholdRule의 임계값은 위반 아님) |
| `tests/test_promote_rules.py` | 새로 만듦 | unittest 28개(6장, 10장, 11장) |

`ontology.ttl`, `imaks_data/`, `work_log.md`, `.gitignore`, 전처리 코드(`src/imaks_kg/preprocess/`)는 고치지 않았다. `schema_tables.md`에는 SHACL 규칙 목록 절이 없어서 고치지 않았다(제안: 4-2절 Sensor 아래에 "S9: 임계값 속성 금지" 한 줄).

## 2. 실행 방법
```
PYTHONPATH=src PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m imaks_kg.kg.seed_to_rdf          # seed.ttl 먼저(필수 입력)
PYTHONPATH=src PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m imaks_kg.kg.preprocess_lock      # 해시 사슬만 검사(쓰기 없음)
PYTHONPATH=src PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m imaks_kg.kg.promote_rules        # 사전 검사 후 승격
.venv/Scripts/python.exe .claude/skills/stage-check/scripts/run_shacl.py --data kg_build/seed_plus_rules.ttl --ont ontology_v1/ontology.ttl
PYTHONPATH=src PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest discover -s tests
```
lock 갱신은 전처리를 재검증한 뒤에만 사람이 한다: `python -m imaks_kg.kg.preprocess_lock --init --force`.
(PowerShell: `$env:PYTHONPATH="src"; $env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python.exe -m imaks_kg.kg.promote_rules`)

## 3. 입력/출력
- 입력(읽기 전용, 이 목록만 읽는다):
  - `preprocessed/documents/doc_manifest.csv`, `pages.jsonl`(문서 제목), `tables.jsonl`
  - `doc_profile.json`, `chunks.jsonl`, `glyph_fixes.csv`(해시 검사만)
  - `preprocessed/sensors/rules/sensor_thresholds.csv`(대조와 의미 검사)
  - `imaks_data/kg_seed/nodes.csv`, `edges.csv`
  - `imaks_data/rules/*.pdf`, `imaks_data/datasheets/*.pdf`(SHA-256 계산용으로 바이트만)
  - `src/imaks_kg/preprocess/documents.py`, `sensors.py`(해시만)
  - `harness/preprocess_lock.json`
  - `kg_build/seed.ttl`(Sensor IRI 확인)
- 읽지 않는 것: 정답 규칙 파일, `nodes_factory.csv`, `data/` 폴더.
- 출력(모두 git 무시 대상: `/kg_build/`, `/reports/*`):
  - `kg_build/rules_deterministic.ttl`: 2,684 트리플, Provenance 240
  - `kg_build/seed_plus_rules.ttl`: seed.ttl과 rules를 합친 파일(SHACL 확인용, 실행할 때마다 다시 만든다)
  - `reports/maint_mapping.md`: MAINT 8행 대조표(코드가 생성)
  - `reports/threshold_mapping.md`: 센서 22행 임계값 대조표(코드가 생성)
- 경로 주입: `load_inputs(paths)`, `run(paths)`, `main(paths)`는 `BPaths`(문서 폴더, 임계값 파일, lock, 전처리 코드 폴더, seed 폴더, seed.ttl, 출력 폴더, 보고서 폴더)를 받는다. 기본값은 settings 상수다.

## 4. 개수
| 항목 | 개수 | 비고 |
|---|---|---|
| Document | 7 | SOP-001~004, DS-ELEC-3300, DS-MECH-4400, DS-THERM-2200 |
| MaintenanceRule | 8 | MAINT-01~08 |
| ThresholdRule | 22 | 센서당 1개(결정 #1). seed Sensor 22개를 각각 정확히 한 번씩 가리킨다 |
| Provenance(document, 표 셀) | 224 | ThresholdRule 22×8셀, MaintenanceRule 8×6셀 |
| Provenance(seedCsv) | 16 | MAINT 노드 행 8, appliesToSensor 엣지(triggers 줄 + resolves 줄) 8 |

코드가 기대 개수(7/8/22)를 검사하고, 다르면 멈춘다.

## 5. 대조 요약
**MAINT(`reports/maint_mapping.md`)**: 8행 중 같음 3(MAINT-05, 06, 08), 다름 5. 다른 5행은 모두 "조치 문구" 차이이고, 센서·우선순위 차이는 0이다. seed 문구가 SOP-003보다 단어가 많다.
- MAINT-01은 seed에만 'main', MAINT-02는 'alignment', MAINT-03은 'TEN', MAINT-04는 'inlet'이 있다.
- MAINT-07은 'Activate emergency'(seed)와 'Emergency'(SOP-003)이 다르다.
- seed Maintenance 행에는 조건(Trigger) 값이 없다. 그래서 조건은 판정에서 빼고 SOP-003 원문만 적었다.
- KG 문구는 SOP-003에서 가져온다(11장). 이 비교 결과는 그대로다.

**임계값(`reports/threshold_mapping.md`)**: seed nodes.csv, SOP-002 표, 전처리 임계값 파일을 센서 22개 × 5값 + 단위로 대조했다. 불일치 0개, 표기만 다른 경우 0개다. 임계값 파일에만 있는 센서는 없다. 데이터시트와 SOP-002의 충돌은 ④ 범위라 이번 대조에 넣지 않았다.

## 6. 확인한 결과(직접 실행, 11장 변경 후 최종)
- `run_shacl.py --data kg_build/seed_plus_rules.ttl --ont ontology_v1/ontology.ttl` → Conforms: True, PASS (S7·S8·S9 포함). `seed.ttl`만 넣어도 PASS.
- 예제 11개:
  - pass_01~05는 PASS.
  - fail_01·02는 S1, fail_03은 S3, fail_04는 S4, fail_05는 S5만 위반한다. 기존 10개 판정은 바뀌지 않았다.
  - fail_06은 S9만 위반한다.
- `unittest discover -s tests` → 101개 OK. 기존 71, test_shacl 추가 2, test_promote_rules 28이다.
- `check_leakage.py`
  - 기본 폴더: PASS.
  - `preprocessed ontology_v1 kg_build src`: PASS.
  - `harness`를 폴더째 넣으면 FAIL 8건이다. 8건 모두 `harness/forbidden_columns.txt`, 즉 금지어 목록 파일 자체가 걸린 것이다(10-4절). `harness/preprocess_lock.json`만 넣으면 PASS.
- `check_raw_unchanged.py` → PASS (1121개 파일).
- `preprocess_lock`(검사 모드) → PASS: 해시 사슬 일치.
- 결정성: 두 번 실행해 출력 SHA-256이 같다. 최종 `rules_deterministic.ttl`은 `6285899452bb…c0b9`이다. 테스트도 메모리에서 다시 만든 결과를 바이트 단위로 비교한다.
- 코드와 테스트에 절대 경로가 없다(grep으로 확인).

test_promote_rules가 확인하는 것:
- 개수와 Document 속성: 7/8/22, MAINT-01~08. Document 값이 doc_manifest·실제 PDF 해시와 같다.
- Rule 공통: 모든 Rule에 sourceDocument가 1개 있고, 표 셀 Provenance 필드가 tables.jsonl의 해당 셀과 같다. appliesToSensor는 seed.ttl의 Sensor이고, ThresholdRule은 센서와 1:1이다.
- MAINT: priority·센서가 seed와 같고, conditionText·responseText가 SOP-003 셀과 같다(11장).
- ThresholdRule: 5값과 responseText가 tables.jsonl과 같고, 임계값 파일과도 같다. extractionMethod는 "table"이고 ruleSeverity는 없다. 임계값 속성은 ThresholdRule에만 있다.
- SHACL: 합본이 적합하다. seed Sensor에 critHi를 넣으면 S9만 위반한다.
- 대조표: 행 수가 맞다.
- 멈춤 조건 4가지: MAINT 행 ID 중복, resolves/triggers 불일치, priority 불일치, 센서 매핑 실패.
- 해시 사슬 반례 10개(10-3절).
- 결정성.
- 소스 검사: 두 모듈의 import가 허용목록 안에 있고, 정답·팩토리 파일명과 `data/` 경로가 없다.

## 7. 설계 선택
- **IRI**: A의 `inst:` 규칙을 따른다.
  - Document: `inst:doc_SOP_002`
  - MaintenanceRule: `inst:rule_MAINT_01`
  - ThresholdRule: `inst:rule_thr_ST02_SEALING_TMP`
  - 표 셀 출처: `inst:prov_doc_SOP_002_p1_table2_r2_c3`
  - MAINT의 seed 출처는 A 방식 그대로다. `inst:prov_seed_node_<nodeId>`와 `inst:prov_seed_appliesToSensor_<M>_<S>`를 쓰고, 뒤의 것은 triggers 줄과 resolves 줄의 `row:<n>` 두 개를 함께 담는다.
- **ThresholdRule identifier**: `SOP-002:THR:<센서 identifier>`로 정했다.
  - 원문에 규칙 ID가 없고, 결정 #1로 센서당 1개라 센서 ID만으로 유일하다.
  - 표 위치 기반 ID와 달리 PDF 레이아웃이 바뀌어도 그대로다. 위치는 Provenance에 있다.
- **행 찾기(SOP-003)**: 헤더가 정확히 `Rule ID | Sensor | Station | Trigger | Action | Priority`인 표에서 1열이 seed ruleId와 정확히 같은 행을 찾는다. 다음 경우에는 멈춘다.
  - 같은 ID가 두 행 이상
  - 표의 ID 집합과 seed의 ID 집합이 다름
  - Station+Sensor 열로 찾은 센서가 resolves 대상과 다름
  - priority가 다름
- **SOP-002 임계값 표**: caption이 `<STATION> Thresholds`이고 헤더 8열이 정확히 같은 표만 쓴다.
  - 이어지는 표(`p2:table1`)는 앞 표(`p1:table5`)와 caption·`continues_in`이 맞는지 확인하고, 앞 표의 헤더를 쓴다.
  - 셀(`cells`)과 `rows_normalized`가 같아야 한다.
- **센서 매핑**: caption의 스테이션 이름 + Sensor 열 약어로 seed의 monitors(Component→Sensor) 엣지에서 sensorType이 같은 Sensor를 찾는다.
  - 정확히 1개가 아니면 멈춘다. 이름이 `<스테이션>_<약어>`가 아니어도 멈춘다.
  - 찾은 IRI가 seed.ttl에 `im:Sensor`로 있는지 확인한다.
- **수치**: 셀 문자열을 엄격한 정규식으로 읽어 `xsd:decimal`로 넣는다. Nominal은 `±` 앞의 수만 쓴다.
- **문서 Provenance(셀 단위)**: 필드는 sourceKind="document", page, tableId, rowIndex·colIndex, bbox, sourceQuote, textSha256이다.
  - rowIndex·colIndex는 1부터 센다(tables.jsonl의 row·col + 1). 이어지는 표는 그 표 자체 기준이다.
  - sourceQuote는 셀의 `text_normalized`이고, textSha256은 그 SHA-256이다.
  - 셀 단위로 둔 이유: 수치마다 나온 좌표를 추적할 수 있다. 또 Provenance에는 열 번호가 하나뿐이라, 행 전체를 노드 하나로 두면 colIndex가 의미를 잃는다.
- **Document**: doc_manifest에 title 컬럼이 없다. 그래서 title은 pages.jsonl 1쪽에서 `Document: <ID> |` 줄 앞의 줄들을 이어 만들었다. 그 줄의 ID가 doc_id와 다르면 멈춘다.
- **만들지 않은 값**: ruleSeverity, actionTarget, ThresholdRule의 conditionText, 허용오차.
- **unit**: 온톨로지의 domain이 Sensor라 ThresholdRule에 붙이지 않았다. 단위 일치는 대조표와 의미 검사로 확인한다.

## 8. 알려진 한계
- "± 허용오차"는 온톨로지에 속성이 없어 KG 속성으로 만들지 않았다. 원문은 Nominal 셀 Provenance(인용·해시)에 남고, 대조표에 참고 열로 적었다.
- Provenance에 문서 ID 전용 속성이 없다. 셀 Provenance가 어느 속성을 뒷받침하는지도 colIndex와 표 헤더로 거꾸로 따져야 한다.
- sourceQuote·responseText·conditionText는 `text_normalized`(줄바꿈 합침, 글리프 치환 적용)다. 줄바꿈이 있던 원문은 tables.jsonl의 `text_raw`에만 있다.
- `xsd:decimal`의 "120"은 rdflib 직렬화에서 `120.0`이 된다. 수치는 같다.
- 대조표 md 두 개는 `/reports/*` 규칙에 걸려 git에 올라가지 않는다.
- 해시 사슬의 한계는 10-4절에 있다.

## 9. 미결정 사항 (ontology.ttl은 고치지 않았다. 필요하면 사용자가 정한다)
1. 허용오차 속성 추가 여부.
2. Provenance에 문서 ID 속성이나 "뒷받침하는 속성 이름" 필드를 추가할지.
3. `extractionMethod` 값 어휘를 고정할지. 현재 값은 ThresholdRule·MaintenanceRule 모두 "table"이다(11장).
4. ThresholdRule에 단위 속성을 둘지.
5. `schema_tables.md`에 S9를 어디에 적을지.
6. 대조표 두 개를 git에 남길지(`.gitignore` 예외 추가).
7. `check_leakage.py`에 `harness`를 넣을 때 금지어 목록 파일 2개를 예외로 둘지(10-4절).

## 10. 해시 사슬 검사 (보완 1, 사용자 요청)

### 10-1. 사슬
```
imaks_data PDF 7개 (현재 SHA-256)
   │  == lock.input_pdfs == doc_manifest.file_sha256
   ▼
harness/preprocess_lock.json  (고정 검증 기록, git 추적, 근거 reports/preprocess_verify.md)
   │  == 현재 해시: doc_manifest.csv, pages.jsonl, tables.jsonl, chunks.jsonl, glyph_fixes.csv,
   │               sensor_thresholds.csv, 전처리 코드 documents.py·sensors.py
   │  doc_profile.json output_sha256 == 현재 파일 해시
   ▼
preprocessed/documents/{doc_manifest, pages, tables}  +  sensors/rules/sensor_thresholds.csv
   │  변환 + 의미 검사(SOP-002 표 22행 == sensor_thresholds.csv)
   ▼
kg_build/rules_deterministic.ttl, seed_plus_rules.ttl, reports/maint_mapping.md, threshold_mapping.md
```

### 10-2. 검사와 멈춤 조건
아래 검사는 출력 파일을 하나라도 쓰기 전에 모두 수행한다. 하나라도 틀리면 `PromoteError`로 멈추고, 새 파일을 만들지 않으며 기존 출력도 건드리지 않는다. 메시지에는 어느 파일이 어떤 해시로 달라졌는지 적는다.

| # | 검사 | 멈춤 조건(메시지 예) |
|---|---|---|
| 1 | lock 존재·형식 버전 | `lock 없음: … (검증 후 python -m imaks_kg.kg.preprocess_lock --init로 생성)` |
| 2 | PDF: 현재 == lock (a) == doc_manifest | `PDF <경로>: 현재 … / lock … / doc_manifest file_sha256 …`, PDF 목록 차이 |
| 3 | 문서 산출물 5개: 현재 == lock (b) | `전처리 산출물 preprocessed/documents/tables.jsonl: 현재 … != lock …` |
| 4 | doc_profile.json output_sha256 == 현재 파일 | `doc_profile.json output_sha256[chunks.jsonl] … != 현재 파일 …` |
| 5 | sensor_thresholds.csv == lock (c) | `임계값 파일 preprocessed/sensors/rules/sensor_thresholds.csv: 현재 … != lock …` |
| 6 | 전처리 코드 2개 == lock (d) | `전처리 코드가 바뀌었으니 재검증 후 lock 갱신: src/imaks_kg/preprocess/documents.py 현재 … != lock …` |
| 7 | 변환 중 결정성 검사(행 찾기·센서 매핑·개수·priority) | 기존 PromoteError |
| 8 | 의미 검사: SOP-002 표 22행 수치·단위 == sensor_thresholds.csv | `의미 검사 실패: … ST02_SEALING_TMP critHi: SOP-002 표 205.0 != 임계값 파일 210.0` |

seed 값과 SOP-002의 차이는 멈춤 조건이 아니다. 지금처럼 대조표에 기록만 한다(통일하지 않음).

### 10-3. lock 생성 전 확인과 lock 내용
- **전처리 재실행 대조**: 전처리 코드는 고치지 않았다. 대신 scratchpad의 일회성 스크립트에서 모듈의 출력 경로 상수만 바꿔 `documents.main()`과 `sensors.main()`을 임시 폴더로 다시 돌렸다.
  - 결과: doc_manifest.csv, pages.jsonl, tables.jsonl, chunks.jsonl, glyph_fixes.csv, sensor_thresholds.csv, ts_input.csv 7개 모두 현재 `preprocessed/`와 SHA-256이 같았다. doc_profile.json 기록과도 같았다.
  - 첫 실행에서는 doc_manifest만 달랐다. 원인은 임시 스크립트의 경로 표기 함수가 절대 경로를 썼기 때문이다. 고쳐서 다시 돌리니 같았다.
  - 임시 산출물(평가 라벨 사본 포함)은 확인 후 지웠다.
- 그다음 `python -m imaks_kg.kg.preprocess_lock --init`으로 lock을 만들었다. 기록 시각은 `2026-10-12T13:31:47+00:00`이다.
- lock 파일 SHA-256: `c7998ba8fdc40a3dae42edba54ea960731f3d25aba842d22ff711cc3a56714d8`
- lock에 담긴 것:
  - (a) PDF 7개의 경로와 SHA-256(doc_manifest와 같음)
  - (b) 문서 산출물 5개의 해시
  - (c) `sensor_thresholds.csv` 해시
  - (d) `created_at`, `created_by`, `documents.py`(2df44da3…5a97)·`sensors.py`(9e3c6a18…c6f5) 해시
  - (e) `basis_report: reports/preprocess_verify.md`
- 생성 시 검사: PDF와 doc_manifest가 같고, doc_profile 기록이 현재 파일과 같고, 근거 보고서가 있어야 만든다. lock이 이미 있으면 `--force` 없이는 덮어쓰지 않는다.
- 보완 1 직후 확인: promote_rules를 다시 실행한 출력 4개의 해시가 보완 전과 같았다(`rules_deterministic.ttl` 8199eea8…19c1, `seed_plus_rules.ttl` 71a2503f…8d69, `maint_mapping.md` b05c3d24…1ecd, `threshold_mapping.md` b9fc44eb…bad9). 그다음 11장 변경으로 앞의 3개가 바뀌었다.
- 반례 테스트(`HashChainGuard`, 임시 폴더 사본에서 실행, 10개):
  - (i) tables.jsonl의 ST02_SEALING TMP CRIT_HI를 210.0 → 205.0으로 바꾸면 멈추고, 출력이 생기지 않는다.
  - (ii) (i)과 같이 바꾼 뒤 lock (b)와 doc_profile까지 새 해시로 맞춰도 의미 검사(`ST02_SEALING_TMP critHi`)에서 멈춘다.
  - (iii) pages.jsonl 한 글자 변경 → 멈춤.
  - (iv) doc_manifest의 SOP-003 PDF 해시 변경 → 멈춤.
  - (v) doc_profile output_sha256 불일치 → 이 항목 1건만으로 멈춤.
  - (vi) 전처리 코드 해시 불일치 → "전처리 코드가 바뀌었으니 재검증 후 lock 갱신"으로 멈춤.
  - (vii) 정상 사본은 통과하고, 출력 4개가 저장소 산출물과 바이트 단위로 같다.
  - (viii) 정상 실행 뒤 표를 바꿔 멈추면, 기존 출력 4개의 mtime_ns와 내용이 그대로다.
  - 추가: 임계값 파일 변경, lock 없음.

### 10-4. 한계
- **lock 기준선은 2026-10-12 재생성본이다.** 10-07 검증(`reports/preprocess_verify.md`) 당시의 출력 해시는 git에 기록이 없어 직접 비교할 수 없다. 이번 lock이 증명하는 것은 "현재 파일 = 현재 전처리 코드로 다시 돌린 결과 = doc_profile 기록"이다. 10-07 검증본과 바이트 단위로 같다는 증명은 아니다.
- lock은 의도적인 동시 변경을 막지 못한다. 예를 들어 tables.jsonl, lock, doc_profile을 함께 고치면 해시 검사를 통과한다. 이때 남는 방어선은 의미 검사뿐이고, 의미 검사는 SOP-002 임계값 수치와 단위만 본다. MAINT 표 문구나 pages 내용을 함께 고친 경우는 막지 못한다. lock이 git에 추적되므로, lock 변경은 diff와 리뷰로 드러나야 한다.
- 의미 검사의 기준인 sensor_thresholds.csv는 센서 시계열 원본에서 나온다. SOP-002 PDF와는 독립된 출처지만, 둘이 원래부터 같다는 것은 이 데이터셋에서 확인한 사실일 뿐이다. 원본이 바뀌어 두 값이 의도적으로 달라지면 이 검사는 멈춘다(통일하지 않음).
- 전처리 코드 해시는 `documents.py`, `sensors.py` 두 파일만 본다. 두 파일이 쓰는 공용 모듈(`common/io_utils.py`, `provenance.py`, `settings.py`)과 pdfplumber 버전 변경은 감지하지 못한다.
- `created_at`은 기록용이며 검사하지 않는다.
- `check_leakage.py`에 `harness`를 폴더째 넣으면 `harness/forbidden_columns.txt`(금지어 목록 파일 자체)에서 8건이 걸려 FAIL이다. lock 파일만 넣으면 PASS다. 점검기 예외는 사용자가 정할 일이라 고치지 않았다.

## 11. MAINT 조건·조치 문구 출처 변경 (2026-10-12 사용자 결정)
병합 기준 1번 중 B 쪽 구현이다.

- **conditionText** = SOP-003 표 1(`SOP-003:p1:table1`)의 해당 행 Trigger 셀(4열) `text_normalized`.
- **responseText** = 같은 행 Action 셀(5열) `text_normalized`. 예전에는 seed action이었다.
- 두 셀 모두 기존 방식의 셀 Provenance가 붙는다(page, tableId, rowIndex, colIndex, bbox, sourceQuote, textSha256). 이 Provenance는 예전에도 6셀 전부에 있었으므로 Provenance 수는 240 그대로다.
- **seed action은 KG 속성으로 두지 않는다.** seed 문구는 `maint_mapping.md` 대조표와 seed Provenance(`prov_seed_node_<nodeId>`가 가리키는 nodes.csv 행)에만 남는다.
- **priority·appliesToSensor 검사**: seed와 SOP-003 값이 다르면 멈춘다(`<ID>: priority가 seed … 와 SOP-003 … 로 다름`). 센서는 예전부터 검사했다. 현재 8행 모두 같다. KG의 priority 값은 seed이고, 두 값이 같음을 확인한 뒤에만 넣는다.
- **maint_mapping.md**: 머리말에 "KG conditionText·responseText 출처 = SOP-003" 설명을 넣고, 행마다 출처 열(`SOP-003 (Trigger 열 4, Action 열 5)`)을 추가했다. seed와 SOP-003 문구 비교(같음 3, 다름 5)는 그대로다.
- **extractionMethod**: MaintenanceRule 값을 "seedCsv"에서 "table"로 바꿨다. 지시에는 없던 변경이다. KG 문구가 이제 표 셀에서 오므로 "seedCsv"는 사실과 다르다고 판단했다. identifier·priority·센서는 seed와 표가 같음을 확인한 값이다. 되돌리려면 상수 한 줄만 바꾸면 된다.
- 만들지 않은 값은 그대로다(ruleSeverity, actionTarget).
- **산출물 해시가 바뀐 이유**:
  - `rules_deterministic.ttl`(8199eea8… → `6285899452bbbaa8ce98cb15495cee5c4d82576a088d075772769e6fb3b4c0b9`): MAINT 8개에 conditionText 8 트리플이 추가됐다(2,676 → 2,684). 다름 5행의 responseText 문구가 바뀌었고, extractionMethod 값도 바뀌었다.
  - `seed_plus_rules.ttl`(71a2503f… → `66ce7f598a68bf140c4985f6c62a19a12b1ca9c076294a61d4f07a42abee0e48`): 위 변경을 포함한다.
  - `maint_mapping.md`(b05c3d24… → `b2033dd63ff258d5dd96726142d60f06685b1d06caf54fcd82714d67e92ed4ac`): 머리말과 출처 열이 바뀌었다.
  - `threshold_mapping.md`(b9fc44eb…bad9): 바뀌지 않았다.
- 테스트: `test_maintenance_matches_seed`가 다음을 확인한다.
  - conditionText 8개가 SOP-003 Trigger 셀과 같다.
  - responseText 8개가 SOP-003 Action 셀과 같다.
  - 두 셀의 Provenance(sourceQuote)가 있다.
  - seed action이 다른 행에서는 KG 값에 그 문구가 없다.
  - priority가 일치하고, extractionMethod가 "table"이며, ruleSeverity가 없다.
  - 별도로 `test_stops_on_priority_mismatch`가 priority가 다르면 멈추는지 확인한다.
- 변경 후 다시 돌린 결과: 합본 SHACL PASS, 전체 unittest 101개 OK, check_leakage(기본 + 지정 폴더) PASS, check_raw_unchanged PASS, 해시 사슬 PASS.

verifier 검증 필요.
