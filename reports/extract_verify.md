# ④ LLM 추출([C]) 검증 보고서

**2차 검증(Gemini 전환·보완 후, 2026-10-13)**

**보완 확인(2026-10-14)**: 2차 검증의 FAIL 2개와 새 해시 장부를 다시 확인했다. 결과는 맨 끝 "## 2차 검증 보완 확인 (2026-10-14)" 절에 덧붙였다. 아래 1~14장은 2차 검증 당시 그대로다.

**실행 전 보완 3건 검증(2026-10-14)**: 구현 보고서 17장의 보완 3건(인터럽트·승인 상태, 동시성, 최소 호출 간격)과 회귀를 다시 확인했다. 판정은 PARTIAL이다(FAIL 2: 대기 중 끊김의 미완료 청크 목록이 빔, journal 없는 finalize 경로의 unused 복원). 안전 동작·동시성·간격·회귀는 모두 PASS다. 결과는 맨 끝 "## 실행 전 보완 3건 검증 (2026-10-14)" 절에 덧붙였다. 앞의 판정과 기록은 그대로다.

이 보고서는 1차 검증 보고서를 덮어쓴다. 작성자는 verifier(독립 검증)다.

**지킨 원칙**
- 실제 API는 호출하지 않았다. `generate_content`, `count_tokens`, `models.list`, `--execute`(실제 클라이언트), `--list-models` 모두 해당한다.
- 내 검사 스크립트는 모두 `netblock.py`를 먼저 불러온다. 이 파일은 다음을 막고 횟수를 센다.
  - `socket.connect`와 `create_connection`
  - `genai.Client`와 `anthropic.Anthropic` 생성(부르면 실패하게 바꿈)
- 모든 실행에서 세 횟수는 0이었다(`{'genai.Client': 0, 'anthropic.Anthropic': 0, 'socket': 0}`).
- `--execute` 경로는 가짜 `genai.Client`로만 돌렸다. 키는 임시 `.env`에 넣은 가짜 키 하나다.
- 다음은 열지 않았다: `imaks_data/kg_seed/ground_truth.csv`, `data/`, `evaluation/`, `imaks_data/human/`.
- 저장소 `.env`는 열거나 출력하지 않았다. 확인한 것은 두 가지뿐이다.
  - 파일이 있는지(`ls`)
  - git이 무시하는지(`git check-ignore`)
- 전체 테스트를 다시 돌릴 때 저장소 `.env` 읽기를 감시했다. 읽은 횟수는 0이다.
- `reports/extract_impl.md` 10~15장은 무엇을 확인할지 찾는 데만 썼다. 판정은 모두 내가 직접 돌린 명령과 계산에 근거한다.
- 스크립트와 가짜 실행 산출물은 모두 저장소 밖에 두었다. 위치는 세션 scratchpad `…/scratchpad/v2/`이고 아래에서 `$S`라고 쓴다.
  - 스크립트: `$S/scripts/`
    - 공통 도구: `netblock.py`, `cli.py`, `ws.py`, `exec_harness.py`
    - 항목 검사: `c1_items.py`, `c2_guard.py`, `c3_exec.py`, `c3b_exec.py`, `c5_errors.py`, `c5_sdk.py`, `c5_anth.py`, `c6_resume.py`, `c6b_dup.py`, `ut_blocked.py`
  - 저장소에 `extraction/`과 `kg_build/rules_llm*.ttl`은 생기지 않았다(작업 끝에 다시 확인).
- 실행 환경: `.venv/Scripts/python.exe`, `PYTHONPATH=src`, `PYTHONIOENCODING=utf-8`.

---

## 판정: **PARTIAL**

> **보완 후 판정(2026-10-14): PASS.** 위 PARTIAL은 2차 검증(2026-10-13) 당시의 원래 판정이라 그대로 둔다. FAIL 2개((j) 일관된 위조, served model 앞부분 일치)는 해시 장부와 `_served_ok` 정확 대조로 해소됐다. 근거는 맨 끝 "2차 검증 보완 확인 (2026-10-14)" 절에 있다. 남은 한계(장부까지 함께 다시 기록하면 통과)는 판정 밖 관찰로 적었다.

**체크리스트**
- `harness/checklist.md`의 공통 5개와 ④ LLM 추출 14개, 모두 19개가 **전부 PASS**다.
- 근거는 Gemini 가짜 전체 경로를 CLI로 끝까지 돌려 나온 RDF다.

**추가 확인 10개**
- 8개는 모든 하위 항목이 통과했다.
- 2개에서 FAIL 하위 항목이 하나씩 나왔다.
  1. **추가 확인 2(무결성).** applied와 manifest를 서로 맞게 위조하면 막지 못한다. 위조 내용은 다음과 같다.
     - 1차 결정을 바꾼다.
     - final.jsonl에서 그 레코드를 지운다.
     - `review_applied.json`의 해시·집계와 `review_manifest.json`의 1차 확정 해시를 다시 계산한다.

     이 위조는 to_rdf를 통과했고 기존 출력 3개가 덮어써졌다. 구현 보고서 10장 "한계"가 이미 인정한 구조적 한계다. 하지만 이번 검증 기준은 "멈춰야 한다"라서 FAIL로 둔다.
  2. **추가 확인 6(이어서 하기).** served model 비교가 앞부분 일치(`<모델>-`) 규칙이다. 그래서 요청 모델 `gemini-3.8-flash`에 대해 `gemini-3.8-flash-lite`가 응답한 기록도 같은 모델로 보고 재사용한다(`resume.py` 39~40행 `_served_ok`).

**체크리스트 밖의 관찰** (판정에 넣지 않음, 7장)
- 승인 기록의 `state` 필드는 내용 해시 밖에 있다. 그래서 used를 unused로 손으로 고치면 승인을 다시 쓸 수 있다.
- QuotaFailure 정보가 없는 429는 메시지에 "free_tier"가 있으면 FATAL_QUOTA로 분류된다(보수적으로 멈추는 쪽).

---

## 1. 항목별 결과 (체크리스트)

판정에 쓴 RDF는 CLI 가짜 전체 경로에서 나왔다. 순서는 다음과 같다.

1. `tests/extract_fakes.py $S/fake_gemini gemini`로 가짜 응답 60개를 만든다.
2. `run --fake … --provider gemini --run-id g1 --out-root $S/runs`
   - 결과: `{"calls": 60, "calls_failed": 3, "fallback_served": 0, "candidates": 31, "rejected": 8, "retries": 0, "reused": 0, "api_chunks": 60, "merged_into_b": 8, "new_rules": 23, "merge_conflicts": 2}`
3. 1차 검토를 모두 accept로 채운다.
4. `review round2`: 0행이다.
5. `review apply`: `kept 31`.
6. `to_rdf --out-dir $S/out_g1`: rules_llm 533 트리플, 합본 3,699 트리플.
7. `run_shacl.py --data $S/out_g1/seed_plus_rules_llm.ttl --ont ontology_v1/ontology.ttl`: `Conforms: True`, exit 0.

### 공통

| 항목 | 결과 | 근거 |
|---|---|---|
| `check_raw_unchanged.py` PASS | PASS | 시작 때와 끝(전체 테스트 2회와 모든 가짜 실행 뒤) 두 번 실행. 둘 다 `PASS: imaks_data/ 원본 불변 (1121개 파일)`, exit 0 |
| `check_leakage.py` PASS | PASS | 기본 폴더 실행과 `preprocessed ontology_v1 kg_build src` 실행 모두 `검사한 파일 59개 … PASS: 금지 컬럼 없음`, exit 0 |
| 코드에 절대 경로 없음 | PASS | `grep -rnE 'C:\\\\|C:/|[A-Z]:\\|/Users/|/home/' src tests`의 결과는 `tests/test_extract_e2e.py:191` 1건이다. 이 줄은 절대 경로를 찾는 검사용 정규식이다. 경로는 `settings.py`의 `REPO_ROOT = Path(__file__)…`에서 계산하고, `.env` 위치도 `DOTENV_FILE = REPO_ROOT / ".env"`(61행)로 정한다 |
| 큰 산출물·원본이 git 추적 대상 아님 | PASS | `git ls-files \| grep -E '^(extraction\|kg_build\|preprocessed\|evaluation\|imaks_data\|data)/\|\.env$'` 결과 0줄. `git status --ignored`: `!! .env, data/, evaluation/, imaks_data/, kg_build/, preprocessed/` |
| 이상값 삭제·보간·평활화 코드 없음 | PASS | `grep -rnE 'interpolat\|dropna\|fillna\|rolling\|smooth\|savgol\|ewm\(\|\.drop\(' src` 결과 0건(exit 1). C는 시계열을 다루지 않는다 |

### ④ LLM 추출

| 항목 | 결과 | 근거 |
|---|---|---|
| 프롬프트가 Role/Task/Example 3단 | PASS | `system.md`의 `# ` 제목: `['# Role', '# Task', '# Example']`(c1_items). 저장된 요청 60개의 `system_instruction`은 한 종류뿐이다. 그 SHA-256이 meta `prompt_sha256` `12c2bcef2ca99a0f…`와 같다 |
| 모든 트리플에 문서 ID·페이지·문자 위치·원문 해시 | PASS | `rules_llm.ttl`의 LLM Provenance는 31개이고 final도 31건이다. 모든 Provenance에 다음이 있다: page(청크 쪽과 같음), sourceQuote(청크 원문 안), textSha256(=SHA-256(quote)), extractionMethod "llm". 위치는 두 종류다. 본문·규칙 17개는 charStart/charEnd이고, 다시 계산한 결과 `pages.jsonl[text_normalized][s:e]`(rule 청크는 줄바꿈을 공백으로)가 인용과 같다. 표 14개는 tableId/rowIndex/colIndex/bbox이고, 다시 계산한 bbox(셀 bbox의 합)와 같다. 문서 ID는 Provenance가 붙은 Rule의 `sourceDocument`에서 나온다. 병합된 건은 B 규칙의 sourceDocument를 썼다. 31개 모두 청크의 doc_id와 같다. 문제 목록은 `[]`이다 |
| 데이터시트 vs SOP-002 충돌을 출처와 함께 둘 다 기록 | PASS | `conflicts --out $S/conflicts.csv`: 5건(DSC-001~005). 5건 모두 원본과 대조했다(2.5절). SOP 값은 `tables.jsonl` 셀이고 B 값(`rules_deterministic.ttl`)과 같다. 데이터시트 값은 적힌 위치(쪽 문자 위치 또는 표 셀)의 원문과 같다. 해시도 맞다. 비고에 "값을 통일하지 않음"이 있다. 저장소 `extraction/conflicts.csv`는 아직 만들어지지 않았다(실제 실행 전) |
| ground_truth.csv가 프롬프트·청킹·추출 입력에 쓰이지 않음 | PASS | `grep -rn "ground_truth\|imaks_data/human\|evaluation" src`: `settings.py:17 EVALUATION_DIR` 정의 하나뿐이다. 이 상수를 쓰는 곳은 `preprocess/sensors.py`(평가용 행 라벨 출력)뿐이고 C 코드에는 없다. 누수 점검도 PASS다. 프롬프트의 ID 목록은 seed.ttl과 같고(아래 센서·공정 항목), 예시 3개는 SOP 청크의 줄을 그대로 옮긴 것이다(2.1절) |
| (MAINT 병합) ID·같은 표 행 인용은 새 Rule이 안 되고 병합 후 identifier 중복 0 | PASS | 병합 8건: basis `id` 7, `table_row` 1, 대상 MAINT-01~08. 합본에서 Rule 53개, identifier 53개, 정규화(공백 제거·대문자)한 값도 53개다. 그래서 중복은 0이다 |
| (MAINT 병합) B 값 불변 | PASS | B Rule 30개의 다섯 값(rdf:type, appliesToSensor, conditionText, responseText, priority)을 `rules_deterministic.ttl`과 합본에서 비교했다. 차이는 0이다. B 트리플 2,684개 가운데 합본에서 빠진 것도 0이다. `rules_llm.ttl` 안에서 B 주어를 가진 트리플은 8개이고 모두 `im:hasProvenance`다 |
| (MAINT 병합) 값이 다른 병합 건은 모두 `extraction/runs/<run_id>/merge_conflicts.csv`에 있고 1차 검토 CSV에도 있음 | PASS | (체크리스트 문구는 1차 지적 뒤 실행 폴더 경로로 고쳐졌다.) 병합 8건의 class·센서·조건·조치를 B와 따로 비교했다. 결과 `{(…table1:chunk:r2, conditionText), (…table1:chunk:r3, class)}`는 `runs/g1/merge_conflicts.csv`와 같다. 두 건의 conflict_id는 모두 `review_round1.csv`의 merge_conflict 행에 있다 |
| (MAINT 병합) LLM 출처가 B에 "재확인" Provenance로 붙고 원본 응답·병합 전 결과 보존 | PASS | 위 8개 hasProvenance의 대상은 extractionMethod "llm"인 Provenance다. 보존된 것: `raw/request` 60개, `raw/response` 60개, `candidates_premerge.jsonl` 31건, `merged.jsonl` 31건, `rules_llm_prereview.ttl` |
| (MAINT 병합) ID가 다른 규칙은 합치지 않음(반례) | PASS | `SOP-001:p1:RULE-ST02-02:r1`(OperationalRule, 센서 ST02_SEALING_TMP)의 결과는 `merged: False`, identifier `RULE-ST02-02`다. 같은 센서의 B 규칙 `SOP-002:THR:ST02_SEALING_TMP`(ThresholdRule)와 합쳐지지 않았다 |
| sourceQuote가 원문 그대로이고 위치(본문은 charStart·charEnd, 표는 tableId·rowIndex·colIndex·bbox)와 textSha256이 맞음, 없으면 거부하고 기록 | PASS | 위치·해시: 위 출처 항목과 같다(31/31). 거부 기록: `rejected.csv` 사유는 `call_failed 3, quote_not_in_chunk 1, rule_id_not_in_chunk 1, sensor_not_in_list 1, station_not_in_list 1, schema 1`이다(체크리스트 문구는 1차 지적 뒤 표 좌표 기준으로 고쳐졌다) |
| 센서·공정 ID가 목록(22, 9) 안 | PASS | seed.ttl을 rdflib로 따로 읽었다. 센서 22개, 공정 9개다. 프롬프트의 `- ID` 줄 31개가 이 둘을 합친 목록과 같다. `rules_llm.ttl`의 appliesToSensor 10종과 actionTarget 7종은 모두 seed의 Sensor·Station IRI다. 목록 밖 ID는 거부됐다(`sensor_not_in_list`, `station_not_in_list`) |
| C 입력 청크가 preprocess_lock과 일치(해시 사슬) | PASS | meta `preprocess_lock_sha256` == 현재 lock(`c7998ba8…`). 입력 60개 모두 다음이 성립한다: text_sha256 == SHA-256(text), source_file_sha256 == lock `input_pdfs`, 현재 PDF 해시도 같다. lock의 `chunks.jsonl` 해시 == 현재 파일. `input_fingerprint` 4개 == 현재 파일. 변경 반례는 3장 (g)에 있다 |
| 재현 정보(모델 ID, 생성 설정, 프롬프트 버전·해시, 입력 청크 해시, 원본 응답) 저장 | PASS | meta에 있는 것(2.6절, 9장): provider gemini, model `gemini-3.8-flash`, temperature 0, seed 20261012, max_tokens 8192, structured_output, thinking_config "미설정(모델 기본값)", schema_changes_for_gemini, google_genai_version, sdk_client, min_interval_s, `generation_settings_sha256`, prompt 버전·해시, 템플릿·예시·스키마 해시, input_chunks 60. `generation_settings_sha256`은 저장된 요청에서 다시 계산한 `988435ec…`와 같다. raw 응답 60개, calls.jsonl 60줄(served_model, request_id, usage, finish) |
| LLM 원본·1차·2차 검토 결과 보존 | PASS | 실행 폴더에 raw/, calls, candidates_premerge, merged, merge_conflicts, rejected, review_round1, review_round2, final, review_applied, review_manifest, meta가 모두 있다. 덮어쓰기는 거부된다: apply 재실행 → "이미 있어 덮어쓰지 않음 … final.jsonl", round2 재실행 → "2차 양식이 이미 만들어짐", 같은 run-id 재실행 → "실행 폴더가 이미 있음" |

---

## 2. 추가 확인 1: 1차 검증 항목 재확인

| # | 항목 | 결과 | 근거 |
|---|---|---|---|
| 2.1 | 입력 60/26 | PASS | `select_chunks`를 다시 돌린 결과와 meta가 같다. 입력 60개(SOP-001 35, SOP-004 11, SOP-002 10, SOP-003 4). 제외 26개(SOP-002 table 11, 데이터시트 15: DS-MECH 8, DS-ELEC 3, DS-THERM 4) |
| 2.1 | 프롬프트 3단·ID 목록·예시 원문·해시 | PASS | 3단과 해시는 위 표에 있다. 예시 3개의 `input_text` 각 줄은 출처 청크 `text.split("\n")`의 **온전한 줄**이다(부분 문자열이 아님). 각 sourceQuote는 input_text 안과 청크 원문 안에 있다. 센서·공정은 목록 안에 있다. 조립된 system에 들어 있다. 문제 0건(c1_items) |
| 2.1 | 인용 위치·해시 | PASS | 본문 17개는 charStart/charEnd, 표 14개는 좌표다(위 표) |
| 2.1 | MAINT 병합 | PASS | 중복 0, B 값 불변, 충돌 기록, RULE-ST02-02 반례(위 표) |
| 2.5 | conflicts.csv 5건 | PASS | 아래 표. SOP 셀, B 값, 데이터시트 원문 위치, 두 해시를 다시 계산해 모두 맞았다 |
| 2.6 | 합본 SHACL | PASS | `run_shacl.py --ont`(추론 끔): `Conforms: True`(3,699 트리플) |

| id | 센서 | SOP-002 값(표 셀) | 데이터시트 값(위치) | 셀·위치·해시 |
|---|---|---|---|---|
| DSC-001 | ST01_FILLING_PRS | WARN_HI 4.2 (SOP-002:p1:table1 r3 c6) | DS-MECH-4400 0.50 bar 여유(p1 char 493-561) | 일치 |
| DSC-002 | ST02_SEALING_CUR | CRIT_HI 15.0 (p1:table2 r4 c7) | DS-ELEC-3300 14 A(table1 r4 c2) | 일치 |
| DSC-003 | ST02_SEALING_CUR | CRIT_HI 15.0 | DS-ELEC-3300 note 2 "up to 14 A"(p1 char 484-525) | 일치 |
| DSC-004 | ST02_SEALING_TMP | CRIT_HI 210.0 (p1:table2 r2 c7) | DS-THERM-2200 −40~+200(table1 r2 c2) | 일치 |
| DSC-005 | ST02_SEALING_TMP | CRIT_HI 210.0 | DS-THERM-2200 note 1 200°C(p1 char 515-562) | 일치 |

---

## 3. 추가 확인 2: 검토·입력 무결성

**방법** (`c2_guard.py`)
- 임시 작업 공간에 입력 사본을 만들었다(documents, seed, B, lock).
- 그 위에서 Gemini 가짜 실행을 했다(run_id `g-guard`).
- 1차 검토: 1건 hold, 나머지 accept. 그다음 2차 생성, 2차 accept.
- 두 기준 상태를 만들었다.
  - `pre`: apply 전
  - `post`: apply와 to_rdf 후. 기존 출력 3개가 있는 상태다.
- 시나리오마다 기준 상태를 새로 복사하고 변조한 뒤 대상 단계를 실행했다.
- 판정 기준(셋 다 만족해야 PASS):
  1. ExtractError로 멈춘다.
  2. 작업 공간 전체에 새 파일이 0개다.
  3. 기존 파일의 내용(SHA-256)과 mtime_ns가 하나도 바뀌지 않는다.

| 시나리오 | 단계 | 결과 | 멈춤 메시지(요약) |
|---|---|---|---|
| (a) review_applied.json 삭제 / apply 전 상태 | to_rdf | PASS / PASS | "검토 기록 review_applied.json가 없음" |
| (b) final.jsonl responseText 변경 | to_rdf | PASS | "final.jsonl이(가) 기록 이후 바뀜: 기록 fb07… / 현재 fc37…" |
| (b') 위 + applied의 final 해시 위조 | to_rdf | PASS | "…RULE-ACCESS-04:r1의 responseText가 merged.jsonl·검토 CSV로 다시 만든 값과 다름" |
| (c) 1차 accept→reject, apply 후 / apply 전 | to_rdf / apply | PASS / PASS | "review_round1.csv … 바뀜" / "(2차 생성 = 1차 확정 때) … 바뀜" |
| (d) 2차 final_decision 변경 / 고정 열 변경(apply 전) / 2차 삭제 | to_rdf / apply / to_rdf | PASS ×3 | "review_round2.csv … 바뀜" / "고정 열 … 다름" / "2차 검토 유무가 기록과 다름" |
| (e) B 산출물 responseText 1글자 | to_rdf / apply | PASS / PASS | "rules_deterministic.ttl(B 산출물)가 추출 때와 다름: 6285… / a06c…" |
| (f) seed.ttl 변경 | to_rdf / apply | PASS / PASS | "kg_build/seed.ttl가 추출 때와 다름" |
| (g) chunks.jsonl 텍스트 변경 / lock 변경 | to_rdf·apply / to_rdf·apply | PASS ×4 | "해시 사슬: 전처리 산출물 … != lock" |
| (h) **1차 검증의 일관된 위조**(1차 결정 변경 + final에서 삭제 + applied 재계산, manifest 그대로) | to_rdf | PASS | "review_round1.csv(1차 확정) 해시가 review_manifest.json와 review_applied.json에서 다름" (1차 지적 결함이 고쳐졌다) |
| (i) manifest만 위조: round1 양식·merged·conflicts, round2 1차 확정·2차 양식, run_id, 지문 해시(7종) / 1차 양식 해시(apply) / manifest 삭제 | to_rdf / apply / to_rdf | PASS ×9 | 항목 이름과 두 값이 메시지에 나온다 |
| (k) 다른 실행(`g-other`)의 manifest로 바꿈 | to_rdf / apply | PASS / PASS | "run_id가 meta.json과 다름: manifest g-other / meta g-guard" |
| (k') 같은 run_id, 다른 작업 공간의 manifest | to_rdf | PASS | "input_fingerprint_sha256가 meta.json과 다름" |
| **(j) applied + manifest 위조**: (h)에 더해 manifest `round2.round1_sha256`도 새 1차 해시로 바꿈 | to_rdf | **FAIL** | 멈추지 않았다. `out/rules_llm.ttl`, `rules_llm_prereview.ttl`, `seed_plus_rules_llm.ttl`이 덮어써졌다. accept를 reject로 바꾸면 2차 양식(edit·hold 행만)이 그대로라 2차 양식 해시도 맞는다 |

**(j)가 통과한 이유**
- 1차 확정 해시가 `review_manifest.json`과 `review_applied.json` 두 곳에만 있다(`guard.py` 196~210행 `pairs`).
- 두 파일 모두 같은 실행 폴더 안에 있고 서명이 없다.
- 그래서 둘을 함께 고치면 대조할 기준이 남지 않는다.
- 구현 보고서 10장 "한계"가 이 점을 이미 인정했다. 고치려면 신뢰 기준점을 실행 폴더 밖에 두어야 한다. 예:
  - 1차 확정 해시를 git이 추적하는 파일(work_log 등)에 옮겨 적는다.
  - 서명 또는 HMAC 키를 실행 폴더 밖에 둔다.

---

## 4. 추가 확인 3: 비용 승인 게이트와 상태 기계

**방법** (`exec_harness.py`, `c3_exec.py`, `c3b_exec.py`)
- `run.main(["--execute", "--provider", "gemini", …])`를 직접 불렀다.
- 바꾼 것은 세 가지다.
  - `genai.Client`: 생성 횟수를 세는 가짜로 바꿨다. `models.generate_content`는 가짜 응답을 주거나 `llm_gemini.fake_error`의 오류를 낸다.
  - 키: 임시 `.env`의 가짜 키를 쓴다.
  - `run.STATUS_CONFIRMED`: 현재 예시 상태(DRAFT)를 "확정"으로 보도록 바꿨다. 예시 파일은 고치지 않았다.
- 대기 함수는 기록만 하고 실제로 기다리지 않는다.
- 입력·프롬프트를 바꾸는 반례는 임시 사본으로 했다. `prepare(paths=…, prompts_dir=…)`에 사본 경로를 주입했다.

| 항목 | 결과 | 근거 |
|---|---|---|
| 승인 없음 | PASS | rc 2, "--approve <estimate_id>가 없음", 클라이언트 생성 0, 실행 폴더 없음 |
| 잘못된 ID(형식 `xyz` / 없는 `0123456789abcdef`) | PASS | rc 2, "형식이 아님" / "추정 기록이 없음", 생성 0, 폴더 없음 |
| 기록 위조(`approved_attempts` 99) | PASS | rc 2, "추정 기록 내용이 해시와 다름: 기록 a4f9… / 다시 계산 4370…", 생성 0 |
| 재사용 | PASS | 성공 실행(state used) 뒤 같은 ID → "쓸 수 없는 승인 상태 used(run_id ok-1 …)", 생성 0 |
| 입력 변경(seed.ttl) | PASS | "fingerprint.input_fingerprint.seed_ttl.sha256: 추정 때 cc9a… / 현재 8fba…", 생성 0 |
| 프롬프트 변경(system.md Task에 한 줄) | PASS | "fingerprint.prompt_sha256: 추정 때 12c2… / 현재 a114…", 생성 0 |
| 예시 변경(examples.json note) | PASS | "fingerprint.examples_sha256: 추정 때 e83b… / 현재 4b36…", 생성 0 |
| 청크 수 초과(1개 승인, 2개 실행) | PASS | "fingerprint.chunks: 추정 때 1개 / 현재 2개 …", "청크 수: 승인 1 < 현재 2", 생성 0 |
| 첫 호출에서 401 → unused로 복원, 다시 쓸 수 있음 | PASS | rc 3, state unused, history `created, reserved, released`. 같은 ID로 429 PerDay(FATAL_QUOTA) → 다시 released. 그 뒤 정상 실행 rc 0 → used |
| 성공 1건 뒤 실패 → used + 부분 실행 정보 | PASS | 청크 ST02-03은 200, ST02-04는 403. state used, `partial_run {reason FATAL_AUTH, completed [ST02-03], not_completed [ST02-04]}`. history의 used 사건에 시도별 (청크, 번호, 분류, 상태) 기록. meta status aborted. 병합·검토 양식은 만들지 않았다 |
| 타임아웃 → usage_check_required, 재사용 거부, resolve | PASS | `httpx.ReadTimeout` → 호출 1회, state usage_check_required, meta `usage_check` 기록. 재사용 → "Console에서 사용량을 확인하고 resolve…" 거부. `approval resolve <id> --as unused --note …` → unused(history `…, usage_check_required, resolved`). 그 뒤 실행 rc 0. unused에서 resolve하면 "usage_check_required 상태에서만 가능"으로 거부 |
| 예약된 승인은 다른 실행이 못 씀 | PASS | `reserve(…, "other-run")` 뒤 execute → "쓸 수 없는 승인 상태 reserved(run_id other-run …) 다른 실행이 예약 중", 생성 0. `finalize(…, "intruder")`는 상태를 바꾸지 않는다(reserved 유지) |
| 이력 보존 | PASS | 한 승인의 history: created → reserved(sm-auth) → released(FATAL_AUTH) → reserved(sm-quota) → released(FATAL_QUOTA) → reserved(sm-reuse-ok) → used. 앞선 사건이 지워지지 않는다 |
| (관찰) state 필드 위조 | 참고 | 사용한 승인의 `state`를 `"unused"`로 손으로 고치면 다시 실행된다(rc 0). `state`·`history`는 설계상 내용 해시(`BODY_FIELDS`, `approval.py` 64~65행) 밖에 있다. 3장 (j)와 같은 종류의 한계라 판정에는 넣지 않는다 |

---

## 5. 추가 확인 4: 청크 수와 API 시도 상한 분리

| 항목 | 결과 | 근거 |
|---|---|---|
| 청크 1개: 429 뒤 200 → 성공, 시도 2, 청크 1 | PASS | `--execute` 1청크, 응답 순서 [429 PerMinute(RetryInfo 7s), 200] → rc 0, state used. meta `approved_chunks 1, approved_attempts 3, actual_chunks 1, actual_attempts 2`. `chunk_attempts`에 시도 1(TRANSIENT_RATE, 429, retry_after_s 7.0, wait_s 7.0)과 시도 2(200)가 있다. 대기 호출은 `[7.0]` |
| 429 ×3 → TRANSIENT_EXHAUSTED, 승인 복원 | PASS | rc 3, abort TRANSIENT_EXHAUSTED, 호출 3회, state unused. 503 ×3도 같다(지수 대기 [2.0, 4.0]) |
| 승인 청크 수를 넘는 처리 차단 | PASS | 실행 경로: 위 "청크 수 초과" 거부(클라이언트 생성 전). `run_calls(max_chunks=1)`에 청크 2개 → "부를 청크 수 2가 승인 청크 수 1를 넘음(시작 안 함)", 폴더 없음. `CallBudget(…, 1, 3)`으로 두 번째 청크 → "승인 청크 수 1를 넘는 청크를 막음" |
| 시도 상한을 넘는 시도 차단 | PASS | `run_calls(max_chunks=2, max_attempts=2)`에서 첫 청크가 429 → 재시도 없이 TRANSIENT_EXHAUSTED("승인 API 시도 상한 소진"), actual 1/1. `CallBudget(…, 1, 2)`에서 세 번째 시도 → "승인 API 시도 상한 2를 넘는 시도를 막음" |
| meta 기록 | PASS | 위 실행 meta에 approved_chunks, approved_attempts, actual_chunks, actual_attempts, chunk_attempts(청크별 시도 이력)가 있다 |
| 공식 `min(N×3, N+10)` == 추정 기록 | PASS | N=1 → 3, N=3 → 9, N=60 → 70. 내가 계산한 값과 추정 기록의 `approved_attempts`가 같다. `attempt_cap_formula`에 식과 값이 적혀 있다(예: `min(60×3, 60+10) = 70`) |

---

## 6. 추가 확인 5: 오류 분류

**Gemini** (`c5_errors.py`)
- 오류 객체는 `google.genai.errors.ClientError/ServerError(code, response_json)`로 만들었다.
- response_json에는 실제 오류 본문 모양을 넣었다: ErrorInfo, QuotaFailure, RetryInfo, Help. 구현 보고서·테스트의 가짜와는 따로, 내가 직접 만들었다.
- 결과: 20개 모두 기대 분류와 같다(`mismatches: 0`).

| 경우 | 분류 | 근거(matched_pattern 요약) |
|---|---|---|
| 401 UNAUTHENTICATED / 403 PERMISSION_DENIED / 400 + ErrorInfo API_KEY_INVALID | FATAL_AUTH ×3 | status·reason |
| 429 + QuotaFailure `…PerDay…-FreeTier`(+RetryInfo 41s) | FATAL_QUOTA | "QuotaFailure 일일 한도" (retryDelay는 쓰지 않음) |
| 429 + QuotaFailure PerMinute, quotaValue "0" | FATAL_QUOTA | "quotaValue 0(할당 없음)" |
| 429 + QuotaFailure PerMinute + RetryInfo 37s | TRANSIENT_RATE, retry_after 37.0 | |
| **반례**: 429, PerMinute QuotaFailure, 메시지에 "free_tier"와 "billing"이 모두 있음 | **TRANSIENT_RATE**, retry_after 12.0 | QuotaFailure를 메시지보다 먼저 본다(`llm_gemini.py` 311~325행) |
| 429 입력 토큰 PerMinute | TRANSIENT_RATE | |
| 400 FAILED_PRECONDITION | FATAL_QUOTA | "status FAILED_PRECONDITION" |
| 404 NOT_FOUND / 400 INVALID_ARGUMENT(스키마) / 413 | FATAL_REQUEST ×3 | |
| 500 INTERNAL / 504 DEADLINE_EXCEEDED | AMBIGUOUS ×2 | "사용량 확인 필요" |
| 503 UNAVAILABLE | TRANSIENT_RATE | |
| httpx ReadTimeout / ConnectTimeout / ConnectError, httpx2 ReadTimeout | AMBIGUOUS ×4 | |
| (관찰) 429, QuotaFailure 없음, 메시지에 "free_tier" | FATAL_QUOTA | `llm_gemini.py` 322행. 분당 한도라도 QuotaFailure가 빠지면 멈추는 쪽으로 분류한다. 7장 참조 |

**Anthropic**
- `llm.fake_exception`으로 만든 SDK 예외 16종이 모두 기대대로 분류됐다.

| 대상 | 분류 |
|---|---|
| 401, 403, CredentialsError | FATAL_AUTH |
| 402, billing_error, 400 "credit balance", 429 "usage limit" | FATAL_BILLING(일치한 문구 기록) |
| 404, 400 bad_request | FATAL_REQUEST |
| 429(retry-after 5) | TRANSIENT_RATE, 5.0 |
| 529, 503 | TRANSIENT_RATE |
| 500, 504, APITimeoutError, APIConnectionError | AMBIGUOUS |

**첫 치명 오류에서 전체 중단** (청크 3개, 첫 청크에서 오류)

| 공급자 | 오류 종류 | 결과 |
|---|---|---|
| Gemini | quota_day, unauthenticated, not_found, invalid, precondition | 매번 호출 1회. 뒤 2청크는 0회. `not_completed`에 3청크 모두 기록 |
| Anthropic | auth, billing402, credit400, spend429, not_found | 호출 1회 |
| Anthropic | internal, timeout | 호출 1회(AMBIGUOUS) |
| Anthropic | overloaded | 같은 청크 3회 뒤 TRANSIENT_EXHAUSTED |

**AMBIGUOUS 재시도 없음**
- Gemini 500: 그 청크 시도 1회, 뒤 청크 0회, 승인은 usage_check_required.
- 504와 타임아웃도 같다.

**SDK 내부 재시도 끔** (`c5_sdk.py`)
- google-genai `2.30.0`을 직접 확인했다.
  - `_api_client.retry_args(None)` = `{'stop': stop_after_attempt(1), 'reraise': True}`.
  - 이 인자로 `tenacity.Retrying`을 돌려 항상 실패하는 함수를 부르면 **시도 1회**다.
  - 쓰이는 위치는 915행 `retry_args(self._http_options.retry_options)`다.
  - 요청마다 재시도를 켜는 경로(1617·1800행)는 요청 `http_options.retry_options`가 있을 때만 동작한다. `build_request`의 config에는 http_options가 없다(저장된 요청의 config 키: system_instruction, temperature, response_mime_type, response_json_schema, max_output_tokens, seed).
- `GeminiClient()` 생성자를 가로채 인자를 확인했다.
  - kwargs는 `api_key`와 `http_options` 두 개다.
  - `http_options.retry_options = None`, `timeout = 600000`.
- `AnthropicClient()` 생성자 kwargs: `{'max_retries': 0, 'timeout': 600.0}`.

---

## 7. 추가 확인 6: 이어서 하기(`--resume-from`)

**방법** (`c6_resume.py`, `c6b_dup.py`)
- 가짜 응답의 `model_version`을 `gemini-3.8-flash`로 바꿨다.
- 실행 A: 26번째 청크 `SOP-001:p2:text3`에서 429 PerDay로 중단했다.
- 실행 FULL: 한 번에 끝까지 돌렸다.
- 실행 B: `resume.collect([A])`와 `restrict`로 A를 이어서 돌렸다.

| 항목 | 결과 | 근거 |
|---|---|---|
| 정상 이어서 하기 == 한 번에 실행 | PASS | 둘 다 1차 전부 accept → round2 → apply까지 했다. 다섯 파일의 SHA-256이 모두 같다: candidates_premerge `f8fe69ea…`, merged `9178822c…`, rejected `8ce5c8fa…`, merge_conflicts `64ca8135…`, **final.jsonl `5cd054c8…`** |
| 실패 응답은 재사용 안 함 | PASS | A의 실패 청크(`RULE-SRV01-02` 거절, `text3` 중단)와 거부 행이 있는 청크 2개는 재사용 목록에 없다. B에서 다시 불렸다. 재사용 24, B 호출 36(=60−24) |
| 재사용 출처 기록 | PASS | meta `reused_from[청크]`에 `run_id A`, `request_id gemini_fake_000`, `raw_path`, `raw_sha256`, `copied_to raw/response/…`, `copied_sha256`가 있다. calls.jsonl의 재사용 24줄에 `reused_from: "A"` |
| 거부: 모델 변경(`gemini-3.8-pro`) | PASS | "model: 이전 gemini-3.8-flash / 현재 gemini-3.8-pro" + generation_settings 차이 |
| 거부: 생성 설정(seed 1, max_output_tokens 4096) | PASS | "generation_settings_sha256: 이전 9884… / 현재 7454…"(seed), "/ 현재 5ff4…"(토큰) |
| 거부: 프롬프트 / 예시 | PASS | "prompt_sha256 …" / "examples_sha256 …" |
| 거부: 입력 지문(seed 변경 사본) | PASS | "input_fingerprint: 이전 (지문) / 현재 (지문)" |
| 거부: 청크 해시(A의 meta에서 한 청크 해시를 0으로 바꿈) | PASS | "청크 SOP-001:p1:RULE-ST01-01 text_sha256: 이전 000… / 현재 d8ad…" |
| 거부: 공급자(anthropic) | PASS | "provider: 이전 gemini / 현재 anthropic …" |
| served model `gemini-2.5-pro` | PASS | 거부: "served model: gemini-2.5-pro / 요청 모델 gemini-3.8-flash" |
| served model `gemini-3.8-flash-001` | PASS(허용) | 버전 접미사라 허용하는 것이 의도된 동작이다 |
| **served model `gemini-3.8-flash-lite`** | **FAIL** | **허용됐다.** `resume.py` 39~40행 `_served_ok`는 `served.startswith(f"{model}-")`이다. 그래서 다른 모델(flash-lite)이 답한 응답도 재사용한다. 버전 접미사만 허용하는 정확한 규칙(예: `-\d{3}$`, `-preview-…`)이나 허용 목록이 필요하다 |
| 같은 청크가 두 실행에 있으면 멈춤 | PASS | `collect([A, FULL])` → "청크 SOP-001:p1:text1의 성공 응답이 여러 실행에 있음(A, FULL)" |
| 합친 뒤 중복 규칙 검출 | PASS | X 실행: `RULE-ST04-03` 청크에서 ruleIdInText `RULE-ST02-04`(원문 "verify RULE-ST02-04.")만 성공. 이를 이어서 ST02-04 청크를 부르면 "여러 실행을 합친 결과 검사 실패 … normalized_rule_id_in_multiple_chunks ['RULE-ST02-04']"로 멈춘다. status `combination_check_failed`이고 merged.jsonl과 1차 양식은 만들지 않는다. 같은 응답을 한 번에 돌리면 `ok: False`를 기록만 하고 완료한다(설계대로) |

---

## 8. 추가 확인 7: 외부 전송 허용 목록(Gemini)

| 항목 | 결과 | 근거 |
|---|---|---|
| 데이터시트 청크 `--chunk`로 주기 | PASS | `prepare(chunk_ids=[DS-ELEC-3300:p1:text1])` → "--chunk에 입력 청크가 아닌 것이 있음 … 데이터시트: LLM 입력 아님". CLI `--dry-run --chunk DS-…` → rc 1, 추정 기록 폴더 없음 |
| SOP-002 표 청크 `--chunk` | PASS | "SOP-002 table 청크: … LLM 입력 아님" |
| 보내기 직전 검사 | PASS | prepare를 거친 ctx의 요청 목록 앞에 데이터시트 청크를 끼워 넣고 `run_calls` → "외부 전송 허용 목록 밖(보내지 않음): DS-ELEC-3300 …". 가짜 클라이언트 호출 0회 |
| 예시 출처 검사 | PASS | 사본 examples.json의 예시 1을 데이터시트 청크의 한 줄로 바꾸면 Gemini `prepare`가 "… (프롬프트 예시 출처)"로 거부한다. 같은 사본을 Anthropic 경로에 주면 받아들인다(허용 목록은 Gemini 경로만, 구현 보고서 14장대로) |
| meta `outbound_allowlist` | PASS | `{"docs": ["SOP-001",…,"SOP-004"], "source_file_prefix": "imaks_data/rules/", "rule": …}`(meta 최상위와 adapter.meta 두 곳) |
| 보내기 직전마다 다시 검사하는지(코드 읽기) | PASS | `run.py` 206~209행: 재사용이 아닌 청크마다 `adapter.outbound_problem(chunk, ctx["docs"])`를 먼저 확인한다. 순서는 이 검사 → `on_first_call`(승인 예약) → 간격 대기 → 요청 저장 → `call_with_policy`다. prepare(99~105행)는 요청 청크와 예시 출처를 모두 확인한다. 재시도(같은 청크)는 다시 검사하지 않지만 같은 청크라 영향이 없다 |

---

## 9. 추가 확인 8: 키 처리와 자동 전환

| 항목 | 결과 | 근거 |
|---|---|---|
| 우선순위: 환경변수 > `.env` | PASS | 환경변수와 임시 `.env`에 서로 다른 가짜 키 → `source=environment`, 환경변수 값이 쓰인다. 환경변수를 지우면 `source=.env`(`export`·따옴표 줄도 읽음) |
| `GOOGLE_API_KEY`가 있으면 멈춤 | PASS | `load_key` → KeyMissingError "환경에 GOOGLE_API_KEY가 설정돼 있어 중단". `--execute` → rc 2, "실제 실행 거부: FATAL_AUTH: …", 클라이언트 생성 0 |
| 키 없음 → 클라이언트 생성 전에 FATAL_AUTH | PASS | `.env` 경로를 없는 파일로 → `--execute` rc 2, "GEMINI_API_KEY가 환경에도 .env에도 없음(클라이언트를 만들지 않음)", 생성 0, 폴더 없음. `GeminiClient()` 직접 생성 → KeyMissingError(error_class FATAL_AUTH) |
| 키가 메시지·meta·repr·로그에 없음 | PASS | 임시 작업 공간의 모든 파일(승인 기록, meta, raw 요청·응답, calls, CSV)과 캡처한 출력에서 두 가짜 키 문자열 검색 → 0건. `repr` = `GeminiClient(key_source='.env')`, 인스턴스 속성은 `key_source, _client`뿐이다. 오류 메시지 안의 `AIza…` 키는 `[가림]`으로 바뀐다 |
| 자동 전환 없음(코드 읽기) | PASS | 공급자는 `run.get_adapter(provider, model)`(56~62행)만 정하고 인자는 CLI `--provider/--model`뿐이다. `GeminiAdapter.model_id = model or GEMINI_MODEL`(394행). FATAL_QUOTA 뒤에 실행되는 것은 `run_calls`의 break → `approval.finalize` → rc 3뿐이고, 모델·공급자·등급을 다시 고르는 코드는 없다(`grep fallback\|switch\|model_id =`). Gemini 요청에는 폴백 필드가 없고 meta에 `fallbacks: 없음`, `auto_switch: 없음`이 있다. Anthropic 경로의 `fallbacks="default"`는 `--provider anthropic`을 줄 때만 쓰인다 |
| `GEMINI_MODEL = "gemini-3.8-flash"` | PASS | `llm_gemini.py` 47행 |
| 요청 설정과 meta 기록 | PASS | 저장된 요청 config: `temperature 0, seed 20261012, response_mime_type application/json, response_json_schema(1,551자, type 배열 2곳을 anyOf로 바꿈), max_output_tokens 8192, system_instruction`. meta에는 temperature·seed·max_tokens·structured_output·thinking_config("미설정(모델 기본값)")·schema_changes_for_gemini(2건)·sdk_client·google_genai_version이 각각 있다. 이 설정 전체(사용자 메시지만 뺀 요청)의 해시가 `generation_settings_sha256`이다(다시 계산해 같음) |

---

## 10. 추가 확인 9: 대표 청크 dry-run

- 명령: `cli.py imaks_kg.extract.run --dry-run --provider gemini --chunk SOP-001:p1:RULE-ST02-04 --approvals-dir $S/approvals_dry9`
- 네트워크 차단 래퍼(`cli.py` → `netblock.py`) 아래에서 돌렸다. 끝난 뒤 횟수는 `{'genai.Client': 0, 'anthropic.Anthropic': 0, 'socket': 0}`였다.

| 항목 | 값 | 독립 확인 |
|---|---|---|
| 공급자·모델·등급 | gemini, gemini-3.8-flash, free(비용 0) | 기록 `provider`, `model`, `billing_tier` |
| 청크 수 | 1 | `approved_chunks 1`, `chunk_filter ['SOP-001:p1:RULE-ST02-04']` |
| 시도 상한 | 3 | `min(1×3, 1+10) = 3` |
| 입력 토큰 추정 | 2,173 ~ 2,897(글자 8,691) | 요청에서 다시 셈: system + contents + 스키마 JSON = 8,691자, ceil(/4) = 2,173, ceil(/3) = 2,897 |
| 출력 상한 | 8,192 | `max_tokens_per_call 8192`, `output_cap_tokens 8192` |
| 호출 간격 | 6.0초 | `pacing.min_interval_s 6.0` |
| estimate_id | `9f063fcaa6c2cc36` | 기록 본문(`BODY_FIELDS`)의 정규화 JSON SHA-256을 다시 계산: `content_sha256`과 같고 앞 16자리 == estimate_id |

(estimate_id는 생성 시각이 해시에 들어가 다시 돌릴 때마다 바뀐다. 구현 보고서의 `bfbdaa3f144fb6d8`과 다른 것은 정상이다.)

---

## 11. 추가 확인 10: 통합

| 항목 | 결과 | 근거 |
|---|---|---|
| `unittest discover -s tests` 전부 통과 | PASS | (1) 그대로 실행: `Ran 239 tests in 378.556s OK`. (2) 다시 실행(`ut_blocked.py`). 이번에는 다음을 막고 감시했다: 소켓, `genai.Client`·`anthropic.Anthropic` 생성, 저장소 `.env` 읽기. 결과는 `ran 239 fail 0 err 0 skip 0`, `NETBLOCK {'genai.Client': 0, 'anthropic.Anthropic': 0, 'socket': 0}`, 저장소 `.env` 읽기 0회 |
| `check_leakage.py`(기본 / `preprocessed ontology_v1 kg_build src`), `check_raw_unchanged.py` | PASS | 공통 표와 같다(작업 시작과 끝에 실행) |
| 절대 경로 없음 | PASS | 공통 표와 같다 |
| `git check-ignore` | PASS(참고 1건) | `extraction/` → `.gitignore:234:/extraction/`, `kg_build/` → `:233:/kg_build/`, `.env` → `:151:.env`. `src/imaks_kg/extract/run.py`, `tests/test_extract_gemini.py` → check-ignore exit 1(무시되지 않음). **참고:** `src/imaks_kg/extract/`와 새 테스트 파일은 아직 커밋 전이라 `git status`에서 `??`(untracked)다. 무시 대상은 아니므로 커밋하면 추적된다 |
| 저장소에 실제 산출물 없음 | PASS | 작업 끝: `extraction/` 없음. `kg_build/`에는 `rules_deterministic.ttl, seed.ttl, seed_plus_rules.ttl`뿐(`rules_llm*.ttl` 없음). `git status --short --ignored`에 새 항목 없음(이 보고서 제외) |

---

## 12. 불합격 사유와 수정이 필요한 위치

체크리스트 19개는 모두 PASS다. 아래는 추가 확인에서 나온 FAIL 하위 항목이다.

1. **applied + manifest를 함께 위조하면 통과한다** (추가 확인 2 (j)).
   - 위치: `src/imaks_kg/extract/guard.py` `verify_review_record`(196~210행)와 `check_manifest`.
   - 원인: 1차 확정 해시의 기준이 같은 실행 폴더 안의 두 JSON뿐이다.
   - 고칠 방향(사용자 결정): 실행 폴더 밖의 신뢰 기준점이 필요하다. 예:
     - round2 생성 때 1차 확정 해시를 git이 추적하는 파일에 옮겨 적는다.
     - 저장소 밖 비밀 키로 manifest·applied에 HMAC을 붙인다.
   - 구현 보고서 10장 "한계"에 이미 적혀 있다.
2. **served model 앞부분 일치 규칙이 다른 모델을 허용한다** (추가 확인 6).
   - 위치: `src/imaks_kg/extract/resume.py` 39~40행 `_served_ok`.
   - 반례: 요청 `gemini-3.8-flash`, 응답 `model_version` `gemini-3.8-flash-lite` → 재사용 허용.
   - 고칠 방향: 버전 접미사 형식만 허용한다(예: `^<model>(-\d{3})?$`). 또는 served model이 요청 모델과 정확히 같을 때만 허용하고, 다르면 사람이 확인하게 한다.

## 13. 미확인 항목과 이유

- **실제 Gemini 응답·오류 형식: 미확인**(실제 호출 금지). 확인하지 못한 것:
  - 오류 본문의 `details` 구조와 quotaId 이름
  - RetryInfo `retryDelay` 형식(소수점 포함 여부)
  - `response_json_schema`의 `anyOf`·`enum` 지원 범위
  - `seed`의 실제 효과
  - `model_version` 값의 실제 형식
  - 무료 등급의 실제 분당·일일 한도
- 내가 만든 오류 본문은 공개 문서 지식에 기댄 모양이다. 실제 API와 다르면 분류가 달라질 수 있다.
- 가짜 응답은 구현자가 만든 `tests/extract_fakes.py`에서 나왔다. 반례 일부는 내가 바꿨다. 그래서 이번 검증이 확인한 것은 검사·병합·검토·승인·재시도 **논리**다. 실제 모델 출력의 다양성은 대표하지 못한다.
- `--count-tokens`(Gemini 미구현)와 `--list-models`: 실행 금지라 동작을 확인하지 않았다(코드만 읽음).

---

## 14. 판정 밖의 관찰

1. **실제 Gemini로 확인하지 않은 데서 오는 한계**
   - 분류는 QuotaFailure의 quotaId에 들어 있는 `PerDay`/`PerMinute` 문자열과 quotaValue에 기댄다. 실제 이름이 다르면 일일 한도가 TRANSIENT로 분류될 수 있다(3회 재시도 후 TRANSIENT_EXHAUSTED로 멈추므로 피해는 제한적이다).
   - QuotaFailure가 빠진 429는 메시지에 "free_tier"가 있으면 FATAL_QUOTA다. 실제 분당 한도 메시지에도 `generate_content_free_tier_requests`가 들어가므로, details가 없는 응답에서는 분당 한도도 즉시 멈춘다. 안전한 쪽이지만 불필요한 중단이 생길 수 있다.
   - 무료 등급의 일일 요청 한도가 60보다 작으면 전체 실행이 중간에 FATAL_QUOTA로 멈춘다. 이 경우 `--resume-from`으로 다음 날 이어가야 한다. 새 추정·승인이 필요하다.
   - 첫 실제 실행은 대표 청크 하나(`--chunk`)로 하고 원본 응답·오류 본문을 확인한 뒤 전체로 넓히기를 권한다.
2. **6초 간격**
   - 6.0초는 분당 10회와 정확히 같다(경계값). 시계 오차, 응답 시간 편차, 재시도가 섞이면 분당 한도에 걸릴 수 있다.
   - 재시도 대기(RetryInfo)와 호출 간격은 따로 계산되므로, 재시도 직후 다음 청크까지 다시 6초를 기다린다.
   - 실제 모델의 분당 한도가 10보다 작으면(예: 5회) 처음부터 맞지 않는다. 모델 한도를 확인한 뒤 약간 여유를 둔 값(예: 분당 한도의 80%)이 안전하다.
   - 가짜 실행(`--fake`)에도 6초 간격이 적용된다. 그래서 60청크 가짜 실행 한 번에 약 6분이 걸렸다. 가짜 실행에서는 `--min-interval-s 0`을 기본으로 하는 편이 낫다.
3. **온톨로지 미비**
   - `ontology.ttl`의 Provenance 속성에 청크 ID, 실행 ID, 모델 ID 전용 속성이 없다. 이 값들은 Provenance IRI(`prov_llm_<run>_<candidate>`)와 실행 폴더 meta·final.jsonl에만 있다.
   - 문서 ID도 Provenance에는 없고 Rule의 `sourceDocument`로만 이어진다. CLAUDE.md 4장 설계대로다. 다만 병합된 LLM Provenance는 B 규칙의 sourceDocument에 기대므로, B와 다른 문서에서 같은 ID를 인용하면 출처 문서가 틀어질 수 있다. 이번 가짜 실행에서는 31개 모두 일치했다.
   - `im:extractionMethod`의 `rdfs:domain`은 `im:Rule`(216행)이다. 그런데 to_rdf는 LLM Provenance 31개에도 이 속성을 붙인다. B Provenance에는 0개다. 추론을 켜면 이 Provenance들이 Rule로 추론된다. 지금 SHACL은 추론을 꺼서 통과한다. domain을 넓히거나 Provenance 전용 속성을 따로 두는 것을 검토할 만하다.
4. **예시 청크가 입력과 겹침**
   - 예시 출처 3개(`SOP-001:p1:RULE-ST01-02`, `SOP-004:p1:RULE-ACCESS-02`, `SOP-003:p1:table2:chunk`)가 모두 60개 입력에 들어 있다.
   - 이 청크들에서는 모델이 예시 출력을 그대로 따라 쓸 수 있다. 그래서 F1_content·Coverage가 실력보다 높게 나올 수 있다.
   - ⑤ 평가에서 이 3청크에서 나온 규칙을 따로 표시해, 포함한 점수와 뺀 점수를 함께 보고하기를 권한다.
5. **기타**
   - 승인 기록의 `state` 필드는 내용 해시 밖이라 손으로 되돌리면 재사용할 수 있다. 3장 (j)와 같은 종류의 한계다.
   - `run.py` 312행의 `--model` 도움말("Gemini는 반드시 사용자가 정한다")은 기본값(`gemini-3.8-flash`)이 생긴 지금의 동작과 맞지 않는다.
   - 실행 중간에 ExtractError가 나면 meta.json은 시작 기록만 남고 calls.jsonl은 쓰이지 않는다. 대상은 보내기 직전 허용 목록 위반, CallBudget 차단이다. 다만 prepare와 has_retry_room이 먼저 막으므로 정상 경로에서는 일어나지 않는다.


---

## 2차 검증 보완 확인 (2026-10-14)

작성자는 verifier(독립 검증)다. 범위는 2차 검증의 FAIL 2개(추가 확인 2 (j), 추가 확인 6 served model)와 새로 추가된 해시 장부(`ledger.py`)다. 위 1~14장 내용은 고치지 않았다.

### 판정: **PASS** (보완 범위 6개 항목 전부 PASS)

- 2차 검증의 FAIL 2개는 둘 다 해소됐다.
  - (j) 일관된 위조: to_rdf와 apply 모두 출력 전에 멈춘다.
  - served model 앞부분 일치 문제: `-lite`, `-pro`, `-preview`, `-8b`를 거부한다.
- 이 보완을 반영하면 [C] 최종 판정은 **PASS**다.
  - 체크리스트 19개는 2차 검증에서 이미 전부 PASS였다.
  - 추가 확인 10개는 이제 전부 PASS다.
- 남은 한계 하나는 판정에 넣지 않았다(아래 "판정 밖의 관찰" 1). 장부까지 함께 고치면 잡지 못한다. 구현 보고서 15장이 이미 인정한 구조적 한계다.

### 지킨 원칙

- **실제 API 호출 0회.** `generate_content`, `count_tokens`, `models.list`, 실제 클라이언트를 쓰는 `--execute`, `--list-models`를 하나도 부르지 않았다.
  - 모든 실행은 `netblock.py`를 먼저 불러왔다. 이 파일은 다음을 막고 횟수를 센다.
    - `socket.connect`와 `create_connection`
    - `genai.Client`와 `anthropic.Anthropic` 생성
    - 저장소 `.env` 읽기
  - 모든 실행이 끝날 때 횟수는 `{'genai.Client': 0, 'anthropic.Anthropic': 0, 'socket': 0, 'repo_env_read': 0}`였다.
  - `--execute`는 한 번만 돌렸다. 이때 `llm_gemini.genai.Client`를 내 가짜 클래스로 바꿨고, 키는 임시 `.env`의 가짜 키를 썼다.
- **열지 않은 것:** `imaks_data/kg_seed/ground_truth.csv`, `data/`, `evaluation/`, `imaks_data/human/`, 저장소 `.env`.
- **임시 위치:** 스크립트와 산출물은 모두 세션 scratchpad `…/scratchpad/v3/` 아래에 두었다(아래에서 `$V`).
  - 스크립트: `$V/scripts/`
    - 공통: `netblock.py`, `cli.py`, `vcommon.py`, `base.py`, `mkfake.py`
    - 항목별: `i1_served.py`, `i2_forge.py`, `i3_ledger.py`, `i4_contents.py`, `ut_blocked.py`
  - 장부는 매번 임시 파일을 썼다.
    - 프로세스 안에서 돌릴 때: `ledger.LEDGER_OVERRIDE`
    - CLI로 돌릴 때: `IMAKS_EXTRACTION_LEDGER`
- **저장소 장부 `harness/extraction_ledger.jsonl`:**
  - 작업 전: 0줄, 0바이트, SHA-256 `e3b0c442…b855`
  - 작업 후: 0줄, SHA-256 같음
  - 스크립트마다 끝에서 다시 확인했고 매번 PASS였다.
- **판정 근거:** 구현 보고서 15~16장은 확인 대상을 찾는 데만 썼다. 판정은 모두 내가 직접 돌린 명령과 계산에 근거한다.
- **실행 환경:** `.venv/Scripts/python.exe`, `PYTHONPATH=src`, `PYTHONIOENCODING=utf-8`.

### 항목별 결과

| 항목 | 결과 | 근거 |
|---|---|---|
| 1. 이전 FAIL 6: served model | **PASS** | 아래 1 |
| 2. 이전 FAIL 2(j): 일관된 위조 | **PASS** | 아래 2 |
| 3. 해시 장부 | **PASS** | 아래 3 |
| 4. 호출 간격 7.5초 | **PASS** | 아래 4 |
| 5. 대표 청크 dry-run | **PASS** | 아래 5 |
| 6. 통합 | **PASS** | 아래 6 |

#### 1. served model (`i1_served.py`, CLI 재확인)

`_served_ok`의 위치는 `resume.py` 43~47행이다. 코드는 `re.fullmatch(rf"{re.escape(model)}(-\d{{3}})?", served)`다.

**직접 호출** (요청 모델 `gemini-3.8-flash`, 15건 모두 기대와 같음)

| served model | 결과 |
|---|---|
| `-lite`, `-pro`, `-preview`, `-8b` | 거부 |
| `-01`, `-0011`, `-001-lite`, `-preview-05-20` | 거부 |
| `gemini-2.5-pro`, 빈 문자열, 대문자, 앞에 글자를 붙인 것 | 거부 |
| `gemini-3X8-flash` | 거부(모델 이름의 `.`가 이스케이프됨) |
| `-001` | 허용 |
| 정확히 일치 | 허용 |

**이어서 하기 경로** (`resume.collect`)
- 방법
  - 실행 A: 앞 청크 2개만 돌렸다. 가짜 응답의 `model_version`을 served 값으로 바꿨다.
  - 새 ctx는 4청크로 만들고 `collect([A])`를 불렀다.
- 결과
  - `-lite`, `-pro`, `-preview`, `-8b`는 거부됐다. 메시지 예: "청크 SOP-001:p1:RULE-ST01-02 served model: gemini-3.8-flash-lite / 요청 모델 gemini-3.8-flash (정확히 같거나 -NNN 버전 접미사만 허용)"
  - `-001`과 정확 일치는 2청크를 재사용했다.

**CLI 경로** (`run --fake … --resume-from A`, 임시 장부)
- served가 `-lite`인 경우: rc 2, 같은 거부 메시지.
- served가 `-001`인 경우: rc 0, "재사용 2개(이전 실행 A), 남은 청크 2개".

**원래 실행과 새 실행의 served model이 다른 경우**
- 두 이전 실행의 served model이 서로 다를 때
  - mixA는 `gemini-3.8-flash`, mixB는 `gemini-3.8-flash-001`로 응답했고, 두 실행의 청크는 겹치지 않는다.
  - `collect([mixA, mixB])`는 거부됐다: "재사용할 응답들의 served model이 서로 다름: gemini-3.8-flash ← mixA:…; gemini-3.8-flash-001 ← mixB:…"
  - 대조군: 각 실행을 하나씩 넣으면 둘 다 재사용된다.
- 원래 실행의 기록(`calls.jsonl`의 served_model)과 원본 응답이 다를 때
  - 기록을 `-001`로 바꾸고 장부는 그대로 두면, 장부가 먼저 잡는다: "calls.jsonl: 장부 기록(추출 끝) … / 현재 …"
  - 장부까지 맞게 다시 기록하면, 두 번째 대조가 잡는다: "served model: 원본 응답 gemini-3.8-flash / 원래 실행 기록 gemini-3.8-flash-001"

#### 2. 2차 검증 (j) 일관된 위조 재현 (`base.py`, `i2_forge.py`)

**기준 상태**
- Gemini 가짜 4청크 실행(run_id `v-forge`, served `gemini-3.8-flash`)을 쓰고, 장부는 작업 공간 안에 두었다.
- 1차 검토는 전부 accept로 채웠다. 대상 `SOP-001:p1:RULE-ST02-02:r1`은 merged에 있다.
- 그다음 round2(0행) → apply → to_rdf를 돌렸다. 이것이 `post` 상태다.
- `pre`는 round2까지만 한 상태다.

**위조 내용** (2차 검증과 같음)
1. 대상의 1차 결정을 accept에서 reject로 바꾼다.
2. final.jsonl에서 그 레코드를 지운다(줄 수 −1을 확인함).
3. `review_applied.json`의 `round1.sha256`, `final_jsonl_sha256`, counts·decision_tally를 `review.tally`로 다시 계산한다.
4. `review_manifest.json`의 `round2.round1_sha256`을 새 1차 해시로 바꾼다.

**판정 기준**
- ExtractError로 멈춘다.
- 작업 공간 전체(장부 포함)의 파일별 SHA-256과 mtime_ns를 전후로 비교한다. 새 파일 0, 삭제 0, 변경 0이어야 한다.

| 시나리오 | 결과 | 근거 |
|---|---|---|
| 대조군: 장부 검사(`ledger.verify_run`)만 끈다 → to_rdf | (위조가 유효함을 확인) | 통과했다. 2차 검증 때처럼 기존 검사만으로는 막지 못하는 위조임을 다시 확인했다 |
| (j) → to_rdf (기존 out) | PASS | "RDF 출력 중단(출력 안 씀): 해시 장부와 현재 파일이 다름". 불일치 파일 4개(final.jsonl, review_applied.json, review_manifest.json, review_round1.csv)가 각각 "장부 기록(검토 적용, 5번째 줄) … / 현재 …"으로 나온다. 작업 공간 차이 없음. 출력 3개의 내용과 mtime_ns가 전후로 같다 |
| (j) → to_rdf (새 out 폴더) | PASS | 같은 메시지로 멈춘다. `out_new` 폴더가 생기지 않았다 |
| 대조군: pre에서 1차 accept→reject + manifest round1_sha256 위조, 장부 검사 끔 → apply | (위조가 유효함을 확인) | 통과했다 |
| pre에서 위 위조 → apply | PASS | "검토 적용 중단(출력 안 씀): 해시 장부와 현재 파일이 다름 - review_manifest.json …(2차 생성(1차 확정), 4번째 줄) - review_round1.csv …". final.jsonl과 applied가 생기지 않았다. 작업 공간 차이 없음 |
| post에서 final.jsonl·applied를 지우고 위 위조 → apply 재실행 | PASS | 장부의 apply_finished 기록(5번째 줄)과 달라 멈춘다. 지운 두 파일은 현재 None으로 나온다. 작업 공간 차이 없음 |

#### 3. 해시 장부 (`i3_ledger.py`, `i4_contents.py`, CLI)

**사슬 무결성**
- 방법: post 장부(6줄)의 중간 줄을 변조했다. 6줄의 순서는 round1_created, run_finished, merge_finished, round2_created, apply_finished, to_rdf_output이다.
- 결과: 모두 to_rdf에서 멈췄고, 작업 공간에 차이가 없다.

| 변조 | 결과 | 메시지 |
|---|---|---|
| 3번째 줄 삭제 | PASS | "사슬 끊김: 3번째 줄의 seq가 4" |
| 2번째 줄 `time` 수정 | PASS | "3번째 줄의 prev_sha256이 앞 줄 해시와 다름" |
| 2번째 줄 파일 해시 수정 | PASS | 위와 같음 |
| 2·3번째 줄 순서 바꿈 | PASS | "2번째 줄의 seq가 3" |
| 순서를 바꾸고 seq를 다시 매김 | PASS | "2번째 줄의 prev_sha256이 앞 줄 해시와 다름" |

- 다른 단계: apply(pre), round2(1차까지만 한 r1), resume.collect에서도 중간 줄을 지우면 "사슬 끊김"으로 멈춘다. 셋 다 PASS다.

**장부 없음, 또는 그 run_id 기록 없음**

| 단계 | 장부 파일 없음 | 사슬은 맞지만 이 run_id 기록이 없음 |
|---|---|---|
| to_rdf | PASS ("해시 장부가 없음") | PASS ("해시 장부에 실행 v-forge 기록이 없음(장부 이전 실행은 쓸 수 없음)") |
| apply | PASS | PASS |
| round2 | PASS | PASS (`v-r1`) |
| resume.collect | PASS | PASS |

- "이 run_id 기록 없음"은 모든 줄의 run_id를 다른 값으로 바꾸고 사슬을 다시 계산해 만들었다.
- 8개 모두 작업 공간에 차이가 없다.

**단계마다 장부를 대조하는지**
- 방법: 다른 검사로는 보이지 않고 장부만 볼 수 있는 불일치를 만들었다. 장부의 한 파일 해시를 `f…f`로 바꾸고 사슬을 다시 계산했다.
- 결과

| 단계 | 바꾼 파일 해시 | 결과 |
|---|---|---|
| round2 | merged.jsonl | PASS(멈춤) |
| apply | candidates_premerge.jsonl | PASS(멈춤) |
| to_rdf | final.jsonl | PASS(멈춤) |
| resume | calls.jsonl | PASS(멈춤) |

- 멈춤 메시지에는 "해시 장부와 현재 파일이 다름"과 해당 파일 이름이 나온다.
- 대조군: 장부를 바꾸지 않은 사본에서는 네 단계가 모두 통과한다.

**승인 check / reserve / resolve**

| 시나리오 | check_approval | reserve | resolve |
|---|---|---|---|
| used를 unused로 손으로 고침(used_by·reserved 필드도 지움) | PASS(거부) | PASS(거부) | (해당 없음) |
| usage_check_required를 unused로 손으로 고침 | PASS(거부) | PASS(거부) | PASS(거부) |
| 그 승인 기록이 없는 장부 | PASS(거부) | PASS(거부) | PASS(거부) |
| 장부 파일 없음 | PASS(거부) | (확인 안 함) | PASS(거부) |

- 손으로 고친 경우의 메시지: "승인 상태가 장부와 다름: 파일 unused / 장부 used(used, 3번째 줄)" 또는 "… 장부 usage_check_required(usage_check_required, 6번째 줄)", 그리고 "승인 기록 파일이 장부의 마지막 기록과 다름".
- 장부에 기록이 없는 경우의 메시지: "해시 장부에 승인 99769935a0eff597 기록이 없음(장부 이전 승인은 쓸 수 없음)".
- 거부될 때 승인 파일의 해시는 바뀌지 않았다.
- 대조군
  - 새 승인은 check를 통과한다.
  - finalize 결과는 used(HTTP 200 한 건)와 usage_check_required(AMBIGUOUS)로 나왔다.
  - 정상 장부에서 resolve는 통과하고, 장부의 마지막 사건은 `resolved`, 상태는 `used`가 된다.

**장부 내용**
- 이번 작업에서 생긴 임시 장부 37개를 모두 검사했다.
  - 최상위 키는 `seq, time, run_id, event, files, prev_sha256`과 승인 사건의 `estimate_id, state`뿐이다.
  - `files` 값은 모두 64자리 16진수다.
  - 파일 이름은 meta.json, calls.jsonl, candidates_premerge.jsonl, rejected.csv, raw_response_bundle, merged.jsonl, merge_conflicts.csv, review_round1/2.csv, review_manifest.json, final.jsonl, review_applied.json, `out:`가 붙은 TTL 3개, `<estimate_id>.json`이다.
- merged.jsonl들의 sourceQuote, conditionText, responseText(12자 이상 84개)가 어느 장부에도 없다.
- 키 형태 문자열(`AIza…`, `sk-ant-…`, `GEMINI_API_KEY`, `api_key`)이 0건이다.
- 가짜 키 확인 (`i4_contents.py`)
  - 임시 `.env`에 `GEMINI_API_KEY=<가짜 키>`를 넣었다. `llm_gemini.DOTENV_FILE`은 이 파일로 바꾸고, 환경변수 GEMINI_API_KEY와 GOOGLE_API_KEY는 지웠다.
  - 이 상태로 `run.main --dry-run` → `--execute --approve`를 돌렸다. 대표 청크 1개를 썼고, 가짜 `genai.Client`를 썼다.
    - 예시 확정 검사는 내 프로세스 안에서만 `run.STATUS_CONFIRMED`를 초안 값으로 바꿔 넘겼다. 코드는 수정하지 않았다.
  - 결과
    - rc는 0/0이다.
    - 가짜 클라이언트는 가짜 키로 1회 생성됐고, generate_content는 1회 불렸다.
    - 장부 사건 순서는 approval_created → reserved → round1_created → run_finished → merge_finished → used다.
    - 장부, 실행 폴더, 승인 기록, 캡처한 표준 출력 어디에도 가짜 키가 없다(0건).

**정상 경로**
- CLI로 돌렸다(`$V/w5cli`, 임시 장부).
  1. `run --fake --provider gemini --min-interval-s 0`(60청크). 결과: calls 60, calls_failed 3, candidates 31, rejected 8, merged_into_b 8, new_rules 23, merge_conflicts 2.
  2. 1차 검토를 전부 accept로 채웠다.
  3. `review round2`(0행) → `review apply`(kept 31) → `to_rdf --out-dir`.
- final.jsonl SHA-256은 apply 직후와 to_rdf 뒤 모두 `fb073508…f7d7f9eb`이고, 장부 apply_finished 기록과도 같다.
- 같은 결과를 프로세스 안에서도 확인했다. 장부를 켠 실행과, 장부 검사·기록을 끈 실행의 결과가 같다.
  - final.jsonl 해시가 같다.
  - rules_llm.ttl과 rules_llm_prereview.ttl도 같다.
  - 장부는 결과를 바꾸지 않는다.
- (참고) 이 final 해시의 앞자리 `fb07…`는 2차 검증 3장 (b)의 기록값과 같다.
- `run_shacl.py --data …/seed_plus_rules_llm.ttl --ont ontology_v1/ontology.ttl` → "Conforms: True", "PASS: SHACL 적합", rc 0. 합본 트리플은 3,699개다. 프로세스 안 pyshacl(`inference="none"`)도 적합이다.

#### 4. 호출 간격

- `llm_gemini.DEFAULT_MIN_INTERVAL_S == 7.5`이고, `GeminiAdapter().default_min_interval_s == 7.5`다.
- `prepare(provider="gemini")`의 기본 `min_interval_s`는 7.5다(Anthropic 기본은 0.0).
- 기본값으로 4청크 가짜 실행을 돌렸다.
  - meta `min_interval_s`가 7.5다.
  - 주입한 sleep에는 `[7.5, 7.5, 7.5]`가 들어왔다. 호출 사이에만 기다리므로 3회다.
- 추정 기록 `pacing.min_interval_s`는 7.5다. `pacing`은 `BODY_FIELDS`에 있어 내용 해시에 포함된다.

#### 5. 대표 청크 dry-run

- 명령: `cli.py imaks_kg.extract.run --dry-run --provider gemini --chunk SOP-001:p1:RULE-ST02-04 --approvals-dir $V/w6dry/approvals`
- `IMAKS_EXTRACTION_LEDGER=$V/w6dry/ledger.jsonl`로 임시 장부를 썼다.

| 항목 | 값 | 독립 확인 |
|---|---|---|
| 모델 | gemini-3.8-flash (gemini, free) | 기록 `provider`, `model`, `billing_tier` |
| 청크 수 | 1 | `approved_chunks 1`, `calls 1`, `chunk_filter ['SOP-001:p1:RULE-ST02-04']` |
| 시도 상한 | 3 | `approved_attempts 3`. 계산: min(1×3, 1+10) = 3 |
| 호출 간격 | 7.5초 | 출력 "호출 간격 7.5초", 기록 `pacing.min_interval_s 7.5` |
| 입력 토큰 추정 | 2,173 ~ 2,897 | 글자 8,691. ceil(8691/4) = 2,173, ceil(8691/3) = 2,897 |
| 네트워크 | 0 | NETBLOCK 횟수 모두 0 |
| estimate_id | `8f9bdbde9a7d470b` | `_content_sha` 재계산값이 `content_sha256`과 같고, 앞 16자리가 estimate_id와 같다 |

- 임시 장부에는 `approval_created`(state unused) 1줄이 생겼다.
- 저장소 `extraction/`은 생기지 않았다.

#### 6. 통합

| 항목 | 결과 | 근거 |
|---|---|---|
| `unittest discover -s tests` | PASS | 그대로 실행: `Ran 251 tests in 434.936s OK`. 네트워크 차단 래퍼로 다시 실행(`ut_blocked.py`): `ran 251 fail 0 err 0 skip 0`, NETBLOCK 모두 0, 저장소 `.env` 읽기 0 |
| `check_leakage.py` (기본) | PASS | 작업 시작과 끝 모두 "검사한 파일 60개 … PASS: 금지 컬럼 없음", rc 0 |
| `check_leakage.py preprocessed ontology_v1 kg_build src harness/extraction_ledger.jsonl` | PASS | 시작과 끝 모두 "검사한 파일 61개 … PASS", rc 0 |
| `check_raw_unchanged.py` | PASS | 시작과 끝 모두 "PASS: imaks_data/ 원본 불변 (1121개 파일)" |
| `git check-ignore` | PASS | `harness/extraction_ledger.jsonl` → rc 1(무시 안 됨, 추적 가능. 현재 `??` 미추적 상태). `extraction/` → `.gitignore:234:/extraction/`. `kg_build/` → `:233:/kg_build/`. `.env` → `:151:.env` |
| 저장소 상태 | PASS | 작업 끝에 `extraction/`이 없다. `kg_build/`에는 기존 3개 파일뿐이다. `git status --short`의 수정 파일 목록이 작업 전 스냅샷과 같다 |

### 불합격 사유와 수정이 필요한 위치

- 보완 범위 안에는 없다.

### 미확인 항목과 이유

- 실제 Gemini 응답의 `model_version` 형식: 미확인(실제 호출 금지).
  - 실제 버전 접미사가 `-001` 같은 3자리 숫자가 아니면 정상 응답도 재사용이 거부된다. 예: `-preview-MM-DD`, `-exp-…`.
  - 이 경우 실패는 안전한 쪽(재사용 거부)이다. 첫 실제 호출 뒤 원본 응답의 값을 확인하기를 권한다.
- 장부 파일의 git 커밋 이력에 따른 방어: 미확인. 장부는 아직 커밋되지 않았다(`??`).
- 내가 바꾼 반례 외의 가짜 응답은 구현자의 `tests/extract_fakes.py`에서 나왔다. 그래서 이번 확인은 검사 논리를 확인한 것이고, 실제 모델 출력의 다양성은 대표하지 못한다.

### 판정 밖의 관찰

1. **장부를 다시 기록하면 위조가 통과한다.**
   - (j) 위조 뒤 `ledger.record_run(..., "apply_finished", …)`로 정상 형식의 줄을 하나 덧붙이면 to_rdf가 통과한다. 비밀값 없이 누구나 덧붙일 수 있다.
   - 구현 보고서 15장 "한계"가 이미 적은 내용이다. 마지막 줄만 고치거나 지우는 경우도 같다.
   - 실제 방어선은 장부를 커밋하고 git diff·이력을 리뷰하는 것이다. 장부가 아직 미추적(`??`)이므로, 첫 실제 실행 전에 빈 장부를 커밋해 두기를 권한다.
2. **장부 사건 순서.** `run_calls` 안에서 `write_round1`이 먼저 기록돼, 장부 순서가 round1_created → run_finished → merge_finished다. 검사는 파일별 최근 기록으로 하므로 동작에는 영향이 없다. 다만 사람이 장부를 읽을 때 순서가 직관과 다르다.
3. **(2차 검증 14장 5에서 이어짐)** `run.py` 315행 `--model` 도움말 "Gemini는 반드시 사용자가 정한다"가 아직 남아 있다. 기본값 `gemini-3.8-flash`가 있는 지금 동작과 맞지 않는다.


---

## 실행 전 보완 3건 검증 (2026-10-14)

작성자는 verifier(독립 검증)다. 범위는 구현 보고서 17장의 보완 3건(P1 인터럽트·승인 상태, P1 동시성, P2 최소 호출 간격)과 회귀·통합이다. 위의 모든 판정과 기록은 고치지 않았다.

### 판정: **PARTIAL**

- 안전에 직결되는 동작은 모두 PASS다.
  - 인터럽트·오류·강제 종료 뒤 승인 상태가 정해진 대로 나온다. 실제 CLI 경로(`run.main --execute`)에서 사용하지 않았음이 확실하지 않은데 unused로 돌아간 경우는 없었다.
  - 동시 예약, 장부 동시 쓰기, 잠금을 쥔 채 강제 종료, 장부와 파일 사이 실패에서 모두 닫힌 쪽으로 멈춘다.
  - 호출 간격, 회귀, 통합도 모두 PASS다.
- FAIL은 2개다. 둘 다 비용이 나가는 안전 문제는 아니다.
  1. 1(e) 부분 실행 정보: 대기 중 끊기면 `partial_run.not_completed`가 빈 목록으로 남는다. 실제로는 2개 청크가 실행되지 않았다.
  2. 1 코드 확인(unused 복원 조건): `finalize`의 journal 없는 경로에서는 AMBIGUOUS(500) 시도가 있어도 unused로 돌아간다. 현재 `run.main`은 항상 journal을 넘기므로 CLI로는 이 경로에 닿지 않는다.

### 지킨 원칙

- **실제 API 호출 0회.** generate, count_tokens, models.list, 실제 클라이언트로 `--execute`, `--list-models`를 하나도 부르지 않았다.
  - 모든 스크립트와 자식 프로세스는 `netblock.py`를 먼저 불러왔다. 이 파일은 다음을 막고 횟수를 센다.
    - `socket.connect`, `create_connection`
    - `genai.Client`, `anthropic.Anthropic` 생성
    - 저장소 `.env` 읽기
  - 실행이 끝날 때마다 횟수는 `{'genai.Client': 0, 'anthropic.Anthropic': 0, 'socket': 0, 'repo_env_read': 0}`였다. 전체 unittest(감싼 실행)도 같다.
  - `--execute`는 `llm_gemini.genai.Client`를 내 가짜 클래스로 바꿔서만 돌렸다. 키는 임시 `.env`의 가짜 키를 썼다.
  - 예시 확정 검사는 내 프로세스 안에서만 `run.STATUS_CONFIRMED`를 초안 값으로 바꿔 넘겼다.
- **열지 않은 것:** `imaks_data/kg_seed/ground_truth.csv`, `data/`, `evaluation/`, `imaks_data/human/`, 저장소 `.env`.
- **examples.json은 바꾸지 않았다.** 작업 전후 SHA-256이 `e83bbc2b…80ec7`로 같다.
- **임시 위치:** 세션 scratchpad `…/scratchpad/v4/`(아래에서 `$V4`) 밖으로는 아무것도 쓰지 않았다.
  - 스크립트: `$V4/scripts/`
    - 공통: `netblock.py`, `cli.py`, `c4.py`, `ut_blocked.py`
    - 항목별: `p1.py`, `p1h.py`, `h_child.py`, `p2.py`, `conc_child.py`, `p3.py`, `p4.py`, `p4b.py`, `obs_journal.py`, `obs_corrupt.py`
  - 장부와 잠금 폴더는 사례마다 `$V4/w/<사례>/` 아래 새로 만들었다.
    - 프로세스 안: `ledger.LEDGER_OVERRIDE`, `locks.LOCK_DIR_OVERRIDE`
    - 자식 프로세스와 CLI: `IMAKS_EXTRACTION_LEDGER`, `IMAKS_EXTRACTION_LOCKS`
  - 시작할 때 `settings.EXTRACTION_LOCKS`(= 저장소 `extraction/.locks`)를 확인했다. `c4.py`는 저장소 `extraction/`이 있으면 시작하지 않는다(assert). 스크립트마다 끝에서도 다시 확인했다.
- **저장소 장부 `harness/extraction_ledger.jsonl`:**
  - 작업 전: 0바이트, SHA-256 `e3b0c442…b855`
  - 작업 후: 0바이트, 같은 해시
  - 스크립트 9개가 끝날 때마다 확인했고 매번 PASS였다.
- **저장소 불변:** 작업 전후로 다음 폴더의 파일 113개 SHA-256 목록이 같다(`diff` 출력 없음).
  - 대상: `src`, `tests`, `harness`, `ontology_v1`, `reports`, `kg_build`, `preprocessed`, `guards`, `.claude`
  - `git status --short` 출력도 작업 전 스냅샷과 같다.
- **판정 근거:** 구현 보고서 17장은 대상 위치를 찾는 데만 썼다. 구현자 테스트(`tests/test_extract_safety.py`, `tests/extract_proc_helper.py`)의 사례는 쓰지 않고 모두 내 스크립트로 다시 만들었다.
  - 구현자 코드에서 빌려 쓴 것은 하나뿐이다. 정상 200 응답 본문은 `tests/extract_fakes.build`로 만들었다.
  - 오류 예외(401, 429 PerDay·PerMinute, 500, 503, 504, ReadTimeout, ConnectError)는 `google.genai.errors`와 `httpx`로 내가 직접 만들었다.
- **실행 환경:** `.venv/Scripts/python.exe`, `PYTHONPATH=src`, `PYTHONIOENCODING=utf-8`.

### 항목별 결과

| 항목 | 결과 | 근거 |
|---|---|---|
| 1(a) 준비 오류(호출 전) → unused | **PASS** | 아래 1 |
| 1(b) 첫 호출 중 KeyboardInterrupt → usage_check_required, 재실행 거부 | **PASS** | 아래 1 |
| 1(c) 200 뒤 해석 예외 → used, 청크 실패, 200 유지 | **PASS** | 아래 1 |
| 1(d) 앞 청크 성공 뒤 보내는 중 KeyboardInterrupt → usage_check_required, 200 증거 유지 | **PASS** | 아래 1 |
| 1(e) 앞 청크 성공 뒤 대기 중 끊김 → used | **PASS** | 아래 1 |
| 1(e) 부분 실행 정보(완료·미완료 청크) | **FAIL** | 아래 1, 불합격 사유 1 |
| 1(f) 서버 오류 응답만(401, 429 PerDay) → unused | **PASS** | 아래 1 |
| 1(g) 타임아웃·500 → usage_check_required | **PASS** | 아래 1 |
| 1(h) 실제 프로세스를 예약·전송 중 강제 종료 → usage_check_required | **PASS** | 아래 1 |
| 1 코드: finally/BaseException 경로가 보수적인 경우를 unused로 되돌리지 않음 | **PASS** | 아래 1 코드 확인 |
| 1 코드: unused 복원은 모든 경로에서 "사용 안 함 확실"이 필요 | **FAIL** | 아래 1 코드 확인, 불합격 사유 2 |
| 2(a) 2·4개 프로세스 동시 예약, 각 5회 → 정확히 1개 성공 | **PASS** | 아래 2 |
| 2(b) 여러 프로세스 장부 동시 덧붙이기 → seq 연속, 사슬 유효 | **PASS** | 아래 2 |
| 2(c) 잠금을 쥔 채 강제 종료 → 다음 프로세스가 잠금 획득, unused로 복원 안 됨 | **PASS** | 아래 2 |
| 2(d) 예약 실패한 실행은 가짜 생성 0회(run_calls 2개 경쟁 5회) | **PASS** | 아래 2 |
| 2(e) 장부 기록과 파일 쓰기 사이 실패(os.replace) → 닫힌 쪽 | **PASS** | 아래 2 |
| 2(f) 코드: 잠금 순서, try/finally 해제, 시간 초과 메시지 | **PASS** | 아래 2 코드 확인 |
| 3(a)~(g) 최소 호출 간격 | **PASS** | 아래 3 |
| 4 회귀(가드, 승인, 이어서 하기, 장부, served model, 외부 전송 허용 목록) | **PASS** | 아래 4 |
| 4 `unittest discover -s tests` | **PASS** | 아래 4 |
| 4 `check_leakage.py` 기본, 지정 폴더 | **PASS** | 아래 4 |
| 4 `check_raw_unchanged.py` | **PASS** | 아래 4 |
| 4 Gemini 가짜 전체 경로 + 합본 SHACL | **PASS** | 아래 4 |
| 4 `git check-ignore` | **PASS** | 아래 4 |

#### 1. 인터럽트와 승인 상태 (`p1.py`, `p1h.py`)

**방법**
- 모든 사례는 실제 CLI 함수 `run.main --execute --provider gemini`를 통했다. 순서는 dry-run으로 추정 기록을 만들고 → 가짜 `genai.Client`로 `--execute`를 돌리는 것이다.
- 가짜 클라이언트의 `models.generate_content`가 사례마다 정한 동작을 한다. 정상 응답, 예외, KeyboardInterrupt, 무한 대기 중 하나다.
- 확인한 것
  - 승인 파일의 state
  - 장부에서 다시 만든 state(`ledger.approval_state`)
  - 장부 사건 순서
  - `실행 폴더/attempts.jsonl`의 (청크, 시도, phase) 순서
  - 승인 history 마지막 항목의 reason과 evidence
- 기본 청크: `SOP-001:p1:RULE-ST01-02`(이하 ST01-02), `SOP-001:p1:RULE-ST02-02`(ST02-02), `SOP-003:p1:table1:chunk`

| 사례 | 승인 최종 상태(파일/장부) | attempts.jsonl·증거 | 결과 |
|---|---|---|---|
| (a1) 예약 뒤 요청 파일 쓰기에서 OSError | unused/unused, 장부 `approval_created → reserved → released` | journal 0줄, 생성 0회. reason "보낸 시도 없음(준비 단계에서 끝남): OSError(중단)". 그 뒤 `check_approval` 통과(파일 = 장부) | PASS |
| (a2) 같은 자리에서 KeyboardInterrupt | unused/unused, KeyboardInterrupt를 다시 던짐 | 생성 0회 | PASS |
| (a3) 예약 전 오류(`meta_base`에서 OSError) | unused, 장부 `approval_created`뿐 | reserved 사건 없음 | PASS |
| (b) 첫 `generate_content` 안에서 KeyboardInterrupt | usage_check_required/usage_check_required | journal은 ST01-02#1 prepared → sending으로 끝남. 증거 `uncertain ['…ST01-02#1(sending)']` | PASS |
| (b) 이어서 같은 승인으로 `--execute` | 거부(rc 2) | "쓸 수 없는 승인 상태 usage_check_required … resolve로 해결해야 한다". 클라이언트 생성 0, 생성 0, 승인 파일 해시 같음, 실행 폴더 안 생김 | PASS |
| (c1) 첫 청크 200 뒤 `llm_gemini.interpret`에서 ValueError | used/used | journal ST01-02: prepared → sending → http_200_received → interpret_failed. calls.jsonl ST01-02: ok False, http_200 True, failure "응답 해석 실패: ValueError: bad parse (verifier)". 두 번째 청크는 정상(interpreted). 증거 `http_200_chunks`에 두 청크가 있다. meta counts calls_failed 1 | PASS |
| (c2, 추가) 200 뒤 해석 중 KeyboardInterrupt | used/used | journal이 http_200_received로 끝남. unused로 돌아가지 않음 | PASS |
| (d) ST01-02 200 → ST02-02 보내는 중 KeyboardInterrupt(3청크) | usage_check_required/usage_check_required | 증거 `sent_attempts 2, http_200_chunks ['…ST01-02'], uncertain ['…ST02-02#1(sending)']`. history completed `['…ST01-02']`. `raw/response/SOP-001__p1__RULE-ST01-02.json`이 남아 있음. 재실행은 거부(rc 2, 생성 0) | PASS |
| (e) ST01-02 200 → 호출 간격 대기(`time.sleep`, 7.48초 요청)에서 KeyboardInterrupt(3청크, 간격 7.5) | used/used, `partial_run` 있음 | 생성 1회, sleep 1회. `partial_run = {completed: ['…ST01-02'], not_completed: []}` | 상태 PASS, 부분 정보 **FAIL** |
| (f1) 401 UNAUTHENTICATED만 | unused/unused, 마지막 사건 released | journal prepared → sending → http_error_response. reason FATAL_AUTH | PASS |
| (f2) 429 RESOURCE_EXHAUSTED + QuotaFailure `…PerDay…`만 | unused/unused, released | 같은 순서. reason FATAL_QUOTA | PASS |
| (f3, 추가) 429 PerMinute 3회 → TRANSIENT_EXHAUSTED | unused | 3시도 모두 http_error_response | PASS |
| (g1) httpx.ReadTimeout | usage_check_required/usage_check_required | journal 끝이 transport_error. 재실행 거부(rc 2, 생성 0) | PASS |
| (g2) 500 INTERNAL | usage_check_required/usage_check_required | journal 끝이 http_error_response(AMBIGUOUS 500). 재실행 거부 | PASS |
| (g3, 추가) 504 / (g6, 추가) ConnectError | usage_check_required | http_error_response / transport_error | PASS |
| (g4, 추가) 200 뒤 다음 청크 500 | usage_check_required | 증거 http_200_chunks `['…ST01-02']`, uncertain `['…ST02-02#1(AMBIGUOUS 500)']`. 불확실한 시도가 우선함 | PASS |
| (g5, 추가) 분류되지 않는 RuntimeError(create 안) | usage_check_required | journal이 sending으로 끝남 | PASS |
| (추가) attempts.jsonl이 깨진 JSON | usage_check_required | `read_journal`이 None을 돌려줌(`obs_corrupt.py`) | PASS |

**(h) 실제 프로세스 강제 종료** (`p1h.py`, `h_child.py`)
- 방법
  - 자식 프로세스가 `run.main --execute`를 돌린다.
  - 가짜 `generate_content`는 표식 파일을 쓰고 3600초 잠든다(전송 중).
  - "before_send" 변형은 예약 뒤 요청 파일 쓰기에서 잠든다(보내기 전).
  - 부모는 표식을 확인한 뒤 아래를 검사하고, 자식을 `terminate()` 또는 `kill()`로 끝낸다.

| 변형 | 자식이 살아 있을 때 | 종료 뒤 첫 `check_approval` | 결과 |
|---|---|---|---|
| 전송 중 + terminate | state reserved. check 거부("다른 실행이 예약 중(실행 잠금을 쥐고 있음)"), reserve 거부("상태 reserved") | 파일·장부 모두 usage_check_required. reason "예약한 실행이 끝맺지 못함(프로세스 비정상 종료). 불확실한 시도 1건 … ['…ST01-02#1(sending)']". check는 usage_check_required로 거부. 다시 검사해도 파일이 바뀌지 않음. 실행 잠금을 다시 잡을 수 있음 | PASS |
| 전송 중 + kill | 같음 | 같음 | PASS |
| 보내기 전 + kill | 같음 | usage_check_required. reason "…보낸 시도 없음(준비 단계에서 끝남)". 비정상 종료는 journal 내용과 상관없이 unused로 돌아가지 않는다 | PASS |

**코드 확인** (`approval.py`, `run.py`, `llm.py`)
- 승인 state를 unused로 쓰는 곳은 세 군데다(`grep`).
  - 추정 생성(124행)
  - `finalize`의 released 분기(360행). `decide`가 UNUSED를 돌려줄 때만 간다(325·326행).
  - `resolve --as unused`(사람이 `--note`를 붙여 usage_check_required에서만)
- `recover_if_abandoned`는 usage_check_required로만 옮긴다(388행).
- `decide`(289~326행)의 판단
  - 불확실한 시도(sending 뒤 응답 기록 없음, transport_error, SURE_NO_GENERATION 밖의 오류)가 하나라도 있으면 usage_check_required다. 이 판단이 200보다 먼저다.
  - unused는 다음 둘 중 하나일 때만이다: 보낸 시도가 없음, 또는 보낸 시도가 모두 FATAL_*·TRANSIENT_* 응답으로 끝남.
- `call_with_policy`(399~460행)는 `sending`을 `client.create` 바로 앞에 남긴다. 응답 단계(`http_200_received` 등)는 해석 전에 남긴다. 그래서 그 사이 어디서 끊겨도 "sending만 있음", 곧 불확실로 남는다.
- `run.main`(420~440행)
  - `except BaseException`에서 오류만 기록하고, finally에서 journal을 증거로 `finalize`한다.
  - "인터럽트였다"는 이유만으로 unused가 되는 분기는 없다.
  - finalize가 실패하면 승인은 reserved로 남고 실행 잠금은 안쪽 finally에서 풀린다. 그러면 다음 검사가 usage_check_required로 옮긴다.
  - 그래서 **finally/BaseException 경로는 보수적인 경우를 unused로 되돌리지 않는다: PASS.**
- **unused 복원 조건: FAIL.** journal이 없는 경로 두 개에서는 "사용 안 함 확실"이 아닌데도 unused가 된다(`obs_journal.py`).
  - (i) `finalize(..., journal=None)`(이전 호출 방식): `_legacy_events`(271~286행)는 `phase` 키가 있는 시도를 그 단계 하나로만 옮기고 `sending`을 넣지 않는다. 지금의 `call_with_policy`가 만드는 시도 기록은 모두 `phase`를 가진다. 그래서 `{error_class AMBIGUOUS, status 500, phase http_error_response}` 시도가 "보내지 않음"으로 읽힌다.
    - 재현: reserve 뒤 `finalize(p, rid, outcome(AMBIGUOUS 500), "")`의 결과가 **unused**다.
  - (ii) journal 경로를 넘겼지만 파일이 없을 때: `read_journal`이 []를 돌려주고, 메모리에 있는 outcome의 시도 기록은 보지 않는다(http_200 수만 본다).
    - 재현: 같은 AMBIGUOUS outcome + 없는 journal 경로 → **unused**.
    - 구현 보고서 17-1 "남은 한계"가 인정한 내용이다.
  - 영향 범위: 현재 `run.main`은 항상 `journal=out_root/run_id/attempts.jsonl`을 넘긴다(434행). 이 파일은 `run_calls`가 쓰는 파일과 같다(196행). 그래서 (i)은 CLI로는 닿지 않는다. (ii)는 실행 중 journal이 지워진 경우에만 생긴다. 위 실제 CLI 사례 17개(재실행 거부 확인 4회 별도)와 실제 프로세스 사례 3개에서 잘못된 unused는 0건이었다.

#### 2. 동시성 (`p2.py`, `conc_child.py`, 실제 자식 프로세스)

- 동기화 방법: 자식이 `ready_<tag>`를 쓰고 `go` 파일이 생길 때까지 1ms 간격으로 돈다. 부모는 모든 ready를 확인한 뒤 `go`를 만든다.
- 자식은 모두 `IMAKS_EXTRACTION_LEDGER`, `IMAKS_EXTRACTION_LOCKS`로 그 사례의 임시 장부·잠금 폴더를 쓴다.

| 항목 | 결과 | 근거 |
|---|---|---|
| (a) 2개 프로세스가 같은 승인을 `approval.reserve`, 5회 | PASS | 5회 모두 승자 1개(p0, p0, p1, p1, p0). 패자 메시지 "승인 예약 실패: 상태 reserved(다른 실행이 쓰는 중이거나 이미 씀)". 파일 reserved_by_run_id = 승자. 장부 `[approval_created, reserved]` 2줄뿐. `verify_approval` 빈 목록 |
| (a) 4개 프로세스, 5회 | PASS | 5회 모두 승자 1개(p3, p3, p0, p2, p1). 나머지는 위와 같음 |
| (b) 4개 프로세스 × 25번 `ledger.append` | PASS | 100줄, seq 1..100 연속, `ledger.load` 사슬 검사 통과. 프로세스별 25줄씩 |
| (b) 4개 프로세스 × 승인 6개씩(write_estimate → reserve → finalize) | PASS | 1 + 4×6×3 = 73줄, 사슬 유효. 승인 24개 모두 `[approval_created, reserved, released]`이고 파일과 장부가 같다. 오류 0 |
| (c) 자식이 reserve 뒤 실행·승인·장부 잠금을 모두 쥐고 잠든 상태 | PASS | 부모의 잠금 시도는 모두 거부된다: 승인 0.3초 → "잠금을 얻지 못함(승인 …, 0.3초): 다른 프로세스가 쓰는 중"(0.33초), 장부도 같은 형식(0.33초), 실행 잠금은 0초 |
| (c) `kill` 뒤 | PASS | 세 잠금 모두 다시 잡힘. `ledger.append` 정상. `check_approval`이 usage_check_required로 옮기고 거부함(파일·장부 같음, unused 아님) |
| (d) 2개 프로세스가 실제 `run.run_calls`로 경쟁(예약은 `on_first_call`), 5회 | PASS | 5회 모두 `[(실패, 호출 0), (성공, 호출 1)]`. 패자 오류 "승인 예약 실패: 상태 reserved…". 생성 횟수는 자식 안의 셈 클라이언트로 쟀다 |
| (d, 추가) 2개 프로세스가 `run.main --execute`로 경쟁, 3회 | PASS | 3회 모두 rc `[0, 2]`, 생성 `[0, 1]`, 최종 used. 패자는 "쓸 수 없는 승인 상태 reserved … 다른 실행이 예약 중" 2회, "실제 실행 거부: 잠금을 얻지 못함(승인 … 실행, 0초)" 1회 |
| (e) reserve 중 `os.replace` 실패 | PASS | OSError가 남. 장부 reserved / 파일 unused(어긋남). 그 뒤 `check_approval` 거부("승인 기록 파일이 장부의 마지막 기록과 다름"), `reserve` 거부("해시 장부와 다름 … 파일 unused / 장부 reserved"), `run.main --execute` rc 2(클라이언트 0, 생성 0). 승인 파일과 장부 해시는 변하지 않음 |
| (e) finalize(used) 중 실패 | PASS | 장부 used / 파일 reserved. check·reserve·execute 모두 거부. 복구도 상태를 옮기지 않음(어긋난 채, unused 아님) |
| (e, 추가) finalize(released) 중, 비정상 종료 복구 중 실패 | PASS | 장부 unused / 파일 reserved, 장부 usage_check_required / 파일 reserved. 둘 다 check·reserve·execute 거부, 생성 0 |
| (f) 잠금 시간 초과 메시지(기본 10초) | PASS | 자식이 승인 잠금을 쥔 동안 `approval.reserve` → 10.0초 뒤 "잠금을 얻지 못함(승인 f03c30afd3d4a26c, 10초): 다른 프로세스가 쓰는 중". 파일·장부 변화 없음. 장부 잠금을 쥔 동안 `ledger.append` → 10.0초 뒤 "잠금을 얻지 못함(해시 장부, 10초): …" |

**코드 확인 (2(f))**
- 잠금을 잡는 곳 전부(`grep approval_lock|ledger_lock|run_lock`)
  - 장부 잠금: `ledger.append`(75행)에서만 잡는다. 그 안에서는 읽기, 사슬 검사, 쓰기만 하고 승인 코드를 부르지 않는다. 그래서 **장부 잠금을 쥔 채 승인 잠금을 잡는 경로는 없다.**
  - 승인 잠금: `write_estimate`(156), `reserve`(234), `finalize`(332), `recover_if_abandoned`(379), `resolve`(406). 모두 그 안에서 `_commit` → `ledger.append` 순서다(승인 → 장부).
  - 실행 잠금: `run.main`(402)은 다른 잠금 없이 잡는다. `recover_if_abandoned`(375)는 timeout 0이고 승인 잠금보다 먼저 잡는다. `check_approval`은 승인 잠금 밖에서 recover를 부른다. 그래서 순서가 항상 실행 → 승인 → 장부로 같다.
- 해제
  - 승인·장부 잠금은 `with`(`FileLock.__exit__`)로 푼다.
  - 실행 잠금은 다음에서 푼다: `run.main` 클라이언트 생성 실패 시(410행), 본 실행의 finally 안쪽 finally(437~438행), recover의 finally(393~394행).
  - 시간 초과 때는 핸들을 닫고 ExtractError를 던진다(80~81행).
- 시간 초과 메시지: 위 실측과 같다.

#### 3. 최소 호출 간격 (`p3.py`, 주입한 시계·sleep, 실제 대기 0)

- 방법
  - 가짜 시계(`clock()`)는 sleep만큼만 흐른다. 원하면 호출마다 정한 시간을 더한다.
  - `run.run_calls(..., sleep=, clock=)`를 직접 불렀다.
  - 모든 실행 중 실제 `time.sleep` 호출은 0회였고, 사례당 실제 소요는 0.4초 미만이었다.

| 항목 | 기대 | 실측(sleep 인자 / 시도 시작 간격) | 결과 |
|---|---|---|---|
| (a) 3청크 모두 200 | [7.5, 7.5] | [7.5, 7.5] / [7.5, 7.5]. meta.pacing_waits_s [0.0, 7.5, 7.5] | PASS |
| (a, 추가) 호출에 3초 걸림 | 7.5 − 3 = 4.5 | [4.5, 4.5] / [7.5, 7.5]. 마지막 시도 시작 기준 | PASS |
| (a, 추가) 호출에 9초 걸림 | 대기 없음 | [] / [9, 9] | PASS |
| (b) 같은 청크 재시도(503, retry_after 없음, backoff 2.0) | 7.5 | [7.5] / [7.5]. retries wait_s [7.5] | PASS |
| (b, 추가) 호출에 6초 걸린 뒤 재시도 | max(7.5−6, 2.0) = 2.0 | [2.0] / [8.0] | PASS |
| (c) 429 PerMinute, RetryInfo 3s | 7.5 | [7.5] / [7.5]. wait_s [7.5] | PASS |
| (d) RetryInfo 20s | 20 | [20.0] / [20.0]. wait_s [20.0] | PASS |
| (e) 재시도(20) 뒤 다음 청크 | [20, 7.5] | [20.0, 7.5]. 시작 시각 1000.0 → 1020.0 → 1027.5 | PASS |
| (e, 추가) 503 두 번 뒤 다음 청크 | [7.5, 7.5, 7.5] | [7.5, 7.5, 7.5] | PASS |
| (f) 이중 대기 없음 | 시도 사이마다 sleep 1회 | 시도 3회에 sleep 2회 [7.5, 20.0]. sleep 목록 = 시작 간격 = retries wait_s | PASS |
| (f) `llm.Pacer` 단위 | wait() 0 → 1초 뒤 wait(3) 6.5 → wait(20) 20 → wait() 7.5 | [0.0, 6.5, 20.0, 7.5], sleep [6.5, 20.0, 7.5] | PASS |
| (g) 승인 청크 2, 시도 상한 min(2×3, 2+10) = 6, 첫 청크 RetryInfo 20 1회 | 실제 청크 2·시도 3, 재시도 1(wait 20) | approved 2/6, actual 2/3, retries 1(wait_s 20.0), pacing_waits [0.0, 20.0, 7.5], counts.retries 1, chunk_attempts {ST01-02: 2, ST02-02: 1} | PASS |
| (g) 상수 | 3 / 10 / 7.5 / 2.0 | `MAX_ATTEMPTS_PER_CHUNK` 3, `MAX_RETRIES_PER_RUN` 10, `DEFAULT_MIN_INTERVAL_S` 7.5, `BACKOFF_BASE_S` 2.0 | PASS |
| (g) 1청크, 503이 계속 | 3시도 뒤 TRANSIENT_EXHAUSTED, 상한 3 | 시도 3, sleep [7.5, 7.5], abort TRANSIENT_EXHAUSTED, approved_attempts 3 | PASS |
| (g) 실행당 재시도 예산: 12청크가 각각 503 한 번 | 상한 min(36, 22) = 22. 재시도 10 뒤 11번째 청크에서 중단. 시도 2×10 + 1 = 21, sleep 20 | 재시도 10, 시도 21, sleep 20, TRANSIENT_EXHAUSTED(`SOP-001:p1:RULE-ST02-04`), 상한 22 | PASS |
| (g) `run.main --execute` 기본 간격(`time.sleep`·`time.monotonic`을 가짜 시계로 바꿈), 첫 시도 429(3s) | sleep [7.5, 7.5] | rc 0, sleep [7.5, 7.5], meta min_interval_s 7.5, pacing_waits [0.0, 7.5, 7.5], approved 2/6, actual 2/3, retries wait_s [7.5], 추정 기록 pacing `{min_interval_s 7.5, max_attempts_per_chunk 3, max_retries_per_run 10}`, 승인 used | PASS |

#### 4. 회귀와 통합 (`p4.py`, `p4b.py`, CLI)

| 항목 | 결과 | 근거 |
|---|---|---|
| 가드: apply 뒤 final.jsonl 줄 삭제 → to_rdf | PASS | "RDF 출력 중단(출력 안 씀): 검토 기록과 파일이 다름 - final.jsonl이(가) 기록 이후 바뀜". 출력 폴더 안 생김 |
| 가드: round2 뒤 1차 결정 accept → reject → apply | PASS | "검토 적용 중단(출력 안 씀): 검토 기록(manifest) 불일치". final.jsonl 안 생김 |
| 장부: 가운데 줄 삭제 → to_rdf | PASS | "해시 장부 사슬 끊김: 3번째 줄의 seq가 4". 원래대로 돌린 대조군은 통과 |
| 승인: `--approve` 없음, 내용 고침(calls 99), 청크 수 초과(3 > 2), 모델 다름(gemini-3.8-pro), used 재사용 | PASS | 다섯 경우 모두 rc 2, 클라이언트 생성 0. 메시지 순서대로 "--approve <estimate_id>가 없음", "추정 기록 내용이 해시와 다름", "청크 수: 승인 2 < 현재 3", "fingerprint.model: 추정 때 gemini-3.8-flash / 현재 gemini-3.8-pro", "쓸 수 없는 승인 상태 used". 대조군(정상 승인)은 rc 0, 생성 2, used |
| 승인: 타임아웃 → usage_check_required → `approval resolve --as unused --note …` | PASS | rc 0, 파일·장부 unused, 장부 마지막 사건 resolved |
| 이어서 하기 + served model | PASS | served `-lite`·`-preview`는 재사용 거부("served model: gemini-3.8-flash-lite / 요청 모델 …"). `-001`과 정확 일치는 2청크를 재사용. `_served_ok` 7가지 기대값과 같음 |
| 외부 전송 허용 목록 | PASS | `DS-ELEC-3300:p1:text1`은 "doc_id DS-ELEC-3300는 외부 전송 허용 목록(SOP-001~004) 밖", SOP 청크는 빈 문자열. ctx에 데이터시트 청크를 끼워 넣고 `run_calls` → 호출 0회로 멈춤. `--chunk DS-…`는 prepare에서 거부 |
| `unittest discover -s tests` | PASS | 그대로 실행: `Ran 269 tests in 492.969s OK`. 네트워크 차단 래퍼로 다시 실행(`ut_blocked.py`): `ran 269 fail 0 err 0 skip 0`(513.7초), NETBLOCK 횟수 모두 0. 두 실행 뒤 모두 저장소 장부 0바이트, `extraction/` 없음 |
| `check_leakage.py` (기본) | PASS | "검사한 파일 61개, 금지어 8개, 컬럼 전용 11개 / PASS: 금지 컬럼 없음", rc 0 |
| `check_leakage.py preprocessed ontology_v1 kg_build src harness/extraction_ledger.jsonl` | PASS | "검사한 파일 62개 … PASS", rc 0 |
| `check_raw_unchanged.py` | PASS | "PASS: imaks_data/ 원본 불변 (1121개 파일)", rc 0 |
| Gemini 가짜 전체 경로(CLI, 임시 장부·잠금 환경변수) | PASS | `run --fake --provider gemini --min-interval-s 0`(60청크) → calls 60, calls_failed 3, candidates 31, rejected 8, merged_into_b 8, new_rules 23, merge_conflicts 2. 1차 33행 accept → round2(0행) → apply(kept 31) → to_rdf. rules_llm 트리플 533, 합본 3,699. final.jsonl SHA-256 `fb073508…f7d7f9eb`(앞 검증들과 같음). attempts.jsonl 240줄 = 60청크 × (prepared, sending, http_200_received, interpreted). 장부 사건 순서 round1_created, run_finished, merge_finished, round2_created, apply_finished, to_rdf_output |
| 합본 SHACL | PASS | `run_shacl.py --data …/seed_plus_rules_llm.ttl --ont ontology_v1/ontology.ttl` → "Conforms: True", "PASS: SHACL 적합" |
| `git check-ignore` | PASS | `extraction/.locks/`와 `extraction/.locks/approval_x.lock` → `.gitignore:234:/extraction/`(rc 0, 무시됨). `harness/extraction_ledger.jsonl` → rc 1(무시 안 됨, 추적 가능. 현재 `??`) |

### 불합격 사유와 수정이 필요한 위치

1. **1(e) 부분 실행 정보의 미완료 청크가 비어 있다.**
   - 현상: `run_calls`는 `outcome["not_completed"]`를 abort 분기(`run.py` 241행)에서만 채운다. BaseException으로 빠져나가면 갱신되지 않는다.
   - 그래서 `approval.finalize`(345·356행)가 남기는 `partial_run`과 history의 `not_completed`가 `[]`가 된다.
   - 재현: 3청크 중 1청크 200 뒤 대기 중 KeyboardInterrupt → `partial_run = {completed: ['…ST01-02'], not_completed: []}`. 실제로는 ST02-02와 SOP-003 table1이 실행되지 않았다.
   - 같은 원인으로 1(c2)(해석 중 인터럽트)에서는 `completed`도 `[]`다. 200을 받은 청크는 `evidence.http_200_chunks`에만 있다.
   - 1(d)의 usage_check_required 기록도 `not_completed: []`다.
   - 요구 근거: `approval.py` 머리말 21행 "used에는 부분 실행 정보(완료·미완료 청크)를 남긴다", 구현 보고서 17-1 "used + partial_run(완료·미완료 청크)".
   - 수정 위치: `run.py` `run_calls`. 루프 진행에 맞춰 outcome의 completed·not_completed를 갱신하거나, finalize에서 승인 청크 목록 − 완료 청크로 계산한다.
2. **journal 없는 finalize 경로에서는 "사용 안 함 확실"이 아닌데도 unused로 돌아간다.**
   - (i) `approval._legacy_events`(271~286행): `phase`가 있는 시도에 `sending`을 넣지 않는다. 그래서 `finalize(journal=None)`이 AMBIGUOUS(500) 시도를 "보내지 않음"으로 보고 unused를 돌려준다(재현함).
   - (ii) journal 경로는 있지만 파일이 없을 때: outcome의 시도 기록을 보지 않고 unused가 된다(재현함, 구현 보고서가 인정한 한계).
   - 현재 CLI(`run.main`)로는 (i)에 닿지 않는다. 그래서 비용 위험은 낮다.
   - 수정 위치: `approval.py` `_legacy_events`, `finalize`. 다음 중 하나다.
     - phase가 있는 시도도 `sending`을 함께 넣는다.
     - journal이 없거나 비었는데 outcome에 시도가 있으면 outcome으로 판단하거나 usage_check_required로 둔다.

### 미확인 항목과 이유

- 네트워크 파일 시스템, POSIX(`fcntl.flock`) 경로: 미확인. 이 기계는 Windows 로컬 디스크뿐이다.
- 운영체제나 저장 장치 수준의 쓰기 손실(fsync 뒤 전원 차단 등): 미확인(흉내 낼 수 없음).
- 실제 Gemini SDK가 전송 중 KeyboardInterrupt를 받았을 때의 내부 동작(재시도, 연결 정리): 미확인(실제 호출 금지). 가짜 클라이언트 안에서 인터럽트를 냈다.
- 실제 응답의 `model_version` 형식: 앞 보완 확인과 같이 미확인.

### 판정 밖의 관찰

1. **해석 실패 청크는 원본 응답 본문이 남지 않는다.**
   - 1(c1)에서 `raw/response/<청크>.json`의 키는 `call_failed, request_id, error, attempts`뿐이다. `interpret_failed` 결과의 `raw`가 비어 있기 때문이다.
   - 200을 받은 사실은 journal, calls.jsonl(`http_200: true`), 승인 증거에 남는다. 다만 비용을 쓴 응답 본문을 나중에 다시 해석하거나 이어서 하기로 재사용할 수는 없다.
2. **장부와 파일이 어긋났을 때 거부 메시지가 오해를 부를 수 있다.**
   - 2(e)에서 finalize나 recover 중 실패해 파일이 reserved로 남으면, `check_approval` 마지막 줄이 "다른 실행이 예약 중(실행 잠금을 쥐고 있음)"이라고 나온다. 실제로는 아무도 실행 잠금을 쥐고 있지 않다.
   - 장부 불일치 줄도 함께 나오지만, 사람이 원인을 볼 때 헷갈릴 수 있다.
   - 이 상태는 `resolve`로도 풀 수 없다(장부 검사에서 거부). 구현 보고서 17-2가 인정한 대로 사람이 새 추정·승인을 만들어야 한다.
3. **장부 읽기는 잠금 없이 한다.**
   - `verify_approval`과 `load`는 장부 잠금 없이 읽는다.
   - 2(b)에서 쓰기와 함께 읽기 4,448회를 돌렸다(2,106회 + 2,342회). 덜 쓰인 줄 때문에 실패한 경우는 0회였다. 실패 1회는 첫 쓰기 전 "해시 장부가 없음"이었다.
   - 덜 쓰인 줄을 읽더라도 결과는 거부(닫힌 쪽)다. 다만 finalize에서 일어나면 확실한 used·unused가 다음 검사에서 usage_check_required로 바뀔 수 있다.
4. **503 UNAVAILABLE도 "생성 안 함 확실"로 본다.** TRANSIENT_RATE가 `SURE_NO_GENERATION`에 들어 있다. 사용자가 정한 오류 분류표를 따른 것이다. 관찰로만 적는다.
5. **실행 잠금 없이 예약하는 호출자가 있으면 위험하다.**
   - `recover_if_abandoned`는 "실행 잠금을 쥔 프로세스가 없으면 죽은 것"으로 본다.
   - `run.main` 밖에서 `run_calls(on_first_call=reserve)`를 실행 잠금 없이 쓰는 호출자가 있다고 하자. 그 실행이 살아 있어도 다른 프로세스의 검사가 usage_check_required로 옮긴다. 결과는 닫힌 쪽이다.
   - 현재 그런 호출자는 테스트와 내 2(d) 스크립트뿐이다.
6. 앞 보완 확인의 관찰 3(`--model` 도움말)은 해소됐다. `run.py` 325행이 이제 "기본: 공급자 상수, Gemini는 사용자가 정한 gemini-3.8-flash. 자동 전환 없음"이다.


## 2026-10-14 latest C follow-up local verification (Codex)

PASS for the tested local scope. Direct execution: unittest discover -s tests, Ran 281 tests in 455.186s, OK. Raw unchanged: 1121 files PASS. Leakage scan: 62 files PASS. A+B SHACL: Conforms True. Code inspection confirms journal + memory conservative judgement, partial completed/pending lists, raw response saved before interpretation, and ledger mismatch messages. Previous PARTIAL findings remain in this report as history; latest fixes are present and the regression suite passes. Real API behavior is not yet included in this verdict.

User confirmed examples 2 and 3 explicitly. No commit or push authorized; the extraction ledger remains uncommitted by user choice.
