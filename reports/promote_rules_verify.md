# 2차 검증(보완 후) — Rule·Document 승격 (B, 결정적 변환) 검증 보고서

- 검증일: 2026-10-12. 검증자: 독립 verifier. 1차 검증 보고서(같은 파일)는 이 보고서로 대체한다.
- 구현 보고서 `reports/promote_rules_impl.md`(10장 해시 사슬, 11장 MAINT 문구 출처)는 확인할 대상을 찾는 데만 썼다.
- 방법: `src/imaks_kg/kg/*`를 import하지 않는 독립 스크립트로 판정했다. 스크립트는 세션 scratchpad(저장소 밖)의 `verify_b.py`이고, csv/json/hashlib/re/decimal/rdflib만 쓴다. 결과는 `PASS` 104건, `FAIL` 0건이다. 멈춤 재현(`stop_repro.py`)과 결정성 확인(`det.py`)만 지시대로 `BPaths`·`promote_rules.run`을 호출했다. 모든 출력 경로는 임시 폴더다.
- `imaks_data/kg_seed/ground_truth.csv`는 열지 않았다.
- 기본 경로의 실제 산출물 5개(rules_deterministic.ttl, seed_plus_rules.ttl, maint_mapping.md, threshold_mapping.md, preprocess_lock.json)는 검증 전후로 SHA-256과 mtime이 같다. `ls -l --time-style=full-iso` 출력의 md5는 전후 모두 `4ea0b030…`이다.

## 판정: PASS

## 항목별 결과

### 공통 5항목
| 항목 | 결과 | 근거 |
|---|---|---|
| `check_raw_unchanged.py` PASS | PASS | `PASS: imaks_data/ 원본 불변 (1121개 파일)`, 검증 시작과 끝 모두 exit=0 |
| `check_leakage.py` PASS | PASS | 기본 폴더: `검사한 파일 41개 … PASS: 금지 컬럼 없음` exit=0. `preprocessed ontology_v1 kg_build src harness/preprocess_lock.json`: `검사한 파일 42개 … PASS` exit=0. harness 폴더 전체 결과는 관찰 절에 적었다(판정 제외) |
| 코드에 절대 경로 없음 | PASS | `grep -rnE "[A-Za-z]:\\\\|[A-Za-z]:/|/Users/|/home/" src/ tests/` 0건. `settings.py`는 `REPO_ROOT = Path(__file__).resolve().parents[2]`를 기준으로 경로를 만든다 |
| 큰 산출물·원본 데이터 git 미추적 | PASS | `git ls-files`에서 `imaks_data/`, `preprocessed/`, `kg_build/`, `evaluation/` 아래 파일 0개. `git check-ignore -q`: kg_build/seed.ttl, rules_deterministic.ttl, preprocessed/documents/tables.jsonl은 rc=0(무시) |
| 삭제·보간·평활화 코드 없음 | PASS | `grep -rnE "interpolate|fillna|dropna|rolling\(|ewm\(|savgol|\.drop\(" src/` 0건 |

### Rule·Document 승격 (B) 8항목
| 항목 | 결과 | 근거 |
|---|---|---|
| seed.ttl+rules 합본이 `run_shacl.py --ont`(추론 끔)로 적합(S7·S8 포함) | PASS | `run_shacl.py --data kg_build/seed_plus_rules.ttl --ont ontology_v1/ontology.ttl` → `Conforms: True` rc=0. 독립 스크립트로 seed.ttl과 rules_deterministic.ttl을 직접 합친 그래프(3,166 트리플)도 `Conforms: True` rc=0. 합친 그래프와 seed_plus_rules.ttl의 트리플 집합이 같다. `run_shacl.py:43` `inference="none"`. 반례 확인: 합친 그래프에서 MAINT-01의 sourceDocument와 Provenance 하나의 textSha256을 빼면 S8·S7 메시지와 함께 `Conforms: False`가 나온다. S7·S8이 실제로 작동한다 |
| Document 7개, identifier·sourceSha256·pageCount = doc_manifest | PASS | Document 7개. 7개 모두 identifier = doc_id, sourceSha256 = manifest file_sha256 = 실제 PDF SHA-256(직접 계산), pageCount = manifest pages, sourcePath = manifest file |
| MaintenanceRule 8개(MAINT-01~08), appliesToSensor = seed resolves 대상, sourceDocument SOP-003, 표 Provenance(tableId,rowIndex,colIndex,bbox,textSha256) | PASS | identifier가 MAINT-01~08로 정확히 8개. appliesToSensor = edges.csv `resolves` 대상(8/8). sourceDocument = `doc_SOP_003`(8/8). 규칙마다 SOP-003:p1:table1 해당 행 c1~c6 셀의 Provenance가 있고 5필드를 모두 갖췄다 |
| `maint_mapping.md`에 seed vs SOP-003 비교 8행 | PASS | `| MAINT-` 8행. seed 조치는 nodes.csv와 같고, SOP-003 Trigger·Action은 tables.jsonl과 같다(8/8). 같음 3, 다름 5는 독립 계산과 같다 |
| ThresholdRule 22개(센서당 1), 수치 = SOP-002 표, extractionMethod="table" | PASS | 22개, appliesToSensor 22개가 서로 다르고 센서마다 1개. 5값×22 = 110값이 Decimal 비교로 SOP-002 표 = KG = sensor_thresholds.csv. 단위도 표와 CSV가 같다. extractionMethod "table" 22/22. sourceDocument SOP-002 |
| seed 임계값 vs SOP-002 대조 결과가 보고서에 있음 | PASS | `reports/threshold_mapping.md` 22행, 요약은 `불일치 0개`. 독립 계산(nodes.csv Sensor 행 vs SOP-002 표)에서도 차이 0건이다. 그래서 "둘 다 기록"할 대상이 없다 |
| 모든 Rule의 appliesToSensor가 seed.ttl의 Sensor | PASS | Rule 30개(MAINT 8 + THR 22)가 모두 appliesToSensor를 갖고, 대상은 모두 seed.ttl의 `rdf:type im:Sensor` 노드다 |
| B 코드에 LLM 호출·정답 파일 참조 없음 | PASS | `src/imaks_kg/kg/*.py`에서 openai, anthropic, requests, urllib, http.client, socket, httpx, langchain, transformers, aiohttp 검색 결과 0건. `ground_truth`는 src 전체에서 0건. `data/`, `evaluation`, `row_labels`, `ts_input`도 kg 코드에서 0건. import는 표준 라이브러리, rdflib, imaks_kg.common·kg·settings뿐이다 |

## 추가 검증 1. PDF부터 실제 입력까지의 해시 사슬 — PASS
lock 파일은 `harness/preprocess_lock.json`(sha256 `c7998ba8…14d8`)이다. 모든 해시는 독립 스크립트가 파일 바이트로 직접 계산했다.

| 대상 | 결과 | 근거 |
|---|---|---|
| 입력 PDF 7개 | PASS | `imaks_data/` 아래 PDF는 모두 7개(rglob)다. `lock.input_pdfs`(7키) == 실제 SHA-256 dict(경로·값 모두 일치) |
| doc_manifest.csv file_sha256 | PASS | 7행 모두 실제 PDF 해시와 같다 |
| 문서 산출물 5개 | PASS | lock.document_outputs 키가 정확히 doc_manifest.csv, pages.jsonl, tables.jsonl, chunks.jsonl, glyph_fixes.csv이고, 5개 모두 현재 파일 해시와 같다 |
| sensor_thresholds.csv | PASS | lock.sensor_outputs 키는 이 파일 하나뿐이고 해시가 현재 파일과 같다(`eef3eb58…ab86`) |
| 전처리 코드 해시 | PASS | documents.py `2df44da3…5a97`, sensors.py `9e3c6a18…c6f5`가 현재 파일과 같다. 같은 폴더의 `__init__.py`는 lock에 없다(관찰) |
| doc_profile.json output_sha256 | PASS | 5개 키 모두 현재 파일 해시와 같다 |
| 코드 자체 검사 | PASS | `python -m imaks_kg.kg.preprocess_lock` → `PASS: 해시 사슬 일치` |

## 추가 검증 2. 멈춤 동작 직접 재현 — PASS
- 방법: 경우마다 새 임시 폴더를 만들고 필요한 입력을 복사했다. 복사한 것은 PDF 7개, nodes/edges.csv, preprocessed/documents 전체, 임계값 CSV, lock, 전처리 코드 2개, seed.ttl, preprocess_verify.md이다. 그 사본을 가리키는 `BPaths`로 `promote_rules.run`을 호출했다.
- 각 경우를 두 번 돌렸다.
  - (1) 정상 실행으로 출력 4개를 먼저 만든 뒤 변형한 경우
  - (2) 출력이 없는 상태에서 변형한 경우
- 판정 기준:
  - `PromoteError`로 멈춘다.
  - 실행 전후 임시 폴더 전체 파일 스냅샷(SHA-256과 mtime_ns)에서 새 파일이 0개이고 바뀐 파일이 0개다.

| 경우 | 기존 출력 있음 | 기존 출력 없음 | 멈춘 단계·메시지 |
|---|---|---|---|
| (a) tables.jsonl SOP-002 ST02_SEALING TMP CRIT_HI 210.0→205.0 | PASS | PASS | 해시 사슬. `전처리 산출물 preprocessed/documents/tables.jsonl: 현재 522a6c… != lock 5659c0…`, doc_profile 불일치 |
| (b) (a)와 같이 바꾼 뒤 lock document_outputs와 doc_profile을 새 해시로 맞춤 | PASS | PASS | 의미 검사. `ST02_SEALING_TMP critHi: SOP-002 표 205.0 != 임계값 파일 210.0` |
| (c) pages.jsonl 한 글자 변경 | PASS | PASS | 해시 사슬. pages.jsonl 현재 ≠ lock, doc_profile 불일치 |
| (d) SOP-003 PDF 바이트 변경(실제 PDF 해시 불일치) | PASS | PASS | 해시 사슬. `PDF …SOP_003_MaintenanceRules.pdf: 현재 a81dc4… / lock 89bb8b… / doc_manifest 89bb8b…` |
| (e) 전처리 코드 documents.py 변경 | PASS | PASS | 해시 사슬. `전처리 코드가 바뀌었으니 재검증 후 lock 갱신: … documents.py` |
| 대조: 변경 없는 사본 | 통과 | - | 출력 4개가 저장소 산출물과 바이트 단위로 같다 |

반례 테스트(`tests/test_promote_rules.py` `HashChainGuard`)를 읽고 확인한 결과:
- (a) `test_i_table_value_change_stops_without_output`가 다룬다(같은 셀, 210.0→205.0). 출력이 없어야 함을 검사한다.
- (b) `test_ii_semantic_check_after_lock_refresh`가 다룬다. lock과 doc_profile을 맞춘 뒤 `check_chain == []`를 먼저 확인하고, 의미 검사 메시지 `ST02_SEALING_TMP critHi`로 멈추는지 본다.
- (c) `test_iii_pages_one_char_change`가 다룬다.
- (d) `test_iv_manifest_pdf_hash_change`는 실제 PDF 바이트가 아니라 doc_manifest의 해시 문자열을 바꾼다. PDF 쪽 불일치 경로(현재 ≠ manifest)는 검사하지만, "PDF 파일 자체가 바뀐" 경우는 테스트가 직접 다루지 않는다. 같은 비교식이 그 경우도 잡는다는 것은 위 재현 (d)로 확인했다.
- (e) `test_vi_preprocess_code_change`가 다룬다.
- 기존 출력의 내용과 mtime이 그대로인지는 `test_viii`가 검사하지만 (a) 경우에만 한다. 나머지 경우는 "출력 없음"만 본다. 이 부분은 위 재현으로 보완했다.
- 이 밖에 doc_profile 불일치(v), 임계값 파일 변경, lock 없음, 정상 사본 바이트 일치(vii)도 테스트에 있다.

## 추가 검증 3. MAINT 문구 출처 변경 — PASS
| 확인 | 결과 | 근거 |
|---|---|---|
| conditionText = SOP-003 표 1 Trigger 셀(text_normalized) | PASS 8/8 | 규칙마다 conditionText는 1개이고, `SOP-003:p1:table1` 같은 Rule ID 행의 `Trigger` 열 값과 같다 |
| responseText = Action 셀 | PASS 8/8 | 규칙마다 responseText는 1개이고, `Action` 열 값과 같다 |
| 두 셀의 Provenance | PASS 8/8×2 | hasProvenance 중 tableId·rowIndex·colIndex가 그 셀(행 i+1, 열 4/5)을 가리키는 것이 정확히 1개 있다. page = 표 page이고, sourceQuote = 셀 text_normalized, textSha256 = sha256(UTF-8 sourceQuote)이다. bbox는 아래 문서 Provenance 전수 대조에서 셀 bbox와 같음을 확인했다 |
| seed action이 KG 속성에 없음 | PASS | seed action과 SOP Action이 다른 5개 규칙(MAINT-01,02,03,04,07)에서 seed action 문구는 그 규칙의 어떤 속성 값에도 없다. 나머지 3개(05,06,08)는 두 문구가 같다. MAINT 속성 집합은 appliesToSensor, conditionText, extractionMethod, hasProvenance, identifier, priority, responseText, sourceDocument, sourceNodeId, type이다. action 계열 속성은 없다 |
| priority·appliesToSensor = seed | PASS 8/8 | priority: KG = nodes.csv priority = SOP-003 Priority. appliesToSensor: KG = edges.csv resolves 대상 |
| maint_mapping.md 같음 3·다름 5와 출처 설명 | PASS | 판정 열은 같음 3(05,06,08)과 다름 5다. 독립 계산(seed action == SOP Action)도 3/5다. 머리말에 "KG의 `conditionText` = SOP-003 Trigger 셀, `responseText` = SOP-003 Action 셀 원문 … seed action은 KG 속성으로 두지 않고" 설명이 있고, 행마다 출처 열 `SOP-003 (Trigger 열 4, Action 열 5)`가 있다 |
| 원문 PDF 교차 확인(참고) | 일치 | pdfplumber로 SOP-003 PDF 1쪽 표를 직접 뽑았다. Trigger·Action 8행 문구가 tables.jsonl 값과 같다. 콘솔 인코딩 때문에 °만 깨져 보였다 |

extractionMethod 관찰(판정 제외, 사실 대조만):
- 8개 모두 `"table"`이다.
- 값별 실제 출처는 다음과 같다.
  - conditionText, responseText: SOP-003 표 셀에서 왔다.
  - identifier: 표 Rule ID와 seed ruleId가 같은 값이다.
  - priority: 코드는 seed 값 `r["priority"]`를 넣는다. 표 값과 같음을 확인한 뒤에만 넣는다.
  - appliesToSensor: seed edges(resolves/triggers)에서 정했고, 표의 Station+Sensor와 같은지 검사했다.
  - sourceNodeId: seed에서만 왔다.
- 따라서 "table"은 규칙의 핵심 텍스트(조건·조치) 출처와 맞는다. 다만 엄밀히는 seed와 표를 섞은 결과다. 일부 값(sourceNodeId, priority·센서 IRI의 실제 대입원)은 seed에서 온다.
- 원래 값 "seedCsv"는 이제 조건·조치 문구에 대해 사실과 다르다.
- `schema_tables.md`는 extractionMethod 값을 "LLM 추출 / 표 결정적 변환"으로 설명하고 "seedCsv"는 sourceKind 값으로만 정의한다. 그래서 "table" 쪽이 스키마 설명에 더 가깝다. 지시에 없던 변경이므로 사용자 확인이 필요하다.

## 추가 검증 4. 재확인 — PASS
| 확인 | 결과 | 근거 |
|---|---|---|
| 임계값 22행 수치 대조 | PASS, 불일치 0 | SOP-002 표 행 22개(이어지는 표 포함, 센서 이름 중복 없음). KG ThresholdRule = 표 = sensor_thresholds.csv, 110값과 단위 22개가 모두 같다 |
| 문서 Provenance 전수 | PASS, 불일치 0 | Provenance 240개 = document 224개 + seedCsv 16개. 224 = MAINT 8×6 + THR 22×8. 224개 모두 다음을 만족한다. (tableId, rowIndex, colIndex)가 tables.jsonl의 셀(row+1, col+1)로 존재하고, page = 표 page, bbox = 셀 bbox(float 비교), sourceQuote = 셀 text_normalized = rows_normalized 해당 칸, textSha256 = sha256(sourceQuote) |
| Document 해시 = PDF | PASS | 7/7 |
| 결정성 | PASS | 임시 출력 폴더로 두 번 실행했다. 출력 4개 해시가 run1 = run2이고 저장소 산출물과도 같다(`6285899…c0b9`, `66ce7f5…0e48`, `b2033dd…d4ac`, `b9fc44e…bad9`). 기본 경로 산출물은 다시 쓰지 않았다 |
| 단위 테스트 | PASS | `unittest discover -s tests` → `Ran 101 tests … OK`. 실행 전후 실제 산출물 mtime·해시 불변 |
| git check-ignore | PASS | 추적 가능(rc=1): harness/preprocess_lock.json, reports/seed_to_rdf_counts.md, reports/maint_mapping.md, reports/threshold_mapping.md(`.gitignore:228-230` 부정 규칙), src/imaks_kg/kg/promote_rules.py. 무시(rc=0): kg_build/*, preprocessed/*. `git status`에서 kg_build/는 `!!`, lock과 대조표 3개는 `??`(미추적이지만 추적 가능)이다 |

## 불합격 사유와 수정이 필요한 위치
없음.

## 미확인 항목과 이유
- lock 기준선이 10-07 전처리 검증 당시 출력과 바이트 단위로 같은지는 확인하지 못했다(미확인). 그때의 해시 기록이 git에 없다. 이번에 확인한 것은 "현재 파일 = lock = doc_profile"이다.
- 전처리를 다시 실행해 lock 해시가 재현되는지는 직접 재실행하지 않았다(미확인). 구현 보고서 10-3의 주장이다.

## 관찰(판정 제외)
- **harness 폴더 전체 누수 검사**: `check_leakage.py harness`는 FAIL이다. `harness/forbidden_columns.txt` 3~10줄의 금지어 8개가 걸리고, checklist.md 2곳과 raw_manifest.json 1곳에서 `ground_truth` 경고가 나온다. 금지어 목록 파일 자체와 문서 문구가 걸린 것이라 알려진 오탐이다. lock 파일만 넣으면 PASS다.
- **해시를 같이 맞추면 문구 변조가 통과한다(재현함)**:
  - 임시 사본에서 SOP-003 표 MAINT-01 Action 셀을 "Do nothing"으로 바꾸고 lock과 doc_profile을 새 해시로 맞췄다. promote_rules는 멈추지 않았고, KG responseText에 그 문구가 들어갔다.
  - 의미 검사는 SOP-002 수치·단위만 본다. 이번 변경으로 MAINT 문구가 표에서 오게 됐으므로 이 경로의 방어선은 lock의 git diff 리뷰뿐이다. 구현 보고서 10-4에도 적혀 있다.
- **전처리 코드 해시 범위**: documents.py와 sensors.py만 본다. `preprocess/__init__.py`, `common/io_utils.py`, `common/provenance.py`, `settings.py`와 pdfplumber 버전이 바뀌어도 감지하지 못한다.
- **반례 테스트 범위**: HashChainGuard (iv)는 doc_manifest 문자열을 바꾸는 방식이라 실제 PDF 바이트 변경을 직접 다루지 않는다. 기존 출력 mtime 보존은 (a) 경우에만 검사한다. 위 재현으로 나머지를 확인했다.
- HashChainGuard는 `repo_root`를 기본값(실제 저장소)으로 두고 실제 PDF를 읽는다. 읽기만 하며, 원본 불변 검사도 PASS다.
- Rule·Document 노드에는 위치 속성(page, tableId, rowIndex, colIndex, bbox, sourceQuote, textSha256)이 없다. 위치 정보는 Provenance에만 있어서 CLAUDE.md 4장 규칙과 맞는다.
- 합본 트리플 수는 3,166개로 1차 검증의 3,158개보다 8개 많다. conditionText 8개가 추가된 것과 맞는다.
