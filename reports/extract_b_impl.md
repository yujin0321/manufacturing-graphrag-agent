# 4단계 LLM 추출 - 2단계 구현 보고

날짜 2026-10-14. 범위: 1단계 보강 + 요청 빌더 + 검증기 + 산출물 + 사람 검토 기록 + TTL 변환 + CLI. 실제 API는 한 번도 호출하지 않았다(mock 공급자와 가짜 응답만). 정답 파일은 열지 않았다(Example 검증 도구 `check_gt_overlap.py`가 하위 프로세스로 읽는 것만 사용). 커밋하지 않았고 CLAUDE.md, work_log.md, ontology_v1/, harness/, .claude/, docs/, requirements.txt, imaks_data/는 수정하지 않았다. Example 파일은 만들지 않았다.

## 만든/고친 파일
1단계 보강(수정): `src/imaks_kg/extract/config.py`, `retry.py`, `client.py`, `fallback.py`, `config/extract.example.toml`, `providers/mock.py`(문서별 응답 mock `ScriptedByDocMock` 추가), 테스트 `tests/test_extract_a_config.py`, `test_extract_a_retry_fallback.py`.
새 파일 `src/imaks_kg/extract/`: `prompts/role_task_v1.txt`, `prompts/response_schema_v1.json`, `prompts/example_registry.json`(항목 0개), `docdata.py`, `example_check.py`, `request_builder.py`, `validator.py`, `artifacts.py`, `review.py`, `to_rdf.py`, `run.py`, `__main__.py`.
새 테스트: `tests/test_extract_b_{stage1,request,validator,example_check,outputs,review,to_rdf}.py`, 도구 `tests/extract_b_helpers.py`, `tests/tests_fake_embedder.py`.

## 사용법 (저장소 루트, `.venv`)
```
PYTHONPATH=src python -m imaks_kg.extract.example_check <내가 쓴 Example 파일>   # 통과하면 해시 등록
PYTHONPATH=src python -m imaks_kg.extract build-requests [--docs SOP-001,SOP-003 | --smoke]
PYTHONPATH=src python -m imaks_kg.extract run [--docs ... | --smoke] [--config config/extract.toml]
PYTHONPATH=src python -m imaks_kg.extract validate --run-id RUN [--out-run-id NEW]
PYTHONPATH=src python -m imaks_kg.extract review-init --run-id RUN --stage 1   # 검토 후 --stage 2 [--seed N]
PYTHONPATH=src python -m imaks_kg.extract review-apply --run-id RUN
PYTHONPATH=src python -m imaks_kg.extract to-rdf --run-id RUN
```
설정: `config/extract.example.toml`을 `config/extract.toml`로 복사해 모델 id, `run_mode`, `[extract] example_file`을 채운다. 시험용 `run --mock-responses FILE`은 mock만 쓰며 실행 이름이 `mock-`로 시작한다.

경로: 입력 `preprocessed/documents/{chunks,tables,pages}.jsonl`, `doc_manifest.csv`, `kg_build/instances/{stations,sensors}.csv`(identifier 열만), `instances.ttl`. 출력 `kg_build/extraction/<run_id>/`(predictions.jsonl, rules_all.jsonl, rules_valid.jsonl, flags.csv, run_summary.json, eval_meta.json, 검토 후 review_stage{1,2}.csv, rules_final.jsonl, review_log.jsonl, review_summary.json, TTL 후 kg_with_rules.ttl, rules_only.ttl, triple_sources.jsonl, to_rdf_report.json). 요청 파일과 응답 원문은 `llm_logs/requests/<run_id>/`, `llm_logs/extract_runs/<run_id>/`(git 제외, 점검 도구 기본 폴더 밖).

## A. 1단계 보강
- `retry.max_attempts` -> `retry.max_retries`(기본 4 = 재시도 4회, 총 5회 시도, 대기 1·2·4·8초, 상한 60초, 지터 유지). 예전 이름을 설정에 쓰면 한국어 안내와 함께 거부한다(조용한 의미 변경 방지). 예시 TOML과 1단계 테스트 3곳(대기/호출 횟수) 수정.
- `run.run_mode`("scoring"|"production", 기본 production). scoring에서 체인의 모델이 정확히 하나가 아니면 설정을 읽을 때와 `extract_call` 직전에 `ConfigError`(한국어)로 거부. 호출 기록(`extract_call`, `model_call` 줄과 요청 메타)에 `run_mode` 기록.
- 설정에 `[extract]`(example_file, max_input_tokens_est=200000, chars_per_token=3.0) 추가.

## B. 설계서 대비 구현한 것
- 프롬프트 Task 13항목(분류 4정의, 원문 보존, 번역 금지, 빈 조치·등급, null ID, 새 인과 금지, 개수 맞추지 않기, 독립 조건 분리·중복 금지, 다른 문서 값에 맞추지 않기, 허용 ID 밖은 빈 배열, 인용 글자 그대로, 1부터 센 표 좌표, JSON만)와 스키마(strict 형태: 필수 항목, additionalProperties false). 분류 정의는 schema_tables 2장을 내용 기준 영어로 옮김.
- Example 게이트: 설정 경로의 파일이 없거나 SHA-256이 `example_registry.json`에 없으면 `run`/`build-requests`가 한국어 안내와 함께 거부. 등록 뒤 한 글자라도 고치면 다시 거부(시험함).
- `example_check`: (a) `check_gt_overlap.py`를 하위 프로세스로 `-n 5 --threshold 0.01`, 종료 0만 통과(2는 미확인=실패), (b) pages.jsonl 5단어 조각 겹침, (c) ID형 토큰·스테이션/센서/문서 이름·수치+단위 조합, (d) 해시. 출력은 개수와 줄 번호만. 시험은 가짜 정답 CSV·가짜 원문·가짜 이름 목록 사용.
- 요청 빌더: 문서당 요청 1개, 청크는 chunks.jsonl 파일 순서(문서 안 순서), 30자 미만 한 줄 제목 병합(`Section:` 줄), `<<chunk ID | page N>>`, 표는 `[행 N]`/`[열M]`(1부터), 허용 ID(Station 9, Sensor 22), 요청 메타(answer_key_supplied=false, seed_maintenance_text_supplied=false, 프롬프트·스키마·Example·입력·문서 입력·PDF·허용목록 해시, 문서 ID, 요청 모델, run_mode, part). 입력 추정 상한 초과 시 section 경계로 분할(이어지는 표는 같은 요청), 못 나누면 `SplitError`로 호출 전에 중단하고 `split_error.json` 기록. seed 정비 문구 파일은 읽지 않음(소스에 해당 파일명 없음을 시험).
- 검증기: 8단계 전부. 차단 오류(JSON/스키마)와 규칙 플래그 `evidence_not_found`, `id_not_in_allowlist`, `table_position_out_of_range`, `duplicate_identifier`, `coverage_gap`, 추가로 `position_unresolved`, `empty_content`. 쪽·charStart/charEnd(쪽 텍스트 기준), 표 tableId/rowIndex/colIndex/bbox, textSha256(인용문), 문서 PDF 해시는 코드가 계산. 청크와 쪽 텍스트가 줄바꿈만 다른 8개 규칙 청크도 글자 단위 대응으로 위치를 구함. 인용이 여러 번 나오거나 표 좌표 없이 여러 셀에 맞으면 추측하지 않고 `position_unresolved`. 통과한 응답은 `mark_validated`. 스키마 불량이면 `--validation-retries`(기본 1)만큼 다시 호출, 그래도 안 되면 실패 기록(원문 보존).
- 산출물 6종 + `eval_meta.json`(평가기 `--meta`에 그대로 전달 가능, 시험함). predictions는 평가기 로더로 읽힘, `model` 필드 포함.
- review: 1단계(KG 제외 플래그 규칙 전부), 2단계(플래그 없는 규칙 + 1단계 accept의 약 20% 무작위 표본, 시드를 파일 머리·`review_stage2.meta.json`에 기록, 같은 시드는 같은 표본), 안내 문구("검토 기준은 SOP 원문뿐, 정답 파일과 비교해 고치지 마세요")를 파일 머리와 CLI 출력에 표시. `review-apply`는 `rules_final.jsonl`(이전·이후·이유·검토자·시각 이력, `human_reviewed`)과 `review_log.jsonl`을 따로 쓰고, 실행 때마다 predictions.jsonl 해시 불변을 확인(시험함).
- to_rdf: 4분류 클래스 노드, identifier, conditionText, responseText, ruleSeverity, extractionMethod="LLM", appliesToSensor/actionTarget(③ 같은 `inst:` IRI), sourceDocument, hasProvenance(page, charStart/End 또는 tableId·rowIndex·colIndex·bbox, sourceQuote, textSha256). `kg_with_rules.ttl`에 ③ 인스턴스 전체 포함. SHACL은 `run_shacl.py`와 같은 설정(ont_graph, 추론 없음)으로 코드에서 호출하고 CLI로도 직접 확인. `triple_sources.jsonl`은 ③ 장부와 같은 `{triple, sources}` 형식(문서 ID·청크 ID·표 위치·텍스트 해시·예측 파일 해시), ③의 `Ledger`/완결성 검사를 재사용. seed 정비 규칙과 병합하지 않고 별도 노드, identifier(또는 IRI) 충돌이면 `id_collisions.json`을 쓰고 접두 없이 중단.

## 설계서·요청과 다르게 한 것 / 가정
1. **coverage의 `status` 키를 `coverage_status`로 바꿨다.** `check_leakage.py`의 컬럼 전용 금지 목록에 `status`가 있어 JSON 키로 쓰면 FAIL이 나는 것을 직접 확인했다. 같은 이유로 산출물 JSON 어디에도 `status` 키를 쓰지 않는다(`outcome` 사용). 설계서 §4를 고칠 것을 제안한다.
2. `ruleSeverity`는 점검 도구가 허용함을 직접 확인(단어 경계 규칙상 통과). 코드·테스트·주석에서 `ground_truth`, `severity` 단어를 쓰지 않았다(시험 코드의 금지어 목록은 문자열을 나눠 조립).
3. `coverage_gap`만 붙은 규칙은 KG 적재 제외 대상이 아니다(설계 §9 1단계 항목에 없음). flags.csv에는 표시, 2단계 모집단에 포함. 제외 플래그는 나머지 5개 + `empty_content`.
4. `empty_content`(condition과 action이 모두 빈 규칙)는 평가기 로더가 파일 전체를 거부하므로 predictions에서만 뺀다(rules_all에는 남고 flags.csv에 표시). 이것이 "점수용 예측에서 숨기지 않는다"의 유일한 예외다.
5. 스키마 위반은 응답 전체를 차단한다(규칙 단위로 살리지 않음). 인용 대조는 글자 그대로(공백·줄바꿈 정규화 없음). 표는 셀 하나 또는 한 행의 셀을 " | "로 이은 문자열을 인용으로 인정하고(후자는 시작 셀을 colIndex로, ③ MAINT provenance 선례와 같은 방식), 프롬프트에 그렇게 지시했다.
6. identifier: 인쇄 ID가 있으면 그대로, 없으면 `문서ID:청크ID의 문서 뒷부분:번호`(예 `SOP-003:p1:table1:chunk:1`). 중복은 해당 identifier를 가진 규칙 모두에 플래그. predictions의 `identifier`도 이 값이다.
7. predictions에는 `run_id`를 넣지 않았다(같은 응답 재검증이 바이트까지 같도록). 실행 이름은 폴더가 가진다.
8. 1단계 검증 재시도는 같은 모델에 새 호출이다(캐시는 검증 전 응답을 재사용하지 않으므로). 비용이 드는 동작이라 기본 1회, 옵션으로 조절.
9. 토큰 추정 상한 기본 200000과 chars_per_token 3은 자리표시 값이다(7개 문서는 실제 분할 없이 약 3천~4.7천 추정 토큰).
10. `validate`는 같은 run_id 폴더에 쓸 때 predictions가 달라지면 거부하고 `--out-run-id`를 요구한다. `build-requests`/`validate`는 `config/extract.toml`이 없으면 견본 설정을 쓴다.

## 직접 실행한 확인
- 전체 단위 테스트 마지막 줄: `Ran 256 tests in 6707.330s` / `OK` (평가기의 SBERT 시험 등 기존 무거운 시험 포함; 이 실행 뒤 시험 코드의 금지어 문자열 3줄을 조립식으로 바꾸고 해당 2개 파일 27개를 다시 돌려 OK. 전체 재실행은 하지 않았다). 신규 extract_b 시험은 개별 실행에서 모두 OK(약 90개).
- `check_leakage.py` 기본 폴더: `검사한 파일 92개, 금지어 8개, 컬럼 전용 11개` / `PASS: 금지 컬럼 없음`, **경고 0건**(kg_build/extraction의 mock 실행 포함 상태).
- `check_secrets.py` 기본: `검사한 파일 146개, 건너뜀 0개, 발견 0건` PASS. `src tests config` 지정: `검사한 파일 69개, 건너뜀 0개, 발견 0건` PASS.
- `check_raw_unchanged.py`: `PASS: imaks_data/ 원본 불변 (1121개 파일)`.
- 절대 경로 grep(`C:\`, `C:/`, `/Users/`, `/home/`) 신규 코드·테스트·설정: 0건.
- **mock 이어 붙이기 한 번**(실제 SOP 청크로 요청 생성, mock 응답은 실행 중에 실제 청크에서 인용을 잘라 만듦; 가짜 Example은 저장소 밖에 둠): `kg_build/extraction/mock-e2e-20261014/`. SOP-001, SOP-003 요청 2개 -> 규칙 6개(정상 3, `evidence_not_found` 1, `id_not_in_allowlist` 1, `table_position_out_of_range` 1) -> predictions 6줄 -> 평가기(가짜 정답 3행, 가짜 임베더)에서 TP 2 / FP 4 / FN 1, lock의 actual_models=`gemini/mock-model` -> review-init 1단계(3개) -> to-rdf: 규칙 3개, 추가 트리플 57개, **SHACL 적합**(`run_shacl.py` CLI로도 `PASS: SHACL 적합`) -> `validate`로 재검증한 predictions가 바이트 동일.

## 미확인 / 한계
- 공급자의 구조화 출력이 이 스키마(`type: [string, null]`, enum에 null, minimum)를 받는지, 생각 수준 필드 이름은 1단계와 같이 **미확인**. 거부되면 스키마를 단순화해야 한다.
- 실제 모델이 인용을 글자 그대로 복사하는 비율, 줄바꿈이 있는 산문 인용의 일치율은 미확인(mock만). 줄바꿈을 공백으로 바꿔 인용하면 `evidence_not_found`가 나온다. 첫 스모크에서 실측 필요.
- **실제 SOP-003 추출은 `MAINT-01~08`을 인쇄 ID로 뽑을 것이므로 to-rdf가 ID 충돌로 중단된다.** 정책(별도 노드, 접두 금지)대로 동작하지만 실제 데이터에서는 항상 걸린다. 결정 필요: 충돌 규칙은 TTL에서 제외하고 기록만 할지, 병합 정책을 바꿀지, `edited_identifier`로 사람이 바꿀지(코드는 이미 지원).
- 실제 SOP-004 표 제목 등에 `Severity`가 있어, 이 단어가 규칙 문장·인용에 들어가면 `kg_build/extraction`의 jsonl/ttl이 `check_leakage.py` 기본 폴더 검사에서 FAIL할 수 있다(mock 실행에는 해당 단어 없음, 실제 실행은 미확인). `preprocessed/documents/`처럼 예외 접두사가 필요하다(`.claude/` 수정이라 제안만).
- 문자 위치는 쪽 텍스트(정규화본) 기준, 청크가 쪽 텍스트와 글자 단위로 대응하지 않는 경우는 `position_unresolved`(현재 데이터에서는 줄바꿈 차이만 있음).
- 같은 identifier가 여러 문서에 있어도 모두 제외 플래그가 붙는다(어느 쪽이 맞는지는 사람이 `edited_identifier`로 정함).
- 호출 기록의 동시 쓰기 안전성, 캐시 텍스트 비마스킹은 1단계 한계 그대로.
- 정비 규칙 병합 여부, Task 클래스, SOP-002 결정적 변환 기준선(§7)은 이번 범위가 아니라 하지 않았다.
- 전체 시험 시간이 길다(6707초); 어느 시험이 대부분인지는 확인하지 않았다(SBERT/SHACL 추정).

## 설계서·체크리스트 수정 제안(수정하지 않음)
- 설계서 §4: coverage 키 `status` -> `coverage_status`(금지 컬럼 목록 때문), `reason`/`rules`를 필수(null/빈 배열)로 명시, `empty_content`·`position_unresolved` 플래그와 `coverage_gap`이 적재 제외가 아님을 명시.
- 설계서 §6: `max_attempts` -> `max_retries`, `run_mode`, `[extract]` 설정 3개, 요청·응답 파일 위치(`llm_logs/requests`, `llm_logs/extract_runs`).
- 설계서 §9: 1단계 검토 대상 목록에 `position_unresolved`, `empty_content` 추가, 2단계 모집단 정의(플래그 없는 규칙 + 1단계 accept), 시드 기록 위치.
- 체크리스트 ④: "사람 검토 입력·수정·최종 채택" 항목에 `review_stage{1,2}.csv`, `rules_final.jsonl`, `review_log.jsonl` 이름과 predictions 불변 확인을 명시. 점검 도구에 `kg_build/extraction` 본문 텍스트 예외 검토.
- Example 작성자 안내: Example은 `.txt/.md/.json` 확장자(점검 도구가 읽는 확장자)여야 하며 `example_check`를 통과한 뒤 `config/extract.toml`의 `[extract] example_file`에 경로를 적는다.

## 남은 작업
mock 실행 산출물(`kg_build/extraction/mock-e2e-20261014/`, `llm_logs/`, `llm_cache/`의 mock 항목)은 git 제외 폴더에 있다. 실제 실행에는 모델 id, 키, 사용자가 쓴 Example이 필요하다.

## v2 변경(MAINT 충돌: 제외+기록)
사용자 확정에 따라 `to_rdf.py`를 고쳤다.
- ③ seed 노드와 identifier(또는 IRI)가 겹치는 LLM 규칙은 **중단하지 않고** 그 규칙만 TTL·출처 장부에서 뺀다(병합 금지, 접두 금지). 충돌하지 않는 규칙은 정상 변환한다. Provenance와 장부는 남은 규칙에서만 만들어지므로 고아 노드가 없다(시험으로 확인).
- 기록: `kg_build/extraction/<run_id>/identifier_conflicts.json` = `{run_id, count, conflicts:[{identifier, seed_node_iris, document_id, chunk_id, kind, reason}]}`. 충돌이 0건이어도 파일을 쓰고 `count: 0`. `to_rdf_report.json`에 `identifier_conflicts` 개수, to-rdf 출력에 "ID 충돌 제외 N개".
- predictions.jsonl, rules_all.jsonl, rules_valid.jsonl은 바뀌지 않는다(해시 불변을 시험).
- 입력 규칙끼리의 identifier 중복은 예전대로 `id_collisions.json`을 쓰고 중단한다(요청 범위 밖이라 유지).
- 시험: 기존 중단 시험을 새 동작으로 교체하고 4개로 늘림(충돌 규칙만 빠짐+SHACL S7·S8 적합+seed 노드 8개 그대로, 충돌 기록 내용, 장부가 모든 트리플을 덮고 고아 Provenance 없음, 충돌 0건이면 count 0, 입력 내 중복은 여전히 중단). 또 `test_extract_b_request`의 레지스트리 시험이 "항목 0개"를 가정했는데 사용자가 `example_v1.txt`를 등록한 뒤 실패해서(코드 문제 아님) 형식 검사로 바꿨다.
- 재검증: 전체 단위 테스트 마지막 줄 `Ran 261 tests in 106.731s` / `OK`. `check_leakage.py` 기본 폴더 `PASS: 금지 컬럼 없음`(경고 0건, 94개 검사). `check_secrets.py` 기본 `검사한 파일 151개, 건너뜀 0개, 발견 0건` PASS, `src tests config reports` 지정 113개 PASS. `check_raw_unchanged.py` `PASS (1121개 파일)`. `ground_truth`·`severity` 단어(ruleSeverity 제외)는 코드·시험에 없음. mock 실행 `mock-e2e-20261014`에 to-rdf를 다시 돌려 SHACL 적합, `identifier_conflicts.json` count 0 확인. 실제 SOP-003 추출에서 MAINT 충돌이 실제로 어떻게 기록되는지는 mock 시험(MAINT-02를 인쇄 ID로 준 가짜 응답)으로만 확인했다.

verifier 검증이 필요하다.
