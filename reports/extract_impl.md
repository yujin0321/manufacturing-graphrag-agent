# [C] LLM 규칙 추출(④) 구현 보고서

작성 2026-10-12, implementer. **실제 LLM 호출은 하지 않았다**(API 키 없음, 비용 승인 전). 모든 실행·테스트는 가짜 응답(FakeClient)으로 했다.
정답 규칙 파일, `data/`, 평가 폴더, `imaks_data/human/` 응답 로그는 열지 않았고 프롬프트·예시·설계에 쓰지 않았다.

## 1. 만든 파일

| 파일 | 내용 |
|---|---|
| `src/imaks_kg/extract/__init__.py` | 패키지 설명 |
| `src/imaks_kg/extract/common.py` | jsonl 읽기, seed ID 목록(`seed_ids`), 청크 ID → 파일 이름(`:`→`__`), `ExtractError` |
| `src/imaks_kg/extract/inputs.py` | 입력 선택(`select_chunks`) + 해시 사슬 검사(`verify_chain`) |
| `src/imaks_kg/extract/prompt.py` | 3단 프롬프트 조립·구조 검사, 예시 검사, 사용자 메시지 |
| `src/imaks_kg/extract/prompts/v1/system.md` | Role/Task/Example 템플릿(자리표시 `{{SENSOR_IDS}}`, `{{STATION_IDS}}`, `{{EXAMPLES}}`) |
| `src/imaks_kg/extract/prompts/v1/examples.json` | 예시 3개 **초안**(`"confirmationStatus": "DRAFT_NEEDS_HUMAN_CONFIRMATION"`, 키 이름은 7장 12번) |
| `src/imaks_kg/extract/schema.py` | 구조화 출력 JSON Schema(`build_schema`) + pydantic `RuleItem` |
| `src/imaks_kg/extract/llm.py` | 요청 조립, `AnthropicClient`, `FakeClient`, 응답 해석, SDK 예외 처리 |
| `src/imaks_kg/extract/run.py` | 실행 CLI(`--dry-run`, `--fake`, `--execute`) |
| `src/imaks_kg/extract/validate.py` | 자동 검사 + Provenance 좌표·해시 계산 + 후보 ID |
| `src/imaks_kg/extract/merge.py` | B 규칙과 병합, identifier 부여, 중복 검사 |
| `src/imaks_kg/extract/conflicts.py` | 데이터시트 vs SOP-002 수치 충돌 후보(결정적) |
| `src/imaks_kg/extract/review.py` | 2단계 사람 검토(`round2`, `apply`) |
| `src/imaks_kg/extract/guard.py` | 검토·입력 무결성 검사(10장, 보완 요청으로 추가) |
| `src/imaks_kg/extract/llm_gemini.py` | Gemini(무료 등급) 어댑터: 키 처리, 클라이언트(SDK 재시도 없음), 요청·응답·오류 분류, 가짜 클라이언트, `--list-models`(13장) |
| `src/imaks_kg/extract/resume.py` | 이어서 하기(`--resume-from`): 재사용 조건 검사, 남은 청크로 제한, 합친 결과 검사(14장) |
| `src/imaks_kg/extract/ledger.py` | git 추적 해시 장부(추가만, 해시 사슬), 단계별 대조, 승인 상태 재구성(15장) |
| `harness/extraction_ledger.jsonl` | 해시 장부(빈 파일로 만듦, git 추적 대상. 커밋은 하지 않음) |
| `src/imaks_kg/extract/approval.py` | `--execute` 비용 승인 게이트(11장, 사용자 승인으로 추가) |
| `src/imaks_kg/extract/to_rdf.py` | 최종 결과 → `rules_llm.ttl`, 검토 전 `rules_llm_prereview.ttl`, 합본 |
| `src/imaks_kg/settings.py` | C 경로 상수 추가(`DOC_CHUNKS`, `EXTRACT_*`, `EXTRACTION_*`, `RULES_LLM_*`, `SEED_RULES_LLM_TTL`) |
| `tests/extract_fakes.py` | SOP 원문 청크로 만드는 가짜 응답(정상 + 일부러 넣은 오류) |
| `tests/extract_support.py` | 테스트 공용(가짜 실행, 검토 CSV 채우기, SHACL) |
| `tests/test_extract_inputs_prompt.py` (12) | 입력 선택, 해시 사슬 멈춤, 3단 구조, ID 목록·해시, 스키마, 요청 형식, 실제 실행 거부 2종, dry-run |
| `tests/test_extract_validate.py` (13) | 스키마·인용·ID 거부, 쪽 좌표·표 좌표·해시, 후보 번호, 폴백·거절·max_tokens, SDK 예외 순서 |
| `tests/test_extract_merge.py` (8) | ID 일치·정규화·표 행 일치 병합, 값 차이 기록, RULE-ST02-02 반례, ID 충돌·중복 0, B 값 불변(합본 비교) |
| `tests/test_extract_review.py` (10) | 1차 양식, 2차는 edit·hold만, 미결정 멈춤, 고친 값 재검사, 병합 변화 멈춤, 양식 열 잠금, 보존 |
| `tests/test_extract_guard.py` (17) | 무결성 반례 (a)~(k): 검토 기록 없음, final·1차·2차 변경, 해시·개수 위조, 일관된 위조(검증자 재현), manifest만 위조(6종), B·seed·청크·lock 변경, 정상 경로 해시 동일, 멈출 때 기존 출력 불변 |
| `tests/test_extract_resume.py` (14) | 청크 수·시도 상한 분리 반례, 이어서 하기(같은 결과·조건 변경 거부·중복 출처·실패 미재사용·합친 뒤 중복 규칙), 외부 전송 허용 목록, 기본 모델 |
| `tests/test_extract_ledger.py` (7) | 장부: 정상 경로, (j) 일관된 위조(manifest까지 위조), 중간 줄 삭제·수정, 장부 없음·실행 기록 없음, apply 단계, 승인 used→unused 수동 변경, 호출 간격 7.5초 |
| `tests/test_extract_gemini.py` (22) | Gemini 키(.env·환경·GOOGLE_API_KEY 충돌·없음), retry_options 없음, 요청 필드, 응답 해석, 오류 분류표, 호출 간격, 중단·재시도, 가짜 전체 경로 + SHACL, CLI 거부·승인·복원, genai.Client 생성 0회 |
| `tests/test_extract_errors.py` (20) | 오류 분류, 즉시 중단, 재시도 한도(청크당·실행당), retry-after, AMBIGUOUS 무재시도, SDK 재시도 끔, 승인 상태 기계(복원·부분 사용·사용량 확인·resolve·예약 충돌), 단일 청크 dry-run(12장) |
| `tests/test_extract_approval.py` (10) | 비용 승인 게이트(승인 없음·잘못된 ID·입력 변경·예시 변경·기록 위조·재사용 거부, 승인+가짜 클라이언트 통과, 호출 상한), 테스트 전 경로에서 실제 `anthropic.Anthropic` 생성 0회 |
| `tests/test_extract_e2e.py` (12) | 끝까지 실행 + 합본 SHACL, 결정성, 재현 기록, 거부 기록, RDF 출처, 충돌 후보, 소스 정적 검사 |

`ontology.ttl`, `shapes.ttl`, `work_log.md`, `.gitignore`는 고치지 않았다. `.gitignore`에는 이미 `/extraction/`이 있다(사용자가 추가, work_log [C] 구현 시작). 따로 손댈 것은 없다.

## 2. 실행 방법과 입출력

모두 저장소 루트에서 `PYTHONPATH=src PYTHONIOENCODING=utf-8`로 실행한다.

| 명령 | 입력 | 출력 |
|---|---|---|
| `.venv/Scripts/python.exe -m imaks_kg.extract.run --dry-run [--count-tokens]` | `preprocessed/documents/*`, `harness/preprocess_lock.json`, `kg_build/seed.ttl`, `kg_build/rules_deterministic.ttl`, `prompts/v1/` | 화면 출력만 |
| `... -m imaks_kg.extract.run --fake <폴더> [--run-id ID] [--out-root DIR]` | 위 + 가짜 응답 폴더 | `extraction/runs/<run_id>/`(기본) |
| `... -m imaks_kg.extract.run --dry-run [--approvals-dir DIR]` | 위 | 화면 출력 + 추정 기록 `extraction/approvals/<estimate_id>.json`(11장) |
| `... -m imaks_kg.extract.run --execute --approve <estimate_id>` | 위 | 같음. **예시 초안·키 없음·승인 없음/불일치/재사용이면 거부**(클라이언트·실행 폴더를 만들지 않음). 이번에 실행하지 않음 |
| `... -m imaks_kg.extract.review round2 --run-dir <실행 폴더>` | `review_round1.csv`(사람이 채움) | `review_round2.csv`(1차 확정. edit·hold가 없어도 0행으로 반드시 만든다) |
| `... -m imaks_kg.extract.review apply --run-dir <실행 폴더>` | 1차·2차 CSV | `final.jsonl`, `review_applied.json` |
| `... -m imaks_kg.extract.to_rdf --run-dir <실행 폴더> [--out-dir DIR]` | `final.jsonl`, `merged.jsonl` | `kg_build/rules_llm.ttl`, `rules_llm_prereview.ttl`, `seed_plus_rules_llm.ttl` |
| `... -m imaks_kg.extract.conflicts [--out CSV]` | 문서 산출물, `rules_deterministic.ttl` | `extraction/conflicts.csv`(기본) |
| `.venv/Scripts/python.exe .claude/skills/stage-check/scripts/run_shacl.py --data kg_build/seed_plus_rules_llm.ttl --ont ontology_v1/ontology.ttl` | 합본 | 적합 여부 |

가짜 응답 폴더 만들기: `PYTHONPATH=src .venv/Scripts/python.exe tests/extract_fakes.py <폴더>`.

실행 폴더 `extraction/runs/<run_id>/` 내용(이미 있으면 거부, 덮어쓰지 않음):
- `meta.json`: 모델 ID, max_tokens, effort, betas, fallbacks, 구조화 출력, 보내지 않은 파라미터와 이유(temperature·top_p·top_k·thinking), anthropic SDK 버전, 프롬프트 버전·조립 해시·템플릿 해시·예시 해시·예시 상태·예시 출처 청크, 스키마 해시, preprocess_lock 경로·해시, B 규칙 파일, 입력 청크 ID·text_sha256·source_file_sha256 목록, 제외 청크와 사유, 시작·끝 시각, 개수
- `raw/request/<청크>.json`(키 없음), `raw/response/<청크>.json`(원본 응답 전체 또는 실패 기록), `calls.jsonl`(실제 답한 모델, 폴백 여부, usage, request_id, stop_reason)
- `candidates_premerge.jsonl`(LLM 단독, 병합 전), `rejected.csv`(사유 코드·사유·원본 항목)
- `merged.jsonl`(병합 후), `merge_conflicts.csv`, `review_round1.csv`
- 검토 뒤: `review_round2.csv`, `final.jsonl`, `review_applied.json`(각 파일 SHA-256)

이번 작업에서 저장소의 `extraction/`과 `kg_build/rules_llm*.ttl`은 **만들지 않았다**. 가짜 실행 산출물은 모두 임시 폴더(테스트는 `tempfile`, 수동 확인은 세션 scratchpad)에 썼다.

## 3. dry-run 결과 (실행함)

```
입력 청크(호출 수): 60   (SOP-001 35, SOP-004 11, SOP-002 10, SOP-003 4)
제외 청크: 26           (SOP-002 table 11, 데이터시트 15. 목록과 사유는 화면과 meta.json에 출력)
프롬프트 v1 sha256=12c2bcef2ca99a0f3c07809e3c44fc804b26736c872b41d1aa4a3d2a42c32f3a 예시 상태=DRAFT_NEEDS_HUMAN_CONFIRMATION
입력 글자 수 합계: 520627
입력 토큰 추정: 약 130157 (글자/4), 상한 추정 173543 (글자/3)
출력 토큰 상한(max_tokens x 호출 수): 960000
```
- 조립된 system 프롬프트는 6,647자이고 60번 모두 같다. 입력의 대부분(약 40만 자)이 반복되는 system이다. 구조화 출력 스키마도 호출마다 들어간다(약 1.6천 자).
- 토큰 수는 글자 수 추정이다. 키가 있으면 `--dry-run --count-tokens`로 `client.messages.count_tokens`를 부를 수 있다(스키마 토큰은 포함되지 않음). 이번에는 키가 없어 부르지 않았다.
- 실제 출력은 청크당 수백 토큰 수준으로 예상되지만 측정값이 아니다. 비용 산정은 사용자 승인 단계에서 단가를 넣어 계산해야 한다.

## 4. 예시 초안과 출처 청크

`prompts/v1/examples.json`(`confirmationStatus`: `DRAFT_NEEDS_HUMAN_CONFIRMATION`). SOP 원문 청크에서 그대로 가져왔다. 정답 규칙 파일은 보지 않았다.

| # | 출처 청크 | 클래스 | 요지 |
|---|---|---|---|
| 1 | `SOP-001:p1:RULE-ST01-02` (rule) | OperationalRule | "If TMP exceeds 26°C, reduce speed by 10% and notify QC." 센서 ST01_FILLING_TMP, 공정 ST01_FILLING, ruleIdInText RULE-ST01-02, actionSteps 2개 |
| 2 | `SOP-004:p1:RULE-ACCESS-02` (rule) | AccessRule | "Security personnel MUST be notified within 2 minutes of detection." 센서·공정 없음, ruleIdInText RULE-ACCESS-02 |
| 3 | `SOP-003:p1:table2:chunk` (table, §2 패턴) | MaintenanceRule | WRH01-TMP↑ → QC HOLD 행. 입력은 표 머리 줄 + WRH01 행만(나머지 두 행 생략, 원문 줄은 그대로). ruleIdInText null, actionSteps 3개 |

- 예시는 `check_examples`가 검사한다: 입력 줄이 실제 청크에 있는지, 인용·ID가 입력에 있는지, 센서·공정이 목록 안인지.
- **사람이 확인할 것:** 분류(특히 §2 패턴을 MaintenanceRule로 둔 것), conditionText/responseText를 어디서 자를지, ruleSeverity를 null로 둔 판단(예시 1·2에는 등급 단어가 없음), targetStations 판단(예시 1의 ST01_FILLING).
- **한계:** 예시 3개의 출처 청크도 추출 입력이다(세 청크 모두 60개 입력에 들어 있음). 이 청크에서는 모델이 예시를 그대로 따라 할 수 있어 결과가 실력보다 좋아 보일 수 있다. 평가(D)에서 이 세 청크를 따로 표시하거나 빼고 볼지 정해야 한다.

## 5. 동작 요약

### 입력과 해시 사슬
- 선택: SOP-001·003·004는 전부, SOP-002는 table이 아닌 청크만, 데이터시트는 제외. 제외 목록에는 사유를 붙인다.
- 해시 사슬(하나라도 틀리면 `ExtractError`로 멈추고 아무것도 쓰지 않음): B의 `preprocess_lock.check_chain`(PDF == lock == doc_manifest, 문서 산출물(chunks.jsonl 포함) == lock, doc_profile == 현재 파일, 임계값 파일 == lock, 전처리 코드 == lock). 그다음 청크마다 `text_sha256 == SHA-256(text)`, `source_file_sha256 ==` lock의 PDF 해시를 보고, text·rule 청크는 쪽 텍스트 좌표와 청크 텍스트가 같은지도 본다.

### 호출과 응답 처리
- 요청은 지시한 형식 그대로다(`client.beta.messages.create`, model `claude-opus-5-5`, max_tokens 16000, betas `server-side-fallback-2026-07-01`, fallbacks `"default"`, output_config effort `high` + json_schema). thinking·temperature·top_p·top_k는 보내지 않는다(테스트로 확인).
- stop_reason이 `end_turn`이 아니면 실패로 기록하고 파싱하지 않는다.
- **지시와 다르게 정한 점:** 성공이면 "첫 text 블록"을 쓰라고 했다. 하지만 SDK 문서에 따르면, 폴백이 일어나면 content 안에 `fallback` 블록이 있고 그 앞은 거절한 모델이 쓰던 출력이다. 그래서 fallback 블록이 있으면 **마지막 fallback 블록 뒤의 첫 text 블록**을 쓰고, 없으면 첫 text 블록을 쓴다. 가짜 응답으로 확인했다(거절 모델의 미완성 JSON 앞부분을 건너뜀).
- 폴백 여부는 `usage.iterations`에 type `fallback_message`가 있는지로 정한다. 실제로 답한 모델은 `response.model`, request_id는 `_request_id`에서 가져온다. 폴백 결과는 검토 CSV의 `served_by_fallback=yes`로 표시한다.
- SDK 예외(APIStatusError, APIConnectionError, CredentialsError)를 잡아 분류하고, 분류에 따라 중단·재시도한다(12장). 오류 메시지는 키 모양 문자열을 가리고 300자까지만 남긴다.
- 키는 `anthropic.Anthropic()` 기본 방식(환경변수)으로만 읽는다. `--execute`를 받으면 (1) 예시가 CONFIRMED가 아닐 때, (2) `ANTHROPIC_API_KEY`가 없을 때 거부한다.

### 자동 검사(validate)
순서대로 검사하고 처음 걸린 사유 하나를 `rejected.csv`에 쓴다: `schema`(최상위 형식, 추가 키, 타입 엄격), `sensor_not_in_list`, `station_not_in_list`, `quote_empty`/`quote_not_in_chunk`, `rule_id_not_in_chunk`, `rule_severity_not_in_chunk`, `quote_spans_table_rows`, `page_coordinate_mismatch`. 호출 실패는 `call_failed`(item_index −1)로 남긴다.
- **ruleIdInText·ruleSeverity도 청크 원문에 글자 그대로 있어야 한다**("만든 ID·등급 금지"를 검사로 옮긴 것, 내 선택).
- **좌표(지시와 다르게 정한 점):** text·rule 청크는 지시대로 `charStart = 청크 char_start + 청크 안 위치`, `charEnd = charStart + 인용 길이`로 쪽 좌표를 계산하고 쪽 텍스트와 대조한다(rule 청크는 전처리에서 줄바꿈을 공백으로 바꿨으므로 줄바꿈→공백으로 비교, 길이는 같다). **table 청크는 이 방식을 쓸 수 없다.** 청크 텍스트가 표 행을 "열: 값; …"으로 직렬화한 것이라 쪽 텍스트와 글자 위치가 맞지 않기 때문이다(24개 table 청크 모두 확인). 그래서 table 청크의 인용은 전처리의 직렬화를 다시 계산해서 어느 행·열에 놓였는지 찾고, 표 좌표(tableId, rowIndex, colIndex(걸친 열마다), 열들의 bbox를 합친 범위)를 쓴다. B의 셀 Provenance와 같은 좌표 체계라 (b) 병합에 바로 쓸 수 있다. 머리 줄이나 두 행 이상에 걸친 인용은 거부한다.
- `textSha256 = SHA-256(sourceQuote)`.
- 후보 ID `<chunk_id>:r<n>`: 검사를 통과한 항목을 청크 안 인용 시작 위치(같으면 끝 위치, 항목 순서) 순으로 번호를 붙인다.

### MAINT 병합(merge) 구현
work_log "MAINT 병합 기준"을 그대로 따랐다.
- B 색인: `rules_deterministic.ttl`의 Rule 30개(MAINT 8 + 임계값 22)를 identifier, 정규화 ID(대문자·공백 제거), 셀 Provenance의 (tableId, rowIndex)로 색인한다. 같은 표 행이 두 B 규칙을 가리키면 멈춘다.
- (a) 정규화한 ruleIdInText가 B identifier와 같으면 병합. 인용한 표 행이 다른 B 규칙의 행이면 `tableRow` 충돌로도 기록한다.
- (b) ruleIdInText가 null이고 인용의 (tableId, rowIndex)가 B 셀 Provenance의 행이면 병합.
- ruleIdInText가 있는데 B에 없는 ID면 (b)도 적용하지 않는다(ID가 다른 규칙은 합치지 않음). 반례 테스트: SOP-001 `RULE-ST02-02`(ST02 TMP > 210°C)는 SOP-002 ST02 TMP 임계값(critHi 210, 같은 센서)과 합쳐지지 않는다.
- 병합하면 새 Rule을 만들지 않고 B 값(class, appliesToSensor, conditionText, responseText, priority)을 바꾸지 않는다. 비교 항목(class, 센서 집합, 공정, conditionText, responseText)이 다르면 `merge_conflicts.csv`에 LLM 값·B 값·두 출처를 쓴다. B MaintenanceRule에는 actionTarget이 없어 공정 비교는 "appliesToSensor 센서의 소속 공정(hasSensor)"과 하고, 그 출처를 값 옆에 적는다. 문구는 문자열 그대로 비교한다.
- 병합하지 않은 후보의 identifier: ruleIdInText(원문 표기)가 다른 후보·B와 겹치지 않으면 그 값, 아니면 위치 기반 ID. 여러 후보가 같은 ID를 내면 그 ID가 자기 청크의 rule_id인 후보가 정확히 하나일 때만 그 후보가 ID를 쓰고 나머지는 위치 기반 ID(예: 한 규칙 문장의 두 등급을 두 레코드로 나누면 둘 다 위치 기반 ID가 된다). 마지막에 B + C identifier 중복 0을 확인하고, 있으면 멈춘다.
- 병합 전(`candidates_premerge.jsonl`)과 병합 후(`merged.jsonl`)를 따로 저장한다.

### 가짜 응답 전체 실행 결과(scratchpad, 테스트와 같은 가짜 응답)
호출 60(실패 2: 거절 1, max_tokens 1. HTTP 200 응답이라 실행은 계속), 폴백 1, 후보 31, 거부 7, B 병합 8(ID 7 + 표 행 1), 새 규칙 23, 병합 충돌 2(MAINT-02 조건 문구, MAINT-03 클래스). 전부 수락으로 검토를 적용하고 `to_rdf`를 돌린 뒤 합본 `seed_plus_rules_llm.ttl`(3,699 트리플)이 `run_shacl.py --ont ontology_v1/ontology.ttl`로 **PASS**. 같은 입력으로 두 번 돌리면 결과 파일(meta.json의 시각 제외)과 TTL 3개의 해시가 같다(테스트).

### 사람 검토(review)
- 1차 `review_round1.csv`: 후보마다 한 행(모든 필드, sourceQuote, 청크 ID, 위치, 병합 여부·근거·B ID, 폴백 여부, 답한 모델, 메모) + merge_conflicts 행. 사람은 `decision`, `edited_fields`(JSON 객체), `comment`만 채운다. 다른 열을 고치면 apply가 멈춘다.
- 고칠 수 있는 필드: 병합하지 않은 후보는 class, conditionText, responseText, ruleSeverity, sensors, targetStations, sourceQuote, ruleIdInText. B에 병합된 후보는 sourceQuote만(B 값은 덮어쓰지 않음). merge_conflict 행은 accept/reject/hold만 받고 edit는 거부한다. B 값은 어느 경우에도 바뀌지 않고, 재확인 출처를 붙일지는 후보 행의 결정이 정한다.
- 2차 `review_round2.csv`: 1차에서 edit·hold인 항목만 담는다. `final_decision`은 accept/edit/reject 중 하나다.
- apply: 빈 결정, 2차 파일 없음, 2차 빈 값·hold가 있으면 멈춘다. 고친 값은 validate 검사를 다시 거치고, 실패하면 멈춘다(좌표·해시도 다시 계산). 고친 뒤 병합을 다시 계산해 병합 여부·대상이 바뀌면 멈춘다. LLM 원본·1차·2차·최종은 모두 남고, 이미 있는 파일은 덮어쓰지 않는다.

### RDF(to_rdf)
- 병합하지 않은 규칙: `inst:rule_llm_<identifier 토큰>`, 4분류 클래스, identifier, conditionText, responseText, ruleSeverity(있을 때), extractionMethod "llm", appliesToSensor, actionTarget, sourceDocument, hasProvenance.
- Provenance: `inst:prov_llm_<run_id>_<candidate_id>`. sourceKind "document", page, sourceQuote, textSha256, extractionMethod "llm". text·rule 청크는 charStart·charEnd, table 청크는 tableId·rowIndex·colIndex·bbox.
- **재확인 출처를 둘 곳: 같은 파일(`rules_llm.ttl`)에서 B 규칙 IRI에 `hasProvenance`만 붙이는 방식을 골랐다.** 이유: (1) LLM에서 온 트리플이 한 파일에 모여 seed + B + C 세 파일만 합치면 된다. (2) B 파일은 그대로라 "B 값 불변"을 파일 비교로 확인할 수 있다. 테스트는 합본에서 B 규칙의 class·appliesToSensor·conditionText·responseText·priority·identifier·actionTarget·sourceDocument 트리플이 B 산출물과 같고, B 트리플이 전부 남아 있고, 새로 붙은 출처는 extractionMethod "llm"뿐임을 확인한다. 단점: `rules_llm.ttl`만 따로 읽으면 B IRI가 정의 없이 나온다.

## 6. 데이터시트 vs SOP-002 수치 충돌 후보 (`conflicts.py`, 실행함, 출력은 scratchpad)

데이터시트 값 15개(표 행 + 본문 주석)를 모았고 후보는 5건이다. 값을 통일하거나 어느 쪽이 맞는지 정하지 않았고, 두 쪽 원문 라벨을 그대로 적었다.

| ID | 센서 | SOP-002(표 셀) | 데이터시트 값과 원문 라벨 | 위치 | 비교 |
|---|---|---|---|---|---|
| DSC-001 | ST01_FILLING_PRS | WARN_HI 4.2 (Nominal 3.8), `SOP-002:p1:table1` 행 3 열 6 | 0.50 bar, "Application Note — Alarm Threshold Setting": "at least 5× the accuracy (0.50 bar) from the nominal operating point" | DS-MECH-4400 p1 char 493-561 | 차이 0.4 < 0.50 (margin) |
| DSC-002 | ST02_SEALING_CUR | CRIT_HI 15.0, `SOP-002:p1:table2` 행 4 열 7 | 14 A, "Continuous overload rating (See note 2)" | DS-ELEC-3300 표1 행 4 열 2 | 15.0 > 14 (상한) |
| DSC-003 | ST02_SEALING_CUR | CRIT_HI 15.0 (같은 셀) | 14 A, "Note 2 — Continuous Overload Rating": "rated for continuous operation up to 14 A" | DS-ELEC-3300 p1 char 484-525 | 15.0 > 14 (상한) |
| DSC-004 | ST02_SEALING_TMP | CRIT_HI 210.0, `SOP-002:p1:table2` 행 2 열 7 | -40 to 200 °C, "Measurement range (Continuous; see note 1)" | DS-THERM-2200 표1 행 2 열 2 | 210.0이 범위 밖 |
| DSC-005 | ST02_SEALING_TMP | CRIT_HI 210.0 (같은 셀) | 200 °C, "Note 1 — Maximum Operating Temperature": "rated maximum for continuous operation is 200°C" | DS-THERM-2200 p1 char 515-562 | 210.0 > 200 (상한) |

- 알려진 후보 3개(ST02 TMP 200 vs 210 ℃, ST02 CUR 14 vs 15 A, ST01 PRS 여유)가 원문에서 실제로 확인됐다. TMP·CUR은 표 행과 본문 주석 두 곳에서 따로 나온다.
- ST01 PRS는 0.30 bar("closer than 3× accuracy ... not recommended") 기준에는 걸리지 않는다(0.4 ≥ 0.30). ST02 PRS는 WARN_HI 차이가 0.5로 기준과 같아서 후보가 아니다(`<` 비교).
- 의미 차이: 데이터시트 값은 "센서의 연속 운전 정격·측정 범위"이고 SOP-002 값은 "경보 임계값"이다. DS-ELEC Note 2는 "process alarm thresholds triggering corrective action be set no higher than the continuous overload rating"이라고 권고한다. 그래서 같은 의미의 충돌인지는 사람이 판단할 몫이다.
- 각 행에는 두 쪽의 문서 ID, 쪽, 표 좌표 또는 문자 위치, 인용, SHA-256이 있다. 테스트는 SOP 인용 == 표 셀, 데이터시트 문자 위치의 쪽 텍스트 == 인용, 해시 일치를 확인한다.
- 수집 규칙은 정규식(`MODEL_CODE`, `UPPER_LABELS`, `TEXT_UPPER`, `TEXT_MARGIN`)과 비교 규칙(range: 모든 값이 범위 안, upper: nominal·warnHi·critHi > 상한, margin: warn·crit과 nominal의 차이 < 여유)이다. 단위가 SOP-002 센서 단위와 같을 때만 비교한다. DS-ELEC는 표 제목에 모델 코드가 없어 문서 제목의 "Current Transformer" → CUR 대응을 상수로 두었다.

## 7. 설계 선택(내가 정한 것)

1. table 청크 인용은 쪽 문자 위치가 아니라 표 좌표(tableId·rowIndex·colIndex·bbox)로 남긴다(5장의 이유). colIndex는 인용이 걸친 열마다 값 하나씩이다.
2. 폴백 응답은 마지막 fallback 블록 뒤의 첫 text를 쓴다(5장).
3. ruleIdInText·ruleSeverity도 원문에 글자 그대로 있어야 통과한다.
4. 같은 ruleIdInText 충돌은 자기 청크 rule_id 기준으로 결정적으로 처리한다(5장).
5. 사용자 메시지에 문서 ID·제목·쪽·절·청크 종류를 맥락으로 넣는다. rule 청크("FLW MUST …")만으로는 어느 공정의 센서인지 알 수 없어서다. 인용은 `<chunk>` 안에서만 하도록 지시하고 검사한다.
6. 제외하지 않은 SOP 제목·머리말 text 청크(30자 미만 포함)도 지시대로 모두 호출한다. 예상 응답은 `{"rules": []}`이다(호출 낭비, 아래 미결 사항).
7. 실패한 호출은 재시도하지 않는다(SDK 기본 재시도만). 실패는 `rejected.csv`에 `call_failed`로 남는다.
8. LLM Provenance에도 `extractionMethod "llm"`을 붙인다(재확인 출처를 구분하기 위해서. 아래 온톨로지 사항 참고).
9. 실행 폴더와 검토 결과는 덮어쓰지 않는다. 다시 하려면 새 run_id를 쓴다.
10. dry-run은 키가 있어도 `--count-tokens`를 함께 줘야만 API를 부른다(실수로 호출하는 것을 막기 위해).
11. `merge_conflicts.csv`는 실행마다 다르므로 `extraction/merge_conflicts.csv`가 아니라 `extraction/runs/<run_id>/merge_conflicts.csv`에 둔다(체크리스트 문구와 경로가 다르다).
12. **지시와 다른 점:** 예시 파일의 상태 키를 `"status"`가 아니라 `"confirmationStatus"`로 했다. `status`는 누수 점검(`harness/forbidden_columns_header_only.txt`)이 JSON 키로 금지하는 단어라서, `status`를 쓰면 `check_leakage.py`의 `src` 검사가 FAIL한다(처음에 그렇게 만들었다가 FAIL을 보고 바꿈). 값과 거부 동작은 지시와 같다.

## 8. 알려진 한계

- 실제 모델 응답으로는 한 번도 돌리지 않았다. 구조화 출력 스키마(배열 enum, `["string","null"]`)가 서버에서 받아들여지는지, 토큰 수, 실제 거절·폴백 빈도는 확인하지 못했다.
- 가짜 응답은 내가 SOP 원문을 보고 만든 것이라 실제 모델 출력의 다양성을 대표하지 않는다. 테스트가 확인하는 것은 파이프라인의 검사·병합·검토 논리다.
- 예시 출처 청크 3개가 추출 입력에도 있다(4장).
- 인용 검사는 정확 일치라서, 모델이 공백이나 기호(—, °, ↑)를 조금만 바꿔도 거부된다. 거부율이 높으면 1차 검토에서 sourceQuote를 고쳐 살릴 수 있다.
- 같은 인용이 청크에 여러 번 나오면 첫 위치를 쓴다(`quote_occurrences`에 횟수를 기록).
- 원문 그대로 남기는 실행 기록(`extraction/runs/*/raw/request/`)에는 SOP-004 §3 제목의 금지어 단어가 들어간다. 그래서 `check_leakage.py`를 `extraction/`에 돌리면 FAIL(오탐, 2건)이다. 기본 폴더와 `preprocessed ontology_v1 kg_build src`는 PASS다. 실제 모델이 그 제목을 sourceQuote로 인용하면 `kg_build/rules_llm.ttl`에도 그 단어가 들어가 kg_build 검사가 FAIL할 수 있다(전처리 문서 폴더와 같은 종류의 오탐).
- 데이터시트 충돌 수집은 이 데이터시트 3개의 표현에 맞춘 정규식이라 다른 문서에는 일반화되지 않는다. 표의 `Max fluid temp` 같은 다른 단위(°C 대 L/min) 행은 비교하지 않는다.
- e2e 테스트는 큰 합본 SHACL을 두 번 돌려 약 1분 걸린다.

## 9. 사용자가 결정할 것

1. **예시 확정:** `prompts/v1/examples.json` 3개를 SOP 원문과 대조해 고치거나 그대로 승인한 뒤 `confirmationStatus`를 `CONFIRMED`로 바꿔야 실제 실행이 가능하다. 예시 출처 청크를 평가에서 어떻게 다룰지도 정해야 한다.
2. **실제 실행 승인:** 호출 60회, 입력 약 13만(상한 17만) 토큰 추정, 출력 상한 96만 토큰. 가격표(입력 $4 / 출력 $20 per 1M, 기준일 2026-10-06)로 추정 비용은 입력만 약 $0.52, 최대 약 $19.89(모든 호출이 max_tokens까지 출력한 경우)다. 예시를 확정하고 키를 설정한 뒤 `--dry-run [--count-tokens]`로 새 추정 기록을 만들고, 그 estimate_id를 승인해 주면 `--execute --approve <estimate_id>`로 실행한다(11장).
3. **제목·머리말 청크 호출 여부:** 지시대로 SOP-001·003·004 전부와 SOP-002 text 청크를 넣었다. 그중 규칙이 없는 제목 청크(예: "2.2 ST02_SEALING", SOP-002 "<STATION> Thresholds" 제목들)를 빼면 호출이 약 20회 줄어든다.
4. **온톨로지 미비(`ontology.ttl`은 고치지 않음, 변경안 필요):**
   - Provenance에 **청크 ID, 실행 ID, 모델 ID 속성이 없다.** 지금은 Provenance IRI(`prov_llm_<run_id>_<chunk_id>_r<n>`)에만 실행 ID와 청크 ID가 들어 있고, 모델 ID는 `meta.json`과 `final.jsonl`(served_model)에만 있다. 예: `chunkId`, `extractionRunId`, `modelId`(domain Provenance) 추가.
   - **`extractionMethod`의 domain이 Rule이다.** 재확인 출처를 구분하려고 Provenance에도 `extractionMethod "llm"`을 붙였다. 추론을 끈 SHACL에서는 문제가 없지만, RDFS 추론을 켜면 Provenance가 Rule로 추론돼 S8에 걸린다. domain을 Rule ∪ Provenance로 넓히거나 Provenance 전용 속성을 두는 변경이 필요하다.
   - Provenance에 **문서 ID 속성이 없다**(B 후속 과제와 같은 문제). LLM 출처는 Rule의 sourceDocument로만 문서를 알 수 있고, 재확인 출처는 B 규칙의 sourceDocument에 기댄다.
   - 셀 여러 개에 걸친 인용은 colIndex를 여러 값으로 쓴다(shape는 개수를 제한하지 않음). 이렇게 쓰는 것이 맞는지 확인이 필요하다.
5. **merge_conflicts.csv 위치:** 체크리스트는 `extraction/merge_conflicts.csv`라고 쓰지만 나는 실행 폴더 안에 두었다(7장 11번). 체크리스트 문구를 바꿀지, 최신 실행본을 `extraction/`에 복사할지 정해야 한다.
6. `actionSteps`는 원본 응답과 jsonl에만 있고 KG에는 넣지 않았다(결정 #3대로).

## 10. 검토·입력 무결성 검사 (보완 요청 반영, `guard.py`)

RDF 출력과 검토 적용은 아래 검사를 모두 통과한 뒤에만 파일을 쓴다. 하나라도 틀리면 `ExtractError`로 멈추고 출력 파일을 하나도 쓰지 않는다(기존 출력의 내용·mtime도 그대로, 테스트 (i)). 멈춤 메시지에는 무엇이 달라졌는지와 기록 해시·현재 해시가 둘 다 들어간다.

### meta.json에 남기는 추출 때 입력 (run.prepare → run_calls)
- `input_fingerprint`: `kg_build/seed.ttl`, `kg_build/rules_deterministic.ttl`, `harness/preprocess_lock.json`, `preprocessed/documents/chunks.jsonl`의 경로와 SHA-256(**새로 추가**). prepare 끝에서 지문을 한 번 더 계산해, 준비 중에 파일이 바뀌었으면 멈춘다.
- 이미 있던 것: `preprocess_lock_sha256`, 입력 청크별 `text_sha256`·`source_file_sha256`(`input_chunks`), `prompt_sha256`(+ 템플릿·예시·스키마 해시).

### 입력 검사 `check_inputs` (1차 양식 생성, 2차 생성, apply, to_rdf. to_rdf는 쓰기 직전에 한 번 더)
1. B의 해시 사슬 검사(`preprocess_lock.check_chain`)를 다시 실행한다. 실패하면 "해시 사슬: …"으로 멈춘다.
2. 현재 seed.ttl, rules_deterministic.ttl, preprocess_lock.json, chunks.jsonl 해시가 `input_fingerprint`와 같아야 한다.
3. 청크 단위 검사(`inputs.chunk_errors`). 각 입력 청크의 현재 `text_sha256`과 SHA-256(text)이 meta 값과 같아야 한다.
4. 통과한 뒤에만 `load_current`가 현재 파일에서 문서·seed·B 규칙을 새로 읽는다. 호출자가 넘긴 ctx는 받지 않는다. 그래서 API가 `apply_review(run_dir, paths=None)`, `to_rdf.run(run_dir, out_dir=None, paths=None)`로 바뀌었다.

### 검토 파일 기록 `review_manifest.json`
- `write_round1`: merged.jsonl, merge_conflicts.csv, 1차 양식의 해시.
- `make_round2`: 그때의 1차 파일 해시(1차 확정)와 2차 양식 해시. 2차 생성을 두 번 할 수 없다.
- 2차 생성과 apply는 merged.jsonl·merge_conflicts.csv가 기록과 같은지 확인한다.
- **보완(검증자 지적, 2026-10-13):** manifest에 `run_id`와 `input_fingerprint_sha256`(meta.json 지문의 정규화 JSON 해시)을 넣어 이 실행에 묶었다. `guard.check_manifest`가 2차 생성·apply·to_rdf 때 manifest의 **모든** 해시를 대조한다.
  - 묶음 == meta.json.
  - 1차 양식 생성 때의 merged.jsonl·merge_conflicts.csv 해시 == 현재 파일.
  - 1차 양식 해시 == 현재 merged·conflicts로 다시 만든 양식의 해시.
  - 2차 생성 때의 1차 해시(1차 확정) == 현재 review_round1.csv.
  - 2차 양식 해시 == 현재 1차로 다시 만든 2차 양식의 해시.
  - 2차 고정 열 == 다시 만든 양식.
  - 2차 파일 유무 == 기록.
  다르면 항목 이름과 두 값을 적어 멈춘다.
- apply는 (1) 2차 생성 기록이 없으면 멈추고(**apply 전에 round2를 반드시 해야 한다**, 0행이어도), (2) 1차 파일이 2차 생성 때와 다르면 멈추고, (3) 2차 파일의 고정 열(final_* 밖)이 1차에서 다시 만든 양식과 다르면 멈춘다. 1차·2차 파일은 사람이 채우는 파일이라 생성 때 해시와는 원래 다르다. 그래서 1차는 "2차 생성 = 1차 확정" 시점의 해시로, 2차는 고정 열 대조로 확인한다.

### to_rdf 전 검토 기록 검사 `verify_review_record`
1. `review_applied.json`이 없으면 멈춘다.
2. final.jsonl, merged.jsonl, merge_conflicts.csv, review_round1.csv, review_round2.csv의 현재 해시가 기록과 같아야 한다. 2차 유무가 기록과 파일에서 다르면 멈춘다.
   - **applied와 manifest의 같은 항목도 대조한다:** merged.jsonl, merge_conflicts.csv, 1차(applied `round1.sha256` == manifest `round2.round1_sha256`). applied에 2차 기록이 없으면 멈춘다.
   - 그다음 위의 `check_manifest`(2차 필수)를 실행한다.
   - 검증자가 재현한 일관된 위조(1차 결정 accept→reject, final에서 그 레코드 삭제, applied 해시·집계 재계산, manifest 그대로)는 이 대조에서 멈춘다(테스트 (j)).
3. 1차·2차 CSV로 결정을 다시 계산해 final.jsonl의 후보 집합·결정이 같은지 확인한다. 각 레코드의 필드도 대조한다: 고치지 않은 필드는 merged.jsonl 값, 고친 필드는 CSV의 값이어야 한다. 그래서 final.jsonl을 고치고 해시까지 위조해도 멈춘다(테스트 (b)).
4. 기록의 `counts`·`decision_tally`가 final.jsonl·merged.jsonl로 다시 계산한 값과 같아야 한다(개수 위조 반례).

### 반례 테스트 (`tests/test_extract_guard.py`, 임시 사본, 17개 통과)
(a) review_applied.json 삭제(apply 전 포함) → to_rdf 멈춤, 출력 0개 · (b) final.jsonl responseText 변경 → 멈춤(두 해시 표시), 해시 위조 시 값 대조로 멈춤, counts 위조 → 멈춤 · (c) 1차 결정 변경: apply 후 → to_rdf 멈춤, apply 전 → apply 멈춤 · (d) 2차 결정 변경 → to_rdf 멈춤, 2차 파일 삭제 → 멈춤, apply 전 고정 열 변경 → apply 멈춤, round2 생성 기록 없음 → apply 멈춤 · (e) rules_deterministic.ttl의 responseText 한 트리플 변경 → apply·to_rdf 둘 다 멈춤, merged.jsonl 변경 → apply 멈춤 · (f) seed.ttl 변경 → apply·to_rdf·round2 멈춤 · (g) chunks.jsonl의 text_sha256 변경·청크 텍스트 변경 → 멈춤, preprocess_lock 변경 → apply·to_rdf 멈춤 · (h) 정상 경로 → 통과, 두 작업 공간의 출력 해시 동일, 합본 SHACL 적합 · (i) 멈출 때 기존 출력 3개의 내용·mtime 불변 · (j) 검증자 재현 일관된 위조 → to_rdf 멈춤, 기존 출력 내용·mtime 불변 · (k) manifest만 위조(1차 양식 해시, 1차 merged 해시, 1차 확정 해시, 2차 양식 해시, run_id, 지문 해시 6종) → to_rdf·apply 둘 다 멈춤, 기존 출력 불변 · meta·manifest 기록 확인.

### 한계
- **해시만으로는 막을 수 없는 위조가 남는다.** manifest, applied, meta, 대상 파일(CSV·jsonl)을 모두 서로 맞게 다시 쓰면 잡지 못한다. 기록과 파일이 같은 폴더에 있고 서명이 없기 때문이다. B의 preprocess_lock과 같은 한계다. 남는 방어선은 git·감사 로그(실행 폴더 보관, 검토 파일 변경 이력)다. `extraction/`은 git 무시 대상이라 지금은 git diff로 볼 수 없다. 실행 폴더를 별도로 보관하거나 manifest·applied 해시를 work_log 같은 추적 파일에 옮겨 적는 방법을 검토할 수 있다(미결).
- 1차 파일은 2차 생성 전까지 자유롭게 바뀔 수 있다(사람이 채우는 중이라서). 1차를 고정하는 시점은 2차 생성이다.
- 시점 차이(검사와 읽기 사이의 변경)는 to_rdf에서 쓰기 직전 재검사로 줄였지만 완전히 막지는 못한다.
- 프롬프트 해시는 meta에 기록만 하고, 검토·출력 시점에 현재 프롬프트와 대조하지 않는다(요청 목록에 없음. 출력은 저장된 응답에서 만들기 때문).

## 11. `--execute` 비용 승인 게이트 (`approval.py`, 사용자 승인 2026-10-13)

### 추정 기록 (`--dry-run`)
`extraction/approvals/<estimate_id>.json`(설정 상수 `EXTRACTION_APPROVALS`, `--approvals-dir`로 바꿀 수 있음)에 다음을 쓴다.
- 모델, 호출 수, 호출당 max_tokens(16,000), 출력 상한(호출 수 × max_tokens).
- 입력 토큰: `--count-tokens`이면 실측(`method: count_tokens`), 아니면 글자 수 추정(`method: chars_estimate`, 값 = 글자/4, 상한 = 글자/3). 어느 쪽인지 기록한다.
- 가격표: 코드 상수 `PRICE_TABLE`(claude-opus-5-5 입력 $4 / 출력 $20 per 1M)와 `PRICE_BASIS_DATE = "2026-10-06"`.
- 비용 범위: 입력만(출력 0), 입력 상한, 출력 최대, 합계 최대.
- 입력 지문: meta와 같은 `input_fingerprint`, 프롬프트 버전·해시, 예시 파일 해시, 스키마 해시, 선택 청크(ID, text_sha256) 목록.
- 생성 시각.
- `estimate_id` = 기록 내용(사용 기록 필드 제외)의 정규화 JSON SHA-256 앞 16자리. 전체 해시는 `content_sha256`에 둔다. 생성 시각이 들어가므로 dry-run마다 새 ID가 나온다.
- 이번 dry-run(기록은 scratchpad): estimate_id `ede87eadf28eb5ed`, 호출 60, 입력 130,157~173,543(글자 수 추정), 출력 상한 960,000, 비용은 입력만 $0.5206, 최대 $19.8942. 저장소의 `extraction/approvals/`는 만들지 않았다.

### 실행 (`--execute --approve <estimate_id>`)
순서대로 확인하고, 하나라도 틀리면 **클라이언트와 실행 폴더를 만들기 전에** 사유와 바뀐 값을 출력하고 코드 2로 끝낸다.
1. 예시가 CONFIRMED인지, `ANTHROPIC_API_KEY`가 있는지(기존 검사).
2. `--approve`가 있는지, ID 형식(16자리 16진수)이 맞는지, 기록 파일이 있는지.
3. 기록 내용 해시가 맞는지(기록을 고치면 거부).
4. 이미 쓴 승인이 아닌지(`used_by_run_id`가 있으면 거부).
5. 모델과 지문(입력 파일 4개 해시, 프롬프트·예시·스키마 해시, 청크 목록)이 현재와 같은지. 다르면 바뀐 키와 추정 때·현재 값을 적는다.
6. 현재 호출 수가 승인한 호출 수를 넘지 않는지.
- (12장에서 바뀜) 승인은 첫 API 호출 직전에 `reserved`가 되고, 실행 결과에 따라 used·unused(자동 복원)·usage_check_required가 된다. meta.json에는 `approval_id`와 `max_calls`를 남긴다.
- 호출은 `CallBudget`이 감싸서, 승인한 호출 수를 넘는 호출은 보내기 전에 막는다. `run_calls(max_calls=…)`는 요청 수가 상한보다 많으면 시작하지 않는다.
- (12장에서 바뀜) 실패한 실행의 승인 처리는 12장 상태 기계를 따른다(200 응답이 없으면 자동 복원).
- 예시를 확정하면 예시 해시가 바뀌므로, 확정 **뒤에** dry-run으로 추정 기록을 새로 만들어야 한다.

### 네트워크 차단(테스트)
- `--execute` 경로를 지나는 모든 테스트는 `anthropic.Anthropic`을 "부르면 실패하는" 목으로 바꾸고, `llm.AnthropicClient`는 FakeClient를 돌려주는 목으로 바꾼다. 초안 거부 테스트는 예시 파일 상태와 무관하게 초안 상태를 주입한다. 그래서 예시를 나중에 CONFIRMED로 바꿔도 테스트가 실제 호출을 시도하지 않는다.
- `NoRealClient` 테스트는 키를 지운 환경에서 가짜 전체 경로(실행·검토·RDF)와 dry-run, execute 거부를 돌리고 `anthropic.Anthropic` 호출이 0회인지 확인한다.
- 예시 파일 상태 테스트는 DRAFT 또는 CONFIRMED를 허용하도록 바꿨다(확정 뒤에도 깨지지 않게).

## 12. 오류 분류, 중단·재시도, 승인 상태 기계, 단일 청크 모드 (보완 2026-10-13)

### 오류 분류 (`llm.classify_exception`)
| 분류 | 대상(SDK 1.13.0) | 처리 |
|---|---|---|
| FATAL_AUTH | 401 AuthenticationError, 403 PermissionDeniedError, CredentialsError | 실행 전체 즉시 중단 |
| FATAL_BILLING | 402(전용 클래스 없음), error.type `billing_error`, 400 + 문구 `BILLING_400_PATTERNS`("credit balance", "billing", "credits", "payment"), 429 + 문구 `SPEND_429_PATTERNS`("spend limit", "usage limit", "spending limit", "credit", "billing") | 즉시 중단. 일치한 문구(`matched_pattern`)와 메시지를 기록 |
| FATAL_REQUEST | 404 NotFoundError, 위에 해당하지 않는 400·413·422(및 그 밖의 4xx) | 즉시 중단(모든 호출이 같은 이유로 실패) |
| TRANSIENT_RATE | 429(실제 속도 제한), 503 ServiceUnavailableError, 529 OverloadedError | 제한된 재시도 |
| TRANSIENT_EXHAUSTED | TRANSIENT_RATE 재시도 한도 소진 | 실행 중단 |
| AMBIGUOUS | APITimeoutError, APIConnectionError, 500 InternalServerError, 504 DeadlineExceededError(및 그 밖의 5xx) | **자동 재시도 없이 중단**, "사용량 확인 필요"(재시도하면 이중 과금 위험) |
| (HTTP 200) | stop_reason refusal·max_tokens 등 | 정상 완료(과금) 응답. 그 청크만 실패로 기록하고 계속 |

- 분류 순서: CredentialsError → APIConnectionError(타임아웃 포함) → 상태 코드(401·403 → 402·billing_error → 400 결제 문구 → 429 지출 문구 → 429·503·529 → 그 밖의 4xx → 5xx).
- 메시지에서 `sk-ant-…` 모양 문자열은 가리고(`[가림]`) 300자까지만 남긴다. 키는 기록하지 않는다.

### 중단·재시도 정책 (`llm.call_with_policy`, `run.run_calls`)
- 치명 분류(FATAL_*), TRANSIENT_EXHAUSTED, AMBIGUOUS가 처음 나오면 실행 전체를 중단한다. 뒤 청크는 부르지 않는다(테스트: 호출 수 1).
- 중단된 실행에 남기는 것: calls.jsonl, 원본 응답(실패 기록에는 분류·시도 목록), candidates_premerge.jsonl(완료 청크분), rejected.csv. meta에는 `status: aborted`, `outcome`(중단 분류·청크, 완료·미완료 청크), AMBIGUOUS이면 `usage_check`도 쓴다. 병합과 검토 양식은 만들지 않는다. 종료 코드는 3이다.
- TRANSIENT_RATE 재시도:
  - 청크당 최대 3회 시도(`MAX_ATTEMPTS_PER_CHUNK`), 실행당 최대 10회 재시도(`MAX_RETRIES_PER_RUN`).
  - 대기 시간은 `retry-after` 헤더가 있으면 그 값(상한 300초), 없으면 2·4·8…초 지수 대기(상한 60초).
  - 재시도마다 (청크, 시도 번호, 상태, retry-after, 대기 시간)을 meta `retries`에 남긴다.
  - 대기 함수는 주입식이라 테스트는 실제로 기다리지 않는다.
- **SDK 내부 재시도 끔:** `anthropic.Anthropic(max_retries=0, timeout=600.0)`. 모든 재시도는 위 정책만 한다. meta에 `sdk_client {max_retries: 0, timeout_s: 600}`와 `retry_policy`를 남긴다. 테스트는 생성자를 목으로 바꿔 이 인자로 한 번 불리는지 확인한다.

### 승인 상태 기계 (`approval.py`)
```
unused ──(첫 API 호출 직전 reserve)──▶ reserved ──┬─ HTTP 200이 1번이라도 ──────────────▶ used (부분 실행이면 partial_run)
  ▲                                               ├─ AMBIGUOUS가 있음 ─────────────────▶ usage_check_required
  └──── released (자동 복원) ◀────────────────────┘  200 없음 + FATAL_* / TRANSIENT_EXHAUSTED / 준비 오류
usage_check_required ──(Console 확인 뒤 resolve --as used|unused --note)──▶ used 또는 unused
```
- **예약:** `run_calls`가 첫 API 호출 직전에 `reserve`를 부른다. reserved·used·usage_check_required인 승인은 다른 실행이 쓸 수 없고, `--execute`가 상태를 적어 거부한다. 남의 예약은 `finalize`가 바꾸지 않는다.
- **자동 복원 조건:**
  - 실행이 FATAL_AUTH / FATAL_BILLING / FATAL_REQUEST / TRANSIENT_EXHAUSTED(또는 준비 오류)로 끝났다.
  - 그 실행에 HTTP 200 응답이 하나도 없다.
  - AMBIGUOUS가 없다.
  - 이 셋을 모두 만족하면 unused로 되돌리고, history에 `released`(사유, 시도별 청크·시도 번호·분류·상태)를 남긴다. 200 없이 끝난 일시 오류 재시도도 "생성 시작 안 함"으로 본다.
- **복원 안 함:** 200이 1번이라도 있으면 `used`이고, 중단된 실행이면 `partial_run`(완료·미완료 청크, 사유)을 남긴다. AMBIGUOUS가 있으면 `usage_check_required`이고 재사용할 수 없다.
- **해결:** 사람이 Console에서 사용량을 확인한 뒤 `python -m imaks_kg.extract.approval resolve <id> --as used|unused --note "..." [--approvals-dir DIR]`로 정한다. usage_check_required에서만 가능하고, `resolved` 사건으로 history에 남는다.
- 복원 뒤 다시 쓸 때도 `--execute`는 입력 지문·프롬프트·예시를 다시 검사한다(테스트).
- 상태·이력 필드는 내용 해시(`BODY_FIELDS`) 밖이라, 상태가 바뀌어도 기록 위조 검사와 충돌하지 않는다. 이전 형식 기록(`used_by_run_id`만 있음)은 used로 읽는다.

### 단일 청크 모드 (`--chunk <chunk_id>`, 여러 번 가능)
- `--dry-run`과 `--execute` 모두에서 선택 청크만 다룬다. 입력 청크가 아닌 ID(예: 데이터시트, SOP-002 표)는 사유를 적어 거부한다.
- 추정 기록·승인은 그 청크 묶음 기준이다(지문의 청크 목록, `chunk_filter`). 호출 상한도 청크 수와 같다. meta에도 `chunk_filter`가 남는다.
- 대표 청크: `SOP-001:p1:RULE-ST02-04`. 예시 출처 청크 3개(SOP-001:p1:RULE-ST01-02, SOP-004:p1:RULE-ACCESS-02, SOP-003:p1:table2:chunk)가 아니고, 원문 ID가 있는 SOP-001 규칙이다. 쪽 텍스트에 줄바꿈이 있어 좌표 검사도 함께 볼 수 있다.
- `--dry-run --chunk SOP-001:p1:RULE-ST02-04 --approvals-dir <scratchpad>/approvals_single` 결과(저장소 extraction/에는 쓰지 않음):

| 항목 | 값 |
|---|---|
| 모델 | claude-opus-5-5 |
| 호출 수 | 1 |
| 입력 글자 수 | 8,714 (system+예시 6,647 + 사용자 메시지 + 구조화 출력 스키마) |
| 입력 토큰 추정(글자 수 기준) | 2,179 (글자/4) ~ 2,905 (글자/3) |
| 출력 상한 | 16,000 |
| 비용 범위(USD, 입력 $4·출력 $20 /1M, 기준일 2026-10-06) | 입력만 $0.0087 ~ $0.0116, 출력 상한 포함 최대 $0.3316 |
| estimate_id | `82744d85b9a90bb6` (생성 시각이 해시에 들어가 다시 돌리면 바뀜) |

### 한계
- billing·지출 한도 문구는 상수 목록과의 부분 일치다. API 문구가 바뀌면 FATAL_REQUEST나 TRANSIENT_RATE로 분류될 수 있다. 일치한 문구를 기록에 남기므로 사후 확인은 할 수 있다.
- 실제 API 응답으로 분류를 확인한 적은 없다(가짜 예외만 사용).
- 중단된 실행을 이어서 하는 기능은 없다. 남은 청크는 `--chunk`로 새 추정·승인·실행을 해야 한다.

## 13. Gemini API 무료 등급 전환 (2026-10-13 사용자 결정)

기본 공급자는 `gemini`이다. Anthropic은 `--provider anthropic`을 줄 때만 쓴다. **공급자·모델·유료 등급으로 자동 전환하지 않는다.** 실패해도 다른 모델, 다른 공급자, 유료 키나 등급으로 바꾸지 않는다. `fallbacks`는 Anthropic 경로에만 있고 Gemini 경로에는 폴백이 없다. meta에는 `auto_switch: 없음`을 남긴다.

### 어댑터 구조
| 공급자에 따라 다른 것(어댑터) | 공급자와 무관한 것(그대로 재사용) |
|---|---|
| 요청 조립 `build_request`, 요청 글자 수 `request_chars` | 입력 선택·해시 사슬(inputs, guard), 프롬프트(prompt), 스키마·사후 검사(schema, validate) |
| 호출 클라이언트 `make_client` / 가짜 `make_fake_client` | 재시도 정책 `llm.call_with_policy`(분류 결과만 씀), `RetryBudget`, `wait_seconds` |
| 응답 해석 `interpret` → `CallResult` | 실행 `run.run_calls`(중단, 호출 간격, 예약 콜백), meta 공통부 |
| 예외 분류 `classify`, 잡을 예외 `sdk_errors` | 승인 상태 기계·호출 상한(approval: reserve·finalize·resolve·CallBudget) |
| 토큰 세기(Anthropic만 `--count-tokens`) | 병합(merge), 검토(review), RDF(to_rdf), 충돌(conflicts) |
| 키 확인 `key_problem`, 모델 확인 `model_problem`, 가격 `PRICE_TABLE[공급자]`, meta 항목 `meta()` | `--chunk`, 추정 기록 형식, 무결성 검사 |

- Anthropic 어댑터는 `llm.AnthropicAdapter`(기존 함수를 감쌈, 모델 `claude-opus-5-5` 고정)이다. Gemini 어댑터는 `llm_gemini.GeminiAdapter`이다. `run.get_adapter(provider, model)`만 공급자를 고른다.

### 키 처리 (`llm_gemini.load_key`)
- 환경변수 `GEMINI_API_KEY`가 있으면 그 값을 쓴다. 없으면 `settings.DOTENV_FILE`(저장소 루트 `.env`)에서 `GEMINI_API_KEY` 줄만 작은 파서로 읽는다(주석, `export`, 따옴표 처리, 새 의존성 없음). 그 값을 `genai.Client(api_key=...)`로 명시적으로 넘긴다.
- 환경에 `GOOGLE_API_KEY`가 있으면 멈춘다. SDK는 둘 다 있으면 GOOGLE_API_KEY를 우선하기 때문이다(`_api_client.py` get_env_api_key).
- 키가 없으면 클라이언트를 만들기 전에 `FATAL_AUTH`로 멈춘다. `--execute`는 그 전에 `refuse_execute_reason`에서 키가 있는지만 확인한다(값은 출력하지 않음).
- 키 값은 오류 메시지, meta, 로그, `repr(GeminiClient)`에 들어가지 않는다(테스트). 오류 메시지 안의 `AIza…` 모양 문자열은 가린다.
- 이번 작업에서 `.env`는 열거나 출력하거나 고치지 않았다. 테스트는 `DOTENV_FILE`을 임시 경로로 바꿔 저장소의 `.env`를 읽지 않는다.

### SDK 재시도 확인 (google-genai 2.30.0)
- `.venv/Lib/site-packages/google/genai/_api_client.py`:
  - `retry_args(options)`(581행): `options is None`이면 `{'stop': tenacity.stop_after_attempt(1), 'reraise': True}`, 즉 재시도하지 않는다.
  - `HttpRetryOptions`를 주면 기본 5회, `_RETRY_HTTP_STATUS_CODES`와 `_HTTPX_TRANSIENT_EXC`(111행: httpx/httpx2 TimeoutException, ConnectError)를 재시도한다.
  - 915행 `retry_kwargs = retry_args(self._http_options.retry_options)`.
- 그래서 `GeminiClient`는 `genai.Client(api_key=..., http_options=types.HttpOptions(timeout=600000))`만 쓰고 `retry_options`는 절대 넣지 않는다. meta에는 `sdk_client: {retry_options: "None (never retry)", timeout_ms: 600000}`를 남긴다. 테스트는 생성자를 목으로 바꿔 `retry_options is None`인지, `retry_args(None)`의 stop이 1회인지 확인한다.

### 요청 (`GeminiAdapter.build_request`)
- 호출: `client.models.generate_content(model, contents=사용자 메시지, config=GenerateContentConfig(system_instruction, temperature=0, response_mime_type="application/json", response_json_schema=…, max_output_tokens=8192, seed=20261012))`. 2.30.0에 있는 필드만 쓴다(`seed`, `thinking_config`, `response_json_schema` 확인함).
- temperature는 0이다(원래 지시 충족). `thinking_config`는 넣지 않아 모델 기본값을 쓰고, meta에 "미설정(모델 기본값)"으로 남긴다.
- 스키마: Gemini에 보내는 사본에서만 `type: ["string","null"]`을 `anyOf: [{type: string}, {type: null}]`로 바꾼다(ruleSeverity, ruleIdInText 두 곳). Gemini가 type 배열을 받는지 실제로 확인하지 못해 보수적으로 바꿨다. 바뀐 점은 meta `schema_changes_for_gemini`에 남는다. 사후 검사는 원래 스키마(pydantic)를 그대로 쓴다.
- 모델: 상수 `GEMINI_MODEL = None`(자리표시)이고 `--model`로 정한다. 정하지 않으면 실제 실행을 거부한다. dry-run·fake는 "미설정"으로 표시하고 진행한다. 승인 기록에는 모델이 들어가므로, 모델을 정한 뒤 dry-run을 다시 해야 한다.
- `--list-models`: `client.models.list()`(생성 없음)를 출력한다. 구현만 했고 실행하지 않았다.

### 응답 해석 (`llm_gemini.interpret`)
- 그 청크만 실패로 기록하고 실행은 계속한다. 이 경우들도 승인에서는 HTTP 200으로 센다:
  - `prompt_feedback.block_reason`이 있음.
  - 후보가 없음.
  - `finish_reason`이 STOP이 아님(SAFETY, MAX_TOKENS, RECITATION 등).
- 성공이면 첫 후보 parts의 text(`thought` part 제외)를 이어 `json.loads` 한다.
- 기록: `model_version`(served_model), `response_id`(request_id), `usage_metadata`의 prompt·candidates·thoughts·total 토큰 수, finish_reason. 원본은 `sdk_http_response`를 빼고 저장한다.

### Gemini 오류 분류 (`llm_gemini.classify`)
| 분류 | 조건(google.genai.errors.APIError: code, status, message, details) | 처리 |
|---|---|---|
| FATAL_AUTH | 401 UNAUTHENTICATED, 403 PERMISSION_DENIED, 400 + ErrorInfo.reason ∈ `API_KEY_REASONS`(API_KEY_INVALID 등) 또는 메시지 "API key not valid", 키 없음 | 즉시 중단 |
| FATAL_QUOTA | 429 RESOURCE_EXHAUSTED + QuotaFailure quotaId·quotaMetric에 PerDay(`DAILY_QUOTA_MARKERS`) 또는 quotaValue 0. QuotaFailure가 없으면 메시지 `FREE_TIER_MESSAGES`("limit: 0", "billing", "free tier" 등). 400 FAILED_PRECONDITION | 즉시 중단, "무료 등급 한도·할당 도달(유료로 바꾸지 않음)" |
| TRANSIENT_RATE | 429 중 QuotaFailure가 모두 PerMinute이거나 근거 없음, 503 UNAVAILABLE | 기존 제한 재시도(청크당 3회·실행당 10회), RetryInfo.retryDelay("37s")를 대기 시간으로 씀 |
| FATAL_REQUEST | 404 NOT_FOUND(모델), 400 INVALID_ARGUMENT(스키마 등), 그 밖의 4xx | 즉시 중단 |
| AMBIGUOUS | 500 INTERNAL, 504 DEADLINE_EXCEEDED, 그 밖의 5xx, 전송 오류(`httpx.TransportError`, `httpx2.TransportError`: 타임아웃·연결 포함) | 재시도 없이 중단, "사용량 확인 필요" |

- **판단 순서(내 선택):** QuotaFailure에 근거가 있으면 메시지 문구보다 먼저 본다. 무료 등급의 분당 한도 메시지에도 "free_tier" 같은 말이 들어가서, 메시지만 보면 분당 한도를 FATAL_QUOTA로 잘못 분류할 수 있기 때문이다.
- 근거(status, reason, quotaId, retryDelay)는 `matched_pattern`에 남긴다. 무료 등급이라 과금은 없지만 할당 소모 여부를 알 수 없으므로 AMBIGUOUS는 기존과 같이 처리한다(승인 `usage_check_required`).
- 테스트는 실제 오류 본문 모양의 dict로 `errors.ClientError(code, response_json)`, `ServerError`를 만들어 17가지 경우의 분류, 즉시 중단(호출 1회), retryDelay 대기, 503 재시도 소진을 확인한다.

### 무료 등급 호출 간격
- `--min-interval-s`의 기본값은 Gemini `DEFAULT_MIN_INTERVAL_S` = 7.5초(15장에서 6.0 → 7.5로 바꿈), Anthropic 0초다. 호출 사이(첫 호출 전 제외)에 대기하고, 재시도 대기와는 따로다.
- meta `min_interval_s`와 추정 기록 `pacing`에 남는다. 대기 함수는 주입식이라 테스트는 기다리지 않는다.

### 승인·비용
- 승인 기록과 상태 기계는 그대로 쓴다. 기록에 `provider`, `billing_tier`, `pacing`이 추가됐다. 공급자나 모델이 추정 때와 다르면 거부한다("자동 전환 없음").
- `PRICE_TABLE`은 공급자별이다. Anthropic `claude-opus-5-5`는 $4/$20, paid. Gemini는 `*` 0/0, `billing_tier: "free"`(기준일 2026-10-13)다. Gemini 비용 필드는 0이고, 대신 호출 수·입력/출력 토큰 추정·호출 간격을 기록한다. 유료 사용은 별도 결정이며 자동으로 바꾸지 않는다.
- `--count-tokens`는 Anthropic만 쓴다. Gemini는 구현하지 않았다고 출력하고 글자 수 추정을 쓴다.

### 대표 청크 dry-run (Gemini, 모델 미설정)
`--dry-run --provider gemini --chunk SOP-001:p1:RULE-ST02-04 --approvals-dir <scratchpad>/approvals_gemini`(저장소 extraction/에는 쓰지 않음):

| 항목 | 값 |
|---|---|
| 공급자·모델 | gemini, **미설정**(사용자가 정함) |
| 호출 수 | 1 |
| 입력 글자 수 | 8,691 |
| 입력 토큰 추정(글자 수 기준) | 2,173 (글자/4) ~ 2,897 (글자/3) |
| 출력 상한 | 8,192 |
| 비용 | 0 (billing_tier free) |
| 호출 간격 | 6.0초 |
| estimate_id | `a6ca0b3817afaa48` (모델을 정하면 다시 추정해야 함) |

### 사용자가 정할 모델 후보
무료 등급 대상 여부는 추측하지 않았다. 아래는 google-genai 2.30.0 패키지의 docstring과 예시 코드에 나오는 Gemini 모델 ID 문자열이다. 사용 가능 여부나 무료 등급 대상 여부를 보장하지 않는다. 사용자가 Google 문서(Gemini API 가격·한도 페이지)나 `--list-models`로 확인한 뒤 `--model`로 정한다.
- `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-2.5-pro`
- `gemini-3-flash-preview`, `gemini-3-pro-preview`, `gemini-3.1-flash-lite`, `gemini-3.1-pro-preview`, `gemini-3.5-flash`
- (이미지·TTS·라이브·컴퓨터 사용용 변형은 이 작업에 맞지 않아 뺐다.)

### 가짜 전체 경로 (Gemini)
- 가짜 Gemini 응답(GenerateContentResponse 형식, thought part 1개, block_reason 1개, SAFETY·MAX_TOKENS 각 1개 포함)으로 fake → validate → merge → 검토 → apply → to_rdf를 돌렸다. 결과: 호출 60, 실패 3, 폴백 0, 후보 31, 거부 8, B 병합 8, 새 규칙 23.
- 합본 SHACL(`run_shacl.py --ont`) **PASS**(3,699 트리플). 같은 경로가 `tests/test_extract_gemini.py`에도 있다.

### 한계
- 실제 Gemini 응답·오류로 확인한 적이 없다. 오류 본문의 details 구조, quotaId 이름, 스키마 지원 범위는 문서 지식에 기댄 가짜다.
- Gemini의 `seed`·`temperature=0`도 완전한 결정성을 보장하지 않는다.
- 호출 간격 6초는 추정값이다. 모델별 실제 분당 한도에 맞춰 사용자가 조정해야 한다.

## 14. 청크·시도 상한 분리, 이어서 하기, 외부 전송 허용 목록, 모델 (보완 2026-10-13)

### 청크 수와 API 시도 상한 분리 (충돌 수정)
- **문제였던 것:** `CallBudget`이 `max_calls`(= 승인 청크 수) 하나로 API 시도를 셌다. 청크 1개 실행에서 429가 한 번 나면 재시도가 막혔다.
- **수정:** 승인에 두 수를 둔다.
  - `approved_chunks`: 처리할 청크 수 상한.
  - `approved_attempts = min(청크 수 × MAX_ATTEMPTS_PER_CHUNK, 청크 수 + MAX_RETRIES_PER_RUN)`(`approval.attempt_cap`). 공식과 값이 추정 기록의 `attempt_cap_formula`에 들어간다. 예: 청크 1 → min(3, 11) = 3, 청크 60 → min(180, 70) = 70.
- `CallBudget(client, max_chunks, max_attempts)`는 새 청크가 승인 청크 수를 넘거나 시도가 상한을 넘으면 보내기 전에 막는다. `llm.call_with_policy`의 재시도는 두 곳 모두에 여유가 있어야 한다.
  - 재시도 예산(청크당 3회, 실행당 10회).
  - `CallBudget.has_retry_room()`: 재시도 1회를 더 해도 아직 시작하지 않은 승인 청크의 첫 시도 몫이 남는지.
  - 여유가 없으면 `TRANSIENT_EXHAUSTED("승인 API 시도 상한")`로 끝난다.
- 기록:
  - 추정 기록·승인 메시지·meta 모두 `approved_chunks`, `approved_attempts`를 남긴다. 추정·승인 출력은 "청크 N개, API 시도 최대 M회"이다.
  - 실행 meta는 `actual_chunks`(실제로 API를 부른 청크 수), `actual_attempts`, `chunk_attempts`(청크별 시도 이력: 번호·분류·상태·대기)를 남긴다.
  - 이전 형식 기록(`calls`만 있음)은 같은 공식으로 읽는다.
- 반례 테스트(`tests/test_extract_resume.py` Budget):
  - 청크 1개에서 429 뒤 200 → 성공, 시도 2·청크 1.
  - 429 3회 → TRANSIENT_EXHAUSTED, 200이 없어 승인이 unused로 복원.
  - 승인 청크 수를 넘는 청크 → 시작 전에 거부.
  - 시도 상한 1 → 재시도 없이 중단, meta 개수가 맞음.

### 이어서 하기 (`--resume-from <run_id>`, 여러 번 가능, `resume.py`)
- **재사용 대상:** 이전 실행의 성공 응답만이다(HTTP 200 + 정상 종료 + JSON 파싱 성공 + 그 청크에 거부 행 없음). 실패(거절·MAX_TOKENS·파싱 실패·거부 행이 있는 청크)는 재사용하지 않고 다시 부른다.
- **재사용 조건:** 하나라도 다르면 그 실행의 재사용을 거부하고 차이를 적어 멈춘다.
  - 공급자, 모델 ID.
  - served model(기록돼 있으면 요청 모델과 같거나 `<모델>-`로 시작해야 함).
  - `generation_settings_sha256`(요청에서 사용자 메시지만 뺀 것의 해시: temperature, seed, max_output_tokens, 보낸 스키마, system 포함. 이번에 meta에 새로 기록).
  - 프롬프트 해시, 예시 해시.
  - 입력 지문 전체(seed, B, lock, chunks.jsonl).
  - 재사용하는 각 청크의 text_sha256.
- 같은 청크의 성공 응답이 여러 실행에 있으면 멈춘다(청크마다 출처는 하나).
- **재사용 응답의 출처:** meta `reused_from[청크]`에 원래 run_id, request_id, 원본 응답 파일 경로, 원본 해시를 남긴다. 원본 응답은 새 실행 폴더 `raw/response/`로 복사하고 복사본 해시도 기록한다. calls.jsonl에는 `reused_from` 표시가 붙는다.
- **추정·승인은 남은 청크만:** `--dry-run --resume-from …`이 남은 청크 기준으로 추정 기록을 만든다. 승인 청크 수와 시도 상한도 남은 청크 기준이다.
- **합친 결과 검사:** 병합 뒤 `meta.combination_checks`에 다음을 남긴다.
  - 새 규칙 identifier 중복.
  - 같은 (chunk_id, 인용 위치) 중복.
  - 서로 다른 청크의 새 규칙이 같은 정규화 ruleIdInText를 가짐.
  - 이어서 하기 실행에서는 하나라도 있으면 병합·검토 양식을 만들지 않고 멈춘다. 일반 실행에서는 기록만 한다. 같은 청크 안에서 한 문장을 등급별 두 레코드로 나누는 것은 허용이다.
- 반례 테스트(Resume):
  - 중단된 실행의 성공분 + 나머지 → candidates·merged·rejected·merge_conflicts·final.jsonl 해시가 한 번에 돌린 결과와 같다.
  - 모델·공급자·프롬프트·예시·생성 설정·입력 지문·청크 해시가 바뀌면 거부한다.
  - 두 실행에 같은 청크가 있으면 멈춘다.
  - 실패 응답과 거부 행이 있는 청크는 재사용하지 않는다.
  - 합친 뒤 RULE-ST02-04가 두 청크에서 새 규칙이 되면 잡는다.
  - CLI dry-run이 남은 청크만 추정한다.

### 외부 전송 허용 목록 (Gemini 경로)
- `llm_gemini.OUTBOUND_DOCS = SOP-001~004`, `OUTBOUND_PATH_PREFIX = "imaks_data/rules/"`.
- `run.prepare`(Gemini)가 모든 요청 청크와 프롬프트 예시 출처 청크(`source_chunk_id`)를 확인한다. `run_calls`도 보내기 직전에 청크마다 다시 확인한다. 밖이면 보내지 않고 멈춘다.
- meta에 `outbound_allowlist`를 남긴다.
- 테스트:
  - 데이터시트 청크는 `--chunk`(입력 선택 단계)와 보내기 직전 단계 모두에서 거부되고, 가짜 클라이언트 호출은 0회다.
  - 데이터시트 예시를 넣은 프롬프트는 Gemini에서 거부된다.
- Anthropic 경로는 이전 동작 그대로다(지시 범위가 Gemini 경로).

### 모델
- `GEMINI_MODEL = "gemini-3.8-flash"`(사용자 지정. 프로젝트 models.list에서 generateContent 지원을 사용자가 확인함). `--model`로 바꿀 수 있다.
- 무료 등급 대상 여부는 첫 호출 전까지 모른다. FATAL_QUOTA(무료 할당 0 등)가 나면 실행을 멈추고 사용자가 다시 고른다. **자동 전환은 없다.** 13장의 "모델 미설정" 설명은 이 변경으로 바뀌었다(자리표시 None → 사용자 지정값).

### 대표 청크 dry-run (Gemini, gemini-3.8-flash)
`--dry-run --provider gemini --chunk SOP-001:p1:RULE-ST02-04 --approvals-dir <scratchpad>/approvals_gemini2`:

| 항목 | 값 |
|---|---|
| 모델 | gemini-3.8-flash (등급 free, 비용 0) |
| 청크 수 | 1 |
| API 시도 상한 | 3 (min(1×3, 1+10)) |
| 입력 토큰 추정(글자 8,691) | 2,173 ~ 2,897 |
| 출력 상한 | 8,192 |
| 호출 간격 | 6.0초 |
| estimate_id | `bfbdaa3f144fb6d8` |

## 15. served model 엄격 대조, 해시 장부, 호출 간격 7.5초 (보완 2026-10-13)

### served model 대조 (2차 검증 FAIL 수정, `resume._served_ok`)
- 이전: `startswith(f"{model}-")`로 접두어 일치를 허용했다. 그래서 요청 `gemini-3.8-flash`, served `gemini-3.8-flash-lite`인 응답이 재사용됐다.
- 수정: `re.fullmatch(rf"{re.escape(model)}(-\d{3})?", served)`. 요청 모델과 정확히 같거나 숫자 3자리 버전 접미사(예: `-001`)일 때만 허용한다. 공급자와 무관한 공통 함수라 Anthropic 경로에도 같다. served model이 비어 있으면 거부한다.
- 추가 대조:
  - 원본 응답에서 다시 읽은 served model이 원래 실행 `calls.jsonl`에 기록된 served model과 같아야 한다.
  - 재사용하는 응답들(여러 실행 포함)의 served model이 모두 같아야 한다.
- 테스트(`test_extract_resume.ServedModel`):
  - `-lite`, `-pro`, `-preview`, `-8b`, `-01`, `-0011`, `-001-lite`는 거부한다.
  - `-001`과 정확 일치는 허용한다.
  - 기록된 served model과 다르면 거부한다(장부가 먼저 잡고, 장부까지 고쳐도 이 대조가 잡음).
  - 실행 사이에 served model이 다르면 거부한다.

### git 추적 해시 장부 (`ledger.py`, `harness/extraction_ledger.jsonl`, `settings.EXTRACTION_LEDGER`)
2차 검증 FAIL (j)를 막으려고 만들었다. (j)는 1차 결정 변경 + final 레코드 삭제 + applied 재계산 + manifest `round1_sha256` 위조처럼 기록과 파일을 서로 맞게 바꾸는 위조다.
- **구조:** 추가만 하는 JSONL이다. 한 줄에 `seq`, `time`, `run_id`, `event`, `files`({파일 이름: SHA-256}), `prev_sha256`(바로 앞 줄 텍스트의 SHA-256, 첫 줄은 0×64)를 담고, 승인 사건이면 `estimate_id`, `state`도 담는다. 규칙 내용·인용·키 값은 넣지 않는다(테스트로 키 집합과 인용 부재 확인).
- **사건:**
  | 사건 | 기록하는 파일 |
  |---|---|
  | run_finished | meta.json, calls.jsonl, candidates_premerge.jsonl, rejected.csv, raw 응답 묶음 해시 |
  | merge_finished | merged.jsonl, merge_conflicts.csv |
  | round1_created | review_round1.csv(양식), review_manifest.json |
  | round2_created | review_round1.csv(1차 확정본), review_round2.csv(양식), review_manifest.json |
  | apply_finished | final.jsonl, review_applied.json, review_round1.csv·review_round2.csv(최종), review_manifest.json |
  | to_rdf_output | 출력 TTL 3개(이름 앞에 `out:`) |
  | approval_created / reserved / used / released / usage_check_required / resolved | 승인 기록 파일 전체 해시(state 포함) |
- **검사 지점(모두 출력 전):**
  - 2차 생성, apply, to_rdf(읽기 전과 쓰기 직전)에서 `verify_run`이 사슬 무결성을 보고, 그 run_id의 파일별 최근 기록이 현재 파일과 같은지 본다.
  - 사람이 채우는 파일은 양식 생성 기록 뒤에는 대조하지 않는다(review_round1.csv는 round1_created 뒤, review_round2.csv는 round2_created 뒤). 그 파일은 다음 단계에서 확정 해시가 기록된다.
  - 이어서 하기(`resume.collect`)는 이전 실행마다 같은 검사를 한다.
  - `check_approval`·`reserve`·`resolve`는 `verify_approval`로 확인한다: 장부의 마지막 승인 사건에서 다시 만든 상태가 파일의 state와 같고, 파일 해시가 마지막 기록과 같아야 한다. state 필드는 내용 해시 밖이므로 이 대조로 used → unused 수동 변경을 잡는다.
  - 장부가 없거나 그 run_id·estimate_id 기록이 없으면 멈춘다(장부 이전 실행·승인은 쓸 수 없음).
  - 기존 검사(입력 지문, manifest, applied)를 먼저 하고 장부 대조를 그 뒤에 한다. 그래서 기존 반례의 멈춤 메시지는 그대로이고, 기존 검사를 통과하는 일관된 위조는 장부가 잡는다.
- **임시 장부:** 테스트는 저장소 장부를 건드리지 않는다. `extract_support`가 프로세스 전체에 임시 장부를 두고, 실행 폴더를 복사하는 테스트는 장부도 함께 복사해 쓴다. 테스트 끝에 저장소 장부 해시가 바뀌지 않았는지 확인한다. CLI는 환경변수 `IMAKS_EXTRACTION_LEDGER`로 임시 장부를 쓸 수 있다. 이번 수동 확인은 모두 scratchpad 임시 장부로 했고, 저장소 장부는 빈 파일 그대로다(SHA-256 e3b0c442…).
- **반례 테스트(`tests/test_extract_ledger.py`, 7개 통과):**
  - (j) 위조: 장부 검사를 끄면 to_rdf가 통과해 버림을 먼저 보인다(검증자 재현). 켜면 review_round1.csv, final.jsonl, review_manifest.json 불일치로 멈추고 기존 출력 내용·mtime이 그대로다.
  - 중간 줄 삭제·수정 → 사슬 끊김으로 멈춘다.
  - 장부 없음 → 멈춘다. 실행 기록 없음 → to_rdf·apply 둘 다 멈춘다.
  - 승인 used → unused 수동 변경 → `check_approval`·`reserve` 거부.
  - 정상 경로 → 통과, 합본 SHACL 적합.
- **한계:** 장부까지 함께 고치고 커밋하면 잡지 못한다(테스트 `rerecord`가 이 경우를 흉내 냄). 마지막 줄만 고치거나 지우는 것도 사슬로는 드러나지 않는다. 남는 방어선은 git diff·이력 리뷰다. 장부 파일은 git 추적 대상이고 저장소에 빈 파일로 만들었지만, 커밋은 하지 않았다.

### Gemini 호출 간격 7.5초
- `llm_gemini.DEFAULT_MIN_INTERVAL_S = 7.5`(분당 8회 이하). meta `min_interval_s`와 추정 기록 `pacing.min_interval_s`에 남는다. 실제 한도는 첫 시험 호출에서 확인하고 조정한다.

### 대표 청크 dry-run (임시 승인 폴더·임시 장부)
`IMAKS_EXTRACTION_LEDGER=<scratchpad>/ledger_tmp.jsonl … --dry-run --provider gemini --chunk SOP-001:p1:RULE-ST02-04 --approvals-dir <scratchpad>/approvals_gemini3`:

| 항목 | 값 |
|---|---|
| 모델 | gemini-3.8-flash (free, 비용 0) |
| 청크 수 / API 시도 상한 | 1 / 3 |
| 입력 토큰 추정(글자 8,691) | 2,173 ~ 2,897 |
| 출력 상한 | 8,192 |
| 호출 간격 | 7.5초 |
| estimate_id | `8b71b89c4c9f4b2f` (임시 장부에 approval_created 기록) |

## 16. 직접 실행한 확인 (보완 후, 2026-10-13 재실행)

- `unittest discover -s tests`: **251개 전부 통과**(2026-10-13 최종, 약 7.4분). 저장소 장부는 빈 파일 그대로(테스트 전후 SHA-256 같음). Gemini 가짜 전체 경로 + 합본 SHACL PASS(3,699 트리플), 누수 점검 두 가지 PASS, 원본 불변 PASS.
- 가짜 응답 묶음에서 SDK 예외 2개(RateLimit, 연결)를 뺐다. 이제 SDK 예외는 실행 전체를 중단하기 때문이다. 오류 경로는 `test_extract_errors.py`가 따로 검사한다. 그래서 가짜 전체 실행의 수치가 바뀌었다(호출 실패 2, 거부 7).
- `check_leakage.py`(기본) PASS, `check_leakage.py preprocessed ontology_v1 kg_build src` PASS, `check_raw_unchanged.py` PASS(1,121개 파일).
- CLI 가짜 전체 경로(scratchpad): fake → validate → merge → 1차 전부 수락 → round2(0행) → apply → to_rdf → `run_shacl.py --data seed_plus_rules_llm.ttl --ont ontology_v1/ontology.ttl` **PASS**(3,699 트리플). 그 뒤 review_applied.json을 지우고 to_rdf를 돌리면 "검토 기록 review_applied.json가 없음"으로 멈추고 출력 폴더가 생기지 않는다.
- `--dry-run --approvals-dir <scratchpad>`: 호출 60, 입력 토큰 추정 약 130,157(상한 173,543), 추정 기록 생성.
- `--execute`(승인 없음, 예시 초안): "examples.json confirmationStatus가 'DRAFT…'"로 거부, 종료 코드 2.
- 저장소의 `extraction/`(approvals 포함)과 `kg_build/rules_llm*.ttl`은 만들지 않았다.
- 작업 중 실수: 코드 검사용으로 `.venv`에 pyflakes 4.0.3을 설치했다가(지시 없음) 바로 제거했다. 지금 `.venv` 패키지 구성은 작업 전과 같다.

verifier 검증 필요


## 17. 실행 전 보완 3건(2026-10-14)

사용자 코드 리뷰에서 나온 3건이다. 실제 API 호출은 0회다. 테스트는 `anthropic.Anthropic`·`genai.Client`를 목으로 바꿔 호출 0을 확인한다. CLI는 `--fake`와 `--dry-run`만 돌렸다. 저장소 장부 `harness/extraction_ledger.jsonl`은 0줄 그대로다. 테스트와 수동 확인은 모두 임시 장부·임시 승인 폴더·임시 잠금 폴더를 썼다. `examples.json`·확정 상태, ontology/shapes, work_log, 체크리스트, `.gitignore`는 바꾸지 않았다.

### 17-1. [P1] 호출 중 인터럽트 뒤 승인 재사용
- **원인:**
  - 호출 도중 KeyboardInterrupt가 나면 `outcome`이 갱신되기 전에 `finally`가 돈다.
  - `finalize`는 "200 없음 + AMBIGUOUS 없음"으로 보고 unused로 복원했다.
  - `run.py`는 ExtractError만 잡아서 BaseException 경로가 따로 없었다.
- **수정:**
  - 시도 단계 기록(journal) `실행 폴더/attempts.jsonl`을 만들었다. 덧붙이기 + flush + fsync로 남긴다.
    - `llm.call_with_policy`가 시도마다 `prepared`(네트워크 없음) → `sending`(클라이언트에 넘기기 직전) → `http_200_received`, `http_error_response`(서버의 HTTP 오류, 분류·상태 포함), `transport_error`(전송 오류·타임아웃), `local_error`(보내기 전 로컬 오류: 자격 증명 없음 등) 중 하나 → `interpreted` 또는 `interpret_failed` 순서로 적는다.
    - 승인 상한 검사(`CallBudget.precheck`)는 `sending` 전에 한다. 그래서 상한으로 막힌 시도는 "보내지 않음"으로 남는다.
  - 해석 중 예외가 나도 200은 잃지 않는다. `interpret_failed`를 적고, 그 청크만 `call_failed`("응답 해석 실패")가 된다. 승인은 used다.
  - `approval.decide(events)`가 승인 정리를 판정한다. **unused는 사용하지 않았음이 확실할 때만이다.**
    - 보낸 시도가 없음, 또는 보낸 시도가 모두 `http_error_response`/`local_error`로 끝났고 그 분류가 FATAL_*·TRANSIENT이며 200이 없음 → unused.
    - 200이 있음 → used.
    - 그 밖(`sending` 뒤 응답 기록 없음, 전송 오류·타임아웃, 5xx AMBIGUOUS, journal을 읽을 수 없음) → `usage_check_required`.
    - 불확실한 시도가 하나라도 있으면 200이 일부 있어도 `usage_check_required`가 우선한다. 끊긴 그 호출이 생성·할당을 소모했는지 모르기 때문이다. 이미 200을 받은 청크는 증거(`evidence.http_200_chunks`)로 남는다.
    - 보낸 시도가 모두 응답을 받은 뒤(예: 호출 간격 대기 중) 끊기면 used + `partial_run`(완료·미완료 청크)이다.
  - `run.main`의 실행부는 BaseException을 잡아 보수적으로 finalize(journal을 증거로 씀)한 뒤 다시 던진다. 실행 잠금은 finally에서 푼다.
  - **비정상 종료:** `--execute`는 실행 내내 실행 잠금(`approval_<id>.run.lock`)을 쥔다. 다음 `check_approval`이 reserved인 승인을 보고 실행 잠금을 잡을 수 있으면(쥔 프로세스가 죽음) `recover_if_abandoned`가 `usage_check_required`로 옮긴다. 이때 예약 때 기록한 journal 경로의 요약을 증거로 남긴다. unused로는 절대 되돌리지 않는다. 실행 잠금을 쥔 프로세스가 살아 있으면 바꾸지 않고 "다른 실행이 예약 중"으로 거부한다.
  - `usage_check_required` 승인은 `resolve` 전까지 `--execute`가 거부한다(이전과 같음).
- **테스트(`tests/test_extract_safety.py` Interrupts, 가짜 호출):**
  - 준비 오류(요청 파일 쓰기 실패) → unused.
  - 첫 호출 중 KeyboardInterrupt → usage_check_required. journal은 prepared·sending으로 끝나고, 재실행은 거부된다.
  - 200 뒤 해석 예외 → used, 청크 실패 기록.
  - 앞 청크 성공 뒤 보내는 중 끊김 → usage_check_required(위 우선순위, 200 받은 청크 기록).
  - 앞 청크 성공 뒤 대기 중 끊김 → used + 부분 실행.
  - 서버 오류만(401) → unused.
  - 타임아웃·500 → usage_check_required.
  - journal을 읽을 수 없음 → usage_check_required.
  - 죽은 예약 → 다음 실행이 usage_check_required로 옮김(Processes, 실제 프로세스).
- **남은 한계:**
  - fsync를 해도 저장 장치나 OS 수준의 쓰기 손실까지는 막지 못한다.
  - journal 자체가 지워지면 `decide`는 "보낸 시도 없음"으로 본다. 다만 비정상 종료 복구는 journal과 무관하게 항상 usage_check_required다.
  - finalize 자체가 실패하면(예: 잠금 시간 초과) 승인은 reserved로 남고, 다음 검사가 usage_check_required로 옮긴다(닫힌 쪽).

### 17-2. [P1] 같은 승인의 동시 예약, 장부 동시 쓰기
- **원인:** 상태 확인과 예약 쓰기 사이에 프로세스 사이 잠금이 없었다. 장부 덧붙이기도 읽기와 쓰기 사이가 열려 있어 seq·prev가 겹칠 수 있었다.
- **수정:**
  - `locks.py`를 새로 만들었다(Windows `msvcrt.locking`, POSIX `fcntl.flock`).
    - 잠금 파일은 `settings.EXTRACTION_LOCKS = extraction/.locks/`이다. `/extraction/`이 이미 git 무시 대상이라 **.gitignore 변경은 필요 없다**(`git check-ignore`로 확인).
    - 시간 제한(기본 10초)이 있고, 넘으면 "잠금을 얻지 못함(…): 다른 프로세스가 쓰는 중"으로 멈춘다. 핸들이 닫히면 OS가 풀므로 프로세스가 죽어도 남지 않는다.
    - 테스트·CLI는 `LOCK_DIR_OVERRIDE`·`IMAKS_EXTRACTION_LOCKS`로 위치를 바꾼다.
  - **잠금 순서는 승인 잠금 → 장부 잠금이다.** `ledger.append`는 장부 잠금만 잡는다(장부 경로별 잠금 파일). 실행 잠금은 다른 쪽이 기다리지 않고(timeout 0) 시도만 하므로 교착이 생기지 않는다.
  - `ledger.append`(장부 잠금 안): 읽기 → 사슬 검사 → seq·prev_sha256 계산 → 덧붙이기 → flush·fsync.
  - `approval.reserve`(승인 잠금 안): 다시 읽기 → 장부 검사(`verify_approval`) → 상태 확인 → **장부에 reserved를 먼저 기록(fsync)** → 승인 파일을 원자적으로 교체(임시 파일 + fsync + `os.replace`). `finalize`·`resolve`·`write_estimate`·비정상 종료 복구도 같은 순서(`_commit`)다.
    - 장부 기록 뒤 파일 쓰기가 실패하면 장부는 reserved, 파일은 unused로 어긋난다. `verify_approval`이 이를 거부하므로 **닫힌 쪽으로 실패한다**(추가 호출 없음).
  - `--execute`는 검사(`check_approval`)를 통과한 뒤 실행 잠금을 잡는다. 못 잡으면 클라이언트를 만들기 전에 거부한다.
- **테스트(실제 자식 프로세스 `tests/extract_proc_helper.py`, 시작 파일로 동기화):**
  - 4개 프로세스가 같은 승인을 동시에 reserve → 정확히 1개 성공, 3개 거부. 장부·파일이 일치한다.
  - 4개 프로세스가 각 15줄을 동시에 장부에 덧붙임 → seq 1..60 연속, prev_sha256 사슬 유효.
  - 실행 잠금을 쥐고 reserved + sending 상태에서 강제 종료(kill) → 살아 있는 동안 검사는 "reserved"로 거부, 죽은 뒤 검사는 usage_check_required로 옮김. 잠금도 다시 잡힌다.
  - 2개 프로세스가 실제 `run_calls`(예약은 첫 호출 직전)로 경쟁 → (성공, 가짜 호출 1)·(실패, 가짜 호출 0).
  - 장부 기록과 파일 쓰기 사이 실패를 흉내 냄(프로세스 안) → `check_approval`·`reserve` 거부.
  - 잠금 시간 초과 메시지가 0.2초 안에 나온다.
  - 실제 프로세스 테스트 6개 중 5개가 자식 프로세스를 쓰고, 전체가 몇 초 안에 끝난다(긴 대기 없음).
- **남은 한계:**
  - 네트워크 파일 시스템에서는 잠금 동작을 보장하지 않는다.
  - 잠금 파일 폴더를 지우거나 다른 경로를 쓰는 프로세스와는 서로를 막지 못한다(같은 `IMAKS_EXTRACTION_LOCKS`를 써야 함).
  - 장부와 파일 사이 실패는 "거부"로 닫힐 뿐 자동으로 고쳐지지 않는다. 사람이 원인을 보고 새 추정·승인을 만들어야 한다.

### 17-3. [P2] 재시도에도 최소 호출 간격
- **원인:** 청크 사이에만 `sleep(interval)`을 했고, 같은 청크의 재시도는 backoff(2초)만 기다렸다(`[2.0]`).
- **수정:**
  - 실행당 `llm.Pacer` 하나(단조 시계·sleep 주입식)가 마지막 API 시도 시작 시각을 기억한다.
  - 모든 시도 전에 `max(0, min_interval − 경과)`를 기다린다. 재시도는 `max(min_interval − 경과, backoff, retry_after)`를 **한 번만** 잔다(이중 대기 없음).
  - 재시도 직후의 다음 청크도 마지막 시도 기준으로 간격을 지킨다.
  - 실제로 잔 시간은 `meta.pacing_waits_s`와 재시도 기록 `wait_s`에 남는다.
  - 청크 수·시도 상한·재시도 예산은 그대로다.
  - `run_calls`·`call_with_policy`의 sleep·clock은 기본값을 실행 때 찾는다(테스트가 바꿀 수 있게).
- **테스트(Pacing, 가짜 시계·sleep, 실제 대기 없음):**
  - 청크 사이 [7.5, 7.5].
  - 같은 청크 재시도 [7.5](2초가 아님).
  - retry_after 3 → 7.5, retry_after 20 → 20.
  - 재시도(20) 직후 다음 청크 → [20, 7.5].
  - 승인 청크 2·시도 상한 6, 실제 청크 2·시도 3, 재시도 기록 1건(wait_s 20)으로 바뀌지 않았다.
  - 기존 Gemini 간격 테스트도 가짜 시계로 바꿨다.
- **남은 한계:** 간격은 이 프로세스 안에서만 지킨다. 같은 키로 여러 프로세스를 동시에 돌리면 합친 속도는 제한하지 않는다(실행 잠금이 같은 승인의 동시 실행은 막는다).

### 확인 결과(2026-10-14)
- `unittest discover -s tests`: **269개 전부 통과**(약 7.9분). 새 테스트 `tests/test_extract_safety.py` 18개(실제 프로세스 6개 포함)다.
- `check_leakage.py` 기본 폴더 PASS. `check_leakage.py preprocessed ontology_v1 kg_build src harness/extraction_ledger.jsonl` PASS. `check_raw_unchanged.py` PASS(1,121개 파일).
- Gemini 가짜 전체 경로(임시 장부·임시 잠금): fake → validate → merge → 검토 → apply → to_rdf, 합본 SHACL **PASS**(3,699 트리플). `attempts.jsonl`에 prepared → sending → http_200_received 순서가 남는다.
- 실제 API 호출 0회. 저장소 장부는 0줄이다.
- 작업 중 실수: 잠금 폴더 덮어쓰기를 테스트 공용 설정에 넣기 전에 테스트를 한 번 돌려서, 저장소에 `extraction/.locks/`(빈 잠금 파일 73개, git 무시 대상)가 생겼다. 지웠고, 덮어쓰기를 넣은 뒤로는 생기지 않음을 확인했다.

verifier 검증 필요


## 18. 실행 전 보완 검증 PARTIAL 후속 (2026-10-14)

`reports/extract_verify.md` "실행 전 보완 3건 검증"의 FAIL 2건과 관찰 2건이다. 실제 API 호출은 0회다. 저장소 장부는 0줄이고, 테스트는 임시 잠금·장부·승인 폴더를 쓴다.

### FAIL 1. 끊긴 실행의 partial_run 완료·미완료가 비어 있음
- **원인:**
  - `run_calls`는 `outcome["not_completed"]`를 중단(abort) 분기에서만 채웠다. 그래서 인터럽트로 끝나면 `partial_run.not_completed`가 `[]`였다.
  - 해석 중에 끊기면 그 청크의 200이 `outcome["completed"]`에 들어가기 전이라 완료 목록도 비었다.
- **수정:**
  - `run_calls`가 시작할 때 `not_completed = 부를 청크 전부`로 두고, 청크가 200을 받을 때마다 `completed`에 넣고 `not_completed`에서 뺀다(청크 전환마다 갱신).
  - 더 믿을 근거로, `approval.finalize`가 완료·미완료를 다시 계산한다. 완료는 시도 기록(`attempts.jsonl`)과 메모리에서 `http_200_received`를 받은 청크다. 미완료는 승인 기록의 청크 목록(`fingerprint.chunks`, 승인 순서)에서 완료를 뺀 것이다.
  - 미완료가 있으면 `partial`로 표시한다.
- **테스트(`tests/test_extract_safety2.py` PartialInfo):**
  - 청크 3개 중 1개 완료 뒤 간격 대기 중 끊김 → used, 완료 [1], 미완료 [2, 3].
  - 두 번째 청크 200 뒤 해석 중 끊김 → used, 완료 [1, 2], 미완료 [3]. 두 청크의 원본 본문이 해석 전에 저장됐다.
  - 두 번째 청크를 보내는 중 끊김 → usage_check_required, 완료 [1], 미완료 [2, 3].
  - `run_calls`의 outcome 목록이 끊긴 시점에도 맞다.

### FAIL 2. journal 없는 정리가 AMBIGUOUS도 unused로 되돌림
- **원인:**
  - (i) `_legacy_events`가 `phase`가 있는 시도에 `sending`을 넣지 않았다. 그래서 `finalize(journal=None)`에서 AMBIGUOUS(500) 시도가 "보내지 않음"으로 보였다.
  - (ii) journal 경로는 주어졌는데 파일이 없으면 메모리 outcome을 무시하고 unused로 판정했다.
- **수정(`approval.judge`):** 증거 두 가지(journal 파일, 메모리 outcome)를 모두 보고, 더 보수적인 쪽을 쓴다. 순서는 usage_check_required > used > unused다.
  - 이전 형식 변환: 단계나 상태가 있는 모든 시도를 `sending`으로 넣는다.
  - journal을 읽을 수 없음 → usage_check_required.
  - journal이 없음(경로 없음·파일 없음):
    - 메모리 outcome이 있으면 그 판정을 쓴다. 보낸 시도 0·200 0일 때만 unused다.
    - 메모리 outcome도 없으면 증거가 없으므로 usage_check_required.
  - journal이 있음: journal 판정과 메모리 판정 중 보수적인 쪽을 쓴다. 보낸 시도 수나 200 청크가 서로 다르면 그 사실을 `evidence.notes`에 남긴다.
  - 결과적으로 unused는 적어도 한 증거가 "보낸 시도 없음" 또는 "모두 서버 오류 응답"을 확인하고, 어느 증거도 반대하지 않을 때만 나온다.
  - unused로 되돌리는 경로 점검:
    - `finalize` → `judge`·`decide`만 거친다.
    - `recover_if_abandoned` → 항상 usage_check_required.
    - `resolve --as unused` → 사람이 Console을 확인한 뒤의 명시적 결정.
    - 그 밖에 unused로 쓰는 곳은 없다.
- **테스트(Evidence):**
  - `finalize(journal=None)` + 500 AMBIGUOUS → usage_check_required.
  - journal 파일 없음 + 메모리에 보낸 시도 → usage_check_required.
  - journal 파일 없음 + 메모리 시도 0 → unused.
  - outcome도 없음 → usage_check_required.
  - journal(401만) vs 메모리(200) → used, 불일치가 기록됨.
  - journal(보내는 중) vs 메모리(없음) → usage_check_required.
  - 이전 형식 변환이 `sending`을 넣는다.

### 관찰 1. 해석에 실패한 200의 원본 본문을 저장하지 않음
- **수정:**
  - `llm.call_with_policy`가 200을 받으면 해석 **전에** `adapter.raw_dump(response)`로 원본을 만들어 `save_raw`에 넘긴다.
  - `run_calls`가 `raw/response/<청크>.json`에 저장하고, journal에 `raw_saved`(파일 상대 경로, SHA-256)를 남긴다.
  - 성공 응답도 같은 방식으로 저장하고, 같은 내용을 다시 쓰지 않는다. 기존 재사용·장부의 원본 해시는 그대로다(이어서 하기 테스트 통과).
  - 해석 실패 결과는 `raw`에 그 본문을 담는다.
- **테스트:** 해석기가 항상 실패해도 청크 3개 모두 `raw_saved`가 있고, 파일 해시가 journal과 같으며, 원본 본문(`content`)이 들어 있다.

### 관찰 2. 장부·승인 파일 불일치인데 "다른 실행이 예약 중"으로 거부
- **수정:** `check_approval`과 `reserve`가 장부 불일치를 보면 `ledger_mismatch_message`로 원인을 적는다.
  - 형식: "해시 장부와 승인 파일이 어긋남: 장부의 기대 상태 X / 파일의 상태 Y. 이 승인은 쓸 수 없다(파일 쓰기 실패나 수동 수정 가능성). --dry-run으로 새 추정을 만들고 다시 승인받는다. 세부: …"
  - 이 경우 상태 기반 메시지("다른 실행이 예약 중")는 붙이지 않는다.
- **테스트:** 장부 기록 뒤 파일 쓰기 실패를 흉내 낸다. 메시지에 "장부의 기대 상태 reserved", "파일의 상태 unused", "새 추정"이 있고 "다른 실행이 예약 중"은 없다.

### 확인 결과
- `unittest discover -s tests`: **281개 전부 통과**(약 8.1분). 새 테스트 `tests/test_extract_safety2.py` 12개다.
- `check_leakage.py` 기본 폴더 PASS. `check_leakage.py preprocessed ontology_v1 kg_build src harness/extraction_ledger.jsonl` PASS. `check_raw_unchanged.py` PASS(1,121개 파일).
- Gemini 가짜 전체 경로(임시 장부·잠금)와 합본 SHACL **PASS**(3,699 트리플). `attempts.jsonl`에 `raw_saved` 60건이 남는다.
- 실제 API 호출 0회. 저장소 장부 0줄. 저장소에 `extraction/`이 생기지 않았다.

### 남은 한계
- 해석 중 BaseException으로 끊기면 그 청크의 결과는 계산되지 않는다. 원본 본문은 저장돼 있으므로, 이어서 하기는 이 청크를 다시 부른다(실패 응답으로 보고 재사용하지 않음). 원본을 다시 해석하는 기능은 없다.
- journal과 메모리 기록이 서로 다른 이유는 기록만 하고 자동으로 따지지 않는다.

verifier 검증 필요
