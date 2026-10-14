# ④ 추출 2단계 검증 보고서
- 판정: PASS (FAIL 항목 없음. 미확인 3건과 판정 외 관찰은 아래)
- 범위: src/imaks_kg/extract/ 2단계 파일 + 1단계 보강 + tests/test_extract_b_* . 구현 보고서는 근거로 쓰지 않음. 실제 API 호출 0회(mock 공급자만), 정답 파일 직접 열람 없음.
- 시험 환경: 가짜 Example과 임시 레지스트리·설정·로그·캐시는 scratchpad. 실제 `example_registry.json`은 시험 전후 동일(항목 0개). 시험용 `kg_build/extraction/mock-verify-e2e*`는 삭제함.

## 항목별 결과

| # | 항목 | 결과 | 근거 |
|---|---|---|---|
| 1a | `max_retries`=4, 총 5회, 대기 1·2·4·8초 | PASS | 주입 sleep 기록 `[1.0,2.0,4.0,8.0]`, 호출 5회(`retry.py`, rng=0). 지터 1.0 주입 시 `[1.25,2.5,5,10,20,40,60,60,60]`로 상한 60 적용 |
| 1b | `max_attempts` 거부 | PASS | `config.py:174` 한국어 안내와 함께 ConfigError (직접 실행 확인) |
| 1c | scoring 체인 정확히 1개 | PASS | 1+1개, 같은 공급자 2개, 0개 모두 ConfigError. 1개는 통과. production은 3개 체인 허용 |
| 1d | 호출 기록에 run_mode | PASS | mock 실행 호출 기록 6줄 모두 `"run_mode": "scoring"` (grep -c 6/6) |
| 1e | production fallback | PASS | production 2모델 체인에서 m1 400 -> m2 성공, 실제 모델 m2 기록 |
| 2a | 프롬프트가 설계서 §3 Task를 담음 | PASS | `role_task_v1.txt` 항목 1~13: 4분류 정의, 값·단위·비교기호 보존, 번역 금지, 빈 문자열/null, 인과 추정 금지, 개수 맞추지 않기, 독립 조건 분리·중복 금지, 타 문서 값 맞춤 금지, 허용 ID, 인용 글자 그대로, 표 1부터, JSON만 |
| 2b | 스키마가 §4와 일치, 올바른 JSON Schema | PASS | 필드·enum·null 허용 일치. jsonschema 패키지 없음 -> 구조 직접 점검과 내장 검사기 시험으로 대체. 단 `status`가 `coverage_status`로 바뀜(관찰 7) |
| 2c | 영어 작성, 금지 단어 없음 | PASS | 본문 영어(표지 `[행 N]`/`[열M]`만 한국어). `severity`·`ground_truth` grep 0건(`ruleSeverity` 제외) |
| 3a | Example 없음/미등록 -> 거부 | PASS | `build-requests`, `run` 모두 rc=2와 ExampleError (미등록 해시, 파일 없음 두 경우) |
| 3b | 정답 겹침 검사 경로 | PASS(코드 확인만) | `example_check.py:check_gt`가 `check_gt_overlap.py -n 5 --threshold 0.01`을 subprocess로 실행, 종료 코드 2는 실패 처리. 정답 위반 파일로 실제 탐지는 시험하지 않음(정답 열람 금지). 깨끗한 파일은 도구가 통과 판정 |
| 3c | 원문 5단어 복사 -> 실패 | PASS | 8개 조각 겹침, rc=1, 등록 안 됨 |
| 3d | 데이터셋 어휘 -> 실패 | PASS | `MAINT-99` 형식, `ST01_FILLING`/`ST01`, `SOP-001`/문서 ID, `175°C` 원문 수치+단위 모두 실패. 파일 없음 rc=2 |
| 3e | 깨끗한 파일 통과·등록 | PASS | 임시 레지스트리에만 SHA-256 등록. 실제 레지스트리 불변 |
| 4a | 문서 1개=요청 1개, 7문서 | PASS | 임시 레지스트리로 7개 요청 생성(문서당 1파일), 청크 29/14/4/9/3/8/4 |
| 4b | 제목 병합 | PASS | 30자 미만 한 줄 청크가 단독 전송 없이 다음 청크 `Section:`으로 붙음. SOP-001 청크 35 -> 전송 29, `merged_title_chunk_ids` 기록 |
| 4c | 표 `[행 N]`·`[열M]` 1부터, tables.jsonl 일치 | PASS | 24개 표 전부 행 수와 셀 문자열이 `rows_normalized`와 일치(셀 줄바꿈->공백만), 헤더=행 1 |
| 4d | 허용 ID | PASS | Station 9 + Sensor 22(`load_allowlist`, 요청 본문에 22개 센서) |
| 4e | 요청 메타 | PASS | `answer_key_supplied:false`, `seed_maintenance_text_supplied:false`, 프롬프트·스키마·Example·입력·문서 PDF 해시, 문서 ID, 요청 모델, run_mode |
| 4f | 길이 한도 분할 | PASS | 한도 3000/3300/3600으로 시험: 섹션 경계 분할, 청크 전체를 순서대로 덮음, 이어지는 표(SOP-002 p2:table1 <- p1:table5)는 같은 파트. 한도 1200~2500에서는 SplitError(`split_error.json` 기록 코드 확인) |
| 4g | 정답·seed 미열람, 샘플링 매개변수 없음 | PASS | `ground_truth`·`kg_seed` extract 코드 grep 0건(`ground_truth`는 테스트 클래스명 1건만). 요청 JSON에 temperature/top_p/top_k 없음 |
| 5a | 검증기 경우별 | PASS | 정상, `evidence_not_found`(없는 인용, 줄바꿈 포함 인용을 공백으로 바꾼 경우), `id_not_in_allowlist`, 표 행/열 99 -> `table_position_out_of_range`, 중복 identifier(실행 전체에서 양쪽에 플래그), coverage 누락 `coverage_gap`, 잘못된 JSON·잘림·필드 누락·enum 위반·추가 필드는 차단 오류(accepted=False), 빈 조건·조치 `empty_content` |
| 5b | 플래그 규칙 predictions 유지 | PASS | 규칙 4개(정상 1, 인용 없음, 목록 밖 ID, 빈 규칙): predictions 3, rules_valid 1, rules_all 4. 빈 규칙 예외는 `artifacts.py` 머리말과 구현 보고서 42~43줄에 명시 |
| 5c | 위치·해시 독립 재계산 | PASS(주의 있음) | 산문 인용 83개: 위치 확정 83, textSha256 83/83 일치. `page[charStart:charEnd]==인용`은 74/83. 나머지 9개는 청크 텍스트가 쪽의 줄바꿈을 공백으로 정규화한 곳이라 길이는 같고 공백 종류만 다름(관찰 1). 표 셀 30개: rowIndex·colIndex(1부터)·tableId·bbox가 `tables.jsonl` 셀(0부터 저장)과 일치, 해시 일치 |
| 5d | 추측 금지 | PASS | 같은 어구가 청크에 여러 번 -> `position_unresolved`, 표 좌표 없이 여러 곳/잘못된 셀 -> `position_unresolved` |
| 5e | mark_validated | PASS | 검증 통과 응답만 캐시 `.validated.json` 생성. 호출 실패(JSON 아님)는 0개. 같은 입력 재실행은 `cache_hit=True`, 공급자 호출 0회. 스키마 불량 후 재호출 성공도 확인 |
| 6a | predictions를 평가기 로더가 읽음 | PASS | `load_predictions`로 30건 오류 없이 로드, `model`·`identifier` 채워짐 |
| 6b | eval_meta 형식 | PASS | 프롬프트·Example·스키마 해시, `requested_models`, `actual_models`, `run_mode` 담긴 JSON(`--meta`는 임의 JSON을 lock에 넣음, `lock.py:40`) |
| 6c | validate | PASS | LLM 재호출 없이 저장된 응답만 재검증(응답 해시 대조), 같은 폴더에서 predictions 해시 동일, `--out-run-id` 새 폴더에서도 바이트 동일(`3d4117e2…`) |
| 6d | predictions에 run_id 없음 | PASS | 검색 결과 없음. `run_summary.json`에 run_id·generated_at·플래그·클래스·문서·모델 집계 |
| 7a | review_stage1/2.csv와 안내문 | PASS | 두 CSV 머리 줄과 CLI 출력에 "검토 기준은 SOP 원문뿐… 정답 파일과 비교해 고치지 마세요". 1단계 대상 = 제외 플래그 6개 규칙 전부 |
| 7b | 2단계 표본과 시드 | PASS | 풀 24개 중 5개(약 20%), 시드 7이 CSV 머리와 `review_stage2.meta.json`에 기록, 다른 실행 폴더에서 같은 시드로 동일 표본(diff 동일) |
| 7c | review-apply | PASS | `rules_final.jsonl`에 이전·이후, 이유, 검토자, 시각, `human_reviewed`. 실행 전후 predictions 해시 불변, 1단계 미결정은 최종에서 제외 기록 |
| 8a | TTL 속성·Provenance | PASS | 규칙에 4분류 타입, identifier, conditionText, responseText, ruleSeverity, extractionMethod="LLM", sourceDocument, hasProvenance, appliesToSensor·actionTarget(링크 시험 확인). Provenance 24개 전부 sourceKind=document, page, 위치(charStart/End 또는 tableId·rowIndex·colIndex·bbox), sourceQuote, textSha256 재계산 일치 |
| 8b | SHACL 직접 실행 | PASS | `run_shacl.py --ont ontology_v1/ontology.ttl --shapes ontology_v1/shapes.ttl` 대상 kg_with_rules.ttl: Conforms True. 출처 필드(page/textSha256/sourceDocument/hasProvenance/identifier)를 뺀 가짜 입력은 S7·S8 위반으로 부적합 |
| 8c | 출처 장부 | PASS | 규칙 전용 TTL 333 트리플이 장부 333건과 정확히 일치(차집합 0), 모든 항목에 sources |
| 8d | ⑦ 이후 타입 부재 | PASS | AnomalyEvent 5유형, Person, CausalLink, causallyAffects, triggers, correlatesWith, Task 모두 0건 |
| 8e | MAINT ID 충돌 중단 | PASS | LLM 규칙 identifier=MAINT-03 -> IdCollisionError, `id_collisions.json` 기록, TTL 미생성. 병합하지 않음 |
| 9 | CLI 종단 | PASS | `run`(임시 설정) -> `validate` -> `review-init 1·2` -> `review-apply` -> `to-rdf` 연결 동작(적합). 기존 `mock-e2e-20261014`: rules_all 6 = summary 6, predictions 6, rules_valid 3, 플래그 3종 각 1(summary = flags.csv = rules_all 집계), review_stage1 3행, SHACL 적합 |
| 10a | check_leakage 기본 폴더 | PASS | 검사 92개, PASS, 경고 0건(시험 산출물 삭제 후) |
| 10b | check_secrets 기본/`src tests config` | PASS | 147개 발견 0 / 69개 발견 0 |
| 10c | check_raw_unchanged | PASS | 1121개 파일 불변 |
| 10d | 절대 경로, 금지 단어 | PASS | src·tests·config에 `C:\`, `/Users/`, `/home/` 0건. `severity`는 `ruleSeverity` 외 0건 |
| 10e | requirements.txt | PASS | 수정 시각 16:46로 2단계 파일(17:03 이후)보다 앞. 추가 패키지 import 없음 |
| 10f | 실제 호출 경로 | PASS | `urlopen`은 `connectivity.py`·`providers/base.py`에만 있고 extract_b 테스트는 `build_providers`·환경변수 미사용. 시험 전부 mock |
| 10g | 전체 단위 테스트 | PASS | `Ran 256 tests in 151.446s` OK |
| 11 | 금지 경로 미수정 | PASS | ontology_v1/(14:45), .claude/(13:57), harness/(15:01) 수정 시각이 모두 2단계 시작(17:03)보다 앞. 이번 작업 중 변경 없음 |
| 12 | 판정 외 관찰 정리 | PASS | 아래 참조 |
| 공통 | 큰 산출물 git 미추적 | PASS | `kg_build/`, `llm_logs/`, `llm_cache/`가 .gitignore 대상(`git check-ignore`) |
| ④ | Role/Task/Example 3단 | PASS | system=Role+Task(`role_task_v1.txt`), 요청 본문 `# EXAMPLE` 절 |
| ④ | 정답이 입력에 쓰이지 않음 | PASS | extract 코드에 정답 파일명 없음, `check_gt_overlap.py src/imaks_kg/extract/prompts` 검사 3개 기준 초과 0건 |
| ④ | 4분류·Task 없음 | PASS | 스키마 enum 4개, TTL에 Task 타입 0 |
| ④ | 모델별 구분 | PASS | predictions `model`/`provider`, summary `by_model`, `eval_meta.actual_models`, 호출 기록 요청/실제 모델 |
| ④ | 스모크 지원 | PASS | `--smoke`가 가장 작은 문서(DS-ELEC-3300, 청크 3개)만 요청 생성 |

## 불합격 사유
없음.

## 미확인
1. 구조화 출력(responseJsonSchema, json_schema) 스키마를 실제 공급자가 받는지: 실제 API 호출 금지라 확인 못함(설계서 §12 열린 항목).
2. 스모크 테스트 실행 기록(체크리스트 ④): 모델 id·키·예산이 정해지기 전이라 기록 없음. 지원 기능만 확인.
3. `check_gt_overlap`이 정답 문구를 실제 베낀 Example을 잡는지: 정답 열람 금지로 시험하지 않음(깨끗한 파일 통과와 호출 코드만 확인). jsonschema 패키지가 없어 스키마는 내장 검사기와 직접 읽기로 점검.

## 판정 외 관찰
1. **인용 위치의 공백 차이:** 청크 텍스트는 쪽 텍스트의 줄바꿈을 공백으로 바꾼 것이라(② 전처리 규약), 산문 인용 83개 중 9개(11%)는 `page[charStart:charEnd]`가 인용과 공백 종류만 다름(`pageSliceExact=false`, `rules_all.jsonl`에만 기록, TTL에는 안 올라감). `textSha256`은 공백으로 바뀐 인용의 해시라 쪽 원문 구간을 직접 해시하면 다름. 설계 §5.5의 "원문 해시"를 쪽 원문 기준으로 해석하면 보완 필요.
2. **해시 방식 불일치:** `schema_sha256`은 JSON을 정렬해 다시 직렬화한 해시라 파일 SHA-256과 다르다(프롬프트·Example은 파일 해시와 같음). 평가 lock에 쓰이므로 설계서에 정의를 적을 것.
3. **표 행 0 같은 값은 응답 전체를 차단:** 스키마 `minimum: 1` 때문에 LLM이 0부터 센 행 하나로 문서 응답 전체가 `schema_error`가 됨(`table_position_out_of_range` 플래그로 가지 않음, 범위 초과 99는 플래그).
4. **JSON 아님/잘림은 검증 재시도 없이 `call_failed`:** 설계 §5.1("실패하면 재시도")과 §6("같은 모델 재시도 없음, 다음 모델")이 어긋나며 코드는 §6을 따름. 스키마 위반만 `--validation-retries`로 재호출. 설계서 정리 필요.
5. **사람이 accept한 `evidence_not_found` 규칙은 TTL에서 빠짐:** 확정 위치가 없어 S8을 만족할 수 없기 때문(`to_rdf_report.json` excluded에 기록). 사람이 고친 `id_not_in_allowlist` 규칙은 목록 밖 ID를 연결하지 않고 `ids_not_linked`에 기록(편집 가능 열이 condition/action/identifier뿐이라 sensors는 수정 불가).
6. **실제 SOP-003 추출 시 MAINT-01~08 충돌로 to-rdf 중단:** 충돌 시 중단·기록 동작은 직접 확인. 실제 SOP-003의 인쇄 ID가 MAINT-xx면 중단될 것이므로 병합/접두 정책을 ⑤ 전에 정해야 함.
7. **`Severity` 문구가 산출물에 들어가면 check_leakage FAIL:** 직접 재현. SOP-004 본문을 인용한 mock 산출물(`predictions.jsonl`, `rules_all.jsonl`, `rules_valid.jsonl`, `triple_sources.jsonl`)이 kg_build/extraction에 있자 기본 폴더 검사가 13건 FAIL. 임시 폴더에서도 `Severity` 문자열이 든 jsonl이면 FAIL, csv의 값은 통과(컬럼 전용). 시험 산출물 삭제 후 PASS 복귀. 실제 SOP-004 추출 후 점검이 FAIL하므로 `forbidden_columns.txt`의 `severity`를 컬럼 전용으로 옮기거나 `kg_build/extraction`을 텍스트 예외로 두는 결정이 필요(사용자 승인 사항).
8. **설계서 §4 수정 필요:** coverage 키가 `status`가 아니라 `coverage_status`(금지 컬럼 목록에 `status`가 있음)이고 `reason`·`rules`가 필수임. 설계서 §4 예시는 아직 `status`.
9. **체크리스트 ④ 문구:** "Rule 클래스가 OperationalRule, ThresholdRule, AccessRule 중 하나"는 4분류(MaintenanceRule 포함)로 고쳐야 함. 스모크 기록 항목은 모델 확정 전에는 미충족으로 남음.
10. **전처리 section 오염(이 단계 범위 밖):** DS-ELEC-3300 청크의 `section` 필드가 문장 조각(`14 A and 20 A is permissible…`)으로 들어가 요청의 `Section:` 줄에 그대로 노출됨. 청크 파일 자체의 문제.
11. **전체 시험 시간:** 256개 테스트 151초(예상 약 215초보다 빠름). 기본 `python`(msys)에는 rdflib가 없어 SHACL·to-rdf는 `.venv\Scripts\python.exe`로만 동작.
